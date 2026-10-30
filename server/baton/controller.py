"""Playback actions shared by the watch API and the web page."""

from __future__ import annotations

import asyncio
import dataclasses
import functools
import logging
import re
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any, TypeVar

from baton import errors
from baton.db import Store
from baton.providers.base import Device, Playback, Provider, RecentContext

OK = "ok"
ALREADY = "already"
ERROR = "error"
RESTART_THRESHOLD_MS = 5000
# Recently played playlists that get a name, before hidden ones are taken out.
MAX_RECENT_PLAYLISTS = 20
# Saved playlists (named by hand), hidden ones, and the playlists the watch gets after Liked
# Songs; its answer must stay small.
MAX_SAVED = 10
MAX_HIDDEN = 50
MAX_LISTED = 10
LIKED_ID = "liked"
LIKED_NAME = "Liked Songs"
# Ids of personal mixes and editorial lists; Spotify does not let a development-mode app read them.
SPOTIFY_OWNED_PREFIX = "37i9dQZF1"
# Recently played items Spotify returns at most; names are looked up until enough resolve.
RECENT_CANDIDATES = 50
UNAVAILABLE_SECONDS = 3600
# A Spotify playlist id is 22 base62 characters.
PLAYLIST_ID_PATTERN = r"[A-Za-z0-9]{22}"
PLAYLIST_ID = re.compile(f"^{PLAYLIST_ID_PATTERN}$")
PLAY_MODES = ("normal", "shuffle", "smart")
UNEXPECTED_MESSAGE = "Spotify sent an answer baton does not understand."
SMART_FALLBACK_MESSAGE = (
    "Smart shuffle is not available through the Spotify API; started with shuffle."
)
T = TypeVar("T")
Command = Callable[..., Coroutine[Any, Any, "Reply"]]
UNEXPECTED_ANSWER = (KeyError, IndexError, TypeError, ValueError, AttributeError)
log = logging.getLogger(__name__)


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
    track_id: str | None = None


@dataclass(frozen=True)
class RecentPlaylist:
    """A recently played playlist with its name and the time of its latest play."""

    id: str
    name: str
    played_at: float


@dataclass(frozen=True)
class Entry:
    """A playlist as listed: ``name`` is what is shown, ``original`` what it is without a rename."""

    id: str
    name: str
    original: str
    saved: bool = False
    hidden: bool = False


@dataclass(frozen=True)
class Listing:
    """The playlists to start from and those that are managed but not on the list."""

    listed: list[Entry]
    more: list[Entry]


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


def guarded(func: Command) -> Command:
    """Turn provider failures and unexpected Spotify answers into an error reply."""

    @functools.wraps(func)
    async def wrapper(self: Controller, *args: Any, **kwargs: Any) -> Reply:
        try:
            return await func(self, *args, **kwargs)
        except errors.ProviderError as exc:
            return failure(exc.code, exc.message)
        except UNEXPECTED_ANSWER:
            log.exception("unexpected answer from Spotify")
            return failure(errors.SPOTIFY_ERROR, UNEXPECTED_MESSAGE)

    return wrapper


def serialized(func: Command) -> Command:
    """Run commands one at a time, each on the state the previous one left behind."""

    @functools.wraps(func)
    async def wrapper(self: Controller, *args: Any, **kwargs: Any) -> Reply:
        async with self._lock:
            try:
                return await func(self, *args, **kwargs)
            finally:
                self._state_generation += 1
                self._state_cache = None

    return wrapper


class Controller:
    """Turns button presses into idempotent provider calls.

    Commands run one at a time. A like, playlist or skip press that waited for another one
    therefore sees what that one did, and a retried press finds its work already done.
    """

    def __init__(
        self,
        provider: Provider,
        store: Store,
        now: Callable[[], float],
        settle_delay: float,
        recent_cache_seconds: float,
        state_cache_seconds: float,
    ) -> None:
        self._provider = provider
        self._store = store
        self._now = now
        self._settle = settle_delay
        self._recent_ttl = recent_cache_seconds
        self._recent: tuple[float, list[RecentPlaylist]] | None = None
        self._started: dict[str, float] = {}
        self._names: dict[str, str] = {}
        self._unavailable: dict[str, float] = {}
        self._state_ttl = state_cache_seconds
        self._state_cache: tuple[float, Reply] | None = None
        self._state_inflight: asyncio.Future[Reply] | None = None
        self._state_generation = 0
        self._lock = asyncio.Lock()

    # state

    async def _soft(self, call: Awaitable[T]) -> T | None:
        """Result of a secondary lookup, None when it fails for a reason other than the login."""
        try:
            return await call
        except errors.ProviderError as exc:
            if exc.code == errors.SPOTIFY_AUTH:
                raise
            return None
        except UNEXPECTED_ANSWER:
            log.exception("unexpected answer from Spotify")
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
            track_id=track.id if track else None,
        )

    async def _fresh(self) -> State:
        """State read after a short pause, once Spotify has applied a command."""
        if self._settle > 0:
            await asyncio.sleep(self._settle)
        return await self._state(await self._provider.playback())

    async def state(self) -> Reply:
        """Current state; reads that overlap or follow each other closely share one lookup."""
        if self._state_cache and self._now() - self._state_cache[0] < self._state_ttl:
            return self._state_cache[1]
        if self._state_inflight is None:
            self._state_inflight = asyncio.ensure_future(self._read_state())
        return await asyncio.shield(self._state_inflight)

    @guarded
    async def _read_state_reply(self) -> Reply:
        return Reply(OK, state=await self._state(await self._provider.playback()))

    async def _read_state(self) -> Reply:
        generation = self._state_generation
        try:
            reply = await self._read_state_reply()
            if reply.result == OK and generation == self._state_generation:
                self._state_cache = (self._now(), reply)
            return reply
        finally:
            self._state_inflight = None

    # playback commands

    @serialized
    @guarded
    async def play_pause(self) -> Reply:
        """Pause when playing, resume when paused, start on the default device when idle."""
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

    @serialized
    @guarded
    async def next(self) -> Reply:
        """Skip to the next track."""
        await self._provider.next()
        return Reply(OK, state=await self._fresh())

    @serialized
    @guarded
    async def previous(self) -> Reply:
        """Restart the track after five seconds, otherwise go to the previous one."""
        pb = await self._provider.playback()
        if pb is None:
            return failure(errors.NO_DEVICE, "No active Spotify device.")
        if (pb.progress_ms or 0) > RESTART_THRESHOLD_MS:
            await self._provider.seek(0)
        else:
            await self._provider.previous()
        return Reply(OK, state=await self._fresh())

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

    async def _current_track(self, track_id: str | None) -> tuple[Playback | None, Reply | None]:
        """The playback, or the reply to give when it holds nothing the press can act on."""
        pb = await self._provider.playback()
        if pb is None or pb.track is None:
            state = await self._state(pb) if pb else None
            return pb, failure(errors.NO_TRACK, "Nothing likable is playing.", state)
        if track_id is not None and track_id != pb.track.id:
            return pb, failure(
                errors.TRACK_CHANGED, "The track changed since it was shown.", await self._state(pb)
            )
        return pb, None

    async def like(self, track_id: str | None = None) -> Reply:
        """Add the current track to Liked Songs if it is not there."""
        return await self._library(want=True, track_id=track_id)

    async def unlike(self, track_id: str | None = None) -> Reply:
        """Remove the current track from Liked Songs if it is there."""
        return await self._library(want=False, track_id=track_id)

    @serialized
    @guarded
    async def _library(self, *, want: bool, track_id: str | None) -> Reply:
        pb, problem = await self._current_track(track_id)
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

    async def playlist_add(self, track_id: str | None = None) -> Reply:
        """Add the current track to the target playlist if it is not in it."""
        return await self._playlist(want=True, track_id=track_id)

    async def playlist_remove(self, track_id: str | None = None) -> Reply:
        """Remove the current track from the target playlist if it is in it."""
        return await self._playlist(want=False, track_id=track_id)

    @serialized
    @guarded
    async def _playlist(self, *, want: bool, track_id: str | None) -> Reply:
        pb, problem = await self._current_track(track_id)
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

    # recent playlists

    async def _playlist_name(self, playlist_id: str) -> str | None:
        """The playlist's name, None when Spotify does not let this login read it.

        Spotify-owned mixes and editorial lists answer with an error to apps in development
        mode; that outcome is remembered for an hour so it is not asked again on every refresh.
        """
        if playlist_id in self._names:
            return self._names[playlist_id]
        if (
            self._now() - self._unavailable.get(playlist_id, -UNAVAILABLE_SECONDS)
            < UNAVAILABLE_SECONDS
        ):
            return None
        try:
            name = (await self._provider.playlist(playlist_id)).name
        except errors.ProviderError as exc:
            if exc.code in (errors.SPOTIFY_AUTH, errors.SPOTIFY_RATE_LIMITED):
                raise
            self._unavailable[playlist_id] = self._now()
            return None
        if not name:
            return None
        self._names[playlist_id] = name
        return name

    async def _recent_name(self, recent: RecentContext) -> str | None:
        """Name of a recent playlist; an unreadable Spotify-owned one is labelled by a track."""
        name = await self._playlist_name(recent.id)
        if name is None and recent.id.startswith(SPOTIFY_OWNED_PREFIX):
            return f"Spotify mix ({recent.track})" if recent.track else "Spotify mix"
        return name

    async def recent_playlists(self) -> list[RecentPlaylist]:
        """Recently played playlists that can be named, most recent first, cached briefly."""
        if self._recent and self._now() - self._recent[0] < self._recent_ttl:
            return self._recent[1]
        playlists: list[RecentPlaylist] = []
        for recent in await self._provider.recent_playlist_contexts(RECENT_CANDIDATES):
            name = await self._recent_name(recent)
            if name is not None:
                playlists.append(RecentPlaylist(recent.id, name, recent.played_at))
            if len(playlists) >= MAX_RECENT_PLAYLISTS:
                break
        self._recent = (self._now(), playlists)
        return playlists

    async def listing(self) -> Listing:
        """The most recently used playlists and the managed ones that did not make the list.

        A playlist was used when Spotify last played from it, when it was started here, or, for
        a saved one, when it was added, whichever is latest. Hidden playlists never make the list.
        """
        settings = self._store.get_settings()
        hidden = {ref.id for ref in settings.hidden_playlists}
        added = {p.id: p.added_at for p in settings.saved_playlists}
        saved = {p.id: p.name for p in settings.saved_playlists}
        names = dict(saved)
        played: dict[str, float] = {}
        for recent in await self.recent_playlists():
            names.setdefault(recent.id, recent.name)
            played[recent.id] = recent.played_at
        used = {
            pid: max(added.get(pid, 0.0), played.get(pid, 0.0), self._started.get(pid, 0.0))
            for pid in names
        }

        def entry(pid: str) -> Entry:
            return Entry(
                pid, settings.playlist_names.get(pid, names[pid]), names[pid], pid in saved
            )

        ranked = [pid for pid in sorted(names, key=lambda pid: -used[pid]) if pid not in hidden]
        listed = [entry(pid) for pid in ranked[:MAX_LISTED]]
        more = [entry(pid) for pid in ranked[MAX_LISTED:] if pid in saved]
        more += [
            Entry(
                ref.id,
                settings.playlist_names.get(ref.id, ref.name),
                ref.name,
                ref.id in saved,
                True,
            )
            for ref in settings.hidden_playlists
        ]
        return Listing(listed, more)

    @guarded
    async def playlists(self, *, detailed: bool = False) -> Reply:
        """Reply carrying the playlists to start from, Liked Songs first.

        The watch gets ``id`` and ``name`` only; ``detailed`` adds what the web page needs to
        manage them, and the managed playlists that are not on the list.
        """
        listing = await self.listing()
        items: list[dict[str, Any]] = [{"id": LIKED_ID, "name": LIKED_NAME}]
        if not detailed:
            items += [{"id": e.id, "name": e.name} for e in listing.listed]
            return Reply(OK, extra={"playlists": items})
        items[0]["fixed"] = True
        items += [dataclasses.asdict(e) for e in listing.listed]
        return Reply(
            OK, extra={"playlists": items, "more": [dataclasses.asdict(e) for e in listing.more]}
        )

    @serialized
    @guarded
    async def play_playlist(self, playlist_id: str, mode: str) -> Reply:
        """Start a playlist as normal, shuffled or smart (falls back to shuffled)."""
        if mode not in PLAY_MODES or not (
            playlist_id == LIKED_ID or PLAYLIST_ID.match(playlist_id)
        ):
            return failure(errors.BAD_REQUEST, "Unknown playlist id or mode.")
        pb = await self._provider.playback()
        device_id = None
        if pb is None or pb.device is None:
            device_id = (await self._default_device()).id
        shuffle = mode != "normal"
        if playlist_id == LIKED_ID:
            await self._provider.start_liked(shuffle=shuffle, device_id=device_id)
        else:
            await self._provider.start_playlist(playlist_id, shuffle=shuffle, device_id=device_id)
        if playlist_id != LIKED_ID:
            self._started[playlist_id] = self._now()
        state = await self._fresh()
        return Reply(OK, message=SMART_FALLBACK_MESSAGE if mode == "smart" else None, state=state)
