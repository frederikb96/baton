"""Shared fixtures: an app wired to the fake Spotify, with a controllable clock."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from baton import auth
from baton.app import create_app
from baton.config import Config, load_config
from baton.db import SpotifyAuthRecord
from tests.fake_spotify import FakeSpotify, create_fake_spotify

UI_KEY = "u" * 32
PUBLIC_URL = "https://baton.example.com"
SPOTIFY_URL = "http://spotify.test"


class Clock:
    """Settable time source."""

    def __init__(self, start: float = 1_800_000_000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t


def base_env(data_dir: Path, **overrides: str) -> dict[str, str]:
    """Environment of a valid key-mode configuration."""
    env = {
        "BATON_PUBLIC_URL": PUBLIC_URL,
        "BATON_UI_KEY": UI_KEY,
        "BATON_SPOTIFY_CLIENT_ID": "client-id",
        "BATON_SPOTIFY_CLIENT_SECRET": "client-secret",
        "BATON_DATA_DIR": str(data_dir),
        "BATON_SETTLE_DELAY_MS": "0",
        "BATON_STATE_CACHE_SECONDS": "0",
        "BATON_SPOTIFY_API_URL": f"{SPOTIFY_URL}/v1",
        "BATON_SPOTIFY_ACCOUNTS_URL": SPOTIFY_URL,
    }
    env.update(overrides)
    return env


@dataclass
class Rig:
    """An app under test and everything around it."""

    app: FastAPI
    config: Config
    fake: FakeSpotify
    clock: Clock
    client: httpx.AsyncClient
    watch_key: str

    @property
    def watch(self) -> dict[str, str]:
        """Authorization header of the pre-created watch key."""
        return {"Authorization": f"Bearer {self.watch_key}"}

    def link(self, authorized_at: float | None = None) -> None:
        """Store a Spotify login the fake accepts."""
        app_state_ = app_state_of(self.app)
        app_state_.store.save_spotify_auth(
            SpotifyAuthRecord(
                refresh_token=self.fake.refresh_token,
                access_token=None,
                access_expires_at=None,
                scope=None,
                authorized_at=self.clock() if authorized_at is None else authorized_at,
            )
        )

    async def login_ui(self) -> None:
        """Sign in to the web page API in key mode."""
        resp = await self.client.post("/api/ui/login", json={"key": UI_KEY})
        assert resp.status_code == 200, resp.text

    async def watch_get(self, path: str) -> httpx.Response:
        """GET a watch route with the watch key."""
        return await self.client.get(f"/api/watch/{path}", headers=self.watch)

    async def watch_post(self, path: str) -> httpx.Response:
        """POST a watch route with the watch key."""
        return await self.client.post(f"/api/watch/{path}", headers=self.watch)

    def settings(self, **kwargs: object) -> None:
        """Store runtime settings directly."""
        state = app_state_of(self.app)
        from baton.db import Ref, UserSettings

        current = state.store.get_settings()
        merged = {
            "target_playlist": current.target_playlist,
            "default_device": current.default_device,
            "market": current.market,
            "saved_playlists": current.saved_playlists,
        }
        for key, value in kwargs.items():
            merged[key] = (
                Ref(*value) if key != "saved_playlists" and isinstance(value, tuple) else value
            )
        state.store.save_settings(UserSettings(**merged))


def app_state_of(app: FastAPI):  # type: ignore[no-untyped-def]
    """The shared state of an app."""
    return app.state.baton


@pytest.fixture(autouse=True)
def no_failed_key_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rejected watch keys are answered slowly in production; tests send many of them."""
    monkeypatch.setattr(auth, "FAILED_KEY_DELAY_SECONDS", 0)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def fake() -> FakeSpotify:
    return FakeSpotify.demo()


@pytest.fixture
async def make_rig(
    tmp_path: Path, fake: FakeSpotify, clock: Clock
) -> AsyncIterator[Callable[..., Rig]]:
    """Factory building a rig; extra keyword arguments override environment variables."""
    created: list[tuple[FastAPI, httpx.AsyncClient]] = []

    def build(**env_overrides: str) -> Rig:
        env = base_env(tmp_path / "data", **env_overrides)
        config = load_config(env)
        spotify = create_fake_spotify(fake)
        app = create_app(config, transport=httpx.ASGITransport(app=spotify), now=clock)
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=PUBLIC_URL, follow_redirects=False
        )
        created.append((app, client))
        _, key = app_state_of(app).store.create_watch_key("test watch")
        return Rig(app, config, fake, clock, client, key)

    yield build
    for app, client in created:
        await client.aclose()
        app_state_of(app).store.close()


@pytest.fixture
async def rig(make_rig: Callable[..., Rig]) -> AsyncIterator[Rig]:
    """A linked key-mode rig with the default playlist and device settings."""
    r = make_rig()
    r.link()
    r.settings(
        target_playlist=("pl10000000000000000000", "My Shazam"),
        default_device=("kitchen-1", "Kitchen speaker"),
    )
    yield r
