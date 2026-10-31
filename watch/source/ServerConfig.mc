import Toybox.Application;
import Toybox.Lang;

// The server address and watch key, which the user sets in the app's settings on the phone.
(:glance)
module ServerConfig {
    const URL_PROPERTY = "serverUrl";
    const KEY_PROPERTY = "watchKey";

    function url() as String {
        return cleanUrl(setting(URL_PROPERTY));
    }

    function key() as String {
        return trim(setting(KEY_PROPERTY));
    }

    function isSet() as Boolean {
        return isComplete(url(), key());
    }

    function isComplete(url as String, key as String) as Boolean {
        return key.length() > 0 && (url.find("https://") == 0 || url.find("http://") == 0);
    }

    // A pasted value may carry spaces or a line break, and a trailing slash would double up with the
    // request paths.
    function cleanUrl(value as String) as String {
        var url = trim(value);
        var last = url.length() - 1;
        return last >= 0 && url.toCharArray()[last] == '/' ? url.substring(0, last) as String : url;
    }

    function trim(value as String) as String {
        var chars = value.toCharArray();
        var start = 0;
        var end = chars.size();
        while (start < end && chars[start] <= ' ') {
            start += 1;
        }
        while (end > start && chars[end - 1] <= ' ') {
            end -= 1;
        }
        return value.substring(start, end) as String;
    }

    function setting(name as String) as String {
        var value = Application.Properties.getValue(name);
        return value instanceof String ? value : "";
    }
}
