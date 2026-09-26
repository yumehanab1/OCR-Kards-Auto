"""面板配置持久化回归；使用临时目录，不启动游戏、不改真实配置。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import gui


class OptionsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patcher = patch.object(gui, "PROJECT_ROOT", self.temp.name)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_first_launch_and_restart(self):
        fresh = gui.Api()
        self.assertEqual(fresh.saved_options["max_rounds"], 3)
        self.assertFalse(fresh.saved_options["ranked"])
        opts = {s["key"]: False for s in gui.SWITCHES}
        opts.update(ranked=True, max_rounds="0")
        self.assertTrue(fresh.save_settings(opts)["ok"])
        restarted = gui.Api()
        self.assertEqual(restarted.saved_options, dict(opts, max_rounds=0))
        self.assertIsNone(restarted.proc)
        self.assertEqual(restarted.snapshot()["saved_options"], restarted.saved_options)
        self.assertEqual(json.loads(Path(gui.options_path()).read_text()), restarted.saved_options)

    def test_invalid_values_preserve_last_config(self):
        api = gui.Api()
        self.assertTrue(api.save_settings({"max_rounds": "99", "dry_run": True})["ok"])
        before = Path(gui.options_path()).read_bytes()
        for bad in ("", "-1", "100", "1.5", True, 3.5, None):
            self.assertFalse(api.save_settings({"max_rounds": bad})["ok"])
            self.assertEqual(Path(gui.options_path()).read_bytes(), before)
        self.assertFalse(api.save_settings({"ranked": "false"})["ok"])
        self.assertEqual(gui.Api().saved_options["max_rounds"], 99)

    def test_corrupt_and_old_config(self):
        path = Path(gui.options_path())
        path.parent.mkdir()
        for data in ("{", "[]", '{"ranked": "false"}'):
            path.write_text(data)
            self.assertEqual(gui.load_options(), gui.normalize_options({}))
        path.write_text('{"max_rounds": 7, "removed_option": true}', encoding="utf-8-sig")
        opts = gui.load_options()
        self.assertEqual(opts["max_rounds"], 7)
        self.assertNotIn("removed_option", opts)
        self.assertFalse(opts["ranked"])

    def test_write_failure_preserves_file_and_memory(self):
        api = gui.Api()
        api.save_settings({"max_rounds": 8})
        before = Path(gui.options_path()).read_bytes()
        with patch.object(gui.os, "replace", side_effect=PermissionError("read-only")):
            result = api.save_settings({"max_rounds": 9})
        self.assertFalse(result["ok"])
        self.assertIn("read-only", result["msg"])
        self.assertEqual(api.saved_options["max_rounds"], 8)
        self.assertEqual(Path(gui.options_path()).read_bytes(), before)
        self.assertEqual(list(Path(gui.options_path()).parent.glob("*.tmp")), [])

    def test_start_persists_without_launching_on_invalid_input(self):
        api = gui.Api()
        with patch.object(gui, "MAIN_LOOP", str(self.root / "missing.py")):
            self.assertFalse(api.start({"play": True, "max_rounds": "12"})["ok"])
        self.assertEqual(gui.Api().saved_options["max_rounds"], 12)
        with patch.object(gui.subprocess, "Popen") as launch:
            self.assertFalse(api.start({"max_rounds": "-1"})["ok"])
            launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
