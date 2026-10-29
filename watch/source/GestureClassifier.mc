import Toybox.Lang;
import Toybox.WatchUi;

// What a physical key gesture means to the app.
module Gesture {
    enum {
        PLAY_PAUSE,
        NEXT,
        PREVIOUS,
        LIKE,
        PLAYLIST_ADD,
        MENU,
        EXIT
    }
}

// Turns raw key pressed/released timing into gestures. The platform delivers no double-press event
// and runs firmware shortcuts on long presses, so only a press with a matching release under
// SHORT_MAX_MS counts; a touch-mapped behaviour or a firmware hold never produces a gesture.
//
//   Start      short                      play/pause
//   Down       short / double             next / previous
//   Up         short / double / hold      like / add to playlist / menu
//   Back       short                      exit
//
// Up and Down have a double-press window, so their single press is emitted only once the window
// has passed without a second press. All timestamps are milliseconds from one monotonic clock and
// are passed in, which keeps the class free of the device clock.
class GestureClassifier {
    // A press longer than this is a hold and does nothing by itself.
    const SHORT_MAX_MS = 600;
    // Time after a first release in which a second press makes a double press.
    const DOUBLE_WINDOW_MS = 380;

    private var _downAt as Dictionary<Number, Number> = {};
    // key -> time at which a lone first tap becomes a single press
    private var _pendingUntil as Dictionary<Number, Number> = {};
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
            // a long second press cancels the first tap as well
            _pendingUntil.remove(key);
            return;
        }
        if (key == WatchUi.KEY_ENTER) {
            _out.add(Gesture.PLAY_PAUSE);
        } else if (key == WatchUi.KEY_ESC) {
            _out.add(Gesture.EXIT);
        } else if (key == WatchUi.KEY_UP || key == WatchUi.KEY_DOWN) {
            if (_pendingUntil.hasKey(key)) {
                _pendingUntil.remove(key);
                _out.add(key == WatchUi.KEY_UP ? Gesture.PLAYLIST_ADD : Gesture.PREVIOUS);
            } else {
                _pendingUntil[key] = now + DOUBLE_WINDOW_MS;
            }
        }
    }

    // The menu behaviour fires while Up is still held. Without Up held it came from touch and is ignored.
    function menuHeld(now as Number) as Void {
        settle(now);
        if (_downAt.hasKey(WatchUi.KEY_UP) && !_menuFired) {
            _menuFired = true;
            _pendingUntil.remove(WatchUi.KEY_UP);
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

    // When a lone first tap becomes a single press, or null when none waits.
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
        _out = [];
        _menuFired = false;
    }

    // Emits the lone taps whose window has passed. A key that is down again is a second press in
    // progress and decides itself on release.
    private function settle(now as Number) as Void {
        var keys = _pendingUntil.keys();
        for (var i = 0; i < keys.size(); i++) {
            var key = keys[i] as Number;
            if (now >= (_pendingUntil[key] as Number) && !_downAt.hasKey(key)) {
                _pendingUntil.remove(key);
                _out.add(key == WatchUi.KEY_UP ? Gesture.LIKE : Gesture.NEXT);
            }
        }
    }
}
