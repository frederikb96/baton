"""The watch API under /api/watch/. Every answer is HTTP 200 with the common envelope."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from baton.auth import app_state, require_watch_key
from baton.controller import Reply

router = APIRouter(prefix="/api/watch", dependencies=[Depends(require_watch_key)])

ACTIONS = {
    "play-pause": "play_pause",
    "next": "next",
    "previous": "previous",
    "previous-track": "previous_track",
    "restart": "restart",
    "like": "like",
    "unlike": "unlike",
    "playlist/add": "playlist_add",
    "playlist/remove": "playlist_remove",
    "playing-playlist/add": "playing_playlist_add",
    "playing-playlist/remove": "playing_playlist_remove",
}


# Commands that act on the playing track and accept the id of the track the caller last saw.
ANCHORED = {
    "like",
    "unlike",
    "playlist_add",
    "playlist_remove",
    "playing_playlist_add",
    "playing_playlist_remove",
}


def add_actions(target: APIRouter) -> None:
    """Register the command routes shared by the watch API and the web page API."""
    for path, method in ACTIONS.items():

        def make(name: str) -> Any:
            async def handler(request: Request) -> dict[str, Any]:
                args = {"track_id": request.query_params.get("track")} if name in ANCHORED else {}
                reply: Reply = await getattr(app_state(request).controller, name)(**args)
                return reply.body()

            return handler

        target.add_api_route(f"/{path}", make(method), methods=["POST"])


@router.get("/state")
async def state(request: Request) -> dict[str, Any]:
    """Current playback state."""
    return (await app_state(request).controller.state()).body()


@router.get("/playlists")
async def playlists(request: Request) -> dict[str, Any]:
    """Recently played playlists."""
    return (await app_state(request).controller.playlists()).body()


@router.post("/playlists/{playlist_id}/play")
async def play_playlist(request: Request, playlist_id: str, mode: str = "normal") -> dict[str, Any]:
    """Start a playlist as normal, shuffle or smart."""
    return (await app_state(request).controller.play_playlist(playlist_id, mode)).body()


add_actions(router)
