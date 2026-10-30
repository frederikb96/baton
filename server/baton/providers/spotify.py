"""Spotify Web API provider."""

from __future__ import annotations

import asyncio
import logging
import math
import re
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import httpx

from baton import errors
from baton.budget import CallBudget
from baton.providers.base import (
    Device,
    Playback,
    Playlist,
    Provider,
    RecentContext,
    RelayResponse,
    Track,
)
from baton.providers.spotify_accounts import SpotifyAccounts

PAGE_SIZE = 50
# Tracks started directly when Spotify refuses the Liked Songs context.
LIKED_FALLBACK_TRACKS = 50
MAX_PAGES = 40
# Spotify caps a playlist at 10000 items; the membership scan must be able to read all of them.
MEMBER_MAX_PAGES = 220
MAX_RETRY_AFTER_SECONDS = 86400
# Pause after a 429 that names none, the longer one when Spotify calls it the used-up quota.
DEFAULT_PAUSE_SECONDS = 60
QUOTA_PAUSE_SECONDS = 900
QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
# A pause up to this long is waited out, so that a press succeeds late instead of failing.
HOLD_SECONDS = 15.0
CALL_REPORT_SECONDS = 3600.0
DEFAULT_MARKET = "from_token"
PLAYER_PATH = "/me/player"
# A playlist context URI; Spotify appends a query (``?sessionId=…&mode=enhanced``) to the
# ones that were played with smart shuffle, and older clients wrote ``spotify:user:<id>:playlist:``.
PLAYLIST_CONTEXT = re.compile(r"^spotify:(?:user:[^:]+:)?playlist:([A-Za-z0-9]+)(?:\?.*)?$")
log = logging.getLogger(__name__)


def _first_artist(item: dict[str, Any]) -> str | None:
    artists = item.get("artists") or []
    names = [a["name"] for a in artists if a and a.get("name")]
    if names:
        return ", ".join(names)
    show = item.get("show") or {}
    return show.get("name") or item.get("publisher")


def _epoch(stamp: object) -> float:
    """Seconds since the epoch of an ISO 8601 timestamp, 0 when it is missing or unreadable."""
    try:
        return datetime.fromisoformat(str(stamp)).timestamp()
    except ValueError:
        return 0.0


def _device(raw: dict[str, Any]) -> Device:
    return Device(
        id=raw.get("id") or "",
        name=raw.get("name") or "",
        type=raw.get("type") or "",
        is_active=bool(raw.get("is_active")),
        is_restricted=bool(raw.get("is_restricted")),
    )


class SpotifyProvider(Provider):
    """Controls whatever device plays through Spotify Connect."""

    def __init__(
        self,
        api_url: str,
        accounts: SpotifyAccounts,
        client: httpx.AsyncClient,
        market: Callable[[], str | None],
        now: Callable[[], float],
        budget: CallBudget,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._api = api_url.rstrip("/")
        self._accounts = accounts
        self._client = client
        self._market = market
        self._now = now
        self._budget = budget
        self._sleep = sleep
        self._reported_at = now()
        self._rate_limited_until = 0.0
        self._playlist_cache: dict[str, tuple[str, set[str]]] = {}
        self._user_id: str | None = None

    # transport

    async def _send(
        self,
        method: str,
        path: str,
        *,
        params: Any = None,
        json: Any = None,
    ) -> httpx.Response:
        """One call, after a short pause is waited out; a short 429 is retried once."""
        wait = self._rate_limited_until - self._now()
        if wait > HOLD_SECONDS:
            raise self._rate_limited(wait)
        if wait > 0:
            await self._sleep(wait)
        resp = await self._authorized(method, path, params, json)
        if resp.status_code == 429:
            self._note_rate_limit(resp, path)
            wait = self._rate_limited_until - self._now()
            if 0 < wait <= HOLD_SECONDS:
                await self._sleep(wait)
                resp = await self._authorized(method, path, params, json)
                if resp.status_code == 429:
                    self._note_rate_limit(resp, path)
        return resp

    async def _authorized(self, method: str, path: str, params: Any, json: Any) -> httpx.Response:
        """One call with the stored login, retried once with a fresh token after a 401."""
        resp: httpx.Response | None = None
        for attempt in range(2):
            token = await self._accounts.access_token(force=attempt == 1)
            self._count_call()
            try:
                resp = await self._client.request(
                    method,
                    f"{self._api}{path}",
                    params=params,
                    json=json,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=15,
                )
            except httpx.HTTPError:
                raise errors.ProviderError(
                    errors.SPOTIFY_ERROR, "Spotify is unreachable."
                ) from None
            if resp.status_code != 401:
                break
        assert resp is not None
        return resp

    def _count_call(self) -> None:
        self._budget.record()
        if self._now() - self._reported_at >= CALL_REPORT_SECONDS:
            self._reported_at = self._now()
            log.info("Spotify calls in the last hour: %d", self._budget.counts()[1])

    def reads_open(self) -> bool:
        """Whether a state read may go out now."""
        return self._now() >= self._rate_limited_until and not self._budget.spent()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        ok: tuple[int, ...] = (200, 201, 202, 204),
    ) -> httpx.Response:
        resp = await self._send(method, path, params=params, json=json)
        if resp.status_code in ok:
            return resp
        raise self._error(resp, path)

    async def relay(
        self, method: str, path: str, params: list[tuple[str, str]], body: Any
    ) -> RelayResponse:
        """Forward a call to the Web API; Spotify's answer is returned whatever its status."""
        resp = await self._send(method, path, params=params or None, json=body)
        if resp.status_code == 401:
            raise self._error(resp, path)
        return RelayResponse(
            resp.status_code,
            resp.content,
            resp.headers.get("content-type"),
            resp.headers.get("retry-after"),
        )

    def _note_rate_limit(self, resp: httpx.Response, path: str) -> None:
        """Stop calling Spotify for the pause it asked for, or a default one if it named none."""
        reason, _ = self._error_fields(resp)
        header = resp.headers.get("Retry-After")
        try:
            seconds = float(header or "")
        except ValueError:
            seconds = QUOTA_PAUSE_SECONDS if reason == QUOTA_EXCEEDED else DEFAULT_PAUSE_SECONDS
        self._rate_limited_until = self._now() + min(max(seconds, 0.0), MAX_RETRY_AFTER_SECONDS)
        short, long = self._budget.counts()
        log.warning(
            "Spotify answered 429 on %s: reason=%s retry_after=%s calls_30s=%d calls_hour=%d",
            path,
            reason or None,
            header,
            short,
            long,
        )

    @staticmethod
    def _rate_limited(wait: float) -> errors.ProviderError:
        return errors.ProviderError(
            errors.SPOTIFY_RATE_LIMITED,
            f"Spotify rate limit reached. Retry in {math.ceil(wait)} s.",
            retry_after=math.ceil(wait),
        )

    @staticmethod
    def _error_fields(resp: httpx.Response) -> tuple[str, str]:
        """The ``reason`` and ``message`` of an error body, empty when it has none."""
        try:
            body = resp.json().get("error", {})
        except (ValueError, AttributeError):
            return "", ""
        if not isinstance(body, dict):
            return "", ""
        return str(body.get("reason") or ""), str(body.get("message") or "")

    @classmethod
    def _error(cls, resp: httpx.Response, path: str) -> errors.ProviderError:
        reason, message = cls._error_fields(resp)
        status = resp.status_code
        if status == 401:
            return errors.ProviderError(
                errors.SPOTIFY_AUTH, "Spotify rejected the login. Log in again on the web page."
            )
        if status == 429:
            wait = resp.headers.get("Retry-After")
            suffix = f" Retry in {wait} s." if wait else ""
            return errors.ProviderError(
                errors.SPOTIFY_RATE_LIMITED, f"Spotify rate limit reached.{suffix}"
            )
        # A 404 on a player call means no device, unless Spotify's own message names another cause.
        no_device_404 = (
            status == 404
            and path.startswith(PLAYER_PATH)
            and (not message or "device" in message.lower())
        )
        if reason == "NO_ACTIVE_DEVICE" or no_device_404:
            return errors.ProviderError(errors.NO_DEVICE, "No active Spotify device.")
        if status == 403:
            detail = f" ({message})" if message else ""
            return errors.ProviderError(
                errors.SPOTIFY_ERROR,
                f"Spotify refused the request{detail}. Premium and an allowed user are required.",
            )
        detail = f": {message}" if message else ""
        return errors.ProviderError(errors.SPOTIFY_ERROR, f"Spotify answered {status}{detail}")

    # playback

    async def playback(self) -> Playback | None:
        """Current playback, None when no device is active."""
        resp = await self._request(
            "GET",
            PLAYER_PATH,
            params={
                "additional_types": "track,episode",
                "market": self._market() or DEFAULT_MARKET,
            },
        )
        if resp.status_code == 204 or not resp.content:
            return None
        data: dict[str, Any] = resp.json()
        device = _device(data["device"]) if data.get("device") else None
        item = data.get("item")
        track: Track | None = None
        title = artist = None
        duration = None
        if item:
            title = item.get("name")
            artist = _first_artist(item)
            duration = item.get("duration_ms")
            playable = item.get("type") == "track" and not item.get("is_local") and item.get("uri")
            if playable:
                track = Track(item["uri"], title or "", artist, duration)
        return Playback(
            is_playing=bool(data.get("is_playing")),
            device=device,
            track=track,
            title=title,
            artist=artist,
            progress_ms=data.get("progress_ms"),
            duration_ms=duration,
        )

    async def devices(self) -> list[Device]:
        """Devices that can be controlled."""
        resp = await self._request("GET", f"{PLAYER_PATH}/devices")
        return [_device(d) for d in resp.json().get("devices", []) if d.get("id")]

    async def pause(self) -> None:
        """Pause the active device."""
        await self._request("PUT", f"{PLAYER_PATH}/pause")

    async def resume(self) -> None:
        """Resume the active device."""
        await self._request("PUT", f"{PLAYER_PATH}/play")

    async def transfer(self, device_id: str, *, play: bool) -> None:
        """Move playback to a device."""
        await self._request("PUT", PLAYER_PATH, json={"device_ids": [device_id], "play": play})

    async def next(self) -> None:
        """Skip to the next track."""
        await self._request("POST", f"{PLAYER_PATH}/next")

    async def previous(self) -> None:
        """Go to the previous track."""
        await self._request("POST", f"{PLAYER_PATH}/previous")

    async def seek(self, position_ms: int) -> None:
        """Jump within the current track."""
        await self._request("PUT", f"{PLAYER_PATH}/seek", params={"position_ms": position_ms})

    # library

    async def is_liked(self, uri: str) -> bool:
        """Whether the track is in Liked Songs."""
        resp = await self._request("GET", "/me/library/contains", params={"uris": uri})
        return bool(resp.json()[0])

    async def like(self, uri: str) -> None:
        """Add the track to Liked Songs."""
        await self._request("PUT", "/me/library", params={"uris": uri})

    async def unlike(self, uri: str) -> None:
        """Remove the track from Liked Songs."""
        await self._request("DELETE", "/me/library", params={"uris": uri})

    # playlists

    async def _snapshot(self, playlist_id: str) -> tuple[str, str]:
        resp = await self._request(
            "GET", f"/playlists/{playlist_id}", params={"fields": "snapshot_id,name"}
        )
        data = resp.json()
        return str(data.get("snapshot_id") or ""), str(data.get("name") or "")

    async def _members(self, playlist_id: str) -> set[str]:
        """Every URI in the playlist, including the pre-relinking URIs, cached per snapshot."""
        snapshot, _ = await self._snapshot(playlist_id)
        cached = self._playlist_cache.get(playlist_id)
        if cached and snapshot and cached[0] == snapshot:
            return cached[1]
        uris: set[str] = set()
        offset = 0
        for _ in range(MEMBER_MAX_PAGES):
            resp = await self._request(
                "GET",
                f"/playlists/{playlist_id}/items",
                params={
                    "limit": PAGE_SIZE,
                    "offset": offset,
                    "market": self._market() or DEFAULT_MARKET,
                    "fields": "items(item(uri,linked_from(uri)),track(uri,linked_from(uri))),next",
                },
            )
            page = resp.json()
            for entry in page.get("items", []):
                inner = (entry or {}).get("item") or (entry or {}).get("track") or {}
                for source in (inner, inner.get("linked_from") or {}):
                    if source.get("uri"):
                        uris.add(source["uri"])
            if not page.get("next"):
                self._playlist_cache[playlist_id] = (snapshot, uris)
                return uris
            offset += PAGE_SIZE
        raise errors.ProviderError(
            errors.SPOTIFY_ERROR, "The playlist is too long to check for the track."
        )

    async def playlist_contains(self, playlist_id: str, uri: str) -> bool:
        """Whether the playlist holds the track."""
        return uri in await self._members(playlist_id)

    async def playlist_add(self, playlist_id: str, uri: str) -> None:
        """Append the track to the playlist."""
        await self._request("POST", f"/playlists/{playlist_id}/items", json={"uris": [uri]})
        self._playlist_cache.pop(playlist_id, None)

    async def playlist_remove(self, playlist_id: str, uri: str) -> None:
        """Remove every occurrence of the track from the playlist."""
        await self._request(
            "DELETE", f"/playlists/{playlist_id}/items", json={"items": [{"uri": uri}]}
        )
        self._playlist_cache.pop(playlist_id, None)

    async def playlist(self, playlist_id: str) -> Playlist:
        """Look up a playlist by id."""
        _, name = await self._snapshot(playlist_id)
        return Playlist(playlist_id, name)

    async def my_playlists(self) -> list[Playlist]:
        """The user's own and followed playlists."""
        result: list[Playlist] = []
        offset = 0
        for _ in range(MAX_PAGES):
            resp = await self._request(
                "GET", "/me/playlists", params={"limit": PAGE_SIZE, "offset": offset}
            )
            page = resp.json()
            result += [Playlist(p["id"], p.get("name") or "") for p in page.get("items", []) if p]
            if not page.get("next"):
                break
            offset += PAGE_SIZE
        return result

    async def recent_playlist_contexts(self, limit: int) -> list[RecentContext]:
        """Recently played playlists, most recent first, without duplicates."""
        resp = await self._request(
            "GET", f"{PLAYER_PATH}/recently-played", params={"limit": PAGE_SIZE}
        )
        seen: dict[str, tuple[str, float]] = {}
        for entry in resp.json().get("items", []):
            context = (entry or {}).get("context") or {}
            match = PLAYLIST_CONTEXT.match(str(context.get("uri") or ""))
            if context.get("type") != "playlist" or not match:
                continue
            if match[1] not in seen:
                track = str(((entry or {}).get("track") or {}).get("name") or "")
                seen[match[1]] = (track, _epoch((entry or {}).get("played_at")))
            if len(seen) >= limit:
                break
        return [RecentContext(pid, track, at) for pid, (track, at) in seen.items()]

    async def _shuffle_then_play(
        self, body: dict[str, Any], *, shuffle: bool, device_id: str | None
    ) -> None:
        device = {"device_id": device_id} if device_id else {}
        await self._request(
            "PUT", f"{PLAYER_PATH}/shuffle", params={"state": str(shuffle).lower(), **device}
        )
        await self._request("PUT", f"{PLAYER_PATH}/play", params=device, json=body)

    async def start_playlist(
        self, playlist_id: str, *, shuffle: bool, device_id: str | None
    ) -> None:
        """Start a playlist with the given shuffle state, optionally on a device."""
        await self._shuffle_then_play(
            {"context_uri": f"spotify:playlist:{playlist_id}"},
            shuffle=shuffle,
            device_id=device_id,
        )

    async def _own_id(self) -> str:
        if self._user_id is None:
            self._user_id = str((await self._request("GET", "/me")).json()["id"])
        return self._user_id

    async def start_liked(self, *, shuffle: bool, device_id: str | None) -> None:
        """Start Liked Songs: its collection context, else the newest liked tracks as a list."""
        context = {"context_uri": f"spotify:user:{await self._own_id()}:collection"}
        try:
            await self._shuffle_then_play(context, shuffle=shuffle, device_id=device_id)
            return
        except errors.ProviderError as exc:
            if exc.code != errors.SPOTIFY_ERROR:
                raise
        resp = await self._request("GET", "/me/tracks", params={"limit": LIKED_FALLBACK_TRACKS})
        uris = [
            item["track"]["uri"]
            for item in resp.json().get("items", [])
            if (item or {}).get("track") and not item["track"].get("is_local")
        ]
        if not uris:
            raise errors.ProviderError(errors.SPOTIFY_ERROR, "There are no liked songs to play.")
        await self._shuffle_then_play({"uris": uris}, shuffle=shuffle, device_id=device_id)
