"""Local Route B prototype: one hand-entered KARDS Android training battle.

Only the documented loopback ADB target is used. No menus, orders, previews,
move/attack, APK helper, host mouse, or retries of uncertain gestures. The
explicit mobile checkout supplies read-only image rules; this is not a release.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import time

import cv2
import numpy as np

from emu_board_witness import target_selection_witness
from emu_rejection_witness import STOP_REASON as REJECTION_REASON, deployment_rejection_witness

WIDTH, HEIGHT = 1280, 720
HELPER = "com.kards.mobilert"
PACKAGES = ("com.android1939.kards", "com.android1939.kardsapk")
PNG_HEADER = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
PNG_END = b"\x00\x00\x00\x00IEND\xaeB`\x82"
MAX_PNG = 20 * 1024 * 1024
POLL = .32
FRESHNESS = 2.
VERIFY_SECONDS = 6.
# Verified on 1.61.27589: the second stable typed row after a buff animation
# arrived 7.53 s after the swipe receipt. Only read more frames, never re-send.
DEPLOY_VERIFY_SECONDS = 10.
UNKNOWN_SECONDS = 6.
OWN_MIN, ABSENT_MAX = .93, .82
SUPPORT_ROI = (200, 415, 1060, 592)
HAND_ROI = (200, 595, 1100, 720)
RESULTS = ("victory", "defeat")
TARGET_SELECTION_PENDING = "target_selection_pending"
APK = Path("android-app/app/src/main")


class Halt(RuntimeError):
    """A closed gate, not an invitation to find another input route."""


def decode_png(data):
    if not (33 <= len(data) <= MAX_PNG and data.startswith(PNG_HEADER) and data.endswith(PNG_END)):
        raise Halt("invalid_or_incomplete_png")
    w, h = struct.unpack_from(">II", data, 16)
    if not (960 <= w <= 2560 and w * 9 == h * 16):
        raise Halt(f"unsupported_screenshot_size:{w}x{h}")
    pixels = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if pixels is None or pixels.shape != (h, w, 3):
        raise Halt("png_decode_failed")
    if (w, h) != (WIDTH, HEIGHT):
        pixels = cv2.resize(pixels, (WIDTH, HEIGHT), interpolation=cv2.INTER_AREA if w > WIDTH else cv2.INTER_LINEAR)
    pixels.setflags(write=False)
    return pixels, (w, h)


@dataclass(frozen=True)
class Frame:
    seq: int
    started: float
    png: bytes
    pixels: np.ndarray
    size: tuple[int, int]
    binding: tuple[str, ...] = ()

    @classmethod
    def read(cls, seq, started, data, binding=()):
        pixels, size = decode_png(data)
        return cls(seq, started, data, pixels, size, binding)

    def at_native(self, point):
        x, y = point
        w, h = self.size
        if not (0 <= x < WIDTH and 0 <= y < HEIGHT):
            raise Halt("point_outside_calibration")
        return int((x+.5)*w/WIDTH), int((y+.5)*h/HEIGHT)


@dataclass(frozen=True)
class Plan:
    kind: str
    origin: tuple[int, int]
    target: tuple[int, int] | None = None


@dataclass(frozen=True)
class Support:
    hq_x: int
    units: tuple[tuple[int, str], ...]  # row slot relative to the HQ, not screen x


@dataclass
class Reading:
    state: str
    reason: str
    evidence: dict
    end: Plan | None = None
    deploy: Plan | None = None
    support: Support | None = None

    def brief(self):
        def points(p):
            return {"origin": p.origin, "target": p.target} if p else None
        return dict(state=self.state, reason=self.reason, **self.evidence,
                    end=points(self.end), deploy=points(self.deploy),
                    support_units=self.support.units if self.support else None)


def match(gray, needle, roi):
    x, y, w, h = roi
    _, score, _, (dx, dy) = cv2.minMaxLoc(cv2.matchTemplate(gray[y:y+h, x:x+w], needle, cv2.TM_CCOEFF_NORMED))
    th, tw = needle.shape
    return float(score), (x+dx, y+dy, tw, th)


def region_motion(a, b, roi):
    x0, y0, x1, y1 = roi
    p, q = (cv2.GaussianBlur(f[y0:y1, x0:x1], (3, 3), 0) for f in (a, b))
    return float((cv2.absdiff(p, q).max(axis=2) > 18).mean())


def support_of(row):
    hq = row["hq"]
    units = tuple(sorted((round((c["cx"]-hq["cx"])/144), c["type"]) for c in row["units"]))
    return Support(int(hq["cx"]), units)


class Vision:
    """Fixed reviewed ROIs + pure mobile/APK rules; never import an engine loop."""

    def __init__(self, root):
        sys.dont_write_bytecode = True
        src, apk = root / "src", root / APK / "python"
        sys.path[:0] = [str(src), str(apk)]

        def module(name, expected):
            m = importlib.import_module(name)
            if not Path(m.__file__).resolve().is_relative_to(expected):
                raise Halt(f"mobile_module_origin_mismatch:{name}")
            return m

        self.board = module("mobile_board", src)
        self.hand = module("mobile_hand", src)
        self.button = module("mobile_end_button", src)
        self.native_hand = module("apk_native.native_hand", apk)
        self.opponent = module("apk_enemy_turn", apk)
        self.available = module("apk_hand_availability", apk)
        self.drop = module("apk_deploy_target", apk)
        self.templates = {}

        def add(name, path, roi):
            data = (root / path).read_bytes()
            color = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            x, y, w, h = roi
            if (color is None or not (0 <= x < x+w <= WIDTH and 0 <= y < y+h <= HEIGHT)
                    or not (8 <= color.shape[0] <= h and 8 <= color.shape[1] <= w)):
                raise Halt(f"bad_template:{name}")
            gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
            if gray.std() < 5:
                raise Halt(f"flat_template:{name}")
            self.templates[name] = (color, gray, roi)

        for state, names in (("ingame", self.button.TEMPLATE_NAMES), ("victory", ("victory_btn",)),
                             ("defeat", ("defeat_btn",)), ("mulligan", ("mulligan_ok_btn",))):
            meta = json.loads((root / f"config/templates.android.{state}.json").read_text(encoding="utf-8-sig"))
            if meta["image_size"] != [WIDTH, HEIGHT]:
                raise Halt(f"template_canvas_mismatch:{state}")
            for name in names:
                entry = meta["templates"][name]
                add(name, entry["path"], tuple(entry["region"][k] for k in ("x", "y", "w", "h")))
        assets = APK / "assets"
        add("defeat_banner", assets / "match-entry/defeat_banner.png", (490, 365, 300, 185))
        for name in ("mulligan_title", "mulligan_title_compact"):
            add(name, assets / f"mulligan-one-shot/{name}.png", (280, 40, 720, 210))
        add("mulligan_ok_btn_compact", assets / "mulligan-one-shot/mulligan_ok_btn_compact.png", (410, 520, 460, 200))
        # Route B 1.61.27589 1280x720 saved frame: same control at 1.10
        # UI scale, not a stretched frame. Only this corroborated variant.
        color, _, _ = self.templates["end_turn_btn"]
        h, w = color.shape[:2]
        color = cv2.resize(color, (round(1.10*w), round(1.10*h)), interpolation=cv2.INTER_CUBIC)
        self.scaled_end_name = "end_turn_btn_110"
        self.templates[self.scaled_end_name] = (color, cv2.cvtColor(color, cv2.COLOR_BGR2GRAY), (1040, 470, 220, 100))

    def stable(self, old, new):
        return self.board.board_motion(old, new) <= self.board.BOARD_MOTION_MAX

    def hands(self, pixels):
        # Core dark plate + contained lower-right operation numeral, corroborated by
        # the native contour deskew rule on the same plate (rejects K-only orders).
        core = self.hand.find_hand(pixels, zone=self.hand.DEFAULT_ZONE, want="orange")
        native = self.native_hand.inspect(pixels)
        geometry = self.available._geometry_plates(pixels) if core else []
        seen, candidates = [], []
        for b in core:
            ad = b["ad_info"]
            hit = [n for n in native if abs(n["center"][0]-b["cx"]) <= 9 and abs(n["center"][1]-b["cy"]) <= 9]
            proof = (b["kind"] == "unit" and b["state"] == "orange" and ad.get("plate_confirmed") and ad.get("ad")
                     and len(hit) == 1 and hit[0]["orange"] and hit[0]["operation_numeral"]
                     and not hit[0]["suspected_order"])
            item = dict(anchor=[b["cx"], b["cy"]], kind="unknown", reason="no_agreeing_unit_marker")
            seen.append(item)
            if not proof:
                continue
            item.update(kind="unit_marker", plate=hit[0]["box"], operation=hit[0]["operation_numeral"])
            approval = self.available.inspect_unit(pixels, b, _geometry=geometry)
            grab = self.available._safe_grab(pixels, b, approval)
            item.update(orange_fraction=round(hit[0]["orange_fraction"], 3), reason=approval["reason"])
            if not grab["point"]:
                item["reason"] = grab["reason"] if approval["allowed"] else approval["reason"]
                continue
            x, y = grab["point"]
            px, py, pw, ph = hit[0]["box"]
            # +25/+25 must still be next to this badge, not in the next card's
            # local shadow. Chipped or grey plates may veto that point only.
            if not (px+pw-6 <= x <= px+pw+20 and py+ph-5 <= y <= py+ph+20):
                item["reason"] = "grab_not_local_to_unit_plate"
                continue
            if any(p["cx"] > hit[0]["center"][0]+12 and
                   p["box"][0] - .41*abs(p["cy"]-y) - 5 <= x+4 for p in geometry):
                item["reason"] = "next_plate_may_cover_grab"
                continue
            item.update(grab=[x, y], reason="agreeing_orange_unit_marker")
            candidates.append((x, y))
        return sorted(set(candidates), key=lambda p: (p[1], p[0])), seen

    def observe(self, pixels, *, mode="plan"):
        gray = cv2.cvtColor(pixels, cv2.COLOR_BGR2GRAY)

        def hit(name):
            return match(gray, *self.templates[name][1:])

        scores = {n: round(hit(n)[0], 4) for n in ("defeat_btn", "defeat_banner", "victory_btn")}
        defeat, victory = max(scores["defeat_btn"], scores["defeat_banner"]), scores["victory_btn"]
        ev = {"result_scores": scores}
        if max(defeat, victory) >= .93:
            if min(defeat, victory) >= .86:
                return Reading("unknown", "conflicting_result_labels", ev)
            return Reading("victory" if victory > defeat else "defeat", "reviewed_result_template", ev)
        if max(defeat, victory) >= .86:
            return Reading("unknown", "possible_result_overlay", ev)

        if any(hit(n)[0] >= .92 for n in ("mulligan_ok_btn", "mulligan_ok_btn_compact", "mulligan_title", "mulligan_title_compact")):
            return Reading("mulligan", "opening_template_not_battle", ev)
        target_selection = target_selection_witness(pixels)
        if target_selection is not None:
            ev["target_selection"] = target_selection
            return Reading("choice", TARGET_SELECTION_PENDING, ev)
        # Attribute this toast only in the post-deploy phase, never to a new plan.
        if mode == "verify_deploy":
            rejection = deployment_rejection_witness(pixels)
            if rejection is not None:
                ev["deployment_rejection"] = rejection
                return Reading("rejected", REJECTION_REASON, ev)
        if self.board.choice_modal(pixels)[0]:
            return Reading("choice", "large_choice_modal", ev)
        transition = self.board.board_transition_reason(pixels)
        if transition:
            return Reading("unknown", "transition:"+transition, ev)

        end_names = (*self.button.TEMPLATE_NAMES, self.scaled_end_name)
        score, name, box = max((s, n, b) for n in end_names for s, b in [hit(n)])
        foe = self.opponent.inspect_opponent_turn(pixels)
        ev.update(end_score=round(score, 4), end_template=name, end_box=box if score >= ABSENT_MAX else None,
                  opponent_score=round(foe["score"], 4), opponent_layout=foe["layout"])
        if foe["present"] is True:
            return (Reading("opponent", "explicit_opponent_and_own_button_absent", ev) if score < ABSENT_MAX
                    else Reading("unknown", "conflicting_turn_controls", ev))
        if score < OWN_MIN:
            return Reading("unknown", "own_turn_control_not_confirmed", ev)
        x, y, w, h = box
        color, color_ev = self.button._stroke_color(pixels[y:y+h, x:x+w], self.templates[name][0])
        ev.update(end_color=color, end_color_evidence=color_ev)
        if color not in ("white", "orange"):
            return Reading("unknown", "own_turn_color_unconfirmed", ev)
        front = self.board.frontline_state(pixels)
        ev["frontline"] = front["owner"]
        ev["frontline_evidence"] = front["evidence"]
        if front["owner"] not in ("empty", "our", "enemy"):
            return Reading("unknown", "battle_geometry_not_confirmed", ev)

        end = Plan("end_turn", (x+w//2, y+h//2))
        result = Reading("own", "own_turn_control_and_board", ev, end=end)
        if mode == "end_only":
            return result
        if mode == "verify_deploy":
            cards, reason, row = self.drop._row(pixels)
            ev["support_reason"] = reason
            if cards is not None and reason == "complete_support_row":
                result.support = support_of(row)
            return result
        origins, ev["hand"] = self.hands(pixels)
        if not origins:
            ev["deploy_reason"] = "no_positive_orange_unit_with_local_grab"
            return result
        landing = self.drop.choose_drop(pixels)
        ev["deploy_reason"] = landing["reason"]
        if not landing["point"] or landing["reason"] != "observed_clear_outer_support_slot":
            return result
        result.support = support_of(landing["evidence"]["row"])
        if len(result.support.units) < 4:
            result.deploy = Plan("deploy", origins[0], tuple(landing["point"]))
        else:
            ev["deploy_reason"] = "support_row_full"
        return result


class Bounds:
    def __init__(self, seconds, stop, clock=time.monotonic, sleep=time.sleep):
        self.clock, self.sleep = clock, sleep
        self.start = clock()
        self.deadline = self.start + seconds
        self.stop = stop

    def check(self):
        if self.stop is not None:
            try:
                self.stop.stat()
            except FileNotFoundError:
                pass
            else:
                raise Halt("stop_file")
        if self.clock() >= self.deadline:
            raise Halt("time_budget")

    def pause(self):
        self.check()
        self.sleep(min(POLL, max(0, self.deadline-self.clock())))
        self.check()


def validate_target(adb, serial, package):
    if adb is None or not adb.is_absolute() or adb.suffix.lower() != ".exe" or not adb.is_file():
        raise ValueError("--adb must be the explicit absolute path of an existing adb .exe")
    m = re.fullmatch(r"127\.0\.0\.1:([1-9][0-9]{0,4})", serial or "")
    if not m or int(m[1]) > 65535:
        raise ValueError("--serial must be the selected local 127.0.0.1:PORT ADB serial")
    if package not in PACKAGES:
        raise ValueError("--package must be the exact selected KARDS package: " + " or ".join(PACKAGES))


def parse_binding(data, package):
    text = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
    boot = re.findall(r"^BOOT=([a-f0-9-]+)\s*$", text, re.M)
    game = re.findall(r"^GAME=([1-9][0-9]*)\s*$", text, re.M)
    helper = re.findall(r"^HELPER=([^\r\n]*)", text, re.M)
    if len(helper) != 1 or helper[0] != "1:":
        raise Halt("helper_running_or_unreadable")
    if (len(boot) != 1 or not re.fullmatch(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", boot[0])
            or len(game) != 1 or text.count("PROCESSES\n") != 1 or text.count("FOCUS\n") != 1):
        raise Halt("device_identity_unreadable")
    processes, focus_text = text.split("PROCESSES\n", 1)[1].split("FOCUS\n", 1)
    procs = re.findall(r"^\s*([1-9][0-9]*)[ \t]+(\S+)", processes, re.M)
    if any(name == HELPER or name.startswith(HELPER+":") for _, name in procs):
        raise Halt("helper_subprocess_running")
    if (game[0], package) not in procs:
        raise Halt("selected_game_pid_not_verified")
    focuses = re.findall(r"^[ \t]*mCurrentFocus=([^\r\n]*)", focus_text, re.M)
    displays = re.findall(r"^[ \t]*mTopFocusedDisplayId=([^\r\n]*)", focus_text, re.M)
    if displays and displays != ["0"]:
        raise Halt("foreground_display_not_default")
    m = re.fullmatch(r"Window\{(\S+) u[0-9]+ ([^ /]+)/([^ }]+)\s*\}", focuses[0].strip()) if len(focuses) == 1 else None
    if not m or m[2] != package:
        raise Halt("selected_game_not_focused")
    return boot[0], game[0], m[1], m[2], m[3]


class Adb:
    """Single loopback serial; all commands use the explicit exe and local server."""

    def __init__(self, adb, serial, package, bounds, runner=subprocess.run):
        self.prefix = [str(adb), "-s", serial]
        self.bounds, self.runner, self.package = bounds, runner, package
        self.env = {k: v for k, v in os.environ.items() if k.upper() not in (
            "ADB_SERVER_SOCKET", "ADB_SERVER_PORT", "ANDROID_ADB_SERVER_ADDRESS", "ANDROID_ADB_SERVER_PORT", "ANDROID_SERIAL")}
        self.env["ADB_SERVER_SOCKET"] = "tcp:127.0.0.1:5037"
        self.seq, self.identity, self.size = 0, None, None
        self.guard_script = (
            f'b=$(cat /proc/sys/kernel/random/boot_id) || exit 91; g=$(pidof {package}) || exit 92; '
            f'h=$(pidof {HELPER}); hc=$?; '
            'printf "BOOT=%s\\nGAME=%s\\nHELPER=%s:%s\\nPROCESSES\\n" "$b" "$g" "$hc" "$h"; '
            'ps -A -o PID,ARGS || exit 93; printf "FOCUS\\n"; '
            "dumpsys window | grep -E '^[[:space:]]*(mCurrentFocus|mTopFocusedDisplayId)='")

    def _call(self, argv, *, limit=3., freshness=None, phase="read"):
        self.bounds.check()
        now = self.bounds.clock()
        if freshness is not None and not 0 <= now-freshness <= FRESHNESS:
            raise Halt("frame_expired_before_dispatch")
        try:
            result = self.runner([*self.prefix, *argv], capture_output=True, check=False,
                                 env=self.env, timeout=min(limit, self.bounds.deadline-now))
        except subprocess.TimeoutExpired as e:
            raise Halt(f"adb_{phase}_timeout") from e
        except OSError as e:
            raise Halt(f"adb_{phase}_launch_failed:{e.__class__.__name__}") from e
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()[-160:]
            raise Halt(f"adb_{phase}_failed:{result.returncode}:{detail}")
        return result.stdout

    def guard(self):
        binding = parse_binding(self._call(["shell", self.guard_script], phase="guard"), self.package)
        if self.identity is None:
            self.identity = binding[:2]
        elif self.identity != binding[:2]:
            raise Halt("boot_or_game_pid_changed")
        return binding

    def capture(self):
        if self.seq == 0 and self._call(["get-state"], phase="get_state").strip() != b"device":
            raise Halt("selected_device_not_ready")
        pre = self.guard()
        start = self.bounds.clock()
        data = self._call(["exec-out", "screencap", "-p"], phase="screencap")
        self.seq += 1
        try:
            frame = Frame.read(self.seq, start, data, pre)
        except Halt as e:
            # Preserve well-framed raw PNGs even when their canvas is refused.
            if len(data) <= MAX_PNG and data.startswith(PNG_HEADER) and data.endswith(PNG_END):
                e.png = data
            raise
        if self.guard() != pre:
            raise Halt("foreground_changed_during_capture")
        self.bounds.check()
        if self.size is None:
            self.size = frame.size
        elif self.size != frame.size:
            raise Halt("screenshot_size_changed")
        return frame

    def prepare(self, frame, plan):
        if frame.seq != self.seq or frame.size != self.size or not frame.binding:
            raise Halt("capture_not_current_bound_frame")
        if self.guard() != frame.binding:
            raise Halt("foreground_changed_before_dispatch")
        start = frame.at_native(plan.origin)
        if plan.kind == "end_turn" and plan.target is None:
            return ["tap", *map(str, start)]
        if plan.kind == "deploy" and plan.target is not None:
            return ["swipe", *map(str, (*start, *frame.at_native(plan.target), 600))]
        raise Halt("unsupported_action")

    def send(self, frame, args):
        self._call(["shell", "input", "touchscreen", "-d", "0", *args], limit=2.5,
                   freshness=frame.started, phase="gesture")


class Journal:
    def __init__(self, path):
        self.path = path
        self.path.mkdir(parents=True, exist_ok=False)

    def event(self, event, **details):
        now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        with (self.path / "events.jsonl").open("a", encoding="utf-8") as out:
            out.write(json.dumps(dict(at=now, event=event, **details), ensure_ascii=False, allow_nan=False)+"\n")

    def png(self, name, data):
        with (self.path / name).open("xb") as out:
            out.write(data)
        return dict(png=name, sha256=hashlib.sha256(data).hexdigest())

    def frame(self, name, frame):
        return dict(frame=frame.seq, size=frame.size, capture_monotonic=round(frame.started, 4),
                    **self.png(name, frame.png))


def close_point(a, b):
    return a is not None and b is not None and max(abs(x-y) for x, y in zip(a, b)) <= 3


def distinct_pair(old, new):
    return (old.seq < new.seq and old.size == new.size and old.binding == new.binding
            and .20 <= new.started-old.started <= 3.)


def consistent_plan(old, new):
    return bool(old and new and old.kind == new.kind and close_point(old.origin, new.origin)
                and (old.target is new.target is None or close_point(old.target, new.target)))


def deployed(plan, before, earlier, latest):
    """Only a stable hand delta AND exactly one new typed outer support slot."""
    f0, r0 = before
    fp, rp = earlier
    f1, r1 = latest
    if not (r0.support and rp.support and r1.support and rp.state == r1.state == "own"):
        return None
    a, b, c = r0.support.units, rp.support.units, r1.support.units
    if (b != c or len(c) != len(a)+1 or not set(a).issubset(c)
            or len(set(c)-set(a)) != 1 or abs(rp.support.hq_x-r1.support.hq_x) > 3):
        return None
    new, = set(c)-set(a)
    slots = [0] + [slot for slot, _ in a]
    expected = min(slots)-1 if plan.target[0] < r0.support.hq_x else max(slots)+1
    if new[0] != expected:
        return None
    changed = [region_motion(f0.pixels, f.pixels, HAND_ROI) for f in (fp, f1)]
    support_change = [region_motion(f0.pixels, f.pixels, SUPPORT_ROI) for f in (fp, f1)]
    support_motion = region_motion(fp.pixels, f1.pixels, SUPPORT_ROI)
    hand_motion = region_motion(fp.pixels, f1.pixels, HAND_ROI)
    if min(changed) < .02 or min(support_change) <= .008 or support_motion > .008 or hand_motion > .025:
        return None
    return dict(proof="stable_hand_change_and_one_typed_outer_support_gain", new_unit=new,
                hand_change=[round(v, 4) for v in changed], support_change=[round(v, 4) for v in support_change],
                support_motion=round(support_motion, 4), hand_motion=round(hand_motion, 4))


def _boundary_reason(reading):
    if reading.state == "choice" and reading.reason == TARGET_SELECTION_PENDING:
        return TARGET_SELECTION_PENDING
    if reading.state == "rejected" and reading.reason == REJECTION_REASON:
        return REJECTION_REASON
    if reading.state in (*RESULTS, "mulligan", "choice"):
        return reading.state
    return None


class Pilot:
    def __init__(self, device, vision, bounds, journal, *, action_limit, end_only=False):
        self.device, self.vision, self.bounds, self.journal = device, vision, bounds, journal
        self.action_limit, self.end_only = action_limit, end_only
        self.attempts, self.receipts = 0, 0
        self.verified = {"deploy": 0, "end_turn": 0}
        self.pending, self.last, self.last_reading = None, None, None

    def read(self, mode):
        frame = self.device.capture()
        self.last, self.last_reading = frame, None
        reading = self.vision.observe(frame.pixels, mode=mode)
        self.last_reading = reading
        return frame, reading

    def verify(self, plan, before):
        window = DEPLOY_VERIFY_SECONDS if plan.kind == "deploy" else VERIFY_SECONDS
        deadline = min(self.bounds.deadline, self.bounds.clock()+window)
        last = None
        while self.bounds.clock() < deadline:
            self.bounds.pause()
            if self.bounds.clock() >= deadline:
                break
            current = self.read("verify_deploy" if plan.kind == "deploy" else "end_only")
            f, r = current
            if boundary := _boundary_reason(r):
                return boundary
            if self.bounds.clock() >= deadline:
                break
            if last and distinct_pair(last[0], f):
                if plan.kind == "end_turn":
                    proof = (dict(proof="two_positive_opponent_labels_own_button_absent")
                             if r.state == last[1].state == "opponent" and
                             r.evidence["opponent_layout"] == last[1].evidence["opponent_layout"] else None)
                else:
                    proof = deployed(plan, before, last, current)
                if proof:
                    idx = self.attempts
                    files = [self.journal.frame(f"a{idx:03d}-post-{i}.png", p[0]) for i, p in enumerate((last, current), 1)]
                    self.journal.event("effect_verified", attempt=idx, action=plan.kind, **proof, evidence=files,
                                       observations=[p[1].brief() for p in (last, current)])
                    self.verified[plan.kind] += 1
                    self.pending = None
                    return None
            last = current
        raise Halt("effect_unconfirmed")

    def drive(self):
        previous, unknown_since, state = None, None, None
        while self.attempts < self.action_limit:
            self.bounds.check()
            current = self.read("end_only" if self.end_only else "plan")
            f, r = current
            if r.state != state:
                if state is None:
                    self.journal.event("entry", observation=r.brief(), **self.journal.frame("entry.png", f))
                else:
                    self.journal.event("state", frame=f.seq, observation=r.brief())
                state = r.state
            if boundary := _boundary_reason(r):
                return boundary
            if state == "unknown":
                if unknown_since is None:
                    unknown_since = self.bounds.clock()
                elif self.bounds.clock()-unknown_since >= UNKNOWN_SECONDS:
                    return "unsupported_or_unknown_screen"
            else:
                unknown_since = None
            if previous and previous[1].state == state == "own" and distinct_pair(previous[0], f):
                pf, pr = previous
                if consistent_plan(pr.end, r.end) and self.vision.stable(pf.pixels, f.pixels):
                    plan = r.deploy or r.end
                    if ((plan.kind == "deploy" and consistent_plan(pr.deploy, r.deploy) and pr.support == r.support
                            and r.support is not None and len(r.support.units) < 4
                            and region_motion(pf.pixels, f.pixels, HAND_ROI) <= .025)
                            or (plan.kind == "end_turn" and pr.deploy is None)):
                        if self.bounds.deadline-self.bounds.clock() < 2.:
                            raise Halt("insufficient_time_for_action")
                        idx = self.attempts + 1
                        files = [self.journal.frame(f"a{idx:03d}-prior.png", pf), self.journal.frame(f"a{idx:03d}-before.png", f)]
                        args = self.device.prepare(f, plan)
                        self.bounds.check()
                        if self.bounds.clock()-f.started > FRESHNESS:
                            raise Halt("frame_expired_before_dispatch")
                        self.journal.event("dispatch_attempt", attempt=idx, action=plan.kind, native_input=args, evidence=files,
                                           binding=f.binding, frame_age_ms=round(1000*(self.bounds.clock()-f.started)),
                                           observation=r.brief())
                        self.attempts, self.pending = idx, plan.kind
                        self.device.send(f, args)
                        self.receipts += 1
                        self.journal.event("adb_returned_zero", attempt=idx, meaning="shell_return_only_not_game_effect")
                        boundary = self.verify(plan, current)
                        if boundary:
                            return boundary
                        if self.attempts >= self.action_limit:
                            return "action_budget"
                        previous = None
                        self.bounds.pause()
                        continue
            previous = current if state == "own" else None
            self.bounds.pause()
        return "action_budget"

    def run(self):
        try:
            reason = self.drive()
        except Halt as error:
            reason = str(error)
            if getattr(error, "png", None):
                self.journal.event("refused_png", **self.journal.png("refused.png", error.png))
        except KeyboardInterrupt:
            reason = "keyboard_interrupt"
        except Exception as error:
            reason = f"runtime_error:{type(error).__name__}:{str(error)[:180]}"
        result = dict(stop_reason=reason, outcome=reason if reason in RESULTS else None,
                      attempts=self.attempts, adb_returned_zero=self.receipts,
                      effects_verified=self.verified, unresolved_action=self.pending)
        if self.last:
            observation = self.last_reading.brief() if self.last_reading else None
            self.journal.event("terminal_frame", observation=observation, **self.journal.frame("terminal.png", self.last))
        self.journal.event("finished", **result)
        return result


@contextmanager
def live_lease():
    # Windows kernel object only; no host window, display, or mouse calls.
    if os.name != "nt":
        raise Halt("live_prototype_requires_windows")
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateMutexW
    create.argtypes, create.restype = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR), wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = create(None, False, "Global\\KardsPCEmuBattlePilot_v1")
    error = ctypes.get_last_error()
    if not handle:
        raise Halt(f"single_instance_lock_failed:{error}")
    try:
        if error == 183:
            raise Halt("another_live_pilot_running")
        yield
    finally:
        kernel.CloseHandle(handle)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mobile-root", required=True, type=Path, help="local read-only mobile source checkout")
    parser.add_argument("--out", required=True, type=Path, help="new standalone evidence directory")
    parser.add_argument("--frame", type=Path, help="inspect one saved PNG; never opens ADB")
    parser.add_argument("--adb", type=Path, help="absolute path to local adb.exe")
    parser.add_argument("--serial", help="explicit connected loopback serial 127.0.0.1:PORT")
    parser.add_argument("--package", choices=PACKAGES, help="exact selected Android game package")
    parser.add_argument("--confirmed-training", action="store_true", help="operator attests a manually entered training battle")
    parser.add_argument("--live", action="store_true", help="allow gestures only with --confirmed-training; otherwise inspect")
    parser.add_argument("--end-only", action="store_true", help="do not attempt unit deployment")
    parser.add_argument("--stop-file", type=Path, help="cooperative stop marker; default OUT/STOP")
    parser.add_argument("--seconds", type=float, default=180., help="wall time budget (2..900 seconds)")
    parser.add_argument("--max-actions", type=int, default=18, help="total attempted gestures (1..64)")
    a = parser.parse_args(argv)
    if a.live and (not a.confirmed_training or a.frame):
        parser.error("--live requires --confirmed-training and forbids --frame")
    if not math.isfinite(a.seconds) or not 2 <= a.seconds <= 900 or not 1 <= a.max_actions <= 64:
        parser.error("invalid --seconds or --max-actions budget")
    root, out = a.mobile_root.resolve(), a.out.resolve()
    if not root.is_dir() or out.is_relative_to(root):
        parser.error("use an existing --mobile-root and a separate --out outside it")
    if a.frame is None:
        try:
            validate_target(a.adb, a.serial, a.package)
        except ValueError as error:
            parser.error(str(error))
    journal = None
    try:
        journal = Journal(out)
        mode = "live" if a.live else "saved_inspect" if a.frame else "device_inspect"
        stop = a.stop_file.resolve() if a.stop_file else out / "STOP"
        bounds = Bounds(a.seconds, stop)
        journal.event("start", mode=mode, mobile_root=str(root), adb=str(a.adb) if a.adb else None,
                      serial=a.serial, package=a.package, confirmed_training=a.confirmed_training,
                      stop_file=str(stop), seconds=a.seconds, max_actions=a.max_actions, end_only=a.end_only)
        bounds.check()
        vision = Vision(root)
        if a.live:
            with live_lease():
                device = Adb(a.adb, a.serial, a.package, bounds)
                result = Pilot(device, vision, bounds, journal, action_limit=a.max_actions, end_only=a.end_only).run()
            code = 0 if (result["stop_reason"] in (*RESULTS, "action_budget", "stop_file") and
                         result["unresolved_action"] is None) else 1
        else:
            frame = (Frame.read(1, bounds.clock(), a.frame.read_bytes()) if a.frame else
                     Adb(a.adb, a.serial, a.package, bounds).capture())
            reading = vision.observe(frame.pixels, mode="end_only" if a.end_only else "plan")
            result = dict(stop_reason="inspection_only", attempts=0, observation=reading.brief(),
                          evidence=journal.frame("inspect.png", frame))
            journal.event("finished", **result)
            code = 0
    except (Halt, OSError, ValueError, KeyError, ImportError, cv2.error) as error:
        result = dict(stop_reason=str(error)[:240], error_type=type(error).__name__)
        if journal is not None:
            data = getattr(error, "png", None)
            if data:
                journal.event("refused_png", **journal.png("refused.png", data))
            journal.event("finished", **result)
        code = 1
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
