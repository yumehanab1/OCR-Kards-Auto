package com.kards.mobilert;

import org.json.JSONArray;
import org.json.JSONObject;

/** Final menu tap boundary. It cannot authorize a battle action or retry a consumed frame. */
final class MenuDispatchGuard {
    static final int MAX_INPUTS = 16;

    private MenuDispatchGuard() { }

    static String validate(JSONObject plan, JSONObject frame, long consumedFrame,
                           boolean cancelled, boolean readOnly, long now, long deadline,
                           int inputs, String stage, String mode, String foreground,
                           long generation) throws Exception {
        if (cancelled) return "cancelled";
        if (readOnly) return "read_only";
        if (!"menu".equals(stage)) return "not_menu_stage";
        if (!(MatchEntryOptions.CASUAL.equals(mode) || MatchEntryOptions.RANKED.equals(mode))
                || !mode.equals(plan.opt("mode"))) return "menu_mode_mismatch";
        if (now >= deadline) return "time_budget";
        if (deadline - now < 8000) return "insufficient_verification_budget";
        if (inputs >= (frame != null && "source_pixels".equals(frame.optString("coordinate_space")) ? 32 : MAX_INPUTS)) return "menu_input_budget";
        if (frame == null || !sameNumber(plan, frame, "frame_id")
                || consumedFrame == frame.optLong("frame_id", -1)) return "stale_or_consumed_frame";
        for (String key : new String[]{"captured_elapsed_ms", "foreground_generation", "source_width", "source_height"}) {
            if (!sameNumber(plan, frame, key)) return "frame_metadata_mismatch";
        }
        boolean nativePixels = "source_pixels".equals(frame.optString("coordinate_space"));
        if ((nativePixels
                ? !NativeFrameCoordinates.valid(frame.optInt("width"), frame.optInt("height"),
                        frame.optInt("source_width"), frame.optInt("source_height"))
                : frame.optInt("width") != 1280 || frame.optInt("height") != 720)
                || !BattleDispatchGuard.supportedFrame(frame.optInt("source_width"), frame.optInt("source_height"))) {
            return "unsupported_frame_size";
        }
        if (!GamePackages.isGame(foreground) || generation != frame.getLong("foreground_generation")) return "foreground_changed";
        long age = now - frame.getLong("captured_elapsed_ms");
        if (age < 0 || age > (nativePixels ? 5000 : BattleDispatchGuard.FRAME_MAX_AGE_MS)) return "frame_age_expired";
        if (!"tap".equals(plan.opt("kind"))) return "menu_tap_required";
        if (nativePixels != "source_pixels".equals(plan.optString("coordinate_space")))
            return "coordinate_space_mismatch";
        if (!(plan.opt("duration_ms") instanceof Number) || plan.getDouble("duration_ms") != 60) {
            return "invalid_menu_duration";
        }
        if (plan.has("path_points")) return "menu_path_forbidden";
        String state = plan.optString("state", ""), context = plan.optString("context", "");
        if (!allowed(state, context)) return "unsupported_menu_action";
        // Every request states this session's verified deck selection explicitly.
        // Other menu actions may use false, but string/number truthiness never grants input.
        if (!(plan.opt("first_deck_selected") instanceof Boolean)) return "invalid_first_deck_selected";
        if (("menu_select_casual".equals(context) || "menu_select_ranked".equals(context)
                || "menu_start_queue".equals(context))
                && !Boolean.TRUE.equals(plan.opt("first_deck_selected"))) return "first_deck_not_verified";
        if (("menu_select_casual".equals(context) && !MatchEntryOptions.CASUAL.equals(mode))
                || ("menu_select_ranked".equals(context) && !MatchEntryOptions.RANKED.equals(mode))) {
            return "menu_mode_mismatch";
        }
        if ("menu_start_queue".equals(context) && !mode.equals(plan.opt("selected_mode"))) {
            return "queue_mode_not_verified";
        }
        JSONArray from = plan.optJSONArray("from"), to = plan.optJSONArray("to");
        int width = nativePixels ? frame.getInt("width") : 1280;
        int height = nativePixels ? frame.getInt("height") : 720;
        if (!point(from, width, height) || !point(to, width, height)) return "invalid_coordinates";
        if (from.getDouble(0) != to.getDouble(0) || from.getDouble(1) != to.getDouble(1)) return "tap_target_mismatch";
        JSONArray bounds = plan.optJSONArray("target_bounds");
        if (bounds == null || bounds.length() != 4) return "invalid_target_bounds";
        for (int i = 0; i < 4; i++) if (!finite(bounds.opt(i))) return "invalid_target_bounds";
        double x = bounds.getDouble(0), y = bounds.getDouble(1), w = bounds.getDouble(2), h = bounds.getDouble(3);
        double frameWidth = nativePixels ? frame.getDouble("width") : 1280;
        double frameHeight = nativePixels ? frame.getDouble("height") : 720;
        if (x < 0 || y < 0 || w <= 0 || h <= 0 || x + w > frameWidth || y + h > frameHeight) return "invalid_target_bounds";
        if ("menu_startup_cleanup".equals(context)) {
            if (!nativePixels || !Boolean.TRUE.equals(plan.opt("startup_cleanup"))
                    || !Boolean.FALSE.equals(plan.opt("queue_requested"))) return "startup_cleanup_scope_required";
            Object attempts=plan.opt("startup_cleanup_attempts");
            if (!finite(attempts) || ((Number)attempts).doubleValue()!=((Number)attempts).intValue()
                    || ((Number)attempts).intValue()<0 || ((Number)attempts).intValue()>=15)
                return "startup_cleanup_exhausted";
            double size=Math.max(8,Math.round(frameHeight*24/720.0));
            double cx=frameWidth/2.0,cy=Math.round(frameHeight*665/720.0);
            if (Math.abs(x-(cx-size/2))>.5 || Math.abs(y-(cy-size/2))>.5 || w!=size || h!=size)
                return "popup_blank_bounds_mismatch";
        }
        if ("menu_clear_login_popup".equals(context)) {
            if (!nativePixels) return "popup_requires_source_pixels";
            JSONObject proof=plan.optJSONObject("login_popup_evidence");
            JSONArray buttons=proof==null?null:proof.optJSONArray("buttons");
            boolean semantic=proof!=null && "current_daily_title_and_buttons".equals(proof.optString("basis"));
            double minimum=semantic ? .90 : .94;
            if(proof==null || !finite(proof.opt("title_score")) || proof.getDouble("title_score")<minimum || proof.getDouble("title_score")>1
                    || !semantic && (!finite(proof.opt("blank_score")) || proof.getDouble("blank_score")<.94 || proof.getDouble("blank_score")>1)
                    || buttons==null || buttons.length()<1 || buttons.length()>3) return "login_popup_unverified";
            for(int i=0;i<buttons.length();i++) {
                JSONObject button=buttons.getJSONObject(i);
                JSONArray box=button.optJSONArray("bounds");
                if(!finite(button.opt("score")) || button.getDouble("score")<minimum || button.getDouble("score")>1
                        || box==null || box.length()!=4) return "login_popup_unverified";
                for(int j=0;j<4;j++) if(!finite(box.opt(j))) return "login_popup_unverified";
                if(!semantic && box.getDouble(1)+box.getDouble(3)+frameHeight*.08>y+h/2)
                    return "login_popup_unverified";
                if(semantic && Math.min(x+w,box.getDouble(0)+box.getDouble(2))>Math.max(x,box.getDouble(0))
                        && Math.min(y+h,box.getDouble(1)+box.getDouble(3))>Math.max(y,box.getDouble(1)))
                    return "login_popup_unverified";
            }
            double size=Math.max(8,Math.round(frameHeight*24/720.0));
            double cx=frameWidth/2.0,cy=Math.round(frameHeight*665/720.0);
            if(Math.abs(x-(cx-size/2))>.5 || Math.abs(y-(cy-size/2))>.5 || w!=size || h!=size)
                return "popup_blank_bounds_mismatch";
        }
        if ("menu_dismiss_generic".equals(context)) {
            if (!nativePixels) return "popup_requires_source_pixels";
            JSONObject evidence=plan.optJSONObject("generic_popup_evidence");
            if (evidence==null) return "generic_popup_unverified";
            JSONArray panel=evidence.optJSONArray("panel_bounds"),edges=evidence.optJSONArray("edge_coverage");
            JSONObject close=evidence.optJSONObject("close");
            boolean currentShape="current_close_x_geometry".equals(evidence.optString("basis"));
            if (panel==null || panel.length()!=4 || edges==null || edges.length()!=4 || close==null
                    || !finite(close.opt("score")) || close.getDouble("score")<0 || close.getDouble("score")>1
                    || !currentShape && close.getDouble("score")<.93
                    || evidence.optString("popup_id").length()!=64) return "generic_popup_unverified";
            for (int i=0;i<4;i++) if (!finite(panel.opt(i)) || !finite(edges.opt(i))
                    || edges.getDouble(i)<0 || edges.getDouble(i)>1
                    || !currentShape && edges.getDouble(i)<.93) return "generic_popup_unverified";
            double px=panel.getDouble(0),py=panel.getDouble(1),pw=panel.getDouble(2),ph=panel.getDouble(3);
            if (px<0 || py<0 || px+pw>frameWidth || py+ph>frameHeight
                    || pw<=0 || ph<=0
                    || !currentShape && (pw<=frameWidth*.30 || pw>=frameWidth*.70 || ph<=frameHeight*.25 || ph>=frameHeight*.75
                        || Math.abs(px+pw/2-frameWidth/2)>frameWidth*.08)
                    || x<px+pw*(currentShape ? .75 : .88)-1 || x+w>px+pw || y<py
                    || y+h>py+ph*(currentShape ? .25 : .18)+1)
                return "generic_popup_bounds_mismatch";
            JSONArray measured=close.optJSONArray("bounds");
            if (measured==null || measured.length()!=4) return "generic_popup_unverified";
            for (int i=0;i<4;i++) if (!finite(measured.opt(i)) || measured.getDouble(i)!=bounds.getDouble(i))
                return "generic_popup_bounds_mismatch";
        }
        if ("menu_dismiss_blocking_popup".equals(context)
                || nativePixels && ("menu_dismiss_pass".equals(context)
                    || "menu_dismiss_weekend".equals(context) && "weekend_title_subtitle_and_panel".equals(plan.optString("popup_basis")))) {
            if (!nativePixels) return "popup_requires_source_pixels";
            double size = Math.max(8, Math.round(frameHeight * 24 / 720.0));
            double cx = frameWidth / 2.0, cy = Math.round(frameHeight * 665 / 720.0);
            if (Math.abs(x - (cx - size / 2)) > .5 || Math.abs(y - (cy - size / 2)) > .5
                    || w != size || h != size) return "popup_blank_bounds_mismatch";
            if (!("task_title_and_subtitle".equals(plan.optString("popup_basis"))
                    || "current_offer_title_subtitle_price".equals(plan.optString("popup_basis"))
                    || "pass_title_subtitle_and_panel".equals(plan.optString("popup_basis"))
                    || "weekend_title_subtitle_and_panel".equals(plan.optString("popup_basis"))))
                return "popup_evidence_missing";
        }
        // These startup offers expose one measured white X. Even a malformed
        // named request cannot substitute the offer body/price as its target.
        if (nativePixels && ("menu_dismiss_airdrop".equals(context) || "menu_dismiss_starter".equals(context)
                || "menu_dismiss_weekend".equals(context) && !"weekend_title_subtitle_and_panel".equals(plan.optString("popup_basis")))) {
            JSONObject evidence = plan.optJSONObject("promotion_evidence");
            if (evidence == null) return "native_promotion_close_unverified";
            double[] min = {Double.POSITIVE_INFINITY, Double.POSITIVE_INFINITY};
            double[] max = {Double.NEGATIVE_INFINITY, Double.NEGATIVE_INFINITY};
            for (String anchor : new String[]{"title", "close", "edge_top", "edge_bottom", "edge_left", "edge_right"}) {
                JSONObject item = evidence.optJSONObject(anchor);
                if (item == null || !finite(item.opt("score")) || item.getDouble("score") < .93)
                    return "native_promotion_close_unverified";
                JSONArray offset = item.optJSONArray("offset"), box = item.optJSONArray("bounds");
                if (offset == null || offset.length()!=2 || box == null || box.length()!=4)
                    return "native_promotion_close_unverified";
                for (int axis=0;axis<2;axis++) {
                    if (!finite(offset.opt(axis))) return "native_promotion_close_unverified";
                    min[axis]=Math.min(min[axis],offset.getDouble(axis));
                    max[axis]=Math.max(max[axis],offset.getDouble(axis));
                }
                for (int i=0;i<4;i++) if (!finite(box.opt(i))) return "native_promotion_close_unverified";
                if ("close".equals(anchor)) for (int i=0;i<4;i++)
                    if (box.getDouble(i)!=bounds.getDouble(i)) return "promotion_close_bounds_mismatch";
            }
            if (max[0]-min[0]>3 || max[1]-min[1]>3) return "native_promotion_close_unverified";
            JSONArray top=evidence.getJSONObject("edge_top").getJSONArray("bounds"),
                    bottom=evidence.getJSONObject("edge_bottom").getJSONArray("bounds");
            if (x<top.getDouble(0)+top.getDouble(2)*.9 || x+w>top.getDouble(0)+top.getDouble(2)+8
                    || y<top.getDouble(1) || y+h>top.getDouble(1)+(bottom.getDouble(1)-top.getDouble(1))*.2)
                return "promotion_close_bounds_mismatch";
        }
        if (!nativePixels && ("menu_dismiss_airdrop".equals(context) || "menu_dismiss_starter".equals(context)
                || "menu_dismiss_weekend".equals(context))
                && (Math.abs(x - 938) > 3 || Math.abs(y - 202) > 3 || w != 25 || h != 25)) {
            return "promotion_close_bounds_mismatch";
        }
        // Half-pixel tolerance permits integer rounding of an odd-sized observed target.
        if (Math.abs(from.getDouble(0) - (x + w / 2)) > .5
                || Math.abs(from.getDouble(1) - (y + h / 2)) > .5) return "tap_outside_target_center";
        return null;
    }

    private static boolean allowed(String state, String action) {
        switch (state) {
            case "unknown": return "menu_startup_cleanup".equals(action);
            case "home": return "menu_home_start".equals(action);
            case "mode_menu": return "menu_battle_mode".equals(action);
            case "deck_list": return "menu_select_deck".equals(action);
            case "deck_ready": return "menu_select_casual".equals(action) || "menu_select_ranked".equals(action)
                    || "menu_start_queue".equals(action) || "menu_close_deck".equals(action);
            case "login_reward": return "menu_dismiss_reward".equals(action);
            case "task_popup": return "menu_dismiss_task".equals(action);
            case "blocking_popup": return "menu_dismiss_blocking_popup".equals(action);
            case "login_popup_cleanup": return "menu_clear_login_popup".equals(action);
            case "generic_popup": return "menu_dismiss_generic".equals(action);
            case "pass_popup": return "menu_dismiss_pass".equals(action);
            case "box_popup": return "menu_dismiss_box".equals(action);
            case "store_popup": return "menu_dismiss_store".equals(action);
            case "airdrop_popup": return "menu_dismiss_airdrop".equals(action);
            case "starter_popup": return "menu_dismiss_starter".equals(action);
            case "weekend_popup": return "menu_dismiss_weekend".equals(action);
            case "disconnected": return "menu_reconnect".equals(action);
            default: return false;
        }
    }

    private static boolean finite(Object value) {
        return value instanceof Number && Double.isFinite(((Number) value).doubleValue());
    }

    private static boolean sameNumber(JSONObject a, JSONObject b, String key) {
        Object left = a.opt(key), right = b.opt(key);
        return finite(left) && finite(right) && ((Number) left).doubleValue() == ((Number) right).doubleValue();
    }

    private static boolean point(JSONArray point, int width, int height) throws Exception {
        return point != null && point.length() == 2 && finite(point.opt(0)) && finite(point.opt(1))
                && point.getDouble(0) > 0 && point.getDouble(0) < width
                && point.getDouble(1) > 0 && point.getDouble(1) < height;
    }
}
