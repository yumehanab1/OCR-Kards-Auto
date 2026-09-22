"""
live_probe.py - non-destructive live check of the KARDS window (M3 tooling).

Does NOT click or drag anything. It:
  1. finds the kards window and forces the calibrated 1280x720 client size
  2. captures a frame and reports basic stats (to prove capture works)
  3. runs the UI state classifier (config/templates.json + states.json)
  4. reports the end-turn button score, which is what TurnEngine uses to decide
     "is it my turn?"
  5. saves the frame to shots/live_probe.png

Use it to sanity-check the pipeline before a session, or to inspect what the
bot currently sees.

Usage:
  .venv\\Scripts\\python.exe dev\\live_probe.py
  .venv\\Scripts\\python.exe dev\\live_probe.py --repeat 10 --interval 1
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2  # noqa: E402

from ui_state import classify, load_meta, load_states, load_templates, match_one  # noqa: E402
from win import (  # noqa: E402
    bring_to_front,
    capture_client_bgr,
    find_by_process,
    set_dpi_aware,
    set_window_client_size,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BTN_BOX = (1090, 430, 200, 90)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=1, help="how many samples")
    ap.add_argument("--interval", type=float, default=1.0)
    args = ap.parse_args()

    set_dpi_aware()
    wins = find_by_process("kards")
    if not wins:
        print("no kards window (is the game running?)")
        return 1
    w = wins[0]
    hwnd = w["hwnd"]
    print(f"kards window: hwnd={hwnd} title={w.get('title')!r} exe={w.get('exe')}")
    bring_to_front(hwnd)
    time.sleep(0.5)
    rect = set_window_client_size(hwnd, 1280, 720, 100, 100)
    print(f"forced client 1280x720, window rect now {rect}")
    time.sleep(1.0)

    tpls = load_templates(load_meta(os.path.join(PROJECT_ROOT, "config", "templates.json")))
    states = load_states(os.path.join(PROJECT_ROOT, "config", "states.json"))
    print(f"templates loaded: {len(tpls)}  states: {list(states)}")

    for i in range(args.repeat):
        frame = capture_client_bgr(hwnd)
        if frame is None:
            print(f"[{i}] capture FAILED (window hidden?)")
            return 1
        state, matches = classify(frame, tpls, states)
        score, reg = match_one(frame, tpls["end_turn_btn"])
        x, y, bw, bh = BTN_BOX
        reg_img = frame[y:y + bh, x:x + bw]
        hsv = cv2.cvtColor(reg_img, cv2.COLOR_BGR2HSV)
        print(f"[{i}] shape={frame.shape} mean={frame.mean():.1f} "
              f"state={state!r} end_turn_score={score:.3f} reg={reg} "
              f"btnbox_sat={hsv[:, :, 1].mean():.0f} val={hsv[:, :, 2].mean():.0f}")
        if matches:
            print("     matched: " + ", ".join(f"{k}={v:.3f}" for k, v in sorted(matches.items())))
        if i == 0:
            out = os.path.join(PROJECT_ROOT, "shots", "live_probe.png")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            cv2.imwrite(out, frame)
            print(f"     saved {out}")
        if i + 1 < args.repeat:
            time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
