import Toybox.Lang;
import Toybox.WatchUi;

// Feeds key press and release times to the controller and swallows every behaviour the platform
// derives from them, so that a touch tap, a swipe or a firmware shortcut cannot act.
class MainDelegate extends WatchUi.BehaviorDelegate {
    private var _controller as Controller;

    function initialize(controller as Controller) {
        BehaviorDelegate.initialize();
        _controller = controller;
    }

    function onKeyPressed(evt as WatchUi.KeyEvent) as Boolean {
        _controller.keyPressed(evt.getKey());
        return true;
    }

    function onKeyReleased(evt as WatchUi.KeyEvent) as Boolean {
        _controller.keyReleased(evt.getKey());
        return true;
    }

    function onKey(evt as WatchUi.KeyEvent) as Boolean {
        if (evt.getKey() == WatchUi.KEY_MENU) {
            _controller.menuHeld();
        }
        return true;
    }

    // Up held long enough: the platform's menu behaviour.
    function onMenu() as Boolean {
        _controller.menuHeld();
        return true;
    }

    function onBack() as Boolean {
        return true;
    }

    function onSelect() as Boolean {
        return true;
    }

    function onNextPage() as Boolean {
        return true;
    }

    function onPreviousPage() as Boolean {
        return true;
    }

    function onNextMode() as Boolean {
        return true;
    }

    function onPreviousMode() as Boolean {
        return true;
    }

    function onTap(evt as WatchUi.ClickEvent) as Boolean {
        return true;
    }

    function onHold(evt as WatchUi.ClickEvent) as Boolean {
        return true;
    }

    function onRelease(evt as WatchUi.ClickEvent) as Boolean {
        return true;
    }

    function onSwipe(evt as WatchUi.SwipeEvent) as Boolean {
        return true;
    }

    function onDrag(evt as WatchUi.DragEvent) as Boolean {
        return true;
    }

    function onFlick(evt as WatchUi.FlickEvent) as Boolean {
        return true;
    }
}
