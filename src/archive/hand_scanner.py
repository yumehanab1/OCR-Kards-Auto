"""
hand_scanner.py - hover each hand card left-to-right and read it (M3).

Reads cards by moving the mouse across the hand fan at a fixed probe y,
pausing long enough for the hover panel to appear, capturing, and running
local OCR + template matching to identify cost / type.

Hot-zone model (calibrated from probes at 1280x720, y probe = 700):
  hand cards span roughly x 340..900; each card ~55-90px wide.
  We scan from x0 to x1 with a small step, but only keep readings that
  CHANGE identity (dedupe same-card repeats). A "reading" = hover + OCR.
"""

from __future__ import annotations

import time

import cv2

from actions import set_cursor
from hover_card_reader import _ocr  # reuse OCR
from ui_state import load_templates, match_one  # template helpers
from win import capture_client_bgr, client_to_screen


class HandScanner:
    def __init__(self, hwnd: int, templates: dict, y: int = 700,
                 x0: int = 340, x1: int = 920, step: int = 12,
                 hold: float = 0.45):
        self.hwnd = hwnd
        self.templates = templates      # icon templates etc.
        self.y = y
        self.x0 = x0
        self.x1 = x1
        self.step = step
        self.hold = hold

    def _hover(self, x: int):
        sx, sy = client_to_screen(self.hwnd, x, self.y)
        set_cursor(sx, sy)
        time.sleep(self.hold)

    def _read_frame(self, frame):
        """Read the enlarged card under hover: cost (OCR) + type (template)."""
        info = {"cost": None, "type": None}
        # 1) type icon via template match over the frame
        best_type = None
        best_score = 0.0
        for name, tpl in self.templates.items():
            if not name.endswith("_icon"):
                continue
            s, reg = match_one(frame, tpl)
            if reg and s > best_score:
                best_score = s
                best_type = name.replace("_icon", "")
        if best_type and best_score > 0.7:
            info["type"] = best_type
        # 2) cost via OCR token like "1K"
        for ln in _ocr(frame):
            import re
            m = re.fullmatch(r"(\d{1,2})\s*K", ln["text"].strip(), re.I)
            if m:
                info["cost"] = int(m.group(1))
                break
        return info

    def scan(self, max_cards: int = 10):
        """
        Move across the hand, dedupe by (type,cost), stop after max_cards
        distinct cards or when no new card for several steps.
        Returns list of {x, cost, type}.
        """
        found = []
        seen = set()
        stale = 0
        prev_key = None
        for x in range(self.x0, self.x1 + 1, self.step):
            self._hover(x)
            frame = capture_client_bgr(self.hwnd)
            if frame is None:
                continue
            info = self._read_frame(frame)
            key = (info["cost"], info["type"])
            if key != prev_key and key not in seen:
                if info["cost"] is not None or info["type"] is not None:
                    found.append({"x": x, **info})
                    seen.add(key)
                    prev_key = key
                    stale = 0
                    if len(found) >= max_cards:
                        break
                else:
                    stale += 1
            else:
                stale += 1
            if stale > 8:  # moved past the hand into empty board area
                break
        return found


if __name__ == "__main__":
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from ui_state import load_meta, load_templates
    from win import find_by_process, set_dpi_aware

    set_dpi_aware()
    wins = find_by_process("kards")
    if not wins:
        print("no kards window")
        raise SystemExit(1)
    meta_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "config", "templates.json")
    tpls = load_templates(load_meta(meta_path)) if os.path.exists(meta_path) else {}
    sc = HandScanner(wins[0]["hwnd"], tpls)
    print("scanning hand... (moves real mouse; Ctrl+C to stop)")
    cards = sc.scan()
    print(f"detected {len(cards)} cards:")
    for c in cards:
        print("  ", c)
