package com.kards.mobilert;

/** Read-only core backed by the dependency-free Android Bitmap recognizer. */
public final class ReadOnlyMobileCore implements MobileCore {
    private final BoardRecognizer recognizer;

    public ReadOnlyMobileCore() {
        this(new BitmapBoardRecognizer());
    }

    /** Injection point for deterministic replay/self-checks. */
    public ReadOnlyMobileCore(BoardRecognizer recognizer) {
        this.recognizer = recognizer == null ? new BitmapBoardRecognizer() : recognizer;
    }

    @Override
    public BoardObservation observe(FrameSnapshot snapshot) {
        if (snapshot == null || !snapshot.isUsable()) {
            return BoardObservation.unknown("帧为空或已释放");
        }
        return recognizer.recognize(snapshot);
    }
}
