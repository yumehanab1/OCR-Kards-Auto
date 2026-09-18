"""
calibrate.py - interactive ROI calibration tool (M0).

Load a captured screenshot (720p KARDS window) and draw rectangles with the
mouse to mark ROIs (hand area, End Turn button, Kredits readout, ...).
Coordinates are stored relative to the *image* (which should equal the fixed
window client size), so the bot can reuse them every launch.

Keys (when the OpenCV window has focus):
  Left-drag  : draw the next rectangle for the current ROI name
  n          : next ROI name
  b          : back to previous ROI name
  d          : delete the last rectangle of the current ROI
  s          : save ROIs to JSON and continue / exit
  q / ESC    : quit without saving (or after save)

Usage:
  python calibrate.py --image shots/kards_720p.png
                      --out config/roi.json
                      --names hand_area,end_turn_btn,kredits,play_btn
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import cv2
import cv_io  # noqa: F401  (开关:让 cv2 认中文路径,见 cv_io.py)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from win import set_dpi_aware  # noqa: E402


class Calibrator:
    def __init__(self, image_path: str, names: list[str]):
        self.img = cv2.imread(image_path)
        if self.img is None:
            raise SystemExit(f"cannot read image: {image_path}")
        self.work = self.img.copy()
        self.h, self.w = self.img.shape[:2]
        self.names = names
        self.idx = 0
        self.rois: dict[str, list[dict]] = {n: [] for n in names}
        self.drag_start: tuple[int, int] | None = None
        self.window = "calibrate"
        self.dirty = False

    def redraw(self) -> None:
        self.work = self.img.copy()
        for i, name in enumerate(self.names):
            color = (0, 200, 255) if i == self.idx else (0, 255, 0)
            for r in self.rois.get(name, []):
                cv2.rectangle(
                    self.work,
                    (r["x"], r["y"]),
                    (r["x"] + r["w"], r["y"] + r["h"]),
                    color,
                    2,
                )
                cv2.putText(
                    self.work,
                    name,
                    (r["x"], max(12, r["y"] - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    color,
                    1,
                    cv2.LINE_AA,
                )
        cv2.putText(
            self.work,
            f"ROI [{self.idx}/{len(self.names)}] {self.names[self.idx]}  "
            "(drag=box  n=next  b=prev  d=del  s=save  q=quit)",
            (10, self.h - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        cv2.imshow(self.window, self.work)

    def on_mouse(self, event, x, y, _flags, _param) -> None:  # noqa: N802
        if event == cv2.EVENT_LBUTTONDOWN:
            self.drag_start = (x, y)
        elif event == cv2.EVENT_LBUTTONUP and self.drag_start:
            x0, y0 = self.drag_start
            self.drag_start = None
            if x0 == x and y0 == y:  # tolerate click-only -> 8x8 dot
                x += 8
                y += 8
            name = self.names[self.idx]
            rect = {
                "x": min(x0, x),
                "y": min(y0, y),
                "w": abs(x - x0),
                "h": abs(y - y0),
            }
            self.rois[name].append(rect)
            self.dirty = True
            self.redraw()

    def save(self, out_path: str) -> None:
        payload = {
            "image_size": {"w": self.w, "h": self.h},
            "rois": {k: v for k, v in self.rois.items() if v},
        }
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"saved ROIs -> {out_path}")

    def run(self, out_path: str) -> int:
        cv2.namedWindow(self.window, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(self.window, self.w, self.h)
        cv2.setMouseCallback(self.window, self.on_mouse)
        self.redraw()
        while True:
            key = cv2.waitKey(20) & 0xFF
            if key in (ord("q"), 27):
                break
            elif key == ord("s"):
                self.save(out_path)
                break
            elif key == ord("n"):
                self.idx = min(self.idx + 1, len(self.names) - 1)
                self.redraw()
            elif key == ord("b"):
                self.idx = max(self.idx - 1, 0)
                self.redraw()
            elif key == ord("d"):
                if self.rois[self.names[self.idx]]:
                    self.rois[self.names[self.idx]].pop()
                    self.redraw()
        cv2.destroyAllWindows()
        return 0


def main() -> int:
    set_dpi_aware()
    ap = argparse.ArgumentParser(description="KARDS ROI calibrator (M0)")
    ap.add_argument("--image", required=True, help="screenshot (720p KARDS window)")
    ap.add_argument("--out", default="config/roi.json", help="output json")
    ap.add_argument(
        "--names",
        default="hand_area,end_turn_btn,kredits_roi,play_btn,surrender_btn",
        help="comma-separated ROI names to define",
    )
    args = ap.parse_args()
    names = [n.strip() for n in args.names.split(",") if n.strip()]
    cal = Calibrator(args.image, names)
    return cal.run(args.out)


if __name__ == "__main__":
    sys.exit(main())
