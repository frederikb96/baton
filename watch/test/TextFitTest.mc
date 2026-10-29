import Toybox.Lang;
import Toybox.Test;

// Ten pixels per character, so the tests need no screen.
class FixedWidth {
    function width(text as String) as Number {
        return text.length() * 10;
    }
}

function fit(text as String, maxWidth as Number, maxLines as Number) as Array<String> {
    return TextFit.wrap(text, maxWidth, maxLines, new FixedWidth().method(:width));
}

(:test)
function shortTextStaysOneLine(logger as Logger) as Boolean {
    var lines = fit("Intro", 100, 2);
    return lines.size() == 1 && lines[0].equals("Intro");
}

(:test)
function longTextWrapsAtSpaces(logger as Logger) as Boolean {
    var lines = fit("Midnight City Lights", 130, 2);
    return lines.size() == 2 && lines[0].equals("Midnight City") && lines[1].equals("Lights");
}

(:test)
function overflowEndsInEllipsis(logger as Logger) as Boolean {
    var lines = fit("A Very Long Track Title That Needs Room", 120, 2);
    return lines.size() == 2 && lines[0].equals("A Very Long") && lines[1].find("...") != null
        && lines[1].length() * 10 <= 120;
}

(:test)
function oneUnbrokenWordIsCutToFit(logger as Logger) as Boolean {
    var lines = fit("Supercalifragilistic", 100, 1);
    return lines.size() == 1 && lines[0].equals("Superca...");
}

(:test)
function emptyTextGivesOneEmptyLine(logger as Logger) as Boolean {
    var lines = fit("", 100, 2);
    return lines.size() == 1 && lines[0].length() == 0;
}
