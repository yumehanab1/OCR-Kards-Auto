import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'mobile/source/android-app/app/src/main/java/com/kards/mobilert/DisplayBounds.java'

STUBS = {
    'android/annotation/TargetApi.java': '''package android.annotation;
public @interface TargetApi { int value(); }
''',
    'android/os/Build.java': '''package android.os;
public final class Build {
    public static final class VERSION { public static int SDK_INT = 29; }
}
''',
    'android/graphics/Rect.java': '''package android.graphics;
public class Rect {
    public int left, top, right, bottom;
    public Rect() {}
    public Rect(int l, int t, int r, int b) { left=l; top=t; right=r; bottom=b; }
    public Rect(Rect o) { this(o.left, o.top, o.right, o.bottom); }
}
''',
    'android/util/DisplayMetrics.java': '''package android.util;
public class DisplayMetrics { public int widthPixels, heightPixels; }
''',
    'android/view/Display.java': '''package android.view;
public class Display {
    public int realMetricsCalls;
    private final int width, height;
    public Display(int width, int height) { this.width=width; this.height=height; }
    public void getRealMetrics(android.util.DisplayMetrics metrics) {
        realMetricsCalls++;
        metrics.widthPixels=width;
        metrics.heightPixels=height;
    }
}
''',
    'android/view/WindowMetrics.java': '''package android.view;
public class WindowMetrics {
    private final android.graphics.Rect bounds;
    public WindowMetrics(android.graphics.Rect bounds) { this.bounds=bounds; }
    public android.graphics.Rect getBounds() { return bounds; }
}
''',
    'android/view/WindowManager.java': '''package android.view;
public interface WindowManager {
    Display getDefaultDisplay();
    WindowMetrics getCurrentWindowMetrics();
}
''',
    'com/kards/mobilert/Api29Harness.java': '''package com.kards.mobilert;
import android.graphics.Rect;
import android.view.Display;
import android.view.WindowManager;
import android.view.WindowMetrics;

public final class Api29Harness {
    private static final class Windows implements WindowManager {
        final Display display = new Display(1280, 720);
        int currentWindowMetricsCalls;
        public Display getDefaultDisplay() { return display; }
        public WindowMetrics getCurrentWindowMetrics() {
            currentWindowMetricsCalls++;
            return new WindowMetrics(new Rect(0, 0, 1280, 720));
        }
    }

    public static void main(String[] args) throws Exception {
        java.lang.reflect.Field sdk = Class.forName("android.os.Build$VERSION").getField("SDK_INT");
        for (int level : new int[]{29, 30, 35}) {
            sdk.setInt(null, level);
            Windows windows = new Windows();
            Rect bounds = DisplayBounds.get(windows);
            System.out.printf("SDK_INT=%d|rect=%d,%d,%d,%d|getRealMetrics=%d|getCurrentWindowMetrics=%d%n",
                    level, bounds.left, bounds.top, bounds.right, bounds.bottom,
                    windows.display.realMetricsCalls, windows.currentWindowMetricsCalls);
        }
    }
}
''',
}


def main():
    with tempfile.TemporaryDirectory(prefix='kards-api29-') as folder:
        root = Path(folder)
        classes = root / 'classes'
        classes.mkdir()
        files = []
        for rel, text in STUBS.items():
            path = root / 'src' / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8')
            files.append(str(path))
        files.append(str(SOURCE))
        javac = subprocess.run(['javac', '-encoding', 'UTF-8', '-d', str(classes)] + files,
                               capture_output=True, text=True, encoding='utf-8', errors='replace')
        if javac.returncode:
            raise SystemExit('javac failed:\n' + javac.stdout + javac.stderr)
        java = subprocess.run(['java', '-cp', str(classes), 'com.kards.mobilert.Api29Harness'],
                              capture_output=True, text=True, encoding='utf-8', errors='replace')
        print(java.stdout.strip())
        if java.returncode:
            raise SystemExit(java.stderr)


if __name__ == '__main__':
    main()
