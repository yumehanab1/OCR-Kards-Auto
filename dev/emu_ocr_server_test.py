"""Shared OCR HTTP, vision fallback and subprocess lifecycle regressions."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import http.client
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import Mock, patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "dev"))
sys.dont_write_bytecode = True

import emu_ocr_server as ocr
import emu_manager as manager
from emu_vision import EmuVision
from emu_manager_test import FakeProcess

ITEMS = [[[1, 2, 30, 40], "共享 OCR", .95]]


class SharedServerTests(unittest.TestCase):
    def setUp(self):
        self.frame = np.full((48, 64, 3), (10, 20, 30), np.uint8)
        self.infer = Mock(return_value=ITEMS)
        self.server = ocr.SharedOcrServer(token="test-secret", ocr_fn=self.infer)
        self.thread = self.server.start_in_thread()
        self.addCleanup(self.server.stop)

    def request(self, method, path, body=None, token="test-secret", headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        try:
            values = {} if token is None else {"X-OCR-Token": token}
            values.update(headers or {})
            conn.request(method, path, body=body, headers=values)
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()

    def test_loopback_only_token_generation_and_authentication(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        for host in ("0.0.0.0", "localhost", "::1", "192.168.1.1"):
            with self.assertRaises(ValueError):
                ocr.SharedOcrServer(host=host)
        for token in (None, "wrong"):
            for method, path in (("GET", "/health"), ("POST", "/ocr"), ("POST", "/shutdown")):
                self.assertEqual(self.request(method, path, token=token)[0], 403)
        with patch.dict(os.environ, {"KARDS_EMU_OCR_TOKEN": "env-secret"}):
            server = ocr.SharedOcrServer()
            try:
                self.assertEqual(server.token, "env-secret")
            finally:
                server.stop()
        with patch.dict(os.environ, {"KARDS_EMU_OCR_TOKEN": ""}):
            servers = [ocr.SharedOcrServer(), ocr.SharedOcrServer()]
            try:
                self.assertNotEqual(servers[0].token, servers[1].token)
                self.assertGreaterEqual(len(servers[0].token), 32)
            finally:
                for server in servers:
                    server.stop()

    def test_health_ocr_fast_png_and_proxy_bypass(self):
        self.assertEqual(self.request("GET", "/health"), (200, {"ok": True, "calls": 0}))
        proxy = {key: "http://127.0.0.1:1" for key in
                 ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")}
        proxy.update(NO_PROXY="", no_proxy="")
        with patch.dict(os.environ, proxy), patch.object(cv2, "imencode", wraps=cv2.imencode) as encode:
            self.assertEqual(ocr.request_ocr(self.server.url, self.server.token, self.frame), ITEMS)
        self.assertEqual(encode.call_args.args[0], ".png")
        self.assertEqual(encode.call_args.args[2], [cv2.IMWRITE_PNG_COMPRESSION, 1])
        np.testing.assert_array_equal(self.infer.call_args.args[0], self.frame)
        self.assertEqual(self.request("GET", "/health"), (200, {"ok": True, "calls": 1}))
        jpeg = cv2.imencode(".jpg", self.frame)[1].tobytes()
        self.assertEqual(self.request("POST", "/ocr", jpeg), (200, {"ok": True, "items": ITEMS}))

    def test_body_limits_invalid_images_and_inference_failure(self):
        self.assertEqual(self.request("POST", "/ocr", b"", headers={"Content-Length": str(ocr.MAX_BODY + 1)})[0], 413)
        for length in ("invalid", "-1"):
            self.assertEqual(self.request("POST", "/ocr", b"", headers={"Content-Length": length})[0], 400)
        for body in (b"", b"not an image"):
            self.assertEqual(self.request("POST", "/ocr", body)[0], 400)
        self.assertEqual(self.request("GET", "/missing")[0], 404)
        self.infer.assert_not_called()
        self.infer.side_effect = RuntimeError("model failed")
        with self.assertRaises(OSError):
            ocr.request_ocr(self.server.url, self.server.token, self.frame)
        self.assertEqual(self.request("GET", "/health")[1]["calls"], 0)

    def test_serialized_inference_for_concurrent_workers(self):
        active = threading.Lock()
        entered, release = threading.Event(), threading.Event()
        calls = []

        def infer(frame):
            self.assertTrue(active.acquire(blocking=False), "Concurrent inference")
            try:
                calls.append(1)
                entered.set()
                self.assertTrue(release.wait(2))
                return ITEMS
            finally:
                active.release()

        self.server.ocr_fn = infer
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(ocr.request_ocr, self.server.url, self.server.token, self.frame) for _ in range(3)]
            try:
                self.assertTrue(entered.wait(2))
                self.assertEqual(len(calls), 1)
            finally:
                release.set()
            self.assertEqual([f.result() for f in futures], [ITEMS] * 3)
        self.assertEqual(self.server.calls, 3)

    def test_lazy_single_rapidocr_model_and_box_conversion(self):
        self.server.ocr_fn = None
        raw = [[np.array([[1, 2], [30, 3], [29, 40], [2, 39]]), "shared", np.float32(.5)]]
        factory = Mock(return_value=Mock(return_value=(raw, None)))
        with patch.dict(sys.modules, {"rapidocr_onnxruntime": Mock(RapidOCR=factory)}):
            factory.assert_not_called()
            for _ in range(2):
                self.assertEqual(ocr.request_ocr(self.server.url, self.server.token, self.frame),
                                 [[[1, 2, 30, 40], "shared", .5]])
            factory.assert_called_once_with(intra_op_num_threads=2, inter_op_num_threads=1)
            self.assertEqual(factory.return_value.call_count, 2)

    def test_shutdown_closes_listener_and_stop_is_idempotent(self):
        self.assertEqual(self.request("POST", "/shutdown"), (200, {"ok": True}))
        self.thread.join(2)
        self.assertFalse(self.thread.is_alive())
        self.server.stop()
        self.server.stop()
        with self.assertRaises(OSError):
            ocr.request_ocr(self.server.url, self.server.token, self.frame, timeout=.2)

    def test_client_rejects_non_loopback_urls_and_http_errors(self):
        for url in ("http://localhost:80", "http://example.com:80", "https://127.0.0.1:80",
                    "http://user@127.0.0.1:80", "http://127.0.0.1:80/path"):
            with self.assertRaises(ValueError):
                ocr.request_ocr(url, "secret", self.frame)
        with self.assertRaises(OSError):
            ocr.request_ocr(self.server.url, "wrong", self.frame)

    def test_vision_shared_and_local_fallback_after_shutdown(self):
        vision = EmuVision(load_core=False, ocr_url=self.server.url, ocr_token=self.server.token)
        self.assertEqual(vision.run_ocr(self.frame), ITEMS)
        self.assertIsNone(vision._ocr)
        self.server.stop()
        local = Mock(return_value=([[[(1, 2), (3, 2), (3, 4), (1, 4)], "local", .9]], None))
        factory = Mock(return_value=local)
        with patch.dict(sys.modules, {"rapidocr_onnxruntime": Mock(RapidOCR=factory)}):
            self.assertEqual(vision.run_ocr(self.frame), [((1, 2, 3, 4), "local", .9)])
            self.assertEqual(vision.run_ocr(self.frame), [((1, 2, 3, 4), "local", .9)])
            factory.assert_called_once_with(intra_op_num_threads=2, inter_op_num_threads=1)

    def test_vision_environment_and_injected_function_precedence(self):
        with patch.dict(os.environ, {"KARDS_EMU_OCR_URL": self.server.url,
                                     "KARDS_EMU_OCR_TOKEN": self.server.token}):
            vision = EmuVision(load_core=False)
            self.assertEqual(vision.run_ocr(self.frame), ITEMS)
            injected = Mock(return_value=[])
            vision = EmuVision(load_core=False, ocr_fn=injected, ocr_url="http://invalid")
            self.assertIsNone(vision.ocr_url)
            self.assertEqual(vision.run_ocr(self.frame), [])
            injected.assert_called_once_with(self.frame)
            self.assertEqual(self.server.calls, 1)


class ManagerOcrTests(unittest.TestCase):
    def setUp(self):
        # Inherit the temp parent's ACL, as in emu_manager_test.py.
        self.root = Path(tempfile.gettempdir()) / ("shared-ocr-test-" + uuid.uuid4().hex)
        self.root.mkdir()
        self.addCleanup(self.cleanup)
        self.workers, self.launches, self.servers = [], [], []
        self.mgr = manager.EmuManager(self.root, python_exe=sys.executable,
                                      discover_fn=lambda **kw: [], popen_fn=self.worker_popen,
                                      ocr_popen_fn=self.ocr_popen, sleep_fn=lambda _: None)
        self.addCleanup(self.mgr.stop_all)

    def cleanup(self):
        root = self.root.resolve()
        self.assertEqual(root.parent, Path(tempfile.gettempdir()).resolve())
        for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            self.assertTrue(path.resolve().is_relative_to(root))
            path.rmdir() if path.is_dir() else path.unlink()
        root.rmdir()

    def worker_popen(self, argv, **kwargs):
        proc = FakeProcess(argv)
        self.workers.append(proc)
        self.launches.append((argv, kwargs))
        return proc

    def ocr_popen(self, argv, **kwargs):
        self.assertEqual(argv, [sys.executable, "-B", str(self.root / "src/emu_ocr_server.py")])
        self.assertNotIn(kwargs["env"]["KARDS_EMU_OCR_TOKEN"], argv)
        proc = subprocess.Popen([*argv[:2], str(ROOT / "src/emu_ocr_server.py")], **kwargs)
        self.servers.append(proc)
        return proc

    def test_starts_once_injects_env_and_stops_all(self):
        started = self.mgr.start_many(["ldplayer:0", "bluestacks:Pie64"], {"stagger_seconds": 0})
        self.assertEqual(started["started"], ["ldplayer:0", "bluestacks:Pie64"])
        self.assertEqual(len(self.servers), 1)
        self.assertTrue(self.mgr.snapshot()["shared_ocr_running"])
        for argv, kwargs in self.launches:
            self.assertEqual(kwargs["env"]["KARDS_EMU_OCR_URL"], self.mgr._ocr_url)
            self.assertEqual(kwargs["env"]["KARDS_EMU_OCR_TOKEN"], self.mgr._ocr_token)
            self.assertNotIn(self.mgr._ocr_token, argv)
        conn = ocr.localhost_connection(self.mgr._ocr_url, timeout=2)
        try:
            conn.request("GET", "/health", headers={"X-OCR-Token": self.mgr._ocr_token})
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read()), {"ok": True, "calls": 0})
        finally:
            conn.close()
        self.assertTrue(self.mgr.stop_all()["ok"])
        self.assertEqual(self.servers[0].poll(), 0)
        self.assertTrue(self.servers[0].stdout.closed)
        self.assertFalse(self.mgr.snapshot()["shared_ocr_running"])

    def test_reap_last_worker_and_restart_new_session(self):
        self.mgr.start_many(["ldplayer:0", "ldplayer:1"], {"stagger_seconds": 0})
        token = self.mgr._ocr_token
        self.workers[0].returncode = 0
        self.assertTrue(self.mgr.snapshot()["shared_ocr_running"])
        self.workers[1].returncode = 0
        self.assertFalse(self.mgr.snapshot()["shared_ocr_running"])
        self.assertEqual(self.servers[0].poll(), 0)
        self.mgr.start_instance("ldplayer:0")
        self.assertEqual(len(self.servers), 2)
        self.assertNotEqual(token, self.mgr._ocr_token)

    def test_shared_disabled_strips_inherited_session(self):
        with patch.dict(os.environ, {"KARDS_EMU_OCR_URL": "stale", "KARDS_EMU_OCR_TOKEN": "stale"}):
            self.assertTrue(self.mgr.start_instance("ldplayer:0", {"shared_ocr": False})["ok"])
        self.assertEqual(self.servers, [])
        for key in ("KARDS_EMU_OCR_URL", "KARDS_EMU_OCR_TOKEN"):
            self.assertNotIn(key, self.launches[0][1]["env"])

    def test_custom_worker_launcher_without_ocr_factory_is_unchanged(self):
        self.mgr.ocr_popen_fn = None
        self.assertTrue(self.mgr.start_instance("ldplayer:0")["ok"])
        self.assertEqual(self.servers, [])
        self.assertFalse(self.mgr.snapshot()["shared_ocr_running"])

    def test_server_start_failure_does_not_block_worker(self):
        self.mgr.ocr_popen_fn = Mock(side_effect=OSError("cannot launch"))
        with self.assertLogs("emu_manager", "WARNING"):
            self.assertTrue(self.mgr.start_instance("ldplayer:0")["ok"])
        self.assertFalse(self.mgr.snapshot()["shared_ocr_running"])
        self.assertNotIn("env", self.launches[0][1])

    def test_invalid_handshake_terminates_then_kills_and_closes_pipe(self):
        proc = Mock(stdout=io.BytesIO(b'{"ready":true,"url":"http://0.0.0.0:1234"}\n'))
        proc.poll.return_value = None
        proc.wait.side_effect = [subprocess.TimeoutExpired("ocr", .5), 0]
        self.mgr.ocr_popen_fn = Mock(return_value=proc)
        with self.assertLogs("emu_manager", "WARNING"):
            self.assertTrue(self.mgr.start_instance("ldplayer:0")["ok"])
        proc.terminate.assert_called_once()
        proc.kill.assert_called_once()
        self.assertTrue(proc.stdout.closed)
        self.assertFalse(self.mgr.snapshot()["shared_ocr_running"])

    def test_worker_spawn_failure_does_not_leak_server(self):
        self.mgr.popen_fn = Mock(side_effect=OSError("worker failed"))
        self.assertFalse(self.mgr.start_instance("ldplayer:0")["ok"])
        self.assertEqual(len(self.servers), 1)
        self.assertEqual(self.servers[0].poll(), 0)

    def test_startup_timeout_is_bounded_and_child_is_reaped(self):
        def hung_popen(argv, **kwargs):
            proc = subprocess.Popen([sys.executable, "-B", "-c", "import time; time.sleep(60)"], **kwargs)
            self.servers.append(proc)
            return proc
        self.mgr.ocr_popen_fn = hung_popen
        start = time.monotonic()
        with self.assertLogs("emu_manager", "WARNING"):
            self.assertTrue(self.mgr.start_instance("ldplayer:0")["ok"])
        self.assertLess(time.monotonic() - start, 8)
        self.assertIsNotNone(self.servers[0].poll())
        self.assertTrue(self.servers[0].stdout.closed)


if __name__ == "__main__":
    unittest.main()
