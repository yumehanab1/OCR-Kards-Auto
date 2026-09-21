"""
turn_engine.py - full automated turn handler (M3, integrated).

When main_loop classifies the screen as in_game, this engine runs a turn:
  1. Wait for OUR turn (end_turn button template present & clickable).
  2. Read our Kredits and scan the hand ONCE (hover-diff), caching the result.
  3. Deploy affordable units (cheap first); orders are played through
     `orders.playable()` - `direct` ones are dragged below the midline, `target`
     ones are dragged onto the target card itself (see `order_target.py`).
     Each card position is attempted at most once per turn.
  4. Click end turn.
  5. Return control; wait for opponent turn then next round.

Design notes (measured live, 2026-09-10):
  - A full hover scan costs ~0.75 s/probe of deliberate sleeps (0.35 s baseline
    settle + 0.4 s hover hold) plus ~1.5 s of RapidOCR per card found; a 6-card
    hand measured 90-105 s. That is affordable ONCE per turn, NOT after every
    deploy - so the scan result is cached for the whole turn.
  - When a card is deployed the hand fan shifts left, which invalidates the
    cached x positions. We keep dragging from the cached positions: KARDS
    accepts the drag while any card is under the cursor.

CRITICAL PRECONDITION: capture_client_bgr falls back to an mss screen grab
because PrintWindow returns black for this GPU-rendered window. That fallback
needs the game window VISIBLE and unobstructed. If KARDS is minimised or
covered, the capture returns whatever is on screen, hover-diff then reports
huge bogus panels (~1172x720) and the scanner invents cards. Do not trust a
run where the window was not in the foreground.

Why deploys failed in the first live run: we dragged cards we could not pay
for. KARDS silently refuses the deploy and leaves the card in hand. Hence the
affordability layer (kredits.py) - it reads "N K/M" and, when the numeral is
unreadable, learns a price cap from refused drags.

Heuristics (v1, safe):
  - deployable types: infantry, tank, fighter, bomber, artillery
  - orders: only what `orders.playable()` allows (direct + target kind 1~6);
    `choice` / blacklist / unsupported and target kind 7 / two-step cards are
    never dragged; counters (`countermeasure`) are never dragged either
  - never re-attempt a card position that already failed this turn
"""

from __future__ import annotations

import time

import cv2

from actions import click, park_cursor
from attack import Attacker, FrontMover
from deploy import drag_deploy, deploy_candidates
import orders                     # 指令卡"能不能打"的唯一来源(见 orders.playable)
import order_target               # target 指令"该往哪个坐标拖"的唯一来源(见那个模块)
import deploy as deploy_mod
from hand_scanner_v2 import HandScannerV2, diff_bbox
from hand_memory import HandMemory
import hand_scanner_v2 as hs_mod
from kredits import Affordability, KreditsTracker, read_kredits
import kredits as kredits_mod
from ui_state import match_one
from win import capture_client_bgr, client_to_screen
import board

# Types we are willing to drag onto the board (artillery IS a unit).
DEPLOYABLE = {"infantry", "tank", "fighter", "bomber", "artillery"}
# Types we never play in v1 (orders usually need targets; counters auto-trigger).
# ★★ 两套词汇:类型图标模板给的是 `counter`,而**卡库里存的是 `countermeasure`**
#   (实测 2026-09-11:`复仇` 查库回来 type='countermeasure',而同一张卡没读出名字时
#   图标给 'counter')。名字读得出的时候以库为准(§7 第 31 条),所以 `counter`
#   这个拼法在新卡组上**根本不会出现** —— 只登记一个就等于没登记。
#   这里的判据目前都是"正向白名单"(ctype in DEPLOYABLE),所以写漏一个是安全的
#   (fail-closed);但 `SKIP` 如果哪天被拿去当决策依据,漏这一个就会出错。
#: ★★ 2026-09-20:**指令卡不再是"一律跳过"了** —— 但只有"不需要选目标"的那一档
#:   (`orders.playable()`,判据来自 `config/order_plays.json`,用户逐张给的)。
#:   这个集合只留作**词汇参考/兜底**:实际判据一律走 `orders.playable()`,
#:   免得两处名单不一致(§7 第 60 条那两套词汇的教训)。
SKIP = {"order", "counter", "countermeasure"}

# End-turn button must match at least this well to count as "our turn".
END_TURN_MIN_SCORE = 0.60

# 一回合最多试几张"完全认不出来"的牌(name/type 都是空)。
# 这类牌只能靠试错确认,每试一次要花一次拖拽 + 一次面板比对(约 2 秒)。
# 上限是为了防止手牌识别整体崩掉时,把一手牌挨个瞎拖一遍。
MAX_UNKNOWN_TRIES = 3

# ★★★ 2026-09-13(第八个会话)**提速**:部署松手后、去读战场验证之前的等待(原 1.2s)。
#   动机(用户):"对局时间还是太长了,不够拟人" —— 实测我方**一个回合 30~101 秒**。
#   ★ 这条不能砍到 0:要等游戏把这次投放结算完,再去数卡/对账(否则会把"成功"读成"没变")。
#   ★ 改完必须实机复测:看 `部署被拒绝` / `卡数异常` 有没有变多。
DEPLOY_SETTLE = 0.6

# ★★ 2026-09-13(第十个会话):把"扫描前那一刻"的整帧留下来(每个回合最多一张)。
#   为什么非留不可:布局条目是按"光标停 SAFE_POINT、扇形未展开"时的两个边缘
#   匹配的,而 `shots/attack_frames` 里的帧**不是这个状态**(里面很多帧有牌被
#   悬停抬起)—— 拿它们验证几何会得出错误结论(我自己就先错过一次)。
#   这是唯一"测量条件对得上"的取证;顺便也能人眼核对"探针落在哪张牌上"。
DUMP_SCAN_FRAMES = True
DUMP_SCAN_MAX = 60          # 只留最新这么多张(和 attack_frames 一个规矩)

# 我方支援阵线最多放几个单位(用户确认)。线满了之后**即使费用充足也放不下**,
# 牌会留在手上 —— 实机整局验证时"开始几个回合有费用却放不下"就是这个原因,
# 不是 bug。所以本回合成功部署达到这个数就直接结束回合,不再白拖。
#
# ★ 取"场上卡数"和"本回合已部署数"的**较大值**:前者被实测证明会抖动
#   (漏读整行 -> 以为线还空着 -> 继续白拖,用户看到的就是"又乱部署了"),
#   后者只依赖"我们自己的动作",不会漏。
SUPPORT_LINE_MAX = 4

# ★★★ 2026-09-13(第九个会话,用户要求):**手牌多的时候不必把费用用完**。
#
# 用户原话:"不一定非要把费用用完,部署一两个之后直接停止识别后面的手牌
# 进入下一回合,手牌多的时候可以用这一点缩短时间。"
# 选定的规则:**手牌 ≥ BIG_HAND_MIN 张时,本回合最多部署 BIG_HAND_MAX 个**。
#
# 为什么这条能省时间(机理):惰性扫描**每出一张牌都要重扫一次**
# (扇形位移 -> 缓存作废),一次 3~9 秒。少出两张 = 少两次扫描。
# ★ 它**只在大手牌时**生效:手里只有 3 张时照旧把费用用干净,
#   免得为了省几秒把场面铺薄、反而拖长整局。
BIG_HAND_MIN = 5            # 手牌到这么多张才算"多"
BIG_HAND_MAX_DEPLOYS = 2    # 大手牌时本回合最多部署几个

# ★★★ 2026-09-13(用户要求):**剩余费用不足这个数时,别再扫手牌了** ——
#   直接结束回合,省掉一次 3~9 秒的惰性扫描。
#   用户原话:"剩余费用小于 2 时可以放弃识别手牌进下一回合。"
#   ★ 代价:手里若只有 1 费牌,这一回合就不出了(用户明确接受这个取舍)。
#   ★ 设为 1 就退回老行为(只在"真的一点钱都没有"时才不扫)。
MIN_KREDITS_TO_SCAN = 2

# ★★★ 2026-09-13 深夜(实机 J4):**判"部署被拒绝"之前,给画面数字的刷新留时间。**
#   画面上的费用数字刷新得比我们读它慢,于是"读数 == 账本 + 这张卡的费"这条
#   看起来很硬的"牌回手"判据,其实分不清"牌真回手了"和"数字还没刷新"。
#   实机原文(21:43:30):`**部署被拒绝**(费用读数 2 与账本 1 不符(读数可疑;
#   原始读数序列 [2, 2]);战场卡数没变(6->6))`,而同一局里 21:12:45 / 21:28:32
#   两次**同样形状**的读数其实是**部署成功**。
#   → 只在这一档(读数一点没动)等一下再读一次;设 0 退回老行为。
DEPLOY_KREDITS_RECHECK_S = 1.5

# 费用未知的牌,记这么一笔账(保守:按最低费算)。以前未知费用一律不设限,
# 那些牌会把预算吃穿 —— 用户观察到的"没费用还在部署"就有这一份。
MIN_UNKNOWN_COST = 1

# ★★ 历史遗留,已经**不再参与任何判断**(2026-09-12)。
#   它原来是"要不要相信场上卡数读数"的闸,默认 False —— 因为 `count_row`/
#   `battlefield_snapshot["our_support"]` 数的是**那一行有几张卡**,会把
#   地形装饰算进去(实测"我支援 10/4"),于是线永远判成满、一张牌都不出。
#   现在这个位置由 `snapshot["our_support_units"]`(徽章数,**不含总部**)接替:
#   它自带两个 fail-closed 出口(读不到我方那一行 / 数出 >4 都返回 None),
#   所以不需要一个全局开关了。保留这个名字只为日志/测试里还能引用到它。
TRUST_FIELD_COUNT = False


class TurnEngine:
    def __init__(self, hwnd, templates, log=print, debug=False,
                 record_kredits=False, use_fast=False, attack=True,
                 lazy_scan=True):
        self.hwnd = hwnd
        self.templates = templates
        self.log = log
        self.debug = debug
        self.record_kredits = record_kredits
        self.use_fast = use_fast     # 用校准好的坐标表直扫(失败会自动回退盲扫)
        self.attack_enabled = attack  # M4:出完牌后让我方单位打敌方总部
        # ★ 惰性扫描:找到第一张出得起的牌就停(默认开)。
        #   实测瓶颈是**探针数**(每个 0.5s 固定等待):全量扫整手牌 14 秒,
        #   而"找到第一张能出的"通常只要前几个探针(2-3 秒)。
        self.lazy_scan = lazy_scan
        self.scanner = HandScannerV2(hwnd, templates)
        # ★★★ 2026-09-13(第十个会话):**手牌记忆** —— 跨回合按"从左到右的次序"
        #   记住手牌,下一轮跳过那些已知"出不起/不是单位"的探针(用户提的第三个优化)。
        #   规则、风险、两条纪律全在 `hand_memory.py` 的文档里;开关
        #   `hand_scanner_v2.USE_HAND_MEMORY`(或 `main_loop --no-hand-memory`)。
        self.memory = HandMemory(log=log)
        self.scanner.memory = self.memory
        self._scans_this_turn = 0     # 本回合扫过几次(第 1 次才允许"抽牌补位")
        self.afford = Affordability()
        # ★ 费用读数去抖(见 kredits.KreditsTracker 的文档)。
        #   实测同一秒内会在 unknown / 5 之间来回跳,而"费用未知"会连锁触发
        #   全量扫描(14 秒)并常常扫回 0 张牌 -> 整回合不出牌。
        #   capture 用 lambda 是为了拿到**当前**的 self.hwnd
        #   (main_loop 是先构造引擎、再挂 hwnd 的)。
        self.kredits = KreditsTracker(
            capture=lambda: capture_client_bgr(self.hwnd),
            read_one=self._read_kredits_raw, log=log, debug=debug)
        self.kredits_info = None     # 本回合费用的读取详情(日志/诊断用)
        self.attacker = Attacker(hwnd, log=log, debug=debug,
                                 templates=templates)
        # ★★★ 2026-09-12:新增"上前线"阶段 —— 用户确认的顺序是
        #   "先能打相邻战线 -> 才能清掉前线 -> 才能上前线";
        #   实机上一局 12 个攻击阶段一次都打不出去,原因就是**没有这一步**
        #   (步兵/坦克在支援线上够不着任何东西,前线又空着)。
        self.front_mover = FrontMover(hwnd, log=log, debug=debug,
                                      templates=templates)
        self.failed_x = set()        # positions already attempted this turn
        self.attempted_x = set()     # every position we dragged from
        self.deployed_this_turn = 0  # 本回合"确认成功"的部署数(用战场卡数确认)
        self.deploy_refused = 0      # 本回合被拒绝的拖拽数(战场卡数没变)
        self.unknown_tried = 0       # 本回合试过的"完全认不出"的牌数
        self.hand_at_turn_start = 0
        #: 黑名单卡只提醒一次(整个进程一次就够;它是"卡组建议",不是每回合的状态)
        self._blacklist_warned = False
        # ★★★ 2026-09-13(用户要求,第九个会话):阶段顺序改成
        #   wait_our_turn -> attack -> move_front -> play -> end_turn
        #   —— **先让场上已有的单位行动,最后才部署手牌**。
        #   机理:**行动也要花 Kredits**(§7 第 74 条:钱一归零,全场徽章一起变灰),
        #   旧顺序(wait -> play -> attack -> move_front -> end)先把钱花在部署上,
        #   于是"钱花光了,单位就打不动了" —— 用户看到的正是这个。
        #   ★ 攻击仍然排在上前线之前:移动会消耗单位的行动,
        #     能打的先打(打了就变灰、不会被选去移动),打不到的才挪上去。
        self.phase = "wait_our_turn"
        self.cards = []              # cached scan result for this turn
        self._scan_count = 0
        self.attacked_this_turn = 0
        self.moved_this_turn = 0          # 本回合成功上前线的单位数
        self.field_at_turn_start = None   # 回合开始时的战场快照
        self.field_now = None             # 最近一次战场快照
        self.kredits_left = None          # 本回合剩余预算(自己记的账)
        self._scanned_full_this_turn = False   # 本回合是否已做过全量扫描
        self.hand_count_this_turn = None  # ★ 本回合锁定的手牌张数(见 _hand_count)

    # --- helpers ---
    def _end_turn_region(self, frame):
        """Return (score, region) for the end-turn button on this frame."""
        return match_one(frame, self.templates["end_turn_btn"])

    def _end_turn_visible(self, frame=None):
        if frame is None:
            frame = capture_client_bgr(self.hwnd)
            if frame is None:
                return False
        s, _reg = self._end_turn_region(frame)
        return s >= END_TURN_MIN_SCORE

    def reset_turn(self):
        self.failed_x = set()
        self.attempted_x = set()
        self.deployed_this_turn = 0
        self.deploy_refused = 0
        self.unknown_tried = 0
        self._blacklist_warned = False       # 新一局重新提醒一次(换牌=换卡组)
        self.attacked_this_turn = 0
        self.hand_at_turn_start = 0
        self.cards = []
        self.field_at_turn_start = None
        self.field_now = None
        self.kredits_left = None
        # 本回合是否已经做过一次全量扫描(防止费用读数抖动导致重复全量扫)
        self._scanned_full_this_turn = False
        # ★ 手牌记忆:第 1 次扫描才允许"右端补未知"(回合开始的抽牌)
        self._scans_this_turn = 0
        # ★ 新回合 = 重新量一次手牌张数(见 _hand_count 的"锁住第一次读数")
        self.hand_count_this_turn = None
        # ★ 注意:下面两样都**不清空** ——
        #   self.kredits_info 是"最近一次费用读取详情",纯诊断,留着便于回合
        #     结束后回看这一回合到底读到了什么(source=agree/prev/estimate)。
        #   self.kredits(KreditsTracker)的跨回合记忆(上回合读到多少、现在是
        #     第几个回合)正是去抖兜底要用的东西。
        self.afford.reset_turn()
        self.attacker.reset_turn()
        self.front_mover.reset_turn()
        self.phase = "wait_our_turn"

    # --- window / frame helpers -------------------------------------------
    def _read_kredits_raw(self, frame):
        """
        读一帧(可能失败 -> None)。抽成方法是为了:
          * 保持"测试里替身 `turn_engine.read_kredits`"这条既有接缝有效
            (KreditsTracker 通过它调用,替身照样生效);
          * 一次识别异常不该弄崩一个回合。
        """
        try:
            return read_kredits(frame, record_samples=self.record_kredits)
        except Exception as e:
            if self.debug:
                self.log(f"[turn] kredits read failed: {type(e).__name__}: {e}")
            return None

    def _current_kredits(self, frame):
        """
        读我方费用。★ 带跨帧去抖 + 跨回合合理性检查(KreditsTracker)。

        为什么不能只读一帧:实测同一秒内会在 unknown 和 5 之间来回跳,而
        "费用未知"会连锁触发全量扫描(14 秒,还常常扫回 0 张牌)。多花
        0.1-0.4 秒换来一个可信的数,是这一整条链上最划算的一笔。

        返回 int 或 None;详情记在 self.kredits_info 里供日志与诊断。
        """
        info = self.kredits.read_turn_start(frame)
        self.kredits_info = info
        # ★★★ 2026-09-13 晚:读不出数字时,把**读数器自己说的原因**一起带上。
        #   `kredits.LAST_REJECT` 由最近一次 `read_kredits` 写(每次调用先清空),
        #   所以它说的就是**这一次**为什么没给数 —— 例如"只切出一个字形、
        #   高度却只有两位数尺度,判为圈漏了第二个字,不猜"。
        #   没有这一行的话,"读不到"在日志里永远长得一样,事后查不出是哪一条判据挡的。
        if not info.get("reader_reject") and kredits_mod.LAST_REJECT:
            info["reader_reject"] = kredits_mod.LAST_REJECT
        value = info["value"]
        # ★ 只有**真的读出来**的值才喂给 Affordability(那是"从实测学到的
        #   上限");推断值只用来做本回合的预算账本,不污染学习层。
        if info["measured"] and value is not None:
            self.afford.note_read(value)
        return value

    # --- 回合预算(用户指出的"没费用还在部署") ---
    def _budget(self, cost, unknown_cost=1):
        """
        这笔费用付得起吗?**并且真的扣掉**。

        为什么要有这个:实测"部署成功"的判据会把被拒绝的部署误报成成功,
        于是 `afford.note_deploy_ok` 每次都把上限清空,引擎就以为费用一直够,
        一个回合里连着拖 —— 用户看到的就是"明明没费用还在乱部署"。
        所以这里改成**自己记一笔账**:

            kredits_left = 回合开始读到的费用
            每次拖牌按卡的费用扣减(费用未知时按 MIN_UNKNOWN_COST 保守扣)

        这个账本只依赖"我们读到的费用"和"卡的费用",不依赖任何容易误判的
        视觉判据,所以不会像面板/卡数判据那样被骗。
        """
        if cost is None:
            cost = unknown_cost
        if not self.afford.can_afford(cost):
            return False
        if self.kredits_left is not None and cost > self.kredits_left:
            return False
        return True

    def _spend(self, cost, unknown_cost=1):
        if self.kredits_left is None:
            return
        self.kredits_left -= (unknown_cost if cost is None else cost)
        if self.kredits_left < 0:
            self.kredits_left = 0

    def _panel_at(self, x):
        """
        Capture the hover panel for hand card at client x, or None when no
        panel is showing. Kept for diagnostics; NOT used to verify deploys
        (see _verify_deploys for why it cannot work).
        """
        self.scanner._move(*self.scanner.safe)
        time.sleep(0.2)
        base = capture_client_bgr(self.hwnd)
        self.scanner._move(x, self.scanner.y)
        time.sleep(self.scanner.hold)
        hov = capture_client_bgr(self.hwnd)
        box = diff_bbox(base, hov)
        if box is None:
            return None
        bx, by, bw, bh = box
        return hov[by:by + bh, bx:bx + bw]

    def _scan(self):
        """Scan the hand once and cache it for this turn."""
        self._scan_count += 1
        t0 = time.time()
        if self.use_fast:
            self.cards = self.scanner.scan_fast(debug=self.debug)
        else:
            self.cards = self.scanner.scan(debug=self.debug)
        self.hand_at_turn_start = len(self.cards)
        # ★★ 手牌记忆:**全量扫描这一路不动记忆,直接作废**。
        #   为什么不做"按结果顺序写回":`scan_fast` 内部会按命中率挑候选、
        #   还会把落在同一张牌上的相邻探针去重,所以"结果个数 == 手牌张数"
        #   这件事**没有保证**;一旦中间某张被漏掉,记忆的次序就会**整体错位**,
        #   而错位只靠"校验一个点"不一定抓得到(漏掉的那张如果在校验点之后)。
        #   全量扫描本来就是罕见路径(费用读不出来时才走),作废的代价只是
        #   下一回合重建一次记忆。
        if self.memory.cards:
            self.memory.invalidate("本回合走了全量扫描(次序没法保证)")
        # Remember each card slot's panel so a later drag can be compared
        # against exactly the same position.
        for c in self.cards:
            c["_before"] = self._panel_at(c["x"])
        # ★ 扫回 0 张时必须说出【倒在哪一条回退分支上】。
        #   实测日志以前只有 `hand scan #10: 0 cards in 0.8s ->`,0.8 秒明显
        #   没真扫,却完全指不出原因(没布局表/测不到边缘/边缘超容差/命中率低/
        #   鼠标被移走)。原因由扫描器写在 last_reason 里。
        why = getattr(self.scanner, "last_reason", None)
        tail = f" | 原因: {why}" if (not self.cards and why) else ""
        self.log(f"[turn] hand scan #{self._scan_count}: {len(self.cards)} cards "
                 f"in {time.time() - t0:.1f}s -> "
                 + ", ".join(f"{c.get('name') or c.get('type')}({c.get('cost')})"
                             for c in self.cards) + tail)
        return self.cards

    def _lazy_find_playable(self):
        """
        ★ 惰性扫描(用户的想法):只找到**第一张现在出得起的牌**就停。

        和 `_scan()` 的区别:`_scan` 把整手牌全读一遍(5 张牌约 14 秒),
        而这里通常只要读前几个探针(约 2-3 秒)。

        返回一张卡 dict 或 None。会把它塞进 `self.cards` 供后续复用。
        """
        budget = self.kredits_left
        if budget is None:
            # 费用读不到时不知道出得起什么 —— 退回全量扫描,**但一回合只扫一次**。
            # ★ 实测踩过的坑:费用读数会抖,于是每一轮 think() 都判"费用未知"
            #   又重新全量扫一遍(15 秒 x N),一整回合全耗在扫描上。
            if self._scanned_full_this_turn:
                self.log("[turn] 费用仍未知,但本回合已全量扫过 -> 直接用上次结果")
                return None
            self.log("[turn] 费用未知 -> 惰性扫描无法判断,改用全量扫描"
                     "(本回合只扫这一次)")
            self._scan()
            self._scanned_full_this_turn = True
            return None
        t0 = time.time()
        edge, right = self.scanner.measure_edges()
        if edge is None:
            if self._scanned_full_this_turn:
                return None
            self.log("[turn] 惰性扫描:测不到扇形左边缘,改用全量扫描")
            self._scan()
            self._scanned_full_this_turn = True
            return None
        # ★★ 2026-09-13(第十个会话):**把"测量条件"那一帧留下来**。
        #   为什么非留不可:布局条目是按"光标停 SAFE_POINT(扇形未展开)"时的
        #   两个边缘匹配的,而 `shots/attack_frames` 里那些帧**不是**这个状态
        #   (实测里面很多帧有牌被悬停/抬起)—— 拿它们验证几何会得出错误结论
        #   (我自己就先下过一个错的结论)。这一帧是**唯一对得上的取证**。
        if DUMP_SCAN_FRAMES:
            self._dump_frame("scan", f"L{edge}R{right}",
                             subdir="scan_frames", cap=DUMP_SCAN_MAX)
        # ★★★ 手牌记忆:第 1 次扫描才允许"右端补未知"(回合开始的抽牌);
        #   同一回合后面的扫描只可能因为**我们出牌**变少 —— 那时张数对不上就是
        #   记忆坏了,必须失效(见 hand_memory.ok_for)。
        allow_draw = (self._scans_this_turn == 0)
        cards, cost = self.scanner.find_playable(
            [budget], edge=edge, right=right, exclude=set(self.attempted_x),
            debug=self.debug, allow_draw=allow_draw)
        self._scans_this_turn += 1
        self._scan_count += 1
        # ★ 把这一轮**真的探到**的结果写回记忆(跳过的那些保留旧身份)。
        self._memory_note_scan()
        if not cards:
            why = getattr(self.scanner, "last_reason", None)
            self.log(f"[turn] 惰性扫描 #{self._scan_count}: "
                     f"{time.time() - t0:.1f}s 内没找到出得起的牌"
                     f"(预算 {budget}) | {self._layout_text()}"
                     + (f" | 原因: {why}" if why else "")
                     + self._memory_text())
            # ★★ 2026-09-13(第十个会话):**把没选中的那些牌也写出来**。
            #   用户的报障"38t 扫到了却跳过部署 / 有费用却没下"在旧日志里
            #   只有上面这一句 —— 看不出是哪张牌、卡在哪一条判据上
            #   (类型没认出?费用没读出?费用超预算?)。
            seen = getattr(self.scanner, "last_probe_seen", None)
            if seen:
                self.log("[turn]   探针逐个读到的: " + self._probes_text(seen)
                         + f"(预算 {budget})")
            # 这一轮已经扫过一遍了 —— 同一回合不要再扫第二次
            # (否则每轮都"没找到"就每轮重扫,把回合时间耗光)。
            # 费用读不到时会走上面的全量扫描分支,所以这里主要是"预算内确实
            # 没有出得起的牌"这一种情况(比如费用只剩 0)。
            self.cards = []
            self._scanned_full_this_turn = True
            return None
        card = cards[0]
        self.cards = [card]
        # ★★ 2026-09-13(第十个会话):惰性模式**也有**基准面板了 ——
        #   扫描时悬停那一帧里就裁着一张牌的放大面板(`card["panel"]`),
        #   直接拿来当 `_before`(不额外花时间)。
        #   旧代码这里写死 None,于是最后那条退路
        #   `_panel_looks_same(None, X)` 恒为 False -> `ok = not False = True`
        #   —— **面板判据在惰性模式下永远报"成功"**(和它自己上面那段
        #   "有意的保守"注释正好相反)。实机证据见 `hand_scanner_v2` 里的说明。
        card["_before"] = card.pop("panel", None)
        self.hand_at_turn_start = max(self.hand_at_turn_start, 1)
        self.log(f"[turn] 惰性扫描 #{self._scan_count}: {time.time() - t0:.1f}s "
                 f"就找到可出的牌 -> "
                 f"{card.get('name') or card.get('type')}({card.get('cost')}) "
                 f"@x{card['x']}(预算 {budget}) | {self._layout_text()}"
                 + self._memory_text())
        return card

    # ------------------------------------------------------------ 手牌记忆(引擎侧)
    def _memory_note_scan(self):
        """
        把本轮探到的结果并回记忆:`{下标: 卡}` -> `memory.note_scan`。

        ★ 下标从 `scanner.last_probe_seen` 来(每个探针都带 `i` = 从左到右第几张)。
          同一个下标探了多次(相邻探针落在同一张牌上)时,以**最后一次有名字的**为准。
        """
        try:
            seen = getattr(self.scanner, "last_probe_seen", None) or []
            count = getattr(self.scanner, "last_hand_count", None)
            probed = {}
            for s in seen:
                if not s.get("panel"):
                    continue
                i = s.get("i")
                if i is None:
                    continue
                if s.get("name") or s.get("type") or s.get("cost") is not None:
                    probed[i] = {"name": s.get("name"), "type": s.get("type"),
                                 "cost": s.get("cost")}
            if probed:
                self.memory.note_scan(probed, count)
        except Exception as e:                    # 记忆坏掉绝不许弄崩一个回合
            self.log(f"[记忆] 回写失败({type(e).__name__}: {e})-> 这一轮不用记忆")

    def _memory_text(self):
        """一行日志用的记忆状态(没用上就是空字符串)。"""
        plan = getattr(self.scanner, "last_memory", None)
        if not plan:
            return ""
        return (f" | 记忆:{self.memory.short()} 跳过 {len(plan.get('skip') or [])} "
                f"必探 {len(plan.get('probe') or [])} "
                f"候选 {[i + 1 for i, _ in (plan.get('targets') or [])]}")

    # ---------------------------------------------------------------- 诊断文本
    def _layout_text(self):
        """
        "这次用了哪条布局表条目" —— 一句话写清楚,便于事后判对/判错。
        (左边缘只能区分到 ±22px,"5 张"和"6 张"两条是会重叠的,所以**必须**写出来。)
        """
        lay = getattr(self.scanner, "last_layout", None)
        if not lay:
            return "布局: 未知"
        if lay.get("count") is None:
            return (f"布局: 表里没有对得上的条目(量到左边缘 "
                    f"{lay.get('measured_edge')},右边缘 "
                    f"{lay.get('measured_right')},容差 "
                    f"{getattr(hs_mod, 'LAYOUT_EDGE_TOL', '?')})")
        runners = lay.get("runner") or []
        run_txt = ("  次选 " + " ".join(
            f"{r['count']}张(L{r['res_l']}/R{r['res_r']})" for r in runners)
            if runners else "")
        # ★★★ 2026-09-13 深夜:用**右边缘**挑的条目要写明理由 ——
        #   否则日志里只看到"选了 8 张",看不出它凭什么(判据跟结论写在一起)。
        via = ("  ★按右边缘挑(左边缘左边有被跳过的窄段:最左那张牌被花纹切碎)"
               if lay.get("via") == "right"
               else ("  ⚠️左边缘可疑(左边有被跳过的窄段)" if lay.get("left_suspect")
                     else ""))
        return (f"布局「{lay['count']} 张」(表内左 {lay['left_edge']},"
                f"量到 L{lay.get('measured_edge')}/R{lay.get('measured_right')};"
                f"选中那条残差 L{lay.get('res_l')}/R{lay.get('res_r')};"
                f"{lay.get('n_probes')} 探针;"
                f"容差内还有 "
                f"{[c for c in (lay.get('cand_counts') or []) if c != lay['count']]})"
                + via + run_txt)

    @staticmethod
    def _probes_text(seen):
        """
        把 `last_probe_seen` 压成一行人话(太长就截断)。

        ★★★ 2026-09-19(实机第二局补):**费用读不出来的那些,要把"OCR 到底看到了什么"
          一起写出来。** 起因:用户报"那个喷火从头到尾就没打出过",而日志里那几行只有
          `x466=fighter(fighter/None,✗)` —— 看得出"没读到",**看不出卡在哪一级**
          (名字 OCR 读成了什么?徽章兜底为什么说 no-badge?卡名压根没进中线带?)
          于是只能靠猜。这一行以后会把 OCR 原文和费用来源一起摊开,
          下次实机就能当场判"是名字读歪了"还是"徽章读不着"。
        """
        parts = []
        for s in seen[:8]:
            if not s.get("panel"):
                parts.append(f"x{s['x']}=无面板")
                continue
            nm = s.get("name") or s.get("type") or "?"
            mark = "✓" if s.get("playable") else "✗"
            txt = f"x{s['x']}={nm}({s.get('type')}/{s.get('cost')},{mark})"
            if s.get("cost") is None:
                # 只在"读不出费用"时追加证据(读出来的那些没必要占地方)
                ev = []
                if s.get("cost_source"):
                    ev.append(str(s["cost_source"]))
                else:
                    ev.append("徽章=无")
                if s.get("ocr"):
                    ev.append(f"OCR={s['ocr']!r}")
                elif s.get("ocr_lines"):
                    ev.append(f"OCR行={s['ocr_lines']}")
                else:
                    ev.append("OCR=空")
                if s.get("name_tier"):
                    ev.append(f"名字级={s['name_tier']}")
                if s.get("icon_score") is not None:
                    ev.append(f"图标={s['icon_score']}")
                txt += "{" + " ".join(ev) + "}"
            parts.append(txt)
        if len(seen) > 8:
            parts.append(f"…共 {len(seen)} 个")
        return " ".join(parts)

    @staticmethod
    def _ident_text(target):
        """
        ★★ 2026-09-13(第十个会话):**"凭什么认定它是这张牌"**。

        旧日志只写结论(`deploying Fw 190 A 百舌鸟 (fighter, cost 6)`),
        于是**判错和判对长得一模一样** —— 这一局第 6/7 回合写成"百舌鸟"、
        费用却只掉了 3(实际拖走的是邻居那张 3 费牌),光看日志完全分不出来。
        这里把识别链上每一级的证据都摊开:
          卡名匹配级别(哪一级命中)/ 费用来源(查库还是徽章兜底)/
          类型图标分(7 个模板里谁赢、赢多少)/ 指纹库距离 / 用的哪块窗口。
        """
        info = target.get("info") or {}
        bits = []
        if info.get("name_tier"):
            bits.append(f"名字={info['name_tier']}")
        if info.get("ocr"):
            bits.append(f"OCR原文={info['ocr']!r}")
        if info.get("icon_score") is not None:
            bits.append(f"图标分={info['icon_score']}")
        if info.get("cost_source"):
            bits.append(f"费用来源={info['cost_source']}")
        elif info.get("cost") is not None and not info.get("name"):
            bits.append("费用来源=查库(名字已认出)")
        if info.get("hash_hit_distance") is not None:
            bits.append(f"指纹库命中(距 {info['hash_hit_distance']})")
        if info.get("ocr_window"):
            bits.append(f"窗口={info['ocr_window']}")
        if not info.get("name"):
            bits.append("**卡名没读出**")
        return "识别依据[" + " ".join(bits or ["无(类型是猜的)"]) + "]"

    def _dump_drag_frame(self, name, target):
        """
        按下之后立刻存一帧 —— **"到底抓了哪张牌"的地面真值**。

        机理:按下后光标上挂着被拖起来的那张牌(KARDS 会把它画得很大、跟着光标),
        所以这一帧里**看得见真身**。离线把这张图和日志里那行
        `deploying <识别到的名字>` 一对照,就能证明/证伪"识别到 A、抓走的是 B"。

        ★ 只有这个位置能取到真值:松手之后牌已经在盘面上了,分不出"本来是手里哪一张"。
        ★ 存盘失败绝不许弄崩拖拽(在 `actions.move_drag` 里已经包了 try)。
        """
        self._dump_frame(f"x{target.get('x')}", name)

    def _dump_frame(self, tag, name="", subdir="deploy_drag", cap=None):
        """
        存一帧到 `shots/<subdir>/`,标签写在图上(取证用,**永不抛出**)。

        `cap` 给了就只留最新的这么多张(和 `attack.py` 的 `DUMP_MAX_FRAMES`
        一个规矩:观察窗够用就行,别把磁盘塞满)。
        """
        try:
            import datetime
            import os
            frame = capture_client_bgr(self.hwnd)
            if frame is None:
                return
            d = os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "shots", subdir)
            os.makedirs(d, exist_ok=True)
            ts = datetime.datetime.now().strftime("%m%d_%H%M%S")
            name_tag = f"{ts}_{tag}"
            out = os.path.join(d, name_tag + ".png")
            cv2.putText(frame, f"{tag} {name}", (8, 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2, cv2.LINE_AA)
            cv2.imwrite(out, frame)
            if cap:
                files = sorted((os.path.join(d, f) for f in os.listdir(d)
                                if f.endswith(".png")), key=os.path.getmtime)
                for old in files[:-cap]:
                    os.remove(old)
            self.log(f"[turn]   存帧 -> shots/{subdir}/{name_tag}.png")
        except Exception as e:                       # 诊断只许丢一行日志
            self.log(f"[turn]   存帧失败({type(e).__name__}: {e})")

    @staticmethod
    def _panel_looks_same(before, after):
        """
        True when a card position looks untouched by the drag.

        `before` is the panel captured during the scan for this exact position
        (see _scan's _before annotation); `after` is the panel right after the
        drag. Both None means we never saw a panel - treat as unchanged
        (no evidence the deploy happened).
        """
        if before is None and after is None:
            return True
        if before is None or after is None:
            return False
        if before.shape != after.shape:
            return False
        return float(cv2.absdiff(before, after).mean()) <= 12.0

    def _verify_deploys(self):
        """
        One whole-hand scan to find out how many cards actually left the hand.
        Returns (started, now, left). Only used by diagnostics: it costs a full
        scan (~90s live) so the turn decision relies on the per-deploy panel
        check instead.

        Note: the scanner de-duplicates identical cards, so `left` is a lower
        bound on the real number of deploys.
        """
        after = self.scanner.scan()
        self._scan_count += 1
        now = len(after)
        left = max(0, self.hand_at_turn_start - now)
        return self.hand_at_turn_start, now, left

    # --- 战场读数(判定"部署到底成没成功") ---
    def _field(self, frame=None, park=False):
        """
        读一次战场:四条线的卡数 + 合计。

        ★ 这是"部署成功"的**真判据**。之前用的是"同一个手牌位置的面板前后
        对比"(`_panel_looks_same`),实机证明它会把**被拒绝的部署**判成成功:
        用户观察到"乱拖了好多次""很多次部署失败都是因为支援阵线已满",
        而日志里每回合都报"成功部署 4 个"。
        场上卡数变化骗不了人 —— 部署真的成功就一定多一张卡。

        ★★★ 2026-09-12(第七个会话第三局)`park=True`:**读之前先把光标停到
        SAFE_POINT**。攻击/上前线那两个阶段早就这么做了(§7 第 72 条 ③),
        而**部署这一路漏了** —— 实测日志里 `落点参考行: **读不到我方那一行**`
        一共 4 次,**每一次都紧跟在 `惰性扫描 #N: … 就找到可出的牌` 后面**:
        扫描刚把光标停在手牌上、**放大悬停面板还挂在屏幕上**,而那个面板正好盖住
        **我方支援线那一行**(`deploy_probe/f052.png` 那一帧就是活证据)——
        于是那一行整条读不出来,落点只能退回兜底常数 y=500。
        """
        if park:
            try:
                park_cursor(self.hwnd)
            except Exception:
                pass
        if frame is None:
            frame = capture_client_bgr(self.hwnd)
        if frame is None:
            return None
        snap = board.battlefield_snapshot(frame, debug=self.debug)
        if snap is None:
            return None
        snap["frame"] = frame
        return snap

    @staticmethod
    def _field_delta(before, after):
        """
        (总卡数变化, 我方支援线变化)。任一快照缺失时返回 (None, None)。
        """
        if before is None or after is None:
            return None, None
        return (after["total"] - before["total"],
                after["our_support"][0] - before["our_support"][0])

    def _kredits_now(self, tries: int = 3, gap: float = 0.25):
        """
        回合**中途**读一次当前剩余费用(用于确认这次部署)。

        ★ 不能用 `self.kredits.read_turn_start()`:那个类带**跨回合**合理性检查
          (R2:剩余费用不可能比上次采用值低),而回合中途费用**本来就是往下走的**
          —— 拿它来确认部署,正好会把我们要找的那个"下降"判成误读。
          所以这里用**原始读取 + 两帧一致**自己抖一次(和 tracker 的 R1 同一个思路)。

        ★★ 2026-09-13(第十个会话):把**每一次原始读数**记进 `self._kredits_samples`。
          为什么必须留:§7 第 66 条早就记过"费用对账会读到滚动中的中间值"
          (`费用读数 3 与账本 1 不符`),而**日志里只有最终采用的那一个数**,
          事后完全分不清"画面真的显示 3"和"读数在动画中间抖了一下"。
          实机第 6/7 回合两次"读数 3 与账本 0/1 不符"就要靠这一串数字定性:
            · `[3, 3]` -> 画面稳定显示 3 -> 那时**确实花掉了 3 费**(抓错牌的嫌疑大增);
            · `[6, 3]` / `[3, 4]` -> 读数在动 -> 是滚动中间值(判据不可信)。
        """
        last = None
        samples = []
        for _ in range(max(1, tries)):
            frame = capture_client_bgr(self.hwnd)
            if frame is not None:
                v = self._read_kredits_raw(frame)
                if v is not None:
                    samples.append(v)
                    if last is not None and v == last:
                        self._kredits_samples = samples
                        return v
                    last = v
            time.sleep(gap)
        self._kredits_samples = samples
        return last

    def _kredits_recheck(self):
        """
        判"部署被拒绝"之前,等一会儿再读一次费用 —— **给画面数字的刷新留时间**。

        为什么要它(实机 J4):画面上的费用数字**刷新得比我们读它慢**,
        于是"读数 == 账本 + 这张卡的费"这个**看起来最硬**的"牌回手"判据,
        其实分不清这两种情况:① 牌真的回手了;② 数字还没刷新。
        实测同一局里两次同样形状的读数,其实是**部署成功**(靠战场卡数才判对)。
        → 等 `DEPLOY_KREDITS_RECHECK_S` 再读一次:数字掉下去了就是成功,没掉才是真拒绝。
        ★ 只在"读数一点没动"这一档才付这个时间(少见),其余路径一秒都不多花。
        """
        if DEPLOY_KREDITS_RECHECK_S <= 0:
            return None
        time.sleep(DEPLOY_KREDITS_RECHECK_S)
        try:
            return self._kredits_now()
        except Exception:
            return None

    def _judge_deploy(self, before, after, target, cost, is_order: bool = False):
        """
        这一次拖拽到底成没成。返回 (ok, note, refused_measured)。

        `refused_measured=True` 表示"**读到费用一点没动**"—— 这是**有证据**的拒绝
        (牌回手),也只有这种情况才值得换个空槽位再试一次。别的失败都可能是
        "钱不够/规则不允许",重试纯属白拖。

        ★★ 判据优先级(2026-09-11 下午按用户实机观察重排):
          ① **费用读数 vs 我们自己的账本** —— 最硬的一条:
             部署成功 -> 剩余费用**一定**少了这张卡的费(账本 `kredits_left`
             在拖之前就已经扣过);被拒绝(牌回手)-> 费用**一点没动**,
             正好等于 `kredits_left + cost`。
             用户实测"砸在已有卡上 = 回手",所以这两条正好把成功/失败分开,
             而且不依赖任何"画面有没有变"的模糊判据。
             ★ 读到**别的值**时不下结论(可能是模板读错),交给 ②③,并把
               读数是多少写进日志 —— 不许悄悄退化。
          ② 战场卡数(老判据;已知会把粘连/地形数进去,只能当参考):
             增 1 = 成功;不变 = 失败;减少或跳变 = 读不准(物理上不可能)。
          ③ 面板对比(最后的退路)。**用了退路就必须在日志里写明**,
             否则又回到"看起来有判据、其实没数据"的状态。
        """
        if cost is not None:
            now = self._kredits_now()
            if now is None:
                extra = "费用读不出;"
            elif now == self.kredits_left:
                return True, (f"费用读数 {now} == 账本 {self.kredits_left}"
                              f"(已扣这张卡的 {cost} 费)"), False
            elif now == self.kredits_left + cost:
                # ★★★ 2026-09-13 深夜(实机 J4 抓到的第四种"显示滞后"):
                #   **这一档不能急着下结论。** 画面上的费用数字刷新得比我们读它慢 ——
                #   实机原文:`Bf 109 E-7 热带型 (cost 4) **部署被拒绝**(费用读数 2
                #   与账本 1 不符(读数可疑;原始读数序列 [2, 2]);战场卡数没变(6->6))`,
                #   而 21:12:45 / 21:28:32 两次**同样的不符**其实是**部署成功**
                #   (靠战场卡数才判对)。误判成"被拒绝"的代价不只是日志:
                #   那张牌会被记进 `failed_x`、记忆里也不删 -> 后面就"张数对不上"。
                #   -> 判"牌回手"之前,**等一会儿再读一次**;数字自己掉下去了就是成功。
                again = self._kredits_recheck()
                if again is not None and again == self.kredits_left:
                    return True, (f"费用读数 {now} 是**旧值**,等 "
                                  f"{DEPLOY_KREDITS_RECHECK_S}s 后重读 = "
                                  f"{again} == 账本 {self.kredits_left}"
                                  f"(数字刷新比我们读得慢)"), False
                shown = now if again is None else again
                return False, (f"费用读数仍是 {shown}(牌回手:账本应为 "
                               f"{self.kredits_left})"), True
            else:
                extra = (f"费用读数 {now} 与账本 {self.kredits_left} 不符"
                         f"(读数可疑;原始读数序列 "
                         f"{getattr(self, '_kredits_samples', None)});")
                # ★★ 2026-09-13(第十个会话):**判据说不清的时候,把现场存下来**。
                #   这一帧里同时有:左下角的剩余费用(画面上到底显示几)、
                #   手牌扇形(那张牌还在不在)、盘面。事后一眼就能定性是
                #   "钱真的少掉 3(抓错牌了)"还是"读数在滚动动画里抖了一下"。
                self._dump_frame("kredits_mismatch", target.get("name") or "")
        else:
            extra = "费用未知(这张牌没读出费用);"

        if is_order:
            # ★★★ 2026-09-20(指令卡):**指令不占槽位** —— 打完盘面上不会多出卡,
            #   所以下面那条"战场卡数 +1 才算成功"对指令是**错的**(会把打成功的
            #   指令记成被拒绝,还会把它塞进 failed_x)。
            #   指令只有一条硬判据:**费用对账**(打完一定扣掉这张卡的费);
            #   读不准就如实写"结论不可信" —— 项目纪律:宁可不下结论,不许伪造结论。
            return False, (extra + "指令卡:费用读数没法对上 -> "
                                  "**结论不可信**(指令不占槽位,不能用战场卡数判)"), False

        d_total, _d_support = self._field_delta(before, after)
        if d_total == 1:
            return True, (extra + f"战场卡数 {before['total']}->{after['total']}"
                                  f"(支援线 {before['our_support'][0]}->"
                                  f"{after['our_support'][0]})"), False
        if d_total == 0:
            return False, (extra + f"战场卡数没变({before['total']}->"
                                   f"{after['total']})"), False
        panel_note = ("战场读不到" if d_total is None else
                      f"⚠️卡数异常 {before['total']}->{after['total']}(读数抖动)")
        base_panel = target.get("_before")
        after_panel = self._panel_at(target["x"])
        if base_panel is None or after_panel is None:
            # ★★ 2026-09-13(第十个会话):**没有基准就不许报成功**。
            #   旧代码在惰性模式下 `_before` 恒为 None,而
            #   `_panel_looks_same(None, 非None)` 返回 False -> `ok=True`
            #   —— 面板判据成了橡皮图章:凡是"费用读数不符 + 卡数读不准"的部署
            #   一律记成"部署成功"(实机第 6/7 回合就是这样)。
            #   现在惰性模式**有**基准面板了(见 `_lazy_find_playable`),
            #   真拿不到基准时明确说"判不出来",并按**最保守**处理:
            #   记成没成(不抬高可负担上限、不占"本回合部署数"额度)。
            #   `refused_measured=False` -> 不会触发"换槽位重试"(那不是有证据的拒绝)。
            return False, (f"{extra}{panel_note} -> 面板判据**没有基准**"
                           f"(扫描那一帧没拍到面板)-> 判不出来,按最保守记成没成"), False
        ok = not self._panel_looks_same(base_panel, after_panel)
        return ok, f"{extra}{panel_note} -> 退回面板判据", False

    @staticmethod
    def _support_units_text(snap):
        """
        把"我方支援线有几个【单位】"格式化成日志文本。

        ★ 必须把 **None(判据不可信)** 和 **0(确实是空的)** 写成两种不同的东西 ——
          "诊断说谎"这个项目反复吃过亏(§7 第 67/68 条):一个 None 被印成 0,
          下次就没人看得出判据已经坏了。
        """
        if not snap:
            return "读不到"
        try:
            n, det = snap.get("our_support_units", (None, {}))
        except Exception:
            return "读不到"
        if n is None:
            return f"判据不可信({(det or {}).get('why') or '未知原因'})"
        return str(n)

    def _support_line_full(self):
        """
        我方支援阵线现在是不是满了。

        ★★ 2026-09-12 用户确认了**分母**:**上限 4 是【单位卡】,总部不占位**。
        所以这里必须用 `our_support_units`(**费用徽章数,不含总部**,见
        `board.support_line_units`),**不能**用 `our_support` ——
        后者是"那一行有几张卡",而总部卡就画在同一行里,于是它**永远多算一个**:
        实测那一帧 `单位 / STALINGRAD(总部) / 单位 / 单位` = 4 张卡,单位只有 **3** 个。
        用行卡数判"满没满"的后果是**还有空位时就以为满了** -> 少出一个单位。
        (文档里一直当作"读数抖动"的 `我支援 5`,真相很可能就是满线:4 单位 + 总部。)

        ★ 三条保守约定(都是为了"宁可多拖一次,也不要整局不出牌"):
          ① **读数不可信(None)时只信本回合部署数** —— None 的两种来源是
             "读不到我方那一行"和"数出 >4"(判据坏了),都不许当成 0 或 4;
          ② 取 **max(场上单位数, 本回合成功部署数)** —— 后者兜住"场上少算一个";
          ③ 本回合部署数 >= 4 直接算满(上限是硬的)。
        """
        by_field = None
        try:
            snap = self.field_now or self.field_at_turn_start
            if snap is not None:
                by_field = snap.get("our_support_units", (None, {}))[0]
        except Exception:
            by_field = None
        if by_field is None:
            return self.deployed_this_turn >= SUPPORT_LINE_MAX
        return max(int(by_field), self.deployed_this_turn) >= SUPPORT_LINE_MAX

    def _hand_count(self):
        """
        ★ 本回合**开始时**手里有几张牌(整个回合固定,**不跟着部署往下掉**)。

        ★★ 为什么必须"锁住第一次读到的值":每部署一张,手牌就少一张,
          而扫描器每次重扫都会报出**当前的**张数。要是直接用最新读数,
          "手牌 ≥5" 这个条件会在部署过程中自己失效 ——
          手里 5 张时出掉 1 张 -> 重扫报 4 -> 上限不生效 -> 又接着出。
          那就完全不是用户要的"手牌多时少出两个"了(实测用例 CASE 37 抓的就是这个)。

        来源:惰性扫描每次都会测扇形左边缘并查布局表,那张表里就带着张数
        (`hand_layout.json` 的 `count`),扫描器顺手记在 `last_hand_count` 上
        —— **不用额外扫一次手牌**。全量扫描模式下引擎自己知道(`hand_at_turn_start`)。

        ★ 拿不到就返回 None,调用方按"不知道"处理(不启用大手牌的部署上限)。
        """
        if self.hand_count_this_turn is not None:
            return self.hand_count_this_turn
        n = getattr(self.scanner, "last_hand_count", None)
        if not (isinstance(n, int) and n > 0):
            n = self.hand_at_turn_start or None
        if isinstance(n, int) and n > 0:
            self.hand_count_this_turn = n          # 锁住,本回合不再改
            return n
        return None

    def _hand_xs(self, exclude_x=None):
        """
        手牌各张的 x(从左到右)—— **target 指令里 kind 5「选择一张手牌」要用**。

        为什么要三个来源(都不用额外截屏/悬停,全是现成的识别结果):
          ① `self.cards` 的 `x` —— 本轮扫描真的悬停到、并且认出来的那张牌
             (探针打在哪张牌上,那个 x 就在那张牌上);
          ② `scanner.last_probe_seen` 里**弹出过面板**的 x —— 弹出面板 = 那个 x 底下
             确实有卡(没面板的探针底下是空气或缝隙,拖过去等于拖到空处);
          ③ 校准表(`config/hand_layout.json`)里**张数对得上**那条布局的 `probes`
             —— 它是"每张牌一个悬停点"的标定结果,扫描器自己就是用它铺探针的。
        三者都只是"候选位置",去重排序后交给 `order_target.pick()` 挑(挑哪张的规则
        在那个模块里,不在这儿 —— 判据只允许一处)。

        ★ `exclude_x` = **正在拖出去的那张牌自己的 x**:把它排掉,因为"拖到自己身上"
          不是"选择一张手牌"。
        ★ 惰性扫描只探到"第一张出得起的牌"就停,所以 ① ② 可能很少 —— 这很正常;
          凑不出 x 时 `pick()` 会 fail-closed(不打这张),而不是硬猜一个位置。
        """
        out = []
        for c in (self.cards or []):
            try:
                out.append({"x": int(c["x"]), "type": c.get("type"), "i": c.get("i")})
            except Exception:
                pass
        try:
            for s in (getattr(self.scanner, "last_probe_seen", None) or []):
                if s.get("panel"):
                    out.append({"x": int(s["x"]), "type": s.get("type"),
                                "i": s.get("i")})
        except Exception:
            pass
        # ③ 校准表:按扫描器这次匹配到的张数取那一条布局的悬停点
        try:
            n = getattr(self.scanner, "last_hand_count", None)
            if isinstance(n, int) and n > 0:
                layouts = self.scanner._load_layouts() or {}
                for v in layouts.values():
                    probes = list(v.get("probes") or [])
                    if v.get("count") == n and len(probes) == n:
                        out.extend({"x": int(p), "type": None, "i": None}
                                   for p in probes)
                        break
        except Exception:
            pass
        if exclude_x is not None:
            try:
                ex = int(exclude_x)
                out = [d for d in out if d["x"] != ex]
            except Exception:
                pass
        # 同一个 x 只留一条,而且**优先留带 `type` 的那条** ——
        # ★★ 2026-09-21:这就是这次改动的全部目的。kind 5「选择一张手牌」里有几张
        #   (势不可挡 / 金属废料 / 特别任务)要求选一张**单位**,`order_target` 只能靠
        #   `type` 才认得出哪张是单位;不给 type,它就只能 fail-closed —— 那 9 张会
        #   **一张都打不出去**。三个来源里 ① ② 天然带 type,③(校准表)只有坐标。
        by_x = {}
        for d in sorted(out, key=lambda d: d["x"]):
            old = by_x.get(d["x"])
            if old is None or (not old.get("type") and d.get("type")):
                by_x[d["x"]] = d
        return [by_x[k] for k in sorted(by_x)]

    def _resync_kredits_after_actions(self):
        """
        ★★★ 2026-09-13:行动阶段之后**按画面重新对一次账**(见调用处的长注释)。

        为什么不能省:账本 `kredits_left` 只在"部署"时扣钱,而
        **攻击和移动同样要花 Kredits**。先行动后部署之后,
        行动花掉的钱没人记 -> 出牌时以为还有满额预算 -> 白拖一张被拒绝。

        ★ 取 **min**(账本, 读数):
          · 读数偏高(已知会误读)-> 不放宽预算;
          · 读数偏低 -> 这一回合少出一个单位(安全侧);
          · 读不到 -> 保持账本不动(不许因为读不到就把预算清成 0)。
        """
        try:
            now = self._kredits_now()
        except Exception:
            now = None
        if now is None:
            return
        if self.kredits_left is None:
            self.kredits_left = now
            self.log(f"[turn] 行动之后对账:账本原本未知 -> 按画面取 {now}")
            return
        # ★★★ 2026-09-13 实机抓到的**已知误读形态**,必须挡住:
        #   §8 P3 记过"回合中途的费用读数会把两位数读成一个字形"(11/12 读成 1)。
        #   实机这一局 10 次对账里**有 2 次就是这个形状**:
        #     `画面剩余 1 < 账本 11` / `画面剩余 1 < 账本 12`
        #   而这两次都把**整回合预算压成 1** -> 那一回合**一个牌都没出**
        #   (`出牌结束(尝试 0 次)`)—— 比"多拖一次"贵得多。
        #   判据(窄而明确):账本是两位数,而读数**正好等于它的首位数字**
        #   -> 判为截断,**这次不对账**(保持账本)。
        #   ★ 代价有界:账本最多比真值高"行动费"那么多,真要出错也只是
        #     多拖一次(而不是整回合不出牌)。
        if self.kredits_left >= 10 and now == self.kredits_left // 10:
            self.log(f"[turn] 行动之后对账:读数 {now} 正好是账本 "
                     f"{self.kredits_left} 的首位数字 -> 判为**截断误读**"
                     f"(§8 P3:两位数只圈到一个字形),这次不对账")
            return
        if now < self.kredits_left:
            self.log(f"[turn] 行动之后对账:画面剩余 {now} < 账本 "
                     f"{self.kredits_left}(行动也要花钱,账本只扣了部署)"
                     f" -> 本回合预算改成 {now}")
            self.kredits_left = now

    def _kredits_measured(self):
        """
        本回合的预算是不是**真的读到过**(而不是"读不到时的保守兜底")。

        ★ 为什么需要:`kredits_info["source"]` 有 `agree/majority/single`(真读到)
          和 `prev`/`estimate`(兜底)两类,`measured` 就是那两类之分。
          "< 2 费就别扫手牌"这条规则**只能对真读到的值生效** ——
          兜底值(`estimate` 恒为 1)只是**下界**,真值可能更多,
          拿它当"钱不够"会把整回合白放弃(用例 CASE 30 就是这个场景)。
        """
        info = self.kredits_info or {}
        if "measured" in info:
            return bool(info["measured"])
        # 老路径/替身没有这个字段时按"可信"处理(退回旧行为)
        return True

    def _deploy_capped(self):
        """
        ★ 2026-09-13 用户要求:**手牌多的时候不必把费用用完**。

        判据(见 BIG_HAND_* 的说明):手牌 >= `BIG_HAND_MIN` 张 **且**
        本回合已成功部署 >= `BIG_HAND_MAX_DEPLOYS` 个 -> 停止出牌。

        ★ 只认**成功**的部署(`deployed_this_turn`),被拒绝的不算 ——
          否则一次"牌回手"就会把这一回合的出牌机会全部吃掉。
        ★ 张数拿不到(None)-> **不启用上限**(fail-open:宁可按老行为把费用用完,
          也不要因为读不到张数就永远只出两张)。
        """
        n = self._hand_count()
        if n is None or n < BIG_HAND_MIN:
            return False
        return self.deployed_this_turn >= BIG_HAND_MAX_DEPLOYS

    # --- one decision pass, returns a status string ---
    def think(self):
        frame = capture_client_bgr(self.hwnd)
        if frame is None:
            return "no_frame"
        et = self._end_turn_visible(frame)

        if self.phase == "wait_our_turn":
            if not et:
                return "opponent_turn"
            # our turn: end-turn button is up, so we may act
            # ★★★ 2026-09-13(用户要求):**先让场上已有单位行动,再部署手牌**。
            #   顺序变成 wait_our_turn -> attack -> move_front -> play -> end_turn。
            #   机理见 play 阶段末尾那段注释:行动要花 Kredits,
            #   旧顺序先部署会把钱花光 -> 单位就打不动了。
            #   (代价:本回合**刚部署的闪击单位**这一次赶不上攻击了 ——
            #    因为攻击阶段已经过去。这一点已写进 PROJECT_STATE。)
            self.phase = "attack" if self.attack_enabled else "play"
            # ★ 先记"这是第几个我方回合":费用一帧也读不出来时,最后一档保守
            #   兜底靠它(`min(回合数, 24)`,第一回合就是 1 费)。
            self.kredits.start_turn()
            kredits = self._current_kredits(frame)
            # 回合预算 = 刚读到的费用(读不到就是 None,退回 Affordability 的判据)
            self.kredits_left = kredits
            info = self.kredits_info or {}
            # ★ 这里只把 `turns_seen` 当**诊断计数**打出来(本进程看到第几个
            #   我方回合),并明确标注 —— 它**不是**费用上限:特殊卡可以额外
            #   增加上限,重启/中途接管后计数也和真实进度对不上。
            if kredits is None:
                self.log(f"[turn] our turn starts: kredits 读不出来 "
                         f"({info.get('note') or '未知原因'})"
                         + (f" | 读数器:{info['reader_reject']}"
                            if info.get("reader_reject") else "")
                         + f" | 本回合预算 None(退回可负担学习层)"
                         f" | {self.afford.describe()}")
            else:
                # ★ 只有"不采信"时才把 note 摊开(正常回合的日志保持一行干净)。
                #   实机那行 `kredits read: 11 [settled-timeout->不采信] 采样
                #   [1,3,5,1,1,1,…]` 以前看不出**为什么**不采信,现在能。
                why = ""
                if "不采信" in (info.get("source") or ""):
                    why = f" | {info.get('note')}"
                self.log(f"[turn] our turn starts (kredits read: {kredits} "
                         f"[{info.get('source')}] 采样 {info.get('samples')})"
                         + why + f" | 本回合预算 {self.kredits_left} "
                         f"| {self.afford.describe()}")
            # 回合开始先量一次战场:这是本回合判断"部署成没成功"的基准。
            # ★ 惰性扫描模式下**不在这里读整手牌** —— 那正是要省掉的 14 秒。
            #   手牌改成"每次要出牌前只找到第一张出得起的"。
            if not self.lazy_scan:
                self._scan()
            self.field_at_turn_start = self._field()
            if self.field_at_turn_start:
                self.log(f"[turn] 战场基准: 我支援 "
                         f"{self.field_at_turn_start['our_support'][0]} 张卡"
                         f"(单位 {self._support_units_text(self.field_at_turn_start)}) / "
                         f"我前线 {self.field_at_turn_start['our_front'][0]} / "
                         f"敌前线 {self.field_at_turn_start['enemy_front'][0]} / "
                         f"敌支援 {self.field_at_turn_start['enemy_support'][0]}")
            return "our_turn"

        if self.phase == "play":
            if not et:
                # turn ended while we were deciding (timeout / opponent acted)
                self.log("[turn] end-turn button gone mid-turn - resyncing")
                self.reset_turn()
                return "turn_switched"

            # ★ 惰性扫描:只在需要决定"下一张出什么"时才去读手牌,
            #   而且**找到第一张出得起的就停**(不用把整手牌读完)。
            #   每出一张牌后手牌扇形都会位移,所以缓存要作废、重新找。
            #   这不是浪费:通常前几个探针就能命中,单次约 2-3 秒,
            #   而全量扫描是 14 秒。
            if self.lazy_scan and not self.cards:
                if self._support_line_full():
                    pass          # 线满了就别扫了,直接进攻击/结束
                elif (self.kredits_left is not None
                        and self.kredits_left < MIN_KREDITS_TO_SCAN
                        and self._kredits_measured()):
                    # ★ 2026-09-13 用户要求:钱太少(< MIN_KREDITS_TO_SCAN)就别扫了,
                    #   省掉一次 3~9 秒的扫描 —— 代价是手里若只有 1 费牌就不出了。
                    #   ★ **只对"真读到的"读数生效**:读不到时的兜底值是
                    #     `1`(§7 第 54 条那条保守估计),它只是**下界**,
                    #     真值完全可能更多 —— 拿它当"钱不够"会把整个回合白白放弃。
                    #     (实测用例 CASE 30 就是这种情况:费用读不出来 -> 估 1 费,
                    #      但那张 1 费牌本来就该照出。)
                    self.log(f"[turn] 本回合只剩 {self.kredits_left} 费"
                             f"(< {MIN_KREDITS_TO_SCAN},真读到)-> 按用户规则"
                             f"不扫手牌,直接结束回合")
                elif self._deploy_capped():
                    # ★ 2026-09-13 用户要求:手牌多时不必把费用用完 ——
                    #   这里直接**不扫了**(省下的正是"每出一张牌重扫一次"那 3~9 秒)。
                    self.log(f"[turn] 手牌 {self._hand_count()} 张(多),"
                             f"本回合已部署 {self.deployed_this_turn} 个 -> "
                             f"按用户规则不再出牌,直接结束回合")
                else:
                    self._lazy_find_playable()

            target = None
            unknown_target = None
            # 支援阵线满了就别再拖了(用户确认最多 4 个):即使费用充足也放不下,
            # 牌会留在手上,拖出去只是白费时间。
            # ★ 判据是【场上实际卡数】,不是"本回合部署了几个":
            #   支援线上本来就可能有上个回合留下的单位,只看本回合计数会多拖。
            line_full = self._support_line_full()
            # ★ 2026-09-13:再加一道"手牌多就不必把费用用完"的闸(用户要求)。
            capped = self._deploy_capped()
            if line_full:
                self.log(f"[turn] 支援阵线已满(场上单位 "
                         f"{self._support_units_text(self.field_now or self.field_at_turn_start)},"
                         f"本回合已部署 {self.deployed_this_turn}/{SUPPORT_LINE_MAX}),"
                         f"不再拖牌")
            elif capped:
                self.log(f"[turn] 手牌多({self._hand_count()} 张)、本回合已部署 "
                         f"{self.deployed_this_turn} 个 -> 按用户规则收手,不再拖牌")
            # ★ 出牌顺序:**便宜的先出**。
            # 实测踩坑(CASE 3):原来按手牌从左到右找第一张付得起的,
            # 于是 5 费时先把 5 费的打出去,剩下 0 费,两张 1 费的反而出不了。
            # 同样费用下"多出几个单位"比"出一个大的"更划算(而且支援线
            # 只放 4 个,更该先塞满便宜单位)。
            # 费用未知的排在最后(它们要占预算,但不该抢在已知便宜牌前面)。
            ordered = sorted(
                self.cards,
                key=lambda c: (c.get("cost") is None, c.get("cost") or 0))

            for c in ([] if capped else ordered):
                if c["x"] in self.failed_x:
                    continue
                cost = c.get("cost")
                ctype = c.get("type")
                is_order_c = (ctype == "order")
                # ★★ 2026-09-20(用户要求):手里有**黑名单卡**就说一句(每局一次)。
                #   为什么在这儿说:黑名单是"用户请别带进卡组"的那些(惩戒那一族玩法复杂),
                #   而不是"引擎不会打" —— 用户看不到日志就不知道自己带了。
                if (not self._blacklist_warned
                        and orders.is_blacklisted(c.get("name"))):
                    self._blacklist_warned = True
                    self.log(f"[turn] ⚠️ 手牌里有**黑名单卡**「{c.get('name')}」——"
                             f"这类卡玩法复杂(要选目标/多步操作),引擎不会打它;"
                             f"建议别把它带进卡组(完整名单见 docs\\order_cards_plan.md)")
                # ★ 支援线满了 -> **单位**放不下;但**指令不占槽位**,照样能打
                #   (2026-09-20:以前 line_full 直接把整个出牌循环清空,于是
                #    "线满了"连带把指令也一起禁掉了)。
                if line_full and not is_order_c:
                    continue
                # ★★★ 2026-09-20:**指令卡**。用户把 674 张指令/反制的打法逐张给了出来,
                #   落在 `config/order_plays.json`。两版下来的放行范围:
                #     第一版:`direct`(286 张,拖到中线以下就打出,和放单位同一个手势
                #       —— 用户原话"拖出路径可以直接复用下单位时的路径");
                #     第二版:+ `target` 里 kind 1~6 且不带 follow 的(落点 = **目标卡
                #       中心**,由 `order_target.pick()` 现算,见下面那一段)。
                #   `choice`/`blacklist`/`unsupported`、target 里的 kind 7(三选一)
                #   与两步卡,全部由 `orders.playable()` 挡在外面(**判据只有那一处**,
                #   这里不另写名单)。
                if orders.playable(ctype, c.get("name")):
                    if self._budget(cost):
                        target = c
                        break
                    continue
                # 认不出来的牌(name/type 都空):不知道它是什么,也可能就是个
                # 便宜单位。费用读到了就按费用判断;费用也没有就试一次 ——
                # 试错成本极低(出不去就留在手上),而结果会立刻把上限压下来。
                # PROJECT_STATE 第 35 条:这类牌以前直接不 append,等于从手牌里
                # 消失,引擎永远不出。
                if ctype is None and c.get("unknown"):
                    if self.unknown_tried >= MAX_UNKNOWN_TRIES:
                        continue
                    if self._budget(cost, unknown_cost=MIN_UNKNOWN_COST):
                        unknown_target = c
                        break
                # 已知是 order/counter -> 一律不碰(需要选目标,风险高)

            if target is None and unknown_target is not None:
                target = unknown_target
                self.log(f"[turn] 未知牌 x={target['x']} "
                         f"(费用 {target.get('cost')}) —— 试一次,出不去就作罢")

            if target is None:
                # ★★★ 2026-09-13(第九个会话,用户要求):阶段顺序整个反过来 ——
                #   **先让场上已有的单位行动(攻击 / 上前线),最后才部署手牌**。
                #   所以"出牌阶段"现在是**最后一段**,出完就结束回合。
                #
                # 为什么用户要这个顺序(机理,不是口味):**行动也要花 Kredits**
                #   (§7 第 74 条:橙 = 本回合没行动过 **且** 还付得起行动费;
                #    Kredits 归零 -> 全场徽章一起变灰)。
                #   旧顺序是"先把钱花在部署上",于是**钱花光之后单位就打不动了** ——
                #   用户看到的就是"部署完之后单位一直不动"。
                self.log(f"[turn] 出牌结束(尝试 {len(self.attempted_x)} 次,"
                         f"成功 {self.deployed_this_turn} 个)-> 结束回合")
                self.phase = "end_turn"
                return "no_targets"

            name = target.get("name") or target.get("type") or "未知牌"
            cost = target.get("cost")
            before = self._field(park=True)

            # ---- 战场读一次:**两种落点都要用它** ----
            #   · 单位 / direct 指令:算"我方那一行的空槽位";
            #   · target 指令:算"目标卡的中心坐标"(见下面那一段)。
            #   ★ 所以它从原来的位置(扣账之后)挪到了扣账之前,内容一字未改。
            field_row = None
            if before is not None and before.get("frame") is not None:
                try:
                    field_row = board.read_field(before["frame"],
                                                 templates=self.templates)
                except Exception as e:
                    self.log(f"[turn] 读我方那一行出错({type(e).__name__}: {e})"
                             f" -> 用兜底落点")

            # ★★★ 2026-09-20(第二版):**target 指令**(表里 211 张,kind 1~6 才放行)。
            #   用户确认的手势是"需要选目标的要**拖到那张卡/总部上**" —— 也就是说
            #   落点不是空槽位,而是**目标卡的中心**,和部署单位共用同一套拖拽。
            #   ★ 判据与坐标**全部**来自 `order_target.pick()`(那个模块只回答"往哪拖",
            #     可离线单测);这里只做两件事:① 判不出目标就不拖;② 记账。
            is_target_order = orders.is_target(name)
            target_drop = None
            if is_target_order:
                got = order_target.pick(
                    name, field_row,
                    frame=(before or {}).get("frame"),
                    hand_xs=self._hand_xs(exclude_x=target["x"]),
                    hand_y=getattr(self.scanner, "y", None),
                    debug=self.debug, log=self.log)
                if got is None:
                    # ★ fail-closed:判不出目标就**不打**,并且如实写日志。
                    #   `pick()` 已经用一行 `[order_target] ...不打(判不出目标)—— 原因`
                    #   说清了**为什么**(判据在那个模块里,这里不重复判);
                    #   这一行补的是"这一拖的后果"。
                    self.attempted_x.add(target["x"])
                    self.failed_x.add(target["x"])
                    self.log(f"[turn] ⚠️ target 指令「{name}」(cost {cost},"
                             f"手牌x={target['x']})**不打** -> 本回合不再试它,"
                             f"继续看下一张(**没有真拖出去,费用不扣**)")
                    if self.lazy_scan:
                        # ★ 惰性模式必须清缓存:不清的话下一轮 think() 会拿这份
                        #   "已经作废的候选"直接走过场 -> 出牌阶段就此结束,
                        #   手里别的牌这一回合全都不出了(实测 CASE 28/29 那条路)。
                        self.cards = []
                        self._scanned_full_this_turn = False
                    return "order_no_target"
                target_drop = (got["x"], got["y"])
                # ★ 一行说清:这是 target 指令 / 目标是什么 / 为什么挑它 / 用哪个坐标
                self.log(f"[turn] target 指令「{name}」(cost {cost}) 手牌x={target['x']}"
                         f" -> 目标{got['what']}({got['x']},{got['y']}) | {got['why']}")

            # ★ 不管后面判成成功还是失败,这一笔费用都要从本回合预算里扣掉:
            #   被拒绝的牌虽然没花掉费用,但它已经浪费了一次拖拽,继续按"费用
            #   还是满的"去决策就会一直拖(用户实测:没费用了还在部署)。
            self._spend(cost)
            self.attempted_x.add(target["x"])
            # ★ 拖过的牌(不管成没成)本回合都不再拖第二遍 ——
            #   成功的已经不在了;失败的再拖一次只是白拖(而"反复拖打不出去的牌"
            #   正是这个项目最想消除的举报源)。旧的失败分支才记 failed_x 是不行的:
            #   非惰性模式下 `self.cards` 缓存还在,同一张牌会被反复选中
            #   (实测用例里拖成了 [500, 500, 500, 500])。
            self.failed_x.add(target["x"])
            if target.get("unknown"):
                self.unknown_tried += 1

            # ---- 落点 ----
            #   · target 指令:上面算出来的**目标卡中心**(不走空槽位);
            #   · 单位 / direct 指令:空槽位候选(不再是随机点)——
            #     用户实测"拖到已有卡的位置上松手 = 牌回手",而游戏不会自动吸附,
            #     所以落点必须是空位;空在哪要从画面现算(行带会漂移)。
            is_order = (target.get("type") == "order")
            # ★ 指令(含 target)**都不占槽位**:成/败只看费用对账,不看战场卡数
            #   (见 `_judge_deploy` 的 is_order 分支 —— 拿卡数判指令会把打成功的
            #    指令记成"被拒绝",还会把它塞进 failed_x)。
            is_order_like = bool(is_order or is_target_order)
            if is_target_order:
                # ★ target 指令**只试一次**:换一个目标重拖没有任何证据支持
                #   (下面那条"换个空槽位再试"是为"砸在已有卡上 -> 回手"写的,
                #    指令不占槽位,压根没有"砸在卡上"这回事)。
                tries = [target_drop]
            else:
                cands = deploy_candidates(field_row, debug=self.debug)
                # ★★ 2026-09-12 新增**诊断**:把"落点参考的是哪一行"写清楚。
                #   为什么需要:实机一局 6 次部署的落点 y **全是 400**(= `DROP_Y_LIMIT`
                #   的下限),而 `deploy_candidates` 的 y = `our_row(field)["cy"]` 夹到
                #   [400,620] —— 所以 y=400 意味着它当时把**一个 cy≤400 的行**当成了我方
                #   (很可能是前线那一行),然后被夹成一个"看起来合法"的落点。
                #   这条日志就是为了让"读错行"**当场可见**,而不是藏在夹取里。
                #   ★ 观测代码包 try:诊断失败只丢一行日志(§7 第 57 条)。
                try:
                    _orow = deploy_mod.our_row(field_row)
                    _rows_txt = "; ".join(
                        f"cy{round(r['cy'])}/{r.get('side')} n{len(r['boxes'])}"
                        for r in ((field_row or {}).get("rows") or []))
                    self.log(f"[turn] 落点参考行: "
                             + (f"cy={round(_orow['cy'])} side={_orow.get('side')}"
                                if _orow else "**读不到我方那一行**(会用兜底常数)")
                             + f" | 行结构[{_rows_txt}] | 候选{cands[:2]}")
                except Exception:
                    pass
                if is_order and not cands:
                    # ★★ 指令**不占槽位**:支援线满了(4 个单位)时 `deploy_candidates`
                    #    会把所有候选都过滤掉、返回空列表 —— 但指令照样能打。
                    #    退到"我方那一行上的固定落点"(兜底常数)。
                    cands = [deploy_mod.fallback_drop()]
                    self.log(f"[turn] 算不出空槽位(支援线满?)-> 指令按兜底落点 "
                             f"({cands[0][0]},{cands[0][1]}) 打")
                if not cands:
                    # 单位在这儿没候选 = 没地方放 -> 别拖(§候选[] 还照样拖是旧账)
                    self.log("[turn] ⚠️ 一个可用落点都算不出来 -> 这一拖跳过(不白拖)")
                    return "no_targets"
                if not field_row or not field_row.get("rows"):
                    self.log("[turn] ⚠️ 读不到我方那一行 -> 落点用兜底常数"
                             f"(y={cands[0][1]}),这一拖可能丢错行")
                tries = cands[:max(1, deploy_mod.MAX_SLOT_TRIES)]

            ok = False
            note = ""
            after = before
            for attempt, (dx, dy) in enumerate(tries, 1):
                verb = "playing  " if is_order_like else "deploying"
                # target 指令那一行要能一眼看出来(落点 = 目标卡中心,不是空槽位)
                kind_txt = "target 指令" if is_target_order else target.get("type")
                self.log(f"[turn] {verb} {name} ({kind_txt}, "
                         f"cost {cost}) 手牌x={target['x']} -> 落点#{attempt}"
                         f"({dx},{dy})(本回合剩余预算 {self.kredits_left})"
                         f" | {self._ident_text(target)}")
                drag_deploy(self.hwnd, target["x"], drop=(dx, dy),
                            hover_wait=self.scanner.hold,
                            on_pressed=lambda: self._dump_drag_frame(
                                name, target))
                time.sleep(DEPLOY_SETTLE)
                # ★ 拖完把光标挪开再复核:落点上会弹放大悬停卡,把旁边的卡盖住
                #   (§7 第 72 条 ③ 那四个读点里的一类,这里以前漏了)。
                before_attempt, after = after, self._field(park=True)
                self.field_now = after
                ok, note, refused_measured = self._judge_deploy(
                    before_attempt or before, after, target, cost,
                    is_order=is_order_like)
                if ok:
                    break
                # 失败 -> 换一个空槽位再试一次。**但只在真的有理由怀疑"砸在卡上"时**:
                #   ① 是"读到费用没动"这种有证据的拒绝(别的失败可能钱不够/规则不允许);
                #   ② 我方那一行**确实有卡**(空行还被拒 -> 不是占位问题,重试是白拖);
                #   ③ 支援线没满(满了换哪个槽位都没用)。
                # 用户实测的第一大拒绝原因就是"砸在已有卡上 -> 回手",这条正好治它;
                # 而"反复拖打不出去的牌"是这个项目最想消除的举报源,所以上限压得很死。
                row_n = 0
                if after is not None:
                    try:
                        row_n = int(after.get("our_support", (0, {}))[0])
                    except Exception:
                        row_n = 0
                if (refused_measured and row_n >= 1 and attempt < len(tries)
                        and not self._support_line_full()):
                    self.log(f"[turn] 这一次没成({note})-> 我方那一行有 {row_n} 张,"
                             f"像是砸在卡上 -> 换个空槽位再试")
                    continue
                break

            # ★ 部署到底成没成功:**优先看场上卡数有没有变**。
            #
            # 以前判据是"同一个手牌位置的面板前后对比"(_panel_looks_same),
            # 实机证明它会把**被拒绝的部署判成成功** —— 日志里每回合都报
            # "成功部署 4 个",而用户实际看到的是"乱拖了好多次"。
            #
            # 判据的优先级见 `_judge_deploy`:
            #   ① **费用读数 vs 我们自己记的账本**(最硬:成功就一定扣了这张卡的费)
            #   ② 战场卡数(有已知弱点,见那里的注释)
            #   ③ 面板对比(最后退路,而且日志里必须写明"用的是退路")
            if ok:
                self.deployed_this_turn += 1
                self.afford.note_deploy_ok(cost)
                what = "指令打出" if is_order_like else "部署成功"
                self.log(f"[turn] {name} {what} "
                         f"(本回合 {self.deployed_this_turn} 个;{note})")
                # ★★★ 手牌记忆:确认出掉的是**第几张** -> 从记忆里删掉(次序左移)。
                #   ★ 只在**确认成功**时才删;被拒绝的牌还在手上,记忆不动
                #     (张数也就对得上,下一轮还能认出它)。
                self.memory.note_played(target.get("i"))
            else:
                self.deploy_refused += 1
                self.afford.note_deploy_failed(cost)
                # 阵线满是最常见的拒绝原因,单独提示(用户指出的头号问题)
                reason = "支援阵线已满" if self._support_line_full() else "费用/规则不允许"
                what = "指令没打出去" if is_order_like else "**部署被拒绝**"
                self.log(f"[turn] {name} (cost {cost}) {what}({note})"
                         f" -> 推断原因:{reason};"
                         f"可负担上限:{self.afford.describe()}")

            # ★ 惰性模式:手牌变了,缓存的"下一张"必须重新找。
            #   出了牌 -> 扇形整体位移、那张牌也没了;
            #   被拒绝 -> 那张牌还在,但已记入 failed_x,下次要跳过它看后面的。
            #   两种情况都应该重新扫,否则引擎会一直盯着同一张。
            #   同时清掉"本回合已扫过"的闸门 —— 每出一张牌都是新的一轮,
            #   不清的话第二张牌就再也找不到了(实测踩过)。
            if self.lazy_scan:
                self.cards = []
                self._scanned_full_this_turn = False
            return "deployed"

        if self.phase == "attack":
            if not et:
                self.log("[turn] end-turn button gone before attacking - resyncing")
                self.reset_turn()
                return "turn_switched"
            # M4:出完牌后,让我方场上单位去打敌方总部(用户确认:拖拽到目标上)。
            # 一次 think() 只推进一段攻击,避免卡住主循环。
            attempts, landed = self.attacker.run_turn(
                hard_stop=lambda: not self._end_turn_visible())
            self.attacked_this_turn += landed
            self.log(f"[turn] 攻击阶段结束:尝试 {attempts} 次,被接受 {landed} 次"
                     f"(本回合累计 {self.attacked_this_turn})")
            # ★ 2026-09-13:攻击之后进"上前线"阶段 —— 能打的已经打了(变灰),
            #   剩下的"够不着目标"的步兵/坦克才挪上去。
            #   ★ 上前线**排在出牌之前**(用户要求:先让场上已有单位行动):
            #     挪上去的单位要花行动费,先做;新部署的单位反正也动不了。
            self.phase = "move_front"
            return "attacked"

        if self.phase == "move_front":
            if not et:
                self.log("[turn] end-turn button gone before moving - resyncing")
                self.reset_turn()
                return "turn_switched"
            moved, refused = self.front_mover.run_turn(
                hard_stop=lambda: not self._end_turn_visible())
            self.moved_this_turn += moved
            self.log(f"[turn] 上前线阶段结束:挪上去 {moved} 个,没动成 {refused} 个"
                     f"(本回合累计 {self.moved_this_turn})")
            # ★★ 2026-09-13:上前线会把我们自己的单位**挪离支援线**(空出位置),
            #   而 `field_at_turn_start` 是**挪之前**的快照 —— 拿它判"线满没满"
            #   会把刚空出来的位置当成还占着 -> **少出一个单位**。
            #   所以这一路真的挪动人之后,进"出牌"阶段前重新读一次战场。
            if moved:
                try:
                    snap = self._field(park=True)
                except Exception:
                    snap = None
                if snap is not None:
                    self.field_now = snap
            # ★★★ 2026-09-13(改序带出来的真问题,实机当场抓到):
            #   **行动也要花 Kredits,而账本只扣了部署。**
            #   `kredits_left` 在回合开始设定,之后只有"出牌"那一支会扣它;
            #   先行动后部署之后,攻击/移动花掉的钱**没人记** ->
            #   出牌时还以为有满额预算 -> 拿 3 费去出 3 费牌 ->
            #   **部署被拒绝**(实机日志:`费用读数 2 与账本 0 不符(读数可疑);
            #   战场卡数没变(5->5)`)—— 正是本项目头号要消除的"白拖一次"。
            #   → 进"出牌"阶段前**按画面重新对一次账**。
            #   ★ 取 **min**(账本, 读数):画面读数偏高(已知会误读)时不许放宽预算;
            #     偏低时最多是"这一回合少出一个单位"(安全侧,而且
            #     `Affordability` 那层还会跟着收敛)。
            self._resync_kredits_after_actions()
            # ★ 2026-09-13:上前线做完 -> 才轮到**出牌**(用户要求的顺序)
            self.phase = "play"
            return "moved_front"

        if self.phase == "end_turn":
            s, reg = self._end_turn_region(capture_client_bgr(self.hwnd))
            if reg and s >= END_TURN_MIN_SCORE:
                cx = reg[0] + reg[2] // 2
                cy = reg[1] + reg[3] // 2
                sx, sy = client_to_screen(self.hwnd, cx, cy)
                click(sx, sy)
                self.log(f"[turn] clicked end turn at client ({cx},{cy}) "
                         f"score {s:.3f}")
            else:
                self.log("[turn] end-turn button vanished before we clicked it")
            self.reset_turn()
            return "ended_turn"

        return "unknown"
