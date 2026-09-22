"""
template_capture.py - capture UI element templates from the live KARDS window.

Flow (interactive, ALL inside the OpenCV window - no terminal typing needed):
  1. Grabs the current KARDS window client area (1280x720 baseline).
  2. Drag a box around one UI element (button / icon / region).
  3. Press the number key (1-9) shown for the template name you want ->
     the crop is saved as ui_templates/<name>.png and recorded in
     config/templates.json.
  4. Repeat for each screen/element; press 'q' to finish.

Keys (focus on the image window):
  drag      : select a rectangle (start a new selection)
  1..9      : save current selection under the preset name mapped to that digit
  c         : re-capture the current KARDS window (after switching screens)
  q / ESC   : quit

Usage:
  .venv\\Scripts\\python.exe dev\\template_capture.py
  .venv\\Scripts\\python.exe dev\\template_capture.py --names a,b,c,d,e,f,g,h,i
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from win import capture_client_bgr, find_by_process, set_dpi_aware  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_NAMES = [
    "play_btn",       # 1  main menu: play / battle entry
    "queue_cancel",   # 2  queueing: cancel-search button
    "end_turn_btn",   # 3  in game: end turn button
    "victory_btn",    # 4  victory screen: continue
    "defeat_btn",     # 5  defeat screen: continue
    "surrender_btn",  # 6  in game: surrender/exit (optional)
    "hand_area",      # 7  your hand region (optional, M3)
    "kredits_roi",    # 8  action points readout (optional, M3)
    "confirm_btn",    # 9  generic confirm/dialog ok (optional)
]


class TemplateCapture:
    def __init__(self, proc: str, out_dir: str, meta_path: str, names: list[str]):
        self.proc = proc
        self.out_dir = out_dir
        self.meta_path = meta_path
        self.names = (names or DEFAULT_NAMES)[:9]
        os.makedirs(out_dir, exist_ok=True)
        self.meta: dict = {"image_size": None, "templates": {}}
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    self.meta = json.load(f)
            except Exception:
                pass

        self.img = None
        self.work = None
        self.drag_start = None
        self.sel: tuple[int, int, int, int] | None = None  # x,y,w,h
        self.window = "template_capture"
        self._saved_count = 0

    # ---- helpers ----
    def grab(self) -> bool:
        wins = find_by_process(self.proc)
        if not wins:
            print(f"no window for process '{self.proc}'")
            return False
        self.img = capture_client_bgr(wins[0]["hwnd"])
        if self.img is None:
            print("capture failed")
            return False
        self.meta["image_size"] = {"w": self.img.shape[1], "h": self.img.shape[0]}
        return True

    def redraw(self) -> None:
        self.work = self.img.copy()
        h, w = self.work.shape[:2]

        if self.sel:
            x, y, sw, sh = self.sel
            cv2.rectangle(self.work, (x, y), (x + sw, y + sh), (0, 200, 255), 2)
            cv2.putText(
                self.work, "press number key to save this crop",
                (x, max(14, y - 6)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 1, cv2.LINE_AA,
            )
        # bottom instruction bar: digit -> name
        bar_y = h - 16
        cv2.rectangle(self.work, (0, h - 44), (w, h), (20, 20, 20), -1)
        parts = []
        for i, name in enumerate(self.names, start=1):
            parts.append(f"{i}:{name}")
        hint = " | ".join(parts) + "   [c]=recapture  [q]=quit"
        cv2.putText(
            self.work, hint, (6, bar_y),
            cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1, cv2.LINE_AA,
        )
        cv2.imshow(self.window, self.work)

    def save_selection(self, name: str) -> bool:
        if not self.sel or self.img is None:
            print("no selection yet - drag a box first")
            return False
        x, y, w, h = self.sel
        crop = self.img[y : y + h, x : x + w]
        if crop.size == 0:
            print("empty crop, skipped")
            return False
        path = os.path.join(self.out_dir, f"{name}.png")
        cv2.imwrite(path, crop)
        self.meta["templates"][name] = {
            "path": os.path.relpath(path, PROJECT_ROOT).replace("\\", "/"),
            "region": {"x": x, "y": y, "w": w, "h": h},
        }
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(self.meta, f, ensure_ascii=False, indent=2)
        self._saved_count += 1
        print(f"[{self._saved_count}] saved template '{name}' -> {path} ({w}x{h})")
        return True

    # ---- mouse ----
    def on_mouse(self, event, x, y, _flags, _param) -> None:  # noqa: N802
        if event == cv2.EVENT_LBUTTONDOWN:
            self.drag_start = (x, y)
        elif event == cv2.EVENT_LBUTTONUP and self.drag_start:
            x0, y0 = self.drag_start
            self.drag_start = None
            if abs(x - x0) < 4 or abs(y - y0) < 4:
                print("selection too small, drag a bigger box")
                return
            self.sel = (min(x0, x), min(y0, y), abs(x - x0), abs(y - y0))
            self.redraw()

    # ---- main loop ----
    def run(self) -> int:
        if not self.grab():
            return 1
        cv2.namedWindow(self.window, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(self.window, self.img.shape[1], self.img.shape[0])
        cv2.setMouseCallback(self.window, self.on_mouse)
        self.redraw()
        print("Capture window opened. Drag a box, then press the matching number key.")
        print("Keys: 1-9 save | c = re-capture | q = quit")
        while True:
            key = cv2.waitKey(30) & 0xFF
            if key in (ord("q"), 27):
                break
            elif key == ord("c"):
                if self.grab():
                    print("window re-captured - drag a new box")
                    self.sel = None
                    self.redraw()
            elif ord("1") <= key <= ord("9"):
                idx = key - ord("1")
                if idx < len(self.names):
                    name = self.names[idx]
                    if self.save_selection(name):
                        self.sel = None
                        self.redraw()
                else:
                    print("no name mapped to this digit (only 1-9)")
        cv2.destroyAllWindows()
        print(f"done. {self._saved_count} template(s) saved. metadata: {self.meta_path}")
        return 0


def main() -> int:
    set_dpi_aware()
    ap = argparse.ArgumentParser(description="KARDS UI template capture (M1)")
    ap.add_argument("--proc", default="kards", help="process name to match")
    ap.add_argument("--names", default="", help="comma list of template names (max 9)")
    out_dir = os.path.join(PROJECT_ROOT, "ui_templates")
    meta = os.path.join(PROJECT_ROOT, "config", "templates.json")
    ap.add_argument("--out-dir", default=out_dir)
    ap.add_argument("--meta", default=meta)
    args = ap.parse_args()
    names = [n.strip() for n in args.names.split(",") if n.strip()] if args.names else None
    tc = TemplateCapture(args.proc, args.out_dir, args.meta, names)
    return tc.run()


if __name__ == "__main__":
    sys.exit(main())
