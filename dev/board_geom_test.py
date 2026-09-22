"""
board_geom_test.py - 离线验证第二代战场读取(不需要游戏)。

用的是真实对局帧:
  shots/board_samples/*.png   (board_sampler.py 采的,鼠标停在安全点)
  shots/deploy_probe/f*.png   (更早采的,不同对局/不同棋盘)

为什么必须离线先验:战场读取是战斗逻辑的地基,而它之前是错的
(实机日志 `我支援 8`,而上限只有 4)。用真实帧把"几行、每行几张、
哪些是总部"逐帧打出来人工核对,比在实机上猜便宜得多。

用法:
  .venv\\Scripts\\python.exe dev\\board_geom_test.py
  .venv\\Scripts\\python.exe dev\\board_geom_test.py --shots        # 顺带存标注图
"""

from __future__ import annotations

import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2  # noqa: E402

import board  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def annotate_field(frame, field, out_path):
    out = frame.copy()
    colors = {"enemy": (0, 0, 255), "our": (0, 255, 0),
              "frontline": (0, 255, 255)}
    for r in field["rows"]:
        col = colors.get(r["side"], (255, 255, 255))
        for u in r["units"]:
            cv2.rectangle(out, (u["x"], u["y"]),
                          (u["x"] + u["w"], u["y"] + u["h"]), col, 2)
            tag = f"{r['side'][:5]}"
            if u["is_hq"]:
                tag += f" HQ{u['hp']}"
            cv2.putText(out, tag, (u["x"], max(12, u["y"] - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 1)
        cv2.putText(out, f"row{r['cy']:.0f} {r['side']} n={r['n']}",
                    (20, int(r["cy"])),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1)
    for u, name in ((field["hq_enemy"], "HQ-E"), (field["hq_our"], "HQ-O")):
        if u:
            cv2.rectangle(out, (u["x"] - 4, u["y"] - 4),
                          (u["x"] + u["w"] + 4, u["y"] + u["h"] + 4),
                          (255, 0, 255), 3)
            cv2.putText(out, f"{name} hp{u['hp']}",
                        (u["x"], u["y"] + u["h"] + 16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 255), 2)
    cv2.imwrite(out_path, out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", action="store_true", help="存标注图")
    ap.add_argument("--max", type=int, default=0, help="最多看几帧")
    args = ap.parse_args()

    files = (sorted(glob.glob(os.path.join(ROOT, "shots", "board_samples",
                                           "*.png")))
             + sorted(glob.glob(os.path.join(ROOT, "shots", "deploy_probe",
                                             "f0*.png"))))
    files = [f for f in files if "_mask" not in f and "_annot" not in f]
    if args.max:
        files = files[:args.max]
    print(f"共 {len(files)} 帧")

    outdir = os.path.join(ROOT, "shots", "field_check")
    if args.shots:
        os.makedirs(outdir, exist_ok=True)

    problems = 0
    for fp in files:
        img = cv2.imread(fp)
        if img is None:
            continue
        name = os.path.basename(fp)
        field = board.read_field(img, debug=False)
        print(f"\n=== {name} ===")
        if not field["rows"]:
            print("    没找到任何卡行  <-- 可疑")
            problems += 1
            continue
        for i, r in enumerate(field["rows"]):
            desc = []
            for u in r["units"]:
                s = f"x{u['cx']}(w{u['w']})"
                if u["is_hq"]:
                    s += f"[HQ hp{u['hp']}]"
                desc.append(s)
            print(f"    行{i} cy≈{r['cy']:5.0f} {r['side']:<9} n={r['n']}  "
                  + " ".join(desc))
        print(f"    -> 我方支援 {len(field['our_support'])} 张, "
              f"敌方支援 {len(field['enemy_support'])} 张, "
              f"前线 {len(field['frontline'])} 张")
        print(f"    -> 我方总部 {field['hq_our']['hp'] if field['hq_our'] else None}, "
              f"敌方总部 {field['hq_enemy']['hp'] if field['hq_enemy'] else None}")
        # 最下面一行必须紧挨手牌(cy 应该明显大于中间行)
        if len(field["rows"]) >= 2:
            gap = field["rows"][-1]["cy"] - field["rows"][-2]["cy"]
            if gap < 80:
                print(f"    !! 最后两行太近(gap {gap:.0f})—— 可能把一张卡拆成了两行")
                problems += 1
        # 一行里的卡中心间距应该接近等距
        for r in field["rows"]:
            xs = [u["cx"] for u in r["units"]]
            if len(xs) >= 3:
                d = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
                if min(d) < 90:
                    print(f"    !! 行 cy{r['cy']:.0f} 卡间距过小 {d} —— 可能重复检测")
                    problems += 1
        if args.shots:
            annotate_field(img, field,
                           os.path.join(outdir, name.replace(".png", "_field.png")))

    print(f"\n看了 {len(files)} 帧,可疑 {problems} 处")
    if args.shots:
        print(f"标注图 -> {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
