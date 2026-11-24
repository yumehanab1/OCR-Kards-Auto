package com.kards.mobilert;

import android.graphics.Bitmap;
import android.graphics.Rect;
import java.io.File;
import java.util.PriorityQueue;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;

/** Actual worker/latch checks; foreground and gestures are entirely synthetic. */
public final class MulliganConcurrencyChecks {
    public static void run(File root) throws Exception {
        for (String mode : new String[]{"cancel", "watchdog", "expired", "foreground"}) check(root, mode);
    }

    private static void check(File root, String mode) throws Exception {
        AtomicLong time = new AtomicLong();
        BoundedMulliganSession.Clock clock = new BoundedMulliganSession.Clock() {
            public long wallTimeMillis() { return 1_800_000_000_000L + time.get(); }
            public long elapsedRealtimeMillis() { return time.get(); }
        };
        Queue scheduler = new Queue(time);
        AtomicInteger taps = new AtomicInteger();
        AtomicLong foreground = new AtomicLong(1);
        BoundedMulliganSession.Platform platform = new BoundedMulliganSession.Platform() {
            public String currentForegroundPackage() { return BoundedMulliganSession.GAME_PACKAGE; }
            public long foregroundGeneration() { return foreground.get(); }
            public boolean dispatchTap(float x, float y, BoundedMulliganSession.TapCallback callback) {
                taps.incrementAndGet(); return true;
            }
        };
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        AtomicReference<Bitmap> bitmap = new AtomicReference<>();
        FrameSource source = callback -> {
            Bitmap image = Bitmap.createBitmap(1280, 720, Bitmap.Config.ARGB_8888);
            image.eraseColor(0xff303030); bitmap.set(image);
            callback.onFrame(new FrameSnapshot(image, clock.wallTimeMillis()));
        };
        AtomicReference<BoundedMulliganSession> current = new AtomicReference<>();
        AtomicReference<String> report = new AtomicReference<>("");
        AtomicReference<Throwable> failure = new AtomicReference<>();
        Thread main = Thread.currentThread();
        ExecutorService worker = Executors.newSingleThreadExecutor();
        BoundedMulliganSession session = new BoundedMulliganSession(root, source, platform, image -> {
            try {
                require(Thread.currentThread() != main && !Thread.holdsLock(current.get()), "Inspector is unlocked background work");
                entered.countDown();
                require(release.await(5, TimeUnit.SECONDS), "Release timeout");
            } catch (Throwable error) { failure.set(error); }
            return new MulliganRecognizer.Result(MulliganRecognizer.Phase.MULLIGAN_CONFIRM,
                    new Rect(600, 630, 680, 674), 1, "synthetic", "confirm");
        }, clock, scheduler, report::set,
                new GameEntryGate(GameEntryGate.CURRENT_GAME, platform.currentForegroundPackage(), 1, 0), () -> worker);
        current.set(session);
        try {
            require(session.start(), "Session starts");
            // Pump only through capture delivery, then deliberately leave inference blocked.
            while (bitmap.get() == null) scheduler.next();
            scheduler.drainDue();
            require(entered.await(5, TimeUnit.SECONDS), "Worker entered inspection");
            if (mode.equals("cancel")) {
                Thread cancel = new Thread(session::cancel);
                cancel.start(); cancel.join(1000);
                require(!cancel.isAlive() && !session.isRunning(), "Cancellation is not blocked by inference");
            } else if (mode.equals("watchdog")) {
                time.set(BoundedMulliganSession.TIME_BUDGET_MS);
                while (session.isRunning()) scheduler.next();
                require(report.get().contains("time_budget"), "Watchdog runs while inference is blocked");
            } else if (mode.equals("foreground")) {
                foreground.incrementAndGet();
                while (session.isRunning()) scheduler.next();
                require(report.get().contains("foreground_changed"), "Foreground watchdog remains live");
            } else time.addAndGet(BoundedMulliganSession.MAX_FRAME_AGE_MS + 1);
            release.countDown();
            if (mode.equals("expired")) {
                // Wait for worker handoff before advancing virtual time through other watchdogs.
                worker.submit(() -> { }).get(5, TimeUnit.SECONDS);
                while (session.isRunning()) scheduler.next();
                require(report.get().contains("frame_expired_during_processing"), "Freshness rechecked after worker");
            }
            require(worker.awaitTermination(5, TimeUnit.SECONDS), "Finished worker shuts down");
            scheduler.drainDue();
            require(taps.get() == 0 && bitmap.get().isRecycled(), "Late inspection cannot tap and releases frame");
            require(failure.get() == null, "Worker assertion: " + failure.get());
        } finally { release.countDown(); session.cancel(); worker.shutdownNow(); }
    }

    private static final class Queue implements BoundedMulliganSession.Scheduler {
        final AtomicLong time;
        final PriorityQueue<Task> tasks = new PriorityQueue<>();
        long order;
        Queue(AtomicLong time) { this.time = time; }
        public synchronized void postDelayed(Runnable work, long delay) { tasks.add(new Task(time.get() + delay, ++order, work)); notifyAll(); }
        void next() throws Exception {
            Task task;
            synchronized (this) {
                if (tasks.isEmpty()) wait(5000);
                require(!tasks.isEmpty(), "Scheduler timeout"); task = tasks.remove();
            }
            time.accumulateAndGet(task.at, Math::max); task.work.run();
        }
        void drainDue() throws Exception {
            while (true) {
                synchronized (this) { if (tasks.isEmpty() || tasks.peek().at > time.get()) return; }
                next();
            }
        }
    }
    private static final class Task implements Comparable<Task> {
        final long at, order;
        final Runnable work;
        Task(long at, long order, Runnable work) { this.at = at; this.order = order; this.work = work; }
        public int compareTo(Task other) { int cmp = Long.compare(at, other.at); return cmp == 0 ? Long.compare(order, other.order) : cmp; }
    }
    private static void require(boolean value, String why) { if (!value) throw new AssertionError(why); }
}
