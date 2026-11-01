"""The watch API contract: envelope, endpoints, idempotency, error codes, auth."""

from __future__ import annotations

import json
from typing import Any

import pytest

from baton.db import Ref, SavedPlaylist
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
STATE_ADDITIONS = {"track_id", "playing_playlist_name", "in_playing_playlist"}
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


# playing playlist -----------------------------------------------------------------------

CYCLING = "pl20000000000000000000"


def plays_from(rig: Rig, playlist_id: str, suffix: str = "") -> None:
    rig.fake.context = f"spotify:playlist:{playlist_id}{suffix}"


async def test_state_reports_the_playing_playlist(rig: Rig) -> None:
    plays_from(rig, CYCLING, "?sessionId=1&mode=enhanced")
    state = (await call(rig, "GET", "state"))["state"]
    assert state["playing_playlist_name"] == "Cycling" and state["in_playing_playlist"] is True
    current_track(rig, T2)
    state = (await call(rig, "GET", "state"))["state"]
    assert state["playing_playlist_name"] == "Cycling" and state["in_playing_playlist"] is False


async def test_state_without_playing_playlist(rig: Rig) -> None:
    rig.fake.context = "spotify:album:a1"
    state = (await call(rig, "GET", "state"))["state"]
    assert state["playing_playlist_name"] is None and state["in_playing_playlist"] is None


async def test_playing_playlist_add_then_remove(rig: Rig) -> None:
    plays_from(rig, CYCLING)
    current_track(rig, T2)
    added = await call(rig, "POST", "playing-playlist/add")
    assert added["result"] == "ok" and added["message"] == "Added to Cycling"
    assert added["state"]["in_playing_playlist"] is True
    assert rig.fake.playlists[CYCLING].items.count(T2) == 1
    again = await call(rig, "POST", "playing-playlist/add")
    assert again["result"] == "already" and again["message"] == "Already in Cycling"
    assert rig.fake.playlists[CYCLING].items.count(T2) == 1
    removed = await call(rig, "POST", "playing-playlist/remove")
    assert removed["result"] == "ok" and removed["message"] == "Removed from Cycling"
    assert removed["state"]["in_playing_playlist"] is False
    assert T2 not in rig.fake.playlists[CYCLING].items
    gone = await call(rig, "POST", "playing-playlist/remove")
    assert gone["result"] == "already" and gone["message"] == "Not in Cycling"


async def test_playing_playlist_add_with_no_playlist_changes_nothing(rig: Rig) -> None:
    body = await call(rig, "POST", "playing-playlist/add")
    assert body["result"] == "error" and body["error"] == "no_playing_playlist"
    assert body["state"]["title"] is not None


@pytest.mark.parametrize("readable", [True, False])
async def test_playing_playlist_of_someone_else_is_refused(rig: Rig, readable: bool) -> None:
    rig.fake.playlists[CYCLING].owner = "someone-else"
    if not readable:
        rig.fake.fail(f"GET /v1/playlists/{CYCLING}", 404, times=1)
    plays_from(rig, CYCLING)
    current_track(rig, T2)
    state = (await call(rig, "GET", "state"))["state"]
    assert state["playing_playlist_name"] is None and state["in_playing_playlist"] is None
    body = await call(rig, "POST", "playing-playlist/add")
    assert body["error"] == "playlist_not_editable"
    assert not rig.fake.calls_to("POST", f"/v1/playlists/{CYCLING}/items")


async def test_collaborative_playlist_of_someone_else_is_editable(rig: Rig) -> None:
    rig.fake.playlists[CYCLING].owner = "someone-else"
    rig.fake.playlists[CYCLING].collaborative = True
    plays_from(rig, CYCLING)
    current_track(rig, T2)
    assert (await call(rig, "POST", "playing-playlist/add"))["result"] == "ok"


async def test_playing_playlist_add_is_refused_when_the_song_changed(rig: Rig) -> None:
    plays_from(rig, CYCLING)
    current_track(rig, T2)
    body = await call(rig, "POST", "playing-playlist/add?track=t1")
    assert body["error"] == "track_changed"
    assert T2 not in rig.fake.playlists[CYCLING].items


async def test_target_add_shows_when_the_target_is_playing(rig: Rig) -> None:
    plays_from(rig, "pl10000000000000000000")
    current_track(rig, T0)
    await call(rig, "GET", "state")
    body = await call(rig, "POST", "playlist/add")
    assert body["state"]["in_playlist"] is True and body["state"]["in_playing_playlist"] is True


async def test_membership_of_the_playing_playlist_is_looked_up_once_per_track(rig: Rig) -> None:
    plays_from(rig, CYCLING)
    await call(rig, "GET", "state")
    await call(rig, "GET", "state")
    assert len(rig.fake.calls_to("GET", f"/v1/playlists/{CYCLING}/items")) == 1


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
    assert rig.fake.playlists["pl10000000000000000000"].items.count(T0) == 1


async def test_playlist_add_of_member_does_not_write(rig: Rig) -> None:
    current_track(rig, T2)
    assert (await call(rig, "POST", "playlist/add"))["result"] == "already"
    assert not rig.fake.calls_to("POST", "/v1/playlists/pl10000000000000000000/items")


async def test_playlist_remove_is_idempotent(rig: Rig) -> None:
    current_track(rig, T2)
    first = await call(rig, "POST", "playlist/remove")
    assert first["result"] == "ok" and first["state"]["in_playlist"] is False
    assert rig.fake.playlists["pl10000000000000000000"].items == []
    assert (await call(rig, "POST", "playlist/remove"))["result"] == "already"
    assert len(rig.fake.calls_to("DELETE", "/v1/playlists/pl10000000000000000000/items")) == 1


async def test_membership_check_reads_every_page(rig: Rig) -> None:
    rig.fake.playlists["pl10000000000000000000"].items = [
        f"spotify:track:x{i}" for i in range(120)
    ] + [T0]
    current_track(rig, T0)
    assert (await call(rig, "POST", "playlist/add"))["result"] == "already"


async def test_playlist_membership_cache_follows_snapshot(rig: Rig) -> None:
    current_track(rig, T0)
    await call(rig, "GET", "state")
    pages = len(rig.fake.calls_to("GET", "/v1/playlists/pl10000000000000000000/items"))
    await call(rig, "GET", "state")
    assert len(rig.fake.calls_to("GET", "/v1/playlists/pl10000000000000000000/items")) == pages
    rig.fake.playlists["pl10000000000000000000"].items.append(T0)
    rig.fake.playlists["pl10000000000000000000"].touch()
    assert (await call(rig, "POST", "playlist/add"))["result"] == "already"


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


async def test_restart_seeks_to_the_start_wherever_the_track_is(rig: Rig) -> None:
    rig.fake.progress_ms = 1000
    assert (await call(rig, "POST", "restart"))["result"] == "ok"
    assert rig.fake.calls_to("PUT", "/v1/me/player/seek") == [{"position_ms": "0"}]
    assert not rig.fake.calls_to("POST", "/v1/me/player/previous")


async def test_previous_track_goes_back_wherever_the_track_is(rig: Rig) -> None:
    rig.fake.progress_ms = 60000
    assert (await call(rig, "POST", "previous-track"))["result"] == "ok"
    assert rig.fake.calls_to("POST", "/v1/me/player/previous")
    assert not rig.fake.calls_to("PUT", "/v1/me/player/seek")


async def test_rate_limit(rig: Rig) -> None:
    rig.fake.fail("GET /v1/me/player", 429, headers={"Retry-After": "70"})
    body = await call(rig, "GET", "state")
    assert body["error"] == "spotify_rate_limited" and "70" in body["message"]


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
    body = await call(rig, "POST", f"playlists/pl20000000000000000000/play?mode={mode}")
    assert body["result"] == "ok"
    assert rig.fake.context == "spotify:playlist:pl20000000000000000000"
    assert rig.fake.shuffle is (mode != "normal")
    assert rig.fake.queue == ["spotify:track:t0", "spotify:track:t3"]
    if mode == "smart":
        assert "not available" in body["message"] and "shuffle" in body["message"]
    else:
        assert body["message"] is None


async def test_play_playlist_defaults_to_normal(rig: Rig) -> None:
    rig.fake.shuffle = True
    await call(rig, "POST", "playlists/pl20000000000000000000/play")
    assert rig.fake.shuffle is False


async def test_play_playlist_without_device_uses_default_device(rig: Rig) -> None:
    rig.fake.active_device = None
    body = await call(rig, "POST", "playlists/pl30000000000000000000/play?mode=shuffle")
    assert body["result"] == "ok" and rig.fake.active_device == "kitchen-1"


@pytest.mark.parametrize(
    "path", ["playlists/pl20000000000000000000/play?mode=chaos", "playlists/bad..id/play"]
)
async def test_play_playlist_bad_request(rig: Rig, path: str) -> None:
    assert (await call(rig, "POST", path))["error"] == "bad_request"


LIKED = {"id": "liked", "name": "Liked Songs"}


async def recent_entries(rig: Rig) -> list[dict[str, str]]:
    """The playlists answer without its leading Liked Songs entry."""
    body = await call(rig, "GET", "playlists")
    assert body["playlists"][0] == LIKED
    entries: list[dict[str, str]] = body["playlists"][1:]
    return entries


async def test_recent_playlists_dedupe_cache_and_limit(rig: Rig) -> None:
    body = await call(rig, "GET", "playlists")
    assert body["result"] == "ok" and body["state"] is None
    assert body["playlists"] == [
        LIKED,
        {"id": "pl20000000000000000000", "name": "Cycling"},
        {"id": "pl10000000000000000000", "name": "My Shazam"},
        {"id": "pl30000000000000000000", "name": "Sunday morning"},
    ]
    calls = len(rig.fake.calls)
    await call(rig, "GET", "playlists")
    assert len(rig.fake.calls) == calls
    rig.clock.t += 301
    rig.fake.recent_contexts = ["pl30000000000000000000"]
    assert [p["id"] for p in await recent_entries(rig)] == ["pl30000000000000000000"]
    assert len([c for c in rig.fake.calls if c[1] == "/v1/playlists/pl30000000000000000000"]) == 1


async def test_recent_playlists_limit_is_ten(rig: Rig) -> None:
    for i in range(30):
        from tests.fake_spotify import FakePlaylist

        rig.fake.playlists[f"p{i}"] = FakePlaylist(f"p{i}", f"List {i}")
    rig.fake.recent_contexts = [f"p{i}" for i in range(30)]
    assert [p["id"] for p in await recent_entries(rig)] == [f"p{i}" for i in range(10)]


async def test_recent_playlists_leave_out_ones_that_cannot_be_named(rig: Rig) -> None:
    rig.fake.recent_contexts = ["editorial1", "pl10000000000000000000", "editorial2"]
    assert await recent_entries(rig) == [{"id": "pl10000000000000000000", "name": "My Shazam"}]
    asked = len(rig.fake.calls_to("GET", "/v1/playlists/editorial1"))
    rig.clock.t += 121
    await call(rig, "GET", "playlists")
    assert len(rig.fake.calls_to("GET", "/v1/playlists/editorial1")) == asked
    rig.clock.t += 3600
    await call(rig, "GET", "playlists")
    assert len(rig.fake.calls_to("GET", "/v1/playlists/editorial1")) == asked + 1


async def test_recent_playlists_fill_up_past_unnamable_ones(rig: Rig) -> None:
    from tests.fake_spotify import FakePlaylist

    for i in range(20):
        rig.fake.playlists[f"p{i}"] = FakePlaylist(f"p{i}", f"List {i}")
    rig.fake.recent_contexts = ["gone1", "gone2", *[f"p{i}" for i in range(20)]]
    assert [p["id"] for p in await recent_entries(rig)] == [f"p{i}" for i in range(10)]


async def test_recent_playlist_played_with_smart_shuffle_is_the_same_playlist(rig: Rig) -> None:
    rig.fake.recent_contexts = [
        "spotify:playlist:pl20000000000000000000?sessionId=1&mode=enhanced",
        "spotify:playlist:pl20000000000000000000?sessionId=2&mode=enhanced",
        "spotify:user:alex:playlist:pl20000000000000000000",
        "pl20000000000000000000",
        "pl30000000000000000000",
    ]
    assert await recent_entries(rig) == [
        {"id": "pl20000000000000000000", "name": "Cycling"},
        {"id": "pl30000000000000000000", "name": "Sunday morning"},
    ]
    assert len(rig.fake.calls_to("GET", "/v1/playlists/pl20000000000000000000")) == 1


async def test_unreadable_spotify_mix_is_listed_with_a_track_as_its_label(rig: Rig) -> None:
    rig.fake.recent_contexts = [
        "37i9dQZF1EXAMPLEONE100",
        "pl10000000000000000000",
        "37i9dQZF1EXAMPLETWO200",
    ]
    assert await recent_entries(rig) == [
        {"id": "37i9dQZF1EXAMPLEONE100", "name": "Spotify mix (Blue Monday)"},
        {"id": "pl10000000000000000000", "name": "My Shazam"},
        {"id": "37i9dQZF1EXAMPLETWO200", "name": "Spotify mix (Blue Monday)"},
    ]


NOW = 1_800_000_000.0
MIX = "37i9dQZF1EXAMPLEONE100"
CYCLING, SHAZAM, SUNDAY = (f"pl{n}0000000000000000000" for n in (2, 1, 3))


async def listed_ids(rig: Rig) -> list[str]:
    """Ids of the playlists answer, Liked Songs left out."""
    return [p["id"] for p in await recent_entries(rig)]


async def test_playlists_follow_last_use_whether_saved_or_not(rig: Rig) -> None:
    rig.fake.recent_contexts = [CYCLING, SHAZAM, SUNDAY]
    rig.fake.recent_times = [NOW - 600, NOW - 3000, NOW - 9000]
    rig.settings(saved_playlists=(SavedPlaylist(MIX, "Daily Mix 1", NOW - 5000),))
    assert await listed_ids(rig) == [CYCLING, SHAZAM, MIX, SUNDAY]


async def test_saved_playlist_never_played_ranks_by_the_time_it_was_added(rig: Rig) -> None:
    rig.fake.recent_contexts = [CYCLING, SUNDAY]
    rig.fake.recent_times = [NOW - 600, NOW - 9000]
    rig.settings(
        saved_playlists=(
            SavedPlaylist("s1", "Added today", NOW - 60),
            SavedPlaylist("s2", "Old", 1.0),
        )
    )
    assert await listed_ids(rig) == ["s1", CYCLING, SUNDAY, "s2"]


async def test_saved_playlist_from_before_adding_was_timed_sorts_last(rig: Rig) -> None:
    rig.fake.recent_contexts = [CYCLING]
    rig.settings(saved_playlists=(SavedPlaylist("s1", "Untimed", 0.0),))
    assert await listed_ids(rig) == [CYCLING, "s1"]


async def test_a_playlist_started_here_moves_up_before_spotify_reports_it(rig: Rig) -> None:
    rig.fake.recent_contexts = [CYCLING, SHAZAM, SUNDAY]
    assert await listed_ids(rig) == [CYCLING, SHAZAM, SUNDAY]
    rig.clock.t += 30
    await call(rig, "POST", f"playlists/{SUNDAY}/play")
    assert await listed_ids(rig) == [SUNDAY, CYCLING, SHAZAM]
    await call(rig, "POST", "playlists/liked/play")
    assert await listed_ids(rig) == [SUNDAY, CYCLING, SHAZAM]


async def test_hidden_playlists_are_left_out_and_the_list_fills_up(rig: Rig) -> None:
    from tests.fake_spotify import FakePlaylist

    for i in range(12):
        rig.fake.playlists[f"p{i}"] = FakePlaylist(f"p{i}", f"List {i}")
    rig.fake.recent_contexts = [f"p{i}" for i in range(12)]
    rig.settings(hidden_playlists=(Ref("p0", "List 0"), Ref("p3", "List 3")))
    assert await listed_ids(rig) == [f"p{i}" for i in (1, 2, 4, 5, 6, 7, 8, 9, 10, 11)]


async def test_a_rename_beats_the_name_of_a_mix_and_of_a_saved_playlist(rig: Rig) -> None:
    rig.fake.recent_contexts = [MIX, CYCLING]
    rig.settings(
        saved_playlists=(SavedPlaylist(CYCLING, "Saved name", NOW),),
        playlist_names={MIX: "Daily Mix 1", CYCLING: "Bike"},
    )
    assert await recent_entries(rig) == [
        {"id": CYCLING, "name": "Bike"},
        {"id": MIX, "name": "Daily Mix 1"},
    ]


async def test_watch_entries_carry_nothing_but_id_and_name(rig: Rig) -> None:
    rig.settings(
        saved_playlists=(SavedPlaylist("s1", "Saved", NOW),),
        hidden_playlists=(Ref(SUNDAY, "Sunday morning"),),
    )
    body = await call(rig, "GET", "playlists")
    assert body["playlists"] and all(set(p) == {"id", "name"} for p in body["playlists"])
    assert set(body) == ENVELOPE_KEYS | {"playlists"}


async def test_page_list_says_what_it_needs_to_manage_entries(rig: Rig) -> None:
    from tests.fake_spotify import FakePlaylist

    for i in range(12):
        rig.fake.playlists[f"p{i}"] = FakePlaylist(f"p{i}", f"List {i}")
    rig.fake.recent_contexts = [f"p{i}" for i in range(12)]
    rig.settings(
        saved_playlists=(SavedPlaylist("old", "Old save", 1.0),),
        playlist_names={"p1": "First"},
        hidden_playlists=(Ref("p5", "List 5"),),
    )
    await rig.login_ui()
    body = (await rig.client.get("/api/ui/playlists/recent")).json()
    assert body["playlists"][0] == {"id": "liked", "name": "Liked Songs", "fixed": True}
    shown = {p["id"]: p for p in body["playlists"][1:]}
    assert len(shown) == 10 and "p5" not in shown
    assert shown["p1"] == {
        "id": "p1",
        "name": "First",
        "original": "List 1",
        "saved": False,
        "hidden": False,
    }
    assert body["more"] == [
        {"id": "old", "name": "Old save", "original": "Old save", "saved": True, "hidden": False},
        {"id": "p5", "name": "List 5", "original": "List 5", "saved": False, "hidden": True},
    ]


async def test_list_is_liked_songs_and_at_most_ten_more(rig: Rig) -> None:
    from tests.fake_spotify import FakePlaylist

    for i in range(30):
        rig.fake.playlists[f"p{i}"] = FakePlaylist(f"p{i}", f"List {i}")
    rig.fake.recent_contexts = [f"p{i}" for i in range(30)]
    rig.settings(
        saved_playlists=tuple(SavedPlaylist(f"s{i}", f"Saved {i}", NOW - 60 * i) for i in range(10))
    )
    ids = [p["id"] for p in (await call(rig, "GET", "playlists"))["playlists"]]
    assert len(ids) == 11 and ids[0] == "liked"


@pytest.mark.parametrize(("mode", "shuffled"), [("normal", False), ("shuffle", True)])
async def test_liked_songs_start_by_their_collection_context(
    rig: Rig, mode: str, shuffled: bool
) -> None:
    rig.fake.shuffle = not shuffled
    body = await call(rig, "POST", f"playlists/liked/play?mode={mode}")
    assert body["result"] == "ok"
    assert rig.fake.context == "spotify:user:alex:collection"
    assert rig.fake.shuffle is shuffled
    assert not rig.fake.calls_to("GET", "/v1/me/tracks")


async def test_liked_songs_fall_back_to_the_newest_liked_tracks(rig: Rig) -> None:
    rig.fake.liked = [T2, T0, T1]
    rig.fake.fail(
        "PUT /v1/me/player/play", 404, {"error": {"status": 404, "message": "Context not found"}}
    )
    body = await call(rig, "POST", "playlists/liked/play?mode=shuffle")
    assert body["result"] == "ok"
    assert rig.fake.queue == [T1, T0, T2]
    assert rig.fake.shuffle is True


async def test_liked_songs_refusal_is_not_taken_for_a_missing_device(rig: Rig) -> None:
    rig.fake.liked = []
    rig.fake.fail(
        "PUT /v1/me/player/play",
        404,
        {"error": {"status": 404, "message": "Context not found"}},
        times=2,
    )
    body = await call(rig, "POST", "playlists/liked/play")
    assert body["error"] == "spotify_error" and "no liked songs" in body["message"]


async def test_liked_songs_without_a_device_still_report_it(rig: Rig) -> None:
    rig.fake.active_device = None
    rig.fake.devices = []
    assert (await call(rig, "POST", "playlists/liked/play"))["error"] == "no_device"


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
    assert len(routes) == 14
    for path, method in routes:
        resp = await rig.client.request(
            method, path.replace("{playlist_id}", "pl10000000000000000000")
        )
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
