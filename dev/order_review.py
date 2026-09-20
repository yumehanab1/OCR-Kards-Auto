# -*- coding: utf-8 -*-
"""
order_review.py - 把指令卡按"打出去要不要选目标"粗分一遍,**生成一份给人核对的表**。

为什么要有这一步(2026-09-20,用户要做"让引擎会用指令卡"):
  在 KARDS 里打指令卡有两种手势(用户确认):
    · **不需要选目标**的 -> 拖到中线以下就打出(和放单位一样);
    · **需要选目标**的   -> 要**拖到那张卡/总部上**松手。
  于是"这张卡要不要选目标"就成了第一道判据。卡库里**没有**这个字段,
  但每张卡都有完整的 `text.zh-Hans` 描述 —— 所以先用**文本**粗分,

  ★ 但文本不等于 UI 行为(官方中文翻译也不一定和实际判定一致)。所以这份分类
    **必须由人过一遍**才敢拿去驱动鼠标:脚本产出 `docs\\order_cards_review.md`,
    用户核对之后以人为准(把错的挪一下,或者直接说哪几条不对)。

用法:
  .venv\\Scripts\\python.exe dev\\order_review.py            # 打印统计 + 写文档
  .venv\\Scripts\\python.exe dev\\order_review.py --stats    # 只看统计
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import card_match  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 「点名一个东西」的说法。卡面描述里出现这些,基本就是"要你指一个目标"。
#: ★ 动词表是**看着实际描述补出来的** —— 第一版只写了「对/消灭/…」,于是
#:   "选择 1 张手牌"、"指向 1 个单位"、"使其与 1 个敌方单位战斗" 全漏到了
#:   "不需要目标"那批里(抽查 B 档头几行就看见了)。宁可多收(收进来只是不做),
#:   不可漏(漏了会拿错手势打出去)。
SINGLE = re.compile(
    r"(对|指向|选择|挑选|选中|指定|消灭|压制|摧毁|使|移动|退回|缴获|攻击|与)\s*"
    r"(1|一)\s*(个|张|名|辆|架|门|支|种)")
#: 「随机」出现的地方说明游戏自己挑 —— 不需要玩家指。
RANDOM = re.compile(r"随机")
#: 「抉择」= 二选一,肯定要额外点一下(即使不要目标也要多一步),第一版排除。
CHOICE = re.compile(r"抉择")
#: ★ 风险词:判成"不需要目标"、但描述里又出现了这些 -> 优先让人看。
#:   纯文本判据一定会错一些(实测漏网例子:"使其**与 1 个**敌方单位战斗" ——
#:   它多半是要你挑一个敌人的),所以把**最可能错的那批**标出来,
#:   核对就不用 386 行全看一遍。宁可多标,不可漏标。
RISK = re.compile(r"目标|选择|任意|指定|抉择|或|与\s*[1一]|(?:1|一)\s*[个张名辆架门支种]")


def classify(text: str) -> tuple[str, str]:
    """返回 (类别, 依据)。类别只有三种,枚举写死,避免下游拼错。"""
    if not text:
        return "未知", "卡库里没有中文描述"
    if CHOICE.search(text):
        return "抉择", "描述里有「抉择」——要二选一,多一步操作"
    m = SINGLE.search(text)
    if m:
        # ★「随机对 1 个敌方单位造成伤害」不算要选目标(游戏自己挑),
        #   看它前面几个字里有没有"随机"。
        start = max(0, m.start() - 4)
        if RANDOM.search(text[start:m.start()]):
            return "不需要目标", f"「{m.group(0)}」前面带随机 -> 游戏自己挑"
        return "需要目标", f"描述里的「{m.group(0)}」"
    return "不需要目标", "描述里没有「点名一个目标」的说法"


def load_orders(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    out = []
    for c in data.get("cards", []):
        j = c.get("json", {})
        if j.get("type") not in ("order", "countermeasure"):
            continue
        zh = (j.get("title") or {}).get("zh-Hans") or ""
        out.append({
            "cardId": c.get("cardId") or j.get("id"),
            "name": zh,
            "cost": j.get("kredits"),
            "type": j.get("type"),
            "text": (j.get("text") or {}).get("zh-Hans") or "",
            "faction": j.get("faction"),
        })
    return out


def _cell(s: str) -> str:
    """Markdown 表格里的单元格:竖线会破坏表格,换行也一样。"""
    return (s or "").replace("|", "\\|").replace("\n", " ").strip()


def write_doc(orders: list[dict], out_path: str) -> Counter:
    stat = Counter()
    # 行 = (费, 卡名, 费, cardId, 描述, 依据, 类型, 风险词)
    rows: dict[str, list[tuple]] = {"不需要目标": [], "需要目标": [], "抉择": [], "未知": []}
    for o in orders:
        kind, why = classify(o["text"])
        stat[kind] += 1
        risk = sorted(set(RISK.findall(o["text"])))
        rows[kind].append((o["cost"] if o["cost"] is not None else 99,
                           o["name"], o["cost"], o["cardId"], o["text"], why,
                           o["type"], "".join(risk)))

    # 第一版只做**指令卡(order)**里"不需要目标"的那批 —— 反制是另一套机制(用户没选)
    v1_all = [r for r in rows["不需要目标"] if r[6] == "order"]
    v1_sure = [r for r in v1_all if not r[7]]      # 描述里没有任何风险词 -> 高置信度
    v1_risk = [r for r in v1_all if r[7]]          # 带风险词 -> 要人看过才敢放行

    lines: list[str] = []
    add = lines.append
    add("# 指令卡:打出去要不要选目标(★ 人工核对表)")
    add("")
    add("> 生成:`dev\\order_review.py`(2026-09-20)。**这是按键粗分的草稿,以你核对后的为准。**")
    add("")
    add("背景:打指令卡有两种手势(你确认的)——**不需要选目标的拖到中线以下**就打出,")
    add("**需要选目标的要拖到那张卡/总部上**。卡库里没有「要不要选目标」这个字段,")
    add("所以先用卡面描述文本粗分;文本不一定等于 UI 行为,所以要你过一遍。")
    add("")
    add("## 先看我用的判据(判错了就是这几条要改)")
    add("")
    add("| # | 判据 | 判成 |")
    add("|---|---|---|")
    add("| 1 | 描述里有 **抉择** | 单独一类:要二选一,多一步操作,第一版不碰 |")
    add("| 2 | 描述里有 **`对/消灭/压制/摧毁/使/移动 + 1 个·张·名·辆·架`** | `需要目标` |")
    add("| 2b | 但那个说法**前面带「随机」** | `不需要目标`(游戏自己挑) |")
    add("| 3 | 其余 | `不需要目标` |")
    add("")
    add(f"## 统计(共 {len(orders)} 张,含反制)")
    add("")
    add("| 类别 | 张数 |")
    add("|---|---|")
    for k in ("不需要目标", "需要目标", "抉择", "未知"):
        add(f"| {k} | {stat[k]} |")
    add("")
    add("★ 第一版要真的打出去的是:**指令卡(order)+ 不需要目标** = "
        f"**{len(v1_all)} 张**;反制卡(countermeasure)是另一套机制,这一版不做。")
    add("")
    add("这一批我又分了两档,理由是纯文本判据一定会错一些,而**打错一张比不出牌更糟**:")
    add("")
    add("| 档 | 判据 | 张数 | 怎么处理 |")
    add("|---|---|---|---|")
    add(f"| **A 高置信度** | 描述里**没有**任何风险词(目标/选择/任意/1 个…/或) | "
        f"**{len(v1_sure)}** | **第一版就打这批**,不用等核对 |")
    add(f"| **B 待确认** | 描述里有风险词 | **{len(v1_risk)}** | 你看过、确认「确实不用选目标」之后再加进 A |")
    add("")
    add("⇒ **要你手工过的是 B 那 "
        f"{len(v1_risk)} 行**(都在第一节里带 ⚠)。花的时间主要在这儿。")
    add("")
    add("")

    def table(rs: list[tuple]):
        add("| # | 卡名 | 费 | 描述 | 判成这类的依据 | cardId |")
        add("|---|---|---|---|---|---|")
        for i, (_, name, cost, cid, text, why, _t, risk) in enumerate(sorted(rs), 1):
            flag = f"⚠ {risk}" if risk else ""
            add(f"| {i} | {_cell(name)} | {cost} | {_cell(text)} | "
                f"{_cell(why)} {flag} | `{cid}` |")
        add("")

    add("## 一、判为「不需要目标」的**指令卡**")
    add("")
    add(f"### A 高置信度({len(v1_sure)} 张)—— ★ 第一版就打这批,不用等你核对")
    add("")
    table(v1_sure)
    add(f"### B 待确认({len(v1_risk)} 张)—— ★★ **要你过一遍的就是这些**(带 ⚠ 的行)")
    add("")
    add("核对要点:这些卡描述里出现了「目标/选择/任意/1 个…/或」这类词,"
        "但我的规则判成「不用选目标」。**只要有其实要选目标的,请标出来** ——")
    add("那样打出去会落空或者被拒,比不出牌更糟。确认没问题的,告诉我一声,我把它们挪进 A。")
    add("")
    table(v1_risk)
    dump_rest = [r for r in rows["不需要目标"] if r[6] != "order"]
    add("## 一b、判为「不需要目标」的**反制卡**(这一版不做,列出来是为了完整)")
    add("")
    table(dump_rest)
    add("## 二、判为「需要目标」的(第一版不做)")
    add("")
    add("第二版才做(要先有「目标挑哪个」的判据)。里面若有**其实不用选目标**的,"
        "也请标出来 —— 那是白丢的一批牌。")
    add("")
    table(rows["需要目标"])
    add("## 三、判为「抉择」的(要二选一,第一版不做)")
    add("")
    table(rows["抉择"])
    if rows["未知"]:
        add("## 四、没有中文描述的")
        add("")
        table(rows["未知"])

    add("---")
    add("")
    add("## 核对完请回答这两个问题(或者直接在表上改)")
    add("")
    add(f"1. **B 档那 {len(v1_risk)} 行**里,哪些**其实要选目标**?(有就点名;没有就说「都没问题」,"
        "我把它们全挪进 A)")
    add("2. 第二节「需要目标」里,哪些**其实不用选目标**?")
    add("")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return stat, v1_sure, v1_risk


#: 聚类的归一化:数字 -> N,引号里的卡名 -> 「」,标点去掉。
#: 目的不是精确,而是把"同一个模板"的卡排在一起,方便整类确认。
_PUNCT = re.compile(r"[，。、；：！？“”\"'（）()\[\]【】…·,.;:!?\-+/\s]")


def _pattern_key(text: str) -> str:
    t = re.sub(r"“[^”]{0,20}”", "「卡」", text or "")
    t = re.sub(r"\d+", "N", t)
    t = _PUNCT.sub("", t)
    return t[:6] or "(空)"


def write_a_doc(rs: list[tuple], out_path: str) -> None:
    """把 A 档(高置信度、第一版要真的打出去的)单独写成一份**给人核对**的表。"""
    lines: list[str] = []
    add = lines.append
    add("# A 档指令卡核对表 —— ★ 第一版要真的打出去的就是这批")
    add("")
    add("> 生成:`dev\\order_review.py`(2026-09-20)。这份是从 "
        "`docs\\order_cards_review.md` 的「A 高置信度」那一档单独抽出来的。")
    add("")
    add("## 你要判断的只有一件事")
    add("")
    add("**这张卡打出去的时候,游戏会不会要我指一个目标?**")
    add("")
    add("| 判断 | 含义 | 怎么办 |")
    add("|---|---|---|")
    add("| **不会** | 它是真的 A 档:拖到中线以下就打出(和放单位一样) | 不用说话,当默认 |")
    add("| **会** | 它其实属于「需要目标」 | **点名**(第几号 / 卡名),我挪出去 |")
    add("")
    add("★ 为什么这条要紧:**拿错手势打出去会落空或者被拒,比「不出这张牌」更糟** ——"
        "所以宁可你多看一眼。")
    add("")
    add(f"## 它们为什么被判成 A 档({len(rs)} 张)")
    add("")
    add("描述里**没有出现**任何一个风险词:"
        "`目标 / 选择 / 任意 / 指定 / 或 / 抉择 / 1 个·1 张·…`")
    add("—— 也就是说**光看文字根本看不出要点名任何东西**。这是我最有把握的一批;")
    add("带风险词的 199 张在另一份文档的 B 档里,不在这份。")
    add("")
    add("★ 聚类只是把同一个模板的排在一起(数字换成 N、卡名换成「卡」),")
    add("**不是判据**,别拿它当结论。")
    add("")

    # 视图一:按描述开头聚类(整类确认用)
    groups: dict[str, list[tuple]] = {}
    for r in rs:
        groups.setdefault(_pattern_key(r[4]), []).append(r)
    add(f"## 视图一:按描述开头聚类({len(groups)} 类)—— 整类扫一遍最快")
    add("")
    add("| 类 | 张数 | 例子(卡名 / 费 / 描述) | 有问题吗 |")
    add("|---|---|---|---|")
    for key, items in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        items = sorted(items)
        ex = " · ".join(f"{n}({c}) {t[:38]}" for _, n, c, _i, t, _w, _ty, _rk in items[:3])
        add(f"| `{key}` | {len(items)} | {_cell(ex)} | |")
    add("")

    # 视图二:完整清单,按费用分组(第几号可以用于点名)
    add(f"## 视图二:完整清单(共 {len(rs)} 张,按费用分组)")
    add("")
    add("「其实要选目标?」那一栏留空给你写(写 y 或者一句话都行)。")
    add("")
    idx = 0
    by_cost: dict[int, list[tuple]] = {}
    for r in rs:
        by_cost.setdefault(r[2] if r[2] is not None else 99, []).append(r)
    for cost in sorted(by_cost):
        items = sorted(by_cost[cost])
        add(f"### {cost} 费({len(items)} 张)")
        add("")
        add("| # | 卡名 | 描述 | cardId | 其实要选目标? |")
        add("|---|---|---|---|---|")
        for _, name, c, cid, text, _why, _ty, _rk in items:
            idx += 1
            add(f"| {idx} | {_cell(name)} | {_cell(text)} | `{cid}` | |")
        add("")

    add("---")
    add("")
    add("## 核对完怎么回我")
    add("")
    add("- 「都有问题」:点名第几号(或者卡名)就行。")
    add("- 「都没问题」:说一句就行 —— 我就按这批写引擎那半。")
    add("")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats", action="store_true", help="只打印统计,不写文档")
    ap.add_argument("--out", default=None, help="输出路径(默认 docs\\order_cards_review.md)")
    ap.add_argument("--db", default=None, help="卡库路径(默认 card_match.DATA_JSON)")
    args = ap.parse_args()

    db = args.db or card_match.DATA_JSON
    if not os.path.exists(db):
        print(f"卡库不在:{db}")
        return 1
    print(f"卡库:{db}")
    orders = load_orders(db)
    print(f"指令 + 反制共 {len(orders)} 张")

    stat = Counter()
    for o in orders:
        stat[classify(o["text"])[0]] += 1
    for k in ("不需要目标", "需要目标", "抉择", "未知"):
        print(f"   {k:8} {stat[k]}")

    if args.stats:
        print("\n---- 抽样各 3 张 ----")
        for kind in ("不需要目标", "需要目标", "抉择"):
            print(f"[{kind}]")
            shown = 0
            for o in orders:
                k, why = classify(o["text"])
                if k == kind and shown < 3:
                    print(f"   {o['name']}({o['cost']}费) {o['text'][:56]}  <- {why}")
                    shown += 1
        return 0

    out = args.out or os.path.join(PROJECT_ROOT, "docs", "order_cards_review.md")
    _stat, v1_sure, _v1_risk = write_doc(orders, out)
    print(f"\n写好了:{out}")

    a_out = os.path.join(os.path.dirname(out), "order_cards_A.md")
    write_a_doc(v1_sure, a_out)
    print(f"写好了:{a_out}(A 档单独一份,{len(v1_sure)} 张,给人核对用)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
