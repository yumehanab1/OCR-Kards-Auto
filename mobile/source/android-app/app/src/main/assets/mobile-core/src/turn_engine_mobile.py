"""手机端回合引擎。

每次 ``think`` 只做一个决定。手机端没有鼠标悬停，因此手牌识别和 PC
端分开；动作、回合判定和结束回合验证都保持 fail-closed。
"""
from __future__ import annotations

import os
import random
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import mobile_hand as mh
import mobile_board as mb

# 结束回合后的等待窗口。按钮/画面信号优先，时间只作最后保险。
END_TURN_DELAY = (3.0, 6.0)
MAX_DEPLOYS_PER_TURN = 6
MAX_FAILED_ATTEMPTS_PER_STATE = 2
MAX_FAILED_ACTIONS_PER_TURN = 6
MAX_FAILED_DEPLOYS_PER_TURN = 6
END_TURN_RETRY = 240.0
END_TURN_STUCK_DIFF = 0.001
END_TURN_STUCK_CONFIRM = 3
END_TURN_MAX_RECLICKS = 3
END_TURN_NONE_CONFIRM = 2
OUR_TURN_NONE_CONFIRM = 2
# 新回合刚出现时给手机端渲染/费用徽章留出的稳定窗口。
TURN_START_SETTLE = 1.0


class MobileTurnEngine:
    """手机版行动链，所有外部动作都可以注入替身做离线验证。"""

    def __init__(self, hwnd=None, templates=None, log=print, dry=False,
                 drop=None, end_turn_delay=None, act_chain=True,
                 grab_frame=None, our_turn=None, deploy=None,
                 click_end_turn=None, move_front=None, attack_hq=None,
                 attack_unit=None, end_turn_state=None, trace=None,
                 trace_every_step=True, turn_start_settle=0.0, board_ready=None):
        self.hwnd = hwnd
        self.templates = templates or {}
        self.log = log or (lambda _m: None)
        self.dry = bool(dry)
        self.drop = drop or mh.DEPLOY_DROP
        self.end_turn_delay = end_turn_delay or END_TURN_DELAY
        self.act_chain = bool(act_chain)
        # 默认 0 保持离线替身即时；生产入口显式传 TURN_START_SETTLE。
        self.turn_start_settle = max(0.0, float(turn_start_settle or 0.0))
        self._turn_ready_at = 0.0

        self._grab = grab_frame or self._grab_real
        self._our_turn = our_turn or self._our_turn_real
        self._deploy = deploy or self._deploy_real
        self._click_end_turn = click_end_turn or self._click_end_turn_real
        self._move_front = move_front or self._move_front_real
        self._attack_hq = attack_hq or self._attack_hq_real
        self._attack_unit = attack_unit or self._attack_unit_real
        self._end_state = end_turn_state or self._end_turn_state_real
        self._board_stability = mb.BoardStability()
        self._board_ready = board_ready or self._board_ready_real

        self.phase = "wait_our_turn"
        self.deployed_this_turn = 0
        self.actions_this_turn = 0
        self._end_clicked_at = None
        self._end_btn_at_click = None
        self._end_btn_last = None
        self._end_btn_gone = False
        self._end_none_seen = 0
        self._end_prev_frame = None
        self._end_prev_shape = None
        self._end_stuck = 0
        self._end_btn_before = None
        self._end_reclick = 0
        self._end_fallback_at = 0.0
        self._end_need_click = False
        self._turn_started = time.time()
        self._last_status = ""
        self.last_end_turn_score = 0.0
        self.turns_seen = 0
        self._action_failures = {}
        self.failed_actions_this_turn = 0
        self._deploy_failures = {}
        self.failed_deploys_this_turn = 0
        self._not_our_seen = 0
        self._after_frame = None
        # One fresh-frame plan is shared by the real action hooks within think.
        # In particular a bomber must not reroll when a different hook is tried.
        self._combat_decision_context = None

        if trace is None:
            try:
                import mobile_trace
                trace = mobile_trace.MobileTrace(
                    log=self.log, every_step=trace_every_step)
            except Exception as e:  # tracing must never stop the engine
                self.log(f"[trace] 录像不可用({type(e).__name__}: {e}),照常跑")
                trace = None
        self.trace = trace
        try:
            import mobile_trace
            mobile_trace.set_recorder(trace)
        except Exception:
            pass

    def _grab_real(self):
        import platformapi
        return platformapi.get().capture_client(None)

    def _board_ready_real(self, frame):
        # The action hook obtains its own fresh frame and validates its actor.
        # Do not require a second full-board observation before choosing it.
        reason = mb.board_transition_reason(frame)
        if reason:
            return False, reason
        front = mb.frontline_state(frame)
        if front.get("owner") not in ("our", "enemy", "empty"):
            return False, "前线归属待确认: " + front.get("reason", "unknown")
        return True, "当前帧前线归属已确认"

    def _matched_end_button(self, frame):
        """回合门控与点击共用按钮颜色、ROI 和可靠分数门槛。"""
        from mobile_end_button import inspect_end_button
        observed = inspect_end_button(frame, self.templates, min_score=mb.END_TURN_MIN)
        self.last_end_turn_score = observed["score"]
        self.last_end_turn_color_reason = observed["reason"]
        return observed["state"], observed["score"], observed["box"]

    def _our_turn_real(self, frame):
        state, score, reg = self._matched_end_button(frame)
        return (state in ("white", "orange") and
                score >= mb.END_TURN_MIN and reg is not None)

    def _deploy_real(self, frame):
        return mh.deploy_one_unit(frame=frame, drop=self.drop, debug=True,
                                  authorize=self._our_turn,
                                  allow_attempt=self._allow_deploy_attempt)

    def _deploy_retry_key(self, frame, badge, target):
        """手牌布局/类型及当前候选作预算键；背景闪烁不恢复次数。"""
        def position(b):
            return (round(int(b["cx"]) / 16), round(int(b["cy"]) / 16), b.get("kind"))
        if hasattr(frame, "shape"):
            state = tuple(sorted(position(b) for b in mh.find_hand(frame, debug=False)))
        else:
            state = repr(frame)
        return state, position(badge), tuple(int(v) for v in target)

    def _allow_deploy_attempt(self, frame, badge, target):
        if self.failed_deploys_this_turn >= MAX_FAILED_DEPLOYS_PER_TURN:
            return False
        key = self._deploy_retry_key(frame, badge, target)
        return self._deploy_failures.get(key, 0) < MAX_FAILED_ATTEMPTS_PER_STATE

    def _note_deploy_attempt(self, attempt, ok):
        if attempt is None or not attempt.get("input_sent"):
            return
        key = self._deploy_retry_key(attempt["before"], attempt["badge"], attempt["target"])
        if ok:
            self._deploy_failures.pop(key, None)
        else:
            self._deploy_failures[key] = self._deploy_failures.get(key, 0) + 1
            self.failed_deploys_this_turn += 1

    def _mark_after(self, frame):
        self._after_frame = frame
        return frame

    def _trace(self, tag, before, state=None, lines=None, after=None):
        if self.trace is None:
            return
        try:
            if after is None:
                after = self._after_frame
            self.trace.record(tag, before, after=after, state=state,
                              lines=lines, turn=self.turns_seen)
        except Exception as e:
            self.log(f"[trace] 记这一步失败(不影响引擎):{type(e).__name__}: {e}")

    def _attack_unit_real(self, frame):
        import mobile_attack
        return mobile_attack.attack_unit(frame=frame, authorize=self._our_turn,
                                         allow_attempt=self._allow_action_attempt,
                                         decision_context=self._combat_decision_context)

    def _attack_hq_real(self, frame):
        import mobile_attack
        return mobile_attack.attack_hq(frame=frame, authorize=self._our_turn,
                                       allow_attempt=self._allow_action_attempt,
                                       decision_context=self._combat_decision_context)

    def _move_front_real(self, frame):
        import mobile_attack
        return mobile_attack.move_to_front(frame=frame, authorize=self._our_turn,
                                           allow_attempt=self._allow_action_attempt,
                                           decision_context=self._combat_decision_context)

    def _end_turn_state_real(self, frame):
        try:
            import mobile_board
            return mobile_board.end_turn_state(frame, self.templates)
        except Exception:
            return None

    def _action_retry_key(self, kind, frame, unit, target):
        """只按可见局面重开预算，背景/按钮闪烁不重置失败次数。"""
        def position(u):
            return (u["row"], round(int(u["badge"]["x"]) / 16),
                    round(int(u["badge"]["cy"]) / 16))
        if hasattr(frame, "shape"):
            units = tuple(sorted(position(u) for u in mb.actionable_units(frame)))
            hq = mb.hq_card(frame, "enemy") or {}
            front = mb.frontline_state(frame)
            targets = tuple(sorted((row, round(int(t["cx"]) / 16),
                                    round(int(t["cy"]) / 16), int(t.get("n_stats") or 0))
                                   for row, cards in (("support", mb.enemy_support_cards(frame)),
                                                      ("front", mb.enemy_front_cards(frame)))
                                   for t in cards))
            state = (units, hq.get("hp"), front.get("owner"), targets)
        else:
            state = repr(frame)  # 离线替身可显式提供不同局面标识。
        return (kind, state, position(unit), tuple(round(int(v) / 16) for v in target))

    def _allow_action_attempt(self, kind, frame, unit, target):
        if self.failed_actions_this_turn >= MAX_FAILED_ACTIONS_PER_TURN:
            return False
        key = self._action_retry_key(kind, frame, unit, target)
        return self._action_failures.get(key, 0) < MAX_FAILED_ATTEMPTS_PER_STATE

    def _note_action_attempt(self, attempt, ok):
        if attempt is None or not attempt.get("input_sent"):
            return
        key = self._action_retry_key(attempt["kind"], attempt["before"],
                                     attempt["unit"], attempt["target"])
        if ok:
            self._action_failures.pop(key, None)
        else:
            self._action_failures[key] = self._action_failures.get(key, 0) + 1
            self.failed_actions_this_turn += 1

    def _rearm(self, why, loud=True, rerun=True):
        if loud:
            self.log(f"[mobile] {why}")
        if rerun:
            self._board_stability.reset()
            self.phase = "wait_our_turn"
            self.deployed_this_turn = 0
            self.actions_this_turn = 0
            self._end_reclick = 0
            self._end_need_click = False
            self._action_failures = {}
            self.failed_actions_this_turn = 0
            self._deploy_failures = {}
            self.failed_deploys_this_turn = 0
            self._not_our_seen = 0
        self._end_clicked_at = None
        self._end_btn_at_click = None
        self._end_btn_gone = False
        self._end_btn_before = None
        self._end_none_seen = 0
        self._end_prev_frame = None
        self._end_prev_shape = None
        self._end_stuck = 0
        self._end_fallback_at = time.time() + END_TURN_RETRY
        self._turn_started = time.time()

    def _count_gone(self):
        self._end_none_seen += 1
        if self._end_none_seen >= END_TURN_NONE_CONFIRM:
            self._end_btn_gone = True

    def _stuck_frames(self, frame, st):
        if frame is None or not hasattr(frame, "shape"):
            self._end_prev_frame = None
            self._end_prev_shape = None
            self._end_stuck = 0
            return 0
        same = False
        if self._end_prev_shape == frame.shape and self._end_prev_frame is not None:
            try:
                import numpy as np
                d = np.abs(frame.astype(np.int16) -
                           self._end_prev_frame.astype(np.int16)).max(axis=2)
                same = float((d > 25).mean()) < END_TURN_STUCK_DIFF
            except Exception:
                same = False
        self._end_prev_frame = frame.copy()
        self._end_prev_shape = frame.shape
        if st is None:
            self._end_stuck = 0
        elif same:
            self._end_stuck += 1
        else:
            self._end_stuck = 0
        return self._end_stuck

    def _note_end_button(self, frame):
        st = self._end_state(frame)
        if self._end_clicked_at is None:
            self._end_btn_last = st
            return st

        waited = time.time() - self._end_clicked_at
        stuck = self._stuck_frames(frame, st)
        if stuck >= END_TURN_STUCK_CONFIRM:
            self._rearm(
                f"★ 点了结束回合之后画面**连续 {stuck} 帧一个像素都没动**、按钮还显示着 -> 那一发没生效(被丢了),立刻补点一次",
                loud=True, rerun=False)
            self._end_reclick += 1
            self._end_need_click = True
            return st

        if time.time() >= self._end_fallback_at:
            confirmed_gone = self._end_none_seen >= END_TURN_NONE_CONFIRM
            if confirmed_gone:
                self._rearm(
                    f"按钮消失过({self._end_none_seen} 帧),已经 {waited:.0f}s -> 按新回合继续",
                    loud=False)
                return st
            if st is None:
                self._count_gone()
                seen = "按钮一直是『没显示』"
            else:
                self._count_gone()
                seen = f"按钮一直是 {st}"
            self._rearm(
                f"点『结束回合』已经 {waited:.0f}s,{seen}(既没消失、也没变色、画面也没冻住)-> 最后一道保险:再点一次",
                loud=True, rerun=False)
            self._end_reclick += 1
            self._end_need_click = True
            return st

        if st is None:
            self._count_gone()
            self._end_btn_last = None
            return st

        self._end_none_seen = 0
        before = self._end_btn_before
        if (before is None or st != before or self._end_btn_gone):
            if before is None:
                why = f"点之前没看清按钮,现在看到 {st}"
            elif st != before:
                why = f"按钮 {before} -> {st}"
            else:
                why = f"按钮消失过又出现,还是 {st}"
            self._rearm(f"回合翻篇了({why},等了 {waited:.0f}s)", loud=False)
            self._end_reclick = max(0, self._end_reclick - 1)
        self._end_btn_last = st
        return st

    def _click_end_turn_real(self):
        f = self._grab()
        if f is None:
            return False
        pending = mb.board_transition_reason(f)
        if pending or mb.choice_modal(f)[0]:
            self._board_stability.reset()
            self.log("[mobile] 结束回合前画面待稳定，不点")
            return False
        state, score, reg = self._matched_end_button(f)
        if state is None or reg is None or score < mb.END_TURN_MIN:
            self.log(f"[mobile] 结束回合按钮匹配太弱({score:.2f}),不点")
            return False
        if isinstance(reg, dict):
            x, y, w, h = reg["x"], reg["y"], reg["w"], reg["h"]
        else:
            x, y, w, h = (int(v) for v in reg[:4])
        cx, cy = int(x + w // 2), int(y + h // 2)
        mh.click_client(cx, cy)
        self.log(f"[mobile] 结束回合:模板 {score:.3f} @ client({cx},{cy})")
        return True

    def think(self, frame=None):
        if frame is None:
            frame = self._grab()
        self._after_frame = None
        self._combat_decision_context = None
        if self.trace is not None:
            self.trace.after = None
        if frame is None:
            self._not_our_seen = 0
            return "抓不到帧"

        if not self._our_turn(frame):
            self._board_stability.reset()
            self._not_our_seen += 1
            if self._not_our_seen < OUR_TURN_NONE_CONFIRM:
                self._trace("回合信号未确认", frame, self.phase, [
                    "按钮暂时没识别到：本帧不动作，保留本回合计数与失败预算",
                    f"连续 {self._not_our_seen}/{OUR_TURN_NONE_CONFIRM} 帧"])
                return "不是我们的回合(待连续确认)"
            if self.phase != "wait_our_turn":
                self.phase = "wait_our_turn"
            self.deployed_this_turn = 0
            self.actions_this_turn = 0
            self._end_clicked_at = None
            self._end_btn_at_click = None
            self._end_btn_last = None
            self._end_btn_gone = False
            self._end_none_seen = 0
            self._end_btn_before = None
            self._end_reclick = 0
            self._action_failures = {}
            self.failed_actions_this_turn = 0
            self._deploy_failures = {}
            self.failed_deploys_this_turn = 0
            self._turn_ready_at = 0.0
            self._trace("不是我们的回合", frame, "wait_our_turn", [
                "对方回合(结束回合按钮没显示)—— 引擎一张牌都不许拖",
                f"end_turn_score={getattr(self, 'last_end_turn_score', float('nan')):.3f}"])
            return "不是我们的回合"

        self._not_our_seen = 0
        btn_state = self._note_end_button(frame)
        if self.phase != "playing":
            btn = {"white": "(还有费用,白色)",
                   "orange": "(费用用完,橙色)", None: ""}.get(btn_state, "")
            self.log(f"[mobile] 轮到我们了{btn}"
                     f"(end_turn_score={getattr(self, 'last_end_turn_score', float('nan')):.3f})")
            self.phase = "playing"
            self.turns_seen += 1
            self.deployed_this_turn = 0
            self.actions_this_turn = 0
            self._end_clicked_at = None
            self._end_btn_at_click = None
            self._end_btn_gone = False
            self._end_none_seen = 0
            self._end_btn_before = None
            self._end_reclick = 0
            self._turn_started = time.time()
            self._turn_ready_at = (self._turn_started + self.turn_start_settle
                                   if self.turn_start_settle > 0 else 0.0)
            if self.trace is not None:
                try:
                    self.trace.turn_overview(frame, state="in_game",
                                             note=f"T{self.turns_seen}_{btn_state or 'no-btn'}")
                except Exception as e:
                    self.log(f"[trace] 回合全景失败:{type(e).__name__}: {e}")

        if self._turn_ready_at:
            remaining = self._turn_ready_at - time.time()
            if remaining > 0:
                self._trace("回合开始稳定", frame, btn_state,
                            [f"等待手机端画面稳定 {remaining:.1f}s"])
                return f"回合开始稳定中({remaining:.1f}s)"
            self._turn_ready_at = 0.0

        if self._end_clicked_at is not None:
            waited = time.time() - self._end_clicked_at
            self._trace("等回合生效", frame, btn_state,
                        [f"本回合已经点过『结束回合』{waited:.0f}s,等按钮消失/变色"])
            return f"本回合已经点过『结束回合』({waited:.0f}s),等它生效"

        if self.dry:
            self._trace("dry-run", frame, btn_state, ["dry-run:不动作"])
            return "dry-run:不动作"

        board_ok, board_detail = self._board_ready(frame)
        if not board_ok:
            # 展示/动态画面无法得出“没有动作”的结论，也不能顺势结束回合。
            self._trace("画面待稳定", frame, btn_state, [board_detail])
            return "画面待稳定: " + board_detail

        deploy_detail = ""
        if self.deployed_this_turn < MAX_DEPLOYS_PER_TURN:
            mh.take_last_deploy_attempt()
            mh.take_last_deploy_pending()
            ok, detail = self._deploy(frame)
            attempt = mh.take_last_deploy_attempt()
            pending = mh.take_last_deploy_pending()
            self._note_deploy_attempt(attempt, ok)
            before = attempt["before"] if attempt is not None else frame
            if attempt is not None:
                self._after_frame = attempt.get("after")
            if ok:
                self._board_stability.reset()
                self.deployed_this_turn += 1
                self._turn_started = time.time()
                self.log(f"[mobile] 出牌成功({self.deployed_this_turn}):{detail}")
                self._trace("出牌成功", before, btn_state,
                            [f"第 {self.deployed_this_turn} 张", detail])
                return f"出了第 {self.deployed_this_turn} 张"
            if attempt is not None and attempt.get("input_sent"):
                self._board_stability.reset()
                self._trace("部署未确认", before, btn_state,
                            [detail, f"本回合部署失败输入 {self.failed_deploys_this_turn}/"
                             f"{MAX_FAILED_DEPLOYS_PER_TURN}",
                             "本步已输入，下一帧重新观察，不继续行动或结束回合"])
                return f"部署未确认({detail});下一帧重新观察"
            if pending:
                self._board_stability.reset()
                self._trace("画面待稳定", before, btn_state, [pending])
                return "画面待稳定: " + pending
            deploy_detail = detail
            self._trace("拒拖", frame, btn_state,
                        ["★ 这一步**没有动作**(拒拖 / 出不动)", detail])
        else:
            deploy_detail = f"本回合已出 {self.deployed_this_turn} 张(上限)"

        act_detail = ""
        # 成功次数只用于诊断。每个 think 最多接受一次行动，下一步仍须
        # 由新帧决定当前谁能行动；有限失败预算在各真实 hook 中单独约束。
        if self.act_chain:
            import mobile_attack
            self._combat_decision_context = {}
            for kind, hook, tag in (("attack_unit", self._attack_unit, "打敌方单位"),
                                    ("attack_hq", self._attack_hq, "打中敌方总部"),
                                    ("movefront", self._move_front, "上前线")):
                plan = self._combat_decision_context.get("plan")
                if plan is not None and plan.get("kind") != kind:
                    # The chosen hook still performs its own fresh preflight.
                    # Other hooks need not repeatedly capture a known mismatch.
                    continue
                # 不让上一步/旧替身的旁路记录误认成本次已输入。
                mobile_attack.take_last_attempt()
                mobile_attack.take_last_actor()
                mobile_attack.take_last_pending()
                ok, detail = hook(frame)
                attempt = mobile_attack.take_last_attempt()
                pending = mobile_attack.take_last_pending()
                self._note_action_attempt(attempt, ok)
                before = attempt["before"] if attempt is not None else frame
                if attempt is not None:
                    self._after_frame = attempt.get("after")
                if ok:
                    self._board_stability.reset()
                    self.actions_this_turn += 1
                    self._turn_started = time.time()
                    self.log(f"[mobile] {tag}({self.actions_this_turn}):{detail}")
                    self._trace(tag, before, btn_state,
                                [f"第 {self.actions_this_turn} 次", detail,
                                 "下一步重新截图统计可行动单位"])
                    return f"{tag} 第 {self.actions_this_turn} 次"
                if attempt is not None and attempt.get("input_sent"):
                    self._board_stability.reset()
                    self._trace("行动未确认", before, btn_state,
                                [detail, f"本回合失败输入 {self.failed_actions_this_turn}/"
                                 f"{MAX_FAILED_ACTIONS_PER_TURN}",
                                 "本步已输入，下一帧重新统计，不沿用旧帧继续动作"])
                    return f"行动未确认({detail});下一帧重新统计可行动单位"
                if pending:
                    self._board_stability.reset()
                    self._trace("画面待稳定", before, btn_state, [pending])
                    return "画面待稳定: " + pending
                if act_detail:
                    act_detail += " | "
                act_detail += detail

        detail = deploy_detail + (" 【行动链】" + act_detail if act_detail else "")
        waited = time.time() - self._turn_started
        need = random.uniform(*self.end_turn_delay)
        if waited < need:
            self._trace("出不动了(等延迟)", frame, btn_state,
                        [f"{need - waited:.1f}s 后结束回合", detail])
            return f"出不动了({detail});{need - waited:.1f}s 后结束回合"

        if btn_state == "white":
            self.log("[mobile] ⚠ 出不动了但『结束回合』还是**白色**(按用户说的=还有余量) -> 多半是行动链漏了能做的事,记一笔;照样结束回合,不许卡死")

        if self._end_reclick > END_TURN_MAX_RECLICKS and self._end_clicked_at is None:
            self._trace("补点到上限", frame, btn_state,
                        [f"★ 停手等人工看:{detail}"])
            return (f"出不动了({detail});『结束回合』补点到上限"
                    f"({END_TURN_MAX_RECLICKS} 次)都没生效 -> 停手等人工看")

        if self._end_need_click:
            self._end_need_click = False
            clicked = self._click_end_turn()
            if clicked:
                self._end_clicked_at = time.time()
                self._end_btn_at_click = btn_state
                self._end_btn_before = btn_state
                self._end_btn_gone = False
                self._end_none_seen = 0
                self._end_fallback_at = time.time() + END_TURN_RETRY
                self._trace("结束回合(补点)", frame, btn_state,
                            [f"补点第 {self._end_reclick} 次", detail])
                return f"出不动了({detail}) -> 结束回合(补点第 {self._end_reclick} 次)"
        elif self._click_end_turn():
            self._end_clicked_at = time.time()
            self._end_btn_at_click = btn_state
            self._end_btn_before = btn_state
            self._end_btn_gone = False
            self._end_none_seen = 0
            self._end_fallback_at = time.time() + END_TURN_RETRY
            self._trace("结束回合", frame, btn_state,
                        [f"按钮颜色={btn_state}", detail])
            return f"出不动了({detail}) -> 结束回合"

        self._trace("按钮找不到", frame, btn_state,
                    ["★ 结束回合按钮找不到 —— 这一步**没有动作**", detail])
        return f"出不动了({detail});但结束回合按钮找不到"


if __name__ == "__main__":
    import argparse
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="手机端回合引擎(单个 think() 试跑)")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--drop", default="")
    ap.add_argument("--no-act", action="store_true")
    ap.add_argument("--no-trace", action="store_true")
    args = ap.parse_args()
    if not (args.once or args.check):
        ap.print_help(); raise SystemExit(0)
    import ui_state
    meta, note = ui_state.load_platform_meta("android")
    print("模板表:", note)
    tpls = ui_state.load_templates(meta)
    drop = mh.DEPLOY_DROP
    if args.drop:
        drop = tuple(int(v) for v in args.drop.split(","))
    eng = MobileTurnEngine(templates=tpls, dry=args.check, drop=drop,
                           act_chain=not args.no_act,
                           trace_every_step=not args.no_trace)
    if eng.trace is not None and eng.trace.on:
        print("录像:", eng.trace.dir)
    print("think() ->", eng.think())
    print("phase=", eng.phase, "deployed=", eng.deployed_this_turn,
          "end_turn_score=", getattr(eng, "last_end_turn_score", None))
