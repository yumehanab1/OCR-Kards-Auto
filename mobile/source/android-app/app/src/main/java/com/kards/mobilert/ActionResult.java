package com.kards.mobilert;

/** Result of an input attempt, including a reason suitable for the audit log. */
public final class ActionResult {
    public enum Status { EXECUTED, REJECTED, VERIFICATION_FAILED }

    private final Status status;
    private final String reason;

    private ActionResult(Status status, String reason) {
        this.status = status == null ? Status.REJECTED : status;
        this.reason = reason == null ? "未提供原因" : reason;
    }

    public static ActionResult rejected(String reason) {
        return new ActionResult(Status.REJECTED, reason);
    }

    public static ActionResult verificationFailed(String reason) {
        return new ActionResult(Status.VERIFICATION_FAILED, reason);
    }

    public static ActionResult executed(String reason) {
        return new ActionResult(Status.EXECUTED, reason);
    }

    public Status status() { return status; }
    public String reason() { return reason; }
    public boolean didSendInput() { return status == Status.EXECUTED; }
}
