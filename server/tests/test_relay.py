"""Key scopes and the Spotify relay under /api/watch/spotify/."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pytest

from baton.db import Store
from tests.conftest import Rig, app_state_of


async def agent_headers(rig: Rig, name: str = "agent") -> dict[str, str]:
    _, plain = app_state_of(rig.app).store.create_watch_key(name, "agent")
    return {"Authorization": f"Bearer {plain}"}


async def test_watch_key_is_refused_on_the_relay(rig: Rig) -> None:
    resp = await rig.client.get("/api/watch/spotify/me/player", headers=rig.watch)
    assert resp.status_code == 403
    assert resp.json()["result"] == "error" and "www-authenticate" not in resp.headers
    assert rig.fake.calls == []


@pytest.mark.parametrize("header", [None, "Bearer wrong"])
async def test_relay_needs_a_key(rig: Rig, header: str | None) -> None:
    headers = {"Authorization": header} if header else {}
    resp = await rig.client.get("/api/watch/spotify/me/player", headers=headers)
    assert resp.status_code == 401 and rig.fake.calls == []


async def test_agent_key_reads_the_player_through_the_relay(rig: Rig) -> None:
    headers = await agent_headers(rig)
    resp = await rig.client.get("/api/watch/spotify/me/player", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["device"]["id"] == "phone-1" and resp.json()["is_playing"] is True


async def test_agent_key_also_opens_the_watch_api(rig: Rig) -> None:
    headers = await agent_headers(rig)
    assert (await rig.client.get("/api/watch/state", headers=headers)).status_code == 200


async def test_relay_forwards_query_and_json_body(rig: Rig) -> None:
    headers = await agent_headers(rig)
    await rig.client.get("/api/watch/spotify/me/player?market=DE", headers=headers)
    assert rig.fake.calls_to("GET", "/v1/me/player")[-1]["market"] == "DE"
    resp = await rig.client.put(
        "/api/watch/spotify/me/player",
        json={"device_ids": ["kitchen-1"], "play": True},
        headers=headers,
    )
    assert resp.status_code == 204 and resp.content == b""
    assert rig.fake.active_device == "kitchen-1"


async def test_relay_passes_spotify_errors_through(rig: Rig) -> None:
    headers = await agent_headers(rig)
    resp = await rig.client.get("/api/watch/spotify/playlists/nope", headers=headers)
    assert resp.status_code == 404 and resp.json()["error"]["message"] == "Not found"


@pytest.mark.parametrize(
    "path",
    [
        "me/../../v2/anything",
        "%2e%2e/%2e%2e/etc",
        "me/player%2f..%2fdevices",
        "me//player",
        "",
    ],
)
async def test_relay_refuses_paths_outside_the_web_api(rig: Rig, path: str) -> None:
    headers = await agent_headers(rig)
    resp = await rig.client.get(f"/api/watch/spotify/{path}", headers=headers)
    assert resp.status_code in (400, 404, 307)
    assert [c for c in rig.fake.calls if c[1].startswith("/v1")] == []


async def test_relay_refuses_a_body_that_is_not_json(rig: Rig) -> None:
    headers = await agent_headers(rig)
    resp = await rig.client.post("/api/watch/spotify/me/player/next", content=b"{", headers=headers)
    assert resp.status_code == 400 and rig.fake.calls == []


async def test_relay_never_shows_the_token(rig: Rig, caplog: pytest.LogCaptureFixture) -> None:
    headers = await agent_headers(rig)
    caplog.set_level(logging.DEBUG)
    resp = await rig.client.get("/api/watch/spotify/me/player", headers=headers)
    await rig.client.get("/api/watch/spotify/playlists/nope", headers=headers)
    assert rig.fake.valid_access
    for token in rig.fake.valid_access:
        assert token not in str(resp.headers) and token not in resp.text
        assert token not in caplog.text


async def test_relay_without_a_spotify_login_answers_conflict(rig: Rig) -> None:
    headers = await agent_headers(rig)
    app_state_of(rig.app).accounts.disconnect()
    resp = await rig.client.get("/api/watch/spotify/me/player", headers=headers)
    assert resp.status_code == 409 and resp.json()["error"] == "spotify_auth"


async def test_key_scope_is_chosen_on_creation_and_changeable(rig: Rig) -> None:
    await rig.login_ui()
    created = (
        await rig.client.post("/api/ui/keys", json={"name": "scripts", "scope": "agent"})
    ).json()
    assert created["scope"] == "agent"
    plain = {"Authorization": f"Bearer {created['key']}"}
    assert (await rig.client.get("/api/watch/spotify/me/player", headers=plain)).status_code == 200

    other = (await rig.client.post("/api/ui/keys", json={"name": "fenix"})).json()
    assert other["scope"] == "watch"
    listing = {k["id"]: k["scope"] for k in (await rig.client.get("/api/ui/keys")).json()["keys"]}
    assert listing[created["id"]] == "agent" and listing[other["id"]] == "watch"

    other_headers = {"Authorization": f"Bearer {other['key']}"}
    url = "/api/watch/spotify/me/player"
    assert (await rig.client.get(url, headers=other_headers)).status_code == 403
    patched = await rig.client.patch(f"/api/ui/keys/{other['id']}", json={"scope": "agent"})
    assert patched.status_code == 200
    assert (await rig.client.get(url, headers=other_headers)).status_code == 200
    await rig.client.patch(f"/api/ui/keys/{other['id']}", json={"scope": "watch"})
    assert (await rig.client.get(url, headers=other_headers)).status_code == 403


async def test_scope_changes_need_a_valid_scope_and_an_active_key(rig: Rig) -> None:
    await rig.login_ui()
    made = (await rig.client.post("/api/ui/keys", json={"name": "x"})).json()
    assert (
        await rig.client.post("/api/ui/keys", json={"name": "y", "scope": "root"})
    ).status_code == 422
    bad = await rig.client.patch(f"/api/ui/keys/{made['id']}", json={"scope": "root"})
    assert bad.status_code == 422
    await rig.client.delete(f"/api/ui/keys/{made['id']}", headers={"X-Baton-Request": "1"})
    gone = await rig.client.patch(f"/api/ui/keys/{made['id']}", json={"scope": "agent"})
    assert gone.status_code == 404
    missing = await rig.client.patch("/api/ui/keys/nothing", json={"scope": "agent"})
    assert missing.status_code == 404


async def test_scope_change_requires_a_ui_session(rig: Rig) -> None:
    resp = await rig.client.patch("/api/ui/keys/abc", json={"scope": "agent"}, headers=rig.watch)
    assert resp.status_code == 401


def test_keys_from_before_scopes_stay_watch_keys(tmp_path: Path) -> None:
    db = sqlite3.connect(tmp_path / "baton.db")
    db.executescript(
        "CREATE TABLE watch_keys (id TEXT PRIMARY KEY, name TEXT NOT NULL, hint TEXT NOT NULL,"
        " key_hash TEXT NOT NULL UNIQUE, created_at REAL NOT NULL, last_used_at REAL,"
        " revoked_at REAL);"
    )
    import hashlib

    db.execute(
        "INSERT INTO watch_keys VALUES ('k1', 'old', 'bk_ab', ?, 1.0, NULL, NULL)",
        (hashlib.sha256(b"bk_old").hexdigest(),),
    )
    db.commit()
    db.close()
    store = Store(tmp_path, lambda: 100.0)
    assert store.verify_watch_key("bk_old") == "watch"
    assert [k.scope for k in store.list_watch_keys()] == ["watch"]
    store.close()
