import Toybox.Application;
import Toybox.Graphics;
import Toybox.Lang;
import Toybox.Timer;
import Toybox.WatchUi;

// The glance-list entry: "Artist - Title" of what plays. It starts from the last track the app
// remembered and refreshes from the server while it is on screen.
(:glance, :glanceView)
class BatonGlance extends WatchUi.GlanceView {
    const REFRESH_MS = 10000;

    private var _text as String;
    private var _timer as Timer.Timer = new Timer.Timer();

    function initialize() {
        GlanceView.initialize();
        var remembered = Application.Storage.getValue(GlanceModel.STORAGE_KEY);
        _text = remembered instanceof String ? remembered : "Baton";
    }

    function onShow() as Void {
        refresh();
        _timer.start(method(:refresh), REFRESH_MS, true);
    }

    function onHide() as Void {
        _timer.stop();
    }

    function refresh() as Void {
        Wire.send(Command.state(), method(:onResponse));
    }

    function onResponse(responseCode as Number, data as Dictionary or String or Null) as Void {
        var state = Outcome.fromResponse(responseCode, data).state;
        var headline = state == null ? null : state.headline();
        if (headline != null) {
            _text = headline;
            WatchUi.requestUpdate();
        }
    }

    function onUpdate(dc as Graphics.Dc) as Void {
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(0, dc.getHeight() / 2, Graphics.FONT_GLANCE, _text,
            Graphics.TEXT_JUSTIFY_LEFT | Graphics.TEXT_JUSTIFY_VCENTER);
    }
}

(:glance)
module GlanceModel {
    const STORAGE_KEY = "glance";
}
