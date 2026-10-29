import Toybox.Lang;

// The only reader of the build-time config. Compiling this file fails with "Undefined symbol
// ':Config'" while config/Config.mc does not exist: copy config/Config.mc.example to it (or run
// ./configure) and fill it in.
(:glance)
module ServerConfig {
    function url() as String {
        var url = Config.SERVER_URL;
        // a trailing slash would double up with the request paths
        var last = url.substring(url.length() - 1, url.length()) as String;
        return last.equals("/") ? url.substring(0, url.length() - 1) as String : url;
    }

    function key() as String {
        return Config.WATCH_KEY;
    }
}
