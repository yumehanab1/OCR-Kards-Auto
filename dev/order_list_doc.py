# -*- coding: utf-8 -*-
r"""order_list_doc.py - 生成两份文档(都由判据现算,不手写):

  1. `docs\指令卡清单.md`      —— 当前能打 / 黑名单 / 暂不支持(正向清单);
  2. `docs\打不出去的指令卡.md` —— **所有打不出去的指令卡**,按原因分组(反向专档)。

为什么要"生成"而不是手写一份
--------------------------
用户 2026-09-21 要一份"黑名单 + 当前可用指令"的文档。手写一份的下场是**立刻过期** ——
这个表已经改过好几轮(指令卡支持、kind5 归黑名单、kind6 全指敌方),而且以后还会改。
所以这两份文档都由**判据本身**生成:

    · 数据(卡名/费用/kind/rows/出处)来自 `config\order_plays.json`;
    · **分档一律问 `src\orders.py`**(`playable()` / `is_blacklisted()` / `mode_of()` /
      `rec_of()` / `target_refuse_reason()`):判据只允许有一处来源,这两份文档也不许另开一套;
    · 于是"改了判据 -> 重跑一次 -> 文档自动跟上",不存在文档和代码说法不一致的情况。

★ 为什么**连分组也不许看 JSON 的 `mode` 字段**:
  `mode` 是**规格表里写的**("用户当初怎么说"),而"这一局到底打不打"是 `src\orders.py`
  的策略层说了算的 —— 典型就是 `kind 5`:表里 `mode` 还是 `target`,而 `orders`
  因为 `KIND5_AS_BLACKLIST` 把它**整档归黑名单**。所以 `打不出去的指令卡.md` 里
  这 10 个卡名出现在**黑名单**组,而不是"需要目标"组。
  如果这里自己读 `mode` 分档,就会得出"需要目标 211 里有 10 张也能打"这种和
  `orders.status()` **对不上的账** —— 这个项目反复栽在这上面(§7 第 60 条)。

★ 唯一的重复:`KIND_TEXT` / `ROW_TEXT` / `CHOICE_ARITY` / `CHOICE_PICK` 是从
  `dev\order_plan.py` 抄来的**人话解释**(那几份 dict 是"用户规格 -> 语义"的原始定义)。
  这里抄一份只是为了文档能自解释;如果哪天改了那边的语义,这里要跟着改
  (或者改成 import —— 但 `order_plan.py` 是脚本,import 会带副作用,所以这里选择抄)。

用法:
  cd /d D:\\kards-auto-repo
  set PYTHONPATH=src
  D:\\kards-auto\\python\\python.exe -u dev\\order_list_doc.py
  # 默认写上面那两份;也可以传两个输出路径覆盖:
  #   argv[1] = 指令卡清单,argv[2] = 打不出去的指令卡
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
OUT_OK = os.path.join(ROOT, "docs", "指令卡清单.md")
OUT_NO = os.path.join(ROOT, "docs", "打不出去的指令卡.md")

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
#: 抉择用另一套码(别和上面混):kind = 扇出码(a=两个选项 b=三个选项);
#: rows = 点哪个(1/2/3 = 左/中/右)。2026-09-21 白名单里只有 a + 1/3。
CHOICE_ARITY = {"a": "两个选项", "b": "三个选项"}
CHOICE_PICK = {"1": "选左边", "2": "选中间", "3": "选右边"}


# --------------------------------------------------------------------------
# 载入(只做"取字段",不在这里判"能不能打")
# --------------------------------------------------------------------------
def load_cards():
    """读规格表原始记录(注:判据不在这里,分档一律问 orders)。"""
    with open(PLAN, encoding="utf-8") as f:
        return (json.load(f).get("cards") or {})


def fold_by_name(cards):
    """按**卡名**归并(引擎手里只有卡名;同名卡在 orders 里已经折叠成一条)。

    返回值里 `n_ids` = 这个卡名在表里对应**几张卡**,`ids` 是那些 cardId ——
    惩戒那一族是"同名折叠"的活样本(12 张卡 -> 1 个卡名),文档里要如实标出来。
    """
    by_name = {}
    for cid, rec in cards.items():
        nm = (rec.get("name") or "").strip()
        if not nm:
            continue
        r = by_name.setdefault(nm, {"name": nm, "cost": rec.get("cost"),
                                    "kind": rec.get("kind") or "",
                                    "rows": rec.get("rows") or "",
                                    "follow": rec.get("follow") or "",
                                    "note": rec.get("note") or "",
                                    "src": rec.get("src") or "",
                                    "ids": []})
        r["ids"].append(cid)
    return by_name


def cost_key(r):
    """排序:费用升序(不知道费用的排最后),同费按卡名。"""
    return (r["cost"] if isinstance(r["cost"], int) else 99, r["name"])


def md_cell(txt) -> str:
    """表格单元格:竖线会把 Markdown 表格拆散,换成全角。"""
    return str(txt or "").replace("|", "／").strip()


def head_lines(title: str, n_cards: int, n_names: int) -> list[str]:
    """两份文档共用的文件头(生成物声明 + 重新生成命令 + 时间 / 开关状态)。"""
    return [
        f"# {title}",
        "",
        "> ★ **这份文件是生成的,别手改。** 重新生成(一次会写**两份**文档):",
        "> ```",
        "> cd /d D:\\kards-auto-repo",
        "> set PYTHONPATH=src",
        "> D:\\kards-auto\\python\\python.exe -u dev\\order_list_doc.py",
        "> ```",
        ">",
        f"> 生成时间:{time.strftime('%Y-%m-%d %H:%M')} · "
        f"数据:`config\\order_plays.json`({n_cards} 张卡 / {n_names} 个卡名)",
        "> · 分档**一律问 `src\\orders.py`**(`playable()` / `is_blacklisted()` / "
        "`mode_of()` / `target_refuse_reason()`),所以判据改了这份就跟着变。",
        f"> · `PLAY_ORDERS={orders.PLAY_ORDERS}` · "
        f"`PLAY_TARGETS={getattr(orders, 'PLAY_TARGETS', None)}` · "
        f"`KIND5_AS_BLACKLIST={getattr(orders, 'KIND5_AS_BLACKLIST', None)}`",
        "",
    ]


# --------------------------------------------------------------------------
# 反向专档:打不出去的指令卡 —— 按原因分组
# --------------------------------------------------------------------------
#: 分组名(同时是展示顺序)。**每个名字后面必须有一句能从判据现算的"为什么"** ——
#: 由 `why_of()` 给;给不出原因就抛异常,宁可生成失败也不出一份对不上账的文档。
GROUP_BLACKLIST = "黑名单(用户点名别带)"
GROUP_CHOICE = "抉择(打出后弹选项)"
GROUP_KIND7 = "三选一(kind 7,打出后弹三张卡)"
GROUP_FOLLOW = "两步卡"
GROUP_COUNTER = "反制卡(这一版不做)"
GROUP_NOWHITE = "抉择:不在白名单里"
GROUP_NOCARE = "用户说「不用管」"
GROUP_NOTEXT = "卡库里没有中文描述"
GROUP_OTHER = "其余(判据说不能打,但没给出可读原因)"

GROUP_ORDER = (GROUP_BLACKLIST, GROUP_CHOICE, GROUP_KIND7, GROUP_FOLLOW,
               GROUP_COUNTER, GROUP_NOWHITE, GROUP_NOCARE, GROUP_NOTEXT,
               GROUP_OTHER)
#: ★★ 哪几组是**横切维度**(只按单一字段分类,和主分组**有交叠**)。
#:   目前只有「两步卡」:`follow` 非空一共 3 个卡名,而它们各自还有更主的原因
#:   (kind 5 归黑名单 1 个、kind 7 三选一 1 个、剩下的才是"纯两步"1 个)。
#:   ⇒ 主分组(其余各组)是**互斥且完备**的划分,这两组是**附注**,
#:     **不能和主分组相加**。摘要表里必须把这件事写出来,否则读表的人会把
#:   199 当成总数,和 `orders.status()` 的账差 2 —— 这正是这张表要避免的错。
GROUP_CROSS = (GROUP_FOLLOW,)
#: 摘要表 / 正文里的"为什么"标题(一句话版;详细理由逐卡写)
GROUP_WHY = {
    GROUP_BLACKLIST: "用户点名「别带这张」;其中 kind 5 是 2026-09-21 整档归进来的",
    GROUP_CHOICE: "打出后弹选项,要先有那个弹窗的坐标才能点",
    GROUP_KIND7: "打出后弹三张卡,点哪一张的判据没有,本次不做",
    GROUP_FOLLOW: "打出后还要再来一次(先选目标、之后再选一次),本次不做",
    GROUP_COUNTER: "反制要等对手动作、按时机响应,这一版没做那套时机判据",
    GROUP_NOWHITE: "抉择但用户没给规格(不在白名单),不知道弹窗该点哪边",
    GROUP_NOCARE: "规格原文写着「不用管」,按不打处理",
    GROUP_NOTEXT: "卡库里没有中文描述,判不出它要干什么",
    GROUP_OTHER: "判据说不能打;原因文本等字段没给全",
}


def kind5_text() -> str:
    """`orders._target_gate` 对 kind 5 的整句原文里,`:` 前那一小段的人话。

    ★ 为什么从判据的原文里截、而不是自己写一句:
      "kind 5 为什么不能打"只允许有一处说法(`src\\orders.py` 的 `_target_gate`)。
      这里只是把那一句里的**一句人话**摘出来放进表格,免得两边口径分家。
    """
    rec = {"mode": orders.MODE_TARGET, "kind": "5"}
    txt = orders._target_gate(rec)[1]
    return txt.split(":", 1)[0].strip() if ":" in txt else txt


def why_of(name: str, group: str, r: dict) -> str:
    """这张牌**为什么**在这一组 —— 逐卡现算,不用任何手写文字。"""
    rec = orders.rec_of(name)
    kind = str(rec.get("kind") or "").strip()
    follow = str(rec.get("follow") or "").strip()
    if group == GROUP_BLACKLIST:
        if orders.is_kind5(name):
            return kind5_text()
        return "用户点名别带"
    if group == GROUP_CHOICE:
        arity = CHOICE_ARITY.get(kind, "")
        pick = CHOICE_PICK.get(str(rec.get("rows") or "").strip(), "")
        if not (arity or pick):
            # 白名单里没给规格 -> 照实写"未给",不猜
            return "打出后弹选项,要弹窗坐标;规格里没给「选左/选右」 —— 未给"
        return (f"打出后弹选项,要弹窗坐标;规格里已给:{arity or '未给'} / {pick or '未给'}"
                " —— 本次不做")
    if group == GROUP_KIND7:
        # ★ 理由一律**引用判据的原话**(`target_refuse_reason`),不在这里自己复述,
        #   免得"文档里写的"和"代码里做的"分家。
        return orders.target_refuse_reason(name).replace("目标码 7 = ", "kind 7 = ")
    if group == GROUP_FOLLOW:
        return (f"两步卡:先按 kind {kind}({KIND_TEXT.get(kind, kind)})选一次目标,"
                f"打出后还要再来一次(follow={follow})—— 本次不做")
    if group == GROUP_COUNTER:
        return r["note"] or "反制卡:这一版不做"
    if group == GROUP_NOWHITE:
        return r["note"] or "抉择:不在白名单里"
    if group == GROUP_NOCARE:
        return r["note"] or "用户说「不用管」"
    if group == GROUP_NOTEXT:
        return r["note"] or "卡库里没有中文描述"
    return r["note"] or orders.target_refuse_reason(name) or ""


def classify(name: str, group_of: dict) -> str:
    """把**打不出去的**一个卡名分到**恰好一组**。

    ★★ 为什么这里不直接读 `config\\order_plays.json` 的 `mode`:
      `mode` 是规格表里的原话,而"这一局打不打"是 `src\\orders.py` 策略层说的算 ——
      kind 5 就是活例子(表里 `mode=target`,策略层因为 `KIND5_AS_BLACKLIST`
      把它整档归黑名单)。照 `mode` 分档会和 `orders.status()` 的账对不上。
      ⇒ 一律用 `orders.is_blacklisted()` / `playable()` / `mode_of()` /
        `target_refuse_reason()` 来分。
    ★ 优先级即判据的优先级:
      1) `is_blacklisted()` 先判 —— kind 5 是**策略层**归进黑名单的,不是表里的 mode;
      2) `mode_of()` 是"表里怎么写的",用来挑出抉择 / 三选一 / 两步这三档;
      3) 剩下的按 `unsupported`(表里其余未支持)分,用出处里的分类字段。
    ★★ kind7 与 follow 的**交叠**怎么处理(这是"分组会算错"的坑):
      `follow` 非空的一共 3 个卡名,其中 1 个是 kind 7(`第 44 特混舰队`,follow=1)、
      1 个是 kind 5(`势不可挡`,follow=1),只有 1 个是"纯两步"(`巡洋舰侦察机`)。
      ⇒ 主分组按**上面这个优先级**取**第一条命中的原因**,所以那 3 个各归
        黑名单 / 三选一 / 两步;`follow` 这一维另在文档里用 ★ 标成**横切维度**,
        **不参与合计**。这样"合计 = 总数 − 能打的"永远成立(现算见 `build_blocked_doc`)。
    """
    rec = orders.rec_of(name)
    mode = orders.mode_of(name)
    kind = str(rec.get("kind") or "").strip()
    follow = str(rec.get("follow") or "").strip()
    if orders.is_blacklisted(name):
        return GROUP_BLACKLIST
    if mode == orders.MODE_CHOICE:
        return GROUP_CHOICE
    if mode == orders.MODE_TARGET and kind == "7":
        return GROUP_KIND7
    if mode == orders.MODE_TARGET and follow:
        return GROUP_FOLLOW
    if mode == orders.MODE_UNSUPPORTED:
        note = group_of[name]["note"]
        if note.startswith("反制卡"):
            return GROUP_COUNTER
        if group_of[name]["src"] == "抉择":
            return GROUP_NOWHITE
        if "不用管" in note:
            return GROUP_NOCARE
        if "没有中文描述" in note:
            return GROUP_NOTEXT
    return GROUP_OTHER


def build_blocked_doc(cards, by_name) -> tuple[str, list[tuple[str, int]]]:
    """生成《打不出去的指令卡》正文。返回 `(文本, [(组名, 张数), ...])`。"""
    blocked = [r for r in by_name.values() if not orders.playable("order", r["name"])]
    blocked.sort(key=cost_key)
    groups: dict[str, list[dict]] = {g: [] for g in GROUP_ORDER}
    for r in blocked:
        groups[classify(r["name"], by_name)].append(r)
    # ★ 一条闸:分完组必须**一个不多一个不少**。判据以后改了(比如放行了 kind 7),
    #   这里会立刻报出来,而不是悄悄出一份对不上账的文档。
    n_grouped = sum(len(v) for v in groups.values())
    if n_grouped != len(blocked):
        raise AssertionError(f"分组漏卡/重卡:{n_grouped} != {len(blocked)}")
    unknown = [r["name"] for r in groups[GROUP_OTHER]]
    if unknown:
        raise AssertionError(f"这些卡分不出原因,不能写进文档:{unknown}")

    summary = [(g, len(groups[g])) for g in GROUP_ORDER]
    total = sum(n for _, n in summary)
    ok_n = len(by_name) - total
    # 黑名单里**表里就写着 blacklist** 的那部分(不含策略层归进来的 kind 5)——
    # 文档要引 `orders.status()` 那句『表里 72 + kind 5 10』,所以这两个数现算。
    bl_names = [r["name"] for r in groups[GROUP_BLACKLIST]]
    n_bl_k5 = sum(1 for nm in bl_names if orders.is_kind5(nm))
    n_bl_tbl = len(bl_names) - n_bl_k5
    # ★ `follow` 是**横切维度**:这里的数是"判据里 follow 非空的卡名数",
    #   和 ★ 组（主分组里的"纯两步"）**不是**一回事,所以分开算。
    n_follow = sum(1 for r in blocked
                   if str(orders.rec_of(r["name"]).get("follow") or "").strip())

    L = head_lines("打不出去的指令卡:按原因分组", len(cards), len(by_name))
    L.append(f"这份文档只收**打不出去**的指令卡(共 **{total}** 个卡名);"
             "能打的那一档在 `docs\\指令卡清单.md`。")
    L.append("")
    L.append("## 摘要")
    L.append("")
    L.append("| 组 | 卡名数 | 为什么打不出去 |")
    L.append("|---|---|---|")
    for g, n in summary:
        mark = " ★" if g in GROUP_CROSS else ""
        L.append(f"| **{g}**{mark} | {n} | {GROUP_WHY[g]} |")
    L.append(f"| **合计** | **{total}** | = 卡名总数 − 能打的 |")
    L.append("")
    L.append("★ = **横切维度**(只按一个字段分类),和上面的主分组**有交叠**,"
             "**不能**和它们相加 —— 见下面「交叠」那一段。"
             "黑名单那一组的内部构成另见第一节。")
    L.append("")
    # ★ 账要平:合计必须等于"卡名总数 − 能打的" —— 两边的数字都由判据现算。
    L.append(f"**账**:卡名总数 `{len(by_name)}`(见 `orders.status()` 的第一个数字)"
             f" − 能打的 `{ok_n}`(`playable()` 为真:可直接打出 "
             f"+ 需要目标里放行的那些)= **{len(by_name)} − {ok_n} = {total}** —— "
             "和上表合计一致。")
    L.append("")
    L.append("> ★ 这张账里**没有**『需要目标 211』那一档:`211` 是**规格表**里的数,"
             "它包含后来被策略层整档归进黑名单的 kind 5。"
             f"本表按**这一局打不打**分组,所以那 {n_bl_k5} 个卡名算在**黑名单**组里"
             f"(黑名单 {len(bl_names)} = 表里 {n_bl_tbl} + kind 5 {n_bl_k5}),"
             "不再算一遍 —— 两边都数一遍就会出现『合计对不上总数』的账。")
    L.append("")
    cross_minor = sum(n for g, n in summary if g in GROUP_CROSS)
    if n_follow:
        others = sum(n for g, n in summary if g not in GROUP_CROSS)
        L.append("### 交叠:★ 那一组为什么不能相加")
        L.append("")
        L.append(f"主分组(不带 ★)是**互斥且完备**的划分,合计 `{others}`;"
                 f"★ 组另外合计 `{cross_minor}`。"
                 f"`{others} + {cross_minor} = {others + cross_minor}` **不是**总数 —— "
                 "因为 ★ 组里的卡**已经**在自己的主分组里算过一次了。")
        L.append("")
        L.append(f"**只看 `follow` 字段**:判据(`config\\order_plays.json`)里 `follow` 非空、"
                 f"且打不出去的卡名一共 **{n_follow}** 个 —— "
                 "`src\\orders.py` 的文件头写的『带 `follow` 的两步卡(3 张)』"
                 "说的就是这个数。它们各自的主要原因是:")
        L.append("")
        L.append("| 卡名 | 费用 | 主要组(算进合计的那个) | 是两步吗 | 规格出处 |")
        L.append("|---|---|---|---|---|")
        for r in sorted(blocked, key=cost_key):
            if not str(orders.rec_of(r["name"]).get("follow") or "").strip():
                continue
            g = classify(r["name"], by_name)
            which = "★ 是(本组)" if g in GROUP_CROSS else "否(只体现在 follow 字段里)"
            L.append(f"| {r['name']} | {r['cost']} | {g} | {which} | "
                     f"{md_cell(r['note'])} |")
        L.append("")
        L.append(f"> 也就是说:『两步卡』有**两种数法**,两个都对、但**只有一种能相加**:"
                 f"① 按 `follow` 字段数 = {n_follow} 个卡名(它们是两步,但各自还有更主的原因);"
                 f"② 按**这一局打不打**的主分组数 = ★ 组 {cross_minor} 个"
                 "(只剩没被更主原因盖住的那个)。"
                 "摘要表的合计用的是**主分组**,所以合计 = 卡名总数 − 能打的,永远平。")
        L.append("")
    L.append("## 先说一句:扫到了不打,是**预期行为**")
    L.append("")
    L.append("上面这些卡如果出现在手牌 / 卡组里,引擎**扫到了会不打**(fail-closed);"
             "黑名单那一组还会在日志里打一条 `⚠️ 手牌里有**黑名单卡**「X」……建议别把它带进卡组`。")
    L.append("这是**设计如此**,不是故障:每一档的『不打』都对应一条明确的判据,"
             "而判据只写在 `src\\orders.py` 里。")
    L.append("")
    L.append("**怎么放开某一档**(改哪里 —— 按『改动成本从低到高』排):")
    L.append("")
    L.append("| 想放开 | 改哪里 | 要注意什么 |")
    L.append("|---|---|---|")
    L.append("| 整个指令卡支持 | `src\\orders.py` 的 `PLAY_ORDERS = True`(总开关) | "
             "关掉 = 退回 2026-09-20 之前:指令一律不碰 |")
    L.append("| 「需要目标」整档 | `src\\orders.py` 的 `PLAY_TARGETS` | "
             "关掉只剩「可直接打出」那一档(A/B 对比用) |")
    L.append("| kind 5「选择一张手牌」 | `src\\orders.py` 的 `KIND5_AS_BLACKLIST` | "
             "置 False = 退回『需要目标』档;但惰性扫描下它结构上用不上"
             "(依据写在那个常量的注释里) |")
    L.append("| kind 1~4/6 里的某几张 | `src\\orders.py` 的 `TARGET_KINDS_OK` | "
             "放行的是**目标码**,不是单张卡 |")
    L.append("| 抉择 / 三选一 / 两步 / 反制 | 这四档**不是开关**:要先补规格"
             "(用户给『弹窗点哪边』的判据),再照 `order_target.py` 的样子加判据 | "
             "只改开关没有用 —— 没有坐标就没有可执行的动作 |")
    L.append("")
    L.append("> 注:上表里的**开关**都在 `src\\orders.py`,那是判据的唯一出处;"
             "`config\\order_plays.json` 是 `dev\\order_plan.py` 从用户规格文档生成的,"
             "**不许手改**(手改会在下次重新生成时被冲掉)。")
    L.append("")

    L.append("## 一、黑名单(用户点名别带)")
    L.append("")
    L.append("这一组的『不打』是用户直接点的名,并且会走引擎那条**每局一次的提示**,"
             "所以分两种来源,分开列:")
    L.append("")
    L.append("| 来源 | 卡名数 | 说明 |")
    L.append("|---|---|---|")
    fam = [r for r in groups[GROUP_BLACKLIST]
           if not orders.is_kind5(r["name"]) and "同族" in (r["note"] or "")]
    rest_bl = [r for r in groups[GROUP_BLACKLIST]
               if not orders.is_kind5(r["name"]) and "同族" not in (r["note"] or "")]
    k5 = [r for r in groups[GROUP_BLACKLIST] if orders.is_kind5(r["name"])]
    L.append(f"| 惩戒族(同名折叠) | {len(fam)} | 用户点名「惩戒和所有同名卡,"
             "包括狂怒/激怒」;同名卡在 `orders` 里**按卡名折叠成一条**(手里只有卡名) |")
    L.append(f"| 其余表里的黑名单 | {len(rest_bl)} | "
             "`config\\order_plays.json` 里 `mode=blacklist`(kind 8 / X)的那些 |")
    L.append(f"| kind 5「选择一张手牌」 | {len(k5)} | "
             "2026-09-21 用户决定**整档归黑名单**(`KIND5_AS_BLACKLIST`);"
             "表里它们还是 `target` —— 这正是『分档不许看 JSON 的 mode』的原因 |")
    L.append(f"| **合计** | **{len(groups[GROUP_BLACKLIST])}** | "
             "= `orders.status()` 的『黑名单 … 个卡名(表里 72 + kind 5 10)』 |")
    L.append("")
    if fam:
        L.append("### 惩戒族(同名折叠)—— 每个卡名对应表里几张卡")
        L.append("")
        L.append("| 卡名 | 费用 | 表里几张卡 | 为什么打不出去 | 规格出处 |")
        L.append("|---|---|---|---|---|")
        for r in sorted(fam, key=cost_key):
            L.append(f"| {r['name']} | {r['cost']} | {len(r['ids'])} | "
                     f"{why_of(r['name'], GROUP_BLACKLIST, r)} | {md_cell(r['note'])} |")
        L.append("")
    if k5:
        L.append("### kind 5「选择一张手牌」归进来的")
        L.append("")
        L.append("| 卡名 | 费用 | 为什么打不出去 | 规格出处 |")
        L.append("|---|---|---|---|")
        for r in sorted(k5, key=cost_key):
            L.append(f"| {r['name']} | {r['cost']} | {why_of(r['name'], GROUP_BLACKLIST, r)} | "
                     f"{md_cell(r['note'])} |")
        L.append("")
    if rest_bl:
        L.append("### 其余(表里 `mode=blacklist`)")
        L.append("")
        L.append("| 卡名 | 费用 | 为什么打不出去 | 规格出处 |")
        L.append("|---|---|---|---|")
        for r in sorted(rest_bl, key=cost_key):
            L.append(f"| {r['name']} | {r['cost']} | {why_of(r['name'], GROUP_BLACKLIST, r)} | "
                     f"{md_cell(r['note'])} |")
        L.append("")

    rest_groups = [g for g in GROUP_ORDER
                   if g != GROUP_BLACKLIST and groups[g]]
    for i, g in enumerate(rest_groups, start=2):
        rs = sorted(groups[g], key=cost_key)
        L.append(f"## {i}、{g}({len(rs)} 个卡名)")
        L.append("")
        L.append(GROUP_WHY[g] + "。")
        L.append("")
        L.append("| 卡名 | 费用 | 为什么打不出去 | 规格出处 |")
        L.append("|---|---|---|---|")
        for r in rs:
            L.append(f"| {r['name']} | {r['cost']} | {why_of(r['name'], g, r)} | "
                     f"{md_cell(r['note'])} |")
        L.append("")

    L.append("---")
    L.append("")
    L.append("## 附:怎么读这张表")
    L.append("")
    L.append("* **费用**来自 `card_db`,是打出去要花的 kredits;引擎按它跟屏幕上的费用读数对账。")
    L.append("* **规格出处**是用户给规格时的编号(`A#行号` = `order_cards_A.md` 的文件行号;"
             "`B#序号` = `order_cards_review.md` B 表那一节的编号;"
             "`需要目标#N` / `抉择#N` = 那两节里的编号),用来回溯原始规格。")
    L.append("* 表里的数是**卡名数**,不是**卡数** —— 两者不一样:"
             "`惩戒` 一个卡名对应表里 12 张卡(引擎手里只有卡名,所以按卡名折叠)。"
             "两个数在 `orders.status()` 里都报了。")
    L.append("* 这三份说法必须是同一个:`src\\orders.py`(判据)· `config\\order_plays.json`(规格)"
             "· 本文档(人看的)。对不上就是有人绕过判据自己写了一套。")
    L.append("")
    return "\n".join(L), summary


# --------------------------------------------------------------------------
# 正向清单(原样保留:当前能打 / 黑名单 / 暂不支持)
# --------------------------------------------------------------------------
def build_main_doc(cards, by_name, playable, blacklist, unsupported) -> str:
    def key(r):
        return cost_key(r)

    playable.sort(key=key)
    blacklist.sort(key=key)
    unsupported.sort(key=key)
    direct = [r for r in playable if orders.mode_of(r["name"]) == orders.MODE_DIRECT]
    targ = [r for r in playable if orders.mode_of(r["name"]) == orders.MODE_TARGET]

    L = head_lines("指令卡清单:当前能打 / 黑名单 / 暂不支持", len(cards), len(by_name))
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
    L.append("> 打不出去的那一档单独有一份按原因分组的专档:`docs\\打不出去的指令卡.md`"
             "(同一支生成器写出来的)。")
    L.append("")

    L.append(f"## 一、当前能打(共 {len(playable)} 个卡名)")
    L.append("")
    L.append(f"### 1.1 可直接打出({len(direct)} 张)—— 拖到中线以下")
    L.append("")
    L.append("| 卡名 | 费用 | 出处 |")
    L.append("|---|---|---|")
    for r in direct:
        L.append(f"| {r['name']} | {r['cost']} | {md_cell(r['note'])} |")
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
        L.append(f"| {r['name']} | {r['cost']} | {what} | {md_cell(r['note'])} |")
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
        if orders.is_kind5(r["name"]):
            # ★ 理由引用判据的原话(只取第一句,免得和后面的说明重复)
            why = (why + " · " if why else "") + \
                f"kind5「选一张手牌」:{kind5_text()}(用户 2026-09-21 整档归黑名单)"
        L.append(f"| {r['name']} | {r['cost']} | {why} |")
    L.append("")

    L.append(f"## 三、暂不支持({len(unsupported)} 张)")
    L.append("")
    buckets = {}
    for r in unsupported:
        if orders.mode_of(r["name"]) == orders.MODE_CHOICE:
            k = "抉择:打出后弹选项"
        elif r["kind"] == "7":
            k = "三选一(kind 7):打出后弹三张卡,要先有那个弹窗的坐标"
        elif r["follow"]:
            k = "两步卡(先选目标、之后再选一次)"
        elif (r["note"] or "").startswith("反制卡"):
            k = "反制卡:这一版不做"
        elif r["src"] == "抉择":
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
            L.append(f"| {r['name']} | {r['cost']} | {md_cell(r['note'])} |")
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
    return "\n".join(L)


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def main() -> int:
    out_ok = (sys.argv[1] if len(sys.argv) > 1 else OUT_OK)
    out_no = (sys.argv[2] if len(sys.argv) > 2 else OUT_NO)
    cards = load_cards()
    by_name = fold_by_name(cards)

    playable, blacklist, unsupported = [], [], []
    for nm, r in by_name.items():
        # ★ 分档问 orders(唯一判据),不自己看 JSON 的 mode
        if orders.is_blacklisted(nm):
            blacklist.append(r)
        elif orders.playable("order", nm):
            playable.append(r)
        else:
            unsupported.append(r)

    text_ok = build_main_doc(cards, by_name, playable, blacklist, unsupported)
    text_no, summary = build_blocked_doc(cards, by_name)
    write(out_ok, text_ok)
    write(out_no, text_no)

    print(f"写好 {out_ok}({len(text_ok)} 字节,{len(by_name)} 个卡名)")
    print(f"  可直接打出 {len([r for r in playable if orders.mode_of(r['name']) == orders.MODE_DIRECT])} / "
          f"需要目标 {len([r for r in playable if orders.mode_of(r['name']) == orders.MODE_TARGET])} / "
          f"黑名单 {len(blacklist)} / 暂不支持 {len(unsupported)}")
    print(f"写好 {out_no}({len(text_no)} 字节)")
    total = 0
    for g, n in summary:
        print(f"    {g}: {n}")
        total += n
    print(f"  打不出去的合计 {total}(= 卡名 {len(by_name)} − 能打的 {len(playable)};"
          f"差 {len(by_name) - len(playable) - total})")
    print(f"  orders.status() = {orders.status()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
