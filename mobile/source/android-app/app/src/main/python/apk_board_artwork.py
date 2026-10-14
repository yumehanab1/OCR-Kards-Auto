"""Exclude only proven lower-card artwork from APK board badge candidates.

The unchanged board recognizers still decide transitions, ownership and actions.
This adapter shares one exclusion set with their nested candidate consumers.
"""
from copy import deepcopy
import hashlib
import sys

import numpy as np

OUT_OF_ROW_PREFIX = "费用徽章不在已确认战场行("
FIELDS = ("frame_id", "captured_elapsed_ms", "foreground_generation",
          "source_width", "source_height")


def candidate_key(badge):
    return tuple(int(badge[k]) for k in ("x", "y", "w", "h", "cx", "cy"))


def on_action_row(badge, board):
    return (board.FRONT_BAND[0] <= badge["cy"] <= board.FRONT_BAND[1]
            or board.SUPPORT_BAND[0] <= badge["cy"] <= board.SUPPORT_BAND[1])


def overlaps(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return max(ax, bx) < min(ax+aw, bx+bw) and max(ay, by) < min(ay+ah, by+bh)


def structural_row(frame, board, vision):
    result = {"complete": False, "reason": "invalid_frame", "cards": [], "hq": None}
    if not (isinstance(frame, np.ndarray) and frame.shape == (720, 1280, 3)
            and frame.dtype == np.uint8):
        return result
    anchors = []
    for candidate in board._support_row_bright_cards(frame, "our"):
        shield, box = board.hq_hp.find_shield(frame, candidate)
        if shield is not None and board._hq_shield_geometry(candidate, box):
            anchors.append(candidate)
    if len(anchors) != 1:
        return dict(result, reason="support_hq_structure_not_unique")
    hq = dict(anchors[0], row_kind="hq")
    result["hq"] = hq
    units = board.cards_from_stats(frame, field=(200, 415, 1120, 595))
    if any(not 425 <= card["y"] <= 470 for card in units):
        return dict(result, reason="unclassified_support_geometry")
    if not 1 <= len(units) <= 4:
        return dict(result, reason="support_unit_count_out_of_range")
    approved = []
    for card in units:
        typ = vision.inspect_unit_type(frame, card)
        if card.get("n_stats", 0) < 2 or typ.get("type") not in vision.TYPES:
            return dict(result, reason="support_unit_evidence_incomplete")
        approved.append(dict(card, row_kind="unit", type=typ["type"], type_evidence=typ))
    cards = sorted([hq]+approved, key=lambda card: card["cx"])
    centers = [int(card["cx"]) for card in cards]
    result.update(cards=cards, centers=centers)
    if abs(float(np.mean(centers))-640) > 12:
        return dict(result, reason="support_row_not_completely_centered")
    if any(not 132 <= b-a <= 156 for a, b in zip(centers, centers[1:])):
        return dict(result, reason="support_row_has_missing_or_overlapping_slot")
    if any(abs(card["y"]-hq["y"]) > 12 for card in cards):
        return dict(result, reason="support_row_vertical_geometry_disagrees")
    return dict(result, complete=True, reason="complete_support_row")


def artwork_evidence(badge, card, board, vision):
    bbox = tuple(int(badge[k]) for k in ("x", "y", "w", "h"))
    stats = card.get("stat_boxes", [])
    result = {"allowed": False, "badge_box": list(bbox),
              "card_box": [card[k] for k in ("x", "y", "w", "h")],
              "type_evidence": card.get("type_evidence"), "stat_boxes": stats}
    if len(stats) < 2 or card.get("type") not in vision.TYPES:
        return dict(result, reason="card_stat_or_type_evidence_incomplete")
    x, y, w, h = (int(card[k]) for k in ("x", "y", "w", "h"))
    if (bbox[2:] != (board.BADGE_WIN, board.BADGE_WIN)
            or not all(23 <= box[2] <= 36 and 23 <= box[3] <= 36 for box in stats)):
        return dict(result, reason="unrecognized_box_geometry")
    strip = [x+8, y+(h+1)//2, x+w-8, min(box[1] for box in stats)]
    operation = [x-2, y-2, 39, 39]
    result.update(art_strip=strip, operation_box=operation)
    if not (strip[0] <= bbox[0] and strip[1] <= bbox[1]
            and bbox[0]+bbox[2] <= strip[2] and bbox[1]+bbox[3] <= strip[3]):
        return dict(result, reason="candidate_not_fully_inside_lower_artwork")
    if overlaps(bbox, operation) or any(overlaps(bbox, box) for box in stats):
        return dict(result, reason="candidate_intersects_operation_or_stat")
    return dict(result, allowed=True, reason="known_support_card_lower_artwork_not_operation_or_stat")


class ArtworkFilter:
    def __init__(self, board, vision, original):
        self.board, self.vision, self.original = board, vision, original
        self._provisional = None
        self.clear()

    def clear(self):
        self.frame = self.info = self.initial = self.decision = None

    def register(self, frame, info):
        self.clear()
        self.frame, self.info = frame, info
        self.initial = self._token(frame)

    def _token(self, frame):
        if (frame is not self.frame or not isinstance(frame, np.ndarray)
                or frame.shape != (720, 1280, 3) or frame.dtype != np.uint8
                or not frame.flags.c_contiguous or not isinstance(self.info, dict)
                or any(type(self.info.get(key)) is not int for key in FIELDS)
                or any(self.info[key] < 0 for key in FIELDS[:3])
                or any(self.info[key] <= 0 for key in FIELDS[3:])):
            return None
        from apk_current_capture_memo import configuration_epoch
        import apk_hq_geometry
        import apk_hq_adapter
        modules = [self.board, self.vision, apk_hq_geometry, apk_hq_adapter, sys.modules[__name__]]
        if "apk_hq_row_split" in sys.modules:
            modules.append(sys.modules["apk_hq_row_split"])
        for name in ("apk_green_stat", "kredits_templates"):
            if name in sys.modules:
                modules.append(sys.modules[name])
        modules += [getattr(self.board, name) for name in ("us", "hq_hp") if hasattr(self.board, name)]
        epoch = configuration_epoch(modules)
        if epoch is None:
            return None
        return (id(self.original), epoch, id(frame), *(self.info[key] for key in FIELDS),
                hashlib.blake2b(memoryview(frame), digest_size=16).digest())

    def _decide(self, frame):
        board, vision = self.board, self.vision
        raw = self.original(frame)
        bad = [badge for badge in raw if not on_action_row(badge, board)]
        result = {"excluded": [], "reason": "no_out_of_row_candidate", "proofs": []}
        if not bad:
            return result
        # During proof construction, nested candidate calls only read raw or
        # the provisional set. They never start another decision. Runtime's
        # board memo bypasses this phase so provisional observations cannot leak.
        previous_busy = getattr(board, "_apk_artwork_filter_busy", False)
        board._apk_artwork_filter_busy = True
        try:
            reason = board.board_transition_reason(frame)
            if reason and not reason.startswith(OUT_OF_ROW_PREFIX):
                return dict(result, reason="other_transition_preserved")
            if board.choice_modal(frame)[0]:
                return dict(result, reason="choice_suspicion_preserved")
            row = structural_row(frame, board, vision)
            if not row["complete"]:
                return dict(result, reason=row["reason"])
            for badge in bad:
                owners = [proof for card in row["cards"] if card.get("row_kind") == "unit"
                          for proof in [artwork_evidence(badge, card, board, vision)] if proof["allowed"]]
                if len(owners) != 1:
                    return dict(result, reason="out_of_row_candidate_unexplained_or_ambiguous")
                result["proofs"].append(owners[0])
            keys = {candidate_key(badge) for badge in bad}
            self._provisional = (frame, keys)
            if board.frontline_state(frame).get("owner") not in ("our", "enemy", "empty"):
                return dict(result, reason="frontline_unknown_preserved")
            return dict(result, excluded=sorted(keys), reason="all_out_of_row_candidates_proven_lower_artwork")
        finally:
            self._provisional = None
            board._apk_artwork_filter_busy = previous_busy

    def candidates(self, frame, *args, **kwargs):
        raw = self.original(frame, *args, **kwargs)
        if getattr(self.board, "_apk_artwork_filter_busy", False):
            keys = self._provisional[1] if self._provisional is not None and frame is self._provisional[0] else set()
            return [badge for badge in raw if candidate_key(badge) not in keys]
        token = self._token(frame)
        if frame is self.frame and self.initial is not None and token != self.initial:
            # Restoration after mutation cannot revive a registered decision.
            self.initial = self.decision = None
        if token is not None and token == self.initial and self.decision is not None:
            decision = deepcopy(self.decision)
        else:
            decision = self._decide(frame)
            if token is not None and token == self.initial and self._token(frame) == token:
                self.decision = deepcopy(decision)
        keys = set(decision["excluded"])
        return [badge for badge in raw if candidate_key(badge) not in keys]


def install(board=None):
    if board is None:
        import mobile_board as board
    import mobile_combat_vision as vision
    if not hasattr(board, "_apk_original_badge_candidates"):
        board._apk_original_badge_candidates = board._badge_candidates
    adapter = ArtworkFilter(board, vision, board._apk_original_badge_candidates)
    board._badge_candidates = adapter.candidates
    board._apk_artwork_filter_busy = False
    return adapter
