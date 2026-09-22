"""
scan_bench.py - offline benchmark for the hand scanner WITHOUT the game running.

It replays the real frames we saved under shots/ (diff_base.png as the safe-point
baseline, shots/probe/probe_*.png as hover frames) through the same diff +
classify path hand_scanner_v2 uses, so we can measure and tune recognition
quality and speed without touching KARDS.

Usage:
  .venv\\Scripts\\python.exe dev\\scan_bench.py
"""

from __future__ import annotations

import glob
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2  # noqa: E402

from hand_scanner_v2 import HandScannerV2, diff_bbox, _load_db  # noqa: E402
from ui_state import load_meta, load_templates  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(PROJECT_ROOT, "shots")


def main() -> int:
    meta = load_meta(os.path.join(PROJECT_ROOT, "config", "templates.json"))
    tpls = load_templates(meta)
    _load_db()
    sc = HandScannerV2(0, tpls)          # hwnd unused: we feed frames directly

    base = cv2.imread(os.path.join(SHOTS, "diff_base.png"))
    if base is None:
        print("missing shots/diff_base.png")
        return 1
    print(f"baseline {base.shape} (SAFE point frame)")

    probes = sorted(glob.glob(os.path.join(SHOTS, "probe", "*.png")))
    print(f"{len(probes)} probe frames\n")
    print(f"{'frame':<26} {'diff bbox':<22} {'classify result':<44} {'sec':>5}")
    print("-" * 102)

    total_cls = 0.0
    found = []
    for p in probes:
        frame = cv2.imread(p)
        name = os.path.basename(p)
        if frame is None:
            print(f"{name:<26} unreadable")
            continue
        if frame.shape != base.shape:
            print(f"{name:<26} shape {frame.shape} != baseline {base.shape}")
            continue
        box = diff_bbox(base, frame)
        if box is None:
            print(f"{name:<26} {'no diff (<3000px)':<22}")
            continue
        x, y, w, h = box
        region = frame[y:y + h, x:x + w]
        t0 = time.time()
        info = sc._classify(region)
        dt = time.time() - t0
        total_cls += dt
        print(f"{name:<26} {str(box):<22} {str(info):<44} {dt:>5.2f}")
        if info.get("name") or info.get("type"):
            found.append((name, info))

    print("-" * 102)
    print(f"classified {len(found)} cards; total classify (OCR) time {total_cls:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
