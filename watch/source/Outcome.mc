import Toybox.Communications;
import Toybox.Lang;

// How one call ended. Result.OK and Result.ALREADY are the server's two success answers.
(:glance)
module Result {
    enum {
        OK,
        ALREADY,
        // the server answered with result "error"
        ERROR,
        // HTTP 401: the watch key is wrong
        REJECTED,
        // no usable answer: transport error, other HTTP status, malformed body, no phone
        FAILED
    }
}

(:glance)
class Outcome {
    var kind as Number;
    // the server's error code, or a local one: no_phone, busy, timeout, bad_response
    var code as String? = null;
    var message as String? = null;
    var state as PlayerState? = null;
    // [id, name] pairs of a playlists answer
    var playlists as Array<Array<String>>? = null;

    function initialize(kind as Number) {
        self.kind = kind;
    }

    static function failed(code as String) as Outcome {
        var o = new Outcome(Result.FAILED);
        o.code = code;
        return o;
    }

    // responseCode is the HTTP status, or a negative Connect IQ transport error.
    static function fromResponse(responseCode as Number, data as Dictionary or String or Null) as Outcome {
        if (responseCode == 401) {
            return new Outcome(Result.REJECTED);
        }
        if (responseCode == Communications.BLE_CONNECTION_UNAVAILABLE) {
            return failed("no_phone");
        }
        if (responseCode != 200 || !(data instanceof Dictionary)) {
            return failed(responseCode == 200 ? "bad_response" : "http_" + responseCode);
        }
        var result = data["result"] as Object?;
        var o = new Outcome(Result.FAILED);
        if ("ok".equals(result)) {
            o.kind = Result.OK;
        } else if ("already".equals(result)) {
            o.kind = Result.ALREADY;
        } else if ("error".equals(result)) {
            o.kind = Result.ERROR;
        } else {
            return failed("bad_response");
        }
        var code = data["error"];
        var message = data["message"] as Object?;
        var state = data["state"] as Object?;
        var playlists = data["playlists"] as Object?;
        o.code = code instanceof String ? code : null;
        o.message = message instanceof String ? message : null;
        if (state instanceof Dictionary) {
            o.state = new PlayerState(state);
        }
        if (playlists instanceof Array) {
            o.playlists = parsePlaylists(playlists);
        }
        return o;
    }

    private static function parsePlaylists(items as Array) as Array<Array<String>> {
        var list = [] as Array<Array<String>>;
        for (var i = 0; i < items.size(); i++) {
            var item = items[i];
            if (item instanceof Dictionary && item["id"] instanceof String && item["name"] instanceof String) {
                list.add([item["id"] as String, item["name"] as String]);
            }
        }
        return list;
    }
}
