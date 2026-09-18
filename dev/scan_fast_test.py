"""
scan_fast_test.py - 离线验证"坐标表直扫"的兜底逻辑(不需要游戏)。

scan_fast 会在布局表不可信时自动回退盲扫。回退条件有四条,任何一条失效都
可能在实机上乱出牌,所以必须逐个验证:

  1. 没有 config/hand_layout.json        -> 回退
  2. 测不到扇形左边缘                     -> 回退
  3. 左边缘和表里所有布局都差太远         -> 回退
  4. 按表悬停时命中率低于 60%             -> 回退

另外验证正常路径:命中率够时就返回表里那些位置的结果,不做盲扫。

用法:
  .venv\\Scripts\\python.exe src\\scan_fast_test.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from unittest import mock

import numpy as np

import hand_calibrate
import hand_scanner_v2 as hsv

FRAME = np.zeros((720, 1280, 3), dtype=np.uint8)
LAYOUTS = {
    "459": {"left_edge": 459, "count": 3, "probes": [493, 559, 628],
            "names": ["T-70", "T-70", "步兵"], "types": ["tank", "tank", "infantry"]},
}

results_log = []


def make_scanner(layouts, edge, hit_every=True, cards_from_table=True):
    """
    layouts        : scan_fast 会读到的布局表
    edge           : detect_left_edge 的返回值(None = 测不到)
    hit_every      : 每个悬停点是否都有面板(False = 命中率 0)
    """
    sc = hsv.HandScannerV2(0, {})
    sc._load_layouts = lambda: layouts
    # 不碰真实鼠标/窗口
    sc._move = lambda x, y: None
    sc._hover_frame = lambda x: FRAME.copy()

    # 记录是否发生了回退盲扫
    sc.scan = lambda max_cards=10, debug=False: (
        results_log.append("blind_scan") or
        [{"x": 111, "name": "盲扫", "type": "infantry", "cost": 1}]
    )
    sc.scan_fast_original = hsv.HandScannerV2.scan_fast

    state = {"i": 0}

    def fake_diff(a, b):
        # 交替返回"有面板/无面板"来模拟命中率
        if not hit_every:
            return None
        state["i"] += 1
        return (100, 100, 400, 400)

    # _classify 的签名后来扩了:y0(区域起始 y)+ box/frame(给指纹库裁卡面用)
    # + debug。测试里全都忽略,只固定返回一张表牌。
    sc._classify = lambda region, y0=0, box=None, frame=None, debug=False: (
        {"name": f"表牌{state['i']}", "type": "infantry", "cost": 2})
    return sc, fake_diff


def run_case(name, layouts, edge, hit_every, expect_fallback):
    results_log.clear()
    sc, fake_diff = make_scanner(layouts, edge, hit_every)
    with mock.patch.object(hsv, "capture_client_bgr", lambda h: FRAME.copy()), \
         mock.patch.object(hsv, "diff_bbox", fake_diff), \
         mock.patch.object(hand_calibrate, "detect_left_edge", lambda f: edge), \
         mock.patch.object(hsv.time, "sleep", lambda s: None):
        cards = sc.scan_fast()
    fell_back = "blind_scan" in results_log
    ok = (fell_back == expect_fallback)
    print(f"  {'OK ' if ok else 'FAIL'} {name:<44} "
          f"回退={'是' if fell_back else '否'} "
          f"(期望{'是' if expect_fallback else '否'}) 得到 {len(cards)} 张")
    return ok


print("=" * 82)
print("scan_fast 兜底逻辑验证")
print("=" * 82)
allok = True
allok &= run_case("1. 没有布局表 -> 回退盲扫", {}, 459, True, True)
allok &= run_case("2. 测不到左边缘 -> 回退盲扫", LAYOUTS, None, True, True)
allok &= run_case("3. 左边缘差太远(459 vs 700) -> 回退", LAYOUTS, 700, True, True)
allok &= run_case("4. 命中率 0% -> 回退盲扫", LAYOUTS, 459, False, True)
allok &= run_case("5. 正常:左边缘 459 命中 -> 用坐标表", LAYOUTS, 459, True, False)
allok &= run_case("6. 左边缘差 2px 在容差内 -> 用坐标表", LAYOUTS, 461, True, False)
# 容差已从 8px 放宽到 22px:左边缘自身有 ±10px 波动(同一副 5 张牌,
# 采集时 421、后来 430),容差太小会直接掉进盲扫
allok &= run_case("7. 左边缘差 9px(放宽后仍匹配)-> 用坐标表", LAYOUTS, 468, True, False)
allok &= run_case("8. 左边缘差 30px 超容差 -> 回退", LAYOUTS, 489, True, True)

print()
print("=" * 82)
print("正常路径返回的坐标是否来自布局表")
print("=" * 82)
results_log.clear()
sc, fake_diff = make_scanner(LAYOUTS, 459, True)
with mock.patch.object(hsv, "capture_client_bgr", lambda h: FRAME.copy()), \
     mock.patch.object(hsv, "diff_bbox", fake_diff), \
     mock.patch.object(hand_calibrate, "detect_left_edge", lambda f: 459), \
     mock.patch.object(hsv.time, "sleep", lambda s: None):
    cards = sc.scan_fast()
xs = [c["x"] for c in cards]
print(f"  布局表悬停点 {LAYOUTS['459']['probes']}")
print(f"  实际返回     {xs}")
ok = xs == LAYOUTS["459"]["probes"]
allok &= ok
print(f"  {'OK' if ok else 'FAIL'} 位置与表一致")

print()
print("=" * 82)
print("★ 每条早退路径都必须说清「为什么」")
print("  (§8 待办 9:实机日志里只有 `0 cards in 0.8s`,完全看不出倒在哪一条)")
print("=" * 82)


def reason_case(name, layouts, edge, hit_every, expect_kw, expect_fallback=None,
                capture_none=False):
    results_log.clear()
    sc, fake_diff = make_scanner(layouts, edge, hit_every)
    cap = (lambda h: None) if capture_none else (lambda h: FRAME.copy())
    with mock.patch.object(hsv, "capture_client_bgr", cap), \
         mock.patch.object(hsv, "diff_bbox", fake_diff), \
         mock.patch.object(hand_calibrate, "detect_left_edge", lambda f: edge), \
         mock.patch.object(hsv.time, "sleep", lambda s: None):
        sc.scan_fast()
    why = sc.last_reason or ""
    fell_back = "blind_scan" in results_log
    ok = expect_kw in why
    if expect_fallback is not None:
        ok = ok and (fell_back == expect_fallback)
    print(f"  {'OK ' if ok else 'FAIL'} {name:<40} -> {why!r}")
    return ok


allok &= reason_case("1. 没布局表", {}, 459, True, "没有 config/hand_layout.json",
                     True)
allok &= reason_case("2. 测不到左边缘", LAYOUTS, None, True, "测不到扇形左边缘",
                     True)
allok &= reason_case("3. 左边缘超容差", LAYOUTS, 700, True, "与最近布局",
                     True)
allok &= reason_case("4. 命中率 0%", LAYOUTS, 459, False, "命中率都低于 60%",
                     True)
allok &= reason_case("5. 命中率够 -> 直扫成功", LAYOUTS, 459, True, "直扫成功",
                     False)
# ★ 这一条是"0 cards in 0.8s"最可疑的成因之一:截图拿不到(窗口不见了/
#   被最小化)时 scan_fast 会**立刻**返回空,而且不走盲扫 —— 以前一句日志都不打。
allok &= reason_case("6. 基准帧截图失败 -> 立刻返回空", LAYOUTS, 459, True,
                     "基准帧截图失败", False, capture_none=True)

print()
print("=" * 82)
print("★ 光标没能落到目标点时,不应该被误判成「用户在操作鼠标」")
print("=" * 82)
# 实机症状:扫描 0.8 秒就返回 0 张牌。成因之一是 Windows 把光标裁剪回屏幕内,
# SetCursorPos 没落到请求点,于是 user_took_over() 把这点误差当成用户动了鼠标,
# 在第一个探针就中止。修法:_move 按【实际落点】记账。
sc = hsv.HandScannerV2(0, {})
sc._last_cursor = None
with mock.patch.object(hsv, "client_to_screen", lambda h, x, y: (x, y)), \
     mock.patch.object(hsv, "set_cursor_checked", lambda x, y: (x + 300, y)):
    sc._move(100, 200)
clamped_ok = (sc._last_cursor == (400, 200) and sc.cursor_clamped == 1)
allok &= clamped_ok
print(f"  {'OK ' if clamped_ok else 'FAIL'} 光标被裁剪 -> 按实际落点记账 "
      f"_last_cursor={sc._last_cursor} cursor_clamped={sc.cursor_clamped}")
with mock.patch.object(hsv, "client_to_screen", lambda h, x, y: (x, y)), \
     mock.patch.object(hsv, "set_cursor_checked", lambda x, y: (x, y)):
    sc._move(100, 200)
ok2 = (sc._last_cursor == (100, 200) and sc.cursor_clamped == 1)
allok &= ok2
print(f"  {'OK ' if ok2 else 'FAIL'} 光标正常落点 -> 不计数 "
      f"_last_cursor={sc._last_cursor} cursor_clamped={sc.cursor_clamped}")

print()
print("=" * 82)
print("★ 惰性扫描选「哪条布局」:两个边缘都要解释得通(2026-09-13 第十个会话)")
print("  布局表里每条都记了 left_edge 和 right_edge,而选条目以前只看左边缘。")
print("  实测(src/edge_probe.py):扇形是**居中**的 -> 两个边缘是同一个张数的")
print("  两次独立测量 -> 「两边都对得上」硬得多;而容差 22 与相邻张数的间距")
print("  (6 张 390 vs 7 张 368 = 22px)一样大,只看一边就是在重叠区里抛硬币。")
print("=" * 82)
# 真实的 1~9 张布局表(取自 config/hand_layout.json 的实测值)
REAL = {
    "570": {"left_edge": 570, "right_edge": 735, "count": 1, "probes": [645]},
    "536": {"left_edge": 536, "right_edge": 772, "count": 2, "probes": [568, 677]},
    "498": {"left_edge": 498, "right_edge": 794, "count": 3, "probes": [536, 605, 711]},
    "459": {"left_edge": 459, "right_edge": 826, "count": 4,
            "probes": [492, 570, 639, 740]},
    "421": {"left_edge": 421, "right_edge": 860, "count": 5,
            "probes": [455, 531, 602, 677, 777]},
    "390": {"left_edge": 390, "right_edge": 886, "count": 6,
            "probes": [434, 499, 566, 634, 703, 802]},
    "368": {"left_edge": 368, "right_edge": 915, "count": 7,
            "probes": [405, 466, 530, 596, 660, 727, 821]},
    "357": {"left_edge": 357, "right_edge": 925, "count": 8,
            "probes": [388, 443, 503, 562, 620, 681, 744, 827]},
    "358": {"left_edge": 358, "right_edge": 915, "count": 9,
            "probes": [389, 437, 483, 539, 589, 636, 690, 740, 829]},
}


def pick_entry(layouts, left, right):
    """跑真实的 `find_playable` 选条目那一段(只关心它挑了哪条)。"""
    sc = hsv.HandScannerV2(0, {})
    sc._load_layouts = lambda: layouts
    sc._move = lambda x, y: None
    sc.last_probe_seen = []
    with mock.patch.object(hsv, "capture_client_bgr", lambda h: FRAME.copy()), \
         mock.patch.object(hsv, "diff_bbox", lambda a, b: None), \
         mock.patch.object(hsv.time, "sleep", lambda s: None):
        sc.find_playable([9], edge=left, right=right, debug=False)
    lay = sc.last_layout or {}
    return lay.get("count"), lay


# ① 两边都量对了 -> 6 张那一帧(base.png 的实测值:L390 R868)
n, lay = pick_entry(REAL, 390, 868)
ok = (n == 6)
allok &= ok
print(f"  {'OK ' if ok else 'FAIL'} 量到 L390/R868(真实 6 张)-> 选中 {n} 张  "
      f"残差 L{lay.get('res_l')}/R{lay.get('res_r')}")

# ② ★ 左边缘模糊、右边缘说了算:L=370(6 张差 20、7 张差 2,老规则选 7)
n_old, _ = pick_entry({k: v for k, v in REAL.items() if k != "357"}, 370, 886)
n_new, lay = pick_entry(REAL, 370, 886)
print(f"     边界情形 L370/R886 -> 选中 {n_new} 张(残差 "
      f"L{lay.get('res_l')}/R{lay.get('res_r')};次选 {lay.get('runner')})")
ok = (n_new == 6)
allok &= ok
print(f"  {'OK ' if ok else 'FAIL'} 左边缘偏向 7 张、右边缘指向 6 张 -> 该选 6 张")

# ③ 右边缘测量坏掉(实测污染过的背景参考区会给出 R=1099)-> 退回只看左边缘
n, lay = pick_entry(REAL, 390, 1099)
ok = (n == 6)
allok &= ok
print(f"  {'OK ' if ok else 'FAIL'} 右边缘 1099(坏测量)-> 仍按左边缘选 {n} 张")

# ④ 8 张 vs 9 张:左边缘只差 1px,靠右边缘(925 vs 915)分开
n8, _ = pick_entry(REAL, 357, 925)
n9, _ = pick_entry(REAL, 358, 915)
ok = (n8 == 8 and n9 == 9)
allok &= ok
print(f"  {'OK ' if ok else 'FAIL'} 8/9 张只靠左边缘分不开 -> L357/R925={n8} 张、"
      f"L358/R915={n9} 张")

# ⑤ A/B 开关关掉 -> 回到"只看左边缘"的老行为(L370 -> 7 张)
_old_switch = hsv.LAYOUT_MATCH_BOTH_EDGES
hsv.LAYOUT_MATCH_BOTH_EDGES = False
n_ab, _ = pick_entry(REAL, 370, 886)
hsv.LAYOUT_MATCH_BOTH_EDGES = _old_switch
ok = (n_ab == 7)
allok &= ok
print(f"  {'OK ' if ok else 'FAIL'} 开关关掉(老行为) L370 -> {n_ab} 张(该是 7)")

print()
print("=" * 82)
print("★ 手牌记忆:该跳的探针真的没悬停吗?(2026-09-13 第十个会话)")
print("  这一段把 `_memory_path` 整条路用替身跑一遍 —— 它是**唯一会动鼠标**的新代码,")
print("  而且是【跳过悬停】的地方:跳错了就会少出一个单位,校验漏了就会照旧记忆乱拖。")
print("=" * 82)
import hand_memory as hmem  # noqa: E402

PROBES6 = [434, 499, 566, 634, 703, 802]


def memory_run(mem_cards, classify_map, budget=3, count=6, left=390, right=886):
    """
    用替身跑一次 `find_playable`(带手牌记忆)。返回 (cards, cost, 悬停过的探针, scanner)。
    `classify_map`: {探针 x: 识别结果 dict}
    """
    sc = hsv.HandScannerV2(0, {})
    entry = {"left_edge": left, "right_edge": right, "count": count,
             "probes": list(PROBES6[:count])}
    sc._load_layouts = lambda: {"k": entry}
    sc.memory = hmem.HandMemory()
    sc.memory.cards = list(mem_cards)
    sc.memory.valid = True
    hovered = []

    def fake_move(x, y):
        hovered.append(x)

    def fake_classify(region, y0=0, box=None, frame=None, debug=False):
        return dict(classify_map.get(hovered[-1], {"name": None, "type": None,
                                                  "cost": None}))

    sc._classify = fake_classify
    with mock.patch.object(hsv, "capture_client_bgr", lambda h: FRAME.copy()), \
         mock.patch.object(hsv, "diff_bbox", lambda a, b: (100, 100, 400, 400)), \
         mock.patch.object(hsv.HandScannerV2, "_move",
                           lambda self, x, y: fake_move(x, y)), \
         mock.patch.object(hsv.time, "sleep", lambda s: None):
        cards, cost = sc.find_playable([budget], edge=left, right=right)
    probed = [x for x in hovered if x in PROBES6[:count]]
    return cards, cost, probed, sc


def C2(name, cond, extra=""):
    global allok
    allok &= bool(cond)
    print(f"  {'OK ' if cond else 'FAIL'} {name}{('  ' + str(extra)) if extra else ''}")


# 记忆(下标 0..5):第 1 张 1 费步兵能出;第 2 张指令、第 3 张 6 费、第 4 张未知、其余 8 费
MEM = [{"name": "步兵第 89 团", "type": "infantry", "cost": 1},
       {"name": "鹰爪", "type": "order", "cost": 3},
       {"name": "Fw 190 A 百舌鸟", "type": "fighter", "cost": 6},
       None,
       {"name": "虎式坦克 H 型", "type": "tank", "cost": 8},
       {"name": "88 毫米高射炮", "type": "artillery", "cost": 6}]
REAL = {434: {"name": "步兵第 89 团", "type": "infantry", "cost": 1},
        499: {"name": "鹰爪", "type": "order", "cost": 3},
        566: {"name": "Fw 190 A 百鹤鸟", "type": "fighter", "cost": 6},
        634: {"name": "三号突击炮 F 型", "type": "tank", "cost": 2},
        703: {"name": "虎式坦克 H 型", "type": "tank", "cost": 8},
        802: {"name": "88 毫米高射炮", "type": "artillery", "cost": 6}}

# ① 记忆说第 1 张就出得起 -> 只该看两张:身份未知的那张 + 要出的那张(校验搭在它身上)
cards, cost, probed, sc = memory_run(MEM, REAL, budget=1)
print(f"    预算 1: 悬停过 {probed}(6 个探针里;未知的下标 3 必须探,校验搭在第 1 张上)")
C2("6 个探针只看了 2 个(其余 4 个真的没悬停)",
  sorted(probed) == [434, 634], probed)
C2("返回的就是那一张", cards and cards[0]["name"] == "步兵第 89 团", cards)

# ② 记忆说"全都出不起" -> 只悬停 1 个(校验点),其余一个都不碰
ALL_BIG = [{"name": f"大牌{i}", "type": "tank", "cost": 8} for i in range(6)]
real_big = {x: {"name": f"大牌{i}", "type": "tank", "cost": 8}
            for i, x in enumerate(PROBES6)}
cards, cost, probed, sc = memory_run(ALL_BIG, real_big, budget=2)
print(f"    全出不起: 悬停过 {probed} -> 省下 {6 - len(probed)} 个探针")
C2("6 个探针只悬停 1 个(校验点)", len(probed) == 1, probed)
C2("没找到可出的牌(结论和老实扫一样)", cards == [], cards)
C2("省下的探针数记进了统计", sc.memory.stats["skipped"] == 5,
   sc.memory.stats["skipped"])

# ③ ★ 校验点读到的东西和记忆不符(次序整体错位)-> 记忆当场失效 + **退回老实扫**
shifted = {x: dict(v) for x, v in REAL.items()}
shifted[434] = {"name": "铁锤", "type": "order", "cost": 3}     # 校验点对不上
cards, cost, probed, sc = memory_run(MEM, shifted, budget=1)
print(f"    校验失败: 悬停过 {probed};记忆 valid={sc.memory.valid}")
C2("校验失败 -> 记忆失效", sc.memory.valid is False)
C2("退回老实扫(每个探针都看过,不是只跳着看)",
   set(probed) >= {434, 499, 566, 634}, probed)
C2("校验失败计进 verify_bad", sc.memory.stats["verify_bad"] == 1, sc.memory.stats)

# ④ 记忆里身份未知的那些**必须去探**(否则永远补不上)
mem_unknown = [None] + MEM[1:]
cards, cost, probed, sc = memory_run(mem_unknown, REAL, budget=2)
print(f"    第 1 张身份未知: 悬停过 {probed}")
C2("下标 0 必须被探(记忆里是 None)", 434 in probed, probed)

print()
print("=" * 82)
print("全部通过" if allok else "存在失败项")
print("=" * 82)
sys.exit(0 if allok else 1)
