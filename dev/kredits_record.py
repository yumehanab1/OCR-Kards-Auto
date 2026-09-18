"""
kredits_record.py - 录制 Kredits 数字字形,用于建模板库(只读,不动鼠标)。

背景:英文见 kredits.py。RapidOCR 读不了这种风格化模板体数字(单字符检测
直接失败),所以精确读费用只能靠模板匹配,而模板必须来自真实截图。

用法(建议在你在对局里正常玩的时候后台跑):
  .venv\\Scripts\\python.exe src\\kredits_record.py --seconds 600

它会每 0.5 秒抓一次左下角费用数字区,把数字字形切出来做归一化,
字形一变就存一张新样例。打完一局后按屏幕上出现的顺序给出 序号 → 值 的对照表,
你只需要确认或纠正。

安全前提:窗口必须可见不被遮挡(截图走 mss 屏幕抓取)。脚本会拒绝在被遮挡时录制。
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2
import numpy as np

from kredits import OURS_BOX, isolate_numeral
from win import (bring_to_front, capture_client_bgr, find_by_process,
                 set_dpi_aware, set_window_client_size)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(PROJECT_ROOT, "shots", "kredits", "samples")

NORM_W, NORM_H = 32, 48          # 归一化后的字形尺寸,用于判重
MAX_RECORDS = 40


def normalize(mask: np.ndarray) -> np.ndarray:
    """把字形掩码缩放到统一尺寸,便于比较变化。"""
    return cv2.resize(mask, (NORM_W, NORM_H), interpolation=cv2.INTER_AREA)


def differs(a: np.ndarray, b: np.ndarray) -> float:
    """两个归一化字形的平均绝对差(0-255)。"""
    return float(cv2.absdiff(a, b).mean())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=600.0, help="录制时长(秒)")
    ap.add_argument("--threshold", type=float, default=18.0,
                    help="字形平均差超过这个值就算换了一个数字")
    ap.add_argument("--interval", type=float, default=0.5, help="采样间隔(秒)")
    ap.add_argument("--save-plates", action="store_true", default=True,
                    help="同时存整块费用区域(默认开),便于之后离线重新提取")
    args = ap.parse_args()

    set_dpi_aware()
    wins = find_by_process("kards")
    if not wins:
        print("找不到 kards 窗口(游戏在运行吗?)")
        return 1
    hwnd = wins[0]["hwnd"]
    print(f"kards hwnd={hwnd}")
    bring_to_front(hwnd)
    time.sleep(0.5)
    set_window_client_size(hwnd, 1280, 720, 100, 100)
    time.sleep(1.0)

    os.makedirs(OUT_DIR, exist_ok=True)
    plate_dir = os.path.join(OUT_DIR, "plates")
    if args.save_plates:
        os.makedirs(plate_dir, exist_ok=True)

    # 数字模板库(0-9 已有),用来给每个字形标注一个"疑似值"
    try:
        import kredits_templates as kt
        kt.build_templates()
    except Exception as e:
        print(f"(模板库不可用,只录像不标注: {e})")

    print(f"数字区 {OURS_BOX},样例存到 {OUT_DIR}")
    print(f"录制 {args.seconds:.0f} 秒,采样间隔 {args.interval}s,换字形阈值 {args.threshold}")
    print(">>> 请在游戏里正常玩,让费用自然变化。窗口保持可见不要最小化。")
    print(">>> 重点:如果能打到 10 费以上,两位数样例就能补齐(现在缺 10-24)。")
    print()

    records: list = []
    last_norm = None
    t0 = time.time()
    samples = 0
    unreadable = 0
    coverage = []

    while time.time() - t0 < args.seconds:
        frame = capture_client_bgr(hwnd)
        if frame is None:
            time.sleep(args.interval)
            continue

        numeral, mask, bbox = isolate_numeral(frame, OURS_BOX)
        samples += 1
        if numeral is None:
            unreadable += 1
            last_norm = None      # 没数字(非对局/读失败),下次重新判断
            time.sleep(args.interval)
            continue

        cov = float((mask > 0).mean())
        coverage.append(cov)

        norm = normalize(mask)
        if last_norm is None or differs(norm, last_norm) > args.threshold:
            idx = len(records)
            h, w = numeral.shape[:2]
            aspect = w / max(1, h)

            # 两段拆分 => 两位数;单段 => 单数字
            try:
                import kredits_templates as kt
                segs = kt.split_glyphs(mask)
            except Exception:
                segs = []

            guess = ""
            quality = "?"
            if len(segs) == 2:
                quality = "两位数"
                digits = []
                for x1, x2 in segs:
                    g = kt.normalize_glyph(mask[:, x1:x2])
                    d, s = kt.match_digit(g)
                    digits.append(f"{d}({s:.2f})" if d is not None else f"?( {s:.2f})")
                guess = " ".join(digits)
            elif len(segs) == 1:
                quality = "单位数"
                g = kt.normalize_glyph(mask)
                d, s = kt.match_digit(g)
                guess = f"{d}({s:.2f})" if d is not None else f"?( {s:.2f})"
            else:
                quality = "无法切分"

            records.append({"idx": idx, "numeral": numeral, "t": time.time() - t0,
                            "aspect": aspect, "coverage": cov, "quality": quality,
                            "guess": guess, "segs": len(segs), "h": h, "w": w})
            last_norm = norm

            stem = f"n_{idx:02d}"
            cv2.imwrite(os.path.join(OUT_DIR, f"{stem}.png"), numeral)
            cv2.imwrite(os.path.join(OUT_DIR, f"{stem}_mask.png"), mask)
            if args.save_plates:
                x1, y1, x2, y2 = OURS_BOX
                cv2.imwrite(os.path.join(plate_dir, f"{stem}_plate.png"),
                            frame[y1:y2, x1:x2])

            print(f"  [{time.time() - t0:7.1f}s] 字形 #{idx:<2} {quality} "
                  f"尺寸 {w}x{h} 宽高比 {aspect:.2f} 填充率 {cov:.2f} "
                  f"-> 疑似 {guess}")
            if idx + 1 >= MAX_RECORDS:
                print("已达到最大样例数,停止")
                break
        else:
            pass

        if samples % 200 == 0:
            print(f"  ...已采样 {samples} 次,字形 {len(records)} 种")

        time.sleep(args.interval)

    occluded = bool(samples and unreadable / samples > 0.95 and not records)

    print()
    print("=" * 78)
    print(f"录制结束:采样 {samples} 次,可读 {samples - unreadable} 次,"
          f"字形 {len(records)} 种")
    print("=" * 78)

    if occluded:
        print("几乎全程读不到数字 —— 窗口大概率被最小化/遮挡了,这次录制不可用。")
        return 1
    if not records:
        print("没有录到任何字形。")
        return 1

    print()
    print(f"{'序号':<6}{'类型':<10}{'尺寸':<10}{'宽高比':<9}{'疑似值':<22}时刻(s)")
    print("-" * 78)
    for r in records:
        size = f"{r['w']}x{r['h']}"
        print(f"#{r['idx']:<5}{r['quality']:<10}{size:<10}"
              f"{r['aspect']:<9.2f}{r['guess']:<22}{r['t']:.1f}")

    print()
    print("说明:「疑似值」是用现有的 0-9 模板库自动标注的,仅供参考;")
    print("      两位数(10-24)的模板还没建,所以两位数的标注可能不准。")
    print(f"确认后我就能把模板补进 kredits_templates.py。样例目录:{OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
