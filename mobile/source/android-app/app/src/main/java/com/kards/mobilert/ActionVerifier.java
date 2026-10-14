package com.kards.mobilert;

/** Central fail-closed gate shared by all future input implementations. */
public final class ActionVerifier {
    private ActionVerifier() { }

    public static boolean mayAttempt(BoardObservation observation) {
        return observation != null
                && observation.state() == BoardObservation.State.MY_TURN
                && observation.isGameScreen()
                && observation.isEndTurnVisible()
                && observation.isActionAuthorized()
                && observation.frontlineOwner() != BoardObservation.FrontlineOwner.UNKNOWN
                && observation.frontlineOwner() != BoardObservation.FrontlineOwner.CONTESTED;
    }
}
