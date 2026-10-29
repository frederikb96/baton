"""Application factory."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from importlib import resources
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from baton import __version__, routes_login, routes_relay, routes_ui, routes_watch
from baton.auth import HEALTH_PATH, WATCH_PREFIX, AppState, Throttle, WatchAuthError, proxy_user
from baton.config import Config
from baton.controller import Controller
from baton.db import Store
from baton.limits import BodyLimitMiddleware
from baton.providers.spotify import SpotifyProvider
from baton.providers.spotify_accounts import SpotifyAccounts

CSP = (
    "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; "
    "base-uri 'none'; form-action 'self'"
)
STATIC_DIR = Path(str(resources.files("baton").joinpath("static")))
# Icon files browsers and home screens fetch without credentials, served in every auth mode.
ICON_FILES = ("icon-32.png", "icon-192.png", "icon-512.png", "apple-touch-icon.png")
ICON_ROUTES = {"/favicon.ico": "icon-32.png", "/apple-touch-icon.png": "apple-touch-icon.png"}
ICON_PATHS = {*ICON_ROUTES, *(f"/static/{name}" for name in ICON_FILES)}


def create_app(
    config: Config,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    now: Callable[[], float] = time.time,
) -> FastAPI:
    """Build the app; ``transport`` and ``now`` let tests replace Spotify and the clock."""
    store = Store(Path(config.data_dir), now)
    store.sync_ui_key(config.ui_key)
    client = httpx.AsyncClient(transport=transport)
    accounts = SpotifyAccounts(config, store, client, now)
    provider = SpotifyProvider(
        config.spotify_api_url, accounts, client, lambda: store.get_settings().market, now
    )
    controller = Controller(
        provider,
        store,
        now,
        config.settle_delay_ms / 1000,
        config.recent_playlists_cache_seconds,
        config.state_cache_seconds,
    )

    def new_throttle() -> Throttle:
        return Throttle(
            config.throttle_max_failures,
            config.throttle_window_seconds,
            config.throttle_lockout_seconds,
            now,
        )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await client.aclose()
        store.close()

    app = FastAPI(
        title="baton",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.baton = AppState(
        config, store, accounts, provider, controller, new_throttle(), new_throttle(), now
    )

    @app.exception_handler(WatchAuthError)
    async def watch_auth_failed(_: Request, exc: WatchAuthError) -> JSONResponse:
        return JSONResponse(
            {"result": "error", "error": None, "message": exc.message, "state": None},
            status_code=exc.status,
            headers={"WWW-Authenticate": "Bearer"} if exc.status == 401 else {},
        )

    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        proxy_open = path == HEALTH_PATH or path.startswith(WATCH_PREFIX) or path in ICON_PATHS
        if config.auth_mode == "proxy" and not proxy_open and proxy_user(request, config) is None:
            response: Response = JSONResponse({"detail": "Not authenticated."}, status_code=401)
        else:
            response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = CSP
        if path.startswith(("/api/", "/auth/")):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.add_middleware(BodyLimitMiddleware)

    app.include_router(routes_watch.router)
    app.include_router(routes_relay.router)
    app.include_router(routes_ui.public)
    app.include_router(routes_ui.router)
    app.include_router(routes_login.router)

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    for route, name in ICON_ROUTES.items():

        def icon(name: str = name) -> FileResponse:
            return FileResponse(STATIC_DIR / name)

        app.add_api_route(route, icon, include_in_schema=False)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
