# Watch app

A Connect IQ app that controls Spotify through the baton server, built to be used without looking: gloves on, watch on the handlebar. It talks to the server over HTTPS through the phone's Garmin Connect app (`docs/api.md` is the contract), so the phone only needs to be paired and Garmin Connect running.

Supported devices are the products in `watch/manifest.xml`: the fēnix 8 family, epix 2 Pro 47 mm, Forerunner 265 and 965. The screen layout follows the display size.

## Controls

Every press is safe to repeat: like and playlist add never toggle, and a command that finds nothing to do answers `already`.

| Button | Press | Action |
|---|---|---|
| Start | short | play / pause |
| Down | short | next track |
| Down | double | previous track (restart when more than 5 s in) |
| Up | short | add to Liked Songs |
| Up | double | add to the target playlist |
| Up | hold ~1 s | menu |
| Back | short | exit the app |

The menu opens on *Remove like*, so Up-hold then Start removes the like; the second entry removes the track from the target playlist, the third lists recently played playlists to start normally, shuffled or with smart shuffle (plain shuffle where Spotify has no smart shuffle). Choosing an entry returns to the main screen; an untouched menu closes after 8 seconds.

Like, add and remove carry the id of the track the screen showed; if another song plays by the time the server gets the request it refuses ("Song changed", error vibration) and the state is refreshed.

Actions fire on release of a press shorter than 0.6 s. Longer presses, the touch screen and the watch's own hold shortcuts (voice control, music controls, recent apps) trigger nothing in the app. Up and Down wait 0.4 s for a second press before acting.

## Vibration

The server's answer decides the pattern, not the press:

| Pattern | Meaning |
|---|---|
| one short pulse | done |
| two very short pulses | already so (idempotent no-op) |
| one long pulse | error: no phone, no connection, key rejected, Spotify problem |
| three ticks | menu opened |

## Screen

Progress ring around the edge, title and artist in the middle, the time at the bottom, a hint glyph beside each button (pause/play at Start, skip at Down, heart and menu dots at Up; the heart is red for a liked track) and the target playlist, green when the track is in it. The last command's result shows for a moment in the same place. Standing problems replace the track: no phone, no connection to the server, device asleep (no active Spotify device), Spotify login expired, watch key rejected, nothing playing.

The app polls the server every 10 seconds and every command answer carries the fresh state; the ring advances locally in between. At most one request is in flight. With no phone connected nothing is sent.

## Launching

- From the app list (Start, then Down to the app). It never closes by itself; moving it to the top of the list saves presses.
- From the glance list the entry shows `artist - title`. An app opened from there is closed by the watch after a couple of minutes without a button press, and shows "Closes when idle".

## Build and install

You need the [Connect IQ SDK](https://developer.garmin.com/connect-iq/sdk/) with the device files and a developer key.

```sh
cd watch
BATON_URL=https://baton.example.com BATON_WATCH_KEY=<key> ./configure
monkeyc -f monkey.jungle -d fenix8solar47mm -o bin/baton.prg -y developer_key.der -w
```

`configure` writes `config/Config.mc`, which is compiled into the app and not tracked; without it the build fails with `Undefined symbol ':Config'` in `ServerConfig.mc`. `config/Config.mc.example` shows the shape. The key is readable inside the `.prg`, so treat the file like the key. Watch keys are created in the server's web page.

Copy `bin/baton.prg` to `GARMIN/Apps` on the watch over USB. The file name is the app's name on the watch, so it has to be unique there.

## Device log

Create an empty file `GARMIN/APPS/LOGS/BATON.TXT` (named like the `.prg`) on the watch to turn logging on. The app then writes one line per event: key presses and releases, recognised gestures, requests with status and round-trip time, vibration patterns, status changes and lifecycle (`start` with launch source, `active`, `inactive`, `stop`). Neither the key nor request headers are logged. Crashes are in `GARMIN/APPS/LOGS/CIQ_LOG.YAML`.

## Develop

- `monkeyc -t` builds the unit tests, `monkeydo bin/test.prg <device> -t` runs them in the simulator. They cover the key classifier, response parsing, status and vibration choice and text fitting.
- A build with a glance view starts the simulator in glance mode. `preview.jungle` leaves the glance out, so the simulator opens the app itself: add `-f preview.jungle`.
- `tools/stub-server.ts` (Bun) stands in for the server: `WATCH_KEY=<key> SCENARIO=playing bun tools/stub-server.ts`, scenarios `playing`, `paused`, `asleep`, `auth`, `notrack`, `rejected`, switchable while running with `GET /__stub/scenario?name=<scenario>`. Point `Config.mc` at it and, in the simulator, switch off *Settings > Use Device HTTPS Requirements* for a plain `http://` address.
- The CI workflow (`.github/workflows/watch.yml`) compiles with a throwaway key and runs the tests for every manifest product; it needs neither the SDK files nor the developer key in the repository.
