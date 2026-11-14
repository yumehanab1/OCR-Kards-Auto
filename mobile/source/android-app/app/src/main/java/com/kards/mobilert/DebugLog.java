package com.kards.mobilert;

import android.content.Context;
import android.os.Build;

import java.io.File;
import java.io.FileWriter;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.text.SimpleDateFormat;
import java.util.ArrayDeque;
import java.util.Date;
import java.util.Locale;

final class DebugLog {
    private static final int LIMIT = 4000;
    private static final long FILE_LIMIT = 4L * 1024 * 1024;
    private static final ArrayDeque<String> lines = new ArrayDeque<>();
    private static final SimpleDateFormat clock = new SimpleDateFormat("HH:mm:ss.SSS", Locale.ROOT);
    private static File file;

    private DebugLog() { }

    static synchronized void init(Context context) {
        if (file == null) {
            File directory = new File(context.getFilesDir(), "debug");
            directory.mkdirs();
            file = new File(directory, "kards.log");
        }
    }

    static synchronized void log(String tag, String message) {
        String line = clock.format(new Date()) + " [" + Thread.currentThread().getName()
                + "] " + tag + " | " + message;
        lines.addLast(line);
        while (lines.size() > LIMIT) lines.removeFirst();
        append(line);
    }

    static void error(String tag, String message, Throwable error) {
        StringWriter buffer = new StringWriter();
        if (error != null) error.printStackTrace(new PrintWriter(buffer));
        log(tag, message + (error == null ? "" : "\n" + buffer));
    }

    static void device(Context context) {
        log("DEVICE", "model=" + Build.MODEL + " sdk=" + Build.VERSION.SDK_INT
                + " release=" + Build.VERSION.RELEASE + " abi=" + Build.SUPPORTED_ABIS[0]
                + " density=" + context.getResources().getDisplayMetrics().density
                + " brand=" + Build.BRAND + " manufacturer=" + Build.MANUFACTURER);
    }

    private static void append(String line) {
        if (file == null) return;
        try {
            if (file.exists() && file.length() > FILE_LIMIT) {
                File rotated = new File(file.getParentFile(), "kards.1.log");
                if (rotated.exists()) rotated.delete();
                file.renameTo(rotated);
            }
            FileWriter writer = new FileWriter(file, true);
            writer.write(line);
            writer.write('\n');
            writer.close();
        } catch (Exception ignored) { }
    }

    static synchronized String snapshot() {
        StringBuilder out = new StringBuilder();
        for (String line : lines) out.append(line).append('\n');
        return out.toString();
    }

    static synchronized int count() { return lines.size(); }

    /** Keeps one diagnostic line readable while preserving both ends of long payloads. */
    static String clip(String value) {
        if (value == null) return "";
        String text = value.replace('\n', ' ');
        if (text.length() <= 700) return text;
        return text.substring(0, 420) + " ... " + text.substring(text.length() - 260);
    }

    static synchronized void clear() {
        lines.clear();
        if (file != null) {
            try { new FileWriter(file, false).close(); }
            catch (Exception ignored) { }
        }
        log("LOG", "日志已清空");
    }

    static String path() { return file == null ? "" : file.getAbsolutePath(); }

    static synchronized String fileText() {
        if (file == null || !file.exists()) return snapshot();
        try {
            return new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8);
        } catch (Exception error) { return snapshot(); }
    }
}
