"""
guard_probe.py - 只读预检:把战场帧上**每一张卡**裁出来放大存图,回答一个问题:

    "守护(guard)这个特性,在**盘面的卡面**上到底长什么样、读不读得出来?"

背景(§10 用户补充的第 2 条 + §8 候选第 -3 条):
  · 用户原话:对方**守护单位**放在总部旁边时会给总部上守护特效,
    **必须先把那个单位打掉**才能打总部 —— 而现在的 `_pick_target` 不看这条,
    于是每个单位每回合白拖一次(第 7 局:fighter×4 + infantry×2 全部"没打中",
    只有 artillery×3 打得进去)。
  · 卡库里**有**这个特性:`card_db/kards_data.json` 的 `attributes`
    里就是 `["ambush","guard",...]`(实测 122 张卡带 guard)。
    但那是"**认得出卡名**"才用得上 —— 盘面上的敌方卡我们**不读名字**。
  · §7 第 67 条记过一条线索:**卡面上那个盾牌图标 = 守护**(我当时把它当成了费用徽章)。
    ★ 但那是**我认错**之后用户顺口指出的,**没有帧级证据**。

所以这个脚本只做一件事:**把卡面摊开给人眼看** —— 不做任何判据、不下任何结论。
看清楚了再决定写不写规则(§7 第 59/67/78 条的纪律:先看图,再动代码)。

用法:
    # 看某一帧的敌方两行(默认:第一行=enemy support,第二行=frontline)
    .venv\\Scripts\\python.exe src\\guard_probe.py --frame shots\\attack_frames\\xxx_attack.png

    # 把 shots/attack_frames 里最新的 N 帧都摊开
    .venv\\Scripts\\python.exe src\\guard_probe.py --latest 6

    # 只裁某一行(--row enemy/frontline/our),或只裁指定的 x 附近
    .venv\\Scripts\\python.exe src\\guard_probe.py --frame ... --row enemy --zoom 4

输出:`shots/guard_probe/<帧名>_<行>_<序号>.png`(单卡放大图)
      + `<帧名>_<行>_montage.png`(一行拼图,一眼看完整行)
"""

from __future__ import annotations

import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2
import numpy as np

import board

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "shots", "guard_probe")


def _row_pick(field, which: str):
    """从 read_field 的结果里挑出要摊开的那一行。"""
    rows = field.get("rows") or []
    if which == "enemy":
        rows = [r for r in rows if r.get("side") == "enemy"]
        return rows[-1] if rows else None          # 最上面那一行 = 敌方支援
    if which == "frontline":
        rows = [r for r in rows if r.get("side") == "frontline"]
        # 前线那一行可能被检成两条(实测 cy286 + cy350)-> 都摊开
        return rows
    if which == "our":
        rows = [r for r in rows if r.get("side") == "our"]
        return rows[-1] if rows else None
    return None


def dump_frame(path, which="enemy", zoom=4, out_dir=OUT):
    frame = cv2.imread(path)
    if frame is None:
        print(f"!! 读不到 {path}")
        return []
    field = board.read_field(frame, templates=None, debug=False)
    picked = _row_pick(field, which)
    if picked is None:
        print(f"{os.path.basename(path)}: 没有 '{which}' 那一行")
        return []
    if not isinstance(picked, list):
        picked = [picked]

    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(path))[0]
    made = []
    for ri, row in enumerate(picked):
        boxes = sorted(row.get("units") or [], key=lambda b: b["x"])
        print(f"\n=== {stem} 行[{which}#{ri}] cy={row.get('cy')} "
              f"side={row.get('side')} 卡数={len(boxes)} ===")
        tiles = []
        for i, b in enumerate(boxes):
            # 卡框往外留一点余量(徽章挂在卡左上角,别切掉)
            x0 = max(0, int(b["x"]) - 10)
            y0 = max(0, int(b["y"]) - 10)
            x1 = min(frame.shape[1], int(b["x"] + b["w"]) + 10)
            y1 = min(frame.shape[0], int(b["y"] + b["h"]) + 10)
            crop = frame[y0:y1, x0:x1]
            if crop.size == 0:
                continue
            big = cv2.resize(crop, None, fx=zoom, fy=zoom,
                             interpolation=cv2.INTER_NEAREST)
            name = f"{stem}_{which}{ri}_{i:02d}_x{int(b['x'])}y{int(b['y'])}.png"
            cv2.imwrite(os.path.join(out_dir, name), big)
            made.append(os.path.join(out_dir, name))
            print(f"  [{i}] x{int(b['x'])} y{int(b['y'])} "
                  f"{int(b['w'])}x{int(b['h'])} is_hq={b.get('is_hq')} "
                  f"type={b.get('type')} hp={b.get('hp')} -> {name}")
            tiles.append(big)
        if tiles:
            h = max(t.shape[0] for t in tiles)
            padded = [cv2.copyMakeBorder(t, 0, h - t.shape[0], 0, 12,
                                         cv2.BORDER_CONSTANT,
                                         value=(0, 0, 0)) for t in tiles]
            montage = np.hstack(padded)
            mp = os.path.join(out_dir, f"{stem}_{which}{ri}_montage.png")
            cv2.imwrite(mp, montage)
            made.append(mp)
            print(f"  拼图 -> {mp}")
    return made


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", help="单个整帧 png")
    ap.add_argument("--latest", type=int, default=0,
                    help="把 shots/attack_frames 里最新的 N 帧都摊开")
    ap.add_argument("--glob", default="", help="自定义帧通配(相对项目根)")
    ap.add_argument("--row", default="enemy",
                    choices=["enemy", "frontline", "our"])
    ap.add_argument("--zoom", type=int, default=4)
    a = ap.parse_args()

    frames = []
    if a.frame:
        frames.append(a.frame)
    if a.glob:
        frames += sorted(glob.glob(os.path.join(ROOT, a.glob)))
    if a.latest:
        d = os.path.join(ROOT, "shots", "attack_frames")
        fs = sorted(glob.glob(os.path.join(d, "*_attack.png")),
                    key=os.path.getmtime)[-a.latest:]
        frames += fs
    if not frames:
        ap.error("要给 --frame / --glob / --latest 之一")
    for f in frames:
        dump_frame(f, which=a.row, zoom=a.zoom)
    print(f"\n全部输出在 {OUT}")


if __name__ == "__main__":
    main()
