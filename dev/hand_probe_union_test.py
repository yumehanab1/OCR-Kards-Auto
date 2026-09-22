# -*- coding: utf-8 -*-
"""
hand_probe_union_test.py - 离线验证"**张数分不清时探针取并集 + 两端补一格**"。

为什么要有它(2026-09-21,用户实机日志之后):
  另一台机器那一局的日志里,引擎对"手牌几张"给过 **5 / 7 / 8 三个答案**
  (见 `docs/ORDER_CARDS_REAL_TEST.md` §7 第 1 条):

    23:41:34 布局「7 张」(表内左 368,量到 L433/R919;选中那条残差 L65/R4;容差内还有 [9, 8])
    23:42:06 布局「5 张」(表内左 421,量到 L414/R812;选中那条残差 L7/R48;容差内还有 [])
    23:42:39 布局「8 张」(表内左 357,量到 L407/R925;选中那条残差 L50/R0;容差内还有 [7, 9])

  根因不是"算错了",而是**这个判断本质上分不出来**:表里 7/8/9 三条的边缘几乎一样
  (左 368/357/358,右 915/925/915),容差 22 之内三条都能过闸;命中率也分不出来
  (每根探针都落在某张牌的热区里)。一旦猜小一档,就会重演 2026-09-13 那个后果 ——
  `hand_scanner_v2.py` 第 96~99 行自己记着:"探针按「5 张」的间距铺 -> 只落在
  第 2/4/6/8 张上,**最左那张铁锤整局一次都没被识别**"。

  ⇒ 修法不是"猜得更准",而是**别猜**:容差内不止一条时按"并集"铺探针,
    再按选中那条的间距往两端各补一格。这个文件就盯着这条判据。

用法:
  cd /d D:\\kards-auto-repo
  set PYTHONPATH=src
  D:\\kards-auto\\python\\python.exe -u dev\\hand_probe_union_test.py
返回码 0 = 全过。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import hand_scanner_v2 as hsv

# --- 真实的布局表条目(直接抄 config/hand_layout.json,别自己编)--------------
L5 = {"count": 5, "left_edge": 421, "right_edge": 860,
      "probes": [455, 531, 602, 677, 777]}
L7 = {"count": 7, "left_edge": 368, "right_edge": 915,
      "probes": [405, 466, 530, 596, 660, 727, 821]}
L8 = {"count": 8, "left_edge": 357, "right_edge": 925,
      "probes": [388, 443, 503, 562, 620, 681, 744, 827]}
L9 = {"count": 9, "left_edge": 358, "right_edge": 915,
      "probes": [389, 437, 483, 539, 589, 636, 690, 740, 829]}
L2 = {"count": 2, "left_edge": 536, "right_edge": 772,
      "probes": [568, 677]}
#: 一张牌的悬停热区半宽(实测约 72px 宽,见 hand_scanner_v2 第 54 行的标定)
HOT_HALF = 36

allok = True


def check(name, ok, extra=""):
    global allok
    allok = allok and ok
    print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"   {extra}" if extra else ""))


def make_scanner():
    """不碰鼠标/窗口的扫描器(和 find_playable_test.py 同一个套路)。"""
    sc = hsv.HandScannerV2(0, {})
    sc.last_layout = {}
    return sc


def xs(pairs):
    return [x for _i, x in pairs]


print("=" * 84)
print("① 只有一条候选(没有歧义)-> 走老行为,一根都不多加")
print("=" * 84)
sc = make_scanner()
out = sc._probes_for([L8])
check("探针 == 这条条目自己的探针",
      xs(out) == L8["probes"], f"{xs(out)}")
check("下标就是 0..n-1(手牌记忆按这个对齐)",
      [i for i, _x in out] == list(range(len(L8["probes"]))), f"{[i for i, _x in out]}")

print()
print("=" * 84)
print("② 有歧义(7 张 / 8 张都在容差内)-> 实走探针必须**盖住两条的并集**")
print("=" * 84)
sc = make_scanner()
cands = [L7, L8]          # 左边缘 368/357,差 11px —— 都在容差 22 之内
out = sc._probes_for(cands)
exp_union = sorted(set(L7["probes"]) | set(L8["probes"]))
hit = [p for p in exp_union if any(abs(p - x) <= hsv.LAYOUT_PROBE_UNION_DEDUP_PX
                                   for x in xs(out))]
check(f"并集里每一根都有实走探针落在它附近(±{hsv.LAYOUT_PROBE_UNION_DEDUP_PX}px)",
      len(hit) == len(exp_union),
      f"缺 {[p for p in exp_union if p not in hit]}  实走={xs(out)}")
check("实走根数 > 选中那条的根数(确实多铺了)",
      len(out) > len(L8["probes"]), f"{len(out)} vs {len(L8['probes'])}")
check("**每一张真实牌都被覆盖**:8 张那条的每个探针 ±36px 内有实走探针",
      all(any(abs(p - x) <= HOT_HALF for x in xs(out)) for p in L8["probes"]),
      f"实走={xs(out)}")

print()
print("=" * 84)
print("③ 两端补一格(只在『有歧义』或『检测器说这条边缘量短了』时才补)")
print("=" * 84)
sc = make_scanner()
sc.last_left_suspect = True           # 检测器自己报的:左边缘旁边有被跳过的窄段
sc.last_right_suspect = True
out = sc._probes_for([L2])            # 568 / 677 -> 间距 109,两端补 459 / 786
got = xs(out)
check("左端补出 568-109=459", 459 in got, f"{got}")
check("右端补出 677+109=786", 786 in got, f"{got}")
check("补出来的探针下标一律 -1(记忆只认 >=0 -> 它们永不被跳过)",
      all(i == -1 for i, x in out if x in (459, 786)), f"{out}")
check("原有两根下标没被弄乱",
      [i for i, x in out if x in (568, 677)] == [0, 1], f"{out}")
sc2 = make_scanner()                  # 没有任何"量短"信号 + 只有一条候选 -> 一根都不补
check("没有信号时不补(不白花那 1.2s)",
      xs(sc2._probes_for([L2])) == L2["probes"], f"{xs(sc2._probes_for([L2]))}")

print()
print("=" * 84)
print("④ 补出来的探针不许越界(左边是固定装饰区,右边是鹰徽面板/按钮)")
print("=" * 84)
sc = make_scanner()
sc.last_left_suspect = True
sc.last_right_suspect = True
out = sc._probes_for([L8])            # 388-62.7 = 325 < FAN_X_MIN(340) -> 必须丢掉
check(f"左端补针 325 < FAN_X_MIN({hsv.FAN_X_MIN}) -> 不出现",
      325 not in xs(out), f"{xs(out)}")
check("右端补针 890(在界内)-> 出现", 890 in xs(out), f"{xs(out)}")
check("所有实走探针都在 [FAN_X_MIN, LAYOUT_PROBE_X_MAX] 内",
      all(hsv.FAN_X_MIN <= x <= hsv.LAYOUT_PROBE_X_MAX for x in xs(out)), f"{xs(out)}")

print()
print("=" * 84)
print("⑤ 去重:挨太近的合成一根,而且**保留带下标的**那根")
print("=" * 84)
sc = make_scanner()
near = {"count": 4, "left_edge": 357, "right_edge": 925,
        "probes": [390, 445, 505, 563, 621, 682, 745, 828]}   # 和 L8 差 1~2px
out = sc._probes_for([L8, near])
check("近重复被合掉了(不会一根位置探两遍)",
      len(out) <= len(L8["probes"]) + len(near["probes"]),
      f"{len(out)} 根: {xs(out)}")
check("保留下来的那根带下标 >= 0(记忆才能跳它)",
      all(i >= 0 for i, x in out if any(abs(x - p) <= 2 for p in L8["probes"])),
      f"{out}")

print()
print("=" * 84)
print("⑥ 同一输入跑两次 -> 结果必须完全一样(要能当判据用)")
print("=" * 84)
a = xs(make_scanner()._probes_for([L7, L8, L9]))
b = xs(make_scanner()._probes_for([L7, L8, L9]))
check("两次一致", a == b, f"{a} vs {b}")
check("9 张那条也被盖住",
      all(any(abs(p - x) <= HOT_HALF for x in a) for p in L9["probes"]),
      f"实走={a}")

print()
print("=" * 84)
print("⑦ 边界:候选为空 -> 返回空表,**不许抛异常**")
print("   (上一轮那个 IndexError 就是这个形状:cands 为空时先炸,兜底永远走不到)")
print("=" * 84)
try:
    out = make_scanner()._probes_for([])
    crashed = None
except Exception as e:                        # noqa: BLE001 — 这里就是要抓它
    out, crashed = None, f"{type(e).__name__}: {e}"
check("没抛异常", crashed is None, "" if crashed is None else f"<- {crashed}")
check("返回空表", out == [], f"{out}")

print()
print("=" * 84)
print("⑧ A/B 开关:LAYOUT_PROBE_UNION=False 时退回『只用选中那条的探针』")
print("=" * 84)
sc = make_scanner()
old_union, old_ends = hsv.LAYOUT_PROBE_UNION, hsv.LAYOUT_PROBE_EXTRA_ENDS
try:
    hsv.LAYOUT_PROBE_UNION = False
    hsv.LAYOUT_PROBE_EXTRA_ENDS = False
    out = sc._probes_for([L7, L8])
    check("实走 == 选中那条自己的探针(老行为)", xs(out) == L7["probes"], f"{xs(out)}")
finally:
    hsv.LAYOUT_PROBE_UNION, hsv.LAYOUT_PROBE_EXTRA_ENDS = old_union, old_ends
check("开关恢复后行为也恢复",
      xs(make_scanner()._probes_for([L7, L8])) != L7["probes"])

print()
print("=" * 84)
print("全部通过" if allok else "★ 有失败项,别打包")
print("=" * 84)
sys.exit(0 if allok else 1)
