# Watch API

The watch app talks to the server through the phone. This is the whole contract; the server and the watch app implement exactly this.

- Base path `/api/watch/`. Every request carries `Authorization: Bearer <watch key>`. No cookies, no identity headers.
- Every response of the watch endpoints below, success or failure, is HTTP 200 with `Content-Type: application/json` and a small body (< 2 KB):
  `{"result": "ok" | "already" | "error", "error": <code or null>, "message": <short human text or null>, "state": <state or null>}`
  Only an invalid/missing watch key gives HTTP 401 (the watch shows "key rejected"). The relay ([below](#spotify-relay)) answers with Spotify's own status, and oversized bodies get `413`.
  - `ok`: the action changed something. `already`: idempotent no-op (track already liked / already in playlist / already absent). `error`: see codes.
  - Error codes: `no_device` (no active Spotify device and the default device is not reachable — "device asleep"), `no_track` (nothing playing, or an episode/ad that cannot be liked), `no_target_playlist` (none configured), `spotify_auth` (Spotify login expired/missing — re-login in the web UI), `spotify_rate_limited`, `spotify_error`, `bad_request`.
- `state` object: `{"is_playing": bool, "title": str|null, "artist": str|null, "progress_ms": int|null, "duration_ms": int|null, "liked": bool|null, "in_playlist": bool|null, "playlist_name": str|null, "device_name": str|null, "server_time_ms": int}`.
  Every command response includes the fresh `state`, so the watch never needs a second request after a press.
- Endpoints (commands are POST without a body):
  - `GET  /api/watch/state`
  - `POST /api/watch/play-pause` — pause if playing, else resume; with no active device, start playback on the default device from the settings.
  - `POST /api/watch/next`
  - `POST /api/watch/previous` — if progress > 5000 ms restart the track (seek 0), else previous track.
  - `POST /api/watch/restart` — start of the current track, wherever it is.
  - `POST /api/watch/previous-track` — previous track, wherever the current one is.
  - `POST /api/watch/like` / `POST /api/watch/unlike` — Liked Songs, contains-check first, never a toggle.
  - `POST /api/watch/playlist/add` / `POST /api/watch/playlist/remove` — the target playlist from the settings, membership check first, never a duplicate.
  - Second release: `GET /api/watch/playlists` → `{"result":"ok","playlists":[{"id","name"}], ...}` Liked Songs first (`id` `liked`), then the ten most recently used playlists (see [below](#playlist-list)); `POST /api/watch/playlists/<id>/play?mode=normal|shuffle|smart` — `smart` falls back to shuffle (Spotify exposes no smart shuffle) and the response says so in `message`.

## Server behaviour beyond the contract

- A rejected key answers `401` with the envelope `{"result": "error", "error": null, "message": "Key rejected.", "state": null}`. The key is checked first: a valid key always works, while a client that keeps sending wrong keys is answered more slowly. Nobody can lock a valid key out.
- Unknown paths and wrong methods are the framework's plain `404` / `405`.
- `state` is `null` when no state is available (login problem, Spotify unreachable). Failed commands such as `no_track` and `no_target_playlist` still carry the state that was read.
- When nothing is active, `GET /state` answers `ok` with `is_playing: false` and every other field `null` (`playlist_name` still shows the configured target).
- `liked` and `in_playlist` are `null` without a likable track; `in_playlist` and `playlist_name` are `null` without a target playlist. Episodes show their title in `state` but are `no_track` for like and playlist actions.
- `play-pause` with no active device looks the default device up by its stored id, then by its stored name, and moves playback there. If it is not listed the answer is `no_device`.
- `play`, `shuffle` and `smart` through `/playlists/<id>/play` set the shuffle state explicitly (`normal` switches shuffle off) and start the playlist on the active device, or on the default device when none is active. A playlist id that is neither `liked` nor 22 alphanumeric characters, or an unknown mode, answers `bad_request`.
- `liked` is Liked Songs and starts like a playlist: the server plays the account's collection context (`spotify:user:<id>:collection`) and, if Spotify refuses that, the newest 50 liked tracks as a plain list. A refusal other than "no active device" is reported as `spotify_error` with Spotify's message.
- Idempotency is decided by a read before every write: `GET /me/library/contains` for likes, the playlist's items for membership (cached per playlist snapshot, so a large playlist is read once per change).
- Commands run one at a time. A press that arrives while another one is running waits and then acts on the state that one left, so a retried or doubled `playlist/add`, `like` or `play-pause` is never applied twice from stale state. `next` and `previous` are not idempotent: each press skips.
- Playlist membership reads the whole playlist, however long, and treats a relinked track (Spotify's `linked_from`) as the same track. If the playlist cannot be read completely the answer is `spotify_error`, never a guess from a partial list.
- See [Staying under Spotify's limits](#staying-under-spotifys-limits) for how often `GET /state` asks Spotify.
- Request bodies are capped at 16 KiB; larger ones get `413`.
- Whatever Spotify sends back, the answer is the envelope above; an unreadable Spotify answer is `spotify_error`.

## Staying under Spotify's limits

Spotify publishes no numbers: it counts calls in a rolling 30 seconds and, for development-mode apps, against a quota shared by the developer account. The server keeps a margin from both.

- `GET /state` costs one Spotify call. Whether the track is liked and on the target and playing playlists is looked up once per track and updated by the server's own commands, so a change made in another app shows with the next track. Whether a playing playlist can be changed is remembered for an hour.
- A state read answers later requests for `BATON_STATE_CACHE_SECONDS`, with `progress_ms` carried forward. A track that has run out is read again at once, and a command's answer replaces the known state.
- Past `BATON_SPOTIFY_BUDGET_30S` or `BATON_SPOTIFY_BUDGET_HOUR` calls, `GET /state` answers the known state until the count has dropped. Commands are never held back by the budget.
- When Spotify answers 429, nothing is sent for the `Retry-After` it names, or for 60 seconds without one (15 minutes for `QUOTA_EXCEEDED`). Meanwhile `GET /state` answers the known state, or `spotify_rate_limited` if there is none. A pause of up to 15 seconds is waited out, so a press answers late instead of failing; during a longer one commands answer `spotify_rate_limited`.
- Each 429 leaves a warning in the log with the path, Spotify's reason, `Retry-After` and the calls made in the last 30 seconds and hour, and the number of calls per hour is logged at info level. That is the way to find the real limit of an account.

## Playlist list

`GET /api/watch/playlists` answers Liked Songs and then at most ten playlists, most recently used first. Each entry is `{"id", "name"}` and nothing else.

- A playlist is *used* when Spotify last played from it, when it was started through the server, or, for a saved playlist, when it was added; the latest of these counts. A saved playlist that was never played therefore sits at the top right after it is added and moves down as other playlists are used. A saved playlist stored without an add time counts as added long ago.
- Spotify's recently played items supply the plays: those that came from a playlist, one entry per playlist (a playlist played with smart shuffle carries a session query on its context URI that is ignored), with names cached, up to 20 playlists that can be named. A playlist started through `/playlists/<id>/play` counts at once, before Spotify has reported it. The recent part is server-cached (`BATON_RECENT_PLAYLISTS_CACHE_SECONDS`).
- A playlist Spotify does not let the login read, such as a personal mix or another Spotify-owned list, has no name to show. A personal mix or editorial list (id starting `37i9dQZF1`) is listed as `Spotify mix (<a track played from it>)` unless a name is set for it; any other unreadable playlist is left out and the list is filled up from older plays.
- Saved playlists are `{id, name, added_at}` entries kept in the settings (at most 10, `added_at` in seconds since the epoch, set by the server). Spotify withholds the playlists it made, and playlists saved from it, from development-mode apps: they are absent from `GET /v1/me/playlists` and their `GET /v1/playlists/<id>` answers 404. Their names therefore come from the user; whether Spotify starts them is decided when one is played.
- `playlist_names` in the settings maps a playlist id to the name shown instead of its own, for saved and recent playlists alike.
- `hidden_playlists` in the settings are `{id, name}` entries (at most 50, the name is the one the playlist had when it was hidden) that never appear in the list. Saving a playlist removes it from them.
- The settings are changed with `PUT /api/ui/settings` (`saved_playlists`, `playlist_names`, `hidden_playlists`; each replaces the stored value as a whole). `GET /api/ui/playlists/recent` returns the same list for the web page with `original` (the name without a rename), `saved` and `hidden` per entry, `fixed` on Liked Songs, and `more`: saved playlists that did not make the list and the hidden ones.

## Additions (backward compatible)

These extend the contract; clients written against the text above keep working unchanged.

- `state.track_id`: `str | null`, the Spotify id of the playing track, `null` when nothing likable is playing. Clients that do not know the field ignore it.
- Optional query parameter `track` on `POST /api/watch/like`, `unlike`, `playlist/add` and `playlist/remove`: the `track_id` of the last state the client showed. If a different track is playing now, nothing is changed and the answer is `{"result": "error", "error": "track_changed", ...}` with the fresh `state`, so the client can show the new track and let the user press again. Without the parameter the commands act on whatever is playing, as before.
- Error code `track_changed`, only ever answered for an anchored request. A client that does not send `track` never sees it.
- `state.playing_playlist_name`: `str | null`, the playlist the track plays from when the login owns it or it is collaborative. `state.in_playing_playlist`: `bool | null`, whether the track is in that playlist. Both are `null` for any other context, including Spotify's own mixes. A smart shuffle session counts as its playlist.
- `POST /api/watch/playing-playlist/add` / `POST /api/watch/playing-playlist/remove`, optionally with `track`: the same check before the write as `playlist/add`, for the playing playlist. `message` names the outcome (`Added to <name>`, `Already in <name>`, `Removed from <name>`, `Not in <name>`). Error codes `no_playing_playlist` (playback does not run from a playlist) and `playlist_not_editable` (it does, but this login may not change it); both change nothing and carry the state.

## Spotify relay

Agent-scope keys (see [server.md](server.md#authentication)) can make any call of the Spotify Web API through the server, which adds its stored Spotify login. Watch-scope keys get `403`; a missing or wrong key gets `401` as everywhere under `/api/watch/`.

- `GET|POST|PUT|DELETE /api/watch/spotify/<path>` is forwarded to `<path>` under the Web API base (`https://api.spotify.com/v1`), with the query string and an optional JSON body. `GET /api/watch/spotify/me/player?market=DE` calls `GET /v1/me/player?market=DE`.
- Spotify's answer comes back unchanged: status, body and `Retry-After`. Nothing else of the exchange is passed on, so the access token is never visible to the caller, and the server does not log it. Every call leaves one log line with the key id, the method, the path without query string and Spotify's status.
- Each path segment may only hold letters, digits, `_`, `:` and `-`. Dots, percent escapes and empty segments are refused with `400`, so a path cannot leave the Web API base. A body that is not JSON is refused with `400`.
- With no usable Spotify login the answer is `409` with `error: "spotify_auth"`; while Spotify has asked for a pause, `429` with `spotify_rate_limited` and a `Retry-After` header with the seconds left; an unreachable Spotify gives `502`. These use the envelope `{"result": "error", "error": ..., "message": ..., "state": null}`.
- The relay does not make Spotify's own limits go away: the app is in development mode, so endpoints Spotify withholds from such apps (for example Spotify-owned playlists) answer as they do for the server itself.

