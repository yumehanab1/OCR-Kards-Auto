"""Offline orchestrator checks: python/python.exe -B dev/emu_manager_test.py -v."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.dont_write_bytecode = True

import emu_manager as manager
from emu_discovery import EmulatorInstance


class FakeProcess:
    def __init__(self, argv, behavior="cooperative", before_wait=None):
        self.pid = 1234
        self.returncode = None
        self.stop_file = Path(argv[argv.index("--stop-file") + 1])
        self.behavior = behavior
        self.before_wait = before_wait
        self.events = []

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.events.append(("wait", timeout))
        if self.before_wait:
            self.before_wait()
        if self.behavior == "cooperative" and self.stop_file.exists():
            self.returncode = 0
        if self.returncode is None:
            raise subprocess.TimeoutExpired("fake worker", timeout)
        return self.returncode

    def terminate(self):
        self.events.append(("terminate",))
        if self.behavior == "terminate":
            self.returncode = -15

    def kill(self):
        self.events.append(("kill",))
        self.returncode = -9


class ManagerTests(unittest.TestCase):
    def setUp(self):
        # Inherit the parent ACL: Python 3.14's private Windows temp-dir ACL
        # excludes the restricted sandbox token used by this test runner.
        self.root = Path(tempfile.gettempdir()) / ("emu-manager-test-" + uuid.uuid4().hex)
        self.root.mkdir()
        self.addCleanup(self.cleanup)
        self.instances = [EmulatorInstance("mumu", "mumu:7", "MuMu 7", mumu_index=7),
                          EmulatorInstance("adb", "adb:127.0.0.1:5555", "ADB")]
        self.discover = Mock(side_effect=lambda **kw: list(self.instances))
        self.processes = []
        self.behavior = "cooperative"
        self.fail_ids = set()
        self.sleeps = []
        self.launches = []
        self.mgr = manager.EmuManager(self.root, python_exe="test-python",
                                      discover_fn=self.discover, popen_fn=self.popen,
                                      sleep_fn=self.sleeps.append)

    def cleanup(self):
        # Remove only this test's resolved temporary root, children first.
        root = self.root.resolve()
        self.assertEqual(root.parent, Path(tempfile.gettempdir()).resolve())
        for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            self.assertTrue(path.resolve().is_relative_to(root))
            path.rmdir() if path.is_dir() else path.unlink()
        root.rmdir()

    def popen(self, argv, **kwargs):
        iid = argv[argv.index("--instance") + 1]
        self.launches.append((iid, argv, kwargs))
        if iid in self.fail_ids:
            raise OSError("launch failed")
        self.assertFalse(Path(argv[argv.index("--stop-file") + 1]).exists())
        self.assertFalse(Path(argv[argv.index("--status-file") + 1]).exists())
        proc = FakeProcess(argv, self.behavior)
        self.processes.append(proc)
        return proc

    def test_options_defaults_types_bounds_and_clean_lists(self):
        opts = manager.normalize_emu_options({})
        self.assertEqual(opts, manager.DEFAULT_EMU_OPTIONS)
        opts["extra_serials"].append("changed")
        self.assertEqual(manager.DEFAULT_EMU_OPTIONS["extra_serials"], [])
        cleaned = manager.normalize_emu_options({
            "mode": "ranked", "max_rounds": 99, "stagger_seconds": 10,
            "extra_serials": [" a ", "", "a", " b"],
            "selected_instances": ["mumu:7", " mumu:7 ", ""], "deck_name": " 日本初始 "})
        self.assertEqual(cleaned["extra_serials"], ["a", "b"])
        self.assertEqual(cleaned["selected_instances"], ["mumu:7"])
        self.assertEqual(cleaned["deck_name"], "日本初始")
        self.assertEqual(manager.normalize_emu_options({"max_rounds": 0, "stagger_seconds": 0})["max_rounds"], 0)
        for invalid in (None, [], {"mode": "invalid"}, {"max_rounds": -1},
                        {"max_rounds": 100}, {"max_rounds": True}, {"max_rounds": "3"},
                        {"stagger_seconds": -1}, {"stagger_seconds": 10.1},
                        {"stagger_seconds": float("nan")}, {"stagger_seconds": float("inf")},
                        {"stagger_seconds": True}, {"dry_run": "false"}, {"allow_attack": 1},
                        {"deck_name": None}, {"extra_serials": "a"}, {"selected_instances": [4]}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                manager.normalize_emu_options(invalid)

    def test_options_atomic_persistence_and_gui_untouched(self):
        self.assertEqual(manager.load_emu_options(self.root), manager.DEFAULT_EMU_OPTIONS)
        config = self.root / "config"
        config.mkdir()
        gui = config / "gui_options.json"
        gui.write_bytes(b'{"existing":true}')
        replace = os.replace
        def verify(source, target):
            self.assertEqual(Path(source).parent, config)
            self.assertEqual(Path(target), config / "emu_options.json")
            self.assertEqual(json.loads(Path(source).read_text(encoding="utf-8"))["mode"], "casual")
            replace(source, target)
        with patch.object(manager.os, "replace", side_effect=verify) as called:
            saved = manager.save_emu_options({"mode": "casual"}, self.root)
        called.assert_called_once()
        self.assertEqual(manager.load_emu_options(str(self.root)), saved)
        self.assertEqual(gui.read_bytes(), b'{"existing":true}')
        with patch.object(manager.os, "replace", side_effect=OSError("blocked")), self.assertRaises(OSError):
            manager.save_emu_options({"mode": "ranked"}, self.root)
        self.assertEqual(manager.load_emu_options(self.root), saved)
        self.assertEqual(list(config.glob("*.tmp")), [])
        with self.assertRaises(ValueError):
            manager.save_emu_options({"max_rounds": 100}, self.root)
        (config / "emu_options.json").write_text('{"mode":"bad"}')
        with self.assertRaises(ValueError):
            manager.load_emu_options(self.root)

    def test_paths_python_and_argv(self):
        self.assertEqual(manager.safe_instance_slug("mumu:7"), "mumu_7")
        self.assertEqual(manager.safe_instance_slug("adb:127.0.0.1:5555"), "adb_127_0_0_1_5555")
        self.assertNotIn("/", manager.safe_instance_slug("../../unsafe"))
        self.assertEqual(manager.default_python_exe(self.root), sys.executable)
        (self.root / "python").mkdir()
        (self.root / "python/python.exe").touch()
        self.assertEqual(manager.default_python_exe(self.root), str(self.root / "python/python.exe"))
        paths = self.mgr.worker_paths("mumu:7")
        self.assertEqual(paths["status_file"], self.root / "logs/emu_mumu_7.status.json")
        argv = self.mgr.build_worker_argv("mumu:7", {})
        self.assertEqual(argv[:3], ["test-python", "-B", str(self.root / "src/emu_worker.py")])
        self.assertIn("--prefer-ipc", argv)
        self.assertNotIn("--extra-serial", argv)
        self.assertEqual(argv[argv.index("--max-rounds") + 1], "3")
        argv = self.mgr.build_worker_argv("adb:127.0.0.1:5555", {
            "prefer_ipc": False, "dry_run": True, "allow_attack": False,
            "allow_deploy": False, "allow_end_turn": False, "auto_launch_kards": False,
            "deck_name": "日本 初始", "mode": "casual", "max_rounds": 0})
        for flag in ("--adb-only", "--dry-run", "--no-attack", "--no-deploy",
                     "--no-end-turn", "--no-auto-launch"):
            self.assertIn(flag, argv)
        self.assertNotIn("--prefer-ipc", argv)
        self.assertEqual(argv[argv.index("--extra-serial") + 1], "127.0.0.1:5555")
        self.assertEqual(argv[argv.index("--deck") + 1], "日本 初始")

    def test_start_duplicate_stale_files_and_saved_overrides(self):
        manager.save_emu_options({"deck_name": "saved", "mode": "casual"}, self.root)
        self.mgr.logs_dir.mkdir()
        paths = self.mgr.worker_paths("mumu:7")
        paths["stop_file"].touch()
        paths["status_file"].write_text('{"running":true,"state":"old"}')
        result = self.mgr.start_instance("mumu:7", {"dry_run": True})
        self.assertTrue(result["ok"])
        self.assertEqual(result["pid"], 1234)
        self.assertIn("saved", result["argv"])
        self.assertIn("casual", result["argv"])
        self.assertIn("--dry-run", result["argv"])
        self.assertEqual(self.launches[0][2], {
            "cwd": str(self.root),
            "creationflags": subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0})
        self.assertEqual(self.mgr.start_instance("mumu:7"),
                         {"ok": False, "msg": "该实例已在运行中"})
        self.assertEqual(len(self.processes), 1)
        self.assertTrue(self.mgr.has_running_workers())
        self.processes[0].returncode = 7
        self.assertFalse(self.mgr.has_running_workers())
        self.assertTrue(self.mgr.start_instance("mumu:7")["ok"])

    def test_start_failure_and_slug_collision(self):
        self.fail_ids.add("bad")
        self.assertFalse(self.mgr.start_instance("bad")["ok"])
        self.assertNotIn("bad", self.mgr._workers)
        self.assertFalse(self.mgr.start_instance("invalid", {"mode": "bad"})["ok"])
        self.assertTrue(self.mgr.start_instance("mumu:7")["ok"])
        self.assertFalse(self.mgr.start_instance("mumu_7")["ok"])
        self.processes[-1].returncode = 0
        self.assertTrue(self.mgr.start_instance("mumu_7")["ok"])
        stop = self.mgr.worker_paths("mumu_7")["stop_file"]
        stop.write_text("stop\n")
        self.assertTrue(self.mgr.has_running_workers())
        self.assertTrue(stop.exists())

    def test_start_many_stagger_partial_failure_and_duplicates(self):
        self.fail_ids.add("bad")
        result = self.mgr.start_many(["bad", "mumu:7", "mumu:7", "bad", "mumu:8", "mumu:9"],
                                     {"stagger_seconds": .25})
        self.assertEqual(result["started"], ["mumu:7", "mumu:8", "mumu:9"])
        self.assertEqual(result["failed"], ["bad"])
        self.assertTrue(result["ok"])
        self.assertEqual(self.sleeps, [.25, .25])
        self.assertFalse(self.mgr.start_many(["bad"])["ok"])
        self.assertFalse(self.mgr.start_many([])["ok"])
        self.sleeps.clear()
        self.assertEqual(self.mgr.start_many(["mumu:10", "mumu:7"])["started"], ["mumu:10"])
        self.assertEqual(self.sleeps, [])

    def test_stop_cooperative_terminate_and_kill(self):
        self.assertEqual(self.mgr.stop_instance("absent"), {"ok": False, "msg": "该实例未在运行"})
        for behavior, code in (("cooperative", 0), ("terminate", -15), ("kill", -9)):
            with self.subTest(behavior=behavior):
                self.behavior = behavior
                self.mgr.start_instance("mumu:7")
                proc = self.processes[-1]
                proc.before_wait = lambda: self.assertEqual(proc.stop_file.read_text(), "stop\n")
                result = self.mgr.stop_instance("mumu:7", timeout=.01)
                self.assertEqual(result["exit_code"], code)
                self.assertFalse(proc.stop_file.exists())
                self.assertFalse(self.mgr.has_running_workers())
                events = [event[0] for event in proc.events]
                self.assertEqual("terminate" in events, behavior != "cooperative")
                self.assertEqual("kill" in events, behavior == "kill")

    def test_stop_all_signals_first_and_uses_shared_deadline(self):
        self.behavior = "kill"
        ids = ["mumu:7", "mumu:8", "mumu:9"]
        self.mgr.start_many(ids, {"stagger_seconds": 0})
        paths = [self.mgr.worker_paths(i)["stop_file"] for i in ids]
        now = [10.0]
        def before_wait():
            self.assertTrue(all(p.exists() for p in paths))
            now[0] += 1
        for proc in self.processes:
            proc.before_wait = before_wait
        with patch.object(manager.time, "monotonic", side_effect=lambda: now[0]):
            result = self.mgr.stop_all(timeout=2)
        self.assertEqual(result, {"ok": True, "stopped": ids})
        self.assertEqual([p.events[0][1] for p in self.processes], [2, 1, 0])
        self.assertTrue(all(not p.exists() for p in paths))
        self.assertEqual(self.mgr.stop_all(), {"ok": True, "stopped": []})

    def test_status_snapshot_disappeared_instance_and_reaped_exit(self):
        manager.save_emu_options({"extra_serials": ["saved:5555"]}, self.root)
        self.mgr.start_instance("mumu:7")
        self.mgr.start_instance("custom:lost")
        paths = self.mgr.worker_paths("mumu:7")
        status = dict(state="own_turn", rounds_done=3, victories=2, defeats=1, turns=18,
                      last_action="deploy", last_error="", backend="ipc", avg_capture_ms=24.5,
                      running=False, pid=99999)
        paths["status_file"].write_text(json.dumps(status), encoding="utf-8")
        paths["log_file"].write_text("one\ntwo\n", encoding="utf-8")
        snapshot = self.mgr.snapshot("mumu:7")
        self.discover.assert_called_with(extra_serials=["saved:5555"])
        self.assertEqual(snapshot["running_count"], 2)
        self.assertEqual(snapshot["log"]["lines"], ["one", "two"])
        rows = {i["instance_id"]: i for i in snapshot["instances"]}
        self.assertTrue(rows["custom:lost"]["worker_running"])
        row = rows["mumu:7"]
        self.assertTrue(row["worker_running"])
        self.assertEqual(row["worker_pid"], 1234)
        self.assertEqual(row["worker_state"], "own_turn")
        for key in ("rounds_done", "victories", "defeats", "turns", "last_action",
                    "last_error", "backend", "avg_capture_ms"):
            self.assertEqual(row[key], status[key])
        self.assertEqual(rows[self.instances[1].instance_id]["worker_state"], "idle")
        self.processes[0].returncode = 9
        self.processes[1].returncode = 0
        paths["stop_file"].touch()
        snapshot = self.mgr.snapshot(extra_serials=[])
        self.discover.assert_called_with(extra_serials=[])
        self.assertEqual(snapshot["running_count"], 0)
        self.assertIsNone(snapshot["log"])
        row = snapshot["instances"][0]
        self.assertEqual(row["worker_exit_code"], 9)
        self.assertIsNone(row["worker_pid"])
        self.assertFalse(paths["stop_file"].exists())
        paths["status_file"].write_text("{incomplete")
        self.assertEqual(self.mgr.list_instances()[0]["worker_state"], "idle")

    def test_tail_bounded_revision_cache_and_missing(self):
        self.assertEqual(self.mgr.tail_instance_log("absent"),
                         {"changed": False, "rev": "", "lines": []})
        self.mgr.logs_dir.mkdir()
        path = self.mgr.worker_paths("mumu:7")["log_file"]
        path.write_text("".join(f"line {i}\n" for i in range(1000)), encoding="utf-8")
        result = self.mgr.tail_instance_log("mumu:7", lines=2)
        self.assertEqual(result["lines"], ["line 998", "line 999"])
        with patch.object(manager.log_io, "tail_lines", side_effect=AssertionError("redundant read")):
            self.assertEqual(self.mgr.tail_instance_log("mumu:7", since_rev=result["rev"]),
                             {"changed": False, "rev": result["rev"], "lines": []})
        self.assertEqual(len(self.mgr.tail_instance_log("mumu:7", lines=99999)["lines"]), 400)
        with path.open("a", encoding="utf-8") as out:
            out.write("new\n")
        self.assertTrue(self.mgr.tail_instance_log("mumu:7", since_rev=result["rev"])["changed"])
        path.write_text("x" * 200000, encoding="utf-8")
        self.assertLess(len(self.mgr.tail_instance_log("mumu:7")["lines"][0]), 2200)

    def test_emulator_provider_delegation(self):
        provider = Mock()
        provider.name = "mumu"
        provider.launch.return_value = True
        provider.shutdown.return_value = False
        with patch.object(manager.emu_discovery, "MuMuProvider", return_value=provider):
            self.assertTrue(self.mgr.launch_emulator("mumu:7")["ok"])
            self.assertFalse(self.mgr.shutdown_emulator("mumu:7")["ok"])
        provider.launch.assert_called_once_with(self.instances[0])
        provider.shutdown.assert_called_once_with(self.instances[0])
        custom = Mock()
        custom.name = "custom"
        custom.launch.return_value = custom.shutdown.return_value = True
        instance = EmulatorInstance("custom", "custom:1", "Custom")
        self.instances.append(instance)
        with patch.object(manager.emu_discovery, "get_registered_providers", return_value=[custom]):
            self.assertTrue(self.mgr.launch_emulator("custom:1")["ok"])
            self.assertTrue(self.mgr.shutdown_emulator("custom:1")["ok"])
        custom.launch.assert_called_once_with(instance)
        custom.shutdown.assert_called_once_with(instance)
        self.mgr.providers = [custom]
        self.assertTrue(self.mgr.launch_emulator("custom:1")["ok"])
        self.assertFalse(self.mgr.launch_emulator("absent")["ok"])
        self.assertFalse(self.mgr.shutdown_emulator("adb:127.0.0.1:5555")["ok"])


if __name__ == "__main__":
    unittest.main()
