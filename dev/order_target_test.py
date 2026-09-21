# -*- coding: utf-8 -*-
"""
order_target_test.py - 「target 指令往哪拖」的**离线**用例(不需要游戏、不需要屏幕)。

只考这些(其余是实机的事):
  ① 每个目标码(1~6)都**能挑出目标**,而且挑不出时**返回 None**(fail-closed);
  ② 行码 a/b/c/d 的收窄真的生效(只满足/只不满足的假 field 各造一个);
  ③ ★ 前线归属读不出时,**绝不**把前线单位当成我方/敌方(这条最重要);
  ④ kind 7(三选一)和带 follow 的两步卡:**一定不返回坐标**;
  ⑤ `PLAY_TARGETS=False` 时 `orders.playable()` 不放行 target(A/B 开关能一句话退回去);
  ⑥ 同一输入跑两次,结果**完全一样**(确定性);
  ⑦ 引擎那一侧的接线(hand_xs 的合并/排除、`think()` 真的把落点当成目标卡中心、
     而且 target 指令**只按费用对账判成败**)。
  ⑧ ★★ 2026-09-21 用户两条决定带出来的判据:
     · kind 6「随意阵营单位」= **一条规则:`KIND6_SIDE = "enemy"`**
       (用户原话"kind6全部指敌方");逐卡定向表那两层结构已删掉;
       `rows` 的收窄照旧生效(6-cd + 敌方 => 只剩 c;6-ab + 敌方 => 只剩 a);
     · kind 5「选择一张手牌」= **整档按黑名单处理**(`orders.KIND5_AS_BLACKLIST`):
       `playable()` 不放行、`is_blacklisted()` 为真 -> 引擎会给"别带这张"的提示;
       本模块那段实现保留当兜底(只挑认得出是单位的那张,认不出就不打);
     · `status()` 那行启动日志的**每个数字都要和逐卡判定对得上**(账要平)。
  ⑨ `why` 里那句"行偏好顺序"必须**从 `ROW_RANK` 现生成**(旧版手写副本漏了
     "我方前线"那一档 -> 日志撒谎)。

★ 假 field 必须和 `board.read_field` 的返回值**同构**(键名、单位 dict 的 cx/cy/is_hq、
  行的 side/cy/boxes 都在)。喂一个"差不多"的结构,`order_target` 的 fail-closed 会
  把用例变成**假绿** —— 那就白测了。

用法:
  cd /d D:\\kards-auto-repo
  set PYTHONPATH=src
  D:\\kards-auto\\python\\python.exe -u dev\\order_target_test.py
"""

from __future__ import annotations

import inspect
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "src"))
sys.path.insert(0, _HERE)          # 用例要 import dev/order_plan.py(比对目标码语义)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np            # noqa: E402

import board                  # noqa: E402
import frontline_line         # noqa: E402
import order_target           # noqa: E402
import order_plan             # noqa: E402  (dev/order_plan.py:TARGET_KIND 的权威定义)
import orders                 # noqa: E402
import turn_engine            # noqa: E402

ALLOK = True
#: 离线假帧。★ 它全黑 —— 真让它去读"前线那条黑线"是读不出来的(这正是我们要的:
#:  "读不出归属"这条分支必须能被离线触发,见 §③)。
FRAME = np.zeros((720, 1280, 3), dtype=np.uint8)

#: 真判据(用例要临时换成脚本化的归属,测完必须还回来)
REAL_OWNER = frontline_line.read_frontline_owner


def C(label, cond, extra=""):
    global ALLOK
    ALLOK &= bool(cond)
    print(f"  {'OK ' if cond else 'FAIL'} {label}" + (f"   {extra}" if extra else ""))


# ---------------------------------------------------------------------------
# 造一个和 board.read_field 同构的假 field
# ---------------------------------------------------------------------------
def unit(cx, cy, is_hq=False):
    """一张卡的框(字段名照 `board.card_boxes` / `read_field` 抄)。"""
    return {"x": cx - 60, "y": cy - 70, "w": 120, "h": 140, "cx": cx, "cy": cy,
            "is_hq": is_hq, "hp": (20 if is_hq else None), "type": None}


def row_of(side, cy, units):
    return {"cy": float(cy), "y0": cy - 70, "y1": cy + 70,
            "boxes": list(units), "units": list(units), "side": side,
            "n": len(units)}


def mkfield(enemy_support=(), our_support=(), frontline=(), hq_enemy=None,
            extra_rows=()):
    """
    假 field。三个单位列表的元素都是 `(cx, cy, is_hq)`,前线用 `(cx, cy, False)`。

    `hq_enemy` = (cx, cy) 时**同时**把它放进敌方支援线那一行 —— 真实实现就是这样
    (`read_field` 是从敌方支援线的卡里找 `is_hq` 得出 `hq_enemy` 的)。
    `extra_rows` 用来塞"结构在、但这一档用不到"的行(造"行在、候选没有"的场景)。
    """
    es = [unit(*t) for t in enemy_support]
    us = [unit(*t) for t in our_support]
    fl = [unit(*t) for t in frontline]
    hq = None
    if hq_enemy is not None:
        hq = unit(hq_enemy[0], hq_enemy[1], True)
        es = es + [hq]
    rows = []
    if es:
        rows.append(row_of("enemy", 180, es))
    if fl:
        rows.append(row_of("frontline", 350, fl))
    if us:
        rows.append(row_of("our", 525, us))
    for r in extra_rows:
        rows.append(r)
    return {"rows": rows, "enemy_support": es, "our_support": us,
            "frontline": fl, "our_units": us, "enemy_units": es,
            "hq_enemy": hq, "hq_our": None}


def owner_fake(owner, why="(用例构造的归属)"):
    """把"读前线归属"换成脚本化的结论(测完必须 `owner_real()` 还回去)。"""
    def _f(frame=None, hwnd=None, debug=False, field=None):
        return {"owner": owner, "band_y": 269, "front_y": 350.0,
                "delta": -81.0, "score": 0.9, "why": why}
    frontline_line.read_frontline_owner = _f


def owner_real():
    frontline_line.read_frontline_owner = REAL_OWNER


def real_card(kind, rows="", follow=""):
    """
    从**真表**里现取一张满足条件的 target 卡(表更新了用例不会跟着烂)。

    写死卡名会在表被改坏时报错在奇怪的地方;而"现取 + 断言取到了"能同时钉住
    "表里确实还有这一类卡"。
    """
    for nm, r in (orders._CARDS or {}).items():
        if (r.get("mode") == orders.MODE_TARGET
                and (r.get("kind") or "") == kind
                and (r.get("rows") or "") == rows
                and (r.get("follow") or "") == follow):
            return nm
    return None


def logs_of(fn):
    """跑一次 pick,把日志收成 list 返回 (结果, 日志)。"""
    out = []
    got = fn(out.append)
    return got, out


print("=" * 92)
print("① 前置:模块/语义/状态行(判据的来源对不对)")
print("=" * 92)
orders._CARDS = None                  # 强制重新载入真表
print("  " + orders.status())
C("打法表载入了", len(orders._CARDS or {}) > 600, f"实得 {len(orders._CARDS or {})} 张")
C("status() 仍能看出分档(可直接打出/需要目标/抉择/黑名单都在)",
  all(k in orders.status() for k in ("可直接打出", "需要目标", "抉择", "黑名单")))
C("status() 如实说清了「本局打哪两档」",
  "两档" in orders.status() and "kind 1~4/6" in orders.status(), orders.status()[:60] + "…")
C("status() 点名了**没做**的那几档(不许写成'指令都能打了')",
  "三选一(kind 7)" in orders.status() and "抉择" in orders.status())
C("status() 点名 kind 5 归黑名单(2026-09-21 用户决定)",
  "kind 5" in orders.status() and "黑名单" in orders.status()
  and "kind 1~6" not in orders.status(), orders.status()[:60] + "…")
# ★ 目标码的语义**以 dev/order_plan.py 的 TARGET_KIND 为准**;order_target.KIND_TEXT
#   只是日志用的展示副本。这一条把"副本"钉死在"正本"上 —— 抄错就跑红。
for k in ("1", "2", "3", "4", "5", "6", "7"):
    C(f"KIND_TEXT[{k}] 与 dev/order_plan.py:TARGET_KIND 一致",
      order_target.KIND_TEXT.get(k) == order_plan.TARGET_KIND.get(k),
      f"{order_target.KIND_TEXT.get(k)!r} vs {order_plan.TARGET_KIND.get(k)!r}")
for k in ("a", "b", "c", "d"):
    C(f"ROW_RANK 覆盖行码 {k}(语义:{order_plan.ROW_KIND[k]})", k in order_target.ROW_RANK)

print()
print("=" * 92)
print("② 每个目标码(1~6):能挑出目标 / 挑不出时返回 None(fail-closed)")
print("=" * 92)
owner_fake("enemy")

# ---- kind 1:指定敌方单位(打不了总部)----
c1 = real_card("1")
C("表里有 kind 1 的卡", bool(c1), str(c1))
got = order_target.pick(c1, mkfield(enemy_support=[(500, 180, False)],
                                    our_support=[(400, 525, False)]))
C(f"kind 1 挑得出敌方单位({c1})",
  got and got["what"] == "敌方支援线单位" and (got["x"], got["y"]) == (500, 180),
  str(got and {k: got[k] for k in ("x", "y", "what")}))
got2, lg2 = logs_of(lambda log: order_target.pick(
    c1, mkfield(our_support=[(400, 525, False)]), log=log))
C("kind 1 盘上没有敌方单位 -> None(不打)", got2 is None)
C("  而且日志里有明确的「不打 + 原因」",
  len(lg2) == 1 and "不打" in lg2[0] and "没有候选目标" in lg2[0],
  lg2[0] if lg2 else "(没有日志)")
# 敌方总部在盘上时,kind 1 **不许**打它(is_hq 的候选不进这一档)
got3 = order_target.pick(c1, mkfield(our_support=[(400, 525, False)],
                                     hq_enemy=(640, 180)))
C("kind 1 盘上只有敌方总部 -> None(1 = 打不了总部)", got3 is None,
  str(got3))

# ---- kind 2:敌方单位或总部 ----
c2 = real_card("2")
C("表里有 kind 2 的卡", bool(c2), str(c2))
got = order_target.pick(c2, mkfield(enemy_support=[(700, 180, False)],
                                    our_support=[(400, 525, False)],
                                    hq_enemy=(900, 180)))
C("kind 2 有单位也有总部时 -> 挑**单位**(单位优先于总部)",
  got and got["what"] == "敌方支援线单位" and got["x"] == 700, str(got))
got = order_target.pick(c2, mkfield(our_support=[(400, 525, False)],
                                    hq_enemy=(900, 180)))
C("kind 2 只剩总部时 -> 挑总部", got and got["what"] == "敌方总部"
  and (got["x"], got["y"]) == (900, 180), str(got))
got = order_target.pick(c2, mkfield(our_support=[(400, 525, False)]))
C("kind 2 单位/总部都没有 -> None", got is None)

# ---- kind 3:指定敌方总部 ----
c3 = real_card("3")
C("表里有 kind 3 的卡", bool(c3), str(c3))
got = order_target.pick(c3, mkfield(enemy_support=[(700, 180, False)],
                                    hq_enemy=(900, 180)))
C("kind 3 只打总部(支援线上的单位不参与)", got and got["what"] == "敌方总部"
  and got["x"] == 900, str(got))
got2, lg2 = logs_of(lambda log: order_target.pick(
    c3, mkfield(enemy_support=[(700, 180, False)]), log=log))
C("kind 3 读不出敌方总部(hq_enemy 没有)-> None", got2 is None)
C("  日志点名「敌方总部读不出来」", bool(lg2) and "总部读不出来" in lg2[0],
  lg2[0] if lg2 else "(没有日志)")

# ---- kind 4:我方单位 ----
c4 = real_card("4")
C("表里有 kind 4 的卡", bool(c4), str(c4))
got = order_target.pick(c4, mkfield(our_support=[(440, 525, False)]))
C("kind 4 挑得出我方单位", got and got["what"] == "我方支援线单位"
  and (got["x"], got["y"]) == (440, 525), str(got))
got = order_target.pick(c4, mkfield(enemy_support=[(500, 180, False)]))
C("kind 4 我方支援线是空的 -> None(不许拿敌方单位凑)", got is None)
# ★★ 硬规矩:我方单位只从 our_support 取 —— 前线上的卡**一张都不算**
got = order_target.pick(c4, mkfield(frontline=[(600, 350, False)],
                                    enemy_support=[(500, 180, False)]))
C("kind 4 前线有卡也不算我方单位(只认 our_support)-> None", got is None, str(got))

# ---- kind 5:选择一张手牌(★★ 2026-09-21 起这一档**归黑名单**,本模块只是兜底)----
# ★★ 政策变了:用户 2026-09-21 决定"kind5进黑名单",所以**这一局不会**有 kind 5 的
#    牌被送到 `pick()`(`orders.playable()` 不放行)。下面这几条测的是**兜底行为** ——
#    万一以后 `orders.KIND5_AS_BLACKLIST` 翻回 False,这一档仍然:
#      · 只挑认得出是单位的那张(这一档里有几张天生要求"选一张**单位**",
#        选到非单位时游戏多半忽略这一下,而引擎只按费用对账会记成"指令打出",
#        还会把那个下标从手牌记忆里删掉);
#      · 一张单位都没有(或身份认不出)-> fail-closed,绝不退回"瞎挑最靠左那张"。
#    黑名单那侧(playable / is_blacklisted / status)在 ⑥.5 段单测。
c5 = real_card("5")
C("表里有 kind 5 的卡", bool(c5), str(c5))
HAND_MIXED = [{"x": 639, "type": "order", "i": 0},
              {"x": 492, "type": "order", "i": 1},
              {"x": 570, "type": "infantry", "i": 2}]
got = order_target.pick(c5, mkfield(our_support=[(400, 525, False)]),
                        hand_cards=HAND_MIXED)
C("kind 5 挑中的是**单位**(最靠左那张是非单位,必须跳过),落点 y = 手牌悬停行",
  got and (got["x"], got["y"]) == (570, order_target.HAND_ROW_Y)
  and got["hand_type"] == "infantry", str(got))
C("  日志写清挑的是第几张 / x / 类型",
  got and "第 3 张" in got["why"] and "x=570" in got["why"]
  and "infantry" in got["why"], got and got["why"])
got, lg = logs_of(lambda log: order_target.pick(
    c5, mkfield(our_support=[(400, 525, False)]),
    hand_cards=[{"x": 492, "type": "order", "i": 0},
                {"x": 570, "type": "countermeasure", "i": 1}], log=log))
C("kind 5 候选里**一张单位都没有** -> None(不打,不许退回'挑最左')",
  got is None, str(got))
C("  日志说清「没有认得出是单位的那张」", bool(lg) and "没有认得出是单位" in lg[0],
  lg[0] if lg else "(没有日志)")
# ★ 裸 x(旧写法)没有类型信息 -> 认不出单位 -> fail-closed。这条是**有意的**:
#   "认不出"和"不是单位"一样,都不许赌。
got, lg = logs_of(lambda log: order_target.pick(
    c5, mkfield(our_support=[(400, 525, False)]), hand_xs=[492, 570], log=log))
C("kind 5 只给裸 x(类型未知)-> None(认不出单位就不许选)", got is None, str(got))
got = order_target.pick(c5, mkfield(our_support=[(400, 525, False)]))
C("kind 5 什么都没给 -> None(不打)", got is None)
got, lg = logs_of(lambda log: order_target.pick(
    c5, mkfield(our_support=[(400, 525, False)]), hand_xs=[], log=log))
C("kind 5 候选是空列表 -> None + 日志说清原因",
  got is None and bool(lg) and "手牌候选" in lg[0], lg[0] if lg else "(没有日志)")
got = order_target.pick(c5, mkfield(our_support=[(400, 525, False)]),
                        hand_cards=[{"x": 492, "type": "tank"}], hand_y=300)
C("kind 5 的 y 落在战场区(传错了 hand_y)-> None(不许点到战场上)", got is None)
got = order_target.pick(c5, mkfield(our_support=[(400, 525, False)]),
                        hand_cards=[{"x": -5, "type": "tank"},
                                    {"x": 99999, "type": "tank"}])
C("kind 5 候选 x 全越界 -> None", got is None)
# 五个单位类型都要认得出来(`orders.playable()` 认的那一套词汇)
_types_ok = all(
    (order_target.pick(c5, mkfield(our_support=[(400, 525, False)]),
                       hand_cards=[{"x": 500, "type": t}]) or {}).get("hand_type") == t
    for t in order_target.UNIT_TYPES)
C("kind 5 五个单位类型都算'认得出是单位'", _types_ok, str(order_target.UNIT_TYPES))

# ---- kind 6:随意阵营单位(★★ 2026-09-21 用户决定:**一条规则 = 一律指敌方**)----
# ★ 演进史(留在这,方便以后翻案时对账):
#   ① 最初:全局 `KIND6_SIDE_ORDER = ("enemy","our")`(敌方优先);
#   ② 按卡面改过一版:逐卡定向表,把那三张"增益/位移"类判成我方,表外 fail-closed;
#   ③ **现在(用户 2026-09-21 明确"kind6全部指敌方")**:回到一条规则,
#      常量 = `order_target.KIND6_SIDE`,没有逐卡例外、也没有"表外不打"的中间态。
print("  规则 KIND6_SIDE =", repr(order_target.KIND6_SIDE))
_g6 = [nm for nm, r in (orders._CARDS or {}).items()
       if r.get("mode") == orders.MODE_TARGET and (r.get("kind") or "") == "6"]
print(f"  表里 kind 6 共 {len(_g6)} 张:{_g6}")
C("① 规则就是 enemy(用户 2026-09-21 决定「kind6全部指敌方」)",
  order_target.KIND6_SIDE == "enemy", repr(order_target.KIND6_SIDE))
C("② 旧的逐卡定向表已经删掉(不许再有'全局默认 + 逐卡覆盖'那两层结构)",
  not hasattr(order_target, "KIND6_SIDE_BY_CARD")
  and not hasattr(order_target, "kind6_side_pref"),
  str([n for n in ("KIND6_SIDE_BY_CARD", "kind6_side_pref")
       if hasattr(order_target, n)]))
C("③ 表里那一档有 10 张卡名(用例下面要逐张过)",
  len(_g6) == 10, f"实得 {len(_g6)}:{_g6}")

c6_cd = "捕风捉影"      # 6-cd:rows 同时含 c(敌方支援)/ d(我方支援)
c6_ab = "运输补给"      # 6-ab:rows 同时含 a(敌方前线)/ b(我方前线)
c6_plain = "战争迷雾"    # 6:不限行
C("那三张'卡面像我方受益'的都在 kind 6 里(它们现在也必须指敌方)",
  all(n in _g6 for n in ("捕风捉影", "帝国指令", "运输补给")),
  str([n for n in ("捕风捉影", "帝国指令", "运输补给") if n not in _g6]))
owner_fake("enemy")

# ① 逐张过:敌我单位都在盘上 -> **每一张**都必须挑敌方(一张都不许挑我方)
#   ★ 盘面要给足:`运输补给` 的 rows=ab 只认**前线**那一行,所以只摆支援线的话
#     它会"没有候选"-> None(那是行码生效,不是规则失效)。所以这里连前线一起摆。
_g6_field = mkfield(enemy_support=[(700, 180, False)],
                    our_support=[(440, 525, False)],
                    frontline=[(600, 350, False)])
_bad = []
for _nm in _g6:
    _got = order_target.pick(_nm, _g6_field)
    if not _got or _got["side"] != "enemy":
        _bad.append((_nm, _got and (_got["side"], _got["x"], _got["row"])))
C(f"④ kind 6 全部 {len(_g6)} 张:敌我都有单位时**都挑敌方**(旧版那三张会挑我方 440)",
  not _bad, str(_bad))
C("  而且逐张挑出来的都是**敌方**那一侧的卡(支援线 700 或前线 600)",
  all((order_target.pick(n, _g6_field) or {}).get("x") in (700, 600) for n in _g6),
  str({n: (order_target.pick(n, _g6_field) or {}).get("x") for n in _g6}))
_got = order_target.pick(c6_plain, mkfield(enemy_support=[(700, 180, False)],
                                           our_support=[(440, 525, False)]))
C("  why 里写明 kind 6 -> 敌方,而且**带上依据**(用户 2026-09-21 决定)",
  _got and "敌方" in _got["why"] and "用户 2026-09-21 决定" in _got["why"],
  _got and _got["why"])
C("  返回里仍然带 kind6_side 诊断键(= enemy)", _got and _got.get("kind6_side") == "enemy",
  str(_got and _got.get("kind6_side")))
C("  敌方一个单位都没有、只有我方 -> None(规则说敌方,就不许拿我方顶上)",
  order_target.pick(c6_plain, mkfield(our_support=[(440, 525, False)])) is None)

# ② rows 的收窄**照旧生效**(规则只决定"哪一侧",哪一行仍由 rows 决定)
#   6-cd + 敌方 => 只剩 c(敌方支援线);我方支援线(d)被行码滤掉
_got = order_target.pick(c6_cd, mkfield(enemy_support=[(700, 180, False)],
                                        our_support=[(440, 525, False)],
                                        frontline=[(600, 350, False)]))
C("⑤ 6-cd + 敌方:两边支援线都有卡 -> 挑**敌方支援线**(c),我方那条被 rows 滤掉",
  _got and _got["row"] == "c" and _got["x"] == 700, str(_got and (_got["x"], _got["row"])))
C("  6-cd + 敌方:敌方支援线上没卡 -> None(不许拿我方支援线凑数)",
  order_target.pick(c6_cd, mkfield(our_support=[(440, 525, False)])) is None)
#   6-ab + 敌方 => 只剩 a(敌方前线);归属不是敌方时前线的卡不算敌方 -> 不打
C("  6-ab + 敌方:只有我方支援线(d,不在 rows 里)-> None",
  order_target.pick(c6_ab, mkfield(our_support=[(440, 525, False)])) is None)
_got = order_target.pick(c6_ab, mkfield(enemy_support=[(700, 180, False)],
                                        frontline=[(600, 350, False)]))
C("  6-ab + 敌方 + 归属=敌方 + 敌方前线有卡 -> 挑**敌方前线**(a)",
  _got and _got["row"] == "a" and _got["x"] == 600, str(_got and (_got["x"], _got["row"])))
owner_fake("our")      # 归属翻成我方:前线那一行就不算敌方了
try:
    C("  6-ab + 敌方 + 归属=**我方** -> 前线那张不算敌方 -> None(绝不把前线当我方/敌方猜)",
      order_target.pick(c6_ab, mkfield(enemy_support=[(700, 180, False)],
                                       frontline=[(600, 350, False)])) is None)
finally:
    owner_fake("enemy")
# 不限行的 6:只挑**敌方**的单位/总部(总部那一档本来只给 kind 2/3,这里顺带钉住)
_got = order_target.pick(c6_plain, mkfield(enemy_support=[(700, 180, False)],
                                           hq_enemy=(900, 180)))
C("  不限行的 6:敌方支援线上有单位 + 总部 -> 挑**单位**(单位优先于总部)",
  _got and _got["x"] == 700 and _got["side"] == "enemy", str(_got and (_got["x"], _got["side"])))
C("  盘上**只有敌方总部** -> None(kind 6 只挑单位,总部那档留给 kind 2/3)",
  order_target.pick(c6_plain, mkfield(hq_enemy=(900, 180))) is None)

# ③ 前线归属读不出时:既不当我方也不当敌方 -> 这一档没有候选(和原来同一结论)
owner_fake(None, "(用例构造:黑线没找到)")
got, lg = logs_of(lambda log: order_target.pick(
    c6_cd, mkfield(frontline=[(600, 350, False)]), log=log))
C("⑥ 前线归属读不出 + 盘上只有前线有卡 -> None(不许赌)", got is None)
C("  日志说清「没有候选目标」并带上归属", bool(lg) and "没有候选目标" in lg[0],
  lg[0] if lg else "(没有日志)")
owner_fake("enemy")

print()
print("=" * 92)
print("③ ★★★ 前线归属读不出时,绝不把前线单位算成自己人/敌人(最关键的一条)")
print("=" * 92)
# ★ 为什么单列一条:`board.py` 第 1411~1414 行写着 —— 前线那一行的归属是**争夺**的,
#   认错的后果是"把敌人的单位当成自己的去拖",§10 把它记成本项目最危险的错误。
#   而 `frontline_line.read_frontline_owner` 在**读不出**时返回 owner=None,
#   这一刻**两个方向都不许猜**:既不能当我方,也不能当敌方,只能不打(fail-closed)。
owner_real()                       # 用**真判据** + 全黑假帧 -> 归属必然读不出
_blank = mkfield(frontline=[(600, 350, False)])
_probe = frontline_line.read_frontline_owner(frame=FRAME, field=_blank)
print(f"  真实判据在全黑假帧上的结论:owner={_probe['owner']!r} | {_probe['why']}")
C("前提:这个场景下归属确实读不出来(否则这条用例没在考它)",
  _probe["owner"] is None, f"owner={_probe['owner']!r}")

c4b = real_card("4")
got, lg = logs_of(lambda log: order_target.pick(
    c4b, mkfield(frontline=[(600, 350, False)],
                 enemy_support=[(500, 180, False)]), frame=FRAME, log=log))
C("【我方目标】前线有卡但归属读不出 -> kind 4 返回 None,**绝不**把前线当自己人",
  got is None, str(got))
c1b = real_card("1")
got, lg = logs_of(lambda log: order_target.pick(
    c1b, mkfield(frontline=[(600, 350, False)],
                 our_support=[(440, 525, False)]), frame=FRAME, log=log))
C("【敌方目标】前线有卡但归属读不出 -> kind 1 返回 None,**也绝不**把前线当敌人",
  got is None, str(got))
got, lg = logs_of(lambda log: order_target.pick(
    c1b, mkfield(enemy_support=[(500, 180, False)],
                 frontline=[(600, 350, False)]), frame=FRAME, log=log))
C("归属读不出时**不挡**别的行:kind 1 仍去打敌方支援线那张,只是把前线排除掉",
  got and got["x"] == 500 and got["what"] == "敌方支援线单位", str(got))
C("  why 里如实写出归属是 None(判据和结论写在一起)",
  got and "前线归属=None" in got["why"], got and got["why"])
c_a = real_card("1", rows="a")
got, lg = logs_of(lambda log: order_target.pick(
    c_a, mkfield(frontline=[(600, 350, False)]), frame=FRAME, log=log))
C(f"行码 a 的卡({c_a}):归属读不出 -> None", got is None)
C("  日志点名「归属读不出」", bool(lg) and "归属读不出" in lg[0],
  lg[0] if lg else "(没有日志)")
owner_fake("enemy")                # 后面的用例继续用脚本化归属

print()
print("=" * 92)
print("④ 行码 a/b/c/d 的收窄真的生效")
print("=" * 92)
# ---- a = 仅前线敌方单位 ----
c_a = real_card("1", rows="a")
C("表里有 rows=a 的 kind 1 卡", bool(c_a), str(c_a))
got = order_target.pick(c_a, mkfield(enemy_support=[(700, 180, False)],
                                     frontline=[(600, 350, False)]))
C("rows=a:支援线有卡也**只能**挑前线那张", got and got["row"] == "a"
  and (got["x"], got["y"]) == (600, 350), str(got))
got = order_target.pick(c_a, mkfield(enemy_support=[(700, 180, False)]))
C("rows=a:前线没卡 -> None(支援线的卡不算)", got is None)
owner_fake(None, "(用例构造:归属读不出)")
got = order_target.pick(c_a, mkfield(frontline=[(600, 350, False)]))
C("rows=a:前线归属读不出 -> None", got is None)
owner_fake("enemy")

# ---- c = 仅敌方支援阵线 ----
c_c = real_card("1", rows="c")
C("表里有 rows=c 的 kind 1 卡", bool(c_c), str(c_c))
got = order_target.pick(c_c, mkfield(enemy_support=[(700, 180, False)],
                                     frontline=[(600, 350, False)]))
C("rows=c:前线有敌方单位也**不许**挑,只挑支援线", got and got["row"] == "c"
  and got["x"] == 700, str(got))
got = order_target.pick(c_c, mkfield(frontline=[(600, 350, False)]))
C("rows=c:支援线没卡 -> None", got is None)

# ---- d = 仅我方支援阵线 ----
c_d = real_card("4", rows="d")
C("表里有 rows=d 的 kind 4 卡", bool(c_d), str(c_d))
got = order_target.pick(c_d, mkfield(our_support=[(440, 525, False)]))
C("rows=d:我方支援线上有单位 -> 挑它", got and got["row"] == "d" and got["x"] == 440,
  str(got))
got = order_target.pick(c_d, mkfield(enemy_support=[(500, 180, False)]))
C("rows=d:我方支援线空 -> None", got is None)

# ---- b = 仅前线友方单位 ----
# ★ 这一条**故意**是 None:kind 4「我方单位」按硬规矩只从 `our_support` 取,
#   而行码 b 要的是"我方**在前线**的单位" —— 两者交集为空。
#   后果:`战术撤退`(4/b)现在永远挑不出目标 -> fail-closed(不打)。
#   这是**有意**的取舍:宁可少打一张,也不拿"归属判错 = 拖自己人"去赌。
c_b = real_card("4", rows="b")
C("表里有 rows=b 的 kind 4 卡", bool(c_b), str(c_b))
got = order_target.pick(c_b, mkfield(our_support=[(440, 525, False)],
                                     frontline=[(600, 350, False)]))
C(f"rows=b 的 kind 4 卡({c_b})挑不出目标 -> None(我方单位只认 our_support)",
  got is None, str(got))
# ★ 但 b 这一档**本身**是能生效的:kind 6 + rows=ab + **归属=敌方** + 敌方前线有卡
#   时,前线的敌方单位就是合法目标(见上面新块 ⑤,卡 = `运输补给`)。
#   下面这几条换成 `帝国指令`(kind 6、rows 不限)验"行序 / 归属"的交互 ——
#   ★ 2026-09-21 起 kind 6 一律指敌方,所以这里挑的是**敌方**那两条线。
c_6any = "帝国指令"          # kind 6,rows 不限
C(f"表里有 rows 不限的 kind 6 卡({c_6any})", c_6any in _g6, c_6any)
owner_fake("enemy")
got = order_target.pick(c_6any, mkfield(enemy_support=[(700, 180, False)],
                                        frontline=[(600, 350, False)]))
C("归属=敌方:敌方支援线和敌方前线都合法 -> 按行序取**敌方前线**(a 排在 c 前面)",
  got and got["row"] == "a" and got["x"] == 600 and got["side"] == "enemy",
  str(got and (got["x"], got["row"])))
got = order_target.pick(c_6any, mkfield(enemy_support=[(700, 180, False)],
                                        frontline=[(600, 350, False)]))
C("  同一次调用再跑一遍 -> 结果一字不差(确定性)",
  got and got["row"] == "a" and got["x"] == 600, str(got and (got["x"], got["row"])))
got = order_target.pick(c_6any, mkfield(enemy_support=[(700, 180, False)],
                                        our_support=[(440, 525, False)],
                                        frontline=[(600, 350, False)]))
C("归属=敌方 + 我方单位也在盘上 -> **仍然只挑敌方**(我方那张 440 不许被挑)",
  got and got["side"] == "enemy" and got["x"] in (600, 700)
  and got["x"] != 440, str(got and (got["x"], got["side"], got["row"])))

# ---- cd = 敌方支援阵线 或 我方支援阵线(多字母 = 并集) ----
c_cd = real_card("6", rows="cd")
C("表里有 rows=cd 的 kind 6 卡", bool(c_cd), str(c_cd))
got = order_target.pick(c_cd, mkfield(enemy_support=[(700, 180, False)],
                                      our_support=[(440, 525, False)],
                                      frontline=[(600, 350, False)]))
C("rows=cd:两边支援线都合法 -> 按**规则(敌方)**取敌方支援线 700,我方那条被滤掉",
  got and got["row"] == "c" and got["x"] == 700, str(got))

print()
print("=" * 92)
print("⑤ kind 7(三选一)和带 follow 的两步卡:一定不返回坐标")
print("=" * 92)
for kind, rows, follow, why in ((("7"), "", "", "三选一"),
                                ("1", "", "7", "两步:先 1 再 7"),
                                ("5", "", "1", "两步:先 5 再 1"),
                                ("7", "", "1", "两步 + 三选一")):
    nm = real_card(kind, rows, follow)
    C(f"表里有 kind {kind} follow={follow or '-'} 的卡({why})", bool(nm), str(nm))
    if not nm:
        continue
    # ① 放行判据不许放它过去
    C(f"  orders.playable() 不放行「{nm}」", orders.playable("order", nm) is False)
    C(f"  orders.is_target() 为假", orders.is_target(nm) is False)
    C(f"  target_refuse_reason() 有话说", bool(orders.target_refuse_reason(nm)),
      orders.target_refuse_reason(nm))
    # ② 就算调用方(或以后的新代码)硬把它送进来,pick() 也必须 fail-closed
    got, lg = logs_of(lambda log, _nm=nm: order_target.pick(
        _nm, mkfield(enemy_support=[(500, 180, False)],
                     our_support=[(440, 525, False)], hq_enemy=(900, 180)),
        hand_xs=[492, 570], log=log))
    C(f"  pick() 硬被调用时也返回 None(不返回坐标)", got is None, str(got))
    C(f"  日志里说明了为什么({why})", bool(lg) and "不打" in lg[0], lg[0] if lg else "")

print()
print("=" * 92)
print("⑥ A/B 开关 PLAY_TARGETS=False:一句话退回第一版")
print("=" * 92)
c1x = real_card("1")
try:
    orders.PLAY_TARGETS = False
    C("关掉后 target 一律不放行", orders.playable("order", c1x) is False, str(c1x))
    C("  而且 status() 会如实说这一档不打", "PLAY_TARGETS=False" in orders.status(),
      orders.status()[:50] + "…")
    C("  但 target_refuse_reason() 说得出原因",
      "PLAY_TARGETS" in orders.target_refuse_reason(c1x),
      orders.target_refuse_reason(c1x))
    # 关掉之后 direct 那 286 张必须**照旧放行**(别把整档指令一起关掉)
    c_direct = next((n for n, r in (orders._CARDS or {}).items()
                     if r.get("mode") == orders.MODE_DIRECT), None)
    C("  关掉 target **不影响** direct 那一档",
      bool(c_direct) and orders.playable("order", c_direct) is True, str(c_direct))
    C("  也不影响单位",
      orders.playable("infantry", "步兵第 89 团") is True)
finally:
    orders.PLAY_TARGETS = True
C("还原之后又放行了", orders.playable("order", c1x) is True, str(c1x))
# 总开关也要留着(别把测试里的临时改动漏出去)
C("PLAY_ORDERS 仍为 True(用例没把它改坏)", orders.PLAY_ORDERS is True)

print()
print("=" * 92)
print("⑥.5 ★★ kind 5 归黑名单(用户 2026-09-21「kind5进黑名单」)—— 政策层在 orders.py")
print("=" * 92)
_k5 = [nm for nm, r in (orders._CARDS or {}).items()
       if r.get("mode") == orders.MODE_TARGET and (r.get("kind") or "") == "5"]
print(f"  表里 kind 5 共 {len(_k5)} 个卡名:{_k5}")
C("① 开关 KIND5_AS_BLACKLIST 默认开着", orders.KIND5_AS_BLACKLIST is True)
C("② kind 5 **不在** TARGET_KINDS_OK 里(kind 7 也不在)",
  "5" not in orders.TARGET_KINDS_OK and "7" not in orders.TARGET_KINDS_OK,
  str(orders.TARGET_KINDS_OK))
_bad_bl = [n for n in _k5 if not orders.is_blacklisted(n)]
_bad_pl = [n for n in _k5 if orders.playable("order", n)]
C(f"③ kind 5 全部 {len(_k5)} 个卡名:is_blacklisted() 为真(引擎那条'别带这张'提示靠它)",
  not _bad_bl, str(_bad_bl))
C("④ kind 5 全部:playable() / is_target() 都不放行",
  not _bad_pl and not any(orders.is_target(n) for n in _k5),
  str(_bad_pl + [n for n in _k5 if orders.is_target(n)]))
C("⑤ target_refuse_reason() 说得出原因,而且点名是黑名单那条决定",
  all("黑名单" in orders.target_refuse_reason(n)
      and "KIND5_AS_BLACKLIST" in orders.target_refuse_reason(n) for n in _k5),
  orders.target_refuse_reason(_k5[0]) if _k5 else "")
C("⑥ 真正表里的黑名单卡照旧是黑名单(这条判据没被改坏)",
  any(orders.mode_of(n) == orders.MODE_BLACKLIST and orders.is_blacklisted(n)
      for n in (orders._CARDS or {})),
  str(next((n for n, r in (orders._CARDS or {}).items()
            if r["mode"] == orders.MODE_BLACKLIST), "")))
C("⑦ 非 kind 5 的 target(kind 1/4/6)不许被误判成黑名单",
  all(not orders.is_blacklisted(n) for n, r in (orders._CARDS or {}).items()
      if r["mode"] == orders.MODE_TARGET and (r.get("kind") or "") not in ("5",)),
  "")
# ★ A/B:开关翻 False -> 立刻退回旧行为(kind 5 又只是"需要目标"里的一档)
try:
    orders.KIND5_AS_BLACKLIST = False
    C("⑧ KIND5_AS_BLACKLIST=False:kind 5 不再是黑名单",
      not any(orders.is_blacklisted(n) for n in _k5), "")
    # ★ 注意:kind 5 里有一张**两步卡**(follow 非空),它就算开关关掉也仍然不放行
    #   —— 那是 `_target_gate` 的第二条闸,和黑名单无关。所以这里分开断言。
    _k5_one = [n for n in _k5 if not (orders.rec_of(n).get("follow") or "").strip()]
    _k5_two = [n for n in _k5 if (orders.rec_of(n).get("follow") or "").strip()]
    C("  而且它**又回到「需要目标」那一档**:不带 follow 的那几张 playable() 放行",
      _k5_one and all(orders.playable("order", n) and orders.is_target(n)
                      for n in _k5_one),
      f"放行 {len(_k5_one)} 张 / 带 follow 的 {_k5_two}")
    C("  带 follow 的 kind 5(两步卡)照旧不放行 —— 那条闸没被这次改动碰坏",
      all(not orders.playable("order", n) and not orders.is_target(n)
          for n in _k5_two), str(_k5_two))
    C("  target_kinds_ok() 里也把 5 加回来了(判据只有一处,status 也问它)",
      "5" in orders.target_kinds_ok(), str(orders.target_kinds_ok()))
    C("  其它黑名单卡不受影响",
      any(orders.is_blacklisted(n) for n, r in (orders._CARDS or {}).items()
          if r["mode"] == orders.MODE_BLACKLIST), "")
    C("  status() 跟着变(不再把 kind 5 算进黑名单)",
      "+ kind 5" not in orders.status(), orders.status()[:80] + "…")
finally:
    orders.KIND5_AS_BLACKLIST = True
C("⑨ 还原之后 kind 5 又是黑名单了", all(orders.is_blacklisted(n) for n in _k5), "")

# ★ status() 那行**账要平**:每个数字都跟"逐卡现算"的结果对账(判据只有一处 —— 这里
#   只数 orders 现成的判定,不复制一份逻辑)。
_st = orders.status()
print("  status() = " + _st)
_tgt = [r for r in (orders._CARDS or {}).values() if r["mode"] == orders.MODE_TARGET]
_ok_n = sum(1 for r in _tgt if orders._target_gate(r)[0])
_bl_n = sum(1 for n in (orders._CARDS or {}) if orders.is_blacklisted(n))
_bl_tbl = sum(1 for r in (orders._CARDS or {}).values() if r["mode"] == orders.MODE_BLACKLIST)
_direct_n = sum(1 for r in (orders._CARDS or {}).values() if r["mode"] == orders.MODE_DIRECT)
C(f"⑩ status 里「需要目标 N 个卡名」= 逐卡数出来的 {len(_tgt)}",
  f"需要目标 {len(_tgt)} 个卡名" in _st, _st)
C(f"⑪ status 里「其中可打 {_ok_n} 个」= `_target_gate()` 逐卡现算的结果",
  f"其中可打 {_ok_n} 个" in _st, _st)
C(f"⑫ status 里「可直接打出 {_direct_n} 个卡名」对得上", 
  f"可直接打出 {_direct_n} 个卡名" in _st, _st)
C(f"⑬ status 里黑名单 = 表里 {_bl_tbl} + kind 5 {len(_k5)} = {_bl_n}(和 is_blacklisted 逐卡现算一致)",
  f"黑名单 {_bl_n} 个卡名" in _st and f"表里 {_bl_tbl} + kind 5 {len(_k5)}" in _st, _st)
C("⑭ 账真的平:可打的 target + 不可打的 target = 表里 target 总数",
  _ok_n + sum(1 for r in _tgt if not orders._target_gate(r)[0]) == len(_tgt),
  f"{_ok_n} + {len(_tgt) - _ok_n} = {len(_tgt)}")
C("⑮ status 点名 kind 5 是被归进来的(读日志的人看得出它为什么不打)",
  "kind 5" in _st and "黑名单" in _st, _st)
C("⑯ status 不许再说「需要目标(kind 1~6)」那种把 kind 5 也算进去的旧口径",
  "kind 1~6" not in _st, _st)

print()
print("=" * 92)
print("⑦ 确定性:同一输入跑两次,结果一字不差")
print("=" * 92)
f = mkfield(enemy_support=[(700, 180, False), (300, 180, False)],
            our_support=[(440, 525, False)], frontline=[(600, 350, False)])
a = order_target.pick(real_card("1"), f)
b = order_target.pick(real_card("1"), mkfield(
    enemy_support=[(300, 180, False), (700, 180, False)],   # 换一下列表顺序
    our_support=[(440, 525, False)], frontline=[(600, 350, False)]))
C("同一帧跑两次 -> 结果一样", a == b, f"{a and (a['x'], a['y'])} vs {b and (b['x'], b['y'])}")
C("候选列表顺序变了也不影响选择(排序不看输入顺序)",
  a and a["x"] == 600 and a["row"] == "a", str(a and (a["x"], a["y"], a["what"])))
cands_xy = order_target.pick(real_card("1"), mkfield(
    enemy_support=[(700, 180, False), (500, 180, False)]))
C("同优先级(同一行)时靠左优先",
  cands_xy and cands_xy["x"] == 500, str(cands_xy and cands_xy["x"]))

# ---- ★★ why 里那句"行偏好顺序"必须**从 ROW_RANK 现生成**(旧版手写副本漏档)----
# 旧版写死成 `行(敌前线>敌支援>我支援)`,把 ROW_RANK 里真实的第 4 档"我方前线"
# (权重 3)漏掉了。手写副本 = 日志撒谎(§7 第 67/68 条)。
# ★ 2026-09-21 起 kind 6 一律指敌方,所以"哪一侧会挑到我方前线"只剩 kind 4 那一档
#   够不到的行 —— 也就是说**这句话现在是给 kind 4/其它档看的全貌**,
#   kind 6 的实战路径只会走 a/c。仍然必须四档齐全(它就是"排序键的说明书")。
_row_txt = order_target.row_order_text()
print(f"  row_order_text() = {_row_txt}")
for _k, _t in order_target.ROW_TEXT.items():
    C(f"行偏好顺序里点到行码 {_k}({_t},权重 {order_target.ROW_RANK.get(_k)})",
      _t in _row_txt, _row_txt)
C("  四档的顺序与 ROW_RANK 的权重一致",
  _row_txt.split(">") == [order_target.ROW_TEXT[k] for k, _v in
                          sorted(order_target.ROW_RANK.items(), key=lambda kv: kv[1])],
  _row_txt)
_row_pick = order_target.pick(c6_ab, mkfield(enemy_support=[(700, 180, False)],
                                             frontline=[(600, 350, False)]))
C("  而且选出来的那条 why 里就是这句(不是另一份手写字符串)",
  _row_pick and _row_txt in _row_pick["why"], _row_pick and _row_pick["why"])
C("  旧版那句漏档的写法不许再出现在任何 why 里",
  _row_pick and "敌前线>敌支援>我支援)" not in _row_pick["why"],
  _row_pick and _row_pick["why"])

# 结构不对(传了 battlefield_snapshot 那个形状:单位列表是 (张数, 诊断) 元组)
# -> 必须 fail-closed,而且**不许**当成"这一行没有卡"(那是"诊断在撒谎")。
snap_like = {"rows": [row_of("enemy", 180, [])],
             "our_support": (2, {"rows": []}), "enemy_support": (1, {}),
             "frontline": [], "total": 3}
got, lg = logs_of(lambda log: order_target.pick(real_card("1"), snap_like, log=log))
C("传进来的不是 read_field 结构(battlefield_snapshot 那种)-> None", got is None)
C("  日志点名「结构不对」", bool(lg) and "结构不对" in lg[0], lg[0] if lg else "")
C("field=None(战场没读出来)-> None", order_target.pick(real_card("1"), None) is None)

print()
print("=" * 92)
print("⑧ 引擎接线:hand_xs 的合并/排除 + think() 真的把牌拖到目标卡上")
print("=" * 92)


class StubScanner:
    """引擎只用到这几样(照 `turn_logic_test.FakeScanner` 的接缝抄)。"""

    def __init__(self):
        self.hold = 0.30
        self.y = 700
        self.last_probe_seen = []
        self.last_hand_count = None
        self.last_layout = None
        self.last_reason = None
        self.memory = None
        self.last_memory = None

    def _load_layouts(self):
        return {}


def new_engine(cards, logs):
    eng = turn_engine.TurnEngine(0, {"end_turn_btn": FRAME}, log=logs.append,
                                 lazy_scan=True)
    eng.kredits.turn_start_settle = 0
    eng.scanner = StubScanner()
    eng.cards = list(cards)
    eng.phase = "play"
    eng.kredits_left = 5
    return eng


turn_engine.capture_client_bgr = lambda hwnd: FRAME
turn_engine.match_one = lambda hay, needle: (0.95, (1120, 453, 130, 36))
turn_engine.park_cursor = lambda hwnd, settle=0.3: True
turn_engine.TurnEngine._dump_drag_frame = lambda self, name, target: None

SNAP = {"our_support": (0, {}), "our_front": (0, {}), "enemy_front": (0, {}),
        "enemy_support": (1, {}), "total": 1, "our_support_units": (0, {})}
turn_engine.board.battlefield_snapshot = lambda frame, debug=False: dict(SNAP)

# ---- ⑧a `_hand_xs`:三个来源合并 + 排掉正在拖的那张 ----
# ★★ 2026-09-21:契约**变形状了** —— `_hand_xs()` 不再交回裸 int 列表,而是
#   `[{"x": int, "type": str|None, "i": int|None}, ...]`(上游为了让 kind 5 认得出
#   单位才改的)。所以下面这几条:① 断言的是**新形状**;② 不只比 x,还钉住
#   "**带 type 的那条在同一个 x 上胜出**" —— 那正是这次改动的价值本身。
#   三处来源(见 `turn_engine._hand_xs` 的注释):
#     ① `self.cards`(本轮真扫到的,天然带 type/i)
#     ② `scanner.last_probe_seen` 里 panel 为真的(带 type/i)
#     ③ 校准表里张数对得上那条布局的 probes(只有坐标)
_PANEL_570 = {"x": 570, "panel": True, "type": "tank", "i": 4}   # ②:带身份的探针
eng = new_engine([{"name": "x", "type": "order", "cost": 1, "x": 492, "i": 0},
                  # ★ 故意让 ① 与 ② 在 x=570 撞车,而且 **① 这条没有 type**
                  #   (`c.get("type")` 是 None)-> 合并后必须是 ② 那条带着 type 的胜出。
                  {"name": "y", "type": None, "cost": 1, "x": 570, "i": 1}], [])
eng.scanner.last_probe_seen = [_PANEL_570,
                               {"x": 999, "panel": False, "type": "infantry", "i": 9},
                               {"x": 492, "panel": True, "type": None, "i": None}]
eng.scanner.last_hand_count = 3
eng.scanner._load_layouts = lambda: {"a": {"count": 3, "probes": [536, 605, 711]},
                                     "b": {"count": 5, "probes": [1, 2, 3, 4, 5]}}
_hx = eng._hand_xs()
print(f"    _hand_xs() = {_hx}")
C("_hand_xs 交回**新形状**(dict 列表,带 x/type/i),不再是裸 int",
  _hx and all(isinstance(d, dict) and {"x", "type", "i"} <= set(d) for d in _hx),
  str(_hx))
C("_hand_xs 合并三处来源(认出来的卡 492/570 + 弹出过面板的探针 570 + 校准表 536/605/711)"
  "、按 x 升序、同一 x 只留一条",
  [d["x"] for d in _hx] == [492, 536, 570, 605, 711], str([d["x"] for d in _hx]))
C("  ★ 同一 x(570)上**带 type 的那条胜出**(① 那条 type=None 被 ② 的 tank/i=4 顶掉)",
  [d for d in _hx if d["x"] == 570] == [{"x": 570, "type": "tank", "i": 4}],
  str([d for d in _hx if d["x"] == 570]))
C("  ★ 本轮真扫到的那张(492)带着 type='order' / i=0 —— 这条以前只比 x,现在要看得出来",
  [d for d in _hx if d["x"] == 492] == [{"x": 492, "type": "order", "i": 0}],
  str([d for d in _hx if d["x"] == 492]))
C("  ★ ③ 校准表那几根只有坐标:type / i 必须是 None(不许拿上一张的身份冒充)",
  all(d["type"] is None and d["i"] is None for d in _hx if d["x"] in (536, 605, 711)),
  str([d for d in _hx if d["x"] in (536, 605, 711)]))
C("  没弹出面板的探针(999)不许进候选",
  999 not in [d["x"] for d in _hx], str([d["x"] for d in _hx]))
_hx_ex = eng._hand_xs(exclude_x=492)
print(f"    _hand_xs(exclude_x=492) = {_hx_ex}")
C("_hand_xs 会把**正在拖的那张**自己排掉(按 x 排,与它有没有 type 无关)",
  [d["x"] for d in _hx_ex] == [536, 570, 605, 711], str([d["x"] for d in _hx_ex]))
C("  ★ 而且排掉之后**别的条目的 type 不许丢**(570 那条仍然是 tank/i=4)",
  [d for d in _hx_ex if d["x"] == 570] == [{"x": 570, "type": "tank", "i": 4}],
  str([d for d in _hx_ex if d["x"] == 570]))
C("_hand_xs 只取**张数对得上**的那条布局(5 张那条的探针 1~5 一个都不许混进来)",
  all(d["x"] not in (1, 2, 3, 4, 5) for d in _hx), str([d["x"] for d in _hx]))
C("  (对照)那个桩里确实还有一条 5 张的布局 —— 上面那条不是在空转",
  sorted(eng.scanner._load_layouts()) == ["a", "b"]
  and len(eng.scanner._load_layouts()["b"]["probes"]) == 5,
  str(eng.scanner._load_layouts()))

# ---- ⑧b target 指令:think() 必须把落点选成**目标卡中心**,并且只按费用判成败 ----
drags = []
turn_engine.drag_deploy = (
    lambda hwnd, card_x, card_y=700, drop=None, jitter=6, hover_wait=None,
    on_pressed=None: (drags.append((card_x, drop, hover_wait)), True)[1])

TARGET_NAME = real_card("1")          # 比如「空中优势」
FIELD = mkfield(enemy_support=[(500, 180, False)], our_support=[(440, 525, False)])
board.read_field = lambda frame, templates=None, debug=False: FIELD
owner_fake("enemy")
logs = []
eng = new_engine([{"name": TARGET_NAME, "type": "order", "cost": 2, "x": 780, "i": 0}],
                 logs)
eng._kredits_now = lambda tries=3, gap=0.25: eng.kredits_left
drags.clear()
st = eng.think()
print(f"    think() -> {st} | drags={[(c, d) for c, d, _ in drags]}")
C("think() 真的拖出去了", st == "deployed" and len(drags) == 1, str(st))
C("落点 = **目标卡中心**(500,180),不是空槽位",
  drags and drags[0][1] == (500, 180), str(drags))
C("拖拽前等了扫描器的 HOLD(和 direct/单位同一套)",
  drags and drags[0][2] == eng.scanner.hold, str(drags))
C("日志里一眼能看出这是 target 指令、目标是什么、用哪个坐标",
  any("target 指令" in m and "目标敌方支援线单位(500,180)" in m for m in logs),
  next((m for m in logs if "target 指令" in m), "(没有这样一行)"))
C("日志里写清了**为什么挑它**(候选数 + 固定顺序 + 前线归属)",
  any("候选" in m and "固定顺序" in m and "前线归属" in m for m in logs))
C("成功那行还是「指令打出」(指令不占槽位,不许写成'部署成功')",
  any("指令打出" in m for m in logs), next((m for m in logs if "成功" in m or "打出" in m), ""))
C("指令的成/败**只看费用对账**(战场卡数一直没变也判成功)",
  any("费用读数" in m and "账本" in m for m in logs))

# ---- ⑧c 判不出目标:不拖、不扣账、记进 failed_x、日志有「不打 + 原因」 ----
drags.clear()
logs2 = []
eng2 = new_engine([{"name": TARGET_NAME, "type": "order", "cost": 2, "x": 780, "i": 0}],
                  logs2)
eng2._kredits_now = lambda tries=3, gap=0.25: eng2.kredits_left
board.read_field = lambda frame, templates=None, debug=False: mkfield(
    our_support=[(440, 525, False)])            # 盘上没有敌方单位 -> 挑不出目标
st2 = eng2.think()
print(f"    think() -> {st2} | drags={drags} | 剩余预算={eng2.kredits_left}")
C("判不出目标时**一次都没拖**", drags == [], str(drags))
C("判不出目标时不扣费用(没真拖出去)", eng2.kredits_left == 5, str(eng2.kredits_left))
C("那张牌记进 failed_x/attempted_x(本回合不再试它)",
  780 in eng2.failed_x and 780 in eng2.attempted_x, f"{eng2.failed_x}/{eng2.attempted_x}")
C("惰性模式的缓存被清掉(否则出牌阶段会就此结束,手里别的牌都不出了)",
  eng2.cards == [] and eng2._scanned_full_this_turn is False, str(eng2.cards))
C("日志里有明确的「不打 + 原因」",
  any("不打" in m for m in logs2), next((m for m in logs2 if "不打" in m), "(没有)"))
C("  reason 来自 order_target(判据只有那一处,引擎不自己判一遍)",
  any(m.startswith("[order_target]") for m in logs2),
  next((m for m in logs2 if m.startswith("[order_target]")), "(没有)"))

# ---- ⑧d kind 5:★ 2026-09-21 起它**归黑名单**,引擎根本不会把它当候选 ----
# ★ 这一段的重点变了:上一版测"kind 5 挑哪张手牌",现在测**两件事**:
#   ① 默认配置下:kind 5 连候选都进不去(`playable()` 不放行),而且用户会看到
#      "别带这张"的提示 —— 这条是**引擎与 orders 的接线**,很值得钉住
#      (`turn_engine` 那条提示问的就是 `orders.is_blacklisted()`);
#   ② 万一 `KIND5_AS_BLACKLIST` 翻回 False:整条路(含上游 type)仍然要能跑通 ——
#      所以这一条**临时把开关关掉**来测,测完立刻还原。
K5 = real_card("5")
FIELD5 = mkfield(our_support=[(440, 525, False)])
board.read_field = lambda frame, templates=None, debug=False: FIELD5

# ⑧d-① 默认(黑名单):引擎不拖它,并且打出"别带这张"的提示
drags.clear()
logs3 = []
eng3 = new_engine([{"name": K5, "type": "order", "cost": 2, "x": 780, "i": 0}], logs3)
eng3.scanner.last_probe_seen = [{"x": 492, "panel": True, "type": "order", "i": 0},
                                {"x": 570, "panel": True, "type": "infantry", "i": 1}]
eng3._kredits_now = lambda tries=3, gap=0.25: eng3.kredits_left
st3 = eng3.think()
print(f"    think() -> {st3} | drags={drags}")
C("黑名单生效:kind 5 一次都没被拖出去", drags == [], str(drags))
C("  而且用户看得到提示(引擎那条『手牌里有黑名单卡…别带这张』靠 is_blacklisted 触发)",
  any("黑名单卡" in m and K5 in m for m in logs3),
  next((m for m in logs3 if "黑名单" in m), "(没有这样一行)"))
C("  也没有任何 target 指令那套日志(它连候选都不是)",
  not any("target 指令" in m for m in logs3))

# ⑧d-② `KIND5_AS_BLACKLIST=False` 时退回旧路:上游带 type -> 挑"认得出是单位"的那张
#   ★ 必须同时把 `_lazy_find_playable` 换成空操作:默认惰性模式下 `think()` 会
#     **重扫手牌并覆盖 `self.cards`**,我们注入的那张牌会被真实扫描(桩,什么都扫不到)
#     冲掉 -> 看起来像"kind 5 不工作",其实是**用例没把牌留在手里**。
#     换掉的只是"上游怎么找候选",`pick()` / `orders` 那边一个判据都没被打桩。
_REAL_FLAG = orders.KIND5_AS_BLACKLIST
_REAL_LAZY = turn_engine.TurnEngine._lazy_find_playable
turn_engine.TurnEngine._lazy_find_playable = lambda self: None
orders.KIND5_AS_BLACKLIST = False
try:
    C("关掉开关后 kind 5 又回到「需要目标」那一档(is_blacklisted 为假)",
      orders.is_blacklisted(K5) is False)
    C("  而且 playable() 又放行它了(回到 2026-09-21 之前的行为)",
      orders.playable("order", K5) is True)
    drags.clear()
    logs_k5 = []
    eng_k5 = new_engine([{"name": K5, "type": "order", "cost": 2, "x": 780, "i": 2}], logs_k5)
    eng_k5.scanner.last_probe_seen = [{"x": 492, "panel": True, "type": "order", "i": 0},
                                      {"x": 570, "panel": True, "type": "infantry", "i": 1}]
    eng_k5._kredits_now = lambda tries=3, gap=0.25: eng_k5.kredits_left
    st_k5 = eng_k5.think()
    print(f"    think() -> {st_k5} | drags={[(c, d) for c, d, _ in drags]}")
    C("  落点是**认得出是单位**的那张手牌(570),不是最靠左的 492",
      drags and drags[0][1] == (570, 700), str(drags))
    C("  日志里的目标写的是「手牌」,并带上类型",
      any("目标手牌" in m and "infantry" in m for m in logs_k5),
      next((m for m in logs_k5 if "target 指令" in m), "(没有)"))
finally:
    orders.KIND5_AS_BLACKLIST = _REAL_FLAG
    turn_engine.TurnEngine._lazy_find_playable = _REAL_LAZY
C("  测完开关还原了(下次判还是黑名单)", orders.is_blacklisted(K5) is True)

# ---- ⑧e direct 指令那一路没被改坏(落点仍是空槽位) ----
old_field = board.read_field
board.read_field = lambda frame, templates=None, debug=False: mkfield(
    our_support=[(440, 525, False)], enemy_support=[(500, 180, False)])
DIRECT = next((n for n, r in (orders._CARDS or {}).items()
               if r.get("mode") == orders.MODE_DIRECT), None)
drags.clear()
logs4 = []
eng4 = new_engine([{"name": DIRECT, "type": "order", "cost": 1, "x": 780, "i": 0}], logs4)
eng4._kredits_now = lambda tries=3, gap=0.25: eng4.kredits_left
st4 = eng4.think()
print(f"    direct「{DIRECT}」think() -> {st4} | drags={[(c, d) for c, d, _ in drags]}")
C("direct 指令照旧拖到**中线以下**的空槽位(不是某张卡上)",
  drags and drags[0][1] and drags[0][1][1] > 360, str(drags))
C("  direct 的日志里**没有** target 那套目标描述",
  not any("target 指令" in m for m in logs4))
board.read_field = old_field
owner_real()

print()
print("=" * 92)
print("全部通过" if ALLOK else "存在失败项")
print("=" * 92)
sys.exit(0 if ALLOK else 1)
