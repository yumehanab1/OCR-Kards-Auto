"""Bounded settlement regressions. No device, no capture, no real sleep.

The verified post-match window uses the fixed Android Continue point at most
fifteen times. Unknown tail pages and known startup overlays continue within that
budget; usable menus stop it. The separate return step never acts through an
overlay, and every loop ends without exceeding its own input/time budget.
"""
import unittest

import numpy as np

import apk_settle as settle
import json

HOME_POINT = (59, 147)          # measured home 开始 slot centre, normalised


def plate(value=0):
    return np.full((720, 1280, 3), value, np.uint8)


class Harness:
    """Scripted states with an optional learned transition.

    `on_tap_state` is the state observed after a tap once the scripted list is
    exhausted, which lets a case assert "tap N produced this screen".
    `start_control` is what the recogniser reports about the 开始 tile: the return
    step may only press it when it is drawn, so a case can script a screen that
    does not carry the control at all.
    """

    def __init__(self, states, on_tap_state=None, frames=None, tap_ok=True,
                 start_control=True):
        self.scripted = list(states)
        self.on_tap_state = on_tap_state
        self.frames = list(frames) if frames is not None else None
        self.tap_ok = tap_ok
        self.start_control = start_control
        self.observed = 0
        self.taps = []
        self.now = 0.0

    def capture(self):
        index = self.observed
        self.observed += 1
        if self.frames:
            # A one-frame script means "this screen never changes", which is
            # what the no-progress case needs to exercise.
            return self.frames[0] if len(self.frames) == 1 else self.frames[min(index, len(self.frames) - 1)]
        # Always-changing screen: a tail page that keeps animating but never
        # becomes one of the known menu screens. Each sample must differ from
        # the previous one, otherwise the loop would (correctly) conclude the
        # screen is frozen.
        return plate(index % 250)

    def observation(self, state):
        # The 开始 tile is drawn on the menu shell, so it is present on the start
        # page and on the card collection alike; a result banner does not carry
        # it. Cases override `start_control` to script either side.
        return {"state": state, "start_control": {"ok": self.start_control, "score": 0.99,
                                                  "bounds": [26, 101, 67, 80]}}

    def classify(self, value):
        # A learned transition wins over the script: once a tap has been made,
        # the screen is whatever that tap produced. This is what lets a case
        # assert "the third tap revealed the start page".
        if self.on_tap_state is not None and self.taps:
            return self.observation(self.on_tap_state)
        index = self.observed - 1
        if index < len(self.scripted):
            state = self.scripted[index]
        else:
            state = self.scripted[-1] if self.scripted else "unknown"
        return self.observation(state)

    def tap(self, point):
        self.taps.append(point)
        return self.tap_ok

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def run(states, on_tap_state=None, frames=None, deadline=60.0, tap_ok=True, points=None):
    harness = Harness(states, on_tap_state, frames, tap_ok)
    machine = settle.Settle(harness.capture, harness.tap, harness.classify,
                            now=harness.clock, sleep=harness.sleep,
                            rng=np.random.default_rng(3), deadline=deadline,
                            **({"points": points} if points else {}))
    return machine.run(), harness


def clicks(report):
    return [event for event in report["events"] if event["event"] == "settle_click"]


class SettlementTests(unittest.TestCase):
    def test_menu_transition_waits_without_spending_a_tail_tap(self):
        report, harness = run(["menu_transition", "menu_transition", "deck_list"])
        self.assertEqual("settle_screen_known:deck_list", report["reason"])
        self.assertEqual([], harness.taps)

    def test_permanent_menu_transition_ends_at_deadline_without_input(self):
        report, harness = run(["menu_transition"], deadline=2.)
        self.assertEqual("settle_deadline", report["reason"])
        self.assertEqual([], harness.taps)

    def test_stops_on_home_after_the_expected_number_of_clicks(self):
        report, harness = run(["result_defeat"] * 3, on_tap_state="home")
        self.assertEqual("settle_screen_known:home", report["reason"])
        self.assertEqual("home", report["final_state"])
        self.assertEqual(1, len(clicks(report)))

    def test_first_candidate_is_used_and_stops_on_home(self):
        # The behaviour asked for: tap inert points and stop the moment the
        # start page is observed.
        report, harness = run(["result_defeat"] * 6, on_tap_state="home",
                              points=((640, 665),))
        used = clicks(report)
        x, y = used[0]["point"]
        self.assertLessEqual(abs(x - 640), settle.JITTER)
        self.assertLessEqual(abs(y - 665), settle.JITTER)
        self.assertEqual("home", report["final_state"])
        self.assertLessEqual(len(used), 2)

    def test_the_start_slot_is_no_longer_a_default_candidate(self):
        # Regression: it is an active menu control on the start page, so using
        # it navigated away from the page settlement is supposed to leave.
        self.assertNotIn(HOME_POINT, settle.SETTLE_POINTS)

    def test_never_more_than_fifteen_clicks_without_a_known_screen(self):
        # A changing result page never receives a sixteenth attempt.
        report, _ = run(["result_defeat"] * 400, deadline=600.0)
        phases = [event["phase"] for event in clicks(report)]
        self.assertEqual(settle.MAX_CLICKS, phases.count("fast"))
        self.assertEqual(15, report["clicks"])
        self.assertEqual("settle_click_budget", report["reason"])

    def test_result_banner_alone_never_ends_settlement(self):
        report, _ = run(["result_defeat"] * 4, on_tap_state="deck_list")
        self.assertEqual("settle_screen_known:deck_list", report["reason"])
        self.assertTrue(any(event["event"] == "settle_on_result_banner"
                            for event in report["events"]))

    def test_fixed_android_point_is_used_when_the_screen_does_not_change(self):
        report, _ = run(["result_defeat"] * 4, frames=[plate(0)] * 4, deadline=60.0)
        used = [event["point"] for event in clicks(report)]
        self.assertEqual(15, len(used))
        for x, y in used:
            self.assertLessEqual(abs(x-640), settle.JITTER)
            self.assertLessEqual(abs(y-665), settle.JITTER)
        self.assertEqual([640, 665], report["active_point"])
        self.assertTrue(any(event["event"] == "settle_screen_unchanged"
                            for event in report["events"]))

    def test_loop_always_ends_without_a_caller_deadline(self):
        # A result page must never trap the campaign: even with a caller who
        # passes no deadline at all, the attempt ends on its own.
        report, _ = run(["result_defeat"] * 200, deadline=None)
        self.assertIsNotNone(report["reason"])
        self.assertEqual("settle_click_budget", report["reason"])
        self.assertEqual(15, len(clicks(report)))

    def test_static_unknown_tail_gets_fifteen_attempts_then_stops(self):
        report, _ = run(["unknown"] * 200, frames=[plate(0)], deadline=600.0)
        self.assertEqual("settle_click_budget", report["reason"])
        self.assertEqual(settle.MAX_CLICKS, len(clicks(report)))
        self.assertEqual(14, report["stuck_observations"])

    def test_jitter_never_leaves_the_frame(self):
        for base in ((2, 2), (1278, 718), HOME_POINT, (640, 665)):
            for seed in range(25):
                point = settle.jittered(base, np.random.default_rng(seed))
                self.assertTrue(0 < point[0] < 1280, point)
                self.assertTrue(0 < point[1] < 720, point)

    def test_one_second_gap_never_enters_a_slow_retry_phase(self):
        report, _ = run(["result_defeat"] * 400, deadline=2000.0)
        slow = [event for event in clicks(report) if event["phase"] == "slow"]
        self.assertEqual([], slow)
        self.assertEqual([1.] * 15, [event['gap_seconds'] for event in clicks(report)])

    def test_unknown_reward_sequence_can_reach_the_menu(self):
        harness = Harness(['result_defeat'])
        states = ['result_defeat', 'unknown', 'unknown', 'deck_list']
        machine = settle.Settle(harness.capture, harness.tap,
                                lambda frame: {'state': states[min(len(harness.taps), 3)]},
                                now=harness.clock, sleep=harness.sleep)
        report = machine.run()
        self.assertEqual('settle_screen_known:deck_list', report['reason'])
        self.assertEqual(3, len(harness.taps))
        self.assertEqual(['result_defeat', 'unknown', 'unknown'],
                         [event['state'] for event in clicks(report)])

    def test_each_attempt_waits_at_least_a_second(self):
        harness = Harness(['unknown'])
        timestamps = []
        def tap(point):
            timestamps.append(harness.now)
            return harness.tap(point)
        report = settle.Settle(harness.capture, tap, harness.classify,
                               now=harness.clock, sleep=harness.sleep).run()
        self.assertEqual(15, report['clicks'])
        self.assertTrue(all(later-earlier >= .999999 for earlier, later in
                            zip(timestamps, timestamps[1:])))

    def test_fifteenth_attempt_is_observed_before_reporting_exhaustion(self):
        harness = Harness(['unknown'])
        def classify(frame):
            return {'state': 'home' if len(harness.taps) == 15 else 'unknown'}
        report = settle.Settle(harness.capture, harness.tap, classify,
                               now=harness.clock, sleep=harness.sleep).run()
        self.assertEqual(15, len(harness.taps))
        self.assertEqual('settle_screen_known:home', report['reason'])
        self.assertTrue(report['on_start_page'])

    def test_menu_transition_after_a_tap_waits_without_spending_more(self):
        harness = Harness(['unknown'])
        seen = {'transitions': 0}
        def classify(frame):
            if not harness.taps:
                return {'state': 'result_victory'}
            seen['transitions'] += 1
            return {'state': 'menu_transition' if seen['transitions'] <= 4 else 'deck_list'}
        report = settle.Settle(harness.capture, harness.tap, classify,
                               now=harness.clock, sleep=harness.sleep).run()
        self.assertEqual(1, len(harness.taps))
        self.assertEqual('settle_screen_known:deck_list', report['reason'])

    def test_cancelled_capture_does_not_dispatch_remaining_attempts(self):
        harness = Harness(['unknown'])
        def capture():
            return None if len(harness.taps) >= 3 else harness.capture()
        report = settle.Settle(capture, harness.tap, harness.classify,
                               now=harness.clock, sleep=harness.sleep).run()
        self.assertEqual(3, len(harness.taps))
        self.assertEqual('settle_capture_failed', report['reason'])

    def test_deadline_stops_an_unknown_tail_before_fifteen(self):
        report, harness = run(['unknown'], deadline=2.5)
        self.assertEqual('settle_deadline', report['reason'])
        self.assertLess(len(harness.taps), 15)

    def test_custom_point_list_uses_only_its_first_reviewed_point(self):
        report, _ = run(['unknown'], points=((400, 501), (880, 501)))
        self.assertEqual([400, 501], report['active_point'])
        for event in clicks(report):
            x, y = event['point']
            self.assertLessEqual(abs(x-400), settle.JITTER)
            self.assertLessEqual(abs(y-501), settle.JITTER)

    def test_every_known_menu_state_stops_without_spending_a_tap(self):
        for state in settle.KNOWN_MENU_STATES:
            with self.subTest(state=state):
                report, harness = run([state])
                self.assertEqual('settle_screen_known:'+state, report['reason'])
                self.assertEqual([], harness.taps)

    def test_capture_failure_ends_without_tapping(self):
        harness = Harness(["result_defeat"])
        machine = settle.Settle(lambda: None, harness.tap, harness.classify,
                                now=harness.clock, sleep=harness.sleep)
        report = machine.run()
        self.assertEqual("settle_capture_failed", report["reason"])
        self.assertEqual([], harness.taps)

    def test_frame_difference_rule(self):
        before = plate(0)
        self.assertFalse(settle.changed(before, before.copy()))
        altered = before.copy()
        altered[100:150, 100:200] = 200
        self.assertTrue(settle.changed(before, altered))
        self.assertTrue(settle.changed(None, before))
        self.assertTrue(settle.changed(before, np.zeros((100, 100, 3), np.uint8)))

    def test_small_change_on_a_dark_screen_is_still_a_change(self):
        # A dark result page must not look frozen: a one-level shift that no
        # absolute per-channel threshold would catch still counts.
        self.assertTrue(settle.changed(plate(0), plate(1)))

    def test_settled_noise_does_not_count_as_a_change(self):
        rng = np.random.default_rng(11)
        base = plate(0).astype(np.int16)
        noisy = base.copy()
        mask = rng.random(base.shape[:2]) < 0.02
        noisy[mask] = 1
        self.assertFalse(settle.changed(base.astype(np.uint8), noisy.astype(np.uint8)))

    def test_rejected_tap_is_recorded_and_stops_the_window(self):
        report, harness = run(["result_defeat"] * 4, on_tap_state="home", tap_ok=False)
        self.assertTrue(any(event.get("accepted") is False for event in clicks(report)))
        self.assertEqual("settle_input_refused", report["reason"])
        self.assertEqual(1, len(harness.taps))

    def test_default_candidates_avoid_the_screen_centre(self):
        # PC measured that a centre tap does not dismiss; keep the default set
        # away from the centre so a tail page's own centre control is not hit.
        for x, y in settle.SETTLE_POINTS:
            self.assertGreater(abs(x - 640) + abs(y - 360), 80, (x, y))

    def test_default_candidates_never_sit_on_a_start_page_control(self):
        # Settlement must leave the game on the start page, so a candidate that
        # lands on a menu button would navigate away from it - which is exactly
        # how a live run ended up on the card-collection screen.
        for x, y in settle.SETTLE_POINTS:
            for control in settle.HOME_CONTROLS:
                cx, cy, cw, ch = control
                self.assertFalse(cx <= x <= cx + cw and cy <= y <= cy + ch,
                                 "candidate %s,%s sits on control %s" % (x, y, control))

    def test_the_start_button_slot_is_not_a_candidate(self):
        # The measured 开始 slot, kept as an explicit regression: it is an active
        # control, not an inert dismissal point.
        for x, y in settle.SETTLE_POINTS:
            self.assertFalse(abs(x - 59) <= 20 and abs(y - 147) <= 20, (x, y))

    def test_known_stop_states_include_usable_menus_and_deferred_login(self):
        for state in ("home", "deck_list", "deck_ready", "queueing",
                      "mulligan_ready", "login_reward", "card_collection",
                      "disconnected"):
            self.assertIn(state, settle.KNOWN_MENU_STATES)

    def test_known_startup_overlays_use_the_same_bounded_window(self):
        for state in settle.POST_MATCH_OVERLAY_STATES:
            with self.subTest(state=state):
                self.assertNotIn(state, settle.KNOWN_MENU_STATES)
                report, harness = run([state])
                self.assertEqual('settle_click_budget', report['reason'])
                self.assertEqual(15, len(harness.taps))
                for x, y in harness.taps:
                    self.assertLessEqual(abs(x-640), settle.JITTER)
                    self.assertLessEqual(abs(y-665), settle.JITTER)

    def test_the_entire_fixed_point_jitter_area_clears_home_controls(self):
        x, y = settle.SETTLE_POINTS[0]
        self.assertEqual((640, 665), (x, y))
        for dx in range(-settle.JITTER, settle.JITTER+1):
            for dy in range(-settle.JITTER, settle.JITTER+1):
                for cx, cy, cw, ch in settle.HOME_CONTROLS:
                    self.assertFalse(cx <= x+dx <= cx+cw and cy <= y+dy <= cy+ch)

    def test_a_disconnect_dialog_ends_settlement_without_a_tap(self):
        # The dialog is not a result page, and its reconnect control is the menu
        # walk's named step: settlement must stop and leave it alone rather than
        # spending taps on a screen it was never meant to dismiss.
        report, harness = run(["disconnected"])
        self.assertEqual("settle_screen_known:disconnected", report["reason"])
        self.assertEqual(0, report["clicks"])
        self.assertEqual([], harness.taps)
        self.assertFalse(report["on_start_page"])

    def test_every_tap_records_what_the_decision_was_based_on(self):
        # A pass that ends "unknown" must carry the evidence that says whether the
        # frame failed to decode, decoded differently, or matched nothing.
        report, _ = run(["result_defeat"] * 4, on_tap_state="home")
        row = clicks(report)[0]["detail"]
        self.assertEqual("result_defeat", row["state"])
        self.assertIn("best", row)
        self.assertIn("frame_shape", row)

    def test_detail_reports_the_best_templates_and_the_start_control(self):
        row = settle.detail({"state": "unknown", "reason": "unsupported_frame_size",
                             "frame_shape": None,
                             "evidence": {"home_play": {"score": 0.5},
                                          "card_tab": {"score": 0.9}}})
        self.assertEqual("unsupported_frame_size", row["reason"])
        self.assertIsNone(row["frame_shape"])
        self.assertEqual([["card_tab", 0.9], ["home_play", 0.5]], row["best"])
        self.assertIsNone(row["start_control"])

    def test_detail_tolerates_a_bare_observation(self):
        # The Java boundary's own fallback is just {"state": "unknown"}.
        row = settle.detail({"state": "unknown"})
        self.assertEqual([], row["best"])
        self.assertIsNone(row["start_control"])
        self.assertEqual("", row["reason"])


class ReturnToStartTests(unittest.TestCase):
    def test_overlay_never_authorises_start_even_when_control_is_reported_visible(self):
        for state in settle.POST_MATCH_OVERLAY_STATES:
            with self.subTest(state=state):
                harness = Harness([state], start_control=True)
                report = settle.ReturnToStart(harness.capture, harness.tap, harness.classify,
                                               now=harness.clock, sleep=harness.sleep).run()
                self.assertEqual('return_overlay_blocked:'+state, report['reason'])
                self.assertEqual([], harness.taps)

    def test_a_deck_details_page_needs_no_return_input(self):
        harness = Harness(['deck_ready'])
        report = settle.ReturnToStart(harness.capture, harness.tap, harness.classify,
                                       now=harness.clock, sleep=harness.sleep).run()
        self.assertEqual('return_reached:deck_ready', report['reason'])
        self.assertEqual([], harness.taps)
        self.assertFalse(report['on_start_page'])
    def test_refused_return_tap_does_not_dispatch_the_remaining_budget(self):
        harness = Harness(['card_collection'], tap_ok=False)
        report = settle.ReturnToStart(harness.capture, harness.tap, harness.classify,
                                      now=harness.clock, sleep=harness.sleep).run()
        self.assertEqual('return_input_refused', report['reason'])
        self.assertEqual(1, report['clicks'])
        self.assertEqual(1, len(harness.taps))

    def test_transition_visibility_never_grants_a_return_tap(self):
        report, harness = self.run_return(["menu_transition", "menu_transition", "deck_list"])
        self.assertEqual("return_reached:deck_list", report["reason"])
        self.assertEqual([], harness.taps)

    def test_permanent_transition_has_a_return_deadline(self):
        harness = Harness(["menu_transition"])
        machine = settle.ReturnToStart(harness.capture, harness.tap, harness.classify,
                                      now=harness.clock, sleep=harness.sleep,
                                      timeout_seconds=2.)
        report = machine.run()
        self.assertEqual("return_deadline", report["reason"])
        self.assertEqual([], harness.taps)

    """The named step that taps the start page's 开始 button."""

    def run_return(self, states, on_tap_state=None, max_clicks=3, start_control=True):
        harness = Harness(states, on_tap_state, start_control=start_control)
        machine = settle.ReturnToStart(harness.capture, harness.tap, harness.classify,
                                       now=harness.clock, sleep=harness.sleep,
                                       max_clicks=max_clicks)
        return machine.run(), harness

    def test_stops_as_soon_as_the_start_page_is_recognised(self):
        report, harness = self.run_return(["card_collection", "card_collection"],
                                          on_tap_state="home")
        self.assertEqual("return_reached:home", report["reason"])
        self.assertEqual("home", report["final_state"])
        self.assertTrue(report["on_start_page"])
        self.assertEqual(1, len(harness.taps))

    def test_taps_only_the_measured_start_button_centre(self):
        report, harness = self.run_return(["card_collection"] * 4,
                                          on_tap_state="mode_menu")
        self.assertEqual("return_reached:mode_menu", report["reason"])
        self.assertFalse(report["on_start_page"])
        for point in harness.taps:
            self.assertEqual(settle.START_BUTTON, point)

    def test_gives_up_after_its_own_budget(self):
        report, harness = self.run_return(["card_collection"] * 8, max_clicks=3)
        self.assertEqual("return_budget_exhausted", report["reason"])
        self.assertEqual(3, len(harness.taps))
        self.assertEqual(3, report["clicks"])
        self.assertEqual("card_collection", report["final_state"])

    def test_the_last_tap_is_judged_by_a_fresh_frame(self):
        # The state in hand was observed before the last tap; a step that
        # reported it as the final state would claim the wrong screen.
        report, _ = self.run_return(["card_collection"] * 8, on_tap_state="home",
                                    max_clicks=1)
        self.assertEqual("return_reached:home", report["reason"])
        self.assertEqual("home", report["final_state"])

    def test_a_page_that_is_still_drawing_is_not_called_buttonless(self):
        # Live: the frame read 0.6 s after the step's own tap had the button gone
        # while the page behind it was not yet drawn. Absence is only believed
        # once consecutive observations agree, and nothing is pressed meanwhile.
        harness = Harness(["card_collection"] * 8, start_control=False)
        machine = settle.ReturnToStart(harness.capture, harness.tap, harness.classify,
                                       now=harness.clock, sleep=harness.sleep)
        report = machine.run()
        self.assertEqual("return_control_absent:card_collection", report["reason"])
        self.assertGreaterEqual(harness.observed, settle.RETURN_SETTLE_OBSERVATIONS)
        self.assertEqual([], harness.taps)

    def test_the_deck_selection_the_start_button_opens_is_a_usable_ending(self):
        # The walk drives the deck selection straight from the 开始 button, so a
        # return that reaches it is one the campaign continues from - even though
        # it is not literally the start page, which `on_start_page` reports.
        harness = Harness(["card_collection"] * 8, start_control=False)
        machine = settle.ReturnToStart(harness.capture, harness.tap, harness.classify,
                                       now=harness.clock, sleep=harness.sleep)
        # The button is already gone on the settled page, as it is on the live
        # mode/deck selection (its 开始 tile is drawn highlighted, not plain).
        machine.classify = lambda frame: {"state": "deck_list",
                                          "start_control": {"ok": False, "score": 0.148}}
        report = machine.run()
        self.assertEqual("return_reached:deck_list", report["reason"])
        self.assertFalse(report["on_start_page"])
        self.assertEqual([], harness.taps)

    def test_the_button_absent_rule_needs_consecutive_agreement(self):
        # One frame without the button must not conclude anything: the step keeps
        # looking, and a button that reappears is pressed within the budget.
        harness = Harness(["card_collection"] * 8, start_control=True)
        seen = {"count": 0}

        def classify(frame):
            seen["count"] += 1
            # The first two observations are of a page that is still drawing.
            if seen["count"] <= 2:
                return {"state": "unknown", "start_control": {"ok": False, "score": 0.1}}
            return {"state": "card_collection", "start_control": {"ok": True, "score": 0.99}}

        machine = settle.ReturnToStart(harness.capture, harness.tap, classify,
                                       now=harness.clock, sleep=harness.sleep,
                                       max_clicks=1)
        report = machine.run()
        self.assertEqual(1, len(harness.taps))
        self.assertEqual("return_budget_exhausted", report["reason"])

    def test_result_page_is_not_treated_as_the_start_page(self):
        # On a real result banner the 开始 tile is not drawn (measured -0.066
        # against the template), so the step has nothing it may press.
        report, harness = self.run_return(["result_defeat"] * 6, max_clicks=2,
                                          start_control=False)
        self.assertEqual("return_control_absent:result_defeat", report["reason"])
        self.assertEqual([], harness.taps)

    def test_a_screen_without_the_start_control_is_never_tapped(self):
        # The gate the operator asked for: only the button's own centre, and
        # only where that button is actually on screen.
        report, harness = self.run_return(["unknown"] * 4, start_control=False)
        self.assertEqual("return_control_absent:unknown", report["reason"])
        self.assertEqual([], harness.taps)
        self.assertTrue(any(event["event"] == "return_control_absent"
                            for event in report["events"]))

    def test_missing_start_button_state_does_not_loop_forever(self):
        harness = Harness(["card_collection"] * 4)
        machine = settle.ReturnToStart(lambda: None, harness.tap, harness.classify,
                                       now=harness.clock, sleep=harness.sleep)
        report = machine.run()
        self.assertEqual("return_capture_failed", report["reason"])
        self.assertEqual([], harness.taps)


class SettleThenReturnTests(unittest.TestCase):
    """The whole post-match attempt: dismiss, then get back to the start page."""

    class Bridge:
        """Java-facing double: frames and recognitions, no device.

        `on_tap_states` is the screen produced by each successive tap, so a case
        can script the real sequence - the dismissal's tap lands on the card
        collection and the 开始 tap then reaches the start page - instead of
        depending on how many frames the loop happens to sample.
        """

        def __init__(self, states, on_tap_states=None, start_control=True):
            self.states = list(states)
            self.on_tap_states = list(on_tap_states) if on_tap_states else None
            self.start_control = start_control
            self.observed = 0
            self.taps = []
            self.settle_requests = []

        def capture(self):
            index = self.observed
            self.observed += 1
            import json
            return json.dumps({"ok": True, "frame_id": index + 1,
                               "captured_elapsed_ms": index * 100,
                               "foreground_generation": 1,
                               "source_width": 1920, "source_height": 1080,
                               "width": 1280, "height": 720,
                               "png_path": "/frames/%05d.png" % (index + 1)})

        def observeMenu(self, request):
            import json
            index = max(0, self.observed - 1)
            if self.on_tap_states and self.taps:
                state = self.on_tap_states[min(len(self.taps) - 1, len(self.on_tap_states) - 1)]
            elif index < len(self.states):
                state = self.states[index]
            else:
                state = self.states[-1]
            payload = json.loads(request)
            path = payload.get("png_path")
            # The recogniser reads a file, so what arrives here must be the file
            # name of a captured frame. A live settlement pass sent the frame's
            # own array repr instead, and the recogniser answered
            # "unsupported_frame_size" for every screen it was shown.
            assert isinstance(path, str) and path.endswith('.png'), path
            assert '\n' not in path and len(path) < 260, path
            assert 'assets' in payload, payload
            return json.dumps({"state": state,
                               "start_control": {"ok": self.start_control, "score": 0.99,
                                                 "bounds": [26, 101, 67, 80]}})

        def dispatchSettle(self, request):
            import json
            self.settle_requests.append(json.loads(request))
            self.taps.append(True)
            return json.dumps({"accepted": True, "completed": True})

    def _patch_imread(self):
        # The runner only needs a frame object it can pass back; real decoding is
        # covered by the device runs, not here.
        import cv2
        original = cv2.imread
        cv2.imread = lambda path: plate(0)
        self.addCleanup(setattr, cv2, "imread", original)

    def _run(self, states, on_tap_states=None, start_control=True, **kwargs):
        import json
        self._patch_imread()
        bridge = self.Bridge(states, on_tap_states, start_control)
        return json.loads(settle.run(bridge, timeout_seconds=30.0, **kwargs)), bridge

    def _virtual_run(self, bridge, **kwargs):
        from unittest import mock
        clock = Harness(['unknown'])
        settle_class = settle.Settle
        return_class = settle.ReturnToStart
        def window(*args, **options):
            return settle_class(*args, now=clock.clock, sleep=clock.sleep, **options)
        def return_step(*args, **options):
            return return_class(*args, now=clock.clock, sleep=clock.sleep, **options)
        with mock.patch.object(settle, 'Settle', window), \
                mock.patch.object(settle, 'ReturnToStart', return_step), \
                mock.patch.object(settle.time, 'monotonic', clock.clock):
            return json.loads(settle.run(bridge, timeout_seconds=30., **kwargs))

    def test_unnamed_level_reward_page_can_be_dismissed_to_home(self):
        self._patch_imread()
        bridge = self.Bridge(['result_defeat'], on_tap_states=['unknown', 'home'],
                             start_control=False)
        report = self._virtual_run(bridge)
        self.assertEqual('settle_screen_known:home', report['reason'])
        self.assertEqual(2, report['clicks'])
        self.assertEqual(2, report['total_clicks'])
        self.assertEqual('return_not_needed:home', report['reason_after_return'])
        self.assertEqual(2, len(bridge.settle_requests))

    def test_postvictory_reward_task_overlay_can_reach_deck_details(self):
        self._patch_imread()
        bridge = self.Bridge(['result_victory'],
                             on_tap_states=['unknown', 'task_popup', 'deck_ready'],
                             start_control=False)
        report = self._virtual_run(bridge)
        self.assertEqual('settle_screen_known:deck_ready', report['reason'])
        self.assertEqual('return_not_needed:deck_ready', report['reason_after_return'])
        self.assertEqual(3, report['clicks'])
        self.assertEqual(3, report['total_clicks'])
        self.assertIsNone(report['return'])
        self.assertFalse(report['on_start_page'])
        self.assertTrue(any(event['event'] == 'settle_on_menu_overlay' for event in report['events']))
        for request in bridge.settle_requests:
            x, y = request['from']
            self.assertLessEqual(abs(x-640), settle.JITTER)
            self.assertLessEqual(abs(y-665), settle.JITTER)

    def test_overlay_at_fifteen_attempts_does_not_spend_the_return_budget(self):
        self._patch_imread()
        bridge = self.Bridge(['task_popup'], start_control=True)
        report = self._virtual_run(bridge)
        self.assertEqual('settle_click_budget', report['reason'])
        self.assertEqual('return_skipped:settle_click_budget', report['reason_after_return'])
        self.assertEqual(15, report['total_clicks'])
        self.assertIsNone(report['return'])
        self.assertEqual(15, len(bridge.settle_requests))

    def test_last_window_attempt_can_clear_overlay_to_deck_ready(self):
        self._patch_imread()
        bridge = self.Bridge(['task_popup'], on_tap_states=['task_popup']*14+['deck_ready'],
                             start_control=False)
        report = self._virtual_run(bridge)
        self.assertEqual('settle_screen_known:deck_ready', report['reason'])
        self.assertEqual('return_not_needed:deck_ready', report['reason_after_return'])
        self.assertEqual(15, report['total_clicks'])
        self.assertIsNone(report['return'])

    def test_fifteen_attempts_and_return_step_keep_separate_budgets(self):
        self._patch_imread()
        bridge = self.Bridge(['result_victory'],
                             on_tap_states=['unknown'] * 14 + ['card_collection'])
        report = self._virtual_run(bridge)
        self.assertEqual('settle_screen_known:card_collection', report['settle_reason'])
        self.assertEqual(15, report['clicks'])
        self.assertEqual(3, report['return']['clicks'])
        self.assertEqual(18, report['total_clicks'])
        self.assertEqual('return_budget_exhausted', report['reason_after_return'])
        for request in bridge.settle_requests[15:]:
            self.assertEqual(list(settle.START_BUTTON), request['from'])

    def test_uncertain_or_refused_dispatch_never_enters_the_return_step(self):
        self._patch_imread()
        for reply in ({'accepted': False, 'completed': False},
                      {'accepted': True, 'completed': False}):
            with self.subTest(reply=reply):
                bridge = self.Bridge(['result_defeat'], start_control=True)
                def dispatch(request):
                    bridge.settle_requests.append(json.loads(request))
                    bridge.taps.append(True)
                    return json.dumps(reply)
                bridge.dispatchSettle = dispatch
                report = self._virtual_run(bridge)
                self.assertEqual('settle_input_refused', report['reason'])
                self.assertEqual('return_skipped:settle_input_refused', report['reason_after_return'])
                self.assertIsNone(report['return'])
                self.assertEqual(1, report['total_clicks'])
                self.assertEqual(1, len(bridge.settle_requests))

    def test_foreground_loss_capture_failure_skips_return_without_more_inputs(self):
        self._patch_imread()
        bridge = self.Bridge(['unknown'])
        original = bridge.capture
        def capture():
            if bridge.taps:
                return json.dumps({'ok': False, 'reason': 'foreground_changed'})
            return original()
        bridge.capture = capture
        report = self._virtual_run(bridge)
        self.assertEqual('settle_capture_failed', report['reason'])
        self.assertEqual('return_skipped:settle_capture_failed', report['reason_after_return'])
        self.assertEqual(1, len(bridge.settle_requests))

    def test_a_start_page_ending_needs_no_return_tap(self):
        report, bridge = self._run(["result_defeat"] * 4, on_tap_states=["home"])
        self.assertEqual("settle_screen_known:home", report["reason"])
        self.assertEqual("return_not_needed:home", report["reason_after_return"])
        self.assertTrue(report["on_start_page"])
        self.assertIsNone(report["return"])
        self.assertEqual(1, len(bridge.settle_requests))

    def test_the_result_page_tap_then_the_start_button(self):
        # The reported live sequence: the dismissal tap leaves the result page
        # for the card collection, and the 开始 button then brings the start page
        # back so the next match can be started.
        report, bridge = self._run(["result_defeat"] * 4,
                                   on_tap_states=["card_collection", "home"])
        self.assertEqual("settle_screen_known:card_collection", report["reason"])
        self.assertEqual("return_reached:home", report["reason_after_return"])
        self.assertEqual("home", report["final_state"])
        self.assertTrue(report["on_start_page"])
        self.assertEqual(1, report["clicks"])
        self.assertEqual(2, report["total_clicks"])
        self.assertEqual(2, len(bridge.settle_requests))
        self.assertEqual(settle.START_BUTTON,
                         (bridge.settle_requests[1]["from"][0],
                          bridge.settle_requests[1]["from"][1]))

    def test_a_card_collection_ending_is_followed_by_the_start_button(self):
        report, bridge = self._run(["card_collection"] * 4, on_tap_states=["home"])
        self.assertEqual("settle_screen_known:card_collection", report["reason"])
        self.assertEqual("return_reached:home", report["reason_after_return"])
        self.assertTrue(report["on_start_page"])
        self.assertEqual("home", report["final_state"])
        self.assertEqual(0, report["clicks"])
        self.assertEqual(1, report["total_clicks"])
        self.assertEqual(1, len(bridge.settle_requests))
        request = bridge.settle_requests[0]
        self.assertEqual("settle", request["context"])
        self.assertEqual(settle.START_BUTTON, (request["from"][0], request["from"][1]))

    def test_an_unknown_screen_ends_without_any_return_tap(self):
        self._patch_imread()
        bridge = self.Bridge(['unknown'], start_control=True)
        report = self._virtual_run(bridge)
        self.assertEqual("return_skipped:settle_click_budget", report["reason_after_return"])
        self.assertFalse(report["on_start_page"])
        # Only the dismissal's own taps went out; the return step added none.
        self.assertEqual(report["clicks"], len(bridge.settle_requests))
        self.assertIsNone(report['return'])
        self.assertEqual(15, len(bridge.settle_requests))

    def test_a_named_page_without_the_start_control_is_left_alone(self):
        report, bridge = self._run(["card_collection"], start_control=False)
        self.assertEqual("settle_screen_known:card_collection", report["reason"])
        self.assertEqual("return_control_absent:card_collection",
                         report["reason_after_return"])
        self.assertEqual([], bridge.settle_requests)

    def test_an_unclassified_screen_is_not_reported_as_a_missing_button(self):
        # The Java boundary's own fallback is a bare {"state": "unknown"}: no
        # control report exists, which is not the same claim as "this page has no
        # 开始 button".
        import json
        self._patch_imread()
        bridge = self.Bridge(["card_collection"])
        bridge.observeMenu = lambda request: json.dumps({"state": "unknown"})
        report = self._virtual_run(bridge)
        self.assertEqual("return_skipped:settle_click_budget",
                         report["reason_after_return"])
        self.assertIsNone(report['return'])
        # Only the dismissal's own tap went out; the return step added none.
        self.assertEqual(report["clicks"], len(bridge.settle_requests))

    def test_the_return_step_can_be_switched_off(self):
        report, bridge = self._run(["card_collection"], return_to_start=False)
        self.assertEqual("return_disabled", report["reason_after_return"])
        self.assertEqual([], bridge.settle_requests)
        self.assertFalse(report["on_start_page"])
        self.assertEqual(0, report["total_clicks"])

    def test_the_recogniser_is_given_the_captured_files_own_path(self):
        # Regression: the machine classifies the decoded image, and the boundary
        # needs the file it came from. Sending the image instead of the path made
        # every live pass answer "unsupported_frame_size" for every screen.
        import json
        self._patch_imread()
        bridge = self.Bridge(["result_defeat"] * 4, on_tap_states=["home"])
        seen = []
        original = bridge.observeMenu

        def record(request):
            seen.append(json.loads(request)["png_path"])
            return original(request)

        bridge.observeMenu = record
        settle.run(bridge, timeout_seconds=30.0)
        self.assertTrue(seen)
        for path in seen:
            self.assertRegex(path, r'^/frames/\d{5}\.png$')

    def test_runner_requests_are_settle_taps_only(self):
        import json
        self._patch_imread()
        bridge = self.Bridge(["result_defeat"] * 4, on_tap_states=["home"])
        report = json.loads(settle.run(bridge, timeout_seconds=30.0))
        self.assertEqual("settle_screen_known:home", report["reason"])
        self.assertTrue(bridge.settle_requests)
        for request in bridge.settle_requests:
            self.assertEqual("settle", request["context"])
            self.assertEqual("tap", request["kind"])
            self.assertEqual(settle.TAP_DURATION_MS, request["duration_ms"])
            self.assertNotIn("path_points", request)
            self.assertEqual(request["from"], request["to"])

    def test_runner_forwards_the_chosen_point(self):
        report, bridge = self._run(["result_defeat"] * 4, on_tap_states=["home"],
                                   points=((59, 147),))
        request = bridge.settle_requests[0]
        self.assertLessEqual(abs(request["from"][0] - 59), settle.JITTER)
        self.assertLessEqual(abs(request["from"][1] - 147), settle.JITTER)

    def test_runner_stops_asking_once_a_known_screen_appears(self):
        import json
        self._patch_imread()
        bridge = self.Bridge(["result_defeat", "result_defeat", "deck_list"],
                             on_tap_states=["mode_menu"])
        report = json.loads(settle.run(bridge, timeout_seconds=30.0))
        self.assertEqual("settle_screen_known:mode_menu", report["reason"])
        # The screen that follows the first tap is already known, so the
        # dismissal stops asking there, and the mode menu it reached is one the
        # campaign walk continues from: the return step spends nothing.
        self.assertEqual(1, report["clicks"])
        self.assertEqual(1, report["total_clicks"])
        self.assertEqual(1, len(bridge.settle_requests))
        self.assertEqual("return_not_needed:mode_menu", report["reason_after_return"])


class FrameReadingTests(unittest.TestCase):
    """How a captured frame is decoded, and what the report says about it.

    A live settle pass classified nothing at all because decoding returned None
    inside a module whose callers decoded the same files without trouble. The
    reader is therefore explicit about the route it took, and it must never
    turn "I could not read the frame" into "I did not recognise the screen".
    """

    class FakeRecognizer:
        """Stands in for the template recogniser: the wrapper is under test."""

        def __init__(self):
            self.frames = []

        def observe(self, frame):
            self.frames.append(frame)
            if frame is None or frame.shape != (720, 1280, 3):
                return {'state': 'unknown', 'reason': 'unsupported_frame_size'}
            return {'state': 'home', 'evidence': {}}

    def setUp(self):
        import cv2
        import apk_match_entry
        self.cv2 = cv2
        self.entry = apk_match_entry
        self.addCleanup(setattr, cv2, 'imread', cv2.imread)
        self.addCleanup(setattr, cv2, 'imdecode', cv2.imdecode)
        self.key = 'frame-reading-tests'
        self.fake = self.FakeRecognizer()
        apk_match_entry._OBSERVERS[self.key] = self.fake
        self.addCleanup(apk_match_entry._OBSERVERS.pop, self.key, None)

    def test_imread_is_used_when_it_works(self):
        self.cv2.imread = lambda path: plate(7)
        frame, route = self.entry.read_frame('whatever.png')
        self.assertEqual('imread', route)
        self.assertEqual((720, 1280, 3), frame.shape)

    def test_the_frames_own_bytes_are_the_fallback(self):
        # Chaquopy loads packaged bytecode: __file__ may name a .py which does
        # not physically exist. Use a real captured-image-shaped PNG on both
        # host and Android, and verify the fallback reads those exact bytes.
        import tempfile
        from pathlib import Path
        expected = plate(9)
        encoded_ok, encoded = self.cv2.imencode('.png', expected)
        self.assertTrue(encoded_ok)
        png_bytes = encoded.tobytes()
        decode = self.cv2.imdecode
        seen = []
        def checked_decode(buffer, flags):
            seen.append(buffer.tobytes())
            return decode(buffer, flags)
        self.cv2.imread = lambda path: None
        self.cv2.imdecode = checked_decode
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / 'captured-frame.png'
            image_path.write_bytes(png_bytes)
            frame, route = self.entry.read_frame(str(image_path))
        self.assertEqual('imdecode', route)
        self.assertEqual([png_bytes], seen)
        np.testing.assert_array_equal(expected, frame)

    def test_an_unreadable_path_is_named(self):
        self.cv2.imread = lambda path: None
        frame, route = self.entry.read_frame('no/such/frame.png')
        self.assertIsNone(frame)
        # The route keeps the reason: "could not read this file" and "read it and
        # saw no screen" must not be the same line in a report.
        self.assertTrue(route.startswith('unreadable:'), route)
        self.assertIn('FileNotFoundError', route)

    def test_the_observation_reports_the_decoded_frame(self):
        self.cv2.imread = lambda path: plate(3)
        observation = json.loads(self.entry.observe('frame.png', self.key))
        self.assertEqual('home', observation['state'])
        self.assertEqual([720, 1280, 3], observation['frame_shape'])
        self.assertEqual('imread', observation['frame_reader'])
        self.assertEqual(1, len(self.fake.frames))

    def test_an_undecodable_frame_is_not_reported_as_a_named_screen(self):
        self.cv2.imread = lambda path: None
        observation = json.loads(self.entry.observe('no/such/frame.png', self.key))
        self.assertEqual('unknown', observation['state'])
        self.assertEqual('unsupported_frame_size', observation['reason'])
        self.assertIsNone(observation['frame_shape'])
        self.assertTrue(observation['frame_reader'].startswith('unreadable:'))
        self.assertEqual('no/such/frame.png', observation['frame_path'])

    def test_settlement_capture_uses_the_same_reader(self):
        # The frame reader must be shared: settlement's own change detection
        # silently compared None with None while the recogniser saw no screen.
        import os
        import shutil
        import tempfile
        self.cv2.imread = lambda path: None
        self.cv2.imdecode = lambda buffer, flags: plate(5)
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, True)
        path = os.path.join(directory, '00001.png')
        with open(path, 'wb') as handle:
            handle.write(b'\x89PNG\r\n\x1a\n')
        harness = SettleThenReturnTests.Bridge(['home'], on_tap_states=['home'])
        original = harness.capture

        def capture_with_a_real_path():
            # The fallback route opens the path, so the case points it at a file
            # that exists; only the decoder is scripted.
            packet = json.loads(original())
            packet['png_path'] = path
            return json.dumps(packet)

        harness.capture = capture_with_a_real_path
        report = json.loads(settle.run(harness, timeout_seconds=30.0))
        self.assertEqual('settle_screen_known:home', report['reason'])
        self.assertEqual([], harness.settle_requests)
        self.assertEqual('imdecode', report['frame_reader'])


if __name__ == "__main__":
    unittest.main()
