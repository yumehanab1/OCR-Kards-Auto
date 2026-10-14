package com.kards.mobilert;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Debug-only orchestration, restricted to the shell's DUMP permission. */
public final class DebugMulliganReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        KardsAccessibilityService service = KardsAccessibilityService.instance();
        if (service == null) {
            setResultCode(1);
            setResultData("service_not_connected; no action armed");
            return;
        }
        try {
            if ("com.kards.mobilert.debug.STOP_MULLIGAN".equals(intent.getAction())) {
                service.cancelMulligan();
            } else if ("com.kards.mobilert.debug.START_MULLIGAN".equals(intent.getAction())) {
                Intent game = context.getPackageManager().getLaunchIntentForPackage("com.android1939.kards");
                if (game == null) throw new IllegalStateException("game_not_installed");
                if (!service.startMulliganOnce()) {
                    setResultCode(3);
                    setResultData(service.lastSessionReport());
                    return;
                }
                game.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                context.startActivity(game);
            } else {
                setResultCode(2);
                setResultData("unsupported_action");
                return;
            }
            setResultCode(0);
            setResultData(service.lastSessionReport());
        } catch (RuntimeException error) {
            service.cancelMulligan();
            setResultCode(3);
            setResultData("session_start_failed: " + error.getClass().getSimpleName());
        }
    }
}
