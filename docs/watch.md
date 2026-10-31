# Watch app

A Connect IQ app that controls Spotify through the baton server, built to be used without looking: gloves on, watch on the handlebar. It talks to the server over HTTPS through the phone's Garmin Connect app (`docs/api.md` is the contract), so the phone only needs to be paired and Garmin Connect running.

Supported devices are the products in `watch/manifest.xml`: the fēnix 8 family, epix 2 Pro 47 mm, Forerunner 265 and 965. The screen layout follows the display size.

## Controls

Every press is safe to repeat: like and playlist add never toggle, and a command that finds nothing to do answers `already`.

| Button | Press | Action |
|---|---|---|
| Start | short | play / pause |
| Down | short | next track |
| Down | double | start of the current track |
| Down | triple | previous track |
| Up | short | add to Liked Songs |
| Up | double | add to the target playlist |
| Up | hold ~0.6 s | menu |
| Back | short | exit the app |

The menu opens on *Remove like*, so Up-hold then Start removes the like; the second entry (*Off playlist*) removes the track from the target playlist, the third (*Playlists*) lists Liked Songs and the ten playlists used last to start normally, shuffled or with smart shuffle (plain shuffle where Spotify has no smart shuffle). Choosing an entry returns to the main screen; an untouched menu closes after 8 seconds.

Like, add and remove carry the id of the track the screen showed; if another song plays by the time the server gets the request it refuses ("Song changed", error vibration) and the state is refreshed.

Actions fire on release of a press shorter than 0.6 s. Apart from the Up hold that opens the menu, longer presses, the touch screen and the watch's own hold shortcuts (voice control, music controls, recent apps) trigger nothing in the app. Up and Down wait 0.4 s for another press before acting, so a double press on Down acts 0.4 s after its last release and a triple press at once.

## Vibration

What you hear needs no confirmation: play/pause, next, previous, restart and starting a playlist vibrate only on an error. Like, playlist add and their removals vibrate either way, and the server's answer decides the pattern:

| Pattern | Meaning |
|---|---|
| one short pulse | done |
| two very short pulses | already so (idempotent no-op) |
| one long pulse | error: no phone, no connection, key rejected, Spotify problem |
| three ticks | menu opened |

## Screen

Progress ring around the edge, title and artist in the middle, the time at the bottom, a hint glyph beside each button (pause/play at Start, skip at Down, heart and menu dots at Up; the heart is red for a liked track) and the target playlist, green when the track is in it. The last command's result shows for a moment in the same place. Standing problems replace the track: no phone, no connection to the server (with the error code and the address tried), device asleep (no active Spotify device), Spotify login expired, watch key rejected, nothing playing.

The app saves battery and Spotify calls by pacing itself. For 60 seconds after a button press or after the app comes to the foreground it runs at full pace: a poll every 20 seconds and the ring redrawn every second. Untouched, it settles to a slow pace: a poll every 5 minutes (it catches a change made on the phone, which therefore shows late; a track that has run out is polled at once, so the next song appears on time, and ever more rarely while the answer still shows it) and, while playing, a redraw every 5 seconds. Every command answer carries the fresh state and a poll follows a button press that wakes the app after a quiet spell. The ring advances locally between answers. At most one request is in flight. With no phone connected nothing is sent. The intervals are the constants in `source/Pacing.mc`.

## Launching

- From the app list (Start, then Down to the app). It never closes by itself; moving it to the top of the list saves presses.
- From the glance list the entry shows `artist - title`. An app opened from there is closed by the watch after a couple of minutes without a button press, and shows "Closes when idle".

## Settings

The app needs the address of your server and a watch key, created in the server's web page. In Garmin Connect on the phone, open the watch's Connect IQ apps, choose Baton and fill in *Server URL* and *Watch key*. The key travels through Garmin's app settings, so revoke it on the server if you stop using the app. Until both are set the watch shows "Set up on phone" and sends nothing; a change arrives while the app runs and takes effect at once.

## Install

The app is on its way to the Connect IQ Store. A store install gets its settings as described above.

## Build locally

You need the [Connect IQ SDK](https://developer.garmin.com/connect-iq/sdk/) with the device files and a developer key. A build copied over USB has no settings page in Garmin Connect, so `local.jungle` bakes the URL and key into the app as its default settings:

```sh
cd watch
BATON_URL=https://baton.example.com BATON_WATCH_KEY=<key> ./configure
monkeyc -f local.jungle -d fenix8solar47mm -o bin/baton.prg -y developer_key.der -w
```

`configure` writes `config/properties.xml`, which is not tracked. The key is readable inside the `.prg`, so treat the file like the key.

Copy `bin/baton.prg` to `GARMIN/Apps` on the watch over USB. The file name is the app's name on the watch, so it has to be unique there.

`monkey.jungle` builds the same app with empty settings, which is what a store package needs.

## Device log

Create an empty file `GARMIN/APPS/LOGS/BATON.TXT` (named like the `.prg`) on the watch to turn logging on. The app then writes one line per event: key presses and releases, recognised gestures, requests with status and round-trip time, vibration patterns, status changes and lifecycle (`start` with launch source, `active`, `inactive`, `stop`). The battery level in percent is logged at start, every 5 minutes and at stop (`battery level 87.00%`), so the log of a ride shows the drain per hour. Neither the key nor request headers are logged. Crashes are in `GARMIN/APPS/LOGS/CIQ_LOG.YAML`.

## Develop

- `monkeyc -t` builds the unit tests, `monkeydo bin/test.prg <device> -t` runs them in the simulator. They cover the key classifier, the settings, response parsing, status and vibration choice, poll and redraw pacing and text fitting.
- A build with a glance view starts the simulator in glance mode. `preview.jungle` is a local build without the glance, so the simulator opens the app itself: run `configure`, then add `-f preview.jungle`.
- `tools/stub-server.ts` (Bun) stands in for the server: `WATCH_KEY=<key> SCENARIO=playing bun tools/stub-server.ts`, scenarios `playing`, `paused`, `asleep`, `auth`, `notrack`, `rejected`, switchable while running with `GET /__stub/scenario?name=<scenario>`. Point `configure` at it and, in the simulator, switch off *Settings > Use Device HTTPS Requirements* for a plain `http://` address.
- The CI workflow (`.github/workflows/watch.yml`) compiles with a throwaway key and runs the tests for every manifest product; it needs neither the SDK files nor the developer key in the repository.
