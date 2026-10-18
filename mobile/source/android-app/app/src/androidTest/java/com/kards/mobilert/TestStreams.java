package com.kards.mobilert;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;

/** Test-only stream helpers for API 30+, without closing caller-owned streams. */
final class TestStreams {
    private TestStreams() { }

    static byte[] readAll(InputStream input) throws IOException {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        copy(input, output);
        return output.toByteArray();
    }

    static long copy(InputStream input, OutputStream output) throws IOException {
        byte[] buffer = new byte[8192];
        long total = 0;
        int length;
        while ((length = input.read(buffer)) != -1) {
            output.write(buffer, 0, length);
            total += length;
        }
        return total;
    }
}
