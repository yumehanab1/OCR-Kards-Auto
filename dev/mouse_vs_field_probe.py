"""
mouse_vs_field_probe.py - 只读 A/B:**鼠标停在哪,会不会影响战场读数?**

为什么要做这个实验(2026-09-12 凌晨,实机观察):
    项目的 §10 "三个必须记住的坑" 第 3 条早就写了:
    **"读战场必须在鼠标位于 SAFE_POINT 时做"** —— 因为 bot 扫描手牌时鼠标在画面上,
    悬停产生的放大卡/信息面板本身也是"亮矩形",还会把真单位盖住。
    但 `attack.Attacker.run_turn()` 里**没有回 SAFE_POINT 这一步**:
    它就在"刚拖完牌、鼠标正停在我们自己单位上"的位置直接截图读盘面。
    实机表现是反复出现
        [attack] 没找到橙色费用徽章 -> 不攻击
        [attack] 读不到敌方总部,放弃攻击
    —— 而同一局里手写只读预检(`attack_probe.py`,它开头会 bring_to_front + 停顿)
    却能把徽章和总部都读出来。这个实验就是把"鼠标位置"这一个变量单独拎出来比。

做法(两次都只读,不动游戏):
    A) 鼠标停在原地 -> 截图 -> 读战场
    B) 鼠标移到 SAFE_POINT -> 等 1 秒 -> 截图 -> 读战场
    比较:行结构 / 我方支援线张数 / 徽章数与橙灰 / 敌方总部血量。

用法:
  .venv\\Scripts\\python.exe src\\mouse_vs_field_probe.py
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2  # noqa: E402

import board  # noqa: E402
import unit_state  # noqa: E402
from actions import set_cursor  # noqa: E402
from win import (bring_to_front, capture_client_bgr, client_to_screen,  # noqa: E402
                 find_by_process, set_dpi_aware, window_is_capturable)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAFE_POINT = (1270, 360)      # 和 hand_scanner_v2.SAFE_POINT 一致


def read(tag, frame):
    rows = board.rows_from_boxes(board.card_boxes(frame))
    badges = unit_state.find_cost_badges(frame, rows=rows)
    field = board.read_field(frame)
    hq = board.find_enemy_hq(frame, field=field)
    print(f"  [{tag}]")
    print(f"    行: " + " | ".join(
        f"cy{round(r['cy'])} n={len(r['boxes'])}" for r in rows) or "    行: (无)")
    print(f"    我方那一行 {len(field['our_support'])} 张 / "
          f"敌方那一行 {len(field['enemy_support'])} 张 / "
          f"前线 {len(field['frontline'])} 张")
    print(f"    徽章 {len(badges)} 个: "
          + ", ".join(f"x{b['x']}y{b['y']}({b['state'] or '?'},S{b['digit_s']:.0f})"
                      for b in badges))
    print(f"    敌方总部: " + (f"血量 {hq.get('hp')} @({hq['cx']},{hq['cy']})"
                              if hq else "**读不到**"))
    return {"rows": len(rows), "our": len(field["our_support"]),
            "badges": len(badges),
            "orange": sum(1 for b in badges if b["state"] == "orange"),
            "hq": hq.get("hp") if hq else None}


def main() -> int:
    set_dpi_aware()
    wins = find_by_process("kards")
    if not wins:
        print("找不到 kards 窗口")
        return 1
    hwnd = wins[0]["hwnd"]
    bring_to_front(hwnd)
    time.sleep(0.6)
    if not window_is_capturable(hwnd, quiet=False):
        print("窗口不可抓取 -> 停手")
        return 1

    os.makedirs(os.path.join(ROOT, "shots", "mouse_field"), exist_ok=True)

    f1 = capture_client_bgr(hwnd)
    if f1 is None:
        print("截图失败")
        return 1
    cv2.imwrite(os.path.join(ROOT, "shots", "mouse_field", "A_asis.png"), f1)
    a = read("A 鼠标原地不动", f1)

    sx, sy = client_to_screen(hwnd, *SAFE_POINT)
    set_cursor(sx, sy)
    time.sleep(1.0)
    f2 = capture_client_bgr(hwnd)
    if f2 is None:
        print("第二次截图失败")
        return 1
    cv2.imwrite(os.path.join(ROOT, "shots", "mouse_field", "B_safepoint.png"), f2)
    b = read("B 鼠标回 SAFE_POINT", f2)

    print()
    print(f"  对比: 徽章 {a['badges']} -> {b['badges']}"
          f"(橙 {a['orange']} -> {b['orange']});"
          f" 行 {a['rows']} -> {b['rows']};"
          f" 我方行 {a['our']} -> {b['our']};"
          f" 敌方总部 {a['hq']} -> {b['hq']}")
    if b["badges"] > a["badges"] or (b["hq"] and not a["hq"]):
        print("  => **鼠标位置确实影响读数**:回 SAFE_POINT 之后读得更多/"
              "更完整(§10 第 3 条那条规矩是对的)")
    elif a["badges"] == b["badges"] and a["hq"] == b["hq"]:
        print("  => 这一帧两者一致(不能据此说鼠标位置无关,只能说这一帧没被挡)")
    else:
        print("  => 原地反而读得更全 —— 需要再看几帧才能下结论")
    print(f"  两帧图 -> shots/mouse_field/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
