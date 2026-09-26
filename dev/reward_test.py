# -*- coding: utf-8 -*-
r"""Offline regression for a dark post-match reward page; no real clicks.

Run from the repository root: .venv\Scripts\python.exe dev\reward_test.py
Requires the local, ignored shots/post_match/reward_claim_20260926.png crop.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import main_loop  # noqa: E402

reward_path = ROOT / "shots/post_match/reward_claim_20260926.png"
reward = cv2.imread(str(reward_path))
assert reward is not None and reward.shape == (720, 1280, 3), reward_path
assert float(reward.mean()) < 10 and float(reward.std()) > 8
assert main_loop.post_match_reward_visible(reward)
assert main_loop.post_match_reward_visible(cv2.resize(reward, (1024, 576)))

black = np.zeros_like(reward)
assert not main_loop.post_match_reward_visible(black)

negative_count = 0
annotated_black = None
for path in (ROOT / "shots").rglob("*.png"):
    if "post_match" in path.parts:
        continue
    try:
        frame = cv2.imread(str(path))
    except (FileNotFoundError, PermissionError):
        continue
    if frame is None or frame.shape != reward.shape or float(frame.mean()) >= 10:
        continue
    negative_count += 1
    assert not main_loop.post_match_reward_visible(frame), path
    if annotated_black is None and float(frame.std()) > 8:
        annotated_black = frame
assert negative_count >= 80, negative_count
assert annotated_black is not None


def run_tail(frame, ticks, *, dismiss=True, visible=True, max_rounds=3):
    """Reproduce the real 4/10 position with all window and mouse I/O stubbed."""
    ctl = main_loop.Controller("kards", dry=False, max_rounds=max_rounds,
                               end_turn=False, play=True)
    ctl.hwnd = 123
    ctl.grab_frame = lambda: frame
    ctl.client_to_screen = lambda x, y: (x, y)
    ctl.max_ticks = ticks
    ctl.round_count = 1
    ctl.dismiss = dismiss
    ctl._post_clicks_done = 4
    ctl._post_clicks_left = 6
    ctl._post_click_last = 0
    ctl.blank_streak = main_loop.BLANK_TOLERANCE
    clicks, logs = [], []
    with patch.object(main_loop, "window_is_capturable", return_value=visible), \
         patch.object(main_loop, "foreground_window", return_value=123), \
         patch.object(main_loop.win32gui, "GetWindowText", return_value="test"), \
         patch.object(main_loop, "classify", return_value=(None, {})), \
         patch.object(main_loop, "click",
                      side_effect=lambda x, y: clicks.append((x, y)) or True), \
         patch.object(main_loop, "log", side_effect=logs.append), \
         patch.object(main_loop.time, "sleep"), \
         patch.object(main_loop, "POST_MATCH_CLICK_GAP", 0):
        ctl.run()
    return ctl, clicks, logs


ctl, clicks, logs = run_tail(reward, 6)
assert ctl._post_clicks_done == 10 and ctl._post_clicks_left == 0
assert ctl.blank_streak == 0 and len(clicks) == 6
assert any("识别到暗色领取奖励页" in line for line in logs)

ctl, clicks, logs = run_tail(black, 3)
assert ctl._post_clicks_done == 4 and ctl._post_clicks_left == 6
assert clicks == []
assert any("pause clicks" in line for line in logs)

ctl, clicks, logs = run_tail(annotated_black, 3)
assert ctl._post_clicks_done == 4 and clicks == []

for options in ({"dismiss": False}, {"visible": False}):
    ctl, clicks, logs = run_tail(reward, 3, **options)
    assert ctl._post_clicks_done == 4 and clicks == []

with patch.object(main_loop, "POST_MATCH_DARK_REWARD", False):
    ctl, clicks, logs = run_tail(reward, 3)
    assert ctl._post_clicks_done == 4 and clicks == []

ctl, clicks, logs = run_tail(reward, 6, max_rounds=1)
assert ctl._post_clicks_done == 10 and len(clicks) == 6
assert logs[-1] == "max_rounds reached, stopping"

print(f"post-match reward offline OK: real dark claim frame, {negative_count} "
      "dark negative frames, 4/10 -> 10/10, black/occluded captures pause, "
      "dismiss-only entry, rollback switch, last-match completion")
