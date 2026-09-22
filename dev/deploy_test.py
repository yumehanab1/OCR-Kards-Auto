"""
deploy_test.py - interactive test: scan hand, pick first deployable unit,
drag it to the battlefield, then verify (hand lost one card / field gained).

This MOVES THE MOUSE and actually PLAYS a card. Only run when you're ready
to spend the Kredits and it's your turn.

Usage:
  .venv\\Scripts\\python.exe dev\\deploy_test.py
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2  # noqa: E402

from deploy import drag_deploy  # noqa: E402
from hand_scanner_v2 import HandScannerV2, _load_db  # noqa: E402
from turn_planner import DEPLOYABLE  # noqa: E402
from ui_state import load_meta, load_templates  # noqa: E402
from win import (  # noqa: E402
    capture_client_bgr,
    find_by_process,
    set_dpi_aware,
    set_window_client_size,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def count_hand_cards(sc):
    """Scan and return number of distinct cards seen (rough hand size)."""
    return len(sc.scan())


def main() -> int:
    set_dpi_aware()
    wins = find_by_process("kards")
    if not wins:
        print("no kards window")
        return 1
    hwnd = wins[0]["hwnd"]
    set_window_client_size(hwnd, 1280, 720, 100, 100)
    time.sleep(1.0)
    _load_db()
    meta = load_meta(os.path.join(PROJECT_ROOT, "config", "templates.json"))
    tpls = load_templates(meta)

    print("=== deploy test ===")
    print("This will actually play a card! Confirm it's your turn & you have a unit.")
    input("Press Enter to scan hand... ")
    sc = HandScannerV2(hwnd, tpls)
    cards = sc.scan()
    print("Hand scan:")
    for c in cards:
        print("  ", c)

    deployable = [c for c in cards if c.get("type") in DEPLOYABLE]
    if not deployable:
        print("No deployable unit found in hand - aborting (nothing played).")
        return 1
    target = deployable[0]
    print(f"\nWill deploy: {target}")

    before_scan = sc.scan()
    n_before = len(before_scan)
    print(f"hand cards before: {n_before}")

    print(f"dragging card at x={target['x']} to battlefield...")
    ok = drag_deploy(hwnd, target["x"])
    print(f"drag sent: {ok}")
    time.sleep(2.5)

    after = sc.scan()
    n_after = len(after)
    print(f"hand cards after: {n_after}")
    for c in after:
        print("  ", c)
    if n_after < n_before:
        print(">>> DEPLOY SUCCESS: hand lost a card")
    else:
        print(">>> hand unchanged - deploy may have failed (or same-count)")
        frame = capture_client_bgr(hwnd)
        cv2.imwrite(os.path.join(PROJECT_ROOT, "shots", "deploy_after.png"), frame)
        print("saved shots/deploy_after.png for inspection")
    return 0


if __name__ == "__main__":
    sys.exit(main())
