"""
orders.py - 指令卡「能不能打」的唯一来源(读 `config/order_plays.json`)。

为什么单独一个模块
------------------
指令卡以前是**一律跳过**的(`turn_engine.SKIP`),原因很实在:有些指令要你**选目标**,
而"选哪个"当时没有判据。2026-09-20 用户把 674 张指令/反制的打法**逐张**给出来了,
落在 `config/order_plays.json` 里,包括:

    direct      拖到中线以下就打出(和放单位一样)
    target      要先选目标(kind/rows 说明选什么;带 follow 的是两步)
    choice      抉择卡:打出后弹选项,按指定位置点
    blacklist   不打,并且要提示用户"别带这张"(惩戒那一族等)
    unsupported 其余(没给规格 / 不在白名单 / 反制)

★ 2026-09-20 第二版(target)放行了哪几档、没放行哪几档:
  · 放行:`direct`(286 张)+ `target` 里 **kind 1~4/6 且不带 follow** 的
    (敌我单位/总部,落点由 `order_target.pick()` 现算);
  · 不放行:`choice`(27 张,要按白名单点选项)、`target` 里的 **kind 5**
    (2026-09-21 用户决定**整档归黑名单**,见 `KIND5_AS_BLACKLIST`)、
    kind 7(三选一,20 张)与带 `follow` 的两步卡(3 张)、
    `blacklist`(83 张,用户点名别带)、`unsupported`(67 张)。
  每一档的**判据都在这个文件里**(见 `_target_gate` / `is_blacklisted`),
  `status()` 会把它们如实打出来。

★ 为什么要有这个模块、而不是让每个调用方自己去读 JSON:
  "这张牌能不能打"这个判据现在**三处**要用(scanner 找候选、turn_engine 决定拖不拖、
  启动时打一行状态)。三处各读一份 = 早晚不一致 —— 这个项目在
  `counter` / `countermeasure` 那两套词汇上已经栽过一次(§7 第 60 条)。
  ⇒ 判据只在这里,别人问它。

★ 和 `card_match.db_status()` 同一个套路:载入失败/一张都没载入时,
  `status()` 要给出一句能打进日志的人话 —— 这类故障**不报错、只是悄悄变笨**
  (v0.1.2 漏卡库、v0.1.5 漏费用模板,两次都是这个形状)。
"""

from __future__ import annotations

import json
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAN_JSON = os.path.join(PROJECT_ROOT, "config", "order_plays.json")

#: ★★ A/B 总开关:整条"指令卡支持"的开关。
#:   False = 退回 2026-09-20 之前的行为(指令一律不碰)。
#:   留这个开关是项目纪律(改判据要能一句话退回去),也方便实机对比"带不带指令"。
PLAY_ORDERS = True

#: ★★ A/B 开关(2026-09-20 第二版):**「需要目标」那一档**(211 张)单独一个开关。
#:   False = target 一律不打,退回第一版(只打「可直接打出」那 286 张)。
#: ★ 为什么必须独立于 `PLAY_ORDERS`:target 多了一整套"往哪个坐标拖"的判据
#:   (`order_target.py`,要读战场/前线归属)。实机出问题时得能**只关这一档**、
#:   把 direct 留着,否则一关就两档都没了,没法对比到底是哪一档的问题。
PLAY_TARGETS = True

#: ★★ A/B 开关(2026-09-21):**`kind 5`「选择一张手牌」整档按黑名单处理**。
#:   依据 = 用户 2026-09-21 的决定:"kind5进黑名单"。
#:
#: 为什么归黑名单、而不是"悄悄不打"(用户看得到才有意义):
#:   黑名单会走 `turn_engine` 那条**每局一次的提示** ——
#:   `⚠️ 手牌里有**黑名单卡**「X」……建议别把它带进卡组`(它问的是
#:   `orders.is_blacklisted()`,所以这里返回 True 就会提示,**不用改 turn_engine**)。
#:   "静默不打"就变成:引擎每回合扫到它、判它不可出、用户永远不知道为什么。
#:
#: ★★ 为什么不直接改 `config/order_plays.json` 里的 `mode`:
#:   那个文件是 `dev/order_plan.py` **从用户的规格文档生成**的(--write),
#:   手改会在下次重新生成时**被冲掉**,而且会让"规格"和"策略"混在一处。
#:   所以策略层放在这里:表说什么还是什么(`target_spec()` 照旧能看到 kind=5),
#:   而"这一局打不打"由 `_target_gate()` / `is_blacklisted()` 回答。
#:
#: 为什么会有这个决定(上一轮实测的结论,写在这是为了以后翻案时有据可查):
#:   引擎默认走**惰性扫描** —— 扫到第一张"可出且付得起"的牌就收手,而出牌阶段
#:   只会尝试 `self.cards` 里那一张(`turn_engine.py`:`card = cards[0]`)。
#:   于是 kind 5 要被打出去,它自己必须就是"扫到的第一张可出的牌",
#:   而那个时刻它**左边带身份(有 type)的候选**只剩"我们付不起的那几张",
#:   右边根本没探过 —— 实测三种情形里两种直接失败、一种会去选一张付不起的牌。
#:   ⇒ 结构上用不上,所以整档不打(而不是继续带着一个永不触发的判据)。
KIND5_AS_BLACKLIST = True

#: 「需要目标」这一档里**已经实现**的目标码(不含 kind 5 —— 它由
#: `KIND5_AS_BLACKLIST` 单独管:开关**开着**时按黑名单处理,关掉时回到这一档)。
#: 语义**以 `dev/order_plan.py` 的 `TARGET_KIND` 为准**(那里是用户原话的落点),
#: 这里只记"我们实现了哪几个":
#:   1 指定敌方单位(打不了总部) / 2 敌方单位或总部 / 3 指定敌方总部 /
#:   4 我方单位 / 6 随意阵营单位
#: ★ **5(选择一张手牌)** 见 `KIND5_AS_BLACKLIST`:用户 2026-09-21 决定整档归黑名单。
#: ★ **7(三选一)不在这里** —— 打出后弹三张卡,要另外一套操作(点哪一张),
#:   不是"拖到一个坐标"能表达的,本次不做。
TARGET_KINDS_OK = ("1", "2", "3", "4", "6")

#: 本局放行的目标码 = `TARGET_KINDS_OK`,**再加上**(开关关掉时的)kind 5。
#: ★ 为什么要这么一个函数、而不是在调用点写 `TARGET_KINDS_OK + ("5",)`:
#:   "哪些 kind 放行"只允许有一处;`_target_gate()` 和 `status()` 都问它,
#:   免得日志里的数字和实际判定分家(这个项目反复吃过的亏)。
def target_kinds_ok():
    """本局允许打的目标码(元组;kind 5 只在 `KIND5_AS_BLACKLIST=False` 时在里面)。"""
    if KIND5_AS_BLACKLIST:
        return TARGET_KINDS_OK
    return TARGET_KINDS_OK + ("5",)

MODE_DIRECT = "direct"
MODE_TARGET = "target"
MODE_CHOICE = "choice"
MODE_BLACKLIST = "blacklist"
MODE_UNSUPPORTED = "unsupported"

_CARDS: dict[str, dict] | None = None
_ERR = ""
_N_CARDS = 0        # 表里的**卡数**(和 `len(_CARDS)` 不同:同名卡会折叠成一个名字)
_CONFLICTS: list[str] = []      # 同名但要求不一样的(按"从严"取值,并留痕)

#: 同名冲突时取哪个 —— 越靠前越"保守"。表是按**卡名**索引的(引擎手里只有卡名),
#: 万一以后出现"两张某卡同名但打法不同",宁可从严(不打)。
_MODE_RANK = (MODE_BLACKLIST, MODE_UNSUPPORTED, MODE_TARGET, MODE_CHOICE, MODE_DIRECT)


def load(path: str = PLAN_JSON) -> None:
    """载入指令卡打法表(只载一次;失败只记账,不抛异常)。"""
    global _CARDS, _ERR, _N_CARDS, _CONFLICTS
    if _CARDS is not None:
        return
    _ERR, _N_CARDS, _CONFLICTS = "", 0, []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        _CARDS = {}
        for cid, rec in (data.get("cards") or {}).items():
            name = (rec.get("name") or "").strip()
            if not name:
                continue
            _N_CARDS += 1
            new = {"mode": rec.get("mode") or MODE_UNSUPPORTED,
                   "kind": rec.get("kind") or "",
                   "rows": rec.get("rows") or "",
                   "follow": rec.get("follow") or "",
                   "cost": rec.get("cost"),
                   "cardId": cid}
            old = _CARDS.get(name)
            if old is None:
                _CARDS[name] = new
            elif old["mode"] != new["mode"]:
                # ★ 同名不同要求:引擎手里只有卡名,分不开 -> **取最保守的那个**,并留痕。
                #   (现在表里只有「惩戒」一种重名,12 张全是黑名单,不冲突;
                #    这条是给以后改表时兜底的。)
                pick = min((old, new),
                           key=lambda r: _MODE_RANK.index(r["mode"])
                           if r["mode"] in _MODE_RANK else len(_MODE_RANK))
                _CONFLICTS.append(f"{name}: {old['mode']} vs {new['mode']} -> {pick['mode']}")
                _CARDS[name] = pick
    except Exception as e:                      # 表坏了也不该让引擎崩
        _ERR = f"{type(e).__name__}: {e}"
        _CARDS = {}
        print(f"orders: 指令卡表载入失败 {e}")


def mode_of(name: str) -> str:
    """这张牌(按**卡名**)该怎么打。不在表里返回空串。"""
    load()
    rec = (_CARDS or {}).get((name or "").strip())
    return rec["mode"] if rec else ""


def rec_of(name: str) -> dict:
    load()
    return (_CARDS or {}).get((name or "").strip()) or {}


def is_direct(name: str) -> bool:
    """能不能**拖到中线以下直接打出**(第一版只支持这一种)。"""
    return PLAY_ORDERS and mode_of(name) == MODE_DIRECT


def target_spec(name: str) -> dict:
    """
    「需要目标」这张牌的目标规格 —— `kind` / `rows` / `follow`(判据的唯一出口)。

    ★ 为什么要有这个函数:引擎要拿 `kind`(挑哪一类目标)和 `rows`(限定哪一行),
      而**读 `config/order_plays.json` 这件事只允许 `orders.py` 干**
      (§7 第 60 条:同一个判据两处各读一份 = 早晚不一致)。
      所以引擎(以及 `order_target.py`)一律问这里,不许自己去开那个 JSON。

    不是 target 档(不在表里 / direct / choice / blacklist / unsupported)返回 `{}`。
    ★ 这里**不判断**"这一局放不放行"(开关 / kind 7 / follow)—— 那是
      `is_target()` / `playable()` / `target_refuse_reason()` 回答的问题。
      把"这张牌是什么"和"现在能不能打"分成两个问题,免得调用方把它们混在一起。
    """
    load()
    rec = (_CARDS or {}).get((name or "").strip()) or {}
    if rec.get("mode") != MODE_TARGET:
        return {}
    return {"mode": MODE_TARGET,
            "kind": rec.get("kind") or "",
            "rows": rec.get("rows") or "",
            "follow": rec.get("follow") or "",
            "cost": rec.get("cost"),
            "cardId": rec.get("cardId")}


def _target_gate(rec: dict) -> tuple[bool, str]:
    """
    「这张 target 指令现在能不能打」—— **target 这一档的判据只有这一处**。

    返回 `(能不能打, 不能打的人话原因)`。四个条件少一条都不行:
      · 开关 `PLAY_TARGETS` 为真(A/B 用);
      · `kind` 不是 5(`KIND5_AS_BLACKLIST` 为真时;见那个常量的长注释);
      · `kind` 在 `target_kinds_ok()` 里(7 = 三选一、空值、没见过的数字**一律不打**);
      · `follow` 为空(带 follow 的是两步卡:先一个动作、再一个动作,本次不做)。
    """
    if not PLAY_TARGETS:
        return False, "PLAY_TARGETS=False(A/B 开关关掉了「需要目标」这一档)"
    kind = str(rec.get("kind") or "").strip()
    if kind == "7":
        return False, "目标码 7 = 三选一(打出后弹三张卡),本次不做"
    if kind not in target_kinds_ok():
        if kind == "5":
            return False, ("目标码 5 = 选择一张手牌,2026-09-21 用户决定**整档归黑名单**"
                           "(KIND5_AS_BLACKLIST;依据与实测见那个常量)"
                           " —— 不打,并且提示别带")
        return False, (f"目标码 {kind!r} 不在已实现的 "
                       f"{'/'.join(target_kinds_ok())} 里(fail-closed)")
    follow = str(rec.get("follow") or "").strip()
    if follow:
        return False, f"两步卡(follow={follow}:打出后还要再来一次),本次不做"
    return True, ""


def is_target(name: str) -> bool:
    """
    这张牌是不是「需要目标」那一档、**且这一局允许打**。

    ★ 它就是 target 指令的总闸:引擎只知道"能不能拖出去"(`playable`),
      具体往哪拖再问 `order_target.pick()`(那个模块只回答坐标)。
    """
    if not PLAY_ORDERS:
        return False
    rec = rec_of(name)
    if rec.get("mode") != MODE_TARGET:
        return False
    return _target_gate(rec)[0]


def target_refuse_reason(name: str) -> str:
    """
    「这张 target 指令**这一局**为什么打不了」的人话原因(能打就返回空串)。

    ★ 给引擎写日志用。为什么要有它:引擎只许**引用**判据、不许自己再判一遍
      (例如自己写 `kind == "7"`),否则"日志里说的"和"代码里做的"早晚会分家
      —— 这个项目在 `counter`/`countermeasure` 那两套词汇上已经栽过一次(§7 第 60 条)。
    """
    if not PLAY_ORDERS:
        return "PLAY_ORDERS=False(指令卡总开关关掉了)"
    rec = rec_of(name)
    if rec.get("mode") != MODE_TARGET:
        return "它不是「需要目标」那一档"
    return _target_gate(rec)[1]


def is_kind5(name: str) -> bool:
    """
    这张牌是不是「需要目标」里的 **kind 5(选择一张手牌)** —— **只回答"它是什么"**,
    不回答"这一局打不打"(那是 `_target_gate` / `is_blacklisted` 的事)。

    ★ 为什么单独留一个"是什么"的函数:`status()` 要**如实报账** ——
      "表里 kind 5 有几个卡名"和"其中几个这一局被归进黑名单"是两件事,
      混在一起就又会写出"需要目标 211 但其中 10 张实际不打"那种对不上的账。
    """
    rec = rec_of(name)
    return bool(rec) and rec.get("mode") == MODE_TARGET \
        and str(rec.get("kind") or "").strip() == "5"


def is_blacklisted(name: str) -> bool:
    """
    用户点名"别带这张"的牌(惩戒那一族),**以及 2026-09-21 归进来的 kind 5 那一档**。

    ★ 为什么要并进这一个函数(而不是另开一个 `is_kind5_blacklisted`):
      引擎那条"手牌里有黑名单卡「X」—— 别带这张"的提示问的就是**这一个**函数
      (`turn_engine` 里 `orders.is_blacklisted(...)`,那个文件不在本次改动范围)。
      并进来 = 用户能看到 kind 5 也在"别带"名单里,**且引擎一行都不用改**。
      `KIND5_AS_BLACKLIST=False` 时这里立刻退回老行为(只剩真正的黑名单卡)。
    """
    if mode_of(name) == MODE_BLACKLIST:
        return True
    return bool(KIND5_AS_BLACKLIST) and is_kind5(name)


def playable(ctype: str, name: str) -> bool:
    """
    "这张牌现在允许被拖出去吗" —— **scanner 和 turn_engine 必须问同一个函数**。

    单位:认得出类型就行(能不能付得起由调用方按预算判);
    指令:**放行「可直接打出」(direct)和「需要目标」(target)两档** ——
      target 的落点由 `order_target.pick()` 现算(拖到目标卡/总部身上再松手,
      见那个模块的文件头),这里只回答"允不允许"。
      `choice`(抉择:打出后弹选项,要按白名单点)/ `blacklist`(用户点名别带)/
      `unsupported` **仍然一律不放行**;target 里的 **kind 5**
      (2026-09-21 归黑名单;见 `KIND5_AS_BLACKLIST`)、kind 7(三选一)和带 `follow`
      的两步卡也不放行(见 `_target_gate`)。
    其它(剩余档 / countermeasure / None)= 不放行(fail-closed)。
    """
    if not ctype:
        return False
    if ctype in ("infantry", "tank", "fighter", "bomber", "artillery"):
        return True
    if ctype in ("order", "counter", "countermeasure"):
        return is_direct(name) or is_target(name)
    return False


def status() -> str:
    """一行说清"指令卡表载入得怎么样" —— 引擎开跑时打进日志用。"""
    load()
    n = len(_CARDS or {})
    if not n:
        return (f"⚠️ 指令卡表没载入({_ERR or '未知原因'}) —— 指令会**一律不打**"
                f"(退回到 2026-09-20 之前的行为);文件应在 {PLAN_JSON}")
    if not PLAY_ORDERS:
        return f"指令卡:表载入 {n} 个卡名,但 PLAY_ORDERS=False -> 这一局不打指令"
    from collections import Counter
    c = Counter(r["mode"] for r in _CARDS.values())
    warn = (f";⚠️ {len(_CONFLICTS)} 个同名卡要求不一致(已按从严处理)" if _CONFLICTS else "")
    # ★★★ 这句话必须**如实**说清放行了哪几档。旧版写的是"本局只打「可直接打出」
    #   这一档" —— 2026-09-20 第二版把 target 也放行了,那句就变成了**谎话**,
    #   而"诊断在撒谎"正是这个项目反复吃亏的地方(§7 第 67/68 条)。
    #   所以现在:① 两档分别写清楚;② 把**没做的那几档**也点名;③ **账必须平** ——
    #   每个数字都由 `_target_gate()` / `is_blacklisted()` 逐卡现算,不另写一份口径
    #   (2026-09-21:kind 5 归黑名单之后,旧写法会出现"需要目标 211 但其中 10 张
    #    实际不打"这种对不上的账,正是这里要避免的)。
    tgt = [r for r in _CARDS.values() if r["mode"] == MODE_TARGET]
    n_tgt = len(tgt)
    n_k5_in_bl = sum(1 for r in tgt if str(r.get("kind") or "").strip() == "5"
                     and KIND5_AS_BLACKLIST) if PLAY_TARGETS else 0
    n_ok = sum(1 for r in tgt if _target_gate(r)[0])
    # 真正会被按"黑名单"对待的卡名数 = 表里的黑名单 + 归进来的 kind 5
    n_bl = sum(1 for nm in _CARDS if is_blacklisted(nm))
    n_bl_tbl = c.get(MODE_BLACKLIST, 0)
    # ★ 各档报的是**卡名数**(表是按卡名索引的,重名会折叠;总张数见 `_N_CARDS`)——
    #   所以这里一律写"个卡名",不写"张",免得读日志的人按张数对不上。
    k5_txt = ""
    if PLAY_TARGETS and KIND5_AS_BLACKLIST:
        k5_txt = f";其中 kind 5「选择一张手牌」{n_k5_in_bl} 个归黑名单"
    if PLAY_TARGETS:
        target_txt = (f"需要目标 {n_tgt} 个卡名(其中可打 {n_ok} 个;"
                      f"kind 7/两步卡不放行{k5_txt})")
    else:
        target_txt = (f"需要目标 {n_tgt} 个卡名"
                      f"(PLAY_TARGETS=False -> 这一档不打)")
    if PLAY_TARGETS and KIND5_AS_BLACKLIST:
        bl_txt = f"黑名单 {n_bl} 个卡名(表里 {n_bl_tbl} + kind 5 {n_k5_in_bl})"
    else:
        bl_txt = f"黑名单 {n_bl_tbl} 个卡名"
    return (f"指令卡:{n} 个卡名 / {_N_CARDS} 张(可直接打出 "
            f"{c.get(MODE_DIRECT, 0)} 个卡名 / {target_txt} / 抉择 "
            f"{c.get(MODE_CHOICE, 0)} 个卡名 / {bl_txt})—— 本局打「可直接打出」"
            + ("+「需要目标(kind 1~4/6)」两档" if PLAY_TARGETS else "这一档")
            + (";kind 5 按黑名单处理(不打 + 提示别带)" if PLAY_TARGETS
               and KIND5_AS_BLACKLIST else "")
            + ";抉择 / 三选一(kind 7)/ 两步(follow)/ 黑名单 一律不打" + warn)
