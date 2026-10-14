"""Exact-capture recognition boundaries; fake I/O and no Android operations."""
from pathlib import Path
import json
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import numpy as np

from apk_current_capture_memo import CurrentCaptureMemo, FIELDS, NAMES, configuration_epoch


class CurrentCaptureMemoTests(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((720, 1280, 3), np.uint8)
        self.info = dict(frame_id=1, captured_elapsed_ms=1000,
                         foreground_generation=2, source_width=1920, source_height=1080)
        self.calls = {name: 0 for name in NAMES}
        self.module = types.ModuleType("fake_board")
        self.module.LIMITS = {"minimum": .93}
        for name in NAMES:
            def original(frame, _name=name):
                self.calls[_name] += 1
                return {"name": _name, "pixels": None if frame is None else int(frame.sum()),
                        "evidence": {"items": [1, 2]}}
            setattr(self.module, name, original)
        self.originals = {name: getattr(self.module, name) for name in NAMES}
        self.enabled = True
        self.memo = CurrentCaptureMemo(self.originals, session_epoch=object(),
            config_epoch=lambda: configuration_epoch([self.module]), eligible=lambda: self.enabled)
        self.memo.bind(self.module)
        self.memo.register(self.frame, self.info)

    def tearDown(self):
        self.memo.uninstall()

    def test_nested_default_recognizers_compute_once_and_copy_results(self):
        for name in NAMES:
            first = getattr(self.module, name)(self.frame)
            first["evidence"]["items"].append(99)
            again = getattr(self.module, name)(self.frame)
            self.assertEqual(again["evidence"]["items"], [1, 2])
            self.assertEqual(self.calls[name], 1)
            self.assertEqual(self.memo.hits[name], 1)
        self.assertEqual(self.info["captured_elapsed_ms"], 1000)

    def test_each_metadata_mutation_taints_even_after_restoration(self):
        for field in FIELDS:
            with self.subTest(field=field):
                self.memo.register(self.frame, self.info)
                self.module.frontline_state(self.frame)
                before = self.calls["frontline_state"]
                self.info[field] += 1
                self.module.frontline_state(self.frame)
                self.info[field] -= 1
                self.module.frontline_state(self.frame)
                self.assertEqual(self.calls["frontline_state"], before + 2)
                self.assertIsNone(self.memo.initial)

    def test_pixel_mutation_and_restoration_cannot_reenable_old_memo(self):
        self.module.frontline_state(self.frame)
        self.frame[0, 0, 0] = 1
        self.assertEqual(self.module.frontline_state(self.frame)["pixels"], 1)
        self.frame[0, 0, 0] = 0
        self.module.frontline_state(self.frame)
        self.assertEqual(self.calls["frontline_state"], 3)

    def test_same_pixels_new_capture_and_old_capture_never_hit(self):
        self.module.frontline_state(self.frame)
        old = self.frame
        self.frame = old.copy()
        self.memo.register(self.frame, dict(self.info))
        self.module.frontline_state(self.frame)
        self.module.frontline_state(old)
        self.assertEqual(self.calls["frontline_state"], 3)
        self.memo.register(self.frame, dict(self.info))
        self.module.frontline_state(self.frame)
        self.assertEqual(self.calls["frontline_state"], 4)

    def test_configuration_change_and_restoration_clear_older_results(self):
        self.module.frontline_state(self.frame)
        self.module.LIMITS["minimum"] = .94
        self.module.frontline_state(self.frame)
        self.module.LIMITS["minimum"] = .93
        self.module.frontline_state(self.frame)
        self.assertEqual(self.calls["frontline_state"], 3)

    def test_callback_change_and_session_change_miss(self):
        self.module.frontline_state(self.frame)
        def replacement(frame):
            return {"replacement": True}
        self.memo.originals["frontline_state"] = replacement
        self.assertEqual(self.module.frontline_state(self.frame), {"replacement": True})
        self.assertEqual(self.memo.hits["frontline_state"], 0)
        self.memo.originals["frontline_state"] = self.originals["frontline_state"]
        self.module.frontline_state(self.frame)
        self.memo.session_epoch = object()
        self.module.frontline_state(self.frame)
        self.assertEqual(self.calls["frontline_state"], 3)

    def test_cancel_or_deadline_eligibility_clears_and_uses_original(self):
        self.module.frontline_state(self.frame)
        self.enabled = False
        self.module.frontline_state(self.frame)
        self.assertIsNone(self.memo.capture)
        self.enabled = True
        self.module.frontline_state(self.frame)
        self.assertEqual(self.calls["frontline_state"], 3)

    def test_busy_artwork_proof_bypasses_hits_and_never_populates(self):
        self.module.frontline_state(self.frame)
        self.module._apk_artwork_filter_busy = True
        self.module.frontline_state(self.frame)
        self.module.board_transition_reason(self.frame)
        self.module.board_transition_reason(self.frame)
        self.assertEqual(self.memo.hits["frontline_state"], 0)
        self.assertEqual(self.calls["board_transition_reason"], 2)
        self.module._apk_artwork_filter_busy = False
        self.module.frontline_state(self.frame)
        self.module.board_transition_reason(self.frame)
        self.assertEqual(self.memo.hits["frontline_state"], 1)
        self.assertEqual(self.calls["board_transition_reason"], 3)

    def test_cancellation_during_original_recognition_cannot_populate(self):
        original = self.memo.originals["frontline_state"]
        def cancelling(frame):
            self.enabled = False
            return original(frame)
        self.memo.originals["frontline_state"] = cancelling
        self.module.frontline_state(self.frame)
        self.assertFalse(self.memo.memo)
        self.assertIsNone(self.memo.capture)

    def test_either_proof_phase_started_during_recognition_cannot_populate(self):
        original = self.originals["frontline_state"]
        for flag in ("_apk_artwork_filter_busy", "_apk_hq_row_split_busy"):
            self.memo.register(self.frame, self.info)
            def starting_phase(frame):
                setattr(self.module, flag, True)
                return original(frame)
            self.memo.originals["frontline_state"] = starting_phase
            self.module.frontline_state(self.frame)
            self.assertFalse(self.memo.memo)
            setattr(self.module, flag, False)

    def test_invalid_frame_metadata_or_unknown_configuration_never_hits(self):
        cases = [None, self.frame[:710], self.frame[:, ::-1], self.frame.astype(np.float32)]
        for frame in cases:
            with self.subTest(shape=getattr(frame, "shape", None)):
                self.memo.register(frame, self.info)
                before = self.calls["frontline_state"]
                self.module.frontline_state(frame)
                self.module.frontline_state(frame)
                self.assertEqual(self.calls["frontline_state"], before + 2)
        for changed in ({"frame_id": True}, {"source_height": 0}, {"foreground_generation": -1}):
            self.memo.register(self.frame, dict(self.info, **changed))
            before = self.calls["frontline_state"]
            self.module.frontline_state(self.frame)
            self.module.frontline_state(self.frame)
            self.assertEqual(self.calls["frontline_state"], before + 2)
        self.memo.register(self.frame, self.info)
        self.module.UNKNOWN_CONFIG = object()
        self.module.frontline_state(self.frame)
        self.module.frontline_state(self.frame)
        self.assertEqual(self.memo.hits["frontline_state"], 0)

    def test_extra_parameters_preserve_original_exception_and_clear(self):
        for name in NAMES:
            self.memo.register(self.frame, self.info)
            with self.assertRaises(TypeError):
                getattr(self.module, name)(self.frame, debug=True)
            self.assertIsNone(self.memo.capture)
            self.assertFalse(self.memo.memo)

    def test_original_exception_does_not_get_cached(self):
        def fail(frame):
            raise RuntimeError("original_failure")
        self.memo.originals["frontline_state"] = fail
        with self.assertRaisesRegex(RuntimeError, "original_failure"):
            self.module.frontline_state(self.frame)
        self.assertIsNone(self.memo.capture)

    def test_uninstall_restores_callbacks_and_next_session_cannot_stack(self):
        self.module.frontline_state(self.frame)
        next_memo = CurrentCaptureMemo(self.originals, session_epoch=object(), config_epoch=1)
        next_memo.bind(self.module)
        self.assertIsNone(self.memo.capture)
        self.assertIsNone(self.memo.module)
        self.assertIs(next_memo.originals["frontline_state"], self.originals["frontline_state"])
        next_memo.uninstall()
        for name in NAMES:
            self.assertIs(getattr(self.module, name), self.originals[name])


class RuntimeCaptureMemoTests(unittest.TestCase):
    def make_runtime(self, out):
        import apk_battle_runtime as runtime
        bridge = types.SimpleNamespace(elapsedRealtime=lambda: 1000, isCancelled=lambda: False,
                                       emit=lambda value: None)
        instance = runtime.Runtime(bridge, out, out, runtime.options_from_json("{}"))
        instance._board_cache = types.SimpleNamespace(clear=Mock(), register=Mock())
        instance.artwork_filter = types.SimpleNamespace(clear=Mock(), register=Mock())
        return instance

    def test_registration_uses_actual_capture_info_and_artwork_goes_first(self):
        import apk_battle_runtime as runtime
        with tempfile.TemporaryDirectory() as out:
            instance = self.make_runtime(out)
            calls = []
            instance.artwork_filter.register = lambda f, i: calls.append(("artwork", f, i))
            instance._board_cache.register = lambda f, i: calls.append(("memo", f, i))
            frame, info = object(), {"frame_id": 2}
            instance._register_board_capture(frame, info)
            self.assertEqual([c[0] for c in calls], ["artwork", "memo"])
            self.assertTrue(all(c[1] is frame and c[2] is info for c in calls))
            instance.events.close()

    def test_failed_capture_clears_both_caches_and_stable_seed(self):
        import apk_battle_runtime as runtime
        with tempfile.TemporaryDirectory() as out:
            instance = self.make_runtime(out)
            instance._stable_seed = {"frame": object()}
            def capture_failure():
                raise runtime.Stop("capture_rejected:foreground_changed")
            instance._capture_frame = capture_failure
            with self.assertRaises(runtime.Stop):
                instance.capture()
            instance._board_cache.clear.assert_called_once()
            instance.artwork_filter.clear.assert_called_once()
            self.assertIsNone(instance._stable_seed)
            instance.events.close()

    def test_cancel_and_deadline_clear_before_terminal_refusal(self):
        import apk_battle_runtime as runtime
        for reason in ("cancelled", "time_budget"):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as out:
                instance = self.make_runtime(out)
                if reason == "cancelled":
                    instance.bridge.isCancelled = lambda: True
                else:
                    instance.deadline = 1000
                with self.assertRaisesRegex(runtime.Stop, reason):
                    instance.check_running()
                instance._board_cache.clear.assert_called_once()
                instance.artwork_filter.clear.assert_called_once()
                instance.events.close()

    def test_uninstalled_diagnostic_runtime_still_supports_clear_and_register(self):
        import apk_battle_runtime as runtime
        stub = types.SimpleNamespace()
        runtime.Runtime._clear_board_cache(stub)
        runtime.Runtime._register_board_capture(stub, object(), {})

    def test_actual_capture_registers_new_frame_before_board_calls(self):
        import cv2
        import apk_battle_runtime as runtime
        with tempfile.TemporaryDirectory() as out:
            instance = self.make_runtime(out)
            path = Path(out) / "capture.png"
            cv2.imwrite(str(path), np.ones((720, 1280, 3), np.uint8))
            current = [1]
            instance.bridge.capture = lambda: dict(frame_id=current[0], captured_elapsed_ms=1000,
                foreground_generation=2, source_width=1920, source_height=1080, png_path=str(path))
            instance.cv2, instance.np = cv2, np
            instance.ui = types.SimpleNamespace(classify=lambda *a: ("in_game", {}))
            instance.templates, instance.states = {}, {}
            instance.end_button = types.SimpleNamespace(inspect_end_button=lambda *a, **k:
                dict(state="white", box=[1100, 300, 100, 70], score=1, present=True, reason="present"))
            board = types.ModuleType("runtime_fake_board")
            board.us, board.hq_hp = types.ModuleType("fake_us"), types.ModuleType("fake_hp")
            board.END_TURN_MIN, board.BOARD_MOTION_MAX = .82, .008
            counts = {name: 0 for name in NAMES}
            def transition(frame):
                self.assertIs(instance._board_cache.capture, frame)
                self.assertEqual(instance._board_cache.info["frame_id"], current[0])
                counts["board_transition_reason"] += 1
                return ""
            def frontline(frame):
                counts["frontline_state"] += 1
                self.assertEqual(board.board_transition_reason(frame), "")
                return {"owner": "empty"}
            board.board_transition_reason, board.frontline_state = transition, frontline
            board.choice_modal, board.board_motion = lambda f: (False, ""), lambda a, b: 0
            instance.mb = board
            instance.choice_gate = runtime.ChoiceModalGate(.008)
            instance._install_board_cache()
            try:
                frame = instance.capture()
                self.assertIs(instance._board_cache.info, instance.last_info)
                board.board_transition_reason(frame)
                board.frontline_state(frame)
                self.assertEqual(counts, {name: 1 for name in NAMES})
                self.assertEqual(instance.last_info["captured_elapsed_ms"], 1000)
                current[0] += 1
                instance.capture()
                self.assertEqual(counts, {name: 2 for name in NAMES})
                self.assertEqual(instance.report["captures"], 2)
                # Failed subsequent foreground capture loses both registrations.
                instance.bridge.capture = lambda: {"ok": False, "reason": "foreground_changed"}
                with self.assertRaisesRegex(runtime.Stop, "foreground_changed"):
                    instance.capture()
                self.assertIsNone(instance._board_cache.capture)
            finally:
                instance._board_cache.uninstall()
                instance.events.close()

    def test_actual_dispatch_clears_before_fake_input_without_changing_metadata(self):
        import apk_battle_runtime as runtime
        with tempfile.TemporaryDirectory() as out:
            instance = self.make_runtime(out)
            instance.options["read_only"] = False
            instance.context = "attack_hq"
            instance.last_info = dict(state="in_game", button="white", transition_reason="",
                choice_modal=False, captured_elapsed_ms=1000, frame_id=1,
                source_width=1920, source_height=1080, foreground_generation=2)
            instance.engine = types.SimpleNamespace(_combat_decision_context={}, turns_seen=1)
            requests = []
            def fake_dispatch(encoded):
                instance._board_cache.clear.assert_called_once()
                instance.artwork_filter.clear.assert_called_once()
                requests.append(json.loads(encoded))
                return {"accepted": True, "completed": True, "reason": "fake_completed"}
            instance.bridge.dispatch = fake_dispatch
            gesture = dict(kind="drag", **{"from": [600, 475], "to": [600, 176]}, duration_ms=1000)
            instance.dispatch(gesture)
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0]["captured_elapsed_ms"], 1000)
            self.assertEqual(instance.report["game_inputs"], 1)
            instance.events.close()

    def test_execute_load_failure_or_stop_always_uninstalls_and_clears(self):
        import apk_battle_runtime as runtime
        for error in (runtime.Stop("offline_stop"), ValueError("offline_error")):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as out:
                instance = self.make_runtime(out)
                cache = instance._board_cache
                cache.uninstall = Mock()
                instance.load_core = Mock(side_effect=error)
                result = json.loads(instance.execute())
                cache.clear.assert_called_once()
                cache.uninstall.assert_called_once()
                instance.artwork_filter.clear.assert_called_once()
                self.assertFalse(result["result_verified"])
                self.assertEqual(result["game_inputs"], 0)


if __name__ == "__main__":
    unittest.main()
