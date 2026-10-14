"""No device: direct/fallback routing and fake bridge refusal checks."""
import types
import unittest
from unittest import mock

import apk_direct_drag as direct


class DirectDragTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.dispatch = mock.Mock()
        self.platform = types.SimpleNamespace(_down_ms=None, _position=None)
        self.runtime = types.SimpleNamespace(context="deploy", platform=self.platform,
            dispatch=self.dispatch, event=lambda kind, value: self.events.append((kind, value)))
        self.platform.runtime = self.runtime
        self.original = mock.Mock(return_value="original_result")
        self.actions = types.SimpleNamespace(move_drag=self.original, PRESS_DELAY=.2, DWELL=.4,
            DWELL_JIGGLE=3, RELEASE_SETTLE=.2, _plat=lambda: self.platform)
        direct.install(self.runtime, self.actions)

    def test_reviewed_contexts_submit_one900ms_drag_keep_release_settle(self):
        for context in sorted(direct.CONTEXTS):
            with self.subTest(context=context), mock.patch.object(direct, "sleep") as wait:
                self.runtime.context = context
                self.dispatch.reset_mock()
                self.assertIs(self.actions.move_drag(827, 659, 999, 505), True)
                self.dispatch.assert_called_once_with({"kind": "drag", "from": [827,659],
                    "to": [999,505], "duration_ms": 900})
                wait.assert_called_once_with(.2)
                self.assertEqual(self.platform._position, (999,505))
        self.original.assert_not_called()

    def test_each_explicit_timing_and_callback_falls_back_before_input(self):
        callback = lambda: None
        for kwargs in ({"press_delay": .2}, {"settle": .3}, {"dwell": .4},
                       {"jiggle": 3}, {"on_pressed": callback}, {"settle": True},
                       {"settle": .15}, {"press_delay": None}, {"dwell": None},
                       {"jiggle": None}, {"on_pressed": None}):
            with self.subTest(kwargs=kwargs), mock.patch.object(direct, "sleep") as wait:
                self.original.reset_mock()
                self.assertEqual(self.actions.move_drag(827,659,999,505,**kwargs), "original_result")
                self.original.assert_called_once()
                self.assertEqual(self.original.call_args.args, (827,659,999,505))
                self.assertEqual(self.original.call_args.kwargs, kwargs)
                wait.assert_not_called()
        self.dispatch.assert_not_called()

    def test_explicit_positional_timing_is_forwarded_unchanged_before_input(self):
        optional=(None,.15,None,None,None)
        for length in range(1,len(optional)+1):
            with self.subTest(length=length), mock.patch.object(direct, "sleep") as wait:
                self.original.reset_mock()
                args=(827,659,999,505)+optional[:length]
                self.assertEqual(self.actions.move_drag(*args), "original_result")
                self.original.assert_called_once_with(*args)
                wait.assert_not_called()
        self.dispatch.assert_not_called()

    def test_unreviewed_hook_or_wrong_platform_and_partial_pointer_use_original(self):
        for mode in ("hook", "platform", "pointer", "constants", "same_point"):
            with self.subTest(mode=mode), mock.patch.object(direct, "sleep"):
                self.runtime.context="deploy";self.actions._plat=lambda:self.platform
                self.platform._down_ms=None;self.actions.DWELL=.4
                self.original.reset_mock()
                coords=(827,659,999,505)
                if mode=="hook":self.runtime.context="end_turn"
                if mode=="platform":self.actions._plat=lambda:object()
                if mode=="pointer":self.platform._down_ms=123
                if mode=="constants":self.actions.DWELL=.2
                if mode=="same_point":coords=(827,659,827,659)
                self.assertEqual(self.actions.move_drag(*coords), "original_result")
                self.original.assert_called_once()
        self.dispatch.assert_not_called()

    def test_bridge_stop_propagates_without_release_wait_or_replay(self):
        failure=KeyboardInterrupt("accepted_incomplete")
        self.dispatch.side_effect=failure
        with mock.patch.object(direct,"sleep") as wait:
            with self.assertRaises(KeyboardInterrupt):self.actions.move_drag(827,659,999,505)
            wait.assert_not_called()
        self.dispatch.assert_called_once()
        self.original.assert_not_called()
        self.assertIsNone(self.platform._position)

    def test_reinstallation_binds_new_session_to_original_function(self):
        first=self.actions.move_drag
        other_platform=types.SimpleNamespace(_down_ms=None,_position=None)
        other_runtime=types.SimpleNamespace(context="attack_hq",platform=other_platform,
            dispatch=mock.Mock(),event=mock.Mock())
        other_platform.runtime=other_runtime
        self.actions._plat=lambda:other_platform
        direct.install(other_runtime,self.actions)
        self.assertIs(self.actions._apk_original_move_drag,self.original)
        self.assertIs(self.actions.move_drag.original,self.original)
        self.assertIsNot(self.actions.move_drag,first)
        with mock.patch.object(direct,"sleep"):
            self.actions.move_drag(640,330,711,174)
        other_runtime.dispatch.assert_called_once()
        self.dispatch.assert_not_called()


if __name__=="__main__":unittest.main()
