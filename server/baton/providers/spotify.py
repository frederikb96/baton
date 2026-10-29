"""Spotify Web API provider."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from baton import errors
from baton.providers.base import Device, Playback, Playlist, Provider, Track
from baton.providers.spotify_accounts import SpotifyAccounts

PAGE_SIZE = 50
MAX_PAGES = 40
DEFAULT_MARKET = "from_token"
PLAYER_PATH = "/me/player"


def _first_artist(item: dict[str, Any]) -> str | None:
    artists = item.get("artists") or []
    names = [a["name"] for a in artists if a and a.get("name")]
    if names:
        return ", ".join(names)
    show = item.get("show") or {}
    return show.get("name") or item.get("publisher")


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
    ) -> None:
        self._api = api_url.rstrip("/")
        self._accounts = accounts
        self._client = client
        self._market = market
        self._playlist_cache: dict[str, tuple[str, set[str]]] = {}

    # transport

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        ok: tuple[int, ...] = (200, 201, 202, 204),
    ) -> httpx.Response:
        resp: httpx.Response | None = None
        for attempt in range(2):
            token = await self._accounts.access_token(force=attempt == 1)
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
        if resp.status_code in ok:
            return resp
        raise self._error(resp, path)

    @staticmethod
    def _error(resp: httpx.Response, path: str) -> errors.ProviderError:
        reason = ""
        message = ""
        try:
            body = resp.json().get("error", {})
            if isinstance(body, dict):
                reason = str(body.get("reason") or "")
                message = str(body.get("message") or "")
        except ValueError:
            pass
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
        if reason == "NO_ACTIVE_DEVICE" or (status == 404 and path.startswith(PLAYER_PATH)):
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
        snapshot, _ = await self._snapshot(playlist_id)
        cached = self._playlist_cache.get(playlist_id)
        if cached and snapshot and cached[0] == snapshot:
            return cached[1]
        uris: set[str] = set()
        offset = 0
        for _ in range(MAX_PAGES):
            resp = await self._request(
                "GET",
                f"/playlists/{playlist_id}/items",
                params={
                    "limit": PAGE_SIZE,
                    "offset": offset,
                    "fields": "items(item(uri),track(uri)),next",
                },
            )
            page = resp.json()
            for entry in page.get("items", []):
                inner = (entry or {}).get("item") or (entry or {}).get("track") or {}
                if inner.get("uri"):
                    uris.add(inner["uri"])
            if not page.get("next"):
                break
            offset += PAGE_SIZE
        self._playlist_cache[playlist_id] = (snapshot, uris)
        return uris

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

    async def recent_playlist_ids(self, limit: int) -> list[str]:
        """Ids of recently played playlists, most recent first, without duplicates."""
        resp = await self._request(
            "GET", f"{PLAYER_PATH}/recently-played", params={"limit": PAGE_SIZE}
        )
        seen: list[str] = []
        for entry in resp.json().get("items", []):
            context = (entry or {}).get("context") or {}
            if context.get("type") != "playlist" or not context.get("uri"):
                continue
            playlist_id = str(context["uri"]).rsplit(":", 1)[-1]
            if playlist_id not in seen:
                seen.append(playlist_id)
            if len(seen) >= limit:
                break
        return seen

    async def start_playlist(
        self, playlist_id: str, *, shuffle: bool, device_id: str | None
    ) -> None:
        """Start a playlist with the given shuffle state, optionally on a device."""
        device = {"device_id": device_id} if device_id else {}
        await self._request(
            "PUT", f"{PLAYER_PATH}/shuffle", params={"state": str(shuffle).lower(), **device}
        )
        await self._request(
            "PUT",
            f"{PLAYER_PATH}/play",
            params=device,
            json={"context_uri": f"spotify:playlist:{playlist_id}"},
        )
