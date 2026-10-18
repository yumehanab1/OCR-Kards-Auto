package com.kards.mobilert;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.Rect;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

/** Synthetic alpha and real PNG/retention checks; no capture, game launch or device input. */
final class RejectedCaptureAuditChecks {
    static JSONObject run(Context context) throws Exception {
        JSONArray checks = new JSONArray();
        File root = Files.createTempDirectory(context.getCacheDir().toPath(), "capture-rejection-checks-").toFile();
        Bitmap mixed = Bitmap.createBitmap(16, 12, Bitmap.Config.ARGB_8888);
        Bitmap transparent = Bitmap.createBitmap(7, 5, Bitmap.Config.ARGB_8888);
        Bitmap opaque = Bitmap.createBitmap(4, 4, Bitmap.Config.ARGB_8888);
        try {
            transparent.eraseColor(Color.TRANSPARENT);
            RejectedCaptureAudit.AlphaStats empty = RejectedCaptureAudit.analyze(transparent);
            check(checks, "all_transparent_counts", empty.pixelCount() == 35
                    && empty.histogram[0] == 35 && empty.histogram[255] == 0
                    && empty.nonopaqueCount() == 35 && empty.translucentCount() == 0);
            check(checks, "all_transparent_bbox", empty.nonopaqueBounds.equals(new Rect(0, 0, 7, 5))
                    && empty.transparentBounds.equals(new Rect(0, 0, 7, 5))
                    && empty.translucentBounds.isEmpty());
            check(checks, "all_transparent_source_gate_refuses", !CapturePixelQuality.isFullyOpaque(transparent));

            mixed.eraseColor(Color.rgb(40, 60, 80));
            mixed.setPixel(2, 1, Color.TRANSPARENT);
            mixed.setPixel(10, 8, Color.TRANSPARENT);
            mixed.setPixel(1, 2, Color.argb(1, 0, 0, 0));
            mixed.setPixel(3, 4, Color.argb(128, 0, 0, 0));
            mixed.setPixel(15, 11, Color.argb(254, 0, 0, 0));
            RejectedCaptureAudit.AlphaStats stats = RejectedCaptureAudit.analyze(mixed);
            check(checks, "sparse_alpha_counts", stats.pixelCount() == 192
                    && stats.histogram[0] == 2 && stats.histogram[255] == 187
                    && stats.translucentCount() == 3 && stats.nonopaqueCount() == 5);
            long histogramTotal = 0;
            for (int i = 0; i < stats.histogram.length; i++) histogramTotal += stats.histogram[i];
            check(checks, "full_histogram_preserves_alpha_bins", histogramTotal == 192
                    && stats.histogram.length == 256 && stats.histogram[1] == 1
                    && stats.histogram[128] == 1 && stats.histogram[254] == 1);
            check(checks, "nonopaque_bbox_right_bottom_exclusive", stats.nonopaqueBounds.equals(new Rect(1, 1, 16, 12)));
            check(checks, "transparent_and_translucent_bboxes", stats.transparentBounds.equals(new Rect(2, 1, 11, 9))
                    && stats.translucentBounds.equals(new Rect(1, 2, 16, 12)));
            check(checks, "single_partial_alpha_source_gate_refuses", !CapturePixelQuality.isFullyOpaque(mixed));

            opaque.eraseColor(Color.WHITE);
            RejectedCaptureAudit.AlphaStats healthy = RejectedCaptureAudit.analyze(opaque);
            check(checks, "opaque_frame_has_no_defect", healthy.histogram[255] == 16
                    && healthy.nonopaqueCount() == 0 && healthy.nonopaqueBounds.isEmpty()
                    && healthy.json().isNull("nonopaque_bbox_ltrb_exclusive")
                    && CapturePixelQuality.isFullyOpaque(opaque));

            JSONObject details = new JSONObject().put("request_id", "synthetic-1")
                    .put("image_width", 16).put("image_height", 12)
                    .put("image_crop_ltrb_exclusive", new JSONArray().put(0).put(0).put(16).put(12))
                    .put("image_planes", new JSONArray().put(new JSONObject().put("row_stride", 80)
                            .put("pixel_stride", 4).put("buffer_position", 3).put("buffer_limit", 947)))
                    .put("image_timestamp_nanos", 123456789L).put("request_started_uptime_ms", 100L)
                    .put("request_deadline_uptime_ms", 1600L).put("display_width", 16)
                    .put("display_height", 12).put("display_density_dpi", 320);
            File paired = RejectedCaptureAudit.save(new File(root, "pairs"), mixed, stats, details,
                    RejectedCaptureAudit.MAX_GROUPS, RejectedCaptureAudit.MAX_BYTES);
            JSONObject saved = read(new File(paired, "audit.json"));
            check(checks, "committed_group_has_png_and_json_only", paired.getName().startsWith("capture-")
                    && paired.listFiles() != null && paired.listFiles().length == 2
                    && new File(paired, "source-copy.png").isFile() && new File(paired, "audit.json").isFile());
            Bitmap decoded = BitmapFactory.decodeFile(new File(paired, "source-copy.png").getAbsolutePath());
            try {
                boolean preserved = decoded != null && decoded.getWidth() == mixed.getWidth()
                        && decoded.getHeight() == mixed.getHeight();
                if (preserved) for (int y = 0; y < 12; y++) for (int x = 0; x < 16; x++)
                    preserved &= Color.alpha(decoded.getPixel(x, y)) == Color.alpha(mixed.getPixel(x, y));
                check(checks, "png_round_trip_preserves_all_source_alpha", preserved);
                check(checks, "png_round_trip_does_not_make_bad_frame_opaque", decoded != null
                        && !CapturePixelQuality.isFullyOpaque(decoded));
            } finally { if (decoded != null) decoded.recycle(); }
            check(checks, "saved_metadata_explains_copy_provenance", saved.getString("evidence_kind").equals("post_copy_source_bitmap_png")
                    && !saved.getBoolean("raw_image_buffer_dump") && !saved.getBoolean("normalized_or_resized")
                    && saved.getBoolean("alpha_preserved") && !saved.getBoolean("recognition_input"));
            check(checks, "saved_alpha_metadata_matches_source", saved.getJSONObject("alpha").getLong("nonopaque_pixels") == 5
                    && saved.getJSONObject("alpha").getJSONArray("histogram_alpha_0_through_255").getLong(128) == 1
                    && saved.getString("png_sha256").length() == 64
                    && saved.getLong("png_bytes") == new File(paired, "source-copy.png").length());
            check(checks, "saved_image_and_request_metadata_survive", saved.getString("request_id").equals("synthetic-1")
                    && saved.getJSONArray("image_planes").getJSONObject(0).getInt("buffer_position") == 3
                    && saved.getJSONArray("image_planes").getJSONObject(0).getInt("row_stride") == 80
                    && saved.getLong("image_timestamp_nanos") == 123456789L
                    && saved.getLong("request_deadline_uptime_ms") == 1600L);

            File countRoot = new File(root, "count-limit");
            for (int i = 0; i < 11; i++) RejectedCaptureAudit.save(countRoot, mixed, stats,
                    new JSONObject().put("request_id", "count-" + i), 8, 32L * 1024L * 1024L);
            check(checks, "retention_keeps_at_most_eight_complete_pairs", groupCount(countRoot) == 8 && pairedOnly(countRoot));
            File bytesRoot = new File(root, "byte-limit");
            File first = RejectedCaptureAudit.save(bytesRoot, mixed, stats, new JSONObject(), 8, 65536);
            long limit = bytes(first) * 2 + 32;
            for (int i = 0; i < 6; i++) RejectedCaptureAudit.save(bytesRoot, mixed, stats, new JSONObject(), 8, limit);
            check(checks, "retention_enforces_aggregate_byte_budget", bytes(bytesRoot) <= limit
                    && groupCount(bytesRoot) > 0 && groupCount(bytesRoot) <= 2 && pairedOnly(bytesRoot));

            File tinyRoot = new File(root, "cannot-fit");
            boolean refused = false;
            try { RejectedCaptureAudit.save(tinyRoot, mixed, stats, new JSONObject(), 8, 1); }
            catch (Exception expected) { refused = true; }
            check(checks, "oversize_pair_is_refused_without_partial_group", refused && groupCount(tinyRoot) == 0
                    && tinyRoot.listFiles() != null && tinyRoot.listFiles().length == 0);
            File blocked = new File(root, "not-a-directory");
            Files.write(blocked.toPath(), new byte[]{9});
            refused = false;
            try { RejectedCaptureAudit.save(blocked, mixed, stats, new JSONObject(), 8, 65536); }
            catch (Exception expected) { refused = true; }
            check(checks, "unwritable_destination_does_not_change_source_alpha", refused
                    && !CapturePixelQuality.isFullyOpaque(mixed) && stats.nonopaqueCount() == 5);
            File stale = new File(countRoot, ".pending-abandoned");
            if (!stale.mkdir()) throw new IllegalStateException("cannot create abandoned stage");
            Files.write(new File(stale, "source-copy.png").toPath(), new byte[]{1, 2, 3});
            RejectedCaptureAudit.save(countRoot, mixed, stats, new JSONObject(), 8, 32L * 1024L * 1024L);
            check(checks, "abandoned_stage_reclaimed_without_leaving_unpaired_files", !stale.exists()
                    && groupCount(countRoot) == 8 && pairedOnly(countRoot));
            check(checks, "production_retention_constants", RejectedCaptureAudit.MAX_GROUPS == 8
                    && RejectedCaptureAudit.MAX_BYTES == 32L * 1024L * 1024L);
            asyncOwnershipChecks(checks);
            return new JSONObject().put("passed", true).put("checks", checks.length()).put("details", checks)
                    .put("device_inputs", 0).put("captures", 0).put("game_launches", 0);
        } finally {
            mixed.recycle(); transparent.recycle(); opaque.recycle(); cleanup(root);
        }
    }

    private static void asyncOwnershipChecks(JSONArray checks) throws Exception {
        ThreadPoolExecutor worker = RejectedCaptureAudit.newWorker();
        CountDownLatch running = new CountDownLatch(1);
        CountDownLatch release = new CountDownLatch(1);
        Bitmap first = Bitmap.createBitmap(2, 2, Bitmap.Config.ARGB_8888);
        Bitmap queued = Bitmap.createBitmap(2, 2, Bitmap.Config.ARGB_8888);
        Bitmap overflow = Bitmap.createBitmap(2, 2, Bitmap.Config.ARGB_8888);
        try {
            boolean accepted = RejectedCaptureAudit.scheduleOwned(first, worker, () -> {
                running.countDown();
                try {
                    if (!release.await(5, TimeUnit.SECONDS)) throw new IllegalStateException("test_worker_release_timeout");
                } catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt();
                    throw new IllegalStateException("test_worker_interrupted", interrupted);
                }
            });
            check(checks, "async_worker_holds_running_bitmap_until_finally", accepted
                    && running.await(2, TimeUnit.SECONDS) && !first.isRecycled());
            boolean enqueued = RejectedCaptureAudit.scheduleOwned(queued, worker, () -> { });
            boolean refused = !RejectedCaptureAudit.scheduleOwned(overflow, worker, () -> {
                throw new IllegalStateException("overflow_must_not_execute");
            });
            check(checks, "async_queue_is_one_and_overflow_is_recycled", enqueued && !queued.isRecycled()
                    && worker.getQueue().size() == 1 && refused && overflow.isRecycled());
            release.countDown();
            worker.shutdown();
            check(checks, "async_completed_and_queued_bitmaps_recycled", worker.awaitTermination(3, TimeUnit.SECONDS)
                    && first.isRecycled() && queued.isRecycled());
        } finally {
            release.countDown(); worker.shutdown(); worker.awaitTermination(3, TimeUnit.SECONDS);
            if (!first.isRecycled()) first.recycle();
            if (!queued.isRecycled()) queued.recycle();
            if (!overflow.isRecycled()) overflow.recycle();
        }
        Bitmap rejected = Bitmap.createBitmap(2, 2, Bitmap.Config.ARGB_8888);
        boolean scheduled = RejectedCaptureAudit.scheduleOwned(rejected, task -> {
            throw new RejectedExecutionException("synthetic_schedule_failure");
        }, () -> { throw new IllegalStateException("rejected_task_must_not_execute"); });
        check(checks, "async_scheduling_failure_recycles_without_throwing", !scheduled && rejected.isRecycled());
        Bitmap failed = Bitmap.createBitmap(2, 2, Bitmap.Config.ARGB_8888);
        boolean delivered = RejectedCaptureAudit.scheduleOwned(failed, Runnable::run, () -> {
            throw new IllegalStateException("synthetic_audit_write_failure");
        });
        check(checks, "async_audit_failure_recycles_without_throwing", delivered && failed.isRecycled());
    }

    private static JSONObject read(File file) throws Exception {
        return new JSONObject(new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8));
    }

    private static int groupCount(File root) {
        File[] children = root.listFiles((dir, name) -> name.startsWith("capture-"));
        return children == null ? 0 : children.length;
    }

    private static boolean pairedOnly(File root) {
        File[] children = root.listFiles();
        if (children == null) return false;
        for (File child : children) {
            File[] files = child.listFiles();
            if (!child.getName().startsWith("capture-") || files == null || files.length != 2
                    || !new File(child, "audit.json").isFile() || !new File(child, "source-copy.png").isFile()) return false;
        }
        return true;
    }

    private static long bytes(File file) {
        if (file.isFile()) return file.length();
        long total = 0;
        File[] children = file.listFiles();
        if (children != null) for (File child : children) total += bytes(child);
        return total;
    }

    private static void cleanup(File file) throws Exception {
        File[] children = file.listFiles();
        if (children != null) for (File child : children) cleanup(child);
        if (file.exists() && !file.delete()) throw new IllegalStateException("test_cleanup_failed");
    }

    private static void check(JSONArray checks, String name, boolean passed) throws Exception {
        checks.put(new JSONObject().put("name", name).put("passed", passed));
        if (!passed) throw new IllegalStateException(name);
    }
}
