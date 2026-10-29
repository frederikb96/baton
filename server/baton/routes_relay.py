"""Spotify Web API relay under /api/watch/spotify/, open to agent-scope keys only."""

from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, Depends, Request, Response

from baton import errors
from baton.auth import app_state, require_agent_scope, require_watch_key

router = APIRouter(
    prefix="/api/watch/spotify",
    dependencies=[Depends(require_watch_key), Depends(require_agent_scope)],
)

METHODS = ["GET", "POST", "PUT", "DELETE"]
# Letters, digits and the few punctuation marks Web API paths use; no dots, so a path cannot
# climb out of the Web API base, and no percent signs, so nothing is decoded a second time.
SEGMENT = re.compile(r"^[A-Za-z0-9_:-]+$")
STATUS_FOR_CODE = {errors.SPOTIFY_AUTH: 409, errors.SPOTIFY_RATE_LIMITED: 429}


def error(status: int, code: str, message: str) -> Response:
    """An error in the shape of the other JSON errors."""
    body = {"result": "error", "error": code, "message": message, "state": None}
    return Response(json.dumps(body), status_code=status, media_type="application/json")


@router.api_route("/{path:path}", methods=METHODS)
async def relay(request: Request, path: str) -> Response:
    """Forward the call, with its query and JSON body, to the same path under the Web API."""
    segments = path.split("/")
    if not all(SEGMENT.match(s) for s in segments):
        return error(400, errors.BAD_REQUEST, "Path must stay under the Spotify Web API.")
    raw = await request.body()
    payload: Any = None
    if raw:
        try:
            payload = json.loads(raw)
        except ValueError:
            return error(400, errors.BAD_REQUEST, "Body must be JSON.")
    try:
        answer = await app_state(request).provider.relay(
            request.method, "/" + path, request.query_params.multi_items(), payload
        )
    except errors.ProviderError as exc:
        return error(STATUS_FOR_CODE.get(exc.code, 502), exc.code, exc.message)
    headers = {"Retry-After": answer.retry_after} if answer.retry_after else {}
    return Response(
        answer.content,
        status_code=answer.status,
        media_type=answer.content_type if answer.content else None,
        headers=headers,
    )
