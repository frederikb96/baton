import Toybox.Communications;
import Toybox.Lang;

// One call of the watch API. A command changes something and is confirmed by a vibration; a poll
// only refreshes the state. The three texts are shown on screen while the command is in flight and
// when the server answers ok or already; an empty one means the answer decides the text.
(:glance)
class Request {
    var path as String;
    var method as Communications.HttpRequestMethod;
    var isCommand as Boolean;
    var pendingText as String;
    var okText as String;
    var alreadyText as String;

    function initialize(path as String, method as Communications.HttpRequestMethod, isCommand as Boolean,
                        pendingText as String, okText as String, alreadyText as String) {
        self.path = path;
        self.method = method;
        self.isCommand = isCommand;
        self.pendingText = pendingText;
        self.okText = okText;
        self.alreadyText = alreadyText;
    }
}

(:glance)
module Command {
    const BASE = "/api/watch/";

    function state() as Request {
        return new Request(BASE + "state", Communications.HTTP_REQUEST_METHOD_GET, false, "", "", "");
    }

    function playPause() as Request {
        return post("play-pause", "...", "", "");
    }

    function next() as Request {
        return post("next", "Next...", "Next", "Next");
    }

    function previous() as Request {
        return post("previous", "Previous...", "Previous", "Previous");
    }

    function like() as Request {
        return post("like", "Liking...", "Liked", "Already liked");
    }

    function unlike() as Request {
        return post("unlike", "Removing...", "Like removed", "Not liked");
    }

    function playlistAdd() as Request {
        return post("playlist/add", "Adding...", "Added", "Already added");
    }

    function playlistRemove() as Request {
        return post("playlist/remove", "Removing...", "Removed", "Not in playlist");
    }

    function playlists() as Request {
        return new Request(BASE + "playlists", Communications.HTTP_REQUEST_METHOD_GET, false, "", "", "");
    }

    // mode: normal, shuffle or smart
    function playPlaylist(id as String, mode as String) as Request {
        return post("playlists/" + id + "/play?mode=" + mode, "Starting...", "", "");
    }

    function post(path as String, pending as String, ok as String, already as String) as Request {
        return new Request(BASE + path, Communications.HTTP_REQUEST_METHOD_POST, true, pending, ok, already);
    }
}
