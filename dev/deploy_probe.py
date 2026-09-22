"""
deploy_probe.py - 只读探测:观察"刚部署完"的那一帧,看我们的单位落在哪。

为什么要这个
------------
M4 的攻击需要知道**我方单位在战场上的坐标**。但实机发现:
  - 敌方单位会出现在【中线下方】(敌方前线),所以"中线以下就是我方"是错的
  - 卡面里的红色占比也不能分阵营(实测苏军步兵卡 red=0.000)
也就是说"从画面里认哪张卡是我的"这件事,目前没有可靠判据。

所以换个思路:**我们自己的部署动作是已知的** —— 拖到某个落点、费用扣掉、
手牌少一张。那就在【刚部署成功的那一帧】读一次战场,把新出现的卡的位置
记下来,和"我们刚才拖的是第几张"配对。多打几个回合就能得到
"落点 x -> 单位 x" 的对照(游戏会按落点决定单位站位)。

这个脚本只读 + 只截图,不点鼠标、不出牌。请让实机 bot 自己跑,脚本在旁边
看着日志/画面。用法:
  .venv\\Scripts\\python.exe dev\\deploy_probe.py --seconds 240
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

import board
from win import capture_client_bgr, find_by_process, set_dpi_aware

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "shots", "deploy_probe")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=240)
    ap.add_argument("--interval", type=float, default=2.0,
                    help="采样间隔(秒)")
    args = ap.parse_args()

    set_dpi_aware()
    wins = find_by_process("kards")
    if not wins:
        print("找不到 kards 窗口")
        return 1
    hwnd = wins[0]["hwnd"]
    os.makedirs(OUT, exist_ok=True)
    print(f"只读采样 {args.seconds:.0f}s,每 {args.interval}s 一帧 -> {OUT}")
    print("(不点鼠标、不出牌;让 bot 自己打,这里只观察战场变化)")

    t0 = time.time()
    prev = None
    prev_sig = None
    saved = 0
    while time.time() - t0 < args.seconds:
        frame = capture_client_bgr(hwnd)
        if frame is None:
            time.sleep(args.interval)
            continue
        units = board.find_units(frame)
        # 只关心战场(排除手牌与顶部手牌堆)
        board_units = [u for u in units if 80 <= u["cy"] <= 605]
        sig = tuple((u["cx"] // 10, u["cy"] // 10, u["w"] // 10)
                    for u in board_units)
        if sig != prev_sig:
            saved += 1
            path = os.path.join(OUT, f"f{saved:03d}.png")
            cv2.imwrite(path, board.annotate(frame, units))
            n_our = sum(1 for u in board_units if u["side"] == "our")
            n_en = sum(1 for u in board_units if u["side"] == "enemy")
            print(f"[{time.time() - t0:6.1f}s] 变化 -> {path}  "
                  f"战场卡 {len(board_units)} 张"
                  f"(判我方 {n_our} / 判敌方 {n_en})")
            for u in board_units:
                print(f"        {u['side']:<5} x{u['cx']:<5} y{u['cy']:<5} "
                      f"{u['w']}x{u['h']} red={u['red_ratio']}")
            prev_sig = sig
        prev = frame
        time.sleep(args.interval)
    print(f"结束,存了 {saved} 张变化帧到 {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
