package com.kards.mobilert;

import java.util.ArrayList;
import org.json.JSONArray;
import org.json.JSONObject;

/** Pure campaign policy. A next round requires evidence, never a guessed result. */
final class MatchCampaignPlan {
    static final long MIN_NEXT_ROUND_MS = 300_000L;
    static final int MIN_NEXT_ROUND_INPUTS = 20;
    final int matchCount;

    MatchCampaignPlan(JSONObject options, String mode) {
        Object value = options.has("match_count") ? options.opt("match_count") : 1;
        if (!(value instanceof Integer || value instanceof Long)
                || ((Number) value).longValue() < 0 || ((Number) value).longValue() > Integer.MAX_VALUE)
            throw new IllegalArgumentException("invalid_match_count");
        matchCount = ((Number) value).intValue();
        if (isMultiple() && !(MatchEntryOptions.CASUAL.equals(mode) || MatchEntryOptions.RANKED.equals(mode)))
            throw new IllegalArgumentException("multiple_matches_require_formal_mode");
        if (isMultiple() && (!Boolean.FALSE.equals(options.opt("read_only"))
                && options.has("read_only"))) throw new IllegalArgumentException("multiple_matches_read_only_forbidden");
        if (isMultiple() && options.has("start_with_opening")
                && !Boolean.TRUE.equals(options.opt("start_with_opening")))
            throw new IllegalArgumentException("multiple_matches_require_opening");
        if (isMultiple() && ((options.has("post_match_settle") && !Boolean.TRUE.equals(options.opt("post_match_settle")))
                || options.has("debug_stage"))) throw new IllegalArgumentException("multiple_matches_require_settlement");
    }

    boolean isMultiple() { return matchCount != 1; }
    boolean isUnlimited() { return matchCount == 0; }

    static long roundDeadline(long started, int seconds) { return started + seconds * 1000L; }

    static int roundInputs(long campaignBattleInputs, long battleBaseline, int menu,
            int opening, int settle) {
        return Math.toIntExact(campaignBattleInputs - battleBaseline + menu + opening + settle);
    }

    static boolean resultConfirmed(JSONObject result) {
        return result != null && Boolean.TRUE.equals(result.opt("result_verified"))
                && ("result_victory".equals(result.opt("stop_reason")) || "result_defeat".equals(result.opt("stop_reason")));
    }

    static boolean returned(JSONObject settle) {
        if (settle == null) return false;
        Object state = settle.opt("final_state");
        if (!("home".equals(state) || "mode_menu".equals(state) || "deck_list".equals(state)
                || "deck_ready".equals(state))) return false;
        String reason = settle.optString("reason_after_return", "");
        return reason.equals("return_not_needed:" + state) || reason.equals("return_reached:" + state);
    }

    static boolean hasUnconfirmedInput(JSONObject result) {
        if (result == null) return false;
        for (String key : new String[]{"failed_inputs", "unconfirmed_inputs", "pending_end_turn_inputs",
                "unconfirmed_skipped", "end_turns_unconfirmed"}) {
            if (result.optInt(key, 0) != 0) return true;
        }
        return false;
    }

    /** Touch completion and end-turn safety are separate from ordinary effect quality. */
    static final class ContinuationEvidence {
        final boolean safe;
        final long ordinaryEffectUnknown;
        final String detail;
        private ContinuationEvidence(boolean safe, long unknown, String detail) {
            this.safe = safe; this.ordinaryEffectUnknown = unknown; this.detail = detail;
        }
    }

    private static ContinuationEvidence blocked(String detail) {
        return new ContinuationEvidence(false, -1, detail);
    }

    private static long counter(JSONObject json, String key) {
        if (!json.has(key)) return 0;
        Object value = json.opt(key);
        if (!(value instanceof Integer || value instanceof Long)) return -1;
        long count = ((Number) value).longValue();
        return count >= 0 ? count : -1;
    }

    private static boolean ordinary(Object kind) {
        return "deploy".equals(kind) || "attack_hq".equals(kind)
                || "attack_unit".equals(kind) || "move_front".equals(kind) || "choice_select".equals(kind);
    }

    private static boolean resultStop(JSONObject hook, JSONObject result) {
        return Boolean.TRUE.equals(hook.opt("terminated")) && "Stop".equals(hook.opt("exception_type"))
                && resultConfirmed(result) && result.opt("stop_reason").equals(hook.opt("detail"));
    }

    private static boolean resolvedEndUnknown(JSONObject hook, JSONObject result) {
        if (!"unconfirmed".equals(hook.opt("final_verification"))) return false;
        if ("turn_transition_timeout".equals(hook.opt("detail"))) return true;
        String currentOwn = "current_own_state_ready_without_transition_proof";
        String detail = hook.optString("detail", "");
        boolean currentResult = resultConfirmed(result)
                && detail.equals("session_stopped_before_turn_confirmation:"+result.optString("stop_reason"));
        if (!currentOwn.equals(detail) && !currentResult) return false;
        JSONObject outcome = hook.optJSONObject("end_turn_outcome");
        return outcome != null && "unconfirmed".equals(outcome.opt("status"))
                && detail.equals(outcome.opt("reason"))
                && hook.has("before_capture") && outcome.has("source_frame_id")
                && counter(hook,"before_capture") >= 0
                && counter(hook,"before_capture") == counter(outcome,"source_frame_id")
                && outcome.has("dispatched_elapsed_ms") && outcome.has("resolved_elapsed_ms")
                && counter(outcome,"dispatched_elapsed_ms") >= 0
                && counter(outcome,"resolved_elapsed_ms") >= counter(outcome,"dispatched_elapsed_ms");
    }

    static ContinuationEvidence continuationEvidence(JSONObject result) {
        if (result == null) return blocked("result_missing");
        long failed = counter(result, "failed_inputs"), unknown = counter(result, "unconfirmed_inputs");
        long pending = counter(result, "pending_end_turn_inputs"), skipped = counter(result, "unconfirmed_skipped");
        long endUnknown = counter(result, "end_turns_unconfirmed"), sent = counter(result, "game_inputs");
        long endConfirmed = counter(result, "end_turns_confirmed");
        if (failed < 0 || unknown < 0 || pending < 0 || skipped < 0 || endUnknown < 0 || sent < 0 || endConfirmed < 0)
            return blocked("counter_type_or_range_invalid");
        if (pending != 0) return blocked("end_turn_pending");
        long failureLimit=result.has("max_failed_inputs")?counter(result,"max_failed_inputs"):5;
        if (failureLimit<1 || failureLimit>10) return blocked("failure_limit_invalid");
        if (failed>=failureLimit) return blocked("failed_streak_limit");
        if (skipped > unknown) return blocked("skipped_not_subset_of_unconfirmed");
        // Old pure-policy fixtures contain no touches or ledger. Positive counts
        // and effect unknowns always require the complete runtime ledger.
        if (!result.has("inputs") && !result.has("hooks") && sent == 0 && failed == 0
                && unknown == 0 && skipped == 0 && endConfirmed == 0 && endUnknown == 0)
            return new ContinuationEvidence(true, 0, "legacy_zero_touch_clean");
        JSONArray packets = result.optJSONArray("inputs"), hooks = result.optJSONArray("hooks");
        if (packets == null || hooks == null) return blocked("receipt_or_hook_ledger_missing");
        ArrayList<String> accepted = new ArrayList<>();
        for (int i = 0; i < packets.length(); i++) {
            JSONObject packet = packets.optJSONObject(i);
            JSONObject request = packet == null ? null : packet.optJSONObject("request");
            JSONObject reply = packet == null ? null : packet.optJSONObject("reply");
            if (request == null || reply == null) return blocked("receipt_structure_invalid");
            Object kind = request.opt("context"), admitted = reply.opt("accepted"), completed = reply.opt("completed");
            if (!(admitted instanceof Boolean) || !(completed instanceof Boolean)) return blocked("receipt_booleans_not_strict");
            if (!ordinary(kind) && !"end_turn".equals(kind)) return blocked("input_context_unknown");
            if (Boolean.TRUE.equals(admitted)) {
                if (!Boolean.TRUE.equals(completed)) return blocked("accepted_touch_incomplete");
                accepted.add((String) kind);
            } else if (Boolean.TRUE.equals(completed) || !("frame_age_expired".equals(reply.opt("reason"))
                    || "input_frame_age_exceeded".equals(reply.opt("reason")) || "frame_expired".equals(reply.opt("reason"))))
                return blocked("dispatcher_failed_or_refused");
        }
        if (accepted.size() != sent) return blocked("accepted_receipt_count_mismatch");
        int cursor = 0;
        long ordinaryUnknown = 0, skippedUnknown = 0, confirmedEnds = 0, unconfirmedEnds = 0;
        for (int i = 0; i < hooks.length(); i++) {
            JSONObject hook = hooks.optJSONObject(i);
            if (hook == null || !hook.has("inputs")) return blocked("hook_structure_invalid");
            long count = counter(hook, "inputs");
            Object kind = hook.opt("kind"), verification = hook.opt("verification"), terminated = hook.opt("terminated");
            if (count < 0 || (!ordinary(kind) && !"end_turn".equals(kind)) || !(terminated instanceof Boolean))
                return blocked("hook_structure_invalid");
            boolean exceptional = hook.has("exception_type") && !hook.isNull("exception_type");
            if (count == 0) {
                if (!"no_input".equals(verification)) return blocked("zero_input_hook_verification_invalid");
                if (Boolean.TRUE.equals(terminated)) {
                    Object detail = hook.opt("detail");
                    boolean replan = "Replan".equals(hook.opt("exception_type"))
                            && detail instanceof String && !((String) detail).isEmpty();
                    if (!replan && !resultStop(hook, result)) return blocked("terminated_no_input_hook");
                } else if (exceptional) return blocked("nonterminated_hook_exception");
                continue;
            }
            if ((Boolean.TRUE.equals(terminated) || exceptional) && !resultStop(hook, result))
                return blocked("accepted_hook_terminated");
            if (count > accepted.size() - cursor) return blocked("hook_receipt_context_or_count_mismatch");
            for (int j = 0; j < count; j++)
                if (!kind.equals(accepted.get(cursor + j))) return blocked("hook_receipt_context_or_count_mismatch");
            cursor += (int) count;
            if ("end_turn".equals(kind)) {
                if (!"pending_transition".equals(verification)) return blocked("end_turn_hook_verification_invalid");
                if ("confirmed".equals(hook.opt("final_verification"))) confirmedEnds += count;
                else if (resolvedEndUnknown(hook, result))
                    unconfirmedEnds += count;
                else return blocked("end_turn_hook_not_resolved");
            } else if ("choice_select".equals(kind)) {
                if ("confirmed".equals(verification)) {
                    if (!"three_choice_disappeared".equals(hook.opt("detail"))) return blocked("choice_resolution_evidence_missing");
                } else if ("unconfirmed".equals(verification)) {
                    if (!"three_choice_still_present".equals(hook.opt("detail"))) return blocked("choice_unknown_evidence_missing");
                    ordinaryUnknown += count;
                } else return blocked("choice_hook_verification_unknown");
            } else if ("unconfirmed".equals(verification) || "unconfirmed_skipped".equals(verification)) {
                if ("unconfirmed_skipped".equals(verification) && "deploy".equals(kind)) return blocked("deploy_skip_not_supported");
                ordinaryUnknown += count;
                if ("unconfirmed_skipped".equals(verification)) skippedUnknown += count;
            } else if ("confirmed_refusal".equals(verification)) {
                if (!"deploy".equals(kind)) return blocked("non_deploy_refusal_not_supported");
            } else if (!"confirmed".equals(verification)) return blocked("ordinary_hook_verification_unknown");
        }
        if (cursor != accepted.size()) return blocked("accepted_touch_not_accounted_by_hooks");
        if (ordinaryUnknown != unknown || skippedUnknown != skipped) return blocked("ordinary_unknown_accounting_mismatch");
        if (failed > ordinaryUnknown+unconfirmedEnds) return blocked("failed_streak_not_explained_by_completed_unknown");
        if (confirmedEnds != endConfirmed) return blocked("end_turn_confirmed_accounting_mismatch");
        if (unconfirmedEnds != endUnknown) return blocked("end_turn_unknown_accounting_mismatch");
        return new ContinuationEvidence(true, ordinaryUnknown, "completed_receipts_bounded_failed_streak");
    }

    String continuationReason(int roundIndex, JSONObject result, JSONObject settle,
            boolean cancelled, boolean uncertain, long nextRoundMs, int nextRoundInputs) {
        if (cancelled) return "campaign_cancelled";
        if (uncertain) return "campaign_input_status_uncertain";
        if (!resultConfirmed(result)) return "campaign_result_unverified";
        if (result.has("exception") && !result.isNull("exception")) return "campaign_engine_failed";
        if (!continuationEvidence(result).safe) return "campaign_action_unconfirmed";
        if (!returned(settle)) return "campaign_return_unverified";
        if (!isUnlimited() && roundIndex >= matchCount) return "campaign_complete";
        if (roundIndex == Integer.MAX_VALUE) return "campaign_round_index_limit";
        // These are the configured fresh per-round limits. The previous round
        // must complete safely, but its spent allowance never funds this one.
        if (nextRoundMs < MIN_NEXT_ROUND_MS) return "campaign_time_reserve";
        if (nextRoundInputs < MIN_NEXT_ROUND_INPUTS) return "campaign_input_reserve";
        return null;
    }
}
