"""Emulator inventory and opt-in lifecycle operations (no helper APK)."""
from __future__ import annotations

import argparse
import csv
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import shutil
import re
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
                extra=dict(item, controllable=True, can_launch=True, can_shutdown=True)))
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


class LDPlayerProvider(EmulatorProvider):
    name = "ldplayer"
    CONSOLES = ("ldconsole.exe", "dnconsole.exe")

    def __init__(self, ld_root: str | None = None, runner=None):
        self.runner = runner or subprocess.run
        candidates = [ld_root, os.environ.get("LDPLAYER_ROOT"),
                      r"C:\LDPlayer\LDPlayer9", r"D:\LDPlayer\LDPlayer9",
                      r"C:\leidian\LDPlayer9", r"D:\leidian\LDPlayer9",
                      r"C:\LDPlayer\LDPlayer4.0", r"D:\LDPlayer\LDPlayer4.0",
                      r"C:\ChangZhi\dnplayer2"]
        self.ld_root = next((r for r in candidates if _find(r, self.CONSOLES)), None)
        self.console_path = _find(self.ld_root, self.CONSOLES)
        self.adb_path = _find(self.ld_root, ("adb.exe",))

    def discover(self) -> list[EmulatorInstance]:
        if not self.console_path:
            return []
        try:
            result = _run(self.runner, [self.console_path, "list2"])
        except (OSError, subprocess.SubprocessError):
            return []
        if result.returncode:
            return []
        instances = []
        for parts in csv.reader(result.stdout.lstrip("\ufeff").splitlines()):
            if len(parts) < 7:
                continue
            try:
                index = int(parts[0])
            except ValueError:
                continue
            if index < 0:
                continue
            title = parts[1].strip() or f"LDPlayer {index}"
            running = parts[4].strip() == "1"
            pid = int(parts[5]) if parts[5].isdigit() else 0
            instances.append(EmulatorInstance(
                provider=self.name, instance_id=f"ldplayer:{index}", name=title,
                adb_serial=f"127.0.0.1:{5555 + index * 2}", adb_path=self.adb_path,
                running=running, process_started=running or pid > 0, ipc_available=False,
                extra={"ld_index": index, "ld_root": self.ld_root,
                       "controllable": True, "can_launch": True, "can_shutdown": True,
                       "alt_serial": f"emulator-{5554 + index * 2}", "pid": pid}))
        return instances

    def _control(self, instance, action):
        index = instance.extra.get("ld_index")
        if not self.console_path or instance.provider != self.name or index is None:
            return False
        try:
            return _run(self.runner, [self.console_path, action, "--index", str(index)]).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def launch(self, instance: EmulatorInstance) -> bool:
        return self._control(instance, "launch")

    def shutdown(self, instance: EmulatorInstance) -> bool:
        return self._control(instance, "quit")


class BlueStacksProvider(EmulatorProvider):
    name = "bluestacks"

    def __init__(self, conf_path: str | None = None, runner=None):
        self.runner = runner or subprocess.run
        candidates = [conf_path, os.environ.get("BLUESTACKS_CONF"),
                      r"C:\ProgramData\BlueStacks_nxt\bluestacks.conf",
                      r"C:\ProgramData\BlueStacks_bgp64\bluestacks.conf",
                      r"C:\ProgramData\BlueStacks\bluestacks.conf"]
        self.conf_path = next((str(p) for p in candidates if p and Path(p).is_file()), None)
        roots = [r"C:\Program Files\BlueStacks_nxt", r"D:\Program Files\BlueStacks_nxt",
                 r"C:\Program Files\BlueStacks"]
        self.player_path = next((p for r in roots if (p := _find(r, ("HD-Player.exe",)))), None)
        self.adb_path = next((p for r in roots if (p := _find(r, ("HD-Adb.exe", "adb.exe")))), None)

    def discover(self) -> list[EmulatorInstance]:
        if not self.conf_path:
            return []
        try:
            lines = Path(self.conf_path).read_text(encoding="utf-8-sig").splitlines()
        except (OSError, UnicodeError):
            return []
        entries = {}
        for line in lines:
            match = re.fullmatch(r'\s*bst\.instance\.([^.]+)\.(display_name|status\.adb_port)\s*=\s*(.*?)\s*', line)
            if match:
                inst, key, value = match.groups()
                entries.setdefault(inst, {})[key] = value.strip('"')
        online = set()
        if self.adb_path:
            try:
                result = _run(self.runner, [self.adb_path, "devices"])
                if result.returncode == 0:
                    online = {p[0] for line in result.stdout.splitlines()
                              if len(p := line.split()) >= 2 and p[1] == "device"}
            except (OSError, subprocess.SubprocessError):
                pass
        instances = []
        for inst, values in entries.items():
            try:
                port = int(values.get("status.adb_port", ""))
            except ValueError:
                continue
            if port <= 0:
                continue
            serial = f"127.0.0.1:{port}"
            running = serial in online
            instances.append(EmulatorInstance(
                provider=self.name, instance_id=f"bluestacks:{inst}",
                name=values.get("display_name") or f"BlueStacks {inst}",
                adb_serial=serial, adb_path=self.adb_path, running=running,
                process_started=running, ipc_available=False,
                extra={"bs_instance": inst, "player_path": self.player_path,
                       "controllable": bool(self.player_path), "can_launch": bool(self.player_path),
                       "can_shutdown": False,
                       "conf_path": self.conf_path}))
        return instances

    def launch(self, instance: EmulatorInstance) -> bool:
        inst = instance.extra.get("bs_instance")
        if not self.player_path or not Path(self.player_path).is_file() or instance.provider != self.name or not inst:
            return False
        try:
            subprocess.Popen([self.player_path, "--instance", inst],
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            return True
        except OSError:
            return False


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
    default_providers = providers is None
    if default_providers:
        mumu = MuMuProvider(mumu_root=mumu_root)
        ldplayer, bluestacks = LDPlayerProvider(), BlueStacksProvider()
        providers = [mumu, ldplayer, bluestacks,
                     GenericAdbProvider(adb_path=adb_path or mumu.adb_path or ldplayer.adb_path or bluestacks.adb_path,
                                             extra_serials=tuple(extra_serials)),
                     *get_registered_providers()]
    found = []
    for provider in providers:
        try:
            found.extend(provider.discover())
        except Exception:
            if not default_providers:
                raise  # Preserve explicit callers' error reporting contract.
    # Dedicated identities win regardless of provider order, including LD aliases.
    live_adb = {i.adb_serial for i in found if i.provider == "adb" and i.running}
    dedicated_serials = {serial for i in found if i.provider != "adb"
                         for serial in (i.adb_serial, i.extra.get("alt_serial")) if serial
                         and (i.running or i.process_started or serial not in live_adb)}
    seen = set()
    result = []
    for instance in found:
        serial = instance.adb_serial
        if instance.provider == "adb" and serial and (serial in seen or serial in dedicated_serials):
            continue
        result.append(instance)
        if serial and instance.provider == "adb":
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
