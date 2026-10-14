"""Exercise optional diagnostic I/O failure and real capture cleanup ordering."""
import io
import json
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock

from apk_battle_runtime import Runtime


class GreenStatRuntimeTests(unittest.TestCase):
    def test_cold_install_tracks_lazy_digit_callbacks_and_in_place_bank_changes(self):
        import numpy as np
        previous = sys.modules.pop("kredits_templates", None)
        runtime = Runtime.__new__(Runtime)
        board = ModuleType("cold_memo_board")
        board.us, board.hq_hp = ModuleType("cold_us"), ModuleType("cold_hp")
        calls = []
        board.board_transition_reason = lambda frame: ""
        board.frontline_state = lambda frame: calls.append(frame) or {"owner": "empty"}
        runtime.mb = board
        runtime.bridge = SimpleNamespace(isCancelled=lambda: False, elapsedRealtime=lambda: 1000)
        runtime.deadline = 2000
        memo = None
        try:
            self.assertNotIn("kredits_templates", sys.modules)
            runtime._install_board_cache()
            memo = runtime._board_cache
            digit = sys.modules["kredits_templates"]
            self.assertEqual(digit._TEMPLATES, {})
            epoch = memo.config_epoch()
            self.assertIsNotNone(epoch)
            self.assertIn(id(digit), [item[0] for item in epoch])
            frame = np.zeros((720, 1280, 3), np.uint8)
            memo.register(frame, dict(frame_id=1, captured_elapsed_ms=1000,
                foreground_generation=1, source_width=1280, source_height=720))
            board.frontline_state(frame)
            board.frontline_state(frame)
            self.assertEqual(len(calls), 1)
            callback = digit.score_against
            digit.score_against = lambda *args, **kwargs: None
            board.frontline_state(frame)
            self.assertEqual(len(calls), 2)
            digit.score_against = callback
            board.frontline_state(frame)
            self.assertEqual(len(calls), 3)
            digit._TEMPLATES = {4: np.zeros((3, 3), np.uint8)}
            board.frontline_state(frame)
            self.assertEqual(len(calls), 4)
            digit._TEMPLATES[4][1, 1] = 255
            board.frontline_state(frame)
            self.assertEqual(len(calls), 5)
            digit._TEMPLATES[4][1, 1] = 0
            board.frontline_state(frame)
            self.assertEqual(len(calls), 6)
        finally:
            if memo is not None:
                memo.uninstall()
            sys.modules.pop("kredits_templates", None)
            if previous is not None:
                sys.modules["kredits_templates"] = previous

    def runtime(self, failure=None, recovered=1):
        order = []
        runtime = Runtime.__new__(Runtime)
        runtime.report = {"unconfirmed_inputs": 3, "actions_confirmed": 4}
        runtime.started = 1000
        runtime.bridge = SimpleNamespace(elapsedRealtime=lambda: 2000,
            emit=mock.Mock(side_effect=OSError("diagnostic bridge") if failure == "emit" else None))
        runtime.events = io.StringIO()
        if failure in ("write", "flush"):
            runtime.events = SimpleNamespace(write=mock.Mock(), flush=mock.Mock())
            getattr(runtime.events, failure).side_effect = OSError("diagnostic " + failure)
        diagnostics = mock.Mock(return_value={"frame_id": 7, "recovered_plate_count": recovered})
        if failure == "diagnostics":
            diagnostics.side_effect = ValueError("diagnostic snapshot")
        runtime.stat_sampler = SimpleNamespace(diagnostics=diagnostics,
            clear=lambda: order.append("stat_clear"),
            register=lambda frame, info: order.append(("stat_register", frame, info)))
        for name in ("_board_cache", "hq_splitter", "artwork_filter"):
            setattr(runtime, name, SimpleNamespace(clear=lambda n=name: order.append(n + "_clear"),
                register=lambda frame, info, n=name: order.append((n + "_register", frame, info))))
        return runtime, order

    def test_optional_diagnostic_failures_cannot_interrupt_required_cache_cleanup(self):
        for failure in ("write", "flush", "emit", "diagnostics"):
            with self.subTest(failure=failure):
                runtime, order = self.runtime(failure)
                runtime._clear_board_cache()
                self.assertEqual(order, ["stat_clear", "_board_cache_clear", "artwork_filter_clear", "hq_splitter_clear"])
                self.assertEqual(runtime.report, {"unconfirmed_inputs": 3, "actions_confirmed": 4,
                                                 "green_stat_diagnostics_dropped": 1})

    def test_healthy_diagnostic_flush_keeps_original_frame_and_does_not_change_action_results(self):
        runtime, order = self.runtime()
        runtime._clear_board_cache()
        event = json.loads(runtime.events.getvalue())
        self.assertEqual(event["kind"], "green_stat_capture_summary")
        self.assertEqual(event["value"]["frame_id"], 7)
        self.assertEqual(runtime.report, {"unconfirmed_inputs": 3, "actions_confirmed": 4})
        self.assertEqual(runtime.bridge.emit.call_count, 1)
        self.assertEqual(order[0], "stat_clear")

    def test_no_recovery_does_not_publish_optional_diagnostic(self):
        runtime, order = self.runtime(recovered=0)
        runtime._clear_board_cache()
        self.assertEqual(runtime.events.getvalue(), "")
        runtime.bridge.emit.assert_not_called()
        self.assertEqual(order[0], "stat_clear")

    def test_green_registration_precedes_all_proofs_and_board_memo(self):
        runtime, order = self.runtime()
        frame, info = object(), {"frame_id": 9}
        runtime._register_board_capture(frame, info)
        self.assertEqual([item[0] for item in order],
                         ["stat_register", "hq_splitter_register", "artwork_filter_register", "_board_cache_register"])
        self.assertTrue(all(item[1] is frame and item[2] is info for item in order))


if __name__ == "__main__":
    unittest.main()
