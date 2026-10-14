"""Host/fake-bridge checks. Never opens a device or emits a real gesture."""
import json
from pathlib import Path
import shutil
import tempfile
import time
import types
import unittest
from unittest import mock

import apk_battle_runtime as runtime


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.options = runtime.options_from_json('{"read_only":false}')
        self.info = {"state": "in_game", "button": "white", "button_box": [1110, 302, 110, 68],
                     "transition_reason": "", "choice_modal": False, "captured_elapsed_ms": 1000}
        self.gesture = {"kind": "drag", "from": [600, 475], "to": [600, 350], "duration_ms": 1000}

    def check(self, gesture=None, context="move_front", info=None, now=2000, remaining=30000, count=0):
        runtime.validate_gesture(gesture or self.gesture, context, self.info if info is None else info,
                                 now, remaining, count, self.options)

    def test_valid_drag_and_tap(self):
        self.check()
        self.check({"kind": "tap", "from": [1160, 330], "to": [1160, 330], "duration_ms": 60}, "end_turn")

    def test_defaults_are_readonly(self):
        self.assertTrue(runtime.options_from_json("{}")["read_only"])
        self.options["read_only"] = True
        with self.assertRaises(runtime.Stop):
            self.check()

    def test_faster_loop_requires_latest_own_turn_without_pending_end_input(self):
        instance = types.SimpleNamespace(last_info=self.info,
                                         now=lambda: 2000,
                                         engine=types.SimpleNamespace(_turn_ready_at=0.),
                                         end_turn_ledger=types.SimpleNamespace(pending=None))
        for button in ("white", "orange"):
            instance.last_info = dict(self.info, button=button)
            self.assertEqual(runtime.Runtime.loop_delay(instance), .25)
        for change in ({"state": None}, {"button": None}, {"choice_modal": True},
                       {"transition_reason": "card_overlay"},
                       {"captured_elapsed_ms": -2000}, {"captured_elapsed_ms": 2001}):
            instance.last_info = dict(self.info, **change)
            self.assertEqual(runtime.Runtime.loop_delay(instance), .6)
        instance.last_info = self.info
        instance.end_turn_ledger.pending = {"status": "pending"}
        self.assertEqual(runtime.Runtime.loop_delay(instance), .6)
        instance.end_turn_ledger.pending = None
        instance.engine._turn_ready_at = time.time() + 10
        self.assertEqual(runtime.Runtime.loop_delay(instance), .6)

    def test_options_reject_unknown_and_invalid(self):
        for encoded in ('{"foo":1}', '{"read_only":"false"}', '{"max_inputs":0}',
                        '{"max_inputs":1.2}', '{"max_seconds":1801}', '{"max_seconds":NaN}'):
            with self.subTest(encoded=encoded), self.assertRaises(ValueError):
                runtime.options_from_json(encoded)

    def test_age_alone_replans(self):
        with self.assertRaises(runtime.Replan):
            self.check(now=4001)
        self.check(now=4000)

    def test_other_refusals_win_over_age(self):
        for kwargs in ({"count": 1}, {"remaining": 7999}, {"context": "anything"},
                       {"info": dict(self.info, state=None)},
                       {"info": dict(self.info, choice_modal=True)},
                       {"info": dict(self.info, transition_reason="motion")},
                       {"info": dict(self.info, button=None)}):
            with self.subTest(kwargs=kwargs), self.assertRaises(runtime.Stop):
                self.check(now=9000, **kwargs)

    def test_future_capture_is_terminal(self):
        with self.assertRaises(runtime.Stop):
            self.check(now=999)

    def test_drag_coordinates_and_kind(self):
        for override in ({"kind": "tap"}, {"from": [1280, 100]}, {"from": [-1, 100]},
                         {"to": [200, 720]}, {"duration_ms": 3001},
                         {"from": [200, 600]}, {"from": [float("nan"), 200]}):
            with self.subTest(override=override), self.assertRaises(runtime.Stop):
                self.check(dict(self.gesture, **override))
        self.check(dict(self.gesture, **{"from": [200, 600], "duration_ms": 900,
            "path_points": [[200, 600], [200, 540], self.gesture["to"]]}), context="deploy")

    def test_deployment_path_has_fixed_lift_and_duration(self):
        for origin, waypoint in (([872, 666], [872, 575]), ([300, 620], [300, 560])):
            path = runtime.deployment_path_points(origin, [353, 505])
            self.assertEqual(path, [origin, waypoint, [353, 505]])
            self.check({"kind": "drag", "from": origin, "to": [353, 505],
                        "duration_ms": 900, "path_points": path}, context="deploy")

    def test_missing_arbitrary_or_malformed_deployment_paths_are_rejected(self):
        gesture = {"kind": "drag", "from": [872, 666], "to": [353, 505], "duration_ms": 900}
        bad_paths = (None, [], [[872, 666], [872, 575]],
                     [[871, 666], [872, 575], [353, 505]],
                     [[872, 666], [871, 575], [353, 505]],
                     [[872, 666], [872, 576], [353, 505]],
                     [[872, 666], [872, 575], [354, 505]],
                     [[872, 666], ["872", 575], [353, 505]],
                     [[872, 666], [872, 575], [353, 505], [400, 500]])
        for path in bad_paths:
            with self.subTest(path=path), self.assertRaisesRegex(runtime.Stop, "invalid_deployment_path"):
                self.check(dict(gesture, path_points=path), context="deploy")
        with self.assertRaisesRegex(runtime.Stop, "invalid_deployment_duration"):
            self.check(dict(gesture, duration_ms=1000, path_points=runtime.deployment_path_points(
                gesture["from"], gesture["to"])), context="deploy")

    def test_intermediate_path_is_forbidden_on_other_actions(self):
        for context in ("attack_hq", "attack_unit", "move_front"):
            with self.subTest(context=context), self.assertRaisesRegex(runtime.Stop, "path_points_outside_deployment"):
                self.check(dict(self.gesture, path_points=[]), context=context)
        tap = {"kind": "tap", "from": [1160, 330], "to": [1160, 330], "duration_ms": 60, "path_points": []}
        with self.assertRaisesRegex(runtime.Stop, "path_points_outside_deployment"):
            self.check(tap, context="end_turn")

    def test_deployment_primitives_emit_one_fixed_900ms_lift_path(self):
        emitted, clock = [], [1000]
        fake = types.SimpleNamespace(check_running=lambda: None, now=lambda: clock[0],
                                     context="deploy", dispatch=emitted.append)
        platform = runtime.AccessibilityPlatform(fake)
        platform.set_cursor(872, 666)
        platform.mouse_down()
        clock[0] += 1700
        platform.mouse_move(353, 505)
        platform.mouse_up()
        platform.flush_input()
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["duration_ms"], 900)
        self.assertEqual(emitted[0]["path_points"], [[872, 666], [872, 575], [353, 505]])

    def test_tap_requires_observed_button(self):
        tap = {"kind": "tap", "from": [1160, 330], "to": [1160, 330], "duration_ms": 60}
        for override in ({"from": [100, 330], "to": [100, 330]},
                         {"to": [1159, 330]}, {"duration_ms": 900}):
            with self.subTest(override=override), self.assertRaises(runtime.Stop):
                self.check(dict(tap, **override), context="end_turn")

    def test_modal_needs_independent_stable_samples(self):
        gate = runtime.ChoiceModalGate(.008)
        self.assertEqual(gate.observe(True, 0, None), "waiting")
        self.assertEqual(gate.observe(True, .1, 0), "waiting")
        self.assertEqual(gate.stable_frames, 1)
        self.assertEqual(gate.observe(True, 1, 0), "waiting")
        self.assertEqual(gate.observe(True, 3.1, 0), "confirmed")
        self.assertEqual(gate.observe(False, 3.2, None), "clear")
        self.assertEqual(gate.stable_frames, 0)

    def test_modal_moving_times_out(self):
        gate = runtime.ChoiceModalGate(.008)
        self.assertEqual(gate.observe(True, 0, None), "waiting")
        self.assertEqual(gate.observe(True, 12, .8), "timeout")

    def test_cancelled_down_emits_nothing(self):
        fake = types.SimpleNamespace(check_running=lambda: (_ for _ in ()).throw(runtime.Stop("cancelled")))
        platform = runtime.AccessibilityPlatform(fake)
        platform.set_cursor(200, 200)
        with self.assertRaises(runtime.Stop):
            platform.mouse_down()

    def test_primitives_emit_once_and_coordinates_stay_normalized(self):
        emitted = []
        clock = [1000]
        fake = types.SimpleNamespace(check_running=lambda: None, now=lambda: clock[0], dispatch=emitted.append)
        platform = runtime.AccessibilityPlatform(fake)
        self.assertEqual(platform.client_to_screen(None, 640, 360), (640, 360))
        platform.set_cursor(600, 475)
        platform.mouse_down()
        clock[0] += 1000
        platform.mouse_move(600, 350)
        platform.mouse_up()
        platform.flush_input()
        self.assertEqual(emitted, [self.gesture])


class SameFrameHandCacheTests(unittest.TestCase):
    """Cache identity is a capture plus pixels, never ndarray identity alone."""

    def setUp(self):
        import numpy as np
        self.fixture = DispatchBridgeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.addCleanup(self.fixture.doCleanups)
        self.fixture._prepare_deployment()
        self.runtime = self.fixture.runtime
        self.frame = np.zeros((720, 1280, 3), np.uint8)
        self.runtime.last_frame = self.frame
        self.runtime.last_id = self.runtime.last_info["frame_id"]

    def test_raw_same_pixels_are_reused_with_deep_copies(self):
        self.fixture.raw_hand_find.return_value[0]["nested"] = {"values": [1, 2]}
        first = self.runtime.find_hand(self.frame)
        first[0]["nested"]["values"][0] = 99
        second = self.runtime.find_hand(self.frame)
        second[0]["nested"]["values"].append(3)
        third = self.runtime.find_hand(self.frame)
        self.assertEqual(third[0]["nested"]["values"], [1, 2])
        self.assertEqual(self.fixture.raw_hand_find.call_count, 1)

    def test_any_pixel_change_invalidates_even_if_later_restored(self):
        for value in (0, 1, 0):
            # Outside the hand: resource/board changes also invalidate.
            self.frame[10, 10, 0] = value
            self.runtime.find_hand(self.frame)
        self.assertEqual(self.fixture.raw_hand_find.call_count, 3)

    def test_capture_identity_and_metadata_never_extend_old_observations(self):
        self.runtime.find_hand(self.frame)
        self.frame = self.frame.copy()
        self.runtime.last_frame = self.frame
        self.runtime.find_hand(self.frame)
        self.runtime.last_info["captured_elapsed_ms"] += 1
        self.runtime.find_hand(self.frame)
        self.runtime.last_id += 1
        self.runtime.last_info["frame_id"] += 1
        self.runtime.find_hand(self.frame)
        self.runtime.last_info["foreground_generation"] += 1
        self.runtime.find_hand(self.frame)
        self.assertEqual(self.fixture.raw_hand_find.call_count, 5)

    def test_capture_clears_cache_before_even_failed_new_capture(self):
        self.runtime.find_hand(self.frame)
        self.runtime.bridge.capture = lambda: {"ok": False, "reason": "unavailable"}
        with self.assertRaisesRegex(runtime.Stop, "capture_rejected:unavailable"):
            runtime.Runtime.capture(self.runtime)
        self.assertEqual(self.runtime._hand_cache, {})
        self.runtime.find_hand(self.frame)
        self.assertEqual(self.fixture.raw_hand_find.call_count, 2)

    def test_recognition_parameters_are_separate_cache_entries(self):
        options = ({}, {"zone": (200, 560, 1100, 720)}, {"want": "any"},
                   {"units_only": True}, {"debug": True}, {"max_units": 1})
        for option in options:
            self.runtime._find_raw_hand(self.frame, **option)
            self.runtime._find_raw_hand(self.frame, **option)
        self.assertEqual(self.fixture.raw_hand_find.call_count, len(options))

    def test_noncurrent_array_never_reuses_a_current_capture(self):
        other = self.frame.copy()
        self.runtime.find_hand(other)
        self.runtime.find_hand(other)
        self.assertEqual(self.fixture.raw_hand_find.call_count, 2)

    def test_float_zone_cannot_alias_cached_integer_zone(self):
        def slice_zone(frame, **kwargs):
            x1, y1, x2, y2 = kwargs["zone"]
            frame[y1:y2, x1:x2]
            return []
        self.fixture.raw_hand_find.side_effect = slice_zone
        self.runtime._find_raw_hand(self.frame, zone=(200, 560, 1100, 720))
        with self.assertRaises(TypeError):
            self.runtime._find_raw_hand(self.frame, zone=(200.0, 560.0, 1100.0, 720.0))
        self.assertEqual(self.fixture.raw_hand_find.call_count, 2)

    def test_recognizer_pixel_mutation_cannot_cache_prechange_result(self):
        def mutate(frame, **kwargs):
            frame[0, 0, 0] += 1
            return [{"kind": "unit"}]
        self.fixture.raw_hand_find.side_effect = mutate
        self.runtime.find_hand(self.frame)
        self.runtime.find_hand(self.frame)
        self.assertEqual(self.fixture.raw_hand_find.call_count, 2)
        self.assertEqual(self.runtime._hand_cache, {})

    def test_availability_candidates_and_nested_results_are_isolated(self):
        candidates = self.fixture.raw_hand_find.return_value
        first = self.runtime.filter_deploy_units(self.frame, candidates, "candidate_selection")
        first[0]["apk_availability"]["credits"] = 0
        second = self.runtime.filter_deploy_units(self.frame, candidates, "dispatch_preflight")
        self.assertEqual(second[0]["apk_availability"]["credits"], 2)
        self.assertEqual(self.fixture.availability_filter.call_count, 1)
        candidates[0]["cx"] += 1
        self.runtime.filter_deploy_units(self.frame, candidates, "dispatch_preflight")
        self.assertEqual(self.fixture.availability_filter.call_count, 2)

    def test_cached_hand_still_checks_final_age_and_target(self):
        self.runtime.find_hand(self.frame, units_only=True)
        self.runtime.context = "deploy"
        self.runtime.engine.drop = (1000, 505)
        gesture = {"kind": "drag", "from": [489, 657], "to": [1000, 505], "duration_ms": 900}
        def late_clear(*args):
            self.fixture.time = 4001
            return {"clear": True, "reason": "clear"}
        with mock.patch("apk_deploy_target.inspect_clear", side_effect=late_clear) as target:
            with self.assertRaisesRegex(runtime.Replan, "input_frame_age_exceeded_replan"):
                self.runtime.dispatch(gesture)
        target.assert_called_once_with(self.frame, [1000, 505])
        self.assertEqual(self.fixture.raw_hand_find.call_count, 1)
        self.assertEqual(self.fixture.availability_filter.call_count, 1)
        self.assertEqual(self.fixture.calls, [])

    def test_changed_resource_pixels_recompute_and_reject_original_grab(self):
        approved = dict(self.fixture.approved_unit)
        def observe(frame, candidates):
            return {"units": [approved] if frame[540, 50, 0] == 0 else [],
                    "credits": 2 if frame[540, 50, 0] == 0 else 0, "checks": []}
        self.fixture.availability_filter.side_effect = observe
        self.runtime.find_hand(self.frame, units_only=True)
        self.frame[540, 50, 0] = 1
        self.runtime.context = "deploy"
        self.runtime.engine.drop = (1000, 505)
        with self.assertRaisesRegex(runtime.Stop, "deployment_origin_not_unique_current_unit"):
            self.runtime.dispatch({"kind": "drag", "from": [489, 657], "to": [1000, 505], "duration_ms": 900})
        self.assertEqual(self.fixture.raw_hand_find.call_count, 2)
        self.assertEqual(self.fixture.availability_filter.call_count, 2)
        self.assertEqual(self.fixture.calls, [])

    def test_dispatch_still_refuses_changed_origin_and_occupied_target(self):
        self.runtime.find_hand(self.frame, units_only=True)
        self.runtime.context = "deploy"
        self.runtime.engine.drop = (1000, 505)
        gesture = {"kind": "drag", "from": [490, 657], "to": [1000, 505], "duration_ms": 900}
        with self.assertRaisesRegex(runtime.Stop, "deployment_origin_not_unique_current_unit"):
            self.runtime.dispatch(gesture)
        gesture["from"] = [489, 657]
        with mock.patch("apk_deploy_target.inspect_clear", return_value={"clear": False, "reason": "occupied"}):
            with self.assertRaisesRegex(runtime.Stop, "deployment_destination_not_clear:occupied"):
                self.runtime.dispatch(gesture)
        self.assertEqual(self.fixture.calls, [])


class ResultCaptureTests(unittest.TestCase):
    """The APK result fallback observes a capture, never invents a result age."""
    def setUp(self):
        import cv2
        import numpy as np
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.time, self.index = 1000, 0
        self.calls = []
        self.core_state, self.result_state = None, 'result_defeat'
        self.bridge = types.SimpleNamespace(elapsedRealtime=lambda: self.time,
            isCancelled=lambda: False, emit=lambda event: None, capture=self.packet,
            observeResult=self.observe_result)
        self.runtime = runtime.Runtime(self.bridge, self.temp.name, self.temp.name,
                                       runtime.options_from_json('{"read_only":false}'))
        self.addCleanup(self.runtime.events.close)
        self.runtime.cv2, self.runtime.np = cv2, np
        self.runtime.ui = types.SimpleNamespace(classify=lambda *args: (self.core_state, {}))
        self.runtime.templates, self.runtime.states = {}, {}
        self.runtime.end_button = types.SimpleNamespace(inspect_end_button=lambda *args, **kwargs:
            dict(state=None, box=None, score=0, present=False, reason='absent'))
        self.runtime.mb = types.SimpleNamespace(END_TURN_MIN=.82, board_transition_reason=lambda f: '',
            choice_modal=lambda f: (False, ''), board_motion=lambda a,b: 0,
            frontline_state=lambda f: 'unknown', hq_card=lambda f, side: None)
        self.runtime.choice_gate = runtime.ChoiceModalGate(.008)
        self.path = Path(self.temp.name)/'capture.png'
        cv2.imwrite(str(self.path), np.ones((720,1280,3),np.uint8))

    def packet(self):
        self.index += 1
        return dict(frame_id=self.index,captured_elapsed_ms=self.time,foreground_generation=1,
                    source_width=1920,source_height=1080,png_path=str(self.path))

    def observe_result(self, encoded):
        packet = json.loads(encoded)
        self.calls.append(packet)
        return dict(packet, ok=True, state=self.result_state, evidence={'defeat_banner':{'ok':True}})

    def capture_at(self, timestamp):
        self.time = timestamp
        return self.runtime.capture()

    def test_pending_end_confirmation_does_not_repeat_irrelevant_hq_scan(self):
        self.core_state = "in_game"
        self.runtime.end_turn_ledger.pending = {"awaiting": True}
        self.runtime.end_turn_ledger.observe = mock.Mock(return_value=[])
        self.runtime.mb.hq_card = mock.Mock(side_effect=AssertionError("irrelevant HQ scan"))
        with mock.patch.dict("sys.modules", {
                "apk_hud_adapter": types.SimpleNamespace(inspect_hud=lambda _: {"layout": "unknown"}),
                "apk_enemy_turn": types.SimpleNamespace(inspect_opponent_turn=lambda _: {"present": True})}):
            self.capture_at(1000)
        self.runtime.mb.hq_card.assert_not_called()
        self.assertEqual(self.runtime.last_info["opponent_turn_label"], {"present": True})
        self.runtime.end_turn_ledger.observe.assert_called_once()

    def test_pending_end_on_unclassified_screen_uses_label_without_hq_scan(self):
        self.core_state, self.result_state = None, "unknown"
        self.runtime.end_turn_ledger.pending = {"awaiting": True}
        self.runtime.end_turn_ledger.observe = mock.Mock(return_value=[])
        self.runtime.mb.hq_card = mock.Mock(side_effect=AssertionError("irrelevant HQ scan"))
        with mock.patch.dict("sys.modules", {
                "apk_hud_adapter": types.SimpleNamespace(inspect_hud=lambda _: {"layout": "unknown"}),
                "apk_enemy_turn": types.SimpleNamespace(inspect_opponent_turn=lambda _: {"present": True})}):
            self.capture_at(1000)
        self.assertIsNone(self.runtime.last_info["state"])
        self.assertEqual(self.runtime.last_info["opponent_turn_label"], {"present": True})
        self.runtime.mb.hq_card.assert_not_called()
        self.runtime.end_turn_ledger.observe.assert_called_once()

    def test_unknown_result_requires_two_fresh_frames_and_original_span(self):
        self.capture_at(1000)
        self.assertFalse(self.runtime.report['result_verified'])
        self.capture_at(1299)
        self.assertFalse(self.runtime.report['result_verified'])
        with self.assertRaisesRegex(runtime.Stop,'^result_defeat$'):
            self.capture_at(1300)
        self.assertEqual([p['captured_elapsed_ms'] for p in self.calls],[1000,1299,1300])
        self.assertEqual(self.runtime.report['captures'],3)
        self.assertTrue(self.runtime.report['result_verified'])
        self.assertEqual(self.runtime.last_info['core_state'],None)

    def test_unknown_between_positive_frames_resets_result_gate(self):
        self.capture_at(1000)
        self.result_state = 'unknown'
        self.capture_at(1400)
        self.result_state = 'result_defeat'
        self.capture_at(1800)
        self.assertFalse(self.runtime.report['result_verified'])
        with self.assertRaisesRegex(runtime.Stop,'^result_defeat$'):
            self.capture_at(2100)

    def test_valid_battle_and_existing_core_result_skip_second_classifier(self):
        self.core_state = 'in_game'
        self.capture_at(1000)
        self.core_state = 'defeat'
        self.capture_at(1400)
        with self.assertRaisesRegex(runtime.Stop,'^result_defeat$'):
            self.capture_at(1800)
        self.assertEqual(self.calls,[])

    def test_menu_named_state_cannot_become_battle_result(self):
        self.result_state = 'disconnected'
        self.capture_at(1000)
        self.capture_at(1400)
        self.assertEqual(self.runtime.last_info['state'],None)
        self.assertFalse(self.runtime.report['result_verified'])

    def test_mismatched_capture_or_bridge_rejection_is_terminal(self):
        self.bridge.observeResult = lambda encoded: dict(json.loads(encoded),ok=True,
            state='result_defeat',captured_elapsed_ms=0)
        with self.assertRaisesRegex(runtime.Stop,'result_observation_capture_mismatch'):
            self.capture_at(1000)
        self.assertFalse(self.runtime.report['result_verified'])

    def test_late_observation_cannot_refresh_original_capture_timestamp(self):
        def late(encoded):
            observed = self.observe_result(encoded)
            self.time += 5001
            return observed
        self.bridge.observeResult = late
        with self.assertRaisesRegex(runtime.Stop,'result_observation_capture_expired'):
            self.capture_at(1000)
        self.assertEqual(self.calls[0]['captured_elapsed_ms'],1000)
        self.assertFalse(self.runtime.report['result_verified'])


class FakeBridge:
    def __init__(self, fixture, output):
        self.fixture, self.output = fixture, output
        self.index = 0
        self.dispatched = []
        self.events = []

    def elapsedRealtime(self):
        return int(time.monotonic() * 1000)

    def isCancelled(self):
        return False

    def capture(self):
        self.index += 1
        target = self.output / "frames" / (str(self.index) + ".png")
        target.parent.mkdir(parents=True, exist_ok=True)
        captured = self.elapsedRealtime()
        shutil.copyfile(self.fixture, target)
        return json.dumps({"frame_id": self.index, "captured_elapsed_ms": captured,
                           "source_width": 1920, "source_height": 1080,
                           "foreground_generation": 1, "png_path": str(target)})

    def dispatch(self, value):
        self.dispatched.append(json.loads(value))
        raise AssertionError("A read-only replay must never dispatch")

    def emit(self, value):
        self.events.append(json.loads(value))


class DispatchBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.time = 2000
        self.calls = []
        self.reply = {"accepted": False, "completed": False, "reason": "frame_age_expired"}
        self.bridge = types.SimpleNamespace(elapsedRealtime=lambda: self.time, isCancelled=lambda: False,
            emit=lambda event: None, dispatch=lambda request: (self.calls.append(json.loads(request)) or json.dumps(self.reply)))
        self.runtime = runtime.Runtime(self.bridge, self.temp.name, self.temp.name,
                                       runtime.options_from_json('{"read_only":false}'))
        self.runtime.context = "attack_hq"
        self.runtime.last_info = {"state": "in_game", "button": "white", "transition_reason": "",
            "choice_modal": False, "captured_elapsed_ms": 1000, "frame_id": 1,
            "source_width": 1920, "source_height": 1080, "foreground_generation": 1}
        self.runtime.last_info["hud_layout"] = "compact"
        self.runtime.engine = types.SimpleNamespace(_combat_decision_context={}, drop=(830, 430), turns_seen=1)
        self.gesture = {"kind": "drag", "from": [600, 475], "to": [600, 176], "duration_ms": 1000}

    def tearDown(self):
        self.runtime.events.close()
        self.temp.cleanup()

    def test_java_age_only_replans_without_counting_input(self):
        with self.assertRaises(runtime.Replan):
            self.runtime.dispatch(self.gesture)
        self.assertEqual(self.runtime.report["game_inputs"], 0)
        self.assertEqual(len(self.calls), 1)

    def test_package_refusal_is_not_confused_with_age(self):
        self.reply["reason"] = "package_changed"
        with self.assertRaises(runtime.Stop):
            self.runtime.dispatch(self.gesture)
        self.assertEqual(self.runtime.report["game_inputs"], 0)

    def test_accepted_incomplete_counts_and_never_replans(self):
        self.reply.update(accepted=True, reason="frame_age_expired")
        with self.assertRaises(runtime.Stop):
            self.runtime.dispatch(self.gesture)
        self.assertEqual(self.runtime.report["game_inputs"], 1)

    def test_gesture_completion_is_not_action_verification(self):
        self.reply.update(accepted=True, completed=True, reason="completed")
        self.runtime.dispatch(self.gesture)
        self.assertEqual(self.runtime.report["game_inputs"], 1)
        self.assertEqual(self.runtime.report["actions_confirmed"], 0)

    def test_bad_deployment_is_terminal_even_when_old(self):
        self.runtime.context = "deploy"
        self.runtime.mh = types.SimpleNamespace(find_hand=lambda *args, **kwargs: [])
        self.runtime.last_frame = object()
        self.time = 9000
        with self.assertRaises(runtime.Stop):
            self.runtime.dispatch(dict(self.gesture, **{"from": [600, 655]}))
        self.assertEqual(self.calls, [])

    def _prepare_deployment(self):
        self.gesture["duration_ms"] = 900
        old, fresh = object(), object()
        self.runtime.capture = mock.Mock(return_value=fresh)
        self.runtime.last_frame = fresh
        self.runtime.mb = types.SimpleNamespace(board_motion=lambda *args: 0, BOARD_MOTION_MAX=.008)
        unit = {"kind": "unit", "state": "orange", "cx": 465, "cy": 635}
        self.approved_unit = dict(unit, apk_grab_point=[489, 657],
                                 apk_availability={"allowed": True, "basis": "orange_unit_geometry_v1",
                                                   "cost": 1, "credits": 2})
        self.raw_hand_find = mock.Mock(return_value=[unit])
        self.runtime.mh = types.SimpleNamespace(find_hand=self.raw_hand_find,
                                                grab_point=lambda item, dy=22: (465, 635 + dy))
        self.runtime.install_hand_adapter()
        availability_patch = mock.patch("apk_hand_availability.filter_units", return_value={
            "units": [self.approved_unit], "checks": [], "credits": 2})
        self.availability_filter = availability_patch.start()
        self.addCleanup(availability_patch.stop)
        self.runtime.engine._deploy_real = mock.Mock(return_value=(True, "deployed"))
        return old, fresh

    def test_hand_limit_applies_after_affordability_filter(self):
        _, fresh = self._prepare_deployment()
        costly = {"kind": "unit", "state": "orange", "cx": 300, "cy": 635}
        self.raw_hand_find.return_value.insert(0, costly)
        units = self.runtime.mh.find_hand(fresh, units_only=True, max_units=1)
        self.assertEqual(units, [self.approved_unit])
        self.assertEqual(self.raw_hand_find.call_args.kwargs["max_units"], 0)
        self.assertEqual(len(self.availability_filter.call_args.args[1]), 2)

    def test_raw_hand_diagnostics_preserve_original_options(self):
        _, fresh = self._prepare_deployment()
        found = self.runtime.mh.find_hand(fresh, want="any", max_units=2)
        self.assertEqual(found, self.raw_hand_find.return_value)
        self.assertEqual(self.raw_hand_find.call_args.kwargs["max_units"], 2)
        self.availability_filter.assert_not_called()

    def test_hand_adapter_reinstall_does_not_wrap_old_session(self):
        _, fresh = self._prepare_deployment()
        self.runtime.install_hand_adapter()
        self.assertIs(self.runtime._core_find_hand, self.raw_hand_find)
        self.runtime.mh.find_hand(fresh, units_only=True)
        self.raw_hand_find.assert_called_once()
        self.availability_filter.assert_called_once()

    def test_unit_grab_uses_approved_interior_point_not_badge_vertical(self):
        self._prepare_deployment()
        self.assertEqual(self.runtime.mh.grab_point(self.approved_unit), (489, 657))
        invalid = dict(self.approved_unit, apk_grab_point=[float("nan"), 657])
        with self.assertRaisesRegex(runtime.Stop, "deployment_grab_point_not_approved"):
            self.runtime.mh.grab_point(invalid)

    def test_unknown_hand_eligibility_skips_deploy_without_pending_or_input(self):
        old, _ = self._prepare_deployment()
        self.availability_filter.return_value = {"units": [], "checks": [{"reason": "card_cost_unknown"}],
                                                 "credits": None}
        with mock.patch("apk_deploy_target.choose_drop") as choose:
            result = self.runtime.legacy_deploy(old)
        self.assertEqual(result, (False, "no_confirmed_affordable_unit_with_safe_grab"))
        choose.assert_not_called()
        self.runtime.engine._deploy_real.assert_not_called()
        self.assertEqual(self.calls, [])

    def test_dispatch_rechecks_same_frame_and_rejects_changed_resources(self):
        _, fresh = self._prepare_deployment()
        selected = self.runtime.mh.find_hand(fresh, units_only=True)
        self.assertEqual(len(selected), 1)
        self.availability_filter.return_value = {"units": [], "checks": [{"reason": "resources_unknown"}],
                                                 "credits": None}
        self.runtime.context = "deploy"
        gesture = dict(self.gesture, **{"from": [489, 657]})
        with self.assertRaisesRegex(runtime.Stop, "deployment_origin_not_unique_current_unit"):
            self.runtime.dispatch(gesture)
        self.assertIs(self.availability_filter.call_args.args[0], fresh)
        self.assertEqual(self.calls, [])

    def test_dispatch_rejects_old_badge_point_and_changed_safe_point(self):
        self._prepare_deployment()
        self.runtime.context = "deploy"
        for origin in ([465, 657], [488, 657]):
            with self.subTest(origin=origin), self.assertRaisesRegex(
                    runtime.Stop, "deployment_origin_not_unique_current_unit"):
                self.runtime.dispatch(dict(self.gesture, **{"from": origin}))
        self.approved_unit["apk_grab_point"] = [510, 657]
        with self.assertRaisesRegex(runtime.Stop, "deployment_origin_not_unique_current_unit"):
            self.runtime.dispatch(dict(self.gesture, **{"from": [489, 657]}))
        self.assertEqual(self.calls, [])

    def test_dispatch_rejects_duplicate_safe_origins(self):
        self._prepare_deployment()
        self.runtime.context = "deploy"
        self.availability_filter.return_value["units"].append(dict(self.approved_unit))
        with self.assertRaisesRegex(runtime.Stop, "deployment_origin_not_unique_current_unit"):
            self.runtime.dispatch(dict(self.gesture, **{"from": [489, 657]}))
        self.assertEqual(self.calls, [])

    def test_geometry_approval_does_not_require_numeric_diagnostics(self):
        self._prepare_deployment()
        for cost, credits in ((3, 2), (None, 2), (1, None), (None, None)):
            with self.subTest(cost=cost, credits=credits):
                self.approved_unit["apk_availability"].update(cost=cost, credits=credits)
                self.assertEqual(self.runtime.approved_grab_point(self.approved_unit), (489, 657))
        self.assertEqual(self.calls, [])

    def test_numeric_metadata_without_action_geometry_cannot_authorize(self):
        self._prepare_deployment()
        for updates in ({"apk_availability": {"allowed": True, "cost": 1, "credits": 2}},
                        {"kind": "order"}, {"state": "gray"},
                        {"apk_availability": {"allowed": False, "basis": "orange_unit_geometry_v1"}}):
            with self.subTest(updates=updates):
                self.assertIsNone(self.runtime.approved_grab_point(dict(self.approved_unit, **updates)))
        self.assertEqual(self.calls, [])

    def test_affordability_work_cannot_spend_frame_age_budget_then_dispatch(self):
        self._prepare_deployment()
        self.runtime.context = "deploy"
        self.runtime.engine.drop = (1000, 505)
        def delayed_filter(frame, units):
            self.time = 4500
            return {"units": [self.approved_unit], "checks": [], "credits": 2}
        self.availability_filter.side_effect = delayed_filter
        gesture = {"kind": "drag", "from": [489, 657], "to": [1000, 505], "duration_ms": 900}
        with mock.patch("apk_deploy_target.inspect_clear", return_value={"clear": True, "reason": "clear"}):
            with self.assertRaises(runtime.Replan):
                self.runtime.dispatch(gesture)
        self.assertEqual(self.calls, [])

    def test_dispatch_approved_candidate_rechecks_destination_then_sends_once(self):
        _, fresh = self._prepare_deployment()
        self.runtime.context = "deploy"
        self.runtime.engine.drop = (1000, 505)
        self.reply.update(accepted=True, completed=True)
        gesture = {"kind": "drag", "from": [489, 657], "to": [1000, 505], "duration_ms": 900}
        with mock.patch("apk_deploy_target.inspect_clear", return_value={"clear": True, "reason": "clear"}) as inspect:
            self.runtime.dispatch(gesture)
        inspect.assert_called_once_with(fresh, [1000, 505])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0]["from"], [489, 657])
        self.assertEqual(self.calls[0]["path_points"], [[489, 657], [489, 575], [1000, 505]])

    def test_dispatch_does_not_silently_replace_forged_deployment_path(self):
        self._prepare_deployment()
        self.runtime.context = "deploy"
        gesture = {"kind": "drag", "from": [489, 657], "to": [1000, 505], "duration_ms": 900,
                   "path_points": [[489, 657], [1000, 575], [1000, 505]]}
        with self.assertRaisesRegex(runtime.Stop, "invalid_deployment_path"):
            self.runtime.dispatch(gesture)
        self.assertEqual(self.calls, [])

    def test_deployment_resource_difference_is_diagnostic_not_identity_proof(self):
        self._prepare_deployment()
        self.runtime.engine.drop = (1000, 505)
        self.reply.update(accepted=True, completed=True)
        gesture = {"kind": "drag", "from": [489, 657], "to": [1000, 505], "duration_ms": 900}
        def deploy():
            self.runtime.dispatch(gesture)
            self.runtime.last_info = dict(self.runtime.last_info, frame_id=2)
            self.runtime.last_id = 2
            return True, "new_support_unit"
        with mock.patch("apk_deploy_target.inspect_clear", return_value={"clear": True, "reason": "clear"}), \
                mock.patch("apk_hud_adapter.inspect_kredits", return_value={"value": 0, "reason": "confirmed"}):
            self.runtime.wrap_hook("deploy", deploy)()
        audit = self.runtime.report["hooks"][-1]["deployment_cost_audit"]
        self.assertEqual((audit["expected_cost"], audit["observed_credit_decrease"]), (1, 2))
        self.assertFalse(audit["decrease_matches_expected_cost"])
        self.assertFalse(audit["selected_identity_verified"])
        self.assertTrue(self.runtime.report["hooks"][-1]["ok"])
        self.assertEqual(self.runtime.report["inputs"][-1]["deployment_plan"]["point"], [489, 657])

    def test_deployment_without_numbers_dispatches_and_skips_resource_ocr(self):
        self._prepare_deployment()
        self.approved_unit["apk_availability"].update(cost=None, credits=None)
        self.runtime.engine.drop = (1000, 505)
        self.reply.update(accepted=True, completed=True)
        gesture = {"kind": "drag", "from": [489, 657], "to": [1000, 505], "duration_ms": 900}
        def deploy():
            self.runtime.dispatch(gesture)
            self.runtime.last_info = dict(self.runtime.last_info, frame_id=2)
            self.runtime.last_id = 2
            return True, "new_support_unit"
        with mock.patch("apk_deploy_target.inspect_clear", return_value={"clear": True, "reason": "clear"}), \
                mock.patch("apk_hud_adapter.inspect_kredits", side_effect=AssertionError("numeric OCR is optional")) as ocr:
            self.runtime.wrap_hook("deploy", deploy)()
        ocr.assert_not_called()
        hook = self.runtime.report["hooks"][-1]
        self.assertTrue(hook["ok"])
        self.assertEqual(hook["deployment_cost_audit"]["status"], "optional_source_resources_unread")
        self.assertEqual(len(self.calls), 1)

    def test_dynamic_deployment_target_reaches_core_with_fresh_frame(self):
        old, fresh = self._prepare_deployment()
        target = {"point": [1000, 505], "reason": "clear_outer_support_slot", "evidence": {}}
        with mock.patch("apk_deploy_target.choose_drop", return_value=target) as choose:
            result = self.runtime.legacy_deploy(old)
        choose.assert_called_once_with(fresh)
        self.assertEqual(self.runtime.engine.drop, (1000, 505))
        self.runtime.engine._deploy_real.assert_called_once_with(fresh)
        self.assertEqual(result, (True, "deployed"))

    def _boundary_attempt(self):
        old, fresh = self._prepare_deployment()
        previous, current = object(), object()
        packets = self.runtime.report["inputs"]
        badge = dict(self.approved_unit)
        def capture():
            value = fresh if self.runtime.last_id < 2 else current
            self.runtime.last_id += 1
            self.runtime.last_frame = value
            self.runtime.last_info = dict(self.runtime.last_info, frame_id=self.runtime.last_id)
            return value
        def core_deploy(frame):
            self.runtime.report["game_inputs"] += 1
            packets.append({"request": {"from": [489, 657], "to": [1000, 505]},
                            "reply": {"accepted": True, "completed": True}})
            self.runtime.last_id = 2
            self.runtime.last_frame = previous
            self.runtime.last_info = dict(self.runtime.last_info, frame_id=2, state=None, button=None)
            self.runtime.mh._LAST_DEPLOY_ATTEMPT = {"before": fresh, "after": previous,
                "badge": badge, "target": (1000, 505), "input_sent": True}
            self.runtime._deployment_dispatched_source = fresh
            self.runtime.mh._LAST_DEPLOY_PENDING = "old_core_turn_boundary_failure"
            return False, "old_core_turn_boundary_failure"
        self.runtime.last_id = 0
        self.runtime.capture = mock.Mock(side_effect=capture)
        self.runtime.engine._deploy_real = mock.Mock(side_effect=core_deploy)
        return old, fresh, previous, current

    def test_deployment_boundary_evidence_updates_same_hook_without_replaying_input(self):
        old, fresh, previous, current = self._boundary_attempt()
        evidence = {"confirmed": True, "reason": "persistent_outer_unit_on_opponent_turn_pair",
                    "selected_identity_verified": False}
        with mock.patch("apk_deploy_target.choose_drop", return_value={"point": [1000, 505]}), \
                mock.patch("apk_enemy_turn.inspect_opponent_turn", return_value={"present": True}), \
                mock.patch("apk_deploy_verify.inspect_pair", return_value=evidence) as verify, \
                mock.patch.object(runtime.time, "sleep"), \
                mock.patch.object(self.runtime, "deployment_cost_audit", return_value={"diagnostic_only": True}):
            result = self.runtime.wrap_hook("deploy", self.runtime.legacy_deploy)(old)
        self.assertTrue(result[0])
        verify.assert_called_once_with(fresh, previous, current,
                                      self.runtime.mh._LAST_DEPLOY_ATTEMPT["badge"], (1000, 505))
        self.assertEqual(self.runtime.report["game_inputs"], 1)
        self.assertEqual(self.runtime.report["actions_confirmed"], 1)
        self.assertEqual(self.runtime.report["unconfirmed_inputs"], 0)
        self.assertEqual(self.runtime.capture.call_count, 2)
        self.assertIs(self.runtime.mh._LAST_DEPLOY_ATTEMPT["after"], current)
        self.assertIsNone(self.runtime.mh._LAST_DEPLOY_PENDING)
        self.assertTrue(self.runtime.report["hooks"][-1]["deployment_boundary_evidence"]["confirmed"])
        self.assertEqual(self.calls, [])

    def test_deployment_unknown_opponent_label_does_not_add_confirmation_captures(self):
        old, _, _, _ = self._boundary_attempt()
        with mock.patch("apk_deploy_target.choose_drop", return_value={"point": [1000, 505]}), \
                mock.patch("apk_enemy_turn.inspect_opponent_turn", return_value={"present": False}), \
                mock.patch("apk_deploy_verify.inspect_pair") as verify:
            result = self.runtime.legacy_deploy(old)
        self.assertFalse(result[0])
        verify.assert_not_called()
        self.assertEqual(self.runtime.capture.call_count, 1)

    def test_deployment_stale_core_attempt_cannot_confirm_current_input(self):
        old, _, _, _ = self._boundary_attempt()
        core_deploy = self.runtime.engine._deploy_real.side_effect
        def stale_attempt(frame):
            result = core_deploy(frame)
            self.runtime.mh._LAST_DEPLOY_ATTEMPT['before'] = object()
            return result
        self.runtime.engine._deploy_real.side_effect = stale_attempt
        with mock.patch("apk_deploy_target.choose_drop", return_value={"point": [1000, 505]}), \
                mock.patch("apk_deploy_verify.inspect_pair") as verify:
            result = self.runtime.legacy_deploy(old)
        self.assertFalse(result[0])
        verify.assert_not_called()
        self.assertEqual(self.runtime.capture.call_count, 1)

    def test_deployment_boundary_confirmation_is_bounded_and_preserves_failure(self):
        old, _, _, _ = self._boundary_attempt()
        with mock.patch("apk_deploy_target.choose_drop", return_value={"point": [1000, 505]}), \
                mock.patch("apk_enemy_turn.inspect_opponent_turn", return_value={"present": True}), \
                mock.patch("apk_deploy_verify.inspect_pair", return_value={"confirmed": False,
                    "reason": "support_pixels_still_moving"}) as verify, \
                mock.patch.object(runtime.time, "sleep"):
            result = self.runtime.legacy_deploy(old)
        self.assertFalse(result[0])
        self.assertEqual(self.runtime.capture.call_count, 4)
        self.assertEqual(verify.call_count, 3)
        self.assertEqual(self.runtime.report["game_inputs"], 1)
        self.assertEqual(self.runtime.mh._LAST_DEPLOY_PENDING, "old_core_turn_boundary_failure")

    def test_deployment_boundary_capture_stop_is_propagated_and_input_accounted(self):
        old, _, _, _ = self._boundary_attempt()
        original = self.runtime.capture.side_effect
        def stopped_capture():
            if self.runtime.last_id >= 2:
                raise runtime.Stop("foreground_changed")
            return original()
        self.runtime.capture.side_effect = stopped_capture
        with mock.patch("apk_deploy_target.choose_drop", return_value={"point": [1000, 505]}), \
                mock.patch("apk_enemy_turn.inspect_opponent_turn", return_value={"present": True}), \
                mock.patch.object(runtime.time, "sleep"), \
                mock.patch.object(self.runtime, "deployment_cost_audit", return_value={}):
            with self.assertRaisesRegex(runtime.Stop, "foreground_changed"):
                self.runtime.wrap_hook("deploy", self.runtime.legacy_deploy)(old)
        hook = self.runtime.report["hooks"][-1]
        self.assertTrue(hook["terminated"])
        self.assertFalse(hook["ok"])
        self.assertEqual(self.runtime.report["unconfirmed_inputs"], 1)
        self.assertEqual(self.runtime.report["game_inputs"], 1)

    def test_unknown_deployment_target_replans_without_calling_core(self):
        old, _ = self._prepare_deployment()
        target = {"point": None, "reason": "support_unit_evidence_incomplete", "evidence": {}}
        with mock.patch("apk_deploy_target.choose_drop", return_value=target):
            with self.assertRaisesRegex(runtime.Replan, "deployment_geometry_unknown"):
                self.runtime.legacy_deploy(old)
        self.runtime.engine._deploy_real.assert_not_called()
        self.assertEqual(self.runtime.engine.drop, (830, 430))
        self.assertEqual(self.calls, [])

    def test_full_support_row_skips_deployment_so_combat_can_continue(self):
        old, _ = self._prepare_deployment()
        reason = "no_confirmed_clear_outer_support_slot"
        with mock.patch("apk_deploy_target.choose_drop", return_value={"point": None, "reason": reason}):
            result = self.runtime.legacy_deploy(old)
        self.assertEqual(result, (False, reason))
        self.runtime.engine._deploy_real.assert_not_called()
        self.assertEqual(self.calls, [])

    def test_deployment_target_rechecked_before_dispatch_even_when_frame_is_old(self):
        self._prepare_deployment()
        self.runtime.context = "deploy"
        self.runtime.engine.drop = (1000, 505)
        gesture = {"kind": "drag", "from": [489, 657], "to": [1000, 505], "duration_ms": 900}
        for now in (2000, 9000):
            for reason in ("occupied", "support_unit_evidence_incomplete"):
                self.time = now
                with self.subTest(now=now, reason=reason):
                    with mock.patch("apk_deploy_target.inspect_clear", return_value={"clear": False, "reason": reason}) as inspect:
                        with self.assertRaisesRegex(runtime.Stop, "deployment_destination_not_clear:" + reason):
                            self.runtime.dispatch(gesture)
                    inspect.assert_called_once_with(self.runtime.last_frame, [1000, 505])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.runtime.report["game_inputs"], 0)

    def test_only_first_capture_can_wait_for_game(self):
        self.runtime.last_id = 2
        self.bridge.capture = lambda: json.dumps({"ok": False, "reason": "waiting_for_new_game_foreground"})
        with mock.patch.object(runtime.time, "sleep") as sleep, self.assertRaises(runtime.Stop):
            self.runtime.capture()
        sleep.assert_not_called()

    def test_initial_wait_does_not_hide_other_foreground_refusal(self):
        packets = iter([{"ok": False, "reason": "waiting_for_new_game_foreground"},
                        {"ok": False, "reason": "foreground_changed"}])
        self.bridge.capture = lambda: json.dumps(next(packets))
        with mock.patch.object(runtime.time, "sleep") as sleep, self.assertRaisesRegex(runtime.Stop, "foreground_changed"):
            self.runtime.capture()
        sleep.assert_called_once_with(.2)

    def test_accepted_hook_stopping_in_verification_is_recorded(self):
        self.reply.update(accepted=True, completed=True, reason="completed")
        def hook():
            self.runtime.dispatch(self.gesture)
            raise runtime.Stop("capture_rejected:cancelled_after_input")
        with self.assertRaisesRegex(runtime.Stop, "cancelled_after_input"):
            self.runtime.wrap_hook("attack_hq", hook)()
        report = self.runtime.report
        self.assertEqual((report["game_inputs"], report["unconfirmed_inputs"], report["failed_inputs"]), (1, 1, 1))
        self.assertEqual(len(report["hooks"]), 1)
        self.assertTrue(report["hooks"][0]["terminated"])
        self.assertFalse(report["hooks"][0]["ok"])
        self.assertEqual(report["hooks"][0]["exception_type"], "Stop")

    def test_failed_gesture_completion_is_recorded_in_hook(self):
        self.reply.update(accepted=True, completed=False, reason="gesture_cancelled")
        with self.assertRaisesRegex(runtime.Stop, "gesture_not_completed"):
            self.runtime.wrap_hook("attack_hq", lambda: self.runtime.dispatch(self.gesture))()
        self.assertEqual(self.runtime.report["unconfirmed_inputs"], 1)
        self.assertEqual(self.runtime.report["hooks"][0]["inputs"], 1)

    def test_exception_after_input_preserves_count_and_original_error(self):
        self.reply.update(accepted=True, completed=True, reason="completed")
        def hook():
            self.runtime.dispatch(self.gesture)
            raise ValueError("recognition_error")
        with self.assertRaisesRegex(ValueError, "recognition_error"):
            self.runtime.wrap_hook("attack_hq", hook)()
        self.assertEqual(self.runtime.report["unconfirmed_inputs"], 1)
        self.assertEqual(self.runtime.report["hooks"][0]["exception_type"], "ValueError")

    def test_later_confirmed_action_does_not_erase_cumulative_failure(self):
        self.runtime.options["max_inputs"] = 3
        self.runtime.options["max_failed_inputs"] = 2
        self.reply.update(accepted=True, completed=True, reason="completed")
        def failed():
            self.runtime.dispatch(self.gesture)
            return False, "no_outcome"
        def succeeded():
            self.runtime.dispatch(self.gesture)
            return True, "hq_hp_decreased"
        self.runtime.wrap_hook("attack_hq", failed)()
        self.runtime.wrap_hook("attack_hq", succeeded)()
        report = self.runtime.report
        self.assertEqual((report["game_inputs"], report["unconfirmed_inputs"], report["failed_inputs"],
                          report["actions_confirmed"]), (2, 1, 0, 1))

    def test_completed_unconfirmed_combat_is_skipped_without_terminal_failure_budget(self):
        self.runtime.options["max_inputs"] = 4
        self.reply.update(accepted=True, completed=True, reason="completed")
        for kind in ("attack_hq", "attack_unit", "move_front"):
            def hook():
                self.runtime.dispatch(self.gesture)
                return False, "visual_outcome_unknown"
            self.runtime.wrap_hook(kind, hook)()
            self.assertEqual(self.runtime.report["hooks"][-1]["verification"], "unconfirmed_skipped")
        self.assertEqual(self.runtime.failed_inputs, 0)
        self.assertEqual(self.runtime.report["unconfirmed_skipped"], 3)
        self.assertEqual(self.runtime.report["unconfirmed_inputs"], 3)
        self.assertEqual(self.runtime.report["actions_confirmed"], 0)

    def test_actor_death_confirmation_and_temporary_loss_keep_distinct_cumulative_ledgers(self):
        self.runtime.options["max_inputs"] = 3
        self.reply.update(accepted=True, completed=True, reason="completed")
        evidence = {"actor_removed": True, "actor_removed_streak": 2}
        self.runtime.ma = types.SimpleNamespace(_LAST_ATTEMPT=None)
        def attack(ok):
            self.runtime.dispatch(self.gesture)
            self.runtime.ma._LAST_ATTEMPT = {"kind": "attack_unit", "simple_combat_evidence": evidence}
            return ok, "settled_row_death" if ok else "temporary_loss_without_confirmation"
        self.runtime.wrap_hook("attack_unit", lambda:attack(False))()
        evidence["actor_removed_streak"] = 3
        self.runtime.wrap_hook("attack_unit", lambda:attack(True))()
        report = self.runtime.report
        self.assertEqual([h["verification"] for h in report["hooks"]], ["unconfirmed_skipped", "confirmed"])
        self.assertEqual([h["combat_evidence"]["actor_removed_streak"] for h in report["hooks"]], [2, 3])
        self.assertEqual((report["game_inputs"], report["actions_confirmed"], report["unconfirmed_inputs"],
                          report["unconfirmed_skipped"], report["failed_inputs"]), (2, 1, 1, 1, 0))

    def test_no_completion_proof_cannot_be_marked_skipped(self):
        def hook():
            self.runtime.report["game_inputs"] += 1
            return False, "no_dispatch_proof"
        self.runtime.wrap_hook("attack_hq", hook)()
        self.assertEqual(self.runtime.report["hooks"][-1]["verification"], "unconfirmed")
        self.assertEqual(self.runtime.failed_inputs, 1)
        self.assertEqual(self.runtime.report["unconfirmed_skipped"], 0)

    def test_prior_rejected_packet_does_not_corrupt_completed_skip_accounting(self):
        self.runtime.report["inputs"].append({"reply": {"accepted": False, "completed": False}})
        self.reply.update(accepted=True, completed=True, reason="completed")
        def hook():
            self.runtime.dispatch(self.gesture)
            return False, "visual_outcome_unknown"
        self.runtime.wrap_hook("move_front", hook)()
        self.assertEqual(self.runtime.report["unconfirmed_skipped"], 1)

    def test_normal_end_turn_returns_true_but_audit_is_pending(self):
        def hook():
            self.runtime.report["game_inputs"] += 1
            return True
        result = self.runtime.wrap_hook("end_turn", hook)()
        self.assertTrue(result)
        item = self.runtime.report["hooks"][0]
        self.assertEqual(item["verification"], "pending_transition")
        self.assertFalse(item["ok"])
        self.assertTrue(item["hook_returned_ok"])
        self.assertEqual(self.runtime.report["actions_confirmed"], 0)
        self.assertEqual(self.runtime.report["unconfirmed_inputs"], 0)
        self.assertEqual(self.runtime.report["pending_end_turn_inputs"], 1)

    def test_rejected_input_does_not_become_unconfirmed(self):
        with self.assertRaises(runtime.Replan):
            self.runtime.wrap_hook("attack_hq", lambda: self.runtime.dispatch(self.gesture))()
        self.assertEqual(self.runtime.report["unconfirmed_inputs"], 0)
        self.assertEqual(self.runtime.report["hooks"][0]["verification"], "no_input")

    def test_campaign_deadline_preserves_eight_second_verification_budget(self):
        self.runtime.events.close()
        self.bridge.deadlineElapsedRealtime = lambda: 8500
        self.runtime = runtime.Runtime(self.bridge, self.temp.name, Path(self.temp.name) / "campaign",
                                       runtime.options_from_json('{"read_only":false,"max_seconds":120}'))
        self.assertEqual(self.runtime.deadline, 8500)
        invoked = []
        with self.assertRaisesRegex(runtime.Stop, "time_budget_before_hook"):
            self.runtime.wrap_hook("attack_hq", lambda: invoked.append(True))()
        self.assertEqual(invoked, [])
        self.assertEqual(self.runtime.report["game_inputs"], 0)

    def test_campaign_deadline_cannot_extend_options_budget(self):
        self.runtime.events.close()
        self.bridge.deadlineElapsedRealtime = lambda: 999999
        self.runtime = runtime.Runtime(self.bridge, self.temp.name, Path(self.temp.name) / "campaign",
                                       runtime.options_from_json('{"max_seconds":20}'))
        self.assertEqual(self.runtime.deadline, 22000)

    def test_missing_campaign_api_preserves_fake_bridge_options(self):
        self.assertEqual(self.runtime.deadline, self.time + 120000)

    def test_end_turn_later_frames_resolve_pending_without_changing_tap_ok(self):
        def hook():
            self.runtime.report["game_inputs"] += 1
            return True
        self.runtime.wrap_hook("end_turn", hook)()
        for fid, captured in ((2, 2500), (3, 3600)):
            self.time = captured
            info = dict(self.runtime.last_info, frame_id=fid, captured_elapsed_ms=captured,
                        button=None, button_present=False,
                        opponent_turn_label={"present": True, "score": .99, "box": [1130, 447, 124, 33]},
                        state=None, frontline={"owner": "empty"}, our_hq={}, enemy_hq={})
            self.runtime._settle_end_turns(self.runtime.end_turn_ledger.observe(info, captured, 1, 0))
        report = self.runtime.report
        self.assertEqual((report["pending_end_turn_inputs"], report["end_turns_confirmed"],
                          report["unconfirmed_inputs"], report["actions_confirmed"]), (0, 1, 0, 0))
        self.assertFalse(report["hooks"][0]["ok"])
        self.assertEqual(report["hooks"][0]["verification"], "pending_transition")
        self.assertEqual(report["hooks"][0]["final_verification"], "confirmed")

    def test_stopping_with_pending_end_turn_records_unconfirmed_once(self):
        def hook():
            self.runtime.report["game_inputs"] += 1
            return True
        self.runtime.wrap_hook("end_turn", hook)()
        self.runtime._settle_end_turns(self.runtime.end_turn_ledger.finalize(2500, "cancelled"))
        self.runtime._settle_end_turns(self.runtime.end_turn_ledger.finalize(2600, "cancelled"))
        report = self.runtime.report
        self.assertEqual((report["pending_end_turn_inputs"], report["end_turns_unconfirmed"],
                          report["unconfirmed_inputs"], report["failed_inputs"]), (0, 1, 1, 1))

    def test_end_turn_timeout_during_capture_blocks_next_dispatch(self):
        self.runtime.options["max_inputs"] = 20
        def hook():
            self.runtime.report["game_inputs"] += 1
            return True
        self.runtime.wrap_hook("end_turn", hook)()
        self.time = 32000
        info = dict(self.runtime.last_info, frame_id=2, captured_elapsed_ms=self.time)
        self.runtime._settle_end_turns(self.runtime.end_turn_ledger.observe(info, self.time, 1, 0))
        self.runtime.last_info = info
        self.runtime.context = "attack_hq"
        self.reply.update(accepted=True, completed=True)
        with self.assertRaisesRegex(runtime.Replan, "awaiting_next_turn_after_end_turn_failure"):
            self.runtime.dispatch(self.gesture)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.runtime.report["game_inputs"], 1)
        self.assertEqual(self.runtime.report["end_turns_unconfirmed"], 1)
        self.assertEqual(self.runtime.failed_inputs, 1)

    def test_pending_end_turn_blocks_all_new_inputs_without_superseding_it(self):
        self.runtime.options["max_inputs"] = 20
        def hook():
            self.runtime.report["game_inputs"] += 1
            return True
        self.runtime.wrap_hook("end_turn", hook)()
        pending = self.runtime.end_turn_ledger.pending
        for context in ("end_turn", "deploy", "move_front", "attack_hq", "attack_unit"):
            self.runtime.context = context
            with self.subTest(context=context), self.assertRaisesRegex(
                    runtime.Replan, "awaiting_previous_end_turn_confirmation"):
                self.runtime.dispatch(self.gesture)
        self.assertEqual(self.calls, [])
        self.assertIs(self.runtime.end_turn_ledger.pending, pending)
        self.assertEqual(self.runtime.report["game_inputs"], 1)
        self.assertEqual(self.runtime.report["unconfirmed_inputs"], 0)

    def test_confirmed_end_turn_releases_next_fresh_input(self):
        self.runtime.options["max_inputs"] = 20
        def hook():
            self.runtime.report["game_inputs"] += 1
            return True
        self.runtime.wrap_hook("end_turn", hook)()
        for fid, captured in ((2, 2500), (3, 3600)):
            info = dict(self.runtime.last_info, frame_id=fid, captured_elapsed_ms=captured,
                        button=None, button_present=False, state=None,
                        opponent_turn_label={"present": True, "box": [1130, 447, 124, 33]},
                        frontline={"owner": "empty"}, our_hq={}, enemy_hq={})
            self.runtime._settle_end_turns(self.runtime.end_turn_ledger.observe(info, captured, 1, 0))
        self.assertIsNone(self.runtime.end_turn_ledger.pending)
        self.runtime.last_info.update(frame_id=4, captured_elapsed_ms=4000)
        self.time = 4100
        self.runtime.context = "attack_hq"
        self.reply.update(accepted=True, completed=True)
        self.runtime.dispatch(self.gesture)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.runtime.report["game_inputs"], 2)
        self.assertEqual(self.runtime.report["end_turns_confirmed"], 1)

    def test_end_turn_at_input_budget_uses_readonly_tail_not_another_think(self):
        def hook():
            self.runtime.report["game_inputs"] += 1
            return True
        self.runtime.wrap_hook("end_turn", hook)()
        captures = []
        def capture():
            self.time += 600
            captures.append(self.time)
            info = dict(self.runtime.last_info, frame_id=1 + len(captures), captured_elapsed_ms=self.time,
                        button=None, button_present=False,
                        opponent_turn_label={"present": True, "score": .99, "box": [1130, 447, 124, 33]},
                        state=None, frontline={"owner": "empty"}, our_hq={}, enemy_hq={})
            self.runtime._settle_end_turns(self.runtime.end_turn_ledger.observe(info, self.time, 1, 0))
        self.runtime.capture = capture
        with mock.patch.object(runtime.time, "sleep"):
            self.runtime._observe_budget_tail()
        self.assertEqual(len(captures), 3)
        self.assertEqual(self.runtime.report["game_inputs"], 1)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.runtime.report["end_turns_confirmed"], 1)


def replay_saved_fixture(core_root, fixture, output):
    bridge = FakeBridge(Path(fixture), Path(output))
    result = json.loads(runtime.run(bridge, core_root, output, '{"read_only":true}'))
    assert not bridge.dispatched and result["game_inputs"] == 0, result
    assert result["stop_reason"] == "inspection_complete", result
    inspection = [event["value"] for event in bridge.events if event["kind"] == "inspection"]
    captures = [event["value"] for event in bridge.events if event["kind"] == "capture"]
    return {"summary": result, "inspection": inspection[0] if inspection else None,
            "observation": captures[-1] if captures else None}


def replay_saved_fixture_json(core_root, fixture, output):
    return runtime._json(replay_saved_fixture(core_root, fixture, output))


def inspect_fixture_hand_json(fixture, hand_json):
    """Check the APK veto on core-classified saved pixels; no capture or dispatch."""
    import cv2
    import apk_hand_availability
    frame = cv2.imread(str(fixture))
    if frame is None:
        raise ValueError("missing_hand_fixture")
    if frame.shape[:2] != (720, 1280):
        frame = cv2.resize(frame, (1280, 720), interpolation=cv2.INTER_LINEAR)
    candidates = [item for item in json.loads(hand_json)
                  if item.get("kind") == "unit" and item.get("state") == "orange"]
    # Historical fixtures also check diagnostic OCR. Live approval uses the
    # default numeric_diagnostics=False and is identical with unknown numbers.
    return runtime._json(apk_hand_availability.filter_units(frame, candidates, numeric_diagnostics=True))


def self_check(core_root=None):
    """Fake I/O checks; device pixel helpers come from the verified core root."""
    import io
    if core_root is not None:
        # Java verifies the immutable core manifest and every source before
        # supplying this path. This only exposes pure pixel helper imports.
        core_source = str(Path(core_root) / "src")
        if not Path(core_source, "mobile_board.py").is_file():
            raise ValueError("pixel_test_core_not_prepared")
        import sys
        if core_source not in sys.path:
            sys.path.insert(0, core_source)
    from apk_direct_drag_test import DirectDragTests
    from apk_deploy_target_test import ProfileSelectionTests as DeployProfileSelectionTests
    from apk_deploy_target_test import SurfaceTests as DeploySurfaceTests
    from apk_deploy_verify_test import DeployBoundaryTests
    from apk_end_turn_ledger_test import EndTurnLedgerTests
    from apk_enemy_turn_test import OpponentTurnLabelTests
    from apk_hand_availability_test import HandAvailabilityTests
    from apk_hq_adapter_test import HqAdapterTests
    from apk_hq_geometry_test import HqGeometryTests
    from apk_settle_test import SettlementTests
    from apk_settle_test import ReturnToStartTests
    from apk_settle_test import SettleThenReturnTests
    from apk_settle_test import FrameReadingTests
    from apk_simple_combat_test import SimpleCombatTests, AttackSampleTests
    from apk_simple_deploy_test import SimpleDeployTests, SimpleDeployRuntimeTests, TypeSamplingRegressionTests
    from apk_board_artwork_test import ArtworkFilterTests
    from apk_current_capture_memo_test import CurrentCaptureMemoTests, RuntimeCaptureMemoTests
    from apk_reward_wait_test import RewardWaitTests
    from apk_hq_row_split_test import HqRowSplitterTests
    from apk_green_stat_test import GreenStatTests
    from apk_green_stat_integration_test import GreenStatRuntimeTests
    from apk_scene_entry_test import SceneEntryTests, TargetRemovalFragmentTests, SingleTypeSupportTests
    suite = unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(cls)
                               for cls in (DirectDragTests, GuardTests, DispatchBridgeTests, SameFrameHandCacheTests, ResultCaptureTests, EndTurnLedgerTests,
                                           OpponentTurnLabelTests, HandAvailabilityTests, HqAdapterTests,
                                           HqGeometryTests, SimpleCombatTests, AttackSampleTests, SimpleDeployTests, SimpleDeployRuntimeTests, TypeSamplingRegressionTests,
                                           ArtworkFilterTests, CurrentCaptureMemoTests, RuntimeCaptureMemoTests, RewardWaitTests, HqRowSplitterTests, GreenStatTests, GreenStatRuntimeTests,
                                           DeploySurfaceTests, DeployProfileSelectionTests, DeployBoundaryTests,
                                           SettlementTests, ReturnToStartTests, SettleThenReturnTests,
                                           FrameReadingTests, SceneEntryTests, TargetRemovalFragmentTests, SingleTypeSupportTests)])
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    return json.dumps({"passed": result.wasSuccessful(), "tests_run": result.testsRun,
                       "failures": len(result.failures), "errors": len(result.errors),
                       "device_inputs": 0, "log": stream.getvalue()})


if __name__ == "__main__":
    unittest.main()
