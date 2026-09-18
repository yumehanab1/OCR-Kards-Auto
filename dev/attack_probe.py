"""
attack_probe.py - 攻击的实机预检 / 单发试打(默认**只读**)。

为什么要有它:攻击是"会动游戏"的动作,而它的每一步判据都可能出错
(徽章认错 -> 拖错单位;总部认错 -> 打空;类型认错 -> 拖了不该拖的)。
所以先做一次**只读预检**,把"我看到了什么"全部打出来人工核对,
确认无误之后再 `--fire` 真打一发。

用法:
  .venv\\Scripts\\python.exe src\\attack_probe.py              # 只读预检
  .venv\\Scripts\\python.exe src\\attack_probe.py --fire        # 真打一发并验证
  .venv\\Scripts\\python.exe src\\attack_probe.py --fire --n 3  # 最多打 3 发

预检会打印:
  1. 战场行(自适应行带:上=敌方 / 中=前线 / 下=我方)
  2. **费用徽章**:每个徽章的位置 + 数字饱和度 + 判成橙/灰
  3. 我方可行动单位(橙色) + 类型 + 拖动起手点
  4. 敌方总部位置 + 血量
  5. 标注图(徽章按橙/灰上色,总部画框)
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import board  # noqa: E402
import unit_state  # noqa: E402
from win import (bring_to_front, capture_client_bgr, find_by_process,  # noqa: E402
                 set_dpi_aware, window_is_capturable)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "shots", "attack_probe")


def annotate(frame, field, badges, hq, units):
    out = frame.copy()
    for r in field["rows"]:
        cv2.putText(out, f"row{r['cy']:.0f} {r['side']} n={r['n']}",
                    (20, int(r["cy"])), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (255, 255, 255), 1)
        for u in r["units"]:
            col = {"enemy": (0, 0, 255), "our": (0, 255, 0),
                   "frontline": (0, 255, 255)}.get(r["side"], (200, 200, 200))
            cv2.rectangle(out, (u["x"], u["y"]),
                          (u["x"] + u["w"], u["y"] + u["h"]), col, 1)
    for b in badges:
        col = {"orange": (0, 165, 255), "grey": (128, 128, 128),
               None: (255, 0, 255)}[b["state"]]
        cv2.rectangle(out, (b["x"] - 2, b["y"] - 2),
                      (b["x"] + b["w"] + 2, b["y"] + b["h"] + 2), col, 2)
        cv2.putText(out, f"S{b['digit_s']:.0f}", (b["x"], b["y"] - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, col, 1)
    for u in units:
        cv2.circle(out, u["src"], 6, (255, 0, 255), 2)
        cv2.putText(out, f"FIRE {u.get('type')}", (u["src"][0] + 8, u["src"][1]),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 2)
    if hq:
        cv2.rectangle(out, (hq["x"] - 4, hq["y"] - 4),
                      (hq["x"] + hq["w"] + 4, hq["y"] + hq["h"] + 4),
                      (255, 0, 255), 3)
        cv2.putText(out, f"HQ hp{hq.get('hp')}", (hq["x"], hq["y"] - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 255), 2)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fire", action="store_true", help="真打(默认只读)")
    ap.add_argument("--n", type=int, default=1, help="最多打几发")
    ap.add_argument("--move-front", action="store_true",
                    help="试一次【上前线】:把我方最左边那个单位拖到前线空位,"
                         "并对比拖前/拖后的战场来验证到底动没动")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    set_dpi_aware()
    wins = find_by_process("kards")
    if not wins:
        print("找不到 kards 窗口")
        return 1
    hwnd = wins[0]["hwnd"]
    bring_to_front(hwnd)
    time.sleep(1.0)
    if not window_is_capturable(hwnd, quiet=False):
        print("窗口不可抓取(被挡住/最小化)-> 停手")
        return 1

    templates = None
    try:
        from ui_state import load_meta, load_templates
        meta = load_meta(os.path.join(ROOT, "config", "templates.json"))
        templates = load_templates(meta)
        print(f"模板 {len(templates)} 个(类型图标 {sum(1 for k in templates if k.endswith('_icon'))} 个)")
    except Exception as e:
        print(f"加载模板失败: {type(e).__name__}: {e}(类型会全是 None,攻击会全部跳过)")

    frame = capture_client_bgr(hwnd)
    if frame is None:
        print("截图失败")
        return 1

    print("\n=== 1) 战场行 ===")
    field = board.read_field(frame, templates=templates, debug=False)
    for i, r in enumerate(field["rows"]):
        desc = []
        for u in r["units"]:
            s = f"x{u['cx']}(w{u['w']},h{u['h']})"
            if u["is_hq"]:
                s += f"[HQ hp{u['hp']}]"
            if u.get("type"):
                s += f"<{u['type']}>"
            desc.append(s)
        print(f"  行{i} cy≈{r['cy']:5.0f} {r['side']:<9} n={r['n']}  "
              + " ".join(desc))
    if not field["rows"]:
        print("  (没找到任何卡行 —— 现在不是对局画面?)")

    print("\n=== 2) 费用徽章(橙=能行动 / 灰=已行动) ===")
    badges = unit_state.find_cost_badges(frame)
    for b in badges:
        print(f"  x{b['x']:4d} y{b['y']:4d} {b['w']:2d}x{b['h']:2d}  "
              f"S={b['digit_s']:6.1f} V={b['digit_v']:5.1f} -> {b['state']}")
    if not badges:
        print("  (一个都没找到)")

    print("\n=== 3) 我方可行动单位(橙色徽章) ===")
    units = unit_state.actionable_units(frame, templates=templates)
    for u in units:
        b = u["badge"]
        print(f"  徽章 x{b['x']} y{b['y']} (S={b['digit_s']})  "
              f"类型={u.get('type')}  拖动起手点={u['src']}")
    if not units:
        print("  (没有橙色徽章 —— 现在不是我们的回合,或者都行动过了)")

    # ★★ 2026-09-12 新增:前线归属(用户给的判据是那条黑线的位置:靠上=友方 / 在下边=敌方)
    #   步兵/坦克只打得到"敌方前线那一行",所以攻击规则直接依赖它;
    #   读不出来引擎会 fail-closed(不攻击),这一栏就是用来一眼确认的。
    print("\n=== 3b) 前线归属(黑线位置) ===")
    try:
        import frontline_line
        info = frontline_line.read_frontline_owner(frame=frame, debug=True)
        names = {"our": "我方", "enemy": "敌方", "neutral": "空着/中立"}
        print(f"  {info['why']}")
        print(f"  => {(names.get(info['owner']) or '读不出(→ 步兵/坦克不攻击)')}")
    except Exception as e:
        print(f"  读归属出错: {type(e).__name__}: {e}")

    print("\n=== 4) 敌方总部 ===")
    hq = board.find_enemy_hq(frame, field=field, templates=templates)
    if hq:
        print(f"  x{hq['x']} y{hq['y']} {hq['w']}x{hq['h']}  "
              f"血量={hq.get('hp')}  中心=({hq['cx']},{hq['cy']})")
    else:
        print("  (没读出来 —— 攻击会放弃)")

    os.makedirs(args.out, exist_ok=True)
    p = os.path.join(args.out, time.strftime("%m%d_%H%M%S") + "_probe.png")
    cv2.imwrite(p, annotate(frame, field, badges, hq, units))
    print(f"\n标注图 -> {p}")

    if not args.fire and not args.move_front:
        print("\n(只读预检结束。确认上面都对,再加 --fire 真打)")
        return 0

    if args.move_front:
        # ---------------- 试一次"上前线" ----------------
        # 用户 2026-09-11 说明:**移动 = 把单位拖到前线的空位;前线最多 5 个。**
        # 这是 attack.move_unit_to_front() 第一次实机跑,所以:
        #   1. 落点用**实测的前线行位置**推,不用那个写死的 y=500
        #      (实测 y500 落在我方支援线里,拖了等于原地放下)
        #   2. 拖前/拖后各读一次战场,用"我方那一行少了一张、中间多了一行"
        #      来验证到底动没动
        print("\n=== 6) 试一次【上前线】(会真的拖一次) ===")
        if not units:
            print("没有橙色徽章单位(不是我们的回合?),放弃")
            return 1
        rows = field["rows"]
        if len(rows) >= 3:
            front_cy = int(rows[1]["cy"])
        else:
            # 只有两行时,前线在两行中间(实测三条线 y≈175/350/525)
            front_cy = int((rows[0]["cy"] + rows[-1]["cy"]) / 2)
        src = units[0]["src"]
        dst = (src[0], front_cy)
        print(f"  单位起手点 {src} -> 前线落点 {dst}"
              f"(前线行 y≈{front_cy};我方行 y≈{int(rows[-1]['cy'])};"
              f"敌方行 y≈{int(rows[0]['cy'])})")
        import board as _b
        from win import client_to_screen
        from actions import move_drag
        n0 = len(field["our_support"])
        n_front0 = len(field["frontline"])
        sx, sy = client_to_screen(hwnd, src[0], src[1])
        dx, dy = client_to_screen(hwnd, dst[0], dst[1])
        move_drag(sx, sy, dx, dy)
        time.sleep(1.4)
        after = capture_client_bgr(hwnd)
        f2 = _b.read_field(after, templates=templates)
        n1 = len(f2["our_support"])
        n_front1 = len(f2["frontline"])
        print(f"  我方支援线: {n0} -> {n1}")
        print(f"  前线:       {n_front0} -> {n_front1}")
        for i, r in enumerate(f2["rows"]):
            print(f"    拖后 行{i} cy≈{r['cy']:.0f} {r['side']:<9} n={r['n']}")
        if n1 < n0:
            print("  => **动成功了**(我方那一行少了一张)")
        elif n_front1 > n_front0:
            print("  => **动成功了**(中间多了一行 = 上前线)")
        else:
            print("  => 没动(被拒绝:前线归属不对 / 满 / 落点不对)")
        p2 = os.path.join(args.out, time.strftime("%m%d_%H%M%S") + "_movefront.png")
        cv2.imwrite(p2, after)
        print(f"  拖后帧 -> {p2}")
        return 0

    # ---------------- 真打 ----------------
    print(f"\n=== 5) 真打(最多 {args.n} 发) ===")
    if hq is None:
        print("没有敌方总部,放弃")
        return 1
    from attack import Attacker, can_attack_from_support

    atk = Attacker(hwnd, log=print, debug=False, templates=templates,
                   max_attacks=args.n)
    attempts, landed = atk.run_turn()
    print(f"\n结果:尝试 {attempts} 次,打中 {landed} 次")
    after = capture_client_bgr(hwnd)
    if after is not None:
        hp2 = board.read_hq_hp(after, hq)
        print(f"敌方总部血量: 打之前 {hq.get('hp')} -> 打之后 {hp2}")
        p2 = os.path.join(args.out, time.strftime("%m%d_%H%M%S") + "_after.png")
        cv2.imwrite(p2, after)
        print(f"打后帧 -> {p2}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
