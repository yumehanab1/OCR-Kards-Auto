"""
orders.py - 指令卡「能不能打」的唯一来源(读 `config/order_plays.json`)。

为什么单独一个模块
------------------
指令卡以前是**一律跳过**的(`turn_engine.SKIP`),原因很实在:有些指令要你**选目标**,
而"选哪个"当时没有判据。2026-09-20 用户把 674 张指令/反制的打法**逐张**给出来了,
落在 `config/order_plays.json` 里,包括:

    direct      拖到中线以下就打出(和放单位一样)—— **第一版只做这一种**
    target      要先选目标(kind/rows 说明选什么;带 follow 的是两步)
    choice      抉择卡:打出后弹选项,按指定位置点
    blacklist   不打,并且要提示用户"别带这张"(惩戒那一族等)
    unsupported 其余(没给规格 / 不在白名单 / 反制)

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


def is_blacklisted(name: str) -> bool:
    """用户点名"别带这张"的牌(惩戒那一族)。"""
    return mode_of(name) == MODE_BLACKLIST


def playable(ctype: str, name: str) -> bool:
    """
    "这张牌现在允许被拖出去吗" —— **scanner 和 turn_engine 必须问同一个函数**。

    单位:认得出类型就行(能不能付得起由调用方按预算判);
    指令:**只放行 direct**(target/choice 要第二步操作,blacklist 用户明确要求别带)。
    其它(order 的其余档 / countermeasure / None)= 不放行(fail-closed)。
    """
    if not ctype:
        return False
    if ctype in ("infantry", "tank", "fighter", "bomber", "artillery"):
        return True
    if ctype in ("order", "counter", "countermeasure"):
        return is_direct(name)
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
    return (f"指令卡:{n} 个卡名 / {_N_CARDS} 张(可直接打出 {c.get(MODE_DIRECT, 0)} / 需要目标 "
            f"{c.get(MODE_TARGET, 0)} / 抉择 {c.get(MODE_CHOICE, 0)} / 黑名单 "
            f"{c.get(MODE_BLACKLIST, 0)})—— 本局只打「可直接打出」这一档{warn}")
