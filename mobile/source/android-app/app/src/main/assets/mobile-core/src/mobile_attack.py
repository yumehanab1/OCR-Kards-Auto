"""手机行动链：当前新帧确认归属后移动、攻击单位或总部。

根据已确认类型及守护选择总部、守护或敌前线。火炮/飞机不会被移动到前线。
未知归属或类型留待新帧确认，不等同于没有合法行动。输入前确认回合、稳定画面与
当前橙色候选，输入后验证结果；成功次数不会永久封锁单位。
"""

from __future__ import annotations

import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import mobile_board as mb          # noqa: E402
import mobile_hand as mh           # noqa: E402
import mobile_combat_policy as combat_policy  # noqa: E402

#: 上前线时往哪个 y 丢(前线虚线中心,`config/board_android.json`:340~360)。
FRONT_DROP_Y = mb.FRONTLINE_Y

#: 拖完等多久再抓帧(动画落定)。手机端动画比电脑端慢一点。
SETTLE_DRAG = 1.4

# 历史短观察窗口，仅保留供旧调用方显式选择；默认行动观察使用下方10s窗口。
# 总部生命刷新、爆炸、结果页都可能延后，结果必须连续两帧确认。
HP_LATE_WAIT = 4.0
HP_POLL = 1.0
# 真机截图/诊断约1秒，再加轮询间隔；横幅消退后还需两张稳定帧。
# 显式 late_wait=0 的短窗口诊断仍保留原来的 SETTLE_DRAG 余量。
ACTION_AFTER_WAIT = 10.0


def _grab():
    import platformapi
    return platformapi.get().capture_client(None)


# 旧单位只能作选择提示：必须在新截图的同行橙色候选中唯一匹配。
SELECT_TOL_X = 26
SELECT_TOL_Y = 40


def _key(u):
    """单位当前截图的徽章位置，不代表跨帧永久身份。"""
    return (int(u["badge"]["x"]), int(u["badge"]["cy"]))


# 保留成功动作的旧诊断接口；引擎不再用它封锁已行动单位。
LAST_ACTOR = None
_LAST_ATTEMPT = None
_LAST_PENDING = None


def take_last_pending():
    """待稳定不是无合法行动，供引擎停止本步而不结束回合。"""
    global _LAST_PENDING
    value, _LAST_PENDING = _LAST_PENDING, None
    return value


def _remember_actor(unit):
    """记录这一次成功动作的原位，仅供诊断。"""
    global LAST_ACTOR
    LAST_ACTOR = _key(unit)


def take_last_actor():
    """取走上一次成功动作的诊断位置。"""
    global LAST_ACTOR
    a, LAST_ACTOR = LAST_ACTOR, None
    return a


def take_last_actor_keys():
    """旧诊断接口兼容：只返回本次原位，不推断迁移身份。"""
    actor = take_last_actor()
    return ({actor} if actor is not None else set()), True


def take_last_attempt():
    """取走本次已发输入记录，验证失败也必须让引擎换新帧。"""
    global _LAST_ATTEMPT
    attempt, _LAST_ATTEMPT = _LAST_ATTEMPT, None
    return attempt


def _prepare(frame, dry_run, authorize):
    global LAST_ACTOR, _LAST_ATTEMPT, _LAST_PENDING
    LAST_ACTOR = _LAST_ATTEMPT = _LAST_PENDING = None
    before = frame if dry_run and frame is not None else _grab()
    if before is None:
        _LAST_PENDING = "抓不到新帧"
        return None, _LAST_PENDING
    if not dry_run and not (authorize(before) if authorize is not None
                            else mb.end_turn_state(before) in ("white", "orange")):
        _LAST_PENDING = "新帧未确认我方回合 -> 不动作"
        return None, _LAST_PENDING
    reason = mb.board_transition_reason(before)
    if reason:
        _LAST_PENDING = reason
        return None, "画面待稳定: " + reason
    if mb.choice_modal(before)[0]:
        _LAST_PENDING = "当前新帧存在选择界面"
        return None, "画面待稳定: " + _LAST_PENDING
    # Ownership, orange actor and type are read from this fresh frame by
    # _policy_action. Post-input evidence still needs independent observations.
    return before, ""


def _selected(units, unit):
    if unit is None:
        return list(units)
    key = _key(unit)
    matches = [u for u in units if u["row"] == unit.get("row")
               and abs(_key(u)[0] - key[0]) <= SELECT_TOL_X
               and abs(_key(u)[1] - key[1]) <= SELECT_TOL_Y]
    return matches if len(matches) == 1 else []


def _front_owner(frame):
    """归属未知必须报告 pending，不能被引擎当作无动作而结束回合。"""
    global _LAST_PENDING
    state = mb.frontline_state(frame)
    owner = state.get("owner", "unknown")
    if owner not in ("our", "enemy", "empty"):
        _LAST_PENDING = "前线归属待确认: " + state.get("reason", "unknown")
        return "unknown"
    return owner


def _combat_observation(frame, unit=None):
    units = [dict(u, type=mb.unit_combat_type(frame, u))
             for u in _selected(_units_after(frame), unit)]
    owner = _front_owner(frame)
    needs_hq = any(u["type"] in combat_policy.RANGED or u["row"] == "front" for u in units)
    hq = mb.hq_card(frame, "enemy") if needs_hq else None
    needs_guard = any(u["type"] == "fighter" or
                      (u["type"] in combat_policy.GROUND and
                       (u["row"] == "front" or owner == "enemy")) for u in units)
    guard = (mb.combat_guard_info(frame, hq=hq) if needs_guard
             else {"status": "unknown", "guards": []})
    # Enemy support fighters intercept bomber attacks on the HQ. Read their
    # existing local type evidence from this same frame; incomplete numerals
    # or a missing unrelated card must not block the whole observation.
    needs_interceptors = any(u["type"] == "bomber" for u in units)
    support = ([dict(c, row="enemy_support") for c in mb.enemy_support_cards(frame)]
               if needs_interceptors or (hq is not None and guard.get("status") == "guarded")
               else [])
    # The HQ shield establishes protection, but only its adjacent support cards
    # can provide it. Keep an explicit list even when adjacency is unconfirmed.
    guard = dict(guard, hq_guards=[])
    if hq is not None and guard.get("status") == "guarded":
        def card_key(card):
            return tuple(card[k] for k in ("x", "y", "w", "h"))
        row_cards = sorted(support + [hq], key=lambda c: c["cx"])
        def adjacent_cards(card):
            indices = [i for i, c in enumerate(row_cards) if card_key(c) == card_key(card)]
            if len(indices) != 1:
                return []
            index = indices[0]
            neighbors = [row_cards[i] for i in (index - 1, index + 1) if 0 <= i < len(row_cards)]
            # Mobile slots are ~144 px apart. Permit the known two-stat-box
            # center offset, but never jump across a missing card-sized slot.
            return [c for c in neighbors if abs(c["cy"] - card["cy"]) <= 40 and
                    0 < abs(c["cx"] - card["cx"]) <= 1.9 * max(c["w"], card["w"])]
        hq_neighbors = {card_key(c) for c in adjacent_cards(hq)}
        support_guards = [c for c in guard.get("guards", [])
                          if c.get("row") in ("enemy_support", "support")]
        protected_keys = {card_key(c) for c in guard.get("protected_units", [])
                          if c.get("row") in ("enemy_support", "support")}
        for candidate in support_guards:
            if card_key(candidate) not in hq_neighbors:
                continue
            protected = candidate.get("protected", False) or card_key(candidate) in protected_keys
            guard["hq_guards"].append(dict(candidate, protected=protected))
    fronts = [dict(c, row="enemy_front") for c in mb.enemy_front_cards(frame)]
    protected = {(c["x"], c["y"], c["w"], c["h"])
                 for c in guard.get("protected_units", []) if c.get("row") == "enemy_front"}
    for target in fronts:
        target["protected"] = (target["x"], target["y"], target["w"], target["h"]) in protected
        glyph = guard.get("detail", {}).get(f'enemy_front@{target["x"]},{target["y"]}')
        if glyph is not None:
            target["guard_state"] = glyph.get("state", "unknown")
    return {"owner": owner, "units": units, "enemy_front": fronts,
            "hq": hq, "guard": guard, "enemy_support": support}


def _policy_action(before, kind, unit, dry_run, allow_attempt, decision_context):
    """首次 hook 决策，之后只重验证；同一 think 共用一个可序列化 plan。"""
    global _LAST_PENDING
    context = decision_context if decision_context is not None else {}
    observation = _combat_observation(before, unit=unit)
    if unit is not None and not observation["units"] and "plan" not in context:
        return None, "指定单位不在新帧的唯一橙色候选中 -> 不动作"
    def allowed(plan):
        actor, target = plan["unit"], plan["target"]
        dst = ((int(actor["card"]["cx"]), FRONT_DROP_Y) if plan["kind"] == "movefront"
               else (int(target["cx"]), int(target["cy"])))
        return dry_run or allow_attempt is None or allow_attempt(plan["kind"], before, actor, dst)
    if "plan" not in context:
        context["plan"] = combat_policy.choose(observation, allow=allowed)
    plan = combat_policy.revalidate(observation, context["plan"], actor_match=_selected)
    if plan["kind"] == "pending":
        _LAST_PENDING = plan["reason"]
        return None, _LAST_PENDING
    if plan["kind"] != kind:
        return None, f"本步统一决策={plan['kind']}: {plan['reason']}"
    if not allowed(plan):
        return None, "当前局面行动失败重试已到上限 -> 不动作"
    return plan, ""


def _begin_attempt(kind, before, unit, target):
    global _LAST_ATTEMPT
    _LAST_ATTEMPT = {"kind": kind, "before": before, "unit": unit,
                     "target": target, "after": None, "input_sent": True}


def _dump(tag, before, after, lines):
    """把这一次行动的证据落盘(失败不影响动作)。"""
    try:
        d = os.path.join(mh.dump_root(), time.strftime("%Y%m%d_%H%M%S") + "_" + tag)
        os.makedirs(d, exist_ok=True)
        mh._w(os.path.join(d, "before.png"), before, "before.png")
        if after is not None:
            mh._w(os.path.join(d, "after.png"), after, "after.png")
        with open(os.path.join(d, "decision.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return d
    except Exception as e:                        # noqa: BLE001
        print(f"  [存帧] 失败(不影响动作):{type(e).__name__}: {e}")
        return ""


def _report(after):
    """
    把"动作刚做完那一刻"的帧交给录像(没开录像时是空操作)。

    ★ 为什么在这里而不是让引擎再抓一帧:只有**做动作的人**知道"我刚做完、
      现在这一帧就是结果";等 `think()` 返回之后再抓,画面早就不是这一步的了
      (见 `mobile_trace` 文件头那段)。
    """
    if _LAST_ATTEMPT is not None:
        _LAST_ATTEMPT["after"] = after
    try:
        import mobile_trace
        mobile_trace.report_after(after)
    except Exception:                             # noqa: BLE001
        pass


def _drag(from_xy, to_xy, settle=SETTLE_DRAG):
    """从客户区一点拖到另一点(平台层负责换算成屏幕坐标)。"""
    import actions
    import platformapi
    p = platformapi.get()
    sx0, sy0 = p.client_to_screen(None, int(from_xy[0]), int(from_xy[1]))
    sx1, sy1 = p.client_to_screen(None, int(to_xy[0]), int(to_xy[1]))
    actions.move_drag(sx0, sy0, sx1, sy1)
    time.sleep(settle)
    return (sx0, sy0, sx1, sy1)


def _units_after(frame):
    return mb.actionable_units(frame)


def _diff_frac(a, b, box, thr: int = 25) -> float:
    """两块图之间"变了多少"的比例(客户区坐标的框)。"""
    import numpy as np
    x0, y0, x1, y1 = (int(v) for v in box)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(a.shape[1], x1), min(a.shape[0], y1)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    d = np.abs(a[y0:y1, x0:x1].astype(int) - b[y0:y1, x0:x1].astype(int)).max(axis=2)
    return float((d > thr).mean())


def _after_samples(timeout):
    """有界采样；过渡/缺帧会打断连续稳定确认，不能推断单位消失。"""
    previous = None
    t0 = time.time()
    while time.time() - t0 <= max(0.0, timeout):
        frame = _grab()
        reason = "抓不到结果帧" if frame is None else mb.board_transition_reason(frame)
        if not reason and mb.frontline_state(frame).get("owner") not in ("our", "enemy", "empty"):
            reason = "结果帧前线归属待确认"
        if reason:
            previous = None
            yield frame, False, reason
        else:
            stable = (previous is not None and
                      mb.board_motion(previous, frame) <= mb.BOARD_MOTION_MAX)
            previous = frame
            yield frame, stable, "" if stable else "等待连续两张稳定结果帧"
        time.sleep(HP_POLL)


def move_to_front(frame=None, unit=None, dry_run=False, debug=True, acted=None,
                  authorize=None, allow_attempt=None, decision_context=None):
    """移动当前新帧里的橙色支援单位；原位及前线落点均变化才算成功。

    移动后可能灰、可能仍橙。`acted` 仅兼容旧调用，不能封锁新的可行动候选。
    """
    before, refusal = _prepare(frame, dry_run, authorize)
    if before is None:
        return False, refusal
    plan, refusal = _policy_action(before, "movefront", unit, dry_run, allow_attempt, decision_context)
    if plan is None:
        return False, refusal
    u = plan["unit"]
    src = u["from"]
    dst = (int(u["card"]["cx"]), FRONT_DROP_Y)
    c = u["card"]
    orig_box = (c["x"], c["y"], c["x"] + c["w"], c["y"] + c["h"])
    want_box = (c["x"], FRONT_DROP_Y, c["x"] + c["w"], FRONT_DROP_Y + c["h"])
    if dry_run:
        return False, f"dry-run:只算了坐标 客户区 {src} -> {dst}"
    _begin_attempt("movefront", before, u, dst)
    screens = _drag(src, dst)
    after, moved, stable = None, False, False
    gone = arrived = 0.0
    pending = ""
    for f, stable, pending in _after_samples(ACTION_AFTER_WAIT + SETTLE_DRAG):
        if f is not None:
            after = f
        if not stable:
            continue
        gone = _diff_frac(before, f, orig_box)
        arrived = _diff_frac(before, f, want_box)
        moved = gone > 0.20 and arrived > 0.12
        if moved:
            break
    if after is None:
        _report(None)
        return False, "拖完抓不到帧 —— 无法验证"
    after_units = _units_after(after)
    detail = (f"客户区 {src} -> {dst}(屏幕 {screens[0]}->{screens[2]});"
              f"原位变化 {gone * 100:.0f}% 前线落点变化 {arrived * 100:.0f}%"
              f";连续结果帧稳定={stable}"
              f" -> {'挪上去了' if moved else '**未确认移动**'}"
              + (f"({pending})" if pending else ""))
    _dump("movefront", before, after,
          ["tag=movefront",
           f"chosen 徽章={u['badge']['x']},{u['badge']['y']} 行={u['row']}",
           f"拖 客户区 {src} -> {dst}", f"屏幕 {screens}",
           f"原位变化率 = {gone * 100:.1f}%   前线落点变化率 = {arrived * 100:.1f}%",
           f"连续结果帧稳定 = {stable};待确认 = {pending}",
           f"结果 = {'上前线成功' if moved else '未确认移动'}",
           f"策略 = {plan}",
           f"拖后能行动候选:{[(a['badge']['x'], a['badge']['cy'], a['row']) for a in after_units]}"])
    if moved:
        _remember_actor(u)
    _report(after)
    return moved, detail


def _attacker_still_there(frame, u, tol_x: int = 26, tol_y: int = 40):
    """当前位置是否仍有橙色候选；本身不能证明攻击接受或拒绝。"""
    return bool([a for a in mb.actionable_units(frame)
                 if abs(a["badge"]["x"] - u["badge"]["x"]) <= tol_x
                 and abs(a["badge"]["cy"] - u["badge"]["cy"]) <= tol_y])


def _read_mobile_kredits(frame):
    """显式使用手机已标定框；配置缺失不退回PC框，也不猜费用。"""
    import json
    import kredits
    try:
        with open(os.path.join(mh.PROJECT_ROOT, "config", "board_android.json"),
                  encoding="utf-8") as source:
            box = tuple(json.load(source)["ours_k"]["box"])
        return kredits.read_kredits(frame, box=box, profile="mobile")
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _target_outcome(before, after, target, targets_before, owner):
    """目标行单位减少，或同位置卡体稳定而生命数字块改变。

    大片卡面/背景差分本身不能证明攻击生效。单位减少还要求原目标块明显改变；
    数字变化只接受原来三个统计框齐全、卡体位置未迁移的样本。
    """
    after_owner = mb.frontline_state(after).get("owner")
    targets_after = (mb.enemy_front_cards(after) if owner == "enemy"
                     else mb.enemy_support_cards(after))
    box = (target["x"], target["y"], target["x"] + target["w"], target["y"] + target["h"])
    changed = _diff_frac(before, after, box)
    cleared = owner == "enemy" and after_owner in ("empty", "our")
    fewer = len(targets_after) < len(targets_before)
    removed = (cleared or fewer) and changed > 0.20
    # A floating damage shield can hide the type/stat row while the target
    # remains in place. Missing typed candidates alone cannot prove removal.
    # Check a distinct upper artwork fragment outside that lower stat row.
    fragment_preserved, fragment_score = False, None
    if removed:
        import cv2
        fragment = (target["x"] + 12, target["y"] + 32,
                    target["x"] + target["w"] - 12, target["y"] + 60)
        x0, y0, x1, y1 = fragment
        original = before[y0:y1, x0:x1]
        current = after[y0:y1, x0:x1]
        distinct_fragment = False
        if original.size and original.shape == current.shape:
            original_gray = cv2.cvtColor(original, cv2.COLOR_BGR2GRAY)
            if float(original_gray.std()) >= 8:
                distinct_fragment = True
                fragment_score = float(cv2.matchTemplate(current, original, cv2.TM_CCOEFF_NORMED)[0, 0])
                fragment_preserved = (fragment_score >= .93 and
                                      _diff_frac(before, after, fragment) < .04)
        if fragment_preserved or (not cleared and not distinct_fragment):
            removed = False
    stats_changed = False
    matches = [c for c in targets_after if abs(c["cx"] - target["cx"]) <= 12
               and abs(c["cy"] - target["cy"]) <= 12]
    stats = sorted(target.get("stat_boxes", []))
    if not removed and len(matches) == 1 and len(stats) == 3:
        x, y, w, h = stats[-1]
        health_box = (x + 4, y + 4, x + w - 4, y + h - 4)
        art_box = (target["x"] + 8, target["y"] + 32,
                   target["x"] + target["w"] - 8, target["y"] + target["h"] - 40)
        stats_changed = (_diff_frac(before, after, art_box) < 0.04 and
                         _diff_frac(before, after, health_box) > 0.10)
    return {"target_removed": removed, "target_stats_changed": stats_changed,
            "target_changed": changed, "targets_before": len(targets_before),
            "targets_after": len(targets_after), "target_art_fragment_preserved": fragment_preserved,
            "target_art_fragment_score": fragment_score}


def _zero_operation_badge(frame, unit):
    """Confirm the current orange operation numeral is zero, not just affordable.

    Reuse the existing enclosed-digit extraction and numeral templates. The
    mask is local evidence for this one attempt, never a persistent unit lock.
    """
    import cv2
    import numpy as np
    import kredits_templates as kt
    import unit_state as us
    try:
        b = unit["badge"]
        x, y, w, h = (int(b[k]) for k in ("x", "y", "w", "h"))
        if frame.shape != (720, 1280, 3) or (w, h) != (28, 28):
            return None
        if x < 0 or y < 0 or x + w > 1280 or y + h > 720:
            return None
        hsv = cv2.cvtColor(frame[y:y+h, x:x+w], cv2.COLOR_BGR2HSV)
        state = us.analyze_digit(hsv[:, :, 2], hsv[:, :, 1], limits=us.DIGIT_LIMITS_MOBILE)
        if not state or state["state"] != "orange":
            return None
        mask, _ = us.enclosed_bright(hsv[:, :, 2])
        glyph = kt.normalize_glyph(mask.astype(np.uint8) * 255)
        bank = kt.build_templates()
        if glyph is None or set(bank) != set(range(10)) or any(not p for p in bank.values()):
            return None
        scores = {d: max(kt.score_against(glyph, t) for t in bank[d]) for d in bank}
        margin = scores[0] - max(scores[d] for d in bank if d != 0)
        if scores[0] < .80 or margin < .20:
            return None
        return {"mask": mask, "box": (x, y, w, h), "score": scores[0], "margin": margin}
    except (KeyError, ValueError, TypeError, AttributeError, cv2.error):
        return None


def _zero_actor_exhausted(before, after, unit, actor_type, numeral):
    """The same surviving actor must visibly retain its now-gray zero badge.

    Disappearance from the orange candidate list alone is insufficient. Keep
    the card artwork/type at its original location and require the previously
    observed numeral pixels to remain bright against their plate but turn gray.
    """
    import cv2
    import numpy as np
    import unit_state as us
    if numeral is None or mb.unit_combat_type(after, unit) != actor_type:
        return False
    c = unit["card"]
    art = (c["x"] + 8, c["y"] + 32, c["x"] + c["w"] - 8, c["y"] + c["h"] - 40)
    if _diff_frac(before, after, art) >= .04:
        return False
    x, y, w, h = numeral["box"]
    hsv = cv2.cvtColor(after[y:y+h, x:x+w], cv2.COLOR_BGR2HSV)
    mask = numeral["mask"]
    background = float(np.percentile(hsv[:, :, 2][~mask], 40))
    visible = float((hsv[:, :, 2][mask] >= background + 30).mean())
    return float(hsv[:, :, 1][mask].mean()) <= us.SAT_GREY_MAX and visible >= .80


def attack_unit(frame=None, unit=None, dry_run=False, late_wait: float = ACTION_AFTER_WAIT,
                acted=None, authorize=None, allow_attempt=None, decision_context=None):
    """统一策略只选敌前线或总部守护，返回 `(ok, detail)`。

    稳定结果帧后，以费用减少及目标消失/数字变化共同确认。零操作费须先认出
    橙0，再连续两次稳定观察到同单位变灰0、我方回合和目标结果，费用必须可读且不变。
    攻击者仍橙只说明还能行动；变灰本身也不能证明接受了攻击。
    """
    global _LAST_PENDING
    before, refusal = _prepare(frame, dry_run, authorize)
    if before is None:
        return False, refusal
    plan, refusal = _policy_action(before, "attack_unit", unit, dry_run, allow_attempt, decision_context)
    if plan is None:
        return False, refusal
    u, t = plan["unit"], plan["target"]
    owner = plan["front_owner"]
    # 守护可在支援或前线，不能按前线归属推断本次实际目标行。
    target_owner = "enemy" if t.get("row") in ("enemy_front", "front") else "our"
    targets = (mb.enemy_front_cards(before) if target_owner == "enemy"
               else mb.enemy_support_cards(before))
    src, dst = u["from"], (int(t["cx"]), int(t["cy"]))
    if dry_run:
        return False, f"dry-run:客户区 {src} -> 敌卡 ({t['x']},{t['y']} {t['w']}x{t['h']})"
    credits_before = _read_mobile_kredits(before)
    zero_numeral = _zero_operation_badge(before, u)
    _begin_attempt("attack_unit", before, u, dst)
    screens = _drag(src, dst)
    greyed, after, confirmed, stable = False, None, False, False
    changed, pending = 0.0, ""
    credits_after, outcome = None, {}
    zero_streak, zero_actor, success_reason = 0, False, "未确认"
    for f, stable, pending in _after_samples(late_wait + SETTLE_DRAG):
        if f is not None:
            after = f
        if not stable:
            zero_streak = 0
            continue
        greyed = not _attacker_still_there(f, u)
        credits_after = _read_mobile_kredits(f)
        outcome = _target_outcome(before, f, t, targets, target_owner)
        changed = outcome["target_changed"]
        spent = (credits_before is not None and credits_after is not None and
                 0 <= credits_after < credits_before)
        target_result = outcome["target_removed"] or outcome["target_stats_changed"]
        zero_actor = bool(zero_numeral is not None and greyed and
                          _zero_actor_exhausted(before, f, u, plan["actor_type"], zero_numeral))
        zero_result = (zero_actor and target_result and credits_before is not None and
                       credits_after == credits_before and
                       mb.end_turn_state(f) in ("white", "orange"))
        zero_streak = zero_streak + 1 if zero_result else 0
        confirmed = spent and target_result or zero_streak >= 2
        if confirmed:
            success_reason = "费用减少与目标结果" if spent else "零操作费、灰0与连续目标结果"
        if confirmed:
            break
    detail = (f"前线归属={owner};客户区 {src} -> 敌卡({t['cx']},{t['cy']});"
              f"稳定帧攻击者橙色消失={greyed} 目标块变化 {changed * 100:.0f}%;"
              f"费用 {credits_before}->{credits_after};目标消失={outcome.get('target_removed', False)};"
              f"目标数字变化={outcome.get('target_stats_changed', False)};连续结果帧稳定={stable}"
              f";零费徽章={zero_numeral is not None};同单位灰0={zero_actor};零费连续证据={zero_streak};{success_reason}"
              + (f"({pending})" if pending else ""))
    _dump("attack_unit", before, after,
          ["tag=attack_unit",
           f"攻击者 徽章={u['badge']['x']},{u['badge']['y']} 行={u['row']}",
           f"目标卡 ({t['x']},{t['y']}) {t['w']}x{t['h']} 牌子数={t.get('n_stats')}",
           f"拖 客户区 {src} -> {dst}", f"屏幕 {screens}",
           f"攻击者橙色消失 = {greyed}", f"目标块变化率 = {changed * 100:.1f}%",
           f"费用 = {credits_before} -> {credits_after};目标证据 = {outcome}",
           f"连续结果帧稳定 = {stable};待确认 = {pending}",
            f"零费 = {None if zero_numeral is None else {k: v for k, v in zero_numeral.items() if k != 'mask'}};同单位灰0={zero_actor};连续证据={zero_streak};{success_reason}",
           f"策略 = {plan}",
           f"结果 = {'打出去了' if confirmed else '没确认打出'}"])
    if confirmed:
        _remember_actor(u)
    _report(after)
    return confirmed, detail


def read_hq_hp(frame, side="enemy"):
    c = mb.hq_card(frame, side)
    return (c or {}).get("hp")


def _victory_evidence(frame):
    """只接受手游胜利文字模板。总部消失、爆炸及未知屏幕都不代表获胜。

    独立读取模板，避免 load_templates 清空引擎共享的 TEMPLATE_REGIONS。
    """
    import json
    import cv_io
    import ui_state
    if frame is None or frame.shape[:2] != (720, 1280):
        return False, -1.0
    try:
        cache = getattr(_victory_evidence, "_cache", None)
        if cache is None:
            path = os.path.join(mh.PROJECT_ROOT, "config", "templates.android.victory.json")
            with open(path, encoding="utf-8") as source:
                entry = json.load(source)["templates"]["victory_btn"]
            template = cv_io.imread(os.path.join(mh.PROJECT_ROOT, entry["path"]))
            if template is None:
                return False, -1.0
            cache = template, entry["region"]
            _victory_evidence._cache = cache
        template, region = cache
        x, y, w, h = (int(region[k]) for k in ("x", "y", "w", "h"))
        score, _box = ui_state.match_one(frame[y:y + h, x:x + w], template)
        return score >= 0.90, score
    except (OSError, ValueError, KeyError, TypeError):
        return False, -1.0


def attack_hq(frame=None, unit=None, dry_run=False, debug=True,
              late_wait: float = ACTION_AFTER_WAIT, acted=None, authorize=None,
              allow_attempt=None, decision_context=None):
    """同策略选择当前橙色单位；稳定掉血或连续两张可靠胜利帧才算成功。

    旧 frame、unit、acted 不能代替当前帧的回合/可行动判定。
    """
    before, refusal = _prepare(frame, dry_run, authorize)
    if before is None:
        return False, refusal
    plan, refusal = _policy_action(before, "attack_hq", unit, dry_run, allow_attempt, decision_context)
    if plan is None:
        return False, refusal
    hq, u = plan["target"], plan["unit"]
    dst = (int(hq["cx"]), int(hq["cy"]))
    hp0, src = hq["hp"], u["from"]
    if dry_run:
        return False, f"dry-run:客户区 {src} -> 总部 {dst}(血量 {hp0})"
    _begin_attempt("attack_hq", before, u, dst)
    screens = _drag(src, dst)
    hp1, after, previous, previous_hp = None, None, None, None
    victories, victory_score, ok, success_reason = 0, -1.0, False, "未确认"
    t0 = time.time()
    while time.time() - t0 <= late_wait + SETTLE_DRAG:
        f = _grab()
        if f is not None:
            after = f
            victory, victory_score = _victory_evidence(f)
            victories = victories + 1 if victory else 0
            hp1 = read_hq_hp(f, "enemy")
            if victories >= 2:
                ok, success_reason = True, "连续两张手游胜利帧"
                break
            reason = mb.board_transition_reason(f)
            stable = (not victory and not reason and
                      mb.frontline_state(f).get("owner") in ("our", "enemy", "empty"))
            if stable:
                decreased = (hp1 is not None and previous_hp is not None and
                             0 <= hp1 <= previous_hp < hp0)
                if previous is not None and decreased and mb.board_motion(previous, f) <= mb.BOARD_MOTION_MAX:
                    ok, success_reason = True, "稳定结果帧掉血"
                    break
                previous, previous_hp = f, hp1
            else:
                previous = previous_hp = None
        else:
            victories = 0
            previous = previous_hp = None
        time.sleep(HP_POLL)
    detail = (f"客户区 {src} -> 总部 {dst};血量 {hp0} -> {hp1}"
              f";胜利连续帧={victories} 模板分数={victory_score:.3f}({success_reason})")
    _dump("attack_hq", before, after,
          ["tag=attack_hq", f"chosen 徽章={u['badge']['x']},{u['badge']['y']} 行={u['row']}",
           f"拖 客户区 {src} -> {dst}", f"屏幕 {screens}",
           f"敌方总部 {hq['x']},{hq['y']} {hq['w']}x{hq['h']} 盾牌={hq.get('shield')}",
           f"血量 {hp0} -> {hp1}", f"胜利连续帧={victories};模板分数={victory_score:.3f}",
           f"结果 = {'打中了' if ok else '没打中'};{success_reason}", f"策略 = {plan}"])
    if ok:
        _remember_actor(u)
    _report(after)
    return ok, detail


if __name__ == "__main__":
    import argparse
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="手机端行动链(单次试跑)")
    ap.add_argument("--move-front", action="store_true", help="把一个单位挪到前线")
    ap.add_argument("--attack-hq", action="store_true", help="按类型与守护策略攻击敌方总部")
    ap.add_argument("--frame", default="", help="用存帧试算(不真的拖)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    frame = None
    if args.frame:
        import cv2
        frame = cv2.imread(os.path.join(mh.PROJECT_ROOT, args.frame))
        args.dry_run = True
    if args.move_front:
        print(move_to_front(frame=frame, dry_run=args.dry_run))
    elif args.attack_hq:
        print(attack_hq(frame=frame, dry_run=args.dry_run))
    else:
        ap.print_help()
