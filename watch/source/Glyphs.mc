import Toybox.Graphics;
import Toybox.Lang;

// Small icons drawn from shapes, centred on (x, y); s is the half-size in pixels.
module Glyphs {
    function play(dc as Graphics.Dc, x as Number, y as Number, s as Number, color as Number) as Void {
        dc.setColor(color, Graphics.COLOR_TRANSPARENT);
        dc.fillPolygon([[x - s * 2 / 5, y - s], [x - s * 2 / 5, y + s], [x + s * 4 / 5, y]]);
    }

    function pause(dc as Graphics.Dc, x as Number, y as Number, s as Number, color as Number) as Void {
        dc.setColor(color, Graphics.COLOR_TRANSPARENT);
        dc.fillRectangle(x - s * 3 / 5, y - s, s * 2 / 5, s * 2);
        dc.fillRectangle(x + s / 5, y - s, s * 2 / 5, s * 2);
    }

    function skip(dc as Graphics.Dc, x as Number, y as Number, s as Number, color as Number) as Void {
        dc.setColor(color, Graphics.COLOR_TRANSPARENT);
        dc.fillPolygon([[x - s * 3 / 5, y - s], [x - s * 3 / 5, y + s], [x + s * 3 / 10, y]]);
        dc.fillRectangle(x + s / 2, y - s, s * 3 / 10 + 1, s * 2);
    }

    function heart(dc as Graphics.Dc, x as Number, y as Number, s as Number, color as Number) as Void {
        var r = s * 11 / 20;
        dc.setColor(color, Graphics.COLOR_TRANSPARENT);
        dc.fillCircle(x - r, y - r / 2, r);
        dc.fillCircle(x + r, y - r / 2, r);
        dc.fillPolygon([[x - r * 2 + 1, y - r / 4], [x + r * 2 - 1, y - r / 4], [x, y + s]]);
    }

    function dots(dc as Graphics.Dc, x as Number, y as Number, s as Number, color as Number) as Void {
        dc.setColor(color, Graphics.COLOR_TRANSPARENT);
        for (var i = -1; i <= 1; i++) {
            dc.fillCircle(x + i * s, y, s / 3 + 1);
        }
    }

    // A list with a plus: the playlist the Up button adds to.
    function playlist(dc as Graphics.Dc, x as Number, y as Number, s as Number, color as Number) as Void {
        dc.setColor(color, Graphics.COLOR_TRANSPARENT);
        var bar = s / 4 + 1;
        dc.fillRectangle(x - s, y - s * 3 / 4, s * 2, bar);
        dc.fillRectangle(x - s, y - bar / 2, s + s / 2, bar);
        dc.fillRectangle(x - s, y + s * 3 / 4 - bar, s, bar);
        var px = x + s * 4 / 5;
        var py = y + s / 2;
        dc.fillRectangle(px - s / 2, py - bar / 2, s + 1, bar);
        dc.fillRectangle(px - bar / 2, py - s / 2, bar, s + 1);
    }
}
