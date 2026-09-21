# -*- coding: utf-8 -*-
"""
find_playable_test.py - 离线验证**惰性扫描** `find_playable()` 的兜底路(不需要游戏)。

为什么单独给这个方法写测试(2026-09-20):
  实机日志(v0.1.6,用户 A:12h44m)里有 34 段卡死 —— 每段 10~61 秒,机器人只是
  每 1.5 秒存一帧,**就是不结束回合**。traceback 指到:

      hand_scanner_v2.py:733  "n_probes": len((cands[0] or {}).get("probes") or [])
      IndexError: list index out of range

  `cands` 为空时(布局表一条都对不上 —— 手牌出完那一刻最容易,因为表里没有
  "0 张"这条)这一行先炸,于是紧跟着的 `if not cands:` 盲扫兜底**永远走不到**,
  异常冒到 main_loop 的 except,这一 tick 根本没执行到"该不该结束回合"。

  根因是"列表可能为空"这件事没有任何一条用例盯着 —— `scan_fast()` 有
  scan_fast_test.py 守着,`find_playable()` 一直没有。这个文件补上。

用法:
  cd D:\\kards-auto
  set PYTHONPATH=D:\\kards-auto\\src
  python\\python.exe dev\\find_playable_test.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import hand_scanner_v2 as hsv

# 布局表:只有 "1 张 / 2 张 / 3 张" 三条(和实机一样,表里没有"0 张")
LAYOUTS = {
    "570": {"left_edge": 570, "count": 1, "probes": [645]},
    "536": {"left_edge": 536, "count": 2, "probes": [568, 645]},
    "498": {"left_edge": 498, "count": 3, "probes": [536, 605, 675]},
}

allok = True


def check(name, ok, extra=""):
    global allok
    allok = allok and ok
    print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"   {extra}" if extra else ""))


def make_scanner(layouts=LAYOUTS, blind=None):
    """造一个不碰鼠标/窗口的扫描器。blind = 盲扫兜底被调用时返回的东西。"""
    sc = hsv.HandScannerV2(0, {})
    sc._load_layouts = lambda: layouts
    sc._memory_plan = lambda *a, **k: None        # 记忆这一路另外测,这里只测几何
    sc.last_left_suspect = False
    sc.last_right_suspect = False
    calls = []

    def fake_blind(budgets, exclude=None, debug=False):
        calls.append(list(budgets))
        return blind if blind is not None else ([], None)

    sc._blind_scan_fallback = fake_blind
    return sc, calls


print("=" * 82)
print("① 布局表一条都对不上 -> 必须走盲扫兜底,而且**不许抛异常**")
print("   (实机:手牌出完/画面被挡 -> 量到的边缘 999 对不上任何一条)")
print("=" * 82)

for tag, edge, right in (("右边也量不到", 999, None),
                         ("右边量到了(1200)", 999, 1200),
                         ("左边缘偏出去一点点(表最近 570,量到 700)", 700, 1200)):
    sc, calls = make_scanner()
    try:
        cards, cost = sc.find_playable([5], edge=edge, right=right)
        crashed = None
    except Exception as e:                        # noqa: BLE001 — 这里就是要抓它
        cards, cost, crashed = None, None, f"{type(e).__name__}: {e}"
    check(f"{tag}: 没抛异常", crashed is None, "" if crashed is None else f"<- {crashed}")
    if crashed is None:
        check(f"{tag}: 走了盲扫兜底", bool(calls), f"calls={calls}")
        check(f"{tag}: 返回 ([], None)", cards == [] and cost is None)
        check(f"{tag}: last_layout 记下「0 个候选」",
              sc.last_layout.get("n_cands") == 0,
              f"n_cands={sc.last_layout.get('n_cands')} n_probes={sc.last_layout.get('n_probes')}")
        # `last_reason` 会被后面每一次 _why() 覆盖,这里只要求"有一条能读的原因":
        # 真兜底会把它改成「盲扫兜底:…」,本用例把兜底打了桩,所以留下的是几何原因。
        why = sc.last_reason or ""
        check(f"{tag}: 原因写给日志了(引擎那行 `| 原因:` 要用)",
              ("容差" in why) or ("兜底" in why), repr(why))

print()
print("=" * 82)
print("② 兜底能真的出牌(布局表坏了也不该整回合不出牌)")
print("=" * 82)
sc, calls = make_scanner(blind=([{"x": 605, "name": "T-26", "type": "tank",
                                  "cost": 2}], 2))
try:
    cards, cost = sc.find_playable([5], edge=999, right=1200)
    crashed = None
except Exception as e:                            # noqa: BLE001
    cards, cost, crashed = None, None, f"{type(e).__name__}: {e}"
check("兜底返回的那张牌被原样交回引擎", crashed is None and cost == 2
      and cards and cards[0].get("name") == "T-26",
      f"crashed={crashed} cards={cards} cost={cost}")

print()
print("=" * 82)
print("③ 对照组:边缘在容差内 -> **不许**走兜底,要用表里那条")
print("=" * 82)
sc, calls = make_scanner()
def _fake_probe_until(entry, budget, exclude=None, max_cards=10, debug=False,
                      probes=None):
    """打桩:不管探针怎么算,都直接交回"表里第一条探针那张牌"。
    ★ 2026-09-21:签名跟着 `_probe_layout_until` 加了 `probes=`(并集探针)一起改,
      否则惰性路一传 `probes=` 就 TypeError —— 打桩和真函数签名必须同步。"""
    return ([{"x": entry["probes"][0], "name": "表牌", "type": "infantry", "cost": 1}], 1)


sc._probe_layout_until = _fake_probe_until
try:
    cards, cost = sc.find_playable([5], edge=572, right=1200)   # 与 570 差 2px
    crashed = None
except Exception as e:                            # noqa: BLE001
    cards, cost, crashed = None, None, f"{type(e).__name__}: {e}"
check("正常路径没抛异常", crashed is None, "" if crashed is None else f"<- {crashed}")
check("没走盲扫兜底", not calls, f"calls={calls}")
check("用的就是表里「1 张」那条", sc.last_layout.get("count") == 1
      and sc.last_layout.get("n_cands", 0) >= 1,
      f"last_layout={ {k: sc.last_layout.get(k) for k in ('count','n_cands','n_probes')} }")
check("把它出的那张牌交回引擎", cost == 1 and cards and cards[0].get("x") == 645,
      f"cards={cards} cost={cost}")

print()
print("=" * 82)
print("全部通过" if allok else "★ 有失败项,别打包")
print("=" * 82)
sys.exit(0 if allok else 1)
