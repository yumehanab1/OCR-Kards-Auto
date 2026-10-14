"""APK combat using geometry and visible action markers, never required HP OCR.

Ordinary completed but unverified gestures quarantine their actor for this
turn; uncertain dispatch still raises through the runtime. A successful move
does not quarantine an orange actor. Current support fighters exclude only
intercepted bomber target categories before dispatch.
"""
from __future__ import annotations

COMBAT_KINDS = frozenset(("attack_hq", "attack_unit", "move_front", "movefront"))
ATTACK_OBSERVE_SECONDS = 18.0
REMOVAL_OBSERVATIONS = 3
REMOVAL_STABLE_SECONDS = 1.0
ATTACK_SAMPLE_GAP = .5


def attack_after_samples(ma, mb, timeout, clock=None, sleep=None):
    """APK attack-only cadence; retain the core's transition/owner/motion gates."""
    import time
    clock, sleep = clock or time.monotonic, sleep or time.sleep
    previous = None
    started = clock()
    while clock() - started <= max(0., timeout):
        frame = ma._grab()
        reason = "抓不到结果帧" if frame is None else mb.board_transition_reason(frame)
        if not reason and mb.frontline_state(frame).get("owner") not in ("our", "enemy", "empty"):
            reason = "结果帧前线归属待确认"
        if reason:
            previous = None
            yield frame, False, reason
        else:
            stable = previous is not None and mb.board_motion(previous, frame) <= mb.BOARD_MOTION_MAX
            previous = frame
            yield frame, stable, "" if stable else "等待连续两张稳定结果帧"
        sleep(ATTACK_SAMPLE_GAP)


def actor_options(obs, actor, *, allow_unknown_guard=False):
    """The existing targeting rules with HQ health made optional."""
    import mobile_combat_policy as policy
    owner, typ, row = obs["owner"], actor.get("type", "unknown"), actor.get("row")
    empty, plan, nearest = policy._empty, policy._plan, policy._nearest
    if typ not in policy.TYPES or row not in ("support", "front"):
        return empty("pending", "单位类型或所在行未确认，本次跳过")
    fronts, hq = obs.get("enemy_front", []), obs.get("hq")
    if typ in policy.GROUND and row == "support":
        if owner == "enemy":
            legal = [c for c in fronts if not c.get("protected", False)
                     and (allow_unknown_guard or c.get("guard_state") != "unknown")]
            if not legal:
                return empty("pending", "敌前线没有已确认可攻击目标，本次跳过")
            return plan("attack_unit", actor, nearest(legal, actor), "enemy_front", owner,
                        "地面支援单位先清除敌方前线")
        return plan("movefront", actor, None, "frontline", owner, "地面支援单位上前线")
    if typ in policy.GROUND and owner != "our":
        return empty("pending", "地面前线单位与归属不一致，本次跳过")
    if not hq or hq.get("geometry_verified") is not True:
        return empty("pending", "总部结构位置未知，本次跳过")
    if typ == "artillery":
        return plan("attack_hq", actor, hq, "hq", owner, "火炮忽略守护，只攻击总部")
    if typ == "bomber":
        if owner == "enemy" and not fronts:
            return empty("pending", "敌前线目标集合未知，本次跳过")
        interceptors = [c for c in obs.get("enemy_support", [])
                        if c.get("row") == "enemy_support" and c.get("type") == "fighter"]
        if interceptors:
            # The PC rule and saved mobile refusal agree: support fighters
            # intercept bombers aimed at HQ/support, while enemy front remains
            # legal. Remove only the intercepted target category; no new roll.
            if owner == "enemy" and fronts:
                return plan("attack_unit", actor, nearest(fronts, actor), "enemy_front", owner,
                            "敌支援战斗机拦截总部攻击，轰炸机只攻击敌前线")
            return empty("pending", "敌支援战斗机拦截总部攻击，没有敌前线目标，本次跳过轰炸机")
        if fronts:
            return plan("bomber_choice", actor, {"hq": hq, "enemy_front": nearest(fronts, actor)},
                        "bomber_choice", owner, "轰炸机在总部与敌前线之间各半选择")
        return plan("attack_hq", actor, hq, "hq", owner, "轰炸机无敌前线时只攻击总部")
    guard = obs.get("guard", {})
    if guard.get("status") == "clear" or (allow_unknown_guard and guard.get("status") == "unknown"):
        return plan("attack_hq", actor, hq, "hq", owner, "总部无守护，优先攻击总部")
    if guard.get("status") == "guarded":
        guards = [c for c in guard.get("hq_guards", guard.get("guards", []))
                  if c.get("row") in ("enemy_support", "support")
                  and not c.get("protected", False)
                  and (allow_unknown_guard or c.get("guard_state") != "unknown")]
        if guards:
            return plan("attack_unit", actor, nearest(guards, actor), "guard", owner,
                        "先解除总部守护")
    return empty("pending", "总部守护或对应守护单位未知，本次跳过")


def choose(obs, *, rng=None, bomber_roll=None, allow=None):
    """Skip a locally unknown actor; retain a globally unknown frontline gate."""
    import mobile_combat_policy as policy
    if obs.get("owner") not in ("our", "enemy", "empty"):
        return policy._empty("pending", "前线归属待确认")
    # The core chooser still owns action priority and the one-time bomber roll.
    # Removing locally unsupported actors prevents their pending result from
    # blocking all other units or a normal end-turn.
    supported = [u for u in obs.get("units", []) if actor_options(obs, u)["kind"] != "pending"]
    result = policy._apk_original_choose(dict(obs, units=supported), rng=rng,
                                         bomber_roll=bomber_roll, allow=allow)
    if result["kind"] == "none" and len(supported) != len(obs.get("units", [])):
        result = dict(result, reason="未确认的单位或目标已跳过，没有其它可执行行动")
    return result


class TurnSkipLedger:
    """A failed actor cannot be rearmed by HP, slots, targets or other cards.

    The core has no persistent card identity across row reflow, duplicate art
    or effects. Therefore a failed actor conservatively quarantines its type
    for this turn. Other types remain available. No visual/numeric changes
    can reopen it; a newly recognized turn clears the quarantine.
    """
    def __init__(self):
        self.turn = None
        self.entries = []

    def sync(self, turn):
        if self.turn != turn:
            self.turn, self.entries = turn, []

    def record(self, frame, unit, typ):
        self.entries.append({"type": typ, "source_point": list(unit.get("from", ()))})

    def filter(self, frame, units):
        blocked_types = {entry["type"] for entry in self.entries}
        if "unknown" in blocked_types or None in blocked_types:
            return []
        return [u for u in units if u.get("type", "unknown") not in blocked_types]


def operation_marker(frame, unit):
    """Observe an orange enclosed marker, without identifying its numeral."""
    import cv2
    import numpy as np
    import unit_state as us
    try:
        b = unit["badge"]
        x, y, w, h = (int(b[k]) for k in ("x", "y", "w", "h"))
        if (frame.shape != (720, 1280, 3) or (w, h) != (28, 28)
                or not (0 <= x < x + w <= 1280 and 0 <= y < y + h <= 720)):
            return None
        hsv = cv2.cvtColor(frame[y:y+h, x:x+w], cv2.COLOR_BGR2HSV)
        state = us.analyze_digit(hsv[:, :, 2], hsv[:, :, 1], limits=us.DIGIT_LIMITS_MOBILE)
        if not state or state["state"] != "orange":
            return None
        mask, _ = us.enclosed_bright(hsv[:, :, 2])
        if not np.any(mask) or np.all(mask):
            return None
        return {"mask": mask, "box": (x, y, w, h)}
    except (KeyError, ValueError, TypeError, AttributeError, cv2.error):
        return None


def actor_removal(before, after, actor, mb, ma):
    """A complete own row lost exactly its selected actor, without HP OCR.

    Orange-candidate disappearance is never death evidence. The row must be
    structurally complete before and after; artwork still anywhere on our
    battlefield vetoes removal, including duplicate cards and a moving actor.
    The caller additionally requires a settled observation sequence.
    """
    import cv2
    import numpy as np
    result = {"actor_removed": False, "reason": "actor_row_unconfirmed"}
    if (not isinstance(before, np.ndarray) or not isinstance(after, np.ndarray)
            or before.shape != (720, 1280, 3) or after.shape != before.shape):
        return result
    row = actor.get("row")
    if row == "front":
        def row_cards(frame):
            owner = mb.frontline_state(frame).get("owner")
            cards = mb._front_cards(frame)
            if owner == "empty" and not cards:
                return []
            if owner != "our" or not cards:
                return None
            centers = sorted(c["cx"] for c in cards)
            if (abs(float(np.mean(centers)) - 640) > 12
                    or any(not 132 <= b-a <= 156 for a, b in zip(centers, centers[1:]))
                    or any(c.get("n_stats", 0) < 2 for c in cards)):
                return None
            return cards
    elif row == "support":
        import apk_deploy_target
        def row_cards(frame):
            cards, _, _ = apk_deploy_target._row(frame)
            return None if cards is None else [c for c in cards if c.get("row_kind") == "unit"]
    else:
        return result
    original, current = row_cards(before), row_cards(after)
    if original is None or current is None:
        return result
    card = actor["card"]
    matches = [c for c in original if abs(c["cx"]-card["cx"]) <= 18
               and abs(c["cy"]-card["cy"]) <= 18]
    result.update(row_before=len(original), row_after=len(current))
    if len(matches) != 1 or len(current) != len(original)-1:
        result["reason"] = "selected_actor_or_single_row_loss_unconfirmed"
        return result
    art = (card["x"]+8, card["y"]+32, card["x"]+card["w"]-8,
           card["y"]+card["h"]-40)
    changed = ma._diff_frac(before, after, art)
    result["actor_art_changed"] = changed
    if changed <= .20:
        result["reason"] = "actor_art_unchanged"
        return result
    x0, y0, x1, y1 = art
    original_art = cv2.cvtColor(before[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    if original_art.size == 0 or float(original_art.std()) < 8:
        result["reason"] = "actor_art_not_distinct"
        return result
    # Search both own rows: row migration cannot masquerade as combat death.
    battlefield = cv2.cvtColor(after[230:590, 200:1120], cv2.COLOR_BGR2GRAY)
    score = float(cv2.minMaxLoc(cv2.matchTemplate(
        battlefield, original_art, cv2.TM_CCOEFF_NORMED))[1])
    result["surviving_actor_art_score"] = score
    if score >= .75:
        result["reason"] = "actor_art_still_on_board"
        return result
    result.update(actor_removed=True, reason="complete_own_row_lost_selected_actor")
    return result


class SimpleCombat:
    def __init__(self, engine, event=None):
        import mobile_attack as ma
        import mobile_board as mb
        self.engine, self.ma, self.mb = engine, ma, mb
        self.event = event or (lambda *args: None)
        self.skips = TurnSkipLedger()
        self._observed_frame = self._observed_turn = None
        self._observed_units = []

    def observation(self, frame, unit=None):
        self.skips.sync(self.engine.turns_seen)
        observed = self.ma._apk_original_combat_observation(frame)
        allowed = self.skips.filter(frame, observed["units"])
        self._observed_frame, self._observed_turn = frame, self.engine.turns_seen
        self._observed_units = allowed
        observed["units"] = self.ma._selected(allowed, unit)
        return observed

    def allow_attempt(self, kind, frame, unit, target):
        self.skips.sync(self.engine.turns_seen)
        if self._observed_frame is not frame or self._observed_turn != self.engine.turns_seen:
            self.observation(frame)
        return len(self.ma._selected(self._observed_units, unit)) == 1

    def note_attempt(self, attempt, ok):
        if attempt is None or not attempt.get("input_sent"):
            return
        self.skips.sync(self.engine.turns_seen)
        if not ok:
            unit, before = attempt["unit"], attempt["before"]
            typ = unit.get("type") or self.mb.unit_combat_type(before, unit)
            self.skips.record(before, unit, typ)
            self._observed_frame = None
            self.engine.failed_actions_this_turn += 1
            self.event("combat_actor_skipped", {"turn": self.engine.turns_seen,
                "kind": attempt["kind"], "type": typ,
                "reason": "completed_input_without_visual_confirmation",
                "scope": "current_turn_same_type_identity_uncertain"})

    def attack_unit(self, frame=None, unit=None, dry_run=False, late_wait=None,
                    acted=None, authorize=None, allow_attempt=None, decision_context=None):
        return self._attack("attack_unit", frame, unit, dry_run, late_wait, authorize,
                            allow_attempt, decision_context)

    def _after_samples(self, timeout):
        return attack_after_samples(self.ma, self.mb, timeout)

    def attack_hq(self, frame=None, unit=None, dry_run=False, debug=True,
                  late_wait=None, acted=None, authorize=None, allow_attempt=None, decision_context=None):
        return self._attack("attack_hq", frame, unit, dry_run, late_wait, authorize,
                            allow_attempt, decision_context)

    def _attack(self, kind, frame, unit, dry_run, late_wait, authorize, allow_attempt, decision_context):
        ma, mb = self.ma, self.mb
        before, refusal = ma._prepare(frame, dry_run, authorize)
        if before is None:
            return False, refusal
        plan, refusal = ma._policy_action(before, kind, unit, dry_run, allow_attempt, decision_context)
        if plan is None:
            return False, refusal
        actor, target = plan["unit"], plan["target"]
        src, dst = actor["from"], (int(target["cx"]), int(target["cy"]))
        if dry_run:
            return False, f"dry-run:{kind} {src}->{dst};无需数值"
        marker = operation_marker(before, actor)
        target_owner = "enemy" if target.get("row") in ("enemy_front", "front") else "our"
        targets = ((mb.enemy_front_cards(before) if target_owner == "enemy"
                    else mb.enemy_support_cards(before)) if kind == "attack_unit" else [])
        ma._begin_attempt(kind, before, actor, dst)
        ma._drag(src, dst)
        wait = ma.ACTION_AFTER_WAIT if late_wait is None else late_wait
        after, confirmed, reason = None, False, "未确认，本回合跳过该单位"
        evidence, exhausted_streak, removed_streak, actor_streak, victories = {}, 0, 0, 0, 0
        stats_streak = 0
        removal_started = actor_started = stats_started = exhausted_started = None
        import time
        # Keep explicitly short diagnostic windows. Normal attacks observe
        # the loss-of-frontline animation to convergence without a second input.
        timeout = max(wait + ma.SETTLE_DRAG, ATTACK_OBSERVE_SECONDS) if late_wait is None else wait + ma.SETTLE_DRAG
        samples = self._after_samples(timeout) if late_wait is None else ma._after_samples(timeout)
        for current, stable, pending in samples:
            if current is None:
                exhausted_streak = removed_streak = actor_streak = stats_streak = victories = 0
                removal_started = actor_started = stats_started = exhausted_started = None
                continue
            after = current
            victory, _ = ma._victory_evidence(current)
            victories = victories + 1 if victory else 0
            if victories >= 2:
                confirmed, reason = True, "连续两张手游胜利帧"
                break
            if not stable or mb.end_turn_state(current) not in ("white", "orange"):
                exhausted_streak = removed_streak = actor_streak = stats_streak = 0
                removal_started = actor_started = stats_started = exhausted_started = None
                continue
            # This helper checks matching artwork/type and visible gray pixels;
            # its historical name says zero, but it reads no numeric value.
            exhausted = ma._zero_actor_exhausted(before, current, actor, plan["actor_type"], marker)
            outcome = (ma._target_outcome(before, current, target, targets, target_owner)
                       if kind == "attack_unit" else {})
            removed = outcome.get("target_removed") is True
            # The core already requires a complete three-stat source, one
            # target at the same location, unchanged artwork and a changed
            # health block. Retain that evidence when duplicate actor artwork
            # prevents proving the selected attacker's removal. No HP OCR.
            stats_changed = outcome.get("target_stats_changed") is True
            actor_outcome = (actor_removal(before, current, actor, mb, ma)
                             if kind == "attack_unit" else {})
            actor_removed = actor_outcome.get("actor_removed") is True
            now = time.monotonic()
            exhausted_streak = exhausted_streak + 1 if exhausted else 0
            removed_streak = removed_streak + 1 if removed else 0
            actor_streak = actor_streak + 1 if actor_removed else 0
            stats_streak = stats_streak + 1 if stats_changed else 0
            removal_started = (now if removal_started is None else removal_started) if removed else None
            actor_started = (now if actor_started is None else actor_started) if actor_removed else None
            stats_started = (now if stats_started is None else stats_started) if stats_changed else None
            exhausted_started = (now if exhausted_started is None else exhausted_started) if exhausted else None
            # The previous one-second sampler implied this duration between
            # gray observations. Faster polling must not weaken it.
            marker_settled = exhausted_streak >= 2 and now-exhausted_started >= REMOVAL_STABLE_SECONDS
            target_settled = removed_streak >= REMOVAL_OBSERVATIONS and now-removal_started >= REMOVAL_STABLE_SECONDS
            actor_settled = actor_streak >= REMOVAL_OBSERVATIONS and now-actor_started >= REMOVAL_STABLE_SECONDS
            stats_settled = stats_streak >= REMOVAL_OBSERVATIONS and now-stats_started >= REMOVAL_STABLE_SECONDS
            evidence = {"actor_marker_exhausted": exhausted, "marker_streak": exhausted_streak,
                        "actor_marker_span_seconds": now-exhausted_started if exhausted else 0,
                        "target_removed": removed, "removed_streak": removed_streak,
                        "target_stats_changed": stats_changed, "target_stats_streak": stats_streak,
                        "actor_removed": actor_removed, "actor_removed_streak": actor_streak,
                        "actor_removal": actor_outcome, "observation_timeout_seconds": timeout}
            if marker_settled or target_settled or actor_settled or stats_settled:
                confirmed = True
                reason = ("同一单位行动标识连续变灰" if marker_settled else
                          "目标在稳定板面连续确认消失" if target_settled else
                          "我方攻击单位在完整行中连续确认消失" if actor_settled else
                          "目标生命区在同一卡体连续确认改变")
                break
        ma._report(after)
        if ma._LAST_ATTEMPT is not None:
            ma._LAST_ATTEMPT["simple_combat_evidence"] = dict(evidence, reason=reason)
        if confirmed:
            ma._remember_actor(actor)
        detail = f"{kind} {src}->{dst};{reason};证据={evidence};总部血量非必要"
        ma._dump(kind, before, after, [detail, f"策略={plan}"])
        return confirmed, detail


def install(engine, event=None):
    """Rebind per-session state while retaining originals across CPython sessions."""
    import mobile_attack as ma
    import mobile_combat_policy as policy
    if not hasattr(policy, "_apk_original_choose"):
        policy._apk_original_choose = policy.choose
    if not hasattr(ma, "_apk_original_combat_observation"):
        ma._apk_original_combat_observation = ma._combat_observation
    policy._actor_options, policy.choose = actor_options, choose
    adapter = SimpleCombat(engine, event)
    ma._combat_observation = adapter.observation
    ma.attack_unit, ma.attack_hq = adapter.attack_unit, adapter.attack_hq
    engine._allow_action_attempt, engine._note_action_attempt = adapter.allow_attempt, adapter.note_attempt
    return adapter
