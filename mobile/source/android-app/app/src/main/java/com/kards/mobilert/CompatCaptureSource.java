package com.kards.mobilert;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.PixelFormat;
import android.graphics.Rect;
import android.hardware.display.DisplayManager;
import android.hardware.display.VirtualDisplay;
import android.media.Image;
import android.media.ImageReader;
import android.media.projection.MediaProjection;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.Looper;
import android.os.SystemClock;
import android.util.DisplayMetrics;
import android.util.Log;
import android.view.WindowManager;

import org.json.JSONArray;
import org.json.JSONObject;

import java.nio.ByteBuffer;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;

/** A consent-owned, read-only display source. It never returns a cached frame. */
final class CompatCaptureSource {
    private static final long REQUEST_TIMEOUT_MS = 1500L;
    private static final AtomicLong REQUEST_IDS = new AtomicLong();

    interface StopListener {
        void onStopped(CompatCaptureSource source, String reason);
    }

    private final Context context;
    private final MediaProjection projection;
    private final StopListener stopListener;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final HandlerThread thread = new HandlerThread("kards-compat-capture");
    private final Handler capture;
    private final AtomicBoolean closed = new AtomicBoolean();
    private final AtomicReference<Request> inFlight = new AtomicReference<>();
    private volatile boolean ready;
    private volatile String state = "兼容截图初始化中（compat_capture_initializing）";
    private ImageReader reader;
    private VirtualDisplay display;
    private DisplaySpec size;

    private final MediaProjection.Callback projectionCallback = new MediaProjection.Callback() {
        @Override public void onStop() {
            close("屏幕共享已停止，请重新授权（compat_capture_revoked）");
        }
    };

    CompatCaptureSource(Context context, MediaProjection projection, StopListener stopListener) {
        this.context = context.getApplicationContext();
        this.projection = projection;
        this.stopListener = stopListener;
        thread.start();
        capture = new Handler(thread.getLooper());
        capture.post(this::initialize);
    }

    boolean isReady() {
        return ready && !closed.get();
    }

    String status() {
        return state;
    }

    /** The original caller's wall-clock request time remains the frame age bound. */
    void requestFrame(FrameSource.Callback callback, long requestedAtMillis) {
        if (callback == null) return;
        if (!isReady()) {
            failOnMain(callback, state);
            return;
        }
        Request request = new Request(callback, requestedAtMillis);
        if (!inFlight.compareAndSet(null, request)) {
            failOnMain(callback, "兼容截图已有请求（compat_capture_busy）");
            return;
        }
        if (!capture.post(() -> begin(request))) {
            finishFailure(request, "兼容截图已关闭（compat_capture_closed）");
        }
    }

    void close(String reason) {
        if (!closed.compareAndSet(false, true)) return;
        ready = false;
        state = reason;
        if (Looper.myLooper() == capture.getLooper()) release();
        else capture.post(this::release);
    }

    private void initialize() {
        if (closed.get()) return;
        try {
            size = readDisplay();
            projection.registerCallback(projectionCallback, capture);
            reader = ImageReader.newInstance(size.width, size.height, PixelFormat.RGBA_8888, 3);
            reader.setOnImageAvailableListener(this::imageAvailable, capture);
            // Keep the surface detached while idle. Each request starts a fresh mirror delivery.
            display = projection.createVirtualDisplay("KARDS compatible capture", size.width,
                    size.height, size.densityDpi, DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                    null, new VirtualDisplay.Callback() {
                        @Override public void onStopped() {
                            close("兼容截图显示已停止（compat_capture_display_stopped）");
                        }
                    }, capture);
            if (display == null) throw new IllegalStateException("virtual_display_null");
            ready = true;
            state = "兼容截图已就绪（media_projection）";
        } catch (RuntimeException error) {
            close("兼容截图初始化失败（compat_capture_init_" + error.getClass().getSimpleName() + "）");
        }
    }

    private void begin(Request request) {
        logTiming(request, "begin", 0L);
        if (closed.get() || !ready) {
            finishFailure(request, state);
            return;
        }
        if (SystemClock.uptimeMillis() >= request.deadlineUptime) {
            finishFailure(request, "兼容截图等待超时（compat_capture_timeout）");
            return;
        }
        try {
            if (!size.sameGeometry(readDisplay())) {
                close("屏幕尺寸已变化，请重新授权兼容截图（compat_capture_geometry_changed）");
                return;
            }
            display.setSurface(null);
            drainImages();
            // ImageReader's MediaProjection timestamps use the monotonic nanosecond clock.
            // Set this only after old images have been drained and before reattaching the surface.
            request.freshAfterNanos = System.nanoTime();
            request.timeout = () -> finishFailure(request,
                    "兼容截图等待新帧超时（compat_capture_timeout）");
            capture.postDelayed(request.timeout,
                    Math.max(0L, request.deadlineUptime - SystemClock.uptimeMillis()));
            display.setSurface(reader.getSurface());
        } catch (RuntimeException error) {
            finishFailure(request, "兼容截图请求失败（compat_capture_request_"
                    + error.getClass().getSimpleName() + "）");
        }
    }

    private void imageAvailable(ImageReader source) {
        Bitmap pixels = null;
        try (Image image = source.acquireLatestImage()) {
            if (image == null) return;
            Request request = inFlight.get();
            if (closed.get() || request == null || request.finished.get()) return;
            if (request.freshAfterNanos == 0L || image.getTimestamp() <= request.freshAfterNanos) return;
            long imageArrivedAt = SystemClock.uptimeMillis();
            logTiming(request, "image_arrived", 0L);
            if (image.getTimestamp() > System.nanoTime() + 100_000_000L) {
                finishFailure(request, "兼容截图时间戳无法确认（compat_capture_timestamp_unconfirmed）");
                return;
            }
            if (SystemClock.uptimeMillis() >= request.deadlineUptime) {
                finishFailure(request, "兼容截图等待新帧超时（compat_capture_timeout）");
                return;
            }
            if (!size.sameGeometry(readDisplay()) || image.getWidth() != size.width
                    || image.getHeight() != size.height
                    || !image.getCropRect().equals(new Rect(0, 0, size.width, size.height))) {
                close("屏幕尺寸已变化，请重新授权兼容截图（compat_capture_geometry_changed）");
                return;
            }
            long copyStartedAt = SystemClock.uptimeMillis();
            pixels = copyRgba(image, size.width, size.height);
            long copyCompletedAt = SystemClock.uptimeMillis();
            logTiming(request, "copy_complete", copyCompletedAt - copyStartedAt);
            // Reject on the capture thread while both the Image metadata and copied alpha exist.
            // The accessibility-service gate remains an independent final check.
            if (!CapturePixelQuality.isFullyOpaque(pixels)) {
                Bitmap rejectedCopy = pixels;
                pixels = null; // The audit path consumes ownership, including metadata/queue failures.
                auditRejectedCopy(request, image, rejectedCopy, imageArrivedAt, copyStartedAt, copyCompletedAt);
                finishFailure(request, "compat_capture_incomplete_frame");
                return;
            }
            if (SystemClock.uptimeMillis() >= request.deadlineUptime) {
                pixels.recycle();
                pixels = null;
                finishFailure(request, "兼容截图转换超时（compat_capture_timeout）");
                return;
            }
            FrameSnapshot snapshot = new FrameSnapshot(pixels, request.requestedAtMillis,
                    size.width, size.height, "media_projection", -1,
                    new Rect(0, 0, size.width, size.height));
            pixels = null; // Snapshot ownership transfers to the callback (or its cancellation path).
            finishFrame(request, snapshot);
        } catch (RuntimeException error) {
            Request request = inFlight.get();
            if (request != null) finishFailure(request, "兼容截图读取失败（compat_capture_image_"
                    + error.getClass().getSimpleName() + "）");
        } finally {
            if (pixels != null && !pixels.isRecycled()) pixels.recycle();
        }
    }

    private void auditRejectedCopy(Request request, Image image, Bitmap pixels,
                                   long imageArrivedAt, long copyStartedAt, long copyCompletedAt) {
        // Building or saving debug evidence can fail without affecting the rejection decision.
        try {
            if ((context.getApplicationInfo().flags
                    & android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) == 0) return;
            JSONArray planes = new JSONArray();
            for (Image.Plane plane : image.getPlanes()) {
                ByteBuffer buffer = plane.getBuffer();
                planes.put(new JSONObject().put("pixel_stride", plane.getPixelStride())
                        .put("row_stride", plane.getRowStride())
                        .put("buffer_position", buffer.position()).put("buffer_limit", buffer.limit())
                        .put("buffer_capacity", buffer.capacity()).put("buffer_remaining", buffer.remaining())
                        .put("buffer_order", buffer.order().toString()));
            }
            Rect crop = image.getCropRect();
            JSONObject details = new JSONObject()
                    .put("requested_at_wall_ms", request.requestedAtMillis)
                    .put("request_started_uptime_ms", request.startedUptime)
                    .put("request_deadline_uptime_ms", request.deadlineUptime)
                    .put("fresh_after_nanos", request.freshAfterNanos)
                    .put("image_arrived_uptime_ms", imageArrivedAt)
                    .put("copy_started_uptime_ms", copyStartedAt)
                    .put("copy_completed_uptime_ms", copyCompletedAt)
                    .put("rejected_uptime_ms", SystemClock.uptimeMillis())
                    .put("failure_delivery_phase", "does_not_wait_for_audit_main_delivery_logged_by_request_id")
                    .put("image_timestamp_nanos", image.getTimestamp())
                    .put("image_format", image.getFormat())
                    .put("image_width", image.getWidth()).put("image_height", image.getHeight())
                    .put("image_crop_ltrb_exclusive", new JSONArray().put(crop.left).put(crop.top)
                            .put(crop.right).put(crop.bottom))
                    .put("image_planes", planes)
                    .put("display_width", size.width).put("display_height", size.height)
                    .put("display_density_dpi", size.densityDpi)
                    .put("physical_display_rotation", context.getSystemService(WindowManager.class)
                            .getDefaultDisplay().getRotation())
                    .put("virtual_display_id", display == null || display.getDisplay() == null
                            ? JSONObject.NULL : display.getDisplay().getDisplayId())
                    .put("virtual_display_rotation", display == null || display.getDisplay() == null
                            ? JSONObject.NULL : display.getDisplay().getRotation());
            // No Image/Plane/ByteBuffer escapes this scope: the worker only owns the bitmap and JSON.
            RejectedCaptureAudit.recordAsyncOwned(context, pixels, request.id, details);
            pixels = null;
        } catch (Exception | OutOfMemoryError error) {
            Log.w("KardsCompatCapture", "rejection_audit_metadata_failed request_id=" + request.id
                    + " error=" + error.getClass().getSimpleName());
        } finally {
            if (pixels != null && !pixels.isRecycled()) pixels.recycle();
        }
    }

    /** Read each visible row, excluding padding, without assuming tightly packed planes. */
    static Bitmap copyRgba(Image image, int width, int height) {
        if (image.getFormat() != PixelFormat.RGBA_8888 || image.getPlanes().length != 1)
            throw new IllegalArgumentException("rgba_plane_required");
        Image.Plane plane = image.getPlanes()[0];
        return copyRgbaPixels(plane.getBuffer(), width, height,
                plane.getPixelStride(), plane.getRowStride());
    }

    /** The source position/limit are immutable to callers, including failure paths. */
    static Bitmap copyRgbaPixels(ByteBuffer source, int width, int height,
                                 int pixelStride, int rowStride) {
        if (source == null || width <= 0 || height <= 0 || pixelStride < 4
                || (long) width * height > Integer.MAX_VALUE)
            throw new IllegalArgumentException("invalid_rgba_stride");
        ByteBuffer bytes = source.duplicate();
        int start = bytes.position();
        long visibleRowBytes = (long) (width - 1) * pixelStride + 4L;
        long end = (long) start + (long) (height - 1) * rowStride + visibleRowBytes;
        if (rowStride < visibleRowBytes || end > bytes.limit())
            throw new IllegalArgumentException("invalid_rgba_stride");
        if (pixelStride == 4 && (long) width * height * 4L <= Integer.MAX_VALUE) {
            Bitmap bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888);
            boolean copied = false;
            try {
                int rowBytes = width * 4;
                // Android's ARGB_8888 native storage accepts the ImageReader RGBA bytes.
                // Copy alpha unchanged; the projection gate still rejects nonopaque frames.
                if (bitmap.getRowBytes() == rowBytes) {
                    ByteBuffer packed;
                    if (rowStride == rowBytes) {
                        bytes.limit(start + bitmap.getByteCount());
                        packed = bytes;
                    } else {
                        packed = ByteBuffer.allocateDirect(bitmap.getByteCount());
                        for (int y = 0; y < height; y++) {
                            int at = start + y * rowStride;
                            bytes.limit(source.limit());
                            bytes.position(at);
                            bytes.limit(at + rowBytes);
                            packed.put(bytes);
                        }
                        packed.flip();
                    }
                    bitmap.copyPixelsFromBuffer(packed);
                    copied = true;
                    return bitmap;
                }
            } finally {
                if (!copied) bitmap.recycle();
            }
        }
        // Unusual pixel/bitmap strides retain the explicit channel conversion.
        bytes = source.duplicate();
        int[] colors = new int[width * height];
        for (int y = 0; y < height; y++) {
            int row = start + y * rowStride;
            int target = y * width;
            for (int x = 0; x < width; x++) {
                int at = row + x * pixelStride;
                int red = bytes.get(at) & 0xff;
                int green = bytes.get(at + 1) & 0xff;
                int blue = bytes.get(at + 2) & 0xff;
                int alpha = bytes.get(at + 3) & 0xff;
                colors[target + x] = (alpha << 24) | (red << 16) | (green << 8) | blue;
            }
        }
        return Bitmap.createBitmap(colors, width, height, Bitmap.Config.ARGB_8888);
    }

    private void finishFrame(Request request, FrameSnapshot snapshot) {
        if (!request.finished.compareAndSet(false, true)) {
            snapshot.close();
            return;
        }
        endMirror(request);
        main.post(() -> {
            logTiming(request, "main_delivery", 0L);
            inFlight.compareAndSet(request, null);
            if (closed.get()) {
                snapshot.close();
                request.callback.onFailure(state);
            } else if (SystemClock.uptimeMillis() >= request.deadlineUptime) {
                snapshot.close();
                request.callback.onFailure("兼容截图交付超时（compat_capture_timeout）");
            } else request.callback.onFrame(snapshot);
        });
    }

    private void finishFailure(Request request, String reason) {
        if (!request.finished.compareAndSet(false, true)) return;
        if (Looper.myLooper() == capture.getLooper()) endMirror(request);
        main.post(() -> {
            logTiming(request, "failure_main_delivery", 0L);
            inFlight.compareAndSet(request, null);
            request.callback.onFailure(reason);
        });
    }

    private void endMirror(Request request) {
        if (request.timeout != null) capture.removeCallbacks(request.timeout);
        if (display != null && !closed.get()) {
            try { display.setSurface(null); } catch (RuntimeException ignored) { }
        }
    }

    private void drainImages() {
        Image old;
        while ((old = reader.acquireLatestImage()) != null) old.close();
    }

    private DisplaySpec readDisplay() {
        WindowManager windows = context.getSystemService(WindowManager.class);
        if (windows == null) throw new IllegalStateException("display_missing");
        DisplayMetrics metrics = new DisplayMetrics();
        windows.getDefaultDisplay().getRealMetrics(metrics);
        if (metrics.widthPixels <= 0 || metrics.heightPixels <= 0 || metrics.densityDpi <= 0)
            throw new IllegalStateException("display_geometry_invalid");
        return new DisplaySpec(metrics.widthPixels, metrics.heightPixels, metrics.densityDpi);
    }

    private void release() {
        Request request = inFlight.get();
        if (request != null) finishFailure(request, state);
        capture.removeCallbacksAndMessages(null);
        if (display != null) {
            try { display.release(); } catch (RuntimeException ignored) { }
            display = null;
        }
        if (reader != null) {
            try { reader.setOnImageAvailableListener(null, null); } catch (RuntimeException ignored) { }
            try { reader.close(); } catch (RuntimeException ignored) { }
            reader = null;
        }
        try { projection.unregisterCallback(projectionCallback); } catch (RuntimeException ignored) { }
        try { projection.stop(); } catch (RuntimeException ignored) { }
        thread.quitSafely();
        main.post(() -> stopListener.onStopped(this, state));
    }

    private void failOnMain(FrameSource.Callback callback, String reason) {
        main.post(() -> callback.onFailure(reason));
    }

    private void logTiming(Request request, String phase, long stageMillis) {
        if ((context.getApplicationInfo().flags & android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0)
            Log.d("KardsCompatCapture", "phase=" + phase
                + " request_id=" + request.id
                + " uptime_ms=" + SystemClock.uptimeMillis()
                + " request_age_ms=" + (SystemClock.uptimeMillis() - request.startedUptime)
                + " stage_ms=" + stageMillis);
    }

    private static final class Request {
        final FrameSource.Callback callback;
        final long requestedAtMillis;
        final String id = SystemClock.elapsedRealtimeNanos() + "-" + REQUEST_IDS.incrementAndGet();
        final long startedUptime = SystemClock.uptimeMillis();
        final long deadlineUptime = startedUptime + REQUEST_TIMEOUT_MS;
        final AtomicBoolean finished = new AtomicBoolean();
        long freshAfterNanos;
        Runnable timeout;

        Request(FrameSource.Callback callback, long requestedAtMillis) {
            this.callback = callback;
            this.requestedAtMillis = requestedAtMillis;
        }
    }

    private static final class DisplaySpec {
        final int width;
        final int height;
        final int densityDpi;

        DisplaySpec(int width, int height, int densityDpi) {
            this.width = width;
            this.height = height;
            this.densityDpi = densityDpi;
        }

        boolean sameGeometry(DisplaySpec other) {
            return width == other.width && height == other.height && densityDpi == other.densityDpi;
        }
    }
}
