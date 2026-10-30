import Toybox.Lang;

// How often the app wakes the phone link and the display. Every poll is a Bluetooth web request
// through the phone and every redraw costs display and CPU time, so both stay as rare as the
// screen can bear: between answers the ring is interpolated, and a track that has run out forces
// an immediate poll. While the user is handling the watch (a key press, the app coming to the
// foreground) it runs at full pace for a window; untouched, it settles to the slow pace.
module Pacing {
    // how long after the last input the app keeps the full pace
    const ACTIVE_WINDOW_MS = 90000;
    // full pace: poll and ring redraw
    const POLL_ACTIVE_MS = 10000;
    const REDRAW_ACTIVE_MS = 1000;
    // slow pace, playing: the poll only catches a change made elsewhere (skip or seek on the phone)
    const POLL_PLAYING_MS = 30000;
    // slow pace, paused, nothing playing, device asleep or any other standing problem
    const POLL_IDLE_MS = 60000;
    // slow pace, playing: the ring and the clock redraw this often unless something else changed
    const REDRAW_PLAYING_MS = 5000;
    // battery level lines in the log
    const BATTERY_LOG_MS = 300000;

    function pollIntervalMs(status as Number, active as Boolean) as Number {
        if (active) {
            return POLL_ACTIVE_MS;
        }
        return status == Status.PLAYING ? POLL_PLAYING_MS : POLL_IDLE_MS;
    }

    function pollDue(soon as Boolean, now as Number, lastAnswerAt as Number, intervalMs as Number) as Boolean {
        return soon || now - lastAnswerAt >= intervalMs;
    }

    function redrawDue(status as Number, active as Boolean, now as Number, lastDrawAt as Number) as Boolean {
        return status == Status.PLAYING && now - lastDrawAt >= (active ? REDRAW_ACTIVE_MS : REDRAW_PLAYING_MS);
    }
}
