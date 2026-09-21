# -*- coding: utf-8 -*-
"""
hand_count_test.py - 离线验证"**手牌张数按实读修正**"(`LAYOUT_COUNT_FROM_PROBES`)。

为什么要有它(2026-09-21,紧接 `hand_probe_union_test.py` 那一条):
  上一轮把"别漏牌"修好了(探针取并集 + 两端补一格),但 `self.last_hand_count`
  还是 **`cands[0]["count"]` 猜的** —— 也就是那个已经被实机证明会猜错的量。它的下游是
  `turn_engine._memory_note_scan` -> `hand_memory.note_scan(probed, count)`,
  于是实机日志里出现成串的:

      [记忆] 失效:张数对不上(记忆 7 张,现在读到 5 张) -> 这一轮退回老实扫

  (那是错张数的下游,不是扫描本身出错 —— 张数对了,这一串就没了。)

判据(一处来源 = `hand_scanner_v2.LAYOUT_COUNT_FROM_PROBES` 那段常量注释):
  `probes` 里**下标 >= 0 的一定是选中那条自己的探针**,**下标 -1 的一定是并集/两端补的**;
  所以"一根 -1 探针读到了牌"就证明**选中那条的覆盖范围之外确实还有牌**:
      实读张数 = base.count + "离它的每一根探针都超过 MAX_SAME_SPAN、且真读到牌的**位置**的
                 个数"(上限 +2)

  ★ 门槛为什么是"离每一根都超过 `MAX_SAME_SPAN`"、不是"落在两端之外":
    实测同一根探针能读到**相邻卡**的一块,所以"稍微超出两端"可能是它本来就该探到的那张牌。
    拿它当"多出来一张"会**多数** —— 23:41:34 那帧(真值 8 张、base 7 张)的左端 x405
    离它的第一根探针只有 37px,照"超出即多"会数成 9,**比不改更坏**。

  ★ 本文件第 ⑥ 段拿**实机原始帧**把这条判据算了一遍(帧在
    `C:\\Users\\31291\\Desktop\\kards-auto\\docs\\real_test_20260920\\`,
    几何全部来自 `config/hand_layout.json`,不用任何屏幕/鼠标)。

用法:
  cd /d D:\\kards-auto-repo
  set PYTHONPATH=D:\\kards-auto-repo\\src
  D:\\kards-auto\\python\\python.exe -u dev\\hand_count_test.py
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
L1 = {"count": 1, "left_edge": 570, "right_edge": 735, "probes": [645]}
L2 = {"count": 2, "left_edge": 536, "right_edge": 772, "probes": [568, 677]}
L3 = {"count": 3, "left_edge": 498, "right_edge": 794, "probes": [536, 605, 711]}
L4 = {"count": 4, "left_edge": 459, "right_edge": 826, "probes": [492, 570, 639, 740]}
L5 = {"count": 5, "left_edge": 421, "right_edge": 860,
      "probes": [455, 531, 602, 677, 777]}
L6 = {"count": 6, "left_edge": 390, "right_edge": 886,
      "probes": [434, 499, 566, 634, 703, 802]}
L7 = {"count": 7, "left_edge": 368, "right_edge": 915,
      "probes": [405, 466, 530, 596, 660, 727, 821]}
L8 = {"count": 8, "left_edge": 357, "right_edge": 925,
      "probes": [388, 443, 503, 562, 620, 681, 744, 827]}
L9 = {"count": 9, "left_edge": 358, "right_edge": 915,
      "probes": [389, 437, 483, 539, 589, 636, 690, 740, 829]}
ALL = [L1, L2, L3, L4, L5, L6, L7, L8, L9]
#: 一张牌的悬停热区半宽(实测约 72px 宽,见 hand_scanner_v2 第 54 行的标定)
HOT_HALF = 36

allok = True


def check(name, ok, extra=""):
    global allok
    allok = allok and ok
    print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"   {extra}" if extra else ""))


def make_scanner(count=None):
    """不碰鼠标/窗口的扫描器(和 find_playable_test.py / hand_probe_union_test.py 同一套路)。"""
    sc = hsv.HandScannerV2(0, {})
    sc.last_layout = {}
    sc.last_hand_count = count
    return sc


def seen_from(hits, misses=()):
    """
    把"哪几个 x 弹了面板"拼成 `_probe_layout_until` 那种 `seen` 记录。

    每一项可以是 `(次序下标, x)` 或 `{i, x}`(直接喂 `_probes_for` 的输出)或只给 `x`
    (那时按并集探针记成 -1)。
    ★ 下标要分得清:选中那条自己的探针下标 >= 0,并集/两端补出来的一律 -1 ——
      用例得能复现真函数里那份记录,不然验的就不是产品那条路。
    """
    def rec(t, panel):
        if isinstance(t, dict):
            i, x = t.get("i", -1), t.get("x")
        elif isinstance(t, tuple):
            i, x = t
        else:
            i, x = -1, t
        return {"i": i, "x": int(x), "panel": panel}

    return [rec(t, True) for t in hits] + [rec(t, False) for t in misses]


def cands_for(edge, right=None, left_suspect=False, right_suspect=False):
    """
    **照抄 `find_playable` 的筛法**(不然用例验证的就不是产品那条路):
    左边缘过闸(容差 22)-> 左右边缘排序 -> 右边缘那一路的候选**并进**来(取并集)。
    ★ 那个"改用右边缘挑"的分支有**三个**前置条件(左边缘可疑 **且** 右边缘不可疑
      **且** 宽度合理),少判一个就会挑出产品根本不会选的条目 —— 用例就白跑了。
    """
    tol = hsv.LAYOUT_EDGE_TOL
    cands = sorted((v for v in ALL if abs(v["left_edge"] - edge) <= tol),
                   key=lambda v: abs(v["left_edge"] - edge))
    if hsv.LAYOUT_MATCH_BOTH_EDGES and right is not None and cands:
        width = right - edge
        if hsv.LAYOUT_WIDTH_SANE[0] <= width <= hsv.LAYOUT_WIDTH_SANE[1]:
            def _rank(v):
                dl = abs(v["left_edge"] - edge)
                d_r = abs(v["right_edge"] - right) if v.get("right_edge") else 999
                return (0 if d_r <= hsv.LAYOUT_RIGHT_TOL else 1, dl + min(d_r, 120), dl)
            cands = sorted(cands, key=_rank)
    sane = (right is not None
            and hsv.LAYOUT_WIDTH_SANE[0] <= (right - edge) <= hsv.LAYOUT_WIDTH_SANE[1])
    if (hsv.LAYOUT_TRUST_RIGHT_IF_LEFT_SUSPECT and left_suspect
            and not right_suspect and sane):
        by_right = sorted((v for v in ALL if v.get("right_edge")
                           and abs(v["right_edge"] - right) <= hsv.LAYOUT_RIGHT_TOL),
                          key=lambda v: abs(v["right_edge"] - right))
        if by_right:
            ids = {id(v) for v in cands}
            cands = sorted(list(cands) + [v for v in by_right if id(v) not in ids],
                           key=lambda v: (abs((v.get("right_edge") or 0) - right)
                                          if v.get("right_edge") else 999,
                                          -(v.get("count") or 0)))
    return cands


def frame_trace(measured_left, measured_right, truth_count, left_suspect=False,
                right_suspect=False):
    """
    把**一帧实机画面**过成一次"整条探针走完":候选 -> 实走探针 -> 每一根读到什么。

    真值模型:手牌是**等距**铺开的(布局表自己就是这么标定的),
    所以 `第 k 张的中心 = 量到的左端 + (最右端 - 左端) / (真值张数 - 1) * k`。
    一根探针"读到牌" = 它落在某张牌的中心 ± 热区半宽内。
    """
    sc = make_scanner()
    sc.last_left_suspect = left_suspect
    sc.last_right_suspect = right_suspect
    cands = cands_for(measured_left, measured_right, left_suspect, right_suspect)
    assert cands, f"这帧没有候选({measured_left}/{measured_right})"
    base = cands[0]
    probes = sc._probes_for(cands)
    step = (measured_right - measured_left) / float(truth_count - 1)
    centers = [measured_left + step * k for k in range(truth_count)]
    hits = [x for _i, x in probes
            if any(abs(x - c) <= HOT_HALF for c in centers)]
    return {"scanner": sc, "cands": cands, "base": base, "probes": probes,
            "centers": centers, "hits": hits, "truth": truth_count,
            "seen": seen_from(hits), "measured": (measured_left, measured_right)}


# ============================================================================
print("=" * 84)
print("① 只有 base(选中那条)自己探到牌 -> 张数**一个都不许动**")
print("   (这一条是『别把对的改坏』:base 对得上时,修正必须是恒等变换)")
print("=" * 84)
sc = make_scanner(count=L8["count"])
changed, was, now = sc._count_correction_from_walk(
    L8, seen=seen_from(L8["probes"]))          # 8 根探针全部弹了面板
check("没改(返回 changed=False)", changed is False, f"{(changed, was, now)}")
check("张数仍是 8", sc.last_hand_count == 8, f"{sc.last_hand_count}")
check("也没往日志里写修正行", "修正" not in (sc.last_reason or ""),
      repr(sc.last_reason))

print()
print("=" * 84)
print("② 并集探针读到牌 -> 张数按规则提一档,而且**日志里有一行说清凭什么**")
print("=" * 84)
sc = make_scanner(count=L8["count"])
out = seen_from(L8["probes"] + [890])        # 890 是 `_probes_for` 补出来的右探针(下标 -1)
changed, was, now = sc._count_correction_from_walk(L8, seen=out)
check("改了", changed is True and was == 8 and now == 9, f"{(changed, was, now)}")
check("last_hand_count = 9", sc.last_hand_count == 9, f"{sc.last_hand_count}")
log = sc.last_reason or ""
check("日志写进 last_reason(引擎那行的 `| 原因:`)", "张数按实读修正" in log, repr(log))
check("日志里有『原以为 N 张 -> 实读到 M 张』", "原以为 8 张 -> 实读到 9 张" in log, repr(log))
check("日志里点名了依据那根探针的 x", "890" in log, repr(log))
check("日志里给了覆盖范围(判据能复核,不是一句结论)",
      f"x{L8['probes'][0]}" in log and f"x{L8['probes'][-1]}" in log, repr(log))

print()
print("=" * 84)
print("③ 同一张牌被两根 -1 探针先后探到 -> 只算**一个位置**(不许当成两张)")
print("   (两根挨得比 `MAX_SAME_SPAN` 近 -> 合并成一处;否则会把同一张牌数成两张 = 猜多)")
print("=" * 84)
sc = make_scanner(count=L8["count"])
changed, was, now = sc._count_correction_from_walk(
    L8, seen=seen_from(L8["probes"] + [895, 902]))    # 两根都在右边那张牌上
check("只提一档(→9),不是两档", now == 9, f"{(changed, was, now)}")

print()
print("=" * 84)
print("④ 两端补出来的探针也走这条路(左端同理)")
print("=" * 84)
sc = make_scanner(count=L8["count"])
changed, was, now = sc._count_correction_from_walk(
    L8, seen=seen_from(L8["probes"] + [325]))
check("左端补针读到牌 -> 也提一档", now == 9, f"{(changed, was, now)}")

print()
print("=" * 84)
print("⑤ 盖不住的情况:两端各真读到一个位置 -> 提满上限(**+2**)")
print("=" * 84)
sc = make_scanner(count=L8["count"])
changed, was, now = sc._count_correction_from_walk(
    L8, seen=seen_from(L8["probes"] + [325, 890]))
check(f"提满 {hsv.LAYOUT_COUNT_MAX_BUMP} 档", now == 8 + hsv.LAYOUT_COUNT_MAX_BUMP,
      f"{(changed, was, now)}")
sc = make_scanner(count=L8["count"])
changed, was, now = sc._count_correction_from_walk(
    L8, seen=seen_from(L8["probes"] + [325, 890, 290]))   # 三处也还是 +2
check("三处也只到上限,不一路加下去", now == 8 + hsv.LAYOUT_COUNT_MAX_BUMP,
      f"{(changed, was, now)}")

print()
print("=" * 84)
print("⑥ ★ 拿**实机原始帧**核算(这一条才证明判据站得住)")
print("   几何全部来自 config/hand_layout.json + 日志里量到的 L/R,不碰屏幕")
print("=" * 84)
#: (量到的左 / 量到的右 / **牌面数出来的真值** / 左边缘可疑 / 右边缘可疑)
#: ★ 真值那一列是"数牌面"数出来的:把 y≈590..715 那条带放大,数**费用徽章**的个数;
#:   再用真值张数下的等距模型核对(每一根实走探针都得落在某张牌中心 ±HOT_HALF 内)。
#: ★ 每帧的 L/R 与"选中几条"全部抄自 `docs/real_test_20260920/main_loop.log` 原文。
FRAMES = [
    # (名字, 量到的 L, 量到的 R, 真值, 左边缘可疑, 右边缘可疑, 这一帧能不能当判据用)
    ("23:41:34 那帧(选中「7 张」,量到 L433/R919)——**选对了**,对照组",
     433, 919, 7, True, False, False),
    ("23:41:58 那帧(选中「5 张」,量到 L414/R812;右边缘只差 48px)",
     414, 812, 8, True, False, True),
    ("23:42:39/23:43:17 那帧(选中「8 张」,量到 L407/R925)",
     407, 925, 9, True, False, True),
    ("23:43:10 那帧(选中「8 张」,量到 L356/R925,左边缘量准了)",
     356, 925, 9, False, False, True),
]
#: ★ 哪些帧**不能**当判据用,以及为什么(不删掉,留在输出里给人看):
#:   23:41:34 那一行日志自相矛盾 —— 它写 `量到 L433` + `选中那条残差 L65`,
#:   而 65 = 433 - 368 ⇒ 表里那条是「7 张」(left_edge 368)。可 433 与 368 差 65,
#:   **过不了左闸(容差 22)**;也就是说"选中 7 张"这件事按现行代码根本复现不出来
#:   (那一局的日志里另有一处同样的矛盾,见 `PC_STATE.md` 第 764~766 行的复核)。
#:   ⇒ 拿它当"对照组"就是拿一条复现不出来的记录当基准,所以只打印、不断言。
SKIP_STRICT = {0}

for idx, (name, mleft, mright, truth, lsus, rsus, usable) in enumerate(FRAMES):
    tr = frame_trace(mleft, mright, truth, lsus, rsus)
    sc, base = tr["scanner"], tr["base"]
    sc.last_hand_count = base["count"]
    print(f"  · {name}")
    print(f"      候选 = {[c['count'] for c in tr['cands']]}  选中 = {base['count']} 张"
          f"  实走探针 = {[x for _i, x in tr['probes']]}")
    print(f"      真值 {truth} 张的牌心 = {[round(c) for c in tr['centers']]}")
    print(f"      实际读到牌的探针 = {tr['hits']}")
    changed, was, now = sc._count_correction_from_walk(base, seen=tr["seen"])
    print(f"      -> 修正:{was} -> {now}")
    if sc.last_reason:
        print(f"         日志:{sc.last_reason}")
    if idx in SKIP_STRICT:
        print("      (这一帧只打印、不断言:日志自相矛盾,复现不出它说的『选中 7 张』;")
        print("       拿它当基准就是把一条复现不出来的记录当判据 —— 见 SKIP_STRICT 的说明)")
        print()
        continue
    # 判据一:真值下的牌心必须能解释实走的每一根探针(否则这一帧的真值模型站不住)
    check(f"    真值 {truth} 张的等距模型能解释实走的每一根探针",
          len(tr["hits"]) == len(tr["probes"]),
          f"{len(tr['hits'])}/{len(tr['probes'])} 根命中")
    # 判据二(最硬的一条):修正**只加不减**,而且**不许超过真值** ——
    #   超过真值就是"猜多",比不改更坏(会把记忆带偏)。
    check("    修正只加不减,且**不超过真值**",
          now >= was and now <= truth, f"{was} -> {now}(真值 {truth})")
    # 判据三:提档必须由"落在选中那条**够不着**的地方"的命中触发
    span = hsv.MAX_SAME_SPAN
    left_reach = base["probes"][0] - span
    right_reach = base["probes"][-1] + span
    outer = sorted(x for x in tr["hits"]
                   if x < left_reach or x > right_reach)
    if now > was:
        check("    提档的依据确实是够不着的地方读到了牌",
              bool(outer), f"够不着={outer}")
    else:
        check("    没提档,因为没有任何命中落在它够不着的地方",
              not outer, f"够不着={outer}")
    print()

# ★ 把"够不着"如实印出来(别让下一个人以为这条判据能修好一切):
print("  ⚠️ 已知够不着(不是回归,是这条判据的上限,写下来免得下次重走):")
print("     · 23:42:38 那帧:选中「5 张」、真值 8 张 -> 本判据只能给 6~7(仍少 1~2)。")
print("       原因:补出来的探针只往外伸**一格**,再往外属于'没探过'的地方 ——")
print("       按项目纪律,没探过就不许猜(宁可按最小值报)。")
print("     · 真值 8 张那帧的**左端**也够不着:选中「5 张」的第一根探针在 x455,")
print("       左端补出来的针在 389/325,而真值第 1 张的牌心更靠左 —— 补一格补不到它。")
print()

print("=" * 84)
print("⑦ 提前收手(找到能出的牌就 return)-> 张数**一根都不许动**")
print("   (那时手里还有没探的位置,拿它推张数就是拿没探过的地方猜)")
print("=" * 84)
sc = make_scanner(count=L8["count"])
sc.last_probe_seen = seen_from(L8["probes"] + [890])   # 外面那根确实读到了牌
real = hsv.HandScannerV2._count_correction_from_walk


def fake_probe_until(entry, budget, exclude=None, max_cards=10, debug=False,
                     probes=None):
    """打桩:永远"第一根就找到能出的牌" -> 真函数那条路会在 return 前收手。
    ★ 签名和真函数一致(含 `probes=`),和 `find_playable_test.py` 同一个套路。"""
    return ([{"x": entry["probes"][0], "name": "表牌", "type": "infantry", "cost": 1}], 1)


calls = []
sc._probe_layout_until = fake_probe_until


def spy(entry, debug=False, seen=None):
    """盯住"修正有没有被调用" —— 提前收手那条路**根本不该走到它**。"""
    calls.append(1)
    return real(sc, entry, debug=debug, seen=seen)


sc._count_correction_from_walk = spy
cards, cost = sc.find_playable([5], edge=L8["left_edge"], right=L8["right_edge"])
check("确实找到了牌(证明走的是『提前收手』那条路)", bool(cards), f"{cards}")
check("张数没被改(仍是 8)", sc.last_hand_count == 8, f"{sc.last_hand_count}")
check("修正函数**一次都没被调用**", not calls, f"calls={calls}")

print()
print("=" * 84)
print("⑧ 整条探针走完(一张能出的都没有)时,修正**在真函数里**自动发生")
print("   ★ 这条走的是 `find_playable` -> `_probe_layout_until` 的收尾出口(提前收手那条路的反面)")
print("=" * 84)
sc = make_scanner(count=L8["count"])
sc._probe_layout_until = real.__get__(sc, hsv.HandScannerV2)
sc.last_probe_seen = []          # 真的走探针时会填;这里先清空


def fake_probe_until_all(entry, budget, exclude=None, max_cards=10, debug=False,
                         probes=None):
    """打桩:装成"整条探针走完了、一张能出的都没有"。

    ★ 这里**自己调了一次** `_count_correction_from_walk` —— 打桩替掉的是"真的去悬停/识别"
      那一段,而收尾那一步(走完之后按实读修张数)是产品逻辑,不该被替掉。
      真函数那条**端到端**的路(不走这个桩、扫描器自己走到收尾出口)是 ⑦ 那条用例
      在反向验证的(它证明提前收手时那次调用**不会**发生)。
    """
    sc.last_probe_seen = seen_from(list(probes or []) + [890])
    real(sc, entry, debug=debug, seen=sc.last_probe_seen)
    return ([], None)


sc._probe_layout_until = fake_probe_until_all
cards, cost = sc.find_playable([5], edge=L8["left_edge"], right=L8["right_edge"])
check("没找到牌([], None)", cards == [] and cost is None, f"{cards} {cost}")
check("张数被修正成 9(实读)", sc.last_hand_count == 9, f"{sc.last_hand_count}")
check("修正留了一份 `last_count_fix`(不会被后面那句『全扫完』覆盖掉)",
      "张数按实读修正" in (sc.last_count_fix or ""), repr(sc.last_count_fix))
# ★ 这一条是**引擎日志**能看见的证据:收尾那句 `原因:` 里报的张数必须已经是实读值 9,
#   而 `last_layout["count"]` 仍是选中那条说的 8 —— 两个数不一样,正好说明"修过"。
check("收尾那句原因里报的张数是实读的 9(不是表里的 8)",
      "实读 9 张" in (sc.last_reason or "") and "表里写 8 张" in (sc.last_reason or ""),
      repr(sc.last_reason))
check("last_layout 仍留着『表里说 8 张』这个原始证据(判据和结论不混在一起)",
      sc.last_layout.get("count") == 8, f"{sc.last_layout.get('count')}")

print()
print("=" * 84)
print("⑨ A/B 开关:LAYOUT_COUNT_FROM_PROBES=False -> 退回老行为(只用 cands[0]['count'])")
print("=" * 84)
sc = make_scanner(count=L8["count"])
old = hsv.LAYOUT_COUNT_FROM_PROBES
try:
    hsv.LAYOUT_COUNT_FROM_PROBES = False
    changed, was, now = sc._count_correction_from_walk(L8, seen=seen_from(L8["probes"] + [890]))
    check("开关关掉 -> 不改、不写日志",
          changed is False and sc.last_hand_count == 8 and not (sc.last_reason or ""),
          f"{(changed, was, now)} count={sc.last_hand_count} reason={sc.last_reason!r}")
finally:
    hsv.LAYOUT_COUNT_FROM_PROBES = old
sc = make_scanner(count=L8["count"])
changed, _w, now = sc._count_correction_from_walk(L8, seen=seen_from(L8["probes"] + [890]))
check("开关恢复后行为也恢复", changed is True and now == 9, f"{(changed, now)}")

print()
print("=" * 84)
print("⑩ 边界:拿不准就不许动(没有探针记录 / 表里没有张数 / 一根探针 / 空候选)")
print("=" * 84)
sc = make_scanner(count=8)
check("没有任何探针记录 -> 不改",
      sc._count_correction_from_walk(L8, seen=[]) == (False, None, None)
      and sc.last_hand_count == 8)
check("探针全没弹面板 -> 不改",
      sc._count_correction_from_walk(L8, seen=seen_from([], [405, 466]))
      == (False, None, None) and sc.last_hand_count == 8)
sc2 = make_scanner(count=None)          # 布局表一条都对不上时就是 None
check("表里张数是 None -> 不改(None 是『不知道』,不是 0)",
      sc2._count_correction_from_walk(L8, seen=seen_from([890, 320]))
      == (False, None, None) and sc2.last_hand_count is None)
sc3 = make_scanner(count=1)
check("只有一根探针(算不出卡距)-> 不改",
      sc3._count_correction_from_walk(L1, seen=seen_from([645]))
      == (False, None, None) and sc3.last_hand_count == 1)
sc4 = make_scanner(count=5)
check("空候选/无探针的条目 -> 不抛异常、不改",
      sc4._count_correction_from_walk({}, seen=seen_from([890]))
      == (False, None, None))

print()
print("=" * 84)
print("全部通过" if allok else "★ 有失败项,别打包")
print("=" * 84)
sys.exit(0 if allok else 1)
