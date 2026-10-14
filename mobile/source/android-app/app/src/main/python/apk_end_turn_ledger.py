"""APK-only end-turn outcome accounting. It never chooses or sends an input.

A completed tap remains pending. Confirmation needs independent post-input
frames with a positive opponent-turn label and an explicitly absent end button.
Board/HQ/resource diagnostics do not gate this separate turn-UI proof. Missing
buttons, color changes and the legacy engine counter alone never prove a transition.
"""
from __future__ import annotations

import math


class EndTurnLedger:
    def __init__(self, max_age_ms=3000, timeout_ms=30000,
                 sample_gap_ms=400, stable_span_ms=1000, label_position_tolerance=2):
        self.max_age_ms = max_age_ms
        self.timeout_ms = timeout_ms
        self.sample_gap_ms = sample_gap_ms
        self.stable_span_ms = stable_span_ms
        self.label_position_tolerance = label_position_tolerance
        self.entries = []
        self.pending = None
        self._candidate = None
        self._last_id = self._last_captured = None

    def _reset_samples(self):
        self._candidate = None

    @staticmethod
    def _positive_label_box(label, width=1280, height=720):
        if not isinstance(label, dict) or label.get("present") is not True:
            return None
        box = label.get("box")
        if (not isinstance(box, (list, tuple)) or len(box) != 4 or
                any(type(v) not in (int, float) or not math.isfinite(v) for v in box)):
            return None
        x, y, w, h = box
        if not (x >= 0 and y >= 0 and w > 0 and h > 0 and x + w <= width and y + h <= height):
            return None
        return tuple(box)

    def _finish(self, status, reason, now_ms, frame_ids=None):
        if self.pending is None:
            return []
        entry = self.pending
        entry.update(status=status, reason=reason, resolved_elapsed_ms=now_ms,
                     evidence_frame_ids=list(frame_ids or []))
        self.pending = None
        self._reset_samples()
        return [dict(entry)]

    def register(self, hook_index, input_index, source, dispatched_ms, engine_turn):
        outcomes = self._finish("unconfirmed", "superseded_by_another_end_tap", dispatched_ms)
        self.pending = {"hook_index": hook_index, "input_index": input_index,
                        "status": "pending", "reason": "awaiting_turn_transition",
                        "source_frame_id": source["frame_id"],
                        "source_generation": source["foreground_generation"],
                        "source_width": source["source_width"], "source_height": source["source_height"],
                        "source_hud_layout": source.get("hud_layout", "unknown"),
                        "coordinate_space": source.get("coordinate_space", "normalized_1280x720"),
                        "source_turn": engine_turn, "dispatched_elapsed_ms": dispatched_ms}
        self.entries.append(self.pending)
        self._last_id = source["frame_id"]
        self._last_captured = source["captured_elapsed_ms"]
        return outcomes

    def observe(self, info, now_ms, engine_turn, motion=None):
        entry = self.pending
        if entry is None:
            return []
        if now_ms - entry["dispatched_elapsed_ms"] >= self.timeout_ms:
            return self._finish("unconfirmed", "turn_transition_timeout", now_ms)
        identity = (info.get("foreground_generation"), info.get("source_width"), info.get("source_height"))
        expected = (entry["source_generation"], entry["source_width"], entry["source_height"])
        if identity != expected:
            return self._finish("unconfirmed", "turn_transition_source_changed", now_ms)
        fid, captured = info.get("frame_id"), info.get("captured_elapsed_ms")
        if (not isinstance(fid, int) or not isinstance(captured, (int, float)) or
                fid <= self._last_id or captured <= self._last_captured or
                captured < entry["dispatched_elapsed_ms"] or not 0 <= now_ms - captured <= self.max_age_ms):
            self._reset_samples()
            return []
        self._last_id, self._last_captured = fid, captured
        label = info.get("opponent_turn_label")
        native = entry["coordinate_space"] == "source_pixels"
        label_box = self._positive_label_box(label, entry["source_width"] if native else 1280,
                                             entry["source_height"] if native else 720)
        # Turn UI proves the transition independently of optional board, HQ,
        # resource and generic transition diagnostics. A real choice modal
        # still interrupts the independent-frame evidence.
        recognized = (info.get("state") in (None, "in_game") and
                      not info.get("choice_modal") and
                      label_box is not None and info.get("button") is None and
                      info.get("button_present") is False)
        if not recognized:
            self._reset_samples()
            return []
        # The engine's same-signal turn counter is never a fallback. Opponent
        # actions may move the board after a completed end tap, so motion and
        # source_hud_layout remain diagnostic only for this ledger.
        previous = self._candidate
        # Inspect label position BEFORE ignoring near-duplicate captures. Even
        # an intervening <400 ms contradiction must break the stable pair.
        moved = previous is not None and any(
            abs(a - b) > self.label_position_tolerance * (entry["source_height"] / 720 if native else 1)
            for a, b in zip(label_box, previous["label_box"]))
        if previous is None or moved:
            self._candidate = {"first_ms": captured, "last_ms": captured, "frames": [fid],
                               "label_box": label_box}
            return []
        gap = captured - previous["last_ms"]
        if gap < self.sample_gap_ms:
            # Near-duplicate captures cannot increase the independent frame count.
            return []
        if gap > 5000:
            self._candidate = {"first_ms": captured, "last_ms": captured, "frames": [fid],
                               "label_box": label_box}
            return []
        previous["last_ms"] = captured
        previous["frames"].append(fid)
        if len(previous["frames"]) >= 2 and captured - previous["first_ms"] >= self.stable_span_ms:
            return self._finish("confirmed", "observed_opponent_turn", now_ms, previous["frames"])
        return []

    def finalize(self, now_ms, reason):
        return self._finish("unconfirmed", "session_stopped_before_turn_confirmation:" + str(reason), now_ms)
