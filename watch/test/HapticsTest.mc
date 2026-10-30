import Toybox.Lang;
import Toybox.Test;

function pulses(kind as Number) as Number {
    var steps = Haptics.pattern(kind);
    var count = 0;
    for (var i = 0; i < steps.size(); i++) {
        if (steps[i][0] > 0) {
            count += 1;
        }
    }
    return count;
}

function longestPulse(kind as Number) as Number {
    var steps = Haptics.pattern(kind);
    var longest = 0;
    for (var i = 0; i < steps.size(); i++) {
        if (steps[i][0] > 0 && steps[i][1] > longest) {
            longest = steps[i][1];
        }
    }
    return longest;
}

(:test)
function resultsChooseTheirOwnPattern(logger as Logger) as Boolean {
    return Haptics.forResult(Result.OK) == Haptics.SUCCESS
        && Haptics.forResult(Result.ALREADY) == Haptics.ALREADY
        && Haptics.forResult(Result.ERROR) == Haptics.ERROR
        && Haptics.forResult(Result.REJECTED) == Haptics.ERROR
        && Haptics.forResult(Result.FAILED) == Haptics.ERROR;
}

(:test)
function onlyInaudibleCommandsConfirmSuccess(logger as Logger) as Boolean {
    var quiet = [Command.playPause(), Command.next(), Command.restart(), Command.previousTrack(),
        Command.playPlaylist("a", "normal")];
    for (var i = 0; i < quiet.size(); i++) {
        if (Haptics.forCommand(quiet[i], Result.OK) != null || Haptics.forCommand(quiet[i], Result.ALREADY) != null
            || Haptics.forCommand(quiet[i], Result.FAILED) != Haptics.ERROR) {
            return false;
        }
    }
    var confirmed = [Command.like(null), Command.unlike(null), Command.playlistAdd(null), Command.playlistRemove(null)];
    for (var i = 0; i < confirmed.size(); i++) {
        if (Haptics.forCommand(confirmed[i], Result.OK) != Haptics.SUCCESS
            || Haptics.forCommand(confirmed[i], Result.ALREADY) != Haptics.ALREADY
            || Haptics.forCommand(confirmed[i], Result.ERROR) != Haptics.ERROR) {
            return false;
        }
    }
    return true;
}

(:test)
function patternsCanBeToldApartByFeel(logger as Logger) as Boolean {
    // success: one short pulse; already: two very short; error: one long; menu: three ticks
    return pulses(Haptics.SUCCESS) == 1 && longestPulse(Haptics.SUCCESS) == 150
        && pulses(Haptics.ALREADY) == 2 && longestPulse(Haptics.ALREADY) <= 60
        && pulses(Haptics.ERROR) == 1 && longestPulse(Haptics.ERROR) >= 600
        && pulses(Haptics.MENU) == 3;
}
