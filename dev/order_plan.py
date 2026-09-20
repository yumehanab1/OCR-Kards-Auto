# -*- coding: utf-8 -*-
"""
order_plan.py - 把用户给的「每张指令卡怎么打」规格,对到具体卡上并生成配置。

## 规格来源(用户 2026-09-20 原话,逐字保留,便于核对)

> a类146-148行是新的天气牌，打出后是弹三个卡出来三选一 168行快速胜利是对一个目标造成伤害
> 239行航母战同快速胜利 311行惩戒和所有同名卡（包括狂怒，激怒）大多数是三选一，少部分是指向指令
> 很复杂 是单独一种玩法 我会提示用户不要带惩戒
> b类：进入正式指定前，指定一个格式：牌号数字-数字-字母，数字1指指定敌方单位（打不了总部），
> 2指敌方单位或总部（都能打），3指指定敌方总部，4指我方单位，5指选择一张手牌（随意点一张），
> 6指随意阵营单位，7指三选一，a仅指前线敌方单位，b仅指前线友方单位，c仅指敌方支援阵线，
> d仅指我方支援阵线；6-1，9-1，12-1，13-1，14-5，15-4，16-1-a，18-6，20是选择并弃一张反制，
> 20也和惩戒加进黑名单，21-4-b，22-1，26-4，27-7，29-1，30-1-c，31在黑名单，33-4-d，35-5，
> 36-5，40-5，43-4（仅3攻以下），51-5（仅美国单位，进黑名单），59-7，68-5，70在黑名单，
> 71-2-c，75-7，76-4，82-5（仅坦克，进黑名单），83-4，84-4-d（仅非守护单位），87-6-ab，89-7，
> 91-7，94-7，97-1-a，100-4，103黑名单，106-4，109黑名单，110也进黑名单，116黑名单，118-1-a，
> 122-4，124-4，125-1-a，126-6，128-1，137-6，138黑名单，143-6，144-1，145-1-a，146-6，149-7，
> 150进黑名单，151-7，156进黑名单，157-6，160-4，161-1-c，162-6，164黑名单，168-4，174黑名单，
> 175-2，184-1，185-5，191-1，195-1，199-1

## 两套编号(★ 别搞混,这是最容易出错的地方)

* **A 类的「146-148 行」= `docs\\order_cards_A.md` 的【文件行号】**
  (已核对:146/147/148 = 狂风/蓝天/薄雾,168 = 快速胜利,239 = 航母战,311 = 惩戒)
* **B 类的「6-1」= `docs\\order_cards_review.md` 里【B 表那一节的序号】**
  (已核对:14 = 好高骛远「选择并弃 1 张牌」-> 5;16 = 巨人苏醒「对**前线 1 个敌方单位**」
   -> 1-a;20 = 战争宣传「选择并弃 1 张反制」-> 黑名单。三条都对得上)

## 目标码 / 行码

    数字 1 = 指定敌方单位(打不了总部)      字母 a = 仅前线敌方单位
    数字 2 = 敌方单位或总部(都能打)        字母 b = 仅前线友方单位
    数字 3 = 指定敌方总部                  字母 c = 仅敌方支援阵线
    数字 4 = 我方单位                      字母 d = 仅我方支援阵线
    数字 5 = 选择一张手牌(随意点一张)
    数字 6 = 随意阵营单位
    数字 7 = 三选一(打出后弹三张卡)
    X      = 黑名单(不打出;并且要在面板上提示用户"别带这张")

用法:
  .venv\\Scripts\\python.exe dev\\order_plan.py --verify    # 只核对映射(默认)
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(PROJECT_ROOT, "docs")

# ---------------------------------------------------------------------------
# 用户的规格(解析成人能核对的字典;原文见模块 docstring)
# ---------------------------------------------------------------------------
#: 目标码 -> 人话
#: ★ 2026-09-20 用户第二份规格里把**黑名单改成了 `8`**(第一份用的是文字"黑名单")。
#:   两个都留着:`X` 只在本文件内部用,`8` 是用户现在的写法。
TARGET_KIND = {
    "1": "指定敌方单位(打不了总部)",
    "2": "敌方单位或总部",
    "3": "指定敌方总部",
    "4": "我方单位",
    "5": "选择一张手牌",
    "6": "随意阵营单位",
    "7": "三选一",
    "8": "黑名单(不打出)",
    "X": "黑名单(不打出)",
}
#: 行码 -> 人话
ROW_KIND = {
    "a": "仅前线敌方单位",
    "b": "仅前线友方单位",
    "c": "仅敌方支援阵线",
    "d": "仅我方支援阵线",
}

#: 抉择类(用户第二份规格)的行码与选项码 —— 和上面那套**完全不是一回事**,别混:
#:   a = 两个选项、b = 三个选项;1 = 选左边、2 = 选中间、3 = 选右边。
CHOICE_ARITY = {"a": "两个选项", "b": "三个选项"}
CHOICE_PICK = {"1": "选左边", "2": "选中间", "3": "选右边"}

#: A 档:用户按 `order_cards_A.md` 的**文件行号**点的
A_LINE_SPEC: dict[int, tuple[str, str, str]] = {
    146: ("7", "", "新的天气牌,打出后弹三张卡三选一"),
    147: ("7", "", "同上"),
    148: ("7", "", "同上"),
    168: ("2", "", "对一个目标造成伤害"),
    239: ("2", "", "同快速胜利"),
    311: ("X", "", "惩戒及其同名卡(含狂怒/激怒):多数是三选一、少数是指向指令," 
                   "玩法复杂 -> 黑名单"),
}

#: B 档:序号 -> (目标码, 行码, 备注)。序号 = `order_cards_review.md` B 表那一节的编号。
B_SPEC: dict[int, tuple[str, str, str]] = {
    6: ("1", "", ""),
    9: ("1", "", ""),
    12: ("1", "", ""),
    13: ("1", "", ""),
    14: ("5", "", ""),
    15: ("4", "", ""),
    16: ("1", "a", ""),
    18: ("6", "", ""),
    20: ("X", "", "选择并弃一张反制"),
    21: ("4", "b", ""),
    22: ("1", "", ""),
    26: ("4", "", ""),
    27: ("7", "", ""),
    29: ("1", "", ""),
    30: ("1", "c", ""),
    31: ("X", "", ""),
    33: ("4", "d", ""),
    35: ("5", "", ""),
    36: ("5", "", ""),
    40: ("5", "", ""),
    43: ("4", "", "仅 3 攻以下"),
    51: ("X", "", "仅美国单位"),
    59: ("7", "", ""),
    68: ("5", "", ""),
    70: ("X", "", ""),
    71: ("2", "c", ""),
    75: ("7", "", ""),
    76: ("4", "", ""),
    82: ("X", "", "仅坦克"),
    83: ("4", "", ""),
    84: ("4", "d", "仅非守护单位"),
    87: ("6", "ab", ""),
    89: ("7", "", ""),
    91: ("7", "", ""),
    94: ("7", "", ""),
    97: ("1", "a", ""),
    100: ("4", "", ""),
    103: ("X", "", ""),
    106: ("4", "", ""),
    109: ("X", "", ""),
    110: ("X", "", ""),
    116: ("X", "", ""),
    118: ("1", "a", ""),
    122: ("4", "", ""),
    124: ("4", "", ""),
    125: ("1", "a", ""),
    126: ("6", "", ""),
    128: ("1", "", ""),
    137: ("6", "", ""),
    138: ("X", "", ""),
    143: ("6", "", ""),
    144: ("1", "", ""),
    145: ("1", "a", ""),
    146: ("6", "", ""),
    149: ("7", "", ""),
    150: ("X", "", ""),
    151: ("7", "", ""),
    156: ("X", "", ""),
    157: ("6", "", ""),
    160: ("4", "", ""),
    161: ("1", "c", ""),
    162: ("6", "", ""),
    164: ("X", "", ""),
    168: ("4", "", ""),
    174: ("X", "", ""),
    175: ("2", "", ""),
    184: ("1", "", ""),
    185: ("5", "", ""),
    191: ("1", "", ""),
    195: ("1", "", ""),
    199: ("1", "", ""),
}

#: 用户说"不要带"的那一族(他的名字只点了惩戒,但说"所有同名卡,包括狂怒/激怒")
BLACKLIST_FAMILY = ("惩戒", "狂怒", "激怒")


# ---------------------------------------------------------------------------
# 第二份规格(2026-09-20 第二遍):覆盖 `order_cards_review.md` 的**第二节「需要目标」**
# 和**第三节「抉择」**。用户原话逐字留在下面两个字符串里,便于核对。
# ---------------------------------------------------------------------------
#: 第二节「需要目标」的编号 1~216。
NEED_TARGET_RAW = (
    "1-5,2-8,3-1,4-1,5-8,6-4,7-8,8-1,9不用管,10-6-cd,11-3,12-1,13-1,14-1,15-4,16-5,17-8,"
    "18-1,19不是指向,20-4,21-8,22-1,23-8,24-1,25-1,26-8,27-1,28-1,29-8,30-4,31-3,32-1,33-1,"
    "34-8,35-4-d,36-3,37-8,38-8,39-8,40-4,41-8,42-1,43-1,44-8,45-4,46-8,47-4,48-4,49-8,50-4,"
    "51-4,52-1,53-4,54-1,55-1,56-8,57-8,58-8,59-8,60-8,61-8,62-1,63-1,64-1,65-8,66-4,67-1,"
    "68-4,69-1,70-1,71-8,72-8,73-4,74-8,75-4,76-8,77-8,78-1,79-1,80-1,81-4,82-8,83-8,84-8,"
    "85-8,86-4,87-4,88-8,89-4,90-4,91-1,92-4,93-4,94-4,95-8,96-7,97-7,98-1→7（两步）,99-1,"
    "100-1,105-7,106-6,107-1,108-8,109-8,110-8,111-4,112-1,113-8,114-4,115-4,116-8,117-4,"
    "118-1,119-8,120-1,121-7,122-8,123-8,124-8,125-7→1,126-4,127-4,128-8,129-1,130-1,131-7,"
    "132-1,133-1,134-1,135-3,136-1,137-8,138-1,139-7,140-8,141-5,142-1,143-4,144-8,145-8,"
    "146-1,147-1,148-8,149-8,151-1,152-8,153-1,154-1,155-8,156-1,157-1,158-1,159-1,160-4,"
    "161-1,162-8,163-3,164-1,165-1,166-4,167-1,168-4,169-4,170-1,171-1,172-4,173-3,174-1,"
    "175-3,176-1,177-4,178-3,179-3,180-1,181-3,182-4,183-1,184-1,185-8,186-8,187-1,188-8,"
    "189-7,190-8,191-3,192-3,193-3,194-1,195-5→1,196-1,197-1,198-1,199-4,200-3,201-8,202-1,"
    "203-1,204-3,205-1,206-7,207-1,208-8,209-1,210-1,211-1,212-3,213-3,214-3,215-8,216-3")

#: 第三节「抉择」——用户给的是**白名单**(只有这些允许用,其余 16 张不打)。
#: 格式:`编号-选项数-选哪个`,a=两个选项 b=三个选项,1=选左边 2=选中间 3=选右边。
CHOICE_WHITELIST_RAW = (
    "4-a-1,7-a-1,8-a-1,9-a-3,10-a-1,13-a-3,17-a-1,18-a-3,19-a-3,20-a-3,21-a-3,23-a-1,25-a-3,"
    "26-a-3,27-a-3,28-a-1,29-a-3,32-a-3,33-a-3,35-a-3,36-a-3,37-a-1,38-a-3,39-a-1,40-a-1,"
    "42-a-3,43-a-3")


def parse_need_target(raw: str) -> dict[int, dict]:
    """把第二份规格解析成 {编号: {mode, kind, rows, follow, note}}。

    支持三种写法(都是用户原话里出现过的):
      `12-1`        普通:目标码 1
      `10-6-cd`     带行码:**行码前面还有一个连字符**,可以多个(c/d 两行)
      `98-1→7（两步）` **两步**:先按 1 选目标,再出现 7(三选一);`125-7→1` 没写"两步"也算
      `9不用管`      跳过(保持不支持)
      `19不是指向`   **不是指向类** -> 按"不需要目标"处理(可以直接打出)
    """
    out: dict[int, dict] = {}
    for tok in re.split(r"[,，]", raw):
        tok = tok.strip()
        if not tok:
            continue
        m = re.match(r"^(\d+)不用管$", tok)
        if m:
            out[int(m.group(1))] = {"mode": "unsupported", "kind": "", "rows": "",
                                    "follow": "", "note": "用户说「不用管」"}
            continue
        m = re.match(r"^(\d+)不是指向$", tok)
        if m:
            out[int(m.group(1))] = {"mode": "direct", "kind": "", "rows": "",
                                    "follow": "", "note": "用户说「不是指向」-> 按不需要目标"}
            continue
        m = re.match(r"^(\d+)-([1-8])(?:-([a-d]+))?→([1-8])(?:（两步）)?$", tok)
        if m:
            out[int(m.group(1))] = {"mode": "target", "kind": m.group(2),
                                    "rows": m.group(3) or "", "follow": m.group(4),
                                    "note": f"两步:{m.group(2)} -> {m.group(4)}"}
            continue
        m = re.match(r"^(\d+)-([1-8])(?:-([a-d]+))?$", tok)
        if m:
            kind = m.group(2)
            out[int(m.group(1))] = {"mode": "blacklist" if kind == "8" else "target",
                                    "kind": kind, "rows": m.group(3) or "", "follow": "",
                                    "note": ""}
            continue
        raise SystemExit(f"第二份规格里这条看不懂:{tok!r}")
    return out


def parse_choice(raw: str) -> dict[int, dict]:
    """抉择白名单 -> {编号: {arity, pick}}。"""
    out: dict[int, dict] = {}
    for tok in re.split(r"[,，]", raw):
        tok = tok.strip()
        if not tok:
            continue
        m = re.match(r"^(\d+)-([ab])-([123])$", tok)
        if not m:
            raise SystemExit(f"抉择白名单里这条看不懂:{tok!r}")
        out[int(m.group(1))] = {"arity": m.group(2), "pick": m.group(3)}
    return out


# ---------------------------------------------------------------------------
# 从两份文档里把编号读回来(★ 直接从**用户看的那份文件**读,
# 这样编号一定和他们数的一致 —— 自己再算一遍反而可能因为判据改过而对不上)
# ---------------------------------------------------------------------------
def read_a_lines(path: str) -> dict[int, dict]:
    """A 文档:文件行号 -> 卡。返回 {行号: {num,name,cid}}"""
    out: dict[int, dict] = {}
    with open(path, encoding="utf-8") as f:
        for i, ln in enumerate(f.read().splitlines(), 1):
            m = re.match(r"^\| (\d+) \| ([^|]+) \| (.*?) \| `([^`]+)` \| \|$", ln)
            if m:
                out[i] = {"num": int(m.group(1)), "name": m.group(2).strip(),
                          "text": m.group(3).strip(), "cid": m.group(4)}
    return out


def read_b_table(path: str) -> dict[int, dict]:
    """B 表:B 那一节的序号 -> 卡。

    ★★ 踩过的坑(2026-09-20,差点把用户的规格判成"编号对不上"):B 表**后面紧跟着
       「一b、判为不需要目标的反制卡」那张表,而它的编号是**从头重新数**的** ——
       用"从 ### B 待确认 切到 ## 二、"这种粗切法会把两张表混在一起,
       后一张的 1~50 号会把 B 表的前 50 行**覆盖掉**(现象:14 号本该是「好高骛远」,
       解析出来却是反制卡「无心漫谈」)。所以必须切到 `## 一b、` 为止。
    """
    with open(path, encoding="utf-8") as f:
        txt = f.read()
    sec = txt.split("### B 待确认")[1]
    for stop in ("## 一b、", "## 一、b", "## 二、"):
        if stop in sec:
            sec = sec.split(stop)[0]
            break
    out: dict[int, dict] = {}
    for m in re.finditer(
            r"^\| (\d+) \| ([^|]+) \| (\d+) \| (.*?) \| (.*?) \| `([^`]+)` \|$", sec, re.M):
        out[int(m.group(1))] = {"name": m.group(2).strip(), "cost": int(m.group(3)),
                                "text": m.group(4).strip(), "cid": m.group(6)}
    return out


def read_section(path: str, start: str, *ends: str) -> dict[int, dict]:
    """读 `order_cards_review.md` 里某一节带编号的卡表 -> {序号: 卡}。

    ★★ 一定要给**准确的结束标记**:这份文档里每张表的编号都是**从头重新数**的,
      切宽了就会把下一张表的 1 号当成这一张的 1 号(踩过一次,见 read_b_table)。
    """
    with open(path, encoding="utf-8") as f:
        txt = f.read()
    if start not in txt:
        raise SystemExit(f"文档里找不到小节:{start!r}")
    sec = txt.split(start, 1)[1]
    for e in ends:
        if e in sec:
            sec = sec.split(e, 1)[0]
    out: dict[int, dict] = {}
    for m in re.finditer(
            r"^\| (\d+) \| ([^|]+) \| (\d+) \| (.*?) \| (.*?) \| `([^`]+)` \|$", sec, re.M):
        out[int(m.group(1))] = {"name": m.group(2).strip(), "cost": int(m.group(3)),
                                "text": m.group(4).strip(), "cid": m.group(6)}
    return out


def verify() -> int:
    a_doc = os.path.join(DOCS, "order_cards_A.md")
    b_doc = os.path.join(DOCS, "order_cards_review.md")
    for p in (a_doc, b_doc):
        if not os.path.exists(p):
            print(f"缺文件:{p}(先跑 dev\\order_review.py)")
            return 1
    A = read_a_lines(a_doc)
    B = read_b_table(b_doc)
    print(f"A 文档解析到 {len(A)} 行卡片行;B 表解析到 {len(B)} 行")
    if len(B) != 199:
        print(f"!! B 表应当是 199 行,解析到 {len(B)} —— 编号可能对不上,先停下")

    print("\n=== A 类(按 order_cards_A.md 的文件行号)===")
    for line, (code, rows, note) in sorted(A_LINE_SPEC.items()):
        c = A.get(line)
        if not c:
            print(f"  ✗ L{line} 不是卡片行(实得:{c})")
            continue
        print(f"  L{line:<4} #{c['num']:<4} {c['name']:<16} -> {code}{rows} "
              f"[{TARGET_KIND[code]}]  {note}")

    print("\n=== B 类(按 order_cards_review.md 的 B 表序号)===")
    bad = []
    for num, (code, rows, note) in sorted(B_SPEC.items()):
        c = B.get(num)
        if not c:
            bad.append(num)
            continue
        extra = (" + " + "/".join(ROW_KIND[r] for r in rows)) if rows else ""
        print(f"  {num:>3} -> {code}{rows:<2} {c['name']:<18}({c['cost']}费) "
              f"{c['text'][:44]}")
        if extra or note:
            print(f"        = {TARGET_KIND[code]}{extra}{'  ★' + note if note else ''}")
    if bad:
        print(f"  ✗ 序号对不上:{bad}")

    unlisted = sorted(n for n in B if n not in B_SPEC)
    print(f"\n=== B 表里**你没点到**的 {len(unlisted)} 行 ===")
    print("(按你的说法这些就是「不用选目标」-> 可以直接拖到中线以下打出)")
    for n in unlisted[:20]:
        c = B[n]
        print(f"  {n:>3}: {c['name']}({c['cost']}费) {c['text'][:50]}")
    if len(unlisted) > 20:
        print(f"  …(还有 {len(unlisted) - 20} 行,完整清单见 order_cards_plan.md)")
    return 0


#: `build_plan()` 会把第二节那张表存进来,`write_plan()` 用来列"跳号"的卡
NEED_ROWS: dict[int, dict] = {}


def build_plan() -> tuple[dict, dict]:
    """把 A/B 两份文档 + 用户规格,合成每张卡的"怎么打"。

    返回 (plan, stats):
      plan[cardId] = {name, cost, mode, kind, rows, note, text}
        mode = "direct"    -> 拖到中线以下就打出(第一版就做)
               "target"    -> 需要先选目标(第二版做;kind/rows 说明选什么)
               "blacklist" -> 不打出,并且要在面板上提示用户"别带这张"
               "unsupported" -> 其余(需要目标但没给规格 / 抉择 / 反制 / 没描述)
    """
    a_doc = os.path.join(DOCS, "order_cards_A.md")
    b_doc = os.path.join(DOCS, "order_cards_review.md")
    A, B = read_a_lines(a_doc), read_b_table(b_doc)
    print(f"A 文档 {len(A)} 行卡片行;B 表 {len(B)} 行")

    # 卡库索引:费用/类型/描述(★ A 文档的视图二没有"费"这一列,得从卡库补)
    import json
    with open(os.path.join(PROJECT_ROOT, "card_db", "kards_data.json"), encoding="utf-8") as f:
        db = json.load(f)
    idx: dict[str, dict] = {}
    for c in db.get("cards", []):
        j = c.get("json", {})
        cid = c.get("cardId") or j.get("id")
        idx[cid] = {"name": (j.get("title") or {}).get("zh-Hans") or "",
                    "cost": j.get("kredits"),
                    "text": (j.get("text") or {}).get("zh-Hans") or "",
                    "type": j.get("type")}

    plan: dict[str, dict] = {}

    # --- A 档:默认就是"直接打出"(描述里没有任何风险词) ---
    for line, c in A.items():
        info = idx.get(c["cid"], {})
        plan[c["cid"]] = {"name": c["name"], "cost": info.get("cost"),
                          "mode": "direct", "kind": "", "rows": "",
                          "note": f"A#{c['num']}", "text": c["text"], "src": "A"}
    # --- A 档里用户点到的例外 ---
    for line, (code, rows, note) in A_LINE_SPEC.items():
        c = A.get(line)
        if not c:
            raise SystemExit(f"A 档第 {line} 行不是卡片行 —— 行号对不上,先别生成")
        mode = "blacklist" if code == "X" else "target"
        plan[c["cid"]].update(mode=mode, kind=code, rows=rows,
                              note=f"A#{c['num']} L{line} 用户指定:{note}")

    # --- B 表:用户没点到的 = 直接打出;点到的按规格 ---
    for num, c in B.items():
        spec = B_SPEC.get(num)
        if spec is None:
            plan[c["cid"]] = {"name": c["name"], "cost": c["cost"], "mode": "direct",
                              "kind": "", "rows": "", "note": f"B#{num}(未特别指定)",
                              "text": c["text"], "src": "B"}
        else:
            code, rows, note = spec
            mode = "blacklist" if code == "X" else "target"
            plan[c["cid"]] = {"name": c["name"], "cost": c["cost"], "mode": mode,
                              "kind": code, "rows": rows,
                              "note": f"B#{num} 用户指定" + (f":{note}" if note else ""),
                              "text": c["text"], "src": "B"}

    # --- 第二份规格:第二节「需要目标」 ---
    NEED = read_section(b_doc, "## 二、", "## 三、")
    CHOICE = read_section(b_doc, "## 三、", "## 四、", "## 核对完")
    globals()["NEED_ROWS"] = NEED
    # ★ 结束标记别用 "---":表格自己的分隔行就是 `|---|---|`,一撞就把它截没了
    #   (第一次就写成 "---",于是第三节解析出 0 行)。
    print(f"第二节「需要目标」{len(NEED)} 行;第三节「抉择」{len(CHOICE)} 行")
    nt_spec = parse_need_target(NEED_TARGET_RAW)
    ch_spec = parse_choice(CHOICE_WHITELIST_RAW)

    for num, c in NEED.items():
        sp = nt_spec.get(num)
        if sp is None:            # 用户没点到(例如 101~104 / 150 跳号了)
            plan[c["cid"]] = {"name": c["name"], "cost": c["cost"], "mode": "unsupported",
                              "kind": "", "rows": "", "follow": "",
                              "note": f"需要目标#{num}:用户没给规格", "text": c["text"],
                              "src": "需要目标"}
            continue
        plan[c["cid"]] = {"name": c["name"], "cost": c["cost"], "mode": sp["mode"],
                          "kind": sp["kind"], "rows": sp["rows"], "follow": sp["follow"],
                          "note": f"需要目标#{num}" + (f" {sp['note']}" if sp["note"] else ""),
                          "text": c["text"], "src": "需要目标"}

    for num, c in CHOICE.items():
        sp = ch_spec.get(num)
        if sp is None:
            plan[c["cid"]] = {"name": c["name"], "cost": c["cost"], "mode": "unsupported",
                              "kind": "", "rows": "", "follow": "",
                              "note": f"抉择#{num}:不在白名单里", "text": c["text"],
                              "src": "抉择"}
            continue
        plan[c["cid"]] = {"name": c["name"], "cost": c["cost"], "mode": "choice",
                          "kind": sp["arity"], "rows": sp["pick"], "follow": "",
                          "note": f"抉择#{num} 白名单:{CHOICE_ARITY[sp['arity']]} / "
                                  f"{CHOICE_PICK[sp['pick']]}",
                          "text": c["text"], "src": "抉择"}

    # --- 黑名单那一族:按名字抓(用户说"惩戒和所有同名卡,包括狂怒/激怒") ---
    for cid, info in idx.items():
        name = info["name"]
        if not name or info["type"] not in ("order", "countermeasure"):
            continue
        if any(w in name for w in BLACKLIST_FAMILY):
            rec = plan.get(cid) or {"name": name, "cost": info["cost"],
                                    "text": info["text"], "src": "同族", "rows": ""}
            rec.update(mode="blacklist", kind="X", rows="",
                       note=f"黑名单同族「{name}」:用户点名别带")
            plan[cid] = rec

    # --- 剩下的:全部标成 unsupported,并写清**为什么暂时不打** ---
    #   (A/B 两档之外的卡:我判成"需要目标"但用户还没给规格、抉择、反制、没描述)
    #   ★ 把它们也写进配置,是为了让"这张牌为什么不出"在日志里能一句话说清 ——
    #     这个项目吃过太多次"引擎悄悄变笨、日志看不出原因"的亏。
    import order_review as _or
    for c in db.get("cards", []):
        j = c.get("json", {})
        if j.get("type") not in ("order", "countermeasure"):
            continue
        cid = c.get("cardId") or j.get("id")
        if cid in plan:
            continue
        name = (j.get("title") or {}).get("zh-Hans") or ""
        text = (j.get("text") or {}).get("zh-Hans") or ""
        kind, _why = _or.classify(text)
        if j.get("type") == "countermeasure":
            why = "反制卡:这一版不做"
        elif kind == "抉择":
            why = "抉择:要二选一,多一步操作"
        elif kind == "需要目标":
            why = "判为需要目标,但还没给它规格"
        elif not text:
            why = "卡库里没有中文描述"
        else:
            why = "还没归类"
        plan[cid] = {"name": name, "cost": j.get("kredits"), "mode": "unsupported",
                     "kind": "", "rows": "", "note": why, "text": text, "src": "其余"}

    stats = Counter(r["mode"] for r in plan.values())
    return plan, stats


def write_plan(plan: dict, stats: Counter) -> None:
    import json
    cfg = os.path.join(PROJECT_ROOT, "config", "order_plays.json")
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    with open(cfg, "w", encoding="utf-8") as f:
        json.dump({"note": "指令卡怎么打。生成自 dev/order_plan.py;规格来自用户 2026-09-20。",
                   "target_kind": TARGET_KIND, "row_kind": ROW_KIND,
                   "cards": plan}, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"写好了:{cfg}")

    L: list[str] = []
    add = L.append
    add("# 指令卡「怎么打」总表(★ 请核对)")
    add("")
    add("> 生成:`dev\\order_plan.py`。规格来自你 2026-09-20 给的那份(原文留在工具文件头)。")
    add("")
    add("| 模式 | 张数 | 含义 |")
    add("|---|---|---|")
    add(f"| `direct` | {stats['direct']} | **拖到中线以下就打出** —— 第一版就做这批 |")
    add(f"| `target` | {stats['target']} | 需要先选目标(第二版做);选什么见下表 |")
    add(f"| `choice` | {stats['choice']} | 抉择卡(白名单内):弹两个/三个选项,按指定位置点 |")
    add(f"| `blacklist` | {stats['blacklist']} | 不打出,并且要提示用户「别带这张」 |")
    add(f"| `unsupported` | {stats['unsupported']} | 其余(没给规格 / 不在白名单 / 反制 / 没描述) |")
    add("")
    add("## 一、你两轮点到的每一条(★ 逐条核对这一节)")
    add("")
    add("| 来源 | 卡名 | 费 | 你的规格 | 说明 | 描述 |")
    add("|---|---|---|---|---|---|")
    for cid, r in sorted(plan.items(), key=lambda kv: kv[1]["note"]):
        if "用户指定" not in r["note"] and r["src"] not in ("需要目标", "抉择"):
            continue
        kind = r["kind"]
        if r["mode"] == "choice":
            spec = f"{kind}-{r['rows']}"
            desc = f"{CHOICE_ARITY.get(kind, '')} / {CHOICE_PICK.get(r['rows'], '')}"
        elif r["mode"] == "direct":
            spec, desc = "直接打出", "用户说「不是指向」"
        else:
            spec = "-" if kind in ("", "X") else f"{kind}" + (
                f"-{r['rows']}" if r["rows"] else "")
            if r.get("follow"):
                spec += f"→{r['follow']}"
            desc = (TARGET_KIND.get(kind, "") +
                    (" + " + "/".join(ROW_KIND[x] for x in r["rows"]) if r["rows"] else ""))
            if r.get("follow"):
                desc += f" —— 两步,之后 {TARGET_KIND.get(r['follow'], r['follow'])}"
        add(f"| {r['note'].split(' 用户指定')[0]} | {_cell(r['name'])} | {r['cost']} | "
            f"`{spec}` | {desc} | {_cell(r['text'])[:60]} |")
    add("")

    # 跳号的:用户漏了 -> 保持不打。★ 必须显式列出来,不然"以为都覆盖了"
    missing = [n for n in range(1, len(NEED_ROWS) + 1) if n not in parse_need_target(NEED_TARGET_RAW)]
    if missing:
        add("## 一b、你**跳号**的那几个(我逐个查了)")
        add("")
        add("| 编号 | 卡名 | 费 | 描述 | 实际结果 |")
        add("|---|---|---|---|---|")
        for n in missing:
            c = NEED_ROWS.get(n)
            if not c:
                continue
            got = plan.get(c["cid"], {})
            tail = ("**已在黑名单**(惩戒同族)—— 等于没漏" if got.get("mode") == "blacklist"
                    else "先不打(等你补规格)")
            add(f"| {n} | {_cell(c['name'])} | {c['cost']} | {_cell(c['text'])[:70]} | {tail} |")
        add("")

    def listing(mode: str, title: str, note: str):
        rs = [(r["cost"] if r["cost"] is not None else 99, r) for r in plan.values()
              if r["mode"] == mode]
        add(f"## {title}({len(rs)} 张)")
        add("")
        add(note)
        add("")
        add("| 卡名 | 费 | 描述 | 来源 |")
        add("|---|---|---|---|")
        for _, r in sorted(rs, key=lambda t: (t[0], t[1]["name"])):
            add(f"| {_cell(r['name'])} | {r['cost']} | {_cell(r['text'])[:70]} | "
                f"{_cell(r['note'])} |")
        add("")

    listing("direct", "二、`direct`:直接打出",
            "这批会**拖到中线以下**打出去(和放单位一样)。第一版就是它们。")
    listing("target", "三、`target`:需要选目标(第二版)",
            "第二版做 —— 要先把「目标挑哪个」的判据做出来。带 `→` 的是**两步**"
            "(先一个动作、再一个动作)。")
    listing("choice", "四、`choice`:抉择卡(白名单内)",
            "打出后弹选项:按白名单点左边/右边。")
    listing("blacklist", "五、`blacklist`:不打出,并提示别带",
            "★ 用户点名的那一族(惩戒/狂怒/激怒):玩法复杂,提示用户**不要带进卡组**。")

    out = os.path.join(DOCS, "order_cards_plan.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"写好了:{out}")


def _cell(s: str) -> str:
    return (s or "").replace("|", "\\|").replace("\n", " ").strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="只核对映射")
    ap.add_argument("--write", action="store_true", help="生成 config\\order_plays.json + 核对表")
    args = ap.parse_args()
    if args.write:
        plan, stats = build_plan()
        print("统计:", dict(stats))
        write_plan(plan, stats)
        return 0
    return verify()


if __name__ == "__main__":
    sys.exit(main())
