package com.kards.mobilert;

/**
 * Visual board adapter.  Implementations must be conservative: geometry is
 * useful for diagnostics, but an uncertain frame must remain UNKNOWN.
 */
public interface BoardRecognizer {
    BoardObservation recognize(FrameSnapshot snapshot);
}
