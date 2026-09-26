# -*- coding: utf-8 -*-
"""
orders_test.py - 指令卡支持的**离线**用例(不需要游戏、不需要窗口)。

只考这几件事(其余是实机的事):
  ① `config/order_plays.json` 载得进来,而且**张数/分档和文档对得上**
     (表坏了或没随包发,引擎会"悄悄不打指令" —— 这正是这个项目栽过三次的形状);
  ② `orders.playable()` 的**真值表** —— 放行单位 + 「可直接打出」的指令,
     其它(需要目标 / 抉择 / 黑名单 / 反制 / 类型未知)**一律不放行**(fail-closed);
  ③ scanner 和 turn_engine **问的是同一个函数**(判据只有一处);
  ③.5 ★★ 2026-09-21 用户决定「kind5进黑名单」:`KIND5_AS_BLACKLIST` 那条策略层
     (`is_blacklisted()` 为真 -> 引擎会给"别带这张"的提示;`playable()` 不放行;
     A/B 翻 False 时退回旧行为);
  ③.6 `status()` 那行启动日志的**每个数字都和逐卡现算一致**(账要平 —— 别出现
     "需要目标 N 个但其中若干实际不打"这种对不上的账)。

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
for mode, label in ((orders.MODE_BLACKLIST, "黑名单"),
                    (orders.MODE_UNSUPPORTED, "不支持")):
    nm = by_mode.get(mode)
    if nm:
        C(f"{label}的指令**不**放行:{nm}", orders.playable("order", nm) is False)

_three = [nm for nm in (orders._CARDS or {}) if orders.is_three_order(nm)]
C("目标码 7 中非两步的三选一共 19 个卡名", len(_three) == 19)
C("三选一指令全部放行", all(orders.playable("order", n) for n in _three))
C("三选一的两步卡仍不放行",
  all(not orders.playable("order", n) for n, r in (orders._CARDS or {}).items()
      if r["mode"] == orders.MODE_TARGET and r["kind"] == "7" and r["follow"]))
try:
    orders.PLAY_THREE_ORDERS = False
    C("三选一开关关闭时整档不放行",
      not any(orders.playable("order", n) for n in _three))
finally:
    orders.PLAY_THREE_ORDERS = True

_marked = [nm for nm in (orders._CARDS or {}) if orders.choice_spec(nm)]
_unmarked = [nm for nm in (orders._CARDS or {})
             if orders.is_choice_card(nm) and not orders.choice_spec(nm)]
C("明确标左/右的双牌抉择共 27 个卡名", len(_marked) == 27)
C("标选边的抉择全部放行", all(orders.playable("order", n) for n in _marked))
C("未标选边的抉择共 16 个卡名", len(_unmarked) == 16)
C("未标选边的抉择全部是黑名单,且不放行",
  all(orders.is_blacklisted(n) and not orders.playable("order", n) for n in _unmarked))
C("呼叫殖民地选左", orders.choice_spec("呼叫殖民地").get("rows") == "1")
try:
    orders.PLAY_CHOICES = False
    C("独立开关关闭时抉择全部不放行",
      not any(orders.playable("order", n) for n in _marked))
    C("关闭抉择不影响 direct", orders.playable("order", by_mode[orders.MODE_DIRECT]))
finally:
    orders.PLAY_CHOICES = True

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
print("③.5 ★★ kind 5「选择一张手牌」归黑名单(用户 2026-09-21「kind5进黑名单」)")
print("=" * 86)
# ★ 依据:用户 2026-09-21 的决定。为什么不改 config/order_plays.json ——
#   那个文件是 dev/order_plan.py 从规格文档生成的,手改会被下次重新生成冲掉;
#   所以策略层放在 orders.py(`KIND5_AS_BLACKLIST`)。
_k5 = [nm for nm, r in (orders._CARDS or {}).items()
       if r["mode"] == orders.MODE_TARGET and (r.get("kind") or "") == "5"]
print(f"  表里 kind 5 = {len(_k5)} 个卡名:{_k5}")
C("开关默认开着", orders.KIND5_AS_BLACKLIST is True)
C(f"kind 5 全部 {len(_k5)} 个:is_blacklisted() 为真(引擎的'别带这张'提示靠它)",
  _k5 and all(orders.is_blacklisted(n) for n in _k5),
  str([n for n in _k5 if not orders.is_blacklisted(n)]))
C("kind 5 全部:playable() 不放行",
  not any(orders.playable("order", n) for n in _k5),
  str([n for n in _k5 if orders.playable("order", n)]))
C("target_refuse_reason() 说得出原因,而且点名是黑名单那条决定",
  all("黑名单" in orders.target_refuse_reason(n) for n in _k5),
  orders.target_refuse_reason(_k5[0]) if _k5 else "")
C("非 kind 5 的 target(kind 1/2/3/4/6)不许被误判成黑名单",
  not any(orders.is_blacklisted(n) for n, r in (orders._CARDS or {}).items()
          if r["mode"] == orders.MODE_TARGET and (r.get("kind") or "") != "5"),
  "")
C("真正表里的黑名单卡照旧是黑名单(这条判据没被改坏)",
  any(orders.is_blacklisted(n) for n, r in (orders._CARDS or {}).items()
      if r["mode"] == orders.MODE_BLACKLIST))
# ★ A/B:翻 False -> 退回旧行为(kind 5 回到「需要目标」那一档)
try:
    orders.KIND5_AS_BLACKLIST = False
    C("KIND5_AS_BLACKLIST=False:kind 5 不再是黑名单",
      not any(orders.is_blacklisted(n) for n in _k5), "")
    _one = [n for n in _k5 if not (orders.rec_of(n).get("follow") or "").strip()]
    C("  不带 follow 的那几张又放行了(回到 2026-09-21 之前)",
      _one and all(orders.playable("order", n) for n in _one),
      f"放行 {len(_one)} 张")
    C("  target_kinds_ok() 里也把 5 加回来了(判据只有一处)",
      "5" in orders.target_kinds_ok(), str(orders.target_kinds_ok()))
    C("  status() 跟着变(不再把 kind 5 算进黑名单)",
      "+ kind 5" not in orders.status(), orders.status()[:70] + "…")
finally:
    orders.KIND5_AS_BLACKLIST = True
C("还原之后 kind 5 又是黑名单", all(orders.is_blacklisted(n) for n in _k5), "")

print()
print("=" * 86)
print("③.6 status() 那行日志:每个数字都要和**逐卡现算**的结果一致(账要平)")
print("=" * 86)
# ★ 这里只数 `orders` 现成的判定(`_target_gate()` / `is_blacklisted()`),不复制一份
#   逻辑 —— 判据只有一处,用例负责"对账"。
_st = orders.status()
print("  " + _st)
_tgt = [r for r in (orders._CARDS or {}).values() if r["mode"] == orders.MODE_TARGET]
_ok_n = sum(1 for r in _tgt if orders._target_gate(r)[0])
_bl_n = sum(1 for n in (orders._CARDS or {}) if orders.is_blacklisted(n))
_tbl_bl = sum(1 for r in (orders._CARDS or {}).values() if r["mode"] == orders.MODE_BLACKLIST)
_dir_n = sum(1 for r in (orders._CARDS or {}).values() if r["mode"] == orders.MODE_DIRECT)
_k5_n = len(_k5)
C(f"「需要目标 {len(_tgt)} 个卡名」对得上", f"需要目标 {len(_tgt)} 个卡名" in _st, _st)
C(f"「其中可打 {_ok_n} 个」= `_target_gate()` 逐卡现算", f"其中可打 {_ok_n} 个" in _st, _st)
C(f"「可直接打出 {_dir_n} 个卡名」对得上", f"可直接打出 {_dir_n} 个卡名" in _st, _st)
C(f"「黑名单 {_bl_n} 个卡名」包含未标选边抉择",
  f"黑名单 {_bl_n} 个卡名" in _st
  and f"表里 {_tbl_bl} + kind 5 {_k5_n} + 未标选边抉择 {len(_unmarked)}" in _st, _st)
C("status 的抉择可打数与逐卡判据一致",
  f"其中可打 {sum(orders.is_choice(n) for n in _marked)} 个" in _st, _st)
C("status 的三选一数与逐卡判据一致",
  f"三选一 {len(_three)} 个" in _st, _st)
C("账真的平:可打 + 不可打 = 表里 target 总数",
  _ok_n + sum(1 for r in _tgt if not orders._target_gate(r)[0]) == len(_tgt),
  f"{_ok_n} + {len(_tgt) - _ok_n} = {len(_tgt)}")
C("旧口径「需要目标(kind 1~6)」不许再出现(kind 5 已经不在那一档)",
  "kind 1~6" not in _st, _st)
C("黑名单数 >= 表里的黑名单数(kind 5 只会让它变多,不会变少)",
  _bl_n >= _tbl_bl, f"{_bl_n} vs {_tbl_bl}")

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
