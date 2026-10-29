"""The watch API contract: envelope, endpoints, idempotency, error codes, auth."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.conftest import Rig

ENVELOPE_KEYS = {"result", "error", "message", "state"}
STATE_KEYS = {
    "is_playing",
    "title",
    "artist",
    "progress_ms",
    "duration_ms",
    "liked",
    "in_playlist",
    "playlist_name",
    "device_name",
    "server_time_ms",
}
# Added after the first release; clients written against the original state object ignore it.
STATE_ADDITIONS = {"track_id"}
T0, T1, T2 = "spotify:track:t0", "spotify:track:t1", "spotify:track:t2"


async def call(rig: Rig, method: str, path: str) -> dict[str, Any]:
    """Call a watch route and check the parts of the contract every answer shares."""
    resp = await rig.client.request(method, f"/api/watch/{path}", headers=rig.watch)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert len(resp.content) < 2048
    body: dict[str, Any] = resp.json()
    assert body.keys() >= ENVELOPE_KEYS
    if body["state"] is not None:
        assert set(body["state"]) == STATE_KEYS | STATE_ADDITIONS
    return body


def current_track(rig: Rig, uri: str) -> None:
    rig.fake.index = rig.fake.queue.index(uri)


async def test_state_shape_and_values(rig: Rig) -> None:
    current_track(rig, T2)
    body = await call(rig, "GET", "state")
    assert body["result"] == "ok" and body["error"] is None
    state = body["state"]
    assert state["is_playing"] is True
    assert (state["title"], state["artist"]) == ("Teardrop", "Massive Attack")
    assert state["progress_ms"] == 83000 and state["duration_ms"] == 330000
    assert state["liked"] is False
    assert state["in_playlist"] is True
    assert state["playlist_name"] == "My Shazam"
    assert state["device_name"] == "Alex's iPhone"
    assert state["server_time_ms"] == int(rig.clock() * 1000)
    assert state["track_id"] == "t2"


async def test_state_without_active_device_is_ok_and_empty(rig: Rig) -> None:
    rig.fake.active_device = None
    body = await call(rig, "GET", "state")
    assert body["result"] == "ok"
    assert body["state"]["is_playing"] is False and body["state"]["title"] is None
    assert body["state"]["liked"] is None and body["state"]["in_playlist"] is None


# play / pause / next / previous ---------------------------------------------------------


async def test_play_pause_toggles(rig: Rig) -> None:
    body = await call(rig, "POST", "play-pause")
    assert body["result"] == "ok" and body["state"]["is_playing"] is False
    assert rig.fake.is_playing is False
    body = await call(rig, "POST", "play-pause")
    assert body["result"] == "ok" and body["state"]["is_playing"] is True
    assert rig.fake.is_playing is True


async def test_play_pause_without_device_starts_on_default_device(rig: Rig) -> None:
    rig.fake.active_device = None
    rig.fake.is_playing = False
    body = await call(rig, "POST", "play-pause")
    assert body["result"] == "ok"
    assert rig.fake.active_device == "kitchen-1" and rig.fake.is_playing is True
    assert body["state"]["device_name"] == "Kitchen speaker"


async def test_default_device_is_found_by_name_when_its_id_changed(rig: Rig) -> None:
    rig.settings(default_device=("stale-id", "kitchen SPEAKER"))
    rig.fake.active_device = None
    body = await call(rig, "POST", "play-pause")
    assert body["result"] == "ok" and rig.fake.active_device == "kitchen-1"


async def test_play_pause_without_device_and_unreachable_default(rig: Rig) -> None:
    rig.fake.active_device = None
    rig.settings(default_device=("gone", "Garage"))
    body = await call(rig, "POST", "play-pause")
    assert (body["result"], body["error"]) == ("error", "no_device")


async def test_play_pause_without_device_and_no_default(rig: Rig) -> None:
    rig.fake.active_device = None
    rig.settings(default_device=None)
    body = await call(rig, "POST", "play-pause")
    assert body["error"] == "no_device"


async def test_next(rig: Rig) -> None:
    body = await call(rig, "POST", "next")
    assert body["result"] == "ok" and body["state"]["title"] == "Heroes"


async def test_next_without_device(rig: Rig) -> None:
    rig.fake.active_device = None
    assert (await call(rig, "POST", "next"))["error"] == "no_device"


@pytest.mark.parametrize(("progress", "restarts"), [(5001, True), (5000, False), (0, False)])
async def test_previous_five_second_rule(rig: Rig, progress: int, restarts: bool) -> None:
    current_track(rig, T1)
    rig.fake.progress_ms = progress
    body = await call(rig, "POST", "previous")
    assert body["result"] == "ok"
    if restarts:
        assert rig.fake.queue[rig.fake.index] == T1 and rig.fake.progress_ms == 0
        assert rig.fake.calls_to("PUT", "/v1/me/player/seek") == [{"position_ms": "0"}]
        assert not rig.fake.calls_to("POST", "/v1/me/player/previous")
        assert body["state"]["title"] == "Heroes"
    else:
        assert rig.fake.queue[rig.fake.index] == T0
        assert not rig.fake.calls_to("PUT", "/v1/me/player/seek")
        assert body["state"]["title"] == "Blue Monday"


async def test_previous_without_device(rig: Rig) -> None:
    rig.fake.active_device = None
    assert (await call(rig, "POST", "previous"))["error"] == "no_device"


# like / unlike --------------------------------------------------------------------------


async def test_like_is_idempotent_and_never_a_toggle(rig: Rig) -> None:
    current_track(rig, T0)
    first = await call(rig, "POST", "like")
    assert first["result"] == "ok" and first["state"]["liked"] is True
    second = await call(rig, "POST", "like")
    assert second["result"] == "already" and second["state"]["liked"] is True
    assert rig.fake.liked.count(T0) == 1
    assert len(rig.fake.calls_to("PUT", "/v1/me/library")) == 1


async def test_like_of_already_liked_track_does_not_write(rig: Rig) -> None:
    current_track(rig, T1)
    body = await call(rig, "POST", "like")
    assert body["result"] == "already"
    assert not rig.fake.calls_to("PUT", "/v1/me/library")


async def test_unlike_is_idempotent(rig: Rig) -> None:
    current_track(rig, T1)
    first = await call(rig, "POST", "unlike")
    assert first["result"] == "ok" and first["state"]["liked"] is False
    second = await call(rig, "POST", "unlike")
    assert second["result"] == "already"
    assert len(rig.fake.calls_to("DELETE", "/v1/me/library")) == 1


# playlist -------------------------------------------------------------------------------


async def test_playlist_add_is_idempotent_without_duplicates(rig: Rig) -> None:
    current_track(rig, T0)
    first = await call(rig, "POST", "playlist/add")
    assert first["result"] == "ok" and first["state"]["in_playlist"] is True
    second = await call(rig, "POST", "playlist/add")
    assert second["result"] == "already"
    assert rig.fake.playlists["pl1"].items.count(T0) == 1


async def test_playlist_add_of_member_does_not_write(rig: Rig) -> None:
    current_track(rig, T2)
    assert (await call(rig, "POST", "playlist/add"))["result"] == "already"
    assert not rig.fake.calls_to("POST", "/v1/playlists/pl1/items")


async def test_playlist_remove_is_idempotent(rig: Rig) -> None:
    current_track(rig, T2)
    first = await call(rig, "POST", "playlist/remove")
    assert first["result"] == "ok" and first["state"]["in_playlist"] is False
    assert rig.fake.playlists["pl1"].items == []
    assert (await call(rig, "POST", "playlist/remove"))["result"] == "already"
    assert len(rig.fake.calls_to("DELETE", "/v1/playlists/pl1/items")) == 1


async def test_membership_check_reads_every_page(rig: Rig) -> None:
    rig.fake.playlists["pl1"].items = [f"spotify:track:x{i}" for i in range(120)] + [T0]
    current_track(rig, T0)
    assert (await call(rig, "POST", "playlist/add"))["result"] == "already"


async def test_playlist_membership_cache_follows_snapshot(rig: Rig) -> None:
    current_track(rig, T0)
    await call(rig, "GET", "state")
    pages = len(rig.fake.calls_to("GET", "/v1/playlists/pl1/items"))
    await call(rig, "GET", "state")
    assert len(rig.fake.calls_to("GET", "/v1/playlists/pl1/items")) == pages
    rig.fake.playlists["pl1"].items.append(T0)
    rig.fake.playlists["pl1"].touch()
    assert (await call(rig, "GET", "state"))["state"]["in_playlist"] is True


async def test_playlist_without_target(rig: Rig) -> None:
    rig.settings(target_playlist=None)
    body = await call(rig, "POST", "playlist/add")
    assert body["error"] == "no_target_playlist" and body["state"]["playlist_name"] is None


# error codes ----------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["like", "unlike", "playlist/add", "playlist/remove"])
async def test_nothing_playing_is_no_track(rig: Rig, path: str) -> None:
    rig.fake.active_device = None
    assert (await call(rig, "POST", path))["error"] == "no_track"


@pytest.mark.parametrize("path", ["like", "unlike", "playlist/add", "playlist/remove"])
async def test_episode_is_no_track_and_state_shows_it(rig: Rig, path: str) -> None:
    rig.fake.episode_playing = True
    body = await call(rig, "POST", path)
    assert body["error"] == "no_track"
    assert body["state"]["title"] == "Episode 1" and body["state"]["liked"] is None


async def test_not_linked_is_spotify_auth(make_rig) -> None:  # type: ignore[no-untyped-def]
    rig = make_rig()
    body = await call(rig, "GET", "state")
    assert (body["result"], body["error"], body["state"]) == ("error", "spotify_auth", None)


async def test_revoked_spotify_login_is_spotify_auth(rig: Rig) -> None:
    rig.fake.refresh_token = "rotated-elsewhere"
    body = await call(rig, "POST", "next")
    assert body["error"] == "spotify_auth"


async def test_rate_limit(rig: Rig) -> None:
    rig.fake.fail("GET /v1/me/player", 429, headers={"Retry-After": "7"})
    body = await call(rig, "GET", "state")
    assert body["error"] == "spotify_rate_limited" and "7" in body["message"]


async def test_spotify_server_error(rig: Rig) -> None:
    rig.fake.fail("POST /v1/me/player/next", 503, {"error": {"status": 503, "message": "down"}})
    body = await call(rig, "POST", "next")
    assert body["error"] == "spotify_error" and "503" in body["message"]


async def test_spotify_forbidden_is_spotify_error(rig: Rig) -> None:
    rig.fake.fail("POST /v1/me/player/next", 403)
    assert (await call(rig, "POST", "next"))["error"] == "spotify_error"


async def test_expired_access_token_is_refreshed_and_retried(rig: Rig) -> None:
    await call(rig, "GET", "state")
    rig.fake.valid_access.clear()
    assert (await call(rig, "GET", "state"))["result"] == "ok"


@pytest.mark.parametrize(("mode", "ok"), [("shuffle", True), ("normal", True), ("smart", True)])
async def test_play_playlist_modes(rig: Rig, mode: str, ok: bool) -> None:
    rig.fake.shuffle = mode == "normal"
    body = await call(rig, "POST", f"playlists/pl2/play?mode={mode}")
    assert body["result"] == "ok"
    assert rig.fake.context == "spotify:playlist:pl2"
    assert rig.fake.shuffle is (mode != "normal")
    assert rig.fake.queue == ["spotify:track:t0", "spotify:track:t3"]
    if mode == "smart":
        assert "not available" in body["message"] and "shuffle" in body["message"]
    else:
        assert body["message"] is None


async def test_play_playlist_defaults_to_normal(rig: Rig) -> None:
    rig.fake.shuffle = True
    await call(rig, "POST", "playlists/pl2/play")
    assert rig.fake.shuffle is False


async def test_play_playlist_without_device_uses_default_device(rig: Rig) -> None:
    rig.fake.active_device = None
    body = await call(rig, "POST", "playlists/pl3/play?mode=shuffle")
    assert body["result"] == "ok" and rig.fake.active_device == "kitchen-1"


@pytest.mark.parametrize("path", ["playlists/pl2/play?mode=chaos", "playlists/bad..id/play"])
async def test_play_playlist_bad_request(rig: Rig, path: str) -> None:
    assert (await call(rig, "POST", path))["error"] == "bad_request"


async def test_recent_playlists_dedupe_cache_and_limit(rig: Rig) -> None:
    body = await call(rig, "GET", "playlists")
    assert body["result"] == "ok" and body["state"] is None
    assert body["playlists"] == [
        {"id": "pl2", "name": "Cycling"},
        {"id": "pl1", "name": "My Shazam"},
        {"id": "pl3", "name": "Sunday morning"},
    ]
    calls = len(rig.fake.calls)
    await call(rig, "GET", "playlists")
    assert len(rig.fake.calls) == calls
    rig.clock.t += 121
    rig.fake.recent_contexts = ["pl3"]
    again = await call(rig, "GET", "playlists")
    assert [p["id"] for p in again["playlists"]] == ["pl3"]
    assert len([c for c in rig.fake.calls if c[1] == "/v1/playlists/pl3"]) == 1


async def test_recent_playlists_limit_is_fifteen(rig: Rig) -> None:
    for i in range(30):
        from tests.fake_spotify import FakePlaylist

        rig.fake.playlists[f"p{i}"] = FakePlaylist(f"p{i}", f"List {i}")
    rig.fake.recent_contexts = [f"p{i}" for i in range(30)]
    assert len((await call(rig, "GET", "playlists"))["playlists"]) == 15


async def test_recent_playlist_with_unknown_name_still_listed(rig: Rig) -> None:
    rig.fake.recent_contexts = ["editorial1"]
    body = await call(rig, "GET", "playlists")
    assert body["playlists"] == [{"id": "editorial1", "name": "Unnamed playlist"}]


# authentication -------------------------------------------------------------------------


@pytest.mark.parametrize("header", [None, "Bearer wrong", "Bearer ", "Basic abc", "bk_nope"])
async def test_bad_key_is_401(rig: Rig, header: str | None) -> None:
    headers = {"Authorization": header} if header is not None else {}
    resp = await rig.client.get("/api/watch/state", headers=headers)
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("application/json")
    assert json.loads(resp.content)["result"] == "error"
    assert rig.fake.calls == []


async def test_every_watch_route_requires_the_key(rig: Rig) -> None:
    from baton import routes_watch

    routes = [(r.path, m) for r in routes_watch.router.routes for m in r.methods]  # type: ignore[attr-defined]
    assert len(routes) == 10
    for path, method in routes:
        resp = await rig.client.request(method, path.replace("{playlist_id}", "pl1"))
        assert resp.status_code == 401, (method, path)


async def test_revoked_key_is_rejected(rig: Rig) -> None:
    from tests.conftest import app_state_of

    store = app_state_of(rig.app).store
    key_id = store.list_watch_keys()[0].id
    assert (await rig.watch_get("state")).status_code == 200
    store.revoke_watch_key(key_id)
    assert (await rig.watch_get("state")).status_code == 401


async def test_success_resets_failure_count(rig: Rig) -> None:
    for _ in range(9):
        await rig.client.get("/api/watch/state", headers={"Authorization": "Bearer x"})
    assert (await rig.watch_get("state")).status_code == 200
    for _ in range(9):
        await rig.client.get("/api/watch/state", headers={"Authorization": "Bearer x"})
    assert (await rig.watch_get("state")).status_code == 200
