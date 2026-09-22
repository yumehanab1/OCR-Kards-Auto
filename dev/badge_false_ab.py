"""badge_false_ab.py - 只读 A/B:假徽章守卫(位置 + "像橙又暗")在**并集**上动了谁。

背景(2026-09-15 实机 J9,证据帧 `shots/scan_frames/0915_184240_scan.png`):
  那一帧 `find_cost_badges` 报了 5 个徽章,其中**两个是假的**:
    · x771 y217(cc 路,22x22,n=94,grey)= 敌方单位卡**底部那排里的类型图标**
      (深色圆角块 + 亮色剪影,和徽章长得一样)-> 反推出一张卡落在**前线行**
      -> `我前线 1`(其实空着);
    · x706 y462(band 路,18x18,n=55,S=136 V=124,orange)= 我们总部右边的**木纹**
      -> 反推出一张卡落进**我方支援行**。
  后果(同一帧的实机日志):`[move] 没动成:我方支援 2->2,前线 X->X+1` ——
  单位**明明挪上去了**(判据帧上它就站在前线),张数却永远"两边不都变"。
  这一轮 7 次"没动成"都是这一族。

本脚本量的**不是徽章,而是并集里最终那张"卡"**(`board.merged_card_boxes`)——
  因为真正污染"某一行有几张"的是卡,不是徽章。两族守卫:
    ① 位置(`unit_state.badge_on_card_body`,在 `board.merged_card_boxes` 里对
       **并集**生效):落在某张已检出卡片下半部分的徽章 -> 丢掉它反推出的卡;
    ② "像橙又暗"(`unit_state.ORANGE_V_MIN`):木纹那一族。

验收标准(老话):**只有该变的变了** ——
  · 掉的那些卡必须能指认成"卡面图标 / 木纹";真徽章反推出来的卡一张都不许掉;
  · **多出来的必须是 0**(守卫只做减法)。

用法:
  .venv\\Scripts\\python.exe dev\\badge_false_ab.py --limit 200
  .venv\\Scripts\\python.exe dev\\badge_false_ab.py --limit 0      # 全量
"""

from __future__ import annotations

import argparse
import glob
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import board  # noqa: E402
import unit_state as us  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "shots", "badge_false_ab")
#: 只取这些目录 —— 别的多半是裁图/放大图/模板,不是整幅板面
DIRS = ["attack_frames", "deploy_drag", "scan_frames", "hits", "hq_hp",
        "samples", "badge_band", "badge_check", "probe", "deploy_probe",
        "guard_probe", "frontline", "board_samples", "field_check",
        "costbadge", "costbadge2", "attack_probe", "shots"]
FULL = (720, 1280)
#: 旧行为 = 位置守卫关、"像橙又暗"门槛 0(等于两道守卫都没有)
OLD_ORANGE_V_MIN = 0.0


def collect(limit: int):
    paths = []
    for d in DIRS:
        p = os.path.join(ROOT, "shots", d)
        if os.path.isdir(p):
            paths += sorted(glob.glob(os.path.join(p, "*.png")))
    frames = []
    for p in paths:
        img = cv2.imread(p)
        if img is not None and img.shape[:2] == FULL:
            frames.append((p, img))
    if limit and len(frames) > limit:
        step = len(frames) / float(limit)
        frames = [frames[int(i * step)] for i in range(limit)]
    return frames


def run_boxes(img, rows, old: bool):
    """旧行为 / 新行为各跑一次(用模块常量做开关,函数本身不改)。

    ★ 两道守卫都要切:`ORANGE_V_MIN`(像橙又暗)和 `STAT_GUARD`(位置)。
      第一版这里只切了前者,位置守卫在两边都开着 —— A/B 于是**看不出**它的作用
      (报"只掉了 6 张",而实际是 26 张)。A/B 的开关必须**逐个**对上要验的判据。
    """
    keep_v, keep_g = us.ORANGE_V_MIN, us.STAT_GUARD
    if old:
        us.ORANGE_V_MIN = OLD_ORANGE_V_MIN
        us.STAT_GUARD = False
    try:
        return board.merged_card_boxes(img, rows=rows)
    finally:
        us.ORANGE_V_MIN, us.STAT_GUARD = keep_v, keep_g


def describe(b):
    s = f"{b.get('from') or 'card'} {int(b['x'])}x{int(b['y'])}"
    bg = b.get("badge")
    if bg:
        s += (f" 徽章({bg.get('w')}x{bg.get('h')} {bg.get('from')} "
              f"state={bg.get('state')} n={bg.get('digit_n')} "
              f"S={bg.get('digit_s'):.0f} V={bg.get('digit_v'):.0f})")
    return s


def tile(img, b, note, w=300, pad=70):
    x0, y0 = max(0, int(b["x"]) - pad), max(0, int(b["y"]) - pad)
    x1 = min(img.shape[1], int(b["x"]) + int(b["w"]) + pad)
    y1 = min(img.shape[0], int(b["y"]) + int(b["h"]) + pad)
    crop = img[y0:y1, x0:x1].copy()
    cv2.rectangle(crop, (int(b["x"]) - x0, int(b["y"]) - y0),
                  (int(b["x"]) - x0 + int(b["w"]),
                   int(b["y"]) - y0 + int(b["h"])), (0, 0, 255), 2)
    crop = cv2.resize(crop, (int(crop.shape[1] * w / crop.shape[0]), w))
    cv2.putText(crop, note, (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                (0, 255, 255), 1, cv2.LINE_AA)
    return crop


def sheet(tiles, name):
    if not tiles:
        return None
    w = max(t.shape[1] for t in tiles)
    tiles = [cv2.copyMakeBorder(t, 0, 2, 0, max(0, w - t.shape[1]),
                                cv2.BORDER_CONSTANT, value=(255, 255, 255))
             for t in tiles]
    out = np.vstack(tiles)
    p = os.path.join(OUT_DIR, name)
    cv2.imwrite(p, out)
    print(f"联系表 -> {p}({out.shape[1]}x{out.shape[0]})")
    return p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200, help="抽样帧数(0 = 全量)")
    ap.add_argument("--tiles", type=int, default=40, help="联系表最多几张")
    args = ap.parse_args()

    frames = collect(args.limit)
    print(f"整幅板面帧 {len(frames)} 张")
    if not frames:
        return 1
    os.makedirs(OUT_DIR, exist_ok=True)

    t0 = time.time()
    n_old = n_new = 0
    gone_tiles, extra_tiles = [], []
    n_gone = n_extra = 0
    shows = 0
    for p, img in frames:
        cb = board.card_boxes(img)
        rr = board.rows_from_boxes(cb)
        old = run_boxes(img, rr, old=True)
        new = run_boxes(img, rr, old=False)
        n_old += len(old)
        n_new += len(new)
        om = {(int(b["x"]), int(b["y"])): b for b in old}
        nm = {(int(b["x"]), int(b["y"])): b for b in new}
        gone = [om[k] for k in om if k not in nm]
        added = [nm[k] for k in nm if k not in om]
        if gone or added:
            shows += 1
            print(f"\n{os.path.basename(p)}: 卡 旧 {len(old)} -> 新 {len(new)}"
                  f"(掉 {len(gone)} / 多 {len(added)})")
        for b in gone:
            n_gone += 1
            print(f"    - {describe(b)}")
            if len(gone_tiles) < args.tiles:
                gone_tiles.append(tile(img, b, f"{os.path.basename(p)[:11]} "
                                                f"{describe(b)[:34]}"))
        for b in added:
            n_extra += 1
            print(f"    + {describe(b)}")
            if len(extra_tiles) < args.tiles:
                extra_tiles.append(tile(img, b, f"{os.path.basename(p)[:11]} "
                                                f"{describe(b)[:34]}"))

    dt = time.time() - t0
    print(f"\n{'=' * 70}\n整程 {dt:.1f}s({dt / max(1, len(frames)) * 1000:.0f}ms/帧)")
    print(f"并集里的卡: 旧 {n_old} -> 新 {n_new}")
    print(f"有差异的帧 {shows}/{len(frames)};掉 {n_gone} 张、多 {n_extra} 张")
    if n_extra:
        print("⚠️ 新行为**多检出**了卡 —— 守卫只做减法,这不该发生,要看联系表")
        sheet(extra_tiles, "tiles_added.png")
    sheet(gone_tiles, "tiles_gone.png")
    print("验收:**只有该变的变了** —— 掉的必须是卡面图标/木纹,多的必须是 0。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
