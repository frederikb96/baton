import Toybox.Communications;
import Toybox.Lang;

// The one place that talks to Communications.
(:glance)
module Wire {
    // Sends request to the configured server; the callback gets (responseCode, data).
    function send(request as Request, callback as Method(responseCode as Number, data as Dictionary or String or Null) as Void) as Void {
        var options = {
            :method => request.method,
            :headers => {
                "Authorization" => "Bearer " + ServerConfig.key()
            },
            :responseType => Communications.HTTP_RESPONSE_CONTENT_TYPE_JSON
        };
        Communications.makeWebRequest(ServerConfig.url() + request.path, {}, options, callback);
    }
}
