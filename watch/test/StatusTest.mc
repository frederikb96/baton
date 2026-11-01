import Toybox.Lang;
import Toybox.Test;

function stateOf(playing as Boolean, title as String?) as PlayerState {
    return new PlayerState({"is_playing" => playing, "title" => title});
}

(:test)
function statusFollowsPhoneThenProblemThenState(logger as Logger) as Boolean {
    var playing = stateOf(true, "T");
    return Status.of(true, false, Status.NO_DEVICE, playing) == Status.NO_PHONE
        && Status.of(true, true, Status.NO_DEVICE, playing) == Status.NO_DEVICE
        && Status.of(true, true, null, null) == Status.CONNECTING
        && Status.of(true, true, null, stateOf(true, "T")) == Status.PLAYING
        && Status.of(true, true, null, stateOf(false, "T")) == Status.PAUSED
        && Status.of(true, true, null, stateOf(false, null)) == Status.NO_TRACK;
}

(:test)
function missingSettingsComeBeforeEverything(logger as Logger) as Boolean {
    return Status.of(false, false, Status.KEY_REJECTED, stateOf(true, "T")) == Status.NOT_SET_UP
        && Status.of(false, true, null, null) == Status.NOT_SET_UP;
}

(:test)
function standingProblemsComeFromTheOutcome(logger as Logger) as Boolean {
    var auth = Outcome.fromResponse(200, {"result" => "error", "error" => "spotify_auth"});
    var asleep = Outcome.fromResponse(200, {"result" => "error", "error" => "no_device"});
    var nothing = Outcome.fromResponse(200, {"result" => "error", "error" => "no_track"});
    var noTarget = Outcome.fromResponse(200, {"result" => "error", "error" => "no_target_playlist"});
    return Status.problemFor(Outcome.fromResponse(401, null)) == Status.KEY_REJECTED
        && Status.problemFor(auth) == Status.AUTH_EXPIRED
        && Status.problemFor(asleep) == Status.NO_DEVICE
        && Status.problemFor(nothing) == Status.NO_TRACK
        && Status.problemFor(Outcome.failed("no_phone")) == Status.NO_PHONE
        && Status.problemFor(Outcome.failed("timeout")) == Status.UNREACHABLE
        && Status.problemFor(noTarget) == null
        && Status.problemFor(Outcome.fromResponse(200, okBody())) == null;
}

(:test)
function everyProblemHasWordsForTheScreen(logger as Logger) as Boolean {
    var problems = [Status.NOT_SET_UP, Status.NO_PHONE, Status.KEY_REJECTED, Status.AUTH_EXPIRED, Status.NO_DEVICE, Status.UNREACHABLE];
    for (var i = 0; i < problems.size(); i++) {
        if (Status.headline(problems[i]).length() == 0 || Status.hint(problems[i]).length() == 0) {
            return false;
        }
    }
    return true;
}

(:test)
function unreachableHintNamesTheFailureAndHost(logger as Logger) as Boolean {
    return Status.unreachableHint("https://baton.example.com", "http_-1001").equals("-1001 baton.example.com")
        && Status.unreachableHint("https://baton.example.com", "http_502").equals("502 baton.example.com")
        && Status.unreachableHint("http://10.0.0.2:8000", "send_failed").equals("send_failed 10.0.0.2:8000")
        && Status.unreachableHint("https://baton.example.com", null).equals("baton.example.com");
}

(:test)
function toastNamesWhatHappened(logger as Logger) as Boolean {
    var like = Command.like(null);
    var ok = Outcome.fromResponse(200, okBody());
    var already = Outcome.fromResponse(200, {"result" => "already"});
    var rejected = Outcome.fromResponse(401, null);
    var noTarget = Outcome.fromResponse(200, {"result" => "error", "error" => "no_target_playlist"});
    var paused = Outcome.fromResponse(200, {"result" => "ok", "state" => {"is_playing" => false}});
    return Status.toastFor(like, ok).equals("Liked")
        && Status.toastFor(like, already).equals("Already liked")
        && Status.toastFor(like, rejected).equals("Key rejected")
        && Status.toastFor(like, noTarget).equals("No target playlist")
        && Status.toastFor(like, Outcome.fromResponse(200, {"result" => "error", "error" => "no_playing_playlist"})).equals("No playlist playing")
        && Status.toastFor(like, Outcome.fromResponse(200, {"result" => "error", "error" => "playlist_not_editable"})).equals("Not your playlist")
        && Status.toastFor(Command.playingPlaylistAdd(null), Outcome.fromResponse(200, {"result" => "ok", "message" => "Added to Cycling"})).equals("Added to Cycling")
        && Status.toastFor(Command.playingPlaylistAdd(null), Outcome.fromResponse(200, {"result" => "already", "message" => "Already in Cycling"})).equals("Already in Cycling")
        && Status.toastFor(like, Outcome.fromResponse(200, {"result" => "error", "error" => "track_changed"})).equals("Song changed")
        && Status.toastFor(like, Outcome.failed("no_phone")).equals("No phone")
        && Status.toastFor(like, Outcome.failed("not_set_up")).equals("Not set up")
        && Status.toastFor(Command.playPause(), ok).equals("Playing")
        && Status.toastFor(Command.playPause(), paused).equals("Paused")
        && Status.toastFor(Command.playPlaylist("a", "smart"), Outcome.fromResponse(200, {"result" => "ok", "message" => "Shuffling instead"})).equals("Shuffling instead");
}
