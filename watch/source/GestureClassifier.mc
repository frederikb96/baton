import Toybox.Lang;
import Toybox.WatchUi;

// What a physical key gesture means to the app.
module Gesture {
    enum {
        PLAY_PAUSE,
        NEXT,
        RESTART,
        PREVIOUS_TRACK,
        LIKE,
        PLAYLIST_ADD,
        PLAYING_PLAYLIST_ADD,
        MENU,
        EXIT
    }
}

// Turns raw key pressed/released timing into gestures. The platform delivers no multi-press event
// and runs firmware shortcuts on long presses, so only a press with a matching release under
// SHORT_MAX_MS counts; a touch-mapped behaviour or a firmware hold never produces a gesture.
//
//   Start      short                      play/pause
//   Down       short / double / triple    next / start of the track / previous track
//   Up         short / double / triple    like / add to target playlist / add to playing playlist
//   Up         hold                       menu
//   Back       short                      exit
//
// Up and Down have a multi-press window, so a press that can still grow into a longer gesture is
// emitted only once the window has passed without another press. All timestamps are milliseconds from one monotonic clock and
// are passed in, which keeps the class free of the device clock.
class GestureClassifier {
    // A press longer than this is a hold and does nothing by itself.
    const SHORT_MAX_MS = 600;
    // Time after a release in which another press continues the gesture.
    const DOUBLE_WINDOW_MS = 380;
    // The longest multi-press: it needs no window and acts at once.
    const MAX_TAPS = 3;

    private var _downAt as Dictionary<Number, Number> = {};
    // key -> time at which the taps so far become their gesture
    private var _pendingUntil as Dictionary<Number, Number> = {};
    // key -> taps so far
    private var _tapCount as Dictionary<Number, Number> = {};
    private var _out as Array<Number> = [];
    private var _menuFired as Boolean = false;

    function press(key as Number, now as Number) as Void {
        settle(now);
        _downAt[key] = now;
        if (key == WatchUi.KEY_UP) {
            _menuFired = false;
        }
    }

    function release(key as Number, now as Number) as Void {
        settle(now);
        var downAt = _downAt[key] as Number?;
        _downAt.remove(key);
        if (downAt == null) {
            return;
        }
        if (key == WatchUi.KEY_UP && _menuFired) {
            _menuFired = false;
            return;
        }
        var held = now - downAt;
        if (held < 0 || held >= SHORT_MAX_MS) {
            // a long press cancels the taps before it as well
            forget(key);
            return;
        }
        if (key == WatchUi.KEY_ENTER) {
            _out.add(Gesture.PLAY_PAUSE);
        } else if (key == WatchUi.KEY_ESC) {
            _out.add(Gesture.EXIT);
        } else if (key == WatchUi.KEY_UP || key == WatchUi.KEY_DOWN) {
            var taps = _pendingUntil.hasKey(key) ? (_tapCount[key] as Number) + 1 : 1;
            if (taps == MAX_TAPS) {
                forget(key);
                _out.add(key == WatchUi.KEY_UP ? Gesture.PLAYING_PLAYLIST_ADD : Gesture.PREVIOUS_TRACK);
            } else {
                _tapCount[key] = taps;
                _pendingUntil[key] = now + DOUBLE_WINDOW_MS;
            }
        }
    }

    // The menu behaviour fires while Up is still held. Without Up held it came from touch and is ignored.
    function menuHeld(now as Number) as Void {
        settle(now);
        if (_downAt.hasKey(WatchUi.KEY_UP) && !_menuFired) {
            _menuFired = true;
            forget(WatchUi.KEY_UP);
            _out.add(Gesture.MENU);
        }
    }

    // The next finished gesture, or null.
    function take(now as Number) as Number? {
        settle(now);
        if (_out.size() == 0) {
            return null;
        }
        var gesture = _out[0];
        _out = _out.slice(1, null);
        return gesture;
    }

    // When waiting taps become their gesture, or null when none wait.
    function nextDeadline() as Number? {
        var deadline = null;
        var keys = _pendingUntil.keys();
        for (var i = 0; i < keys.size(); i++) {
            var until = _pendingUntil[keys[i]] as Number;
            if (!_downAt.hasKey(keys[i] as Number) && (deadline == null || until < deadline)) {
                deadline = until;
            }
        }
        return deadline;
    }

    function reset() as Void {
        _downAt = {};
        _pendingUntil = {};
        _tapCount = {};
        _out = [];
        _menuFired = false;
    }

    // Emits the taps whose window has passed. A key that is down again is a further press in
    // progress and decides itself on release.
    private function settle(now as Number) as Void {
        var keys = _pendingUntil.keys();
        for (var i = 0; i < keys.size(); i++) {
            var key = keys[i] as Number;
            if (now >= (_pendingUntil[key] as Number) && !_downAt.hasKey(key)) {
                var taps = _tapCount[key] as Number;
                forget(key);
                if (key == WatchUi.KEY_UP) {
                    _out.add(taps == 1 ? Gesture.LIKE : Gesture.PLAYLIST_ADD);
                } else {
                    _out.add(taps == 1 ? Gesture.NEXT : Gesture.RESTART);
                }
            }
        }
    }

    private function forget(key as Number) as Void {
        _pendingUntil.remove(key);
        _tapCount.remove(key);
    }
}
