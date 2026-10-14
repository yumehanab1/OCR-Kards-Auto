package com.kards.mobilert;

import org.json.JSONObject;

/** A start request's answer, independent of the previous campaign's report. */
final class BattleStartAttempt {
    private BattleStartAttempt() { }

    static String busyReason(BattleWorkerLease.Snapshot lease, boolean ownerActive) {
        if (!lease.isOwned()) return "";
        if (ownerActive) return "active_campaign";
        if ("UNBOUND".equals(lease.workerState) || "NEW".equals(lease.workerState)) return "worker_reserved";
        return "worker_still_finishing";
    }

    static String report(boolean accepted, String operation, String reason, long elapsed,
                         String priorSessionId, boolean priorActive, String sessionId,
                         BattleWorkerLease.Snapshot lease, String errorDetail) {
        try {
            JSONObject worker = new JSONObject().put("owned", lease.isOwned())
                    .put("owner_session_id", lease.sessionId).put("worker_state", lease.workerState)
                    .put("worker_name", lease.workerName)
                    .put("recovered_terminated_session_id", lease.recoveredSessionId);
            JSONObject value = new JSONObject().put("event", accepted ? "start_accepted" : "start_rejected")
                    .put("accepted", accepted).put("operation", operation).put("reason", reason)
                    .put("attempted_elapsed_ms", elapsed).put("prior_session_id", priorSessionId)
                    .put("prior_active", priorActive).put("session_id", sessionId).put("lease", worker);
            if (errorDetail != null && !errorDetail.isEmpty()) value.put("error_detail", errorDetail);
            return value.toString();
        } catch (Exception impossible) {
            return "{\"event\":\"start_rejected\",\"accepted\":false,\"reason\":\"start_diagnostics_error\"}";
        }
    }

    static String userMessage(String report) {
        String reason;
        try { reason = new JSONObject(report).optString("reason"); }
        catch (Exception invalid) { reason = "start_diagnostics_error"; }
        switch (reason) {
            case "active_campaign": return "上一场辅助仍在运行。请先停止当前辅助，等待收尾完成后再开始。";
            case "worker_still_finishing": return "上一场已停止，后台引擎仍在保存记录和退出。请等待收尾完成后再开始。";
            case "worker_reserved": return "上一场正在准备开局或取消开局。请等待当前会话结束后再开始。";
            case "invalid_options": return "启动参数无效。请重新选择对局模式后再试。";
            case "current_game_not_foreground": return "游戏尚未在前台。请先打开 KARDS，再启动本次调试。";
            case "opening_start_failed": return "开局辅助未能启动。请检查游戏画面和无障碍服务后再试。";
            case "worker_start_failed": return "后台引擎未能启动。请查看诊断记录后重试。";
            default: return "本次辅助未能启动（" + reason + "）。请查看诊断记录后重试。";
        }
    }
}
