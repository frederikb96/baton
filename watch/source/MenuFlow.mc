import Toybox.Application;
import Toybox.Lang;
import Toybox.WatchUi;

// The menu opened by holding Up. Every action sends its command and returns to the main screen.
module MenuFlow {
    // Menu2 clips a line at the edge of the round screen instead of shortening it.
    const LABEL_CHARS = 13;

    function chars(text as String) as Number {
        return text.length();
    }

    function fit(text as String, maxChars as Number) as String {
        return TextFit.ellipsize(text, maxChars, new Lang.Method(MenuFlow, :chars));
    }

    function controller() as Controller {
        return (Application.getApp() as BatonApp).controller as Controller;
    }

    function offLabel(playlist as String) as String {
        return fit("Off " + playlist, LABEL_CHARS);
    }

    // Remove-like is the focused item, so holding Up and pressing Start removes the like. The
    // playing playlist has an entry of its own unless it is the target playlist.
    function openRoot() as Void {
        var state = controller().state;
        var target = state == null ? null : state.playlistName;
        var playing = state == null ? null : state.playingPlaylistName;
        var menu = new WatchUi.Menu2({:title => "Baton"});
        menu.addItem(new WatchUi.MenuItem("Remove like", null, :unlike, null));
        if (playing != null && !playing.equals(target)) {
            menu.addItem(new WatchUi.MenuItem(offLabel(playing), null, :removePlaying, null));
        }
        menu.addItem(new WatchUi.MenuItem(target == null ? "Off playlist" : offLabel(target), null, :remove, null));
        menu.addItem(new WatchUi.MenuItem("Playlists", null, :playlists, null));
        WatchUi.pushView(menu, new RootMenuDelegate(), WatchUi.SLIDE_UP);
    }

    // Sends the request from the main screen.
    function finish(request as Request) as Void {
        var c = controller();
        c.closeMenus();
        c.send(request);
    }
}

class RootMenuDelegate extends WatchUi.Menu2InputDelegate {
    function initialize() {
        Menu2InputDelegate.initialize();
    }

    function onSelect(item as WatchUi.MenuItem) as Void {
        var id = item.getId();
        if (id == :unlike) {
            MenuFlow.finish(Command.unlike(MenuFlow.controller().trackId()));
        } else if (id == :removePlaying) {
            MenuFlow.finish(Command.playingPlaylistRemove(MenuFlow.controller().trackId()));
        } else if (id == :remove) {
            MenuFlow.finish(Command.playlistRemove(MenuFlow.controller().trackId()));
        } else if (id == :playlists) {
            MenuFlow.controller().requestPlaylists(new PlaylistsLoader().method(:onPlaylists));
            item.setSubLabel("Loading...");
            WatchUi.requestUpdate();
        }
    }

    function onBack() as Void {
        MenuFlow.controller().menuLeft(1);
        WatchUi.popView(WatchUi.SLIDE_DOWN);
    }
}

// Shows Liked Songs, the saved playlists and the recent playlists once the server has answered.
class PlaylistsLoader {
    function onPlaylists(outcome as Outcome) as Void {
        var list = outcome.playlists;
        if (list == null || list.size() == 0) {
            MenuFlow.controller().closeMenus();
            MenuFlow.controller().showMessage("No playlists");
            return;
        }
        var menu = new WatchUi.Menu2({:title => "Playlists"});
        for (var i = 0; i < list.size(); i++) {
            menu.addItem(new WatchUi.MenuItem(MenuFlow.fit(list[i][1], MenuFlow.LABEL_CHARS), null, list[i][0], null));
        }
        MenuFlow.controller().menuDeeper();
        WatchUi.pushView(menu, new PlaylistMenuDelegate(), WatchUi.SLIDE_LEFT);
    }
}

class PlaylistMenuDelegate extends WatchUi.Menu2InputDelegate {
    function initialize() {
        Menu2InputDelegate.initialize();
    }

    function onSelect(item as WatchUi.MenuItem) as Void {
        var menu = new WatchUi.Menu2({:title => item.getLabel()});
        menu.addItem(new WatchUi.MenuItem("Play", null, "normal", null));
        menu.addItem(new WatchUi.MenuItem("Shuffle", null, "shuffle", null));
        menu.addItem(new WatchUi.MenuItem("Smart shuffle", null, "smart", null));
        MenuFlow.controller().menuDeeper();
        WatchUi.pushView(menu, new PlayModeMenuDelegate(item.getId() as String), WatchUi.SLIDE_LEFT);
    }

    function onBack() as Void {
        MenuFlow.controller().menuLeft(1);
        WatchUi.popView(WatchUi.SLIDE_RIGHT);
    }
}

class PlayModeMenuDelegate extends WatchUi.Menu2InputDelegate {
    private var _playlistId as String;

    function initialize(playlistId as String) {
        Menu2InputDelegate.initialize();
        _playlistId = playlistId;
    }

    function onSelect(item as WatchUi.MenuItem) as Void {
        MenuFlow.finish(Command.playPlaylist(_playlistId, item.getId() as String));
    }

    function onBack() as Void {
        MenuFlow.controller().menuLeft(1);
        WatchUi.popView(WatchUi.SLIDE_RIGHT);
    }
}
