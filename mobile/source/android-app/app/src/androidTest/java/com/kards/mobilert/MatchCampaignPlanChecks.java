package com.kards.mobilert;

import org.json.JSONArray;
import org.json.JSONObject;

/** Pure campaign policy checks; no worker/service/device is created. */
public final class MatchCampaignPlanChecks {
    private final JSONArray checks = new JSONArray();
    private int failures;
    private interface Check { void run() throws Exception; }
    public static JSONObject run() throws Exception {
        MatchCampaignPlanChecks test = new MatchCampaignPlanChecks(); test.matrix();
        return new JSONObject().put("checks", test.checks).put("check_count", test.checks.length())
                .put("failure_count", test.failures).put("device_inputs", 0);
    }
    private void matrix() throws Exception {
        check("default_is_one", () -> require(new MatchCampaignPlan(new JSONObject(), "training").matchCount == 1));
        for (String mode : new String[]{"casual","ranked"}) for (int count : new int[]{0,1,2,3,17,Integer.MAX_VALUE}) {
            check(mode+"_count_"+count, () -> require(new MatchCampaignPlan(new JSONObject().put("match_count",count),mode).matchCount == count));
        }
        check("integer_long_count_supported", () -> require(new MatchCampaignPlan(
                new JSONObject().put("match_count",17L),"casual").matchCount == 17));
        check("zero_long_is_unlimited", () -> require(new MatchCampaignPlan(
                new JSONObject().put("match_count",0L),"ranked").isUnlimited()));
        for (Object invalid : new Object[]{-1,-9L,(long)Integer.MAX_VALUE+1,Long.MAX_VALUE,"2",2.0,1.0,0.0,true,JSONObject.NULL,new JSONArray()})
            check("invalid_count_"+invalid, () -> reject(new JSONObject().put("match_count",invalid),"casual","invalid_match_count"));
        for (int count : new int[]{0,2,7}) {
            check("training_cannot_loop_"+count, () -> reject(new JSONObject().put("match_count",count),"training","multiple_matches_require_formal_mode"));
            for (Object invalid : new Object[]{true,"false",0,JSONObject.NULL})
                check("read_only_cannot_loop_"+count+"_"+invalid, () -> reject(new JSONObject().put("match_count",count).put("read_only",invalid),"casual","multiple_matches_read_only_forbidden"));
            for (Object invalid : new Object[]{false,"true",1,JSONObject.NULL}) {
                check("loop_requires_settle_"+count+"_"+invalid, () -> reject(new JSONObject().put("match_count",count).put("post_match_settle",invalid),"casual","multiple_matches_require_settlement"));
                check("loop_requires_opening_"+count+"_"+invalid, () -> reject(new JSONObject().put("match_count",count).put("start_with_opening",invalid),"casual","multiple_matches_require_opening"));
            }
            check("debug_cannot_loop_"+count, () -> reject(new JSONObject().put("match_count",count).put("debug_stage","settle"),"casual","multiple_matches_require_settlement"));
        }
        MatchCampaignPlan plan = new MatchCampaignPlan(new JSONObject().put("match_count",2),"casual");
        check("verified_return_can_continue", () -> require(plan.continuationReason(1,result(),returned(),false,false,300000,20)==null));
        check("cancel_blocks", () -> equal("campaign_cancelled",plan.continuationReason(1,result(),returned(),true,false,900000,100)));
        check("uncertain_blocks", () -> equal("campaign_input_status_uncertain",plan.continuationReason(1,result(),returned(),false,true,900000,100)));
        check("time_under_reserve_blocks", () -> equal("campaign_time_reserve",plan.continuationReason(1,result(),returned(),false,false,299999,100)));
        check("input_under_reserve_blocks", () -> equal("campaign_input_reserve",plan.continuationReason(1,result(),returned(),false,false,900000,19)));
        check("second_complete_only_after_evidence", () -> equal("campaign_complete",plan.continuationReason(2,result(),returned(),false,false,0,0)));
        check("second_cancel_still_blocks", () -> equal("campaign_cancelled",plan.continuationReason(2,result(),returned(),true,false,0,0)));
        for (Object invalid : new Object[]{false,"true",1,JSONObject.NULL})
            check("strict_result_boolean_"+invalid, () -> require(!MatchCampaignPlan.resultConfirmed(result().put("result_verified",invalid))));
        check("missing_result_is_rejected", () -> require(!MatchCampaignPlan.resultConfirmed(null)));
        check("wrong_stop_reason_rejected", () -> require(!MatchCampaignPlan.resultConfirmed(result().put("stop_reason","engine_finished"))));
        check("verified_defeat_is_valid", () -> require(MatchCampaignPlan.resultConfirmed(result().put("stop_reason","result_defeat"))));
        for (String state : new String[]{"home","deck_list","mode_menu","deck_ready"}) for (String prefix : new String[]{"return_reached:","return_not_needed:"})
            check("return_"+prefix+state, () -> require(MatchCampaignPlan.returned(returned().put("final_state",state).put("reason_after_return",prefix+state))));
        for (String state : new String[]{"unknown","menu_transition","disconnected","card_collection",
                "task_popup","pass_popup","box_popup","store_popup","login_reward"})
            check("wrong_return_state_"+state, () -> require(!MatchCampaignPlan.returned(returned().put("final_state",state).put("reason_after_return","return_reached:"+state))));
        check("deck_ready_requires_matching_return_reason", () -> require(!MatchCampaignPlan.returned(
                returned().put("final_state","deck_ready").put("reason_after_return","return_reached:deck_list"))));
        check("deck_ready_can_continue_with_strict_result_and_reserve", () -> require(plan.continuationReason(
                1,result(),returned().put("final_state","deck_ready").put("reason_after_return","return_not_needed:deck_ready"),
                false,false,300000,20)==null));
        for (String reason : new String[]{"return_control_absent:home","return_reached:deck_list","settle_screen_known:home","return_deadline",""})
            check("wrong_return_reason_"+reason, () -> require(!MatchCampaignPlan.returned(returned().put("reason_after_return",reason))));
        check("failed_second_not_complete", () -> equal("campaign_result_unverified",plan.continuationReason(2,null,returned(),false,false,0,0)));
        check("failed_second_return_not_complete", () -> equal("campaign_return_unverified",plan.continuationReason(2,result(),null,false,false,0,0)));
        MatchCampaignPlan unlimited = new MatchCampaignPlan(new JSONObject().put("match_count",0),"ranked");
        for (int index : new int[]{1,2,3,10000}) {
            check("unlimited_continues_after_round_"+index, () -> require(unlimited.continuationReason(index,result(),returned(),false,false,1800000,200)==null));
            check("unlimited_cancel_blocks_round_"+index, () -> equal("campaign_cancelled",unlimited.continuationReason(index,result(),returned(),true,false,1800000,200)));
            check("unlimited_uncertain_blocks_round_"+index, () -> equal("campaign_input_status_uncertain",unlimited.continuationReason(index,result(),returned(),false,true,1800000,200)));
        }
        check("unlimited_result_missing_stops", () -> equal("campaign_result_unverified",unlimited.continuationReason(4,null,returned(),false,false,1800000,200)));
        check("unlimited_return_missing_stops", () -> equal("campaign_return_unverified",unlimited.continuationReason(4,result(),null,false,false,1800000,200)));
        check("unlimited_does_not_restart_with_tiny_config", () -> equal("campaign_time_reserve",unlimited.continuationReason(4,result(),returned(),false,false,299999,200)));
        check("unlimited_does_not_restart_without_input_config", () -> equal("campaign_input_reserve",unlimited.continuationReason(4,result(),returned(),false,false,1800000,19)));
        check("unlimited_round_index_cannot_wrap", () -> equal("campaign_round_index_limit",unlimited.continuationReason(Integer.MAX_VALUE,result(),returned(),false,false,1800000,200)));
        MatchCampaignPlan five = new MatchCampaignPlan(new JSONObject().put("match_count",5),"casual");
        check("finite_five_continues_at_four", () -> require(five.continuationReason(4,result(),returned(),false,false,1800000,200)==null));
        check("finite_five_stops_at_target", () -> equal("campaign_complete",five.continuationReason(5,result(),returned(),false,false,0,0)));
        check("error_even_with_result_never_continues", () -> equal("campaign_engine_failed",unlimited.continuationReason(4,result().put("exception","failure"),returned(),false,false,1800000,200)));
        for (String metric : new String[]{"failed_inputs","unconfirmed_inputs","pending_end_turn_inputs","unconfirmed_skipped","end_turns_unconfirmed"})
            check("unproven_metric_still_blocks_"+metric, () -> equal("campaign_action_unconfirmed",unlimited.continuationReason(4,result().put(metric,1),returned(),false,false,1800000,200)));
        continuationLedger(unlimited);
        check("spent_prior_round_cannot_shrink_fresh_deadline", () -> {
            long first = MatchCampaignPlan.roundDeadline(100000,1800);
            long nextStarted = first-1;
            long second = MatchCampaignPlan.roundDeadline(nextStarted,1800);
            require(second-nextStarted==1800000 && second>first);
        });
        check("fresh_round_rebases_all_input_categories", () -> {
            require(MatchCampaignPlan.roundInputs(200,200,0,0,0)==0);
            require(MatchCampaignPlan.roundInputs(210,200,3,1,10)==24);
            require(MatchCampaignPlan.roundInputs(210,210,0,0,0)==0);
        });
        check("large_campaign_total_preserves_small_round_guard", () -> {
            require(MatchCampaignPlan.roundInputs(3000000010L,3000000000L,3,1,10)==24);
            require(MatchCampaignPlan.roundInputs(3000000200L,3000000000L,0,0,0)==200);
        });
    }
    private void continuationLedger(MatchCampaignPlan plan) throws Exception {
        check("completed_end_timeout_under_limit_can_continue", () -> {
            JSONObject value=ledger("end_turn","pending_transition").put("end_turns_confirmed",0).put("end_turns_unconfirmed",1).put("failed_inputs",1).put("max_failed_inputs",5);
            value.getJSONArray("hooks").getJSONObject(0).put("final_verification","unconfirmed").put("detail","turn_transition_timeout");
            String original=value.toString();require(plan.continuationReason(4,value,returned(),false,false,1800000,200)==null && original.equals(value.toString()));
        });
        check("completed_end_timeouts_at_limit_stop", () -> {
            JSONObject value=ledger("end_turn","pending_transition").put("end_turns_confirmed",0).put("end_turns_unconfirmed",1).put("failed_inputs",1).put("max_failed_inputs",1);
            value.getJSONArray("hooks").getJSONObject(0).put("final_verification","unconfirmed").put("detail","turn_transition_timeout");unsafe(value);
        });
        check("phantom_end_timeout_is_rejected", () -> unsafe(ledger("end_turn","pending_transition").put("end_turns_unconfirmed",1)));
        check("resolved_three_choice_can_continue", () -> require(plan.continuationReason(4,ledger("choice_select","confirmed"),returned(),false,false,1800000,200)==null));
        check("choice_resolution_detail_required", () -> {
            JSONObject value=ledger("choice_select","confirmed");value.getJSONArray("hooks").getJSONObject(0).remove("detail");unsafe(value);
        });
        check("choice_incomplete_touch_still_blocks", () -> {
            JSONObject value=ledger("choice_select","confirmed");value.getJSONArray("inputs").getJSONObject(0).getJSONObject("reply").put("completed",false);unsafe(value);
        });
        check("choice_skipped_is_not_supported", () -> unsafe(ledger("choice_select","unconfirmed_skipped")));
        for (String kind : new String[]{"deploy","attack_hq","attack_unit","move_front","choice_select"}) {
            check("completed_ordinary_effect_unknown_can_continue_"+kind, () -> {
                JSONObject value = ledger(kind,"unconfirmed"); String before = value.toString();
                require(plan.continuationReason(4,value,returned(),false,false,1800000,200)==null);
                require(MatchCampaignPlan.hasUnconfirmedInput(value) && !value.getBoolean("full_game_passed"));
                require(MatchCampaignPlan.continuationEvidence(value).ordinaryEffectUnknown==1 && before.equals(value.toString()));
            });
        }
        for (String kind : new String[]{"attack_hq","attack_unit","move_front"})
            check("skipped_is_unknown_subset_"+kind, () -> {
                JSONObject value = ledger(kind,"unconfirmed_skipped");
                require(MatchCampaignPlan.continuationEvidence(value).safe
                        && MatchCampaignPlan.continuationEvidence(value).ordinaryEffectUnknown==1);
            });
        check("deploy_skip_not_a_supported_ordinary_effect", () -> unsafe(ledger("deploy","unconfirmed_skipped")));
        check("finite_target_completes_with_unknown_quality", () -> {
            MatchCampaignPlan finite = new MatchCampaignPlan(new JSONObject().put("match_count",3),"casual");
            equal("campaign_complete",finite.continuationReason(3,ledger("deploy","unconfirmed"),returned(),false,false,0,0));
        });
        check("strict_result_stop_inside_deploy_is_normal_terminal_boundary", () -> {
            JSONObject value = ledger("deploy","unconfirmed");
            value.getJSONArray("hooks").getJSONObject(0).put("terminated",true).put("exception_type","Stop").put("detail","result_victory");
            require(MatchCampaignPlan.continuationEvidence(value).safe && value.getInt("unconfirmed_inputs")==1);
        });
        for (String detail : new String[]{"result_defeat","choice_modal_confirmed","unknown_screen_timeout","cancelled","gesture_rejected"})
            check("global_result_does_not_allow_other_stop_"+detail, () -> {
                JSONObject value = ledger("deploy","unconfirmed");
                value.getJSONArray("hooks").getJSONObject(0).put("terminated",true).put("exception_type","Stop").put("detail",detail);
                unsafe(value);
            });
        for (Object malformed : new Object[]{-1,"1",1.5,true,JSONObject.NULL})
            for (String metric : new String[]{"failed_inputs","unconfirmed_inputs","pending_end_turn_inputs","unconfirmed_skipped",
                    "end_turns_unconfirmed","end_turns_confirmed","game_inputs"})
                check("strict_counter_"+metric+"_"+malformed, () -> unsafe(ledger("deploy","unconfirmed").put(metric,malformed)));
        for (Object bad : new Object[]{"true",1,JSONObject.NULL}) for (String field : new String[]{"accepted","completed"})
            check("strict_receipt_boolean_"+field+"_"+bad, () -> {
                JSONObject value = ledger("deploy","unconfirmed");
                value.getJSONArray("inputs").getJSONObject(0).getJSONObject("reply").put(field,bad); unsafe(value);
            });
        check("accepted_incomplete_is_unsafe_even_with_result", () -> {
            JSONObject value = ledger("deploy","unconfirmed");
            value.getJSONArray("inputs").getJSONObject(0).getJSONObject("reply").put("completed",false); unsafe(value);
        });
        for (String reason : new String[]{"frame_age_expired","input_frame_age_exceeded","frame_expired"})
            check("explicit_no_touch_age_replan_keeps_existing_behavior_"+reason, () -> {
                JSONObject value = ledger("deploy","unconfirmed");
                value.getJSONArray("inputs").put(receipt("deploy").put("reply",new JSONObject().put("accepted",false)
                        .put("completed",false).put("reason",reason)));
                value.getJSONArray("hooks").put(hook("deploy","no_input",0).put("terminated",true)
                        .put("exception_type","Replan").put("detail",reason));
                require(MatchCampaignPlan.continuationEvidence(value).safe);
            });
        check("other_dispatcher_refusal_is_unsafe", () -> {
            JSONObject value = ledger("deploy","unconfirmed");
            value.getJSONArray("inputs").put(receipt("deploy").put("reply",new JSONObject().put("accepted",false)
                    .put("completed",false).put("reason","dispatcher_failed"))); unsafe(value);
        });
        for (Object bad : new Object[]{"false",0,JSONObject.NULL}) for (int count : new int[]{0,1})
            check("terminated_requires_boolean_count_"+count+"_"+bad, () -> {
                JSONObject value = ledger("deploy","unconfirmed");
                if(count==0)value.getJSONArray("hooks").put(hook("deploy","no_input",0).put("terminated",bad));
                else value.getJSONArray("hooks").getJSONObject(0).put("terminated",bad);
                unsafe(value);
            });
        for (int count : new int[]{0,1}) check("missing_terminated_rejected_count_"+count, () -> {
            JSONObject value = ledger("deploy","unconfirmed");
            JSONObject candidate = count==0?hook("deploy","no_input",0):value.getJSONArray("hooks").getJSONObject(0);
            candidate.remove("terminated");if(count==0)value.getJSONArray("hooks").put(candidate);unsafe(value);
        });
        for (String exception : new String[]{"RuntimeError","Stop","Replan"})
            check("nonterminated_zero_input_exception_rejected_"+exception, () -> {
                JSONObject value = ledger("deploy","unconfirmed");
                value.getJSONArray("hooks").put(hook("deploy","no_input",0).put("exception_type",exception));unsafe(value);
            });
        check("zero_input_result_stop_before_end_tap_is_safe", () -> {
            JSONObject value = ledger("deploy","unconfirmed");
            value.getJSONArray("hooks").put(hook("end_turn","no_input",0).put("terminated",true)
                    .put("exception_type","Stop").put("detail","result_victory"));
            require(MatchCampaignPlan.continuationEvidence(value).safe);
        });
        check("zero_input_replan_without_detail_rejected", () -> {
            JSONObject value = ledger("deploy","unconfirmed");
            value.getJSONArray("hooks").put(hook("deploy","no_input",0).put("terminated",true).put("exception_type","Replan"));unsafe(value);
        });
        check("positive_replan_cannot_be_excused_by_confirmed_result", () -> {
            JSONObject value = ledger("deploy","unconfirmed");
            value.getJSONArray("hooks").getJSONObject(0).put("terminated",true).put("exception_type","Replan").put("detail","frame_expired");unsafe(value);
        });
        check("missing_verification_rejected", () -> {
            JSONObject value = ledger("deploy","unconfirmed");value.getJSONArray("hooks").getJSONObject(0).remove("verification");unsafe(value);
        });
        for (String removed : new String[]{"inputs","hooks"}) check("missing_ledger_rejected_"+removed, () -> {
            JSONObject value = ledger("deploy","unconfirmed");value.remove(removed);unsafe(value);
        });
        check("truncated_hook_ledger_rejected", () -> unsafe(ledger("deploy","unconfirmed").put("hooks",new JSONArray())));
        check("receipt_context_mismatch_rejected", () -> {
            JSONObject value = ledger("deploy","unconfirmed");value.getJSONArray("inputs").getJSONObject(0).getJSONObject("request")
                    .put("context","attack_hq");unsafe(value);
        });
        check("accepted_count_mismatch_rejected", () -> unsafe(ledger("deploy","unconfirmed").put("game_inputs",2)));
        check("hook_count_mismatch_rejected", () -> {
            JSONObject value = ledger("deploy","unconfirmed");value.getJSONArray("hooks").getJSONObject(0).put("inputs",2);unsafe(value);
        });
        check("unknown_accounting_mismatch_rejected", () -> unsafe(ledger("deploy","unconfirmed").put("unconfirmed_inputs",0)));
        check("skipped_larger_than_unknown_rejected", () -> unsafe(ledger("attack_hq","unconfirmed_skipped").put("unconfirmed_skipped",2)));
        check("unexplained_failed_streak_rejected", () -> unsafe(ledger("deploy","unconfirmed").put("failed_inputs",2)));
        check("finally_confirmed_end_turn_is_safe", () -> require(MatchCampaignPlan.continuationEvidence(ledger("end_turn","pending_transition")).safe));
        for (String finalState : new String[]{"pending","unconfirmed","true",""})
            check("end_turn_final_not_confirmed_blocks_"+finalState, () -> {
                JSONObject value = ledger("end_turn","pending_transition");
                value.getJSONArray("hooks").getJSONObject(0).put("final_verification",finalState);unsafe(value);
            });
        for (String metric : new String[]{"pending_end_turn_inputs","end_turns_unconfirmed"})
            check("end_turn_unresolved_counter_still_blocks_"+metric, () -> unsafe(ledger("deploy","unconfirmed").put(metric,1)));
        check("result_stop_cannot_substitute_for_sent_end_turn_transition", () -> {
            JSONObject value = ledger("end_turn","unconfirmed");
            value.getJSONArray("hooks").getJSONObject(0).put("terminated",true).put("exception_type","Stop").put("detail","result_victory");unsafe(value);
        });
        check("missing_end_turn_hook_cannot_be_hidden_by_zero_counts", () -> unsafe(ledger("end_turn","pending_transition").put("end_turns_confirmed",0)));
    }
    private static JSONObject receipt(String kind) throws Exception {
        return new JSONObject().put("request",new JSONObject().put("context",kind)).put("reply",new JSONObject()
                .put("accepted",true).put("completed",true).put("reason","gesture_completed_unverified"));
    }
    private static JSONObject hook(String kind,String verification,int count) throws Exception {
        return new JSONObject().put("kind",kind).put("verification",verification).put("inputs",count).put("terminated",false);
    }
    private static JSONObject ledger(String kind,String verification) throws Exception {
        boolean unknown = "unconfirmed".equals(verification) || "unconfirmed_skipped".equals(verification);
        JSONObject record = hook(kind,verification,1);
        if("choice_select".equals(kind))record.put("detail","confirmed".equals(verification)?"three_choice_disappeared":"three_choice_still_present");
        if("end_turn".equals(kind))record.put("final_verification","confirmed");
        return result().put("game_inputs",1).put("full_game_passed",false).put("unconfirmed_inputs",unknown?1:0)
                .put("unconfirmed_skipped","unconfirmed_skipped".equals(verification)?1:0).put("failed_inputs",0)
                .put("end_turns_confirmed","end_turn".equals(kind)?1:0)
                .put("inputs",new JSONArray().put(receipt(kind))).put("hooks",new JSONArray().put(record));
    }
    private static void unsafe(JSONObject result) { require(!MatchCampaignPlan.continuationEvidence(result).safe); }
    private static JSONObject result() throws Exception { return new JSONObject().put("result_verified",true).put("stop_reason","result_victory"); }
    private static JSONObject returned() throws Exception { return new JSONObject().put("final_state","home").put("reason_after_return","return_reached:home"); }
    private static void reject(JSONObject value,String mode,String reason) {
        try { new MatchCampaignPlan(value,mode); } catch(IllegalArgumentException error) { equal(reason,error.getMessage()); return; }
        throw new AssertionError("invalid campaign accepted");
    }
    private static void require(boolean ok) { if(!ok)throw new AssertionError("failed"); }
    private static void equal(String expected,String actual) { require(expected.equals(actual)); }
    private void check(String name,Check action) throws Exception {
        JSONObject row=new JSONObject().put("name",name);
        try {action.run();row.put("passed",true);}catch(Throwable error){failures++;row.put("passed",false).put("error",error.toString());}
        checks.put(row);
    }
}
