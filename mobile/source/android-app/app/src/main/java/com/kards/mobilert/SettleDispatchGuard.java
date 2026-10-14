package com.kards.mobilert;

import org.json.JSONArray;
import org.json.JSONObject;

/** Final boundary for post-match settlement taps.
 *
 * Settlement only exists to leave a result/tail screen, so it may not use any
 * battle or menu authority: it is enabled only after a verified result, accepts
 * a single short tap, and refuses points that overlap a live control. It cannot
 * retry a consumed frame, and it shares the campaign deadline and foreground
 * admission with the rest of the session.
 */
final class SettleDispatchGuard {
    /** Dismissal budget: how many arbitrary taps may be spent leaving the
     *  result and tail pages. Must equal `apk_settle.MAX_CLICKS`. */
    static final int MAX_CLICKS = 15;
    /** Return budget: how many taps the start-button step may spend bringing the
     *  game back to the start page. Must equal `apk_settle.RETURN_MAX_CLICKS`. */
    static final int RETURN_MAX_CLICKS = 3;
    /** The most taps one post-match phase can spend in total. The guard is the
     *  outer bound for the session, so it admits both phases and nothing more;
     *  each phase still keeps its own smaller budget inside the module. */
    static final int TOTAL_MAX_CLICKS = MAX_CLICKS + RETURN_MAX_CLICKS;
    static final long TAP_DURATION_MS = 60;
    /** The start page's own 开始 button, centre in normalised 1280x720 frame
     *  space. This is the one control the return step presses, and it presses
     *  only after the recogniser has reported that the button is drawn on the
     *  frame that authorises the tap. Must equal `apk_settle.START_BUTTON`. */
    static final int[] START_BUTTON = {59, 147};
    /** Reviewed settlement candidates in normalised 1280x720 frame space.
     *
     *  Every point must be inert on the screen the game returns to, because
     *  settlement's purpose is to leave the game on the start page so a
     *  campaign can run again. Measured on the real start page:
     *    开始 (59,147)  卡牌 (41,234)  商店 (41,320)  军需箱 (334,590)
     *    任务 (578,590)  打开卡包 (1180,584)  Bilibili (1180,197)  竞技场 (1180,357)
     *  An earlier list included (59,147) as a "safe start-button slot"; on the
     *  start page that is the 开始 button, and a live run was carried off to the
     *  card-collection screen by it. The bottom Continue point (640,665) closed
     *  both the post-victory quest page and the task popup in recorded tests.
     *
     *  Kept here, next to the boundary that enforces them, so the guard can be
     *  exercised on a host JVM without the Android build. */
    static final int[][] DEFAULT_POINTS = {
            {640, 665}, {400, 501}, {880, 501}, {153, 633}, {1126, 633}};
    private static final String GAME = "com.android1939.kards";

    private SettleDispatchGuard() { }

    /** Parse a caller-supplied point list, falling back to the reviewed set.
     *
     *  A malformed option can never produce a stray tap: anything unusable
     *  yields the reviewed defaults instead. */
    static int[][] parsePoints(org.json.JSONArray supplied) {
        if (supplied == null || supplied.length() == 0) return DEFAULT_POINTS;
        int[][] points = new int[supplied.length()][];
        for (int i = 0; i < supplied.length(); i++) {
            org.json.JSONArray pair = supplied.optJSONArray(i);
            if (pair == null || pair.length() != 2) return DEFAULT_POINTS;
            int x = pair.optInt(0, -1), y = pair.optInt(1, -1);
            if (x <= 0 || x >= 1280 || y <= 0 || y >= 720) return DEFAULT_POINTS;
            points[i] = new int[]{x, y};
        }
        return points;
    }

    static String validate(JSONObject plan, JSONObject frame, long consumedFrame,
                           boolean cancelled, boolean readOnly, long now, long deadline,
                           int clicks, int maxClicks, int[][] occupied,
                           String foreground, long generation) throws Exception {
        if (cancelled) return "cancelled";
        if (readOnly) return "read_only";
        if (now >= deadline) return "time_budget";
        if (clicks >= maxClicks) return "settle_click_budget";
        if (frame == null || !sameNumber(plan, frame, "frame_id")
                || consumedFrame == frame.optLong("frame_id", -1)) return "stale_or_consumed_frame";
        for (String key : new String[]{"captured_elapsed_ms", "foreground_generation",
                "source_width", "source_height"}) {
            if (!sameNumber(plan, frame, key)) return "frame_metadata_mismatch";
        }
        boolean nativePixels = "source_pixels".equals(frame.optString("coordinate_space"));
        if ((nativePixels
                ? !NativeFrameCoordinates.valid(frame.optInt("width"), frame.optInt("height"),
                        frame.optInt("source_width"), frame.optInt("source_height"))
                : frame.optInt("width") != 1280 || frame.optInt("height") != 720)
                || !BattleDispatchGuard.supportedFrame(frame.optInt("source_width"),
                                                       frame.optInt("source_height"))) {
            return "unsupported_frame_size";
        }
        if (!GAME.equals(foreground) || generation != frame.getLong("foreground_generation")) {
            return "foreground_changed";
        }
        long age = now - frame.getLong("captured_elapsed_ms");
        if (age < 0 || age > BattleDispatchGuard.FRAME_MAX_AGE_MS) return "frame_age_expired";
        if (!"settle".equals(plan.optString("context"))) return "unsupported_settle_action";
        if (nativePixels != "source_pixels".equals(plan.optString("coordinate_space")))
            return "coordinate_space_mismatch";
        if (!"tap".equals(plan.optString("kind"))) return "settle_tap_required";
        if (!(plan.opt("duration_ms") instanceof Number)
                || plan.getDouble("duration_ms") != TAP_DURATION_MS) return "invalid_settle_duration";
        if (plan.has("path_points")) return "settle_path_forbidden";
        JSONArray from = plan.optJSONArray("from"), to = plan.optJSONArray("to");
        int width = nativePixels ? frame.getInt("width") : 1280;
        int height = nativePixels ? frame.getInt("height") : 720;
        if (!point(from, width, height) || !point(to, width, height)) return "invalid_coordinates";
        if (from.getDouble(0) != to.getDouble(0) || from.getDouble(1) != to.getDouble(1)) {
            return "tap_target_mismatch";
        }
        // A settlement tap is arbitrary, but it must not land on a control the
        // session knows about (the end-turn button is observer-confirmed live).
        for (int[] box : occupied) {
            if (box == null || box.length != 4) continue;
            double x = from.getDouble(0), y = from.getDouble(1);
            if (x >= box[0] - 8 && x <= box[2] + 8 && y >= box[1] - 8 && y <= box[3] + 8) {
                return "settle_point_on_live_control";
            }
        }
        return null;
    }

    private static boolean point(JSONArray value, int width, int height) throws Exception {
        if (value == null || value.length() != 2) return false;
        for (int i = 0; i < 2; i++) {
            Object item = value.opt(i);
            if (!(item instanceof Number) || !Double.isFinite(((Number) item).doubleValue())) return false;
        }
        double x = value.getDouble(0), y = value.getDouble(1);
        return x > 0 && x < width && y > 0 && y < height;
    }

    private static boolean sameNumber(JSONObject a, JSONObject b, String key) {
        Object left = a.opt(key), right = b.opt(key);
        return left instanceof Number && right instanceof Number
                && Double.isFinite(((Number) left).doubleValue())
                && ((Number) left).doubleValue() == ((Number) right).doubleValue();
    }
}
