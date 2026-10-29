"""Spotify login (authorization code flow) and the health probe."""

from __future__ import annotations

import html
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse

from baton import errors
from baton.auth import app_state, keys_equal, proxy_user, require_ui

router = APIRouter()
OAUTH_COOKIE = "baton_oauth"
OAUTH_COOKIE_PATH = "/auth/spotify"
OAUTH_COOKIE_MAX_AGE = 600


def _page(title: str, body: str) -> HTMLResponse:
    """A small result page that continues to the app through a same-site navigation."""
    content = (
        "<!doctype html><html lang=en><meta charset=utf-8>"
        '<meta http-equiv=refresh content="2;url=/">'
        '<link rel=icon type=image/png href="/static/icon-32.png">'
        f"<title>{html.escape(title)}</title>"
        '<link rel=stylesheet href="/static/style.css">'
        '<body><main class="card">'
        f"<h1>{html.escape(title)}</h1><p>{html.escape(body)}</p>"
        '<p><a class="button primary" href="/">Continue</a></p></main></body></html>'
    )
    response = HTMLResponse(content)
    response.delete_cookie(OAUTH_COOKIE, path=OAUTH_COOKIE_PATH)
    return response


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@router.post("/auth/spotify/login", dependencies=[Depends(require_ui)])
async def spotify_login(request: Request, response: Response) -> dict[str, str]:
    """Register a login and return the Spotify URL to open.

    A POST, so the same-origin check of the UI API applies and a link on another site cannot
    start a login in the owner's browser. A cookie ties the round trip to this browser.
    """
    state = app_state(request)
    token, url = state.accounts.start_login()
    response.set_cookie(
        OAUTH_COOKIE,
        token,
        max_age=OAUTH_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=state.config.cookie_secure,
        path=OAUTH_COOKIE_PATH,
    )
    return {"url": url}


@router.get("/auth/spotify/callback", response_model=None)
async def spotify_callback(
    request: Request, code: str | None = None, state: str | None = None, error: str | None = None
) -> Any:
    """Finish the login. The session cookie is SameSite=Strict and not sent on this cross-site
    navigation, so the request proves itself with the state cookie set when the login started.
    """
    app = app_state(request)
    if app.config.auth_mode == "proxy" and proxy_user(request, app.config) is None:
        return HTMLResponse("Not authenticated.", status_code=401)
    cookie = request.cookies.get(OAUTH_COOKIE)
    if not state or not cookie or not keys_equal(cookie, state):
        return HTMLResponse("Login was not started from this browser.", status_code=400)
    if error or not code:
        app.store.pop_oauth_state(state)
        return _page("Spotify login failed", f"Spotify answered: {error or 'no code'}.")
    try:
        await app.accounts.finish_login(state, code)
    except errors.ProviderError as exc:
        return _page("Spotify login failed", exc.message)
    return _page("Spotify linked", "Login complete.")
