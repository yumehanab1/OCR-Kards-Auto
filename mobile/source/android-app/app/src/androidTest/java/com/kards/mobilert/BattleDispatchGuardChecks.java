package com.kards.mobilert;

import android.accessibilityservice.GestureDescription;
import android.graphics.PathMeasure;
import org.json.JSONArray;
import org.json.JSONObject;

/** Fake gate facts and in-memory Android paths only; never invokes an input service. */
final class BattleDispatchGuardChecks {
    private final JSONArray checks = new JSONArray();
    private int failures;

    private static final class Case {
        JSONObject frame = new JSONObject().put("frame_id", 12).put("captured_elapsed_ms", 10000)
                .put("foreground_generation", 5).put("source_width", 1920).put("source_height", 1080)
                .put("width", 1280).put("height", 720);
        JSONObject plan = new JSONObject().put("frame_id", 12).put("captured_elapsed_ms", 10000)
                .put("foreground_generation", 5).put("source_width", 1920).put("source_height", 1080)
                .put("kind", "drag").put("context", "attack_hq").put("duration_ms", 900)
                .put("from", new JSONArray().put(640).put(450)).put("to", new JSONArray().put(640).put(150));
        long consumed = 11;
        boolean cancelled;
        boolean readOnly;
        long now = 11000;
        long deadline = 30000;
        int inputs = 1;
        int maxInputs = 3;
        String foreground = "com.android1939.kards";
        long generation = 5;

        Case() throws Exception { }

        String verdict() throws Exception {
            return BattleDispatchGuard.validate(plan, frame, consumed, cancelled, readOnly,
                    now, deadline, inputs, maxInputs, foreground, generation);
        }
    }

    private interface Edit { void apply(Case test) throws Exception; }

    static JSONObject run() throws Exception {
        BattleDispatchGuardChecks test = new BattleDispatchGuardChecks();
        test.matrix();
        return new JSONObject().put("checks", test.checks).put("check_count", test.checks.length())
                .put("failure_count", test.failures).put("device_inputs", 0).put("uses_real_service", false);
    }

    private void matrix() throws Exception {
        verify("native_three_choice_middle", BattleDispatchGuardChecks::choice, null);
        verify("native_three_choice_missing_bounds", test -> {choice(test);test.plan.remove("choice_boxes");}, "three_choice_bounds_unconfirmed");
        verify("native_three_choice_wrong_card", test -> {choice(test);test.plan.put("from",point(799,645)).put("to",point(799,645));}, "three_choice_middle_target");
        verify("native_three_choice_drag_rejected", test -> {choice(test);test.plan.put("kind","drag");}, "choice_requires_native_tap");
        verify("native_three_choice_overlap_rejected", test -> {choice(test);test.plan.getJSONArray("choice_boxes").getJSONArray(2).put(0,1600);}, "three_choice_alignment");
        verify("valid_hq_drag", test -> { }, null);
        verify("valid_normalized_source", test -> {
            test.frame.put("source_width", 1280).put("source_height", 720);
            test.plan.put("source_width", 1280).put("source_height", 720);
        }, null);
        verify("valid_end_tap", test -> {
            test.plan.put("kind", "tap").put("context", "end_turn").put("duration_ms", 60)
                    .put("to", test.plan.getJSONArray("from"));
        }, null);
        verify("native_source_attack_coordinates", test -> {
            nativeFrame(test);
            test.plan.put("from", point(1800, 780)).put("to", point(2000, 250));
        }, null);
        verify("native_source_edge_rejected", test -> {
            nativeFrame(test);
            test.plan.put("to", point(2772, 200));
        }, "invalid_coordinates");
        verify("native_source_mixed_space_rejected", test -> {
            nativeFrame(test);
            test.plan.remove("coordinate_space");
        }, "coordinate_space_mismatch");
        verify("native_source_geometry_mismatch", test -> {
            nativeFrame(test);
            test.frame.put("width", 2771);
        }, "unsupported_frame_size");
        verify("cancelled_session_denies_input", test -> test.cancelled = true, "cancelled");
        verify("readonly_session_denies_input", test -> test.readOnly = true, "read_only");
        verify("zero_input_budget", test -> { test.inputs = 0; test.maxInputs = 0; }, "input_budget");
        verify("exhausted_input_budget", test -> test.inputs = 3, "input_budget");
        verify("deadline_is_exclusive", test -> test.now = test.deadline, "time_budget");
        verify("reserve_exactly_eight_seconds", test -> test.deadline = test.now + 8000, null);
        verify("reserve_verification_before_input", test -> test.deadline = test.now + 7999, "insufficient_verification_budget");
        verify("missing_current_frame", test -> test.frame = null, "stale_or_consumed_frame");
        verify("old_frame_id", test -> test.plan.put("frame_id", 11), "stale_or_consumed_frame");
        verify("accepted_frame_cannot_be_reused", test -> test.consumed = 12, "stale_or_consumed_frame");
        verify("forged_capture_time", test -> test.plan.put("captured_elapsed_ms", 11000), "frame_metadata_mismatch");
        verify("forged_foreground_generation", test -> test.plan.put("foreground_generation", 6), "frame_metadata_mismatch");
        verify("forged_source_width", test -> test.plan.put("source_width", 1280), "frame_metadata_mismatch");
        verify("forged_source_height", test -> test.plan.put("source_height", 720), "frame_metadata_mismatch");
        verify("unsupported_source_pair", test -> {
            test.frame.put("source_width", 1920).put("source_height", 720);
            test.plan.put("source_width", 1920).put("source_height", 720);
        }, "unsupported_frame_size");
        verify("normalized_width_mismatch", test -> test.frame.put("width", 1279), "unsupported_frame_size");
        verify("normalized_height_mismatch", test -> test.frame.put("height", 721), "unsupported_frame_size");
        verify("non_game_foreground", test -> test.foreground = "com.kards.mobilert", "foreground_changed");
        verify("unknown_foreground", test -> test.foreground = null, "foreground_changed");
        verify("leave_and_return_invalidates_frame", test -> test.generation = 7, "foreground_changed");
        verify("age_zero_is_valid", test -> test.now = 10000, null);
        verify("age_limit_inclusive", test -> test.now = 13000, null);
        verify("one_ms_beyond_age_limit", test -> test.now = 13001, "frame_age_expired");
        verify("future_capture_timestamp", test -> test.now = 9999, "frame_age_expired");
        verify("unsupported_gesture", test -> test.plan.put("kind", "swipe_shell"), "unsupported_gesture");
        verify("unsupported_action", test -> test.plan.put("context", "menu"), "unsupported_action");
        verify("zero_x_is_outside_input_bounds", test -> test.plan.put("from", point(0, 450)), "invalid_coordinates");
        verify("right_edge_is_outside_input_bounds", test -> test.plan.put("to", point(1280, 150)), "invalid_coordinates");
        verify("bottom_edge_is_outside_input_bounds", test -> test.plan.put("to", point(640, 720)), "invalid_coordinates");
        verify("negative_coordinate", test -> test.plan.put("to", point(640, -1)), "invalid_coordinates");
        verify("incomplete_point", test -> test.plan.put("from", new JSONArray().put(640)), "invalid_coordinates");
        verify("nan_coordinate_is_rejected", test -> test.plan.put("from", new JSONArray().put("NaN").put(450)), "invalid_coordinates");
        verify("too_short_duration", test -> test.plan.put("duration_ms", 39), "invalid_duration");
        verify("too_long_duration", test -> test.plan.put("duration_ms", 2501), "invalid_duration");
        verify("tap_cannot_change_target", test -> test.plan.put("kind", "tap"), "tap_target_mismatch");
        verify("deployment_fixed_lift_path", BattleDispatchGuardChecks::deployment, null);
        verify("deployment_minimum_lift_branch", test -> {
            deployment(test);
            test.plan.put("from", point(300, 620)).put("path_points", new JSONArray()
                    .put(point(300, 620)).put(point(300, 560)).put(point(353, 505)));
        }, null);
        verify("deployment_missing_path", test -> { deployment(test); test.plan.remove("path_points"); }, "invalid_deployment_path");
        verify("deployment_null_path", test -> { deployment(test); test.plan.put("path_points", JSONObject.NULL); }, "invalid_deployment_path");
        verify("deployment_extra_point", test -> {
            deployment(test); test.plan.getJSONArray("path_points").put(point(400, 500));
        }, "invalid_deployment_path");
        verify("deployment_changed_origin", test -> {
            deployment(test); test.plan.getJSONArray("path_points").put(0, point(871, 666));
        }, "invalid_deployment_path");
        verify("deployment_lateral_motion_before_lift", test -> {
            deployment(test); test.plan.getJSONArray("path_points").put(1, point(871, 575));
        }, "invalid_deployment_path");
        verify("deployment_changed_lift_height", test -> {
            deployment(test); test.plan.getJSONArray("path_points").put(1, point(872, 576));
        }, "invalid_deployment_path");
        verify("deployment_changed_destination", test -> {
            deployment(test); test.plan.getJSONArray("path_points").put(2, point(354, 505));
        }, "invalid_deployment_path");
        verify("deployment_string_waypoint_rejected", test -> {
            deployment(test); test.plan.getJSONArray("path_points").put(1, new JSONArray().put("872").put(575));
        }, "invalid_deployment_path");
        verify("deployment_incomplete_waypoint", test -> {
            deployment(test); test.plan.getJSONArray("path_points").put(1, new JSONArray().put(872));
        }, "invalid_deployment_path");
        verify("deployment_duration_fixed", test -> { deployment(test); test.plan.put("duration_ms", 901); }, "invalid_deployment_duration");
        verify("deployment_fractional_duration_rejected", test -> { deployment(test); test.plan.put("duration_ms", 900.5); }, "invalid_deployment_duration");
        verify("deployment_cannot_start_on_board", test -> {
            deployment(test); test.plan.put("from", point(872, 450)).put("path_points", new JSONArray()
                    .put(point(872, 450)).put(point(872, 390)).put(point(353, 505)));
        }, "invalid_deployment_path");
        verify("other_drag_context_cannot_accept_path", test -> test.plan.put("path_points", new JSONArray()), "path_points_outside_deployment");
        verify("tap_context_cannot_accept_path", test -> {
            test.plan.put("kind", "tap").put("context", "end_turn").put("duration_ms", 60)
                    .put("to", test.plan.getJSONArray("from")).put("path_points", new JSONArray());
        }, "path_points_outside_deployment");
        geometry(1280, 720);
        geometry(1920, 1080);
        geometry(2772, 1240);
        nativeGeometry();

        // These emulate evidence writing / IPC occurring between earlier and final gates.
        finalGate("cancel_between_preparation_and_dispatch", test -> test.cancelled = true, "cancelled");
        finalGate("deadline_crossed_during_prepared_evidence", test -> test.deadline = test.now, "time_budget");
        finalGate("age_expires_during_prepared_evidence", test -> test.now = 13001, "frame_age_expired");
        finalGate("foreground_changes_after_preparation", test -> test.foreground = "android", "foreground_changed");
        finalGate("input_budget_exhausted_after_preparation", test -> test.inputs = test.maxInputs, "input_budget");
        finalGate("frame_consumed_after_preparation", test -> test.consumed = 12, "stale_or_consumed_frame");
    }

    private static void deployment(Case test) throws Exception {
        test.plan.put("context", "deploy").put("kind", "drag").put("duration_ms", 900)
                .put("from", point(872, 666)).put("to", point(353, 505))
                .put("path_points", new JSONArray().put(point(872, 666)).put(point(872, 575)).put(point(353, 505)));
    }

    private void geometry(int width, int height) throws Exception {
        Case test = new Case();
        deployment(test);
        test.frame.put("source_width", width).put("source_height", height);
        test.plan.put("source_width", width).put("source_height", height);
        GestureDescription gesture = ApkBattleSession.buildGesture(test.plan, test.frame);
        GestureDescription.StrokeDescription stroke = gesture.getStroke(0);
        PathMeasure path = new PathMeasure(stroke.getPath(), false);
        double sx = width / 1280.0, sy = height / 720.0;
        float liftLength = (float) (91 * sy);
        float[] origin = new float[2], halfway = new float[2], waypoint = new float[2], target = new float[2];
        boolean positions = path.getPosTan(0, origin, null) && path.getPosTan(liftLength / 2, halfway, null)
                && path.getPosTan(liftLength, waypoint, null) && path.getPosTan(path.getLength(), target, null);
        boolean passed = positions && gesture.getStrokeCount() == 1 && stroke.getDuration() == 900 && !stroke.willContinue()
                && near(origin, 872 * sx, 666 * sy) && near(halfway, 872 * sx, 620.5 * sy)
                && near(waypoint, 872 * sx, 575 * sy) && near(target, 353 * sx, 505 * sy)
                && !path.nextContour();
        check("single_stroke_lift_geometry_" + width, passed, "one continuous 900ms lift path",
                ApkBattleSession.physicalPathPoints(test.plan, test.frame).toString());
    }

    private static boolean near(float[] point, double x, double y) {
        return Math.abs(point[0] - x) < .02 && Math.abs(point[1] - y) < .02;
    }

    private void nativeGeometry() throws Exception {
        Case test = new Case();
        nativeFrame(test);
        test.plan.put("from", point(2000, 850)).put("to", point(1500, 300));
        JSONArray path = ApkBattleSession.physicalPathPoints(test.plan, test.frame);
        check("native_source_pixels_not_rescaled", path.getJSONArray(0).getDouble(0) == 2000
                        && path.getJSONArray(0).getDouble(1) == 850
                        && path.getJSONArray(1).getDouble(0) == 1500
                        && path.getJSONArray(1).getDouble(1) == 300,
                "same source coordinates", path.toString());
    }

    private static void nativeFrame(Case test) throws Exception {
        test.frame.put("width", 2772).put("height", 1240).put("source_width", 2772)
                .put("source_height", 1240).put("coordinate_space", "source_pixels");
        test.plan.put("source_width", 2772).put("source_height", 1240)
                .put("coordinate_space", "source_pixels");
    }

    private static void choice(Case test) throws Exception {
        nativeFrame(test);
        test.plan.put("kind","tap").put("context","choice_select").put("duration_ms",60)
                .put("from",point(1385,645)).put("to",point(1385,645))
                .put("choice_boxes",new JSONArray()
                        .put(new JSONArray().put(544).put(282).put(514).put(728))
                        .put(new JSONArray().put(1128).put(281).put(514).put(728))
                        .put(new JSONArray().put(1716).put(279).put(514).put(728)));
    }

    private static JSONArray point(double x, double y) throws Exception {
        return new JSONArray().put(x).put(y);
    }

    private void verify(String name, Edit edit, String expected) throws Exception {
        Case test = new Case();
        edit.apply(test);
        String actual = test.verdict();
        check(name, java.util.Objects.equals(expected, actual), expected, actual);
    }

    private void finalGate(String name, Edit edit, String expected) throws Exception {
        Case test = new Case();
        String earlier = test.verdict();
        edit.apply(test);
        String actual = test.verdict();
        check(name, earlier == null && expected.equals(actual), expected, actual);
    }

    private void check(String name, boolean passed, String expected, String actual) throws Exception {
        checks.put(new JSONObject().put("name", name).put("passed", passed)
                .put("expected", expected == null ? JSONObject.NULL : expected)
                .put("actual", actual == null ? JSONObject.NULL : actual));
        if (!passed) failures++;
    }
}
