package com.kards.mobilert;

import org.json.JSONObject;
import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/** Host entry point; SDK classes compile the code, test-only graphics adapters execute mulligan checks. */
public final class JavaLayerRegressionChecks {
    public static void main(String[] args) throws Exception {
        File root = Files.createTempDirectory("kards-java-regression-").toFile();
        UpdateCheckerChecks.run();
        assets(root);
        replay();
        terminalAndCaptureOwnership();
        verify("battle_progress", BattleProgressReportChecks.run());
        verify("training_panel", TrainingPanelStateChecks.run());
        verify("mulligan", MulliganSessionChecks.run(root));
        MulliganConcurrencyChecks.run(root);
        System.out.println("J-01 through J-09 host checks PASS; evidence=" + root);
    }

    private static void assets(File root) throws Exception {
        String[] names = {"template.png", "manifest.json"};
        File assets = new File(root, "assets");
        NativeOpeningInspector.AssetOpener opener = name ->
                new ByteArrayInputStream(("new:" + name).getBytes(StandardCharsets.UTF_8));
        File old = NativeOpeningInspector.installAssets(assets, "191-1", names, opener);
        File next = NativeOpeningInspector.installAssets(assets, "192-2", names, opener);
        require(!old.equals(next) && new File(old, ".complete").isFile(), "Version directories are isolated");
        File corrupt = new File(assets, "193-3");
        require(corrupt.mkdir(), "fixture directory");
        Files.write(new File(corrupt, names[0]).toPath(), new byte[]{1});
        try {
            NativeOpeningInspector.installAssets(assets, "193-3", names, name -> new InputStream() {
                @Override public int read() throws IOException { throw new IOException("interrupted copy"); }
            });
            throw new AssertionError("Expected interrupted copy");
        } catch (IOException expected) { }
        require(!new File(corrupt, ".complete").exists(), "Failure cannot publish marker");
        NativeOpeningInspector.installAssets(assets, "193-3", names, opener);
        require(new String(Files.readAllBytes(new File(corrupt, names[0]).toPath()), StandardCharsets.UTF_8)
                .equals("new:" + names[0]), "Truncated asset replaced");
        Files.write(new File(corrupt, ".complete").toPath(), "wrong-version".getBytes(StandardCharsets.UTF_8));
        NativeOpeningInspector.installAssets(assets, "193-3", names, opener);
        require(new String(Files.readAllBytes(new File(corrupt, ".complete").toPath()), StandardCharsets.UTF_8)
                .equals("193-3"), "Marker mismatch reinstalled");
        NativeOpeningInspector.installAssets(assets, "193-3", names, name -> { throw new IOException("must reuse complete install"); });
    }

    private static void replay() throws Exception {
        BlockingQueue<Runnable> main = new LinkedBlockingQueue<>();
        AtomicBoolean alive = new AtomicBoolean(true);
        MainActivity.ReplayWorker worker = new MainActivity.ReplayWorker(Executors.newSingleThreadExecutor(), main::add, alive::get);
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        StringBuilder shown = new StringBuilder();
        Thread caller = Thread.currentThread();
        try {
            worker.submit(() -> {
                require(Thread.currentThread() != caller, "Replay off caller thread");
                entered.countDown();
                await(release);
                return "old";
            }, shown::append);
            require(entered.await(5, TimeUnit.SECONDS), "Replay entered");
            worker.submit(() -> "latest", shown::append);
            release.countDown();
            take(main).run(); take(main).run();
            require(shown.toString().equals("latest"), "Stale result ignored");
            worker.submit(() -> "destroyed", shown::append);
            Runnable completion = take(main);
            alive.set(false);
            completion.run();
            require(shown.toString().equals("latest"), "Dead activity ignored");
            alive.set(true);
            worker.submit(() -> "closed", shown::append);
            completion = take(main);
            worker.close();
            completion.run();
            require(shown.toString().equals("latest"), "Closing invalidates queued result");
        } finally { release.countDown(); worker.close(); }
    }

    /** Allocate without Android constructors: test only the real terminal/owner guards, never a service. */
    private static void terminalAndCaptureOwnership() throws Exception {
        require(Modifier.isSynchronized(ApkBattleSession.class.getDeclaredMethod("cancel", String.class).getModifiers()),
                "Cancel shares finish monitor");
        ApkBattleSession session = allocate(ApkBattleSession.class);
        set(session, "report", "finished");
        set(session, "stopReason", "done");
        AtomicBoolean cancelled = new AtomicBoolean();
        set(session, "cancelled", cancelled);
        CountDownLatch entered = new CountDownLatch(1), returned = new CountDownLatch(1);
        Thread cancel = new Thread(() -> { entered.countDown(); session.cancel("late_cancel"); returned.countDown(); });
        synchronized (session) {
            cancel.start();
            require(entered.await(5, TimeUnit.SECONDS), "Cancel thread entered");
            require(!returned.await(100, TimeUnit.MILLISECONDS), "Cancel waits for the finish monitor");
        }
        require(returned.await(5, TimeUnit.SECONDS), "Cancel exits after finish monitor released");
        session.cancel("late_cancel");
        require("finished".equals(session.report()) && !cancelled.get(), "Terminal cancel is strict no-op");
        for (String reason : new String[]{"campaign_complete", "campaign_return_unverified", "campaign_input_uncertain"}) {
            require(reason.equals(ApkBattleSession.terminalReason("casual", false, reason)), "Casual reason preserved");
            require(reason.equals(ApkBattleSession.terminalReason("ranked", false, reason)), "Ranked reason preserved");
        }
        require("engine_finished".equals(ApkBattleSession.terminalReason("training", false, "ignored")), "Legacy training");
        require("engine_finished".equals(ApkBattleSession.terminalReason("casual", true, "ignored")), "Read only");
        CompatCaptureService service = allocate(CompatCaptureService.class);
        CompatCaptureSource old = allocate(CompatCaptureSource.class), replacement = allocate(CompatCaptureSource.class);
        set(replacement, "closed", new AtomicBoolean());
        set(service, "ownedSource", replacement);
        Field active = CompatCaptureService.class.getDeclaredField("activeSource"); active.setAccessible(true);
        Object prior = active.get(null);
        try {
            active.set(null, replacement);
            require(CompatCaptureService.hasSource() && !CompatCaptureService.isReady(), "Unready source still exists");
            service.sourceStopped(old, "late callback");
            require(active.get(null) == replacement, "Old callback cannot clear replacement");
            AtomicBoolean replaced = new AtomicBoolean();
            set(service, "ownedSource", null);
            set(service, "retiringSource", old);
            active.set(null, old);
            set(service, "pendingReplacement", (Runnable) () -> replaced.set(true));
            service.sourceStopped(old, "released");
            require(replaced.get(), "Replacement waits for release callback");
            service.sourceStopped(old, "duplicate callback");
            replaced.set(false);
            active.set(null, old);
            set(service, "retiringSource", old);
            set(service, "pendingReplacement", (Runnable) () -> replaced.set(true));
            java.lang.reflect.Method shutdown = CompatCaptureService.class.getDeclaredMethod("shutdown", String.class);
            shutdown.setAccessible(true); shutdown.invoke(service, "user stop");
            service.sourceStopped(old, "late release after stop");
            require(!replaced.get() && !CompatCaptureService.hasSource(), "Stop revokes pending reauthorization");
        } finally { active.set(null, prior); }
    }

    private static <T> T allocate(Class<T> type) throws Exception {
        Class<?> unsafe = Class.forName("sun.misc.Unsafe");
        Field field = unsafe.getDeclaredField("theUnsafe"); field.setAccessible(true);
        return type.cast(unsafe.getMethod("allocateInstance", Class.class).invoke(field.get(null), type));
    }
    private static void set(Object target, String name, Object value) throws Exception {
        Field field = target.getClass().getDeclaredField(name); field.setAccessible(true); field.set(target, value);
    }
    private static Runnable take(BlockingQueue<Runnable> queue) throws Exception {
        Runnable result = queue.poll(5, TimeUnit.SECONDS);
        require(result != null, "Completion timeout"); return result;
    }
    private static void await(CountDownLatch latch) {
        try { require(latch.await(5, TimeUnit.SECONDS), "Latch timeout"); }
        catch (InterruptedException error) { Thread.currentThread().interrupt(); throw new AssertionError(error); }
    }
    private static void verify(String name, JSONObject result) throws Exception {
        System.out.println(name + ": " + result.optInt("check_count", result.optInt("case_count"))
                + " checks; failures=" + result.getInt("failure_count"));
        if (result.getInt("failure_count") != 0) System.out.println(result);
        require(result.getInt("failure_count") == 0, name + " failures");
    }
    private static void require(boolean value, String why) { if (!value) throw new AssertionError(why); }
}
