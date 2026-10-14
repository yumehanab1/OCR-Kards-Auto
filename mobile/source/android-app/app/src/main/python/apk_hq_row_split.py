"""Recover a unique APK HQ only from a proven horizontal bright merge.

Original core pixels, geometry, transitions and ownership remain authoritative.
Current-capture reuse never creates a date, sample, turn or input authority.
"""
from copy import deepcopy
import hashlib
import sys
import cv2
import numpy as np

FIELDS = ("frame_id", "captured_elapsed_ms", "foreground_generation", "source_width", "source_height")

def valid(frame):
    return isinstance(frame, np.ndarray) and frame.shape == (720, 1280, 3) and frame.dtype == np.uint8

def contained(box, outer):
    x, y, w, h = box; ox, oy, ow, oh = outer
    return ox <= x and oy <= y and x+w <= ox+ow and y+h <= oy+oh

def overlap(a, b):
    x, y, w, h = a; xx, yy, ww, hh = b
    return max(x, xx) < min(x+w, xx+ww) and max(y, yy) < min(y+h, yy+hh)

def known_units(frame, board, vision):
    cards = board.cards_from_stats(frame, field=(200, 415, 1120, 595))
    if not 1 <= len(cards) <= 4:
        return None
    result = []
    for card in cards:
        typ = vision.inspect_unit_type(frame, card)
        if card.get("n_stats", 0) < 2 or typ.get("type") not in vision.TYPES or not 425 <= card["y"] <= 470:
            return None
        result.append(dict(card, type=typ["type"], type_evidence=typ))
    return result

def raw_dark_shields(frame, board):
    hp = board.hq_hp
    mask = (cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)[:, :, 2] < hp.SHIELD_DARK_V).astype(np.uint8)
    keep = np.zeros_like(mask); keep[425:590, 200:1120] = 1; mask &= keep
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    return [[int(v) for v in (x, y, w, h)] for x, y, w, h, area in stats[1:]
            if hp.SHIELD_W_MIN <= w <= hp.SHIELD_W_MAX and hp.SHIELD_H_MIN <= h <= hp.SHIELD_H_MAX
            and area >= hp.SHIELD_FILL_MIN*w*h]

def merged_bright_components(frame, board):
    mask = (cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)[:, :, 2] > board.CARD_BRIGHT_V).astype(np.uint8)
    keep = np.zeros_like(mask); keep[425:590, 200:1120] = 1; mask &= keep
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    return [dict(box=[int(v) for v in (x, y, w, h)], area=int(area)) for x, y, w, h, area in stats[1:]
            if w > board.CARD_W_RANGE[1] and board.CARD_H_RANGE[0] <= h <= board.CARD_H_RANGE[1]
            and area >= .5*w*h]

def full_row_ok(cards, hq):
    centers = [card["cx"] for card in sorted([*cards, hq], key=lambda c: c["cx"])]
    return (abs(float(np.mean(centers))-640) <= 12
            and all(132 <= b-a <= 156 for a, b in zip(centers, centers[1:]))
            and all(abs(card["y"]-hq["y"]) <= 12 for card in cards))

def split_proofs(frame, board, vision, original_bright):
    cards = known_units(frame, board, vision)
    if cards is None:
        return {"candidate": None, "proofs": [], "reason": "support_stats_or_type_unknown"}
    merged = merged_bright_components(frame, board)
    proposals = []
    for dark in raw_dark_shields(frame, board):
        if any(overlap(dark, box) for card in cards for box in card["stat_boxes"]):
            continue
        owners = [blob for blob in merged if contained(dark, blob["box"]) and any(
            contained((c["x"], c["y"], c["w"], c["h"]), blob["box"]) for c in cards)]
        if len(owners) != 1:
            continue
        blob = owners[0]; sx, sy, sw, sh = dark; center = sx+sw/2
        left = [card for card in cards if card["cx"] < center]
        right = [card for card in cards if card["cx"] > center]
        if len(left) == len(cards):
            unit = max(left, key=lambda c: c["cx"])
            fields = [(cut, 425, 1120, 590) for cut in range(unit["x"]+unit["w"]+1, sx)]
            side = "left"
        elif len(right) == len(cards):
            unit = min(right, key=lambda c: c["cx"])
            fields = [(200, 425, cut, 590) for cut in range(sx+sw+1, unit["x"])]
            side = "right"
        else:
            continue
        accepted = []
        for field in fields:
            for candidate in original_bright(frame, field):
                box = tuple(candidate[k] for k in ("x", "y", "w", "h"))
                if not contained(box, blob["box"]):
                    continue
                clearance = (candidate["x"]-field[0] if side == "left"
                             else field[2]-candidate["x"]-candidate["w"])
                if clearance < 4:  # Original 9x9 closing radius; reject a cropped contour.
                    continue
                shield, shield_box = board.hq_hp.find_shield(frame, candidate)
                if shield is None or not board._hq_shield_geometry(candidate, shield_box):
                    continue
                if tuple(shield_box) != (sx-2, sy-2, sw+4, sh+4) or not full_row_ok(cards, candidate):
                    continue
                accepted.append(dict(card=candidate, shield=list(shield_box), raw_dark_shield=dark,
                                     field=list(field), cut_clearance=clearance, side=side, merged_component=blob))
        if accepted:
            # Variants share this exact independently detected shield. Width
            # chooses its complete contour, never between different HQ identities.
            chosen = max(accepted, key=lambda proof: proof["card"]["w"])
            chosen["validated_contour_variants"] = len(accepted)
            proposals.append(chosen)
    return {"candidate": proposals[0]["card"] if len(proposals) == 1 else None,
            "proofs": proposals, "units": cards, "reason": "unique_hq_structure" if len(proposals) == 1 else "unique_hq_structure_not_proven"}

class HqRowSplitter:
    def __init__(self, board, vision, original_row, original_bright, raw_badges):
        self.board, self.vision = board, vision
        self.original_row, self.original_bright, self.raw_badges = original_row, original_bright, raw_badges
        self._provisional = None
        self.clear()

    def clear(self):
        self.frame = self.info = self.initial = self.decision = None

    def register(self, frame, info):
        self.clear(); self.frame, self.info = frame, info; self.initial = self._token(frame)

    def _token(self, frame):
        if (frame is not self.frame or not valid(frame) or not frame.flags.c_contiguous
                or not isinstance(self.info, dict) or any(type(self.info.get(k)) is not int for k in FIELDS)
                or any(self.info[k] < 0 for k in FIELDS[:3]) or any(self.info[k] <= 0 for k in FIELDS[3:])):
            return None
        from apk_current_capture_memo import configuration_epoch
        modules = [self.board, self.vision, sys.modules[__name__], self.board.hq_hp]
        if hasattr(self.board, "us"): modules.append(self.board.us)
        for name in ("apk_hq_geometry", "apk_hq_adapter", "apk_green_stat", "kredits_templates"):
            if name in sys.modules: modules.append(sys.modules[name])
        epoch = configuration_epoch(modules)
        if epoch is None: return None
        return (id(self.original_row), id(self.original_bright), id(self.raw_badges), epoch, id(frame),
                *(self.info[k] for k in FIELDS), hashlib.blake2b(memoryview(frame), digest_size=16).digest())

    def _decide(self, frame):
        board = self.board
        rejected = {"allowed": False, "candidate": None, "proofs": [], "reason": "unknown"}
        # Both proof phases bypass ordinary memo. The raw candidate callback
        # prevents artwork/HQ from bootstrapping each other's missing evidence.
        prior_hq = getattr(board, "_apk_hq_row_split_busy", False)
        prior_art = getattr(board, "_apk_artwork_filter_busy", False)
        board._apk_hq_row_split_busy = board._apk_artwork_filter_busy = True
        try:
            raw = self.raw_badges(frame)
            if any(not (board.FRONT_BAND[0] <= b["cy"] <= board.FRONT_BAND[1]
                        or board.SUPPORT_BAND[0] <= b["cy"] <= board.SUPPORT_BAND[1]) for b in raw):
                return dict(rejected, reason="raw_out_of_row_preserved")
            if board.board_transition_reason(frame) or board.choice_modal(frame)[0]:
                return dict(rejected, reason="transition_or_choice_preserved")
            proof = split_proofs(frame, board, self.vision, self.original_bright)
            if proof["candidate"] is None: return dict(rejected, **proof)
            self._provisional = (frame, proof["candidate"])
            front = board.frontline_state(frame)
            if front.get("owner") not in ("our", "enemy", "empty"):
                return dict(rejected, **dict(proof, reason="original_frontline_unknown_preserved", frontline=front))
            return dict(proof, allowed=True, reason="known_unit_unique_shield_horizontal_split", frontline=front)
        finally:
            self._provisional = None
            board._apk_hq_row_split_busy, board._apk_artwork_filter_busy = prior_hq, prior_art

    def row(self, frame, side, field=None):
        board = self.board
        if field is None: field = board.FIELD
        original = self.original_row(frame, side, field)
        if original or side != "our" or tuple(field) != tuple(board.FIELD) or not valid(frame): return original
        if getattr(board, "_apk_hq_row_split_busy", False):
            if self._provisional is not None and frame is self._provisional[0]:
                return [deepcopy(self._provisional[1])]
            return original
        if getattr(board, "_apk_artwork_filter_busy", False): return original
        token = self._token(frame)
        if frame is self.frame and self.initial is not None and token != self.initial:
            self.initial = self.decision = None
        try:
            if token is not None and token == self.initial and self.decision is not None:
                decision = deepcopy(self.decision)
            else:
                decision = self._decide(frame)
                if token is not None and token == self.initial and self._token(frame) == token:
                    self.decision = deepcopy(decision)
        except Exception:
            self.clear()
            return original
        return [deepcopy(decision["candidate"])] if decision["allowed"] else original

def install(board=None, vision=None):
    if board is None:
        import mobile_board as board
    if vision is None:
        import mobile_combat_vision as vision
    if not hasattr(board, "_apk_original_support_row_bright_cards"):
        board._apk_original_support_row_bright_cards = board._support_row_bright_cards
    if not hasattr(board, "_apk_hq_row_split_original_bright_cards"):
        board._apk_hq_row_split_original_bright_cards = board.bright_cards
    if not hasattr(board, "_apk_hq_row_split_raw_badges"):
        board._apk_hq_row_split_raw_badges = getattr(board, "_apk_original_badge_candidates", board._badge_candidates)
    adapter = HqRowSplitter(board, vision, board._apk_original_support_row_bright_cards,
                            board._apk_hq_row_split_original_bright_cards, board._apk_hq_row_split_raw_badges)
    board._support_row_bright_cards = adapter.row
    board._apk_hq_row_split_busy = False
    return adapter
