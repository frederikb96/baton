"""Counts Spotify calls so that optional reads stay under the limits."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable

SHORT_WINDOW_SECONDS = 30.0
LONG_WINDOW_SECONDS = 3600.0


class CallBudget:
    """Rolling counts of the calls made to Spotify.

    Spotify measures a rolling 30 second window and, for development-mode apps, a quota it does
    not publish. Commands always go out; a state read is skipped once either count here reaches
    its limit, and the last known state is answered instead.
    """

    def __init__(self, per_30s: int, per_hour: int, now: Callable[[], float]) -> None:
        self._per_30s = per_30s
        self._per_hour = per_hour
        self._now = now
        self._calls: deque[float] = deque()

    def record(self) -> None:
        """Count one call."""
        self._calls.append(self._now())
        self._prune()

    def _prune(self) -> None:
        horizon = self._now() - LONG_WINDOW_SECONDS
        while self._calls and self._calls[0] <= horizon:
            self._calls.popleft()

    def counts(self) -> tuple[int, int]:
        """Calls in the last 30 seconds and in the last hour."""
        self._prune()
        horizon = self._now() - SHORT_WINDOW_SECONDS
        return sum(1 for at in self._calls if at > horizon), len(self._calls)

    def spent(self) -> bool:
        """Whether a limit is reached, so that a read that can be skipped should be."""
        short, long = self.counts()
        return short >= self._per_30s or long >= self._per_hour
