package com.kards.mobilert;

import org.json.JSONArray;
import org.json.JSONObject;

/** Fake frame metadata and targets only. No gestures are dispatched. */
public final class MenuDispatchGuardChecks {
    private final JSONArray checks = new JSONArray();
    private int failures;
    private interface Edit { void apply(Case test) throws Exception; }

    private static final class Case {
        JSONObject frame = new JSONObject().put("frame_id", 3).put("captured_elapsed_ms", 1000)
                .put("foreground_generation", 5).put("source_width", 1920).put("source_height", 1080)
                .put("width", 1280).put("height", 720);
        JSONObject plan = new JSONObject(frame.toString()).put("kind", "tap").put("duration_ms", 60)
                .put("state", "home").put("context", "menu_home_start").put("mode", "casual")
                .put("first_deck_selected", true)
                .put("from", point(200, 150)).put("to", point(200, 150))
                .put("target_bounds", new JSONArray().put(150).put(125).put(100).put(50));
        long consumed, now = 1500, deadline = 100000, generation = 5;
        boolean cancelled, readOnly;
        int inputs;
        String stage = "menu", mode = "casual", foreground = "com.android1939.kards";
        Case() throws Exception { }
        String verdict() throws Exception {
            return MenuDispatchGuard.validate(plan, frame, consumed, cancelled, readOnly, now, deadline,
                    inputs, stage, mode, foreground, generation);
        }
    }

    public static JSONObject run() throws Exception {
        MenuDispatchGuardChecks test = new MenuDispatchGuardChecks();
        test.matrix();
        return new JSONObject().put("checks", test.checks).put("check_count", test.checks.length())
                .put("failure_count", test.failures).put("device_inputs", 0);
    }

    private void matrix() throws Exception {
        verify("startup_unknown_allows_blank_without_popup_proof", t -> nativeStartup(t), null);
        verify("startup_queue_refuses_blank", t -> {nativeStartup(t);t.plan.put("queue_requested",true);}, "startup_cleanup_scope_required");
        verify("startup_disabled_refuses_blank", t -> {nativeStartup(t);t.plan.put("startup_cleanup",false);}, "startup_cleanup_scope_required");
        verify("startup_fifteen_refuses_blank", t -> {nativeStartup(t);t.plan.put("startup_cleanup_attempts",15);}, "startup_cleanup_exhausted");
        verify("startup_battle_refuses_blank", t -> {nativeStartup(t);t.stage="battle";}, "not_menu_stage");
        verify("startup_home_refuses_blank", t -> {nativeStartup(t);t.plan.put("state","home");}, "unsupported_menu_action");
        verify("startup_wrong_point_refuses_blank", t -> {nativeStartup(t);t.plan.put("target_bounds",new JSONArray().put(100).put(100).put(41).put(41));}, "popup_blank_bounds_mismatch");
        String[][] pairs = {{"home", "menu_home_start"}, {"mode_menu", "menu_battle_mode"},
                {"deck_list", "menu_select_deck"}, {"deck_ready", "menu_select_casual"},
                {"deck_ready", "menu_select_ranked"}, {"deck_ready", "menu_start_queue"},
                {"login_reward", "menu_dismiss_reward"}, {"disconnected", "menu_reconnect"},
                {"task_popup", "menu_dismiss_task"}, {"pass_popup", "menu_dismiss_pass"},
                {"box_popup", "menu_dismiss_box"}, {"deck_ready", "menu_close_deck"},
                {"airdrop_popup", "menu_dismiss_airdrop"}, {"starter_popup", "menu_dismiss_starter"},
                {"weekend_popup", "menu_dismiss_weekend"}};
        for (String[] pair : pairs) {
            verify("recognized_" + pair[1], test -> {
                action(test, pair[0], pair[1]);
                if ("menu_select_ranked".equals(pair[1])) { test.mode = "ranked"; test.plan.put("mode", "ranked"); }
                test.plan.put("selected_mode", test.mode);
            }, null);
            if (!requiresFirstDeck(pair[1])) {
                verify("unselected_first_deck_allows_" + pair[1], test -> {
                    action(test, pair[0], pair[1]);
                    test.plan.put("first_deck_selected", false);
                }, null);
            }
        }
        for (String context : new String[]{"menu_select_casual", "menu_select_ranked", "menu_start_queue"}) {
            verify("unverified_first_deck_refuses_" + context, test -> {
                action(test, "deck_ready", context);
                if ("menu_select_ranked".equals(context)) { test.mode = "ranked"; test.plan.put("mode", "ranked"); }
                test.plan.put("selected_mode", test.mode).put("first_deck_selected", false);
            }, "first_deck_not_verified");
        }
        verify("first_deck_selection_field_is_required", test -> test.plan.remove("first_deck_selected"), "invalid_first_deck_selected");
        Object[] invalidSelections = {"true", "false", 1, 0, JSONObject.NULL, new JSONArray(), new JSONObject()};
        for (int i = 0; i < invalidSelections.length; i++) {
            final Object value = invalidSelections[i];
            verify("first_deck_selection_is_strict_boolean_" + i,
                    test -> test.plan.put("first_deck_selected", value), "invalid_first_deck_selected");
            verify("queue_cannot_coerce_first_deck_selection_" + i, test -> {
                action(test, "deck_ready", "menu_start_queue");
                test.plan.put("selected_mode", "casual").put("first_deck_selected", value);
            }, "invalid_first_deck_selected");
        }
        String[][] newActions = {{"task_popup", "menu_dismiss_task"}, {"pass_popup", "menu_dismiss_pass"},
                {"box_popup", "menu_dismiss_box"}, {"deck_ready", "menu_close_deck"},
                {"airdrop_popup", "menu_dismiss_airdrop"}, {"starter_popup", "menu_dismiss_starter"},
                {"weekend_popup", "menu_dismiss_weekend"}};
        for (String[] pair : newActions) {
            verify("wrong_state_refuses_" + pair[1], test -> action(test, "home", pair[1]), "unsupported_menu_action");
            verify("consumed_frame_refuses_" + pair[1], test -> {
                action(test, pair[0], pair[1]); test.consumed = 3;
            }, "stale_or_consumed_frame");
            verify("expired_frame_refuses_" + pair[1], test -> {
                action(test, pair[0], pair[1]); test.now = 4001;
            }, "frame_age_expired");
            verify("foreground_change_refuses_" + pair[1], test -> {
                action(test, pair[0], pair[1]); test.generation++;
            }, "foreground_changed");
            verify("input_budget_refuses_" + pair[1], test -> {
                action(test, pair[0], pair[1]); test.inputs = 16;
            }, "menu_input_budget");
            verify("cancelled_refuses_" + pair[1], test -> {
                action(test, pair[0], pair[1]); test.cancelled = true;
            }, "cancelled");
            verify("wrong_stage_refuses_" + pair[1], test -> {
                action(test, pair[0], pair[1]); test.stage = "battle";
            }, "not_menu_stage");
        }
        verify("task_popup_cannot_dismiss_pass", test -> action(test, "task_popup", "menu_dismiss_pass"), "unsupported_menu_action");
        verify("pass_popup_cannot_dismiss_box", test -> action(test, "pass_popup", "menu_dismiss_box"), "unsupported_menu_action");
        verify("box_popup_cannot_dismiss_task", test -> action(test, "box_popup", "menu_dismiss_task"), "unsupported_menu_action");
        verify("airdrop_cannot_use_starter_close", test -> action(test, "airdrop_popup", "menu_dismiss_starter"), "unsupported_menu_action");
        verify("starter_cannot_use_airdrop_close", test -> action(test, "starter_popup", "menu_dismiss_airdrop"), "unsupported_menu_action");
        verify("weekend_cannot_use_starter_close", test -> action(test, "weekend_popup", "menu_dismiss_starter"), "unsupported_menu_action");
        verify("starter_cannot_use_weekend_close", test -> action(test, "starter_popup", "menu_dismiss_weekend"), "unsupported_menu_action");
        for (String[] pair : new String[][]{{"airdrop_popup", "menu_dismiss_airdrop"},
                                           {"starter_popup", "menu_dismiss_starter"},
                                           {"weekend_popup", "menu_dismiss_weekend"}}) {
            verify("offer_body_is_not_close_" + pair[1], test -> {
                action(test, pair[0], pair[1]);
                test.plan.put("target_bounds", new JSONArray().put(340).put(450).put(100).put(50))
                        .put("from", point(390, 475)).put("to", point(390, 475));
            }, "promotion_close_bounds_mismatch");
            verify("offer_large_target_is_not_close_" + pair[1], test -> {
                action(test, pair[0], pair[1]);
                test.plan.put("target_bounds", new JSONArray().put(938).put(202).put(50).put(50));
            }, "promotion_close_bounds_mismatch");
            verify("offer_moved_target_is_not_close_" + pair[1], test -> {
                action(test, pair[0], pair[1]);
                test.plan.put("target_bounds", new JSONArray().put(942).put(202).put(25).put(25));
            }, "promotion_close_bounds_mismatch");
            verify("offer_coherent_small_shift_allowed_" + pair[1], test -> {
                action(test, pair[0], pair[1]);
                test.plan.put("target_bounds", new JSONArray().put(940).put(203).put(25).put(25))
                        .put("from", point(952.5, 215.5)).put("to", point(952.5, 215.5));
            }, null);
            verify("offer_cannot_purchase_" + pair[1], test -> action(test, pair[0], "menu_purchase_offer"), "unsupported_menu_action");
        }
        verify("deck_close_uses_verified_neutral_target_center", test -> {
            action(test, "deck_ready", "menu_close_deck");
            test.plan.put("first_deck_selected", false);
        }, null);
        verify("deck_close_rejects_off_center_tap", test -> {
            action(test, "deck_ready", "menu_close_deck");
            test.plan.put("from", point(855, 600)).put("to", point(855, 600));
        }, "tap_outside_target_center");
        verify("mode_context_alias_is_not_authorized", test -> action(test, "deck_ready", "menu_select_mode_casual"), "unsupported_menu_action");
        verify("wrong_screen_cannot_use_known_action", t -> t.plan.put("state", "matching"), "unsupported_menu_action");
        verify("battle_action_cannot_use_menu_dispatch", t -> t.plan.put("context", "end_turn"), "unsupported_menu_action");
        verify("ranked_session_cannot_select_casual", t -> {
            t.mode = "ranked"; t.plan.put("mode", "ranked").put("state", "deck_ready").put("context", "menu_select_casual");
        }, "menu_mode_mismatch");
        verify("queue_requires_observed_selected_mode", t -> {
            t.plan.put("state", "deck_ready").put("context", "menu_start_queue");
        }, "queue_mode_not_verified");
        verify("queue_rejects_the_other_selected_mode", t -> {
            t.plan.put("state", "deck_ready").put("context", "menu_start_queue").put("selected_mode", "ranked");
        }, "queue_mode_not_verified");
        verify("request_cannot_change_campaign_mode", t -> t.plan.put("mode", "ranked"), "menu_mode_mismatch");
        verify("training_does_not_enable_menu_dispatch", t -> { t.mode = "training"; t.plan.put("mode", "training"); }, "menu_mode_mismatch");
        verify("cancelled_campaign_refuses_input", t -> t.cancelled = true, "cancelled");
        verify("read_only_refuses_input", t -> t.readOnly = true, "read_only");
        for (String phase : new String[]{"opening", "battle", "finished"}) {
            verify("no_menu_input_during_" + phase, t -> t.stage = phase, "not_menu_stage");
        }
        verify("sixteenth_menu_input_is_allowed", t -> t.inputs = 15, null);
        verify("seventeenth_menu_input_is_refused", t -> t.inputs = 16, "menu_input_budget");
        verify("deadline_refuses_input", t -> t.deadline = t.now, "time_budget");
        verify("verification_time_reserved", t -> t.deadline = t.now + 7999, "insufficient_verification_budget");
        verify("consumed_frame_cannot_retry", t -> t.consumed = 3, "stale_or_consumed_frame");
        verify("missing_capture_refuses_input", t -> t.frame = null, "stale_or_consumed_frame");
        verify("another_frame_cannot_authorize_input", t -> t.plan.put("frame_id", 4), "stale_or_consumed_frame");
        verify("metadata_string_is_not_coerced", t -> t.plan.put("captured_elapsed_ms", "1000"), "frame_metadata_mismatch");
        for (String key : new String[]{"captured_elapsed_ms", "foreground_generation", "source_width", "source_height"}) {
            verify("changed_metadata_" + key, t -> t.plan.put(key, t.plan.getLong(key) + 1), "frame_metadata_mismatch");
        }
        verify("unsupported_source_size_refuses_input", t -> {
            t.frame.put("source_width", 1600); t.plan.put("source_width", 1600);
        }, "unsupported_frame_size");
        verify("non_game_foreground_refuses_input", t -> t.foreground = "com.kards.mobilert", "foreground_changed");
        verify("foreground_generation_cannot_change", t -> t.generation++, "foreground_changed");
        verify("frame_at_age_boundary_allowed", t -> t.now = 4000, null);
        verify("frame_after_age_boundary_refused", t -> t.now = 4001, "frame_age_expired");
        verify("future_capture_refused", t -> t.now = 999, "frame_age_expired");
        verify("menu_never_drags", t -> t.plan.put("kind", "drag"), "menu_tap_required");
        verify("tap_duration_fixed", t -> t.plan.put("duration_ms", 61), "invalid_menu_duration");
        verify("duration_string_not_coerced", t -> t.plan.put("duration_ms", "60"), "invalid_menu_duration");
        verify("custom_path_refused", t -> t.plan.put("path_points", new JSONArray()), "menu_path_forbidden");
        verify("different_tap_end_refused", t -> t.plan.put("to", point(201, 150)), "tap_target_mismatch");
        verify("point_at_screen_edge_refused", t -> t.plan.put("from", point(0, 150)), "invalid_coordinates");
        verify("missing_target_bounds_refused", t -> t.plan.remove("target_bounds"), "invalid_target_bounds");
        verify("out_of_screen_bounds_refused", t -> t.plan.put("target_bounds", new JSONArray().put(1250).put(125).put(100).put(50)), "invalid_target_bounds");
        verify("point_must_be_target_center", t -> {
            t.plan.put("from", point(201, 150)).put("to", point(201, 150));
        }, "tap_outside_target_center");
        verify("rounded_odd_target_center_allowed", t -> t.plan.put("target_bounds", new JSONArray().put(150).put(125).put(101).put(51)), null);
        verify("normalized_1280_source_allowed", t -> {
            t.frame.put("source_width", 1280).put("source_height", 720);
            t.plan.put("source_width", 1280).put("source_height", 720);
        }, null);
        verify("native_source_pixels_allowed", t -> {
            t.frame.put("width", 2772).put("height", 1240).put("source_width", 2772).put("source_height", 1240).put("coordinate_space", "source_pixels");
            t.plan.put("width", 2772).put("height", 1240).put("source_width", 2772).put("source_height", 1240).put("coordinate_space", "source_pixels")
                    .put("target_bounds", new JSONArray().put(400).put(300).put(200).put(100))
                    .put("from", point(500, 350)).put("to", point(500, 350));
        }, null);
        verify("native_source_pixels_rejects_normalized_plan", t -> {
            t.frame.put("width", 2772).put("height", 1240).put("source_width", 2772).put("source_height", 1240).put("coordinate_space", "source_pixels");
            t.plan.put("source_width", 2772).put("source_height", 1240);
        }, "coordinate_space_mismatch");
        for (int count:new int[]{1,2,3}) verify("native_daily_slots_"+count,t -> nativeDaily(t,count),null);
        for (int count:new int[]{0,4}) verify("native_daily_slot_count_rejected_"+count,t -> nativeDaily(t,count),"login_popup_unverified");
        verify("native_daily_title_still_required",t -> {nativeDaily(t,2);t.plan.getJSONObject("login_popup_evidence").put("title_score",.93);},"login_popup_unverified");
        verify("native_daily_blank_still_required",t -> {nativeDaily(t,2);t.plan.getJSONObject("login_popup_evidence").put("blank_score",.93);},"login_popup_unverified");
        verify("native_task_popup_blank_allowed", t -> nativePopup(t), null);
        verify("native_pass_popup_blank_allowed", t -> {
            nativePopup(t); t.plan.put("state","pass_popup").put("context","menu_dismiss_pass")
                    .put("popup_basis","pass_title_subtitle_and_panel");
        }, null);
        verify("native_task_popup_card_point_refused", t -> {
            nativePopup(t);
            t.plan.put("target_bounds", new JSONArray().put(1300).put(700).put(41).put(41));
        }, "popup_blank_bounds_mismatch");
        verify("native_task_popup_requires_evidence", t -> {
            nativePopup(t); t.plan.remove("popup_basis");
        }, "popup_evidence_missing");
        verify("native_promotion_six_anchors_allowed", t -> nativeOffer(t), null);
        verify("native_generic_popup_allowed", t -> nativeGeneric(t), null);
        verify("native_generic_popup_missing_id_refused", t -> {
            nativeGeneric(t); t.plan.getJSONObject("generic_popup_evidence").remove("popup_id");
        }, "generic_popup_unverified");
        verify("native_generic_popup_bad_edge_refused", t -> {
            nativeGeneric(t); t.plan.getJSONObject("generic_popup_evidence").getJSONArray("edge_coverage").put(0, .8);
        }, "generic_popup_unverified");
        verify("native_promotion_missing_edge_refused", t -> {
            nativeOffer(t); t.plan.getJSONObject("promotion_evidence").remove("edge_left");
        }, "native_promotion_close_unverified");
        verify("native_promotion_low_score_refused", t -> {
            nativeOffer(t); t.plan.getJSONObject("promotion_evidence").getJSONObject("title").put("score", .92);
        }, "native_promotion_close_unverified");
        verify("native_promotion_incoherent_panel_refused", t -> {
            nativeOffer(t); t.plan.getJSONObject("promotion_evidence").getJSONObject("edge_top")
                    .put("offset", point(10, 0));
        }, "native_promotion_close_unverified");
    }

    private static void nativeGeneric(Case t) throws Exception {
        nativePopup(t);
        JSONObject evidence=new JSONObject()
                .put("panel_bounds",new JSONArray().put(827).put(328).put(1107).put(572))
                .put("edge_coverage",new JSONArray().put(1).put(1).put(.98).put(.98))
                .put("popup_id","eabbf3dbc0c68476914646759853db593763bab0f124f7a5b0bb77f84d6b2eae")
                .put("close",new JSONObject().put("score",.985).put("bounds",new JSONArray().put(1892).put(354).put(39).put(39)));
        t.plan.put("state","generic_popup").put("context","menu_dismiss_generic")
                .put("generic_popup_evidence",evidence).put("target_bounds",new JSONArray().put(1892).put(354).put(39).put(39))
                .put("from",point(1911.5,373.5)).put("to",point(1911.5,373.5));
    }

    private static void nativeOffer(Case t) throws Exception {
        nativePopup(t);
        JSONObject evidence=new JSONObject();
        String[] names={"title","close","edge_top","edge_bottom","edge_left","edge_right"};
        int[][] boxes={{881,414,317,84},{1891,353,42,42},{831,340,1114,10},
                {829,890,1114,12},{828,350,10,540},{1932,350,12,540}};
        for(int i=0;i<names.length;i++) evidence.put(names[i],new JSONObject().put("score",.95)
                .put("offset",point(0,0)).put("bounds",new JSONArray(boxes[i])));
        t.plan.put("state","starter_popup").put("context","menu_dismiss_starter")
                .put("promotion_evidence",evidence).put("target_bounds",new JSONArray(boxes[1]))
                .put("from",point(1912,374)).put("to",point(1912,374));
    }

    private static void nativePopup(Case t) throws Exception {
        t.frame.put("width", 2772).put("height", 1240).put("source_width", 2772)
                .put("source_height", 1240).put("coordinate_space", "source_pixels");
        for (String key : new String[]{"width", "height", "source_width", "source_height", "coordinate_space"})
            t.plan.put(key, t.frame.get(key));
        double size = Math.round(1240 * 24 / 720.0), cy = Math.round(1240 * 665 / 720.0);
        t.plan.put("state", "blocking_popup").put("context", "menu_dismiss_blocking_popup")
                .put("popup_basis", "task_title_and_subtitle")
                .put("target_bounds", new JSONArray().put(1386-size/2).put(cy-size/2).put(size).put(size))
                .put("from", point(1386, cy)).put("to", point(1386, cy));
    }

    private static void nativeStartup(Case t) throws Exception {
        nativePopup(t);
        t.plan.put("state","unknown").put("context","menu_startup_cleanup")
                .put("startup_cleanup",true).put("queue_requested",false).put("startup_cleanup_attempts",0);
    }

    private static void nativeDaily(Case t,int count) throws Exception {
        nativePopup(t);JSONArray buttons=new JSONArray();
        for(int i=0;i<count;i++) buttons.put(new JSONObject().put("score",.99)
                .put("bounds",new JSONArray().put(1000+i*300).put(830).put(90).put(50)));
        t.plan.put("state","login_popup_cleanup").put("context","menu_clear_login_popup")
                .put("login_popup_evidence",new JSONObject().put("title_score",.99).put("blank_score",.99).put("buttons",buttons));
    }

    private static JSONArray point(double x, double y) throws Exception { return new JSONArray().put(x).put(y); }
    private static boolean requiresFirstDeck(String context) {
        return "menu_select_casual".equals(context) || "menu_select_ranked".equals(context) || "menu_start_queue".equals(context);
    }
    private static void action(Case test, String state, String context) throws Exception {
        test.plan.put("state", state).put("context", context);
        int[] bounds;
        switch (context) {
            case "menu_close_deck": bounds = new int[]{840, 586, 28, 28}; break;
            case "menu_select_deck": bounds = new int[]{358, 87, 177, 250}; break;
            case "menu_dismiss_task": bounds = new int[]{890, 585, 32, 30}; break;
            case "menu_dismiss_pass":
            case "menu_dismiss_box": bounds = new int[]{932, 199, 31, 29}; break;
            case "menu_dismiss_airdrop":
            case "menu_dismiss_weekend":
            case "menu_dismiss_starter": bounds = new int[]{938, 202, 25, 25}; break;
            default: return;
        }
        JSONArray target = new JSONArray();
        for (int value : bounds) target.put(value);
        double x = bounds[0] + bounds[2] / 2.0, y = bounds[1] + bounds[3] / 2.0;
        test.plan.put("target_bounds", target).put("from", point(x, y)).put("to", point(x, y));
    }
    private void verify(String name, Edit edit, String expected) throws Exception {
        JSONObject row = new JSONObject().put("name", name);
        try {
            Case test = new Case(); edit.apply(test);
            String actual = test.verdict();
            boolean passed = java.util.Objects.equals(expected, actual);
            row.put("passed", passed).put("expected", expected == null ? JSONObject.NULL : expected)
                    .put("actual", actual == null ? JSONObject.NULL : actual);
            if (!passed) failures++;
        } catch (Throwable failure) { failures++; row.put("passed", false).put("error", failure.toString()); }
        checks.put(row);
    }
}
