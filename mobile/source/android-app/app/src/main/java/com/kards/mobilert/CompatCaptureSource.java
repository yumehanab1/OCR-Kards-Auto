package com.kards.mobilert;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.PixelFormat;
import android.graphics.Point;
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
    private boolean naturalBuffer;
    private boolean geometryRepairAttempted;
    private boolean logicalRecoveryAttempted;
    private long preparationDeadlineUptime;
    private int geometryTransitions;
    private boolean geometrySettling;
    private long mirrorGeneration;
    private final Runnable preparedGeometryMonitor = this::monitorPreparedGeometry;
    private final DisplayManager.DisplayListener displayListener = new DisplayManager.DisplayListener() {
        @Override public void onDisplayAdded(int id) { }
        @Override public void onDisplayRemoved(int id) { }
        @Override public void onDisplayChanged(int id) {
            if (id == android.view.Display.DEFAULT_DISPLAY && !closed.get()) {
                capture.removeCallbacks(geometryChanged);
                capture.postDelayed(geometryChanged, 250L);
            }
        }
    };
    private final Runnable geometryChanged = () -> {
        if (closed.get()) return;
        try {
            DisplaySpec current = readDisplay();
            if (!size.sameGeometry(current)) adaptGeometry(current, inFlight.get());
        } catch (RuntimeException error) {
            close("compat_capture_geometry_transition_failed");
        }
    };
    private Object mirrorToken;

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
        if (closed.get()) {
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
        // Never tear down the projection while its callback dispatcher is iterating.
        capture.post(this::release);
    }

    private void initialize() {
        if (closed.get()) return;
        try {
            size = readDisplay();
            projection.registerCallback(projectionCallback, capture);
            context.getSystemService(DisplayManager.class).registerDisplayListener(displayListener, capture);
            createMirror();
            // Ignore work queued for a mirror superseded by a real display transition.
            long generation = mirrorGeneration;
            capture.postDelayed(() -> {
                if (closed.get() || generation != mirrorGeneration) return;
                if (mirrorGeometryMatches()) finishInitialization();
                else repairGeometry(this::finishInitialization);
            }, 300L);
        } catch (RuntimeException error) {
            close("兼容截图初始化失败（compat_capture_init_" + error.getClass().getSimpleName() + "）");
        }
    }

    private void createMirror() {
        mirrorGeneration++;
        // The producer surface follows the virtual device's natural axes; normalize only by
        // an exact quarter-turn after copying, never by cropping, stretching or filling alpha.
        reader = ImageReader.newInstance(size.bufferWidth(naturalBuffer), size.bufferHeight(naturalBuffer),
                PixelFormat.RGBA_8888, 3);
        reader.setOnImageAvailableListener(this::imageAvailable, capture);
        int flags = DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR;
        if (naturalBuffer) flags |= ProjectionGeometry.ROTATES_WITH_CONTENT;
        display = projection.createVirtualDisplay("KARDS compatible capture", size.bufferWidth(naturalBuffer),
                size.bufferHeight(naturalBuffer), size.densityDpi, flags, reader.getSurface(),
                new VirtualDisplay.Callback() {
                    private final Object token = mirrorToken = new Object();
                    @Override public void onStopped() {
                        if (mirrorToken == token) close("兼容截图显示已停止（compat_capture_display_stopped）");
                    }
                }, capture);
        if (display == null) throw new IllegalStateException("virtual_display_null");
    }

    private void repairGeometry(Runnable done) {
        geometryRepairAttempted = true;
        // Android 14+ permits only one display per consent. This legacy path never retries there.
        if (android.os.Build.VERSION.SDK_INT >= 34 || !ProjectionGeometry.swapsAxes(size.rotation)) {
            done.run(); return;
        }
        state = "正在恢复兼容截图方向（compat_capture_initializing）";
        try {
            mirrorToken = null;
            display.setSurface(null);
            display.release();
            display = null;
            reader.setOnImageAvailableListener(null, null);
            reader.close();
            naturalBuffer = true;
            createMirror();
            long generation = mirrorGeneration;
            capture.postDelayed(() -> {
                if (closed.get() || generation != mirrorGeneration) return;
                Log.d("KardsCompatCapture", "natural_buffer_repair matches=" + mirrorGeometryMatches());
                done.run();
            }, 300L);
        } catch (RuntimeException error) {
            Log.w("KardsCompatCapture", "natural_buffer_repair_failed", error);
            close("兼容截图方向恢复失败（compat_capture_virtual_geometry_mismatch）");
        }
    }

    private void finishInitialization() {
        Log.d("KardsCompatCapture", "initialized natural_buffer=" + naturalBuffer);
        if (closed.get()) return;
        geometrySettling = false;
        capture.removeCallbacks(preparedGeometryMonitor);
        ready = ProjectionFramePolicy.ready(closed.get(), mirrorGeometryMatches());
        state = ready ? "兼容截图已就绪（media_projection）"
                : "兼容截图虚拟屏方向异常，请修复模拟器截图旋转设置"
                        + "（compat_capture_virtual_geometry_mismatch）";
        preparationDeadlineUptime = SystemClock.uptimeMillis() + 10_000L;
        capture.postDelayed(preparedGeometryMonitor, 250L);
    }

    private void monitorPreparedGeometry() {
        long now = SystemClock.uptimeMillis();
        if (ProjectionFramePolicy.prepareIdleGeometry(android.os.Build.VERSION.SDK_INT,
                closed.get(), inFlight.get() != null, now, preparationDeadlineUptime)) {
            try {
                DisplaySpec current = readDisplay();
                if (!size.sameGeometry(current)) { adaptGeometry(current, null); return; }
                if (geometrySettling) return;
                if (!mirrorGeometryMatches() && ProjectionFramePolicy.recoverLogicalMirror(
                        android.os.Build.VERSION.SDK_INT, closed.get(), naturalBuffer,
                        logicalRecoveryAttempted)) {
                    recoverLogicalMirror(null);
                }
                ready = ProjectionFramePolicy.ready(closed.get(), mirrorGeometryMatches());
                state = ready ? "兼容截图已就绪（media_projection）"
                        : "兼容截图布局稳定中（compat_capture_initializing）";
            } catch (RuntimeException error) {
                close("兼容截图准备失败（compat_capture_prepare_"
                        + error.getClass().getSimpleName() + "）");
            }
        }
        if (android.os.Build.VERSION.SDK_INT < 34
                && ProjectionFramePolicy.deliver(closed.get(), SystemClock.uptimeMillis(),
                        preparationDeadlineUptime)) {
            capture.postDelayed(preparedGeometryMonitor, 250L);
        }
    }

    private void recoverLogicalMirror(Request request) {
        logicalRecoveryAttempted = true;
        ready = false;
        state = "正在重新建立兼容截图方向（compat_capture_initializing）";
        try {
            // A delayed WM override can invalidate the initialization-only natural fallback.
            // Recreate once under the live request; never detach per accepted frame.
            mirrorToken = null;
            if (display != null) display.release();
            display = null;
            reader.setOnImageAvailableListener(null, null);
            reader.close();
            naturalBuffer = false;
            createMirror();
            Log.d("KardsCompatCapture", "logical_mirror_recovery request_id="
                    + (request == null ? "idle_preparation" : request.id));
            if (request != null) capture.postDelayed(() -> begin(request), 300L);
        } catch (RuntimeException error) {
            close("兼容截图方向恢复失败（compat_capture_virtual_geometry_mismatch）");
        }
    }

    private void adaptGeometry(DisplaySpec current, Request request) {
        if (closed.get() || size.sameGeometry(current)) return;
        if (request != null && !ProjectionFramePolicy.deliver(false,
                SystemClock.uptimeMillis(), request.deadlineUptime)) {
            finishFailure(request, "兼容截图等待超时（compat_capture_timeout）");
            return;
        }
        if (android.os.Build.VERSION.SDK_INT >= 34 || ++geometryTransitions > 8) {
            close("compat_capture_geometry_changed");
            return;
        }
        ready = false;
        geometrySettling = true;
        if (request != null) request.freshAfterNanos = 0L;
        mirrorToken = null;
        if (display != null) display.release();
        display = null;
        if (reader != null) {
            reader.setOnImageAvailableListener(null, null);
            reader.close();
        }
        size = current;
        naturalBuffer = false;
        geometryRepairAttempted = false;
        logicalRecoveryAttempted = false;
        createMirror();
        long generation = mirrorGeneration;
        Log.d("KardsCompatCapture", "geometry_transition=" + geometryTransitions
                + " width=" + size.width + " height=" + size.height);
        preparationDeadlineUptime = SystemClock.uptimeMillis() + 10_000L;
        capture.postDelayed(() -> {
            if (closed.get() || generation != mirrorGeneration) return;
            Runnable settled = () -> {
                finishInitialization();
                if (request != null && !request.finished.get()) begin(request);
            };
            if (mirrorGeometryMatches()) settled.run();
            else repairGeometry(settled);
        }, 300L);
    }

    private void begin(Request request) {
        if (request.finished.get()) return;
        logTiming(request, "begin", 0L);
        request.beginCount++;
        if (closed.get()) {
            finishFailure(request, state);
            return;
        }
        // Readiness is evaluated below against live geometry on every request.
        if (SystemClock.uptimeMillis() >= request.deadlineUptime) {
            finishFailure(request, "兼容截图等待超时（compat_capture_timeout）");
            return;
        }
        // Arm the original deadline BEFORE any geometry rebuild or asynchronous wait.
        if (request.timeout == null) {
            request.timeout = () -> finishFailure(request,
                    "兼容截图等待新帧超时（compat_capture_timeout）");
            capture.postDelayed(request.timeout,
                    Math.max(0L, request.deadlineUptime - SystemClock.uptimeMillis()));
        }
        try {
            DisplaySpec current = readDisplay();
            if (!size.sameGeometry(current)) {
                adaptGeometry(current, request);
                return;
            }
            if (geometrySettling) {
                capture.postDelayed(() -> begin(request), 50L);
                return;
            }
            boolean geometryMatches = mirrorGeometryMatches();
            logTiming(request, "mirror_geometry", 0L);
            Log.d("KardsCompatCapture", "request_id=" + request.id
                    + " mirrorGeometryMatches=" + geometryMatches + " settling=" + geometrySettling
                    + " natural_buffer=" + naturalBuffer + " generation=" + mirrorGeneration
                    + " source=" + size.width + "x" + size.height + " rotation=" + size.rotation);
            if (!geometryMatches) {
                if (ProjectionFramePolicy.recoverLogicalMirror(android.os.Build.VERSION.SDK_INT,
                        closed.get(), naturalBuffer, logicalRecoveryAttempted)) {
                    recoverLogicalMirror(request);
                    return;
                }
                if (ProjectionFramePolicy.awaitLogicalLayout(closed.get(), logicalRecoveryAttempted,
                        SystemClock.uptimeMillis(), request.deadlineUptime)) {
                    capture.postDelayed(() -> begin(request), 50L);
                    return;
                }
                // Also cover a delayed WM override arriving after initialization.
                if (!geometryRepairAttempted) {
                    repairGeometry(() -> begin(request));
                    return;
                }
                finishFailure(request, "兼容截图虚拟屏方向异常，请重新授权兼容截图"
                        + "（compat_capture_virtual_geometry_mismatch）");
                return;
            }
            ready = ProjectionFramePolicy.ready(closed.get(), mirrorGeometryMatches());
            if (!ready) { finishFailure(request, state); return; }
            state = "兼容截图已就绪（media_projection）";
            long drainStartedAt = SystemClock.uptimeMillis();
            request.drainedImages += drainImages();
            logTiming(request, "drain_complete", SystemClock.uptimeMillis() - drainStartedAt);
            // Keep the producer connected. Detaching on each request recreates WM mirroring
            // and can reset its rotation/crop. Old images are still never eligible.
            request.freshAfterNanos = System.nanoTime();
            logTiming(request, "freshness_armed", 0L);
        } catch (RuntimeException error) {
            finishFailure(request, "兼容截图请求失败（compat_capture_request_"
                    + error.getClass().getSimpleName() + "）");
        }
    }

    private boolean mirrorGeometryMatches() {
        if (display == null || display.getDisplay() == null) return false;
        Point actual = new Point();
        display.getDisplay().getRealSize(actual);
        return actual.x == size.width && actual.y == size.height
                && display.getDisplay().getRotation() == (naturalBuffer ? size.rotation : android.view.Surface.ROTATION_0);
    }

    private void imageAvailable(ImageReader source) {
        if (source != reader || closed.get()) return;
        Bitmap pixels = null;
        try (Image image = source.acquireLatestImage()) {
            if (image == null) return;
            Request request = inFlight.get();
            if (closed.get() || request == null || request.finished.get()) return;
            request.imageCallbacks++;
            request.lastImageTimestamp = image.getTimestamp();
            if (!ProjectionFramePolicy.fresh(request.freshAfterNanos, image.getTimestamp())) {
                request.staleImages++;
                logTiming(request, "stale_image_rejected", 0L);
                return;
            }
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
            DisplaySpec current = readDisplay();
            if (!size.sameGeometry(current) || !mirrorGeometryMatches()) {
                request.freshAfterNanos = 0L;
                // Close this acquired Image before replacing its reader/producer.
                capture.post(() -> {
                    if (closed.get() || request.finished.get()) return;
                    DisplaySpec live = readDisplay();
                    if (!size.sameGeometry(live)) adaptGeometry(live, request);
                    else begin(request);
                });
                return;
            }
            int bufferWidth = size.bufferWidth(naturalBuffer), bufferHeight = size.bufferHeight(naturalBuffer);
            if (image.getWidth() != bufferWidth || image.getHeight() != bufferHeight
                    || !image.getCropRect().equals(new Rect(0, 0, bufferWidth, bufferHeight))) {
                // A malformed/cropped frame is not evidence of a display transition.
                finishFailure(request, "compat_capture_buffer_geometry_mismatch");
                return;
            }
            long copyStartedAt = SystemClock.uptimeMillis();
            pixels = copyRgba(image, bufferWidth, bufferHeight);
            long copyCompletedAt = SystemClock.uptimeMillis();
            logTiming(request, "copy_complete", copyCompletedAt - copyStartedAt);
            // Reject on the capture thread while both the Image metadata and copied alpha exist.
            // The accessibility-service gate remains an independent final check.
            long opaqueStartedAt = SystemClock.uptimeMillis();
            boolean opaque = CapturePixelQuality.isFullyOpaque(pixels);
            logTiming(request, "opaque_complete", SystemClock.uptimeMillis() - opaqueStartedAt);
            if (!opaque) {
                Bitmap rejectedCopy = pixels;
                pixels = null; // The audit path consumes ownership, including metadata/queue failures.
                auditRejectedCopy(request, image, rejectedCopy, imageArrivedAt, copyStartedAt, copyCompletedAt);
                finishFailure(request, "compat_capture_incomplete_frame");
                return;
            }
            if (naturalBuffer) {
                long rotationStartedAt = SystemClock.uptimeMillis();
                Bitmap logical = ProjectionGeometry.toLogical(pixels, size.rotation);
                if (logical != pixels) pixels.recycle();
                pixels = logical;
                logTiming(request, "rotation_complete", SystemClock.uptimeMillis() - rotationStartedAt);
            }
            if (pixels.getWidth() != size.width || pixels.getHeight() != size.height)
                throw new IllegalStateException("logical_pixel_geometry_mismatch");
            if (SystemClock.uptimeMillis() >= request.deadlineUptime) {
                pixels.recycle();
                pixels = null;
                finishFailure(request, "兼容截图转换超时（compat_capture_timeout）");
                return;
            }
            logAccepted(request, image);
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
                    .put("natural_orientation_virtual_display", naturalBuffer)
                    .put("virtual_device_width", size.bufferWidth(naturalBuffer)).put("virtual_device_height", size.bufferHeight(naturalBuffer))
                    .put("buffer_width", size.bufferWidth(naturalBuffer)).put("buffer_height", size.bufferHeight(naturalBuffer))
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
                if (bitmap.getRowBytes() == rowBytes && rowStride == rowBytes) {
                    bytes.limit(start + bitmap.getByteCount());
                    ByteBuffer packed = bytes;
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
        // Padded/unusual strides: bounded strips, not a second full-frame
        // direct buffer (whose native memory waits for GC after every image).
        int rows = Math.min(32, height);
        int[] colors = new int[width * rows];
        Bitmap bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888);
        boolean copied = false;
        try {
            for (int top = 0; top < height; top += rows) {
                int count = Math.min(rows, height - top);
                for (int y = 0; y < count; y++) {
                    int row = start + (top + y) * rowStride;
                    for (int x = 0; x < width; x++) {
                        int at = row + x * pixelStride;
                        int red = bytes.get(at) & 0xff;
                        int green = bytes.get(at + 1) & 0xff;
                        int blue = bytes.get(at + 2) & 0xff;
                        int alpha = bytes.get(at + 3) & 0xff;
                        colors[y * width + x] = (alpha << 24) | (red << 16) | (green << 8) | blue;
                    }
                }
                bitmap.setPixels(colors, 0, width, 0, top, width, count);
            }
            copied = true;
            return bitmap;
        } finally {
            if (!copied) bitmap.recycle();
        }
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
            } else if (!ProjectionFramePolicy.deliver(false, SystemClock.uptimeMillis(), request.deadlineUptime)) {
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
        // The consent owns the continuous producer, not an individual frame request.
        // imageAvailable drains idle images without retaining or exposing them.
    }

    private int drainImages() {
        Image old;
        int count = 0;
        while ((old = reader.acquireLatestImage()) != null) {
            old.close();
            count++;
        }
        return count;
    }

    private DisplaySpec readDisplay() {
        WindowManager windows = context.getSystemService(WindowManager.class);
        if (windows == null) throw new IllegalStateException("display_missing");
        DisplayMetrics metrics = new DisplayMetrics();
        windows.getDefaultDisplay().getRealMetrics(metrics);
        if (metrics.widthPixels <= 0 || metrics.heightPixels <= 0 || metrics.densityDpi <= 0)
            throw new IllegalStateException("display_geometry_invalid");
        return new DisplaySpec(metrics.widthPixels, metrics.heightPixels, metrics.densityDpi,
                windows.getDefaultDisplay().getRotation());
    }

    private void release() {
        Request request = inFlight.get();
        if (request != null) finishFailure(request, state);
        mirrorToken = null;
        capture.removeCallbacksAndMessages(null);
        try { context.getSystemService(DisplayManager.class).unregisterDisplayListener(displayListener); }
        catch (RuntimeException error) { Log.w("KardsCompatCapture", "display_unregister_failed", error); }
        if (display != null) {
            try { display.release(); Log.d("KardsCompatCapture", "virtual_display_released"); }
            catch (RuntimeException error) { Log.e("KardsCompatCapture", "virtual_display_release_failed", error); }
            display = null;
        }
        if (reader != null) {
            try { reader.setOnImageAvailableListener(null, null); } catch (RuntimeException ignored) { }
            try { reader.close(); } catch (RuntimeException ignored) { }
            reader = null;
        }
        main.post(() -> {
            try { projection.unregisterCallback(projectionCallback); }
            catch (RuntimeException error) { Log.w("KardsCompatCapture", "unregister_failed", error); }
            try { projection.stop(); }
            catch (RuntimeException error) { Log.w("KardsCompatCapture", "projection_stop_failed", error); }
        });
        thread.quitSafely();
        main.post(() -> stopListener.onStopped(this, state));
    }

    private void failOnMain(FrameSource.Callback callback, String reason) {
        main.post(() -> callback.onFailure(reason));
    }

    private void logAccepted(Request request, Image image) {
        if ((context.getApplicationInfo().flags & android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0)
            Log.d("KardsCaptureTrace", "route=media_projection request_id=" + request.id
                    + " requested_at_wall_ms=" + request.requestedAtMillis
                    + " fresh_after_nanos=" + request.freshAfterNanos
                    + " image_timestamp_nanos=" + image.getTimestamp()
                    + " image_width=" + image.getWidth() + " image_height=" + image.getHeight()
                    + " natural_buffer=" + naturalBuffer + " rotation=" + size.rotation
                    + " display_id=" + display.getDisplay().getDisplayId()
                    + " output_width=" + size.width + " output_height=" + size.height);
    }

    private void logTiming(Request request, String phase, long stageMillis) {
        if ((context.getApplicationInfo().flags & android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0)
            Log.d("KardsCompatCapture", "phase=" + phase
                + " request_id=" + request.id
                + " uptime_ms=" + SystemClock.uptimeMillis()
                + " request_age_ms=" + (SystemClock.uptimeMillis() - request.startedUptime)
                + " stage_ms=" + stageMillis
                + " begin_count=" + request.beginCount
                + " drained_images=" + request.drainedImages
                + " image_callbacks=" + request.imageCallbacks
                + " stale_images=" + request.staleImages
                + " fresh_after_nanos=" + request.freshAfterNanos
                + " last_image_timestamp_nanos=" + request.lastImageTimestamp);
    }

    private static final class Request {
        final FrameSource.Callback callback;
        final long requestedAtMillis;
        final String id = SystemClock.elapsedRealtimeNanos() + "-" + REQUEST_IDS.incrementAndGet();
        final long startedUptime = SystemClock.uptimeMillis();
        final long deadlineUptime = startedUptime + REQUEST_TIMEOUT_MS;
        final AtomicBoolean finished = new AtomicBoolean();
        long freshAfterNanos;
        int beginCount;
        int drainedImages;
        int imageCallbacks;
        int staleImages;
        long lastImageTimestamp;
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
        final int rotation;

        DisplaySpec(int width, int height, int densityDpi, int rotation) {
            this.width = width;
            this.height = height;
            this.densityDpi = densityDpi;
            this.rotation = rotation;
        }

        int bufferWidth(boolean natural) { return natural ? ProjectionGeometry.bufferWidth(width, height, rotation) : width; }
        int bufferHeight(boolean natural) { return natural ? ProjectionGeometry.bufferHeight(width, height, rotation) : height; }

        boolean sameGeometry(DisplaySpec other) {
            return width == other.width && height == other.height && densityDpi == other.densityDpi && rotation == other.rotation;
        }
    }
}
