"""Read-only Android KARDS vision and single-action planning (1280 x 720)."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import types
from typing import Any, Callable

import cv2
import numpy as np


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def runtime_root(root: Path | None = None) -> Path:
    base = Path(root) if root is not None else repo_root()
    for cand in (base / "mobile/source/android-app/app/src/main",
                 base / "src/emu_runtime"):
        if (cand / "assets/mobile-core").is_dir():
            return cand
    raise FileNotFoundError(f"Emulator vision runtime not found under {base}")


def load_mobile_modules(repo_root: Path | None = None):
    """Load the bundled readers, never exporting generated files into mobile/.

    Workers are separate processes. Preserve an already imported PC win module;
    no reader here calls its capture/input methods. Disable bytecode as well as
    redirecting the diagnostic digit exports, including subsequent lazy imports.
    """
    main = runtime_root(repo_root)
    sys.dont_write_bytecode = True
    if "win" not in sys.modules:
        try:
            importlib.import_module("win")
        except (ImportError, OSError, AttributeError):
            shim = types.ModuleType("win")
            shim.capture_client_bgr = lambda *a, **k: None
            shim.client_size = lambda *a, **k: (1280, 720)
            shim.client_to_screen = lambda x, y, *a, **k: (int(x), int(y))
            shim.find_by_process = lambda *a, **k: True
            shim.set_dpi_aware = lambda *a, **k: None
            sys.modules["win"] = shim
    for path in (main / "python", main / "assets/mobile-core/src"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    kredits = importlib.import_module("kredits_templates")
    destination = str(Path(tempfile.gettempdir()) / "kards_emu_kredits_tpl")
    kredits.TEMPLATE_DIR = kredits.TEMPLATES_DIR = destination
    names = ("mobile_board", "mobile_hand", "mobile_end_button", "apk_hq_adapter",
             "apk_hq_geometry", "apk_simple_combat", "mobile_combat_policy",
             "apk_hand_availability", "apk_deploy_target", "apk_enemy_turn",
             "apk_native.native_hand")
    modules = {name.split(".")[-1]: importlib.import_module(name) for name in names}
    modules["apk_hq_adapter"].install()
    modules["apk_hq_geometry"].install()
    # The APK chooser delegates priority to the original policy and expects its
    # geometry-only actor options installed, without installing an input engine.
    policy = modules["mobile_combat_policy"]
    if not hasattr(policy, "_apk_original_choose"):
        policy._apk_original_choose = policy.choose
    policy._actor_options = modules["apk_simple_combat"].actor_options
    return types.SimpleNamespace(**modules)


@dataclass
class ScreenObservation:
    state: str
    reason: str
    target: tuple[int, int] | None = None
    end_button: tuple[int, int, int, int] | None = None
    ocr_texts: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionPlan:
    kind: str
    origin: tuple[int, int]
    target: tuple[int, int] | None = None
    path: list[tuple[int, int]] | None = None
    key: tuple = ()
    reason: str = ""


def _box_center(box):
    x0, y0, x1, y1 = box
    return (int((x0 + x1) / 2), int((y0 + y1) / 2))


def _orange_pixel_count(frame, box):
    x0, y0, x1, y1 = map(int, box)
    patch = frame[max(0, y0-12):min(720, y1+12), max(0, x0-12):min(1280, x1+12)]
    if not patch.size:
        return 0
    h, s, v = cv2.split(cv2.cvtColor(patch, cv2.COLOR_BGR2HSV))
    return int(((h >= 5) & (h <= 35) & (s >= 90) & (v >= 100)).sum())


def frame_motion(a: np.ndarray, b: np.ndarray,
                 roi: tuple[int, int, int, int] | None = None) -> float:
    """Fraction of pixels changed by >18 levels; ROI uses x0,y0,x1,y1."""
    if a is None or b is None or a.shape != b.shape:
        return 0.0
    if roi is not None:
        x0, y0, x1, y1 = roi
        a, b = a[y0:y1, x0:x1], b[y0:y1, x0:x1]
    if not a.size:
        return 0.0
    return float((cv2.absdiff(a, b).max(axis=2) > 18).mean())


class EmuVision:
    def __init__(self, root: Path | None = None, ocr_fn: Callable | None = None,
                 load_core: bool = True, ocr_threads: int = 2,
                 ocr_cache_ttl: float = 2.5, clock_fn=time.monotonic,
                 ocr_url: str | None = None, ocr_token: str | None = None):
        self.root = Path(root) if root is not None else repo_root()
        self.core = load_mobile_modules(self.root) if load_core else None
        self.ocr_fn, self._ocr = ocr_fn, None
        self.ocr_url = self.ocr_token = None
        if ocr_fn is None:
            self.ocr_url = ocr_url if ocr_url is not None else os.environ.get("KARDS_EMU_OCR_URL") or None
            self.ocr_token = ocr_token if ocr_token is not None else os.environ.get("KARDS_EMU_OCR_TOKEN") or ""
        self.ocr_threads = ocr_threads
        self.ocr_cache_ttl, self.clock = ocr_cache_ttl, clock_fn
        self._ocr_cache = None
        self.last_deploy_reason = ""
        self.templates = {}
        main = runtime_root(self.root)
        base = main / "assets/mobile-core"
        names = {"end_turn_btn", "end_turn_btn_white", "end_turn_btn_orange",
                 "victory_btn", "defeat_btn"}
        if self.core:
            names.update(self.core.mobile_end_button.TEMPLATE_NAMES)
        for state in ("ingame", "victory", "defeat"):
            meta = json.loads((base / f"config/templates.android.{state}.json").read_text(encoding="utf-8-sig"))
            for name, entry in meta["templates"].items():
                if name in names:
                    self._add_template(name, base / entry["path"],
                                       tuple(entry["region"][k] for k in ("x", "y", "w", "h")))
        self._add_template("defeat_banner", main / "assets/match-entry/defeat_banner.png", (490, 365, 300, 185))
        color = self.templates["end_turn_btn"][0]
        h, w = color.shape[:2]
        scaled = cv2.resize(color, (round(w*1.10), round(h*1.10)), interpolation=cv2.INTER_CUBIC)
        self.templates["end_turn_btn_110"] = (scaled, cv2.cvtColor(scaled, cv2.COLOR_BGR2GRAY), (1040, 470, 220, 100))

    def _add_template(self, name, path, roi):
        color = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        if color is None:
            raise ValueError(f"Unreadable template: {path}")
        self.templates[name] = (color, cv2.cvtColor(color, cv2.COLOR_BGR2GRAY), roi)

    def _match(self, frame, name):
        color, gray, (x, y, w, h) = self.templates[name]
        patch = cv2.cvtColor(frame[y:y+h, x:x+w], cv2.COLOR_BGR2GRAY)
        _, score, _, (dx, dy) = cv2.minMaxLoc(cv2.matchTemplate(patch, gray, cv2.TM_CCOEFF_NORMED))
        th, tw = gray.shape
        return float(score), (x+dx, y+dy, tw, th)

    def run_ocr(self, frame):
        if self.ocr_fn is not None:
            return self.ocr_fn(frame)
        if self.ocr_url:
            try:
                if __package__:
                    from .emu_ocr_server import request_ocr
                else:
                    from emu_ocr_server import request_ocr
                return request_ocr(self.ocr_url, self.ocr_token, frame)
            except Exception:
                pass  # A failed shared service must not interrupt a worker's local OCR.
        if self._ocr is None:
            from rapidocr_onnxruntime import RapidOCR
            try:
                self._ocr = RapidOCR(intra_op_num_threads=self.ocr_threads,
                                     inter_op_num_threads=1)
            except TypeError:
                self._ocr = RapidOCR()
        result, _ = self._ocr(frame)
        return [((int(min(p[0] for p in box)), int(min(p[1] for p in box)),
                  int(max(p[0] for p in box)), int(max(p[1] for p in box))), text, float(score))
                for box, text, score in (result or [])]

    def classify_battle(self, frame: np.ndarray, *, allow_opponent_turn: bool = True) -> ScreenObservation | None:
        if (frame is None or frame.shape != (720, 1280, 3) or frame.dtype != np.uint8):
            return ScreenObservation("unknown", "invalid_frame")
        if int(frame.max()) < 8:
            return ScreenObservation("blank", "black_screen")
        for name in ("victory_btn", "defeat_btn", "defeat_banner"):
            score, _ = self._match(frame, name)
            if score >= .90:
                return ScreenObservation("victory" if name == "victory_btn" else "defeat",
                                         name, (640, 665), evidence={"score": score})
        if self.core:
            for name in self.templates:
                if not name.startswith("end_turn_btn"):
                    continue
                score, box = self._match(frame, name)
                if score < .86:
                    continue
                x, y, w, h = box
                color, metrics = self.core.mobile_end_button._stroke_color(
                    frame[y:y+h, x:x+w], self.templates[name][0])
                if color in ("white", "orange"):
                    return ScreenObservation("own_turn", name, (x+w//2, y+h//2), box,
                                             evidence={"score": score, "color": color, **metrics})
            if allow_opponent_turn and self.core.apk_enemy_turn.inspect_opponent_turn(frame).get("present") is True:
                return ScreenObservation("opponent_turn", "enemy_turn_label")
        return None

    def invalidate_ocr_cache(self):
        """Force the next screen observation to read fresh OCR evidence."""
        self._ocr_cache = None

    def classify_screen(self, frame: np.ndarray, *, target_mode="training", deck_name="",
                        allow_fast_opponent: bool = True):
        if target_mode not in ("training", "casual", "ranked"):
            raise ValueError("Unsupported mode")
        battle = self.classify_battle(frame, allow_opponent_turn=allow_fast_opponent)
        if battle is not None:
            self._ocr_cache = None
            return battle
        key = (target_mode, deck_name)
        thumb = cv2.resize(frame, (160, 90))
        now = self.clock()
        if self._ocr_cache is not None:
            prev_key, prev_thumb, cached, ts = self._ocr_cache
            if (key == prev_key and now - ts < self.ocr_cache_ttl
                    and frame_motion(prev_thumb, thumb) < .005):
                return deepcopy(cached)
        entries = [(box, text, _box_center(box)) for box, text, score in self.run_ocr(frame) if score >= .5]
        texts = [e[1] for e in entries]

        def find(text, predicate=lambda p: True):
            return next((e for e in entries if text in e[1] and predicate(e[2])), None)

        def point(entry, default=None):
            return entry[2] if entry else default

        def obs(state, target=None, reason=None):
            result = ScreenObservation(state, reason or "ocr_"+state, target, ocr_texts=texts)
            self._ocr_cache = (key, thumb, deepcopy(result), now)
            return result

        if any(find(t) for t in ("断开连接", "重新连接", "Reconnect", "NETWORKERROR", "NETWORK ERROR", "请检查网络连接")):
            # Prefer the restart button over the instruction mentioning it.
            restart = next((e for e in entries if e[1] == "重启"), None) or find("重启")
            return obs("disconnected", point(find("重新连接") or restart or find("重试") or find("Reconnect"), (640, 402)))
        if find("选择目标", lambda p: p[1] < 520):
            return obs("target_selection")
        confirm = find("确认", lambda p: 450 <= p[0] <= 850 and p[1] >= 580)
        if find("选择要替换的卡牌") or confirm:
            return obs("mulligan", point(confirm, (640, 648)))
        end_btn = next((e for e in entries
                        if ("结束回合" in e[1] or "END TURN" in e[1].upper())
                        and e[2][0] >= 980 and 420 <= e[2][1] <= 620), None)
        if end_btn:
            return obs("own_turn", end_btn[2], "ocr_end_turn")
        if find("敌方", lambda p: p[0] >= 1000 and 440 <= p[1] <= 590):
            return obs("opponent_turn", None, "ocr_opponent_turn")
        if find("胜利") and not find("对战模式"):
            return obs("victory", point(find("继续"), (640, 665)))
        if find("失败") or find("查看战场"):
            return obs("defeat", point(find("继续"), (640, 665)))
        if find("每日登录奖励"):
            claimable = [e for e in entries if "领取" in e[1]
                         and "已领取" not in e[1] and e[2][1] < 600]
            claim = next((e for e in claimable if e[1] == "领取"),
                         claimable[0] if claimable else None)
            return obs("login_reward", (claim[2][0], min(600, claim[2][1] + 90)) if claim else (640, 655))
        if find("完成所有入伍任务") or ((find("战争经济") or find("增援")) and not find("开始", lambda p: p[0] < 200)):
            return obs("task_popup", (640, 665))
        if find("已发现对手") or find("正在寻找对手") or find("取消", lambda p: 450 <= p[0] <= 830 and p[1] >= 450):
            return obs("queueing")
        training, battle_tab = find("训练模式"), find("对战模式")
        if training and battle_tab:
            start = find("开始", lambda p: p[0] >= 900 and p[1] >= 480)
            state = "deck_detail" if start else "deck_list"
            desired, other = (training, battle_tab) if target_mode == "training" else (battle_tab, training)
            desired_orange, other_orange = (_orange_pixel_count(frame, e[0]) for e in (desired, other))
            # Ambiguous battle selection must not accidentally start ranked.
            selected = desired_orange > other_orange or (target_mode == "training" and other_orange <= desired_orange)
            if not selected:
                return obs(state, desired[2], "select_mode_tab")
            if start:
                if target_mode != "training":
                    casual = find("休闲", lambda p: p[0] >= 800)
                    ranked = find("排位", lambda p: p[0] >= 800)
                    if not casual or not ranked:
                        return obs(state, None, "submode_not_visible")
                    wanted, unwanted = (casual, ranked) if target_mode == "casual" else (ranked, casual)
                    if _orange_pixel_count(frame, wanted[0]) <= _orange_pixel_count(frame, unwanted[0]):
                        return obs(state, wanted[2], "select_submode")
                return obs(state, start[2], "start_selected_mode")
            named = find(deck_name, lambda p: p[0] >= 450 and 100 <= p[1] <= 650) if deck_name else None
            if named:
                x, y = named[2]
                return obs(state, (x, max(160, y-80)), "select_named_deck")
            decks = [e for e in entries if e not in (training, battle_tab) and e[2][0] >= 500 and 320 <= e[2][1] <= 500]
            chosen = min(decks, key=lambda e: e[2][0]) if decks else None
            return obs(state, (chosen[2][0], max(160, chosen[2][1]-106)) if chosen else (625, 290), "select_default_deck")
        start = find("开始", lambda p: p[0] < 220)
        if start and any(find(t) for t in ("商店", "任务", "竞技场", "军需箱", "卡包")):
            return obs("home", start[2])
        dismiss = find("关闭") or find("继续")
        if dismiss or any(find(t) for t in ("轻触领取", "轻触继续", "轻触任意位置", "点击任意位置", "点击继续")):
            return obs("promo_popup", point(dismiss, (640, 665)))
        if self.core and self.core.mobile_board.choice_modal(frame)[0]:
            return obs("choice_modal", (640, 360), "board_choice_modal")
        return obs("unknown", reason="unrecognized_screen")

    def enemy_hq(self, frame):
        try:
            hq = self.core.mobile_board.hq_card(frame, "enemy")
            return (int(hq["cx"]), int(hq["cy"])) if hq and hq.get("geometry_verified") else None
        except Exception:
            return None

    def plan_combat_action(self, frame, skip_actors=None):
        try:
            mb = self.core.mobile_board
            units = mb.actionable_units(frame)
            def key(u):
                return (u["row"], int(u["badge"]["x"])//24, int(u["badge"]["cy"])//24)
            units = [dict(u, type=mb.unit_combat_type(frame, u)) for u in units if key(u) not in (skip_actors or set())]
            hq = mb.hq_card(frame, "enemy")
            guard = dict(mb.combat_guard_info(frame, hq=hq))
            support = [dict(c, row="enemy_support") for c in mb.enemy_support_cards(frame)]
            fronts = [dict(c, row="enemy_front") for c in mb.enemy_front_cards(frame)]
            def card_key(c):
                return tuple(c[k] for k in ("x", "y", "w", "h"))
            protected = {card_key(c) for c in guard.get("protected_units", [])}
            for target in fronts + support:
                glyph = guard.get("detail", {}).get(f'{target["row"]}@{target["x"]},{target["y"]}', {})
                target.update(protected=card_key(target) in protected,
                              guard_state=glyph.get("state", "unknown"))
            # Only the immediate support neighbours can guard this HQ. Preserve
            # protection/unknown glyph vetoes and the bomber interceptor row tag.
            guard["hq_guards"] = []
            if hq is not None and guard.get("status") == "guarded":
                row = sorted(support + [hq], key=lambda c: c["cx"])
                index = next(i for i, c in enumerate(row) if c is hq)
                neighbors = [row[i] for i in (index-1, index+1) if 0 <= i < len(row)]
                guard_keys = {card_key(c) for c in guard.get("guards", [])}
                guard["hq_guards"] = [c for c in neighbors if card_key(c) in guard_keys
                                      and abs(c["cy"]-hq["cy"]) <= 40
                                      and 0 < abs(c["cx"]-hq["cx"]) <= 1.9*max(c["w"], hq["w"])]
            observed = dict(units=units, owner=mb.frontline_state(frame)["owner"], hq=hq,
                            enemy_front=fronts, enemy_support=support, guard=guard)
            plan = self.core.apk_simple_combat.choose(observed)
            kind = plan["kind"]
            if kind not in ("attack_hq", "attack_unit", "movefront", "move_front"):
                return None
            actor = plan["unit"]
            origin = ((int(actor["cx"]), int(actor["cy"])) if "cx" in actor else
                      (int(actor["badge"]["x"])+28, int(actor["badge"]["cy"])+35))
            if kind in ("movefront", "move_front"):
                kind, target = "move_front", (min(960, max(320, origin[0])), int(mb.FRONTLINE_Y))
            else:
                target = (int(plan["target"]["cx"]), int(plan["target"]["cy"]))
            return ActionPlan(kind, origin, target, key=key(actor), reason=plan.get("reason", ""))
        except Exception:
            return None

    def find_open_support_slot(self, frame):
        try:
            row = None
            try:
                raw = self.core.apk_deploy_target._row(frame)
                if isinstance(raw, tuple):
                    cards, _, row = raw
                    if cards is None:
                        row = None
                else:
                    row = raw
                if row and row["hq"] and row["centers"]:
                    if len(row["units"]) >= 4:
                        return None
                    centers, bounds = row["centers"], row["bounds"]
                    y = max(485, min(515, int(row["hq"]["cy"])))
                else:
                    row = None
            except Exception:
                row = None
            if row is None:
                mb = self.core.mobile_board
                hq = mb.hq_card(frame, "our")
                units = mb.cards_from_stats(frame, field=(200, 415, 1120, 595))
                if hq:
                    # Stats can also detect the HQ: count only distinct units.
                    units = [u for u in units if not (
                        u["x"] <= hq["cx"] <= u["x"]+u["w"]
                        and u["y"] <= hq["cy"] <= u["y"]+u["h"]
                        or (max(u["x"], hq["x"]) < min(u["x"]+u["w"], hq["x"]+hq["w"])
                            and max(u["y"], hq["y"]) < min(u["y"]+u["h"], hq["y"]+hq["h"])))]
                if len(units) >= 4:
                    return None
                occupied = ([hq] if hq else []) + units
                bounds = [(c["x"], c["y"], c["x"]+c["w"], c["y"]+c["h"]) for c in occupied]
                centers = [c["cx"] for c in occupied]
                y = max(485, min(515, int(hq["cy"]))) if hq else 505
            if centers:
                lo, hi = min(centers), max(centers)
                candidates = (hi+144, lo-144, hi+135, lo-135, 855, 425, 710, 920)
            else:
                candidates = (855, 425, 710, 920)
            best = None
            for x in candidates:
                x = int(x)
                if not 350 <= x <= 930:
                    continue
                if any(a-15 <= x <= c+15 and b-15 <= y <= d+15 for a, b, c, d in bounds):
                    continue
                hsv = cv2.cvtColor(frame[y-45:y+45, x-40:x+40], cv2.COLOR_BGR2HSV)
                bright = float(((hsv[:, :, 2] >= 185) & (hsv[:, :, 1] <= 75)).mean())
                # Prefer strict dark-board clearance even over an earlier bright slot.
                if bright < .12:
                    return (x, y)
                if bright < .28 and (best is None or bright < best[0]):
                    best = (bright, (x, y))
            if best is not None:
                return best[1]
        except Exception:
            pass
        return None

    def plan_deploy_action(self, frame, skip_grabs=None):
        self.last_deploy_reason = ""
        try:
            c = self.core
            target = self.find_open_support_slot(frame)
            if target is None:
                self.last_deploy_reason = "no_open_slot"
                return None
            hand = c.mobile_hand.find_hand(frame, zone=c.mobile_hand.DEFAULT_ZONE, want="orange")
            if not hand:
                self.last_deploy_reason = "no_orange_hand"
                return None
            try:
                native = c.native_hand.inspect(frame)
            except Exception:
                native = []
            geometry = c.apk_hand_availability._geometry_plates(frame)
            skipped = False
            for b in hand:
                ad = b.get("ad_info", {})
                hit = [n for n in native if abs(n["center"][0]-b["cx"]) <= 9 and abs(n["center"][1]-b["cy"]) <= 9]
                if not (b.get("kind") == "unit" and b.get("state") == "orange" and ad.get("plate_confirmed") and ad.get("ad")
                        and len(hit) == 1 and hit[0].get("orange") and hit[0].get("operation_numeral")
                        and not hit[0].get("suspected_order")):
                    continue
                approval = c.apk_hand_availability.inspect_unit(frame, b, _geometry=geometry)
                grab = c.apk_hand_availability._safe_grab(frame, b, approval)["point"]
                if not grab:
                    continue
                gx, gy = map(int, grab)
                key = (gx//24, gy//24)
                if key in (skip_grabs or set()):
                    skipped = True
                    continue
                self.last_deploy_reason = "ok:deploy_orange_unit"
                return ActionPlan("deploy", (gx, gy), target,
                                  [(gx, gy), (gx, min(575, gy-60)), target], key, "deploy_orange_unit")
            for b in hand:
                if not (b.get("kind") == "unit" and b.get("state") == "orange"
                        and b.get("ad_info", {}).get("plate_confirmed")):
                    continue
                hit = [n for n in native if abs(n["center"][0]-b["cx"]) <= 9 and abs(n["center"][1]-b["cy"]) <= 9]
                if any(n.get("suspected_order") for n in hit):
                    continue
                gx = min(1150, max(200, int(b["cx"]) + 25))
                gy = min(705, max(580, int(b["cy"]) + 25))
                key = (gx//24, gy//24)
                if key in (skip_grabs or set()):
                    skipped = True
                    continue
                self.last_deploy_reason = "ok:deploy_orange_unit_fallback"
                return ActionPlan("deploy", (gx, gy), target,
                                  [(gx, gy), (gx, min(575, gy-60)), target], key, "deploy_orange_unit_fallback")
            self.last_deploy_reason = "all_skipped" if skipped else f"all_hand_filtered(n={len(hand)})"
        except Exception as exc:
            self.last_deploy_reason = f"error:{type(exc).__name__}"
        return None

    def detect_insufficient_kredits(self, frame):
        if frame is None:
            return False
        return any("指挥点数不足" in text or "无法使用" in text
                   for _, text, _ in self.run_ocr(frame[120:260, 300:980]))

    frame_motion = staticmethod(frame_motion)
