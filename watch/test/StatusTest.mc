import Toybox.Lang;
import Toybox.Test;

function stateOf(playing as Boolean, title as String?) as PlayerState {
    return new PlayerState({"is_playing" => playing, "title" => title});
}

(:test)
function statusFollowsPhoneThenProblemThenState(logger as Logger) as Boolean {
    var playing = stateOf(true, "T");
    return Status.of(false, Status.NO_DEVICE, playing) == Status.NO_PHONE
        && Status.of(true, Status.NO_DEVICE, playing) == Status.NO_DEVICE
        && Status.of(true, null, null) == Status.CONNECTING
        && Status.of(true, null, stateOf(true, "T")) == Status.PLAYING
        && Status.of(true, null, stateOf(false, "T")) == Status.PAUSED
        && Status.of(true, null, stateOf(false, null)) == Status.NO_TRACK;
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
    var problems = [Status.NO_PHONE, Status.KEY_REJECTED, Status.AUTH_EXPIRED, Status.NO_DEVICE, Status.UNREACHABLE];
    for (var i = 0; i < problems.size(); i++) {
        if (Status.headline(problems[i]).length() == 0 || Status.hint(problems[i]).length() == 0) {
            return false;
        }
    }
    return true;
}

(:test)
function toastNamesWhatHappened(logger as Logger) as Boolean {
    var like = Command.like();
    var ok = Outcome.fromResponse(200, okBody());
    var already = Outcome.fromResponse(200, {"result" => "already"});
    var rejected = Outcome.fromResponse(401, null);
    var noTarget = Outcome.fromResponse(200, {"result" => "error", "error" => "no_target_playlist"});
    var paused = Outcome.fromResponse(200, {"result" => "ok", "state" => {"is_playing" => false}});
    return Status.toastFor(like, ok).equals("Liked")
        && Status.toastFor(like, already).equals("Already liked")
        && Status.toastFor(like, rejected).equals("Key rejected")
        && Status.toastFor(like, noTarget).equals("No target playlist")
        && Status.toastFor(like, Outcome.failed("no_phone")).equals("No phone")
        && Status.toastFor(Command.playPause(), ok).equals("Playing")
        && Status.toastFor(Command.playPause(), paused).equals("Paused")
        && Status.toastFor(Command.playPlaylist("a", "smart"), Outcome.fromResponse(200, {"result" => "ok", "message" => "Shuffling instead"})).equals("Shuffling instead");
}
