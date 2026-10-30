# Server

One container: the watch API ([api.md](api.md)), a small web page for playback control and settings, and the Spotify login. State lives in a SQLite database on the `/data` volume.

## Run it

- Create your own Spotify developer app (below), then copy `server/compose.example.yaml` and a `.env` with the variables from the table.
- `docker compose up -d`, open the public URL, sign in, press *Log in with Spotify*, create a watch key and enter it in the watch app's settings.
- Generate the access key with `openssl rand -base64 32`.
- The image runs as uid 1000 with a read-only root filesystem; it writes only to `/data`. `GET /healthz` answers 200 without authentication. In `proxy` mode a proxy in front may still put its own login ahead of it.
- The server speaks HTTP only. The watch (through the phone) and Spotify's redirect URI need an HTTPS address, so a TLS-terminating reverse proxy or tunnel is part of every install. Plain `http://127.0.0.1:<port>` works for the Spotify login from the same machine, not for the watch.

## Spotify developer app

- Create the app at <https://developer.spotify.com/dashboard>. It runs in Spotify's development mode: the owner needs an active Premium subscription, and at most five Spotify accounts can use it, each added by name and email under *User Management* in the dashboard. Someone not on the list can log in but every API call fails with 403.
- Every operator needs their own app; Spotify gives extended quota only to organisations, so one hosted instance cannot serve many people.
- Redirect URI to register: `<BATON_PUBLIC_URL>/auth/spotify/callback`. Spotify accepts HTTPS addresses and loopback IP literals (`http://127.0.0.1:PORT`, `http://[::1]:PORT`); `localhost` is rejected.
- Client id and secret of the app go into `BATON_SPOTIFY_CLIENT_ID` and `BATON_SPOTIFY_CLIENT_SECRET`.
- Spotify refresh tokens last six months and renewing does not extend them. The web page shows the days left; log in again before they run out. A login that Spotify rejects makes the watch API answer `spotify_auth` until someone logs in again on the web page.
- The login asks for the scopes to read and control playback, read recently played items, manage the library and manage playlists.

## Configuration

Bootstrap values only. Each is read from the environment variable `BATON_` plus the key in upper case by `baton/config.py`; the defaults, and which values have none, are in `server/baton/default_config.yaml`.

| Variable | Purpose |
|---|---|
| `BATON_PUBLIC_URL` | Externally visible origin. Spotify's redirect URI is built from it, never from the request's `Host` header. |
| `BATON_AUTH_MODE` | `key` or `proxy`, see below. |
| `BATON_UI_KEY` | Secret that unlocks the web page in `key` mode, at least 24 characters. |
| `BATON_SPOTIFY_CLIENT_ID` | Client id of your Spotify app. |
| `BATON_SPOTIFY_CLIENT_SECRET` | Client secret of your Spotify app. |
| `BATON_DATA_DIR` | Directory of the SQLite database (the image sets `/data`). |
| `BATON_LISTEN_HOST` | Listen address. |
| `BATON_LISTEN_PORT` | Listen port. |
| `BATON_LOG_LEVEL` | Log level. |
| `BATON_TRUST_PROXY_HEADERS` | Take the client address for throttling from the last `X-Forwarded-For` entry; enable only behind a proxy that sets it. Without it, every client behind a proxy shares one address. |
| `BATON_PROXY_USER_HEADER` | Header carrying the authenticated user in `proxy` mode. |
| `BATON_SESSION_DAYS` | Lifetime of a web page session in `key` mode. |
| `BATON_SPOTIFY_API_URL` | Spotify Web API base URL. |
| `BATON_SPOTIFY_ACCOUNTS_URL` | Spotify accounts service base URL. |
| `BATON_SETTLE_DELAY_MS` | Pause after a skip before the fresh state is read. |
| `BATON_THROTTLE_MAX_FAILURES` | Failed attempts within the window that lock a client out of the web page login, and that start slowing down rejected watch keys. |
| `BATON_THROTTLE_WINDOW_SECONDS` | Window in which failures are counted. |
| `BATON_THROTTLE_LOCKOUT_SECONDS` | Length of a login lockout. |
| `BATON_RECENT_PLAYLISTS_CACHE_SECONDS` | How long Spotify's recently played playlists are reused for the playlist list. |
| `BATON_STATE_CACHE_SECONDS` | How long a playback state read answers later requests without asking Spotify. |
| `BATON_SPOTIFY_BUDGET_30S` | Spotify calls in a rolling 30 seconds at which state reads stop and the last known state is answered. |
| `BATON_SPOTIFY_BUDGET_HOUR` | The same for a rolling hour. |

The server refuses to start when a required value is missing or invalid and says which one. Other `BATON_*` variables are ignored, so the service-link variables Kubernetes injects for a Service named `baton` (`BATON_PORT=tcp://…`, `BATON_SERVICE_HOST`, …) do not interfere; that is why the listen settings are called `BATON_LISTEN_HOST` and `BATON_LISTEN_PORT`.

Everything a user changes while the server runs lives in the database and is set through the web page or the API: target playlist, saved, renamed and hidden playlists, default playback device, market and the watch keys with their scope.

Spotify needs a market (a two-letter country code) to say which tracks are playable; the server asks for `from_token`, which Spotify resolves from the login, so nothing has to be set. To pin one anyway, change the stored setting through the API while signed in to the page, for example `PUT /api/ui/settings` with `{"market": "DE"}` (`null` goes back to the login's own).

## Authentication

Two route families, never sharing a credential:

- `/api/watch/` accepts only a valid key (`Authorization: Bearer`). Cookies and identity headers are ignored there, and a key opens nothing outside it. Keys are created on the web page, shown once, stored hashed and revocable. Each key has a scope: a `watch` key (the default, and what every key from before scopes is) opens the watch API; an `agent` key also opens the Spotify relay described in [api.md](api.md#spotify-relay). The scope is chosen when the key is created and can be changed on the page afterwards (`PATCH /api/ui/keys/<id>` with `{"scope": "agent"}` or `"watch"`); the key value stays the same. An agent key is a full Spotify client for the linked account, so give one only to something you trust as much. The key is checked first, so a valid key always works; a client that keeps sending wrong keys is only answered more slowly, never locked out.
- Everything else (web page, `/api/ui/`, settings, keys, Spotify login) is guarded by the auth mode. Only `/healthz` and the icon files (`/favicon.ico`, `/apple-touch-icon.png`, `/static/icon-*.png`, `/static/apple-touch-icon.png`) are open.

Modes:

- `key` (default): `BATON_UI_KEY` is required. The web page exchanges it for an `HttpOnly`, `SameSite=Strict` session cookie (`Secure` on HTTPS installs).
- `proxy`: a reverse proxy in front authenticates users and sets the header named by `BATON_PROXY_USER_HEADER`; requests without a non-empty value are refused. The server trusts the header, so it must be reachable only through the proxy, and the proxy must route `/api/watch/` past its own login (the watch cannot sign in) and strip the header from requests it does not authenticate.

In both modes state-changing calls from the web page must send JSON or the `X-Baton-Request` header, which a cross-site form post cannot do. Repeated wrong keys on the web page login lock that client out for a while; the watch API has its own, separate counter. Sessions are tied to the current `BATON_UI_KEY`: starting the server with a different key signs every browser out.

Request bodies on `/api/ui/` and `/api/watch/` are capped at 16 KiB (`413` above). Logs carry no Spotify request URLs and no query strings, so neither listening history nor OAuth codes end up in them.

## Web page API

The page uses `/api/ui/`: `session`, `login`, `logout`, `status`, `state`, the same command paths as the watch API, `device`, `playlists/recent`, `playlists/<id>/play`, `spotify/playlists`, `spotify/devices`, `spotify/disconnect`, `settings` (including `saved_playlists`, `playlist_names` and `hidden_playlists`) and `keys` (`PATCH keys/<id>` changes a key's scope). It is meant for the page, not as a stable interface. The Spotify login starts with `POST /auth/spotify/login`, which answers `{"url": …}` for the page to open, and ends at the callback `/auth/spotify/callback`. It is a POST so that it passes the same-origin check above and a link on another site cannot start it.

## Development

- `cd server && python -m venv .venv && .venv/bin/pip install -e '.[dev]'`
- `.venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/pytest`
- The tests run against `tests/fake_spotify.py`, a stateful stand-in for Spotify. Run on its own it serves a local instance without a Spotify account: `uvicorn --factory tests.fake_spotify:demo_app --port 9101`, then start the server with `BATON_SPOTIFY_API_URL=http://127.0.0.1:9101/v1`, `BATON_SPOTIFY_ACCOUNTS_URL=http://127.0.0.1:9101` and `BATON_PUBLIC_URL=http://127.0.0.1:8080`.
