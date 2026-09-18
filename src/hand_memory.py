"""
hand_memory.py - 手牌记忆:跨回合记住手牌,**按【从左到右的次序】**,用来跳过已知的探针。

用户提的(2026-09-13):
> "新抽上来的手牌因为只能放在最右侧,理论上可以做个手牌记忆,搭配识别当前手牌量,
>   跳过已知手牌位置,减少识别速度。"

能省什么
--------
惰性扫描最贵的一次不是"出了一张牌",而是"**N 个探针全扫完、一张都出不起**"
(实测 6 张约 12~16s)。有了记忆,这一路只需要:
  量边缘(0.5s)+ **一次校验**(悬停+识别 ≈ 2s)+ 跳过其余全部 -> 约 2.5s。

为什么必须记"次序"而不是"x"
---------------------------
手牌是**居中扇形**:抽一张、出一张,所有牌的 x 都会平移(§7 第 25 条实测:
同一副手牌,悬停左边 x=367、悬停中间 x=394、光标在安全点 369)。
所以"第 3 个探针"这个**位置**是稳定的,而 x 不是。
`config/hand_layout.json` 里每一条(`count -> probes`)就是"每个张数下、从左到右的
探针 x 列表",于是 `记忆[i] <-> probes[i]`。

次序怎么对齐(只有三种事会发生)
------------------------------
1. **我们出掉一张**:我们自己知道出的是第几个 -> `note_played(i)` 把它从记忆里删掉;
2. **回合开始抽一张**:按用户说的规则**新牌一定在最右** -> 右边补一个 `None`(身份未知);
3. **别的原因少了一张**(对手让你弃牌等)-> 张数对不上 -> **失效**。
`reconcile()` 就是这三条的判据,**任何对不上都 fail-open**(退回老实扫一遍)。

风险与两条纪律(跳过悬停 = 不再当帧确认那张牌还在不在)
------------------------------------------------------
① **一次校验代替全部校验**:如果次序真的错位了(比如"弃一张 + 抽一张"这种
   张数不变、次序整体平移的情况),那么**每一个下标的身份都是错的** ——
   所以只要**随机校验一个我们本来打算跳过的那张**,就能抓到整体错位。
   校验点会逐回合轮换(`verify_cursor`),不会每次都盯同一张。
② **真要出的那张必须当帧确认**:记忆只用来"决定不去看哪些",**绝不用来决定拖哪里** ——
   要出牌时仍然老老实实悬停+识别,读到的东西和记忆对不上就当场失效、退回老实扫。
   于是"照旧记忆拖一个不存在的位置"这条风险从结构上被消掉了。

关掉它:`hand_scanner_v2.USE_HAND_MEMORY = False`(或 `main_loop --no-hand-memory`)。
"""

from __future__ import annotations


class HandMemory:
    """一手牌的"次序记忆" + 用来跳过探针的计划器(纯逻辑,不碰窗口/不碰 OCR)。"""

    # 一个回合里最多容忍"抽几张"——超过这个数就当成不可信(实测每回合就抽 1 张)
    MAX_DRAW_PER_TURN = 2

    def __init__(self, log=None):
        self.log = log
        # 每张:{'name','type','cost'} 或 None(= 知道有这么一张,但身份没读到)
        self.cards: list = []
        self.turn = -1
        self.valid = False
        self.reason = "还没扫过手牌"
        self.verify_cursor = 0
        self.stats = {
            "turns": 0,              # 记忆被使用的回合数
            "scans": 0,              # 用过记忆的扫描次数
            "skipped": 0,            # 一共跳过了多少个探针
            "saved_s": 0.0,          # 估算省下的秒数(每个探针按 PROBE_COST_S 算)
            "verify_ok": 0,          # 校验通过次数
            "verify_bad": 0,         # 校验抓到错位(失效)次数
            "invalid": 0,            # 因张数/次序对不上而失效的次数
        }

    # 一个探针的"悬停 + 等待 + 识别"大约多少钱(用来估算省了多少秒)。
    # 取 1.9s:实测悬停固定等待 0.5s(回安全点 0.2 + 悬停 0.3)+ `_classify` 约 1.4s。
    PROBE_COST_S = 1.9

    # ---------------------------------------------------------------- 生命周期
    def reset(self, why: str = "新的一局"):
        self.cards = []
        self.turn = -1
        self.valid = False
        self.reason = why
        self.verify_cursor = 0

    def invalidate(self, why: str):
        """记忆不可用(fail-open:调用方必须老老实实扫一遍)。"""
        self.valid = False
        self.reason = why
        self.stats["invalid"] += 1
        if self.log:
            self.log(f"[记忆] 失效:{why} -> 这一轮退回老实扫")
        return False

    # ------------------------------------------------------------------ 对齐
    def ok_for(self, count, allow_draw=False):
        """
        现在这一手有 `count` 张,记忆还能用吗?(不可用会顺手失效并写日志)

        判据(全部 fail-open):
          · 记忆空 / 张数读不到            -> 不可用
          · count == len(cards)            -> 可用
          · count == len+1..len+MAX 且 allow_draw -> 右边补 None(抽牌,身份未知)
          · 其它                            -> 失效
        """
        if not self.valid or not self.cards:
            return False
        if count is None:
            return False
        n = len(self.cards)
        if count == n:
            return True
        drawn = count - n
        if allow_draw and 1 <= drawn <= self.MAX_DRAW_PER_TURN:
            self.cards += [None] * drawn
            if self.log:
                self.log(f"[记忆] 回合开始抽了 {drawn} 张 -> 右端补 "
                         f"{drawn} 个未知(其余 {n} 张的身份不变)")
            return True
        self.invalidate(f"张数对不上(记忆 {n} 张,现在读到 {count} 张"
                        f"{';回合中途只可能因为出牌变少' if not allow_draw else ''})")
        return False

    # ------------------------------------------------------------------ 更新
    def note_scan(self, probed: dict, count):
        """
        把这一轮**真的探到**的结果写回记忆。`probed`: {下标: 卡} —— 没探的下标保留旧值。

        ★ 这是"跳过"能成立的前提:跳过的那些保持旧身份,探到的用新身份覆盖。
        ★★ 第一次扫描时记忆是**空的**,必须**当场铺出 N 个格子**再填 —— 否则
          "从没记过 -> 永远记不上"(`len(cards)=0 != count` 会被当成"没对齐"),
          实测就是这么让记忆一次都用不上的(2026-09-13 19:00 那一局日志里
          一条 `[记忆]` 都没有)。
        ★★★ 2026-09-13 深夜实机抓到的第二个同族 bug:**失效之后记忆再也活不过来**。
          `invalidate()` 只把 `valid` 置假、**保留** `self.cards`(旧身份),而这里
          只在"`cards` 是空的"时才重新铺格子 —— 于是张数一旦变过,后面每一次
          `note_scan` 都撞 `len(cards) != count` -> 又失效一次,**整局再也用不上**。
          实机账(20:50 那一局):第一次失效发生在 20:56:27,之后 6 次
          "扫描后发现张数变了"、**命中 0 次**(前面命中 5 次),白白多扫了 60 秒。
          ⇒ 判据改成"**没有记忆**(空)或者**这份记忆已经作废**"都重新铺。
        """
        if count is None:
            return
        if not self.cards or not self.valid:
            # 第一次扫(记忆是空的)/ 上一份记忆已经作废 -> 按当前张数重新铺一张空表
            self.cards = [None] * int(count)
        elif len(self.cards) != count:
            # 扫完发现张数变了(比如中途有牌被弃掉)-> 这一份记忆作废
            self.invalidate(f"扫描后发现张数变了(原来记 {len(self.cards)} 张,"
                            f"现在 {count} 张)")
            return
        filled = 0
        for i, card in (probed or {}).items():
            if not isinstance(i, int) or not (0 <= i < len(self.cards)):
                continue
            if card is None:
                continue
            self.cards[i] = {"name": card.get("name"), "type": card.get("type"),
                             "cost": card.get("cost")}
            filled += 1
        self.valid = True
        known = sum(1 for c in self.cards if c)
        self.reason = f"记着 {known}/{len(self.cards)} 张的身份"

    def note_played(self, index):
        """我们**确认出掉**了第 index 张 -> 从记忆里删掉(次序因此左移一位)。"""
        if not self.valid or not isinstance(index, int):
            return
        if 0 <= index < len(self.cards):
            gone = self.cards[index]
            del self.cards[index]
            if self.log:
                nm = (gone or {}).get("name") or (gone or {}).get("type") or "?"
                self.log(f"[记忆] 出掉了第 {index + 1} 张({nm})-> 记忆剩 "
                         f"{len(self.cards)} 张")

    # ------------------------------------------------------------------ 计划
    def plan(self, budget, deployable):
        """
        给这一轮扫描排个"计划":哪些下标**不用探**、哪些**必须探**、先出哪张、校验哪一张。

        返回 dict:
          probe    必须探的下标(身份未知的,或预算/类型没法判断的)
          skip     可以**跳过悬停**的下标(记忆里明确"出不起/不是单位")
          targets  记忆里"能出"的下标,按**便宜的先出**排好
          verify   校验点(优先挑一个本来要跳过的;没得挑就用第一个 target)
          saved    预计省下几个探针

        ★ 判据只用**记忆里已经有的**东西;`deployable` 由调用方给(保持"可部署类型"
          只有一处定义)。
        """
        probe, skip, targets = [], [], []
        for i, c in enumerate(self.cards):
            if not c:
                probe.append(i)                 # 身份未知 -> 只能去探
                continue
            ctype, cost = c.get("type"), c.get("cost")
            if ctype in deployable and cost is not None and cost <= budget:
                targets.append((i, cost))
            else:
                skip.append(i)                  # 明确出不起 / 不是单位 -> 跳过悬停
        targets.sort(key=lambda t: (t[1], t[0]))
        # 校验点怎么挑(决定了记忆划不划算):
        #   ① **优先挑一个"能出的"(target)** —— 那一张本来就要悬停,
        #      校验等于**免费**(跳过数全额省下);
        #   ② 没有 target 时才挑一个"本来要跳过的" —— 校验会吃掉一个跳过名额,
        #      所以只有 skip ≥ 2 才真的省(pool 里恰好 1 张时 saved = 0,
        #      调用方会因此**不用记忆**,见 `_memory_plan` 的 saved>0 闸);
        #   ③ 都只挑**身份已知**的(拿 None 校验等于白做)。
        pool = ([i for i, _ in targets if self.cards[i]]
                or [i for i in skip if self.cards[i]]
                or [i for i in probe if self.cards[i]])
        verify = pool[self.verify_cursor % len(pool)] if pool else None
        self.verify_cursor += 1
        saved = len(skip) - (1 if (verify in skip) else 0)
        return {"probe": probe, "skip": skip, "targets": targets,
                "verify": verify, "saved": max(0, saved)}

    def note_plan_used(self, saved_probes: int, verify_ok: bool):
        self.stats["scans"] += 1
        self.stats["skipped"] += max(0, saved_probes)
        self.stats["saved_s"] += max(0, saved_probes) * self.PROBE_COST_S
        if verify_ok:
            self.stats["verify_ok"] += 1

    def note_verify_bad(self):
        self.stats["verify_bad"] += 1

    # ------------------------------------------------------------------ 展示
    def describe(self) -> str:
        if not self.cards:
            return f"空({self.reason})"
        parts = []
        for c in self.cards:
            if not c:
                parts.append("?")
            else:
                parts.append(f"{c.get('name') or c.get('type') or '?'}"
                             f"({c.get('cost')})")
        st = self.stats
        return (f"{len(self.cards)} 张 [{' '.join(parts)}] "
                f"跳过 {st['skipped']} 探针/省约 {st['saved_s']:.0f}s "
                f"校验 {st['verify_ok']}✓/{st['verify_bad']}✗ 失效 {st['invalid']}")

    def short(self) -> str:
        """一行日志用的短描述。"""
        if not self.valid or not self.cards:
            return f"不可用({self.reason})"
        return f"记着 {len(self.cards)} 张"
