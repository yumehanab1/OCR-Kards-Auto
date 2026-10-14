"""APK-owned adapter for the frozen mobile engine; no shell, ADB or Termux.

Java calls run on one worker thread. All capture/input crosses the supplied
Accessibility bridge. The engine and its before/after verification remain the
packaged mobile core. This adapter is intentionally outside the G8 source line.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
import types

from apk_end_turn_ledger import EndTurnLedger


class Stop(BaseException):
    """A terminal refusal must not be swallowed by legacy except Exception."""


class Replan(BaseException):
    """No gesture was accepted; discard provisional records and get new frames."""


def _json_default(value):
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "tolist"):
        return value.tolist()
    raise TypeError(type(value).__name__)


def _json(value):
    return json.dumps(value, ensure_ascii=False, default=_json_default)


def _parse(value):
    return value if isinstance(value, dict) else json.loads(str(value))


def options_from_json(value):
    supplied = _parse(value or "{}")
    allowed = {"read_only", "max_inputs", "max_seconds", "max_failed_inputs",
               "idle_seconds", "unknown_seconds", "deploy_enabled"}
    if not isinstance(supplied, dict) or set(supplied) - allowed:
        raise ValueError("unsupported_runtime_options")
    result = {"read_only": True, "max_inputs": 1, "max_seconds": 120,
              "max_failed_inputs": 5, "idle_seconds": 120,
              "unknown_seconds": 15, "deploy_enabled": True}
    result.update(supplied)
    for name in ("read_only", "deploy_enabled"):
        if type(result[name]) is not bool:
            raise ValueError("invalid_" + name)
    for name, low, high in (("max_inputs", 1, 300), ("max_seconds", 10, 1800),
                            ("max_failed_inputs", 1, 10), ("idle_seconds", 15, 300),
                            ("unknown_seconds", 5, 45)):
        if type(result[name]) not in (int, float) or not math.isfinite(result[name]):
            raise ValueError("invalid_" + name)
        if not low <= result[name] <= high:
            raise ValueError("invalid_" + name)
    for name in ("max_inputs", "max_failed_inputs"):
        if int(result[name]) != result[name]:
            raise ValueError("invalid_" + name)
        result[name] = int(result[name])
    return result


def deployment_path_points(origin, target):
    """Fixed deployment-only lift; a hypothesis to validate on live selection."""
    for point in (origin, target):
        if (not isinstance(point, (list, tuple)) or len(point) != 2 or
                any(type(v) not in (int, float) or not math.isfinite(v) for v in point)):
            return None
    return [list(origin), [origin[0], min(575, origin[1] - 60)], list(target)]


def validate_gesture(gesture, context, info, now_ms, remaining_ms, count, options):
    """Independent normalized-coordinate guard before Java's final dispatch gate."""
    if options["read_only"]:
        raise Stop("read_only_input_forbidden")
    if count >= options["max_inputs"]:
        raise Stop("input_budget")
    if remaining_ms < 8000:
        raise Stop("time_budget_before_input")
    if context not in ("deploy", "attack_unit", "attack_hq", "move_front", "end_turn"):
        raise Stop("input_without_engine_hook")
    if (not info or info.get("state") != "in_game" or
            info.get("button") not in ("white", "orange") or
            info.get("transition_reason") or info.get("choice_modal")):
        raise Stop("input_without_recent_own_turn_frame")
    expected = "tap" if context == "end_turn" else "drag"
    if gesture.get("kind") != expected:
        raise Stop("unexpected_gesture_kind")
    for name in ("from", "to"):
        point = gesture.get(name)
        if (not isinstance(point, (list, tuple)) or len(point) != 2 or
                any(type(v) not in (int, float) or not math.isfinite(v) for v in point) or
                not (0 <= point[0] < 1280 and 0 <= point[1] < 720)):
            raise Stop("invalid_gesture_" + name)
    duration = gesture.get("duration_ms")
    if type(duration) not in (int, float) or not math.isfinite(duration):
        raise Stop("invalid_gesture_duration")
    if expected == "drag":
        if not 100 <= duration <= 2500:
            raise Stop("invalid_drag_duration")
        if gesture["from"][1] >= 570 and context != "deploy":
            raise Stop("unidentified_hand_deployment_forbidden")
    else:
        if not 40 <= duration <= 150 or gesture["from"] != gesture["to"]:
            raise Stop("invalid_tap")
        box = info.get("button_box")
        if not box or len(box) != 4:
            raise Stop("end_button_location_unknown")
        x, y, w, h = box
        tx, ty = gesture["from"]
        if not (x <= tx <= x + w and y <= ty <= y + h):
            raise Stop("tap_outside_current_end_button")
    if context == "deploy":
        points = gesture.get("path_points")
        expected_points = deployment_path_points(gesture["from"], gesture["to"])
        if duration != 900:
            raise Stop("invalid_deployment_duration")
        if (gesture["from"][1] < 560 or not isinstance(points, (list, tuple)) or len(points) != 3 or
                any(not isinstance(p, (list, tuple)) or len(p) != 2 or
                    any(type(v) not in (int, float) or not math.isfinite(v) for v in p) for p in points) or
                [list(p) for p in points] != expected_points):
            raise Stop("invalid_deployment_path")
    elif "path_points" in gesture:
        raise Stop("path_points_outside_deployment")
    captured = info.get("captured_elapsed_ms")
    if type(captured) not in (int, float) or captured > now_ms:
        raise Stop("invalid_capture_timestamp")
    if now_ms - captured > 3000:
        raise Replan("input_frame_age_exceeded_replan")


class ChoiceModalGate:
    """G8 modal gate: suspect frames forbid touch; three stable frames confirm."""
    def __init__(self, motion_max):
        self.motion_max = motion_max
        self.first_seen = self.stable_since = self.last_seen = None
        self.stable_frames = 0

    def observe(self, present, now, motion):
        if not present:
            self.first_seen = self.stable_since = self.last_seen = None
            self.stable_frames = 0
            return "clear"
        if self.first_seen is None:
            self.first_seen = self.stable_since = self.last_seen = now
            self.stable_frames = 1
            return "waiting"
        gap = now - self.last_seen
        if gap >= .4:
            if gap <= 5 and motion is not None and motion <= self.motion_max:
                self.stable_frames += 1
            else:
                self.stable_frames = 1
                self.stable_since = now
            self.last_seen = now
        elif gap < 0 or (motion is not None and motion > self.motion_max):
            self.stable_frames = 1
            self.stable_since = self.last_seen = now
        if self.stable_frames >= 3 and now - self.stable_since >= 3:
            return "confirmed"
        return "timeout" if now - self.first_seen >= 12 else "waiting"


def discard_provisional(engine, attack, hand):
    engine._board_stability.reset()
    engine._combat_decision_context = None
    engine._after_frame = None
    if engine.trace is not None:
        engine.trace.after = None
    attack.take_last_attempt()
    attack.take_last_actor()
    attack.take_last_pending()
    hand.take_last_deploy_attempt()
    hand.take_last_deploy_pending()


class AccessibilityPlatform:
    """Legacy platform primitives accumulate only; mouse_up emits one gesture."""
    name = "android"

    def __init__(self, runtime):
        self.runtime = runtime
        self._position = None
        self._points = []
        self._down_ms = None

    def capture_client(self, hwnd=None):
        return self.runtime.capture()

    def capture_screen(self, monitor_index=0):
        return self.capture_client()

    def client_size(self, hwnd=None):
        return 1280, 720

    def client_to_screen(self, hwnd, x, y):
        # "screen" is the bridge's documented normalized 1280x720 space.
        return int(x), int(y)

    def find_game_window(self):
        return True if not self.runtime.bridge.isCancelled() else None

    def set_dpi_aware(self):
        pass

    def cursor_pos(self):
        return None

    def set_cursor(self, x, y):
        self._position = (int(x), int(y))
        if self._down_ms is not None:
            self._points.append(self._position)

    def mouse_move(self, x, y):
        self.set_cursor(x, y)

    def mouse_down(self):
        self.runtime.check_running()
        if self._position is None or self._down_ms is not None:
            raise Stop("invalid_pointer_sequence")
        self._down_ms = self.runtime.now()
        self._points = [self._position]

    def mouse_up(self):
        if self._down_ms is None or not self._points:
            raise Stop("pointer_up_without_down")
        origin, target = self._points[0], self._points[-1]
        duration = self.runtime.now() - self._down_ms
        moved = any(point != origin for point in self._points)
        self._down_ms, self._points = None, []
        gesture = {"kind": "drag" if moved else "tap", "from": list(origin),
                   "to": list(target), "duration_ms": int(max(900, min(2500, duration))) if moved else 60}
        if moved and getattr(self.runtime, "context", None) == "deploy":
            gesture.update(duration_ms=900, path_points=deployment_path_points(origin, target))
        self.runtime.dispatch(gesture)

    def flush_input(self):
        # mouse_up dispatches. A partial trajectory must never become an input.
        if self._down_ms is not None:
            raise Stop("unfinished_pointer_sequence")


class Runtime:
    def __init__(self, bridge, core_root, evidence_root, options):
        self.bridge = bridge
        self.root = Path(core_root).resolve()
        self.out = Path(evidence_root).resolve()
        self.options = options
        self.started = self.now()
        self.deadline = self.started + options["max_seconds"] * 1000
        campaign_deadline = getattr(bridge, "deadlineElapsedRealtime", None)
        if campaign_deadline is not None:
            value = campaign_deadline()
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("invalid_campaign_deadline")
            self.deadline = min(self.deadline, int(value))
        self.out.mkdir(parents=True, exist_ok=True)
        self.events = (self.out / "battle-events.jsonl").open("x", encoding="utf-8")
        self.context = None
        self.last_frame = self.last_info = None
        self.last_id = -1
        self._hand_cache_frame = None
        self._hand_cache = {}
        self._board_cache = None
        self._stable_seed = None
        self.last_progress = self.started
        self.unknown_since = None
        self.failed_inputs = 0
        self._deployment_boundary_evidence = None
        self._deployment_dispatched_source = None
        self._simple_deployment_plan = None
        from apk_simple_deploy import FailedLayoutLedger
        self._simple_deploy_ledger = FailedLayoutLedger()
        self.end_turn_ledger = EndTurnLedger()
        self.end_turn_blocked_turn = None
        self.engine = None
        self._result_state = None
        self._result_since = None
        self._result_count = 0
        self.report = {"scope": "apk_embedded_mobile_engine", "runtime_version": 1,
                       "read_only": options["read_only"], "options": options,
                       "host_inputs": 0, "game_inputs": 0, "actions_confirmed": 0,
                       "unconfirmed_inputs": 0, "failed_inputs": 0, "pending_end_turn_inputs": 0,
                       "unconfirmed_skipped": 0,
                       "deployment_refusals_confirmed": 0,
                       "end_turns_confirmed": 0, "end_turns_unconfirmed": 0, "end_turn_outcomes": [],
                       "deadline_elapsed_ms": self.deadline,
                       "captures": 0, "hooks": [], "inputs": [], "stop_reason": None,
                       "exception": None, "result_verified": False,
                       "full_game_passed": False, "core_root": str(self.root),
                       "evidence_root": str(self.out)}

    def _clear_hand_cache(self):
        self._hand_cache_frame = None
        self._hand_cache.clear()

    def _clear_board_cache(self):
        stat_sampler = getattr(self, "stat_sampler", None)
        if stat_sampler is not None:
            try:
                stat_diagnostics = stat_sampler.diagnostics()
                if stat_diagnostics.get("recovered_plate_count"):
                    self.event("green_stat_capture_summary", stat_diagnostics)
            except Exception:
                # Optional counters must not interrupt cancellation, expiry or
                # clearing recognition state. Required action events retain
                # their existing error handling and evidence obligations.
                self.report["green_stat_diagnostics_dropped"] = self.report.get("green_stat_diagnostics_dropped", 0) + 1
            finally:
                stat_sampler.clear()
        cache = getattr(self, "_board_cache", None)
        if cache is not None:
            cache.clear()
        artwork = getattr(self, "artwork_filter", None)
        if artwork is not None:
            artwork.clear()
        hq_splitter = getattr(self, "hq_splitter", None)
        if hq_splitter is not None:
            hq_splitter.clear()

    def _install_board_cache(self):
        from apk_current_capture_memo import CurrentCaptureMemo, NAMES, configuration_epoch
        # The first stat read loads this module lazily. Include its callbacks
        # and template bank before choosing memo dependencies; importing does
        # not build the bank.
        import kredits_templates
        # Adapters have finished binding before this snapshot scope is chosen.
        # Their callback identities and literal constants remain checked on hits.
        modules = [self.mb, self.mb.us, self.mb.hq_hp]
        modules.extend(sys.modules[name] for name in
                       ("apk_hq_adapter", "apk_hq_geometry", "apk_hq_row_split", "apk_board_artwork", "apk_green_stat", "kredits_templates", "mobile_combat_vision")
                       if name in sys.modules)
        self._board_cache = CurrentCaptureMemo(
            {name: getattr(self.mb, name) for name in NAMES},
            session_epoch=object(), config_epoch=lambda: configuration_epoch(modules),
            eligible=lambda: not self.bridge.isCancelled() and self.now() < self.deadline)
        self._board_cache.bind(self.mb)

    def _register_board_capture(self, frame, info):
        stat_sampler = getattr(self, "stat_sampler", None)
        if stat_sampler is not None:
            stat_sampler.register(frame, info)
        hq_splitter = getattr(self, "hq_splitter", None)
        if hq_splitter is not None:
            hq_splitter.register(frame, info)
        artwork = getattr(self, "artwork_filter", None)
        if artwork is not None:
            artwork.register(frame, info)
        cache = getattr(self, "_board_cache", None)
        if cache is not None:
            cache.register(frame, info)

    def _hand_frame_token(self, frame):
        """Only the current capture's exact full pixels can reuse recognition.

        Identity alone is insufficient: core callers may mutate an ndarray.
        The capture timestamp stays in the key and is never refreshed by hits.
        """
        import numpy as np
        info = self.last_info
        if (frame is not self.last_frame or not isinstance(frame, np.ndarray)
                or frame.shape != (720, 1280, 3) or frame.dtype != np.uint8
                or not frame.flags.c_contiguous or not isinstance(info, dict)
                or type(info.get("frame_id")) is not int or info["frame_id"] != self.last_id
                or any(type(info.get(k)) is not int for k in (
                    "captured_elapsed_ms", "foreground_generation", "source_width", "source_height"))):
            self._clear_hand_cache()
            return None
        token = (id(frame), self.last_id, info["captured_elapsed_ms"],
                 info["foreground_generation"], info["source_width"], info["source_height"],
                 hashlib.blake2b(memoryview(frame), digest_size=16).digest())
        if token != self._hand_cache_frame:
            self._clear_hand_cache()
            self._hand_cache_frame = token
        return token

    def _same_frame_hand_observation(self, frame, key, observe):
        token = self._hand_frame_token(frame)
        if token is not None and key in self._hand_cache:
            return copy.deepcopy(self._hand_cache[key]), True
        result = observe()
        # A recognizer changing pixels cannot cache its pre-change result.
        if token is not None and self._hand_frame_token(frame) == token:
            self._hand_cache[key] = copy.deepcopy(result)
        return result, False

    def _find_raw_hand(self, frame, zone=None, want="orange", units_only=False, debug=False, max_units=0):
        # Keep every recognition option distinct, including debug and limits;
        # Only integer list/tuple zones are cacheable. A float zone must retain
        # the core's slicing error rather than alias an equal integer key.
        if (zone is not None and (not isinstance(zone, (list, tuple))
                or any(type(v) is not int for v in zone))):
            return self._core_find_hand(frame, zone=zone, want=want, units_only=units_only,
                                        debug=debug, max_units=max_units)
        if not (isinstance(want, str) and type(units_only) is bool and type(debug) is bool
                and type(max_units) is int):
            return self._core_find_hand(frame, zone=zone, want=want, units_only=units_only,
                                        debug=debug, max_units=max_units)
        key = ("raw", None if zone is None else tuple(zone), want, units_only, debug, max_units)
        result, _ = self._same_frame_hand_observation(frame, key, lambda: self._core_find_hand(
            frame, zone=zone, want=want, units_only=units_only, debug=debug, max_units=max_units))
        return result

    def now(self):
        return int(self.bridge.elapsedRealtime())

    def check_running(self):
        if self.bridge.isCancelled():
            self._clear_board_cache()
            raise Stop("cancelled")
        if self.now() >= self.deadline:
            self._clear_board_cache()
            raise Stop("time_budget")

    def event(self, kind, value):
        encoded = _json({"elapsed_ms": self.now() - self.started, "kind": kind, "value": value})
        self.events.write(encoded + "\n")
        self.events.flush()
        self.bridge.emit(encoded)

    def load_core(self):
        sys.dont_write_bytecode = True
        source = self.root / "src"
        if not (source / "turn_engine_mobile.py").is_file():
            raise Stop("packaged_core_missing")
        # CPython is retained across sessions. Never silently mix core versions.
        loaded = sys.modules.get("turn_engine_mobile")
        if loaded is not None and Path(loaded.__file__).resolve().parent != source:
            raise Stop("different_core_already_loaded_restart_app")
        if str(source) not in sys.path:
            sys.path.insert(0, str(source))
        import platformapi
        self.platformapi = platformapi
        self.platform = AccessibilityPlatform(self)
        platformapi.set_platform(self.platform)
        shim = types.ModuleType("win")
        shim.capture_client_bgr = lambda *args, **kwargs: platformapi.get().capture_client(*args, **kwargs)
        shim.find_by_process = lambda *args, **kwargs: platformapi.get().find_game_window()
        shim.set_dpi_aware = lambda: platformapi.get().set_dpi_aware()
        sys.modules["win"] = shim
        os.environ["KARDS_PLATFORM"] = "android"
        os.environ["KARDS_TRACE"] = "0"
        os.environ["KARDS_DUMP_DIR"] = str(self.out / "actions")
        os.environ["KARDS_TRACE_DIR"] = str(self.out / "trace")
        import cv2
        import numpy as np
        import ui_state
        import mobile_board
        import mobile_hand
        import mobile_attack
        import mobile_end_button
        import turn_engine_mobile
        self.cv2, self.np, self.ui = cv2, np, ui_state
        self.mb, self.mh, self.ma = mobile_board, mobile_hand, mobile_attack
        self.end_button = mobile_end_button
        self.tem = turn_engine_mobile
        import actions
        import apk_direct_drag
        self.event("direct_drag_adapter", apk_direct_drag.install(self, actions))
        # APK-specific HUD support is isolated from the unchanged mobile core.
        try:
            import apk_hud_adapter
        except ImportError:
            self.event("hud_adapter", "not_packaged_standard_layout_only")
        else:
            self.event("hud_adapter", apk_hud_adapter.install())
        import apk_hq_adapter
        self.event("hq_adapter", apk_hq_adapter.install())
        import apk_hq_geometry
        self.event("hq_geometry", apk_hq_geometry.install())
        import apk_green_stat
        self.stat_sampler = apk_green_stat.install(self.mb)
        self.event("green_stat_adapter", {"installed": True, "support_band": [540, 586],
                                         "score_min": .86, "digit_margin_min": .12})
        import apk_hq_row_split
        self.hq_splitter = apk_hq_row_split.install(self.mb)
        import apk_board_artwork
        self.artwork_filter = apk_board_artwork.install(self.mb)
        self.event("board_structure_adapters", {"hq_row_split": True, "artwork_negative_filter": True})
        self.install_hand_adapter()
        meta, note = ui_state.load_platform_meta("android")
        self.templates = ui_state.load_templates(meta)
        states = ui_state.load_states(str(self.root / "config" / "states.json"))
        self.states = {**{k: states[k] for k in ("victory", "defeat") if k in states}, **states}
        self.choice_gate = ChoiceModalGate(self.mb.BOARD_MOTION_MAX)
        discard_provisional(types.SimpleNamespace(_board_stability=types.SimpleNamespace(reset=lambda: None),
                                                  trace=None), self.ma, self.mh)
        self.event("core_loaded", {"templates": len(self.templates), "note": note,
                                   "numpy": np.__version__, "opencv": cv2.__version__})

    def install_hand_adapter(self):
        """APK-only candidate vetoes; preserve the packaged core and its hooks.

        Modules survive sessions in embedded CPython, so retain the original
        functions on the module rather than wrapping the last session again.
        """
        hand = self.mh
        if not hasattr(hand, "_apk_original_find_hand"):
            hand._apk_original_find_hand = hand.find_hand
            hand._apk_original_grab_point = hand.grab_point
        self._core_find_hand = hand._apk_original_find_hand
        self._core_grab_point = hand._apk_original_grab_point
        hand.find_hand = self.find_hand
        hand.grab_point = self.grab_point

    @staticmethod
    def approved_grab_point(badge):
        approval = badge.get("apk_availability", {})
        point = badge.get("apk_grab_point")
        if (approval.get("allowed") is not True or
                approval.get("basis") != "orange_unit_geometry_v1" or
                badge.get("kind") != "unit" or badge.get("state") != "orange" or
                not isinstance(point, (tuple, list)) or len(point) != 2 or
                any(type(v) not in (int, float) or not math.isfinite(v) for v in point) or
                not (0 <= point[0] < 1280 and 560 <= point[1] < 720)):
            return None
        return tuple(int(v) for v in point)

    def filter_deploy_units(self, frame, candidates, stage):
        import apk_hand_availability
        # Reusing this pure observation is not reusing gesture authorization:
        # dispatch still proves the current origin/target and final frame age.
        key = ("availability", json.dumps(candidates, sort_keys=True, default=_json_default))
        observed, cache_hit = self._same_frame_hand_observation(frame, key, lambda:
            apk_hand_availability.filter_units(frame, candidates) if candidates else
            {"units": [], "credits": None, "checks": []})
        units = [badge for badge in observed["units"]
                 if badge.get("kind") == "unit" and badge.get("state") == "orange"
                 and self.approved_grab_point(badge) is not None]
        self.event("deployment_availability", {
            "stage": stage,
            "same_frame_cache_hit": cache_hit,
            "frame_id": self.last_info.get("frame_id") if self.last_info and frame is self.last_frame else None,
            "credits": observed["credits"], "checks": observed["checks"],
            "accepted_points": [list(self.approved_grab_point(badge)) for badge in units]})
        return units

    def find_hand(self, frame, zone=None, want="orange", units_only=False, debug=False, max_units=0):
        # Apply the limit after action-color/geometry checks so a rejected
        # first card cannot hide another playable unit.
        candidates = self._find_raw_hand(frame, zone=zone, want=want, units_only=units_only,
                                        debug=debug, max_units=0 if units_only else max_units)
        if not units_only:
            return candidates
        units = self.filter_deploy_units(frame, candidates, "candidate_selection")
        return units[:max_units] if max_units > 0 else units

    def grab_point(self, badge, dy=22):
        if "apk_availability" in badge or "apk_grab_point" in badge:
            point = self.approved_grab_point(badge)
            if point is None:
                raise Stop("deployment_grab_point_not_approved")
            return point
        # Non-action diagnostics still ask for legacy points on the raw hand.
        # Deploy units always carry approval; dispatch independently rechecks
        # raw candidates and never accepts this diagnostic fallback as proof.
        return self._core_grab_point(badge, dy=dy)

    def board_ready(self, frame):
        """Read current ownership; each hook validates its fresh local actor."""
        self._stable_seed = None
        ready, reason = self.engine._board_ready_real(frame)
        info = self.last_info or {}
        # Log the decision already made, without another recognition pass.
        # The independent observer counts episodes from these fresh captures.
        self.event("scene_entry", dict(ready=ready, reason=reason, observed_elapsed_ms=self.now(), **{key: info.get(key)
            for key in ("frame_id", "captured_elapsed_ms", "foreground_generation",
                        "source_width", "source_height", "state", "button",
                        "choice_modal", "transition_reason", "frontline")}))
        return ready, reason

    def capture(self):
        try:
            return self._capture_frame()
        except BaseException:
            self._clear_board_cache()
            self._stable_seed = None
            raise

    def _capture_frame(self):
        # A new capture clears even identical pixels; cache hits never extend
        # the capture timestamp or the final input freshness window.
        self._clear_hand_cache()
        self._clear_board_cache()
        self.check_running()
        packet = _parse(self.bridge.capture())
        # The user starts from the app, then switches to the game. Only the
        # first capture may wait for that new foreground generation. Once a
        # game frame exists, losing/changing foreground is a terminal refusal.
        if (self.last_id < 0 and not packet.get("ok", True) and
                packet.get("reason") == "waiting_for_new_game_foreground"):
            self.event("waiting_for_game", {"remaining_ms": max(0, self.started + 10000 - self.now())})
            while (not packet.get("ok", True) and
                   packet.get("reason") == "waiting_for_new_game_foreground" and
                   self.now() < self.started + 10000):
                time.sleep(.2)
                self.check_running()
                packet = _parse(self.bridge.capture())
        if not packet.get("ok", True):
            raise Stop("capture_rejected:" + str(packet.get("reason", "unknown")))
        for key in ("frame_id", "captured_elapsed_ms", "source_width", "source_height",
                    "foreground_generation", "png_path"):
            if key not in packet:
                raise Stop("capture_missing_" + key)
        index = int(packet["frame_id"])
        captured = int(packet["captured_elapsed_ms"])
        if index <= self.last_id or captured > self.now() or self.now() - captured > 5000:
            raise Stop("invalid_or_stale_capture_packet")
        source_ratio = packet["source_width"] / packet["source_height"] if int(packet["source_height"]) > 0 else 0
        if source_ratio < 1.70 or source_ratio > 2.30:
            raise Stop("unsupported_capture_aspect_ratio")
        path = Path(str(packet["png_path"])).resolve()
        if self.out not in path.parents:
            raise Stop("capture_outside_session_evidence")
        raw = path.read_bytes()
        frame = self.cv2.imdecode(self.np.frombuffer(raw, self.np.uint8), self.cv2.IMREAD_COLOR)
        if frame is None or frame.shape != (720, 1280, 3):
            raise Stop("invalid_normalized_capture")
        self.last_id = index
        state, matches = self.ui.classify(frame, self.templates, self.states)
        core_state = state
        result_observation = None
        # Valid battle frames use one classifier. Only the old core's unknown
        # frames need the APK's existing strict, correctly sized result banner.
        observe_result = getattr(self.bridge, "observeResult", None)
        if state is None and observe_result is not None:
            result_observation = _parse(observe_result(_json(packet)))
            if result_observation.get("ok") is not True:
                raise Stop("result_observation_rejected:" + str(result_observation.get("reason", "unknown")))
            for key in ("frame_id", "captured_elapsed_ms", "foreground_generation",
                        "source_width", "source_height", "png_path"):
                if result_observation.get(key) != packet[key]:
                    raise Stop("result_observation_capture_mismatch")
            if self.now() - captured > 5000:
                raise Stop("result_observation_capture_expired")
            if result_observation.get("state") == "result_defeat":
                state = "defeat"
        button = self.end_button.inspect_end_button(frame, self.templates, min_score=self.mb.END_TURN_MIN)
        box = button["box"]
        if isinstance(box, dict):
            box = [box[k] for k in ("x", "y", "w", "h")]
        info = {k: packet[k] for k in ("frame_id", "captured_elapsed_ms", "source_width",
                                       "source_height", "foreground_generation", "png_path")}
        self._register_board_capture(frame, info)
        info.update(state=state, matches=matches, button=button["state"], button_box=box,
                    button_score=button["score"], button_present=button.get("present"),
                    button_reason=button.get("reason"), transition_reason=self.mb.board_transition_reason(frame),
                    choice_modal=self.mb.choice_modal(frame)[0])
        if result_observation is not None:
            info.update(core_state=core_state, apk_result_observation=result_observation)
        motion = self.mb.board_motion(self.last_frame, frame) if self.last_frame is not None else None
        info["board_motion"] = motion
        info["choice_gate"] = self.choice_gate.observe(info["choice_modal"], captured / 1000, motion)
        info["frontline"] = self.mb.frontline_state(frame)
        # HQs help diagnose an unclassified screen. A pending end tap is
        # confirmed by its opponent label, independently of HQ recognition.
        if state != "in_game" and self.end_turn_ledger.pending is None and self.context != "end_turn":
            info["our_hq"] = self.mb.hq_card(frame, "our")
            info["enemy_hq"] = self.mb.hq_card(frame, "enemy")
        if self.end_turn_ledger.pending is not None or self.context == "end_turn":
            import apk_hud_adapter
            import apk_enemy_turn
            info["hud_layout"] = apk_hud_adapter.inspect_hud(frame)["layout"]
            info["opponent_turn_label"] = apk_enemy_turn.inspect_opponent_turn(frame)
        self.last_frame, self.last_info = frame, info
        self.report["captures"] += 1
        self.event("capture", info)
        self._settle_end_turns(self.end_turn_ledger.observe(
            info, self.now(), self.engine.turns_seen if self.engine else 0, motion))
        if state in ("victory", "defeat"):
            if self._result_state == state and captured - self._result_since >= 300:
                self._result_count += 1
            elif self._result_state != state:
                self._result_state, self._result_since, self._result_count = state, captured, 1
            if self._result_count >= 2:
                self.report["result_verified"] = True
                if self.context not in ("attack_hq", "attack_unit"):
                    raise Stop("result_" + state)
        else:
            self._result_state = self._result_since = None
            self._result_count = 0
        if state is not None and state not in ("in_game", "victory", "defeat"):
            raise Stop("unsupported_state_" + state)
        if info["choice_gate"] in ("confirmed", "timeout"):
            raise Stop("choice_modal_" + info["choice_gate"])
        return frame

    def dispatch(self, gesture):
        self.check_running()
        # A pending end-turn may become unconfirmed during a capture inside
        # think(). Enforce its failure budget at the last input boundary too.
        if self.failed_inputs >= self.options["max_failed_inputs"]:
            raise Stop("repeated_unconfirmed_action")
        # Do not let a new input supersede an unresolved end tap. Continue
        # capturing until its positive-label evidence confirms it or the
        # ledger's existing timeout accounts for the failure before dispatch.
        if self.end_turn_ledger.pending is not None:
            raise Replan("awaiting_previous_end_turn_confirmation")
        if self.end_turn_blocked_turn == self.engine.turns_seen:
            raise Replan("awaiting_next_turn_after_end_turn_failure")
        info = self.last_info
        deployment_plan = None
        if self.context == "deploy" and "path_points" not in gesture:
            gesture = dict(gesture, path_points=deployment_path_points(gesture.get("from"), gesture.get("to")))
        try:
            validate_gesture(gesture, self.context, info, self.now(), self.deadline - self.now(),
                             self.report["game_inputs"], self.options)
        except Replan:
            # An expired frame cannot downgrade an independent deployment
            # refusal into a retry. Run those guards before final age refusal.
            pass
        if self.context == "deploy":
            if not self.options["deploy_enabled"]:
                raise Stop("deployment_not_enabled")
            raw_find = self._find_raw_hand if hasattr(self, "_core_find_hand") else self.mh.find_hand
            raw_units = raw_find(self.last_frame, want="orange", units_only=True, debug=False, max_units=0)
            units = self.filter_deploy_units(self.last_frame, raw_units, "dispatch_preflight")
            simple_plan = self._simple_deployment_plan
            if simple_plan is not None:
                import apk_simple_deploy
                reason = apk_simple_deploy.validate_plan(simple_plan, self.last_frame,
                    dict(info, turn_id=self.engine.turns_seen),
                    gesture, units, self.approved_grab_point)
                if reason:
                    raise Stop("deployment_simple_preflight:" + reason)
                if not self._simple_deploy_ledger.allowed(simple_plan):
                    raise Stop("deployment_simple_layout_already_failed")
                deployment_plan = dict(simple_plan, point=list(simple_plan["origin"]))
                self.event("deployment_simple_preflight", deployment_plan)
            else:
                # Retain the old hook for diagnostic regression callers. Live
                # production uses a current one-use simple plan above.
                matching = [unit for unit in units if unit.get("kind") == "unit" and
                            unit.get("state") == "orange" and
                            tuple(gesture["from"]) == self.approved_grab_point(unit)]
                if len(matching) != 1:
                    raise Stop("deployment_origin_not_unique_current_unit")
                chosen = matching[0]
                deployment_plan = {"frame_id": info["frame_id"],
                                   "cost": chosen["apk_availability"]["cost"],
                                   "credits_before": chosen["apk_availability"]["credits"],
                                   "plate": chosen["apk_availability"].get("plate"),
                                   "point": list(self.approved_grab_point(chosen)),
                                   "grab": chosen.get("apk_grab"), "selected_identity_verified": False}
                if any(abs(gesture["to"][i] - self.engine.drop[i]) > 12 for i in (0, 1)):
                    raise Stop("deployment_destination_not_support_drop")
                import apk_deploy_target
                clearance = apk_deploy_target.inspect_clear(self.last_frame, gesture["to"])
                self.event("deployment_destination_preflight", clearance)
                if not clearance["clear"]:
                    raise Stop("deployment_destination_not_clear:" + clearance["reason"])
        # Recognition and primitive construction consume time. Recheck now,
        # then Java checks again immediately beside dispatchGesture.
        validate_gesture(gesture, self.context, info, self.now(), self.deadline - self.now(),
                         self.report["game_inputs"], self.options)
        request = dict(gesture, context=self.context)
        request.update({key: info[key] for key in ("frame_id", "captured_elapsed_ms", "source_width",
                                                 "source_height", "foreground_generation")})
        if self.context == "deploy" and self._simple_deployment_plan is not None:
            self._simple_deployment_plan["consumed"] = True
        self._clear_hand_cache()
        self._clear_board_cache()
        reply = _parse(self.bridge.dispatch(_json(request)))
        accepted = reply.get("accepted") is True
        item = {"request": request, "reply": reply, "source_hud_layout": info.get("hud_layout", "unknown"),
                "accepted_elapsed_ms": self.now() if accepted else None,
                "deployment_plan": deployment_plan,
                "combat_plan": (self.engine._combat_decision_context or {}).get("plan")}
        self.report["inputs"].append(item)
        if accepted:
            self.report["game_inputs"] += 1
            self.last_progress = self.now()
            if deployment_plan is not None:
                self._deployment_dispatched_source = self.last_frame
        self.event("dispatch", item)
        if not accepted:
            reason = str(reply.get("reason", "unknown"))
            if reason in ("frame_age_expired", "input_frame_age_exceeded", "frame_expired"):
                raise Replan("java_frame_expired_replan:" + reason)
            raise Stop("gesture_rejected:" + reason)
        if reply.get("completed") is not True:
            # It may have partly acted. Never replay an accepted gesture.
            raise Stop("gesture_not_completed:" + str(reply.get("reason", "unknown")))

    def wrap_hook(self, kind, function):
        def wrapped(*args):
            self.check_running()
            if self.deadline - self.now() < 8000:
                raise Stop("time_budget_before_hook")
            self.context = kind
            before = self.report["game_inputs"]
            capture_id = self.last_id
            try:
                result = function(*args)
            except BaseException as failure:
                self.context = None
                self._record_hook(kind, before, capture_id, None, failure)
                raise
            finally:
                self.context = None
            self._record_hook(kind, before, capture_id, result)
            return result
        return wrapped

    def _record_hook(self, kind, inputs_before, capture_id, result, failure=None):
        """Keep accepted-but-interrupted inputs visible, even during BaseException stop."""
        sent = self.report["game_inputs"] - inputs_before
        returned_ok = (bool(result[0]) if isinstance(result, tuple) else bool(result)) if failure is None else False
        confirmed = sent > 0 and returned_ok and kind != "end_turn"
        completed_packets = [packet for packet in self.report["inputs"]
                             if packet["reply"].get("accepted") is True][-sent:] if sent else []
        deploy_refused = (kind == "deploy" and isinstance(self._deployment_boundary_evidence, dict)
                          and self._deployment_boundary_evidence.get("no_effect") is True
                          and self._deployment_boundary_evidence.get("reason") == "stable_no_deployment_effect"
                          and self._deployment_boundary_evidence.get("late_refusal_observation") is True
                          and sent == 1 and len(completed_packets) == 1
                          and (completed_packets[0].get("deployment_plan") or {}).get("kind") == "simple_support_count_v1"
                          and (completed_packets[0].get("deployment_plan") or {}).get("frame_id") ==
                              self._deployment_boundary_evidence.get("source_frame_id"))
        completed = (len(completed_packets) == sent
                     and all(packet["reply"].get("completed") is True for packet in completed_packets))
        refused = sent > 0 and not returned_ok and failure is None and deploy_refused and completed
        # A completed simple drag can have an unreadable visual outcome. Its
        # per-turn failed-layout ledger already prevents replaying that card.
        # Keep the unknown audit without turning it into a campaign stop.
        deploy_unknown = (kind == "deploy" and sent == 1 and completed
                          and not returned_ok and failure is None
                          and isinstance(self._deployment_boundary_evidence, dict)
                          and self._deployment_boundary_evidence.get("confirmed") is False
                          and self._deployment_boundary_evidence.get("no_effect") is False
                          and (completed_packets[0].get("deployment_plan") or {}).get("kind") == "simple_support_count_v1"
                          and (completed_packets[0].get("deployment_plan") or {}).get("frame_id") ==
                              self._deployment_boundary_evidence.get("source_frame_id"))
        skipped = (sent > 0 and not returned_ok and failure is None
                   and kind in ("attack_hq", "attack_unit", "move_front")
                   and len(completed_packets) == sent
                   and all(packet["reply"].get("completed") is True for packet in completed_packets))
        if kind == "end_turn" and sent and failure is None and returned_ok:
            verification = "pending_transition"
        else:
            verification = ("confirmed" if confirmed else "confirmed_refusal" if refused else "unconfirmed_skipped" if skipped
                            else "unconfirmed" if sent else "no_input")
        item = {"kind": kind, "turn": self.engine.turns_seen, "ok": confirmed,
                "hook_returned_ok": returned_ok, "verification": verification,
                "terminated": failure is not None,
                "detail": str(failure) if failure is not None else result[1] if isinstance(result, tuple) else None,
                "inputs": sent, "before_capture": capture_id, "after_capture": self.last_id}
        if failure is not None:
            item["exception_type"] = type(failure).__name__
        if sent and kind in ("attack_hq", "attack_unit"):
            attempt = getattr(getattr(self, "ma", None), "_LAST_ATTEMPT", None)
            if isinstance(attempt, dict) and attempt.get("kind") == kind:
                evidence = attempt.get("simple_combat_evidence")
                if isinstance(evidence, dict):
                    item["combat_evidence"] = copy.deepcopy(evidence)
        if kind == "deploy" and sent:
            item["deployment_cost_audit"] = self.deployment_cost_audit()
            if self._deployment_boundary_evidence is not None:
                item["deployment_boundary_evidence"] = copy.deepcopy(self._deployment_boundary_evidence)
        if sent and (kind != "end_turn" or failure is not None or not returned_ok):
            if confirmed:
                self.failed_inputs = 0
            elif not skipped and not refused and not deploy_unknown:
                self.failed_inputs += sent
            if not confirmed and not refused:
                self.report["unconfirmed_inputs"] += sent
            if refused:
                self.report["deployment_refusals_confirmed"] += sent
            if skipped:
                self.report["unconfirmed_skipped"] += sent
            self.report["actions_confirmed"] += int(confirmed)
            if kind == "end_turn":
                self.report["end_turns_unconfirmed"] += sent
                item["final_verification"] = "unconfirmed"
        self.report["failed_inputs"] = self.failed_inputs
        hook_index = len(self.report["hooks"])
        self.report["hooks"].append(item)
        self.event("hook", item)
        if verification == "pending_transition":
            accepted = [entry for entry in self.report["inputs"] if entry["reply"].get("accepted") is True]
            for offset in range(sent):
                packet = accepted[-sent + offset] if len(accepted) >= sent else None
                source = dict(packet["request"], hud_layout=packet["source_hud_layout"]) if packet else self.last_info
                dispatched = packet["accepted_elapsed_ms"] if packet else self.now()
                outcomes = self.end_turn_ledger.register(hook_index, inputs_before + offset + 1,
                                                         source, dispatched, self.engine.turns_seen)
                self._settle_end_turns(outcomes)
            self.report["pending_end_turn_inputs"] = int(self.end_turn_ledger.pending is not None)

    def deployment_cost_audit(self):
        """Record resource changes for QA, never turn them into identity proof."""
        packets = [packet for packet in self.report["inputs"]
                   if packet["reply"].get("accepted") is True and packet.get("deployment_plan")]
        if not packets:
            return {"status": "deployment_plan_missing", "selected_identity_verified": False}
        plan = packets[-1]["deployment_plan"]
        audit = {"status": "no_new_post_input_frame", "source_frame_id": plan["frame_id"],
                 "expected_cost": plan["cost"], "credits_before": plan["credits_before"],
                 "post_frame_id": self.last_info.get("frame_id") if self.last_info else None,
                 "credits_after": None, "observed_credit_decrease": None,
                 "decrease_matches_expected_cost": None, "selected_identity_verified": False,
                 "meaning": "diagnostic_only_card_effects_may_change_resources"}
        if audit["post_frame_id"] is None or audit["post_frame_id"] <= plan["frame_id"]:
            return audit
        if type(plan["credits_before"]) is not int:
            audit["status"] = "optional_source_resources_unread"
            return audit
        try:
            import apk_hud_adapter
            observed = apk_hud_adapter.inspect_kredits(self.last_frame)
            audit["resources_after"] = observed
            audit["credits_after"] = observed["value"]
            audit["status"] = "post_resources_unknown"
            if type(observed["value"]) is int and type(plan["credits_before"]) is int:
                delta = plan["credits_before"] - observed["value"]
                audit.update(status="observed", observed_credit_decrease=delta,
                             decrease_matches_expected_cost=(delta == plan["cost"]
                                 if type(plan["cost"]) is int else None))
        except Exception as error:
            audit.update(status="resource_observation_error", error=type(error).__name__)
        return audit

    def _settle_end_turns(self, outcomes):
        for outcome in outcomes:
            confirmed = outcome["status"] == "confirmed"
            key = "end_turns_confirmed" if confirmed else "end_turns_unconfirmed"
            self.report[key] += 1
            if not confirmed:
                self.report["unconfirmed_inputs"] += 1
                self.failed_inputs += 1
                self.end_turn_blocked_turn = outcome.get("source_turn", self.engine.turns_seen)
            item = self.report["hooks"][outcome["hook_index"]]
            # Preserve the original hook's ok=false/pending_transition record:
            # this separate field is supported by later screenshots.
            item["final_verification"] = outcome["status"]
            item["post_verification"] = outcome
            self.report["end_turn_outcomes"].append(outcome)
            self.event("end_turn_verification", outcome)
        self.report["pending_end_turn_inputs"] = int(self.end_turn_ledger.pending is not None)
        self.report["failed_inputs"] = self.failed_inputs

    def legacy_deploy(self, frame):
        self._deployment_boundary_evidence = None
        self._deployment_dispatched_source = None
        fresh = self.capture()
        info = self.last_info
        if (info["state"] != "in_game" or info["button"] is None or
                info["choice_modal"] or info["transition_reason"] or
                self.mb.board_motion(frame, fresh) > self.mb.BOARD_MOTION_MAX):
            raise Replan("deployment_waits_for_fresh_stable_frame")
        units = self.mh.find_hand(fresh, want="orange", units_only=True, debug=False)
        if not units:
            return False, "no_confirmed_affordable_unit_with_safe_grab"
        if units:
            import apk_deploy_target
            landing = apk_deploy_target.choose_drop(fresh)
            self.event("deployment_destination_selected", landing)
            if landing["point"] is None:
                if landing["reason"] == "no_confirmed_clear_outer_support_slot":
                    return False, "no_confirmed_clear_outer_support_slot"
                raise Replan("deployment_geometry_unknown:" + landing["reason"])
            self.engine.drop = tuple(landing["point"])
        inputs_before = self.report["game_inputs"]
        result = self.engine._deploy_real(fresh)
        if result[0] or self.report["game_inputs"] - inputs_before != 1:
            return result
        attempt = getattr(self.mh, "_LAST_DEPLOY_ATTEMPT", None)
        packet = self.report["inputs"][-1]
        if (not isinstance(attempt, dict) or not attempt.get("input_sent") or
                attempt.get("before") is not self._deployment_dispatched_source or
                packet["reply"].get("accepted") is not True or
                packet["reply"].get("completed") is not True or
                tuple(packet["request"]["from"]) != self.approved_grab_point(attempt.get("badge", {})) or
                tuple(packet["request"]["to"]) != tuple(attempt.get("target", ()))):
            return result
        import apk_deploy_verify
        previous = attempt.get("after")
        if previous is not self.last_frame:
            return result
        import apk_enemy_turn
        if (self.last_info.get("button") is not None or
                apk_enemy_turn.inspect_opponent_turn(previous).get("present") is not True):
            return result
        # Observe only. No own-turn predicate or retry may replay this input.
        for _ in range(3):
            if self.deadline - self.now() < 2000:
                break
            previous_id = self.last_id
            time.sleep(.5)
            current = self.capture()
            evidence = apk_deploy_verify.inspect_pair(attempt.get("before"), previous, current,
                                                     attempt["badge"], attempt["target"])
            evidence.update(previous_frame_id=previous_id, current_frame_id=self.last_id,
                            original_detail=result[1])
            self._deployment_boundary_evidence = evidence
            self.event("deployment_turn_boundary_verification", evidence)
            attempt["after"] = current
            if evidence["confirmed"]:
                attempt["apk_boundary_verification"] = evidence
                self.mh._LAST_DEPLOY_PENDING = None
                return True, "persistent_new_support_unit_across_turn_boundary"
            if evidence["reason"] not in ("positive_opponent_label_pair_missing",
                                          "support_geometry_still_moving", "support_pixels_still_moving"):
                break
            previous = current
        return result

    def simple_deploy(self, frame):
        """One user-authorized simple attempt, followed only by observation."""
        import apk_simple_deploy as simple
        self._deployment_boundary_evidence = None
        self._deployment_dispatched_source = None
        self._simple_deployment_plan = None
        self.mh._LAST_DEPLOY_ATTEMPT = self.mh._LAST_DEPLOY_PENDING = None
        time.sleep(self.mb.BOARD_SAMPLE_GAP)
        fresh = self.capture()
        info = self.last_info
        if (info["state"] != "in_game" or info["button"] not in ("white", "orange") or
                info["choice_modal"] or info["transition_reason"]):
            raise Replan("deployment_waits_for_fresh_stable_frame")
        if simple.motion(frame, fresh, simple.HAND_ROI) > simple.HAND_MOTION_MAX:
            # Hand motion blocks this drag, not unrelated units on the board.
            return False, "deployment_hand_still_moving"
        row = simple.support_observation(fresh)
        if type(row["count"]) is not int or row["count"] >= 4:
            reason = "support_row_full" if row["count"] == 4 else "support_count_unknown:" + row["reason"]
            self.event("deployment_simple_selected", {"plan": None, "reason": reason, "support": row})
            return False, reason
        raw = self._find_raw_hand(fresh, want="any", units_only=False, debug=False, max_units=0)
        candidates = self._find_raw_hand(fresh, want="orange", units_only=True, debug=False, max_units=0)
        units = self.filter_deploy_units(fresh, candidates, "simple_selection")
        allowed_units = [b for b in units if self.engine._allow_deploy_attempt(fresh, b, simple.TARGET)]
        if units and not allowed_units:
            return False, "deployment_retry_budget_exhausted"
        plan, reason = simple.make_plan(fresh, dict(info, turn_id=self.engine.turns_seen),
                                        allowed_units, raw, self.approved_grab_point,
                                        self._simple_deploy_ledger, row=row)
        self.event("deployment_simple_selected", {"plan": plan, "reason": reason, "support": row})
        if plan is None:
            return False, reason
        if not self.engine._allow_deploy_attempt(fresh, plan["badge"], simple.TARGET):
            return False, "deployment_retry_budget_exhausted"
        self.engine.drop = simple.TARGET
        self._simple_deployment_plan = plan
        attempt = {"before": fresh, "after": None, "badge": dict(plan["badge"]),
                   "target": simple.TARGET, "input_sent": False,
                   "before_support": row["count"], "simple_plan": dict(plan)}
        self.mh._LAST_DEPLOY_ATTEMPT = attempt
        inputs_before = self.report["game_inputs"]
        try:
            self.dispatch({"kind": "drag", "from": list(plan["origin"]), "to": list(simple.TARGET),
                           "duration_ms": 900,
                           "path_points": deployment_path_points(plan["origin"], simple.TARGET)})
        except BaseException:
            attempt["input_sent"] = self.report["game_inputs"] > inputs_before
            if attempt["input_sent"]:
                self._simple_deploy_ledger.failed(plan)
            raise
        finally:
            self._simple_deployment_plan = None
        attempt["input_sent"] = True
        verification_start = self.now()
        time.sleep(.6)
        previous = self.capture()
        attempt["after"] = previous
        source_observation = dict(row, transition=info["transition_reason"], choice_modal=info["choice_modal"])
        source_observation["refusal_regions"] = simple.refusal_regions(fresh, row)
        previous_observation = simple.observe(previous)
        evidence = None
        pair_index = 0
        transient_pair = bool(previous_observation.get("transition") or previous_observation.get("choice_modal"))
        # A draw/order display can trip the broad core choice detector. Capture
        # owns the existing stable-choice/timeout gate; a single suspect frame
        # only extends this read-only verification window, never authorizes touch.
        while pair_index < 5 or (transient_pair and self.now() - verification_start < 12000):
            time.sleep(.5)
            previous_id = self.last_id
            current = self.capture()
            attempt["after"] = current
            current_observation = simple.observe(current)
            pair_index += 1
            transient_pair = any(o.get("transition") or o.get("choice_modal")
                                 for o in (previous_observation, current_observation))
            observations = iter((source_observation, previous_observation, current_observation))
            evidence = simple.inspect_pair(fresh, previous, current, observer=lambda f: next(observations))
            evidence.update(mode=plan["mode"], source_frame_id=plan["frame_id"],
                            previous_frame_id=previous_id, current_frame_id=self.last_id,
                            late_refusal_observation=self.now() - verification_start >= 1800,
                            post_observation_elapsed_ms=self.now() - verification_start,
                            post_observation_pair=pair_index,
                            animation_observation_extended=pair_index > 5)
            self._deployment_boundary_evidence = evidence
            attempt["simple_verification"] = evidence
            self.event("deployment_simple_verification", evidence)
            if evidence["confirmed"]:
                return True, evidence["reason"]
            if evidence["no_effect"] and evidence["late_refusal_observation"]:
                self._simple_deploy_ledger.failed(plan)
                return False, "stable_no_deployment_effect"
            previous = current
            previous_observation = current_observation
        self._simple_deploy_ledger.failed(plan)
        reason = evidence["reason"] if evidence else "deployment_post_observation_missing"
        self.mh._LAST_DEPLOY_PENDING = reason
        return False, reason

    def end_turn(self):
        if self.engine._end_reclick >= self.options["max_failed_inputs"]:
            raise Stop("turn_transition_failed_%d_times" % self.options["max_failed_inputs"])
        return self.engine._click_end_turn_real()

    def loop_delay(self):
        info = self.last_info or {}
        turn_ready_at = getattr(self.engine, "_turn_ready_at", 0.)
        captured = info.get("captured_elapsed_ms")
        fresh = type(captured) is int and 0 <= self.now() - captured <= 3000
        if (self.end_turn_ledger.pending is None and info.get("state") == "in_game" and
                info.get("button") in ("white", "orange") and
                not info.get("choice_modal") and not info.get("transition_reason") and
                fresh and (not turn_ready_at or time.time() >= turn_ready_at)):
            return .25
        return .6

    def _observe_budget_tail(self):
        """At the input limit only observe; give an end tap its independent pair."""
        if self.end_turn_ledger.pending is None:
            time.sleep(.6)
            self.capture()
            return
        until = min(self.deadline, self.now() + 6000)
        while self.end_turn_ledger.pending is not None and self.now() < until:
            time.sleep(.6)
            self.capture()

    def execute(self):
        try:
            self.load_core()
            self._install_board_cache()
            self.engine = self.tem.MobileTurnEngine(templates=self.templates,
                log=lambda value: self.event("engine_log", value), grab_frame=self.capture,
                deploy=lambda frame: (False, "deployment_disabled"),
                turn_start_settle=.2, end_turn_delay=(.2, .5))
            engine = self.engine
            engine._board_ready = self.board_ready
            import apk_simple_combat
            self.simple_combat = apk_simple_combat.install(engine, self.event)
            self.event("simple_combat", {"installed": True, "hq_hp_required": False,
                "ordinary_unconfirmed": "skip_actor_for_current_turn"})
            engine._attack_unit = self.wrap_hook("attack_unit", engine._attack_unit_real)
            engine._attack_hq = self.wrap_hook("attack_hq", engine._attack_hq_real)
            engine._move_front = self.wrap_hook("move_front", engine._move_front_real)
            engine._click_end_turn = self.wrap_hook("end_turn", self.end_turn)
            if self.options["deploy_enabled"]:
                engine._deploy = self.wrap_hook("deploy", self.simple_deploy)
                self.event("simple_deploy", {"installed": True, "target": [440, 500],
                    "middle_fallback": [640, 665], "support_limit": 4, "material_required": False,
                    "selected_identity_verified": False})
            previous_turn = 0
            while True:
                frame = self.capture()
                info = self.last_info
                if self.options["read_only"]:
                    # Read-only includes useful concrete recognition, no think.
                    import apk_hud_adapter
                    import apk_deploy_target
                    import apk_hq_geometry
                    self.event("inspection", {"frontline": info["frontline"],
                        "units": self.mb.actionable_units(frame),
                        "enemy_hq": apk_hq_geometry.hq_card(frame, "enemy", include_hp=True),
                        "our_hq": apk_hq_geometry.hq_card(frame, "our", include_hp=True),
                        "hand": self.mh.find_hand(frame, debug=False),
                        "combat": self.ma._combat_observation(frame),
                        "kredits": apk_hud_adapter.inspect_kredits(frame),
                        "deployment_landing": apk_deploy_target.choose_drop(frame)})
                    raise Stop("inspection_complete")
                if info["state"] in ("victory", "defeat"):
                    time.sleep(.4)
                    continue
                if info["choice_modal"]:
                    engine._board_stability.reset()
                    time.sleep(.6)
                    continue
                recognizable = info["state"] == "in_game" or (info.get("our_hq") and info.get("enemy_hq"))
                if recognizable:
                    self.unknown_since = None
                elif self.unknown_since is None:
                    self.unknown_since = self.now()
                elif self.now() - self.unknown_since >= self.options["unknown_seconds"] * 1000:
                    raise Stop("unknown_screen_timeout")
                try:
                    status = engine.think(frame=frame)
                except Replan as exc:
                    self._clear_board_cache()
                    discard_provisional(engine, self.ma, self.mh)
                    status = str(exc)
                scene_blocked = status.startswith("画面待稳定: ")
                scene_source = (dict(observed_elapsed_ms=self.now(), **{key: self.last_info.get(key)
                    for key in ("frame_id", "captured_elapsed_ms", "foreground_generation",
                                "source_width", "source_height", "state", "button",
                                "choice_modal", "transition_reason", "frontline")})
                    if scene_blocked else None)
                self.event("think", {"status": status, "turn": engine.turns_seen,
                    "frame_id": info["frame_id"], "game_inputs": self.report["game_inputs"],
                    "failed_actions": engine.failed_actions_this_turn,
                    "failed_deploys": engine.failed_deploys_this_turn,
                    "scene_blocked": scene_blocked, "scene_source": scene_source})
                if self.report["result_verified"]:
                    raise Stop("result_" + self._result_state)
                if self.failed_inputs >= self.options["max_failed_inputs"]:
                    raise Stop("repeated_unconfirmed_action")
                if engine.turns_seen != previous_turn:
                    previous_turn, self.last_progress = engine.turns_seen, self.now()
                    self.end_turn_blocked_turn = None
                if self.report["game_inputs"] >= self.options["max_inputs"]:
                    self._observe_budget_tail()
                    raise Stop("input_budget")
                if self.now() - self.last_progress >= self.options["idle_seconds"] * 1000:
                    raise Stop("no_progress_timeout")
                if "停手等人工" in status:
                    raise Stop("engine_requests_intervention")
                delay = self.loop_delay()
                self.event("loop_wait", {"seconds": delay, "frame_id": self.last_id,
                    "pending_end_turn": self.end_turn_ledger.pending is not None})
                time.sleep(delay)
        except Stop as exc:
            self.report["stop_reason"] = str(exc)
        except BaseException as exc:
            self.report["exception"] = type(exc).__name__ + ": " + str(exc)
            self.report["stop_reason"] = "runtime_exception"
        finally:
            self._clear_board_cache()
            cache = getattr(self, "_board_cache", None)
            if cache is not None:
                cache.uninstall()
            stat_sampler = getattr(self, "stat_sampler", None)
            if stat_sampler is not None:
                stat_sampler.uninstall()
            self._settle_end_turns(self.end_turn_ledger.finalize(self.now(), self.report["stop_reason"]))
            self.report["elapsed_ms"] = self.now() - self.started
            self.report["engine_turns_seen"] = self.engine.turns_seen if self.engine else 0
            # Reaching a result is a battle-session result. Campaign ownership
            # and opening evidence must be joined by Java before full-game QA.
            self.report["battle_result_reached"] = self.report["result_verified"] and \
                self.report["stop_reason"] in ("result_victory", "result_defeat")
            self.event("finished", self.report)
            (self.out / "battle-summary.json").write_text(_json(self.report), encoding="utf-8")
            self.events.close()
        return _json(self.report)


def run(bridge, core_root, evidence_root, options_json="{}"):
    """Entry point for Java; input defaults off. No external process is created."""
    options = options_from_json(options_json)
    return Runtime(bridge, str(core_root), str(evidence_root), options).execute()
