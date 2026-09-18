"""
unit_state_test.py - 离线验证"这回合还能不能行动"的判据(不需要游戏)。

判据(用户 2026-09-11 确认):**单位卡左上角的费用数字,橙=能行动,灰=已行动。**
实测(shots/badge/live.png 人工核对):
    能行动(橙)  S ≈ 116 ~ 178
    不能行动(灰) S ≈  17 ~  60
    中间(73~80)读不准 -> 一律当"不能行动"

这个测试用**合成帧**把判据钉死:
  1. 深色方块 + 橙色数字 -> 'orange'
  2. 深色方块 + 灰色数字 -> 'grey'
  3. 深色方块 + 中间饱和度 -> None(读不准),而且 can_attack() 必须返回 False
  4. 没有徽章的帧 -> 空列表(不能瞎报)
  5. 手牌区的徽章必须被排除(否则手牌的颜色会污染判据)

用法:
  .venv\\Scripts\\python.exe src\\unit_state_test.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import board  # noqa: E402
import unit_state  # noqa: E402

CLOTH = (60, 70, 60)          # 深青色桌面(BGR)


def make_frame():
    """一块桌布 + 一张"卡"(浅色顶条带),卡左上角一个深色费用徽章。"""
    f = np.zeros((720, 1280, 3), dtype=np.uint8)
    f[:, :] = CLOTH
    return f


def put_card(f, x, y):
    """画一张卡:浅色顶条带 + 浅色卡身(足够亮,能通过卡面判据)。"""
    cv2.rectangle(f, (x, y), (x + 130, y + 146), (170, 180, 175), -1)
    cv2.rectangle(f, (x, y), (x + 130, y + 28), (185, 195, 190), -1)
    return f


def put_badge(f, x, y, hsv_color, size=18):
    """在 (x,y) 画一个深色徽章,里面一个该颜色的数字。"""
    cv2.rectangle(f, (x, y), (x + size, y + size), (60, 60, 62), -1)
    digit = np.uint8([[hsv_color]])
    bgr = cv2.cvtColor(digit, cv2.COLOR_HSV2BGR)[0, 0]
    cv2.rectangle(f, (x + 6, y + 3), (x + 11, y + size - 3),
                  tuple(int(c) for c in bgr), -1)
    return f


def hsv_bgr(h, s, v):
    """HSV(OpenCV 尺度)-> BGR 元组。"""
    px = np.uint8([[[h, s, v]]])
    b, g, r = cv2.cvtColor(px, cv2.COLOR_HSV2BGR)[0, 0]
    return int(b), int(g), int(r)


def put_badge_bg(f, x, y, bg_bgr, digit_hsv, size=18):
    """
    画一个**底色可选**的徽章。

    ★ 为什么需要它:金边卡上徽章的底色是**深棕(高饱和)**,
    而"数字像素"的旧判据是绝对的 `(V>135)|(S>90)` —— 它会把深棕底色
    整块算成"数字",平均饱和度被拉到 135+,**灰数字被判成橙色**。
    这个合成用例就是钉死这条(见下面 CASE 7)。
    """
    cv2.rectangle(f, (x, y), (x + size, y + size), bg_bgr, -1)
    db, dg, dr = hsv_bgr(*digit_hsv)
    cv2.rectangle(f, (x + 6, y + 3), (x + 11, y + size - 3), (db, dg, dr), -1)
    return f


problems = 0


def check(name, cond, extra=""):
    global problems
    print(f"  {'OK ' if cond else 'FAIL'} {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        problems += 1


print("=" * 78)
print("CASE 1: 橙色数字(还能行动) / 灰色数字(已行动)")
print("=" * 78)
# 实测橙色 S≈116~178、灰色 S≈17~60
f = make_frame()
put_card(f, 300, 440)                      # 我方那一行
put_badge(f, 303, 444, (20, 170, 210))     # H=20(橙), S=170, V=210
put_card(f, 500, 440)
put_badge(f, 503, 444, (20, 30, 200))      # S=30(灰)
badges = unit_state.find_cost_badges(f, debug=True)
states = sorted(b["state"] for b in badges)
print(f"    -> {[b['state'] for b in badges]}  S={[b['digit_s'] for b in badges]}")
check("找出 2 个徽章", len(badges) == 2, f"实得 {len(badges)}")
check("一个是 orange 一个是 grey", states == ["grey", "orange"], str(states))
orange = [b for b in badges if b["state"] == "orange"]
check("橙色徽章的 S 明显高于阈值",
      bool(orange) and orange[0]["digit_s"] >= unit_state.SAT_ORANGE_MIN,
      f"S={orange[0]['digit_s'] if orange else None}")

print()
print("=" * 78)
print("CASE 2: 中间饱和度 -> 读不准 -> can_attack 必须返回 False")
print("=" * 78)
# ★ 2026-09-11 晚**重新标定**:数字判据换成"被暗包住的亮块"之后,
#   实测灰 <= 105、橙 >= 130,**空档是 105~130**(见 unit_state.SAT_GREY_MAX
#   上面那段实测记录)。所以"灰带里的样本"从旧的 S=90 挪到 S=115
#   —— 这是跟着**测量结果**走,不是"为了让测试过而放宽判据"。
f2 = make_frame()
put_card(f2, 300, 440)
put_badge(f2, 303, 444, (20, 115, 200))    # S=115 落在灰带 (105,120) 里
b2 = unit_state.find_cost_badges(f2)
print(f"    -> {[(b['state'], b['digit_s']) for b in b2]}")
check("灰带里判成 None", b2 and b2[0]["state"] is None, str(b2))
card_box = {"x": 300, "y": 440, "w": 130, "h": 146}
check("can_attack 保守返回 False",
      unit_state.can_attack(f2, card_box) is False)
check("can_move_to_front 同样保守",
      unit_state.can_move_to_front(f2, card_box) is False)

print()
print("=" * 78)
print("CASE 3: 没有徽章的帧不能瞎报")
print("=" * 78)
f3 = make_frame()
put_card(f3, 300, 440)                     # 只有卡,没有徽章
b3 = unit_state.find_cost_badges(f3)
check("空列表", b3 == [], str(b3))
check("can_attack 返回 False", unit_state.can_attack(f3, card_box) is False)

print()
print("=" * 78)
print("CASE 4: 手牌区的徽章必须被排除")
print("=" * 78)
f4 = make_frame()
put_card(f4, 300, 560)                     # y=560 属于手牌区
put_badge(f4, 303, 564, (20, 170, 210))
b4 = unit_state.find_cost_badges(f4)
check("手牌区的徽章不算", b4 == [], str(b4))
f5 = make_frame()
put_card(f5, 300, 300)                     # y=300 是前线,算板面
put_badge(f5, 303, 304, (20, 170, 210))
b5 = unit_state.find_cost_badges(f5)
check("板面上的徽章算", len(b5) == 1, str(b5))

print()
print("=" * 78)
print("CASE 5: actionable_units 只返回橙色徽章,并给出拖动起手点")
print("=" * 78)
f6 = make_frame()
put_card(f6, 300, 440)
put_badge(f6, 303, 444, (20, 170, 210))    # 橙 -> 可行动
put_card(f6, 500, 440)
put_badge(f6, 503, 444, (20, 30, 200))     # 灰 -> 不可行动
units = unit_state.actionable_units(f6)
print(f"    -> {[(u['badge']['state'], u['src']) for u in units]}")
check("只返回 1 个(橙色的那个)", len(units) == 1, str(len(units)))
if units:
    u = units[0]
    sx, sy = u["src"]
    check("起手点落在卡身上(不是徽章上,也不是卡外)",
          u["box"]["x"] < sx < u["box"]["x"] + u["box"]["w"]
          and u["box"]["y"] < sy < u["box"]["y"] + u["box"]["h"],
          f"src=({sx},{sy}) box={u['box']}")
    check("认不出类型时 type 为 None(调用方会拒绝拖)",
          u["type"] is None, str(u["type"]))

print()
print("=" * 78)
print("CASE 6: ★ 徽章和暗桌布粘成一片时,行带补检必须还能找到它")
print("=" * 78)
print("""  背景(2026-09-11 晚,离线 + 实机对照找到的真 bug):
    金边卡的徽章深色方块和卡的深色左/上边框连在一起、再连到暗桌面 ——
    整个连通域变成 770x440,被尺寸过滤丢掉。
    实测 shots/board_samples/0911_122530_001.png:我方支援线 3 张**带徽章的**
    单位卡一个都检不出 -> 攻击被自己拒掉(ALLOW_BOX_FALLBACK=False)。""")
f7 = make_frame()
put_card(f7, 300, 440)
put_badge(f7, 300, 440, (20, 150, 210))    # 贴在卡的左上角,和桌布直接相连
_cc = unit_state._badges_cc(f7)
_rows7 = board.rows_from_boxes(board.card_boxes(f7))
_uni = unit_state.find_cost_badges(f7, rows=_rows7)
print(f"    连通域版 {len(_cc)} 个 / 合并 {len(_uni)} 个: "
      f"{[(b['from'], b['state']) for b in _uni]}")
check("连通域版确实检不出(它和桌布是一个连通域)", len(_cc) == 0,
      str([(b["x"], b["y"]) for b in _cc]))
check("合并后找到 1 个,而且是橙色的", len(_uni) == 1
      and _uni[0]["state"] == "orange", str(_uni))
check("而且知道它是补检找出来的(from='band')",
      bool(_uni) and _uni[0]["from"] == "band",
      _uni[0]["from"] if _uni else "无")

print()
print("=" * 78)
print("CASE 7: ★ 饱和深棕底色 + 灰数字 -> 必须是 grey,**绝不能**报 orange")
print("=" * 78)
print("""  背景:旧判据 `(V>135)|(S>90)` 是**绝对**的,金边卡徽章的深棕底色
    (实测 S≈137~149)被整块算成"数字像素",平均饱和度被拉到 135+ ->
    一个**已行动的灰数字**被判成"能行动"。这正是"把不能行动的牌拖出去"的来源。
    实测抓到过 `18x18 S=135.3 V=53.3 n=316 -> orange`(n=316/324)。""")
f8 = make_frame()
put_card(f8, 300, 440)
put_badge_bg(f8, 303, 444, hsv_bgr(14, 145, 46), (0, 20, 200))   # 深棕底+灰数字
b8 = unit_state.find_cost_badges(f8)
print(f"    -> {[(b['state'], b['digit_s'], b['digit_n']) for b in b8]}")
check("检出 1 个", len(b8) == 1, str(b8))
check("判成 grey(不是 orange)", bool(b8) and b8[0]["state"] == "grey",
      str(b8[0]["state"]) if b8 else "无")
check("数字像素不会把整块底色算进去(n 远小于 324)",
      bool(b8) and b8[0]["digit_n"] < 200,
      str(b8[0]["digit_n"]) if b8 else "无")

print()
print("=" * 78)
print("CASE 8: ★ 补检的 digit_n 下限:木纹/图标牌那类假阳性必须被挡掉,真徽章一个都不能掉")
print("=" * 78)
print("""  背景(2026-09-12 第六个会话,实机三例 + 语料 A/B,见 PROJECT_STATE §7 第 77 条):
    · `0912_153308` x857y453:蓝图桌上的圆圈 -> 支援线 4 个单位读成 5;
    · `0912_154321` x706y462:**木桌木纹,而且是橙色** -> 被当成"能行动的我方单位";
    · `0912_154730` x571y107:敌方格总部旁边那个"深色小方块 + 亮色齿轮图标"的**卡上图标牌**。
    语料里 band 上 digit_n<=29 的 7 个**逐个放大看过全是假的**,而真徽章最低 35 ->
    阈值 32 落在空档正中,只加在**补检**这条路(主判据 244 个样本最低就是 35)。""")
f9 = make_frame()
put_card(f9, 300, 440)
put_badge(f9, 300, 440, (20, 150, 210))          # 真徽章:数字 6x12 = 72px
put_card(f9, 470, 440)                           # 右边再来一张卡,给假阳性当"亮卡面"背景
# 假阳性:紧贴右边那张卡左边缘的"深色小方块 + 一个很小的亮块"(= 图标牌 / 木纹的形状)
cv2.rectangle(f9, (452, 452), (470, 470), (60, 60, 62), -1)
cv2.rectangle(f9, (458, 455), (461, 461), (210, 205, 200), -1)   # 实测 digit_n≈28
_rows9 = board.rows_from_boxes(board.card_boxes(f9))
_old9 = unit_state.find_cost_badges_band(f9, _rows9, digit_min=0)     # 旧行为(A/B)
_new9 = unit_state.find_cost_badges_band(f9, _rows9)                  # 新行为(带下限)
print(f"    旧(不做下限) {len(_old9)} 个: "
      f"{[(b['x'], b['y'], b['digit_n']) for b in _old9]}")
print(f"    新(下限 {unit_state.BAND_DIGIT_MIN_PX}) {len(_new9)} 个: "
      f"{[(b['x'], b['y'], b['digit_n']) for b in _new9]}")
check("旧行为下确实会多出那个假阳性(否则这条用例什么也没证明)",
      len(_old9) == 2, str([(b["x"], b["y"], b["digit_n"]) for b in _old9]))
check("加上下限后只剩真徽章那一个",
      len(_new9) == 1 and _new9[0]["digit_n"] == 78,
      str([(b["x"], b["y"], b["digit_n"]) for b in _new9]))
check("真徽章的 digit_n 在下限之上(没被误杀)",
      bool(_new9) and _new9[0]["digit_n"] >= unit_state.BAND_DIGIT_MIN_PX,
      str(_new9[0]["digit_n"]) if _new9 else "无")

print()
print("=" * 78)
print("全部通过" if problems == 0 else f"有 {problems} 项失败")
print("=" * 78)
sys.exit(0 if problems == 0 else 1)
