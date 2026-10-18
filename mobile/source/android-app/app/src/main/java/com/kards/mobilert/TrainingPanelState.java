package com.kards.mobilert;

import org.json.JSONObject;

/** Read-only presentation of the campaign report. Never authorizes or retries a game action. */
public final class TrainingPanelState {
    public final boolean hasSession;
    public final boolean active;
    public final boolean finished;
    public final boolean interrupted;
    public final String sessionId;
    public final String statusKind;
    public final String title;
    public final String summary;
    public final String outcomeLabel;
    public final String durationDisplay;
    public final String turnCount;
    /** Confirmed deployment, movement and attack actions; excludes ending a turn. */
    public final String actionCount;
    /** User-facing explanation, never an internal reason code or exception. */
    public final String stopReason;
    public final String matchMode;
    public final String modeLabel;

    private TrainingPanelState(boolean hasSession, boolean active, boolean finished,
            boolean interrupted, String sessionId, String statusKind, String title,
            String summary, String outcomeLabel, String durationDisplay, String turnCount,
            String actionCount, String stopReason, String matchMode) {
        this.hasSession = hasSession;
        this.active = active;
        this.finished = finished;
        this.interrupted = interrupted;
        this.sessionId = sessionId;
        this.statusKind = statusKind;
        this.title = title;
        this.summary = summary;
        this.outcomeLabel = outcomeLabel;
        this.durationDisplay = durationDisplay;
        this.turnCount = turnCount;
        this.actionCount = actionCount;
        this.stopReason = stopReason;
        this.matchMode = matchMode;
        this.modeLabel = "casual".equals(matchMode) ? "休闲" : "ranked".equals(matchMode) ? "排位"
                : "training".equals(matchMode) ? "训练调试" : "模式未记录";
    }

    public static TrainingPanelState from(String report) {
        final JSONObject campaign;
        try {
            if (report == null || report.trim().isEmpty()) return empty();
            campaign = new JSONObject(report);
        } catch (Exception invalid) {
            return empty();
        }
        return fromCampaign(campaign).withMode(mode(campaign)).withCampaign(campaign);
    }

    private static TrainingPanelState fromCampaign(JSONObject campaign) {
        String id = string(campaign, "session_id");
        if (id.isEmpty()) return empty();

        String event = string(campaign, "event");
        boolean active = isTrue(campaign, "active");
        boolean knownInactive = Boolean.FALSE.equals(campaign.opt("active"));
        // A cancelled worker may still publish engine events before the campaign finishes.
        boolean stopping = "stopping".equals(event) || (knownInactive && !"finished".equals(event));
        boolean finished = knownInactive && "finished".equals(event);
        JSONObject engine = campaign.optJSONObject("engine");
        String engineKind = string(engine, "kind");
        // A live engine event has {kind,value}; the final campaign stores the summary directly.
        JSONObject value = engine == null ? null : engine.optJSONObject("value");
        JSONObject totals = "finished".equals(engineKind) ? value : engine;
        String turns = count(totals, "engine_turns_seen");
        if ("—".equals(turns) && ("think".equals(engineKind) || "hook".equals(engineKind))) {
            turns = count(value, "turn");
        }
        String actions = count(totals, "actions_confirmed");
        String stage = string(campaign, "stage");
        if ("menu".equals(stage) || "opening".equals(stage) || "menu".equals(engineKind)) {
            turns = "—";
            actions = "—";
        }
        // Missing live cumulative counters stay unknown: input attempts are not successes.
        String duration = duration(number(campaign, "elapsed_ms"));
        String reason = string(campaign, "reason");
        String engineReason = string(totals, "stop_reason");
        if (reason.isEmpty() || "engine_finished".equals(reason) || "finished".equals(reason)) {
            if (!engineReason.isEmpty()) reason = engineReason;
        }
        if ("opening_not_verified".equals(reason)) {
            String openingReason = string(campaign.optJSONObject("opening"), "stopReason");
            if (!openingReason.isEmpty()) reason = openingReason;
        }

        if (stopping) return state(active, false, false, id, "stopping", "正在停止训练",
                "正在结束当前操作，请稍候。", "正在停止", duration, turns, actions, "");

        if (active) {
            if (isTrue(campaign, "read_only")) return state(true, false, false, id,
                    "running", "正在观察游戏", "正在检查当前画面。", "观察中",
                    duration, turns, actions, "");
            if ("menu".equals(stage) || (stage.isEmpty() && "menu".equals(engineKind))) {
                String screen = "menu".equals(engineKind) ? string(value, "state") : "waiting_for_game";
                boolean waiting = "waiting_for_game".equals(screen);
                String title = waiting ? "等待游戏" : "queueing".equals(screen) ? "等待匹配"
                        : "mulligan_ready".equals(screen) ? "准备起手"
                        : "disconnected".equals(screen) ? "等待游戏连接" : "准备对局";
                return state(true, false, false, id, waiting ? "waiting" : "preparing", title, menuSummary(screen, mode(campaign)),
                        waiting ? "待命中" : "queueing".equals(screen) ? "匹配中" : "准备中", duration, turns, actions, "");
            }
            if ("opening".equals(stage)) return state(true, false, false, id, "preparing", "正在处理起手",
                    "正在确认起手牌，完成后自动进入战斗。", "起手中", duration, turns, actions, "");
            if ("battle".equals(stage)) return state(true, false, false, id, "running", "对局进行中",
                    runningSummary(engineKind, value), "进行中", duration, turns, actions, "");
            boolean preparing = "armed".equals(event) && engine == null;
            return state(true, false, false, id, preparing ? "preparing" : "running",
                    preparing ? "正在准备训练" : "训练进行中",
                    preparing ? "等待训练起手画面，进入对局后自动操作。" : runningSummary(engineKind, value),
                    preparing ? "准备中" : "进行中", duration, turns, actions, "");
        }

        boolean resultVerified = isTrue(totals, "result_verified");
        if (finished && resultVerified && ("result_victory".equals(reason) || "result_defeat".equals(reason))) {
            String outcome = "result_victory".equals(reason) ? "本局获胜" : "本局失利";
            return state(false, finished, false, id, "complete", "训练结束·" + outcome,
                    "已识别对局结算，自动操作已停止。" + singleEffectCaveat(campaign, totals), outcome, duration, turns, actions,
                    "对局已结束。");
        }
        if ("inspection_complete".equals(reason) && isTrue(campaign, "read_only")) {
            return state(false, finished, false, id, "complete", "观察已完成",
                    "已检查当前游戏画面。", "观察完成", duration, turns, actions, "观察已结束。");
        }
        if ("user_stop".equals(reason) || "cancelled".equals(reason)) {
            return state(false, finished, false, id, "stopped", "训练已停止",
                    "已按停止请求结束自动操作。", "已停止", duration, turns, actions, "手动停止。");
        }
        String detail = explain(reason, string(totals, "exception"),
                isTrue(campaign, "input_status_uncertain"));
        return state(false, finished, true, id, "interrupted", "训练已中断", detail,
                "未完成", duration, turns, actions, detail);
    }

    /** Historical files cannot establish that a worker is still running in this app process. */
    public static TrainingPanelState fromSaved(String report) {
        TrainingPanelState saved = from(report);
        if (!saved.hasSession || saved.finished) return saved;
        String explanation = "上次运行未留下结束记录，请查看游戏当前状态后重新开始。";
        TrainingPanelState history = state(false, true, true, saved.sessionId, "interrupted", "上次运行已中断",
                explanation, "未完成", saved.durationDisplay, saved.turnCount, saved.actionCount,
                explanation).withMode(saved.matchMode);
        try { return history.withCampaign(new JSONObject(report)); }
        catch (Exception invalid) { return history; }
    }

    private static TrainingPanelState empty() {
        return new TrainingPanelState(false, false, false, false, "", "empty", "准备开始对局",
                "开启辅助服务后，即可开始一局对战。", "暂无记录", "—", "—", "—", "", "unknown");
    }

    private static TrainingPanelState state(boolean active, boolean finished, boolean interrupted,
            String id, String kind, String title, String summary, String outcome,
            String duration, String turns, String actions, String reason) {
        return new TrainingPanelState(true, active, finished, interrupted, id, kind, title,
                summary, outcome, duration, turns, actions, reason, "training");
    }

    private static String mode(JSONObject campaign) {
        if (!campaign.has("match_mode")) {
            // Existing complete reports came from the training-only runtime. A missing summary
            // placeholder cannot establish which mode was selected before the process stopped.
            return "history_incomplete".equals(string(campaign, "event")) ? "unknown" : "training";
        }
        String mode = string(campaign, "match_mode");
        return "casual".equals(mode) || "ranked".equals(mode) || "training".equals(mode) ? mode : "unknown";
    }

    private TrainingPanelState withMode(String mode) {
        String label = "casual".equals(mode) ? "休闲对局" : "ranked".equals(mode) ? "排位对战" : "对局";
        boolean training = "training".equals(mode);
        return new TrainingPanelState(hasSession, active, finished, interrupted, sessionId, statusKind,
                training ? title : title.replace("训练", label),
                training ? summary : summary.replace("训练起手画面", "游戏起手画面").replace("训练画面", "游戏画面")
                        .replace("训练", "对局"), outcomeLabel, durationDisplay, turnCount, actionCount,
                training ? stopReason : stopReason.replace("训练起手画面", "游戏起手画面").replace("训练画面", "游戏画面")
                        .replace("训练", "对局"), mode);
    }

    private TrainingPanelState withCampaign(JSONObject campaign) {
        Object requested = campaign.opt("match_count");
        if (!(requested instanceof Integer || requested instanceof Long) || !hasSession) return this;
        long target = number(campaign, "match_count");
        if (target < 0 || target > Integer.MAX_VALUE || target == 1) return this;
        boolean unlimited = target == 0;
        long index = number(campaign, "round_index");
        long done = number(campaign, "completed_matches");
        String doneText = done < 0 || (!unlimited && done > target) ? "—" : Long.toString(done);
        String progress = "第 " + (index > 0 ? Long.toString(index) : "—")
                + (unlimited ? " 局 · 无限循环" : " / " + target + " 局");
        String newTitle = title, newSummary = progress + "。" + summary;
        String newOutcome = outcomeLabel;
        String newTurns = turnCount, newActions = actionCount;
        boolean complete = !unlimited && "campaign_complete".equals(string(campaign, "reason")) && done == target
                && finished && !isTrue(campaign, "input_status_uncertain");
        org.json.JSONArray rounds = campaign.optJSONArray("rounds");
        boolean projected = "campaign_progress_v1".equals(string(campaign, "report_kind"));
        JSONObject totals = projected ? campaign.optJSONObject("round_totals") : null;
        // Only the session evaluates full input/hook evidence. A bounded live
        // projection carries that terminal verdict, never incomplete evidence.
        complete &= projected ? isTrue(campaign, "campaign_complete_verified")
                && number(totals, "closed_round_count") == target
                && isTrue(totals, "all_closed_rounds_safe")
                && !isTrue(campaign, "projection_overflow")
                : rounds != null && rounds.length() == target;
        if (complete && !projected) for (int i = 0; i < rounds.length(); i++) {
            JSONObject row = rounds.optJSONObject(i);
            JSONObject engine = row == null ? null : row.optJSONObject("engine");
            JSONObject settle = row == null ? null : row.optJSONObject("settle");
            complete &= MatchCampaignPlan.resultConfirmed(engine) && MatchCampaignPlan.returned(settle)
                    && MatchCampaignPlan.continuationEvidence(engine).safe
                    && !isTrue(row, "input_status_uncertain")
                    && !(engine.has("exception") && !engine.isNull("exception"));
        }
        if (complete) {
            newTitle = (target == 2 ? "两" : Long.toString(target)) + "局对战已完成";
            newSummary = "已确认 " + target + " 局胜负并完成回页，本次辅助已停止。";
            newOutcome = "完成 " + target + " / " + target + " 局";
        } else if (unlimited) {
            newSummary = (finished ? "无限循环已停止。" : progress + "。")
                    + "已确认 " + doneText + " 局胜负。" + summary;
            if (finished) {
                newOutcome = "已确认 " + doneText + " 局";
                // A result for the last game cannot complete an unlimited run.
                if ("complete".equals(statusKind)) newTitle = "无限循环已停止";
            }
        } else if (finished) {
            newSummary = "已确认 " + doneText + " / " + target + " 局胜负。" + summary;
        }
        long turns = 0, actions = 0;
        boolean knownTurns = rounds != null && rounds.length() > 0;
        boolean knownActions = knownTurns;
        if (rounds != null) for (int i = 0; i < rounds.length(); i++) {
            JSONObject row = rounds.optJSONObject(i);
            JSONObject engine = row == null ? null : row.optJSONObject("engine");
            long oneTurns = number(engine, "engine_turns_seen"), oneActions = number(engine, "actions_confirmed");
            if (oneTurns < 0) knownTurns = false; else turns += oneTurns;
            if (oneActions < 0) knownActions = false; else actions += oneActions;
        }
        if (projected) {
            turns = number(totals, "engine_turns_seen");
            actions = number(totals, "actions_confirmed");
            knownTurns = turns >= 0;
            knownActions = actions >= 0;
        }
        if (finished && knownTurns) newTurns = Long.toString(turns);
        if (finished && knownActions) newActions = Long.toString(actions);
        if (projected && finished) {
            if (!knownTurns) newTurns = "—";
            if (!knownActions) newActions = "—";
        }
        long unknownEffects = 0;
        boolean knownEffects = rounds != null && rounds.length() > 0;
        if (rounds != null) for (int i = 0; i < rounds.length(); i++) {
            JSONObject row = rounds.optJSONObject(i);
            long unknown = effectUnknown(row == null ? null : row.optJSONObject("engine"));
            if (unknown < 0 || unknownEffects > Long.MAX_VALUE - unknown) knownEffects = false;
            else unknownEffects += unknown;
        }
        if (projected) {
            unknownEffects = number(totals, "unconfirmed_inputs");
            knownEffects = unknownEffects >= 0;
        }
        if (knownEffects && unknownEffects > 0) newSummary += effectCaveat(unknownEffects);
        boolean incompleteTarget = !unlimited && finished && !complete && "complete".equals(statusKind);
        if (incompleteTarget) {
            newTitle = "本次对战未完成";
            newOutcome = "未完成";
        }
        return new TrainingPanelState(hasSession, active, finished, complete ? false : incompleteTarget || interrupted,
                sessionId, complete ? "complete" : incompleteTarget ? "interrupted"
                        : unlimited && finished && "complete".equals(statusKind) ? "stopped" : statusKind,
                newTitle, newSummary, newOutcome,
                durationDisplay, newTurns, newActions, complete ? "对局已结束。"
                        : incompleteTarget ? "尚未完成本次全部局数。" : stopReason, matchMode);
    }

    private static long effectUnknown(JSONObject engine) {
        if (engine == null) return -1;
        if (!engine.has("unconfirmed_inputs")) return 0;
        return number(engine, "unconfirmed_inputs");
    }

    private static String singleEffectCaveat(JSONObject campaign, JSONObject engine) {
        Object requested = campaign.opt("match_count");
        if ((requested instanceof Integer || requested instanceof Long)
                && (((Number) requested).longValue() == 0 || ((Number) requested).longValue() > 1)) return "";
        return effectCaveat(engine);
    }

    private static String effectCaveat(JSONObject engine) { return effectCaveat(effectUnknown(engine)); }

    private static String effectCaveat(long unknown) {
        return unknown > 0 ? "其中 " + unknown + " 次操作的效果未确认。" : "";
    }

    private static String menuSummary(String screen, String mode) {
        switch (screen) {
            case "waiting_for_game": return "辅助已待命，等待 KARDS 进入前台。使用手动入口时，请切到后台自行打开 KARDS；对战准备最多等待 3 分钟。";
            case "home": return "正在进入对战菜单。";
            case "mode_menu": return "正在选择对战模式。";
            case "deck_list": return "正在选择列表中第一个牌组。";
            case "deck_ready": return "正在准备" + ("ranked".equals(mode) ? "排位对战" : "casual".equals(mode) ? "休闲对局" : "对局") + "。";
            case "queueing": return "正在寻找对手，匹配成功后自动进入对局。";
            case "mulligan_ready": return "已进入起手画面，正在准备确认。";
            case "unknown": return "等待画面稳定，再继续准备对局。";
            case "menu_transition": return "等待页面和牌组显示完整，再继续准备对局。";
            case "login_reward": return "正在检查登录奖励页面。";
            case "task_popup": return "正在关闭任务提示，随后继续准备对局。";
            case "pass_popup": return "正在关闭通行证提示，随后继续准备对局。";
            case "box_popup": return "正在关闭奖励箱提示，随后继续准备对局。";
            case "store_popup": return "正在关闭商店提示，随后继续准备对局。";
            case "airdrop_popup": return "正在关闭空投优惠提示，随后继续准备对局。";
            case "starter_popup": return "正在关闭新手优惠提示，随后继续准备对局。";
            case "weekend_popup": return "正在关闭周末优惠提示，随后继续准备对局。";
            case "disconnected": return "游戏连接已断开，请先恢复连接。";
            default: return "等待游戏进入前台。";
        }
    }

    private static String runningSummary(String kind, JSONObject value) {
        if ("capture".equals(kind)) {
            String screen = string(value, "state");
            if ("victory".equals(screen) || "defeat".equals(screen)) return "正在确认对局结算。";
            if (value != null && isTrue(value.optJSONObject("opponent_turn_label"), "present")) {
                return "等待对方行动，轮到我方后继续。";
            }
        }
        return "正在自动出牌、移动和攻击。请保持游戏在前台。";
    }

    private static String explain(String reason, String exception, boolean uncertain) {
        if (uncertain || reason.contains("input_status_uncertain") || reason.contains("gesture_not_completed")) {
            return "未能确认操作已完成，自动操作已停止。请查看游戏当前状态。";
        }
        if (reason.contains("SecurityException") || exception.contains("SecurityException")
                || reason.contains("permission") || reason.contains("accessibility")) {
            return "辅助服务暂不可用，请检查授权后重试。";
        }
        if (reason.contains("foreground_changed") || reason.contains("not_game_foreground")) {
            return "游戏已离开前台。回到训练画面后可重新开始。";
        }
        if (reason.contains("capture_black_frame"))
            return "系统截图连续返回黑屏。请在工具与诊断中启用兼容截图，再重新开始辅助。";
        if (reason.contains("compat_capture_incomplete_frame"))
            return "兼容截图连续不完整，重试后仍未恢复，已停止。请检查模拟器画面与截图设置。";
        if (reason.contains("compat_capture"))
            return "兼容截图已中断，请在工具与诊断中重新启用后再开始辅助。";
        if (reason.startsWith("menu_")) return "对战准备未完成，请检查游戏画面后重试。";
        if (reason.startsWith("time_budget") || "input_budget".equals(reason) || "frame_budget".equals(reason)) {
            return "已达到本次训练上限，自动操作已停止。";
        }
        if (reason.startsWith("choice_modal") || "engine_requests_intervention".equals(reason)) {
            return "当前画面需要手动处理。完成选择后可重新开始。";
        }
        if (reason.contains("capture") || reason.contains("截图能力") || reason.contains("invalid_frame")
                || reason.contains("frame_expired") || reason.contains("stale") || reason.contains("frame_size")) {
            return "暂时无法读取清晰的游戏画面，请检查游戏显示和辅助服务后重试。";
        }
        if (reason.contains("unknown_screen") || reason.contains("recognition")
                || reason.startsWith("unsupported_state") || "opening_not_verified".equals(reason)
                || "post_verification_timeout".equals(reason)) {
            return "未能确认当前游戏画面。回到训练起手画面后重试。";
        }
        if (reason.startsWith("repeated_unconfirmed") || "no_progress_timeout".equals(reason)) {
            return "暂时无法继续推进对局，自动操作已停止。请查看游戏当前状态。";
        }
        if (reason.contains("storage") || reason.contains("evidence_write") || reason.contains("summary_write")) {
            return "训练记录保存失败，请检查可用存储空间后重试。";
        }
        return "本次训练未能完成，自动操作已停止。可在诊断信息中查看详情。";
    }

    private static String string(JSONObject json, String key) {
        Object value = json == null ? null : json.opt(key);
        return value instanceof String ? ((String) value).trim() : "";
    }

    private static boolean isTrue(JSONObject json, String key) {
        return json != null && Boolean.TRUE.equals(json.opt(key));
    }

    private static long number(JSONObject json, String key) {
        Object value = json == null ? null : json.opt(key);
        if (!(value instanceof Number)) return -1;
        double numeric = ((Number) value).doubleValue();
        if (!Double.isFinite(numeric) || numeric < 0 || numeric != Math.floor(numeric)
                || numeric >= Long.MAX_VALUE) return -1;
        return ((Number) value).longValue();
    }

    private static String count(JSONObject json, String key) {
        long value = number(json, key);
        return value < 0 ? "—" : Long.toString(value);
    }

    private static String duration(long milliseconds) {
        if (milliseconds < 0) return "—";
        long seconds = milliseconds / 1000;
        if (seconds < 60) return seconds + "秒";
        long minutes = seconds / 60;
        if (minutes < 60) return minutes + "分" + seconds % 60 + "秒";
        return minutes / 60 + "小时" + minutes % 60 + "分";
    }
}
