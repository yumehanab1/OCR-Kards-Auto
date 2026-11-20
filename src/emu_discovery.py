"""Emulator inventory and opt-in lifecycle operations (no helper APK)."""
from __future__ import annotations

import argparse
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any


@dataclass(frozen=True)
class EmulatorInstance:
    provider: str
    instance_id: str
    name: str
    adb_serial: str | None = None
    adb_path: str | None = None
    running: bool = False
    process_started: bool = False
    mumu_root: str | None = None
    mumu_index: int | None = None
    android_version: str | None = None
    ipc_dll_path: str | None = None
    ipc_available: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EmulatorProvider(ABC):
    name: str

    @abstractmethod
    def discover(self) -> list[EmulatorInstance]:
        raise NotImplementedError

    def launch(self, instance: EmulatorInstance) -> bool:
        return False

    def shutdown(self, instance: EmulatorInstance) -> bool:
        return False


_providers: dict[str, EmulatorProvider] = {}


def register_provider(provider: EmulatorProvider) -> None:
    """Register or replace a provider by name; insertion order sets priority."""
    _providers[provider.name] = provider


def get_registered_providers() -> list[EmulatorProvider]:
    return list(_providers.values())


def _run(runner, args):
    return runner(args, capture_output=True, text=True, encoding="utf-8",
                  errors="replace", timeout=15,
                  creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)


def _find(root, relatives):
    if root:
        for relative in relatives:
            path = Path(root) / relative
            if path.is_file():
                return str(path)
    return None


class MuMuProvider(EmulatorProvider):
    name = "mumu"
    MANAGERS = ("nx_main/MuMuManager.exe", "shell/MuMuManager.exe")
    ADBS = ("nx_main/adb.exe", "shell/adb.exe")
    DLLS = ("nx_main/sdk/external_renderer_ipc.dll",
            "nx_device/12.0/shell/sdk/external_renderer_ipc.dll",
            "shell/sdk/external_renderer_ipc.dll")

    def __init__(self, mumu_root: str | None = None, runner=None):
        self.runner = runner or subprocess.run
        candidates = [mumu_root, os.environ.get("MUMU_ROOT"),
                      r"C:\Program Files\Netease\MuMu",
                      r"C:\Program Files\Netease\MuMu Player 12",
                      r"D:\Program Files\Netease\MuMu",
                      r"D:\Program Files\Netease\MuMu Player 12"]
        self.mumu_root = next((r for r in candidates if _find(r, self.MANAGERS)), None)
        self.manager_path = _find(self.mumu_root, self.MANAGERS)
        self.adb_path = _find(self.mumu_root, self.ADBS)
        self.ipc_dll_path = _find(self.mumu_root, self.DLLS)

    def discover(self) -> list[EmulatorInstance]:
        if not self.manager_path:
            return []
        result = _run(self.runner, [self.manager_path, "info", "-v", "all"])
        if result.returncode:
            raise RuntimeError(f"MuMu discovery failed: {result.stderr}")
        data = json.loads(result.stdout.lstrip("\ufeff"))
        items = [(data.get("index"), data)] if "index" in data else data.items()
        instances = []
        for key, item in items:
            if not isinstance(item, dict):
                continue
            index = int(item.get("index", key))
            try:
                port = int(item.get("adb_port") or 0)
            except (TypeError, ValueError):
                port = 0
            host = item.get("adb_host_ip") or "127.0.0.1"
            version = item.get("android_version")
            instances.append(EmulatorInstance(
                provider=self.name, instance_id=f"mumu:{index}",
                name=str(item.get("name") or f"MuMu {index}"),
                adb_serial=f"{host}:{port}" if port > 0 else None,
                adb_path=self.adb_path, running=bool(item.get("is_android_started")),
                process_started=bool(item.get("is_process_started")),
                mumu_root=self.mumu_root, mumu_index=index,
                android_version=str(version) if version is not None else None,
                ipc_dll_path=self.ipc_dll_path, ipc_available=bool(self.ipc_dll_path),
                extra=dict(item)))
        return instances

    def _control(self, instance, action):
        if not self.manager_path or instance.provider != self.name or instance.mumu_index is None:
            return False
        result = _run(self.runner, [self.manager_path, "control", "-v",
                                    str(instance.mumu_index), action])
        try:
            data = json.loads(result.stdout)
        except (ValueError, TypeError):
            return action == "launch" and result.returncode == 0
        if isinstance(data, dict) and "errcode" in data:
            return data["errcode"] == 0
        return action == "launch" and result.returncode == 0

    def launch(self, instance: EmulatorInstance) -> bool:
        return self._control(instance, "launch")

    def shutdown(self, instance: EmulatorInstance) -> bool:
        return self._control(instance, "shutdown")


class GenericAdbProvider(EmulatorProvider):
    name = "adb"

    def __init__(self, adb_path: str | None = None,
                 extra_serials: tuple[str, ...] = (), runner=None):
        self.adb_path = (adb_path or os.environ.get("ADB_PATH") or
                         shutil.which("adb") or MuMuProvider().adb_path)
        self.extra_serials = extra_serials
        self.runner = runner or subprocess.run

    def discover(self) -> list[EmulatorInstance]:
        if not self.adb_path:
            return []
        for serial in self.extra_serials:
            try:
                _run(self.runner, [self.adb_path, "connect", serial])
            except (OSError, subprocess.SubprocessError):
                pass  # A device may already be connected; the inventory is authoritative.
        result = _run(self.runner, [self.adb_path, "devices", "-l"])
        if result.returncode:
            raise RuntimeError(f"ADB discovery failed: {result.stderr}")
        instances = []
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) < 2 or line.startswith(("List of devices", "*")):
                continue
            serial, state = fields[:2]
            model = next((f[6:] for f in fields[2:] if f.startswith("model:")), serial)
            instances.append(EmulatorInstance(
                provider=self.name, instance_id=f"adb:{serial}", name=model,
                adb_serial=serial, adb_path=self.adb_path, running=state == "device",
                process_started=state in ("device", "offline", "authorizing"),
                extra={"state": state}))
        return instances


def discover_all(extra_serials: Sequence[str] = (), adb_path: str | None = None,
                 mumu_root: str | None = None,
                 providers: Sequence[EmulatorProvider] | None = None) -> list[EmulatorInstance]:
    if providers is None:
        mumu = MuMuProvider(mumu_root=mumu_root)
        providers = [mumu, GenericAdbProvider(adb_path=adb_path or mumu.adb_path,
                                             extra_serials=tuple(extra_serials)),
                     *get_registered_providers()]
    found = [instance for provider in providers for instance in provider.discover()]
    # MuMu identity wins even when a caller supplies providers in reverse order.
    mumu_serials = {i.adb_serial for i in found if i.provider == "mumu" and i.adb_serial}
    seen = set()
    result = []
    for instance in found:
        serial = instance.adb_serial
        if instance.provider == "adb" and serial and (serial in seen or serial in mumu_serials):
            continue
        result.append(instance)
        if serial:
            seen.add(serial)
    return sorted(result, key=lambda i: (not i.running, i.provider != "mumu", i.provider,
                                        i.mumu_index if i.mumu_index is not None else -1,
                                        i.instance_id))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--extra-serial", action="append", default=[])
    args = parser.parse_args()
    instances = discover_all(extra_serials=args.extra_serial)
    if args.json:
        print(json.dumps([i.to_dict() for i in instances], ensure_ascii=False, indent=2))
    else:
        for instance in instances:
            print(f"{instance.instance_id}\t{'ready' if instance.running else 'stopped'}\t"
                  f"{instance.name}\t{instance.adb_serial or '-'}")
