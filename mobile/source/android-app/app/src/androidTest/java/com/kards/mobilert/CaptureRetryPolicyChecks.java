package com.kards.mobilert;

/** Pure policy checks; no capture requests, game launches or device inputs. */
public final class CaptureRetryPolicyChecks {
    private static int checks;
    private static final String INCOMPLETE = "compat_capture_incomplete_frame";
    private static final String BLACK = "capture_black_frame";
    private static final String WINDOW = "temporary_window_capture_error";

    private static void expect(boolean condition, String reason) {
        checks++;
        if (!condition) throw new AssertionError(reason);
    }

    public static int runChecks() {
        checks = 0;
        Scenario recovered = scenario(INCOMPLETE, "ok");
        expect(recovered.recovered && recovered.attempts == 2 && recovered.retries == 1,
                "one incomplete frame recovers only after a new successful attempt");
        recovered = scenario(INCOMPLETE, BLACK, WINDOW, "ok");
        expect(recovered.recovered && recovered.attempts == 4 && recovered.retries == 3,
                "three different failures share three retries before recovery");
        Scenario failed = scenario(INCOMPLETE, INCOMPLETE, INCOMPLETE, INCOMPLETE, "ok");
        expect(!failed.recovered && failed.attempts == 4 && failed.retries == 3,
                "persistent incomplete stops after initial attempt plus three retries");
        expect(INCOMPLETE.equals(failed.reason), "incomplete reason survives exhaustion");
        failed = scenario(BLACK, BLACK, BLACK, BLACK, "ok");
        expect(!failed.recovered && failed.attempts == 4 && BLACK.equals(failed.reason),
                "black frame retains previous terminal reason and bound");
        failed = scenario(WINDOW, WINDOW, WINDOW, WINDOW, "ok");
        expect(!failed.recovered && failed.attempts == 4
                        && "window_capture_retry_exhausted".equals(failed.reason),
                "window failure retains previous terminal reason and bound");
        failed = scenario(BLACK, WINDOW, INCOMPLETE, INCOMPLETE, "ok");
        expect(!failed.recovered && failed.attempts == 4 && failed.retries == 3
                        && INCOMPLETE.equals(failed.reason),
                "failure type changes cannot reset the shared retry budget");
        failed = scenario(INCOMPLETE, BLACK, INCOMPLETE, WINDOW, "ok");
        expect(!failed.recovered && failed.retries == 3
                        && "window_capture_retry_exhausted".equals(failed.reason),
                "mixed exhaustion preserves the last failure type");
        for (String reason : new String[]{"foreground_changed", "time_budget", "cancelled",
                "compat_capture_geometry_changed", "compat_capture_timeout", "capture_timeout",
                "compat_capture_revoked", "unsupported_frame_size", "capture_black_frame_suffix"}) {
            failed = scenario(reason, "ok");
            expect(!failed.recovered && failed.attempts == 1 && failed.retries == 0
                            && reason.equals(failed.reason), "nonretryable rejection: " + reason);
        }
        CaptureRetryPolicy policy = new CaptureRetryPolicy();
        CaptureRetryPolicy.Decision decision = policy.onFailure(INCOMPLETE, true, false);
        expect(!decision.retry && !decision.exhausted && decision.retriesUsed == 0
                        && "cancelled".equals(decision.reason), "cancel does not spend a retry");
        decision = policy.onFailure(BLACK, false, true);
        expect(!decision.retry && !decision.exhausted && decision.retriesUsed == 0
                        && "time_budget".equals(decision.reason), "deadline does not spend a retry");
        decision = policy.onFailure(WINDOW, true, true);
        expect(!decision.retry && "cancelled".equals(decision.reason), "cancel wins over deadline");
        decision = policy.onFailure(INCOMPLETE, false, false);
        expect(decision.retry && decision.retriesUsed == 1,
                "cancel and deadline decisions do not consume retry slots");
        for (int retry = 2; retry <= CaptureRetryPolicy.MAX_RETRIES; retry++) {
            decision = policy.onFailure(INCOMPLETE, false, false);
            expect(decision.retry && decision.retriesUsed == retry, "exact retry number " + retry);
        }
        decision = policy.onFailure(INCOMPLETE, false, false);
        expect(!decision.retry && decision.exhausted && decision.retriesUsed == 3,
                "fourth transient failure exhausts the policy");
        decision = policy.onFailure(BLACK, true, false);
        expect(!decision.retry && !decision.exhausted && "cancelled".equals(decision.reason),
                "cancellation remains authoritative after retry exhaustion");
        decision = new CaptureRetryPolicy().onFailure(INCOMPLETE, false, false);
        expect(decision.retry && decision.retriesUsed == 1, "new capture call gets a fresh retry budget");
        expect(!CaptureRetryPolicy.isRetryable(null), "missing reason cannot retry");
        return checks;
    }

    private static Scenario scenario(String... results) {
        CaptureRetryPolicy policy = new CaptureRetryPolicy();
        Scenario scenario = new Scenario();
        for (String reason : results) {
            scenario.attempts++;
            if ("ok".equals(reason)) {
                scenario.recovered = true;
                return scenario;
            }
            CaptureRetryPolicy.Decision decision = policy.onFailure(reason, false, false);
            scenario.retries = decision.retriesUsed;
            scenario.reason = decision.reason;
            if (!decision.retry) return scenario;
        }
        throw new AssertionError("scenario did not reach success or terminal failure");
    }

    private static final class Scenario {
        boolean recovered;
        int attempts;
        int retries;
        String reason;
    }

    public static void main(String[] args) {
        System.out.println("Capture retry policy: " + runChecks() + " checks passed; inputs=0");
    }
}
