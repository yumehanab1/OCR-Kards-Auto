"""
calibrate_cost_color.py - 用"回合开始 / 回合结束"的对照帧,标定"能不能行动"的判据。

背景
----
用户给了判据:**单位卡左上角的费用数字会从橙色变成灰色**。
但直接量"橙色像素数 vs 灰色像素数"不可靠(见 PROJECT_STATE 第 50 条):
绝对阈值抗不住光照和背景。所以这里改成量**相对量**:

    取费用数字所在的那个小方块,算它里面"偏黄橙像素"的**饱和度均值**。
    数字还是橙色 -> 饱和度高;数字变灰 -> 饱和度低。

因为同一张卡在"回合开始"和"回合结束"两帧里的位置几乎不动,所以可以
**按 x 坐标把两帧的卡配对**,直接比较同一张卡的颜色变化 —— 这就是最干净的
对照样本。

怎么用
------
1. 先跑 `turn_sampler.py` 采若干回合的 start/end 帧。
2. 跑本脚本:
   ```
   .venv\\Scripts\\python.exe dev\\calibrate_cost_color.py
   ```
   它会:
     - 打印每个回合里"配对上的卡"在 start/end 两帧的饱和度值
     - 给出**建议阈值**(两类分布之间的分界)
     - 输出每张卡的放大图到 shots/cost_calib/,供人工核对
3. 把建议阈值填进 `unit_state.py` 的常量。
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2
import numpy as np

import board

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAIRS_DIR = os.path.join(ROOT, "shots", "turn_pairs")
CALIB_DIR = os.path.join(ROOT, "shots", "cost_calib")

# 费用数字方块:在卡框(可能偏下/偏窄)的左上方搜这一块。
SEARCH_X = (-0.06, 0.42)
SEARCH_Y = (-0.22, 0.16)

# "橙黄"像素:r 明显大于 b,且有一定饱和度
ORANGE_MIN_R = 120
ORANGE_RB = 40
ORANGE_RG = 8


def search_rect(unit, frame_shape):
    x, y, w, h = unit["x"], unit["y"], unit["w"], unit["h"]
    fh, fw = frame_shape[:2]
    x0 = max(0, min(fw, int(x + w * SEARCH_X[0])))
    x1 = max(0, min(fw, int(x + w * SEARCH_X[1])))
    y0 = max(0, min(fh, int(y + h * SEARCH_Y[0])))
    y1 = max(0, min(fh, int(y + h * SEARCH_Y[1])))
    return x0, y0, x1, y1


def cost_metrics(frame, unit):
    """
    返回费用数字那一块的度量:
      orange_sat  偏橙像素的平均饱和度(S=1-min/max)  —— 主判据
      orange_frac 偏橙像素占比
      orange_n    偏橙像素数
      dark_n      方块里暗像素数(方块底色,用来确认取对了地方)
      rect        取的那块
    """
    x0, y0, x1, y1 = search_rect(unit, frame.shape)
    crop = frame[y0:y1, x0:x1]
    m = {"rect": (x0, y0, x1 - x0, y1 - y0), "orange_n": 0, "orange_frac": 0.0,
         "orange_sat": 0.0, "dark_n": 0, "px": int(crop.shape[0] * crop.shape[1])}
    if crop.size == 0:
        return m
    b, g, r = (crop[:, :, i].astype(np.float32) for i in range(3))
    mx = np.maximum(np.maximum(b, g), r)
    mn = np.minimum(np.minimum(b, g), r)
    sat = np.where(mx > 0, 1.0 - mn / np.maximum(mx, 1.0), 0.0)
    orange = ((r >= ORANGE_MIN_R) & ((r - b) >= ORANGE_RB)
              & ((r - g) >= ORANGE_RG))
    m["orange_n"] = int(orange.sum())
    m["orange_frac"] = float(orange.mean())
    if m["orange_n"] > 0:
        m["orange_sat"] = float(sat[orange].mean())
    m["dark_n"] = int((mx < 70).sum())
    return m


def match_units(units_a, units_b, tol=18):
    """按 cx 把两帧的卡配对(位置几乎不动)。返回 [(ua, ub), ...]。"""
    pairs, used = [], set()
    for ua in units_a:
        best, bd = None, 10 ** 6
        for i, ub in enumerate(units_b):
            if i in used:
                continue
            d = abs(ua["cx"] - ub["cx"])
            if d < bd:
                best, bd = i, d
        if best is not None and bd <= tol:
            used.add(best)
            pairs.append((ua, units_b[best]))
    return pairs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=PAIRS_DIR)
    ap.add_argument("--dump", action="store_true", default=True,
                    help="输出每张卡的放大图")
    args = ap.parse_args()

    if not os.path.isdir(args.dir):
        print(f"没有采样目录 {args.dir};请先跑 turn_sampler.py")
        return 1
    starts = sorted(glob.glob(os.path.join(args.dir, "*_start.png")))
    if not starts:
        print(f"{args.dir} 里没有 *_start.png;请先跑 turn_sampler.py")
        return 1
    os.makedirs(CALIB_DIR, exist_ok=True)

    rows = []          # (turn, cx, cy, start_sat, end_sat, ...)
    for sp in starts:
        base = sp[:-len("_start.png")]
        ep = base + "_end.png"
        if not os.path.exists(ep):
            continue
        turn = re.search(r"turn(\d+)", sp)
        turn = turn.group(1) if turn else "?"
        fa, fb = cv2.imread(sp), cv2.imread(ep)
        if fa is None or fb is None:
            continue
        ua = board.find_units(fa)
        ub = board.find_units(fb)
        pairs = match_units(ua, ub)
        print(f"=== 回合 {turn}: start 检出 {len(ua)} 张, end 检出 {len(ub)} 张, "
              f"配对 {len(pairs)} 对 ===")
        print(f"   {'cx':>5}{'cy':>5}{'start_sat':>10}{'end_sat':>9}"
              f"{'start_oN':>9}{'end_oN':>8}{'Δsat':>8}")
        for A, B in pairs:
            ma = cost_metrics(fa, A)
            mb = cost_metrics(fb, B)
            d = ma["orange_sat"] - mb["orange_sat"]
            print(f"   {A['cx']:>5}{A['cy']:>5}{ma['orange_sat']:>10.3f}"
                  f"{mb['orange_sat']:>9.3f}{ma['orange_n']:>9}{mb['orange_n']:>8}"
                  f"{d:>8.3f}")
            rows.append((turn, A["cx"], A["cy"], ma, mb))
            if args.dump:
                for tag, f, u, m in (("start", fa, A, ma), ("end", fb, B, mb)):
                    x0, y0, x1, y1 = m["rect"]
                    crop = f[y0:y1, x0:x1]
                    if crop.size:
                        big = cv2.resize(crop, None, fx=6, fy=6,
                                         interpolation=cv2.INTER_NEAREST)
                        cv2.imwrite(os.path.join(
                            CALIB_DIR,
                            f"t{turn}_x{A['cx']}_{tag}_sat{m['orange_sat']:.2f}.png"),
                            big)

    if not rows:
        print("\n没有配对上的卡。可能原因:两帧之间单位位置变了 / 没检出卡。")
        return 1

    sa = np.array([r[3]["orange_sat"] for r in rows])
    sb = np.array([r[4]["orange_sat"] for r in rows])
    print()
    print("=" * 78)
    print(f"配对样本 {len(rows)} 对")
    print(f"  start(回合开始,应多为'可行动'): 饱和度 均值 {sa.mean():.3f} "
          f"范围 {sa.min():.3f}~{sa.max():.3f}")
    print(f"  end  (回合结束,打过的应变灰):   饱和度 均值 {sb.mean():.3f} "
          f"范围 {sb.min():.3f}~{sb.max():.3f}")
    # 建议阈值:两类的中点(若有分离)
    all_s = np.concatenate([sa, sb])
    mid = (sa.mean() + sb.mean()) / 2
    print(f"  建议阈值(两类均值中点)= {mid:.3f}")
    # 用"start 高 / end 低"这个方向算一下分离度
    good = sa > sb
    print(f"  start 饱和度 > end 饱和度的比例: {good.mean():.0%}"
          f"  ({good.sum()}/{len(good)})")
    if good.mean() < 0.7:
        print("  ⚠️ 分离度不足 —— 判据可能取错了区域,或这一回合没有单位行动过。")
        print("     请打开 shots/cost_calib/ 里的放大图人工核对。")
    print(f"  放大图:{CALIB_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
