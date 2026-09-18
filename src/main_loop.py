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
            click(cx, cy)
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
                log(f"[in_game] turn engine error: {type(e).__name__}: {e}")
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
        time.sleep(2.5)

    # ---- dismiss tail screens (level-up / quest progress) ----
    #: 结算之后那些"任意点击跳过"的尾巴页 —— **点哪儿有效是实测出来的**。
    #  ★★ 用户 2026-09-13 深夜实测:**正中心点了不触发跳过**,要往旁边挪 ~50px
    #     (用户原话:"在中心位置点并不会触发跳过,要再往旁边挪 50 像素左右,左中下随意")。
    #  ⇒ 不再只点中心,而是**轮着点这几个位置**(每个间隔 1.8 秒):
    #     先点"中心偏左 120px",不行再点"中下",再"中心偏右",最后才回中心。
    #     这样即使某个位置在某些界面上无效,后面几次也会撞上有效的那一个 ——
    #     而以前**每次都点同一个点**,无效就一直无效(`dismiss_tries` 到 12 次就放弃)。
    DISMISS_POINTS = ((520, 360), (640, 470), (760, 360), (640, 360))

    def click_center(self):
        """点一下尾巴页把它跳过(位置轮换,见 DISMISS_POINTS 的实测说明)。"""
        frame_w, frame_h = 1280, 720
        px, py = self.DISMISS_POINTS[self.dismiss_tries % len(self.DISMISS_POINTS)]
        cx_client = px + random.randint(-25, 25)
        cy_client = min(frame_h - 20, py + random.randint(-15, 15))
        log(f"[dismiss] -> 跳过点击 #{self.dismiss_tries + 1} "
            f"client({cx_client},{cy_client})(★中心点不生效,轮换位置)")
        if not self.dry:
            try:
                cx, cy = self.client_to_screen(cx_client, cy_client)
                click(cx, cy)
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
            return False

        # Still on victory/defeat itself: not clicked through yet, wait.
        if state in ("victory", "defeat"):
            time.sleep(1.0)
            return True

        # Unknown tail screen (level-up / quest) -> arbitrary click to dismiss.
        if self.dismiss_tries >= 12:
            log("[dismiss] too many attempts, giving up until screen changes")
            self.dismiss = False
            self.dismiss_tries = 0
            return False

        if time.time() - self.dismiss_last > 1.8:
            self.dismiss_tries += 1
            self.click_center()
        else:
            time.sleep(0.4)
        return True

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

            # Dismiss tail screens (level-up/quest) first.
            if self.dismiss:
                busy = self.tick_dismiss(state)
                if busy:
                    time.sleep(0.8)
                    if self.max_ticks and ticks > self.max_ticks:
                        break
                    continue

            if state:
                self.handle_state(state)
            else:
                # unknown screen: wait, log only on change
                time.sleep(2)

            if self.max_rounds and self.round_count >= self.max_rounds:
                log("max_rounds reached, stopping")
                break
            time.sleep(0.8)
        return 0


def main() -> int:
    set_dpi_aware()
    ap = argparse.ArgumentParser(description="KARDS grind main loop (M2)")
    ap.add_argument("--proc", default="kards")
    ap.add_argument("--dry-run", action="store_true", help="log decisions, never click")
    ap.add_argument("--max-rounds", type=int, default=0, help="stop after N finished rounds")
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
            if why == "held-by-other":
                log("❌ 已经有一个 main_loop 在跑了 —— 拒绝启动第二个实例。")
            else:
                log(f"❌ 单实例锁不可用({why})—— 为了不出现两个实例抢鼠标,"
                    f"同样拒绝启动。")
            log("   两个实例会抢同一个鼠标:一方把光标放到手牌上,另一方又把它"
                "移走,于是双方的让行判据都为真,扫描在第一个探针就中止"
                "(日志表现:`hand scan: 0 cards in 0.8s`)。")
            log("   要么等它结束(或在那个窗口按 Ctrl+C),要么先确认没有残留进程:")
            log("     Get-CimInstance Win32_Process -Filter \"Name like '%python%'\" | "
                "Select ProcessId,CommandLine")
            log("   确认机器上确实没有别的实例、且锁机制坏掉时,才用 "
                "--allow-multi-instance 绕过。")
            return 2
        log("单实例锁已取得(main_loop 是唯一的实例)")

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
