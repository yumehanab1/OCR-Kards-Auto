package com.kards.mobilert;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Development orchestration only. No game coordinates are accepted from broadcasts. */
public final class DebugBattleReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        KardsAccessibilityService service = KardsAccessibilityService.instance();
        if (service == null) { setResultCode(1); setResultData("service_not_connected"); return; }
        boolean armedThisRequest = false;
        try {
            String action = intent.getAction();
            if("com.kards.mobilert.debug.CAPTURE_AUDIT".equals(action)) {
                setResultCode(0);setResultData(DebugScreenshotAudit.start(service));return;
            }
            if("com.kards.mobilert.debug.WINDOW_STATUS".equals(action)) {
                setResultCode(0);setResultData(service.gameWindowDiagnostic());return;
            }
            if ("com.kards.mobilert.debug.START_BATTLE".equals(action)) {
                String options = intent.getStringExtra("options");
                String mode = GameEntryGate.parseMode(new org.json.JSONObject(options == null ? "{}" : options));
                Intent game = null;
                if (GameEntryGate.LAUNCH_GAME.equals(mode)) {
                    game = GamePackages.findLaunchable(context.getPackageManager()::getLaunchIntentForPackage);
                    if (game == null) throw new IllegalStateException("game_not_installed");
                }
                if (!service.startBattle(options)) { setResultCode(3); setResultData(service.lastStartAttempt()); return; }
                armedThisRequest = true;
                if (game != null) {
                    game.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    context.startActivity(game);
                }
            } else if ("com.kards.mobilert.debug.STOP_BATTLE".equals(action)) service.cancelBattle();
            else if ("com.kards.mobilert.debug.SETTLE_ONCE".equals(action)) {
                // Test the settlement dismissal on the screen that is up now.
                // The reviewed point list and the click budget stay in the
                // guard; no coordinate may arrive from a broadcast.
                org.json.JSONObject options = new org.json.JSONObject()
                        .put("entry_mode", GameEntryGate.CURRENT_GAME)
                        .put("match_mode", "casual")
                        .put("read_only", false)
                        .put("start_with_opening", false)
                        .put("max_seconds", 180)
                        .put("post_match_settle", true)
                        .put("native_menu", intent.getBooleanExtra("native_menu", false))
                        .put("settle_points", reviewedPoints())
                        .put("debug_stage", "settle");
                if (!service.startSettleOnce(options.toString())) {
                    setResultCode(3); setResultData(service.lastStartAttempt()); return;
                }
                armedThisRequest = true;
            } else if (!"com.kards.mobilert.debug.STATUS_BATTLE".equals(action)) {
                setResultCode(2); setResultData("unsupported_action"); return;
            }
            setResultCode(0); setResultData(service.battleProgressReport());
        } catch (Exception error) {
            if (armedThisRequest) service.cancelBattle();
            setResultCode(3);
            try {
                String reason = armedThisRequest ? "game_launch_failed"
                        : "game_not_installed".equals(error.getMessage()) ? "game_not_installed"
                        : error instanceof IllegalArgumentException || error instanceof org.json.JSONException
                                ? "invalid_options" : "invalid_request";
                setResultData(new org.json.JSONObject().put("event", "start_rejected").put("accepted", false)
                        .put("reason", reason)
                        .put("error_detail", error.getClass().getSimpleName() + ":" + error.getMessage()).toString());
            } catch (Exception impossible) { setResultData("battle_error:" + error.getClass().getSimpleName()); }
        }
    }

    /** The reviewed candidates, taken from the guard that enforces them. */
    private static org.json.JSONArray reviewedPoints() {
        org.json.JSONArray points = new org.json.JSONArray();
        for (int[] point : SettleDispatchGuard.DEFAULT_POINTS) {
            points.put(new org.json.JSONArray().put(point[0]).put(point[1]));
        }
        return points;
    }
}
