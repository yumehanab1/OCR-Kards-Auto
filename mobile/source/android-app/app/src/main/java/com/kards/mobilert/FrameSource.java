package com.kards.mobilert;

/** Read-only source of foreground frames.  Implementations must not send input. */
public interface FrameSource {
    void requestFrame(Callback callback);

    interface Callback {
        void onFrame(FrameSnapshot snapshot);

        void onFailure(String message);
    }
}
