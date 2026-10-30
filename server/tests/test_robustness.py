"""Behaviour under bad clients, retries, concurrency and a flaky Spotify."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
import uvicorn

import baton.__main__ as entry
from baton import auth, logs
from baton.config import load_config
from baton.providers import spotify as spotify_provider
from tests.conftest import UI_KEY, Rig, app_state_of, base_env
from tests.fake_spotify import FakePlaylist

T0, T1, T2, T3 = (f"spotify:track:t{i}" for i in range(4))
BAD = {"Authorization": "Bearer wrong"}


def envelope(resp: Any) -> dict[str, Any]:
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


def spotify_calls(rig: Rig, method: str, path: str) -> int:
    return len(rig.fake.calls_to(method, path))


# watch key lockout ---------------------------------------------------------------------


async def test_valid_watch_key_works_after_many_bad_requests(rig: Rig) -> None:
    for _ in range(50):
        resp = await rig.client.get("/api/watch/state", headers=BAD)
        assert resp.status_code == 401
    assert (await rig.watch_get("state")).status_code == 200


async def test_bad_watch_keys_are_slowed_once_the_client_keeps_failing(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth, "FAILED_KEY_DELAY_SECONDS", 0.3)

    async def timed() -> float:
        start = time.monotonic()
        assert (await rig.client.get("/api/watch/state", headers=BAD)).status_code == 401
        return time.monotonic() - start

    assert await timed() < 0.2
    for _ in range(9):
        await timed()
    assert await timed() >= 0.3


async def test_ui_login_lockout_does_not_touch_the_watch_and_the_reverse(rig: Rig) -> None:
    for _ in range(10):
        await rig.client.post("/api/ui/login", json={"key": "wrong"})
    assert (await rig.client.post("/api/ui/login", json={"key": UI_KEY})).status_code == 429
    assert (await rig.watch_get("state")).status_code == 200

    rig.clock.t += 301
    for _ in range(20):
        await rig.client.get("/api/watch/state", headers=BAD)
    assert (await rig.client.post("/api/ui/login", json={"key": UI_KEY})).status_code == 200


# playlist membership -------------------------------------------------------------------


def long_playlist(rig: Rig, size: int, track_at: int) -> None:
    items = [f"spotify:track:filler{i}" for i in range(size)]
    items[track_at] = T2
    rig.fake.playlists["big"] = FakePlaylist("big", "Big one", items)
    rig.settings(target_playlist=("big", "Big one"))


async def test_membership_sees_a_track_beyond_the_two_thousandth_item(rig: Rig) -> None:
    long_playlist(rig, 2100, 2050)
    rig.fake.index = rig.fake.queue.index(T2)
    body = envelope(await rig.watch_post("playlist/add"))
    assert body["result"] == "already" and body["state"]["in_playlist"] is True
    assert len(rig.fake.playlists["big"].items) == 2100


async def test_a_playlist_that_cannot_be_read_completely_is_an_error_not_a_guess(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(spotify_provider, "MEMBER_MAX_PAGES", 3)
    long_playlist(rig, 400, 399)
    rig.fake.index = rig.fake.queue.index(T2)
    body = envelope(await rig.watch_post("playlist/add"))
    assert body["result"] == "error" and body["error"] == "spotify_error"
    assert len(rig.fake.playlists["big"].items) == 400


@pytest.mark.parametrize("playing", ["spotify:track:t2r", T2])
async def test_a_relinked_track_is_the_same_track(rig: Rig, playing: str) -> None:
    rig.fake.relinks[T2] = "spotify:track:t2r"
    rig.fake.tracks["spotify:track:t2r"] = rig.fake.tracks[T2]
    rig.fake.queue = [T0, T1, playing]
    rig.fake.index = 2
    body = envelope(await rig.watch_post("playlist/add"))
    assert body["result"] == "already"
    assert rig.fake.playlists["pl10000000000000000000"].items == [T2]


# Spotify login -------------------------------------------------------------------------


async def test_one_failed_token_request_does_not_brick_the_login(rig: Rig) -> None:
    rig.fake.fail("POST /api/token", 401, {"error": "invalid_client"})
    first = envelope(await rig.watch_get("state"))
    assert first["result"] == "error" and first["error"] == "spotify_error"
    assert envelope(await rig.watch_get("state"))["result"] == "ok"
    record = app_state_of(rig.app).store.get_spotify_auth()
    assert record is not None and record.invalid_reason is None


async def test_other_token_endpoint_failures_are_retried_too(rig: Rig) -> None:
    rig.fake.fail("POST /api/token", 400, {})
    rig.fake.fail("POST /api/token", 503, {"error": "unavailable"})
    assert envelope(await rig.watch_get("state"))["result"] == "error"
    assert envelope(await rig.watch_get("state"))["result"] == "error"
    assert envelope(await rig.watch_get("state"))["result"] == "ok"


async def test_invalid_grant_still_marks_the_login_invalid_without_calling_again(
    rig: Rig,
) -> None:
    rig.fake.fail("POST /api/token", 400, {"error": "invalid_grant"})
    assert envelope(await rig.watch_get("state"))["error"] == "spotify_auth"
    calls = spotify_calls(rig, "POST", "/api/token")
    assert envelope(await rig.watch_get("state"))["error"] == "spotify_auth"
    assert spotify_calls(rig, "POST", "/api/token") == calls


# concurrency and anchors ---------------------------------------------------------------


async def test_concurrent_playlist_adds_add_once(rig: Rig) -> None:
    rig.fake.latency = 0.03
    rig.fake.index = rig.fake.queue.index(T0)
    replies = await asyncio.gather(*[rig.watch_post("playlist/add") for _ in range(2)])
    assert sorted(envelope(r)["result"] for r in replies) == ["already", "ok"]
    assert rig.fake.playlists["pl10000000000000000000"].items.count(T0) == 1


async def test_concurrent_play_pause_acts_one_after_the_other(rig: Rig) -> None:
    rig.fake.latency = 0.03
    replies = await asyncio.gather(*[rig.watch_post("play-pause") for _ in range(2)])
    states = sorted(envelope(r)["state"]["is_playing"] for r in replies)
    assert states == [False, True]
    assert rig.fake.is_playing is True


async def test_concurrent_likes_write_once(rig: Rig) -> None:
    rig.fake.latency = 0.03
    rig.fake.index = rig.fake.queue.index(T0)
    replies = await asyncio.gather(*[rig.watch_post("like") for _ in range(3)])
    assert sorted(envelope(r)["result"] for r in replies) == ["already", "already", "ok"]
    assert len(rig.fake.calls_to("PUT", "/v1/me/library")) == 1


async def test_state_reports_the_track_id(rig: Rig) -> None:
    rig.fake.index = rig.fake.queue.index(T3)
    assert envelope(await rig.watch_get("state"))["state"]["track_id"] == "t3"
    rig.fake.active_device = None
    assert envelope(await rig.watch_get("state"))["state"]["track_id"] is None


@pytest.mark.parametrize(
    "path", ["like", "unlike", "playlist/add", "playlist/remove"], ids=lambda p: p
)
async def test_anchored_press_on_a_changed_track_changes_nothing(rig: Rig, path: str) -> None:
    rig.fake.index = rig.fake.queue.index(T0)
    liked, items = list(rig.fake.liked), list(rig.fake.playlists["pl10000000000000000000"].items)
    resp = await rig.client.post(f"/api/watch/{path}?track=t3", headers=rig.watch)
    body = envelope(resp)
    assert body["result"] == "error" and body["error"] == "track_changed"
    assert body["state"]["track_id"] == "t0"
    assert (rig.fake.liked, rig.fake.playlists["pl10000000000000000000"].items) == (liked, items)


async def test_anchored_press_on_the_same_track_acts(rig: Rig) -> None:
    rig.fake.index = rig.fake.queue.index(T0)
    like = await rig.client.post("/api/watch/like?track=t0", headers=rig.watch)
    add = await rig.client.post("/api/watch/playlist/add?track=t0", headers=rig.watch)
    assert (envelope(like)["result"], envelope(add)["result"]) == ("ok", "ok")


async def test_unanchored_press_acts_on_whatever_plays(rig: Rig) -> None:
    rig.fake.index = rig.fake.queue.index(T0)
    assert envelope(await rig.watch_post("like"))["result"] == "ok"


# body size -----------------------------------------------------------------------------


async def test_a_large_login_body_is_refused_before_it_is_read(rig: Rig) -> None:
    resp = await rig.client.post("/api/ui/login", content=b"x" * 1_000_000)
    assert resp.status_code == 413


async def test_a_streamed_body_is_cut_off_at_the_cap(rig: Rig) -> None:
    sent = 0

    async def chunks() -> AsyncIterator[bytes]:
        nonlocal sent
        for _ in range(64):
            sent += 65536
            yield b"x" * 65536

    resp = await rig.client.post(
        "/api/ui/login", content=chunks(), headers={"Content-Type": "application/json"}
    )
    assert resp.status_code == 413
    assert sent < 4 * 65536


async def test_watch_routes_cap_the_body_too(rig: Rig) -> None:
    resp = await rig.client.post("/api/watch/like", content=b"x" * 100_000, headers=rig.watch)
    assert resp.status_code == 413


async def test_normal_bodies_still_pass(rig: Rig) -> None:
    resp = await rig.client.post("/api/ui/login", json={"key": UI_KEY})
    assert resp.status_code == 200


# Spotify quota -------------------------------------------------------------------------


async def test_concurrent_state_reads_share_one_lookup(make_rig: Callable[..., Rig]) -> None:
    rig = make_rig(BATON_STATE_CACHE_SECONDS="1")
    rig.link()
    rig.settings(target_playlist=("pl10000000000000000000", "My Shazam"))
    await rig.watch_get("state")  # warms the playlist snapshot cache
    rig.fake.calls.clear()
    rig.clock.t += 5
    rig.fake.latency = 0.03
    replies = await asyncio.gather(*[rig.watch_get("state") for _ in range(50)])
    assert all(envelope(r)["result"] == "ok" for r in replies)
    assert len(rig.fake.calls) <= 3


async def test_state_is_reused_and_a_command_answer_replaces_it(
    make_rig: Callable[..., Rig],
) -> None:
    rig = make_rig(BATON_STATE_CACHE_SECONDS="1")
    rig.link()
    await rig.watch_get("state")
    before = len(rig.fake.calls)
    await rig.watch_get("state")
    assert len(rig.fake.calls) == before  # no clock movement: served from the cache
    rig.clock.t += 2
    await rig.watch_get("state")
    assert len(rig.fake.calls) > before
    answer = envelope(await rig.watch_post("next"))
    after_command = len(rig.fake.calls)
    assert envelope(await rig.watch_get("state"))["state"]["title"] == answer["state"]["title"]
    assert len(rig.fake.calls) == after_command
    rig.clock.t += 2
    await rig.watch_get("state")
    assert len(rig.fake.calls) > after_command


async def test_a_track_costs_one_lookup_of_its_flags_and_a_poll_one_call(rig: Rig) -> None:
    rig.settings(target_playlist=("pl10000000000000000000", "My Shazam"))
    await rig.watch_get("state")
    rig.fake.calls.clear()
    for _ in range(5):
        await rig.watch_get("state")
    assert [c[1] for c in rig.fake.calls] == ["/v1/me/player"] * 5


async def test_a_like_updates_the_flags_without_another_lookup(rig: Rig) -> None:
    await rig.watch_get("state")
    assert envelope(await rig.watch_post("like"))["state"]["liked"] is True
    rig.fake.calls.clear()
    assert envelope(await rig.watch_get("state"))["state"]["liked"] is True
    assert not rig.fake.calls_to("GET", "/v1/me/library/contains")


async def test_the_known_state_carries_progress_and_rereads_when_the_track_runs_out(
    make_rig: Callable[..., Rig],
) -> None:
    rig = make_rig(BATON_STATE_CACHE_SECONDS="15")
    rig.link()
    first = envelope(await rig.watch_get("state"))["state"]
    rig.fake.calls.clear()
    rig.clock.t += 10
    later = envelope(await rig.watch_get("state"))["state"]
    assert later["progress_ms"] == first["progress_ms"] + 10000
    assert rig.fake.calls == []
    state = app_state_of(rig.app).controller
    assert state._known is not None
    known = dataclasses.replace(
        state._known,
        state=dataclasses.replace(state._known.state, duration_ms=first["progress_ms"] + 11000),
    )
    state._known = known
    rig.clock.t += 2
    await rig.watch_get("state")
    assert spotify_calls(rig, "GET", "/v1/me/player") == 1


async def test_a_spent_budget_answers_the_known_state_and_commands_still_go_out(
    make_rig: Callable[..., Rig],
) -> None:
    rig = make_rig(BATON_SPOTIFY_BUDGET_30S="3")
    rig.link()
    first = envelope(await rig.watch_get("state"))
    envelope(await rig.watch_get("state"))
    rig.fake.calls.clear()
    assert envelope(await rig.watch_get("state"))["state"]["title"] == first["state"]["title"]
    assert rig.fake.calls == []
    assert envelope(await rig.watch_post("next"))["result"] == "ok"
    rig.clock.t += 31
    rig.fake.calls.clear()
    envelope(await rig.watch_get("state"))
    assert spotify_calls(rig, "GET", "/v1/me/player") == 1


async def test_a_rate_limit_pause_answers_the_known_state(rig: Rig) -> None:
    title = envelope(await rig.watch_get("state"))["state"]["title"]
    rig.fake.fail("GET /v1/me/player", 429, headers={"Retry-After": "600"})
    body = envelope(await rig.watch_get("state"))
    assert body["result"] == "ok" and body["state"]["title"] == title
    calls = len(rig.fake.calls)
    assert envelope(await rig.watch_get("state"))["result"] == "ok"
    assert len(rig.fake.calls) == calls


async def test_a_short_pause_is_waited_out_and_the_press_succeeds(rig: Rig) -> None:
    async def sleep(seconds: float) -> None:
        rig.clock.t += seconds

    app_state_of(rig.app).provider._sleep = sleep
    rig.fake.fail("POST /v1/me/player/next", 429, headers={"Retry-After": "5"})
    assert envelope(await rig.watch_post("next"))["result"] == "ok"
    assert len(rig.fake.calls_to("POST", "/v1/me/player/next")) == 2


async def test_a_long_retry_after_is_kept_and_a_429_without_one_pauses_too(rig: Rig) -> None:
    rig.fake.fail("GET /v1/me/player", 429, headers={"Retry-After": "7200"})
    await rig.watch_get("state")
    rig.clock.t += 7000
    assert envelope(await rig.watch_get("state"))["error"] == "spotify_rate_limited"
    rig.clock.t += 201
    rig.fake.fail(
        "GET /v1/me/player",
        429,
        {"error": {"status": 429, "message": "Too many requests", "reason": "QUOTA_EXCEEDED"}},
    )
    assert envelope(await rig.watch_get("state"))["error"] == "spotify_rate_limited"
    calls = len(rig.fake.calls)
    rig.clock.t += 800
    assert envelope(await rig.watch_get("state"))["error"] == "spotify_rate_limited"
    assert len(rig.fake.calls) == calls
    rig.clock.t += 101
    assert envelope(await rig.watch_get("state"))["result"] == "ok"


async def test_retry_after_pauses_all_spotify_calls(rig: Rig) -> None:
    rig.fake.fail("GET /v1/me/player", 429, headers={"Retry-After": "30"})
    first = envelope(await rig.watch_get("state"))
    assert first["error"] == "spotify_rate_limited"
    calls = len(rig.fake.calls)
    rig.clock.t += 10
    second = envelope(await rig.watch_get("state"))
    assert second["error"] == "spotify_rate_limited" and "20 s" in second["message"]
    assert len(rig.fake.calls) == calls
    rig.clock.t += 21
    assert envelope(await rig.watch_get("state"))["result"] == "ok"


# smaller findings ----------------------------------------------------------------------


async def test_unexpected_spotify_json_still_answers_the_envelope(rig: Rig) -> None:
    rig.fake.fail("GET /v1/me/player", 200, {"device": 5})
    body = envelope(await rig.watch_get("state"))
    assert body["result"] == "error" and body["error"] == "spotify_error"
    rig.fake.fail("GET /v1/me/library/contains", 200, {"unexpected": True})
    body = envelope(await rig.watch_post("like"))
    assert body.keys() >= {"result", "error", "message", "state"}


async def test_a_command_with_unexpected_spotify_json_answers_the_envelope(rig: Rig) -> None:
    rig.fake.fail("GET /v1/me/library/contains", 200, {"unexpected": True})
    body = envelope(await rig.watch_post("like"))
    assert body["result"] == "error" and body["error"] == "spotify_error"


@pytest.mark.parametrize(
    "playlist_id",
    [
        "../me/player",
        "pl20000000000000000000?x=1",
        "pl20000000000000000000/../pl30000000000000000000",
        "a b",
    ],
)
async def test_settings_reject_a_malformed_playlist_id(rig: Rig, playlist_id: str) -> None:
    await rig.login_ui()
    rig.fake.calls.clear()
    resp = await rig.client.put("/api/ui/settings", json={"target_playlist_id": playlist_id})
    assert resp.status_code == 422
    assert rig.fake.calls == []
    ok = await rig.client.put(
        "/api/ui/settings", json={"target_playlist_id": "pl20000000000000000000"}
    )
    assert ok.status_code == 200 and ok.json()["target_playlist"]["id"] == "pl20000000000000000000"


def test_logs_carry_no_spotify_urls_or_oauth_codes() -> None:
    saved = {n: logging.getLogger(n).level for n in logs.QUIET_LOGGERS}
    access = logging.getLogger("uvicorn.access")
    filters = list(access.filters)
    try:
        logs.harden_logging()
        for name in logs.QUIET_LOGGERS:
            assert not logging.getLogger(name).isEnabledFor(logging.INFO)
        record = logging.LogRecord(
            "uvicorn.access",
            logging.INFO,
            __file__,
            1,
            '%s - "%s %s HTTP/%s" %d',
            ("1.2.3.4:5", "GET", "/auth/spotify/callback?code=abc&state=xyz", "1.1", 302),
            None,
        )
        for f in access.filters:
            assert isinstance(f, logs.StripQuery) and f.filter(record)
        assert record.getMessage() == '1.2.3.4:5 - "GET /auth/spotify/callback HTTP/1.1" 302'
    finally:
        for name, level in saved.items():
            logging.getLogger(name).setLevel(level)
        access.filters[:] = filters


async def test_sessions_end_when_the_ui_key_changes(
    make_rig: Callable[..., Rig],
) -> None:
    first = make_rig()
    await first.login_ui()
    cookie = first.client.cookies["baton_session"]

    same_key = make_rig()
    same_key.client.cookies.set("baton_session", cookie)
    assert (await same_key.client.get("/api/ui/status")).status_code == 200

    rotated = make_rig(BATON_UI_KEY="r" * 32)
    rotated.client.cookies.set("baton_session", cookie)
    assert (await rotated.client.get("/api/ui/status")).status_code == 401
    assert (await same_key.client.get("/api/ui/status")).status_code == 401


# configuration -------------------------------------------------------------------------

SERVICE_LINK_ENV = {
    "BATON_PORT": "tcp://10.0.0.1:8080",
    "BATON_PORT_8080_TCP": "tcp://10.0.0.1:8080",
    "BATON_PORT_8080_TCP_PROTO": "tcp",
    "BATON_PORT_8080_TCP_PORT": "8080",
    "BATON_PORT_8080_TCP_ADDR": "10.0.0.1",
    "BATON_SERVICE_HOST": "10.0.0.1",
    "BATON_SERVICE_PORT": "8080",
}


def test_kubernetes_service_link_variables_do_not_break_the_config(tmp_path: Any) -> None:
    config = load_config(base_env(tmp_path, **SERVICE_LINK_ENV))
    assert (config.listen_host, config.listen_port) == ("0.0.0.0", 8080)


def test_the_server_starts_with_service_link_variables_set(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in {**base_env(tmp_path), **SERVICE_LINK_ENV}.items():
        monkeypatch.setenv(name, value)
    started: dict[str, Any] = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: started.update(kw))
    assert entry.main() == 0
    assert (started["host"], started["port"]) == ("0.0.0.0", 8080)


def test_listen_port_is_set_with_its_own_variable(tmp_path: Any) -> None:
    config = load_config(base_env(tmp_path, BATON_LISTEN_PORT="9090"))
    assert config.listen_port == 9090
