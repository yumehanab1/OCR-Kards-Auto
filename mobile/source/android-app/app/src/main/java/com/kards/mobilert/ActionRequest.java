package com.kards.mobilert;

/**
 * A normalized input request for the future combat executor.
 *
 * <p>The request is only data.  Constructing one never touches the screen;
 * the current APK deliberately has no implementation that can execute it.</p>
 */
public final class ActionRequest {
    public enum Kind { TAP, SWIPE }

    private final Kind kind;
    private final float x;
    private final float y;
    private final float endX;
    private final float endY;
    private final long durationMillis;

    private ActionRequest(Kind kind, float x, float y, float endX, float endY,
                          long durationMillis) {
        this.kind = kind;
        this.x = x;
        this.y = y;
        this.endX = endX;
        this.endY = endY;
        this.durationMillis = durationMillis;
    }

    public static ActionRequest tap(float x, float y) {
        return create(Kind.TAP, x, y, x, y, 0L);
    }

    public static ActionRequest swipe(float x, float y, float endX, float endY,
                                      long durationMillis) {
        if (durationMillis < 1L || durationMillis > 10_000L) {
            throw new IllegalArgumentException("durationMillis out of range");
        }
        return create(Kind.SWIPE, x, y, endX, endY, durationMillis);
    }

    private static ActionRequest create(Kind kind, float x, float y, float endX,
                                        float endY, long durationMillis) {
        if (kind == null || !finite(x) || !finite(y) || !finite(endX) || !finite(endY)
                || x < 0f || y < 0f || endX < 0f || endY < 0f) {
            throw new IllegalArgumentException("invalid gesture coordinates");
        }
        return new ActionRequest(kind, x, y, endX, endY, durationMillis);
    }

    private static boolean finite(float value) {
        return !Float.isNaN(value) && !Float.isInfinite(value);
    }

    public Kind kind() { return kind; }
    public float x() { return x; }
    public float y() { return y; }
    public float endX() { return endX; }
    public float endY() { return endY; }
    public long durationMillis() { return durationMillis; }
}
