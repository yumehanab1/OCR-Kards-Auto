package com.kards.mobilert;

import org.json.JSONArray;
import org.json.JSONObject;

/** Pure final-input checks; all platform facts must be freshly supplied by the bridge. */
final class BattleDispatchGuard {
    static final long FRAME_MAX_AGE_MS = 3000;
    private static final String GAME = "com.android1939.kards";

    private BattleDispatchGuard() { }

    static String validate(JSONObject plan, JSONObject frame, long consumedFrame,
                           boolean cancelled, boolean readOnly, long now, long deadline,
                           int inputs, int maxInputs, String foreground, long generation) throws Exception {
        if (cancelled) return "cancelled";
        if (readOnly) return "read_only";
        if (now >= deadline) return "time_budget";
        if (deadline - now < 8000) return "insufficient_verification_budget";
        if (inputs >= maxInputs) return "input_budget";
        if (frame == null || plan.getLong("frame_id") != frame.getLong("frame_id")
                || consumedFrame == frame.getLong("frame_id")) return "stale_or_consumed_frame";
        if (plan.getLong("captured_elapsed_ms") != frame.getLong("captured_elapsed_ms")
                || plan.getLong("foreground_generation") != frame.getLong("foreground_generation")
                || plan.getInt("source_width") != frame.getInt("source_width")
                || plan.getInt("source_height") != frame.getInt("source_height")) return "frame_metadata_mismatch";
        boolean nativePixels = "source_pixels".equals(frame.optString("coordinate_space"));
        if (nativePixels != "source_pixels".equals(plan.optString("coordinate_space"))) return "coordinate_space_mismatch";
        int width = nativePixels ? frame.getInt("width") : 1280;
        int height = nativePixels ? frame.getInt("height") : 720;
        if ((nativePixels ? !NativeFrameCoordinates.valid(width, height, frame.getInt("source_width"), frame.getInt("source_height"))
                : frame.getInt("width") != 1280 || frame.getInt("height") != 720)
                || !supportedFrame(frame.getInt("source_width"), frame.getInt("source_height"))) {
            return "unsupported_frame_size";
        }
        if (!GAME.equals(foreground) || generation != frame.getLong("foreground_generation")) return "foreground_changed";
        long age = now - frame.getLong("captured_elapsed_ms");
        if (age < 0 || age > FRAME_MAX_AGE_MS) return "frame_age_expired";
        String kind = plan.getString("kind");
        if (!("tap".equals(kind) || "drag".equals(kind))) return "unsupported_gesture";
        String context = plan.getString("context");
        if (!("deploy".equals(context) || "move_front".equals(context) || "attack_hq".equals(context)
                || "attack_unit".equals(context) || "end_turn".equals(context) || "choice_select".equals(context))) return "unsupported_action";
        if ("choice_select".equals(context)) {
            if (!nativePixels || !"tap".equals(kind)) return "choice_requires_native_tap";
            JSONArray boxes=plan.optJSONArray("choice_boxes");
            if (boxes==null || boxes.length()!=3) return "three_choice_bounds_unconfirmed";
            double previousRight=-1,firstY=-1,firstWidth=-1;
            for (int i=0;i<3;i++) {
                JSONArray box=boxes.optJSONArray(i);
                if (box==null || box.length()!=4) return "three_choice_bounds_unconfirmed";
                double x=box.getDouble(0),y=box.getDouble(1),bw=box.getDouble(2),bh=box.getDouble(3);
                if (!(x>0 && y>0 && x+bw<width && y+bh<height && bw>.35*height && bw<.48*height
                        && bh>.50*height && bh<.70*height)) return "three_choice_geometry";
                if (i>0 && (!(x-previousRight>.015*width && x-previousRight<.08*width)
                        || Math.abs(y-firstY)>=.025*height || Math.abs(bw-firstWidth)>=.10*firstWidth)) return "three_choice_alignment";
                if (i==0) {firstY=y;firstWidth=bw;}
                if (i==1 && (Math.abs(x+bw/2-width/2)>=.08*width
                        || Math.abs(plan.getJSONArray("from").getDouble(0)-(x+bw/2))>1
                        || Math.abs(plan.getJSONArray("from").getDouble(1)-(y+bh/2))>1)) return "three_choice_middle_target";
                previousRight=x+bw;
            }
        }
        if (!point(plan.getJSONArray("from"), width, height) || !point(plan.getJSONArray("to"), width, height)) return "invalid_coordinates";
        long duration = plan.getLong("duration_ms");
        if (duration < 40 || duration > 2500) return "invalid_duration";
        if ("tap".equals(kind) && !plan.getJSONArray("from").toString().equals(plan.getJSONArray("to").toString())) {
            return "tap_target_mismatch";
        }
        return validatePath(plan, frame);
    }

    static String validatePath(JSONObject plan) throws Exception {
        return validatePath(plan, null);
    }

    static String validatePath(JSONObject plan, JSONObject frame) throws Exception {
        boolean nativePixels = "source_pixels".equals(plan.optString("coordinate_space"));
        if (nativePixels && (frame == null || !"source_pixels".equals(frame.optString("coordinate_space"))
                || !NativeFrameCoordinates.valid(frame.getInt("width"), frame.getInt("height"),
                        frame.getInt("source_width"), frame.getInt("source_height")))) return "coordinate_space_mismatch";
        int width = nativePixels ? frame.getInt("width") : 1280;
        int height = nativePixels ? frame.getInt("height") : 720;
        double scale = height / 720.0;
        if (!"deploy".equals(plan.optString("context"))) {
            return plan.has("path_points") ? "path_points_outside_deployment" : null;
        }
        if (!"drag".equals(plan.optString("kind"))) return "invalid_deployment_path";
        if (!(plan.opt("duration_ms") instanceof Number) || plan.getDouble("duration_ms") != 900) {
            return "invalid_deployment_duration";
        }
        JSONArray from = plan.getJSONArray("from"), to = plan.getJSONArray("to");
        JSONArray points = plan.optJSONArray("path_points");
        if (from.getDouble(1) < 560 * scale || points == null || points.length() != 3) return "invalid_deployment_path";
        for (int i = 0; i < 3; i++) {
            JSONArray p = points.optJSONArray(i);
            if (p == null || !point(p, width, height)) return "invalid_deployment_path";
        }
        JSONArray lift = points.getJSONArray(1);
        if (!samePoint(points.getJSONArray(0), from) || !samePoint(points.getJSONArray(2), to)
                || lift.getDouble(0) != from.getDouble(0)
                || lift.getDouble(1) != Math.min(575 * scale, from.getDouble(1) - 60 * scale)) {
            return "invalid_deployment_path";
        }
        return null;
    }

    private static boolean samePoint(JSONArray a, JSONArray b) throws Exception {
        return a.getDouble(0) == b.getDouble(0) && a.getDouble(1) == b.getDouble(1);
    }

    static boolean supportedFrame(int width, int height) {
        return FrameAspectProfile.supported(width, height);
    }

    private static boolean point(JSONArray point) throws Exception {
        return point(point, 1280, 720);
    }

    private static boolean point(JSONArray point, int width, int height) throws Exception {
        return point.length() == 2 && point.opt(0) instanceof Number && point.opt(1) instanceof Number
                && Double.isFinite(point.getDouble(0)) && Double.isFinite(point.getDouble(1))
                && point.getDouble(0) > 0 && point.getDouble(0) < width
                && point.getDouble(1) > 0 && point.getDouble(1) < height;
    }
}
