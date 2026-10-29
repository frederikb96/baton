import Toybox.Lang;
import Toybox.System;

// One request in flight at a time: the phone link queues badly (as little as one pending request on
// some phones), so the next call goes out from the previous callback. Commands wait in a short queue
// and go before the next poll; a poll is only started when nothing else waits.
class ApiClient {
    // the state is also refreshed by every command answer
    const POLL_INTERVAL_MS = 10000;
    // no callback after this long: the call is given up and its late answer ignored
    const TIMEOUT_MS = 25000;
    const MAX_QUEUED = 3;

    private var _listener as Method(request as Request, outcome as Outcome) as Void;
    private var _queue as Array<Request> = [];
    private var _inFlight as PendingCall? = null;
    private var _pollDueAt as Number = 0;

    function initialize(listener as Method(request as Request, outcome as Outcome) as Void) {
        _listener = listener;
    }

    function command(request as Request, now as Number) as Void {
        if (_queue.size() >= MAX_QUEUED) {
            _listener.invoke(request, Outcome.failed("busy"));
            return;
        }
        _queue.add(request);
        pump(now);
    }

    // Called every second: gives up stuck calls, starts queued commands and due polls.
    function tick(now as Number, polling as Boolean) as Void {
        var call = _inFlight;
        if (call != null && now - call.startedAt > TIMEOUT_MS) {
            _inFlight = null;
            Log.line("api", "timeout " + call.request.path);
            _listener.invoke(call.request, Outcome.failed("timeout"));
        }
        pump(now);
        if (polling && _inFlight == null && _queue.size() == 0 && now >= _pollDueAt && phoneConnected()) {
            issue(Command.state(), now);
        }
    }

    // The next tick polls.
    function pollSoon() as Void {
        _pollDueAt = 0;
    }

    function phoneConnected() as Boolean {
        return System.getDeviceSettings().phoneConnected;
    }

    function finish(call as PendingCall, responseCode as Number, data as Dictionary or String or Null) as Void {
        if (_inFlight != call) {
            Log.line("api", "late answer ignored " + call.request.path);
            return;
        }
        var now = System.getTimer();
        _inFlight = null;
        _pollDueAt = now + POLL_INTERVAL_MS;
        Log.line("api", call.request.path + " http=" + responseCode + " rtt=" + (now - call.startedAt) + "ms");
        _listener.invoke(call.request, Outcome.fromResponse(responseCode, data));
        pump(now);
    }

    private function pump(now as Number) as Void {
        while (_inFlight == null && _queue.size() > 0) {
            var request = _queue[0];
            _queue = _queue.slice(1, null);
            if (phoneConnected()) {
                issue(request, now);
            } else {
                _listener.invoke(request, Outcome.failed("no_phone"));
            }
        }
    }

    private function issue(request as Request, now as Number) as Void {
        var call = new PendingCall(self, request, now);
        _inFlight = call;
        try {
            Wire.send(request, call.method(:onResponse));
        } catch (ex) {
            _inFlight = null;
            _pollDueAt = now + POLL_INTERVAL_MS;
            Log.line("api", "send failed " + request.path);
            _listener.invoke(request, Outcome.failed("send_failed"));
        }
    }
}

// Binds one response to the request it answers.
class PendingCall {
    var request as Request;
    var startedAt as Number;
    private var _client as ApiClient;

    function initialize(client as ApiClient, request as Request, startedAt as Number) {
        _client = client;
        self.request = request;
        self.startedAt = startedAt;
    }

    function onResponse(responseCode as Number, data as Dictionary or String or Null) as Void {
        _client.finish(self, responseCode, data);
    }
}
