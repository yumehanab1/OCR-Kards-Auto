"""Process orchestration for emulator workers, independent of the PC engine lock."""
from __future__ import annotations

from collections.abc import Sequence
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time

if __package__:
    from . import emu_discovery, log_io
else:
    import emu_discovery
    import log_io


DEFAULT_EMU_OPTIONS = {
    "mode": "training", "deck_name": "", "max_rounds": 3, "prefer_ipc": True,
    "allow_attack": True, "allow_deploy": True, "allow_end_turn": True,
    "dry_run": False, "auto_launch_kards": True, "stagger_seconds": 1.5,
    "extra_serials": [], "selected_instances": [],
}


def normalize_emu_options(opts: dict) -> dict:
    """Return independent defaults plus validated known fields; reject bad values."""
    if not isinstance(opts, dict):
        raise ValueError("Options must be a dictionary")
    result = {}
    for key, default in DEFAULT_EMU_OPTIONS.items():
        value = opts.get(key, default)
        if isinstance(default, bool):
            valid = type(value) is bool
        elif key == "max_rounds":
            valid = type(value) is int and 0 <= value <= 99
        elif key == "stagger_seconds":
            valid = (type(value) in (int, float) and math.isfinite(value)
                     and 0 <= value <= 10)
            if valid:
                value = float(value)
        elif isinstance(default, list):
            valid = isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value)
            if valid:
                value = list(dict.fromkeys(v.strip() for v in value if v.strip()))
        else:
            valid = isinstance(value, str)
            if valid:
                value = value.strip()
        if not valid or (key == "mode" and value not in ("training", "casual", "ranked")):
            raise ValueError(f"Invalid emulator option: {key}")
        result[key] = value
    return result


def load_emu_options(project_root: Path | str) -> dict:
    path = Path(project_root) / "config/emu_options.json"
    try:
        opts = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        opts = {}
    return normalize_emu_options(opts)


def save_emu_options(opts: dict, project_root: Path | str) -> dict:
    opts = normalize_emu_options(opts)
    path = Path(project_root) / "config/emu_options.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as out:
            temporary = Path(out.name)
            json.dump(opts, out, ensure_ascii=False, indent=2)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return opts


def safe_instance_slug(instance_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", instance_id).strip("_") or "instance"


def default_python_exe(project_root: Path) -> str:
    bundled = Path(project_root) / "python/python.exe"
    return str(bundled) if bundled.is_file() else sys.executable


class EmuManager:
    def __init__(self, project_root: Path | str, python_exe: str | None = None,
                 discover_fn=None, popen_fn=None, sleep_fn=time.sleep, providers=None):
        self.project_root = Path(project_root)
        self.logs_dir = self.project_root / "logs"
        self.python_exe = python_exe or default_python_exe(self.project_root)
        self.discover_fn = discover_fn or emu_discovery.discover_all
        self.popen_fn = popen_fn or subprocess.Popen
        self.sleep_fn = sleep_fn
        self.providers = list(providers or ())
        self._lock = threading.RLock()
        self._workers: dict[str, dict] = {}

    def worker_paths(self, instance_id: str) -> dict[str, Path]:
        base = "emu_" + safe_instance_slug(instance_id)
        return {key: self.logs_dir / (base + suffix) for key, suffix in
                (("log_file", ".log"), ("status_file", ".status.json"), ("stop_file", ".stop"))}

    def build_worker_argv(self, instance_id: str, opts: dict) -> list[str]:
        opts = normalize_emu_options(opts)
        paths = self.worker_paths(instance_id)
        argv = [self.python_exe, "-B", str(self.project_root / "src/emu_worker.py"),
                "--instance", instance_id, "--mode", opts["mode"],
                "--max-rounds", str(opts["max_rounds"])]
        for key in ("stop_file", "log_file", "status_file"):
            argv += ["--" + key.replace("_", "-"), str(paths[key])]
        if opts["deck_name"]:
            argv += ["--deck", opts["deck_name"]]
        argv += ["--prefer-ipc" if opts["prefer_ipc"] else "--adb-only"]
        for key in ("attack", "deploy", "end_turn"):
            if not opts["allow_" + key]:
                argv.append("--no-" + key.replace("_", "-"))
        if opts["dry_run"]:
            argv.append("--dry-run")
        if not opts["auto_launch_kards"]:
            argv.append("--no-auto-launch")
        if instance_id.startswith("adb:"):
            argv += ["--extra-serial", instance_id[4:]]
        return argv

    def _options(self, overrides):
        saved = load_emu_options(self.project_root)
        if overrides is not None:
            if not isinstance(overrides, dict):
                raise ValueError("Options must be a dictionary")
            saved.update(overrides)
        return normalize_emu_options(saved)

    def _reap(self):
        for worker in self._workers.values():
            code = worker["proc"].poll()
            if code is not None and worker["exit_code"] is None:
                worker["stop_file"].unlink(missing_ok=True)
            worker["exit_code"] = code

    def list_instances(self, extra_serials: Sequence[str] = ()) -> list[dict]:
        discovered = self.discover_fn(extra_serials=extra_serials)
        with self._lock:
            self._reap()
            instances = {i.instance_id: i.to_dict() for i in discovered}
            for iid, worker in self._workers.items():
                if worker["exit_code"] is None and iid not in instances:
                    instances[iid] = emu_discovery.EmulatorInstance(
                        provider=iid.partition(":")[0], instance_id=iid, name=iid).to_dict()
            for iid, inst in instances.items():
                paths = self.worker_paths(iid)
                try:
                    status = json.loads(paths["status_file"].read_text(encoding="utf-8-sig"))
                    if not isinstance(status, dict):
                        status = {}
                except (OSError, ValueError):
                    status = {}
                worker = self._workers.get(iid)
                running = worker is not None and worker["exit_code"] is None
                inst.update(worker_running=running,
                            worker_pid=worker["proc"].pid if running else None,
                            worker_exit_code=worker["exit_code"] if worker else None,
                            worker_state=status.get("state", "idle"),
                            log_file=str(paths["log_file"]))
                for key in ("rounds_done", "victories", "defeats", "turns"):
                    inst[key] = status.get(key, 0)
                for key in ("last_action", "last_error", "backend"):
                    inst[key] = status.get(key, "")
                inst["avg_capture_ms"] = status.get("avg_capture_ms")
            return list(instances.values())

    def start_instance(self, instance_id: str, opts: dict | None = None) -> dict:
        with self._lock:
            self._reap()
            if instance_id in self._workers and self._workers[instance_id]["exit_code"] is None:
                return {"ok": False, "msg": "该实例已在运行中"}
            try:
                options = self._options(opts)
                paths = self.worker_paths(instance_id)
                # Sanitized IDs can collide; never share another live worker's stop file.
                if any(w["exit_code"] is None and w["stop_file"] == paths["stop_file"]
                       for w in self._workers.values()):
                    return {"ok": False, "msg": "实例日志路径与运行中的实例冲突"}
                argv = self.build_worker_argv(instance_id, options)
                self.logs_dir.mkdir(parents=True, exist_ok=True)
                paths["stop_file"].unlink(missing_ok=True)
                paths["status_file"].unlink(missing_ok=True)
                proc = self.popen_fn(argv, cwd=str(self.project_root),
                                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                return {"ok": False, "instance_id": instance_id, "msg": str(exc)}
            self._workers[instance_id] = dict(proc=proc, **paths, started_at=time.time(),
                                              opts=options, argv=argv, exit_code=None)
            return {"ok": True, "instance_id": instance_id, "pid": proc.pid,
                    "argv": argv, "log_file": str(paths["log_file"])}

    @staticmethod
    def _wait_until(worker, deadline):
        proc = worker["proc"]
        if proc.poll() is None:
            try:
                proc.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                pass

    def _finish_stops(self, workers, timeout):
        deadline = time.monotonic() + max(0.0, timeout)
        for worker in workers:
            self._wait_until(worker, deadline)
        remaining = [w for w in workers if w["proc"].poll() is None]
        for worker in remaining:
            worker["proc"].terminate()
        deadline = time.monotonic() + 3.0
        for worker in remaining:
            self._wait_until(worker, deadline)
        for worker in remaining:
            if worker["proc"].poll() is None:
                worker["proc"].kill()
                worker["proc"].wait()
        self._reap()

    def stop_instance(self, instance_id: str, timeout: float = 6.0) -> dict:
        with self._lock:
            self._reap()
            worker = self._workers.get(instance_id)
            if worker is None or worker["exit_code"] is not None:
                return {"ok": False, "msg": "该实例未在运行"}
            worker["stop_file"].write_text("stop\n", encoding="utf-8")
            self._finish_stops([worker], timeout)
            return {"ok": True, "instance_id": instance_id,
                    "exit_code": worker["proc"].returncode, "msg": "实例已停止"}

    def start_many(self, instance_ids: Sequence[str], opts: dict | None = None) -> dict:
        options = self._options(opts)
        results, started, failed = {}, [], []
        # Wait before the next attempt, never after the final attempt.
        pending_stagger = False
        for iid in dict.fromkeys(instance_ids):
            with self._lock:
                worker = self._workers.get(iid)
                already_running = worker is not None and worker["proc"].poll() is None
            if pending_stagger and not already_running:
                self.sleep_fn(options["stagger_seconds"])
                pending_stagger = False
            result = self.start_instance(iid, options)
            results[iid] = result
            (started if result["ok"] else failed).append(iid)
            if result["ok"]:
                pending_stagger = True
        return {"ok": bool(started), "results": results, "started": started, "failed": failed}

    def stop_all(self, timeout: float = 6.0) -> dict:
        with self._lock:
            self._reap()
            active = {iid: w for iid, w in self._workers.items() if w["exit_code"] is None}
            for worker in active.values():
                worker["stop_file"].write_text("stop\n", encoding="utf-8")
            self._finish_stops(list(active.values()), timeout)
            return {"ok": True, "stopped": list(active)}

    def _control_emulator(self, instance_id, action):
        opts = load_emu_options(self.project_root)
        instances = self.discover_fn(extra_serials=opts["extra_serials"])
        instance = next((i for i in instances if i.instance_id == instance_id), None)
        if instance is None:
            return {"ok": False, "msg": "未找到实例"}
        providers = [*self.providers, *emu_discovery.get_registered_providers()]
        provider = next((p for p in providers if p.name == instance.provider), None)
        if provider is None and instance.provider == "mumu":
            provider = emu_discovery.MuMuProvider(mumu_root=instance.mumu_root)
        if provider is None:
            return {"ok": False, "msg": "该提供方不支持实例控制"}
        try:
            ok = bool(getattr(provider, action)(instance))
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            return {"ok": False, "instance_id": instance_id, "msg": str(exc)}
        return {"ok": ok, "instance_id": instance_id}

    def launch_emulator(self, instance_id: str) -> dict:
        return self._control_emulator(instance_id, "launch")

    def shutdown_emulator(self, instance_id: str) -> dict:
        return self._control_emulator(instance_id, "shutdown")

    def tail_instance_log(self, instance_id: str, lines: int = 200, since_rev: str = "") -> dict:
        path = self.worker_paths(instance_id)["log_file"]
        rev = log_io.revision(path)
        if since_rev == rev:
            return {"changed": False, "rev": rev, "lines": []}
        return {"changed": True, "rev": rev, "lines": log_io.tail_lines(path, lines),
                "log_file": str(path)}

    def snapshot(self, selected_log_id: str = "", log_since_rev: str = "",
                 extra_serials: Sequence[str] | None = None) -> dict:
        options = load_emu_options(self.project_root)
        instances = self.list_instances(options["extra_serials"] if extra_serials is None else extra_serials)
        return {"instances": instances, "running_count": sum(i["worker_running"] for i in instances),
                "options": options,
                "log": self.tail_instance_log(selected_log_id, since_rev=log_since_rev) if selected_log_id else None}

    def has_running_workers(self) -> bool:
        with self._lock:
            self._reap()
            return any(w["exit_code"] is None for w in self._workers.values())
