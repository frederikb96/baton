"""UI auth modes and the separation between watch and UI credentials."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from baton import routes_watch
from baton.config import ConfigError, load_config
from tests.conftest import UI_KEY, Rig, base_env

JSON_HEADER = {"X-Baton-Request": "1"}
PROXY = {"BATON_AUTH_MODE": "proxy", "BATON_UI_KEY": ""}
UI_GET_PATHS = [
    "/api/ui/status",
    "/api/ui/state",
    "/api/ui/settings",
    "/api/ui/keys",
    "/api/ui/spotify/playlists",
    "/api/ui/spotify/devices",
    "/api/ui/playlists/recent",
    "/auth/spotify/login",
]


# start-up ------------------------------------------------------------------------------


def test_key_mode_refuses_to_start_without_ui_key(tmp_path: Path) -> None:
    env = base_env(tmp_path)
    del env["BATON_UI_KEY"]
    with pytest.raises(ConfigError, match="ui_key is required"):
        load_config(env)


def test_key_mode_is_the_default_and_rejects_a_short_key(tmp_path: Path) -> None:
    assert load_config(base_env(tmp_path)).auth_mode == "key"
    with pytest.raises(ConfigError, match="at least"):
        load_config(base_env(tmp_path, BATON_UI_KEY="short"))


def test_proxy_mode_needs_no_ui_key(tmp_path: Path) -> None:
    assert load_config(base_env(tmp_path, **PROXY)).auth_mode == "proxy"


def test_unknown_auth_mode_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(base_env(tmp_path, BATON_AUTH_MODE="open"))


@pytest.mark.parametrize(
    "name", ["BATON_PUBLIC_URL", "BATON_SPOTIFY_CLIENT_ID", "BATON_SPOTIFY_CLIENT_SECRET"]
)
def test_required_values_have_no_defaults(tmp_path: Path, name: str) -> None:
    env = base_env(tmp_path)
    del env[name]
    with pytest.raises(ConfigError, match=name):
        load_config(env)


@pytest.mark.parametrize(
    "url",
    ["http://baton.example.com", "http://localhost:8080", "https://baton.example.com/app", "baton"],
)
def test_public_url_must_be_https_or_loopback_origin(tmp_path: Path, url: str) -> None:
    with pytest.raises(ConfigError, match="PUBLIC_URL"):
        load_config(base_env(tmp_path, BATON_PUBLIC_URL=url))


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:8080", "http://[::1]:8080", "https://a.example.com/"]
)
def test_public_url_accepts_loopback_and_https(tmp_path: Path, url: str) -> None:
    config = load_config(base_env(tmp_path, BATON_PUBLIC_URL=url))
    assert config.redirect_uri == f"{url.rstrip('/')}/auth/spotify/callback"


# key mode ------------------------------------------------------------------------------


async def test_ui_routes_need_a_session(rig: Rig) -> None:
    for path in UI_GET_PATHS:
        assert (await rig.client.get(path)).status_code == 401, path


async def test_login_sets_a_hardened_cookie(rig: Rig) -> None:
    resp = await rig.client.post("/api/ui/login", json={"key": UI_KEY})
    cookie = resp.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "secure" in cookie
    assert "path=/" in cookie
    assert (await rig.client.get("/api/ui/status")).status_code == 200


async def test_cookie_is_not_secure_on_a_loopback_http_install(
    make_rig: Callable[..., Rig],
) -> None:
    rig = make_rig(BATON_PUBLIC_URL="http://127.0.0.1:8080")
    resp = await rig.client.post("/api/ui/login", json={"key": UI_KEY})
    assert "secure" not in resp.headers["set-cookie"].lower()


async def test_wrong_ui_key(rig: Rig) -> None:
    resp = await rig.client.post("/api/ui/login", json={"key": "x" * 32})
    assert resp.status_code == 401 and "set-cookie" not in resp.headers


async def test_ui_key_failures_lock_out(rig: Rig) -> None:
    for _ in range(10):
        await rig.client.post("/api/ui/login", json={"key": "wrong"})
    assert (await rig.client.post("/api/ui/login", json={"key": UI_KEY})).status_code == 429
    rig.clock.t += 301
    assert (await rig.client.post("/api/ui/login", json={"key": UI_KEY})).status_code == 200


async def test_lockout_follows_forwarded_address_only_when_trusted(
    make_rig: Callable[..., Rig],
) -> None:
    rig = make_rig(BATON_TRUST_PROXY_HEADERS="true")
    for _ in range(10):
        await rig.client.post(
            "/api/ui/login", json={"key": "wrong"}, headers={"X-Forwarded-For": "9.9.9.9"}
        )
    locked = await rig.client.post(
        "/api/ui/login", json={"key": UI_KEY}, headers={"X-Forwarded-For": "9.9.9.9"}
    )
    other = await rig.client.post(
        "/api/ui/login", json={"key": UI_KEY}, headers={"X-Forwarded-For": "8.8.8.8"}
    )
    assert (locked.status_code, other.status_code) == (429, 200)


async def test_session_expires(rig: Rig) -> None:
    await rig.login_ui()
    rig.clock.t += 30 * 86400 + 1
    assert (await rig.client.get("/api/ui/status")).status_code == 401


async def test_logout_ends_the_session(rig: Rig) -> None:
    await rig.login_ui()
    stale = rig.client.cookies.get("baton_session")
    await rig.client.post("/api/ui/logout", json={})
    rig.client.cookies.set("baton_session", stale or "")
    assert (await rig.client.get("/api/ui/status")).status_code == 401


async def test_session_endpoint_reports_state_without_auth(rig: Rig) -> None:
    assert (await rig.client.get("/api/ui/session")).json() == {
        "auth_mode": "key",
        "authenticated": False,
    }
    await rig.login_ui()
    assert (await rig.client.get("/api/ui/session")).json()["authenticated"] is True


async def test_state_changing_calls_need_json_or_custom_header(rig: Rig) -> None:
    await rig.login_ui()
    form = {"Content-Type": "application/x-www-form-urlencoded"}
    for path in ("/api/ui/play-pause", "/api/ui/next", "/api/ui/like", "/api/ui/keys"):
        resp = await rig.client.post(path, content=b"a=b", headers=form)
        assert resp.status_code == 403, path
        text_plain = await rig.client.post(
            path, content=b"{}", headers={"Content-Type": "text/plain"}
        )
        assert text_plain.status_code == 403, path
    assert rig.fake.calls == []
    assert (await rig.client.post("/api/ui/play-pause", headers=JSON_HEADER)).status_code == 200
    assert (await rig.client.post("/api/ui/next", json={})).status_code == 200
    delete = await rig.client.delete("/api/ui/keys/none")
    assert delete.status_code == 403


async def test_login_form_post_is_refused(rig: Rig) -> None:
    resp = await rig.client.post(
        "/api/ui/login",
        content=f"key={UI_KEY}",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code in (403, 422) and "set-cookie" not in resp.headers


async def test_identity_header_grants_nothing_in_key_mode(rig: Rig) -> None:
    resp = await rig.client.get("/api/ui/status", headers={"X-Auth-Request-User": "admin"})
    assert resp.status_code == 401


# watch routes versus UI credentials ---------------------------------------------------


async def test_session_cookie_does_not_open_watch_routes(rig: Rig) -> None:
    await rig.login_ui()
    assert (await rig.client.get("/api/watch/state")).status_code == 401


async def test_watch_key_does_not_open_ui_routes(rig: Rig) -> None:
    for path in UI_GET_PATHS:
        assert (await rig.client.get(path, headers=rig.watch)).status_code == 401, path


@pytest.mark.parametrize("mode_env", [{}, PROXY])
async def test_forged_identity_header_on_watch_routes_grants_nothing(
    make_rig: Callable[..., Rig], mode_env: dict[str, str]
) -> None:
    rig = make_rig(**mode_env)
    rig.link()
    for headers in (
        {"X-Auth-Request-User": "admin"},
        {"X-Auth-Request-User": "admin", "X-Auth-Request-Email": "a@example.com"},
        {"X-Forwarded-User": "admin"},
    ):
        assert (await rig.client.get("/api/watch/state", headers=headers)).status_code == 401
    assert rig.fake.calls == []


def test_watch_routes_expose_only_the_contract() -> None:
    paths = sorted(f"{m} {r.path}" for r in routes_watch.router.routes for m in r.methods)  # type: ignore[attr-defined]
    assert paths == sorted(
        [
            "GET /api/watch/state",
            "GET /api/watch/playlists",
            "POST /api/watch/play-pause",
            "POST /api/watch/next",
            "POST /api/watch/previous",
            "POST /api/watch/like",
            "POST /api/watch/unlike",
            "POST /api/watch/playlist/add",
            "POST /api/watch/playlist/remove",
            "POST /api/watch/playlists/{playlist_id}/play",
        ]
    )


# proxy mode ----------------------------------------------------------------------------


@pytest.fixture
def proxy_rig(make_rig: Callable[..., Rig]) -> Rig:
    rig = make_rig(**PROXY)
    rig.link()
    return rig


async def test_proxy_mode_requires_the_identity_header_on_every_non_watch_route(
    proxy_rig: Rig,
) -> None:
    for path in ["/", "/static/app.js", "/api/ui/session", *UI_GET_PATHS]:
        assert (await proxy_rig.client.get(path)).status_code == 401, path
        blank = await proxy_rig.client.get(path, headers={"X-Auth-Request-User": "  "})
        assert blank.status_code == 401, path


async def test_proxy_mode_accepts_the_identity_header(proxy_rig: Rig) -> None:
    headers = {"X-Auth-Request-User": "alice"}
    for path in ["/", "/static/app.js", *[p for p in UI_GET_PATHS if "login" not in p]]:
        assert (await proxy_rig.client.get(path, headers=headers)).status_code == 200, path
    session = (await proxy_rig.client.get("/api/ui/session", headers=headers)).json()
    assert session == {"auth_mode": "proxy", "authenticated": True, "user": "alice"}


async def test_proxy_mode_header_name_is_configurable(make_rig: Callable[..., Rig]) -> None:
    rig = make_rig(**PROXY, BATON_PROXY_USER_HEADER="Remote-User")
    assert (
        await rig.client.get("/api/ui/status", headers={"X-Auth-Request-User": "a"})
    ).status_code == 401
    assert (await rig.client.get("/api/ui/status", headers={"Remote-User": "a"})).status_code == 200


async def test_proxy_mode_still_blocks_form_posts(proxy_rig: Rig) -> None:
    resp = await proxy_rig.client.post(
        "/api/ui/play-pause",
        content=b"x=1",
        headers={"X-Auth-Request-User": "a", "Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 403


async def test_proxy_mode_has_no_key_login(proxy_rig: Rig) -> None:
    resp = await proxy_rig.client.post(
        "/api/ui/login", json={"key": "x"}, headers={"X-Auth-Request-User": "a"}
    )
    assert resp.status_code in (401, 404)


async def test_proxy_mode_watch_key_and_health_need_no_header(proxy_rig: Rig) -> None:
    assert (await proxy_rig.client.get("/healthz")).status_code == 200
    assert (await proxy_rig.watch_get("state")).status_code == 200


async def test_proxy_mode_login_callback_needs_the_header(proxy_rig: Rig) -> None:
    assert (await proxy_rig.client.get("/auth/spotify/callback?code=a&state=b")).status_code == 401


# hardening -----------------------------------------------------------------------------


async def test_security_headers_and_no_store(rig: Rig) -> None:
    resp = await rig.client.get("/api/watch/state", headers=rig.watch)
    assert resp.headers["cache-control"] == "no-store"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in resp.headers["content-security-policy"]


async def test_healthz_is_open(rig: Rig) -> None:
    resp = await rig.client.get("/healthz")
    assert resp.status_code == 200 and resp.json() == {"status": "ok"}


async def test_no_api_docs_are_served(rig: Rig) -> None:
    for path in ("/docs", "/openapi.json", "/redoc"):
        assert (await rig.client.get(path)).status_code in (401, 404)


async def test_the_page_uses_no_inline_style_or_script(rig: Rig) -> None:
    page = (await rig.client.get("/")).text
    assert "style=" not in page and "<style" not in page
    assert "<script>" not in page and "onclick=" not in page
