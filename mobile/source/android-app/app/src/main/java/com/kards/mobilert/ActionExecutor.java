package com.kards.mobilert;

/**
 * Boundary for future Accessibility dispatch.  Implementations must gate an
 * action with a fresh BoardObservation and report whether input was sent.
 */
public interface ActionExecutor {
    ActionResult execute(ActionRequest request, BoardObservation observation);
}
