package com.kards.mobilert;

import android.graphics.Rect;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * Conservative board-state contract shared by the Android adapter and the
 * future visual/strategy core.  Unknown observations never authorize input.
 */
public final class BoardObservation {
    public enum State {
        UNKNOWN,
        NON_GAME,
        IN_GAME,
        MY_TURN,
        OPPONENT_TURN,
        VICTORY,
        DEFEAT
    }

    /** Coarse row ownership.  A visual adapter must leave this UNKNOWN when
     * the divider or the card row is not clear enough to trust. */
    public enum FrontlineOwner {
        UNKNOWN,
        EMPTY,
        MINE,
        OPPONENT,
        CONTESTED
    }

    /** A geometry-only candidate.  It is never an authorization to act. */
    public static final class Candidate {
        public enum Kind { HQ, FRONTLINE, SUPPORT, END_TURN }

        private final Kind kind;
        private final Rect bounds;
        private final int confidencePermille;

        public Candidate(Kind kind, Rect bounds, int confidencePermille) {
            this.kind = kind == null ? Kind.SUPPORT : kind;
            this.bounds = bounds == null ? new Rect() : new Rect(bounds);
            this.confidencePermille = Math.max(0, Math.min(1000, confidencePermille));
        }

        public Kind kind() { return kind; }
        public Rect bounds() { return new Rect(bounds); }
        public int confidencePermille() { return confidencePermille; }
    }

    private final State state;
    private final boolean actionAuthorized;
    private final String reason;
    private final boolean gameScreen;
    private final boolean endTurnVisible;
    private final FrontlineOwner frontlineOwner;
    private final List<Candidate> candidates;

    private BoardObservation(State state, boolean actionAuthorized, String reason) {
        this(state, actionAuthorized, reason, state == State.IN_GAME || state == State.MY_TURN
                        || state == State.OPPONENT_TURN,
                false, FrontlineOwner.UNKNOWN, Collections.<Candidate>emptyList());
    }

    private BoardObservation(State state, boolean actionAuthorized, String reason,
                             boolean gameScreen, boolean endTurnVisible,
                             FrontlineOwner frontlineOwner, List<Candidate> candidates) {
        this.state = state == null ? State.UNKNOWN : state;
        // A missing/unknown state can never authorize an action.  The first
        // APK core is read-only, so callers should keep this false as well.
        this.actionAuthorized = this.state != State.UNKNOWN && actionAuthorized;
        this.reason = reason == null ? "未提供原因" : reason;
        this.gameScreen = gameScreen && this.state != State.NON_GAME;
        this.endTurnVisible = endTurnVisible;
        this.frontlineOwner = frontlineOwner == null ? FrontlineOwner.UNKNOWN : frontlineOwner;
        ArrayList<Candidate> copy = new ArrayList<>();
        if (candidates != null) copy.addAll(candidates);
        this.candidates = Collections.unmodifiableList(copy);
    }

    public static BoardObservation unknown(String reason) {
        return new BoardObservation(State.UNKNOWN, false, reason);
    }

    public static BoardObservation of(State state, boolean actionAuthorized, String reason) {
        return new BoardObservation(state, actionAuthorized, reason);
    }

    /** Factory used by the conservative Bitmap recognizer. */
    public static BoardObservation recognized(State state, String reason,
                                              boolean gameScreen, boolean endTurnVisible,
                                              FrontlineOwner frontlineOwner,
                                              List<Candidate> candidates) {
        // The first Android adapter is read-only.  Keep this false even when a
        // later recognizer learns enough geometry to describe an action.
        return new BoardObservation(state, false, reason, gameScreen, endTurnVisible,
                frontlineOwner, candidates);
    }

    public State state() {
        return state;
    }

    public boolean isActionAuthorized() {
        return actionAuthorized;
    }

    public String reason() {
        return reason;
    }

    public boolean isGameScreen() { return gameScreen; }

    public boolean isEndTurnVisible() { return endTurnVisible; }

    public FrontlineOwner frontlineOwner() { return frontlineOwner; }

    public List<Candidate> candidates() { return candidates; }

    public String displayState() {
        return state.name();
    }
}
