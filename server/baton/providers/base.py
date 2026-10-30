"""The audio source interface the controller works against."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Device:
    """A playback device."""

    id: str
    name: str
    type: str
    is_active: bool
    is_restricted: bool = False


@dataclass(frozen=True)
class Track:
    """A track that can be liked and put into playlists."""

    uri: str
    title: str
    artist: str | None
    duration_ms: int | None

    @property
    def id(self) -> str:
        """The Spotify id, the last part of the URI."""
        return self.uri.rsplit(":", 1)[-1]


@dataclass(frozen=True)
class Playback:
    """What is playing right now.

    ``track`` is None for episodes, ads and anything else that cannot be liked.
    """

    is_playing: bool
    device: Device | None
    track: Track | None
    title: str | None
    artist: str | None
    progress_ms: int | None
    duration_ms: int | None


@dataclass(frozen=True)
class Playlist:
    """A playlist reference."""

    id: str
    name: str


@dataclass(frozen=True)
class RecentContext:
    """A playlist something was recently played from: its latest play and the track played."""

    id: str
    track: str
    played_at: float


@dataclass(frozen=True)
class RelayResponse:
    """The answer of the source's API to a relayed call."""

    status: int
    content: bytes
    content_type: str | None
    retry_after: str | None


class Provider(ABC):
    """Operations an audio source offers. Failures raise ``errors.ProviderError``."""

    @abstractmethod
    def reads_open(self) -> bool:
        """Whether a state read may go out now, or the last known state should answer."""

    @abstractmethod
    async def playback(self) -> Playback | None:
        """Current playback, None when no device is active."""

    @abstractmethod
    async def devices(self) -> list[Device]:
        """Devices that can be controlled."""

    @abstractmethod
    async def pause(self) -> None:
        """Pause the active device."""

    @abstractmethod
    async def resume(self) -> None:
        """Resume the active device."""

    @abstractmethod
    async def transfer(self, device_id: str, *, play: bool) -> None:
        """Move playback to a device."""

    @abstractmethod
    async def next(self) -> None:
        """Skip to the next track."""

    @abstractmethod
    async def previous(self) -> None:
        """Go to the previous track."""

    @abstractmethod
    async def seek(self, position_ms: int) -> None:
        """Jump within the current track."""

    @abstractmethod
    async def is_liked(self, uri: str) -> bool:
        """Whether the track is in Liked Songs."""

    @abstractmethod
    async def like(self, uri: str) -> None:
        """Add the track to Liked Songs."""

    @abstractmethod
    async def unlike(self, uri: str) -> None:
        """Remove the track from Liked Songs."""

    @abstractmethod
    async def playlist_contains(self, playlist_id: str, uri: str) -> bool:
        """Whether the playlist holds the track."""

    @abstractmethod
    async def playlist_add(self, playlist_id: str, uri: str) -> None:
        """Append the track to the playlist."""

    @abstractmethod
    async def playlist_remove(self, playlist_id: str, uri: str) -> None:
        """Remove every occurrence of the track from the playlist."""

    @abstractmethod
    async def playlist(self, playlist_id: str) -> Playlist:
        """Look up a playlist by id."""

    @abstractmethod
    async def my_playlists(self) -> list[Playlist]:
        """The user's own and followed playlists."""

    @abstractmethod
    async def recent_playlist_contexts(self, limit: int) -> list[RecentContext]:
        """Recently played playlists, most recent first, without duplicates."""

    @abstractmethod
    async def start_playlist(
        self, playlist_id: str, *, shuffle: bool, device_id: str | None
    ) -> None:
        """Start a playlist with the given shuffle state, optionally on a device."""

    @abstractmethod
    async def start_liked(self, *, shuffle: bool, device_id: str | None) -> None:
        """Start Liked Songs with the given shuffle state, optionally on a device."""

    @abstractmethod
    async def relay(
        self, method: str, path: str, params: list[tuple[str, str]], body: Any
    ) -> RelayResponse:
        """Forward a call to the source's own API with the stored login."""
