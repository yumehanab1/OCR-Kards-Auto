"""Process orchestration for emulator workers, independent of the PC engine lock."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
import json
import http.client
import logging
import math
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit

if __package__:
    from . import emu_discovery, log_io
else:
    import emu_discovery
    import log_io


DEFAULT_EMU_OPTIONS = {
    "mode": "training", "deck_name": "", "max_rounds": 3, "prefer_ipc": True,
    "allow_attack": True, "allow_deploy": True, "allow_end_turn": True,
    "dry_run": False, "auto_launch_kards": True, "stagger_seconds": 1.5,
    "extra_serials": [], "selected_instances": [], "shared_ocr": True,
    "watchdog_seconds": 240, "jitter_ratio": .15,
    "daily_max_rounds": 0, "daily_max_minutes": 0, "instance_overrides": {},
}


INSTANCE_OVERRIDE_KEYS = (
    "mode", "deck_name", "max_rounds", "prefer_ipc", "allow_attack", "allow_deploy",
    "allow_end_turn", "dry_run", "auto_launch_kards", "watchdog_seconds", "jitter_ratio",
    "daily_max_rounds", "daily_max_minutes",
)


def normalize_emu_options(opts: dict) -> dict:
    """Return independent defaults plus validated known fields; reject bad values."""
    if not isinstance(opts, dict):
        raise ValueError("Options must be a dictionary")
    if any(key not in DEFAULT_EMU_OPTIONS for key in opts):
        raise ValueError("Unknown emulator option")
    result = {}
    for key, default in DEFAULT_EMU_OPTIONS.items():
        value = opts.get(key, default)
        if isinstance(default, bool):
            valid = type(value) is bool
        elif key in ("max_rounds", "watchdog_seconds", "daily_max_rounds", "daily_max_minutes"):
            upper = {"max_rounds": 99, "watchdog_seconds": 3600,
                     "daily_max_rounds": 999, "daily_max_minutes": 1440}[key]
            valid = type(value) is int and 0 <= value <= upper
        elif key in ("stagger_seconds", "jitter_ratio"):
            valid = (type(value) in (int, float) and math.isfinite(value)
                     and 0 <= value <= (10 if key == "stagger_seconds" else .5))
            if valid:
                value = float(value)
        elif key == "instance_overrides":
            if not isinstance(value, dict):
                raise ValueError("Invalid emulator option: instance_overrides")
            overrides = {}
            for iid, entry in value.items():
                if (not isinstance(iid, str) or not iid.strip() or not isinstance(entry, dict)
                        or any(k not in INSTANCE_OVERRIDE_KEYS for k in entry)):
                    raise ValueError(f"Invalid instance override: {iid}")
                if entry:
                    normalized = normalize_emu_options({**entry, "instance_overrides": {}})
                    overrides[iid] = {k: normalized[k] for k in entry}
            value, valid = overrides, True
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


def resolve_instance_options(opts: dict, instance_id: str) -> dict:
    """Return independent flat global settings with this instance's overrides."""
    result = normalize_emu_options(opts)
    overrides = result.pop("instance_overrides")
    result.update(overrides.get(instance_id, {}))
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
                 discover_fn=None, popen_fn=None, sleep_fn=time.sleep, providers=None,
                 ocr_popen_fn=None):
        self.project_root = Path(project_root)
        self.logs_dir = self.project_root / "logs"
        self.python_exe = python_exe or default_python_exe(self.project_root)
        self.discover_fn = discover_fn or emu_discovery.discover_all
        self.popen_fn = popen_fn or subprocess.Popen
        self.ocr_popen_fn = ocr_popen_fn
        self.sleep_fn = sleep_fn
        self.providers = list(providers or ())
        self._lock = threading.RLock()
        self._workers: dict[str, dict] = {}
        self._ocr_proc = None
        self._ocr_url = self._ocr_token = ""

    def _ocr_running(self):
        proc = self._ocr_proc
        return proc is not None and proc.poll() is None

    def _stop_ocr_server(self):
        proc, url, token = self._ocr_proc, self._ocr_url, self._ocr_token
        self._ocr_proc = None
        self._ocr_url = self._ocr_token = ""
        if proc is None:
            return
        try:
            if proc.poll() is None and url:
                connection = http.client.HTTPConnection("127.0.0.1", urlsplit(url).port, timeout=.5)
                try:
                    connection.request("POST", "/shutdown", body=b"", headers={"X-OCR-Token": token})
                    response = connection.getresponse()
                    response.read()
                except (OSError, http.client.HTTPException):
                    pass  # An unresponsive service is terminated below.
                finally:
                    connection.close()
                try:
                    proc.wait(timeout=.5)
                except subprocess.TimeoutExpired:
                    pass
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=.5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=1)
        except (OSError, subprocess.SubprocessError):
            logging.getLogger(__name__).warning("Could not stop shared OCR process")
        finally:
            if proc.stdout is not None:
                proc.stdout.close()

    def _ensure_ocr_server(self):
        """Called with _lock held; fake worker launchers remain worker-only."""
        if self.ocr_popen_fn is None and self.popen_fn is not subprocess.Popen:
            return
        if self._ocr_running():
            return
        self._stop_ocr_server()
        token = secrets.token_urlsafe(24)
        ready, lines = threading.Event(), []
        try:
            proc = (self.ocr_popen_fn or subprocess.Popen)(
                [self.python_exe, "-B", str(self.project_root / "src/emu_ocr_server.py")],
                cwd=str(self.project_root), stdout=subprocess.PIPE,
                env={**os.environ, "KARDS_EMU_OCR_TOKEN": token},
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            self._ocr_proc = proc

            def read_ready():
                try:
                    lines.append(proc.stdout.readline(4096))
                except (OSError, ValueError):
                    pass
                finally:
                    ready.set()

            threading.Thread(target=read_ready, daemon=True).start()
            if not ready.wait(5.0) or not lines:
                raise ValueError("OCR startup timed out")
            data = json.loads(lines[0])
            url = data.get("url", "")
            address = urlsplit(url)
            if (data.get("ready") is not True or address.scheme != "http"
                    or address.hostname != "127.0.0.1" or not address.port
                    or address.username is not None or address.password is not None
                    or address.path or address.query or address.fragment or proc.poll() is not None):
                raise ValueError("Invalid OCR startup response")
            self._ocr_url, self._ocr_token = url, token
        except (OSError, ValueError, TypeError, AttributeError, subprocess.SubprocessError):
            logging.getLogger(__name__).warning("Shared OCR unavailable; workers will use local OCR")
            self._stop_ocr_server()

    def worker_paths(self, instance_id: str) -> dict[str, Path]:
        base = "emu_" + safe_instance_slug(instance_id)
        return {key: self.logs_dir / (base + suffix) for key, suffix in
                (("log_file", ".log"), ("status_file", ".status.json"), ("stop_file", ".stop"))}

    def build_worker_argv(self, instance_id: str, opts: dict) -> list[str]:
        eff = resolve_instance_options(opts, instance_id)
        paths = self.worker_paths(instance_id)
        argv = [self.python_exe, "-B", str(self.project_root / "src/emu_worker.py"),
                "--instance", instance_id, "--mode", eff["mode"],
                "--max-rounds", str(eff["max_rounds"])]
        for key in ("stop_file", "log_file", "status_file"):
            argv += ["--" + key.replace("_", "-"), str(paths[key])]
        if eff["deck_name"]:
            argv += ["--deck", eff["deck_name"]]
        argv += ["--prefer-ipc" if eff["prefer_ipc"] else "--adb-only"]
        for key in ("attack", "deploy", "end_turn"):
            if not eff["allow_" + key]:
                argv.append("--no-" + key.replace("_", "-"))
        if eff["dry_run"]:
            argv.append("--dry-run")
        if not eff["auto_launch_kards"]:
            argv.append("--no-auto-launch")
        if instance_id.startswith("adb:"):
            argv += ["--extra-serial", instance_id[4:]]
        for key, flag in (("watchdog_seconds", "--watchdog-seconds"), ("jitter_ratio", "--jitter"),
                          ("daily_max_rounds", "--daily-max-rounds"),
                          ("daily_max_minutes", "--daily-max-minutes")):
            if eff[key] > 0:
                argv += [flag, str(eff[key])]
        if eff["daily_max_rounds"] > 0 or eff["daily_max_minutes"] > 0:
            argv += ["--daily-usage-file", str(self.logs_dir / "emu_daily_usage.json")]
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
        if not any(w["exit_code"] is None for w in self._workers.values()):
            self._stop_ocr_server()

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
                if options["shared_ocr"]:
                    self._ensure_ocr_server()
                launch_options = {}
                # Remove stale inherited sessions even when shared OCR is disabled.
                if ("KARDS_EMU_OCR_URL" in os.environ or "KARDS_EMU_OCR_TOKEN" in os.environ
                        or (options["shared_ocr"] and self._ocr_running())):
                    env = {k: v for k, v in os.environ.items()
                           if k not in ("KARDS_EMU_OCR_URL", "KARDS_EMU_OCR_TOKEN")}
                    if options["shared_ocr"] and self._ocr_running():
                        env.update(KARDS_EMU_OCR_URL=self._ocr_url, KARDS_EMU_OCR_TOKEN=self._ocr_token)
                    launch_options["env"] = env
                proc = self.popen_fn(argv, cwd=str(self.project_root),
                                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                                     **launch_options)
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                self._reap()
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
        if provider is None and instance.provider == "ldplayer":
            provider = emu_discovery.LDPlayerProvider(ld_root=instance.extra.get("ld_root"))
        if provider is None and instance.provider == "bluestacks":
            provider = emu_discovery.BlueStacksProvider(conf_path=instance.extra.get("conf_path"))
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
        # Keep the GUI manager independent of the worker's cv2/vision imports.
        try:
            usage = json.loads((self.logs_dir / "emu_daily_usage.json").read_text(encoding="utf-8-sig"))
            today = usage.get(datetime.now().strftime("%Y-%m-%d"), {})
            if not isinstance(today, dict):
                today = {}
        except (OSError, ValueError, AttributeError):
            today = {}
        for inst in instances:
            iid = inst["instance_id"]
            entry = today.get(iid, {})
            rounds, minutes = 0, 0.0
            if isinstance(entry, dict):
                r, m = entry.get("rounds", 0), entry.get("minutes", 0.0)
                if type(r) is int and r >= 0:
                    rounds = r
                if type(m) in (int, float) and math.isfinite(m) and m >= 0:
                    minutes = round(float(m), 1)
            inst.update(daily_rounds=rounds, daily_minutes=minutes,
                        override=options["instance_overrides"].get(iid, {}).copy())
        return {"instances": instances, "running_count": sum(i["worker_running"] for i in instances),
                "options": options, "shared_ocr_running": bool(self._ocr_running()),
                "log": self.tail_instance_log(selected_log_id, since_rev=log_since_rev) if selected_log_id else None}

    def has_running_workers(self) -> bool:
        with self._lock:
            self._reap()
            return any(w["exit_code"] is None for w in self._workers.values())
