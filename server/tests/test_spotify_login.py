"""Spotify login: authorization code flow, state check, refresh, invalid_grant, redirect URI."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import httpx

from tests.conftest import PUBLIC_URL, Rig, app_state_of


async def start_login(rig: Rig, headers: dict[str, str] | None = None) -> httpx.Response:
    await rig.login_ui()
    return await rig.client.get("/auth/spotify/login", headers=headers)


async def test_full_login_round_trip(make_rig) -> None:  # type: ignore[no-untyped-def]
    rig: Rig = make_rig()
    resp = await start_login(rig)
    assert resp.status_code == 302
    target = urlsplit(resp.headers["location"])
    query = parse_qs(target.query)
    assert f"{target.scheme}://{target.netloc}" == "http://spotify.test"
    assert query["client_id"] == ["client-id"] and query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"] and query["code_challenge"][0]
    assert "user-modify-playback-state" in query["scope"][0]
    assert "client-secret" not in resp.headers["location"]

    # Spotify's authorize step, then the redirect back to baton carrying code and state.
    back = urlsplit((await _fake_authorize(rig, resp.headers["location"])).headers["location"])
    assert f"{back.scheme}://{back.netloc}{back.path}" == f"{PUBLIC_URL}/auth/spotify/callback"
    callback = await rig.client.get(f"{back.path}?{back.query}")
    assert callback.status_code == 200 and "Spotify linked" in callback.text
    assert "http-equiv=refresh" in callback.text
    assert "style=" not in callback.text and "<style" not in callback.text  # the CSP blocks both

    status = (await rig.client.get("/api/ui/status")).json()["spotify"]
    assert status["linked"] and status["valid"] and status["expires_in_days"] == 180
    record = app_state_of(rig.app).store.get_spotify_auth()
    assert record is not None and record.refresh_token == rig.fake.refresh_token
    assert (await rig.watch_get("state")).json()["result"] == "ok"


async def _fake_authorize(rig: Rig, location: str) -> httpx.Response:
    from tests.fake_spotify import create_fake_spotify

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_fake_spotify(rig.fake)),
        base_url="http://spotify.test",
    ) as spotify:
        return await spotify.get(location.removeprefix("http://spotify.test"))


async def test_redirect_uri_comes_from_configuration_not_the_host_header(make_rig) -> None:  # type: ignore[no-untyped-def]
    rig: Rig = make_rig()
    resp = await start_login(
        rig, headers={"Host": "evil.example.org", "X-Forwarded-Host": "evil.example.org"}
    )
    query = parse_qs(urlsplit(resp.headers["location"]).query)
    assert query["redirect_uri"] == [f"{PUBLIC_URL}/auth/spotify/callback"]


async def test_login_needs_ui_auth(make_rig) -> None:  # type: ignore[no-untyped-def]
    rig: Rig = make_rig()
    assert (await rig.client.get("/auth/spotify/login")).status_code == 401


async def test_callback_rejects_wrong_or_missing_state(make_rig) -> None:  # type: ignore[no-untyped-def]
    rig: Rig = make_rig()
    resp = await start_login(rig)
    state = parse_qs(urlsplit(resp.headers["location"]).query)["state"][0]
    cookie = rig.client.cookies.get("baton_oauth")
    assert cookie == state

    wrong = await rig.client.get("/auth/spotify/callback?code=good-code&state=forged")
    assert wrong.status_code == 400
    rig.client.cookies.delete("baton_oauth")
    missing_cookie = await rig.client.get(f"/auth/spotify/callback?code=good-code&state={state}")
    assert missing_cookie.status_code == 400
    assert app_state_of(rig.app).store.get_spotify_auth() is None


async def test_callback_state_is_single_use_and_expires(make_rig) -> None:  # type: ignore[no-untyped-def]
    rig: Rig = make_rig()
    resp = await start_login(rig)
    state = parse_qs(urlsplit(resp.headers["location"]).query)["state"][0]
    ok = await rig.client.get(f"/auth/spotify/callback?code=good-code&state={state}")
    assert "Spotify linked" in ok.text
    rig.client.cookies.set("baton_oauth", state, path="/auth/spotify")
    replay = await rig.client.get(f"/auth/spotify/callback?code=good-code&state={state}")
    assert "failed" in replay.text

    rig.client.cookies.delete("baton_oauth")
    resp = await start_login(rig)
    state = parse_qs(urlsplit(resp.headers["location"]).query)["state"][0]
    rig.clock.t += 601
    late = await rig.client.get(f"/auth/spotify/callback?code=good-code&state={state}")
    assert "failed" in late.text


async def test_callback_with_bad_code_shows_failure(make_rig) -> None:  # type: ignore[no-untyped-def]
    rig: Rig = make_rig()
    resp = await start_login(rig)
    state = parse_qs(urlsplit(resp.headers["location"]).query)["state"][0]
    bad = await rig.client.get(f"/auth/spotify/callback?code=nope&state={state}")
    assert "failed" in bad.text and app_state_of(rig.app).store.get_spotify_auth() is None


async def test_callback_after_user_denied(make_rig) -> None:  # type: ignore[no-untyped-def]
    rig: Rig = make_rig()
    resp = await start_login(rig)
    state = parse_qs(urlsplit(resp.headers["location"]).query)["state"][0]
    denied = await rig.client.get(f"/auth/spotify/callback?error=access_denied&state={state}")
    assert "access_denied" in denied.text


async def test_access_token_is_refreshed_when_it_expires(rig: Rig) -> None:
    await rig.watch_get("state")
    await rig.watch_get("state")
    assert rig.fake.issued == 1
    rig.clock.t += 3600 - 59
    assert (await rig.watch_get("state")).json()["result"] == "ok"
    assert rig.fake.issued == 2


async def test_rotated_refresh_token_is_stored_and_authorization_date_kept(rig: Rig) -> None:
    rig.fake.refresh_response_rotates = True
    start = rig.clock()
    await rig.watch_get("state")
    rig.clock.t += 4000
    await rig.watch_get("state")
    record = app_state_of(rig.app).store.get_spotify_auth()
    assert record is not None
    assert record.refresh_token == rig.fake.refresh_token != "refresh-1"
    assert record.authorized_at == start


async def test_invalid_grant_marks_the_login_invalid(rig: Rig) -> None:
    rig.fake.refresh_token = "something-else"
    body = (await rig.watch_get("state")).json()
    assert body["error"] == "spotify_auth"
    status = app_state_of(rig.app).accounts.status()
    assert status["linked"] and not status["valid"] and "log in again" in status["message"].lower()
    calls = len(rig.fake.calls)
    await rig.watch_get("state")
    assert len(rig.fake.calls) == calls  # no hammering of the accounts service


async def test_new_login_clears_the_invalid_mark(make_rig) -> None:  # type: ignore[no-untyped-def]
    rig: Rig = make_rig()
    rig.link()
    rig.fake.refresh_token = "other"
    await rig.watch_get("state")
    assert not app_state_of(rig.app).accounts.status()["valid"]
    resp = await start_login(rig)
    state = parse_qs(urlsplit(resp.headers["location"]).query)["state"][0]
    await rig.client.get(f"/auth/spotify/callback?code=good-code&state={state}")
    assert app_state_of(rig.app).accounts.status()["valid"]


async def test_days_until_renewal_count_down_from_authorization(rig: Rig) -> None:
    accounts = app_state_of(rig.app).accounts
    assert accounts.status()["expires_in_days"] == 180
    rig.clock.t += 100 * 86400 + 3600
    assert accounts.status()["expires_in_days"] == 80
    rig.clock.t += 80 * 86400
    status = accounts.status()
    assert not status["valid"] and status["expires_in_days"] == 0


async def test_status_without_login(make_rig) -> None:  # type: ignore[no-untyped-def]
    rig: Rig = make_rig()
    assert app_state_of(rig.app).accounts.status()["linked"] is False


async def test_disconnect_forgets_the_login(rig: Rig) -> None:
    await rig.login_ui()
    resp = await rig.client.post("/api/ui/spotify/disconnect", json={})
    assert resp.status_code == 200
    assert (await rig.watch_get("state")).json()["error"] == "spotify_auth"


async def test_spotify_outage_during_refresh_is_spotify_error(rig: Rig) -> None:
    rig.fake.fail("POST /api/token", 500)
    assert (await rig.watch_get("state")).json()["error"] == "spotify_error"
    assert app_state_of(rig.app).accounts.status()["valid"]
