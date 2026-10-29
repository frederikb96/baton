"""Error codes shared by the providers, the controller and the watch API."""

from __future__ import annotations

NO_DEVICE = "no_device"
NO_TRACK = "no_track"
NO_TARGET_PLAYLIST = "no_target_playlist"
SPOTIFY_AUTH = "spotify_auth"
SPOTIFY_RATE_LIMITED = "spotify_rate_limited"
SPOTIFY_ERROR = "spotify_error"
BAD_REQUEST = "bad_request"
TRACK_CHANGED = "track_changed"


class ProviderError(Exception):
    """A failure with a stable error code and a short human readable message."""

    def __init__(self, code: str, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_after = retry_after
