import Toybox.Lang;

// What the main screen reports besides a playing track.
module Status {
    enum {
        CONNECTING,
        PLAYING,
        PAUSED,
        NO_TRACK,
        NO_PHONE,
        KEY_REJECTED,
        AUTH_EXPIRED,
        NO_DEVICE,
        UNREACHABLE
    }

    // The standing problem an outcome reports, or null when it shows the server and Spotify working.
    function problemFor(outcome as Outcome) as Number? {
        if (outcome.kind == Result.REJECTED) {
            return KEY_REJECTED;
        } else if (outcome.kind == Result.FAILED) {
            return "no_phone".equals(outcome.code) ? NO_PHONE : UNREACHABLE;
        } else if (outcome.kind == Result.ERROR) {
            if ("spotify_auth".equals(outcome.code)) {
                return AUTH_EXPIRED;
            } else if ("no_device".equals(outcome.code)) {
                return NO_DEVICE;
            } else if ("no_track".equals(outcome.code)) {
                return NO_TRACK;
            }
        }
        return null;
    }

    // Standing problem first, then what the last state says.
    function of(phoneConnected as Boolean, problem as Number?, state as PlayerState?) as Number {
        if (!phoneConnected) {
            return NO_PHONE;
        } else if (problem != null) {
            return problem;
        } else if (state == null) {
            return CONNECTING;
        } else if (state.title == null && !state.isPlaying) {
            return NO_TRACK;
        }
        return state.isPlaying ? PLAYING : PAUSED;
    }

    function headline(status as Number) as String {
        if (status == NO_PHONE) {
            return "No phone";
        } else if (status == KEY_REJECTED) {
            return "Key rejected";
        } else if (status == AUTH_EXPIRED) {
            return "Spotify login expired";
        } else if (status == NO_DEVICE) {
            return "Device asleep";
        } else if (status == NO_TRACK) {
            return "Nothing playing";
        } else if (status == UNREACHABLE) {
            return "No connection";
        }
        return "Connecting";
    }

    function hint(status as Number) as String {
        if (status == NO_PHONE) {
            return "Phone not connected";
        } else if (status == KEY_REJECTED) {
            return "Check the watch key";
        } else if (status == AUTH_EXPIRED) {
            return "Log in again on the web";
        } else if (status == NO_DEVICE) {
            return "Start Spotify on a device";
        } else if (status == UNREACHABLE) {
            return "Server not reachable";
        }
        return "";
    }

    // The short text confirming a finished command.
    function toastFor(request as Request, outcome as Outcome) as String {
        if (outcome.kind == Result.OK || outcome.kind == Result.ALREADY) {
            var text = outcome.kind == Result.OK ? request.okText : request.alreadyText;
            if (text.length() > 0) {
                return text;
            }
            if (outcome.message != null) {
                return outcome.message as String;
            }
            var state = outcome.state;
            return state != null ? (state.isPlaying ? "Playing" : "Paused") : "Done";
        } else if (outcome.kind == Result.REJECTED) {
            return "Key rejected";
        } else if (outcome.kind == Result.FAILED) {
            var code = outcome.code;
            if ("no_phone".equals(code)) {
                return "No phone";
            }
            return "busy".equals(code) ? "Busy" : ("timeout".equals(code) ? "No answer" : "Failed");
        }
        var error = outcome.code;
        if ("no_target_playlist".equals(error)) {
            return "No target playlist";
        } else if ("spotify_rate_limited".equals(error)) {
            return "Rate limited";
        } else if ("spotify_auth".equals(error)) {
            return "Login expired";
        } else if ("no_device".equals(error)) {
            return "Device asleep";
        } else if ("no_track".equals(error)) {
            return "Nothing playing";
        }
        return "Spotify error";
    }
}
