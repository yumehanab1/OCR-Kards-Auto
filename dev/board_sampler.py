"""
board_sampler.py - 只读采样战场帧,给 M4 战斗逻辑做标定用。

为什么需要它
------------
战斗逻辑(攻击 / 上前线)的前提是"知道每张卡在哪、是哪一方的、这回合能不能动"。
而 `board.count_row` 现在读出来的东西是垃圾 —— 实机日志反复出现
`我支援 8`(支援线上限只有 4)、`我前线 10`。行带(`OUR_SUPPORT_BAND` 等)是
早先猜的常数,`count_row` 又是"亮列数 ÷ 单卡宽度"这种一坏就整体虚高的算法。

修它的前提是**先有真实帧**。所以这个脚本只做一件事:

    把鼠标停在 SAFE_POINT(不弹悬停面板、不高亮卡) -> 截一帧 -> 存下来
    + 存一张卡面掩码图
    + 算一条【卡面纵向剖面】(每个 y 有多少比例的像素是卡面)

纵向剖面是关键:四条战线在剖面上就是四个峰,峰的位置就是**真实的行带**,
不必再猜。掩码图用于核对"到底是卡面被认出来了,还是桌面/地形被误认"。

★ 只读:全程不点击、不拖拽、不按键盘。唯一的副作用是把鼠标挪到安全点。
★ 每次截图前都查窗口可见性(被别的窗口盖住时抓到的是别人的画面)。

用法:
  .venv\\Scripts\\python.exe src\\board_sampler.py                    # 采 20 帧,每 6 秒一张
  .venv\\Scripts\\python.exe src\\board_sampler.py --seconds 180 --interval 3
  .venv\\Scripts\\python.exe src\\board_sampler.py --label our_turn    # 给这批帧打标签
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import board  # noqa: E402
from actions import set_cursor_checked  # noqa: E402
from hand_scanner_v2 import SAFE_POINT  # noqa: E402
from win import (  # noqa: E402
    bring_to_front,
    capture_client_bgr,
    client_to_screen,
    find_by_process,
    set_dpi_aware,
    window_is_capturable,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(ROOT, "shots", "board_samples")

# 剖面统计的纵向范围(和 board.BOARD_Y0/Y1 一致)与分箱高度
PROFILE_Y0, PROFILE_Y1 = 80, 620
PROFILE_BIN = 5


def card_mask(frame):
    """
    复用 board 的自适应判据,但**单独返回掩码**便于存图核对。
    (board._card_mask 是内部函数,这里直接调它,保证标定和实际用的判据一致。)
    """
    return board._card_mask(frame)


def vertical_profile(mask, x0=board.BOARD_X0, x1=board.BOARD_X1,
                     y0=PROFILE_Y0, y1=PROFILE_Y1, bin_h=PROFILE_BIN):
    """
    卡面纵向剖面:每个 y 分箱里"是卡面"的像素在整行宽度上的占比。

    四条战线会在剖面上形成四个峰 —— 峰位就是真实行带,不用再猜。
    返回 [(y_center, frac), ...]
    """
    sub = mask[y0:y1, x0:x1] > 0
    rows = sub.mean(axis=1)                    # 每一行是卡面的比例
    out = []
    for i in range(0, len(rows) - bin_h + 1, bin_h):
        seg = rows[i:i + bin_h]
        out.append((y0 + i + bin_h // 2, round(float(seg.mean()), 4)))
    return out


def horizontal_profile(mask, y0, y1, x0=board.BOARD_X0, x1=board.BOARD_X1,
                       bin_w=10):
    """
    某条行带内的横向剖面:每个 x 分箱里"是卡面"的竖向占比。

    用来找**卡的水平位置与间距**(同一行的卡在横向上是等距的几段)。
    """
    sub = mask[y0:y1, x0:x1] > 0
    cols = sub.mean(axis=0)
    out = []
    for i in range(0, len(cols) - bin_w + 1, bin_w):
        seg = cols[i:i + bin_w]
        out.append((x0 + i + bin_w // 2, round(float(seg.mean()), 4)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="战场帧只读采样(不点任何东西)")
    ap.add_argument("--seconds", type=float, default=120.0)
    ap.add_argument("--interval", type=float, default=6.0)
    ap.add_argument("--outdir", default=DEFAULT_OUT)
    ap.add_argument("--label", default="", help="给这批帧打的标签(进索引)")
    ap.add_argument("--no-front", action="store_true",
                    help="不要把窗口置前(不想抢焦点时用)")
    args = ap.parse_args()

    set_dpi_aware()
    wins = find_by_process("kards")
    if not wins:
        print("找不到 kards 窗口")
        return 1
    hwnd = wins[0]["hwnd"]
    if not args.no_front:
        bring_to_front(hwnd)
        time.sleep(0.8)

    os.makedirs(args.outdir, exist_ok=True)
    index_path = os.path.join(args.outdir, "index.jsonl")
    stamp = time.strftime("%m%d_%H%M%S")

    # 把鼠标停在安全点:否则悬停会把卡高亮/弹放大面板,剖面就脏了
    sx, sy = client_to_screen(hwnd, *SAFE_POINT)
    set_cursor_checked(sx, sy)
    time.sleep(0.4)

    print(f"采样 {args.seconds:.0f}s,每 {args.interval:.0f}s 一张 -> {args.outdir}")
    print("(只读:不点击、不拖拽;鼠标停在 SAFE_POINT "
          f"{SAFE_POINT} 以免悬停面板污染画面)")
    t0 = time.time()
    n = 0
    while time.time() - t0 < args.seconds:
        if not window_is_capturable(hwnd, quiet=True):
            print("  [跳过] 窗口不可见/被遮挡 —— 抓到的会是别人的画面")
            time.sleep(2)
            continue
        frame = capture_client_bgr(hwnd)
        if frame is None:
            print("  [跳过] 截图失败")
            time.sleep(2)
            continue

        n += 1
        tag = f"{stamp}_{n:03d}"
        raw_path = os.path.join(args.outdir, f"{tag}.png")
        cv2.imwrite(raw_path, frame)

        mask = card_mask(frame)
        mask_path = os.path.join(args.outdir, f"{tag}_mask.png")
        cv2.imwrite(mask_path, mask)

        # 标注图:把当前 board.py 认为的卡 + 行带画上去,一眼看出错在哪
        try:
            b = board.read_board(frame, debug=False)
            ann = board.annotate(frame, b["units"], b["hq_enemy"], b["hq_our"])
        except Exception as e:
            b = {"units": [], "our": [], "enemy": [], "hq_enemy": None,
                 "hq_our": None}
            ann = frame.copy()
            print(f"    read_board 抛异常: {type(e).__name__}: {e}")
        for y0, y1, name in ((*board.OUR_SUPPORT_BAND, "our_sup"),
                             (*board.OUR_FRONT_BAND, "our_front"),
                             (*board.ENEMY_FRONT_BAND, "enemy_front"),
                             (*board.ENEMY_SUPPORT_BAND, "enemy_sup")):
            cv2.rectangle(ann, (board.BOARD_X0, y0), (board.BOARD_X1, y1),
                          (255, 128, 0), 1)
            cv2.putText(ann, name, (board.BOARD_X0 + 2, y0 + 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 128, 0), 1)
        ann_path = os.path.join(args.outdir, f"{tag}_annot.png")
        cv2.imwrite(ann_path, ann)

        vprof = vertical_profile(mask)
        # 当前常数行带在真实帧上算出多少(这就是 "我支援 8/4" 的来源)
        rows = {}
        for y0, y1, name in ((*board.OUR_SUPPORT_BAND, "our_support"),
                             (*board.OUR_FRONT_BAND, "our_front"),
                             (*board.ENEMY_FRONT_BAND, "enemy_front"),
                             (*board.ENEMY_SUPPORT_BAND, "enemy_support")):
            cnt, det = board.count_row(frame, y0, y1)
            rows[name] = {"y": [y0, y1], "count": cnt, **det}

        # 剖面上的峰(卡面占比明显高的分箱)-> 真实行带的候选
        peaks = [(y, f) for y, f in vprof if f >= 0.35]

        rec = {
            "t": time.strftime("%H:%M:%S"),
            "label": args.label,
            "raw": os.path.basename(raw_path),
            "mask": os.path.basename(mask_path),
            "annot": os.path.basename(ann_path),
            "sizes": [int(frame.shape[1]), int(frame.shape[0])],
            "mean": round(float(frame.mean()), 1),
            "count_row_now": rows,
            "units_now": [{"cx": u["cx"], "cy": u["cy"], "w": u["w"],
                           "h": u["h"], "side": u["side"]}
                          for u in b.get("units", [])],
            "vprofile": vprof,
            "vpeaks": peaks,
        }
        with open(index_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        # 线上打印精简信息,采样时就能看出对不对
        band_str = " ".join(f"{k}={v['count']}" for k, v in rows.items())
        peak_str = (", ".join(f"y{y}({f:.2f})" for y, f in peaks[:14])
                    or "无")
        print(f"[{n:03d}] {rec['t']} mean={rec['mean']:5.1f} | "
              f"现有行带: {band_str} | 剖面峰: {peak_str}")
        time.sleep(max(0.2, args.interval))

    print(f"\n共采 {n} 帧 -> {args.outdir}")
    print(f"索引: {index_path}")
    print("下一步(离线,不需要游戏):")
    print("  1. 看 *_annot.png:现有行带到底压在卡的什么位置")
    print("  2. 看 *_mask.png:卡面有没有被干净地分出来(地形装饰有没有混进来)")
    print("  3. 看 index.jsonl 的 vpeaks:四条战线的真实 y 在哪")
    return 0


if __name__ == "__main__":
    sys.exit(main())
