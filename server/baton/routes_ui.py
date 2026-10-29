"""JSON API of the web page, outside /api/watch/."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from baton import __version__, errors
from baton.auth import (
    SESSION_COOKIE,
    app_state,
    check_csrf,
    client_id,
    keys_equal,
    new_session_cookie_args,
    proxy_user,
    require_ui,
    session_valid,
)
from baton.db import Ref
from baton.routes_watch import add_actions

public = APIRouter(prefix="/api/ui")
router = APIRouter(prefix="/api/ui", dependencies=[Depends(require_ui)])

STATUS_FOR_CODE = {
    errors.SPOTIFY_AUTH: 409,
    errors.BAD_REQUEST: 400,
    errors.NO_DEVICE: 409,
    errors.SPOTIFY_RATE_LIMITED: 429,
}


def provider_failure(exc: errors.ProviderError) -> HTTPException:
    """Map a provider failure to an HTTP error for the web page."""
    return HTTPException(
        STATUS_FOR_CODE.get(exc.code, 502), {"error": exc.code, "message": exc.message}
    )


class LoginBody(BaseModel):
    """Body of the key login."""

    key: str


class SettingsBody(BaseModel):
    """Settings update; only the fields present are changed, null clears."""

    target_playlist_id: str | None = None
    default_device_id: str | None = None
    market: str | None = Field(default=None, pattern=r"^([A-Za-z]{2}|from_token)?$")


class KeyBody(BaseModel):
    """Body of a watch key creation."""

    name: str = Field(min_length=1, max_length=60)


class DeviceBody(BaseModel):
    """Body of a device switch."""

    device_id: str


@public.get("/session")
async def session(request: Request) -> dict[str, Any]:
    """Whether the caller is signed in; lets the page decide between login form and content."""
    state = app_state(request)
    if state.config.auth_mode == "proxy":
        user = proxy_user(request, state.config)
        return {"auth_mode": "proxy", "authenticated": user is not None, "user": user}
    return {"auth_mode": "key", "authenticated": session_valid(request, state)}


@public.post("/login")
async def login(request: Request, body: LoginBody, response: Response) -> dict[str, Any]:
    """Exchange the UI key for a session cookie (key mode only)."""
    check_csrf(request)
    state = app_state(request)
    if state.config.auth_mode != "key" or state.config.ui_key is None:
        raise HTTPException(404, "Not available.")
    client = client_id(request, state.config)
    if state.throttle.locked(client):
        raise HTTPException(429, "Too many failed attempts. Try again later.")
    if not keys_equal(body.key, state.config.ui_key):
        state.throttle.fail(client)
        raise HTTPException(401, "Wrong key.")
    state.throttle.succeed(client)
    token = state.store.create_session(state.config.session_days * 86400)
    response.set_cookie(value=token, **new_session_cookie_args(state.config))  # type: ignore[arg-type]
    return {"authenticated": True}


@public.post("/logout")
async def logout(request: Request, response: Response) -> dict[str, Any]:
    """End the session."""
    check_csrf(request)
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        app_state(request).store.delete_session(token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"authenticated": False}


# playback ------------------------------------------------------------------------------


@router.get("/status")
async def status(request: Request) -> dict[str, Any]:
    """Version, login state and settings."""
    state = app_state(request)
    return {
        "version": __version__,
        "auth_mode": state.config.auth_mode,
        "spotify": state.accounts.status(),
        "settings": state.store.get_settings().to_json(),
        "server_time_ms": int(time.time() * 1000),
    }


@router.get("/state")
async def playback_state(request: Request) -> dict[str, Any]:
    """Current playback state."""
    return (await app_state(request).controller.state()).body()


add_actions(router)


@router.get("/playlists/recent")
async def recent_playlists(request: Request) -> dict[str, Any]:
    """Recently played playlists."""
    return (await app_state(request).controller.playlists()).body()


@router.post("/playlists/{playlist_id}/play")
async def play_playlist(request: Request, playlist_id: str, mode: str = "normal") -> dict[str, Any]:
    """Start a playlist as normal, shuffle or smart."""
    return (await app_state(request).controller.play_playlist(playlist_id, mode)).body()


@router.post("/device")
async def switch_device(request: Request, body: DeviceBody) -> dict[str, Any]:
    """Move playback to another device, keeping the play state."""
    state = app_state(request)
    try:
        pb = await state.provider.playback()
        await state.provider.transfer(body.device_id, play=bool(pb and pb.is_playing))
    except errors.ProviderError as exc:
        raise provider_failure(exc) from None
    return (await state.controller.state()).body()


# Spotify data for the pickers ----------------------------------------------------------


@router.get("/spotify/playlists")
async def my_playlists(request: Request) -> dict[str, Any]:
    """The user's playlists, for the target playlist picker."""
    try:
        items = await app_state(request).provider.my_playlists()
    except errors.ProviderError as exc:
        raise provider_failure(exc) from None
    return {"playlists": [{"id": p.id, "name": p.name} for p in items]}


@router.get("/spotify/devices")
async def devices(request: Request) -> dict[str, Any]:
    """Playback devices, for the default device picker and the device switch."""
    try:
        items = await app_state(request).provider.devices()
    except errors.ProviderError as exc:
        raise provider_failure(exc) from None
    return {
        "devices": [
            {"id": d.id, "name": d.name, "type": d.type, "is_active": d.is_active} for d in items
        ]
    }


@router.post("/spotify/disconnect")
async def disconnect(request: Request) -> dict[str, Any]:
    """Forget the Spotify login."""
    app_state(request).accounts.disconnect()
    return {"linked": False}


# settings and keys ---------------------------------------------------------------------


@router.get("/settings")
async def get_settings(request: Request) -> dict[str, Any]:
    """Runtime settings."""
    return app_state(request).store.get_settings().to_json()


@router.put("/settings")
async def put_settings(request: Request, body: SettingsBody) -> dict[str, Any]:
    """Change settings; playlist and device are resolved against Spotify and stored by name."""
    state = app_state(request)
    current = state.store.get_settings()
    changed = body.model_fields_set
    target, device, market = current.target_playlist, current.default_device, current.market
    try:
        if "target_playlist_id" in changed:
            if body.target_playlist_id:
                found = await state.provider.playlist(body.target_playlist_id)
                target = Ref(found.id, found.name)
            else:
                target = None
        if "default_device_id" in changed:
            if body.default_device_id:
                match = [
                    d for d in await state.provider.devices() if d.id == body.default_device_id
                ]
                if not match:
                    raise errors.ProviderError(
                        errors.BAD_REQUEST, "Device is not listed by Spotify."
                    )
                device = Ref(match[0].id, match[0].name)
            else:
                device = None
    except errors.ProviderError as exc:
        raise provider_failure(exc) from None
    if "market" in changed:
        market = (body.market or "").upper() or None
        if market == "FROM_TOKEN":
            market = "from_token"
    updated = type(current)(target, device, market)
    state.store.save_settings(updated)
    return updated.to_json()


@router.get("/keys")
async def list_keys(request: Request) -> dict[str, Any]:
    """Watch keys without their secrets."""
    keys = app_state(request).store.list_watch_keys()
    return {
        "keys": [
            {
                "id": k.id,
                "name": k.name,
                "hint": k.hint,
                "created_at": k.created_at,
                "last_used_at": k.last_used_at,
                "revoked": k.revoked_at is not None,
            }
            for k in keys
        ]
    }


@router.post("/keys")
async def create_key(request: Request, body: KeyBody) -> dict[str, Any]:
    """Create a watch key. The value is in this response only."""
    key, plain = app_state(request).store.create_watch_key(body.name.strip())
    return {"id": key.id, "name": key.name, "key": plain}


@router.delete("/keys/{key_id}")
async def revoke_key(request: Request, key_id: str) -> dict[str, Any]:
    """Revoke a watch key."""
    if not app_state(request).store.revoke_watch_key(key_id):
        raise HTTPException(404, "No such active key.")
    return {"revoked": key_id}
