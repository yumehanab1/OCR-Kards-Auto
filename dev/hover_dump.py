"""
hover_dump.py - **只读**取证:悬停指定 x 坐标,把**悬停帧**存下来,并把
**整帧 OCR 的每一行(含 y 位置和字高)**打出来。

为什么需要它:卡名读不出时,`hand_scanner_v2 --debug` 只会给你"裁剪后的
OCR 结果"—— 你能看到"名字不在结果里",但看不到**它为什么不在了**
(是名字被那条金色横幅挡住了?还是这一级 OCR 根本没覆盖到卡名带?
还是字太小/太花被 RapidOCR 丢掉了?)。
这个工具直接把画面和"每一行在哪儿"摆出来。

用法:
  .venv\\Scripts\\python.exe dev\\hover_dump.py --x 492 --x 639 --x 740
  .venv\\Scripts\\python.exe dev\\hover_dump.py --layout 4      # 用布局表里的 4 张牌坐标

只会移动鼠标(悬停),**不点击**;结束时把光标放回安全点。
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
import numpy as np  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(ROOT, "shots", "hoverdump")


def dump_lines(frame, tag):
    """整帧 OCR,把每一行连位置一起打出来(卡名一定在 y<550 的中线附近)。"""
    from hover_card_reader import _ocr

    t0 = time.time()
    try:
        lines = _ocr(frame)
    except Exception as exc:
        print(f"    OCR 失败: {exc}")
        return
    dt = time.time() - t0
    print(f"    整帧 OCR {len(lines)} 行,{dt:.2f}s(按 y 排:y 高 宽 置信 文本)")
    for ln in sorted(lines, key=lambda l: float(l.get("y", 0))):
        y = float(ln.get("y", 0))
        h = float(ln.get("h", 0))
        w = float(ln.get("w", 0))
        x = float(ln.get("x", 0))
        zone = ""
        if y < 550:
            zone = "  <- 中线区(卡名该在这)"
        if h >= 20:
            zone += " [大字]"
        txt = str(ln.get("text", "")).strip()
        print(f"      y{y:6.1f} h{h:5.1f} x{x:6.1f} w{w:6.1f} "
              f"c{float(ln.get('conf', 0)):.2f}  {txt}{zone}")


def main() -> int:
    ap = argparse.ArgumentParser(description="只读悬停取证(不点击)")
    ap.add_argument("--x", type=int, action="append", default=[],
                    help="要悬停的客户区 x(可重复)")
    ap.add_argument("--layout", type=int, default=0,
                    help="用 config/hand_layout.json 里 N 张牌的坐标")
    ap.add_argument("--no-ocr", action="store_true", help="只存图,不跑整帧 OCR")
    args = ap.parse_args()

    xs = list(args.x)
    if args.layout:
        import json

        path = os.path.join(ROOT, "config", "hand_layout.json")
        data = json.load(open(path, encoding="utf-8"))
        key = str(args.layout)
        entry = data.get(key) or data.get("layouts", {}).get(key)
        if not entry:
            print(f"布局表里没有「{args.layout} 张」")
            return 1
        # 布局表里存的是各种左右边缘,取第一组
        coords = entry.get("xs") or entry.get("centers") or entry
        if isinstance(coords, dict):
            coords = next(iter(coords.values()))
        xs = [int(c) for c in coords]
    if not xs:
        print("要么给 --x,要么给 --layout N")
        return 1

    from hand_scanner_v2 import HandScannerV2, PROBE_Y
    from ui_state import load_meta, load_templates
    from win import find_by_process, set_dpi_aware, set_window_client_size

    set_dpi_aware()
    wins = find_by_process("kards")
    if not wins:
        print("找不到 kards 窗口")
        return 1
    hwnd = wins[0]["hwnd"]
    set_window_client_size(hwnd, 1280, 720, 100, 100)
    time.sleep(1.0)
    meta_path = os.path.join(ROOT, "config", "templates.json")
    tpls = load_templates(load_meta(meta_path)) if os.path.exists(meta_path) else {}
    sc = HandScannerV2(hwnd, tpls)

    os.makedirs(OUTDIR, exist_ok=True)
    print(f"悬停 y={PROBE_Y}(手牌带),安全点 {sc.safe},每次悬停 {sc.hold}s")
    try:
        for x in xs:
            print(f"\n=== 悬停 x={x} ===")
            frame = sc._hover_frame(x)
            if frame is None:
                print("    截图失败")
                continue
            full = os.path.join(OUTDIR, f"x{x:04d}_full.png")
            cv2.imwrite(full, frame)
            # 中线那一带放大存一份,方便人眼看卡名带
            band = frame[150:560, :]
            cv2.imwrite(os.path.join(OUTDIR, f"x{x:04d}_band.png"),
                        cv2.resize(band, None, fx=1.6, fy=1.6,
                                   interpolation=cv2.INTER_NEAREST))
            print(f"    存图 {os.path.basename(full)} + band 放大图")
            if not args.no_ocr:
                dump_lines(frame, f"x{x}")
    finally:
        # 无论出什么事,都要把光标放回安全点(否则下一个工具会踩到悬停面板)
        try:
            sc._move(*sc.safe)
        except Exception:
            pass
        print("\n光标已放回安全点")
    return 0


if __name__ == "__main__":
    sys.exit(main())
