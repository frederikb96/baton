import Toybox.Lang;
import Toybox.Test;
import Toybox.WatchUi;

// Feeds one key tap (press at `at`, release `held` ms later) and returns the release time.
function tap(c as GestureClassifier, key as Number, at as Number, held as Number) as Number {
    c.press(key, at);
    c.release(key, at + held);
    return at + held;
}

// Everything finished by `now`, in order.
function drain(c as GestureClassifier, now as Number) as Array<Number> {
    var all = [] as Array<Number>;
    var g = c.take(now);
    while (g != null) {
        all.add(g);
        g = c.take(now);
    }
    return all;
}

function sameGestures(got as Array<Number>, want as Array<Number>) as Boolean {
    if (got.size() != want.size()) {
        return false;
    }
    for (var i = 0; i < want.size(); i++) {
        if (got[i] != want[i]) {
            return false;
        }
    }
    return true;
}

(:test)
function startShortIsPlayPauseAtOnce(logger as Logger) as Boolean {
    var c = new GestureClassifier();
    tap(c, WatchUi.KEY_ENTER, 1000, 90);
    return sameGestures(drain(c, 1090), [Gesture.PLAY_PAUSE]);
}

(:test)
function startHoldDoesNothing(logger as Logger) as Boolean {
    var c = new GestureClassifier();
    tap(c, WatchUi.KEY_ENTER, 1000, 1500);
    return sameGestures(drain(c, 5000), []);
}

(:test)
function downSingleWaitsForTheWindow(logger as Logger) as Boolean {
    var c = new GestureClassifier();
    var released = tap(c, WatchUi.KEY_DOWN, 1000, 80);
    var early = drain(c, released + 100);
    var late = drain(c, released + c.DOUBLE_WINDOW_MS);
    return sameGestures(early, []) && sameGestures(late, [Gesture.NEXT])
        && c.nextDeadline() == null;
}

(:test)
function downDoubleIsPreviousOnly(logger as Logger) as Boolean {
    var c = new GestureClassifier();
    var released = tap(c, WatchUi.KEY_DOWN, 1000, 80);
    released = tap(c, WatchUi.KEY_DOWN, released + 150, 80);
    return sameGestures(drain(c, released + 2000), [Gesture.PREVIOUS]);
}

(:test)
function downTripleIsPreviousThenNext(logger as Logger) as Boolean {
    var c = new GestureClassifier();
    var released = tap(c, WatchUi.KEY_DOWN, 1000, 80);
    released = tap(c, WatchUi.KEY_DOWN, released + 100, 80);
    released = tap(c, WatchUi.KEY_DOWN, released + 100, 80);
    return sameGestures(drain(c, released + 2000), [Gesture.PREVIOUS, Gesture.NEXT]);
}

(:test)
function slowSecondTapIsTwoSingles(logger as Logger) as Boolean {
    var c = new GestureClassifier();
    var released = tap(c, WatchUi.KEY_DOWN, 1000, 80);
    tap(c, WatchUi.KEY_DOWN, released + c.DOUBLE_WINDOW_MS + 50, 80);
    return sameGestures(drain(c, 10000), [Gesture.NEXT, Gesture.NEXT]);
}

(:test)
function secondTapStartedInWindowCountsEvenIfReleasedLate(logger as Logger) as Boolean {
    var c = new GestureClassifier();
    var released = tap(c, WatchUi.KEY_DOWN, 1000, 80);
    tap(c, WatchUi.KEY_DOWN, released + c.DOUBLE_WINDOW_MS - 20, 300);
    return sameGestures(drain(c, 10000), [Gesture.PREVIOUS]);
}

(:test)
function upSingleAndDouble(logger as Logger) as Boolean {
    var single = new GestureClassifier();
    tap(single, WatchUi.KEY_UP, 1000, 80);
    var double = new GestureClassifier();
    var released = tap(double, WatchUi.KEY_UP, 1000, 80);
    released = tap(double, WatchUi.KEY_UP, released + 120, 80);
    return sameGestures(drain(single, 5000), [Gesture.LIKE])
        && sameGestures(drain(double, 5000), [Gesture.PLAYLIST_ADD]);
}

(:test)
function upHoldOpensMenuAndItsReleaseIsIgnored(logger as Logger) as Boolean {
    var c = new GestureClassifier();
    c.press(WatchUi.KEY_UP, 1000);
    c.menuHeld(2000);
    c.release(WatchUi.KEY_UP, 2300);
    return sameGestures(drain(c, 9000), [Gesture.MENU]) && c.nextDeadline() == null;
}

(:test)
function upHoldAfterATapDropsTheTap(logger as Logger) as Boolean {
    var c = new GestureClassifier();
    var released = tap(c, WatchUi.KEY_UP, 1000, 80);
    c.press(WatchUi.KEY_UP, released + 100);
    c.menuHeld(released + 1100);
    c.release(WatchUi.KEY_UP, released + 1500);
    return sameGestures(drain(c, 9000), [Gesture.MENU]);
}

(:test)
function upHeldTooShortForMenuDoesNothing(logger as Logger) as Boolean {
    var c = new GestureClassifier();
    tap(c, WatchUi.KEY_UP, 1000, 800);
    return sameGestures(drain(c, 9000), []);
}

(:test)
function menuWithoutUpHeldIsTouchAndIgnored(logger as Logger) as Boolean {
    var c = new GestureClassifier();
    c.menuHeld(1000);
    return sameGestures(drain(c, 9000), []);
}

(:test)
function releaseWithoutPressDoesNothing(logger as Logger) as Boolean {
    var c = new GestureClassifier();
    c.release(WatchUi.KEY_ENTER, 1000);
    c.release(WatchUi.KEY_DOWN, 1100);
    c.release(WatchUi.KEY_ESC, 1200);
    return sameGestures(drain(c, 9000), []);
}

(:test)
function pressWithoutReleaseIsReplacedByTheNextPress(logger as Logger) as Boolean {
    var c = new GestureClassifier();
    c.press(WatchUi.KEY_ENTER, 1000);
    tap(c, WatchUi.KEY_ENTER, 9000, 100);
    return sameGestures(drain(c, 9100), [Gesture.PLAY_PAUSE]);
}

(:test)
function backShortExitsBackHoldDoesNot(logger as Logger) as Boolean {
    var c = new GestureClassifier();
    tap(c, WatchUi.KEY_ESC, 1000, 100);
    var exit = drain(c, 1100);
    tap(c, WatchUi.KEY_ESC, 5000, 1200);
    return sameGestures(exit, [Gesture.EXIT]) && sameGestures(drain(c, 9000), []);
}

(:test)
function touchMappedBehavioursProduceNoKeyEvents(logger as Logger) as Boolean {
    // A swipe or tap arrives as behaviours only: no key press, no key release.
    var c = new GestureClassifier();
    return sameGestures(drain(c, 1000), []) && c.nextDeadline() == null;
}

(:test)
function independentKeysDoNotMix(logger as Logger) as Boolean {
    var c = new GestureClassifier();
    var released = tap(c, WatchUi.KEY_DOWN, 1000, 80);
    released = tap(c, WatchUi.KEY_UP, released + 100, 80);
    return sameGestures(drain(c, released + 2000), [Gesture.NEXT, Gesture.LIKE]);
}

(:test)
function deadlineTracksTheEarliestLoneTap(logger as Logger) as Boolean {
    var c = new GestureClassifier();
    var released = tap(c, WatchUi.KEY_DOWN, 1000, 80);
    return c.nextDeadline() == released + c.DOUBLE_WINDOW_MS;
}
