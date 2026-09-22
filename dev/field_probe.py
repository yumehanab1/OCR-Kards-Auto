"""
field_probe.py - **只读**探针:抓一帧(或读本地图),把"新一代战场读取"整条链路
打出来,并存一张标注图,供人眼核对。

它存在的理由:`board.py` 的 CLI 走的是**旧的** `read_board()`(`find_units` 那条
已弃用的路),所以命令行跑出来老是"我方 0 / 敌方 0"。新一代链路是
`merged_card_boxes -> rows_from_boxes -> read_field`,外加 `find_cost_badges`
(费用徽章,攻击的定位锚点)和 `find_enemy_hq`(整行 OCR 找总部血量)。

**只截图,不移动鼠标、不点击**(战场读取必须在鼠标位于安全点时做,
否则悬停面板会被当成卡)。

用法:
  .venv\\Scripts\\python.exe dev\\field_probe.py                 # 抓当前帧
  .venv\\Scripts\\python.exe dev\\field_probe.py --frame shots\\live_probe.png
  .venv\\Scripts\\python.exe dev\\field_probe.py --out shots\\x.png --raw
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2  # noqa: E402

import board  # noqa: E402
import unit_state  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def annotate(frame, field, boxes, badges, hq):
    out = frame.copy()
    colors = {"enemy": (0, 0, 255), "our": (0, 255, 0),
              "frontline": (0, 255, 255)}
    for i, r in enumerate(field["rows"]):
        col = colors.get(r["side"], (255, 255, 255))
        cv2.putText(out, f"row{i} cy{r['cy']:.0f} {r['side']} n={r['n']}",
                    (12, max(14, int(r["cy"]))),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1)
        for u in r["units"]:
            cv2.rectangle(out, (u["x"], u["y"]),
                          (u["x"] + u["w"], u["y"] + u["h"]), col, 2)
    for b in boxes:                       # 蓝 = 亮度掩码给的卡框
        if b.get("from") != "badge":
            cv2.rectangle(out, (b["x"], b["y"]),
                          (b["x"] + b["w"], b["y"] + b["h"]), (255, 0, 0), 1)
    for b in badges:                      # 绿 = 费用徽章
        cv2.rectangle(out, (b["x"] - 2, b["y"] - 2),
                      (b["x"] + b["w"] + 2, b["y"] + b["h"] + 2), (0, 255, 0), 2)
        cv2.putText(out, f"{b['state'] or '?'}", (b["x"], max(10, b["y"] - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
    if hq:                                # 品红 = 敌方总部(血量)
        cv2.rectangle(out, (hq["x"], hq["y"]),
                      (hq["x"] + hq["w"], hq["y"] + hq["h"]), (255, 0, 255), 2)
        cv2.putText(out, f"HQ-E hp{hq['hp']}", (hq["x"], hq["y"] - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="只读战场探针(不移动鼠标)")
    ap.add_argument("--frame", default=None, help="读本地图片,不抓屏")
    ap.add_argument("--out", default=None)
    ap.add_argument("--raw", action="store_true", help="顺带存一份原始帧")
    ap.add_argument("--types", action="store_true",
                    help="对我们的单位也跑一遍类型识别(慢,每张约 0.5s)")
    args = ap.parse_args()

    if args.frame:
        frame = cv2.imread(args.frame)
        if frame is None:
            print(f"读不到 {args.frame}")
            return 1
    else:
        from win import capture_client_bgr, find_by_process, set_dpi_aware

        set_dpi_aware()
        wins = find_by_process("kards")
        if not wins:
            print("找不到 kards 窗口")
            return 1
        frame = capture_client_bgr(wins[0]["hwnd"])
        if frame is None:
            print("截图失败(窗口被盖住/最小化?)")
            return 1

    templates = None
    if args.types:
        try:
            from ui_state import load_templates
            templates = load_templates()
        except Exception as exc:                # 诊断失败只丢功能,不许崩
            print(f"(类型识别不可用: {exc})")

    boxes = board.merged_card_boxes(frame, debug=False)
    badges = unit_state.find_cost_badges(frame)
    field = board.read_field(frame, templates=templates, debug=False)
    hq = board.find_enemy_hq(frame, field=field)

    print(f"合并卡框 {len(boxes)} 个 / 费用徽章 {len(badges)} 个")
    for i, r in enumerate(field["rows"]):
        desc = []
        for u in r["units"]:
            s = f"x{u['cx']}(w{u['w']},{u.get('from') or 'mask'})"
            if u["is_hq"]:
                s += f"[HQ hp{u['hp']}]"
            if u.get("type"):
                s += f"<{u['type']}>"
            desc.append(s)
        print(f"  行{i} cy≈{r['cy']:5.0f} {r['side']:<9} n={r['n']}  "
              + " ".join(desc))
    print(f"  -> 我方支援 {len(field['our_support'])} / "
          f"敌方支援 {len(field['enemy_support'])} / 前线 {len(field['frontline'])}")
    print(f"  -> 我方总部 {field['hq_our']['hp'] if field['hq_our'] else None} / "
          f"敌方总部 {hq['hp'] if hq else None}")
    if field["our_support"]:
        print("  我方支援线每张卡的 x: "
              + str([u["cx"] for u in field["our_support"]]))
    print("  徽章状态: " + str([(b["x"], b["state"], b["digit_s"])
                                for b in badges]))

    out = args.out or os.path.join(ROOT, "shots", "field_probe.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    cv2.imwrite(out, annotate(frame, field, boxes, badges, hq))
    print(f"标注图: {out}")
    if args.raw:
        raw = out.replace(".png", "_raw.png")
        cv2.imwrite(raw, frame)
        print(f"原始帧: {raw}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
