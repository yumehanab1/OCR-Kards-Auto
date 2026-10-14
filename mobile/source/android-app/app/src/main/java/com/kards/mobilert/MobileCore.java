package com.kards.mobilert;

/** Read-only observation boundary for the future Android combat engine. */
public interface MobileCore {
    BoardObservation observe(FrameSnapshot snapshot);
}
