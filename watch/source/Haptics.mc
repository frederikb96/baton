import Toybox.Attention;
import Toybox.Lang;

// The vibration that confirms a command, chosen by what the server answered. Each pattern differs
// in pulse count or length so it can be told apart through a glove. A command you hear the effect
// of vibrates only when it fails.
module Haptics {
    enum {
        SUCCESS,
        ALREADY,
        ERROR,
        MENU
    }

    // [duty cycle, milliseconds] steps; duty 0 is a pause
    function pattern(kind as Number) as Array<Array<Number>> {
        if (kind == SUCCESS) {
            return [[100, 150]];
        } else if (kind == ALREADY) {
            return [[100, 60], [0, 80], [100, 60]];
        } else if (kind == MENU) {
            return [[100, 40], [0, 70], [100, 40], [0, 70], [100, 40]];
        }
        return [[100, 600]];
    }

    function forResult(result as Number) as Number {
        if (result == Result.OK) {
            return SUCCESS;
        }
        return result == Result.ALREADY ? ALREADY : ERROR;
    }

    // The pattern a finished command plays, or null for none.
    function forCommand(request as Request, result as Number) as Number? {
        var kind = forResult(result);
        return kind == ERROR || request.confirm ? kind : null;
    }

    function play(kind as Number) as Void {
        Log.line("haptics", "pattern " + kind);
        if (!(Attention has :vibrate)) {
            return;
        }
        var steps = pattern(kind);
        var profiles = [] as Array<Attention.VibeProfile>;
        for (var i = 0; i < steps.size(); i++) {
            profiles.add(new Attention.VibeProfile(steps[i][0], steps[i][1]));
        }
        Attention.vibrate(profiles);
    }
}
