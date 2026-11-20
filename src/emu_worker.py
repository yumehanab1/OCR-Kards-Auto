"""One emulator per process. Run with --instance mumu:7 --mode training.

Counters describe dispatched attempts, not confirmed game effects. --dry-run
captures/classifies/plans but never taps, drags, launches or stops a package.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import signal
import tempfile
import threading
import time

import cv2

if __package__:
    from .emu_transport import EmuTransportError
    from .emu_vision import EmuVision, frame_motion
else:
    from emu_transport import EmuTransportError
    from emu_vision import EmuVision, frame_motion


@dataclass
class WorkerConfig:
    instance_id: str
    mode: str = "training"
    deck_name: str = ""
    max_rounds: int = 0
    prefer_ipc: bool = True
    allow_attack: bool = True
    allow_deploy: bool = True
    allow_end_turn: bool = True
    dry_run: bool = False
    auto_launch_kards: bool = True
    stop_mobile_helper: bool = True
    poll_interval: float = .35
    stop_file: str | None = None
    log_file: str | None = None
    status_file: str | None = None
    adb_path: str | None = None
    extra_serial: str | None = None
    max_seconds: float = 0.0

    def __post_init__(self):
        if self.mode not in ("training", "casual", "ranked"):
            raise ValueError("Unsupported mode")
        if self.max_rounds < 0 or self.max_seconds < 0 or self.poll_interval <= 0:
            raise ValueError("Limits must be nonnegative; poll interval must be positive")


class EmuWorker:
    def __init__(self, config: WorkerConfig, transport=None, vision=None,
                 sleep_fn=time.sleep, clock_fn=time.monotonic):
        self.cfg = config
        self.transport, self.vision = transport, vision
        self.sleep_fn, self.clock = sleep_fn, clock_fn
        self.stop_event = threading.Event()
        self._started = self.clock()
        self._startup_done = False
        self._last_foreground = self._last_launch = float("-inf")
        self._foreground = False
        self._unknown_streak = 0
        self._last_unknown_ocr = float("-inf")
        self._unknown_turn_streak = 0
        self._match_recorded = False
        self._match_turns = 0
        self._match_started = self._started
        self._settling = False
        self._settle_clicks = 0
        self._captures = 0
        self._capture_ms = 0.0
        self._reset_turn()
        now = self._timestamp()
        self.status = dict(instance_id=config.instance_id, name=config.instance_id,
                           pid=os.getpid(), backend=getattr(transport, "backend_name", ""),
                           running=False, state="unknown", mode=config.mode, rounds_done=0,
                           victories=0, defeats=0, turns=0, deploys=0, attacks=0,
                           last_action="", last_error="", avg_capture_ms=0.0,
                           started_at=now, updated_at=now)

    @staticmethod
    def _timestamp():
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def log(self, message):
        line = f"{self._timestamp()} {message}"
        print(line, flush=True)
        if self.cfg.log_file:
            path = Path(self.cfg.log_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as out:
                out.write(line + "\n")

    def _write_status(self):
        self.status["updated_at"] = self._timestamp()
        if not self.cfg.status_file:
            return
        path = Path(self.cfg.status_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             prefix=path.name+".", suffix=".tmp", delete=False) as out:
                temporary = out.name
                json.dump(self.status, out, ensure_ascii=False, indent=2)
                out.flush()
                os.fsync(out.fileno())
            # Windows readers can briefly hold the destination without delete
            # sharing. Keep the previous status intact until replacement works.
            delays = (.02, .04, .08, .12, .20)
            for attempt in range(len(delays) + 1):
                try:
                    os.replace(temporary, path)
                    break
                except OSError:
                    if attempt == len(delays):
                        raise
                    self.sleep_fn(delays[attempt])
        except OSError as exc:
            self.log(f"warning: status write skipped: {exc}")
        finally:
            if temporary:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass

    def stop(self):
        self.stop_event.set()

    def should_stop(self):
        if (self.stop_event.is_set() or
                (self.cfg.stop_file and Path(self.cfg.stop_file).exists()) or
                (self.cfg.max_seconds > 0 and self.clock()-self._started >= self.cfg.max_seconds)):
            self.stop_event.set()
            return True
        return False

    def _sleep(self, seconds):
        end = self.clock() + seconds
        while not self.should_stop():
            remaining = end-self.clock()
            if remaining <= 0:
                break
            self.sleep_fn(min(.1, remaining))

    def _startup(self):
        if self._startup_done or self.should_stop():
            return
        if self.transport is None:
            if __package__:
                from .emu_discovery import discover_all
                from .emu_transport import create_transport
            else:
                from emu_discovery import discover_all
                from emu_transport import create_transport
            instances = discover_all(extra_serials=[self.cfg.extra_serial] if self.cfg.extra_serial else [],
                                     adb_path=self.cfg.adb_path)
            instance = next((i for i in instances if i.instance_id == self.cfg.instance_id or
                             "adb:"+str(i.adb_serial) == self.cfg.instance_id), None)
            if instance is None:
                raise RuntimeError(f"Instance not found: {self.cfg.instance_id}")
            self.status["name"] = instance.name
            if self.should_stop():
                return
            self.transport = create_transport(instance, self.cfg.prefer_ipc, log=self.log)
        self.status["backend"] = self.transport.backend_name
        self._startup_done = True
        if self.cfg.stop_mobile_helper and not self.cfg.dry_run and not self.should_stop():
            try:
                if not self.transport.force_stop_package("com.kards.mobilert"):
                    self.log("warning: mobile helper force-stop not confirmed")
            except EmuTransportError as exc:
                self.log(f"warning: mobile helper force-stop: {exc}")
        if self.vision is None:
            self.vision = EmuVision()

    def _capture(self):
        if self.should_stop():
            return None
        before = self.clock()
        frame = self.transport.capture_bgr()
        self._capture_ms += (self.clock()-before)*1000
        self._captures += 1
        self.status["avg_capture_ms"] = round(self._capture_ms/self._captures, 3)
        return frame

    def _observe(self, frame):
        return self.vision.classify_screen(frame, target_mode=self.cfg.mode, deck_name=self.cfg.deck_name,
                                           allow_fast_opponent=self._match_turns > 0)

    def _input(self, kind, target=None, path=None, duration_ms=650):
        if self.should_stop():
            return False
        self.status["last_action"] = ("dry_run:" if self.cfg.dry_run else "") + kind
        if self.cfg.dry_run:
            self.log(f"[dry-run] {kind} {path or target}")
            return False
        if path is not None:
            self.transport.drag(path, duration_ms=duration_ms)
        else:
            self.transport.tap(*target)
        return True

    def _reset_turn(self):
        self._in_own_turn = False
        self._turn_rechecked = False
        self.skip_actors, self.skip_grabs = set(), set()
        self.attacks_this_turn = self.deploys_this_turn = self.end_retries = 0

    def _foreground_ready(self):
        if not self.cfg.auto_launch_kards:
            return True
        now = self.clock()
        interval = 1.0 if self._unknown_streak >= 3 else 5.0
        if now-self._last_foreground < interval:
            if not self._foreground:
                self._sleep(self.cfg.poll_interval)
            return self._foreground
        self._last_foreground = now
        if self.should_stop():
            return False
        try:
            foreground, _ = self.transport.is_kards_foreground()
            self._foreground = foreground
            if foreground:
                return True
            if not self.cfg.dry_run and now-self._last_launch >= 20 and not self.should_stop():
                self._last_launch = now
                self.log("launching KARDS")
                self.transport.launch_kards()
        except EmuTransportError as exc:
            self.log(f"warning: KARDS foreground/launch: {exc}; retrying later")
            self._foreground = False
        self._sleep(1.0)
        return False

    def _settle(self):
        if self._settle_clicks < 15:
            if self._input("settle", (640, 665)):
                self._settle_clicks += 1
        self._sleep(1.0)

    def _own_turn(self, frame, obs):
        if not self._in_own_turn:
            self._in_own_turn = True
            self.status["turns"] += 1
            self._match_turns += 1
            self.log("our turn starts")
            self._sleep(1.2)
            frame = self._capture()
            if frame is None:
                return
            obs = self._observe(frame)
            if obs.state != "own_turn":
                return
        if self.should_stop():
            return
        if self.cfg.allow_attack and self.attacks_this_turn < 10:
            plan = self.vision.plan_combat_action(frame, self.skip_actors)
            if plan:
                marker = "move" if plan.kind == "move_front" else "attack"
                self.log(f"[{marker}] {plan.kind} {plan.origin} -> {plan.target}")
                sent = self._input(plan.kind, path=[plan.origin, plan.target], duration_ms=650)
                if not sent:
                    self._sleep(self.cfg.poll_interval)
                    return
                self.attacks_this_turn += 1
                self.status["attacks"] += 1
                self._sleep(1.1)
                after = self._capture()
                if frame_motion(frame, after) < .004:
                    self.skip_actors.add(plan.key)
                return
        if self.cfg.allow_deploy and self.deploys_this_turn < 6:
            plan = self.vision.plan_deploy_action(frame, self.skip_grabs)
            if plan:
                self.log(f"[deploy] {plan.origin} -> {plan.target}")
                if not self._input("deploy", path=plan.path, duration_ms=900):
                    self._sleep(self.cfg.poll_interval)
                    return
                self.deploys_this_turn += 1
                self.status["deploys"] += 1
                deadline, changed, rejected = self.clock()+3.5, False, False
                while self.clock() < deadline and not self.should_stop():
                    self._sleep(min(.6, deadline-self.clock()))
                    after = self._capture()
                    if after is None:
                        break
                    rejected = self.vision.detect_insufficient_kredits(after)
                    changed = frame_motion(frame, after, (200, 415, 1120, 720)) >= .004
                    if rejected or changed:
                        break
                if rejected or not changed:
                    self.skip_grabs.add(plan.key)
                return
        if ((self.cfg.allow_attack or self.cfg.allow_deploy)
                and self.attacks_this_turn == 0 and self.deploys_this_turn == 0 and not self._turn_rechecked):
            self._turn_rechecked = True
            self.log(f"[turn] no deploy/attack (deploy={getattr(self.vision, 'last_deploy_reason', '')})")
            self._sleep(.8)
            return
        if self.cfg.allow_end_turn and obs.target:
            self.log(f"[turn] ending turn (deploy={getattr(self.vision, 'last_deploy_reason', '')})")
            if not self._input("end_turn", obs.target):
                self._sleep(self.cfg.poll_interval)
                return
            deadline = self.clock()+3.5
            while self.clock() < deadline and not self.should_stop():
                self._sleep(min(.6, deadline-self.clock()))
                after = self._capture()
                if after is None:
                    break
                result = self.vision.classify_battle(after)
                if result is None or result.state != "own_turn":
                    # The own-turn button disappeared after our end-turn tap.
                    self._reset_turn()
                    return
            self.end_retries += 1
            if self.end_retries >= 3:
                self.log("warning: end turn still unconfirmed after 3 attempts")
                self._sleep(1.0)
        else:
            self._sleep(self.cfg.poll_interval)

    def step(self):
        if self.should_stop():
            return False
        self._startup()
        if self.should_stop():
            return False
        self.status["running"] = True
        try:
            if not self._foreground_ready():
                return not self.should_stop()
            frame = self._capture()
            if frame is None:
                self._sleep(self.cfg.poll_interval)
                return not self.should_stop()
            obs = self._observe(frame)
            state = obs.state
            if state != self.status["state"]:
                self.log(f"state -> {state}")
            if state == "unknown" and obs.ocr_texts:
                now = self.clock()
                if self.status["state"] != "unknown" or now-self._last_unknown_ocr >= 15:
                    summary = " | ".join(" ".join(t.split()) for t in obs.ocr_texts[:6])[:140]
                    self.log(f"unknown OCR: {summary}")
                    self._last_unknown_ocr = now
            self.status["state"] = state
            if state in ("home", "deck_list", "deck_detail", "queueing", "mulligan", "victory", "defeat"):
                self._match_turns = 0
                self._reset_turn()
            self._unknown_streak = self._unknown_streak+1 if state in ("unknown", "blank") else 0
            self._unknown_turn_streak = self._unknown_turn_streak+1 if state == "unknown" else 0
            if self._in_own_turn and self._unknown_turn_streak >= 3:
                self._reset_turn()
            if state in ("own_turn", "opponent_turn", "in_game", "mulligan", "queueing"):
                if self._match_recorded:
                    self._match_started = self.clock()
                self._match_recorded = False
                self._settling = False
                self._settle_clicks = 0
            if state in ("home", "deck_list", "deck_detail"):
                self._settling = False
                self._reset_turn()
                if self.cfg.max_rounds > 0 and self.status["rounds_done"] >= self.cfg.max_rounds:
                    self.stop()
                    return False
            if state in ("victory", "defeat"):
                if not self._match_recorded:
                    self._match_recorded = True
                    self._settling = True
                    self.status["rounds_done"] += 1
                    self.status["victories" if state == "victory" else "defeats"] += 1
                    elapsed = (self.clock()-self._match_started)/60
                    self.log(f"== round {self.status['rounds_done']} finished ({state}) after {elapsed:.2f} min ==")
                self._reset_turn()
                self._settle()
            elif state in ("login_reward", "task_popup", "promo_popup", "disconnected", "home",
                           "deck_list", "deck_detail"):
                if obs.target:
                    self._input(state, obs.target)
                self._sleep(1.0)
            elif state == "mulligan":
                self._sleep(.6)
                after = self._capture()
                if after is not None and frame_motion(frame, after) < .02:
                    settled = self._observe(after)
                    if settled.state == "mulligan" and settled.target:
                        self._input(state, settled.target)
                        self._sleep(1.0)
            elif state == "choice_modal":
                self._sleep(.6)
                if self._match_turns > 0:
                    after = self._capture()
                    if (after is not None and frame_motion(frame, after) < .015
                            and self._observe(after).state == "choice_modal"):
                        self._input(state, (640, 360))
                        self._sleep(1.2)
            elif state == "target_selection":
                self._input(state, self.vision.enemy_hq(frame) or (1200, 680))
                self._sleep(1.0)
            elif state == "opponent_turn":
                self._reset_turn()
                self._sleep(1.0)
            elif state == "queueing":
                self._sleep(1.5)
            elif state == "own_turn":
                self._own_turn(frame, obs)
            elif state == "unknown" and self._settling:
                self._settle()
            elif state in ("unknown", "blank") and not self._settling:
                self._sleep(1.0 if self._unknown_streak < 3 else 2.0)
            else:
                self._sleep(self.cfg.poll_interval)
            return not self.should_stop()
        finally:
            self.status["running"] = not self.should_stop()
            self._write_status()

    def run(self):
        try:
            while self.step():
                pass
        except Exception as exc:
            self.status["last_error"] = f"{type(exc).__name__}: {exc}"
            self.log(f"error: {self.status['last_error']}")
            self.stop()
        finally:
            try:
                if self.transport is not None:
                    self.transport.close()
            finally:
                self.status["running"] = False
                self._write_status()
        return dict(self.status)


def main(argv=None):
    cv2.setNumThreads(2)
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.GetCurrentProcess.restype = ctypes.c_void_p
            kernel32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            kernel32.SetPriorityClass.restype = ctypes.c_int
            if not kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), 0x00004000):
                raise ctypes.WinError()
        except Exception as exc:
            print(f"warning: could not lower worker priority: {exc}", flush=True)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", required=True)
    parser.add_argument("--mode", choices=("training", "casual", "ranked"), default="training")
    parser.add_argument("--deck", default="")
    parser.add_argument("--max-rounds", type=int, default=0)
    backend = parser.add_mutually_exclusive_group()
    backend.add_argument("--prefer-ipc", dest="prefer_ipc", action="store_true", default=True)
    backend.add_argument("--adb-only", dest="prefer_ipc", action="store_false")
    for option in ("attack", "deploy", "end-turn"):
        parser.add_argument("--no-"+option, dest="allow_"+option.replace("-", "_"), action="store_false")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-auto-launch", dest="auto_launch_kards", action="store_false")
    for option in ("stop-file", "log-file", "status-file", "extra-serial", "adb-path"):
        parser.add_argument("--"+option)
    parser.add_argument("--max-seconds", type=float, default=0.0)
    args = vars(parser.parse_args(argv))
    args["instance_id"], args["deck_name"] = args.pop("instance"), args.pop("deck")
    worker = EmuWorker(WorkerConfig(**args))
    def stop_handler(signum, frame):
        worker.stop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, stop_handler)
    result = worker.run()
    return 1 if result["last_error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
