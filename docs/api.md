# Watch API

The watch app talks to the server through the phone. This is the whole contract; the server and the watch app implement exactly this.

- Base path `/api/watch/`. Every request carries `Authorization: Bearer <watch key>`. No cookies, no identity headers.
- Every response, success or failure, is HTTP 200 with `Content-Type: application/json` and a small body (< 2 KB):
  `{"result": "ok" | "already" | "error", "error": <code or null>, "message": <short human text or null>, "state": <state or null>}`
  Only an invalid/missing watch key gives HTTP 401 (the watch shows "key rejected").
  - `ok`: the action changed something. `already`: idempotent no-op (track already liked / already in playlist / already absent). `error`: see codes.
  - Error codes: `no_device` (no active Spotify device and the default device is not reachable — "device asleep"), `no_track` (nothing playing, or an episode/ad that cannot be liked), `no_target_playlist` (none configured), `spotify_auth` (Spotify login expired/missing — re-login in the web UI), `spotify_rate_limited`, `spotify_error`, `bad_request`.
- `state` object: `{"is_playing": bool, "title": str|null, "artist": str|null, "progress_ms": int|null, "duration_ms": int|null, "liked": bool|null, "in_playlist": bool|null, "playlist_name": str|null, "device_name": str|null, "server_time_ms": int}`.
  Every command response includes the fresh `state`, so the watch never needs a second request after a press.
- Endpoints (commands are POST without a body):
  - `GET  /api/watch/state`
  - `POST /api/watch/play-pause` — pause if playing, else resume; with no active device, start playback on the default device from the settings.
  - `POST /api/watch/next`
  - `POST /api/watch/previous` — if progress > 5000 ms restart the track (seek 0), else previous track.
  - `POST /api/watch/like` / `POST /api/watch/unlike` — Liked Songs, contains-check first, never a toggle.
  - `POST /api/watch/playlist/add` / `POST /api/watch/playlist/remove` — the target playlist from the settings, membership check first, never a duplicate.
  - Second release: `GET /api/watch/playlists` → `{"result":"ok","playlists":[{"id","name"}], ...}` most recently played first (max 15, server-cached); `POST /api/watch/playlists/<id>/play?mode=normal|shuffle|smart` — `smart` falls back to shuffle (Spotify exposes no smart shuffle) and the response says so in `message`.

## Server behaviour beyond the contract

- A rejected key answers `401` with the envelope `{"result": "error", "error": null, "message": "Key rejected.", "state": null}`. The key is checked first: a valid key always works, while a client that keeps sending wrong keys is answered more slowly. Nobody can lock a valid key out.
- Unknown paths and wrong methods are the framework's plain `404` / `405`.
- `state` is `null` when no state is available (login problem, Spotify unreachable). Failed commands such as `no_track` and `no_target_playlist` still carry the state that was read.
- When nothing is active, `GET /state` answers `ok` with `is_playing: false` and every other field `null` (`playlist_name` still shows the configured target).
- `liked` and `in_playlist` are `null` without a likable track; `in_playlist` and `playlist_name` are `null` without a target playlist. Episodes show their title in `state` but are `no_track` for like and playlist actions.
- `play-pause` with no active device looks the default device up by its stored id, then by its stored name, and moves playback there. If it is not listed the answer is `no_device`.
- `play`, `shuffle` and `smart` through `/playlists/<id>/play` set the shuffle state explicitly (`normal` switches shuffle off) and start the playlist on the active device, or on the default device when none is active. A playlist id that is not alphanumeric or an unknown mode answers `bad_request`.
- The recent playlists come from Spotify's recently played items that were played from a playlist, one entry per playlist (a playlist played with smart shuffle carries a session query on its context URI that is ignored), with names cached. A playlist Spotify does not let the login read, such as a personal mix or another Spotify-owned list, has no name to show and is left out; the list is filled up from older plays instead, up to 15.
- Idempotency is decided by a read before every write: `GET /me/library/contains` for likes, the playlist's items for membership (cached per playlist snapshot, so a large playlist is read once per change).
- Commands run one at a time. A press that arrives while another one is running waits and then acts on the state that one left, so a retried or doubled `playlist/add`, `like` or `play-pause` is never applied twice from stale state. `next` and `previous` are not idempotent: each press skips.
- Playlist membership reads the whole playlist, however long, and treats a relinked track (Spotify's `linked_from`) as the same track. If the playlist cannot be read completely the answer is `spotify_error`, never a guess from a partial list.
- `GET /state` is shared between requests that arrive together or right after each other (about a second, `BATON_STATE_CACHE_SECONDS`); every command invalidates it. When Spotify answers 429 with `Retry-After`, further Spotify calls are answered `spotify_rate_limited` until that pause has passed (capped at five minutes).
- Request bodies are capped at 16 KiB; larger ones get `413`.
- Whatever Spotify sends back, the answer is the envelope above; an unreadable Spotify answer is `spotify_error`.

## Additions (backward compatible)

These extend the contract; clients written against the text above keep working unchanged.

- `state.track_id`: `str | null`, the Spotify id of the playing track, `null` when nothing likable is playing. Clients that do not know the field ignore it.
- Optional query parameter `track` on `POST /api/watch/like`, `unlike`, `playlist/add` and `playlist/remove`: the `track_id` of the last state the client showed. If a different track is playing now, nothing is changed and the answer is `{"result": "error", "error": "track_changed", ...}` with the fresh `state`, so the client can show the new track and let the user press again. Without the parameter the commands act on whatever is playing, as before.
- Error code `track_changed`, only ever answered for an anchored request. A client that does not send `track` never sees it.

## Spotify relay

Agent-scope keys (see [server.md](server.md#authentication)) can make any call of the Spotify Web API through the server, which adds its stored Spotify login. Watch-scope keys get `403`; a missing or wrong key gets `401` as everywhere under `/api/watch/`.

- `GET|POST|PUT|DELETE /api/watch/spotify/<path>` is forwarded to `<path>` under the Web API base (`https://api.spotify.com/v1`), with the query string and an optional JSON body. `GET /api/watch/spotify/me/player?market=DE` calls `GET /v1/me/player?market=DE`.
- Spotify's answer comes back unchanged: status, body and `Retry-After`. Nothing else of the exchange is passed on, so the access token is never visible to the caller, and the server does not log it.
- Each path segment may only hold letters, digits, `_`, `:` and `-`. Dots, percent escapes and empty segments are refused with `400`, so a path cannot leave the Web API base. A body that is not JSON is refused with `400`.
- With no usable Spotify login the answer is `409` with `error: "spotify_auth"`; while Spotify has asked for a pause, `429` with `spotify_rate_limited`; an unreachable Spotify gives `502`. These use the envelope `{"result": "error", "error": ..., "message": ..., "state": null}`.
- The relay does not make Spotify's own limits go away: the app is in development mode, so endpoints Spotify withholds from such apps (for example Spotify-owned playlists) answer as they do for the server itself.

