package com.kards.mobilert;

import android.annotation.TargetApi;
import android.app.Activity;
import android.graphics.Rect;
import android.os.Build;
import android.util.DisplayMetrics;
import android.view.WindowManager;

import java.util.Collections;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Host checks for the dispatch/ownership contract, plus a device-only bounds check. */
public final class Api29CompatChecks {
    private int checks;

    public static void main(String[] args) {
        Api29CompatChecks test = new Api29CompatChecks();
        test.displayRoute();
        test.emptyCombatLists();
        test.screenshotTerminalDelivery();
        System.out.println("Api29CompatChecks: " + test.checks + " passed");
    }

    private void displayRoute() {
        Rect legacy = new Rect(0, 0, 1280, 720);
        Rect modern = new Rect(4, 8, 1604, 1208);
        check("API 29 reads only real-display metrics", DisplayBounds.select(29, () -> legacy,
                () -> { throw new AssertionError("API 29 touched window metrics"); }) == legacy);
        for (int sdk : new int[]{30, 34, 35}) {
            check("API " + sdk + " reads only current-window metrics", DisplayBounds.select(sdk,
                    () -> { throw new AssertionError("Modern Android touched real-display metrics"); },
                    () -> modern) == modern);
        }
    }

    @SuppressWarnings("deprecation")
    static void displayOnDevice(Activity activity) {
        WindowManager windows = activity.getWindowManager();
        Rect expected;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            expected = BoundsApi30.get(windows);
        } else {
            DisplayMetrics metrics = new DisplayMetrics();
            windows.getDefaultDisplay().getRealMetrics(metrics);
            expected = new Rect(0, 0, metrics.widthPixels, metrics.heightPixels);
        }
        Rect actual = DisplayBounds.get(windows);
        if (actual.isEmpty() || !actual.equals(expected)) throw new AssertionError("Wrong display bounds: " + actual);
    }

    @TargetApi(30)
    private static final class BoundsApi30 {
        static Rect get(WindowManager windows) { return windows.getCurrentWindowMetrics().getBounds(); }
    }

    private void emptyCombatLists() {
        CombatPolicy.Observation observation = new CombatPolicy.Observation(null, null, null, null,
                Collections.emptyList(), null);
        check("Missing guards remain unknown with an empty list",
                observation.guard().status() == CombatPolicy.GuardStatus.UNKNOWN && observation.guard().guards().isEmpty());
        check("Null or empty combat inputs stay empty", observation.units().isEmpty() && observation.enemyFront().isEmpty());
        try {
            observation.guard().guards().add(null);
            throw new AssertionError("Empty combat list is mutable");
        } catch (UnsupportedOperationException expected) {
            checks++;
        }
    }

    private void screenshotTerminalDelivery() {
        // The display and API 34 window adapters both deliver through this terminal receiver.
        RuntimeException downstream = new IllegalStateException("consumer failed");
        AtomicInteger successes = new AtomicInteger(), failures = new AtomicInteger(), discards = new AtomicInteger();
        SystemScreenshotApi30.Terminal terminal = new SystemScreenshotApi30.Terminal(reason -> failures.incrementAndGet());
        try {
            terminal.request(() -> terminal.success(() -> {
                successes.incrementAndGet();
                throw downstream;
            }, discards::incrementAndGet));
            throw new AssertionError("Consumer exception did not propagate");
        } catch (RuntimeException actual) {
            check("Consumer exception is not converted into a request failure", actual == downstream);
        }
        terminal.failure("duplicate platform failure");
        terminal.success(successes::incrementAndGet, discards::incrementAndGet);
        check("Success transfers ownership once; duplicate pixels are discarded",
                successes.get() == 1 && failures.get() == 0 && discards.get() == 1);

        SystemScreenshotApi30.Terminal failure = new SystemScreenshotApi30.Terminal(reason -> {
            failures.incrementAndGet();
            throw downstream;
        });
        try {
            failure.request(() -> failure.failure("platform failure"));
            throw new AssertionError("Failure consumer exception did not propagate");
        } catch (RuntimeException actual) {
            check("Failure consumer exception is not reported twice", actual == downstream && failures.get() == 1);
        }
        failure.success(successes::incrementAndGet, discards::incrementAndGet);
        check("Pixels received after failure are discarded", successes.get() == 1 && discards.get() == 2);

        AtomicReference<String> report = new AtomicReference<>();
        SystemScreenshotApi30.Terminal requestFailure = new SystemScreenshotApi30.Terminal(reason -> {
            if (!report.compareAndSet(null, reason)) throw new AssertionError("Duplicate failure");
        });
        requestFailure.request(() -> { throw new SecurityException(); });
        requestFailure.failure("late callback");
        check("Platform request exception reports a single failure", report.get().contains("SecurityException"));
    }

    private void check(String name, boolean passed) {
        if (!passed) throw new AssertionError(name);
        checks++;
    }
}
