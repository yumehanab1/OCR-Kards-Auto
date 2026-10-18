package com.kards.mobilert;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

/** Pure concurrent checks. No Android calls, launches or device input. */
public final class DispatchAttemptChecks {
    private static int checks;
    private static void expect(boolean ok, String message) {
        checks++;
        if (!ok) throw new AssertionError(message);
    }
    private static void await(CountDownLatch latch) throws Exception {
        if (!latch.await(3, TimeUnit.SECONDS)) throw new AssertionError("test latch timed out");
    }
    private static void join(Thread thread, AtomicReference<Throwable> failure) throws Exception {
        thread.join(3000);
        if (thread.isAlive()) throw new AssertionError("test thread did not finish");
        if (failure.get() != null) throw new AssertionError("test worker failed", failure.get());
    }

    public static int runChecks() throws Exception {
        checks = 0;
        DispatchAttempt attempt = new DispatchAttempt();
        expect(attempt.isPreparing(), "new attempt prepares without implying input");
        CountDownLatch blocked = new CountDownLatch(1), resume = new CountDownLatch(1);
        AtomicBoolean submitted = new AtomicBoolean(true);
        AtomicReference<Throwable> threadFailure = new AtomicReference<>();
        final DispatchAttempt queued = attempt;
        Thread delayedMain = new Thread(() -> {
            try { blocked.countDown(); await(resume); submitted.set(queued.trySubmit(8100)); }
            catch (Throwable error) { threadFailure.set(error); }
        }, "dispatch-check-delayed-main");
        delayedMain.start();
        await(blocked);
        DispatchAttempt.Result terminal = attempt.timeout("gesture_callback_timeout", 8000);
        expect(terminal.state == DispatchAttempt.State.TIMED_OUT_BEFORE_INPUT
                        && !terminal.accepted && !terminal.inputUncertain,
                "timeout wins while main is blocked before input");
        expect("dispatch_prepare_timeout_before_input".equals(terminal.reason),
                "preparation timeout has its own precise reason");
        expect("dispatch_interrupted_before_input".equals(DispatchAttempt.interruptionReason(terminal)),
                "interruption of a queued timeout remains known no input");
        resume.countDown(); join(delayedMain, threadFailure);
        expect(!submitted.get() && !attempt.trySubmit(8200), "late main task can never claim input");
        expect(!attempt.callback(true, 8300) && attempt.result() == terminal,
                "spurious late callback cannot rewrite no-input timeout");

        attempt = new DispatchAttempt();
        CountDownLatch claimed = new CountDownLatch(1), releaseSubmission = new CountDownLatch(1);
        final DispatchAttempt submitting = attempt;
        threadFailure.set(null);
        Thread inPlatform = new Thread(() -> {
            try {
                if (!submitting.trySubmit(1)) throw new AssertionError("first claim lost");
                claimed.countDown(); await(releaseSubmission);
                submitting.submissionReturned(true, 9000);
            } catch (Throwable error) { threadFailure.set(error); }
        }, "dispatch-check-platform");
        inPlatform.start(); await(claimed);
        terminal = attempt.timeout("gesture_callback_timeout", 8000);
        expect(terminal.state == DispatchAttempt.State.TIMED_OUT_INPUT_UNCERTAIN
                        && terminal.inputUncertain && !terminal.accepted,
                "claim before platform return remains uncertain at timeout");
        expect("gesture_callback_timeout".equals(terminal.reason), "in-flight reason remains compatible");
        expect("dispatch_interrupted_input_status_uncertain".equals(DispatchAttempt.interruptionReason(terminal)),
                "interruption during platform submission remains uncertain");
        releaseSubmission.countDown(); join(inPlatform, threadFailure);
        expect(attempt.result() == terminal && !attempt.callback(true, 9001),
                "late acceptance and callback cannot erase uncertainty");
        expect(!attempt.trySubmit(9002), "an in-flight timeout cannot resubmit");

        attempt = new DispatchAttempt();
        expect(attempt.trySubmit(1), "fresh attempt claims once");
        expect(!attempt.trySubmit(2), "duplicate submission cannot claim");
        attempt.submissionReturned(true, 3);
        terminal = attempt.timeout("settle_callback_timeout", 8000);
        expect(terminal.accepted && terminal.inputUncertain && !terminal.completed,
                "known platform acceptance remains counted during callback timeout");
        expect("settle_callback_timeout".equals(terminal.reason), "settlement keeps in-flight reason");

        attempt = new DispatchAttempt(); attempt.trySubmit(1); attempt.submissionReturned(true, 2);
        expect(attempt.callback(true, 3), "first completion accepted");
        terminal = attempt.result();
        expect(terminal.completed && terminal.accepted && !terminal.inputUncertain,
                "completion preserves existing success response");
        expect(attempt.timeout("gesture_callback_timeout", 4) == terminal,
                "callback at await boundary wins over a later timeout CAS");
        expect("dispatch_interrupted_after_completed_input".equals(DispatchAttempt.interruptionReason(terminal)),
                "simultaneous interrupt and completed callback never claim no input");
        expect(!attempt.callback(false, 5) && !attempt.callback(true, 6)
                        && attempt.result() == terminal, "duplicate conflicting callbacks ignored");

        attempt = new DispatchAttempt(); attempt.trySubmit(1);
        expect(attempt.callback(true, 2), "callback may arrive at submission-return boundary");
        terminal = attempt.result(); attempt.submissionReturned(true, 3);
        expect(attempt.result() == terminal && terminal.completed,
                "submission return does not replace a winning callback");

        attempt = new DispatchAttempt(); attempt.trySubmit(1); attempt.submissionReturned(true, 2);
        expect(attempt.callback(false, 3), "cancel callback accepted once");
        terminal = attempt.result();
        expect(terminal.accepted && !terminal.completed && terminal.inputUncertain
                        && "gesture_cancelled".equals(terminal.reason), "cancel remains uncertain and counted");
        expect(attempt.timeout("gesture_callback_timeout", 4) == terminal,
                "callback cancellation not misreported as timeout");
        expect("dispatch_interrupted_input_status_uncertain".equals(DispatchAttempt.interruptionReason(terminal)),
                "interrupt after cancelled accepted gesture stays uncertain");

        attempt = new DispatchAttempt(); attempt.trySubmit(1); attempt.submissionReturned(false, 2);
        terminal = attempt.result();
        expect(terminal.state == DispatchAttempt.State.REJECTED && !terminal.accepted
                        && !terminal.inputUncertain, "platform refusal is known no input");
        expect(!attempt.callback(true, 3) && attempt.timeout("unused", 4) == terminal,
                "platform refusal cannot be overwritten by a late callback or timeout");

        attempt = new DispatchAttempt(); attempt.rejectPreparation("capture_expired", 1);
        terminal = attempt.result();
        expect(!terminal.inputUncertain && "capture_expired".equals(terminal.reason)
                        && !attempt.trySubmit(2), "preparation guard rejection stays no input");
        expect(attempt.timeout("unused", 3) == terminal, "guard result survives boundary timeout");
        attempt = new DispatchAttempt(); attempt.fail("boundary", 1);
        expect(!attempt.result().inputUncertain && !attempt.trySubmit(2),
                "exception before claim proves no input");
        attempt = new DispatchAttempt(); attempt.trySubmit(1); attempt.fail("boundary", 2);
        expect(attempt.result().inputUncertain && !attempt.result().accepted,
                "exception within submission cannot prove no input");
        attempt = new DispatchAttempt(); attempt.trySubmit(1); attempt.submissionReturned(true, 2);
        attempt.fail("boundary", 3);
        expect(attempt.result().accepted && attempt.result().inputUncertain,
                "exception after acceptance preserves real acceptance");

        // Exercise the actual claim-vs-timeout CAS simultaneously, without sleeps.
        for (int run = 0; run < 100; run++) {
            final DispatchAttempt raced = new DispatchAttempt();
            CountDownLatch go = new CountDownLatch(1);
            AtomicBoolean won = new AtomicBoolean();
            AtomicReference<DispatchAttempt.Result> timed = new AtomicReference<>();
            threadFailure.set(null);
            Thread submitter = new Thread(() -> {
                try { await(go); won.set(raced.trySubmit(1)); }
                catch (Throwable error) { threadFailure.set(error); }
            });
            Thread timer = new Thread(() -> {
                try { await(go); timed.set(raced.timeout("gesture_callback_timeout", 2)); }
                catch (Throwable error) { threadFailure.set(error); }
            });
            submitter.start(); timer.start(); go.countDown();
            join(submitter, threadFailure); join(timer, threadFailure);
            expect(timed.get().inputUncertain == won.get(),
                    "only claim winner can yield uncertain timeout, race " + run);
            expect((timed.get().state == DispatchAttempt.State.TIMED_OUT_BEFORE_INPUT) != won.get(),
                    "exactly one no-input/submission state wins, race " + run);
            expect(!raced.trySubmit(3), "neither race outcome permits another input, race " + run);
        }
        attempt = new DispatchAttempt();
        for (int i = 0; i < 100; i++) attempt.stage("stage", i);
        expect(attempt.stages().size() == DispatchAttempt.MAX_STAGES, "in-memory diagnostic bound");
        attempt.stages().clear();
        expect(attempt.stages().size() == DispatchAttempt.MAX_STAGES, "diagnostic snapshots independent");
        return checks;
    }

    public static void main(String[] args) throws Exception {
        System.out.println("Dispatch attempt: " + runChecks() + " checks passed; inputs=0");
    }
}
