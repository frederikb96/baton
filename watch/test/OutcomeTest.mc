import Toybox.Communications;
import Toybox.Lang;
import Toybox.Test;

function okBody() as Dictionary {
    return {
        "result" => "ok",
        "error" => null,
        "message" => null,
        "state" => {
            "is_playing" => true,
            "title" => "Intro",
            "artist" => "The xx",
            "progress_ms" => 1200,
            "duration_ms" => 127000,
            "liked" => true,
            "in_playlist" => false,
            "playlist_name" => "My Shazam",
            "device_name" => "Phone",
            "server_time_ms" => 1793299258493l
        }
    };
}

(:test)
function okAnswerCarriesTheState(logger as Logger) as Boolean {
    var o = Outcome.fromResponse(200, okBody());
    var s = o.state;
    return o.kind == Result.OK && s != null && s.isPlaying && "Intro".equals(s.title)
        && "The xx".equals(s.artist) && s.progressMs == 1200 && s.durationMs == 127000
        && s.liked == true && s.inPlaylist == false && "My Shazam".equals(s.playlistName)
        && "The xx - Intro".equals(s.headline());
}

(:test)
function alreadyAnswerIsASuccessKind(logger as Logger) as Boolean {
    var body = okBody();
    body["result"] = "already";
    return Outcome.fromResponse(200, body).kind == Result.ALREADY;
}

(:test)
function errorAnswerKeepsCodeAndMessage(logger as Logger) as Boolean {
    var o = Outcome.fromResponse(200, {"result" => "error", "error" => "no_device", "message" => "asleep", "state" => null});
    return o.kind == Result.ERROR && "no_device".equals(o.code) && "asleep".equals(o.message) && o.state == null;
}

(:test)
function http401IsAKeyRejection(logger as Logger) as Boolean {
    return Outcome.fromResponse(401, {"detail" => "invalid"}).kind == Result.REJECTED
        && Outcome.fromResponse(401, null).kind == Result.REJECTED;
}

(:test)
function noPhoneIsRecognisedFromTheTransportError(logger as Logger) as Boolean {
    var o = Outcome.fromResponse(Communications.BLE_CONNECTION_UNAVAILABLE, null);
    return o.kind == Result.FAILED && "no_phone".equals(o.code);
}

(:test)
function otherStatusesAndBadBodiesFail(logger as Logger) as Boolean {
    var server = Outcome.fromResponse(502, null);
    var transport = Outcome.fromResponse(-1001, null);
    var notJson = Outcome.fromResponse(200, "text");
    var unknownResult = Outcome.fromResponse(200, {"result" => "maybe"});
    return server.kind == Result.FAILED && "http_502".equals(server.code)
        && transport.kind == Result.FAILED && "http_-1001".equals(transport.code)
        && notJson.kind == Result.FAILED && "bad_response".equals(notJson.code)
        && unknownResult.kind == Result.FAILED && "bad_response".equals(unknownResult.code);
}

(:test)
function stateWithWrongTypesKeepsDefaults(logger as Logger) as Boolean {
    var s = new PlayerState({"is_playing" => "yes", "title" => 5, "progress_ms" => "x", "liked" => 1});
    return !s.isPlaying && s.title == null && s.progressMs == null && s.liked == null && s.headline() == null;
}

(:test)
function playlistsAnswerListsIdAndName(logger as Logger) as Boolean {
    var o = Outcome.fromResponse(200, {
        "result" => "ok",
        "playlists" => [{"id" => "a", "name" => "One"}, {"id" => 7, "name" => "bad"}, {"id" => "b", "name" => "Two"}]
    });
    var list = o.playlists;
    return list != null && list.size() == 2 && "a".equals(list[0][0]) && "Two".equals(list[1][1]);
}

(:test)
function commandsUseTheContractPathsAndMethods(logger as Logger) as Boolean {
    var like = Command.like();
    var state = Command.state();
    var play = Command.playPlaylist("abc", "shuffle");
    return like.path.equals("/api/watch/like") && like.method == Communications.HTTP_REQUEST_METHOD_POST && like.isCommand
        && Command.unlike().path.equals("/api/watch/unlike")
        && Command.playlistAdd().path.equals("/api/watch/playlist/add")
        && Command.playlistRemove().path.equals("/api/watch/playlist/remove")
        && Command.playPause().path.equals("/api/watch/play-pause")
        && Command.next().path.equals("/api/watch/next")
        && Command.previous().path.equals("/api/watch/previous")
        && state.path.equals("/api/watch/state") && state.method == Communications.HTTP_REQUEST_METHOD_GET && !state.isCommand
        && play.path.equals("/api/watch/playlists/abc/play?mode=shuffle");
}
