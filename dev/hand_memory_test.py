"""
hand_memory_test.py - 离线验证"手牌记忆"的次序对齐与 fail-open(不需要游戏)。

手牌记忆要成立,靠的是三条**只有玩家能确认**的规则(见 hand_memory.py 的文档):
  1. 新抽的牌**一定在最右**;
  2. 我们出掉的那张,是**我们知道自己出的是第几张**;
  3. 除此之外张数变化(对手让你弃牌等)= **不可信,必须失效**。

这个文件就用脚本化的"一手牌的历史"把这三条 + 两条纪律钉住:
  · **校验点抓整体错位**(弃一张+抽一张,张数不变,但次序整体平移);
  · **真要出的那张必须当帧确认**(`_same_identity`:名字/类型/费用对不上就是不同)。

用法:
  .venv\\Scripts\\python.exe src\\hand_memory_test.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import hand_memory
import hand_scanner_v2 as hsv
from hand_memory import HandMemory

DEPLOYABLE = {"infantry", "tank", "fighter", "bomber", "artillery"}
allok = True
logs = []


def C(name, cond, extra=""):
    global allok
    allok &= bool(cond)
    print(f"  {'OK ' if cond else 'FAIL'} {name}{('  ' + str(extra)) if extra else ''}")


def card(name, type_, cost):
    return {"name": name, "type": type_, "cost": cost}


def new_mem():
    logs.clear()
    m = HandMemory(log=lambda s: logs.append(s))
    m.cards = [card("步兵第 89 团", "infantry", 1),
               card("鹰爪", "order", 3),
               card("Fw 190 A 百舌鸟", "fighter", 6),
               None]                      # 第 4 张:知道有那么一张,但身份没读到
    m.valid = True
    m.reason = "测试用"
    return m


print("=" * 82)
print("CASE 1: 计划 —— 该跳的跳、该探的探、便宜的先出、留一个校验点")
print("=" * 82)
m = new_mem()
plan = m.plan(budget=3, deployable=DEPLOYABLE)
print(f"    预算 3: probe={plan['probe']} skip={plan['skip']} "
      f"targets={plan['targets']} verify={plan['verify']} saved={plan['saved']}")
C("身份未知的第 4 张必须去探", plan["probe"] == [3], plan["probe"])
C("出不起的百舌鸟(6)被跳过", 2 in plan["skip"], plan["skip"])
C("能出的两张都进了候选(按费用排)", plan["targets"] == [(0, 1)], plan["targets"])
C("校验点落在'能出的'那张上 —— 那张本来就要悬停,校验是**免费**的",
  plan["verify"] == 0 and plan["saved"] == len(plan["skip"]), plan)

# 预算 6:两张都能出,候选要按"便宜的先出"排
m = new_mem()
plan = m.plan(budget=6, deployable=DEPLOYABLE)
print(f"    预算 6: targets={plan['targets']}(第 1 张 1 费、第 3 张 6 费)")
C("便宜的先出", plan["targets"] == [(0, 1), (2, 6)], plan["targets"])
C("没有可跳的就不硬用记忆(省不到东西)",
  m.plan(budget=9, deployable=DEPLOYABLE)["saved"] <= 1)

# 全是"出不起"的一手:这是最贵的那种扫描(6 个探针全扫完约 12~16s)
m = HandMemory(log=lambda s: logs.append(s))
m.cards = [card(f"大牌{i}", "tank", 8) for i in range(6)]
m.valid = True
plan = m.plan(budget=2, deployable=DEPLOYABLE)
print(f"    全出不起(6 张): skip={plan['skip']} verify={plan['verify']} "
      f"saved={plan['saved']}(约 {plan['saved'] * m.PROBE_COST_S:.0f}s)")
C("6 张全跳、只留 1 次校验 -> 省 5 个探针", plan["saved"] == 5, plan["saved"])

print()
print("=" * 82)
print("CASE 2b: ★ 第一次扫描必须**当场铺格子**再填(实机踩过:不铺就永远记不上)")
print("        19:00 那一局日志里一条 `[记忆]` 都没有 —— 根因就是这里")
print("=" * 82)
m = HandMemory(log=lambda s: logs.append(s))
m.note_scan({0: card("步兵第 89 团", "infantry", 1),
             2: card("Fw 190 A 百舌鸟", "fighter", 6)}, 5)
print(f"    第一次扫到 2 张(共 5 张)-> cards="
      f"{[(c or {}).get('name') for c in m.cards]}")
C("按张数铺出 5 个格子", len(m.cards) == 5, m.cards)
C("探到的两张填进对应下标",
  m.cards[0] and m.cards[0]["name"] == "步兵第 89 团" and m.cards[2])
C("没探到的下标保持 None(身份未知 -> 下一轮会去探它)",
  m.cards[1] is None and m.cards[3] is None and m.cards[4] is None)
C("铺完之后 ok_for 可用", m.ok_for(5) is True)
# 下一轮:记忆里"出不起的"能跳过了
plan = m.plan(budget=1, deployable=DEPLOYABLE)
print(f"    预算 1: skip={plan['skip']} probe={plan['probe']} saved={plan['saved']}")
C("已知出不起的百舌鸟(6 费)被跳过", 2 in plan["skip"], plan["skip"])
C("未知的两张必须去探", set(plan["probe"]) >= {1, 3, 4}, plan["probe"])
C("省下的 = 被跳过的那些(校验免费,不占名额)", plan["saved"] == 1, plan["saved"])
# ★ 而"一张能出的都没有"时,校验只能落在要跳过的那张上 -> 省 1 个名额
m3 = HandMemory(log=lambda s: logs.append(s))
m3.note_scan({i: card(f"大牌{i}", "tank", 8) for i in range(3)}, 3)
plan3 = m3.plan(budget=1, deployable=DEPLOYABLE)
print(f"    3 张全出不起: skip={plan3['skip']} verify={plan3['verify']} "
      f"saved={plan3['saved']}(= 3 张 - 1 次校验)")
C("全出不起时省 N-1 个", plan3["saved"] == 2, plan3["saved"])
# ★ 但只要还有一张"能出的",校验就落在它身上(那张本来就要悬停)-> 免费
m2 = HandMemory(log=lambda s: logs.append(s))
m2.note_scan({0: card("步兵第 89 团", "infantry", 1),
              1: card("鹰爪", "order", 3),
              2: card("Fw 190 A 百舌鸟", "fighter", 6)}, 3)
plan = m2.plan(budget=3, deployable=DEPLOYABLE)
print(f"    1 张能出 + 2 张出不起: skip={plan['skip']} targets={plan['targets']} "
      f"verify={plan['verify']} saved={plan['saved']}")
C("校验落在'能出的'那张上(本来就要悬停)-> 3 张里挑 2 个的活只花 1 次悬停",
  plan["verify"] == 0 and plan["saved"] == 2, plan)

print()
print("=" * 82)
print("CASE 2: 次序对齐 —— 抽牌补右端 / 出牌删自己那张 / 其它一律失效")
print("=" * 82)
m = new_mem()
C("张数一样 -> 可用", m.ok_for(4) is True)
C("回合开始抽 1 张 -> 右端补 None(其余身份不变)",
  m.ok_for(5, allow_draw=True) and m.cards[-1] is None
  and m.cards[0]["name"] == "步兵第 89 团")
C("同一回合再抽(allow_draw=False)-> 不许补,判失效", m.ok_for(6) is False)
C("失效会写日志", any("张数对不上" in s for s in logs), logs[-1:])

m = new_mem()
m.note_played(1)                     # 出掉第 2 张(鹰爪)
print(f"    出掉第 2 张后: {[ (c or {}).get('name') for c in m.cards ]}")
C("出牌 = 从记忆里删掉那一张(次序左移)",
  [(c or {}).get("name") for c in m.cards]
  == ["步兵第 89 团", "Fw 190 A 百舌鸟", None])
C("删完张数正好对上 -> 下一轮可用", m.ok_for(3) is True)

m = new_mem()
m.invalidate("测试")
C("失效后 ok_for 一律 False(fail-open)", m.ok_for(4) is False and m.ok_for(4, True) is False)

print()
print("=" * 82)
print("CASE 3: ★ 校验点能抓住「整体错位」(弃一张 + 抽一张,张数不变)")
print("=" * 82)
# 记忆: [A B C D];真实局面: 对手让你弃掉 A、回合开始又抽了 E -> [B C D E]
m = new_mem()
shifted = [card("鹰爪", "order", 3), card("Fw 190 A 百舌鸟", "fighter", 6),
           None, card("新抽的", "infantry", 2)]
for i, real in enumerate(shifted):
    mem = m.cards[i] if i < len(m.cards) else None
    ok = hsv._same_identity(mem, real)
    print(f"    第 {i + 1} 张:记忆={mem and mem.get('name')!r:<18} "
          f"真实={real and real.get('name')!r:<16} -> 同一个人? {ok}")
C("错位后**每一个**下标的身份都不对(所以校验一个点就够)",
  all(not hsv._same_identity(m.cards[i], shifted[i]) for i in range(4)))

print()
print("=" * 82)
print("CASE 4: ★ 真要出的那张必须当帧确认 —— _same_identity 的判据")
print("=" * 82)
cases = [
    ("名字都对上", card("鹰爪", "order", 3), card("鹰爪", "order", 3), True),
    ("名字不同", card("鹰爪", "order", 3), card("铁锤", "order", 3), False),
    # ★★★ 2026-09-13 深夜改(**用户实测**"明明有记忆却隔一两回合整手重扫"):
    #   记忆那边**只有类型**(卡名没读到)—— 这**不是"它变了"的证据**,
    #   退回比类型。以前这里判"不同",于是那种条目每次被校验点抽到都失效。
    ("只有一边有名字 + 类型相同 -> 同一个(名字是没读到,不是变了)",
     {"name": None, "type": "order", "cost": None},
     {"name": "鹰爪", "type": "order", "cost": 3}, True),
    ("只有一边有名字 + 类型不同 -> 不同(真漂移照样抓)",
     {"name": None, "type": "tank", "cost": None},
     {"name": "鹰爪", "type": "order", "cost": 3}, False),
    ("只有一边有名字 + 类型相同但费用明确不同 -> 不同",
     {"name": None, "type": "tank", "cost": 3},
     {"name": "三号坦克 H 型", "type": "tank", "cost": 8}, False),
    ("都没名字:类型+费用都对", {"name": None, "type": "tank", "cost": 3},
     {"name": None, "type": "tank", "cost": 3}, True),
    ("都没名字:费用不同", {"name": None, "type": "tank", "cost": 3},
     {"name": None, "type": "tank", "cost": 2}, False),
    ("类型拼法不同(counter/countermeasure)-> 保守判不同",
     {"name": None, "type": "counter", "cost": 2},
     {"name": None, "type": "countermeasure", "cost": 2}, False),
    ("记忆是 None(不知道)-> 不同", None, card("鹰爪", "order", 3), False),
]
for name, mem, info, want in cases:
    got = hsv._same_identity(mem, info)
    C(name, got == want, f"得到 {got}")

print()
print("=" * 82)
print("CASE 5: 统计口径 —— 「跳过」要算成省下的秒数,而且只算**真跳过**的")
print("=" * 82)
m = new_mem()
plan = m.plan(budget=3, deployable=DEPLOYABLE)
m.note_plan_used(plan["saved"], verify_ok=True)
print(f"    {m.describe()}")
C("跳过数记进了统计", m.stats["skipped"] == plan["saved"], m.stats)
C("省下的秒数 = 跳过数 × 单个探针成本",
  abs(m.stats["saved_s"] - plan["saved"] * hand_memory.HandMemory.PROBE_COST_S) < 1e-6)
C("校验通过计入 verify_ok", m.stats["verify_ok"] == 1 and m.stats["verify_bad"] == 0)
m.note_verify_bad()
C("校验失败单独计数(实机要靠它看出'记忆错位过')", m.stats["verify_bad"] == 1)

print()
print("=" * 82)
print("CASE 6: ★★★ 失效之后记忆必须能**活过来**(2026-09-13 深夜实机抓到的 bug)")
print("        实机账(20:50 那一局):20:56:27 第一次失效之后,连着 6 次")
print("        「扫描后发现张数变了」、**命中 0 次**(在那之前命中 5 次)——")
print("        因为 `invalidate()` 只把 valid 置假、保留旧 `cards`,而 `note_scan`")
print("        只在 cards **为空**时才重新铺格子 -> 张数一旦变过就整局再也用不上。")
print("=" * 82)
m = new_mem()                                   # 4 张,身份都认得
C("前提:这份记忆本来是好的", m.valid and m.ok_for(4) is True)
m.invalidate("实机:出牌之后扇形还没重排,量到的张数不对")
C("失效后 cards 还在(旧身份)—— 这正是那个坑的温床", bool(m.cards), len(m.cards))
# ★ 失效之后的第一次扫描:张数和旧记忆**不一样** -> 必须重新铺格子,而不是又失效一次
m.note_scan({0: card("步兵第 89 团", "infantry", 1),
             1: card("鹰爪", "order", 3)}, 2)
print(f"    失效后重扫(2 张):valid={m.valid} 记忆={[ (c or {}).get('name') for c in m.cards ]}")
C("★ 失效后重新铺成**当前的**张数(2 张),而不是又报一次失效", len(m.cards) == 2)
C("★ 记忆当场恢复可用(不再整局躺平)", m.valid is True and m.ok_for(2) is True)
C("探到的身份写回去了", (m.cards[0] or {}).get("name") == "步兵第 89 团")
# 而"同一份有效记忆碰到不同张数"仍然必须失效(保守那条不许被这次修改破坏)
m2 = new_mem()
m2.note_scan({0: card("A", "infantry", 1)}, 9)   # 有效记忆 -> 张数不同
C("有效记忆 + 张数不同 -> 照旧失效(fail-open 那条没被破坏)",
  m2.valid is False, m2.reason)

print()
print("=" * 82)
print("全部通过" if allok else "存在失败项")
print("=" * 82)
sys.exit(0 if allok else 1)
