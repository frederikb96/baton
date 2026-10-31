import Toybox.Graphics;
import Toybox.Lang;
import Toybox.Math;
import Toybox.System;
import Toybox.WatchUi;

// The main screen: progress ring around the edge, title and artist in the middle, a hint glyph at
// each button, the time at the bottom. Geometry follows the screen size.
class MainView extends WatchUi.View {
    const BLACK = 0x000000;
    const WHITE = 0xFFFFFF;
    const GRAY = 0xAAAAAA;
    const DARK_GRAY = 0x555555;
    const RING_TRACK = 0x000055;
    const RING_PLAYING = 0x00AAFF;
    const RING_PAUSED = 0x5555AA;
    const RING_PROBLEM = 0x550000;
    const RED = 0xFF0000;
    const GREEN = 0x00FF55;
    const ORANGE = 0xFFAA00;

    private var _controller as Controller;

    function initialize(controller as Controller) {
        View.initialize();
        _controller = controller;
    }

    function onUpdate(dc as Graphics.Dc) as Void {
        _controller.drawn();
        var w = dc.getWidth();
        var h = dc.getHeight();
        var status = _controller.status();
        dc.setColor(WHITE, BLACK);
        dc.clear();
        if (dc has :setAntiAlias) {
            dc.setAntiAlias(true);
        }
        drawRing(dc, w, h, status);
        if (status == Status.PLAYING || status == Status.PAUSED) {
            drawTrack(dc, w, h, status);
        } else {
            drawProblem(dc, w, h, status);
        }
        drawHints(dc, w, h, status);
        drawTime(dc, w, h);
        if (_controller.launchedFromGlance) {
            dc.setColor(DARK_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawText(w / 2, h * 12 / 100, Graphics.FONT_XTINY, "Closes when idle",
                Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
        }
    }

    private function drawRing(dc as Graphics.Dc, w as Number, h as Number, status as Number) as Void {
        var radius = w / 2 - 5;
        dc.setPenWidth(8);
        var problem = status != Status.PLAYING && status != Status.PAUSED;
        dc.setColor(problem ? RING_PROBLEM : RING_TRACK, Graphics.COLOR_TRANSPARENT);
        dc.drawCircle(w / 2, h / 2, radius);
        var progress = _controller.progressMs();
        var state = _controller.state;
        if (problem || progress == null || state == null || state.durationMs == null || (state.durationMs as Number) <= 0) {
            return;
        }
        var fraction = progress.toFloat() / (state.durationMs as Number).toFloat();
        if (fraction <= 0.0) {
            return;
        }
        dc.setColor(status == Status.PLAYING ? RING_PLAYING : RING_PAUSED, Graphics.COLOR_TRANSPARENT);
        if (fraction >= 1.0) {
            dc.drawCircle(w / 2, h / 2, radius);
            return;
        }
        // from 12 o'clock clockwise
        var end = (90 - (360.0 * fraction).toNumber() + 360) % 360;
        dc.drawArc(w / 2, h / 2, radius, Graphics.ARC_CLOCKWISE, 90, end);
    }

    private function drawTrack(dc as Graphics.Dc, w as Number, h as Number, status as Number) as Void {
        var state = _controller.state as PlayerState;
        var textWidth = w * 52 / 100;
        var titleFont = Graphics.FONT_SMALL;
        var artistFont = Graphics.FONT_TINY;
        var titleLines = wrap(dc, state.title == null ? "" : state.title as String, titleFont, textWidth, 2);
        var lineHeight = dc.getFontHeight(titleFont);
        var artistHeight = dc.getFontHeight(artistFont);
        var block = lineHeight * titleLines.size() + artistHeight + 4;
        var y = h * 42 / 100 - block / 2;
        if (status == Status.PAUSED) {
            dc.setColor(ORANGE, Graphics.COLOR_TRANSPARENT);
            dc.drawText(w / 2, h * 18 / 100, Graphics.FONT_XTINY, "PAUSED",
                Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
        }
        dc.setColor(status == Status.PLAYING ? WHITE : GRAY, Graphics.COLOR_TRANSPARENT);
        for (var i = 0; i < titleLines.size(); i++) {
            dc.drawText(w / 2, y + lineHeight / 2, titleFont, titleLines[i], Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
            y += lineHeight;
        }
        dc.setColor(GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(w / 2, y + 4 + artistHeight / 2, artistFont,
            wrap(dc, state.artist == null ? "" : state.artist as String, artistFont, textWidth, 1)[0],
            Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
        drawInfoRow(dc, w, h, state);
    }

    // Target playlist membership, or the result of the last command.
    private function drawInfoRow(dc as Graphics.Dc, w as Number, h as Number, state as PlayerState) as Void {
        var y = h * 68 / 100;
        var toast = _controller.toast;
        var font = Graphics.FONT_XTINY;
        if (toast != null) {
            dc.setColor(WHITE, Graphics.COLOR_TRANSPARENT);
            dc.drawText(w / 2, y, font, wrap(dc, toast, font, w * 60 / 100, 1)[0],
                Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
            return;
        }
        var name = state.playlistName == null ? "Playlist" : state.playlistName as String;
        var text = wrap(dc, name, font, w * 40 / 100, 1)[0];
        var color = state.inPlaylist == true ? GREEN : DARK_GRAY;
        var iconSize = 8;
        var total = iconSize * 2 + 6 + dc.getTextWidthInPixels(text, font);
        var x = w / 2 - total / 2;
        Glyphs.playlist(dc, x + iconSize, y, iconSize, color);
        dc.setColor(color, Graphics.COLOR_TRANSPARENT);
        dc.drawText(x + iconSize * 2 + 6, y, font, text, Graphics.TEXT_JUSTIFY_LEFT | Graphics.TEXT_JUSTIFY_VCENTER);
    }

    private function drawProblem(dc as Graphics.Dc, w as Number, h as Number, status as Number) as Void {
        var lines = wrap(dc, Status.headline(status), Graphics.FONT_SMALL, w * 56 / 100, 3);
        var lineHeight = dc.getFontHeight(Graphics.FONT_SMALL);
        var y = h * 42 / 100 - lineHeight * lines.size() / 2;
        dc.setColor(status == Status.CONNECTING || status == Status.NO_TRACK || status == Status.NOT_SET_UP ? GRAY : RED, Graphics.COLOR_TRANSPARENT);
        for (var i = 0; i < lines.size(); i++) {
            dc.drawText(w / 2, y + lineHeight / 2, Graphics.FONT_SMALL, lines[i],
                Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
            y += lineHeight;
        }
        var hint = _controller.toast != null ? _controller.toast as String : Status.hint(status);
        dc.setColor(GRAY, Graphics.COLOR_TRANSPARENT);
        var hintLines = wrap(dc, hint, Graphics.FONT_XTINY, w * 56 / 100, 2);
        var hintHeight = dc.getFontHeight(Graphics.FONT_XTINY);
        for (var i = 0; i < hintLines.size(); i++) {
            dc.drawText(w / 2, y + 6 + hintHeight / 2, Graphics.FONT_XTINY, hintLines[i],
                Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
            y += hintHeight;
        }
    }

    // Start at 2 o'clock, Up at 9, Down at 8, like the buttons of the watch.
    private function drawHints(dc as Graphics.Dc, w as Number, h as Number, status as Number) as Void {
        var radius = w * 40 / 100;
        var size = w * 5 / 100;
        var start = polar(w, h, 30, radius);
        if (status == Status.PLAYING) {
            Glyphs.pause(dc, start[0], start[1], size, WHITE);
        } else {
            Glyphs.play(dc, start[0], start[1], size, status == Status.PAUSED ? GREEN : DARK_GRAY);
        }
        var down = polar(w, h, 210, radius);
        Glyphs.skip(dc, down[0], down[1], size, status == Status.PLAYING || status == Status.PAUSED ? WHITE : DARK_GRAY);
        var up = polar(w, h, 180, radius);
        var state = _controller.state;
        var liked = state != null && state.liked == true && (status == Status.PLAYING || status == Status.PAUSED);
        Glyphs.heart(dc, up[0], up[1] - size * 3 / 4, size, liked ? RED : DARK_GRAY);
        Glyphs.dots(dc, up[0], up[1] + size * 3 / 2, size * 2 / 3, GRAY);
    }

    private function drawTime(dc as Graphics.Dc, w as Number, h as Number) as Void {
        var time = System.getClockTime();
        var hour = time.hour;
        if (!System.getDeviceSettings().is24Hour) {
            hour = hour % 12 == 0 ? 12 : hour % 12;
        }
        dc.setColor(GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(w / 2, h * 86 / 100, Graphics.FONT_XTINY, hour.format("%d") + ":" + time.min.format("%02d"),
            Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
    }

    // Point at angle (degrees, 0 = 3 o'clock, counter-clockwise) and radius from the centre.
    private function polar(w as Number, h as Number, degrees as Number, radius as Number) as Array<Number> {
        var rad = Math.toRadians(degrees);
        return [w / 2 + (radius * Math.cos(rad)).toNumber(), h / 2 - (radius * Math.sin(rad)).toNumber()];
    }

    // Greedy word wrap into at most maxLines; the last line ends in "..." when text is cut.
    private function wrap(dc as Graphics.Dc, text as String, font as Graphics.FontType, maxWidth as Number, maxLines as Number) as Array<String> {
        return TextFit.wrap(text, maxWidth, maxLines, new TextMeasure(dc, font).method(:width));
    }
}

class TextMeasure {
    private var _dc as Graphics.Dc;
    private var _font as Graphics.FontType;

    function initialize(dc as Graphics.Dc, font as Graphics.FontType) {
        _dc = dc;
        _font = font;
    }

    function width(text as String) as Number {
        return _dc.getTextWidthInPixels(text, _font);
    }
}
