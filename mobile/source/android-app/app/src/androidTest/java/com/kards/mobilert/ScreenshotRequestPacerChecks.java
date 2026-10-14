package com.kards.mobilert;

/** Clock and burst regressions, also runnable without an Android device. */
public final class ScreenshotRequestPacerChecks {
    private static int checks;

    private static void expect(long actual, long expected, String reason) {
        checks++;
        if (actual != expected) throw new AssertionError(reason + ": " + actual);
    }

    public static int runChecks() {
        checks = 0;
        ScreenshotRequestPacer shared = new ScreenshotRequestPacer();
        expect(shared.acquireDelay(1000), 0, "first opening screenshot");
        expect(shared.acquireDelay(1000), 400, "simultaneous caller waits");
        expect(shared.acquireDelay(1100), 300, "battle handover keeps opening slot");
        expect(shared.acquireDelay(1399), 1, "early retry still waits");
        expect(shared.acquireDelay(1400), 0, "first battle screenshot admitted");
        expect(shared.acquireDelay(1400), 400, "native failure cannot bypass admission");
        expect(shared.acquireDelay(1800), 0, "next real attempt after failure");
        expect(shared.acquireDelay(5000), 0, "idle caller has no extra delay");
        expect(shared.acquireDelay(4000), 400, "backward clock cannot admit");
        expect(shared.acquireDelay(5399), 1, "backward clock did not reset slot");
        expect(shared.acquireDelay(5400), 0, "monotonic clock recovered");
        for (int i = 0; i < 8; i++) {
            expect(shared.acquireDelay(5400), 400, "waiting callers cannot reserve same slot");
        }
        expect(shared.acquireDelay(5800), 0, "only one waiting caller admitted");
        expect(shared.acquireDelay(5800), 400, "second waiting caller reschedules");
        return checks;
    }

    public static void main(String[] args) {
        System.out.println("Screenshot pacer: " + runChecks() + " checks passed; inputs=0");
    }
}
