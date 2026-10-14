package com.kards.mobilert;

import org.json.JSONArray;
import org.json.JSONObject;

/** Fake frame metadata only; no gesture is ever dispatched.
 *
 * The settlement guard is the boundary that lets a campaign leave a finished
 * match's result screen, so these checks pin both directions: a well-formed
 * settle tap is allowed, and every way of smuggling battle/menu authority
 * through it is refused.
 */
public final class SettleDispatchGuardChecks {
    private final JSONArray checks = new JSONArray();
    private int failures;
    private interface Edit { void apply(Case test) throws Exception; }

    private static final class Case {
        final JSONObject frame;
        final JSONObject plan;
        long consumed, now = 1500, deadline = 100000, generation = 5;
        boolean cancelled, readOnly;
        int clicks, maxClicks = SettleDispatchGuard.TOTAL_MAX_CLICKS;
        int[][] occupied = new int[0][];
        String foreground = "com.android1939.kards";

        Case() throws Exception {
            frame = new JSONObject().put("frame_id", 7).put("captured_elapsed_ms", 1000)
                    .put("foreground_generation", 5).put("source_width", 1920).put("source_height", 1080)
                    .put("width", 1280).put("height", 720);
            plan = new JSONObject(frame.toString()).put("kind", "tap")
                    .put("duration_ms", SettleDispatchGuard.TAP_DURATION_MS)
                    .put("context", "settle")
                    .put("from", point(640, 665)).put("to", point(640, 665));
        }

        String verdict() throws Exception {
            return SettleDispatchGuard.validate(plan, frame, consumed, cancelled, readOnly, now,
                    deadline, clicks, maxClicks, occupied, foreground, generation);
        }
    }

    public static JSONObject run() throws Exception {
        SettleDispatchGuardChecks test = new SettleDispatchGuardChecks();
        test.matrix();
        return new JSONObject().put("checks", test.checks).put("check_count", test.checks.length())
                .put("failure_count", test.failures).put("device_inputs", 0);
    }

    private void matrix() throws Exception {
        verify("settle_tap_allowed", test -> { });
        verify("native_source_pixels_settle_allowed", test -> {
            test.frame.put("width", 2772).put("height", 1240).put("source_width", 2772).put("source_height", 1240).put("coordinate_space", "source_pixels");
            test.plan.put("width", 2772).put("height", 1240).put("source_width", 2772).put("source_height", 1240).put("coordinate_space", "source_pixels")
                    .put("from", point(1386, 1100)).put("to", point(1386, 1100));
        });
        verify("fixed_continue_point_is_the_observed_android_point_allowed", test -> {
            if (SettleDispatchGuard.DEFAULT_POINTS[0][0] != 640 || SettleDispatchGuard.DEFAULT_POINTS[0][1] != 665)
                throw new IllegalStateException("default no longer hits Android Continue");
        });
        verify("fixed_continue_jitter_envelope_clears_home_controls_allowed", test -> {
            int[][] controls = {{26,101,93,181},{8,201,75,268},{8,287,75,354},
                    {255,555,425,627},{499,555,694,627},{1110,555,1280,627},
                    {1120,170,1280,225},{1120,330,1280,385}};
            for (int x=628;x<=652;x++) for (int y=653;y<=677;y++) {
                for (int[] control:controls) if(x>=control[0]&&x<=control[2]&&y>=control[1]&&y<=control[3])
                    throw new IllegalStateException("jitter hits live home control");
                test.plan.put("from",point(x,y)).put("to",point(x,y));
                if(test.verdict()!=null) throw new IllegalStateException("safe jitter point refused");
            }
        });
        verify("every_reviewed_point_is_allowed", test -> {
            for (int[] point : SettleDispatchGuard.DEFAULT_POINTS) {
                test.plan.put("from", point(point[0], point[1]));
                test.plan.put("to", point(point[0], point[1]));
                if (test.verdict() != null) throw new IllegalStateException("refused " + point[0] + "," + point[1]);
            }
        });
        verify("default_points_avoid_the_frame_centre_allowed", test -> {
            for (int[] point : SettleDispatchGuard.DEFAULT_POINTS) {
                if (Math.abs(point[0] - 640) + Math.abs(point[1] - 360) <= 80) {
                    throw new IllegalStateException("point too close to centre");
                }
            }
        });
        verify("default_points_clear_the_start_page_controls_allowed", test -> {
            // Measured start-page controls. A candidate inside one clicks a menu
            // button, and settlement must leave the game on the start page.
            int[][] controls = {{26, 101, 93, 181}, {8, 201, 75, 268}, {8, 287, 75, 354},
                                {255, 555, 425, 627}, {499, 555, 694, 627},
                                {1110, 555, 1280, 627}, {1120, 170, 1280, 225},
                                {1120, 330, 1280, 385}};
            for (int[] point : SettleDispatchGuard.DEFAULT_POINTS) {
                for (int[] control : controls) {
                    if (point[0] >= control[0] && point[0] <= control[2]
                            && point[1] >= control[1] && point[1] <= control[3]) {
                        throw new IllegalStateException("point " + point[0] + "," + point[1]
                                + " sits on a start-page control");
                    }
                }
            }
        });
        verify("start_slot_is_not_a_candidate_allowed", test -> {
            for (int[] point : SettleDispatchGuard.DEFAULT_POINTS) {
                if (Math.abs(point[0] - 59) <= 20 && Math.abs(point[1] - 147) <= 20) {
                    throw new IllegalStateException("the 开始 slot is an active control");
                }
            }
        });
        verify("start_button_is_the_measured_home_play_slot_allowed", test -> {
            // The return step presses this centre and nothing else. It is the
            // home_play tile's measured centre (38,151,101,120 in the 1920x1080
            // start-page sample), so a drifted constant would press the wrong
            // part of the left menu column.
            if (Math.abs(SettleDispatchGuard.START_BUTTON[0] - 59) > 2
                    || Math.abs(SettleDispatchGuard.START_BUTTON[1] - 147) > 2) {
                throw new IllegalStateException("start button drifted from the measured slot");
            }
        });
        verify("start_button_tap_allowed", test -> {
            test.plan.put("from", point(SettleDispatchGuard.START_BUTTON[0], SettleDispatchGuard.START_BUTTON[1]));
            test.plan.put("to", point(SettleDispatchGuard.START_BUTTON[0], SettleDispatchGuard.START_BUTTON[1]));
        });
        verify("start_button_is_not_a_dismissal_candidate_allowed", test -> {
            for (int[] point : SettleDispatchGuard.DEFAULT_POINTS) {
                if (point[0] == SettleDispatchGuard.START_BUTTON[0]
                        && point[1] == SettleDispatchGuard.START_BUTTON[1]) {
                    throw new IllegalStateException("the return button became a blind dismissal point");
                }
            }
        });
        verify("dismissal_budget_leaves_the_return_budget_allowed", test -> {
            // The dismissal may spend its whole budget and the return step must
            // still be able to act: the guard's cap is the two phases together.
            test.clicks = SettleDispatchGuard.MAX_CLICKS;
        });
        verify("start_button_after_a_full_dismissal_allowed", test -> {
            test.clicks = SettleDispatchGuard.MAX_CLICKS;
            test.plan.put("from", point(SettleDispatchGuard.START_BUTTON[0], SettleDispatchGuard.START_BUTTON[1]));
            test.plan.put("to", point(SettleDispatchGuard.START_BUTTON[0], SettleDispatchGuard.START_BUTTON[1]));
        });
        verify("battle_context_refused", test -> test.plan.put("context", "deploy"));
        verify("end_turn_context_refused", test -> test.plan.put("context", "end_turn"));
        verify("menu_context_refused", test -> test.plan.put("context", "menu_home_start"));
        verify("drag_refused", test -> {
            test.plan.put("kind", "drag");
            test.plan.put("to", point(700, 400));
        });
        verify("path_points_refused", test -> test.plan.put("path_points",
                new JSONArray().put(point(640, 501)).put(point(640, 400)).put(point(700, 300))));
        verify("wrong_duration_refused", test -> test.plan.put("duration_ms", 900));
        verify("long_press_refused", test -> test.plan.put("duration_ms", 2500));
        verify("tap_target_mismatch_refused", test -> test.plan.put("to", point(500, 501)));
        verify("outside_frame_refused", test -> {
            test.plan.put("from", point(0, 501));
            test.plan.put("to", point(0, 501));
        });
        verify("return_budget_exhausted_refused", test -> test.clicks = SettleDispatchGuard.TOTAL_MAX_CLICKS);
        verify("total_budget_is_both_phases_allowed", test -> {
            if (SettleDispatchGuard.TOTAL_MAX_CLICKS
                    != SettleDispatchGuard.MAX_CLICKS + SettleDispatchGuard.RETURN_MAX_CLICKS) {
                throw new IllegalStateException("the guard's cap is not the two phase budgets");
            }
        });
        verify("live_control_refused", test -> test.occupied = new int[][]{{600, 635, 760, 690}});
        verify("control_far_away_allowed", test -> test.occupied = new int[][]{{20, 20, 120, 90}});
        verify("stale_frame_refused", test -> test.consumed = 7);
        verify("expired_frame_refused", test -> test.now = 1000 + BattleDispatchGuard.FRAME_MAX_AGE_MS + 1);
        verify("deadline_refused", test -> test.now = 100000);
        verify("cancelled_refused", test -> test.cancelled = true);
        verify("read_only_refused", test -> test.readOnly = true);
        verify("foreground_change_refused", test -> test.generation = 6);
        verify("wrong_package_refused", test -> test.foreground = "com.other.app");
        verify("metadata_mismatch_refused", test -> test.plan.put("source_width", 1280));
        verify("wrong_frame_size_refused", test -> test.frame.put("width", 1920));
        verify("unsupported_source_refused", test -> test.frame.put("source_width", 1000));
    }

    private void verify(String name, Edit edit) throws Exception {
        Case test = new Case();
        edit.apply(test);
        String verdict = test.verdict();
        String expected = name.endsWith("_allowed") ? null : "reject";
        boolean ok = expected == null ? verdict == null : verdict != null;
        if (!ok) failures++;
        checks.put(new JSONObject().put("name", name).put("expected", expected == null ? "allowed" : "rejected")
                .put("actual", verdict == null ? "allowed" : verdict).put("passed", ok));
    }

    private static JSONArray point(int x, int y) throws Exception {
        return new JSONArray().put(x).put(y);
    }
}
