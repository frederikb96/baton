import Toybox.Lang;

// The state object of the watch API. Fields the server leaves out or sends with another type stay null.
(:glance)
class PlayerState {
    var isPlaying as Boolean = false;
    var title as String? = null;
    var artist as String? = null;
    var progressMs as Number? = null;
    var durationMs as Number? = null;
    var liked as Boolean? = null;
    var inPlaylist as Boolean? = null;
    var playlistName as String? = null;

    function initialize(d as Dictionary) {
        isPlaying = flag(d["is_playing"] as Object?) == true;
        title = text((d["title"] as Object?));
        artist = text((d["artist"] as Object?));
        progressMs = number((d["progress_ms"] as Object?));
        durationMs = number((d["duration_ms"] as Object?));
        liked = flag((d["liked"] as Object?));
        inPlaylist = flag((d["in_playlist"] as Object?));
        playlistName = text((d["playlist_name"] as Object?));
    }

    // "Artist - Title", or whichever half is known
    function headline() as String? {
        if (artist != null && title != null) {
            return artist + " - " + title;
        }
        return title != null ? title : artist;
    }

    private function text(v as Object?) as String? {
        return v instanceof String ? v : null;
    }

    private function flag(v as Object?) as Boolean? {
        return v instanceof Boolean ? v : null;
    }

    private function number(v as Object?) as Number? {
        if (v instanceof Number || v instanceof Long || v instanceof Float || v instanceof Double) {
            return v.toNumber();
        }
        return null;
    }
}
