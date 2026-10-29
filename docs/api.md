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

- A rejected key answers `401` with the envelope `{"result": "error", "error": null, "message": "Key rejected.", "state": null}`. A client that keeps sending wrong keys is locked out for a while and gets the same `401` (`"Too many failed attempts. Try again later."`), even with a correct key.
- Unknown paths and wrong methods are the framework's plain `404` / `405`.
- `state` is `null` when no state is available (login problem, Spotify unreachable). Failed commands such as `no_track` and `no_target_playlist` still carry the state that was read.
- When nothing is active, `GET /state` answers `ok` with `is_playing: false` and every other field `null` (`playlist_name` still shows the configured target).
- `liked` and `in_playlist` are `null` without a likable track; `in_playlist` and `playlist_name` are `null` without a target playlist. Episodes show their title in `state` but are `no_track` for like and playlist actions.
- `play-pause` with no active device looks the default device up by its stored id, then by its stored name, and moves playback there. If it is not listed the answer is `no_device`.
- `play`, `shuffle` and `smart` through `/playlists/<id>/play` set the shuffle state explicitly (`normal` switches shuffle off) and start the playlist on the active device, or on the default device when none is active. A playlist id that is not alphanumeric or an unknown mode answers `bad_request`.
- The recent playlists come from Spotify's recently played items that were played from a playlist, deduplicated, with names cached. A playlist whose name cannot be read is listed as `Unnamed playlist`.
- Idempotency is decided by a read before every write: `GET /me/library/contains` for likes, the playlist's items for membership (cached per playlist snapshot, so a large playlist is read once per change).
