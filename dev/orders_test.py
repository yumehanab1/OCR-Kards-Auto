# -*- coding: utf-8 -*-
"""
orders_test.py - 指令卡支持的**离线**用例(不需要游戏、不需要窗口)。

只考三件事(其余是实机的事):
  ① `config/order_plays.json` 载得进来,而且**张数/分档和文档对得上**
     (表坏了或没随包发,引擎会"悄悄不打指令" —— 这正是这个项目栽过三次的形状);
  ② `orders.playable()` 的**真值表** —— 放行单位 + 「可直接打出」的指令,
     其它(需要目标 / 抉择 / 黑名单 / 反制 / 类型未知)**一律不放行**(fail-closed);
  ③ scanner 和 turn_engine **问的是同一个函数**(判据只有一处)。

用法:
  .venv\\Scripts\\python.exe dev\\orders_test.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import deploy        # noqa: E402
import hand_scanner_v2 as hs   # noqa: E402
import orders        # noqa: E402

ALLOK = True


def C(label, cond, extra=""):
    global ALLOK
    ALLOK &= bool(cond)
    print(f"  {'OK ' if cond else 'FAIL'} {label}" + (f"   {extra}" if extra else ""))


print("=" * 86)
print("① 指令卡表载得进来吗(载不进来 = 引擎悄悄不打指令,不会报错)")
print("=" * 86)
orders._CARDS = None          # 强制重新载入
print("  " + orders.status())
C("表载入了(不是 0 张)", len(orders._CARDS or {}) > 600,
  f"实得 {len(orders._CARDS or {})} 张")
C("status() 里能看到分档(说明 JSON 结构没变)",
  all(k in orders.status() for k in ("可直接打出", "需要目标", "抉择", "黑名单")))
C("默认开着(PLAY_ORDERS=True)", orders.PLAY_ORDERS is True)

print()
print("=" * 86)
print("② playable() 真值表:只放行「单位」和「可直接打出的指令」")
print("=" * 86)
CASES = [
    ("infantry", "步兵第 89 团", True, "单位 -> 放行(能不能付得起由预算另判)"),
    ("tank", "T-70", True, "单位 -> 放行"),
    ("fighter", "喷火 Mk Ia", True, "单位 -> 放行"),
    ("order", None, False, "指令但名字没读出来 -> **不放行**(fail-closed)"),
    ("counter", "复仇", False, "反制 -> 不放行"),
    ("countermeasure", "无心漫谈", False, "反制(另一种拼法)-> 不放行"),
    (None, None, False, "类型都没读出来 -> 不放行"),
    ("order", "这张卡卡库里没有", False, "指令但不在表里 -> 不放行"),
]
for ctype, name, want, why in CASES:
    got = orders.playable(ctype, name)
    C(f"{why}", got == want, f"playable({ctype!r}, {name!r}) = {got}")

# 从表里各挑一张真卡来考(不写死卡名,免得卡库一更新用例就红)
by_mode = {}
for nm, rec in (orders._CARDS or {}).items():
    by_mode.setdefault(rec["mode"], nm)
C("表里确实有「可直接打出」的指令", orders.MODE_DIRECT in by_mode,
  by_mode.get(orders.MODE_DIRECT, ""))
if orders.MODE_DIRECT in by_mode:
    nm = by_mode[orders.MODE_DIRECT]
    C(f"direct 的指令放行:{nm}", orders.playable("order", nm) is True)
for mode, label in ((orders.MODE_TARGET, "需要目标"), (orders.MODE_CHOICE, "抉择"),
                    (orders.MODE_BLACKLIST, "黑名单"), (orders.MODE_UNSUPPORTED, "不支持")):
    nm = by_mode.get(mode)
    if nm:
        C(f"{label}的指令**不**放行:{nm}", orders.playable("order", nm) is False)

print()
print("=" * 86)
print("③ 判据只有一处:scanner 问的就是 orders.playable()")
print("=" * 86)
for ctype, name, want, _why in CASES:
    got = hs.is_playable(ctype, name)
    C(f"hand_scanner_v2.is_playable({ctype!r}) == orders.playable()",
      got == orders.playable(ctype, name), f"实得 {got}")
C("on-scanner 的放行集合里没有任何黑名单卡",
  not any(orders.is_blacklisted(n) and hs.is_playable("order", n)
          for n in (orders._CARDS or {})))

print()
print("=" * 86)
print("④ A/B 总开关:PLAY_ORDERS=False 要能一句话退回老行为")
print("=" * 86)
nm_direct = by_mode.get(orders.MODE_DIRECT, "")
try:
    orders.PLAY_ORDERS = False
    C("关掉之后指令一律不放行", not hs.is_playable("order", nm_direct))
    C("关掉之后**单位照旧放行**(别把单位一起关掉)",
      hs.is_playable("infantry", "步兵第 89 团"))
finally:
    orders.PLAY_ORDERS = True
C("打开之后又放行了", hs.is_playable("order", nm_direct))

print()
print("=" * 86)
print("⑤ 兜底落点(支援线满 4 个单位时指令还得有地方落)")
print("=" * 86)
x, y = deploy.fallback_drop()
C(f"兜底落点 ({x},{y}) 在允许范围内",
  deploy.DROP_X_LIMIT[0] <= x <= deploy.DROP_X_LIMIT[1]
  and deploy.DROP_Y_LIMIT[0] <= y <= deploy.DROP_Y_LIMIT[1])
# ★ 什么时候真的需要兜底:整行挤满(每个候选都贴着某张卡)时 `slot_candidates` 会给空列表。
#   (实测"支援线满 4 个单位"**不一定**空 —— 左右两侧通常还留得下候选点,
#    所以这一档其实是"行读错了/挤到极限"时的保险,不是常见路径。)
crowded = list(range(300, 991, 70))
C("整行挤满时 slot_candidates 返回空列表 -> 引擎那边必须有兜底",
  deploy.slot_candidates(crowded, deploy.FALLBACK_DROP_Y) == [],
  f"occupied={len(crowded)} 个点")
C("而指令在这种情况下仍有落点(不依赖空槽位)",
  deploy.fallback_drop() is not None)

print()
print("=" * 86)
print("全部通过" if ALLOK else "存在失败项")
print("=" * 86)
sys.exit(0 if ALLOK else 1)
