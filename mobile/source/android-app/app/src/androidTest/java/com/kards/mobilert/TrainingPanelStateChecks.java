package com.kards.mobilert;

import org.json.JSONArray;
import org.json.JSONObject;

/** JSON presentation checks only; no service, screenshots, gestures or game state changes. */
public final class TrainingPanelStateChecks {
    private final JSONArray checks = new JSONArray();
    private int failures;

    public static JSONObject run() throws Exception {
        return run(null);
    }

    /** A host runner can additionally pass the original, unmodified live20 summary. */
    public static JSONObject run(String originalLive20Report) throws Exception {
        TrainingPanelStateChecks test = new TrainingPanelStateChecks();
        test.emptyAndMalformed();
        test.live20(originalLive20Report == null ? live20Projection() : originalLive20Report);
        test.activeStates();
        test.terminalStates();
        test.invalidStatistics();
        test.savedHistory();
        test.formalModesAndStages();
        test.waitingForUserGameEntry();
        test.twoRoundCampaign();
        test.numericCampaign();
        test.continuationEffects();
        test.boundedCampaignProgress();
        return new JSONObject().put("checks", test.checks).put("check_count", test.checks.length())
                .put("failure_count", test.failures).put("test_count", test.checks.length()).put("device_inputs", 0)
                .put("uses_real_service", false)
                .put("original_live20_report_supplied", originalLive20Report != null);
    }

    private void boundedCampaignProgress() throws Exception {
        JSONObject totals = new JSONObject().put("closed_round_count", 3)
                .put("all_closed_rounds_safe", true).put("engine_turns_seen", 27)
                .put("actions_confirmed", 72).put("unconfirmed_inputs", 11);
        JSONObject progress = campaign("finished", false, "campaign_complete")
                .put("report_kind", "campaign_progress_v1").put("match_mode", "casual")
                .put("match_count", 3).put("round_index", 3).put("completed_matches", 3)
                .put("round_totals", totals).put("campaign_complete_verified", true)
                .put("engine", new JSONObject().put("full_game_passed", false));
        TrainingPanelState complete = TrainingPanelState.from(progress.toString());
        check("bounded_progress_uses_full_evidence_verdict_and_preserves_unknown",
                complete.finished && !complete.interrupted && "complete".equals(complete.statusKind)
                && complete.summary.contains("11 次") && "72".equals(complete.actionCount)
                && "27".equals(complete.turnCount) && !progress.has("rounds"));
        for (String field : new String[] {"campaign_complete_verified", "round_totals"}) {
            JSONObject missing = new JSONObject(progress.toString());
            missing.remove(field);
            check("bounded_progress_missing_" + field + "_cannot_complete",
                    !"complete".equals(TrainingPanelState.from(missing.toString()).statusKind));
        }
        for (Object flag : new Object[] {false, "true", 1, JSONObject.NULL}) {
            progress.put("campaign_complete_verified", flag);
            check("bounded_progress_verdict_is_strict_boolean_" + checks.length(),
                    !"complete".equals(TrainingPanelState.from(progress.toString()).statusKind));
        }
        progress.put("campaign_complete_verified", true);
        totals.put("all_closed_rounds_safe", false);
        check("bounded_progress_unsafe_closed_round_cannot_complete",
                !"complete".equals(TrainingPanelState.from(progress.toString()).statusKind));
        totals.put("all_closed_rounds_safe", true).put("closed_round_count", 2);
        check("bounded_progress_partial_campaign_cannot_complete",
                !"complete".equals(TrainingPanelState.from(progress.toString()).statusKind));
        totals.put("closed_round_count", 3);
        progress.put("input_status_uncertain", true);
        check("bounded_progress_uncertain_input_cannot_complete",
                !"complete".equals(TrainingPanelState.from(progress.toString()).statusKind));
        progress.put("input_status_uncertain", false).put("projection_overflow", true);
        check("bounded_progress_overflow_cannot_complete",
                !"complete".equals(TrainingPanelState.from(progress.toString()).statusKind));
        progress.remove("projection_overflow");
        progress.put("event", "engine").put("active", true).put("stage", "battle");
        check("bounded_progress_active_is_never_complete", TrainingPanelState.from(progress.toString()).active
                && !TrainingPanelState.from(progress.toString()).finished);
        progress.put("event", "finished").put("active", false).put("match_count", 0);
        check("bounded_progress_unlimited_never_completes_target",
                !"complete".equals(TrainingPanelState.from(progress.toString()).statusKind));
        totals.put("actions_confirmed", JSONObject.NULL).put("engine_turns_seen", -1);
        TrainingPanelState unknown = TrainingPanelState.from(progress.toString());
        check("bounded_progress_missing_counts_stay_unknown", "—".equals(unknown.actionCount)
                && "—".equals(unknown.turnCount));
    }

    private void emptyAndMalformed() throws Exception {
        for (String source : new String[] {null, "", " ", "{}", "null", "[]", "{bad json", "{\"session_id\":null}"}) {
            TrainingPanelState state = TrainingPanelState.from(source);
            check("empty_or_invalid_is_not_a_completed_session_" + checks.length(),
                    !state.hasSession && !state.active && !state.finished && !state.interrupted
                            && "暂无记录".equals(state.outcomeLabel)
                            && "—".equals(state.actionCount) && "—".equals(state.turnCount));
        }
    }

    private void twoRoundCampaign() throws Exception {
        JSONObject first = new JSONObject().put("engine",new JSONObject().put("engine_turns_seen",4).put("actions_confirmed",6)
                .put("result_verified",true).put("stop_reason","result_victory"))
                .put("settle",new JSONObject().put("final_state","deck_list").put("reason_after_return","return_reached:deck_list"));
        JSONObject second = new JSONObject().put("engine",new JSONObject().put("engine_turns_seen",8).put("actions_confirmed",9)
                .put("result_verified",true).put("stop_reason","result_defeat"))
                .put("settle",new JSONObject().put("final_state","home").put("reason_after_return","return_not_needed:home"));
        JSONObject campaign = new JSONObject().put("session_id","loop-check").put("match_mode","casual")
                .put("match_count",2).put("round_index",2).put("completed_matches",1)
                .put("event","menu").put("active",true).put("stage","menu")
                .put("engine",new JSONObject().put("kind","menu").put("value",new JSONObject().put("state","menu_transition")))
                .put("rounds",new JSONArray().put(first));
        TrainingPanelState running = TrainingPanelState.from(campaign.toString());
        check("second_round_progress_is_visible",running.active && running.summary.contains("第 2 / 2 局") && running.summary.contains("显示完整"));
        campaign.put("active",false).put("event","finished").put("reason","campaign_complete")
                .put("completed_matches",2).put("rounds",new JSONArray().put(first).put(second));
        TrainingPanelState complete = TrainingPanelState.from(campaign.toString());
        check("two_round_complete_has_clear_outcome",complete.finished && !complete.interrupted
                && "两局对战已完成".equals(complete.title) && "完成 2 / 2 局".equals(complete.outcomeLabel));
        check("two_round_stats_sum_all_rounds","12".equals(complete.turnCount) && "15".equals(complete.actionCount));
        JSONObject deckReturn = second.getJSONObject("settle");
        deckReturn.put("final_state","deck_ready").put("reason_after_return","return_not_needed:deck_ready");
        TrainingPanelState deckComplete = TrainingPanelState.from(campaign.toString());
        check("two_round_deck_details_completion_agrees_with_campaign", !deckComplete.interrupted
                && "两局对战已完成".equals(deckComplete.title) && "完成 2 / 2 局".equals(deckComplete.outcomeLabel));
        deckReturn.put("reason_after_return","return_not_needed:deck_list");
        check("deck_details_wrong_return_reason_does_not_claim_complete",TrainingPanelState.from(campaign.toString()).interrupted);
        deckReturn.put("final_state","task_popup").put("reason_after_return","return_reached:task_popup");
        check("task_overlay_never_claims_two_round_completion",TrainingPanelState.from(campaign.toString()).interrupted);
        deckReturn.put("final_state","home").put("reason_after_return","return_not_needed:home");
        campaign.put("reason","campaign_return_unverified").put("completed_matches",1);
        TrainingPanelState stopped = TrainingPanelState.from(campaign.toString());
        check("incomplete_loop_does_not_claim_two_matches",stopped.interrupted && stopped.summary.contains("已确认 1 / 2 局"));
        campaign.put("reason","campaign_complete").put("completed_matches",2).put("input_status_uncertain",true);
        check("uncertain_loop_cannot_claim_complete",TrainingPanelState.from(campaign.toString()).interrupted);
        campaign.put("input_status_uncertain",false).put("rounds",new JSONArray().put(first));
        check("count_alone_cannot_claim_complete",TrainingPanelState.from(campaign.toString()).interrupted);
    }

    private void numericCampaign() throws Exception {
        JSONObject row = new JSONObject().put("engine",new JSONObject().put("engine_turns_seen",4).put("actions_confirmed",6)
                .put("result_verified",true).put("stop_reason","result_defeat"))
                .put("settle",new JSONObject().put("final_state","home").put("reason_after_return","return_reached:home"));
        JSONArray rounds = new JSONArray().put(new JSONObject(row.toString())).put(new JSONObject(row.toString()))
                .put(new JSONObject(row.toString()));
        JSONObject report = campaign("engine",true,"menu").put("match_mode","casual").put("stage","menu")
                .put("match_count",3).put("round_index",3).put("completed_matches",2).put("rounds",rounds)
                .put("engine",new JSONObject().put("kind","menu").put("value",new JSONObject().put("state","home")));
        check("arbitrary_finite_count_and_current_round_are_visible", TrainingPanelState.from(report.toString()).summary.contains("第 3 / 3 局"));
        report.put("event","finished").put("active",false).put("reason","campaign_complete").put("completed_matches",3);
        TrainingPanelState complete = TrainingPanelState.from(report.toString());
        check("three_matches_complete_only_with_all_round_evidence", "3局对战已完成".equals(complete.title)
                && "完成 3 / 3 局".equals(complete.outcomeLabel) && !complete.interrupted && "complete".equals(complete.statusKind));
        check("arbitrary_match_count_sums_round_statistics", "12".equals(complete.turnCount) && "18".equals(complete.actionCount));
        rounds.getJSONObject(2).getJSONObject("engine").put("unconfirmed_inputs",1);
        check("finite_complete_refuses_unproven_unknown_without_ledger", TrainingPanelState.from(report.toString()).interrupted);
        rounds.getJSONObject(2).getJSONObject("engine").remove("unconfirmed_inputs");
        rounds.getJSONObject(2).getJSONObject("engine").put("exception","private_internal_detail");
        check("finite_complete_refuses_round_exception", TrainingPanelState.from(report.toString()).interrupted);
        rounds.getJSONObject(2).getJSONObject("engine").remove("exception");
        report.put("rounds",new JSONArray().put(row).put(row));
        check("finite_count_alone_never_proves_all_rounds", TrainingPanelState.from(report.toString()).interrupted);
        report.put("reason","engine_finished").put("engine",row.getJSONObject("engine")).put("completed_matches",2);
        check("one_game_result_cannot_complete_a_larger_finite_target", TrainingPanelState.from(report.toString()).interrupted
                && "本次对战未完成".equals(TrainingPanelState.from(report.toString()).title));
        report.put("rounds",rounds).put("match_count",0).put("event","engine").put("active",true)
                .put("reason","menu").put("round_index",4).put("completed_matches",3);
        TrainingPanelState infinite = TrainingPanelState.from(report.toString());
        check("unlimited_progress_has_completed_count_without_zero_target", infinite.active && infinite.summary.contains("第 4 局 · 无限循环")
                && infinite.summary.contains("已确认 3 局胜负") && !infinite.summary.contains(" / 0"));
        report.put("event","finished").put("active",false).put("reason","user_stop");
        TrainingPanelState stopped = TrainingPanelState.from(report.toString());
        check("unlimited_stopped_reports_confirmed_games_without_finite_completion", stopped.finished && "stopped".equals(stopped.statusKind)
                && "已确认 3 局".equals(stopped.outcomeLabel) && stopped.summary.contains("无限循环已停止")
                && !stopped.summary.contains(" / 0") && !stopped.title.contains("对战已完成"));
        report.put("reason","campaign_complete");
        check("unlimited_never_claims_campaign_target_completion", TrainingPanelState.from(report.toString()).interrupted
                && !"complete".equals(TrainingPanelState.from(report.toString()).statusKind));
        report.put("reason","engine_finished").put("engine",row.getJSONObject("engine"));
        check("unlimited_last_game_result_is_not_whole_run_completion", "stopped".equals(TrainingPanelState.from(report.toString()).statusKind)
                && "无限循环已停止".equals(TrainingPanelState.from(report.toString()).title));
        report.put("event","engine").put("active",true).put("reason","menu").put("engine",JSONObject.NULL);
        TrainingPanelState history = TrainingPanelState.fromSaved(report.toString());
        check("unlimited_history_keeps_confirmed_count_without_resuming", history.finished && !history.active && history.interrupted
                && history.summary.contains("已确认 3 局胜负") && "上次运行已中断".equals(history.title));
        report.put("match_count",Integer.MAX_VALUE).put("round_index",7);
        check("maximum_finite_int_count_is_not_clamped_to_two", TrainingPanelState.from(report.toString()).summary.contains("第 7 / 2147483647 局"));
        for (Object invalid : new Object[]{-1, "0", 0.5, 2147483648L}) {
            report.put("match_count",invalid);
            check("malformed_campaign_count_does_not_invent_progress_" + checks.length(),
                    !TrainingPanelState.from(report.toString()).summary.contains("无限循环")
                    && !TrainingPanelState.from(report.toString()).summary.contains(" / "));
        }
        // JSONObject.toString canonicalizes 2.0 to 2; preserve an actual raw
        // fractional numeric type in the presentation input for this check.
        report.put("match_count",2);
        check("floating_count_is_not_campaign_integer", !TrainingPanelState.from(
                report.toString().replace("\"match_count\":2", "\"match_count\":2.0")).summary.contains(" / "));
    }

    private void continuationEffects() throws Exception {
        JSONObject engine = unknownEngine();
        JSONObject row = new JSONObject().put("engine",engine).put("settle",new JSONObject()
                .put("final_state","deck_ready").put("reason_after_return","return_reached:deck_ready"));
        JSONArray rounds = new JSONArray().put(new JSONObject(row.toString())).put(new JSONObject(row.toString()))
                .put(new JSONObject(row.toString()));
        JSONObject report = campaign("finished",false,"campaign_complete").put("match_mode","casual")
                .put("match_count",3).put("round_index",3).put("completed_matches",3).put("rounds",rounds)
                .put("input_status_uncertain",false).put("engine",engine);
        String original = report.toString();
        TrainingPanelState complete = TrainingPanelState.from(original);
        check("finite_unknown_effects_can_complete_strict_results_and_returns", !complete.interrupted
                && "3局对战已完成".equals(complete.title) && "complete".equals(complete.statusKind));
        check("finite_completion_caveat_counts_skipped_only_once", complete.summary.contains("其中 3 次操作的效果未确认")
                && complete.summary.contains("完成回页") && !complete.summary.contains("6 次操作"));
        check("unknown_effects_do_not_increase_confirmed_actions", "18".equals(complete.actionCount));
        check("presentation_does_not_mutate_unknown_or_qa", original.equals(report.toString())
                && !rounds.getJSONObject(0).getJSONObject("engine").getBoolean("full_game_passed")
                && rounds.getJSONObject(0).getJSONObject("engine").getInt("unconfirmed_inputs")==1);
        rounds.getJSONObject(0).put("input_status_uncertain",true);
        check("round_native_uncertainty_overrides_clean_campaign_flag", TrainingPanelState.from(report.toString()).interrupted);
        rounds.getJSONObject(0).remove("input_status_uncertain");
        JSONObject first = rounds.getJSONObject(0).getJSONObject("engine");
        first.put("pending_end_turn_inputs",1);
        check("finite_pending_end_turn_still_refuses_completion", TrainingPanelState.from(report.toString()).interrupted);
        first.remove("pending_end_turn_inputs");
        first.getJSONArray("inputs").getJSONObject(0).getJSONObject("reply").put("completed",false);
        check("finite_accepted_incomplete_touch_still_refuses_completion", TrainingPanelState.from(report.toString()).interrupted);
        first.getJSONArray("inputs").getJSONObject(0).getJSONObject("reply").put("completed",true);
        first.getJSONArray("hooks").getJSONObject(0).put("terminated",true).put("exception_type","Stop").put("detail","result_victory");
        check("finite_exact_confirmed_result_stop_can_complete_with_caveat", !TrainingPanelState.from(report.toString()).interrupted);
        first.getJSONArray("hooks").getJSONObject(0).put("detail","choice_modal_confirmed");
        check("finite_modal_stop_cannot_use_global_result_as_excuse", TrainingPanelState.from(report.toString()).interrupted);
        first.getJSONArray("hooks").getJSONObject(0).put("terminated",false).remove("exception_type");
        report.put("event","engine").put("active",true).put("reason","menu").put("match_count",0)
                .put("round_index",4).put("engine",new JSONObject().put("kind","menu").put("value",new JSONObject().put("state","home")));
        TrainingPanelState running = TrainingPanelState.from(report.toString());
        check("unlimited_running_progress_keeps_unknown_caveat", running.active && running.summary.contains("无限循环")
                && running.summary.contains("其中 3 次操作的效果未确认"));
        report.put("event","finished").put("active",false).put("reason","user_stop");
        TrainingPanelState stopped = TrainingPanelState.from(report.toString());
        check("unlimited_stop_keeps_unknown_caveat_without_target_completion", "stopped".equals(stopped.statusKind)
                && stopped.summary.contains("其中 3 次操作的效果未确认") && !stopped.title.contains("对战已完成"));
        JSONObject single = campaign("finished",false,"engine_finished").put("match_count",1).put("match_mode","casual")
                .put("engine",unknownEngine());
        TrainingPanelState one = TrainingPanelState.from(single.toString());
        check("single_verified_result_retains_unknown_caveat", "本局获胜".equals(one.outcomeLabel)
                && one.summary.contains("其中 1 次操作的效果未确认") && "6".equals(one.actionCount));
        single.remove("match_count");
        check("legacy_single_result_retains_unknown_caveat", TrainingPanelState.from(single.toString()).summary.contains("1 次操作的效果未确认"));
        single.getJSONObject("engine").put("unconfirmed_inputs","1");
        check("malformed_unknown_count_does_not_invent_caveat", !TrainingPanelState.from(single.toString()).summary.contains("次操作的效果未确认"));
    }

    private static JSONObject unknownEngine() throws Exception {
        return new JSONObject().put("result_verified",true).put("stop_reason","result_victory")
                .put("game_inputs",1).put("unconfirmed_inputs",1).put("unconfirmed_skipped",1)
                .put("failed_inputs",0).put("end_turns_confirmed",0).put("actions_confirmed",6)
                .put("engine_turns_seen",4).put("full_game_passed",false)
                .put("inputs",new JSONArray().put(new JSONObject().put("request",new JSONObject().put("context","attack_unit"))
                        .put("reply",new JSONObject().put("accepted",true).put("completed",true))))
                .put("hooks",new JSONArray().put(new JSONObject().put("kind","attack_unit").put("inputs",1)
                        .put("terminated",false).put("verification","unconfirmed_skipped")));
    }

    private void live20(String report) throws Exception {
        TrainingPanelState state = TrainingPanelState.from(report);
        check("real_live20_defeat_is_normal_result_not_technical_failure", state.hasSession
                && !state.active && state.finished && !state.interrupted
                && "complete".equals(state.statusKind) && "训练结束·本局失利".equals(state.title));
        check("real_live20_uses_campaign_elapsed_not_shorter_battle_elapsed",
                "8分59秒".equals(state.durationDisplay));
        check("real_live20_uses_confirmed_non_end_turn_actions", "9".equals(state.actionCount));
        check("real_live20_uses_engine_turn_count", "10".equals(state.turnCount));
        check("qa_full_game_passed_false_does_not_hide_verified_defeat", "本局失利".equals(state.outcomeLabel));

        JSONObject victory = new JSONObject(report);
        victory.getJSONObject("engine").put("stop_reason", "result_victory");
        TrainingPanelState won = TrainingPanelState.from(victory.toString());
        check("verified_victory_has_distinct_outcome", "训练结束·本局获胜".equals(won.title) && !won.interrupted);

        JSONObject notVerified = new JSONObject(report);
        notVerified.getJSONObject("engine").put("result_verified", false);
        TrainingPanelState uncertain = TrainingPanelState.from(notVerified.toString());
        check("unverified_result_is_not_claimed_as_completed_match", uncertain.interrupted
                && "未完成".equals(uncertain.outcomeLabel));

        // The last live event precedes the final wrapper and nests this same summary under value.
        JSONObject finishedEvent = new JSONObject(report);
        JSONObject totals = finishedEvent.getJSONObject("engine");
        finishedEvent.put("event", "engine").put("active", true).put("reason", "finished")
                .put("engine", new JSONObject().put("kind", "finished").put("value", totals));
        TrainingPanelState completing = TrainingPanelState.from(finishedEvent.toString());
        check("live_finished_envelope_exposes_totals_without_prematurely_stopping", completing.active
                && !completing.finished && "9".equals(completing.actionCount) && "10".equals(completing.turnCount));
        finishedEvent.put("active", false);
        TrainingPanelState lateWorkerEvent = TrainingPanelState.from(finishedEvent.toString());
        check("cancelled_worker_final_event_is_not_campaign_completion", !lateWorkerEvent.finished
                && "stopping".equals(lateWorkerEvent.statusKind));
        finishedEvent.put("event", "finished");
        TrainingPanelState finalEnvelope = TrainingPanelState.from(finishedEvent.toString());
        check("nested_final_totals_support_actual_live_envelope", finalEnvelope.finished
                && "本局失利".equals(finalEnvelope.outcomeLabel));
    }

    private void activeStates() throws Exception {
        JSONObject armed = campaign("armed", true, "waiting_for_game").put("elapsed_ms", 5);
        TrainingPanelState opening = TrainingPanelState.from(armed.toString());
        check("armed_waits_for_opening_without_fake_statistics", opening.active && !opening.finished
                && "preparing".equals(opening.statusKind) && "准备中".equals(opening.outcomeLabel)
                && "0秒".equals(opening.durationDisplay) && "—".equals(opening.turnCount));

        JSONObject think = campaign("engine", true, "think").put("game_inputs", 42)
                .put("engine", new JSONObject().put("kind", "think")
                        .put("value", new JSONObject().put("turn", 3).put("game_inputs", 42)));
        TrainingPanelState running = TrainingPanelState.from(think.toString());
        check("real_think_shape_exposes_known_turn_but_not_attempt_count", running.active
                && "running".equals(running.statusKind) && "3".equals(running.turnCount)
                && "—".equals(running.actionCount));

        JSONObject hook = campaign("engine", true, "hook").put("engine", new JSONObject().put("kind", "hook")
                .put("value", new JSONObject().put("turn", 5).put("ok", true).put("inputs", 1)));
        TrainingPanelState acted = TrainingPanelState.from(hook.toString());
        check("single_hook_success_is_not_a_cumulative_action_total", "5".equals(acted.turnCount)
                && "—".equals(acted.actionCount));

        JSONObject observed = campaign("engine", true, "capture").put("engine", new JSONObject().put("kind", "capture")
                .put("value", new JSONObject().put("opponent_turn_label", new JSONObject().put("present", true))));
        check("explicit_opponent_label_produces_waiting_copy",
                TrainingPanelState.from(observed.toString()).summary.contains("等待对方"));
        observed.getJSONObject("engine").getJSONObject("value").put("opponent_turn_label", JSONObject.NULL).put("button", "gray");
        check("unknown_button_color_does_not_invent_opponent_turn",
                !TrainingPanelState.from(observed.toString()).summary.contains("等待对方"));

        observed.getJSONObject("engine").getJSONObject("value").put("state", "defeat");
        TrainingPanelState resultFrame = TrainingPanelState.from(observed.toString());
        check("one_result_frame_is_still_confirmation_in_progress", resultFrame.active && !resultFrame.finished
                && "正在确认对局结算。".equals(resultFrame.summary));
    }

    private void terminalStates() throws Exception {
        TrainingPanelState stop = TrainingPanelState.from(campaign("finished", false, "user_stop").toString());
        check("manual_stop_is_not_game_defeat_or_technical_error", stop.finished && !stop.interrupted
                && "stopped".equals(stop.statusKind) && "已停止".equals(stop.outcomeLabel));
        TrainingPanelState stopping = TrainingPanelState.from(campaign("stopping", false, "user_stop").toString());
        check("cancellation_in_flight_does_not_claim_finished", !stopping.finished
                && "stopping".equals(stopping.statusKind));

        JSONObject openingFailure = campaign("finished", false, "opening_not_verified")
                .put("opening", new JSONObject().put("stopReason", "unknown_screen"));
        TrainingPanelState unknown = TrainingPanelState.from(openingFailure.toString());
        check("opening_recognition_failure_is_explained", unknown.interrupted
                && unknown.summary.contains("未能确认当前游戏画面") && !unknown.summary.contains("unknown_screen"));

        JSONObject permissionFailure = campaign("finished", false, "engine_error:java.lang.SecurityException: secret/path");
        TrainingPanelState permissions = TrainingPanelState.from(permissionFailure.toString());
        check("permission_failure_has_user_copy_without_exception_or_path", permissions.interrupted
                && permissions.summary.contains("检查授权") && !permissions.summary.contains("secret")
                && !permissions.summary.contains("SecurityException"));

        JSONObject enginePermission = campaign("finished", false, "engine_finished").put("engine", new JSONObject()
                .put("stop_reason", "runtime_exception").put("exception", "SecurityException: denied"));
        check("nested_runtime_permission_exception_is_translated",
                TrainingPanelState.from(enginePermission.toString()).summary.contains("检查授权"));

        TrainingPanelState screenshot = TrainingPanelState.from(campaign("finished", false,
                "capture_rejected:截图能力：失败，错误码=2；后续接入 MediaProjection 备用通道。").toString());
        check("real_capture_boundary_error_does_not_expose_implementation_plan",
                screenshot.summary.contains("无法读取") && !screenshot.summary.contains("MediaProjection"));

        TrainingPanelState foreground = TrainingPanelState.from(campaign("finished", false, "foreground_changed").toString());
        check("leaving_game_is_explained_without_result_claim", foreground.interrupted
                && foreground.summary.contains("离开前台") && "未完成".equals(foreground.outcomeLabel));

        TrainingPanelState budget = TrainingPanelState.from(campaign("finished", false, "time_budget").toString());
        check("bounded_session_limit_is_visible", budget.interrupted && budget.summary.contains("训练上限"));
        JSONObject uncertain = campaign("finished", false, "anything").put("input_status_uncertain", true);
        check("uncertain_gesture_prompts_checking_game", TrainingPanelState.from(uncertain.toString()).summary.contains("未能确认操作已完成"));
        TrainingPanelState unknownReason = TrainingPanelState.from(campaign("finished", false, "new_private_code_123").toString());
        check("future_reasons_fall_back_to_nontechnical_copy", unknownReason.interrupted
                && !unknownReason.summary.contains("new_private_code_123"));

        JSONObject inspect = campaign("finished", false, "engine_finished").put("read_only", true)
                .put("engine", new JSONObject().put("stop_reason", "inspection_complete"));
        check("readonly_inspection_is_not_a_training_victory", "观察完成".equals(TrainingPanelState.from(inspect.toString()).outcomeLabel));
    }

    private void invalidStatistics() throws Exception {
        JSONObject report = campaign("finished", false, "user_stop").put("elapsed_ms", -1)
                .put("game_inputs", 100).put("total_game_inputs", 101)
                .put("engine", new JSONObject().put("actions_confirmed", JSONObject.NULL).put("engine_turns_seen", -2));
        TrainingPanelState missing = TrainingPanelState.from(report.toString());
        check("negative_or_missing_stats_remain_unknown", "—".equals(missing.durationDisplay)
                && "—".equals(missing.turnCount) && "—".equals(missing.actionCount));
        report.put("elapsed_ms", "539025").getJSONObject("engine").put("actions_confirmed", "9").put("engine_turns_seen", 1.5);
        TrainingPanelState coerced = TrainingPanelState.from(report.toString());
        check("wrong_types_are_not_coerced_into_statistics", "—".equals(coerced.durationDisplay)
                && "—".equals(coerced.actionCount) && "—".equals(coerced.turnCount));
        report.put("elapsed_ms", 3661000).getJSONObject("engine").put("actions_confirmed", 0).put("engine_turns_seen", 0);
        TrainingPanelState zero = TrainingPanelState.from(report.toString());
        check("known_zero_is_distinct_from_unknown", "0".equals(zero.actionCount) && "0".equals(zero.turnCount));
        check("long_duration_is_readable", "1小时1分".equals(zero.durationDisplay));
    }

    private void savedHistory() throws Exception {
        JSONObject active = campaign("engine", true, "think").put("engine", new JSONObject().put("kind", "think")
                .put("value", new JSONObject().put("turn", 3)));
        String original = active.toString();
        TrainingPanelState savedActive = TrainingPanelState.fromSaved(original);
        check("saved_active_report_cannot_claim_a_live_worker", !savedActive.active && savedActive.finished
                && savedActive.interrupted && "上次运行已中断".equals(savedActive.title)
                && "3".equals(savedActive.turnCount));
        check("viewing_history_does_not_mutate_original_report", original.equals(active.toString())
                && TrainingPanelState.from(original).active);
        TrainingPanelState savedStopping = TrainingPanelState.fromSaved(campaign("stopping", false, "user_stop").toString());
        check("saved_cancellation_without_end_is_interrupted", savedStopping.interrupted
                && "上次运行已中断".equals(savedStopping.title));
        TrainingPanelState savedDefeat = TrainingPanelState.fromSaved(live20Projection());
        check("saved_verified_result_is_preserved", !savedDefeat.interrupted
                && "训练结束·本局失利".equals(savedDefeat.title) && "9".equals(savedDefeat.actionCount));
        check("saved_corrupt_or_empty_report_stays_empty", !TrainingPanelState.fromSaved("broken").hasSession
                && !TrainingPanelState.fromSaved(null).hasSession && !TrainingPanelState.fromSaved("{}").hasSession);
        JSONObject unknownActive = new JSONObject(live20Projection()).put("active", "false");
        TrainingPanelState malformed = TrainingPanelState.from(unknownActive.toString());
        check("wrong_active_type_does_not_claim_finished_result", !malformed.finished && malformed.interrupted
                && "未完成".equals(malformed.outcomeLabel));
    }

    private void formalModesAndStages() throws Exception {
        for (String mode : new String[] {"casual", "ranked"}) {
            JSONObject report = new JSONObject(live20Projection()).put("match_mode", mode).put("stage", "battle");
            TrainingPanelState result = TrainingPanelState.from(report.toString());
            check(mode + "_result_names_the_actual_mode_not_training", result.finished && !result.interrupted
                    && mode.equals(result.matchMode) && !result.title.contains("训练")
                    && ("casual".equals(mode) ? "休闲" : "排位").equals(result.modeLabel)
                    && "9".equals(result.actionCount));
            check(mode + "_saved_result_preserves_mode", mode.equals(TrainingPanelState.fromSaved(report.toString()).matchMode));
        }
        check("legacy_reports_remain_training_debug", "训练调试".equals(TrainingPanelState.from(live20Projection()).modeLabel));
        JSONObject training = new JSONObject(live20Projection()).put("match_mode", "training");
        check("explicit_training_remains_separate_from_formal_modes",
                "训练调试".equals(TrainingPanelState.from(training.toString()).modeLabel));
        JSONObject missingHistory = campaign("history_incomplete", true, "");
        check("missing_summary_does_not_invent_training_mode", "模式未记录".equals(
                TrainingPanelState.fromSaved(missingHistory.toString()).modeLabel));
        JSONObject invalidMode = new JSONObject(live20Projection()).put("match_mode", "private_unknown_mode");
        TrainingPanelState unknownMode = TrainingPanelState.from(invalidMode.toString());
        check("unknown_mode_is_not_exposed_or_called_training", "模式未记录".equals(unknownMode.modeLabel)
                && !unknownMode.title.contains("private_unknown_mode") && !unknownMode.title.contains("训练"));

        JSONObject menu = campaign("engine", true, "menu").put("match_mode", "casual").put("stage", "menu")
                .put("game_inputs", 7).put("engine", new JSONObject().put("kind", "menu")
                        .put("value", new JSONObject().put("state", "queueing").put("mode", "casual")
                                .put("action", "internal_menu_context").put("selected_mode", "casual")));
        TrainingPanelState queue = TrainingPanelState.from(menu.toString());
        check("queueing_is_waiting_for_match_not_battle", queue.active && "等待匹配".equals(queue.title)
                && "匹配中".equals(queue.outcomeLabel) && "—".equals(queue.actionCount) && "—".equals(queue.turnCount));
        check("menu_action_context_is_never_homepage_copy", !queue.summary.contains("internal_menu_context"));
        String[][] popups = {{"task_popup", "任务提示"}, {"pass_popup", "通行证提示"}, {"box_popup", "奖励箱提示"},
                {"airdrop_popup", "空投优惠提示"}, {"starter_popup", "新手优惠提示"},
                {"weekend_popup", "周末优惠提示"}};
        for (String[] popup : popups) {
            menu.getJSONObject("engine").getJSONObject("value").put("state", popup[0])
                    .put("action", "menu_dismiss_" + popup[0]);
            TrainingPanelState prompt = TrainingPanelState.from(menu.toString());
            check(popup[0] + "_explains_preparation_without_exposing_action_context", prompt.active
                    && "preparing".equals(prompt.statusKind) && prompt.summary.contains(popup[1])
                    && !prompt.summary.contains("menu_dismiss_") && "—".equals(prompt.actionCount));
        }
        menu.getJSONObject("engine").getJSONObject("value").put("state", "unknown");
        check("unknown_menu_frame_waits_for_stability", TrainingPanelState.from(menu.toString()).summary.contains("等待画面稳定"));
        menu.getJSONObject("engine").getJSONObject("value").put("state", "deck_list");
        check("deck_selection_explains_first_deck_policy", TrainingPanelState.from(menu.toString()).summary.contains("列表中第一个牌组")
                && !TrainingPanelState.from(menu.toString()).summary.contains("德国"));
        menu.put("match_mode", "ranked").getJSONObject("engine").getJSONObject("value").put("state", "deck_ready");
        check("ranked_preparation_is_named_without_claiming_confirmed_mode", "正在准备排位对战。".equals(
                TrainingPanelState.from(menu.toString()).summary));
        menu.getJSONObject("engine").getJSONObject("value").put("state", "disconnected");
        check("disconnected_menu_explains_connection", "等待游戏连接".equals(TrainingPanelState.from(menu.toString()).title));
        menu.getJSONObject("engine").getJSONObject("value").put("state", "mulligan_ready");
        check("recognized_opening_is_preparation_not_battle", "准备起手".equals(TrainingPanelState.from(menu.toString()).title));
        menu.put("stage", "opening");
        TrainingPanelState opening = TrainingPanelState.from(menu.toString());
        check("explicit_opening_stage_overrides_previous_menu_event", "正在处理起手".equals(opening.title)
                && opening.active && "—".equals(opening.actionCount));
        menu.put("stage", "battle").put("engine", new JSONObject().put("kind", "think")
                .put("value", new JSONObject().put("turn", 2)));
        TrainingPanelState battle = TrainingPanelState.from(menu.toString());
        check("battle_stage_uses_actual_turn_and_mode", "对局进行中".equals(battle.title)
                && "2".equals(battle.turnCount) && "排位".equals(battle.modeLabel));
        TrainingPanelState saved = TrainingPanelState.fromSaved(menu.toString());
        check("interrupted_saved_formal_session_preserves_mode", saved.interrupted && !saved.active
                && "排位".equals(saved.modeLabel) && "上次运行已中断".equals(saved.title));
    }

    private void waitingForUserGameEntry() throws Exception {
        for (String mode : new String[] {"casual", "ranked"}) {
            JSONObject report = campaign("armed", true, "waiting_for_game")
                    .put("match_mode", mode).put("stage", "menu").put("entry_mode", "launch_game");
            TrainingPanelState waiting = TrainingPanelState.from(report.toString());
            check(mode + "_armed_waits_for_manual_game_entry", waiting.active && !waiting.finished
                    && "waiting".equals(waiting.statusKind) && "等待游戏".equals(waiting.title)
                    && "待命中".equals(waiting.outcomeLabel) && waiting.summary.contains("自行打开 KARDS")
                    && waiting.summary.contains("3 分钟") && "—".equals(waiting.turnCount)
                    && "—".equals(waiting.actionCount));
            report.put("entry", new JSONObject().put("admitted_generation", 7));
            check(mode + "_foreground_token_does_not_claim_battle", "等待游戏".equals(
                    TrainingPanelState.from(report.toString()).title));
            report.put("event", "engine").put("engine", new JSONObject().put("kind", "menu")
                    .put("value", new JSONObject().put("state", "waiting_for_game")));
            check(mode + "_menu_wait_keeps_manual_entry_instruction", "waiting".equals(
                    TrainingPanelState.from(report.toString()).statusKind));
            TrainingPanelState saved = TrainingPanelState.fromSaved(report.toString());
            check(mode + "_saved_wait_does_not_rearm", !saved.active && saved.interrupted
                    && "上次运行已中断".equals(saved.title));
            report.getJSONObject("engine").getJSONObject("value").put("state", "home");
            TrainingPanelState home = TrainingPanelState.from(report.toString());
            check(mode + "_actual_menu_observation_leaves_waiting_state", "preparing".equals(home.statusKind)
                    && "正在进入对战菜单。".equals(home.summary));
        }
    }

    private static JSONObject campaign(String event, boolean active, String reason) throws Exception {
        return new JSONObject().put("session_id", "panel-check-session").put("event", event)
                .put("active", active).put("reason", reason).put("elapsed_ms", 1000)
                .put("opening", JSONObject.NULL).put("engine", JSONObject.NULL);
    }

    private static String live20Projection() {
        // Exact presentation-relevant values from live20 summary.json (not a synthetic success).
        // Original SHA256: ecf49c8ccf62388c1de3236c2c3db915575b8f8540aa2acffb56dfc25b79495c.
        return "{\"event\":\"finished\",\"active\":false,\"session_id\":\"1791275132134-5c00b730\","
                + "\"elapsed_ms\":539025,\"reason\":\"engine_finished\",\"game_inputs\":19,"
                + "\"total_game_inputs\":20,\"read_only\":false,\"input_status_uncertain\":false,"
                + "\"engine\":{\"elapsed_ms\":525404,\"actions_confirmed\":9,\"end_turns_confirmed\":10,"
                + "\"engine_turns_seen\":10,\"stop_reason\":\"result_defeat\",\"result_verified\":true,"
                + "\"battle_result_reached\":true,\"full_game_passed\":false}}";
    }

    private void check(String name, boolean passed) throws Exception {
        checks.put(new JSONObject().put("name", name).put("passed", passed));
        if (!passed) failures++;
    }
}
