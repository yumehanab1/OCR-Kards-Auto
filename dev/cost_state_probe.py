"""
cost_state_probe.py - 标定"这回合还能不能行动"的判据(只读)。

背景(用户 2026-09-11 说明):
  **单位卡左上角的费用数字:橙色 = 这回合还能移动/攻击;灰色 = 本回合已行动。**
  (注意:卡上那个**盾牌**图标是"守护"特性,不是费用,也不是判据 —— 我认错过一次。)

这个脚本做的事情:
  1. 读 `config/templates.json` 里由 `template_capture.py` 存的 `cost_num` 区域
     (用户拖框存下来的**真值**,不再靠猜);
  2. 在真实帧上定位同一张卡,推出"费用数字"相对**卡左上角**的偏移;
  3. 对场上每一张卡按这个偏移裁出费用数字,量它的色相/饱和度/明度;
  4. 把每一张卡的裁图拼成一张总图存盘,并打印统计 —— 橙/灰要能分开,
     就得在这个统计里看到**两个峰**。

用法:
  # 先框一次(在游戏里):
  #   .venv\\Scripts\\python.exe src\\template_capture.py --names cost_num
  .venv\\Scripts\\python.exe src\\cost_state_probe.py            # 用当前实时画面
  .venv\\Scripts\\python.exe src\\cost_state_probe.py --frame shots/xxx.png
  .venv\\Scripts\\python.exe src\\cost_state_probe.py --sweep shots/deploy_probe/*.png
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

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import board  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
META = os.path.join(ROOT, "config", "templates.json")
OUTDIR = os.path.join(ROOT, "shots", "cost_state")


def load_cost_num_meta():
    """读用户框下来的 cost_num 区域 + 模板图。返回 (region, crop) 或 (None, None)。"""
    if not os.path.exists(META):
        return None, None
    with open(META, "r", encoding="utf-8") as f:
        meta = json.load(f)
    entry = meta.get("templates", {}).get("cost_num")
    if not entry:
        return None, None
    reg = entry.get("region")
    path = entry.get("path")
    if not reg or not path:
        return None, None
    img = cv2.imread(os.path.join(ROOT, path))
    return reg, img


def digit_stats(crop):
    """
    量一小块里"数字像素"的颜色。

    数字是这块里最亮的东西(深色方块上的浅色数字),所以取 V 最高的那一撮像素,
    再统计它们的 H/S。返回 dict 或 None。
    """
    if crop is None or crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    H, S, V = hsv[:, :, 0].astype(np.int16), hsv[:, :, 1], hsv[:, :, 2]
    # 取最亮的 15% 像素当作"数字字形"
    thr = np.percentile(V, 85)
    m = V >= max(thr, 110)
    if m.sum() < 8:
        return None
    return {
        "n": int(m.sum()),
        "h": float(H[m].mean()),
        "s": float(S[m].mean()),
        "v": float(V[m].mean()),
        "sat_hi_frac": float((S[m] > 90).mean()),
    }


def find_offset(frame, region, crop):
    """
    推出"费用数字区域"相对**卡左上角**的偏移。

    做法:在帧里找和 crop 最像的位置(模板匹配)-> 看它落在哪张卡的左上角附近
    -> 偏移 = 匹配位置 - 那张卡的左上角。
    """
    if crop is None:
        return None
    boxes = board.card_boxes(frame)
    if not boxes:
        return None
    res = cv2.matchTemplate(frame, crop, cv2.TM_CCOEFF_NORMED)
    _, best, _, loc = cv2.minMaxLoc(res)
    mx, my = int(loc[0]), int(loc[1])
    # 找"左上角在匹配点左上方、且距离最近"的那张卡
    cand = [b for b in boxes if b["x"] <= mx + 6 and b["y"] <= my + 6]
    if not cand:
        cand = boxes
    card = max(cand, key=lambda b: (b["x"] + b["y"]))
    dx, dy = mx - card["x"], my - card["y"]
    print(f"    模板匹配 分数={best:.3f} 位置=({mx},{my}) "
          f"最接近的卡 x{card['x']} y{card['y']} {card['w']}x{card['h']} "
          f"-> 偏移 dx={dx} dy={dy}")
    return dx, dy, best


def probe(frame, region, crop, dx, dy, tag, save=True):
    """对一帧里的每张卡裁出费用数字区域,量颜色,拼图存盘。"""
    boxes = board.card_boxes(frame)
    rows = board.rows_from_boxes(boxes)
    side_of = {}
    for r in rows:
        for b in r["boxes"]:
            side_of[id(b)] = r.get("side", "?")
    tiles, stats = [], []
    for b in boxes:
        x0, y0 = b["x"] + dx, b["y"] + dy
        x1, y1 = x0 + region["w"], y0 + region["h"]
        if x0 < 0 or y0 < 0 or x1 > frame.shape[1] or y1 > frame.shape[0]:
            continue
        c = frame[y0:y1, x0:x1]
        st = digit_stats(c)
        side = side_of.get(id(b), "?")
        stats.append((side, b["cx"], b["cy"], st))
        tiles.append(c)
        if st:
            print(f"    {side:<9} x{b['cx']:4d} y{b['cy']:4d}  "
                  f"H={st['h']:5.1f} S={st['s']:5.1f} V={st['v']:5.1f}  "
                  f"高饱和占比={st['sat_hi_frac']:.2f}")
    if save and tiles:
        os.makedirs(OUTDIR, exist_ok=True)
        hh = max(t.shape[0] for t in tiles)
        ww = max(t.shape[1] for t in tiles)
        sheet = np.zeros((hh, ww * len(tiles), 3), dtype=np.uint8)
        for i, t in enumerate(tiles):
            sheet[:t.shape[0], i * ww:i * ww + t.shape[1]] = t
        sheet = cv2.resize(sheet, None, fx=6, fy=6,
                           interpolation=cv2.INTER_NEAREST)
        p = os.path.join(OUTDIR, f"{tag}_cost_sheet.png")
        cv2.imwrite(p, sheet)
        print(f"    拼图 -> {p}")
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", default=None, help="用本地图片(默认抓实时画面)")
    ap.add_argument("--sweep", nargs="*", default=None,
                    help="在一批帧上跑(用于看橙/灰是不是两个峰)")
    args = ap.parse_args()

    region, crop = load_cost_num_meta()
    if region is None:
        print("还没标定: config/templates.json 里没有 cost_num 的 region。")
        print("请先跑一次(在游戏里拖框):")
        print("  .venv\\Scripts\\python.exe src\\template_capture.py --names cost_num")
        return 2
    print(f"cost_num 区域(用户框的): {region}")
    print(f"模板图: {crop.shape[1]}x{crop.shape[0]}" if crop is not None else "无模板图")

    if args.sweep:
        files = []
        for pat in args.sweep:
            files.extend(sorted(glob.glob(pat)))
        print(f"扫 {len(files)} 帧")
        dx = dy = None
        allstats = []
        for fp in files:
            img = cv2.imread(fp)
            if img is None:
                continue
            if dx is None:
                got = find_offset(img, region, crop)
                if not got:
                    continue
                dx, dy, _ = got
                print(f"  用第一帧定出偏移 dx={dx} dy={dy}")
            print(f"  {os.path.basename(fp)}")
            allstats += probe(img, region, crop, dx, dy,
                              os.path.basename(fp).replace(".png", ""),
                              save=False)
        print(f"\n共 {len(allstats)} 张卡。按 H(色相) 看分布:")
        hs = [s["h"] for _side, _x, _y, s in allstats if s]
        ss = [s["s"] for _side, _x, _y, s in allstats if s]
        if hs:
            print(f"  H: min {min(hs):.1f} max {max(hs):.1f} 均值 {np.mean(hs):.1f}")
            print(f"  S: min {min(ss):.1f} max {max(ss):.1f} 均值 {np.mean(ss):.1f}")
            hist, edges = np.histogram(ss, bins=8, range=(0, 240))
            for i, c in enumerate(hist):
                print(f"    S {int(edges[i]):3d}-{int(edges[i+1]):3d}: {c:3d} "
                      + "#" * c)
        return 0

    if args.frame:
        img = cv2.imread(args.frame)
        if img is None:
            print(f"读不到 {args.frame}")
            return 1
        tag = os.path.basename(args.frame).replace(".png", "")
    else:
        from win import capture_client_bgr, find_by_process, set_dpi_aware
        set_dpi_aware()
        w = find_by_process("kards")
        if not w:
            print("找不到 kards 窗口")
            return 1
        img = capture_client_bgr(w[0]["hwnd"])
        if img is None:
            print("截图失败")
            return 1
        tag = "live"

    got = find_offset(img, region, crop)
    if not got:
        print("定位失败(场上没有卡?)")
        return 1
    dx, dy, _ = got
    print("每张卡的费用数字区域:")
    probe(img, region, crop, dx, dy, tag)
    return 0


if __name__ == "__main__":
    sys.exit(main())
