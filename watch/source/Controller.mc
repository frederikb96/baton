import Toybox.Application;
import Toybox.Lang;
import Toybox.System;
import Toybox.Timer;
import Toybox.WatchUi;

// Ties key gestures, the server client, the vibration feedback and the screen state together.
class Controller {
    // how long a result text stays on screen
    const TOAST_MS = 2500;
    // an opened menu closes by itself, so a stray hold cannot leave a remove action under Start
    const MENU_TIMEOUT_MS = 8000;

    var state as PlayerState? = null;
    var toast as String? = null;
    var launchedFromGlance as Boolean = false;

    private var _classifier as GestureClassifier = new GestureClassifier();
    private var _api as ApiClient;
    private var _tickTimer as Timer.Timer = new Timer.Timer();
    private var _windowTimer as Timer.Timer = new Timer.Timer();
    private var _stateAt as Number = 0;
    private var _toastUntil as Number = 0;
    private var _problem as Number? = null;
    private var _active as Boolean = true;
    private var _menuDepth as Number = 0;
    private var _menuUntil as Number = 0;
    private var _playlistsHandler as Method(outcome as Outcome) as Void? = null;
    private var _lastMinute as Number = -1;
    private var _lastHeadline as String? = null;
    private var _lastStatus as Number = -1;

    function initialize() {
        _api = new ApiClient(method(:onOutcome));
    }

    function start() as Void {
        _tickTimer.start(method(:onTick), 1000, true);
        _api.tick(System.getTimer(), true);
    }

    function stop() as Void {
        _tickTimer.stop();
        _windowTimer.stop();
    }

    function setActive(active as Boolean) as Void {
        _active = active;
        if (active) {
            _api.pollSoon();
        }
    }

    // What the screen shows.
    function status() as Number {
        return Status.of(_api.phoneConnected(), _problem, state);
    }

    // Playback position now: the last answer plus the time since it, while playing.
    function progressMs() as Number? {
        var s = state;
        if (s == null || s.progressMs == null) {
            return null;
        }
        var progress = s.progressMs as Number;
        if (s.isPlaying && status() == Status.PLAYING) {
            progress += System.getTimer() - _stateAt;
        }
        var duration = s.durationMs;
        if (duration != null && progress > duration) {
            progress = duration;
        }
        return progress;
    }

    // ---- keys ----

    function keyPressed(key as Number) as Void {
        var now = System.getTimer();
        Log.line("key", "pressed " + key);
        _classifier.press(key, now);
    }

    function keyReleased(key as Number) as Void {
        var now = System.getTimer();
        Log.line("key", "released " + key);
        _classifier.release(key, now);
        afterInput(now);
    }

    function menuHeld() as Void {
        var now = System.getTimer();
        Log.line("key", "menu hold");
        _classifier.menuHeld(now);
        afterInput(now);
    }

    function onWindow() as Void {
        afterInput(System.getTimer());
    }

    private function afterInput(now as Number) as Void {
        var gesture = _classifier.take(now);
        while (gesture != null) {
            dispatch(gesture);
            gesture = _classifier.take(now);
        }
        _windowTimer.stop();
        var deadline = _classifier.nextDeadline();
        if (deadline != null) {
            // Timer needs at least 50 ms
            var wait = deadline - now + 10;
            _windowTimer.start(method(:onWindow), wait < 50 ? 50 : wait, false);
        }
    }

    private function dispatch(gesture as Number) as Void {
        Log.line("gesture", gesture.toString());
        if (gesture == Gesture.PLAY_PAUSE) {
            send(Command.playPause());
        } else if (gesture == Gesture.NEXT) {
            send(Command.next());
        } else if (gesture == Gesture.PREVIOUS) {
            send(Command.previous());
        } else if (gesture == Gesture.LIKE) {
            send(Command.like(trackId()));
        } else if (gesture == Gesture.PLAYLIST_ADD) {
            send(Command.playlistAdd(trackId()));
        } else if (gesture == Gesture.MENU) {
            openMenu();
        } else if (gesture == Gesture.EXIT) {
            System.exit();
        }
    }

    // ---- commands ----

    function trackId() as String? {
        var s = state;
        return s == null ? null : s.trackId;
    }

    function send(request as Request) as Void {
        showToast(request.pendingText);
        _api.command(request, System.getTimer());
    }

    function onOutcome(request as Request, outcome as Outcome) as Void {
        var now = System.getTimer();
        if (outcome.state != null) {
            state = outcome.state;
            _stateAt = now;
            rememberForGlance();
        }
        if (!"busy".equals(outcome.code)) {
            _problem = Status.problemFor(outcome);
        }
        if ("track_changed".equals(outcome.code)) {
            _api.pollSoon();
        }
        if (request.isCommand) {
            Haptics.play(Haptics.forResult(outcome.kind));
            showToast(Status.toastFor(request, outcome));
        }
        if (_playlistsHandler != null && request.path.equals(Command.playlists().path)) {
            var handler = _playlistsHandler as Method(outcome as Outcome) as Void;
            _playlistsHandler = null;
            handler.invoke(outcome);
        }
        WatchUi.requestUpdate();
    }

    function showMessage(text as String) as Void {
        showToast(text);
    }

    private function showToast(text as String) as Void {
        toast = text.length() > 0 ? text : null;
        _toastUntil = System.getTimer() + TOAST_MS;
        WatchUi.requestUpdate();
    }

    // The glance shows the last track the app knew.
    private function rememberForGlance() as Void {
        var s = state;
        var headline = s == null ? null : s.headline();
        if (headline != null && !headline.equals(_lastHeadline)) {
            _lastHeadline = headline;
            Application.Storage.setValue(GlanceModel.STORAGE_KEY, headline);
        }
    }

    // ---- menu ----

    function openMenu() as Void {
        _classifier.reset();
        Haptics.play(Haptics.MENU);
        _menuDepth = 1;
        _menuUntil = System.getTimer() + MENU_TIMEOUT_MS;
        MenuFlow.openRoot();
    }

    // A deeper menu level was pushed.
    function menuDeeper() as Void {
        _menuDepth += 1;
        _menuUntil = System.getTimer() + MENU_TIMEOUT_MS;
    }

    // The menu delegate popped itself.
    function menuLeft(levels as Number) as Void {
        _menuDepth = _menuDepth > levels ? _menuDepth - levels : 0;
    }

    // Back to the main screen from any menu depth.
    function closeMenus() as Void {
        while (_menuDepth > 0) {
            _menuDepth -= 1;
            WatchUi.popView(WatchUi.SLIDE_IMMEDIATE);
        }
        _classifier.reset();
    }

    function requestPlaylists(handler as Method(outcome as Outcome) as Void) as Void {
        _playlistsHandler = handler;
        _api.command(Command.playlists(), System.getTimer());
    }

    // ---- clock ----

    function onTick() as Void {
        var now = System.getTimer();
        _api.tick(now, _active);
        if (_menuDepth > 0 && now > _menuUntil) {
            closeMenus();
        }
        var stale = toast != null && now > _toastUntil;
        if (stale) {
            toast = null;
        }
        var status = status();
        if (status != _lastStatus) {
            _lastStatus = status;
            Log.line("ctl", "status " + status + " phone=" + _api.phoneConnected());
            WatchUi.requestUpdate();
        }
        var minute = System.getClockTime().min;
        var s = state;
        var progress = progressMs();
        if (s != null && s.isPlaying && progress != null && s.durationMs != null && progress >= (s.durationMs as Number)
            && now - _stateAt > 1500) {
            // the track has run out: the next one is probably playing
            _api.pollSoon();
        }
        if (stale || minute != _lastMinute || (s != null && s.isPlaying && status() == Status.PLAYING)) {
            _lastMinute = minute;
            WatchUi.requestUpdate();
        }
    }
}
