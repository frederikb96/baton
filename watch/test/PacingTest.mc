import Toybox.Lang;
import Toybox.Test;

(:test)
function onlyAPlayingTrackPollsAtTheShortInterval(logger as Logger) as Boolean {
    var others = [Status.CONNECTING, Status.PAUSED, Status.NO_TRACK, Status.NO_PHONE, Status.KEY_REJECTED,
        Status.AUTH_EXPIRED, Status.NO_DEVICE, Status.UNREACHABLE];
    for (var i = 0; i < others.size(); i++) {
        if (Pacing.pollIntervalMs(others[i], false) != Pacing.POLL_IDLE_MS) {
            return false;
        }
    }
    return Pacing.pollIntervalMs(Status.PLAYING, false) == Pacing.POLL_PLAYING_MS
        && Pacing.POLL_PLAYING_MS < Pacing.POLL_IDLE_MS;
}

(:test)
function inputGivesEveryStatusTheFullPace(logger as Logger) as Boolean {
    var all = [Status.CONNECTING, Status.PLAYING, Status.PAUSED, Status.NO_TRACK, Status.NO_PHONE,
        Status.KEY_REJECTED, Status.AUTH_EXPIRED, Status.NO_DEVICE, Status.UNREACHABLE];
    for (var i = 0; i < all.size(); i++) {
        if (Pacing.pollIntervalMs(all[i], true) != Pacing.POLL_ACTIVE_MS) {
            return false;
        }
    }
    return Pacing.POLL_ACTIVE_MS < Pacing.POLL_PLAYING_MS;
}

(:test)
function aPollIsDueWhenAskedForOrWhenTheIntervalHasPassed(logger as Logger) as Boolean {
    var interval = Pacing.POLL_PLAYING_MS;
    return Pacing.pollDue(true, 1000, 1000, interval)
        && !Pacing.pollDue(false, 1000 + interval - 1, 1000, interval)
        && Pacing.pollDue(false, 1000 + interval, 1000, interval);
}

(:test)
function onlyAPlayingTrackRedrawsOnTheClock(logger as Logger) as Boolean {
    var step = Pacing.REDRAW_PLAYING_MS;
    var fast = Pacing.REDRAW_ACTIVE_MS;
    return !Pacing.redrawDue(Status.PLAYING, false, 1000 + step - 1, 1000)
        && Pacing.redrawDue(Status.PLAYING, false, 1000 + step, 1000)
        && !Pacing.redrawDue(Status.PAUSED, false, 1000 + step, 1000)
        && !Pacing.redrawDue(Status.PLAYING, true, 1000 + fast - 1, 1000)
        && Pacing.redrawDue(Status.PLAYING, true, 1000 + fast, 1000)
        && !Pacing.redrawDue(Status.PAUSED, true, 1000 + fast, 1000);
}
