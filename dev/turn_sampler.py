"""
turn_sampler.py - 只读采样:在每个回合的【开始】和【结束】各存一帧。

要解决什么问题
--------------
用户给了判据:"单位卡左上角的费用数字会从橙色变成灰色"。
要标定这个判据的阈值,需要**对照样本**:
  - 回合开始那一刻:所有单位都刷新了,数字应该都是"还能行动"的颜色
  - 回合结束那一刻:这一回合攻击过的单位应该变成"已行动"的颜色

所以只要在同一局里、成对地存"回合开始帧"和"回合结束帧",就能量出阈值。

★ 只截图、不点鼠标、不出牌。让 bot(main_loop --play)自己打,
  这个采样器在旁边按回合边界存图。

怎么判断回合边界(全部只读):
  - **我方回合**:模板匹配 end_turn_btn 分数高(实测我方 0.996 / 敌方 0.519)
  - 所以 "分数从低变高" = 我方回合开始;"从高变低" = 我方回合结束

用法:
  .venv\\Scripts\\python.exe dev\\turn_sampler.py --seconds 1800
输出:
  shots/turn_pairs/YYYYmmdd_HHMMSS_turnNNN_scale.png   (缩放后整帧,省空间)
  shots/turn_pairs/YYYYmmdd_HHMMSS_turnNNN_start.png
  shots/turn_pairs/YYYYmmdd_HHMMSS_turnNNN_end.png
  shots/turn_pairs/index.txt  每行一帧的元信息(分数/时间)
  另外会把每帧的"卡框 + 费用区搜索块"标注图存一份,方便直接看
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
from ui_state import load_meta, load_templates, match_one
from win import capture_client_bgr, find_by_process, set_dpi_aware

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "shots", "turn_pairs")
META = os.path.join(ROOT, "config", "templates.json")

# 判"是我方回合"的阈值:实测我方 0.996 / 敌方 0.519
OURS_MIN = 0.60
SAMPLE_INTERVAL = 0.6      # 轮询间隔(秒)


def annotated(frame):
    """把卡框 + 费用搜索块画出来,方便直接看判据对不对。"""
    vis = frame.copy()
    for u in board.find_units(frame):
        color = (0, 0, 255) if u["side"] == "enemy" else (0, 255, 0)
        cv2.rectangle(vis, (u["x"], u["y"]),
                      (u["x"] + u["w"], u["y"] + u["h"]), color, 2)
        # 费用搜索块(unit_state 用的那块)
        from unit_state import _search_crop
        _c, (sx, sy, sw, sh) = _search_crop(frame, u)
        cv2.rectangle(vis, (sx, sy), (sx + sw, sy + sh), (255, 0, 255), 1)
    return vis


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=1800)
    ap.add_argument("--proc", default="kards")
    ap.add_argument("--annotate", action="store_true", default=True,
                    help="同时存标注图(默认开)")
    args = ap.parse_args()

    set_dpi_aware()
    wins = find_by_process(args.proc)
    if not wins:
        print("找不到 kards 窗口")
        return 1
    hwnd = wins[0]["hwnd"]
    os.makedirs(OUT, exist_ok=True)
    tpls = load_templates(load_meta(META))
    end_turn = tpls["end_turn_btn"]
    stamp = time.strftime("%Y%m%d_%H%M%S")
    index_path = os.path.join(OUT, "index.txt")

    print(f"只读采样 {args.seconds:.0f}s -> {OUT}")
    print("每当我方回合【开始】/【结束】各存一帧(不点鼠标、不出牌)")

    t0 = time.time()
    was_ours = None
    turn_no = 0
    last_save = 0.0

    def save(frame, tag, score):
        nonlocal turn_no
        name = f"{stamp}_turn{turn_no:03d}_{tag}.png"
        path = os.path.join(OUT, name)
        cv2.imwrite(path, frame)
        if args.annotate:
            cv2.imwrite(os.path.join(OUT, name.replace(".png", "_ann.png")),
                        annotated(frame))
        with open(index_path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{name}\t{tag}\t"
                    f"score={score:.3f}\n")
        print(f"  [{time.time() - t0:6.1f}s] 轮次{turn_no:03d} {tag:<5} "
              f"score={score:.3f} -> {name}")

    while time.time() - t0 < args.seconds:
        frame = capture_client_bgr(hwnd)
        if frame is None:
            time.sleep(SAMPLE_INTERVAL)
            continue
        score, _reg = match_one(frame, end_turn)
        ours = score >= OURS_MIN
        if was_ours is None:
            was_ours = ours
            if ours:
                turn_no += 1
                save(frame, "start", score)
            time.sleep(SAMPLE_INTERVAL)
            continue
        if ours and not was_ours:
            # 我方回合开始
            turn_no += 1
            save(frame, "start", score)
            last_save = time.time()
        elif was_ours and not ours:
            # 我方回合结束(点了结束回合 / 超时)
            save(frame, "end", score)
            last_save = time.time()
        was_ours = ours
        time.sleep(SAMPLE_INTERVAL)

    print(f"\n结束:存了 {turn_no} 个回合的样本到 {OUT}")
    print(f"索引:{index_path}")
    print("下一步:比较 start / end 两帧里每张单位的费用数字颜色,定阈值。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
