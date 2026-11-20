"""Offline only: synthetic/recorded PNGs and an injected subprocess double.
    python -B dev/emu_battle_pilot_test.py --mobile-root <local-mobile-checkout>

Supply --battle-e and --card3-run with --mobile-root for the local incident
replays. Without --mobile-root, only the synthetic/transport tests run. No
sample, including an explicit live-flag CLI rejection test, contacts ADB.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

import emu_battle_pilot as p

MOBILE = BATTLE_E = CARD3_RUN = None
G7 = Path("shots/android/hand/runtime_20261003g/repro/native_g7_fetch_001/") / "native_g7_play_001/20261004_015410_7d2cbb"
VICTORY = Path("shots/android/hand/runtime_20261003f/repro/native_f2_fetch_002/") / "native_f2_play_002/20261003_140938_afeadb/0027_normalized.png"
PACKAGE = p.PACKAGES[0]
BOOT = "0122d7f5-7bb7-427c-90ba-93bb0ff735e3"
SERIAL = "127.0.0.1:16608"
EXE = r"C:\example\adb.exe"
END = p.Plan("end_turn", (1156, 504))
DEPLOY = p.Plan("deploy", (700, 652), (786, 505))


def setUpModule():
    if MOBILE is None:
        return
    # The mobile digit reader exports diagnostic PNGs on first use. Keep the
    # real source masks and code, but never export into the fixture checkout.
    src = MOBILE / "src"
    with patch.object(sys, "path", [str(src), *sys.path]):
        import kredits_templates as digits
    if Path(digits.__file__).resolve() != src / "kredits_templates.py":
        raise RuntimeError("unexpected_mobile_digit_module")
    temp = tempfile.TemporaryDirectory(prefix="emu-pilot-digits-", dir=os.environ.get("PI_SCRATCH_DIR"))
    unittest.addModuleCleanup(temp.cleanup)
    output_dir = patch.object(digits, "TEMPLATES_DIR", temp.name)
    output_dir.start()
    unittest.addModuleCleanup(output_dir.stop)


def picture(code, size=(1280, 720)):
    w, h = size
    im = np.full((h, w, 3), code, np.uint8)
    if code in (2, 7):
        im[460:555, 666:774] = 160
        im[610:720, 620:740] = 175
    ok, encoded = cv2.imencode(".png", im)
    assert ok
    return encoded.tobytes()


PNG = {i: picture(i) for i in range(10)}


def guard_out(*, package=PACKAGE, game_pid=2319, window="self", helper="1:", extra="", display=0):
    # adb shell without -T may use Windows/PTY CRLF for textual output.
    return (f"BOOT={BOOT}\r\nGAME={game_pid}\r\nHELPER={helper}\r\nPROCESSES\r\n"
            f"  PID ARGS\r\n {game_pid} {PACKAGE}\r\n{extra}FOCUS\r\n"
            f"  mCurrentFocus=Window{{{window} u0 {package}/com.epicgames.unreal.GameActivity}}\r\n"
            f"  mTopFocusedDisplayId={display}\r\n").encode()


class Clock:
    now = 0.

    def __call__(self):
        return self.now

    def wait(self, delta):
        self.now += delta


class FakeAdb:
    def __init__(self, frames, clock):
        self.frames = list(frames)
        self.index = 0
        self.clock = clock
        self.calls, self.inputs = [], []
        self.on_guard = lambda n: guard_out()
        self.on_input = lambda: SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        self.guard_count = 0

    def __call__(self, args, **opts):
        self.calls.append(args)
        assert args[:3] == [EXE, "-s", SERIAL], "real/default/wrong ADB target"
        assert 0 < opts["timeout"] <= 3.
        assert opts["env"]["ADB_SERVER_SOCKET"] == "tcp:127.0.0.1:5037"
        assert not any(k.upper() == "ANDROID_SERIAL" for k in opts["env"])
        cmd = args[3:]
        self.clock.wait(.025)
        if cmd == ["get-state"]:
            result = b"device\n"
        elif cmd[:2] == ["shell", "input"]:
            self.inputs.append(cmd)
            return self.on_input()
        elif cmd[0] == "shell":
            assert "mCurrentFocus" in cmd[1] and f"pidof {p.HELPER}" in cmd[1]
            self.guard_count += 1
            result = self.on_guard(self.guard_count)
        elif cmd == ["exec-out", "screencap", "-p"]:
            item = self.frames[min(self.index, len(self.frames)-1)]
            self.index += 1
            result = PNG[item] if isinstance(item, int) else item
        else:
            raise AssertionError(f"unapproved fake command {cmd}")
        return SimpleNamespace(returncode=0, stdout=result, stderr=b"")


class FakeVision:
    @staticmethod
    def observe(pixels, *, mode):
        n = int(pixels[0, 0, 0])
        if n in (0, 1, 2, 7):
            support = p.Support(568, ((1 if n == 2 else -1, "infantry"),)) if n in (2, 7) else p.Support(640, ())
            return p.Reading("own", "fixture", {}, end=END, deploy=DEPLOY if n == 1 and mode == "plan" else None, support=support)
        if n == 8:
            return p.Reading("choice", "large_choice_modal", {})
        if n == 9:
            return p.Reading("choice", "target_selection_pending", {})
        state = {3: "opponent", 4: "unknown", 5: "defeat", 6: "mulligan"}[n]
        return p.Reading(state, "fixture", {"opponent_layout": "standard"} if n == 3 else {})

    @staticmethod
    def stable(a, b):
        return True


def incident_events(path):
    return [json.loads(line) for line in (path / "events.jsonl").read_text(encoding="utf-8").splitlines()]


def incident_png(path, entry):
    raw = (path / entry["png"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        raise AssertionError(f"saved frame hash mismatch: {entry['png']}")
    return raw


class Harness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="emu-b-pilot-test-", dir=os.environ.get("PI_SCRATCH_DIR"))
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.clock = Clock()
        self.stop = self.directory / "STOP"
        self.bounds = p.Bounds(30, self.stop, self.clock, self.clock.wait)
        self.journal = p.Journal(self.directory / "audit")

    def configure(self, frames, *, limit=1, vision=None, end_only=False):
        self.runner = FakeAdb(frames, self.clock)
        self.adb = p.Adb(EXE, SERIAL, PACKAGE, self.bounds, runner=self.runner)
        self.pilot = p.Pilot(self.adb, vision or FakeVision(), self.bounds, self.journal,
                             action_limit=limit, end_only=end_only)
        return self.pilot

    def events(self):
        return [json.loads(line) for line in (self.journal.path / "events.jsonl").read_text(encoding="utf-8").splitlines()]


class PilotTests(Harness):
    def test_end_requires_two_positive_labels_and_keeps_raw_evidence(self):
        # Button disappearance alone (4) and one earlier opponent label do not count.
        result = self.configure([0, 0, 3, 4, 3, 3]).run()
        self.assertEqual(result["stop_reason"], "action_budget")
        self.assertEqual(result["effects_verified"], {"deploy": 0, "end_turn": 1})
        self.assertEqual(self.runner.inputs, [["shell", "input", "touchscreen", "-d", "0", "tap", "1156", "504"]])
        verified = next(e for e in self.events() if e["event"] == "effect_verified")
        self.assertEqual([x["frame"] for x in verified["evidence"]], [5, 6])
        for artifact in verified["evidence"]:
            self.assertEqual(hashlib.sha256((self.journal.path / artifact["png"]).read_bytes()).hexdigest(), artifact["sha256"])

    def test_deploy_needs_later_pair_then_one_end_then_terminal(self):
        result = self.configure([1, 1, 4, 2, 2, 0, 0, 3, 3, 5, 0, 0], limit=8).run()
        self.assertEqual(result["outcome"], "defeat")
        self.assertEqual(result["effects_verified"], {"deploy": 1, "end_turn": 1})
        self.assertEqual([x[5] for x in self.runner.inputs], ["swipe", "tap"])
        self.assertEqual(self.runner.inputs[0][6:], ["700", "652", "786", "505", "600"])
        self.assertEqual(self.runner.index, 10)

    def test_deploy_animation_may_settle_after_six_seconds_without_resend(self):
        self.configure([1, 1, 4, 4, 2, 2], limit=1)
        original = self.adb.capture

        def slow_capture():
            if self.runner.inputs:
                self.clock.wait(1.4)  # the second settled image comes after 6 s
            return original()

        self.adb.capture = slow_capture
        result = self.pilot.run()
        self.assertEqual(result["effects_verified"], {"deploy": 1, "end_turn": 0})
        self.assertEqual((self.runner.index, len(self.runner.inputs)), (6, 1))
        self.assertIsNone(result["unresolved_action"])

    def test_wrong_deployment_side_not_verified(self):
        result = self.configure([1, 1, 7, 7], limit=8).run()
        self.assertEqual(result["unresolved_action"], "deploy")
        self.assertEqual(result["stop_reason"], "effect_unconfirmed")
        self.assertEqual(result["effects_verified"]["deploy"], 0)
        self.assertEqual(len(self.runner.inputs), 1)

    def test_return_zero_but_no_proof_never_retries(self):
        result = self.configure([0, 0, 4, 4], limit=8).run()
        self.assertEqual((result["attempts"], result["adb_returned_zero"], result["effects_verified"]["end_turn"]), (1, 1, 0))
        self.assertEqual(result["stop_reason"], "effect_unconfirmed")
        self.assertEqual(len(self.runner.inputs), 1)

    def test_timeout_after_launch_is_unresolved_never_retried(self):
        def fail():
            raise subprocess.TimeoutExpired([EXE], 2.5)
        self.configure([1, 1, 2, 2], limit=8)
        self.runner.on_input = fail
        result = self.pilot.run()
        self.assertEqual((result["stop_reason"], result["unresolved_action"]), ("adb_gesture_timeout", "deploy"))
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(result["adb_returned_zero"], 0)
        self.assertEqual(len(self.runner.inputs), 1)

    def test_nonzero_receipt_is_not_success(self):
        self.configure([0, 0, 3, 3], limit=8)
        self.runner.on_input = lambda: SimpleNamespace(returncode=1, stdout=b"", stderr=b"offline")
        result = self.pilot.run()
        self.assertEqual(result["stop_reason"], "adb_gesture_failed:1:offline")
        self.assertEqual(result["unresolved_action"], "end_turn")
        self.assertEqual(result["adb_returned_zero"], 0)
        self.assertEqual(len(self.runner.inputs), 1)

    def test_result_during_postcheck_exits_not_action_success(self):
        result = self.configure([0, 0, 5, 3, 3, 0], limit=8).run()
        self.assertEqual(result["outcome"], "defeat")
        self.assertEqual(result["effects_verified"]["end_turn"], 0)
        self.assertEqual(result["unresolved_action"], "end_turn")
        self.assertEqual(self.runner.index, 3)

    def test_mulligan_no_dispatch_even_with_own_frame_next(self):
        result = self.configure([6, 0, 0]).run()
        self.assertEqual(result["stop_reason"], "mulligan")
        self.assertEqual(self.runner.index, 1)
        self.assertFalse(self.runner.inputs)

    def test_existing_large_choice_stop_reason_unchanged(self):
        result = self.configure([0, 0, 8, 3, 3], limit=8).run()
        self.assertEqual((result["stop_reason"], result["unresolved_action"]), ("choice", "end_turn"))
        self.assertEqual(result["effects_verified"], {"deploy": 0, "end_turn": 0})
        self.assertEqual((self.runner.index, len(self.runner.inputs)), (3, 1))

    def test_target_selection_keeps_prior_verified_total_and_pending_deploy(self):
        result = self.configure([0, 0, 3, 3, 1, 1, 9, 2, 2], limit=8).run()
        self.assertEqual(result, dict(stop_reason="target_selection_pending", outcome=None,
                                      attempts=2, adb_returned_zero=2,
                                      effects_verified={"deploy": 0, "end_turn": 1}, unresolved_action="deploy"))
        self.assertEqual([e["action"] for e in self.events() if e["event"] == "effect_verified"], ["end_turn"])
        self.assertEqual([cmd[5] for cmd in self.runner.inputs], ["tap", "swipe"])
        self.assertEqual(self.runner.index, 7)

    def test_unknown_timeout_never_dispatches(self):
        result = self.configure([4]).run()
        self.assertEqual(result["stop_reason"], "unsupported_or_unknown_screen")
        self.assertFalse(self.runner.inputs)

    def test_stop_before_capture_never_calls_adb(self):
        self.stop.touch()
        result = self.configure([0, 0]).run()
        self.assertEqual(result["stop_reason"], "stop_file")
        self.assertFalse(self.runner.calls)

    def test_stop_during_gesture_prevents_continuation(self):
        self.configure([0, 0, 3, 3, 0, 0], limit=8)
        def stop():
            self.stop.touch()
            return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        self.runner.on_input = stop
        result = self.pilot.run()
        self.assertEqual(result["stop_reason"], "stop_file")
        self.assertEqual(result["unresolved_action"], "end_turn")
        self.assertEqual(len(self.runner.inputs), 1)

    def test_time_budget_has_no_input(self):
        self.bounds.deadline = .15
        result = self.configure([0, 0]).run()
        self.assertEqual(result["stop_reason"], "time_budget")
        self.assertFalse(self.runner.inputs)

    def test_first_focus_change_and_exact_package_no_input(self):
        for name in (p.PACKAGES[1], PACKAGE+".overlay", "com.android.settings"):
            with self.subTest(name=name), self.assertRaisesRegex(p.Halt, "selected_game_not_focused"):
                p.parse_binding(guard_out(package=name), PACKAGE)
        self.configure([0, 0])
        self.runner.on_guard = lambda i: guard_out(window="other" if i == 5 else "self")
        self.assertEqual(self.pilot.run()["stop_reason"], "foreground_changed_before_dispatch")
        self.assertFalse(self.runner.inputs)

    def test_helper_child_blocks_before_screenshot(self):
        self.configure([0, 0])
        self.runner.on_guard = lambda i: guard_out(extra=f" 31337 {p.HELPER}:capture\r\n")
        self.assertEqual(self.pilot.run()["stop_reason"], "helper_subprocess_running")
        self.assertEqual(self.runner.index, 0)
        self.assertFalse(self.runner.inputs)

    def test_helper_pid_and_nondefault_display_fail_closed(self):
        with self.assertRaisesRegex(p.Halt, "helper_running_or_unreadable"):
            p.parse_binding(guard_out(helper="0:131"), PACKAGE)
        with self.assertRaisesRegex(p.Halt, "foreground_display_not_default"):
            p.parse_binding(guard_out(display=3), PACKAGE)

    def test_stale_frame_blocked_before_any_input(self):
        self.configure([0, 0])
        def slow_guard(i):
            if i == 5:
                self.clock.wait(p.FRESHNESS+.1)
            return guard_out()
        self.runner.on_guard = slow_guard
        self.assertEqual(self.pilot.run()["stop_reason"], "frame_expired_before_dispatch")
        self.assertFalse(self.runner.inputs)

    def test_foreground_window_cannot_change_during_capture(self):
        self.configure([0, 0])
        self.runner.on_guard = lambda i: guard_out(window=str(i))
        self.assertEqual(self.pilot.run()["stop_reason"], "foreground_changed_during_capture")
        self.assertFalse(self.runner.inputs)

    def test_aspect_or_resolution_change_blocks_and_keeps_refusal(self):
        self.configure([picture(0, (1612, 720))])
        result = self.pilot.run()
        self.assertEqual(result["stop_reason"], "unsupported_screenshot_size:1612x720")
        self.assertTrue((self.journal.path / "refused.png").is_file())
        self.assertFalse(self.runner.inputs)

    def test_16x9_remaps_fixed_canvas_and_rejects_truncated_png(self):
        f = p.Frame.read(1, 0., picture(0, (1920, 1080)))
        self.assertEqual(f.pixels.shape, (720, 1280, 3))
        self.assertEqual(f.at_native((1279, 719)), (1919, 1079))
        self.assertEqual(f.at_native((640, 360)), (960, 540))
        with self.assertRaisesRegex(p.Halt, "invalid_or_incomplete_png"):
            p.decode_png(PNG[0][:-12])

    def test_saved_inspection_never_opens_adb(self):
        src, dst = self.directory / "frame.png", self.directory / "inspect"
        src.write_bytes(PNG[1])
        with patch.object(p, "Adb", side_effect=AssertionError("must not construct device")), patch.object(p, "Vision", return_value=FakeVision()), redirect_stdout(io.StringIO()):
            mobile = self.directory / "mobile"
            mobile.mkdir()
            code = p.main(["--mobile-root", str(mobile), "--frame", str(src), "--out", str(dst)])
        self.assertEqual(code, 0)
        self.assertEqual((dst / "inspect.png").read_bytes(), PNG[1])

    def test_cli_refuses_live_without_attestation_or_with_saved_frame(self):
        for flags in (["--live"], ["--live", "--confirmed-training", "--frame", "a.png"]):
            with self.subTest(flags=flags), patch.object(p, "Adb", side_effect=AssertionError("must not construct device")), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as err:
                p.main(["--mobile-root", str(self.directory), "--out", str(self.directory / "out"), *flags])
            self.assertEqual(err.exception.code, 2)

    @unittest.skipUnless(os.name == "nt", "Windows mutex")
    def test_windows_single_instance_without_adb(self):
        with p.live_lease():
            with self.assertRaisesRegex(p.Halt, "another_live_pilot_running"):
                with p.live_lease():
                    self.fail("locked run entered")
        with p.live_lease():
            pass


class SavedPngTests(Harness):
    @classmethod
    def setUpClass(cls):
        if MOBILE is None:
            raise unittest.SkipTest("supply --mobile-root for real PNG tests")
        cls.vision = p.Vision(MOBILE)

    def file(self, name):
        return (MOBILE / name).read_bytes()

    def observe(self, name, mode="plan"):
        return self.vision.observe(p.Frame.read(1, 0., self.file(name)).pixels, mode=mode)

    def test_saved_own_to_enemy_fake_transport(self):
        frames = [self.file(f"shots/android/ingame/f{i}.png") for i in (0, 0, 1, 2)]
        result = self.configure(frames, vision=self.vision).run()
        self.assertEqual(result["effects_verified"]["end_turn"], 1)
        self.assertEqual(self.runner.inputs[0][6:], ["1734", "756"])

    def test_two_saved_own_frames_plan_local_unit(self):
        for i in (4, 5):
            r = self.observe(f"shots/android/ingame/f{i}.png")
            self.assertEqual(r.state, "own")
            self.assertEqual(r.deploy, p.Plan("deploy", (732, 648), (786, 505)))
            self.assertEqual(r.support.units, ())
            self.assertNotIn("card_name", r.evidence["hand"][1])
        self.assertIsNone(self.observe("shots/android/ingame/f4.png", "end_only").deploy)

    def test_saved_order_markers_never_promoted(self):
        for file, xs in (("dump_hammer_and_il2.png", (469, 568)), ("dump_nine_units.png", (324, 384))):
            frame = p.Frame.read(1, 0., self.file(f"shots/android/hand/kind/{file}"))
            origins, evidence = self.vision.hands(frame.pixels)
            self.assertTrue(origins, "negative alongside positive candidates")
            for x in xs:
                item = next(c for c in evidence if c["anchor"][0] == x)
                self.assertEqual(item["kind"], "unknown")
                self.assertNotIn("grab", item)
                self.assertTrue(all(abs(px-x-25) > 8 for px, _ in origins))

    def test_saved_deploy_plan_and_two_later_confirming_frames(self):
        # Historical action used different grab/drop points. This is a fake-
        # transport replay of visual evidence, not a live pilot swipe test.
        frames = [self.file(G7 / f"{i:04d}_normalized.png") for i in (4, 5, 6, 7, 8)]
        result = self.configure(frames, vision=self.vision).run()
        self.assertEqual(result["effects_verified"]["deploy"], 1)
        self.assertEqual(self.runner.inputs[0][5:], ["swipe", "654", "648", "810", "505", "600"])
        verified = next(e for e in self.events() if e["event"] == "effect_verified")
        self.assertEqual(verified["new_unit"], [1, "infantry"])
        self.assertEqual([e["frame"] for e in verified["evidence"]], [4, 5])

    def test_saved_typed_gain_and_full_support_readback(self):
        base = G7 / "actions/20261004_015424_deploy"
        a, b = self.observe(base / "before.png"), self.observe(base / "after.png", "verify_deploy")
        self.assertEqual(a.support.units, ())
        self.assertEqual(b.support.units, ((1, "infantry"),))
        self.assertIsNotNone(a.deploy)
        full = self.observe(G7 / "actions/20261004_015711_deploy/after.png", "verify_deploy")
        self.assertEqual(len(full.support.units), 4)
        self.assertIsNone(self.observe(G7 / "actions/20261004_015711_deploy/after.png").deploy)

    def test_saved_opening_victory_defeat_unknown_have_no_plan(self):
        expectations = (("shots/android/queue/q_c.png", "mulligan"),
                        ("shots/android/end/d_b.png", "defeat"), (VICTORY, "victory"),
                        ("shots/android/ingame/f3.png", "unknown"))
        for file, expected in expectations:
            with self.subTest(file=file):
                r = self.observe(file)
                self.assertEqual(r.state, expected)
                self.assertIsNone(r.end)
                self.assertIsNone(r.deploy)

    def test_widescreen_archived_native_frame_is_not_rescaled_to_fit(self):
        with self.assertRaisesRegex(p.Halt, "unsupported_screenshot_size:1612x720"):
            self.observe("repro/recall174_20261113/optimized-sixth-000064.png")

class TargetSelectionReplayTests(Harness):
    @classmethod
    def setUpClass(cls):
        if MOBILE is None or BATTLE_E is None:
            raise unittest.SkipTest("supply --mobile-root and --battle-e for the target-selection replay")
        cls.vision = p.Vision(MOBILE)
        events = incident_events(BATTLE_E)
        dispatch, = [e for e in events if e["event"] == "dispatch_attempt" and e["attempt"] == 4]
        samples = [e for e in events if e["event"] == "verification_sample" and e["attempt"] == 4]
        terminal, = [e for e in events if e["event"] == "terminal_frame"]
        assert [e["frame"] for e in samples] == list(range(34, 41))
        assert terminal["sha256"] == samples[-1]["sha256"]  # alias, not another independent frame
        cls.before = [incident_png(BATTLE_E, e) for e in dispatch["evidence"]]
        cls.after = [(e["png"], incident_png(BATTLE_E, e)) for e in [*samples, terminal]]

    @staticmethod
    def pixels(raw):
        return p.decode_png(raw)[0]

    def assert_prompt(self, reading):
        self.assertEqual((reading.state, reading.reason), ("choice", "target_selection_pending"))
        self.assertEqual((reading.end, reading.deploy, reading.support), (None, None, None))
        self.assertEqual(reading.evidence["target_selection"]["label"], "选择目标")
        self.assertNotIn("frontline", reading.evidence)

    def assert_prompt_stop(self, result, *, pending, terminal_png, index):
        attempts = int(pending is not None)
        self.assertEqual(result, dict(stop_reason="target_selection_pending", outcome=None,
                                      attempts=attempts, adb_returned_zero=attempts,
                                      effects_verified={"deploy": 0, "end_turn": 0}, unresolved_action=pending))
        self.assertEqual(self.runner.index, index, "must stop on the first positive prompt")
        events = self.events()
        self.assertEqual([e["event"] for e in events].count("dispatch_attempt"), attempts)
        self.assertNotIn("effect_verified", [e["event"] for e in events])
        terminal, finished = events[-2:]
        self.assertEqual(terminal["event"], "terminal_frame")
        self.assertEqual(terminal["frame"], index)
        self.assertEqual(terminal["observation"]["state"], "choice")
        self.assertEqual(terminal["observation"]["reason"], "target_selection_pending")
        self.assertEqual(terminal["observation"]["target_selection"]["label"], "选择目标")
        self.assertEqual(terminal["sha256"], hashlib.sha256(terminal_png).hexdigest())
        self.assertEqual((self.journal.path / terminal["png"]).read_bytes(), terminal_png)
        self.assertEqual(finished["event"], "finished")
        self.assertEqual({k: finished[k] for k in result}, result)

    def test_old_e_postframes_are_choice_in_all_modes_before_board_geometry(self):
        with patch.object(self.vision.board, "frontline_state", side_effect=AssertionError("no geometry on prompt")):
            for name, raw in self.after:
                for mode in ("plan", "verify_deploy", "end_only"):
                    with self.subTest(file=name, mode=mode):
                        self.assert_prompt(self.vision.observe(self.pixels(raw), mode=mode))

    def test_old_e_preframes_and_masked_out_prompt_do_not_become_choice(self):
        for raw in self.before:
            reading = self.vision.observe(self.pixels(raw))
            self.assertEqual(reading.state, "own")
            self.assertEqual(reading.deploy, p.Plan("deploy", (655, 648), (880, 505)))
            self.assertNotIn("target_selection", reading.evidence)
        frame = self.pixels(self.after[0][1]).copy()
        frame[262:301, 643:678] = 0  # lose one glyph; the other three and both rails are intact
        reading = self.vision.observe(frame, mode="verify_deploy")
        self.assertNotEqual(reading.state, "choice")
        self.assertNotIn("target_selection", reading.evidence)

    def test_result_and_mulligan_take_priority_even_with_target_banner_pixels(self):
        template = self.pixels(self.after[0][1])[247:316, 559:721]
        for path, state in (("shots/android/queue/q_c.png", "mulligan"),
                            ("shots/android/end/d_b.png", "defeat"), (VICTORY, "victory")):
            with self.subTest(state=state):
                frame = self.pixels((MOBILE / path).read_bytes()).copy()
                frame[247:316, 559:721] = template
                self.assertIsNotNone(p.target_selection_witness(frame))
                reading = self.vision.observe(frame)
                self.assertEqual(reading.state, state)
                self.assertEqual((reading.end, reading.deploy, reading.support), (None, None, None))
                self.assertNotIn("target_selection", reading.evidence)

    def test_deploy_verification_keeps_action_unresolved_without_another_input(self):
        post = self.after[0][1]
        self.configure([*self.before, post, *self.before], limit=8, vision=self.vision)
        with patch.object(p, "deployed", side_effect=AssertionError("not a deployment proof")) as deployed:
            result = self.pilot.run()
        deployed.assert_not_called()
        self.assert_prompt_stop(result, pending="deploy", terminal_png=post, index=3)
        self.assertEqual([cmd[5:] for cmd in self.runner.inputs], [["swipe", "655", "648", "880", "505", "600"]])

    def test_decision_stops_even_when_sandwiched_between_two_own_frames(self):
        post = self.after[0][1]
        result = self.configure([self.before[0], post, self.before[1]], limit=8,
                                vision=self.vision).run()
        self.assert_prompt_stop(result, pending=None, terminal_png=post, index=2)
        self.assertFalse(self.runner.inputs)

    def test_end_only_decision_stops_without_attempting_end_turn(self):
        post = self.after[0][1]
        result = self.configure([post, *self.before], limit=8, vision=self.vision, end_only=True).run()
        self.assert_prompt_stop(result, pending=None, terminal_png=post, index=1)
        self.assertFalse(self.runner.inputs)

    def test_end_turn_verification_does_not_count_prompt_as_opponent(self):
        post = self.after[0][1]
        result = self.configure([*self.before, post, *self.before], limit=8,
                                vision=self.vision, end_only=True).run()
        self.assert_prompt_stop(result, pending="end_turn", terminal_png=post, index=3)
        self.assertEqual([cmd[5] for cmd in self.runner.inputs], ["tap"])


class Card3NegativeReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if MOBILE is None or CARD3_RUN is None:
            raise unittest.SkipTest("supply --mobile-root and --card3-run for the card 3 replay")
        from emu_training_profile import TrainingVision

        root = Path(__file__).resolve().parents[1]
        capture = CARD3_RUN.parent
        frames = [p.decode_png((capture / f"first-{n}.png").read_bytes())[0] for n in (1, 2)]
        cls.vision = TrainingVision(MOBILE, frames, card_db=root / "card_db/kards_data.json", ocr=lambda _: [])
        events = incident_events(CARD3_RUN)
        cls.dispatch, = [e for e in events if e["event"] == "dispatch_attempt" and e["attempt"] == 3]
        cls.samples = [e for e in events if e["event"] == "sample" and e["attempt"] == 3]
        cls.terminal, = [e for e in events if e["event"] == "terminal_frame"]
        assert [e["frame"] for e in cls.samples] == list(range(23, 32))

    def test_card3_unchanged_support_is_neither_choice_nor_deploy_success(self):
        vision = self.vision
        binding = tuple(self.dispatch["binding"])

        def read(e):
            f = p.Frame.read(e["frame"], e["capture_monotonic"], incident_png(CARD3_RUN, e), binding)
            r = vision.observe(f.pixels, mode="verify_deploy")
            self.assertNotIn("target_selection", r.evidence, e["png"])
            original = e.get("observation", {}).get("state", "own")
            is_rejection = e["frame"] in (23, 24)
            self.assertEqual(r.state, "rejected" if is_rejection else original, e["png"])
            if is_rejection:
                self.assertEqual(original, "unknown")  # preserve historical runtime classification
                self.assertEqual((r.end, r.deploy), (None, None))
                self.assertEqual(r.evidence["deployment_rejection"]["label"], "指挥点数不足，无法使用此卡牌")
            return f, r

        before = read(self.dispatch["evidence"][-1])
        plan = p.Plan("deploy", (416, 676), (855, 505))
        samples = [read(e) for e in self.samples]
        terminal = read(self.terminal)
        self.assertEqual(terminal[0].png, samples[-1][0].png)
        self.assertEqual([r.reason for _, r in samples[:2]], ["deploy_rejected_insufficient_kredits"] * 2)
        self.assertEqual(before[1].support.units, ((1, "infantry"),))
        for _, r in samples[2:] + [terminal]:
            self.assertEqual(r.support.units, before[1].support.units)
        for previous, current in zip(samples, samples[1:]):
            self.assertTrue(p.distinct_pair(previous[0], current[0]))
            self.assertIsNone(p.deployed(plan, before, previous, current))


class RejectionBoundaryTest(Harness):
    def test_postdeploy_rejection_never_sends_another_action(self):
        if MOBILE is None or CARD3_RUN is None:
            self.skipTest("pass --mobile-root and --card3-run for original post-deploy frames")
        sample = next(e for e in incident_events(CARD3_RUN) if e.get("png") == "read-0023.png")
        banner = incident_png(CARD3_RUN, sample)
        native = p.Vision(MOBILE)

        class Mixed(FakeVision):
            @staticmethod
            def observe(pixels, *, mode):
                # Only the two pre-action frames are fixtures; use the real PNG
                # recognizer throughout post-deploy verification.
                if mode == "plan":
                    return FakeVision.observe(pixels, mode=mode)
                return native.observe(pixels, mode=mode)

        self.assertNotEqual(native.observe(p.decode_png(banner)[0], mode="plan").state, "rejected")
        result = self.configure([1, 1, banner, 1, 1], limit=8, vision=Mixed()).run()
        self.assertEqual(result, dict(stop_reason=p.REJECTION_REASON, outcome=None, attempts=1,
                                      adb_returned_zero=1, effects_verified={"deploy":0, "end_turn":0},
                                      unresolved_action="deploy"))
        self.assertEqual([cmd[5] for cmd in self.runner.inputs], ["swipe"])
        self.assertEqual(self.runner.index, 3)



if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--mobile-root", type=Path)
    parser.add_argument("--battle-e", type=Path)
    parser.add_argument("--card3-run", type=Path)
    opts, extra = parser.parse_known_args()
    MOBILE = opts.mobile_root.resolve() if opts.mobile_root else None
    BATTLE_E = opts.battle_e.resolve() if opts.battle_e else None
    CARD3_RUN = opts.card3_run.resolve() if opts.card3_run else None
    unittest.main(argv=[__file__, *extra])
