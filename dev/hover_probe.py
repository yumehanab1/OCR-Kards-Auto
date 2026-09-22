"""
hover_probe.py - probe hand-card hover hot spots.

Moves the mouse across a horizontal band just above the hand fan and takes a
screenshot at each probe point, so we can learn which x position hovers card
#1, #2, ... #N. Screenshots are saved as shots/probe_XXX.png; a vision pass
(or your own eyes) then maps each file to the card it revealed.

How to read results: open shots/probe_*.png in order. Each shows the hover
detail panel of the card under the cursor at that moment. Consecutive files
that show the SAME card mean the cursor was still inside that card's hot zone;
the transition x positions mark the boundaries between cards.

Usage:
  .venv\\Scripts\\python.exe dev\\hover_probe.py [--x0 300] [--x1 1000] [--step 20]
                                        [--y 560] [--hold 0.6]

Args:
  --x0, --x1  : scan range in client x (default 300..1000)
  --step      : probe spacing in px (default 20)
  --y         : fixed probe y just above the hand fan (default 560; tune if needed)
  --hold      : seconds to hold hover before capture (default 0.6)
  --sleep     : seconds to move between probes (default 0.4)
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import win32gui  # noqa: E402

from actions import set_cursor  # noqa: E402
from win import (  # noqa: E402
    capture_client_bgr,
    client_to_screen,
    find_by_process,
    set_dpi_aware,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(PROJECT_ROOT, "shots", "probe")


def main() -> int:
    set_dpi_aware()
    ap = argparse.ArgumentParser()
    ap.add_argument("--proc", default="kards")
    ap.add_argument("--x0", type=int, default=300)
    ap.add_argument("--x1", type=int, default=1000)
    ap.add_argument("--step", type=int, default=20)
    ap.add_argument("--y", type=int, default=560)
    ap.add_argument("--hold", type=float, default=0.6)
    ap.add_argument("--sleep", type=float, default=0.4)
    args = ap.parse_args()

    wins = find_by_process(args.proc)
    if not wins:
        print(f"no window for process '{args.proc}'")
        return 1
    hwnd = wins[0]["hwnd"]
    os.makedirs(SHOTS, exist_ok=True)
    print(f"window hwnd={hwnd}; scanning x {args.x0}..{args.x1} step {args.step} at y={args.y}")
    print("moves the REAL mouse. Press Ctrl+C to abort.")

    n = 0
    for x in range(args.x0, args.x1 + 1, args.step):
        sx, sy = client_to_screen(hwnd, x, args.y)
        set_cursor(sx, sy)
        time.sleep(args.sleep)          # let the panel appear
        time.sleep(args.hold)           # keep hovering while we capture
        img = capture_client_bgr(hwnd)
        if img is None:
            print(f"x={x}: capture failed")
            continue
        path = os.path.join(SHOTS, f"probe_{n:03d}_x{x:04d}.png")
        cv2.imwrite(path, img)
        n += 1
        print(f"x={x}: saved {os.path.basename(path)}")
        time.sleep(0.1)

    print(f"done. {n} probes in {SHOTS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
