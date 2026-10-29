import Toybox.Lang;

// Word wrap and ellipsis against a width function, so the logic runs without a screen.
module TextFit {
    const ELLIPSIS = "...";

    // Greedy word wrap into at most maxLines lines; text that does not fit ends in an ellipsis.
    // Always returns at least one line.
    function wrap(text as String, maxWidth as Number, maxLines as Number, width as Method(text as String) as Number) as Array<String> {
        var lines = [] as Array<String>;
        var rest = text;
        while (lines.size() < maxLines - 1 && width.invoke(rest) > maxWidth) {
            var cut = breakAt(rest, maxWidth, width);
            if (cut <= 0) {
                break;
            }
            lines.add(rest.substring(0, cut) as String);
            rest = (rest.substring(cut, rest.length()) as String);
            while (rest.length() > 0 && (rest.substring(0, 1) as String).equals(" ")) {
                rest = rest.substring(1, rest.length()) as String;
            }
        }
        lines.add(ellipsize(rest, maxWidth, width));
        return lines;
    }

    // The text cut to fit, ending in an ellipsis when something was removed.
    function ellipsize(text as String, maxWidth as Number, width as Method(text as String) as Number) as String {
        if (width.invoke(text) <= maxWidth) {
            return text;
        }
        var n = text.length();
        while (n > 1 && width.invoke((text.substring(0, n) as String) + ELLIPSIS) > maxWidth) {
            n -= 1;
        }
        return (text.substring(0, n) as String) + ELLIPSIS;
    }

    // Index to cut text at for one line: after the last space that fits, else the longest prefix that fits.
    function breakAt(text as String, maxWidth as Number, width as Method(text as String) as Number) as Number {
        var fit = 0;
        var space = 0;
        for (var i = 1; i <= text.length(); i++) {
            if (width.invoke(text.substring(0, i) as String) > maxWidth) {
                break;
            }
            fit = i;
            if (i < text.length() && (text.substring(i, i + 1) as String).equals(" ")) {
                space = i;
            }
        }
        return space > 0 ? space : fit;
    }
}
