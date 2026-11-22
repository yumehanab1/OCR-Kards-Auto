r"""Offline Phase 1 tests. Run: .\python\python.exe -B dev/emu_transport_test.py"""
from __future__ import annotations

import ctypes as ct
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import cv2
import numpy as np
import emu_discovery as discovery
import emu_transport as transport
from emu_discovery import EmulatorInstance, EmulatorProvider
from emu_transport import AdbTransport, EmuTransportError, MuMuIpcTransport


def result(stdout="", code=0, stderr=""):
    return subprocess.CompletedProcess([], code, stdout, stderr)


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.registry = patch.dict(discovery._providers, {}, clear=True)
        self.registry.start()
        self.addCleanup(self.registry.stop)

    def mumu(self, data):
        runner = Mock(return_value=result(json.dumps(data)))
        with patch.object(Path, "is_file", return_value=True):
            provider = discovery.MuMuProvider("test-root", runner=runner)
        return provider, runner

    def test_mumu_shapes_and_lifecycle(self):
        vm = dict(index="7", name="Android 15", adb_host_ip="127.0.0.1", adb_port="16384",
                  is_android_started=True, is_process_started=True, android_version="15")
        for data in [vm, {"7": vm, "2": dict(index=2, name="Stopped", adb_port=0)}]:
            with self.subTest(data=data):
                provider, runner = self.mumu(data)
                instances = provider.discover()
                item = instances[0]
                self.assertEqual(item.instance_id, "mumu:7")
                self.assertEqual(item.adb_serial, "127.0.0.1:16384")
                self.assertTrue(item.running and item.process_started and item.ipc_available)
                self.assertEqual(item.android_version, "15")
                self.assertEqual(item.to_dict()["mumu_index"], 7)
                self.assertTrue(item.extra['can_launch'] and item.extra['can_shutdown'])
                self.assertEqual(runner.call_args.args[0][1:], ["info", "-v", "all"])
                self.assertEqual(runner.call_args.kwargs["creationflags"],
                                 subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                if len(instances) == 2:
                    self.assertIsNone(instances[1].adb_serial)
                    self.assertFalse(instances[1].running)
                runner.return_value = result('{"errcode": 0}')
                self.assertTrue(provider.launch(item))
                self.assertEqual(runner.call_args.args[0][1:], ["control", "-v", "7", "launch"])
                self.assertTrue(provider.shutdown(item))
                self.assertEqual(runner.call_args.args[0][-1], "shutdown")
                runner.return_value = result('{"errcode": 1}')
                self.assertFalse(provider.launch(item))
                self.assertFalse(provider.shutdown(item))
                runner.return_value = result("")
                self.assertTrue(provider.launch(item))
                self.assertFalse(provider.shutdown(item))

    def test_mumu_path_candidates(self):
        for relative in discovery.MuMuProvider.DLLS:
            with self.subTest(relative=relative), patch.dict(os.environ, {"MUMU_ROOT": "env-root"}), \
                    patch.object(Path, "is_file", lambda p: p.as_posix() in {
                        "env-root/shell/MuMuManager.exe", "env-root/shell/adb.exe", f"env-root/{relative}"}):
                provider = discovery.MuMuProvider()
                self.assertEqual(provider.mumu_root, "env-root")
                self.assertEqual(Path(provider.ipc_dll_path).as_posix(), f"env-root/{relative}")

    def test_generic_devices_and_connect(self):
        output = ("List of devices attached\n127.0.0.1:5555 device product:p model:LD_Player transport_id:1\n"
                  "emulator-5554 offline\na unauthorized\nb authorizing\n\n")
        runner = Mock(side_effect=[OSError("connect failed"), result(output)])
        items = discovery.GenericAdbProvider("adb.exe", ("127.0.0.1:5555",), runner).discover()
        self.assertEqual(runner.call_args_list[0].args[0], ["adb.exe", "connect", "127.0.0.1:5555"])
        self.assertEqual(items[0].name, "LD_Player")
        self.assertEqual([i.running for i in items], [True, False, False, False])
        self.assertEqual([i.process_started for i in items], [True, True, False, True])

    def test_dedupe_sort_and_registry(self):
        class Provider(EmulatorProvider):
            name = "custom"

            def discover(self):
                return [EmulatorInstance("custom", "custom:1", "Custom")]

        custom = Provider()
        discovery.register_provider(custom)
        self.assertEqual(discovery.get_registered_providers(), [custom])
        self.assertFalse(custom.launch(custom.discover()[0]))
        mumu = [EmulatorInstance("mumu", f"mumu:{n}", "VM", adb_serial=f"host:{n}",
                                 mumu_index=n, running=True) for n in (10, 2)]
        adb = [EmulatorInstance("adb", "adb:host:2", "Duplicate", adb_serial="host:2", running=True)]
        with patch.object(discovery.MuMuProvider, "discover", return_value=mumu), \
                patch.object(discovery.GenericAdbProvider, "discover", return_value=adb):
            items = discovery.discover_all()
        self.assertEqual([i.instance_id for i in items], ["mumu:2", "mumu:10", "custom:1"])
        items = discovery.discover_all(providers=[Mock(discover=lambda: adb), Mock(discover=lambda: mumu)])
        self.assertEqual(len(items), 2)

    def test_ldplayer_list2_and_controls(self):
        output = ('0," Main, VM ",1,2,1,123,456,1280,720,240\n'
                  '2, ,0,0,0,789,0\n3,Stopped,0,0,0,bad,0\n'
                  'index,title,top,bind,running,pid,vbox\nbad\n')
        runner = Mock(return_value=result(output))
        with patch.object(Path, "is_file", return_value=True):
            provider = discovery.LDPlayerProvider("ld-root", runner)
        items = provider.discover()
        self.assertEqual([i.instance_id for i in items], ["ldplayer:0", "ldplayer:2", "ldplayer:3"])
        self.assertEqual(items[0].name, "Main, VM")
        self.assertEqual(items[1].name, "LDPlayer 2")
        self.assertEqual(items[1].adb_serial, "127.0.0.1:5559")
        self.assertEqual(items[1].extra, {"ld_index": 2, "ld_root": "ld-root",
                                        "controllable": True, "can_launch": True, "can_shutdown": True,
                                        "alt_serial": "emulator-5558", "pid": 789})
        self.assertEqual([i.running for i in items], [True, False, False])
        self.assertEqual([i.process_started for i in items], [True, True, False])
        self.assertTrue(all(not i.ipc_available for i in items))
        self.assertEqual(Path(items[0].adb_path).name, "adb.exe")
        self.assertEqual(runner.call_args.args[0], [provider.console_path, "list2"])
        runner.return_value = result()
        self.assertTrue(provider.launch(items[1]))
        self.assertEqual(runner.call_args.args[0], [provider.console_path, "launch", "--index", "2"])
        self.assertTrue(provider.shutdown(items[1]))
        self.assertEqual(runner.call_args.args[0], [provider.console_path, "quit", "--index", "2"])
        runner.return_value = result(code=1)
        self.assertEqual(provider.discover(), [])
        self.assertFalse(provider.launch(items[0]))
        runner.side_effect = OSError("not usable")
        self.assertEqual(provider.discover(), [])

    def test_ldplayer_root_detection_and_absence(self):
        with patch.dict(os.environ, {"LDPLAYER_ROOT": "env-ld"}), \
                patch.object(Path, "is_file", lambda p: p.as_posix() in
                             {"env-ld/dnconsole.exe", "env-ld/adb.exe"}):
            provider = discovery.LDPlayerProvider()
            self.assertEqual(provider.ld_root, "env-ld")
            self.assertEqual(Path(provider.console_path).name, "dnconsole.exe")
        with patch.object(Path, "is_file", return_value=False):
            runner = Mock()
            self.assertEqual(discovery.LDPlayerProvider(runner=runner).discover(), [])
            self.assertEqual(discovery.BlueStacksProvider(runner=runner).discover(), [])
            runner.assert_not_called()

    def bluestacks(self):
        conf = ('bst.instance.Nougat32.display_name="Main BlueStacks"\n'
                'bst.instance.Nougat32.status.adb_port="5555"\n'
                'bst.instance.Pie64.status.adb_port="5565"\n'
                'bst.instance.Bad.status.adb_port="bad"\n'
                'bst.instance.Zero.status.adb_port="0"\n'
                'bst.instance.Negative.status.adb_port="-1"\n'
                'bst.instance.NoPort.display_name="Missing"\n')
        runner = Mock(return_value=result("List of devices attached\n127.0.0.1:5555 device\n127.0.0.1:5565 offline\n"))
        with patch.object(Path, "is_file", return_value=True):
            provider = discovery.BlueStacksProvider("test.conf", runner)
        with patch.object(Path, "read_text", return_value=conf):
            items = provider.discover()
        return provider, runner, items, conf

    def test_bluestacks_config_online_and_launch(self):
        provider, runner, items, conf = self.bluestacks()
        self.assertEqual([i.instance_id for i in items], ["bluestacks:Nougat32", "bluestacks:Pie64"])
        self.assertEqual([i.name for i in items], ["Main BlueStacks", "BlueStacks Pie64"])
        self.assertEqual([i.running for i in items], [True, False])
        self.assertEqual([i.process_started for i in items], [True, False])
        self.assertEqual(items[0].extra, {"bs_instance": "Nougat32", "player_path": provider.player_path,
                                         "controllable": True, "can_launch": True, "can_shutdown": False,
                                         "conf_path": "test.conf"})
        runner.assert_called_once()
        self.assertEqual(runner.call_args.args[0], [provider.adb_path, "devices"])
        with patch.object(Path, "is_file", return_value=True), patch.object(discovery.subprocess, "Popen") as launch:
            self.assertTrue(provider.launch(items[0]))
            self.assertEqual(launch.call_args.args[0], [provider.player_path, "--instance", "Nougat32"])
            launch.return_value.wait.assert_not_called()
        provider.player_path = None
        self.assertFalse(provider.launch(items[0]))
        self.assertFalse(provider.shutdown(items[0]))
        for unavailable in (None, OSError("adb missing")):
            runner.reset_mock()
            if unavailable is None:
                provider.adb_path = None
            else:
                provider.adb_path = "adb.exe"
                runner.side_effect = unavailable
            with patch.object(Path, "read_text", return_value=conf):
                stopped = provider.discover()
                self.assertTrue(all(not i.running for i in stopped))
                self.assertTrue(all(not i.extra['can_launch'] and not i.extra['can_shutdown'] for i in stopped))
            if unavailable is None:
                runner.assert_not_called()

    def test_dedicated_serial_and_ld_alias_dedupe_in_either_order(self):
        with patch.object(Path, "is_file", return_value=True):
            ld = discovery.LDPlayerProvider("ld", Mock(return_value=result("0,LD,0,0,1,1,1")))
        bs, _, bs_items, _ = self.bluestacks()
        dedicated = [*ld.discover(), replace(bs_items[1], running=True, process_started=True)]
        generic = discovery.GenericAdbProvider("adb.exe", runner=Mock(return_value=result(
            "127.0.0.1:5555 device\nemulator-5554 device\n127.0.0.1:5565 device\nusb device\n")))
        for providers in ([Mock(discover=lambda: dedicated), generic],
                          [generic, Mock(discover=lambda: dedicated)]):
            items = discovery.discover_all(providers=providers)
            self.assertEqual({i.instance_id for i in items}, {"ldplayer:0", "bluestacks:Pie64", "adb:usb"})

    def test_stopped_dedicated_instance_never_hides_live_adb(self):
        for provider in ('mumu', 'ldplayer', 'bluestacks'):
            for alias in (False, True):
                for running, started in ((False, False), (True, False), (False, True)):
                    dedicated = EmulatorInstance(provider, provider + ':0', 'VM',
                        adb_serial='host:5555', running=running, process_started=started,
                        extra={'alt_serial': 'emulator-5554'})
                    serial = 'emulator-5554' if alias else 'host:5555'
                    generic = EmulatorInstance('adb', 'adb:' + serial, 'Generic',
                                               adb_serial=serial, running=True)
                    for order in ([dedicated, generic], [generic, dedicated]):
                        with self.subTest(provider=provider, alias=alias, running=running, started=started):
                            items = discovery.discover_all(providers=[Mock(discover=lambda: order)])
                            self.assertEqual(generic in items, not (running or started))

    def test_default_discovery_isolates_failures_explicit_callers_still_raise(self):
        good = EmulatorInstance("custom", "custom:1", "Custom")
        discovery.register_provider(Mock(name="custom", discover=Mock(return_value=[good])))
        with patch.object(discovery.MuMuProvider, "discover", side_effect=RuntimeError("mumu failed")), \
                patch.object(discovery.LDPlayerProvider, "discover", side_effect=OSError("ld failed")), \
                patch.object(discovery.BlueStacksProvider, "discover", return_value=[]), \
                patch.object(discovery.GenericAdbProvider, "discover", return_value=[]):
            self.assertEqual(discovery.discover_all(), [good])
        for provider in (discovery.MuMuProvider(), discovery.GenericAdbProvider("adb.exe")):
            with patch.object(provider, "discover", side_effect=RuntimeError("explicit")), self.assertRaises(RuntimeError):
                discovery.discover_all(providers=[provider])


class FakeDll:
    def __init__(self):
        self.size = (1280, 720)
        self.buffers = []
        self.nemu_connect = Mock(return_value=17)
        self.nemu_disconnect = Mock()
        self.nemu_capture_display = Mock(side_effect=self.capture)
        self.nemu_input_event_touch_down = Mock(return_value=0)
        self.nemu_input_event_touch_up = Mock(return_value=0)

    def capture(self, handle, display, length, wp, hp, pixels):
        w, h = self.size
        ct.cast(wp, ct.POINTER(ct.c_int))[0] = w
        ct.cast(hp, ct.POINTER(ct.c_int))[0] = h
        if length:
            self.buffers.append(pixels)
            rgba = np.ctypeslib.as_array(pixels).reshape(h, w, 4)
            rgba[:h // 2] = (10, 20, 30, 255)  # OpenGL bottom half
            rgba[h // 2:] = (70, 80, 90, 255)
        return 0


class IpcTests(unittest.TestCase):
    def test_connect_paired_adb_best_effort(self):
        for failure in (None, EmuTransportError("ADB disabled")):
            with self.subTest(failure=failure):
                dll = FakeDll()
                adb = Mock(spec=AdbTransport)
                adb.connect.side_effect = failure
                ipc = MuMuIpcTransport("root", 7, "fake.dll", adb_transport=adb,
                                       dll_loader=lambda _: dll)
                try:
                    ipc.connect()
                    ipc.connect()
                    adb.connect.assert_called_once_with()
                    dll.nemu_connect.assert_called_once_with("root", 7)
                    self.assertEqual(ipc.capture_bgr().shape, (720, 1280, 3))
                finally:
                    ipc.close()

    def setUp(self):
        self.dll = FakeDll()
        self.sleep = Mock()
        self.ipc = MuMuIpcTransport("root", 7, "fake.dll", dll_loader=lambda _: self.dll,
                                    sleep_fn=self.sleep)
        self.ipc.connect()
        self.addCleanup(self.ipc.close)

    def test_connection_signatures_and_close(self):
        self.dll.nemu_connect.assert_called_once_with("root", 7)
        self.assertEqual(self.dll.nemu_connect.argtypes, [ct.c_wchar_p, ct.c_int])
        self.assertEqual(self.dll.nemu_capture_display.argtypes[-1], ct.c_void_p)
        self.ipc.connect()
        self.dll.nemu_connect.assert_called_once()
        self.ipc.close()
        self.ipc.close()
        self.dll.nemu_disconnect.assert_called_once_with(17)
        with self.assertRaises(EmuTransportError):
            self.ipc.capture_bgr()

    def test_capture_orientation_colors_reuse_and_resize(self):
        first = self.ipc.capture_bgr()
        np.testing.assert_array_equal(first[0, 0], [90, 80, 70])
        np.testing.assert_array_equal(first[-1, -1], [30, 20, 10])
        self.ipc.capture_bgr()
        self.assertIs(self.dll.buffers[0], self.dll.buffers[1])
        self.dll.size = (1920, 1080)
        resized = self.ipc.capture_bgr()
        self.assertIsNot(self.dll.buffers[1], self.dll.buffers[2])
        self.assertEqual(self.ipc.last_native_size, (1920, 1080))
        self.assertEqual(resized.shape, (720, 1280, 3))
        self.assertEqual(resized.dtype, np.uint8)
        np.testing.assert_array_equal(resized[0, 0], [90, 80, 70])
        np.testing.assert_array_equal(resized[-1, -1], [30, 20, 10])
        np.testing.assert_array_equal(first[0, 0], [90, 80, 70])

    def test_tap_and_drag(self):
        self.ipc.last_native_size = (1920, 1080)
        self.ipc.tap(1279, 719)
        self.dll.nemu_input_event_touch_down.assert_called_with(17, 0, 1919, 1079)
        self.sleep.assert_called_with(0.06)
        self.dll.nemu_input_event_touch_up.assert_called_once_with(17, 0)
        self.dll.nemu_input_event_touch_down.reset_mock()
        self.sleep.reset_mock()
        self.ipc.drag([(0, 0), (1279, 0), (1279, 719)], 96)
        coordinates = [c.args[2:] for c in self.dll.nemu_input_event_touch_down.call_args_list]
        self.assertEqual(coordinates[0], (0, 0))
        self.assertEqual(coordinates[-1], (1919, 1079))
        self.assertIn((1919, 0), coordinates)
        self.assertGreater(len(coordinates), 3)
        self.assertAlmostEqual(sum(c.args[0] for c in self.sleep.call_args_list), 0.126)

    def test_release_on_down_and_sleep_error(self):
        for operation in [lambda: self.ipc.tap(4, 5),
                          lambda: self.ipc.drag([(0, 0), (20, 0), (20, 20)])]:
            for fault in ("down", "sleep"):
                with self.subTest(fault=fault):
                    self.dll.nemu_input_event_touch_up.reset_mock()
                    self.dll.nemu_input_event_touch_down.return_value = 1 if fault == "down" else 0
                    self.sleep.side_effect = RuntimeError("sleep failure") if fault == "sleep" else None
                    with self.assertRaises((EmuTransportError, RuntimeError)):
                        operation()
                    self.dll.nemu_input_event_touch_up.assert_called_once_with(17, 0)

    def test_serialized_touch(self):
        entered, release = threading.Event(), threading.Event()
        self.ipc._sleep = lambda _: (entered.set(), release.wait(2))
        worker = threading.Thread(target=self.ipc.tap, args=(1, 1))
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            self.assertFalse(self.ipc._lock.acquire(blocking=False))
        finally:
            release.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())

    def test_adb_delegation(self):
        adb = Mock(spec=AdbTransport)
        adb.get_foreground_package.return_value = transport.KARDS_PACKAGES[0]
        adb.is_kards_foreground.return_value = (True, transport.KARDS_PACKAGES[0])
        self.ipc.adb = adb
        self.ipc.list_packages("kards")
        adb.list_packages.assert_called_once_with("kards")
        self.assertEqual(self.ipc.is_kards_foreground(), (True, transport.KARDS_PACKAGES[0]))
        adb.is_kards_foreground.assert_called_once_with(transport.KARDS_PACKAGES)
        self.ipc.launch_kards()
        adb.launch_kards.assert_called_once_with(None)
        self.ipc.force_stop_package("pkg")
        adb.force_stop_package.assert_called_once_with("pkg")
        adb.resolve_kards_package.return_value = transport.KARDS_PACKAGES[1]
        self.assertEqual(self.ipc.resolve_kards_package(), transport.KARDS_PACKAGES[1])
        adb.resolve_kards_package.assert_called_once_with()


class AdbTests(unittest.TestCase):
    def setUp(self):
        self.runner = Mock(return_value=result())
        self.adb = AdbTransport("host:5555", "adb.exe", runner=self.runner)

    def test_connect(self):
        self.runner.side_effect = [result("connected"), result("device\n")]
        self.adb.connect()
        self.assertEqual(self.runner.call_args_list[0].args[0], ["adb.exe", "connect", "host:5555"])
        self.assertEqual(self.runner.call_args.args[0], ["adb.exe", "-s", "host:5555", "get-state"])
        self.runner.side_effect = [result(), result("offline")]
        with self.assertRaises(EmuTransportError):
            self.adb.connect()

    def test_missing_device_reconnects_once(self):
        for binary in (False, True):
            for error in ("device 'host:5555' not found", "device OFFLINE"):
                with self.subTest(binary=binary, error=error):
                    self.runner.reset_mock()
                    stderr = error.encode() if binary else error
                    output = b"png bytes" if binary else "ready"
                    self.runner.side_effect = [result(code=1, stderr=stderr),
                                               result("already connected to host:5555"),
                                               result(output)]
                    args = ["exec-out", "screencap", "-p"] if binary else ["get-state"]
                    self.assertEqual(self.adb._run(args, binary=binary, timeout=23), output)
                    calls = self.runner.call_args_list
                    self.assertEqual([c.args[0] for c in calls], [
                        ["adb.exe", "-s", "host:5555"] + args,
                        ["adb.exe", "connect", "host:5555"],
                        ["adb.exe", "-s", "host:5555"] + args])
                    self.assertEqual(calls[0].kwargs, calls[2].kwargs)
                    self.assertEqual(calls[2].kwargs["timeout"], 23)

    def test_reconnect_does_not_loop(self):
        failure = result(code=1, stderr="device 'host:5555' not found")
        self.runner.side_effect = [failure, result("unable to connect"), failure]
        with self.assertRaises(EmuTransportError):
            self.adb._run(["get-state"])
        self.assertEqual(self.runner.call_count, 3)

    def test_reconnect_only_for_targeted_network_device_errors(self):
        for serial, targeted, retry, error in (
                ("emulator-5554", True, True, "device not found"),
                ("host:5555", False, True, "device offline"),
                ("host:5555", True, False, "device not found"),
                ("host:5555", True, True, "unauthorized")):
            with self.subTest(serial=serial, targeted=targeted, retry=retry, error=error):
                runner = Mock(return_value=result(code=1, stderr=error))
                adb = AdbTransport(serial, "adb.exe", runner=runner)
                with self.assertRaises(EmuTransportError):
                    adb._run(["get-state"], targeted=targeted, _retry_connect=retry)
                runner.assert_called_once()

    def test_png_capture_and_invalid(self):
        frame = np.full((1080, 1920, 3), (12, 34, 56), np.uint8)
        self.runner.return_value = result(cv2.imencode(".png", frame)[1].tobytes())
        captured = self.adb.capture_bgr()
        self.assertEqual(captured.shape, (720, 1280, 3))
        self.assertEqual(self.adb.last_native_size, (1920, 1080))
        np.testing.assert_array_equal(captured[0, 0], [12, 34, 56])
        self.assertEqual(self.runner.call_args.args[0][-3:], ["exec-out", "screencap", "-p"])
        for raw in (b"not png", b"\x89PNG\r\n\x1a\n"):
            self.runner.return_value = result(raw)
            with self.assertRaises(EmuTransportError):
                self.adb.capture_bgr()

    def test_touch_and_fallback(self):
        self.adb.last_native_size = (1920, 1080)
        self.adb.tap(2000, -1)
        self.assertEqual(self.runner.call_args.args[0][-1], "input tap 1919 0")
        self.adb.drag([(0, 0), (1279, 719)], 250)
        self.assertEqual(self.runner.call_args.args[0][-1], "input swipe 0 0 1919 1079 250")
        self.runner.reset_mock()
        self.adb.drag([(0, 0), (1279, 0), (1279, 719)], 90)
        self.runner.assert_called_once()
        script = self.runner.call_args.args[0][-1]
        for text in ("motionevent DOWN 0 0", "motionevent MOVE 1919 0", "motionevent UP 1919 1079", "sleep"):
            self.assertIn(text, script)
        for failure in (result("Unknown command: motionevent"), result(code=1, stderr="unsupported")):
            self.runner.side_effect = [failure, result()]
            self.adb.drag([(0, 0), (10, 10), (1279, 719)], 90)
            self.assertEqual(self.runner.call_args.args[0][-1], "input swipe 0 0 1919 1079 90")

    def test_drag_unknown_outcome_releases_without_replay_or_reconnect(self):
        failures = [subprocess.TimeoutExpired('adb', 1),
                    OSError('adb executable not found'),
                    result(code=1, stderr='timed out'),
                    result(code=1, stderr='device offline'),
                    result(code=1, stderr="device 'host:5555' not found"),
                    result(code=1, stderr='connection lost'),
                    result(code=1, stderr='KARDS_MOTION_DOWN_DISPATCHED\ninvalid MOVE'),
                    result('KARDS_MOTION_DOWN_DISPATCHED\nUnknown command: motionevent'),
                    result('Error: injection failed')]
        for failure in failures:
            for release_fails in (False, True):
                with self.subTest(failure=failure, release_fails=release_fails):
                    self.runner.reset_mock()
                    self.runner.side_effect = [failure,
                        result(code=1, stderr='device offline') if release_fails else result()]
                    with self.assertRaises(EmuTransportError):
                        self.adb.drag([(0, 0), (20, 20), (30, 40)], 90)
                    self.assertEqual(self.runner.call_count, 2)
                    commands = [c.args[0][-1] for c in self.runner.call_args_list]
                    self.assertEqual(commands[-1], 'input motionevent UP 30 40')
                    self.assertFalse(any('input swipe' in c for c in commands))

    def test_resolve_installed_and_active_kards_package(self):
        for foreground, installed, expected in (
                (transport.KARDS_PACKAGES[1], list(transport.KARDS_PACKAGES), transport.KARDS_PACKAGES[1]),
                ('com.other', [transport.KARDS_PACKAGES[1]], transport.KARDS_PACKAGES[1]),
                (None, [transport.KARDS_PACKAGES[0]], transport.KARDS_PACKAGES[0]),
                (None, [], None)):
            with patch.object(self.adb, 'get_foreground_package', return_value=foreground), \
                    patch.object(self.adb, 'list_packages', return_value=installed):
                self.assertEqual(self.adb.resolve_kards_package(), expected)

    def test_foreground_variants(self):
        package = transport.KARDS_PACKAGES[0]
        for marker in ("mCurrentFocus", "mResumedActivity", "topResumedActivity"):
            line = f"{marker}=Window{{123 u0 {package}/.MainActivity}}"
            self.runner.side_effect = [result(line)] if marker == "mCurrentFocus" else [result("mCurrentFocus=null"), result(line)]
            self.assertEqual(self.adb.is_kards_foreground(), (True, package))
        self.runner.side_effect = [result("mCurrentFocus=null"), result("")]
        self.assertEqual(self.adb.is_kards_foreground(), (False, ""))

    def test_packages_launch_and_stop(self):
        package = transport.KARDS_PACKAGES[1]
        self.runner.return_value = result(f"package:{package}\npackage:com.other.app\n")
        self.assertEqual(self.adb.list_packages("kards"), [package])
        self.runner.side_effect = [self.runner.return_value, result("Events injected: 1")]
        self.assertTrue(self.adb.launch_kards())
        self.assertIn(f"monkey -p {package} -c android.intent.category.LAUNCHER 1", self.runner.call_args.args[0][-1])
        self.runner.side_effect = None
        self.runner.return_value = result("")
        self.assertTrue(self.adb.force_stop_package(package))
        self.assertEqual(self.runner.call_args.args[0][-1], f"am force-stop {package}")
        self.assertFalse(self.adb.launch_kards())
        self.adb.force_stop_package("pkg; echo bad")
        self.assertIn("'pkg; echo bad'", self.runner.call_args.args[0][-1])

    def test_errors(self):
        for failure in (OSError("missing"), subprocess.TimeoutExpired("adb", 1)):
            self.runner.side_effect = failure
            with self.assertRaises(EmuTransportError):
                self.adb.tap(0, 0)


class WorkerAdbRecoveryTests(unittest.TestCase):
    def make_worker(self):
        from emu_worker import EmuWorker, WorkerConfig
        adb = Mock(spec=AdbTransport)
        adb.backend_name = "mumu_ipc"
        worker = EmuWorker(WorkerConfig("mumu:7"), transport=adb, vision=Mock(),
                           clock_fn=lambda: 100.0)
        worker.log = Mock()
        worker._sleep = Mock()
        return worker, adb

    def test_startup_force_stop_error_is_nonfatal(self):
        worker, adb = self.make_worker()
        adb.force_stop_package.side_effect = EmuTransportError("device not found")
        worker._startup()
        self.assertTrue(worker._startup_done)
        adb.force_stop_package.assert_called_once_with("com.kards.mobilert")
        self.assertIn("warning:", worker.log.call_args.args[0])
        self.assertEqual(worker.status["last_error"], "")

    def test_foreground_and_launch_errors_retry_later(self):
        for operation in ("is_kards_foreground", "launch_kards"):
            with self.subTest(operation=operation):
                worker, adb = self.make_worker()
                adb.is_kards_foreground.return_value = (False, "")
                getattr(adb, operation).side_effect = EmuTransportError("device offline")
                self.assertFalse(worker._foreground_ready())
                self.assertFalse(worker._foreground)
                self.assertIn("warning:", worker.log.call_args.args[0])
                self.assertEqual(worker.status["last_error"], "")
                getattr(adb, operation).side_effect = None
                adb.is_kards_foreground.return_value = (True, transport.KARDS_PACKAGES[0])
                worker.clock = lambda: 106.0
                self.assertTrue(worker._foreground_ready())


class HelperAndFactoryTests(unittest.TestCase):
    def test_geometry(self):
        self.assertEqual(transport.scale_point(-5, 900, (1920, 1080)), (0, 1079))
        for frame in (np.zeros((720, 1280), np.uint8), np.zeros((720, 1280, 3), float),
                      np.zeros((1280, 720, 3), np.uint8), np.zeros((480, 640, 3), np.uint8),
                      np.zeros((0, 1280, 3), np.uint8)):
            with self.assertRaises(EmuTransportError):
                transport.normalize_frame_bgr(frame)
        path = transport.interpolate_path([(0, 0), (10, 0), (10, 30)], 64)
        self.assertEqual([(x, y) for x, y, _ in path], [(0, 0), (10, 0), (10, 10), (10, 20), (10, 30)])
        self.assertAlmostEqual(sum(p[2] for p in path), .064)
        self.assertEqual(path[-1][2], 0)
        self.assertEqual(transport.interpolate_path([(1, 1), (1, 1)], 100)[0], (1, 1, .1))
        with self.assertRaises(ValueError):
            transport.interpolate_path([(0, 0)], 100)

    def test_factory_ipc_failure_falls_back(self):
        instance = EmulatorInstance("mumu", "mumu:7", "VM", adb_serial="host:7", adb_path="adb.exe",
                                    mumu_root="root", mumu_index=7, ipc_available=True, ipc_dll_path="fake.dll")
        dll = FakeDll()
        dll.nemu_connect.return_value = 0
        runner = Mock(side_effect=[result("connected"), result("device")])
        log = Mock()
        with patch.object(transport.ct, "CDLL", return_value=dll), \
                patch.object(transport.subprocess, "run", runner):
            connected = transport.create_transport(instance, log=log)
        self.assertIsInstance(connected, AdbTransport)
        log.assert_called_once()
        self.assertEqual(runner.call_count, 2)
        dll.nemu_disconnect.assert_not_called()
        with self.assertRaises(EmuTransportError):
            transport.create_transport(replace(instance, provider="adb", adb_path=None))

    def test_custom_factory_and_ipc_preference(self):
        instance = EmulatorInstance("custom", "custom:1", "Custom")
        factory = Mock(return_value=Mock(spec=AdbTransport))
        with patch.dict(transport._factories, {}, clear=True):
            transport.register_transport_factory("custom", factory)
            connected = transport.create_transport(instance, prefer_ipc=False)
        factory.assert_called_once_with(instance, {"prefer_ipc": False, "log": None})
        connected.connect.assert_called_once()
        instance = replace(instance, provider="mumu", adb_serial="host:7", adb_path="adb.exe",
                           mumu_root="root", mumu_index=7, ipc_available=True, ipc_dll_path="fake.dll")
        with patch.object(transport, "MuMuIpcTransport") as ipc, patch.object(transport, "AdbTransport") as adb:
            self.assertIs(transport.create_transport(instance), ipc.return_value)
            ipc.return_value.connect.assert_called_once()
            adb.return_value.connect.assert_not_called()
            self.assertIs(transport.create_transport(instance, prefer_ipc=False), adb.return_value)
            adb.return_value.connect.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
