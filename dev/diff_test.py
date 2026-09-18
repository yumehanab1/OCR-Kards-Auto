"""
diff_test.py - interactive diff validation for hover panel isolation.

Flow:
  1. Force KARDS window to 1280x720.
  2. Move mouse to SAFE point, capture baseline.
  3. Ask you to hover a hand card; wait for Enter.
  4. Capture hover, diff, print the changed bbox.
  5. Save images to shots/ for inspection.

Usage:
  .venv\\Scripts\\python.exe src\\diff_test.py
"""

from __future__ import annotations

import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from actions import set_cursor  # noqa: E402
from win import (  # noqa: E402
    capture_client_bgr,
    client_to_screen,
    find_by_process,
    set_dpi_aware,
    set_window_client_size,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(PROJECT_ROOT, "shots")
SAFE = (1270, 360)  # screen middle line, far right - user-tested safe spot

DIFF_THRESH = 25


def capture(hwnd):
    return capture_client_bgr(hwnd)


def diff_bbox(a, b):
    if a is None or b is None or a.shape != b.shape:
        return None
    d = cv2.absdiff(a, b)
    gray = cv2.cvtColor(d, cv2.COLOR_BGR2GRAY)
    mask = (gray > DIFF_THRESH).astype(np.uint8)
    if mask.sum() < 3000:
        return None
    ys, xs = np.where(mask > 0)
    return (int(xs.min()), int(ys.min()), int(xs.max()) - int(xs.min()) + 1,
            int(ys.max()) - int(ys.min()) + 1)


def main() -> int:
    set_dpi_aware()
    wins = find_by_process("kards")
    if not wins:
        print("no kards window")
        return 1
    hwnd = wins[0]["hwnd"]
    set_window_client_size(hwnd, 1280, 720, 100, 100)
    time.sleep(1.0)

    os.makedirs(SHOTS, exist_ok=True)

    # baseline
    sx, sy = client_to_screen(hwnd, *SAFE)
    set_cursor(sx, sy)
    time.sleep(0.7)
    base = capture(hwnd)
    cv2.imwrite(os.path.join(SHOTS, "diff_base.png"), base)
    print(f"baseline captured at safe {SAFE} -> {base.shape}")

    input(">>> Hover over a hand card now (keep it still), then press Enter...")
    time.sleep(0.6)
    hover = capture(hwnd)
    cv2.imwrite(os.path.join(SHOTS, "diff_hover.png"), hover)
    print(f"hover captured -> {hover.shape}")

    box = diff_bbox(base, hover)
    if box:
        x, y, w, h = box
        print(f"DIFF bbox: x {x}-{x+w}  y {y}-{y+h}  size {w}x{h}")
        # save diff region crop for inspection
        crop = hover[y:y + h, x:x + w]
        cv2.imwrite(os.path.join(SHOTS, "diff_region.png"), crop)
        print("saved diff_region.png")
    else:
        print("No meaningful diff (panel did not appear, or sizes differ)")
        # diagnose
        if base.shape != hover.shape:
            print(f"  size mismatch: base {base.shape} vs hover {hover.shape}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
