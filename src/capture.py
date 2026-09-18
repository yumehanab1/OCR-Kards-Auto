"""
capture.py - CLI for window discovery + fixed-size client capture (M0).

Usage:
  python capture.py list [--fragment TEXT]      list windows (default: all)
  python capture.py snap --fragment TEXT --out shots/x.png
        [--client 1280x720] [--pos 0,0]
        captures the window's client area; if --client given, first forces
        the window client size to WxH and moves it to x,y.
        If --fragment cannot be found, falls back to full-screen capture.
"""

from __future__ import annotations

import argparse
import os
import sys

import cv2
import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from win import (  # noqa: E402
    bring_to_front,
    capture_client_bgr,
    capture_screen_bgr,
    find_by_process,
    find_windows,
    list_all_windows,
    set_dpi_aware,
    set_window_client_size,
)


def cmd_list(args: argparse.Namespace) -> int:
    wins = find_windows(args.fragment) if args.fragment else list_all_windows()
    if not wins:
        print("no windows found")
        return 1
    for w in wins:
        print(f"hwnd={w['hwnd']:<9} pid={w['pid']:<7} rect={w['rect']}  {w['title'][:70]}")
    return 0


def cmd_snap(args: argparse.Namespace) -> int:
    out = args.out if os.path.isabs(args.out) else os.path.join(PROJECT_ROOT, args.out)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    img = None
    method = "window-client"

    # Prefer process-name matching: never matches explorer/folders.
    wins = find_by_process(args.proc, title_contains=args.title) if args.proc else []
    if not wins and args.fragment:
        wins = find_windows(args.fragment)
    if wins:
        hwnd = wins[0]["hwnd"]
        bring_to_front(hwnd)
        if args.client:
            try:
                w, h = [int(x) for x in args.client.lower().split("x")]
            except ValueError:
                print(f"bad --client format: {args.client} (use WxH e.g. 1280x720)")
                return 2
            pos = None
            if args.pos:
                px, py = [int(x) for x in args.pos.split(",")]
                pos = (px, py)
            set_window_client_size(hwnd, w, h, *(pos or ()))
            print(f"forced client size to {w}x{h} for hwnd={hwnd}")
        import time

        time.sleep(0.5)
        img = capture_client_bgr(hwnd)
        if img is None:
            print("client capture failed, falling back to full screen")
            method = "screen"
            img = capture_screen_bgr(args.monitor)
    else:
        print(f"no window matches fragment '{args.fragment}', full-screen fallback")
        method = "screen"
        img = capture_screen_bgr(args.monitor)

    if img is None:
        print("capture failed")
        return 1

    cv2.imwrite(out, img)
    print(f"[{method}] saved {out} shape={img.shape[1]}x{img.shape[0]}")
    return 0


def main() -> int:
    set_dpi_aware()
    ap = argparse.ArgumentParser(description="KARDS capture tools (M0)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="list visible windows")
    p_list.add_argument("--fragment", default="", help="title fragment filter")

    p_snap = sub.add_parser("snap", help="capture a window or the screen")
    p_snap.add_argument("--proc", default="kards", help="match by process exe name (recommended)")
    p_snap.add_argument("--title", default="", help="extra filter: window title must contain this")
    p_snap.add_argument("--fragment", default="", help="fallback: match by window title fragment")
    p_snap.add_argument("--out", default="shots/cap.png", help="output png path")
    p_snap.add_argument("--client", default="", help="force client size WxH, e.g. 1280x720")
    p_snap.add_argument("--pos", default="", help="move window to x,y e.g. 0,0")
    p_snap.add_argument("--monitor", type=int, default=0, help="monitor index for screen fallback")
    p_snap.set_defaults(func=cmd_snap)
    p_list.set_defaults(func=cmd_list)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
