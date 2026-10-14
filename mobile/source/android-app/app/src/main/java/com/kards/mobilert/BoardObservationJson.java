package com.kards.mobilert;

import android.graphics.Rect;

import java.util.Locale;

/**
 * Dependency-free serializer for Android board observation contract v1.
 * Unknown visual facts are emitted as unknown/null values; the read-only APK
 * never serializes an authorized action.
 */
public final class BoardObservationJson {
    private BoardObservationJson() { }

    /** Serialize a live frame with a single-sample (therefore unstable) mark. */
    public static String toJson(BoardObservation observation, FrameSnapshot frame,
                                long nowMillis) {
        BoardObservation safe = observation == null
                ? BoardObservation.unknown("观察为空") : observation;
        int width = frame == null ? 1280 : frame.width();
        int height = frame == null ? 720 : frame.height();
        int sourceWidth = frame == null ? 0 : frame.sourceWidth();
        int sourceHeight = frame == null ? 0 : frame.sourceHeight();
        long captured = frame == null ? Math.max(0L, nowMillis)
                : Math.max(0L, frame.capturedAtMillis());
        long age = frame == null ? 0L : Math.max(0L, nowMillis - captured);
        boolean rejected = width != 1280 || height != 720;
        BoardObservation contractSafe = rejected
                ? BoardObservation.unknown("核心帧尺寸未归一化为 1280×720") : safe;
        return build(contractSafe, null, sourceWidth, sourceHeight,
                rejected ? 1280 : width, rejected ? 720 : height,
                captured, age, rejected);
    }

    /** Serialize a decoded saved frame without retaining its Bitmap. */
    public static String replayJson(BoardObservation observation, String source,
                                    int sourceWidth, int sourceHeight,
                                    int normalizedWidth, int normalizedHeight) {
        BoardObservation safe = observation == null
                ? BoardObservation.unknown("回放未产生观测") : observation;
        long now = System.currentTimeMillis();
        int width = normalizedWidth > 0 ? normalizedWidth : 1280;
        int height = normalizedHeight > 0 ? normalizedHeight : 720;
        boolean rejected = width != 1280 || height != 720
                || normalizedWidth <= 0 || normalizedHeight <= 0;
        BoardObservation contractSafe = rejected
                ? BoardObservation.unknown("回放帧尺寸未归一化为 1280×720") : safe;
        return build(contractSafe, source, sourceWidth, sourceHeight,
                rejected ? 1280 : width, rejected ? 720 : height,
                now, 0L, rejected);
    }

    /** Legacy flat writer retained for callers outside the current replay path. */
    @Deprecated
    public static String encode(BoardObservation observation, String source,
                                int sourceWidth, int sourceHeight,
                                int normalizedWidth, int normalizedHeight) {
        BoardObservation safe = observation == null
                ? BoardObservation.unknown("回放未产生观测") : observation;
        StringBuilder out = new StringBuilder(512).append('{');
        field(out, "source", source == null ? "" : source);
        number(out, "sourceWidth", sourceWidth);
        number(out, "sourceHeight", sourceHeight);
        number(out, "normalizedWidth", normalizedWidth);
        number(out, "normalizedHeight", normalizedHeight);
        field(out, "state", safe.displayState());
        bool(out, "gameScreen", safe.isGameScreen());
        bool(out, "endTurnVisible", safe.isEndTurnVisible());
        field(out, "frontlineOwner", safe.frontlineOwner().name());
        bool(out, "actionAuthorized", false);
        field(out, "reason", safe.reason());
        out.append("\"candidates\":[");
        boolean first = true;
        for (BoardObservation.Candidate candidate : safe.candidates()) {
            if (!first) out.append(',');
            first = false;
            Rect r = candidate.bounds();
            out.append('{');
            field(out, "kind", candidate.kind().name());
            number(out, "confidencePermille", candidate.confidencePermille());
            number(out, "left", r.left);
            number(out, "top", r.top);
            number(out, "right", r.right);
            number(out, "bottom", r.bottom);
            trimComma(out).append('}');
        }
        out.append("]}");
        return out.toString();
    }

    private static String build(BoardObservation value, String source,
                                int sourceWidth, int sourceHeight,
                                int width, int height, long captured, long age,
                                boolean normalizationRejected) {
        StringBuilder out = new StringBuilder(2600).append('{');
        number(out, "schema_version", 1);
        field(out, "state", value.displayState());
        bool(out, "action_authorized", false);
        field(out, "reason", value.reason());
        out.append("\"frame\":{");
        number(out, "width", width);
        number(out, "height", height);
        number(out, "captured_at_ms", captured);
        number(out, "age_ms", age);
        nullableNumber(out, "source_width", sourceWidth);
        nullableNumber(out, "source_height", sourceHeight);
        trimComma(out).append("},");
        out.append("\"stability\":{");
        bool(out, "stable", false);
        number(out, "sample_count", 1);
        field(out, "transition_reason", "单帧观察，尚未完成连续稳定确认");
        out.append("\"motion_fraction\":null},");
        out.append("\"frontline\":{");
        field(out, "owner", frontlineName(value.frontlineOwner()));
        field(out, "reason", "当前适配器只输出前线几何候选，未确认归属");
        out.append("\"line_y\":null,\"line_score\":null,\"front_cards_confirmed\":null},");
        out.append("\"units\":[],\"enemy_support\":[],\"enemy_front\":[],");
        out.append("\"hq\":null,");
        out.append("\"guard\":{");
        field(out, "status", "unknown");
        bool(out, "complete", false);
        bool(out, "hq_guarded", false);
        out.append("\"hq_guards\":[],\"protected_units\":[]},");
        out.append("\"diagnostics\":{");
        bool(out, "game_screen", value.isGameScreen());
        bool(out, "end_turn_visible", value.isEndTurnVisible());
        number(out, "candidate_count", value.candidates().size());
        bool(out, "normalization_rejected", normalizationRejected);
        field(out, "executor_mode", "read_only");
        if (source != null) field(out, "source", source);
        out.append("\"candidates\":[");
        boolean first = true;
        for (BoardObservation.Candidate candidate : value.candidates()) {
            if (!first) out.append(',');
            first = false;
            out.append('{');
            field(out, "kind", candidate.kind().name());
            number(out, "confidence_permille", candidate.confidencePermille());
            out.append("\"bounds\":");
            appendGeometry(out, candidate.bounds());
            trimComma(out).append('}');
        }
        out.append("]}");
        trimComma(out).append('}');
        return out.toString();
    }

    private static String frontlineName(BoardObservation.FrontlineOwner owner) {
        if (owner == null) return "unknown";
        switch (owner) {
            case MINE: return "our";
            case OPPONENT: return "enemy";
            case EMPTY: return "empty";
            default: return "unknown";
        }
    }

    private static void appendGeometry(StringBuilder out, Rect rect) {
        Rect r = rect == null ? new Rect() : rect;
        int left = Math.max(0, Math.min(1280, r.left));
        int top = Math.max(0, Math.min(720, r.top));
        int width = Math.max(0, Math.min(1280, r.width()));
        int height = Math.max(0, Math.min(720, r.height()));
        out.append('{');
        number(out, "x", left);
        number(out, "y", top);
        number(out, "w", width);
        number(out, "h", height);
        number(out, "cx", Math.min(1280, left + width / 2));
        number(out, "cy", Math.min(720, top + height / 2));
        trimComma(out).append('}');
    }

    private static StringBuilder field(StringBuilder out, String key, String value) {
        out.append(quote(key)).append(':').append(quote(value)).append(',');
        return out;
    }

    private static StringBuilder number(StringBuilder out, String key, long value) {
        out.append(quote(key)).append(':').append(value).append(',');
        return out;
    }

    private static StringBuilder nullableNumber(StringBuilder out, String key, int value) {
        out.append(quote(key)).append(':')
                .append(value > 0 ? Integer.toString(value) : "null").append(',');
        return out;
    }

    private static StringBuilder bool(StringBuilder out, String key, boolean value) {
        out.append(quote(key)).append(':').append(value ? "true" : "false").append(',');
        return out;
    }

    private static StringBuilder trimComma(StringBuilder out) {
        if (out.length() > 0 && out.charAt(out.length() - 1) == ',') out.setLength(out.length() - 1);
        return out;
    }

    private static String quote(String value) {
        if (value == null) return "null";
        StringBuilder out = new StringBuilder(value.length() + 2).append('"');
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            switch (c) {
                case '\\': out.append("\\\\"); break;
                case '"': out.append("\\\""); break;
                case '\n': out.append("\\n"); break;
                case '\r': out.append("\\r"); break;
                case '\t': out.append("\\t"); break;
                default:
                    if (c < 0x20) out.append(String.format(Locale.ROOT, "\\u%04x", (int) c));
                    else out.append(c);
            }
        }
        return out.append('"').toString();
    }
}
