import Toybox.Application;
import Toybox.Lang;
import Toybox.WatchUi;

(:glance)
class BatonApp extends Application.AppBase {
    var controller as Controller? = null;
    private var _fromGlance as Boolean = false;

    function initialize() {
        AppBase.initialize();
    }

    function onStart(state as Dictionary?) as Void {
        _fromGlance = flag(state, :launchedFromGlance);
        Log.line("app", "start fromGlance=" + _fromGlance + " resume=" + flag(state, :resume));
    }

    private function flag(state as Dictionary?, key as Symbol) as Boolean {
        var v = state == null ? null : state[key] as Object?;
        return v instanceof Boolean && v;
    }

    function onStop(state as Dictionary?) as Void {
        Log.line("app", "stop suspend=" + flag(state, :suspend));
    }

    (:typecheck(disableGlanceCheck))
    function onActive(state as Dictionary?) as Void {
        Log.line("app", "active");
        var c = controller;
        if (c != null) {
            c.setActive(true);
        }
    }

    (:typecheck(disableGlanceCheck))
    function onInactive(state as Dictionary?) as Void {
        Log.line("app", "inactive");
        var c = controller;
        if (c != null) {
            c.setActive(false);
        }
    }

    (:typecheck(disableGlanceCheck))
    function getInitialView() as [WatchUi.Views] or [WatchUi.Views, WatchUi.InputDelegates] {
        var c = new Controller();
        controller = c;
        c.launchedFromGlance = _fromGlance;
        c.start();
        return [new MainView(c), new MainDelegate(c)];
    }

    (:glanceView)
    function getGlanceView() as [WatchUi.GlanceView] or [WatchUi.GlanceView, WatchUi.GlanceViewDelegate] or Null {
        return [new BatonGlance()];
    }
}
