"""Runtime settings and watch keys: stored in the database, changed through the API."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import httpx

from baton.app import create_app
from baton.config import load_config
from tests.conftest import Rig, app_state_of, base_env
from tests.fake_spotify import create_fake_spotify

XHDR = {"X-Baton-Request": "1"}


async def test_target_playlist_round_trip_stores_name(rig: Rig) -> None:
    await rig.login_ui()
    pickable = (await rig.client.get("/api/ui/spotify/playlists")).json()["playlists"]
    assert {"id": "pl2", "name": "Cycling"} in pickable
    resp = await rig.client.put("/api/ui/settings", json={"target_playlist_id": "pl2"})
    assert resp.status_code == 200
    assert resp.json()["target_playlist"] == {"id": "pl2", "name": "Cycling"}
    assert (await rig.client.get("/api/ui/settings")).json()["target_playlist"]["name"] == "Cycling"
    state = (await rig.watch_get("state")).json()["state"]
    assert state["playlist_name"] == "Cycling"
    cleared = await rig.client.put("/api/ui/settings", json={"target_playlist_id": None})
    assert cleared.json()["target_playlist"] is None


async def test_unknown_target_playlist_is_rejected_and_nothing_changes(rig: Rig) -> None:
    await rig.login_ui()
    resp = await rig.client.put("/api/ui/settings", json={"target_playlist_id": "missing"})
    assert resp.status_code >= 400
    assert app_state_of(rig.app).store.get_settings().target_playlist.name == "My Shazam"


async def test_default_device_round_trip_stores_name_and_id(rig: Rig) -> None:
    await rig.login_ui()
    listed = (await rig.client.get("/api/ui/spotify/devices")).json()["devices"]
    assert {d["id"] for d in listed} == {"phone-1", "kitchen-1"}
    resp = await rig.client.put("/api/ui/settings", json={"default_device_id": "phone-1"})
    assert resp.json()["default_device"] == {"id": "phone-1", "name": "Alex's iPhone"}
    bad = await rig.client.put("/api/ui/settings", json={"default_device_id": "nope"})
    assert bad.status_code == 400
    assert app_state_of(rig.app).store.get_settings().default_device.id == "phone-1"


async def test_partial_update_keeps_other_settings(rig: Rig) -> None:
    await rig.login_ui()
    resp = await rig.client.put("/api/ui/settings", json={"market": "de"})
    body = resp.json()
    assert body["market"] == "DE" and body["target_playlist"]["id"] == "pl1"
    assert body["default_device"]["id"] == "kitchen-1"
    bad = await rig.client.put("/api/ui/settings", json={"market": "Germany"})
    assert bad.status_code == 422


async def test_market_setting_is_sent_to_spotify(rig: Rig) -> None:
    await rig.watch_get("state")
    assert rig.fake.calls_to("GET", "/v1/me/player")[0]["market"] == "from_token"
    await rig.login_ui()
    await rig.client.put("/api/ui/settings", json={"market": "DE"})
    await rig.watch_get("state")
    assert rig.fake.calls_to("GET", "/v1/me/player")[-1]["market"] == "DE"


async def test_saving_the_page_settings_leaves_the_market_alone(rig: Rig) -> None:
    await rig.login_ui()
    await rig.client.put("/api/ui/settings", json={"market": "DE"})
    body = {"target_playlist_id": "pl2", "default_device_id": "phone-1"}
    resp = await rig.client.put("/api/ui/settings", json=body)
    assert resp.json()["market"] == "DE"


async def test_page_has_no_market_field(rig: Rig) -> None:
    await rig.login_ui()
    page = (await rig.client.get("/")).text
    script = (await rig.client.get("/static/app.js")).text
    assert "market" not in page.lower() and "market" not in script.lower()


async def test_device_list_shows_a_device_that_appears_later(rig: Rig) -> None:
    await rig.login_ui()
    first = (await rig.client.get("/api/ui/spotify/devices")).json()["devices"]
    rig.fake.devices.append({"id": "ph-2", "name": "Fresh iPhone", "type": "Smartphone"})
    again = (await rig.client.get("/api/ui/spotify/devices")).json()["devices"]
    assert [d["id"] for d in again] == [d["id"] for d in first] + ["ph-2"]


async def test_settings_survive_a_restart(rig: Rig, tmp_path: Path) -> None:
    await rig.login_ui()
    await rig.client.put("/api/ui/settings", json={"target_playlist_id": "pl3"})
    app_state_of(rig.app).store.close()
    second = create_app(
        load_config(base_env(tmp_path / "data")),
        transport=httpx.ASGITransport(app=create_fake_spotify(rig.fake)),
        now=rig.clock,
    )
    assert app_state_of(second).store.get_settings().target_playlist.id == "pl3"
    app_state_of(second).store.close()


async def test_runtime_settings_are_not_configuration() -> None:
    from importlib import resources

    import yaml

    keys = set(yaml.safe_load(resources.files("baton").joinpath("default_config.yaml").read_text()))
    assert not keys & {"target_playlist", "default_device", "market", "watch_key", "watch_keys"}


async def test_watch_key_lifecycle(rig: Rig) -> None:
    await rig.login_ui()
    created = (await rig.client.post("/api/ui/keys", json={"name": "fenix"})).json()
    plain = created["key"]
    assert plain.startswith("bk_") and len(plain) > 40
    headers = {"Authorization": f"Bearer {plain}"}
    assert (await rig.client.get("/api/watch/state", headers=headers)).status_code == 200

    listing = (await rig.client.get("/api/ui/keys")).json()["keys"]
    entry = next(k for k in listing if k["id"] == created["id"])
    assert entry["name"] == "fenix" and entry["last_used_at"] is not None and not entry["revoked"]
    assert plain not in str(listing) and "hash" not in str(listing)

    assert (
        await rig.client.delete(f"/api/ui/keys/{created['id']}", headers=XHDR)
    ).status_code == 200
    assert (await rig.client.get("/api/watch/state", headers=headers)).status_code == 401
    assert (
        await rig.client.delete(f"/api/ui/keys/{created['id']}", headers=XHDR)
    ).status_code == 404
    revoked = next(
        k for k in (await rig.client.get("/api/ui/keys")).json()["keys"] if k["id"] == created["id"]
    )
    assert revoked["revoked"] is True


async def test_only_the_hash_of_a_key_is_stored(rig: Rig, tmp_path: Path) -> None:
    await rig.login_ui()
    plain = (await rig.client.post("/api/ui/keys", json={"name": "x"})).json()["key"]
    path = tmp_path / "data" / "baton.db"
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    db = sqlite3.connect(path)
    dump = "\n".join(db.iterdump())
    db.close()
    assert plain not in dump and plain.removeprefix("bk_") not in dump


async def test_key_name_is_required(rig: Rig) -> None:
    await rig.login_ui()
    assert (await rig.client.post("/api/ui/keys", json={"name": ""})).status_code == 422


async def test_saved_playlists_round_trip_and_survive_other_changes(rig: Rig) -> None:
    await rig.login_ui()
    saved = [
        {"id": "37i9dQZF1EXAMPLEONE1", "name": " Daily Mix 1 "},
        {"id": "5Pplaylist", "name": "Feel Good Indie"},
        {"id": "5Pplaylist", "name": "Feel Good Indie again"},
    ]
    resp = await rig.client.put("/api/ui/settings", json={"saved_playlists": saved})
    assert resp.status_code == 200
    assert resp.json()["saved_playlists"] == [
        {"id": "37i9dQZF1EXAMPLEONE1", "name": "Daily Mix 1"},
        {"id": "5Pplaylist", "name": "Feel Good Indie again"},
    ]
    other = await rig.client.put("/api/ui/settings", json={"market": "de"})
    assert len(other.json()["saved_playlists"]) == 2
    assert len((await rig.client.get("/api/ui/status")).json()["settings"]["saved_playlists"]) == 2
    names = [p["name"] for p in (await rig.watch_get("playlists")).json()["playlists"]]
    assert names[:3] == ["Liked Songs", "Daily Mix 1", "Feel Good Indie again"]
    cleared = await rig.client.put("/api/ui/settings", json={"saved_playlists": []})
    assert cleared.json()["saved_playlists"] == []


async def test_saved_playlists_are_validated(rig: Rig) -> None:
    await rig.login_ui()
    for bad in (
        [{"id": "bad..id", "name": "x"}],
        [{"id": "abc", "name": ""}],
        [{"id": f"p{i}", "name": "x"} for i in range(11)],
    ):
        resp = await rig.client.put("/api/ui/settings", json={"saved_playlists": bad})
        assert resp.status_code == 422
    assert app_state_of(rig.app).store.get_settings().saved_playlists == ()


async def test_settings_stored_before_saved_playlists_existed_still_load(rig: Rig) -> None:
    state = app_state_of(rig.app)
    state.store._exec(  # noqa: SLF001
        "UPDATE kv SET value = ? WHERE key = 'settings'",
        ('{"target_playlist": null, "default_device": null, "market": null}',),
    )
    assert state.store.get_settings().saved_playlists == ()


async def test_page_offers_saved_playlists(rig: Rig) -> None:
    await rig.login_ui()
    page = (await rig.client.get("/")).text
    script = (await rig.client.get("/static/app.js")).text
    assert 'id="saved-form"' in page and 'id="saved"' in page
    assert "saved_playlists" in script
