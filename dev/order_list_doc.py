# -*- coding: utf-8 -*-
r"""order_list_doc.py - 生成《指令卡清单:当前能打 / 黑名单 / 暂不支持》。

为什么要"生成"而不是手写一份
--------------------------
用户 2026-09-21 要一份"黑名单 + 当前可用指令"的文档。手写一份的下场是**立刻过期** ——
这个表已经改过好几轮(指令卡支持、kind5 归黑名单、kind6 全指敌方),而且以后还会改。
所以这份文档由**判据本身**生成:

    · 数据(卡名/费用/kind/rows/出处)来自 `config\order_plays.json`;
    · **分档一律问 `src\orders.py`**(`playable()` / `is_blacklisted()` / `mode_of()`):
      判据只允许有一处来源,这份文档也不许另开一套;
    · 于是"改了判据 -> 重跑一次 -> 文档自动跟上",不存在文档和代码说法不一致的情况。

★ 唯一的重复:`KIND_TEXT` / `ROW_TEXT` 是从 `dev\order_plan.py` 抄来的**人话解释**
  (那两份 dict 是"用户规格 -> 语义"的原始定义)。这里抄一份只是为了文档能自解释;
  如果哪天改了那边的语义,这里要跟着改(或者改成 import —— 但 `order_plan.py` 是脚本,
  import 会带副作用,所以这里选择抄)。

用法:
  cd /d D:\\kards-auto-repo
  set PYTHONPATH=src
  D:\\kards-auto\\python\\python.exe -u dev\\order_list_doc.py
  # 默认写 docs\\指令卡清单.md;也可以传一个输出路径
"""

from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import orders                                        # noqa: E402  判据的唯一出口

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAN = os.path.join(ROOT, "config", "order_plays.json")

#: 目标码 -> 人话(抄自 dev\order_plan.py 的 TARGET_KIND,以那里为准)
KIND_TEXT = {
    "1": "指定敌方单位(打不了总部)",
    "2": "敌方单位或总部",
    "3": "指定敌方总部",
    "4": "我方单位",
    "5": "选择一张手牌",
    "6": "随意阵营单位",
    "7": "三选一(打出后弹三张卡)",
    "8": "黑名单(不打出)",
    "X": "黑名单(不打出)",
}
#: 行码 -> 人话(抄自 ROW_KIND)
ROW_TEXT = {"a": "仅前线敌方单位", "b": "仅前线友方单位",
            "c": "仅敌方支援阵线", "d": "仅我方支援阵线"}
#: 抉择用另一套码(别和上面混):a=两个选项 b=三个选项;1/2/3=左/中/右
CHOICE_ARITY = {"a": "两个选项", "b": "三个选项"}
CHOICE_PICK = {"1": "选左边", "2": "选中间", "3": "选右边"}


def load_cards():
    with open(PLAN, encoding="utf-8") as f:
        return (json.load(f).get("cards") or {})


def main() -> int:
    out_path = (sys.argv[1] if len(sys.argv) > 1
                else os.path.join(ROOT, "docs", "指令卡清单.md"))
    cards = load_cards()

    # 按**卡名**归并(引擎手里只有卡名;同名卡在 orders 里已经折叠成一条)
    by_name = {}
    for cid, rec in cards.items():
        nm = (rec.get("name") or "").strip()
        if not nm:
            continue
        by_name.setdefault(nm, {"name": nm, "cost": rec.get("cost"),
                                "kind": rec.get("kind") or "",
                                "rows": rec.get("rows") or "",
                                "follow": rec.get("follow") or "",
                                "note": rec.get("note") or "",
                                "ids": []})["ids"].append(cid)

    playable, blacklist, unsupported = [], [], []
    for nm, r in by_name.items():
        # ★ 分档问 orders(唯一判据),不自己看 JSON 的 mode
        if orders.is_blacklisted(nm):
            blacklist.append(r)
        elif orders.playable("order", nm):
            playable.append(r)
        else:
            unsupported.append(r)

    def key(r):
        return (r["cost"] if isinstance(r["cost"], int) else 99, r["name"])

    playable.sort(key=key)
    blacklist.sort(key=key)
    unsupported.sort(key=key)
    direct = [r for r in playable if orders.mode_of(r["name"]) == orders.MODE_DIRECT]
    targ = [r for r in playable if orders.mode_of(r["name"]) == orders.MODE_TARGET]

    L = []
    L.append("# 指令卡清单:当前能打 / 黑名单 / 暂不支持")
    L.append("")
    L.append("> ★ **这份文件是生成的,别手改。** 重新生成:")
    L.append("> ```")
    L.append("> cd /d D:\\kards-auto-repo")
    L.append("> set PYTHONPATH=src")
    L.append("> D:\\kards-auto\\python\\python.exe -u dev\\order_list_doc.py")
    L.append("> ```")
    L.append(">")
    L.append(f"> 生成时间:{time.strftime('%Y-%m-%d %H:%M')} · "
             f"数据:`config\\order_plays.json`({len(cards)} 张卡 / {len(by_name)} 个卡名)")
    L.append("> · 分档**一律问 `src\\orders.py`**(`playable()` / `is_blacklisted()`),"
             "所以判据改了这份就跟着变。")
    L.append(f"> · `PLAY_ORDERS={orders.PLAY_ORDERS}` · "
             f"`PLAY_TARGETS={getattr(orders, 'PLAY_TARGETS', None)}` · "
             f"`KIND5_AS_BLACKLIST={getattr(orders, 'KIND5_AS_BLACKLIST', None)}`")
    L.append("")
    L.append("## 摘要")
    L.append("")
    L.append("| 档 | 卡名数 | 什么意思 |")
    L.append("|---|---|---|")
    L.append(f"| **可直接打出** | {len(direct)} | 从手牌**拖到中线以下**就打出(和放单位一样) |")
    L.append(f"| **需要目标(能打)** | {len(targ)} | 从手牌**拖到那张卡/总部身上**再松手 |")
    L.append(f"| **黑名单** | {len(blacklist)} | **别带这张** —— 引擎识别到会提示,并且不打 |")
    L.append(f"| 暂不支持 | {len(unsupported)} | 这一版没做(原因见第三节) |")
    L.append(f"| 合计 | {len(by_name)} | |")
    L.append("")

    L.append(f"## 一、当前能打(共 {len(playable)} 个卡名)")
    L.append("")
    L.append(f"### 1.1 可直接打出({len(direct)} 张)—— 拖到中线以下")
    L.append("")
    L.append("| 卡名 | 费用 | 出处 |")
    L.append("|---|---|---|")
    for r in direct:
        L.append(f"| {r['name']} | {r['cost']} | {r['note']} |")
    L.append("")
    L.append(f"### 1.2 需要目标({len(targ)} 张)—— 拖到目标卡 / 总部身上")
    L.append("")
    L.append("挑什么由 `kind`(目标码)+ `rows`(行码)决定;`kind=6`(随意阵营单位)"
             "**一律指敌方**(用户 2026-09-21 决定)。")
    L.append("")
    L.append("| 卡名 | 费用 | 挑什么 | 出处 |")
    L.append("|---|---|---|---|")
    for r in sorted(targ, key=lambda x: (x["kind"], key(x))):
        what = KIND_TEXT.get(r["kind"], f"kind={r['kind']}")
        if r["rows"]:
            what += " · " + "/".join(ROW_TEXT.get(c, c) for c in r["rows"])
        if r["kind"] == "6":
            what += " · **指敌方**"
        if r["follow"]:
            what += f"(两步,之后 {KIND_TEXT.get(r['follow'], r['follow'])})"
        L.append(f"| {r['name']} | {r['cost']} | {what} | {r['note']} |")
    L.append("")

    L.append(f"## 二、黑名单({len(blacklist)} 张)—— 别带这张")
    L.append("")
    L.append("引擎在启动时会把这一档的**张数**打进日志;对局中在手牌里认出黑名单卡时,"
             "会打一条 `⚠️ 手牌里有**黑名单卡**「X」` 提示,并且**不会**打它。")
    L.append("")
    L.append("| 卡名 | 费用 | 为什么进黑名单 |")
    L.append("|---|---|---|")
    for r in blacklist:
        why = r["note"] or ""
        if r["kind"] == "5" or KIND_TEXT.get(r["kind"], "").startswith("选择一张手牌"):
            why = (why + " · " if why else "") + \
                "kind5「选一张手牌」:默认惰性扫描下结构上用不上(用户 2026-09-21 归黑名单)"
        L.append(f"| {r['name']} | {r['cost']} | {why} |")
    L.append("")

    L.append(f"## 三、暂不支持({len(unsupported)} 张)")
    L.append("")
    buckets = {}
    for r in unsupported:
        if r["kind"] == "7":
            k = "三选一(kind 7):打出后弹三张卡,要先有那个弹窗的坐标"
        elif r["follow"]:
            k = "两步卡(先选目标、之后再选一次)"
        elif r["kind"] == "5":
            k = "kind5「选一张手牌」"
        elif r["kind"] in CHOICE_PICK or (r["kind"] in CHOICE_ARITY):
            k = "抉择:打出后弹选项"
        elif "反制" in (r["note"] or ""):
            k = "反制卡:这一版不做"
        elif "抉择" in (r["note"] or ""):
            k = "抉择:不在白名单里"
        elif "不用管" in (r["note"] or ""):
            k = "用户说「不用管」"
        else:
            k = (r["note"] or "其余")
        buckets.setdefault(k, []).append(r)
    for k in sorted(buckets, key=lambda k: -len(buckets[k])):
        rs = sorted(buckets[k], key=key)
        L.append(f"### {k}({len(rs)} 张)")
        L.append("")
        L.append("| 卡名 | 费用 | 出处 |")
        L.append("|---|---|---|")
        for r in rs:
            L.append(f"| {r['name']} | {r['cost']} | {r['note']} |")
        L.append("")

    L.append("---")
    L.append("")
    L.append("## 附:怎么读这张表")
    L.append("")
    L.append("* **费用**来自 `card_db`,是打出去要花的 kredits;引擎按它跟屏幕上的费用读数对账。")
    L.append("* **出处**是用户给规格时的编号(`A#行号` = `order_cards_A.md` 的文件行号;"
             "`B#序号` = `order_cards_review.md` B 表那一节的编号;"
             "`需要目标#N` = 「需要目标」那一节里的编号),用来回溯原始规格。")
    L.append("* 这份表**不是**『能不能付得起』的判据 —— 那要看当回合的费用,由引擎现算。")
    L.append("")

    text = "\n".join(L)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"写好 {out_path}({len(text)} 字节,{len(by_name)} 个卡名)")
    print(f"  可直接打出 {len(direct)} / 需要目标 {len(targ)} / "
          f"黑名单 {len(blacklist)} / 暂不支持 {len(unsupported)}")
    print(f"  orders.status() = {orders.status()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
