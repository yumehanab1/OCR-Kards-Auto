"""
hand_layout_pick_ab.py - 只读 A/B:**布局条目该按哪条边缘挑**(老=先按左边缘筛,新=两个边缘并集)。

为什么要它(2026-09-13 深夜实机抓到的真问题)
--------------------------------------------
实机 20:56:27 那一帧(`shots/scan_frames/0913_205627_scan.png`)逐像素核对过:
  · 手牌**真是 8 张**:卡面左边缘 357、右边缘 ~925,正好是布局表「8 张」那条(357/925);
  · 但 `detect_left_edge` 量到的是 **416** —— 最左那张牌与桌面的色差被它自己的
    卡面花纹切成了 **6 / 13 / 14px 三段**,都低于 `MIN_FAN_RUN_W=40` 被跳过,
    于是第一个"够宽"的段(416 = **第 2 张**的左边缘)被当成了扇形左边缘;
  · 现在的匹配是"**先用左边缘筛候选**(容差 22)**再用右边缘排序**",
    而「8 张」的左边缘离量到的 416 差 59px -> **在筛选那一步就被丢掉了**,
    右边缘 926 与表里 925 只差 1px 也救不回来;
  · 后果:选中「5 张」-> 探针按 5 张的间距铺 -> **只落在第 2/4/6/8 张**上
    (实机探针读数 x455/x531/x677/x777 与画面逐张核对完全吻合),
    奇数张整局没被扫过;记忆的张数也跟着错,后面连环失效。

新规则(候选取**并集**,再排序)
------------------------------
  候选 = {左边缘进容差} ∪ {右边缘进容差(且量到的宽度合理)}
  排序 = ① 两边都对得上 ② 残差和小的 ③ 左边缘近的
★ 只在"量到的宽度合理"时右边缘才参与 —— 背景参考区被污染时
  `detect_edges` 会给出 `R=1099` 这种坏值,那时自动退回老规则(只看左边缘)。

用法
----
  .venv\\Scripts\\python.exe src\\hand_layout_pick_ab.py             # 扫 shots/scan_frames
  .venv\\Scripts\\python.exe src\\hand_layout_pick_ab.py --glob "shots/**/*.png"
  .venv\\Scripts\\python.exe src\\hand_layout_pick_ab.py --truth 0913_205627_scan.png=8

★ 只读:不碰窗口、不写任何东西(除了把对照图存到 shots/hand_edge_ab/)。
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2

import hand_calibrate as hc
from hand_scanner_v2 import (LAYOUT_EDGE_TOL, LAYOUT_MATCH_BOTH_EDGES,
                             LAYOUT_RIGHT_TOL, LAYOUT_WIDTH_SANE)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAYOUT_JSON = os.path.join(ROOT, "config", "hand_layout.json")
OUT_DIR = os.path.join(ROOT, "shots", "hand_edge_ab")


def load_layouts():
    with open(LAYOUT_JSON, "r", encoding="utf-8") as f:
        return json.load(f).get("layouts", {})


def pick_old(items, le, re_):
    """老规则:先用左边缘筛,再用两个边缘排序(和 hand_scanner_v2 里那一段一致)。"""
    cands = sorted((v for v in items
                    if abs(v.get("left_edge", -999) - le) <= LAYOUT_EDGE_TOL),
                   key=lambda v: abs(v["left_edge"] - le))
    if LAYOUT_MATCH_BOTH_EDGES and re_ is not None and cands:
        width = re_ - le
        if LAYOUT_WIDTH_SANE[0] <= width <= LAYOUT_WIDTH_SANE[1]:
            def _rank(v):
                dl = abs(v["left_edge"] - le)
                d_r = (abs(v["right_edge"] - re_) if v.get("right_edge") else 999)
                return (0 if d_r <= LAYOUT_RIGHT_TOL else 1,
                        dl + min(d_r, 120), dl)
            cands = sorted(cands, key=_rank)
    return (cands[0] if cands else None), cands


def pick_new(items, le, re_):
    """
    候选 = {左边缘进容差} ∪ {右边缘进容差(且量到的宽度合理)},再排序。

    ★ 排序键的教训(2026-09-13 深夜,两轮实测):
      · 第一版按"**残差和**"排 -> 这一帧挑成 7 张:左边缘差了 59px 把和拉爆,
        而「7 张」两边各差 48/11 -> 和 59 < 「8 张」的 59+1=60。**错的那条反而赢**。
      · 所以改成"**先看哪条边缘像**":取两个残差里**小的那个**当主判据
        (实测右边缘是准的:926 对表里 8 张的 925 只差 1px),另一条只当并列时的
        次序。这样"左边缘整体偏了"不会再连累判断。
      · 仍然要求:宽度合理时右边缘才参与 —— 背景被污染时 `detect_edges` 会给出
        `R=1099` 这种坏值,那时 `LAYOUT_WIDTH_SANE` 会挡掉,自动退回只看左边缘。
    """
    width_ok = (re_ is not None
                and LAYOUT_WIDTH_SANE[0] <= (re_ - le) <= LAYOUT_WIDTH_SANE[1])

    def _dl(v):
        return abs(v["left_edge"] - le)

    def _dr(v):
        return (abs(v["right_edge"] - re_)
                if (width_ok and v.get("right_edge")) else 999)

    by_left = [v for v in items if _dl(v) <= LAYOUT_EDGE_TOL]
    by_right = ([v for v in items if _dr(v) <= LAYOUT_RIGHT_TOL] if width_ok else [])
    union = {id(v): v for v in by_left + by_right}
    if not union:
        return None, []
    # ① 两个残差里小的那个(哪条边缘像,就信哪条) ② 另一条 ③ 张数多的优先(保守:
    #    宁可多铺几个探针,也不要把整张牌漏掉 —— 实测漏掉的正是最左那张"铁锤")
    cands = sorted(union.values(),
                   key=lambda v: (min(_dl(v), _dr(v)),
                                  max(_dl(v), _dr(v)),
                                  -int(v.get("count") or 0)))
    return cands[0], cands


def main() -> int:
    ap = argparse.ArgumentParser(description="布局条目挑选 A/B(只读)")
    ap.add_argument("--glob", default=os.path.join(ROOT, "shots", "scan_frames",
                                                   "*.png"))
    ap.add_argument("--truth", action="append", default=[],
                    help="人工核对过的真值:文件名=张数(可给多次)")
    args = ap.parse_args()

    truth = {}
    for t in args.truth:
        name, _, n = t.partition("=")
        truth[name.strip()] = int(n)

    layouts = load_layouts()
    items = [v for v in layouts.values() if v.get("left_edge") is not None]
    print("布局表:")
    for v in sorted(items, key=lambda v: v["count"]):
        print(f"   {v['count']:>2} 张  left={v['left_edge']:>4} "
              f"right={v.get('right_edge')}  probes={len(v.get('probes') or [])}")
    print(f"容差:左 {LAYOUT_EDGE_TOL} / 右 {LAYOUT_RIGHT_TOL} / "
          f"宽度合理区间 {LAYOUT_WIDTH_SANE}")

    paths = sorted(glob.glob(args.glob))
    paths = [p for p in paths if not os.path.basename(p).startswith("_")]
    if not paths:
        print(f"没有帧:{args.glob}")
        return 1
    print(f"\n语料 {len(paths)} 帧\n")
    print(f"{'帧':<30}{'量到L':>6}{'量到R':>7}  | {'老':<22}{'新':<22}变化")
    print("-" * 96)

    changed = []
    old_wrong = new_wrong = 0
    for p in paths:
        frame = cv2.imread(p)
        if frame is None:
            continue
        le, re_ = hc.detect_edges(frame)
        name = os.path.basename(p)
        if le is None:
            print(f"{name:<30}{'—':>6}{'—':>7}  | 量不到边缘")
            continue
        old, _oc = pick_old(items, le, re_)
        new, _nc = pick_new(items, le, re_)
        def _fmt(v):
            if v is None:
                return "-"
            dl = abs(v["left_edge"] - le)
            d_r = (abs(v["right_edge"] - re_) if (v.get("right_edge") and re_)
                   else None)
            return f"{v['count']}张 L{dl}/R{d_r if d_r is not None else '-'}"
        mark = ""
        if (old or {}).get("count") != (new or {}).get("count"):
            mark = "★ 变了"
            changed.append((name, le, re_, old, new))
        t = truth.get(name)
        if t is not None:
            mark += f"  真值 {t} 张: 老{'✓' if (old or {}).get('count') == t else '✗'}" \
                    f" 新{'✓' if (new or {}).get('count') == t else '✗'}"
            old_wrong += (old or {}).get("count") != t
            new_wrong += (new or {}).get("count") != t
        print(f"{name:<30}{le:>6}{str(re_):>7}  | {_fmt(old):<22}{_fmt(new):<22}{mark}")

    print("-" * 96)
    print(f"两规则**选中的条目不同**的帧:{len(changed)} / {len(paths)}")
    for name, le, re_, old, new in changed:
        print(f"  · {name}: 量到 L{le}/R{re_} -> 老 "
              f"{(old or {}).get('count')} 张 / 新 {(new or {}).get('count')} 张")
    if truth:
        print(f"\n有人工真值的帧:老规则错 {old_wrong} 张,新规则错 {new_wrong} 张")
    print("\n判据:① 有真值的帧必须变对;② 没有真值的帧要逐帧看过再决定收不收。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
