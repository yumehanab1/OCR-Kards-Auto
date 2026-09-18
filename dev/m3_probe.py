"""
m3_probe.py - end-to-end test: scan hand and identify each card (no playing).

Moves the real mouse across the hand, hovers each card, reads type icon
(template match) + cost (OCR). Prints the hand. Does NOT deploy anything.

Usage: run while it's YOUR turn with cards in hand.
  .venv\\Scripts\\python.exe src\\m3_probe.py
"""

from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2  # noqa: E402

from hand_scanner import HandScanner  # noqa: E402
from ui_state import load_meta, load_templates  # noqa: E402
from win import find_by_process, set_dpi_aware  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    set_dpi_aware()
    wins = find_by_process("kards")
    if not wins:
        print("no kards window")
        return 1
    hwnd = wins[0]["hwnd"]
    meta = load_meta(os.path.join(PROJECT_ROOT, "config", "templates.json"))
    tpls = load_templates(meta)

    print("=== M3 hand scan probe ===")
    print("Make sure it's YOUR turn and you have cards. Scanning in 3s...")
    time.sleep(3)

    sc = HandScanner(hwnd, tpls)
    cards = sc.scan()
    print(f"\nScanned {len(cards)} card position(s):")
    for c in cards:
        print(f"  x={c['x']:>4}  type={str(c['type']):<12} cost={c['cost']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
