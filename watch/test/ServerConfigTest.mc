import Toybox.Lang;
import Toybox.Test;

(:test)
function pastedSettingsAreCleanedUp(logger as Logger) as Boolean {
    return ServerConfig.trim("  abc \n").equals("abc")
        && ServerConfig.trim("abc").equals("abc")
        && ServerConfig.trim(" \n").equals("")
        && ServerConfig.cleanUrl(" https://baton.example.com/\n").equals("https://baton.example.com")
        && ServerConfig.cleanUrl("").equals("");
}

(:test)
function settingsAreCompleteWithAWebAddressAndAKey(logger as Logger) as Boolean {
    return ServerConfig.isComplete("https://baton.example.com", "k")
        && ServerConfig.isComplete("http://192.168.1.2:8000", "k")
        && !ServerConfig.isComplete("https://baton.example.com", "")
        && !ServerConfig.isComplete("baton.example.com", "k")
        && !ServerConfig.isComplete("", "");
}

(:test)
function settingsStartEmpty(logger as Logger) as Boolean {
    return !ServerConfig.isSet();
}
