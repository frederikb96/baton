"""A stateful stand-in for the parts of Spotify the server talks to.

Used by the tests through an ASGI transport and, run on its own, as the Spotify behind a local
instance (``uvicorn --factory tests.fake_spotify:demo_app``).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlencode

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

GOOD_CODE = "good-code"
PAGE = 50


@dataclass
class FakePlaylist:
    """A playlist with ordered items."""

    id: str
    name: str
    items: list[str] = field(default_factory=list)
    snapshot: int = 1

    def touch(self) -> None:
        """Bump the snapshot id after a change."""
        self.snapshot += 1


@dataclass
class FakeSpotify:
    """Everything the fake serves and records."""

    tracks: dict[str, tuple[str, str, int]] = field(default_factory=dict)
    queue: list[str] = field(default_factory=list)
    index: int = 0
    progress_ms: int = 0
    is_playing: bool = False
    shuffle: bool = False
    devices: list[dict[str, Any]] = field(default_factory=list)
    active_device: str | None = None
    liked: list[str] = field(default_factory=list)
    playlists: dict[str, FakePlaylist] = field(default_factory=dict)
    recent_contexts: list[str] = field(default_factory=list)
    context: str | None = None
    refresh_token: str = "refresh-1"
    valid_access: set[str] = field(default_factory=set)
    issued: int = 0
    expires_in: int = 3600
    calls: list[tuple[str, str, dict[str, str]]] = field(default_factory=list)
    faults: dict[str, list[tuple[int, dict[str, Any], dict[str, str]]]] = field(
        default_factory=dict
    )
    episode_playing: bool = False
    refresh_response_rotates: bool = False

    def current_uri(self) -> str | None:
        """URI of the current track."""
        if self.active_device is None or not self.queue:
            return None
        return self.queue[self.index % len(self.queue)]

    def calls_to(self, method: str, path: str) -> list[dict[str, str]]:
        """Recorded query parameters of calls to a path."""
        return [p for m, pa, p in self.calls if m == method and pa == path]

    def fail(
        self,
        method_path: str,
        status: int,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        times: int = 1,
    ) -> None:
        """Make the next calls to ``"METHOD /path"`` fail."""
        self.faults.setdefault(method_path, []).extend(
            [(status, body or {}, headers or {})] * times
        )

    @classmethod
    def demo(cls) -> FakeSpotify:
        """A small library with one phone that is playing."""
        fake = cls()
        songs = [
            ("Blue Monday", "New Order", 449000),
            ("Heroes", "David Bowie", 371000),
            ("Teardrop", "Massive Attack", 330000),
            ("Windowlicker", "Aphex Twin", 366000),
        ]
        for i, (name, artist, dur) in enumerate(songs):
            fake.tracks[f"spotify:track:t{i}"] = (name, artist, dur)
        fake.queue = list(fake.tracks)
        fake.devices = [
            {"id": "phone-1", "name": "Alex's iPhone", "type": "Smartphone", "is_active": True},
            {"id": "kitchen-1", "name": "Kitchen speaker", "type": "Speaker", "is_active": False},
        ]
        fake.active_device = "phone-1"
        fake.is_playing = True
        fake.progress_ms = 83000
        fake.liked = ["spotify:track:t1"]
        fake.playlists = {
            "pl1": FakePlaylist("pl1", "My Shazam", ["spotify:track:t2"]),
            "pl2": FakePlaylist("pl2", "Cycling", ["spotify:track:t0", "spotify:track:t3"]),
            "pl3": FakePlaylist("pl3", "Sunday morning", []),
        }
        fake.recent_contexts = ["pl2", "pl1", "pl2", "pl3"]
        return fake


def create_fake_spotify(fake: FakeSpotify) -> FastAPI:
    """The ASGI app serving the accounts and Web API endpoints from ``fake``."""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def record(request: Request) -> None:
        fake.calls.append((request.method, request.url.path, dict(request.query_params)))

    def injected(request: Request) -> Response | None:
        queue = fake.faults.get(f"{request.method} {request.url.path}")
        if queue:
            status, body, headers = queue.pop(0)
            return JSONResponse(body, status_code=status, headers=headers)
        return None

    def issue() -> dict[str, Any]:
        fake.issued += 1
        token = f"access-{fake.issued}"
        fake.valid_access.add(token)
        return {
            "access_token": token,
            "token_type": "Bearer",
            "expires_in": fake.expires_in,
            "scope": "user-read-playback-state",
        }

    @app.get("/authorize")
    async def authorize(request: Request) -> Response:
        query = request.query_params
        target = (
            f"{query['redirect_uri']}?{urlencode({'code': GOOD_CODE, 'state': query['state']})}"
        )
        return RedirectResponse(target)

    @app.post("/api/token")
    async def token(request: Request) -> Response:
        record(request)
        if (early := injected(request)) is not None:
            return early
        form = dict(parse_qsl((await request.body()).decode()))
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Basic ") or b":" not in base64.b64decode(auth[6:]):
            return JSONResponse({"error": "invalid_client"}, status_code=401)
        if form.get("grant_type") == "authorization_code":
            if form.get("code") != GOOD_CODE or not form.get("code_verifier"):
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            return JSONResponse({**issue(), "refresh_token": fake.refresh_token})
        if form.get("refresh_token") != fake.refresh_token:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        body = issue()
        if fake.refresh_response_rotates:
            fake.refresh_token = f"refresh-{fake.issued}"
            body["refresh_token"] = fake.refresh_token
        return JSONResponse(body)

    @app.middleware("http")
    async def gate(request: Request, call_next: Any) -> Response:
        if request.url.path.startswith("/v1"):
            record(request)
            auth = request.headers.get("authorization", "")
            if auth.removeprefix("Bearer ") not in fake.valid_access:
                return JSONResponse({"error": {"status": 401, "message": "expired"}}, 401)
            if (early := injected(request)) is not None:
                return early
        response: Response = await call_next(request)
        return response

    def need_device() -> Response | None:
        if fake.active_device is None:
            return JSONResponse(
                {
                    "error": {
                        "status": 404,
                        "message": "No active device",
                        "reason": "NO_ACTIVE_DEVICE",
                    }
                },
                404,
            )
        return None

    @app.get("/v1/me/player")
    async def player() -> Response:
        uri = fake.current_uri()
        if fake.active_device is None:
            return Response(status_code=204)
        device = next(d for d in fake.devices if d["id"] == fake.active_device)
        item: dict[str, Any] | None = None
        if fake.episode_playing:
            item = {
                "type": "episode",
                "uri": "spotify:episode:e1",
                "name": "Episode 1",
                "duration_ms": 1800000,
                "show": {"name": "A Podcast"},
            }
        elif uri:
            name, artist, duration = fake.tracks[uri]
            item = {
                "type": "track",
                "uri": uri,
                "name": name,
                "duration_ms": duration,
                "artists": [{"name": artist}],
            }
        return JSONResponse(
            {
                "device": {**device, "is_active": True},
                "is_playing": fake.is_playing,
                "progress_ms": fake.progress_ms,
                "shuffle_state": fake.shuffle,
                "item": item,
                "currently_playing_type": "episode" if fake.episode_playing else "track",
            }
        )

    @app.get("/v1/me/player/devices")
    async def devices() -> dict[str, Any]:
        return {
            "devices": [{**d, "is_active": d["id"] == fake.active_device} for d in fake.devices]
        }

    @app.put("/v1/me/player")
    async def transfer(request: Request) -> Response:
        body = await request.json()
        wanted = body["device_ids"][0]
        if wanted not in {d["id"] for d in fake.devices}:
            return JSONResponse({"error": {"status": 404, "message": "Device not found"}}, 404)
        fake.active_device = wanted
        fake.is_playing = bool(body.get("play"))
        return Response(status_code=204)

    @app.put("/v1/me/player/pause")
    async def pause() -> Response:
        if (missing := need_device()) is not None:
            return missing
        fake.is_playing = False
        return Response(status_code=204)

    @app.put("/v1/me/player/play")
    async def play(request: Request) -> Response:
        device_id = request.query_params.get("device_id")
        if device_id:
            fake.active_device = device_id
        if (missing := need_device()) is not None:
            return missing
        raw = await request.body()
        if raw:
            body = await request.json()
            context = body.get("context_uri")
            if context:
                fake.context = context
                fake.index = 0
                fake.progress_ms = 0
                playlist = fake.playlists.get(context.rsplit(":", 1)[-1])
                if playlist and playlist.items:
                    fake.queue = list(playlist.items)
        fake.is_playing = True
        return Response(status_code=204)

    @app.put("/v1/me/player/shuffle")
    async def shuffle(request: Request) -> Response:
        if (missing := need_device()) is not None and not request.query_params.get("device_id"):
            return missing
        fake.shuffle = request.query_params["state"] == "true"
        return Response(status_code=204)

    @app.post("/v1/me/player/next")
    async def next_track() -> Response:
        if (missing := need_device()) is not None:
            return missing
        fake.index = (fake.index + 1) % len(fake.queue)
        fake.progress_ms = 0
        return Response(status_code=204)

    @app.post("/v1/me/player/previous")
    async def previous() -> Response:
        if (missing := need_device()) is not None:
            return missing
        fake.index = (fake.index - 1) % len(fake.queue)
        fake.progress_ms = 0
        return Response(status_code=204)

    @app.put("/v1/me/player/seek")
    async def seek(request: Request) -> Response:
        if (missing := need_device()) is not None:
            return missing
        fake.progress_ms = int(request.query_params["position_ms"])
        return Response(status_code=204)

    @app.get("/v1/me/player/recently-played")
    async def recent() -> dict[str, Any]:
        items: list[dict[str, Any]] = [
            {
                "track": {"uri": "spotify:track:t0"},
                "context": {"type": "playlist", "uri": f"spotify:playlist:{pid}"},
            }
            for pid in fake.recent_contexts
        ]
        items.insert(1, {"track": {"uri": "spotify:track:t1"}, "context": None})
        items.insert(
            2,
            {
                "track": {"uri": "spotify:track:t1"},
                "context": {"type": "album", "uri": "spotify:album:a1"},
            },
        )
        return {"items": items}

    @app.get("/v1/me/library/contains")
    async def contains(uris: str) -> list[bool]:
        return [u in fake.liked for u in uris.split(",")]

    @app.put("/v1/me/library")
    async def like(uris: str) -> Response:
        for uri in uris.split(","):
            if uri in fake.liked:
                fake.liked.remove(uri)  # a re-like moves it to the top, like a new added date
            fake.liked.append(uri)
        return Response(status_code=200)

    @app.delete("/v1/me/library")
    async def unlike(uris: str) -> Response:
        for uri in uris.split(","):
            if uri in fake.liked:
                fake.liked.remove(uri)
        return Response(status_code=200)

    @app.get("/v1/me/playlists")
    async def my_playlists(offset: int = 0, limit: int = PAGE) -> dict[str, Any]:
        everything = [{"id": p.id, "name": p.name} for p in fake.playlists.values()]
        page = everything[offset : offset + limit]
        more = offset + limit < len(everything)
        return {"items": page, "next": "more" if more else None}

    def find(playlist_id: str) -> FakePlaylist | None:
        return fake.playlists.get(playlist_id)

    @app.get("/v1/playlists/{playlist_id}")
    async def playlist(playlist_id: str) -> Response:
        found = find(playlist_id)
        if found is None:
            return JSONResponse({"error": {"status": 404, "message": "Not found"}}, 404)
        return JSONResponse({"name": found.name, "snapshot_id": f"snap-{found.snapshot}"})

    @app.get("/v1/playlists/{playlist_id}/items")
    async def playlist_items(playlist_id: str, offset: int = 0, limit: int = PAGE) -> Response:
        found = find(playlist_id)
        if found is None:
            return JSONResponse({"error": {"status": 404, "message": "Not found"}}, 404)
        page = found.items[offset : offset + limit]
        more = offset + limit < len(found.items)
        return JSONResponse(
            {"items": [{"item": {"uri": u}} for u in page], "next": "more" if more else None}
        )

    @app.post("/v1/playlists/{playlist_id}/items")
    async def playlist_add(playlist_id: str, request: Request) -> Response:
        found = find(playlist_id)
        if found is None:
            return JSONResponse({"error": {"status": 404, "message": "Not found"}}, 404)
        found.items += (await request.json())["uris"]
        found.touch()
        return JSONResponse({"snapshot_id": f"snap-{found.snapshot}"}, status_code=201)

    @app.delete("/v1/playlists/{playlist_id}/items")
    async def playlist_remove(playlist_id: str, request: Request) -> Response:
        found = find(playlist_id)
        if found is None:
            return JSONResponse({"error": {"status": 404, "message": "Not found"}}, 404)
        gone = {i["uri"] for i in (await request.json())["items"]}
        found.items = [u for u in found.items if u not in gone]
        found.touch()
        return JSONResponse({"snapshot_id": f"snap-{found.snapshot}"})

    return app


def demo_app() -> FastAPI:
    """Entry point for running the fake on its own."""
    return create_fake_spotify(FakeSpotify.demo())
