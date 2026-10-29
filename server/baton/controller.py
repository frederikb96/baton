"""Playback actions shared by the watch API and the web page."""

from __future__ import annotations

import asyncio
import dataclasses
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from baton import errors
from baton.db import Store
from baton.providers.base import Device, Playback, Playlist, Provider

OK = "ok"
ALREADY = "already"
ERROR = "error"
RESTART_THRESHOLD_MS = 5000
MAX_RECENT_PLAYLISTS = 15
PLAYLIST_ID = re.compile(r"^[A-Za-z0-9]{1,64}$")
PLAY_MODES = ("normal", "shuffle", "smart")
SMART_FALLBACK_MESSAGE = (
    "Smart shuffle is not available through the Spotify API; started with shuffle."
)
T = TypeVar("T")


@dataclass(frozen=True)
class State:
    """Playback state as delivered to clients."""

    is_playing: bool
    title: str | None
    artist: str | None
    progress_ms: int | None
    duration_ms: int | None
    liked: bool | None
    in_playlist: bool | None
    playlist_name: str | None
    device_name: str | None
    server_time_ms: int


@dataclass(frozen=True)
class Reply:
    """Outcome of an action, serialised as the common response envelope."""

    result: str
    error: str | None = None
    message: str | None = None
    state: State | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def body(self) -> dict[str, Any]:
        """The JSON envelope."""
        out: dict[str, Any] = {
            "result": self.result,
            "error": self.error,
            "message": self.message,
            "state": dataclasses.asdict(self.state) if self.state else None,
        }
        out.update(self.extra)
        return out


def failure(code: str, message: str, state: State | None = None) -> Reply:
    """An error reply."""
    return Reply(ERROR, code, message, state)


class Controller:
    """Turns button presses into idempotent provider calls."""

    def __init__(
        self,
        provider: Provider,
        store: Store,
        now: Callable[[], float],
        settle_delay: float,
        recent_cache_seconds: float,
    ) -> None:
        self._provider = provider
        self._store = store
        self._now = now
        self._settle = settle_delay
        self._recent_ttl = recent_cache_seconds
        self._recent: tuple[float, list[Playlist]] | None = None
        self._names: dict[str, str] = {}

    # state

    async def _soft(self, call: Awaitable[T]) -> T | None:
        """Result of a secondary lookup, None when it fails for a reason other than the login."""
        try:
            return await call
        except errors.ProviderError as exc:
            if exc.code == errors.SPOTIFY_AUTH:
                raise
            return None

    async def _state(
        self,
        pb: Playback | None,
        *,
        liked: bool | None = None,
        in_playlist: bool | None = None,
    ) -> State:
        target = self._store.get_settings().target_playlist
        track = pb.track if pb else None
        if track is not None and liked is None:
            liked = await self._soft(self._provider.is_liked(track.uri))
        if track is not None and target is not None and in_playlist is None:
            in_playlist = await self._soft(self._provider.playlist_contains(target.id, track.uri))
        return State(
            is_playing=bool(pb and pb.is_playing),
            title=pb.title if pb else None,
            artist=pb.artist if pb else None,
            progress_ms=pb.progress_ms if pb else None,
            duration_ms=pb.duration_ms if pb else None,
            liked=liked if track else None,
            in_playlist=in_playlist if track and target else None,
            playlist_name=target.name if target else None,
            device_name=pb.device.name if pb and pb.device else None,
            server_time_ms=int(self._now() * 1000),
        )

    async def _fresh(self) -> State:
        """State read after a short pause, once Spotify has applied a command."""
        if self._settle > 0:
            await asyncio.sleep(self._settle)
        return await self._state(await self._provider.playback())

    async def state(self) -> Reply:
        """Current state."""
        try:
            return Reply(OK, state=await self._state(await self._provider.playback()))
        except errors.ProviderError as exc:
            return failure(exc.code, exc.message)

    # playback commands

    async def play_pause(self) -> Reply:
        """Pause when playing, resume when paused, start on the default device when idle."""
        try:
            pb = await self._provider.playback()
            if pb is None or pb.device is None:
                device = await self._default_device()
                await self._provider.transfer(device.id, play=True)
                return Reply(OK, state=await self._fresh())
            if pb.is_playing:
                await self._provider.pause()
            else:
                await self._provider.resume()
            return Reply(
                OK, state=await self._state(dataclasses.replace(pb, is_playing=not pb.is_playing))
            )
        except errors.ProviderError as exc:
            return failure(exc.code, exc.message)

    async def next(self) -> Reply:
        """Skip to the next track."""
        try:
            await self._provider.next()
            return Reply(OK, state=await self._fresh())
        except errors.ProviderError as exc:
            return failure(exc.code, exc.message)

    async def previous(self) -> Reply:
        """Restart the track after five seconds, otherwise go to the previous one."""
        try:
            pb = await self._provider.playback()
            if pb is None:
                return failure(errors.NO_DEVICE, "No active Spotify device.")
            if (pb.progress_ms or 0) > RESTART_THRESHOLD_MS:
                await self._provider.seek(0)
            else:
                await self._provider.previous()
            return Reply(OK, state=await self._fresh())
        except errors.ProviderError as exc:
            return failure(exc.code, exc.message)

    async def _default_device(self) -> Device:
        """The configured default device if Spotify lists it."""
        default = self._store.get_settings().default_device
        if default is not None:
            devices = [d for d in await self._provider.devices() if not d.is_restricted]
            for device in devices:
                if device.id == default.id:
                    return device
            for device in devices:
                if device.name.casefold() == default.name.casefold():
                    return device
        raise errors.ProviderError(errors.NO_DEVICE, "Default device is asleep or not set.")

    # library and playlist

    async def _current_track(self) -> tuple[Playback | None, Reply | None]:
        pb = await self._provider.playback()
        if pb is None or pb.track is None:
            state = await self._state(pb) if pb else None
            return pb, failure(errors.NO_TRACK, "Nothing likable is playing.", state)
        return pb, None

    async def like(self) -> Reply:
        """Add the current track to Liked Songs if it is not there."""
        return await self._library(want=True)

    async def unlike(self) -> Reply:
        """Remove the current track from Liked Songs if it is there."""
        return await self._library(want=False)

    async def _library(self, *, want: bool) -> Reply:
        try:
            pb, problem = await self._current_track()
            if problem or pb is None or pb.track is None:
                return problem or failure(errors.NO_TRACK, "Nothing likable is playing.")
            liked = await self._provider.is_liked(pb.track.uri)
            if liked == want:
                return Reply(ALREADY, state=await self._state(pb, liked=liked))
            if want:
                await self._provider.like(pb.track.uri)
            else:
                await self._provider.unlike(pb.track.uri)
            return Reply(OK, state=await self._state(pb, liked=want))
        except errors.ProviderError as exc:
            return failure(exc.code, exc.message)

    async def playlist_add(self) -> Reply:
        """Add the current track to the target playlist if it is not in it."""
        return await self._playlist(want=True)

    async def playlist_remove(self) -> Reply:
        """Remove the current track from the target playlist if it is in it."""
        return await self._playlist(want=False)

    async def _playlist(self, *, want: bool) -> Reply:
        try:
            pb, problem = await self._current_track()
            if problem or pb is None or pb.track is None:
                return problem or failure(errors.NO_TRACK, "Nothing likable is playing.")
            target = self._store.get_settings().target_playlist
            if target is None:
                return failure(
                    errors.NO_TARGET_PLAYLIST, "No target playlist is set.", await self._state(pb)
                )
            member = await self._provider.playlist_contains(target.id, pb.track.uri)
            if member == want:
                return Reply(ALREADY, state=await self._state(pb, in_playlist=member))
            if want:
                await self._provider.playlist_add(target.id, pb.track.uri)
            else:
                await self._provider.playlist_remove(target.id, pb.track.uri)
            return Reply(OK, state=await self._state(pb, in_playlist=want))
        except errors.ProviderError as exc:
            return failure(exc.code, exc.message)

    # recent playlists

    async def _playlist_name(self, playlist_id: str) -> str:
        if playlist_id not in self._names:
            try:
                self._names[playlist_id] = (await self._provider.playlist(playlist_id)).name
            except errors.ProviderError as exc:
                if exc.code in (errors.SPOTIFY_AUTH, errors.SPOTIFY_RATE_LIMITED):
                    raise
                return "Unnamed playlist"
        return self._names[playlist_id]

    async def recent_playlists(self) -> list[Playlist]:
        """Recently played playlists, most recent first, cached for a short time."""
        if self._recent and self._now() - self._recent[0] < self._recent_ttl:
            return self._recent[1]
        ids = await self._provider.recent_playlist_ids(MAX_RECENT_PLAYLISTS)
        names = [await self._playlist_name(i) for i in ids]
        playlists = [Playlist(i, n) for i, n in zip(ids, names, strict=True)]
        self._recent = (self._now(), playlists)
        return playlists

    async def playlists(self) -> Reply:
        """Reply carrying the recent playlists."""
        try:
            items = [{"id": p.id, "name": p.name} for p in await self.recent_playlists()]
            return Reply(OK, extra={"playlists": items})
        except errors.ProviderError as exc:
            return failure(exc.code, exc.message)

    async def play_playlist(self, playlist_id: str, mode: str) -> Reply:
        """Start a playlist as normal, shuffled or smart (falls back to shuffled)."""
        if mode not in PLAY_MODES or not PLAYLIST_ID.match(playlist_id):
            return failure(errors.BAD_REQUEST, "Unknown playlist id or mode.")
        try:
            pb = await self._provider.playback()
            device_id = None
            if pb is None or pb.device is None:
                device_id = (await self._default_device()).id
            await self._provider.start_playlist(
                playlist_id, shuffle=mode != "normal", device_id=device_id
            )
            state = await self._fresh()
            return Reply(
                OK, message=SMART_FALLBACK_MESSAGE if mode == "smart" else None, state=state
            )
        except errors.ProviderError as exc:
            return failure(exc.code, exc.message)
