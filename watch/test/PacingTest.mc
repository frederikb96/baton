import Toybox.Lang;
import Toybox.Test;

(:test)
function inputGivesTheFullPaceAndUntouchedTheSlowOne(logger as Logger) as Boolean {
    return Pacing.pollIntervalMs(true) == Pacing.POLL_ACTIVE_MS
        && Pacing.pollIntervalMs(false) == Pacing.POLL_SLOW_MS
        && Pacing.POLL_ACTIVE_MS < Pacing.POLL_SLOW_MS;
}

(:test)
function aPollIsDueWhenAskedForOrWhenTheIntervalHasPassed(logger as Logger) as Boolean {
    var interval = Pacing.POLL_SLOW_MS;
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
