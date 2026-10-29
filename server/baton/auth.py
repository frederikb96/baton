"""Authentication for the two route families and request hardening.

Watch routes (``/api/watch/``) accept only a valid watch key. Every other route is guarded
by the configured UI auth mode. The two never share credentials: no cookie or identity header
is looked at on watch routes, and a watch key opens nothing outside them.
"""

from __future__ import annotations

import asyncio
import hmac
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request

from baton.config import Config
from baton.controller import Controller
from baton.db import AGENT_SCOPE, Store
from baton.providers.spotify_accounts import SpotifyAccounts

if TYPE_CHECKING:
    from baton.providers.base import Provider

SESSION_COOKIE = "baton_session"
CSRF_HEADER = "x-baton-request"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
WATCH_PREFIX = "/api/watch/"
HEALTH_PATH = "/healthz"
# Pause before answering a rejected key from a client that keeps failing.
FAILED_KEY_DELAY_SECONDS = 1.0


class WatchAuthError(Exception):
    """The watch key is missing or invalid (401), or valid but not allowed here (403)."""

    def __init__(self, message: str, status: int = 401) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


class Throttle:
    """Per-client failed attempt counter with a lockout."""

    def __init__(
        self, max_failures: int, window: float, lockout: float, now: Callable[[], float]
    ) -> None:
        self._max = max_failures
        self._window = window
        self._lockout = lockout
        self._now = now
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._locked_until: dict[str, float] = {}

    def locked(self, client: str) -> bool:
        """Whether the client is currently locked out."""
        until = self._locked_until.get(client)
        if until is None:
            return False
        if self._now() >= until:
            del self._locked_until[client]
            self._failures.pop(client, None)
            return False
        return True

    def fail(self, client: str) -> None:
        """Record a failed attempt and start the lockout once the limit is reached."""
        now = self._now()
        recent = self._failures[client]
        recent.append(now)
        while recent and now - recent[0] > self._window:
            recent.popleft()
        if len(recent) >= self._max:
            self._locked_until[client] = now + self._lockout

    def succeed(self, client: str) -> None:
        """Forget earlier failures."""
        self._failures.pop(client, None)


@dataclass
class AppState:
    """Everything the route handlers share."""

    config: Config
    store: Store
    accounts: SpotifyAccounts
    provider: Provider
    controller: Controller
    throttle: Throttle
    watch_throttle: Throttle
    now: Callable[[], float]


def app_state(request: Request) -> AppState:
    """The shared state of the running app."""
    state: AppState = request.app.state.baton
    return state


def client_id(request: Request, config: Config) -> str:
    """Address used for throttling."""
    if config.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "")
        last = forwarded.rsplit(",", 1)[-1].strip()
        if last:
            return last
    return request.client.host if request.client else "unknown"


def bearer_token(request: Request) -> str | None:
    """The token of an ``Authorization: Bearer`` header."""
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


async def require_watch_key(request: Request) -> None:
    """Dependency of every watch route.

    The key is checked first, so a valid key always passes. Wrong keys never lock anyone out;
    a client that keeps sending them is only answered more slowly.
    """
    state = app_state(request)
    client = client_id(request, state.config)
    token = bearer_token(request)
    scope = state.store.verify_watch_key(token) if token is not None else None
    if scope is not None:
        state.watch_throttle.succeed(client)
        request.state.key_scope = scope
        return
    state.watch_throttle.fail(client)
    if state.watch_throttle.locked(client):
        await asyncio.sleep(FAILED_KEY_DELAY_SECONDS)
    raise WatchAuthError("Key rejected.")


async def require_agent_scope(request: Request) -> None:
    """Dependency of routes that only agent-scope keys open; runs after ``require_watch_key``."""
    if request.state.key_scope != AGENT_SCOPE:
        raise WatchAuthError("This key may not use the Spotify relay.", status=403)


def proxy_user(request: Request, config: Config) -> str | None:
    """The authenticated user a proxy announced, if any."""
    value = request.headers.get(config.proxy_user_header, "").strip()
    return value or None


def session_valid(request: Request, state: AppState) -> bool:
    """Whether the request carries a valid session cookie."""
    token = request.cookies.get(SESSION_COOKIE)
    return bool(token) and state.store.verify_session(token or "")


def check_csrf(request: Request) -> None:
    """State changing requests must be JSON or carry the custom header (no form posts)."""
    if request.method in SAFE_METHODS:
        return
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type != "application/json" and CSRF_HEADER not in request.headers:
        raise HTTPException(403, "Send JSON or the X-Baton-Request header.")


async def require_ui(request: Request) -> None:
    """Dependency of every UI API route."""
    state = app_state(request)
    if state.config.auth_mode == "proxy":
        if proxy_user(request, state.config) is None:
            raise HTTPException(401, "Not authenticated.")
    elif not session_valid(request, state):
        raise HTTPException(401, "Not authenticated.")
    check_csrf(request)


def new_session_cookie_args(config: Config) -> dict[str, object]:
    """Attributes of the session cookie."""
    return {
        "key": SESSION_COOKIE,
        "httponly": True,
        "samesite": "strict",
        "secure": config.cookie_secure,
        "path": "/",
        "max_age": config.session_days * 86400,
    }


def keys_equal(a: str, b: str) -> bool:
    """Constant-time string comparison."""
    return hmac.compare_digest(a.encode(), b.encode())
