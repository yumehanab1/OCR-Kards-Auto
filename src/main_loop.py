"""
main_loop.py - top-level loop that drives KARDS through the grind flow.

Flow:  main_menu -(play)-> deck_select -(casual)-> -(deck_ok)-> queueing
       -> mulligan -(ok)-> in_game -> ... -> victory/defeat -> main_menu

State handlers rely on ui_state.classify(). Template regions are client-area
coordinates (1280x720 capture space); clicks convert them to screen
coordinates via ClientToScreen before moving the mouse.

Safety:
  - every action is followed by a cooldown so the same template cannot be
    clicked repeatedly within one screen;
  - if the capture is blank/occluded for several rounds we stop acting and log;
  - in-game behaviour is intentionally minimal in M2 (see IN_GAME mode).

Usage:
  .venv\\Scripts\\python.exe src\\main_loop.py            # normal loop
  .venv\\Scripts\\python.exe src\\main_loop.py --dry-run  # decide+log, never click
  .venv\\Scripts\\python.exe src\\main_loop.py --max-rounds 3
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
# ★ 2026-09-19:"turn engine error" 要打 traceback(见那处的长注释)。
#   原来只在 `main()` 顶层 import 一次,别处拿不到。
import traceback

import cv2
import win32gui

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
# ★ 别漏了 stderr:Windows 上它默认跟着控制台代码页(936)。中文路径一旦进了
#   traceback,写出来就是一串 \ufffd,使用者拿到的报错等于没有信息。
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import cv_io  # noqa: E402,F401  (开关:让 cv2 认中文路径,见 cv_io.py)
from actions import click  # noqa: E402
# ★★★ 2026-09-21 深夜(实机抓到的**按下前就存在**的 bug):
#   `click_template()` 的失败分支里写了
#       `_why = actions_mod.take_input_error() or "原因读不出"`
#   而 `actions_mod` 这个名字**只在 `main()` 函数体里** import 过
#   (`import actions as actions_mod`,见本文件末尾)。
#   `click_template` 是 Controller 的方法,作用域里根本没有这个名字 ——
#   于是**只要有一次点击失败**,这一行就抛 `NameError`,异常一路冒到
#   `main()` 的兜底 except -> **整个引擎当场退出**。
#   实机判据(2026-09-21 21:29:31,run#9):
#       [deck_select] -> click casual_mode_btn at screen(-703,962) match=1.000
#       💥 未捕获异常 … NameError: name 'actions_mod' is not defined
#   讽刺的是:v0.1.6 专门做了"点击失败要软着陆、不许把引擎带走"(§7 那条),
#   结果**软着陆的那一行自己先崩** —— 等于那条修复只覆盖了"click() 返回 False"
#   之前的路径,没覆盖"要报原因"这一步。
#   ⇒ 在模块顶层 import 一次(函数里那次保留,免得动到别处的写法)。
import actions as actions_mod  # noqa: E402
from turn_engine import END_TURN_MIN_SCORE, TurnEngine  # noqa: E402
from ui_state import classify, load_meta, load_states, load_templates, match_one  # noqa: E402
from win import (  # noqa: E402
    acquire_single_instance_lock,
    capture_client_bgr,
    find_by_process,
    foreground_window,
    set_dpi_aware,
    set_window_client_size,
    window_is_capturable,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
META = os.path.join(PROJECT_ROOT, "config", "templates.json")
STATES = os.path.join(PROJECT_ROOT, "config", "states.json")
LOG = os.path.join(PROJECT_ROOT, "logs", "main_loop.log")

# Cooldown (s) after each click, and blank-frame tolerance.
COOLDOWN_AFTER_CLICK = 2.5
BLANK_TOLERANCE = 6          # consecutive blank frames before we pause acting
QUEUE_TIMEOUT_MIN = 12       # queueing longer than this -> click cancel

# ---- 2026-09-21 深夜(用户提议)**打完一局之后的"补点窗口"** ----
#  ★ 用户的提议(2026-09-21):*"识别到对局结束就每秒点一次持续十秒"* ——
#    胜负状态识别成功并完成首次点击后,结算流程还会依次出现等级、任务和奖励页。
#    这些尾页没有稳定模板,所以在 `finish_round()` 中开启补点窗口,每秒点一次,
#    最多十次,直到识别到新的已知流程状态才提前结束。
#: ★ 点哪儿 —— **用户 2026-09-21 指定"安全点可以复用主页面的开始位置"**。
#:  也就是说:结算/弹窗那一屏上,点**主界面「开始」按钮所在的那块位置**是安全的
#:  (那儿在结算页上没有真按钮,所以点下去最多是"没反应",不会误触发别的功能)。
#:
#:  坐标怎么来的(不是拍的):
#:    · `config\templates.json` 里 `casual_mode_btn.region` = (1165,547,105,33)
#:      -> 中心 **(1217,563)**;
#:    · 我又拿现成的**真实主界面帧**在客户区 1280x720 上跑了一次
#:      `match_one`(score=1.000),实测 region=(1165,542,105,33)
#:      -> 中心 **(1217,558)**。
#:    两者差 5px(模板匹配的正常偏差),取 **558**(实测值)。
#:  ★ 为什么不用原来那四个角:用户明确说了复用开始位置;而且四角在实测里
#:    **连续 3 次画面不动**(见 `DISMISS_STUCK_NOTE`),说明那几处对这一屏不生效。
#:  ★ 抖动 ±25/±15 与 `click_center` 一致 —— 固定一个像素点容易正好落在
#:    "没反应的那一格"上,抖动留出余量(但不越界,见下面的 min/max 夹取)。
POST_MATCH_POINT = (1217, 558)
#: 抖动幅度(客户区像素),与结算页那套保持一致。
POST_MATCH_JITTER_X = 25
POST_MATCH_JITTER_Y = 15
#: 总开关(A/B 回退:False = 完全退回老行为,一行都不点)。
POST_MATCH_CLICKS = True
#: 点几下 / 间隔多久 —— 用户指定"每秒一次、持续十秒"。
POST_MATCH_CLICK_N = 10
POST_MATCH_CLICK_GAP = 1.0
#: ★ 点哪儿 = **`POST_MATCH_POINT` 这一个固定点 + 抖动**(实走在 `_post_match_clicking`)。
#:  这个点是用户 2026-09-21 指定的安全点(`casual_mode_btn` 那一块,
#:  坐标来源见上面 103-113 行);以后要换点,只改这一个常量
#:  (别在别处再写死坐标)。
#:  ★ 不轮换:早期设想的"复用结算页那四个角、逐次轮换"已被实测否掉 ——
#:  那几处连点 3 次画面都不动(见上面 109-110 行),对这一屏不生效。
#: ★ 与 `dismiss` 的关系:补点窗口跑完就**交回**给主循环 ——
#:  如果画面已经变回已知状态,`dismiss` 那套会照常收工;没变就一 tick 一 tick 继续
#:  (那时 `dismiss` 若为 True,由它接手后续的重试)。
#:
#: 补点窗口只允许由 `finish_round()` 开启。未知画面持续多久都不能单独
#: 触发点击，否则对手回合的 `state=None` 会被误判成结算页。


# ---- 2026-09-21(M3/M5)结算页:判据从"点了几次"改成"画面变了没有" ----
#: 尾部页最多"快"点几次 —— 用尽后**不是放弃**,而是转成慢速退避重试(见
#  `tick_dismiss` 里那段长注释)。
DISMISS_MAX_FAST = 12
#: 两次快点的最小间隔(原来的硬编码值,提出来是为了让慢速重试能复用同一道闸)。
DISMISS_FAST_GAP = 1.8
#: 慢速重试的退避:第 n 次慢点的间隔 = SLOW_BASE + n*SLOW_STEP,封顶 SLOW_CAP。
#: 为什么"逐次拉长"而不是固定间隔:未知奖励页可能只是**网络慢/动画长**,
#:  固定 1.8s 一直重试会把"抢物理鼠标"这件事做上几百次;拉长之后每秒的动作数
#:  随停留时间**下降**,既不会把屏幕点满,又能一直保持"还在试"这个事实可见。
DISMISS_SLOW_BASE = 3.0
DISMISS_SLOW_STEP = 2.0
DISMISS_SLOW_CAP = 15.0
#: 帧差判据(照抄开发树 `C:\Users\31291\Desktop\kards-auto\src\main_loop.py`
#  第 766~789 行那段"卡在认不出的画面上"里的现成写法,判据一字未改):
#  逐像素取三通道最大差 > 25 的像素**占比**;`< 0.001` 就算"这一下点下去画面没动"。
#  为什么用"占比 < 0.001"而不是"最大差 == 0":实机画面里总有抗锯齿/动画噪点,
#  逐像素全等是不存在的 —— 见开发树那处注释(它当时也是照实测定的阈值)。
DISMISS_DIFF_THRESHOLD = 25
DISMISS_DIFF_MIN = 0.001
#: 连续几次"画面没动"就停手。
DISMISS_STUCK_LIMIT = 3
#: 点完到回读一帧之间的等待(让游戏有机会切画面)。
DISMISS_FRAME_SETTLE = 0.6
#: 开发树那段"停手"注释的判据要点,这里照抄下来(免得移植后判据只剩一个数字):
#  ★ **别急着说"客户端卡死"** —— 连点几次画面不动,更可能的情况是
#    **点的地方本来就不响应**(结算页这一屏没有真按钮,谁也不知道哪一块灵);
#    所以这里只写"停手 + 把事实打进日志",**不写"客户端死了"这种结论**。
DISMISS_STUCK_NOTE = (
    "⚠️ 连点 3 次画面几乎没变(dd<0.001)-> 停手不再点。"
    "**别急着说'客户端卡死'**(开发树那次就误判过):先拿一个本来该有反应的东西"
    "试试(右上角齿轮菜单)—— 它也不动才是客户端的问题;它动了,说明"
    "**是这一屏点的位置本来就不响应**(用户说过'除了中心哪都能跳',"
    "那更可能是这局画面根本没走到结算页)。"
)

#: `deck_select` 界面上"选对局模式"的那几只按钮 —— **按顺序试**。
#  ★★ 2026-09-13 深夜(用户指出):以前这里**只认对战模式**那一只
#    (`casual_mode_btn`),而用户开的是**训练模式** —— 按钮长得不一样,
#    模板只有 0.48 -> 拒绝点击 -> 空转 45 秒(日志 140 行 "match too weak")。
#  ⇒ 候选表 + "一只都没匹配上就告警"。**要给某个模式加按钮,只要**:
#    ① 在那个模式的牌组界面截一张整帧(引擎空转时 `capture.py snap` 即可);
#    ② 把按钮那一块裁出来存成 `ui_templates/<名字>.png`;
#    ③ 在 `config/templates.json` 里加一条(带 `region`,和 `casual_mode_btn` 同一格式);
#    ④ 名字填进下面这张表。
#  ⚠️ 没录模板的名字**留在表里也没事**(代码会跳过它),但**不要瞎填位置去点击** ——
#    这个项目最贵的错误是"乱点"。
MODE_BTNS = ("casual_mode_btn", "training_mode_btn", "ranked_mode_btn")


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line)
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


class Controller:
    def __init__(self, proc: str, dry: bool, max_rounds: int, end_turn: bool,
                 play: bool = False, fast_scan: bool = False,
                 attack: bool = True, lazy_scan: bool = True):
        self.proc = proc
        self.dry = dry
        self.max_rounds = max_rounds
        self.end_turn = end_turn  # M2: auto-click end turn while in game
        self.play = play          # M3: hand in-game turns to TurnEngine
        self.fast_scan = fast_scan  # 用校准好的坐标表直扫
        self.attack = attack      # M4: 出完牌后让我方单位打敌方总部
        # ★ 惰性扫描:找到第一张出得起的牌就停,不读整手牌(默认开,见 §11)
        self.lazy_scan = lazy_scan
        self.turn_engine = None
        self.last_turn_status = None
        self.hwnd = None
        self.meta = load_meta(META)
        self.templates = load_templates(self.meta)
        self.states = load_states(STATES)
        self.last_click = 0.0
        self.blank_streak = 0
        self.occluded_ticks = 0      # 窗口被遮挡/最小化的连续 tick 数
        self.round_started = time.time()
        self.round_count = 0
        self.current_state = None
        # deck_select is a two-step screen: casual first, then deck_ok
        self.deck_step = "casual"
        # ★ 选模式那几只按钮**都没匹配上**的连续次数(见 handle_deck_select)
        self._mode_miss = 0
        # after a result, arbitrary clicks dismiss level-up / quest screens
        self.dismiss = False
        self.dismiss_tries = 0
        self.dismiss_last = 0.0
        # ★ 2026-09-21(M3):"点了没生效"要用**画面变了没有**来判,不再靠次数猜。
        #   `_dismiss_frame` = 上一次点击后的那一帧(灰度、缩小到 1/4),点完再回读
        #   一帧跟它比;`_dismiss_stuck` = 连续几次"画面几乎没变"。
        #   ★ 为什么不存整帧:整帧是 1280x720x3 的实时画面(2.7MB),而这个项目
        #     栽过"把实时画面留在状态里"的坑(内存 + 序列化);灰度小图只够做
        #     差分,做不了别的,正好。这个字段**只在本类内部用**。
        self._dismiss_frame = None
        self._dismiss_stuck = 0
        # ★ 2026-09-21:"提前停手、改走慢速"那条 ⚠️ 只许打一次(这个分支每次 tick
        #   都会被走到,不加这个开关就是每 tick 一条,日志会被刷掉)。
        self._dismiss_slow_said = False
        # ★★ 2026-09-21 深夜:"打完一局之后的补点窗口"(见 POST_MATCH_CLICKS 那段)。
        #   `_post_clicks_left` = 还剩几下要补;`_post_click_last` = 上一下的时间。
        #   为什么不用"结束时刻 + 10 秒"算区间:主循环一个 tick 里可能睡好几段,
        #   用"剩余次数"记账更稳,而且日志里能直接看出"还差几下"。
        self._post_clicks_left = 0
        self._post_click_last = 0.0
        self._post_clicks_done = 0

    # ---- capture & classify ----
    def grab_frame(self):
        if self.hwnd is None:
            wins = find_by_process(self.proc)
            if not wins:
                return None
            self.hwnd = wins[0]["hwnd"]
        return capture_client_bgr(self.hwnd)

    def client_to_screen(self, x: int, y: int):
        if self.hwnd is None:
            return (x, y)
        return win32gui.ClientToScreen(self.hwnd, (int(x), int(y)))

    # ---- click helpers ----
    def click_template(self, name: str) -> bool:
        if name not in self.templates:
            log(f"template '{name}' not loaded")
            return False
        frame = self.grab_frame()
        if frame is None:
            return False
        score, region = match_one(frame, self.templates[name])
        if region is None or score < 0.6:  # don't click a weak match
            log(f"[{self.current_state}] '{name}' match too weak ({score:.2f}), skip click")
            return False
        cx, cy = self.client_to_screen(
            region[0] + region[2] // 2, region[1] + region[3] // 2
        )
        log(f"[{self.current_state}] -> click {name} at screen({cx},{cy}) "
            f"match={score:.3f}")
        if not self.dry:
            # ★★ 2026-09-19(v0.1.6):鼠标操作现在会**失败**(系统可能不让动光标)。
            #   失败时说清楚"点了但没动成",而不是记成"点过了" ——
            #   实机教训:以前 SetCursorPos 一抛异常整轮就结束,用户看到的是
            #   "运行到卡组页面不会点确定"(其实是点了就崩、原地不动)。
            if not click(cx, cy):
                _why = actions_mod.take_input_error() or "原因读不出"
                log(f"⚠️ [{self.current_state}] {name} 这一下**没点成**:{_why}")
                return False
        self.last_click = time.time()
        return True

    def can_act(self) -> bool:
        return (time.time() - self.last_click) > COOLDOWN_AFTER_CLICK

    # ---- state handlers ----
    def handle_main_menu(self):
        if self.can_act():
            if self.click_template("play_btn"):
                self.deck_step = "casual"
                time.sleep(1.5)

    def handle_deck_select(self):
        # Two sub-steps on the same screen: press casual mode, then confirm deck.
        # ★★★ 2026-09-13 深夜(**用户当场指出**):引擎以前**只认对战模式那一只按钮**
        #   (`casual_mode_btn`),而用户开的是**训练模式** —— 那只按钮长得不一样,
        #   模板只匹配到 **0.48** -> 拒绝点击(对的,不能乱点) -> 在牌组界面
        #   **空转 45 秒**,日志刷了 **140 行** "match too weak"。
        #   ⇒ 改成**候选表**:哪只匹配得上就点哪只;一只都没匹配上时**大声告警**
        #     (以前它只是静静地刷日志,人不在旁边根本看不出来)。
        if not self.can_act():
            return
        if self.deck_step == "casual":
            for name in MODE_BTNS:
                if name not in self.templates:
                    continue                    # 还没录模板的候选直接跳过
                if self.click_template(name):
                    log(f"[deck_select] 用 '{name}' 进了对局流程")
                    self.deck_step = "deck_ok"
                    self._mode_miss = 0
                    time.sleep(1.0)
                    return
            self._mode_miss += 1
            # 只在前几次和每隔一段时间报一次,免得又变成刷屏
            if self._mode_miss in (3, 10, 30) or self._mode_miss % 120 == 0:
                log(f"⚠️ 选模式的界面:候选按钮 {list(MODE_BTNS)} **一只都没匹配上**"
                    f"(已连续 {self._mode_miss} 次)—— 多半是**这个模式(比如训练模式)"
                    f"的按钮还没录模板**,需要人点一下;"
                    f"录模板见 §3 第 8 条。")
            # ★★★ 2026-09-13 深夜(用户指出"训练模式的按钮不一样"之后的修法):
            #   **模式是游戏自己记住的** —— 这一屏只要能按到「开始」就能进对局,
            #   模式按钮只是"顺便切一下"。所以模式按钮一只都不匹配时,
            #   **不要在这里干等**,直接按「开始」。
            #   实测依据:训练模式的牌组界面(2026-09-13 22:44 存帧
            #   `shots/_deck_select_training.png`,已归档到 `shots/ui_deck_select/`)
            #   上 `deck_ok_btn` 匹配 **0.931**、而 `casual_mode_btn` 只有 **0.476**
            #   —— 按钮一直在那儿,以前只是流程要求"先点模式"才够不着它。
            if self.click_template("deck_ok_btn"):
                log("[deck_select] 没有模式按钮可点 -> 直接按「开始」"
                    "(对局模式是游戏自己记住的)")
                self.deck_step = "done"
                self._mode_miss = 0
                time.sleep(1.5)
        else:
            if self.click_template("deck_ok_btn"):
                self.deck_step = "done"
                time.sleep(1.5)

    def handle_queueing(self):
        waited = time.time() - self.round_started
        if waited > QUEUE_TIMEOUT_MIN * 60 and self.can_act():
            log(f"queueing >{QUEUE_TIMEOUT_MIN}min, click cancel to restart flow")
            if self.click_template("queue_cancel"):
                self.deck_step = "casual"
                self.round_started = time.time()

    def handle_mulligan(self):
        # ★★ 2026-09-12 实机抓到的真 bug:换牌(= 新的一局开始了)意味着
        #   **费用账本必须从头开始**,而 `TurnEngine` 是**整个进程只建一次**的
        #   (`if self.turn_engine is None`),它里面的 `KreditsTracker` 带着
        #   **上一局的锚点**。于是新一局的第一回合读到 1 会被 R2
        #   ("剩余费用不可能比上次采用值低")判成误读,改用上一局的 14/15 当预算。
        #   实测日志:
        #       上一局结尾 ... 15 ...
        #       00:28:36 [turn] our turn starts (kredits read: 15 [agree->不采信]
        #               采样 [1, 1]) | 本回合预算 15      <- 新一局第一回合!
        #   后果正是这个项目最想消除的东西:**预算虚高 -> 一直拖买不起的牌 -> 乱拖**。
        #   修法:新一局开始时把引擎整个丢掉,下一 tick 重建成干净的
        #   (费用锚点、支援线计数、可负担上限全都是"每一局独立"的状态)。
        self.turn_engine = None
        if self.can_act():
            if self.click_template("mulligan_ok_btn"):
                time.sleep(1.5)

    def handle_in_game(self):
        """
        M3: hand over to the turn engine, which does one decision per call:
        read Kredits -> scan hand -> drag an affordable unit -> click end turn.
        M2 fallback (`--end-turn` without `--play`) only clicks end turn.
        """
        if self.play and not self.dry:
            if self.turn_engine is None:
                self.turn_engine = TurnEngine(
                    self.hwnd, self.templates, log=log, use_fast=self.fast_scan,
                    attack=self.attack, lazy_scan=self.lazy_scan)
                log(f"[in_game] turn engine attached "
                    f"({'坐标表直扫' if self.fast_scan else '盲扫'}, "
                    f"攻击={'开' if self.attack else '关'}, "
                    f"扫描={'惰性(找到第一张可出的就停)' if self.lazy_scan else '全量'})")
            if self.hwnd is None:
                return
            self.turn_engine.hwnd = self.hwnd
            # ★ 诊断(PROJECT_STATE §8 待办 9 后半 / 待办 14 的入口):
            #   曾经出现"很暗的过渡画面(实测 mean=25.2、state=None)被当成对局
            #   交给回合引擎,于是扫描空转"。要判断这一点,得把**交棒那一刻
            #   画面长什么样**记下来。条件与引擎自己的判据一致(结束回合按钮
            #   ≥ END_TURN_MIN_SCORE,也就是"引擎马上要开始出牌了"),
            #   所以每个我方回合正好打一行,不刷屏。
            #
            # ★★ 诊断代码绝不许弄崩主循环:第一版这里写成了 self.log(...),
            #    而 Controller 用的是**模块级**的 log() —— 一进对局就
            #    AttributeError 把整个 run 打挂(实测 11:59:10 崩过)。
            #    所以整块包在 try 里:观测失败只丢一行日志,不影响出牌。
            try:
                if self.turn_engine.phase == "wait_our_turn":
                    f = self.grab_frame()
                    if f is not None:
                        s, _reg = match_one(f, self.templates["end_turn_btn"])
                        if s >= END_TURN_MIN_SCORE:
                            suspect = s < 0.82 or f.mean() < 20
                            log(f"[in_game] 交棒给回合引擎: frame mean={f.mean():.1f} "
                                f"std={f.std():.1f} end_turn_score={s:.3f}"
                                + ("  ⚠️画面可疑(分数偏低或过暗),若接下来"
                                   "扫描空转就是这个原因" if suspect else ""))
            except Exception as e:
                log(f"[in_game] 交棒诊断失败(不影响出牌): "
                    f"{type(e).__name__}: {e}")
            try:
                st = self.turn_engine.think()
            except Exception as e:
                # ★★★ 2026-09-19(v0.1.6):**这里必须打 traceback。**
                #   实机证据(用户 E:\kards-auto 那份日志):这里有**几十行**
                #     `[in_game] turn engine error: IndexError: list index out of range`
                #   每 1.5 秒一条、连着刷了一个多小时,而**只打了异常类型和消息** ——
                #   完全看不出崩在哪个函数、哪一行,只能靠猜。
                #   以后第一条带完整 traceback,后面同样的错只报次数(不刷屏)。
                _sig = f"{type(e).__name__}: {e}"
                if _sig != getattr(self, "_te_err_sig", None):
                    self._te_err_sig = _sig
                    self._te_err_n = 0
                    log(f"[in_game] turn engine error: {_sig}\n"
                        + "".join(traceback.format_exc()))
                else:
                    self._te_err_n = getattr(self, "_te_err_n", 0) + 1
                    if self._te_err_n == 1 or self._te_err_n % 20 == 0:
                        log(f"[in_game] turn engine error 同一处又犯了 "
                            f"{self._te_err_n} 次({_sig})—— traceback 见上面第一条")
                return
            if st != self.last_turn_status:
                log(f"[in_game] turn engine: {st} "
                    f"(phase={self.turn_engine.phase}, "
                    f"deploys={self.turn_engine.deployed_this_turn})")
                self.last_turn_status = st
            return

        # M2 minimal: optionally click end-turn so a real match can conclude.
        if self.end_turn and self.can_act():
            # human-ish pacing: only click end turn after a random delay
            if time.time() - self.last_click > random.uniform(20, 45):
                self.click_template("end_turn_btn")

    def handle_victory(self):
        if self.can_act():
            if self.click_template("victory_btn"):
                self.finish_round("victory")

    def handle_defeat(self):
        if self.can_act():
            if self.click_template("defeat_btn"):
                self.finish_round("defeat")

    def finish_round(self, result: str):
        self.round_count += 1
        elapsed = (time.time() - self.round_started) / 60
        log(f"== round {self.round_count} finished ({result}) after {elapsed:.1f} min ==")
        self.round_started = time.time()
        self.deck_step = "casual"
        # level-up / quest-complete screens follow; dismiss with any-click.
        self.dismiss = True
        self.dismiss_tries = 0
        # ★★ 2026-09-21 深夜(用户提议):**开一个 10 下的补点窗口**。
        #   胜负状态被识别并点击后,结算页还可能依次出现等级、任务和奖励页面；
        #   这些页面没有稳定的模板,所以用固定安全点每秒补点一次,最多十次。
        self._post_clicks_left = POST_MATCH_CLICK_N if POST_MATCH_CLICKS else 0
        self._post_clicks_done = 0
        self._post_click_last = 0.0     # 0 = 下一 tick 立刻点第一下
        if self._post_clicks_left:
            log(f"[post_match] 对局结束 -> 开 {POST_MATCH_CLICK_N} 下补点窗口"
                f"(每 {POST_MATCH_CLICK_GAP:.1f}s 一下,共 {POST_MATCH_CLICK_N} 下:"
                f"固定安全点 {POST_MATCH_POINT} + 抖动)"
                f" —— 覆盖认不出的结算/弹窗尾页(见 POST_MATCH_CLICKS)")
        time.sleep(2.5)

    def _post_match_clicking(self, state: str | None = None) -> bool:
        """
        打完一局之后的补点窗口:每秒点一下、点够 `POST_MATCH_CLICK_N` 下。

        返回 True = 补点还没做完(主循环这一 tick 不要干别的,继续让它点)。
        返回 False = 做完了(或没开),主循环照常走。

        ★ 该窗口只在识别并处理 victory/defeat 后开启,覆盖胜负、等级、任务
          和任务奖励等结算尾页。

        ★ 点的位置:**主页面的「开始」按钮那一块**(`POST_MATCH_POINT`)——
          用户 2026-09-21 指定的安全点。固定在同一个位置 + 抖动,
          **不再用那四个角**(实测那几处连点 3 次画面都不动,对这一屏不生效)。
          以后要换点,只改 `POST_MATCH_POINT` 一处。
        """
        if self._post_clicks_left <= 0:
            return False
        # 补点只针对胜负后的未知尾屏。只要已经识别到主菜单、匹配、
        # 选牌或新对局，说明结算流程已经结束，立即取消剩余点击。
        if state and state not in ("victory", "defeat"):
            log(f"[post_match] 已识别到 {state} -> 结束剩余补点"
                f"(还剩 {self._post_clicks_left} 下)")
            self._post_clicks_left = 0
            return False
        now = time.time()
        if now - self._post_click_last < POST_MATCH_CLICK_GAP:
            time.sleep(0.2)
            return True
        frame = self.grab_frame()
        if frame is not None and getattr(frame, "shape", None) and len(frame.shape) >= 2:
            fh, fw = int(frame.shape[0]), int(frame.shape[1])
        else:
            fw, fh = 1280, 720
        # ★ 固定点 + 抖动(夹在客户区内,别越界 —— 越界会被 SetCursorPos 静默夹回,
        #   那会让"右上/右下"变成同一个点,日志却照样说点过了;见 click_center 那段)。
        bx, by = POST_MATCH_POINT
        if bx > fw or by > fh:            # 兜底:窗口变小了(实测出现过 1024x576)
            bx, by = int(fw * 0.95), int(fh * 0.78)
        cx = min(fw - 10, max(10, bx + random.randint(-POST_MATCH_JITTER_X,
                                                     POST_MATCH_JITTER_X)))
        cy = min(fh - 10, max(10, by + random.randint(-POST_MATCH_JITTER_Y,
                                                     POST_MATCH_JITTER_Y)))
        self._post_clicks_left -= 1
        self._post_clicks_done += 1
        n_done = self._post_clicks_done
        log(f"[post_match] 补点 {n_done}/{POST_MATCH_CLICK_N} "
            f"client({cx},{cy})/{fw}x{fh}(开始按钮那块安全点;"
            f"对局已结束,结算尾页补点)")
        if not self.dry:
            try:
                sx, sy = self.client_to_screen(cx, cy)
                click(sx, sy)
            except Exception as e:      # 补点失败绝不许弄崩主循环(§7 第 57 条)
                log(f"[post_match] 这一下没点成:{type(e).__name__}: {e}")
        self._post_click_last = time.time()
        if self._post_clicks_left == 0:
            log(f"[post_match] {POST_MATCH_CLICK_N} 下补点用完 -> 交回主循环"
                f"(画面若已变回已知状态,`dismiss` 那套会照常收工)")
        return True

    # ---- dismiss tail screens (level-up / quest progress) ----
    #: 结算之后那些"任意点击跳过"的尾巴页 —— **点哪儿有效是实测出来的**。
    #  ★★ 用户 2026-09-13 深夜实测:**正中心点了不触发跳过**,要往旁边挪 ~50px
    #     (用户原话:"在中心位置点并不会触发跳过,要再往旁边挪 50 像素左右,左中下随意")。
    #  ★★★ 2026-09-19(v0.1.6)用户又提了一次,而且给了明确位置:
    #     *"卡结算页面的问题很普遍,能不能把结算页面的点击位置挪一下,
    #       挪到左到右四分之三屏幕的这中位置,不要居中"*
    #     ⇒ **首选点改成"左起 3/4、竖直居中"**(1280x720 基准下就是 **960, 360**),
    #       并且**不再把屏幕正中当候选**(原来是 (640,360))。
    #     ★ 为什么还留几个候选而不是只点一个点:同一天的实测结论是
    #       "某个位置在某些界面上无效" —— 只点一个点、无效就一直无效
    #       (`dismiss_tries` 到 12 次就放弃)。所以围着这个新位置留几个**同样不居中**
    #       的备选(上下 ±50、再往左 60),轮着点。
    # ★★★ 2026-09-21(用户当场给的新口径,替换掉"左起 3/4"那套):
    #   用户原话:**"没有(继续按钮),除了点中心点哪都能跳过,建议点左上右上左下右下"**。
    #   ⇒ ① 这一屏**没有真按钮**,所以"给它录个模板用 click_template 点"这条路**不成立**
    #        (`main_loop.py` 第 79~80 行那条"不要瞎填位置去点击"的规矩,在这里没有可点的目标);
    #     ② 候选点改成**四个角**,顺序就是用户说的 左上 -> 右上 -> 左下 -> 右下。
    #   ★ 为什么之前那套(960,360)/(960,410)/(960,310)/(900,360)要换掉:它四个点全都挤在
    #     屏幕中右部,一旦"这个位置在这种界面上无效"就是四个点一起无效(代码注释里
    #     自己写过这句实测结论)。四个角分布最开,而且"除了中心哪都能跳"这条已由用户确认,
    #     所以越远离中心越安全。
    #   ★ 留边距(`_INSET`)不是为了避开按钮,是为了**别贴到客户区最边上**:
    #     窗口有一半在屏外时 `SetCursorPos` 会把坐标静默夹回(`actions.py` 里的老坑),
    #     贴边点会点到窗口边框/HUD 上。
    DISMISS_INSET = 0.12        # 距边 12%(1280x720 -> 154 / 86)

    @classmethod
    def dismiss_points(cls, frame_w: int = 1280, frame_h: int = 720):
        """
        结算页/尾巴页的候选点击点(客户区坐标)—— **四个角**,左上开始。

        坐标 = 按 `DISMISS_INSET` 内缩后的四个角;顺序 = 左上 / 右上 / 左下 / 右下
        (用户 2026-09-21 指定的顺序)。判据与来由见上面那段注释。
        """
        ix = int(frame_w * cls.DISMISS_INSET)
        iy = int(frame_h * cls.DISMISS_INSET)
        left, right = ix, frame_w - ix
        top, bottom = iy, frame_h - iy
        return ((left, top), (right, top), (left, bottom), (right, bottom))

    def click_center(self):
        """
        点一下尾巴页把它跳过(位置轮换,见 `dismiss_points` 的实测说明)。

        ★ 名字保留(调用点太多),但**它现在点的是四个角,离屏幕中心最远** ——
          用户两次实测"点中心不生效",2026-09-21 又确认"除了中心哪都能跳过,
          建议点左上右上左下右下"。
        """
        # ★★★ 2026-09-21(M7)坐标别再用写死的 1280x720 基准:
        #   真实依据取自**这一帧自己的尺寸**(`frame.shape`)。
        #   为什么必须改:`main()` 虽然每次启动都试着 `set_window_client_size(1280,720)`,
        #   但**这一屏恰恰是最容易不是 1280x720 的地方** —— PC_STATE 里记着实测:
        #   "上一局结束后窗口变成 1024x576"。按 1280 算出来的四个角,(153,86) 与
        #   (1127,634) 在 1024x576 上分别落在 x=15% / x=110%(**右侧两个点直接跑到
        #   客户区外面**),`SetCursorPos` 会把越界坐标**静默夹回** -> 两个"右上/右下"
        #   其实是同一个位置,而日志照样说"跳过点击 #2 #4"。
        #   `frame_w=1280` 只作**兜底**:抓不到帧时保持老行为,不改变任何既有判据
        #   (这条兜底也是 A/B 回退路径:把 `grab_frame` 换成 `lambda: None`
        #    就退回"永远按 1280x720 算")。
        frame = self.grab_frame()
        if frame is not None and getattr(frame, "shape", None) and len(frame.shape) >= 2:
            frame_h, frame_w = int(frame.shape[0]), int(frame.shape[1])
        else:
            frame_w, frame_h = 1280, 720
        pts = self.dismiss_points(frame_w, frame_h)
        # ★★★ 2026-09-21 修 off-by-one(复核者查出来的):`tick_dismiss` 是
        #   **先 `dismiss_tries += 1` 再点** 的,所以第一次真正点出去时 tries 已经是 1,
        #   老写法 `pts[tries % 4]` 取到的是**索引 1 = (960,410)** ——
        #   用户明确指定的首选 "(960,360)" 要等到第 5 次才轮到,日志还把它写成"#2"。
        #   现在按 `tries - 1` 取,首选就是第一下。
        px, py = pts[(max(self.dismiss_tries, 1) - 1) % len(pts)]
        cx_client = px + random.randint(-25, 25)
        cy_client = min(frame_h - 20, max(20, py + random.randint(-15, 15)))
        log(f"[dismiss] -> 跳过点击 #{max(self.dismiss_tries, 1)} "
            f"client({cx_client},{cy_client})/{frame_w}x{frame_h}"
            f"(★点中心不生效;首选左上角,轮换 左上→右上→左下→右下)")
        if not self.dry:
            try:
                cx, cy = self.client_to_screen(cx_client, cy_client)
                # ★ 2026-09-21:接住返回值 —— 老代码把它丢了,于是"鼠标被系统挡住、
                #   根本没按下"时这里一个字都不写,日志却照样说"跳过点击 #N"
                #   (`actions.click` 那条路自己是有记账的,只是没人读)。
                if click(cx, cy) is False:
                    log("[dismiss] ⚠️ 这一下没点成(鼠标被系统挡住?坐标越界?)—— "
                        "下一轮还会再试")
            except Exception as e:
                log(f"[dismiss] click failed: {e}")
        self.last_click = time.time()
        self.dismiss_last = time.time()

    def tick_dismiss(self, state: str) -> bool:
        """
        While dismissing, keep clicking until we are back on a KNOWN screen
        (main_menu ideally). Unknown/blank screens get arbitrary clicks;
        known actionable screens stop dismissal. Returns True while we are
        still busy dismissing (so the loop should not run normal handlers).
        """
        if not self.dismiss:
            return False

        # We reached a screen we understand -> dismissal done.
        if state in (
            "main_menu", "deck_select", "queueing", "mulligan", "in_game",
        ):
            log(f"[dismiss] back on '{state}', dismissal complete")
            self.dismiss = False
            self.dismiss_tries = 0
            # ★ 2026-09-21:帧差状态和"已宣布改走慢速"的开关一起复位 —— 下一个
            #   结算页要用**全新**的基准帧(否则会拿上一局的画面当基准,第一下
            #   就报"没变"),告警也要能再响一次。
            self._dismiss_frame = None
            self._dismiss_stuck = 0
            self._dismiss_slow_said = False
            return False

        # Still on victory/defeat itself: 刚点完先给它一点时间切画面。
        # ★★★ 2026-09-21 **修死锁**(这是用户报的"卡在结算页出不来"的完整机理):
        #   老代码这一段**只睡不点、也不增 `dismiss_tries`** —— 于是只要画面一直判成
        #   victory/defeat,`dismiss_tries >= 12` 那个上限**永远不会触发**;
        #   而主循环在 dismiss 期间走的是 `continue`,**绕过**了 max_rounds 的退出检查
        #   ⇒ 引擎永久卡在结算页,而且**不会自己停**(唯一例外是那一 tick 恰好够 max_rounds)。
        #   为什么它容易被踩到:victory/defeat 的模板其实是"胜利/失败"**横幅文字**
        #   (`victory_btn` 中心 = 642,459)—— 正是用户两次实测说"点中心不生效"的那一块;
        #   点上去没反应 -> 状态还是 victory -> 老代码就永远在那里睡。
        #   现在:点完等 1.2s 还没切走,就**落进下面的轮换点击**
        #   (于是自动获得 12 次上限与计数,不会再无限等)。
        if state in ("victory", "defeat"):
            # 判据用现成的 `dismiss_last`(click_center 每点一次就刷新它),
            # 不再另开一个计数变量 —— 少一个状态就少一处能写错的地方。
            if time.time() - self.dismiss_last < 1.2:
                time.sleep(0.4)
                return True
            log(f"[dismiss] 点完 {time.time() - self.dismiss_last:.1f}s 还停在 {state} "
                "-> 当成'那一下没生效',按候选点继续点")
            # 落到下面:走带上限的轮换点击

        # Unknown tail screen (level-up / quest) -> arbitrary click to dismiss.
        # ★★★ 2026-09-21(M3 的**落地处**)"点了没生效"必须在**行为**上看得见 ——
        #   只多打一行日志、鼠标照旧盲点 12 次,那等于没做。所以这里加一道闸:
        #   一旦连续 3 次"画面几乎没变"(`_dismiss_stuck`,判据在
        #   `_dismiss_note_frame` 里,从开发树移植),**快速点击这一段就不再动手**。
        #   ★ 停的是**快的那一段**,不是全部:下面 M5 那条慢速重试还在(每慢一次
        #     仍会点一下,而且日志里看得见),所以不是"什么都不做"。
        #   ★ 恢复条件同样重要:画面真的变了(`_dismiss_note_frame` 会把
        #     `_dismiss_stuck` 归零)或状态切回已知画面(方法开头那段),
        #     点击就立刻回到正常节奏 —— 它只是"别再无脑重复同一件事",不是"关掉"。
        #   ★ 为什么这条闸只放在**快**的那一段:慢速段的间隔本来就拉到 3~15s,
        #     "每次都抢物理鼠标"这个代价已经被 M5 的退避处理掉了。
        fast_ok = self._dismiss_stuck < DISMISS_STUCK_LIMIT

        # ★★★ 2026-09-21(M5)**12 次用尽之后不许"什么都不做"**。
        #   老代码是 `dismiss = False; dismiss_tries = 0; return False` ——
        #   于是主循环立刻回去跑常规 handler:状态还是认不出的奖励页/结算页,
        #   `state -> None` -> 走 "unknown screen" 那条分支 **sleep(2)**,
        #   一 tick 一 tick 地空转到天荒地老,**日志里一个字都没有**。
        #   用户反馈过的那类"界面卡住不动、也没有任何提示",正是这个形状。
        #   ⇒ 现在改成:**保留 dismiss=True + 退避重试**(间隔逐次拉长,见
        #     `_dismiss_retry_gap`),并且**至少打一条 ⚠️** 说明"不是放弃了,
        #     是改成慢速重试"。这样屏幕上多多少少还有人在点,日志里也看得见。
        #   ★ 这里**不再**重置 `dismiss_tries`:快/慢两段的计数放在同一个变量上,
        #     于是"已经试了多少次"只可能有一个真值(判据只有一处),
        #     而且点击落点 `pts[(tries-1) % 4]` 会继续往下轮换。
        #   ⚠️ 卡死风险对照:慢速重试**不是**死循环 —— 退出条件有三条:
        #     ① 画面切回任何一个已知状态(方法开头那段);② `--max-rounds` 达标
        #     (主循环里,2026-09-21 M6 已经把退出检查挪到 `continue` 之前);
        #     ③ 有人去关掉程序。**这里故意不自动退出**:排队/对手回合/加载都
        #     可能长时间没反应,见到"久"就退会误伤正常对局(PC_STATE §7 那条
        #     "不要自动退出"的规矩)。
        #
        # ★★ 2026-09-21 **M3 与 M5 的接缝(写用例时才量出来的)**:
        #   M3 判定"点了没生效"之后会停掉**快**的那一段,而慢速那一段最早也要
        #   `dismiss_tries` 走满 `DISMISS_MAX_FAST`(12)才启动 —— 两段一叠加就
        #   会出现一个**谁都不点**的缝:快速段被 M3 停了、计数停在 4,于是永远
        #   到不了 12,慢速段永远不启动 ⇒ 屏幕上再没人点,`dismiss` 却一直是 True
        #   (主循环那边以为"还在跳过"),这正好是 M3/M5 想要避免的那种"什么都不做"。
        #   ⇒ 判据改成:**只要快速段被 M3 停了,就立刻改走慢速(退避)那一段** ——
        #     不必等计数满 12。理由很直:计数只是"试了几次"的记账,而 M3 已经
        #     给出了更强的结论("这几次点下去画面没动"),没有理由再空等 8 次。
        #   ★ 顺带保住"至少会再点一下":画面真的变了的话,慢速那一下的回读就会
        #     把 `_dismiss_stuck` 归零 -> 快点立刻恢复(见 `_dismiss_note_frame`)。
        slow_mode = self.dismiss_tries >= DISMISS_MAX_FAST or not fast_ok
        if slow_mode:
            gap = self._dismiss_retry_gap()
            if self.dismiss_tries == DISMISS_MAX_FAST:
                log(f"[dismiss] ⚠️ 快速跳过已经试满 {DISMISS_MAX_FAST} 次、画面还是没切走"
                    f" -> **放弃快速跳过,改成慢速重试**(间隔从 {gap:.0f}s 起"
                    f"逐次拉长、封顶 {DISMISS_SLOW_CAP:.0f}s)。"
                    f"这不是放弃:每慢速一次还会点一下,日志里看得见;"
                    f"画面一旦切回已知状态就立刻恢复。")
            elif not fast_ok and self.dismiss_tries < DISMISS_MAX_FAST \
                    and not self._dismiss_slow_said:
                # ★ M3 提前触发的情形(还没试满 12 次):也要明说"改成慢速重试",
                #   否则日志里只有一条"停手不再点",读起来像**彻底放弃了**。
                #   `_dismiss_slow_said` 保证**只打一条**(这个分支会被反复走到)。
                self._dismiss_slow_said = True
                log(f"[dismiss] ⚠️ 连点 {self.dismiss_tries} 次画面都没变 -> "
                    f"**快速点击提前停手,改成慢速重试**(每 {gap:.0f}s 再试一下,"
                    f"逐次拉长、封顶 {DISMISS_SLOW_CAP:.0f}s)。这不是放弃;"
                    f"画面一变就立刻恢复成正常节奏。")
            elif self.dismiss_tries >= DISMISS_MAX_FAST \
                    and (self.dismiss_tries - DISMISS_MAX_FAST) % 10 == 0:
                # 慢速阶段不刷屏:每 10 次报一下"还在试"。
                log(f"[dismiss] 慢速重试中:已试 {self.dismiss_tries} 次,"
                    f"当前间隔 {gap:.0f}s(画面仍未切走)")
            if time.time() - self.dismiss_last > gap:
                self.dismiss_tries += 1
                self.click_center()
                self._dismiss_note_frame()
            else:
                time.sleep(0.4)
            return True

        if time.time() - self.dismiss_last > DISMISS_FAST_GAP:
            self.dismiss_tries += 1
            self.click_center()
            # ★ 2026-09-21(M3):点完**回读一帧**,和上一帧比(判据见
            #   `_dismiss_note_frame`)。放在 `click_center` **之后**是有意的:
            #   要比的是"点下去的**效果**",所以基准帧必须是**上一次点击之后**
            #   那一帧。
            self._dismiss_note_frame()
        else:
            time.sleep(0.4)
        return True

    def _dismiss_retry_gap(self) -> float:
        """
        慢速重试的当前间隔(秒)—— 逐次拉长、封顶(2026-09-21 M5)。

        `dismiss_tries` 已经超过 `DISMISS_MAX_FAST` 时:
        `DISMISS_SLOW_BASE + (tries - MAX)*STEP`,不超过 `SLOW_CAP`。
        为什么"越试越慢":见 `DISMISS_SLOW_BASE` 上面的注释(少抢鼠标、
        又让"还在试"这件事一直留在日志里)。这个函数在测试里也被直接调用,
        所以它**不碰鼠标、不改状态**,只读 `dismiss_tries`。
        """
        n = max(self.dismiss_tries - DISMISS_MAX_FAST, 0)
        return min(DISMISS_SLOW_BASE + n * DISMISS_SLOW_STEP, DISMISS_SLOW_CAP)

    def _dismiss_note_frame(self) -> None:
        """
        记下"这一下点完之后画面变了没有"(2026-09-21 M3)。

        ★★★ 判据是从**开发树**移植的:`C:\\Users\\31291\\Desktop\\kards-auto\\
          src\\main_loop.py` 第 766~789 行(`_stuck_ticks`/`_stuck_dead` 那一段,
          搜 `连点 3 次画面一点都没变`)。
        ★ 为什么可以移植、为什么现在才移:那棵树是本项目的**旧版/手机端那棵**,
          用户 2026-09-21 已明确决定**不再同步它** —— 但那段代码是**实机判据**
          (2026-09-19 现场:游戏进程 107% CPU 空转、点『结束回合』画面 0.00% 变化),
          判据本身跟"哪棵树"无关,所以照抄判据、**把这棵树的代码写过来**,
          而不是去动那棵树。移植时**判据一字未改**:仍然是"三通道逐像素最大差
          > 25 的像素占比 < 0.001"算"画面没动",仍然是**连续 3 次**才停手。
        ★ 收益(这是 M3 的全部意义):结算页原来**盲点 12 次**(每一次都要抢物理
          鼠标、还可能点到别的东西上),现在一旦"点了没生效"就**当场停手**,
          而且把这件事**变成日志里看得见的事实** —— 否则"卡在结算页"永远只能靠猜。
        ★ 注意它**只负责观察**:停手之后走的是 M5 那条慢速重试,**没有**把
          `dismiss` 置回 False —— 一置 False 主循环就会回去空转(那正是要修的病)。
        """
        try:
            # ★ 先等一小会儿再回读:点下去到画面真的切走之间有个过程,立刻回读
            #   多半拿到的是**还没变的同一帧**,那会把"正常但慢"误判成"没生效"。
            #   (`DISMISS_FRAME_SETTLE`,可调;A/B 回退:改成 0 就退回"点完立刻读")
            time.sleep(DISMISS_FRAME_SETTLE)
            after = self.grab_frame()
            if after is None:
                return
            # 灰度 + 缩到 1/4:差分只需要"变没变",不需要细节;小图也让
            # 这个字段的内存占用可以忽略(见 __init__ 里的说明)。
            if not hasattr(after, "shape") or len(after.shape) < 2:
                return
            small = after
            if small.shape[0] > 360 or small.shape[1] > 640:
                small = cv2.resize(small, (small.shape[1] // 4, small.shape[0] // 4))
            if small.ndim == 3:
                small = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            prev = self._dismiss_frame
            self._dismiss_frame = small
            if prev is None or prev.shape != small.shape:
                # 第一次点(或画面尺寸变了):没有可比的上一次,不算"没动"。
                # ★ 尺寸变了这一条是 2026-09-21 M7 带出来的:窗口尺寸一改,
                #   旧帧和新帧不同形状,直接相减会抛异常(而且也不是"没变")。
                return
            # ★★ 这里**只用 cv2、不用 numpy** —— 本模块从头到尾没有
            #   `import numpy`,第一版照抄开发树写成 `np.abs(...)` 的结果是
            #   **每次都抛 NameError**,被下面的 except 吞掉:判据表面上"跑过了",
            #   实际上一次都没生效(`_stuck_dead` 永远是 0、告警永远不响)。
            #   ⇒ 这正是本项目反复栽的那个形状:**判据在边界外悄悄失效、而且不报错**。
            #   `cv2.absdiff` 对 uint8 做饱和差分(不会像裸减那样回绕),
            #   再和常量比 -> 得到和开发树 `np.abs(...)>25` **同一个掩码**。
            diff = cv2.absdiff(small, prev)
            dd = float((diff > DISMISS_DIFF_THRESHOLD).mean())
            if dd < DISMISS_DIFF_MIN:
                self._dismiss_stuck += 1
            else:
                self._dismiss_stuck = 0
            if self._dismiss_stuck == DISMISS_STUCK_LIMIT:
                log(f"[dismiss] " + DISMISS_STUCK_NOTE
                    + f"(已试 {self.dismiss_tries} 次;帧差 dd={dd:.5f}"
                      f"<{DISMISS_DIFF_MIN})")
        except Exception as e:                # noqa: BLE001
            # ★ 观察代码绝不许弄崩主循环:这条规矩这个项目已经栽过(见
            #   `handle_in_game` 里"诊断代码绝不许弄崩主循环"那段)。
            # ★★ 但**"不崩"不等于"可以不做声"**:这套判据第一版就写错过一次
            #   (`np` 没 import),异常被这里吞掉,判据一次都没生效 —— 表面上
            #   "日志里没报错",实际上告警永远不会响。所以失败也要留痕,而且
            #   带异常类型(下一份日志就能定位)。
            log(f"[dismiss] ⚠️ 帧差判据这次没算成(跳过点击照旧,但"
                f"『点了没生效』这个告警这次是瞎的):{type(e).__name__}: {e}")

    # ---- per-round dispatch ----
    def handle_state(self, state: str):
        handlers = {
            "main_menu": self.handle_main_menu,
            "deck_select": self.handle_deck_select,
            "queueing": self.handle_queueing,
            "mulligan": self.handle_mulligan,
            "in_game": self.handle_in_game,
            "victory": self.handle_victory,
            "defeat": self.handle_defeat,
        }
        h = handlers.get(state)
        if h:
            h()

    def run(self) -> int:
        log(f"main_loop start (dry={self.dry} end_turn={self.end_turn} "
            f"max_rounds={self.max_rounds})")
        self.round_started = time.time()
        last_state_log = ""
        ticks = 0
        while True:
            ticks += 1
            if self.max_ticks and ticks > self.max_ticks:
                log(f"max_ticks reached ({self.max_ticks}), stopping")
                break
            # ★★ 2026-09-21 深夜:把 `--max-rounds` 的闸**挪到循环最上面**,
            #   但加一个条件:**补点窗口没做完就先别停**。
            #   为什么必须加这个条件:用户要的东西正是"对局结束后每秒点一次、
            #   持续十秒",而 `finish_round()` 是在**点按钮那一下**就把
            #   `round_count` +1 的 —— 闸在最上面的话,`--max-rounds 1`
            #   会在**第一下补点之前**就退出,那十下一下都跑不到(实测 run#7:
            #   5 行、2 秒退出,`[dismiss]`/`[post_match]` 一行都没有)。
            #   所以这里的口径是:**先把补点窗口跑完,再执行 max_rounds 退出**。
            #   ★ 循环里原来那道闸(下面 `if self._max_rounds_hit(): break`)照旧保留,
            #     两条路径都还要过 —— 这里只是"补点没做完时不许提前停"。
            #   ★★★ 2026-09-21 深夜(**顺序有讲究,踩过一次**):
            #     必须先把 `_post_clicks_left <= 0` 写在**左边**。
            #     原先写的是 `_max_rounds_hit() and self._post_clicks_left <= 0` ——
            #     Python 的 `and` 先算左边,于是**补点期间每一 tick 都会调
            #     `_max_rounds_hit()`**,而那个函数一判到就 log
            #     ⇒ 实机 run#11 / run#12 各刷出 **40 多行 `max_rounds reached, stopping`**,
            #       而引擎一下都没停(它正要跑完那十下)。
            #     "日志说停、实际没停"是这个项目最忌讳的东西 —— 所以这不是
            #     "少打一行"的问题,是**判据和事实不一致**。
            #   ★ 循环里原来那道闸(下面 L1041 那处)照旧保留,两条路径都要过。
            if self._post_clicks_left <= 0 and self._max_rounds_hit():
                break
            frame = self.grab_frame()
            if frame is None:
                log("KARDS window not found - waiting")
                time.sleep(5)
                continue

            # blank/occluded detection
            if frame.mean() < 10 or frame.std() < 8:
                self.blank_streak += 1
                if self.blank_streak == 1:
                    log("blank frame - window minimized/occluded?")
                if self.blank_streak > BLANK_TOLERANCE:
                    # window is not usable; do nothing until it recovers
                    time.sleep(10)
                    continue
            else:
                self.blank_streak = 0

            # ★★ 硬前提:窗口必须可见、不被遮挡(见 win.window_is_capturable)。
            #   截图走 mss 的屏幕矩形抓取(PrintWindow 对 GPU 窗口全黑),所以
            #   窗口一旦被盖住,我们抓到的就是**别人的画面**:差分报出假面板、
            #   扫描器"看"出根本不存在的牌、主循环还会照着假坐标点到别人窗口上。
            #   常见的盖住来源:别的自动化工具的 GUI / 模拟器窗口(ALAS 这类,
            #   它自己走 adb 不碰光标,但它的窗口会盖上来)、浏览器、聊天窗口。
            #   注意这挡不住"两个 main_loop 抢鼠标",那一条由启动时的
            #   acquire_single_instance_lock 挡。
            #   所以这个检查必须在**每个 tick 动作之前**做,不是启动时查一次。
            if not window_is_capturable(self.hwnd, quiet=True):
                self.occluded_ticks += 1
                if self.occluded_ticks == 1 or self.occluded_ticks % 30 == 0:
                    fg = foreground_window()
                    log("⚠️ KARDS 窗口不可见/被遮挡 -> 本 tick 不动作。"
                        f"(已持续 {self.occluded_ticks} tick;"
                        f"前台窗口 hwnd={fg} "
                        f"{win32gui.GetWindowText(fg)!r})"
                        " 请把 KARDS 置于最前,别让别的窗口盖住它。")
                time.sleep(2)
                continue
            if self.occluded_ticks:
                log(f"✅ KARDS 窗口恢复可见,继续(之前被挡 {self.occluded_ticks} tick)")
                self.occluded_ticks = 0

            state, matches = classify(frame, self.templates, self.states)
            if state != last_state_log:
                log(f"state -> {state}")
                last_state_log = state
            self.current_state = state

            # ★★ 2026-09-23:补点窗口只由 victory/defeat 识别后的
            #   `finish_round()` 开启。未知画面本身不再启动补点,避免对手回合
            #   的 `state=None` 被误判为结算页。
            if self._post_match_clicking(state):
                # ★ `_post_match_clicking()` 返回 True 有两种情况:
                #   ① 补点还有剩(`_post_clicks_left > 0`)—— 我们**故意不停**,
                #      所以这里不调 `_max_rounds_hit()`(它一判到就 log,
                #      会在没停的时候刷出几十行"stopping";run#11 实测 40+ 行)。
                #      让它 `continue`,下一 tick 接着点。
                #   ② 这一 tick 刚好点完最后一下(返回 True 但剩 0)——
                #      这时才该问"要不要停",并且**允许它 log**(确实要停了)。
                if self.max_ticks and ticks > self.max_ticks:
                    break
                if self._post_clicks_left > 0:
                    continue
                if self._max_rounds_hit():
                    break
                continue

            # Dismiss tail screens (level-up/quest) first.
            if self.dismiss:
                busy = self.tick_dismiss(state)
                if busy:
                    time.sleep(0.8)
                    if self.max_ticks and ticks > self.max_ticks:
                        break
                    # ★★★ 2026-09-21(M6)**退出检查必须在 continue 之前**。
                    #   老代码把 `max_rounds` 那段放在循环末尾,而 dismiss 期间的
                    #   `continue` **绕过**了它 —— 只要人卡在结算页/未知奖励页,
                    #   `--max-rounds` 就永远不生效(和"死锁"叠加时,引擎既出不来
                    #   也不会自己停,只能去任务管理器杀进程)。
                    #   判据放在**这里**而不是循环末尾一处:两条路径都要过这道闸。
                    #   方法里的 `_max_rounds_hit()` 只读状态 + 打日志,**不点鼠标**。
                    if self._max_rounds_hit():
                        break
                    continue

            if state:
                self.handle_state(state)
            else:
                # unknown screen: wait, log only on change
                time.sleep(2)

            # ★★★ 2026-09-21 深夜(**实机抓到的第二个 bug**):这道闸也要加
            #   `_post_clicks_left <= 0` 的条件,和循环最上面那道(L912)一致。
            #   为什么:run#10 实测 —— `handle_state()` 里点完 `defeat_btn` ->
            #   `finish_round()` 开了 10 下补点窗口,但**同一 tick 继续往下走**
            #   就撞到这道闸:**窗口刚开、一下都还没点,引擎就退出了**
            #   (22:56:08 开窗口 -> 22:56:10 `max_rounds reached, stopping`)。
            #   用户原话:*"到了对局结束的时候他又不点"* —— 就是这一行。
            #   ⇒ 口径统一成一句:**补点窗口没跑完,任何一道 max_rounds 闸都不许停。**
            #   ★ 顺序同上:`_post_clicks_left <= 0` 必须在**左**(见 L912 那段)。
            if self._post_clicks_left <= 0 and self._max_rounds_hit():
                break
            time.sleep(0.8)
        return 0

    def _max_rounds_hit(self, do_log: bool = True) -> bool:
        """
        `--max-rounds` 该不该停?(2026-09-21 M6)

        判据只有这一处 —— 主循环里有**两条**路径会走到"这一 tick 结束了"
        (dismiss 期间的 `continue` 和正常路径),两条都必须过这道闸。
        老写法把这段判据写在循环末尾,**dismiss 那条 `continue` 绕过了它**。
        ★ 数的是"打完一整局"(`finish_round` 里 +1),不是回合数 ——
          帮助文本已经写明(见 `--max-rounds` 的 help)。

        ★★★ 2026-09-21 深夜:`do_log=False` 是**补点窗口期间**专用的。
          为什么必须加:补点窗口那十下我们**故意不停**(要先把十下点完),可
          `_max_rounds_hit()` 在一个 tick 里会被调 3 次(顶部闸 / 补点分支 / 末尾闸),
          它每次都 log —— 实机 run#11 把 `max_rounds reached, stopping`
          **打了 40 多行,而引擎一下都没停**。
          ⇒ 那就是"日志说了一件事、引擎做了另一件事",这个项目最忌讳这个
            (§7:"我说修好了,先问哪一帧能证明")。
          所以:**判到但不打算停**时由调用方传 `do_log=False`,
          "要停"这个事实只在**真的停的那一刻**说一次。
        """
        if self.max_rounds and self.round_count >= self.max_rounds:
            if do_log:
                log("max_rounds reached, stopping")
            return True
        return False


def main() -> int:
    set_dpi_aware()
    ap = argparse.ArgumentParser(description="KARDS grind main loop (M2)")
    ap.add_argument("--proc", default="kards")
    ap.add_argument("--dry-run", action="store_true", help="log decisions, never click")
    ap.add_argument("--max-rounds", type=int, default=0,
                    help="stop after N finished **matches** —— 一局打完(出现胜/负结算)"
                         "才 +1,**不是回合数**;一局没结算完就永远不会停(0 = 不停)"
                         "。★ 2026-09-20 实机踩过:另一台机器把它读成'跑 1 轮',"
                         "跑了 5 个回合没停就记成疑点了 —— 行为本来就是对的,是这句"
                         "帮助文本有歧义(见 docs/ORDER_CARDS_REAL_TEST.md §6)")
    ap.add_argument("--max-ticks", type=int, default=0, help="test: stop after N loop ticks")
    ap.add_argument("--end-turn", action="store_true",
                    help="M2: auto-click end turn inside a match")
    ap.add_argument("--play", action="store_true",
                    help="M3: 对局中交给回合引擎(读费用→扫描→出牌→结束回合)")
    ap.add_argument("--fast-scan", action="store_true",
                    help="M3f: 用校准好的手牌坐标表直扫(需先跑 hand_calibrate.py)")
    ap.add_argument("--attack", action="store_true",
                    help="M4: 开启攻击阶段(默认关;逐张定位与'上前线'还没校准,见 PROJECT_STATE §10)")
    ap.add_argument("--no-lazy", action="store_true",
                    help="关掉惰性扫描(回到回合开始读整手牌;慢但信息全)")
    ap.add_argument("--full-frame-state", action="store_true",
                    help="状态识别退回【整帧】模板匹配(2026-09-13 起默认按每个模板"
                         "自己的 region 搜,快 ~39 倍;这个开关只用于万一 ROI 出问题时"
                         "一键退回老行为,见 ui_state.ROI_MATCH)")
    ap.add_argument("--allow-multi-instance", action="store_true",
                    help="跳过单实例锁(默认**不允许**第二个实例:两个实例会抢同一个鼠标,"
                         "扫描会被自己人中止成 `0 cards in 0.8s`)")
    # ---- 部署落点/松手时机(2026-09-11 下午,用户实机确认后新增)----
    # 背景:用户实测 ①拖到**已有卡的位置**上松手 = 牌**回手**(游戏不会自动吸附),
    #            ②快松 vs 停一秒再松,结果不同且**稳定复现**。
    # 这几个开关就是为了在一局里原地 A/B,不用改代码重跑。
    ap.add_argument("--dwell", type=float, default=None,
                    help="拖到目标后**保持按住**多少秒再松手(默认 1.0;想对比快松就传 0.2)")
    ap.add_argument("--press-delay", type=float, default=None,
                    help="按下之后等多少秒才开始移动(默认 0.25;太短可能没进拖拽态)")
    ap.add_argument("--slot-tries", type=int, default=None,
                    help="同一张牌最多试几个落点(默认 2;1 = 一次不成就不试)")
    ap.add_argument("--random-drop", action="store_true",
                    help="退回**老的随机落点**(用于 A/B 证明'选空槽位'确实有用)")
    ap.add_argument("--drop-y", type=int, default=None,
                    help="读不到我方那一行时的兜底落点 y(默认 500)")
    ap.add_argument("--no-hover-before-press", action="store_true",
                    help="退回老行为:按下之前**不等**扇形展开(只等 0.15s)。"
                         "默认是等 —— 身份是在扇形展开那一帧认的,按下也必须在同一个"
                         "状态(实机证据:第 6/7 回合'百舌鸟'抓成了邻居那张 3 费牌)。"
                         "这个开关只为实机 A/B 留的。")
    ap.add_argument("--no-hand-memory", action="store_true",
                    help="关掉**手牌记忆**(退回'每个探针都老实悬停'的老行为)。"
                         "手牌记忆按【从左到右的次序】记住上一轮的牌,跳过已知出不起/"
                         "不是单位的探针;见 src/hand_memory.py。")
    args = ap.parse_args()

    # 把开关应用到模块(这些模块都是在**调用时**读自己的常量的,所以这里改了就生效)
    import actions as actions_mod
    import deploy as deploy_mod

    if args.dwell is not None:
        actions_mod.DWELL = args.dwell
        log(f"拖拽停顿 DWELL={args.dwell}s")
    if args.press_delay is not None:
        actions_mod.PRESS_DELAY = args.press_delay
        log(f"按下等待 PRESS_DELAY={args.press_delay}s")
    if args.slot_tries is not None:
        deploy_mod.MAX_SLOT_TRIES = args.slot_tries
        log(f"落点重试上限 MAX_SLOT_TRIES={args.slot_tries}")
    if args.random_drop:
        deploy_mod.deploy_candidates = lambda field, debug=False: [
            deploy_mod.random_drop_point()]
        log("⚠️ 退回随机落点(老行为,用于 A/B)")
    if args.drop_y is not None:
        deploy_mod.FALLBACK_DROP_Y = args.drop_y
        log(f"兜底落点 y={args.drop_y}")
    if args.no_hover_before_press:
        deploy_mod.HOVER_BEFORE_PRESS = False
        log("⚠️ 退回老行为:按下之前不等扇形展开(A/B 用)")
    if args.no_hand_memory:
        import hand_scanner_v2 as hs_mod
        hs_mod.USE_HAND_MEMORY = False
        log("⚠️ 关掉手牌记忆(每个探针都老实悬停,A/B 用)")

    # ★★ 单实例锁 —— 必须在做任何动作之前拿。
    #   实测:两个 main_loop 同时跑时,互相把对方的光标移走,于是双方的
    #   让行判据都一路为真,扫描全都在第一个探针中止(日志 `0 cards in 0.8s`),
    #   还会互相结束对方的回合。见 win.acquire_single_instance_lock 的说明。
    if not args.allow_multi_instance:
        locked, why = acquire_single_instance_lock()
        if not locked:
            # ★ 2026-09-19(v0.1.6):`why` 现在可能带着"占用者是谁"的说明
            #   (`held-by-other|占用者 PID=1234(还在跑)…`),所以**不能再用等号判**。
            if why.startswith("held-by-other"):
                _note = why.split("|", 1)[1] if "|" in why else ""
                log("❌ 已经有一个 main_loop 在跑了 —— 拒绝启动第二个实例。"
                    + (f"\n   {_note}" if _note else ""))
            else:
                log(f"❌ 单实例锁不可用({why})—— 为了不出现两个实例抢鼠标,"
                    f"同样拒绝启动。")
            log("   两个实例会抢同一个鼠标:一方把光标放到手牌上,另一方又把它"
                "移走,于是双方的让行判据都为真,扫描在第一个探针就中止"
                "(日志表现:`hand scan: 0 cards in 0.8s`)。")
            log("   先确认没有残留进程(引擎是独立进程,关面板不一定带走它):")
            log("     Get-CimInstance Win32_Process -Filter \"Name like '%python%'\" | "
                "Select ProcessId,CommandLine")
            log("   确认机器上确实没有别的实例、且锁机制坏掉时,才用 "
                "--allow-multi-instance 绕过。")
            return 2
        log("单实例锁已取得(main_loop 是唯一的实例)")

    # ★★★ 2026-09-19(实机):**开局第一行就报"卡库在不在"。**
    #   为什么非要这一行:卡库(`card_db/kards_data.json`)缺失时引擎
    #   **不崩、不报错**,只是 `match_name()` 永远返回 None ——
    #   于是"卡名 -> 费用"这条**最硬的路**整条失效,费用只剩徽章 OCR 兜底,
    #   而徽章 OCR 本来就不稳 -> 大部分牌 cost=None -> 惰性扫描认为一张都出不起
    #   -> **整回合一张牌不出**(2026-09-19 那一局第 1/2/4/6 回合)。
    #   当天日志里唯一的线索只有 `识别依据[... **卡名没读出**]`,完全指不到病因。
    try:
        from card_match import db_status
        _db = db_status()
    except Exception as _e:                      # 报不出来也不许挡住启动
        _db = f"⚠️ 卡库状态读不出来({type(_e).__name__}: {_e})"
    log(_db)
    # ★★★ 2026-09-19(v0.1.5):**同一类坑的第二次,所以这次一起报。**
    #   费用数字模板原来放在 `shots/kredits/samples_r1/`,而 `shots/` **不进发布包**
    #   -> 每个发布包都载入 0 个模板 -> 费用永远读不出 -> 每回合按"上一回合+1"推算
    #   -> 行动花掉的钱没人记 -> **没费用还去拖牌被游戏拒绝**。
    #   离线判据:60 张存帧喂 `read_kredits`,修之前 **0/60**,修之后 **48/60**
    #   (剩下 12 张根本不是对局画面,没有数字可读)。
    try:
        import kredits_templates as _kt
        log(_kt.status())
    except Exception as _e:
        log(f"⚠️ 费用数字模板状态读不出来({type(_e).__name__}: {_e})")

    # ★★★ 2026-09-20(指令卡):**同一类坑的第三次预防** —— 开局报"指令卡表在不在"。
    #   表(`config/order_plays.json`)缺失时引擎不崩,只是**指令一张都不打**
    #   (退回 2026-09-20 之前的行为),而那种"悄悄变笨"最难查。
    try:
        import orders as _ord
        log(_ord.status())
    except Exception as _e:
        log(f"⚠️ 指令卡表状态读不出来({type(_e).__name__}: {_e})")

    if args.full_frame_state:
        import ui_state as _ui
        _ui.ROI_MATCH = False
        log("状态识别退回整帧匹配(ROI_MATCH=False)—— 慢 ~39 倍,仅用于排查")

    # ★★★ 2026-09-13(第九个会话实机抓到的缺口):**强制客户区 1280x720**。
    #   档案 §5 写着"每次跑前必须 set_window_client_size",而**所有别的入口都有**
    #   (live_probe / hand_scanner_v2 / hover_dump / deploy / turn_test …),
    #   **只有 main_loop 漏了** —— 于是窗口一旦被改成别的尺寸(上一局打完、
    #   游戏自己重置、或者用户手动缩放),主循环会**静默地全程用错尺寸**:
    #   所有按坐标的判据全废 —— state 一个模板都匹配不上 -> `state -> None`
    #   -> 主循环只在"未知画面"分支里空转,**什么都不做**,而日志里看不出原因。
    #   实测:上一局结束后窗口变成 1024x576,再跑主循环就完全没有反应。
    #   ★ 只认尺寸、不认位置(§7 第 2/3 条:客户区正好 1280x720 就没问题,
    #     窗口在哪不影响 client 坐标)。
    wins0 = find_by_process(args.proc)
    if wins0:
        try:
            set_window_client_size(wins0[0]["hwnd"], 1280, 720)
            # ★ 回读 **client** rect 才算数:`set_window_client_size` 返回的是
            #   窗口 frame 的 (l,t,r,b) —— 直接拿它当宽高会打出一条假日志
            #   (实测打出来是 1507x1026)。§7 第 2/3 条:这里**只认尺寸**。
            cr = win32gui.GetClientRect(wins0[0]["hwnd"])
            cw, ch = cr[2] - cr[0], cr[3] - cr[1]
            if (cw, ch) == (1280, 720):
                log(f"窗口客户区已强制为 1280x720(实际 {cw}x{ch})")
            else:
                log(f"⚠️ 客户区设成 {cw}x{ch},不是 1280x720 —— "
                    f"后面所有按坐标的判据(模板/落点/扫描)都可能失效,请检查窗口")
        except Exception as e:
            log(f"⚠️ 设置窗口尺寸失败({type(e).__name__}: {e})—— "
                f"后面所有按坐标的判据都可能失效")
    else:
        log(f"⚠️ 没找到 {args.proc} 窗口(后面每次 tick 都会重新找)")

    ctl = Controller(args.proc, args.dry_run, args.max_rounds, args.end_turn,
                     play=args.play, fast_scan=args.fast_scan,
                     attack=args.attack, lazy_scan=not args.no_lazy)
    ctl.max_ticks = args.max_ticks
    try:
        return ctl.run()
    except KeyboardInterrupt:
        log("interrupted by user")
        return 0
    except Exception:
        # ★★★ 2026-09-15 新增:**崩在哪一行,必须落在项目自己的文件里。**
        #   证据:上一轮(10:49:03)整跑在"第一发打单位"的日志之后**无声无息没了**,
        #   日志最后一行停在 `[attack] #1 我方 infantry ... -> 敌方前线单位 ...`,
        #   而异常栈只到了 stderr —— stderr 归后台任务所有,后台任务一结束那段
        #   文字就再也拿不回来,只能靠猜是哪一段代码炸的(§7 第 57 条的反面:
        #   观测信息不能只活在控制台里)。
        #   这里**不改任何判据**,只在异常逃到顶层时把原始 traceback 原样写进
        #   `logs/main_loop.log`,并返回 3 让外面能看出"这局是崩了,不是打完了"。
        import traceback
        log("💥 未捕获异常,引擎在这里停下(以下为原始 traceback):")
        for ln in traceback.format_exc().rstrip().splitlines():
            log("    " + ln)
        return 3


if __name__ == "__main__":
    sys.exit(main())
