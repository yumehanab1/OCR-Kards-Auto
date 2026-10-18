package com.kards.mobilert;

import android.content.Context;
import android.content.pm.ApplicationInfo;
import android.graphics.Bitmap;
import android.graphics.Rect;
import android.os.SystemClock;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.Executor;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

/** Debug evidence of a rejected post-copy bitmap, never a game-recognition input. */
final class RejectedCaptureAudit {
    static final int MAX_GROUPS = 8;
    static final long MAX_BYTES = 32L * 1024L * 1024L;
    private static final String TAG = "KardsCompatCapture";
    private static final String GROUP_PREFIX = "capture-";
    private static final String PENDING_PREFIX = ".pending-";
    private static final ThreadPoolExecutor WORKER = newWorker();

    private RejectedCaptureAudit() { }

    /** One running audit and at most one queued bitmap; this method always consumes ownership. */
    static void recordAsyncOwned(Context context, Bitmap bitmap, String requestId, JSONObject details) {
        if ((context.getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) == 0) {
            recycle(bitmap);
            return;
        }
        if (!scheduleOwned(bitmap, WORKER, () -> record(context, bitmap, requestId, details)))
            Log.w(TAG, "rejection_audit_dropped request_id=" + requestId
                    + " reason=worker_full_or_unavailable");
    }

    static ThreadPoolExecutor newWorker() {
        return new ThreadPoolExecutor(1, 1, 0L, TimeUnit.MILLISECONDS,
                new ArrayBlockingQueue<>(1), runnable -> {
                    Thread worker = new Thread(() -> {
                        try { android.os.Process.setThreadPriority(android.os.Process.THREAD_PRIORITY_BACKGROUND); }
                        catch (RuntimeException ignored) { }
                        runnable.run();
                    }, "kards-rejected-capture-audit");
                    worker.setDaemon(true);
                    return worker;
                }, new ThreadPoolExecutor.AbortPolicy());
    }

    /** Executor must either accept the task or reject before running it, as ThreadPoolExecutor does. */
    static boolean scheduleOwned(Bitmap bitmap, Executor executor, Runnable audit) {
        try {
            executor.execute(() -> {
                try {
                    audit.run();
                } catch (RuntimeException | OutOfMemoryError error) {
                    Log.w(TAG, "rejection_audit_worker_failed error=" + error.getClass().getSimpleName());
                } finally {
                    recycle(bitmap);
                }
            });
            return true;
        } catch (RuntimeException | OutOfMemoryError error) {
            recycle(bitmap);
            return false;
        }
    }

    private static void recycle(Bitmap bitmap) {
        if (bitmap != null && !bitmap.isRecycled()) bitmap.recycle();
    }

    /** Fail closed even when analysis, encoding, storage or retention fails. */
    static void record(Context context, Bitmap bitmap, String requestId, JSONObject details) {
        if ((context.getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) == 0) return;
        try {
            AlphaStats stats = analyze(bitmap);
            Log.w(TAG, "rejected request_id=" + requestId + " reason=compat_capture_incomplete_frame"
                    + " nonopaque_pixels=" + stats.nonopaqueCount()
                    + " transparent_pixels=" + stats.histogram[0]
                    + " translucent_pixels=" + stats.translucentCount());
            JSONObject metadata = new JSONObject(details.toString()).put("request_id", requestId);
            File group = save(new File(context.getFilesDir(), "capture-rejections"), bitmap,
                    stats, metadata, MAX_GROUPS, MAX_BYTES);
            Log.w(TAG, "rejection_audit_saved request_id=" + requestId
                    + " group=" + group.getName());
        } catch (Exception | OutOfMemoryError error) {
            // Diagnostics must neither turn a rejected frame into an accepted one nor kill capture.
            Log.w(TAG, "rejection_audit_failed request_id=" + requestId
                    + " error=" + error.getClass().getSimpleName());
        }
    }

    static AlphaStats analyze(Bitmap bitmap) {
        if (bitmap == null || bitmap.isRecycled())
            throw new IllegalArgumentException("capture_bitmap_missing");
        AlphaStats stats = new AlphaStats(bitmap.getWidth(), bitmap.getHeight());
        int rows = Math.min(32, stats.height);
        int[] pixels = new int[stats.width * rows];
        for (int top = 0; top < stats.height; top += rows) {
            int count = Math.min(rows, stats.height - top);
            bitmap.getPixels(pixels, 0, stats.width, 0, top, stats.width, count);
            for (int y = 0; y < count; y++) for (int x = 0; x < stats.width; x++) {
                int alpha = pixels[y * stats.width + x] >>> 24;
                stats.histogram[alpha]++;
                if (alpha < 255) extend(stats.nonopaqueBounds, x, top + y);
                if (alpha == 0) extend(stats.transparentBounds, x, top + y);
                if (alpha > 0 && alpha < 255) extend(stats.translucentBounds, x, top + y);
            }
        }
        return stats;
    }

    private static void extend(Rect bounds, int x, int y) {
        if (bounds.isEmpty()) bounds.set(x, y, x + 1, y + 1);
        else bounds.union(x, y, x + 1, y + 1);
    }

    static final class AlphaStats {
        final int width;
        final int height;
        final long[] histogram = new long[256];
        final Rect nonopaqueBounds = new Rect();
        final Rect transparentBounds = new Rect();
        final Rect translucentBounds = new Rect();

        AlphaStats(int width, int height) { this.width = width; this.height = height; }
        long pixelCount() { return (long) width * height; }
        long nonopaqueCount() { return pixelCount() - histogram[255]; }
        long translucentCount() { return nonopaqueCount() - histogram[0]; }

        JSONObject json() throws Exception {
            JSONArray values = new JSONArray();
            for (long count : histogram) values.put(count);
            return new JSONObject().put("total_pixels", pixelCount())
                    .put("opaque_pixels", histogram[255])
                    .put("transparent_pixels", histogram[0])
                    .put("translucent_pixels", translucentCount())
                    .put("nonopaque_pixels", nonopaqueCount())
                    .put("histogram_alpha_0_through_255", values)
                    .put("nonopaque_bbox_ltrb_exclusive", bounds(nonopaqueBounds))
                    .put("transparent_bbox_ltrb_exclusive", bounds(transparentBounds))
                    .put("translucent_bbox_ltrb_exclusive", bounds(translucentBounds));
        }
    }

    private static Object bounds(Rect rect) {
        if (rect.isEmpty()) return JSONObject.NULL;
        return new JSONArray().put(rect.left).put(rect.top).put(rect.right).put(rect.bottom);
    }

    /** Package-visible to exercise real PNG encoding and bounded pair lifetimes in instrumentation. */
    static synchronized File save(File directory, Bitmap bitmap, AlphaStats stats,
                                  JSONObject details, int maxGroups, long maxBytes) throws Exception {
        if (maxGroups < 1 || maxBytes < 1) throw new IllegalArgumentException("invalid_audit_limits");
        if (bitmap == null || bitmap.isRecycled() || bitmap.getWidth() != stats.width
                || bitmap.getHeight() != stats.height) throw new IllegalArgumentException("audit_bitmap_mismatch");
        if (Files.isSymbolicLink(directory.toPath())) throw new IOException("audit_directory_symlink");
        if ((!directory.isDirectory() && !directory.mkdirs()) || !directory.isDirectory())
            throw new IOException("audit_directory_unavailable");
        List<File> groups = new ArrayList<>();
        File[] children = directory.listFiles();
        if (children == null) throw new IOException("audit_directory_unreadable");
        for (File child : children) {
            if (child.getName().startsWith(PENDING_PREFIX)) deleteTree(child);
            else if (child.getName().startsWith(GROUP_PREFIX)) {
                if (Files.isSymbolicLink(child.toPath()) || !child.isDirectory())
                    throw new IOException("audit_group_invalid");
                if (!new File(child, "audit.json").isFile() || !new File(child, "source-copy.png").isFile())
                    deleteTree(child);
                else groups.add(child);
            } else throw new IOException("audit_unmanaged_entry");
        }
        groups.sort(Comparator.comparing(File::getName));
        Budget budget = new Budget(groups, maxBytes);
        while (groups.size() >= maxGroups) budget.evictOldest();
        while (budget.existingBytes > maxBytes) budget.evictOldest();
        String token = String.format(java.util.Locale.ROOT, "%013d-%s", System.currentTimeMillis(), UUID.randomUUID());
        File pending = new File(directory, PENDING_PREFIX + token);
        File committed = new File(directory, GROUP_PREFIX + token);
        if (!pending.mkdir()) throw new IOException("audit_staging_unavailable");
        boolean complete = false;
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            File png = new File(pending, "source-copy.png");
            try (FileOutputStream file = new FileOutputStream(png);
                 OutputStream limited = new BudgetStream(file, budget, digest)) {
                if (!bitmap.compress(Bitmap.CompressFormat.PNG, 100, limited))
                    throw new IOException("audit_png_encode_failed");
                limited.flush();
                file.getFD().sync();
            }
            JSONObject audit = new JSONObject(details.toString())
                    .put("schema", 1).put("reason", "compat_capture_incomplete_frame")
                    .put("evidence_kind", "post_copy_source_bitmap_png")
                    .put("raw_image_buffer_dump", false)
                    .put("normalized_or_resized", false).put("alpha_preserved", true)
                    .put("recognition_input", false)
                    .put("bitmap_width", stats.width).put("bitmap_height", stats.height)
                    .put("bitmap_config", String.valueOf(bitmap.getConfig()))
                    .put("bitmap_has_alpha", bitmap.hasAlpha())
                    .put("bitmap_premultiplied", bitmap.isPremultiplied())
                    .put("alpha", stats.json()).put("png_file", "source-copy.png")
                    .put("png_bytes", png.length()).put("png_sha256", hex(digest.digest()))
                    .put("audit_encoded_uptime_ms", SystemClock.uptimeMillis())
                    .put("max_groups", maxGroups).put("max_bytes", maxBytes);
            byte[] json = (audit.toString(2) + "\n").getBytes(StandardCharsets.UTF_8);
            try (FileOutputStream file = new FileOutputStream(new File(pending, "audit.json"));
                 OutputStream limited = new BudgetStream(file, budget, null)) {
                limited.write(json); limited.flush(); file.getFD().sync();
            }
            if (!pending.renameTo(committed)) throw new IOException("audit_commit_failed");
            complete = true;
            return committed;
        } finally {
            if (!complete) deleteTree(pending);
        }
    }

    private static String hex(byte[] bytes) {
        StringBuilder value = new StringBuilder(bytes.length * 2);
        for (byte b : bytes) value.append(String.format(java.util.Locale.ROOT, "%02x", b & 255));
        return value.toString();
    }

    private static long bytes(File file) throws IOException {
        if (Files.isSymbolicLink(file.toPath())) throw new IOException("audit_entry_symlink");
        if (file.isFile()) return file.length();
        if (!file.isDirectory()) throw new IOException("audit_entry_missing");
        File[] children = file.listFiles();
        if (children == null) throw new IOException("audit_entry_unreadable");
        long total = 0;
        for (File child : children) total = Math.addExact(total, bytes(child));
        return total;
    }

    private static void deleteTree(File file) throws IOException {
        // Never follow a directory link while reclaiming private diagnostic evidence.
        if (!Files.isSymbolicLink(file.toPath()) && file.isDirectory()) {
            File[] children = file.listFiles();
            if (children == null) throw new IOException("audit_cleanup_unreadable");
            for (File child : children) deleteTree(child);
        }
        if (file.exists() || Files.isSymbolicLink(file.toPath()))
            if (!file.delete()) throw new IOException("audit_cleanup_failed");
    }

    private static final class Budget {
        final List<File> groups;
        final long maximum;
        long existingBytes;
        long pendingBytes;
        Budget(List<File> groups, long maximum) throws IOException {
            this.groups = groups; this.maximum = maximum;
            for (File group : groups) existingBytes = Math.addExact(existingBytes, bytes(group));
        }
        void reserve(int count) throws IOException {
            if (count < 0 || pendingBytes > maximum - count) throw new IOException("audit_pair_exceeds_budget");
            while (existingBytes > maximum - pendingBytes - count) evictOldest();
            pendingBytes += count;
        }
        void evictOldest() throws IOException {
            if (groups.isEmpty()) throw new IOException("audit_pair_exceeds_budget");
            File oldest = groups.get(0);
            long reclaimed = bytes(oldest);
            // Hide the whole pair atomically before deletion, including a process death mid-cleanup.
            File removing = new File(oldest.getParentFile(), PENDING_PREFIX + "delete-" + UUID.randomUUID());
            if (!oldest.renameTo(removing)) throw new IOException("audit_evict_rename_failed");
            deleteTree(removing);
            groups.remove(0);
            existingBytes -= reclaimed;
        }
    }

    private static final class BudgetStream extends OutputStream {
        final OutputStream target;
        final Budget budget;
        final MessageDigest digest;
        BudgetStream(OutputStream target, Budget budget, MessageDigest digest) {
            this.target = target; this.budget = budget; this.digest = digest;
        }
        @Override public void write(int value) throws IOException {
            budget.reserve(1); target.write(value);
            if (digest != null) digest.update((byte) value);
        }
        @Override public void write(byte[] values, int offset, int count) throws IOException {
            budget.reserve(count); target.write(values, offset, count);
            if (digest != null) digest.update(values, offset, count);
        }
        @Override public void flush() throws IOException { target.flush(); }
        @Override public void close() throws IOException { target.close(); }
    }
}
