import Toybox.Lang;
import Toybox.System;

// Lines go to the simulator console and, on a device, to GARMIN/APPS/LOGS/<app file name>.TXT when
// that file exists. Neither the key nor request headers are ever logged.
(:glance)
module Log {
    function line(tag as String, message as String) as Void {
        System.println(System.getTimer() + " " + tag + " " + message);
    }

    // The battery level in percent, as precise as the device reports it.
    function battery(event as String) as Void {
        line("battery", event + " " + System.getSystemStats().battery.format("%.2f") + "%");
    }
}
