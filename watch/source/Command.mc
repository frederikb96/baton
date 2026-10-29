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

    function like(trackId as String?) as Request {
        return post(anchored("like", trackId), "Liking...", "Liked", "Already liked");
    }

    function unlike(trackId as String?) as Request {
        return post(anchored("unlike", trackId), "Removing...", "Like removed", "Not liked");
    }

    function playlistAdd(trackId as String?) as Request {
        return post(anchored("playlist/add", trackId), "Adding...", "Added", "Already added");
    }

    function playlistRemove(trackId as String?) as Request {
        return post(anchored("playlist/remove", trackId), "Removing...", "Removed", "Not in playlist");
    }

    function playlists() as Request {
        return new Request(BASE + "playlists", Communications.HTTP_REQUEST_METHOD_GET, false, "", "", "");
    }

    // mode: normal, shuffle or smart
    function playPlaylist(id as String, mode as String) as Request {
        return post("playlists/" + id + "/play?mode=" + mode, "Starting...", "", "");
    }

    // The id of the track the screen showed: the server refuses the action when another one plays now.
    function anchored(path as String, trackId as String?) as String {
        return trackId == null ? path : path + "?track=" + trackId;
    }

    function post(path as String, pending as String, ok as String, already as String) as Request {
        return new Request(BASE + path, Communications.HTTP_REQUEST_METHOD_POST, true, pending, ok, already);
    }
}
