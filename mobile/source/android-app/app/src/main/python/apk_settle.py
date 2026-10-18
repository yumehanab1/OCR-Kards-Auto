"""Bounded post-match settlement: dismiss the result and tail screens.

Ported from the PC runner's dismiss state machine (PC settlement state machine),
which was corrected repeatedly against real play. What is kept from it:

* the window only opens after a verified victory/defeat, never on an arbitrary
  unknown screen - an opponent's turn also reads as "unknown";
* it stops the moment any known screen is recognised (main menu, deck list,
  queue, mulligan, in game), cancelling the remaining clicks;
* after a verified result, unknown level/reward pages use a fixed safe point
  once per second, for at most fifteen dispatch attempts;
* a click that does not change the screen is recorded, never treated as proof
  that settlement finished;
* "the screen did not move" is measured, not assumed.

What is deliberately not kept: PC's tap coordinates. Android's layout, its
result banner and its tail screens differ, so the fixed first point is this
project's own - see SETTLE_POINTS. The recorded post-victory quest Continue and
startup task panel both responded at (640,665). The remaining
points stay in the reviewed API list; this window uses only its first point.

Coordinates in SETTLE_POINTS are in the normalised 1280x720 frame space, which
is what the recognisers and dispatch guards use. The Java boundary converts them
to device pixels exactly like battle drags (source_width/1280), so they must not
be pre-scaled here.
"""
from __future__ import annotations

import json
import time

import numpy as np

#: Result/tail pages are dismissed by an arbitrary tap: their banner text is
#: not a button. Android's measured bottom-centre point is used with jitter.
#:
#: Every point here must also be inert on the frame the game returns to - the
#: start page. Measured on the real home screen (normalised 1280x720):
#:   开始 (59,147)  卡牌 (41,234)  商店 (41,320)  军需箱 (334,590)
#:   任务 (578,590)  打开卡包 (1180,584)  Bilibili (1180,197)  竞技场 (1180,357)
#: An earlier list included (59,147) as "the safe start-button slot"; on the
#: start page that is the 开始 button itself, and a live run ended up on the
#: card-collection screen because of it. Settlement must leave the game on the
#: start page, so the fixed point sits below the carousel/menu controls.
SETTLE_POINTS = (
    (640, 665),   # visible Continue on post-match quest; also closes task popup
    (400, 501),   # low band, left of centre: clear of 军需箱 (ends x~424) and
    (880, 501),   # right of 任务 (ends x~693); both sit in empty tabletop
    (153, 633),   # lower corners, PC's 12%-inset rule, kept below the left
    (1126, 633),  # button column (ends x~115) and above the frame edge
)
#: Controls measured on the real start page (normalised 1280x720). Settlement
#: must leave the game there, so no candidate may sit inside one of these: an
#: earlier list included the 开始 slot and a live run ended up on the card
#: collection because of it.
HOME_CONTROLS = (
    (26, 101, 67, 80),      # 开始
    (8, 201, 67, 67),       # 卡牌
    (8, 287, 67, 67),       # 商店
    (255, 555, 170, 72),    # 军需箱
    (499, 555, 195, 72),    # 任务
    (1110, 555, 170, 72),   # 打开卡包
    (1120, 170, 195, 55),   # Bilibili promo
    (1120, 330, 195, 55),   # 竞技场
)
MAX_CLICKS = 15
CLICK_GAP_SECONDS = 1.0
JITTER = 12
#: Settlement taps are single short presses; the Java boundary requires exactly
#: this duration so a settle request can never be mistaken for a battle gesture.
TAP_DURATION_MS = 60
#: "the screen did not move". PC used "share of pixels whose strongest channel
#: differs by more than 25", which is fine on its bright frames but blind on a
#: dark one: a level-1 change on a near-black screen never reaches 25 in any
#: channel. The mean absolute difference over the frame is used instead, so the
#: same small relative change counts the same on a bright or a dark screen.
#: Real anti-aliasing noise on a settled screen stays well below this.
DIFF_MEAN_THRESHOLD = 0.35
FRAME_SETTLE_SECONDS = 0.6
#: Deadline also bounds capture delays and waits for menu-transition frames.
#: The fifteen-attempt ceiling always applies even when this deadline is longer.
DEFAULT_TIMEOUT_SECONDS = 90.0

#: Existing startup overlays are still known to the menu flow, but they are
#: not usable return pages. Keep the same bounded post-match point window open
#: until the overlay disappears; no new tail-page recogniser or named action.
POST_MATCH_OVERLAY_STATES = frozenset(("task_popup", "pass_popup", "box_popup", "store_popup"))
#: Screens that mean settlement is over. Anything else keeps settling. The
#: disconnect dialog belongs here: it is not a result page and settlement must
#: not tap it, because reconnecting is the menu walk's own named step - the walk
#: observes `disconnected` and presses the reconnect control it has measured.
KNOWN_MENU_STATES = frozenset(("home", "mode_menu", "deck_list", "deck_ready",
                               "queueing", "mulligan_ready", "login_reward",
                               "card_collection", "disconnected"))
#: The one screen a finished campaign may be left on: the start page, whose own
#: 开始 button begins the next match. Everything else in KNOWN_MENU_STATES ends
#: the dismissal safely but is not yet where the next match can be started from,
#: which is why the return step below exists.
START_PAGE_STATES = frozenset(("home",))
#: A finished match's own pages. Seeing one means the tap did not leave the
#: result screen yet, so it must not count as success - PC fixes exactly this
#: deadlock, where the banner text stayed on screen forever.
RESULT_STATES = frozenset(("result_victory", "result_defeat"))


def changed(before, after):
    """True when two frames differ beyond anti-aliasing noise.

    `before`/`after` are same-sized uint8 BGR frames. Missing or mismatched
    input is treated as "changed", because refusing to conclude "stuck" is the
    safe direction: the loop keeps making bounded attempts either way.
    """
    if before is None or after is None:
        return True
    if before.shape != after.shape:
        return True
    difference = np.abs(after.astype(np.int16) - before.astype(np.int16))
    return float(difference.mean()) >= DIFF_MEAN_THRESHOLD


def jittered(point, rng, width=1280, height=720):
    """Clamp into the frame so a jittered tap can never leave the screen."""
    x = min(width - 8, max(8, int(point[0]) + int(rng.integers(-JITTER, JITTER + 1))))
    y = min(height - 8, max(8, int(point[1]) + int(rng.integers(-JITTER, JITTER + 1))))
    return (x, y)


def detail(observation):
    """What a decision was based on, small enough to keep in every event.

    A settlement pass that ends "unknown" has to say whether the app failed to
    decode the frame, decoded a different shape, or matched nothing - those are
    different faults and only one of them is about the game's screen.
    """
    observation = observation or {}
    control = observation.get("start_control") or {}
    evidence = observation.get("evidence") or {}
    best = sorted(((name, (row or {}).get("score")) for name, row in evidence.items()),
                  key=lambda item: -(item[1] if isinstance(item[1], (int, float)) else -9))
    return {"state": observation.get("state", ""),
            "reason": observation.get("reason", ""),
            "frame_shape": observation.get("frame_shape"),
            "frame_reader": observation.get("frame_reader", ""),
            "frame_path": observation.get("frame_path", ""),
            "start_control": ({"ok": control.get("ok"), "score": control.get("score"),
                               "visible": control.get("visible"), "variant": control.get("variant")}
                              if control else None),
            "best": [[name, score] for name, score in best[:3]]}


class FreshSettlementFrameRequired(Exception):
    """The dispatch boundary explicitly refused an expired, unsent gesture."""


class Settle:
    """One bounded settlement attempt. Pure logic; frame capture and tapping are
    injected, so every branch is testable without a device."""

    def __init__(self, capture, tap, classify, now=time.monotonic, sleep=time.sleep,
                 rng=None, points=SETTLE_POINTS, deadline=None,
                 timeout_seconds=DEFAULT_TIMEOUT_SECONDS, reward_wait=None):
        self.capture = capture
        self.tap = tap
        self.classify = classify          # frame -> observation dict with 'state'
        self.now = now
        self.sleep = sleep
        self.rng = rng if rng is not None else np.random.default_rng()
        self.points = tuple(points)
        # Always bounded: a caller-supplied deadline may be later, but no caller
        # can make this loop run forever by omitting one.
        hard_stop = now() + timeout_seconds
        self.deadline = hard_stop if deadline is None else min(deadline, hard_stop)
        self.clicks = 0
        self.stuck = 0
        self.events = []
        self.last_frame = None
        self.finished_reason = None
        self.reward_wait = reward_wait

    # ---- evidence ----
    def _event(self, kind, **fields):
        row = {"event": kind, "clicks": self.clicks, "stuck": self.stuck}
        row.update(fields)
        self.events.append(row)
        return row

    def run(self):
        """Settle until a known screen appears or the budget/deadline ends."""
        self._event("settle_started", points=[list(p) for p in self.points],
                    active_point=list(self.points[0]), max_clicks=MAX_CLICKS)
        last_click_at = None
        expired_dispatches = 0
        while True:
            if self.deadline is not None and self.now() >= self.deadline:
                self.finished_reason = "settle_deadline"
                break
            frame = self.capture()
            if frame is None:
                self.finished_reason = "settle_capture_failed"
                break
            observation = self.classify(frame) or {}
            state = observation.get("state", "")
            if state == "menu_transition":
                # A recognised menu shell is still drawing its first card.
                # Settlement must wait, never spend an arbitrary tail-page tap.
                self._event("settle_waiting_for_menu", detail=detail(observation))
                self.sleep(FRAME_SETTLE_SECONDS)
                continue
            if state in KNOWN_MENU_STATES:
                self.finished_reason = "settle_screen_known:" + state
                self._event("settle_finished", state=state)
                return self.report(state)
            if self.reward_wait is not None:
                decision = self.reward_wait.decide(frame, observation, self.now())
                if decision["stop"]:
                    self.finished_reason = decision["reason"]
                    break
                if decision["wait"]:
                    self._event("settle_readonly_reward_wait", reason=decision["reason"],
                                phase=decision.get("phase"), detail=detail(observation))
                    self.sleep(FRAME_SETTLE_SECONDS)
                    continue
            # Read a fresh frame after the final attempt before deciding: its
            # tap may have reached the menu. It never authorises a sixteenth
            # attempt, even if this tail page is still unknown or animating.
            if self.clicks >= MAX_CLICKS:
                self.finished_reason = "settle_click_budget"
                break
            # A tap needs time to take effect: while the gap is open, keep
            # waiting without judging the screen. Judging here would compare two
            # samples of the same wait, not the screen before and after a tap.
            gap = CLICK_GAP_SECONDS
            if last_click_at is not None and self.now() - last_click_at < gap:
                self.sleep(min(0.2, gap))
                continue
            if state in RESULT_STATES:
                # Still on the banner itself; the next click continues the
                # fixed-point window rather than waiting on a text that is not a
                # button (PC's deadlock, kept fixed here by construction).
                self._event("settle_on_result_banner", state=state)
            elif state in POST_MATCH_OVERLAY_STATES:
                self._event("settle_on_menu_overlay", state=state)
            if self.last_frame is not None and not changed(self.last_frame, frame):
                self.stuck += 1
                self._event("settle_screen_unchanged", state=state)
            else:
                self.stuck = 0
            # The first point is the measured Android dismissal point. Keep
            # the reviewed list/custom-points API, but spend the whole bounded
            # window here instead of rotating through unneeded candidates.
            point = jittered(self.points[0], self.rng)
            try:
                accepted = self.tap(point)
            except FreshSettlementFrameRequired as error:
                expired_dispatches += 1
                self._event("settle_reacquire", receipt=error.args[0],
                            consecutive_rejections=expired_dispatches)
                if expired_dispatches >= 3:
                    self.finished_reason = "settle_expired_dispatch_budget"
                    break
                self.sleep(FRAME_SETTLE_SECONDS)
                continue
            expired_dispatches = 0
            self.clicks += 1
            last_click_at = self.now()
            self._event("settle_click", point=list(point), state=state,
                        observation=observation.get("state", ""),
                        detail=detail(observation),
                        accepted=bool(accepted), gap_seconds=gap,
                        phase="fast")
            # A refused or incomplete dispatch is not a safe retry signal.
            # Java may have accepted part of the gesture before cancelling;
            # never send another request after that ambiguous callback.
            if not accepted:
                self.finished_reason = "settle_input_refused"
                break
            if self.reward_wait is not None:
                # tap's True already requires accepted AND completed at run's
                # Java boundary; only that completed reply arms a claim exit.
                self.reward_wait.note_dispatch(True, True, self.now())
            self.last_frame = frame
            self.sleep(FRAME_SETTLE_SECONDS)
        self._event("settle_finished", reason=self.finished_reason)
        return self.report(None)

    def report(self, state):
        return {"reason": self.finished_reason, "clicks": self.clicks,
                "stuck_observations": self.stuck, "final_state": state,
                "on_start_page": state in START_PAGE_STATES,
                "points": [list(p) for p in self.points],
                "active_point": list(self.points[0]), "events": self.events}


#: The start page's own 开始 button, measured centre in normalised frame space.
#: The user identified this button as the target for looping a campaign: tapping
#: its centre is the named step that starts the next match. The same tile is
#: drawn on the card-collection screen, which is why the step below verifies the
#: control is on screen before pressing it instead of trusting a page name.
START_BUTTON = (59, 147)
#: Screens the return step accepts as "the campaign can start the next match
#: from here". `home` is the start page itself. `mode_menu` and `deck_list` are
#: the mode and deck selection the 开始 button opens - observed live, tapping it
#: from the card collection lands on the deck selection - and the campaign walk
#: drives both directly (`menu_battle_mode`, `menu_select_deck`).
#: `deck_ready` is also usable: a fresh menu flow first closes that old detail
#: page and reselects the list's first deck before it can request matchmaking.
#: Whether the game is literally back on the start page is reported separately, as
#: `on_start_page`.
RETURN_DONE_STATES = frozenset(("home", "mode_menu", "deck_list", "deck_ready"))
#: The return step taps only the measured button, and only this many times.
RETURN_MAX_CLICKS = 3
#: How many consecutive observations must agree that the button is not on screen
#: before the step believes it. A page that is still being drawn lacks the button
#: without that meaning anything: a live pass read the frame 0.6 s after its own
#: tap and saw the button already gone while the page behind it was not yet
#: drawn, and called a screen the walk can use "unrecognised".
RETURN_SETTLE_OBSERVATIONS = 3


class ReturnToStart:
    """Bring the game back to the start page by tapping its 开始 button.

    Deliberately separate from the settlement dismissal: settlement's points are
    inert by design (they must not press any menu control), while this step
    presses exactly one named control and nothing else.

    Every tap is gated on the control being drawn in the frame that authorises
    it. That gate is the whole safety argument: the recogniser reports the 开始
    tile for every page, so a screen the tile is absent from (a result banner, an
    unknown tail page, the arena the operator had never seen) produces no tap at
    all - the step reports `return_control_absent` and stops. The step also stops
    as soon as the start page is recognised, and never taps more than its budget.
    """

    def __init__(self, capture, tap, classify, now=time.monotonic, sleep=time.sleep,
                 point=START_BUTTON, max_clicks=RETURN_MAX_CLICKS,
                 timeout_seconds=DEFAULT_TIMEOUT_SECONDS):
        self.capture = capture
        self.tap = tap
        self.classify = classify
        self.now = now
        self.sleep = sleep
        self.point = point
        self.max_clicks = max_clicks
        self.events = []
        self.finished_reason = None
        self.deadline = now() + timeout_seconds

    def _event(self, kind, **fields):
        row = {"event": kind}
        row.update(fields)
        self.events.append(row)
        return row

    def run(self):
        self._event("return_started", point=list(self.point))
        previous = None
        clicks = 0
        state = ""
        blind = 0
        expired_dispatches = 0
        while True:
            if self.now() >= self.deadline:
                self.finished_reason = "return_deadline"
                break
            frame = self.capture()
            if frame is None:
                self.finished_reason = "return_capture_failed"
                break
            observation = self.classify(frame) or {}
            state = observation.get("state", "")
            if state == "menu_transition":
                blind = 0
                self._event("return_waiting_for_menu", detail=detail(observation))
                self.sleep(FRAME_SETTLE_SECONDS)
                continue
            if state in RETURN_DONE_STATES:
                self.finished_reason = "return_reached:" + state
                break
            if state in POST_MATCH_OVERLAY_STATES:
                self.finished_reason = "return_overlay_blocked:" + state
                self._event("return_overlay_blocked", state=state, detail=detail(observation))
                break
            control = observation.get("start_control")
            if control is None or not control.get("ok"):
                # Nothing here may be pressed - yet. The button being absent is
                # only conclusive once consecutive observations agree, because a
                # page still drawing looks the same as a page without it.
                blind += 1
                if blind >= RETURN_SETTLE_OBSERVATIONS:
                    if control is None:
                        # No control report at all: the screen was not classified,
                        # so nothing about the button is known. That is a different
                        # fault from "this page does not draw the button".
                        self.finished_reason = "return_classification_incomplete:" + state
                        self._event("return_classification_incomplete", state=state,
                                    detail=detail(observation))
                    else:
                        self.finished_reason = "return_control_absent:" + state
                        self._event("return_control_absent", state=state,
                                    score=control.get("score"), detail=detail(observation))
                    break
                self.sleep(FRAME_SETTLE_SECONDS)
                continue
            blind = 0
            if clicks >= self.max_clicks:
                self.finished_reason = "return_budget_exhausted"
                break
            if previous is not None and not changed(previous, frame):
                # The previous tap produced nothing at all; try again rather
                # than counting it as progress.
                self._event("return_screen_unchanged", state=state, clicks=clicks)
            try:
                accepted = self.tap(self.point)
            except FreshSettlementFrameRequired as error:
                expired_dispatches += 1
                self._event("return_reacquire", receipt=error.args[0],
                            consecutive_rejections=expired_dispatches)
                if expired_dispatches >= 3:
                    self.finished_reason = "return_expired_dispatch_budget"
                    break
                self.sleep(FRAME_SETTLE_SECONDS)
                continue
            expired_dispatches = 0
            clicks += 1
            self._event("return_click", point=list(self.point), state=state,
                        detail=detail(observation),
                        accepted=bool(accepted), clicks=clicks)
            if not accepted:
                self.finished_reason = "return_input_refused"
                break
            previous = frame
            self.sleep(FRAME_SETTLE_SECONDS)
        self._event("return_finished", state=state, clicks=clicks,
                    reason=self.finished_reason)
        return self.report(state, clicks)

    def report(self, state, clicks):
        return {"reason": self.finished_reason, "clicks": clicks,
                "final_state": state, "on_start_page": state in START_PAGE_STATES,
                "point": list(self.point), "events": self.events}


def run(bridge, points=None, assets_dir=None, timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
        return_to_start=True, verified_result=False, component_scope=False, native=False):
    """Entry point for Java: settle the screen the finished battle left behind.

    `points` may arrive as a JSON array string (what the Java boundary sends)
    or as an already-parsed sequence of pairs, which is what the offline tests
    pass. `bridge` supplies the same three operations the pure machine takes -
    capture, classify and tap - so every decision still runs through this
    module while all device I/O stays behind the Java boundary. Each tap is
    re-validated there against the freshly captured frame, the campaign
    deadline and the foreground admission.

    With `return_to_start` the attempt does not end on just any known screen:
    settlement leaves whatever screen the result page becomes, then the 开始
    button is pressed until the start page is up again, so the campaign can run
    the next match instead of being stranded in a menu. That second step is
    bounded and refuses to act on a screen where the button is not drawn.

    The normal Java campaign calls this only after strict resultConfirmed.
    Debug SETTLE_ONCE is an explicitly authorised component-test exception;
    neither this module nor that debug entry claims a verified battle result.
    """
    import json as _json

    assets = str(assets_dir) if assets_dir else None
    if isinstance(points, str):
        points = [tuple(pair) for pair in _json.loads(points)] if points.strip() else None
    elif points is not None:
        points = [tuple(pair) for pair in points] or None

    state = {"packet": None, "reader": "", "path": "", "observation": None}
    if native:
        from apk_native.menu import NativeMenuRecognizer
        # Only the already authorised result cleanup window can defer semantics.
        # Unknown rewards get its original bounded neutral point; confirmed
        # menu geometry still ends cleanup. No new action or result is inferred.
        native_recognizer=NativeMenuRecognizer(assets,bridge,settlement=verified_result is True or component_scope is True)

    def classify(frame):
        """Classify the frame the machine just captured.

        The recogniser lives behind the Java boundary and reads a *file*, so the
        path it is given must be the one that the capture behind this frame
        recorded. The machine hands `classify` the decoded image, and passing
        that image on as if it were a path is how every live settlement pass
        classified a numpy repr instead of a screen: the recogniser answered
        "unsupported_frame_size" - which reads exactly like "I cannot name this
        screen" - for every frame, so settlement never once saw the page it was
        dismissing. The guard below keeps that failure impossible to repeat.
        """
        if not state["path"]:
            return {"state": "unknown", "reason": "no_captured_frame"}
        if native:
            observed=native_recognizer.observe(frame,state['packet'])
            observed.update(frame_shape=list(frame.shape),frame_reader=state['reader'],frame_path=state['path'])
            state['observation']=observed
            return observed
        request = {"png_path": state["path"], "assets": assets}
        observation = bridge.observeMenu(_json.dumps(request))
        return _json.loads(observation) if isinstance(observation, str) else observation

    def capture_frame():
        packet = bridge.captureNative() if native else bridge.capture()
        packet = _json.loads(packet) if isinstance(packet, str) else packet
        if not packet.get("ok"):
            state["packet"] = None
            return None
        state["packet"] = packet
        # The same decoder the settlement's own recogniser uses: a frame this
        # module cannot read must not silently become "the screen never changed".
        from apk_match_entry import read_frame
        frame, route = read_frame(packet["png_path"])
        if native and (frame is None or packet.get('coordinate_space')!='source_pixels'
                or frame.shape[:2]!=(packet['source_height'],packet['source_width'])):
            state['packet']=None
            return None
        state["reader"] = route
        state["path"] = str(packet["png_path"])
        return frame

    def tap(point):
        packet = state["packet"]
        if packet is None:
            return False
        if native:
            if list(point)==list(START_BUTTON):
                control=(state.get('observation') or {}).get('start_control') or {}
                if control.get('ok') is not True or not control.get('bounds'):return False
                x,y,w,h=control['bounds'];point=[x+w/2,y+h/2]
            else:
                # Only the reviewed centre-bottom dismissal envelope is mapped.
                # This is a point in the untouched source image, not image scaling.
                scale=packet['height']/720
                point=[packet['width']/2+(point[0]-640)*scale,point[1]*scale]
        request = {key: packet[key] for key in
                   ("frame_id", "captured_elapsed_ms", "foreground_generation",
                    "source_width", "source_height")}
        request.update(context="settle", kind="tap", duration_ms=TAP_DURATION_MS,
                       **{"from": [float(point[0]), float(point[1])],
                          "to": [float(point[0]), float(point[1])]})
        if native:request['coordinate_space']='source_pixels'
        reply = bridge.dispatchSettle(_json.dumps(request))
        reply = _json.loads(reply) if isinstance(reply, str) else reply
        receipt = {"frame_id":packet["frame_id"],"request":request,"reply":reply}
        state.setdefault("dispatch_receipts",[]).append(receipt)
        if (reply.get("accepted") is False and reply.get("completed") is False
                and reply.get("reason") in ("frame_age_expired","temporary_game_window_occluded")):
            raise FreshSettlementFrameRequired(receipt)
        return bool(reply.get("accepted") and reply.get("completed"))

    bounded_seconds = min(DEFAULT_TIMEOUT_SECONDS, max(0., float(timeout_seconds)))
    return_deadline = time.monotonic() + bounded_seconds
    machine = Settle(capture_frame, tap, classify, timeout_seconds=bounded_seconds,
                     **({"points": points} if points else {}))
    # These admissions come explicitly from Java's strict result predicate or
    # its existing debug-only SETTLE_ONCE component scope, never from an unknown
    # image or merely calling this function. Optional asset failure keeps the
    # original bounded point window; it cannot manufacture a known menu.
    from apk_reward_wait import load_gate
    admitted = verified_result is True or component_scope is True
    if native:
        gate,gate_reason=None,'native_optional_reward_templates_not_adapted'
    else:
        gate, gate_reason = load_gate(assets, session_epoch=str(assets),
                                     result_verified=admitted, deadline=machine.deadline)
    machine.reward_wait = gate
    report = machine.run()
    report["dispatch_receipts"] = state.setdefault("dispatch_receipts",[])
    report["reward_wait"] = {"enabled": gate is not None, "reason": gate_reason,
                             "verified_result": verified_result is True,
                             "component_scope": component_scope is True}
    # How the pass read the device's frames, kept at the top level as well: a
    # pass that ends "capture failed" has to say which file and which decoder.
    report["frame_reader"] = state["reader"]
    report["frame_path"] = state["path"]
    # The dismissal's own verdict is kept verbatim under its own key, so a
    # reader can still see whether the result page itself was left behind.
    report["settle_reason"] = machine.finished_reason
    report["return"] = None
    report["total_clicks"] = report["clicks"]
    if not return_to_start:
        report["reason_after_return"] = "return_disabled"
    elif not str(report["reason"]).startswith("settle_screen_known:"):
        # A spent window still on an unknown/overlay is not a return admission.
        # Never press the Start tile through a post-match popup.
        report["reason_after_return"] = "return_skipped:" + report["reason"]
    elif report["final_state"] in RETURN_DONE_STATES:
        report["reason_after_return"] = "return_not_needed:" + str(report["final_state"])
    else:
        step = ReturnToStart(capture_frame, tap, classify,
                            timeout_seconds=max(0., return_deadline-time.monotonic()))
        returned = step.run()
        report["return"] = returned
        report["reason_after_return"] = returned["reason"]
        report["final_state"] = returned["final_state"]
        report["on_start_page"] = returned["on_start_page"]
        report["total_clicks"] = report["clicks"] + returned["clicks"]
        report["events"] = report["events"] + returned["events"]
    return _json.dumps(report, ensure_ascii=False)


def loads(value):
    return value if isinstance(value, dict) else json.loads(str(value))
