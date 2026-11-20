"""Serialized emulator capture/touch transports; coordinates use 1280 x 720.

Injected runners follow subprocess.run's interface. Custom factories return an
unconnected transport; create_transport connects it before returning it.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
import ctypes as ct
import logging
import math
import os
import re
import shlex
import subprocess
import threading
import time

import cv2
import numpy as np

if __package__:
    from .emu_discovery import EmulatorInstance
else:
    from emu_discovery import EmulatorInstance

BASE_WIDTH = 1280
BASE_HEIGHT = 720
KARDS_PACKAGES = ("com.android1939.kards", "com.android1939.kardsapk")


class EmuTransportError(RuntimeError):
    pass


def _validate_size(w, h):
    # Permit small navigation-bar differences, not portrait or 4:3 stretching.
    if h <= 0 or w < 640 or w <= h or abs(w / h - 16 / 9) > 0.18:
        raise EmuTransportError(f"Expected 16:9 landscape capture, got {w}x{h}")


def normalize_frame_bgr(bgr: np.ndarray) -> tuple[np.ndarray, tuple[int, int]]:
    if not isinstance(bgr, np.ndarray) or bgr.dtype != np.uint8 or bgr.ndim != 3 or bgr.shape[2] != 3:
        raise EmuTransportError("Expected a three-channel uint8 BGR image")
    h, w = bgr.shape[:2]
    _validate_size(w, h)
    if (w, h) != (BASE_WIDTH, BASE_HEIGHT):
        bgr = cv2.resize(bgr, (BASE_WIDTH, BASE_HEIGHT), interpolation=cv2.INTER_AREA)
    return np.ascontiguousarray(bgr), (w, h)


def scale_point(x: float, y: float, native_size: tuple[int, int]) -> tuple[int, int]:
    w, h = native_size
    if w <= 0 or h <= 0 or not all(math.isfinite(v) for v in (x, y)):
        raise ValueError("Coordinates must be finite and native size positive")
    return (round(min(max(x, 0), BASE_WIDTH - 1) * (w - 1) / (BASE_WIDTH - 1)),
            round(min(max(y, 0), BASE_HEIGHT - 1) * (h - 1) / (BASE_HEIGHT - 1)))


def interpolate_path(points: Sequence[tuple[float, float]], duration_ms: int,
                     step_ms: int = 16) -> list[tuple[int, int, float]]:
    """Sample by arc length; each sleep follows its point, final sleep is zero.

    Include waypoint times as well as uniform steps so corners are never cut.
    """
    if len(points) < 2 or duration_ms < 0 or step_ms <= 0:
        raise ValueError("Need two points, nonnegative duration and positive step")
    if not all(math.isfinite(v) for p in points for v in p):
        raise ValueError("Waypoints must be finite")
    distances = [0.0]
    for a, b in zip(points, points[1:]):
        distances.append(distances[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    total = distances[-1]
    if not total:
        x, y = map(round, points[-1])
        return [(x, y, duration_ms / 1000), (x, y, 0.0)]
    steps = max(1, math.ceil(duration_ms / step_ms))
    fractions = sorted({i / steps for i in range(steps + 1)} |
                       {d / total for d in distances})
    result = []
    segment = 0
    for i, fraction in enumerate(fractions):
        distance = fraction * total
        while segment < len(points) - 2 and distances[segment + 1] <= distance:
            segment += 1
        length = distances[segment + 1] - distances[segment]
        t = (distance - distances[segment]) / length if length else 1.0
        a, b = points[segment:segment + 2]
        delay = (fractions[i + 1] - fraction) * duration_ms / 1000 if i + 1 < len(fractions) else 0.0
        result.append((round(a[0] + (b[0] - a[0]) * t),
                       round(a[1] + (b[1] - a[1]) * t), delay))
    return result


class EmuTransport(ABC):
    backend_name = "base"
    last_native_size = (BASE_WIDTH, BASE_HEIGHT)

    @abstractmethod
    def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()

    @abstractmethod
    def capture_bgr(self) -> np.ndarray:
        raise NotImplementedError

    @abstractmethod
    def tap(self, x: float, y: float, duration_ms: int = 60) -> None:
        raise NotImplementedError

    @abstractmethod
    def drag(self, points: Sequence[tuple[float, float]], duration_ms: int = 900) -> None:
        raise NotImplementedError

    def list_packages(self, filter_str: str = "") -> list[str]:
        return self.adb.list_packages(filter_str) if getattr(self, "adb", None) else []

    def get_foreground_package(self) -> str | None:
        return self.adb.get_foreground_package() if getattr(self, "adb", None) else None

    def is_kards_foreground(self, packages: Sequence[str] = KARDS_PACKAGES) -> tuple[bool, str]:
        if getattr(self, "adb", None):
            return self.adb.is_kards_foreground(packages)
        package = self.get_foreground_package()
        return package in packages, package or ""

    def launch_kards(self, package: str | None = None) -> bool:
        return self.adb.launch_kards(package) if getattr(self, "adb", None) else False

    def force_stop_package(self, package: str) -> bool:
        return self.adb.force_stop_package(package) if getattr(self, "adb", None) else False


class AdbTransport(EmuTransport):
    backend_name = "adb"

    def __init__(self, serial: str, adb_path: str, timeout: float = 10.0, runner=None):
        self.serial, self.adb_path, self.timeout = serial, adb_path, timeout
        self.runner = runner or subprocess.run
        self._lock = threading.RLock()
        self.last_native_size = (BASE_WIDTH, BASE_HEIGHT)

    def _run(self, args, *, binary=False, targeted=True, timeout=None, _retry_connect=True):
        args = list(args)
        command = [self.adb_path] + (["-s", self.serial] if targeted else []) + args
        kwargs = dict(capture_output=True, timeout=timeout or self.timeout,
                      creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if not binary:
            kwargs.update(text=True, encoding="utf-8", errors="replace")
        try:
            result = self.runner(command, **kwargs)
        except (OSError, subprocess.SubprocessError) as exc:
            raise EmuTransportError(f"ADB {self.serial}: {exc}") from exc
        if result.returncode:
            stderr = result.stderr
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            if (targeted and _retry_connect and ":" in self.serial and
                    any(marker in stderr.lower() for marker in ("not found", "offline"))):
                self._run(["connect", self.serial], targeted=False)
                return self._run(args, binary=binary, targeted=targeted,
                                 timeout=timeout, _retry_connect=False)
            raise EmuTransportError(f"ADB {self.serial}: {result.stderr}")
        return result.stdout

    def _shell(self, *args, timeout=None):
        # adb joins shell arguments remotely: quote each untrusted argument there.
        return self._run(["shell", shlex.join(str(a) for a in args)], timeout=timeout)

    def connect(self) -> None:
        with self._lock:
            if ":" in self.serial:
                self._run(["connect", self.serial], targeted=False)
            if self._run(["get-state"]).strip() != "device":
                raise EmuTransportError(f"ADB device is not ready: {self.serial}")

    def close(self) -> None:
        # Do not disconnect the shared ADB server/device used by other transports.
        with self._lock:
            pass

    def capture_bgr(self) -> np.ndarray:
        with self._lock:
            raw = self._run(["exec-out", "screencap", "-p"], binary=True)
            if not isinstance(raw, bytes) or not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                raise EmuTransportError("ADB screencap did not return PNG bytes")
            try:
                frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
            except cv2.error as exc:
                raise EmuTransportError("Invalid screencap PNG") from exc
            frame, self.last_native_size = normalize_frame_bgr(frame)
            return frame

    def tap(self, x: float, y: float, duration_ms: int = 60) -> None:
        with self._lock:
            nx, ny = scale_point(x, y, self.last_native_size)
            self._shell("input", "tap", nx, ny)

    def drag(self, points: Sequence[tuple[float, float]], duration_ms: int = 900) -> None:
        with self._lock:
            if len(points) < 2 or duration_ms < 0:
                raise ValueError("Need two points and nonnegative duration")
            native = [scale_point(x, y, self.last_native_size) for x, y in points]
            timeout = self.timeout + duration_ms / 1000
            if len(native) > 2:
                path = interpolate_path(native, duration_ms)
                commands = ["set -e", "trap 'input motionevent UP %d %d' EXIT" % native[-1]]
                for i, (x, y, delay) in enumerate(path):
                    commands.append(f"input motionevent {'DOWN' if i == 0 else 'MOVE'} {x} {y}")
                    if delay:
                        commands.append(f"sleep {delay:.6f}")
                try:
                    output = self._run(["shell", "; ".join(commands)], timeout=timeout)
                    if re.search(r"unknown command|error:|exception|not found", output, re.I):
                        raise EmuTransportError(output)
                    return
                except EmuTransportError:
                    # Older Android input implementations lack motionevent.
                    pass
            self._shell("input", "swipe", *native[0], *native[-1], duration_ms, timeout=timeout)

    def list_packages(self, filter_str: str = "") -> list[str]:
        with self._lock:
            output = self._shell("pm", "list", "packages")
            return [line[8:].strip() for line in output.splitlines()
                    if line.startswith("package:") and filter_str in line[8:]]

    def get_foreground_package(self) -> str | None:
        with self._lock:
            for args, markers in [(('dumpsys', 'window'), ('mCurrentFocus',)),
                                  (('dumpsys', 'activity', 'activities'),
                                   ('topResumedActivity', 'mResumedActivity'))]:
                output = self._shell(*args)
                for marker in markers:
                    for line in output.splitlines():
                        if marker in line:
                            match = re.search(r"\b([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+)/[\w.$]+", line)
                            if match:
                                return match[1]
            return None

    def launch_kards(self, package: str | None = None) -> bool:
        with self._lock:
            if package is None:
                installed = self.list_packages()
                package = next((p for p in KARDS_PACKAGES if p in installed), None)
            if not package:
                return False
            output = self._shell("monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1")
            return bool(re.search(r"Events injected:\s*[1-9]\d*", output))

    def force_stop_package(self, package: str) -> bool:
        with self._lock:
            output = self._shell("am", "force-stop", package)
            return not re.search(r"error|exception", output, re.I)


class MuMuIpcTransport(EmuTransport):
    backend_name = "mumu_ipc"

    def __init__(self, mumu_root: str, mumu_index: int, dll_path: str,
                 display_id: int = 0, adb_transport: AdbTransport | None = None,
                 dll_loader=None, sleep_fn=time.sleep):
        self.mumu_root, self.mumu_index, self.dll_path = mumu_root, mumu_index, dll_path
        self.display_id, self.adb = display_id, adb_transport
        self._loader = dll_loader or ct.CDLL
        self._sleep = sleep_fn
        self._lock = threading.Lock()
        self._dll = None
        self._handle = 0
        self._buffer = None
        self._buffer_size = None
        self.last_native_size = (BASE_WIDTH, BASE_HEIGHT)

    def connect(self) -> None:
        with self._lock:
            if self._handle:
                return
            try:
                dll = self._loader(self.dll_path)
                signatures = {
                    "nemu_connect": ([ct.c_wchar_p, ct.c_int], ct.c_int),
                    "nemu_disconnect": ([ct.c_int], None),
                    "nemu_capture_display": ([ct.c_int, ct.c_uint, ct.c_int,
                                               ct.POINTER(ct.c_int), ct.POINTER(ct.c_int), ct.c_void_p], ct.c_int),
                    "nemu_input_event_touch_down": ([ct.c_int] * 4, ct.c_int),
                    "nemu_input_event_touch_up": ([ct.c_int] * 2, ct.c_int),
                }
                for name, (args, result) in signatures.items():
                    function = getattr(dll, name)
                    function.argtypes, function.restype = args, result
                handle = dll.nemu_connect(self.mumu_root, self.mumu_index)
                if handle <= 0:
                    raise EmuTransportError("MuMu IPC connect returned no handle")
                self._dll, self._handle = dll, handle
            except (OSError, AttributeError, TypeError, ValueError) as exc:
                raise EmuTransportError(f"Cannot connect MuMu IPC: {exc}") from exc
            if self.adb is not None:
                try:
                    self.adb.connect()
                except EmuTransportError:
                    pass  # IPC capture/touch remains usable when ADB is disabled.

    def close(self) -> None:
        with self._lock:
            if self._handle:
                try:
                    self._dll.nemu_disconnect(self._handle)
                finally:
                    self._handle = 0
                    self._buffer = None
                    self._buffer_size = None
            if self.adb:
                self.adb.close()

    def _ready(self):
        if not self._handle:
            raise EmuTransportError("MuMu IPC is not connected")

    @staticmethod
    def _check(result, operation):
        if result != 0:
            raise EmuTransportError(f"MuMu IPC {operation} failed ({result})")

    def capture_bgr(self) -> np.ndarray:
        with self._lock:
            self._ready()
            w, h = ct.c_int(), ct.c_int()
            capture = self._dll.nemu_capture_display
            self._check(capture(self._handle, self.display_id, 0, ct.byref(w), ct.byref(h), None), "size query")
            size = (w.value, h.value)
            _validate_size(*size)
            if size != self._buffer_size:
                self._buffer = (ct.c_ubyte * (size[0] * size[1] * 4))()
                self._buffer_size = size
            self._check(capture(self._handle, self.display_id, len(self._buffer),
                                ct.byref(w), ct.byref(h), self._buffer), "capture")
            if (w.value, h.value) != size:
                raise EmuTransportError("MuMu resolution changed during capture; retry capture")
            rgba = np.ctypeslib.as_array(self._buffer).reshape(size[1], size[0], 4)
            bgr = cv2.cvtColor(rgba[::-1, :, :], cv2.COLOR_RGBA2BGR)
            frame, self.last_native_size = normalize_frame_bgr(bgr)
            return frame

    def _down(self, x, y):
        self._check(self._dll.nemu_input_event_touch_down(self._handle, self.display_id, x, y), "touch down")

    def _up(self):
        self._check(self._dll.nemu_input_event_touch_up(self._handle, self.display_id), "touch up")

    def tap(self, x: float, y: float, duration_ms: int = 60) -> None:
        if duration_ms < 0:
            raise ValueError("Duration must be nonnegative")
        with self._lock:
            self._ready()
            point = scale_point(x, y, self.last_native_size)
            try:
                self._down(*point)
                self._sleep(duration_ms / 1000)
            finally:
                self._up()

    def drag(self, points: Sequence[tuple[float, float]], duration_ms: int = 900) -> None:
        with self._lock:
            self._ready()
            path = interpolate_path([scale_point(x, y, self.last_native_size) for x, y in points], duration_ms)
            try:
                for x, y, delay in path:
                    self._down(x, y)
                    if delay:
                        self._sleep(delay)
                self._sleep(0.03)
            finally:
                self._up()


_factories: dict[str, Callable[[EmulatorInstance, dict], EmuTransport]] = {}


def register_transport_factory(provider: str, factory: Callable[[EmulatorInstance, dict], EmuTransport]) -> None:
    _factories[provider] = factory


def create_transport(instance: EmulatorInstance, prefer_ipc: bool = True, log=None) -> EmuTransport:
    if instance.provider in _factories:
        transport = _factories[instance.provider](instance, {"prefer_ipc": prefer_ipc, "log": log})
        transport.connect()
        return transport
    adb = (AdbTransport(instance.adb_serial, instance.adb_path)
           if instance.adb_serial and instance.adb_path else None)
    if (instance.provider == "mumu" and prefer_ipc and instance.ipc_available and
            instance.ipc_dll_path and instance.mumu_root and instance.mumu_index is not None):
        ipc = MuMuIpcTransport(instance.mumu_root, instance.mumu_index,
                               instance.ipc_dll_path, adb_transport=adb)
        try:
            ipc.connect()
            return ipc
        except EmuTransportError as exc:
            ipc.close()
            message = f"MuMu IPC unavailable; falling back to ADB: {exc}"
            logger = log or logging.getLogger(__name__)
            if callable(logger):
                logger(message)
            else:
                logger.warning(message)
            if adb is None:
                raise EmuTransportError("IPC failed and no ADB serial/path is available") from exc
    if adb is None:
        raise EmuTransportError("An ADB serial and executable path are required")
    adb.connect()
    return adb
