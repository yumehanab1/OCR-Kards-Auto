# -*- coding: utf-8 -*-
r"""Offline card-selection regression: no game window, no real clicks.

Run: .venv\Scripts\python.exe dev\choice_test.py [--samples-dir PATH] [--normal-frame PATH]
The ignored samples directory needs choice_two.png, choice_two_sea_battle.png,
choice_two_sea_battle_blocked.png, three_first.png, three_second.png,
three_unit.png and normal.png. These are original 1284x766/767 screenshots
or 1280x720 clients.
Existing shots/ supply real negative frames. No game window is accessed.
"""

from __future__ import annotations

import glob
import os
import sys
import argparse
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from unittest.mock import Mock

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import order_choice
import orders
import turn_engine
import main_loop


def read(path):
    frame = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is not None and frame.shape[:2] in ((766, 1284), (767, 1284)):
        frame = frame[45:765, 2:1282]
    return frame


repo = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--samples-dir", type=Path, default=repo / "shots/choice_samples")
parser.add_argument("--normal-frame", type=Path,
                    default=None,
                    help="Real normal in-game frame for modal recovery tests")
args = parser.parse_args()
samples = [read(str(args.samples_dir / name)) for name in
           ("choice_two.png", "three_first.png", "three_second.png")]
assert all(order_choice.calibrated(f) for f in samples), "缺已确认截图"
two, first_three, second_three = samples
assert [order_choice.detect_count(f)[0] for f in samples] == [2, 3, 3]
blocked_real = read(str(repo / "shots/choice/0926_192524_blocked.png"))
assert order_choice.detect_count(blocked_real)[0] == 2
sea_battle = read(str(args.samples_dir / "choice_two_sea_battle.png"))
sea_blocked = read(str(args.samples_dir / "choice_two_sea_battle_blocked.png"))
assert order_choice.detect_count(sea_battle)[0] == 2
assert order_choice.detect_count(sea_blocked)[0] == 2
for frame, titles in ((first_three, ("蓝天", "薄雾", "狂风")),
                      (second_three, ("雷暴", "热带风暴", "旋风"))):
    matched, seen, _ = order_choice.three_titles_match(frame)
    assert matched is True and seen == titles, (matched, seen)
three_unreadable = first_three.copy()
for x in order_choice.THREE_LEFTS:
    three_unreadable[430:457, x + 8:x + 184] = (205, 205, 205)
assert order_choice.detect_count(three_unreadable)[0] == 3
assert order_choice.three_titles_match(three_unreadable)[0] is None
assert order_choice.changed_since(order_choice.selection_image(first_three),
                                  second_three)
assert order_choice.new_three_set(order_choice.selection_image(first_three),
                                  second_three)
hover_only = first_three.copy()
hover_only[285:505, 324:514] = second_three[285:505, 324:514]
assert not order_choice.new_three_set(order_choice.selection_image(first_three),
                                      hover_only)

negatives = 0
for path in glob.glob(str(repo / "shots/**/*.png"), recursive=True):
    if ("annotated" in path
            or Path(path).resolve().parent in (
                args.samples_dir.resolve(), (repo / "shots/choice").resolve())):
        continue
    try:
        frame = read(path)
    except (FileNotFoundError, PermissionError):
        # Existing debug frame retention may prune a file after glob listed it.
        continue
    if order_choice.calibrated(frame):
        negatives += 1
        assert order_choice.detect_count(frame)[0] is None, f"误识别选牌:{path}"
assert negatives >= 100, f"真实负帧不足:{negatives}"

orders.load()
marked = [name for name in orders._CARDS if orders.choice_spec(name)]
unmarked = [name for name in orders._CARDS if orders.is_choice_card(name)
            and not orders.choice_spec(name)]
assert len(marked) == 27 and len(unmarked) == 16
assert all(orders.is_choice(name) and not orders.is_blacklisted(name)
           for name in marked)
assert all(orders.is_blacklisted(name) and not orders.playable("order", name)
           for name in unmarked)
assert all(not orders.playable("infantry", name) for name in unmarked)
assert orders.choice_spec("呼叫殖民地")["rows"] == "1"
assert order_choice.CHOICE_POINTS == {"1": (531, 375), "3": (750, 375)}
assert order_choice.THREE_POINTS == {"1": (420, 375), "2": (640, 375),
                                     "3": (859, 375)}

normal = read(str(args.normal_frame or args.samples_dir / "normal.png"))
assert order_choice.calibrated(normal)
assert order_choice.detect_count(normal)[0] is None
clicked = []
flow = order_choice.SelectionFlow("呼叫殖民地", now=0.0)
three_ok = lambda _frame: (True, ("蓝天", "薄雾", "狂风"), "test")


def tick(frame, at):
    return flow.tick(frame, normal_visible=lambda _: True,
                     click_client=lambda x, y: clicked.append((x, y)) or True,
                     can_act=lambda: True,
                     read_three_titles=three_ok,
                     now=at, log=lambda _: None)[0]


assert tick(two, 0.1) == "waiting"
assert tick(two, 0.11) == "waiting" and not clicked  # rapid polling is not confirmation
assert tick(two, 0.3) == "waiting" and not clicked
assert tick(two, 0.7) == "clicked" and clicked == [(531, 375)]
assert tick(two, 0.8) == "waiting" and clicked == [(531, 375)]

# Forecast/development may produce another set after the first choice.
old_choice = orders.random.choice
try:
    draws = iter(("2", "3"))
    orders.random.choice = lambda sides: next(draws)
    assert tick(first_three, 1.6) == "waiting"
    assert tick(first_three, 1.8) == "waiting"
    assert tick(first_three, 2.0) == "clicked"
    assert clicked[-1] == (640, 375)
    assert tick(first_three, 2.1) == "waiting"  # no duplicate on same screen
    assert tick(second_three, 3.0) == "waiting"
    assert tick(second_three, 3.2) == "waiting"
    assert tick(second_three, 3.4) == "clicked"
    assert clicked[-1] == (859, 375)
finally:
    orders.random.choice = old_choice

assert tick(normal, 3.5) == "waiting"
assert tick(normal, 6.1) == "complete"
assert len(clicked) == 3

# The 21:36 unit-triggered menu is a separate real scene from the two weather
# samples. Exercise actual OCR, the recorded middle pick, and board recovery.
unit_real = read(str(args.samples_dir / "three_unit.png"))
assert order_choice.detect_count(unit_real)[0] == 3
assert order_choice.three_titles_match(unit_real)[:2] == (
    True, ("死神降临", "团结就是力量", "我们能做到！"))
unit_real_flow = order_choice.SelectionFlow("", now=0)
unit_real_click = Mock(return_value=True)
with patch.object(orders.random, "choice", return_value="2"):
    for frame, at, expected in ((unit_real, 0.1, "waiting"),
                                (unit_real, 0.3, "waiting"),
                                (unit_real, 0.5, "clicked"),
                                (unit_real, 1.5, "waiting"),
                                (normal, 1.8, "waiting"),
                                (normal, 4.4, "complete")):
        result, _ = unit_real_flow.tick(
            frame, normal_visible=lambda _: True, can_act=lambda: True,
            click_client=unit_real_click, now=at, log=lambda _: None)
        assert result == expected, (at, result)
unit_real_click.assert_called_once_with(640, 375)

# Real two-card failures resolve from stable geometry without any OCR.
two_blank = blocked_real.copy()
for x in order_choice.CARD_LEFTS:
    two_blank[430:457, x + 8:x + 184] = (205, 205, 205)
assert order_choice.detect_count(two_blank)[0] == 2

def two_tick(flow, frame, at, click, can_act=lambda: True):
    return flow.tick(frame, normal_visible=lambda _: True,
                     click_client=click, can_act=can_act,
                     now=at, log=lambda _: None)[0]

with patch.object(order_choice, "_title_strips",
                  side_effect=AssertionError("two-card flow must not OCR")):
    for frame, name, point in ((blocked_real, "呼叫殖民地", (531, 375)),
                               (two_blank, "呼叫殖民地", (531, 375)),
                               (sea_battle, "海战", (750, 375)),
                               (sea_blocked, "海战", (750, 375))):
        real_flow = order_choice.SelectionFlow(name, now=0)
        real_click = Mock(return_value=True)
        for at, expected in ((0.1, "waiting"), (0.11, "waiting"),
                              (0.3, "waiting"), (0.7, "clicked"),
                              (1.6, "waiting"), (3.0, "waiting")):
            assert two_tick(real_flow, frame, at, real_click) == expected
        real_click.assert_called_once_with(*point)
        assert two_tick(real_flow, normal, 3.1, real_click) == "waiting"
        assert two_tick(real_flow, normal, 5.7, real_click) == "complete"

    # Check every marked side and every unmarked card, regardless of title.
    for name in marked:
        marked_flow = order_choice.SelectionFlow(name, now=0)
        marked_click = Mock(return_value=True)
        assert two_tick(marked_flow, two_blank, 0.1, marked_click) == "waiting"
        assert two_tick(marked_flow, two_blank, 0.7, marked_click) == "clicked"
        marked_click.assert_called_once_with(
            *order_choice.CHOICE_POINTS[orders.choice_spec(name)["rows"]])
    for name in ["", "未知卡名", *unmarked]:
        refused_click = Mock()
        assert two_tick(order_choice.SelectionFlow(name, now=0), sea_blocked,
                        0.1, refused_click) == "blocked"
        refused_click.assert_not_called()

# Slow cumulative motion must reset the stable interval. Alter card art only,
# preserving real panel/border evidence and small adjacent-frame differences.
animation = []
for delta in (0, 12, 24, 36, 48):
    frame = sea_blocked.copy()
    for x in order_choice.CARD_LEFTS:
        art = frame[290:420, x + 10:x + 180]
        art[:] = np.clip(art.astype(np.int16) + delta, 0, 255).astype(np.uint8)
    assert order_choice.detect_count(frame)[0] == 2
    animation.append(frame)
moving = order_choice.SelectionFlow("海战", now=0)
moving_click = Mock(return_value=True)
for frame, at in zip(animation, (0.1, 0.25, 0.4, 0.55, 0.7)):
    assert two_tick(moving, frame, at, moving_click) == "waiting"
moving_click.assert_not_called()
assert two_tick(moving, animation[-1], 1.3, moving_click) == "clicked"
moving_click.assert_called_once_with(750, 375)

unsettled = order_choice.SelectionFlow("海战", now=0)
unsettled_click = Mock()
for i, at in enumerate((0.1, 0.4, 0.7, 1.0, 2.0, 3.0, 4.0, 5.0, 6.1)):
    expected = "blocked" if at == 6.1 else "waiting"
    assert two_tick(unsettled, animation[0 if i % 2 else -1], at,
                    unsettled_click) == expected
unsettled_click.assert_not_called()

# A second two-card menu cannot reuse the first menu's rule after a board gap.
followup = order_choice.SelectionFlow("海战", now=0)
followup_click = Mock(return_value=True)
for frame, at, expected in ((sea_blocked, 0.1, "waiting"),
                            (sea_blocked, 0.7, "clicked"),
                            (normal, 1.0, "waiting"),
                            (normal, 1.4, "waiting"),
                            (sea_blocked, 1.6, "waiting"),
                            (sea_blocked, 2.2, "blocked")):
    assert two_tick(followup, frame, at, followup_click) == expected
followup_click.assert_called_once_with(750, 375)

# Missing panels, wrong resolution, ambiguity and loss of foreground stop.
for bad_frame in (np.zeros_like(two), two[:600]):
    bad_flow, bad_click = order_choice.SelectionFlow("海战", now=0), Mock()
    assert two_tick(bad_flow, bad_frame, 0.1, bad_click) == "waiting"
    assert two_tick(bad_flow, bad_frame, 6.1, bad_click) == "blocked"
    bad_click.assert_not_called()
with patch.object(order_choice, "detect_count", return_value=(-1, "ambiguous")):
    bad_click = Mock()
    assert two_tick(order_choice.SelectionFlow("海战", now=0), sea_blocked,
                    0.1, bad_click) == "blocked"
    bad_click.assert_not_called()
focus_flow, focus_click = order_choice.SelectionFlow("海战", now=0), Mock()
assert two_tick(focus_flow, sea_blocked, 0.1, focus_click,
                can_act=lambda: False) == "waiting"
assert two_tick(focus_flow, sea_blocked, 0.2, focus_click) == "waiting"
assert two_tick(focus_flow, sea_blocked, 0.8, focus_click,
                can_act=Mock(side_effect=(True, False))) == "waiting"
focus_click.assert_not_called()

hover_guard = order_choice.SelectionFlow("", now=0)
hover_click = Mock(return_value=True)
def hover_tick(frame, at):
    return hover_guard.tick(frame, normal_visible=lambda _: False,
                            click_client=hover_click, can_act=lambda: True,
                            read_three_titles=three_ok,
                            now=at, log=lambda _: None)[0]
assert hover_tick(first_three, 0.1) == "waiting"
assert hover_tick(first_three, 0.3) == "waiting"
assert hover_tick(first_three, 0.5) == "clicked"
assert hover_tick(hover_only, 1.2) == "blocked"
hover_click.assert_called_once()

# The same three choices can recur after an observed board gap. It is a new
# selection, but a single missing frame must never release the click guard.
same = order_choice.SelectionFlow("", now=0)
same_clicks = []
def same_tick(frame, at):
    return same.tick(frame, normal_visible=lambda _: True,
                     click_client=lambda x, y: same_clicks.append((x, y)) or True,
                     can_act=lambda: True, read_three_titles=three_ok,
                     now=at, log=lambda _: None)[0]
assert same_tick(first_three, 0.1) == "waiting"
assert same_tick(first_three, 0.3) == "waiting"
assert same_tick(first_three, 0.5) == "clicked"
assert same_tick(normal, 0.6) == "waiting"
assert same_tick(first_three, 1.2) == "waiting"
assert len(same_clicks) == 1
assert same_tick(normal, 1.3) == "waiting"
assert same_tick(normal, 1.7) == "waiting"
assert same_tick(first_three, 1.8) == "waiting"
assert same_tick(first_three, 2.0) == "waiting"
assert same_tick(first_three, 2.2) == "clicked"
assert len(same_clicks) == 2

# A transient option set is not stable merely because its card count matches.
transient = order_choice.SelectionFlow("", now=0)
transient_clicks = []
def transient_tick(frame, at):
    return transient.tick(frame, normal_visible=lambda _: False,
                          click_client=lambda x, y: transient_clicks.append((x, y)) or True,
                          can_act=lambda: True, read_three_titles=three_ok,
                          now=at, log=lambda _: None)[0]
assert transient_tick(first_three, 0.1) == "waiting"
assert transient_tick(second_three, 0.3) == "waiting" and not transient_clicks
assert transient_tick(second_three, 0.5) == "waiting"
assert transient_tick(second_three, 0.7) == "clicked"

# Three-card reveal retains its title gate. A random side is drawn only after all three known names agree twice.
three_retry = order_choice.SelectionFlow("测试开发", now=0)
three_click = Mock(return_value=True)
three_draw = Mock(return_value="2")
def three_retry_tick(at, result):
    return three_retry.tick(
        first_three, normal_visible=lambda _: False,
        click_client=three_click, can_act=lambda: True,
        read_three_titles=lambda _: result, now=at, log=lambda _: None)[0]
with patch.object(orders.random, "choice", three_draw):
    assert three_retry_tick(0.1, (None, ("", "", ""), "blank")) == "waiting"
    assert three_retry_tick(0.3, (None, ("", "", ""), "blank")) == "waiting"
    assert three_retry_tick(1.0, (True, ("蓝天", "薄雾", "狂风"), "first")) == "waiting"
    assert three_retry_tick(1.3, (True, ("雷暴", "热带风暴", "旋风"), "changed")) == "waiting"
    three_draw.assert_not_called()
    three_click.assert_not_called()
    assert three_retry_tick(1.6, (True, ("雷暴", "热带风暴", "旋风"), "stable")) == "clicked"
    three_draw.assert_called_once_with(("1", "2", "3"))
    three_click.assert_called_once_with(640, 375)

for title_result, deadline in ((None, 6.4), (False, 1.4)):
    three_guard = order_choice.SelectionFlow("测试开发", now=0)
    three_guard_click = Mock(return_value=True)
    def three_guard_tick(at):
        return three_guard.tick(
            first_three, normal_visible=lambda _: False,
            click_client=three_guard_click, can_act=lambda: True,
            read_three_titles=lambda _: (title_result, ("", "", ""), "test"),
            now=at, log=lambda _: None)[0]
    assert three_guard_tick(0.1) == "waiting"
    assert three_guard_tick(0.3) == "waiting"
    assert three_guard_tick(deadline) == "blocked"
    three_guard_click.assert_not_called()

# Individually valid names can still oscillate between OCR reads. Neither a
# valid-but-unconfirmed reading nor an intermittent blank may restart the
# overall confirmation deadline and leave selection waiting indefinitely.
for alternate in ((True, ("雷暴", "热带风暴", "旋风"), "changed"),
                  (None, ("", "", ""), "blank")):
    unstable = order_choice.SelectionFlow("", now=0)
    unstable_click = Mock(return_value=True)
    with patch.object(orders.random, "choice") as unstable_draw:
        for i, at in enumerate((0.1, 0.3, 1.0, 2.0, 3.0, 4.0, 5.0, 6.4)):
            titles = three_ok(None) if i % 2 else alternate
            status, _ = unstable.tick(
                first_three, normal_visible=lambda _: False, can_act=lambda: True,
                click_client=unstable_click, read_three_titles=lambda _: titles,
                now=at, log=lambda _: None)
            assert status == ("blocked" if at == 6.4 else "waiting"), (at, status)
        unstable_click.assert_not_called()
        unstable_draw.assert_not_called()

# Failed mouse input must stop before ordinary play.
guarded = order_choice.SelectionFlow("呼叫殖民地", now=0)
guarded_click = Mock(return_value=False)
assert two_tick(guarded, two, 0.1, guarded_click) == "waiting"
assert two_tick(guarded, two, 0.7, guarded_click) == "blocked"
guarded_click.assert_called_once_with(531, 375)

# A unit or triggered effect can open the stage from the current screen,
# without any previous card name. The three-card rule still supplies a pick.
assert orders.selection_pick("", 2, 0) == ""
old_choice = orders.random.choice
try:
    orders.random.choice = lambda sides: sides[1]
    assert orders.selection_pick("", 3, 0) == "2"
finally:
    orders.random.choice = old_choice

external = turn_engine.TurnEngine.__new__(turn_engine.TurnEngine)
external.hwnd = 1
external.phase = "play"
external.log = lambda _: None
external._dump_frame = lambda *a, **kw: None
external_points = []
old_capture = turn_engine.capture_client_bgr
old_window = turn_engine.win.window_is_capturable
old_screen = turn_engine.client_to_screen
old_click = turn_engine.click
try:
    turn_engine.capture_client_bgr = lambda _: first_three
    turn_engine.win.window_is_capturable = lambda *a, **kw: True
    turn_engine.client_to_screen = lambda _, x, y: (x, y)
    turn_engine.click = lambda x, y, jitter=0: external_points.append((x, y)) or True
    orders.random.choice = lambda sides: sides[1]
    assert external.think() == "selection_waiting"
    assert external.phase == "selection_pending"
    assert external.selection_pending["external"] is True
    with patch.object(order_choice.time, "monotonic",
                      return_value=external.selection_flow.started_at + 0.3):
        assert external.think() == "selection_waiting"
    with patch.object(order_choice.time, "monotonic",
                      return_value=external.selection_flow.started_at + 0.5):
        assert external.think() == "selection_clicked"
    assert external_points == [(640, 375)]
    external._end_turn_visible = lambda _: True
    turn_engine.capture_client_bgr = lambda _: normal
    at = external.selection_flow.started_at + 3
    with patch.object(order_choice.time, "monotonic", return_value=at):
        assert external.think() == "selection_waiting"
    with patch.object(order_choice.time, "monotonic", return_value=at + 3):
        assert external.think() == "selection_resolved"
    assert external.phase == "play" and external.selection_pending is None
finally:
    orders.random.choice = old_choice
    turn_engine.capture_client_bgr = old_capture
    turn_engine.win.window_is_capturable = old_window
    turn_engine.client_to_screen = old_screen
    turn_engine.click = old_click

# Attack/move effects interrupt at the current popup before reading the field
# or continuing the next ordinary phase. Resuming must preserve that phase.
for phase in ("attack", "move_front"):
    action_engine = turn_engine.TurnEngine.__new__(turn_engine.TurnEngine)
    action_engine.hwnd = 1
    action_engine.phase = phase
    action_engine.log = lambda _: None
    action_engine._dump_frame = lambda *a, **kw: None
    action_engine._end_turn_visible = lambda _: True
    action_engine.attacked_this_turn = action_engine.moved_this_turn = 0
    action_engine._field = Mock(side_effect=AssertionError("popup read as battlefield"))
    action_engine._resync_kredits_after_actions = Mock(
        side_effect=AssertionError("popup read as kredits"))
    action_engine.attacker = SimpleNamespace(landed=0)
    action_engine.front_mover = SimpleNamespace(moved=0, refused=0)
    screen = [normal]
    def run_action(hard_stop):
        screen[0] = first_three
        assert hard_stop()
        return (1, 0)
    action_engine.attacker.run_turn = run_action
    action_engine.front_mover.run_turn = run_action
    with patch.object(turn_engine, "capture_client_bgr", side_effect=lambda _: screen[0]):
        assert action_engine.think() == "selection_pending"
    assert action_engine.selection_pending["external"]
    assert action_engine.selection_resume_phase == phase
    action_engine._field.assert_not_called()
    action_engine._resync_kredits_after_actions.assert_not_called()
    action_engine.selection_flow = SimpleNamespace(tick=lambda *a, **kw: ("complete", "test"))
    with patch.object(turn_engine, "capture_client_bgr", return_value=normal):
        assert action_engine.think() == "selection_resolved"
    assert action_engine.phase == phase

# A deployed unit's selection must defer accounting until the popup closes.
unit = turn_engine.TurnEngine.__new__(turn_engine.TurnEngine)
unit.hwnd = 1
unit.phase = "play"
unit.lazy_scan = False
unit.debug = False
unit.cards = [{"name": "测试单位", "type": "infantry", "cost": 2, "x": 500, "i": 0}]
unit.failed_x, unit.attempted_x = set(), set()
unit._blacklist_warned = False
unit.kredits_left = 4
unit.deployed_this_turn = 0
unit.log = lambda _: None
unit._dump_frame = unit._dump_drag_frame = lambda *a, **kw: None
unit._end_turn_visible = unit._budget = lambda *a, **kw: True
unit._support_line_full = unit._deploy_capped = lambda: False
unit._field = Mock(return_value={})
unit._judge_deploy = Mock(return_value=(True, "test", False))
unit.afford = SimpleNamespace(note_deploy_ok=Mock())
unit.memory = SimpleNamespace(note_played=Mock())
unit.scanner = SimpleNamespace(hold=0)
screen = [normal]
def deploy_unit(*a, **kw):
    screen[0] = first_three
    return True
with patch.object(turn_engine, "capture_client_bgr", side_effect=lambda _: screen[0]), \
     patch.object(turn_engine, "deploy_candidates", return_value=[(600, 520)]), \
     patch.object(turn_engine, "drag_deploy", side_effect=deploy_unit), \
     patch.object(turn_engine.time, "sleep"):
    assert unit.think() == "selection_pending"
unit._judge_deploy.assert_not_called()
unit.memory.note_played.assert_not_called()
assert unit.kredits_left == 2 and unit.deployed_this_turn == 0
assert unit.selection_pending["deferred_deploy"]["target"]["i"] == 0
unit.selection_flow = SimpleNamespace(tick=lambda *a, **kw: ("complete", "test"))
with patch.object(turn_engine, "capture_client_bgr", return_value=normal):
    assert unit.think() == "selection_resolved"
unit._judge_deploy.assert_called_once()
unit.memory.note_played.assert_called_once_with(0)
assert unit.deployed_this_turn == 1 and unit.kredits_left == 2
assert unit.phase == "play" and unit.cards == []

# Missing popup blocks a choice card; an engine block stays latched.
engine = turn_engine.TurnEngine.__new__(turn_engine.TurnEngine)
engine.hwnd = 1
engine.phase = "selection_pending"
engine.selection_pending = {"name": "呼叫殖民地", "target": {"i": 0},
                            "cost": 4, "kredits_before": 4}
engine.selection_flow = order_choice.SelectionFlow("呼叫殖民地", now=-100.0)
engine.log = lambda _: None
engine._dump_frame = lambda *a, **kw: None
old_capture = turn_engine.capture_client_bgr
old_window = turn_engine.win.window_is_capturable
try:
    turn_engine.capture_client_bgr = lambda _: normal
    turn_engine.win.window_is_capturable = lambda *a, **kw: True
    assert engine.think() == "selection_blocked"
    assert engine.phase == "selection_blocked"
    assert engine.think() == "selection_blocked"
finally:
    turn_engine.capture_client_bgr = old_capture
    turn_engine.win.window_is_capturable = old_window

# The outer page classifier may return unknown throughout the modal. Neither
# dismissal nor normal page handlers may steal control from card selection.
for frame, phase in [(first_three, "attack"), (normal, "selection_pending")]:
    controller = main_loop.Controller("kards", dry=False, max_rounds=0,
                                      end_turn=False, play=True)
    controller.max_ticks = 1
    controller.hwnd = 1
    controller.turn_engine = SimpleNamespace(phase=phase)
    controller.grab_frame = lambda: frame
    controller.handle_in_game = Mock()
    controller.handle_state = Mock()
    # A live choice stage is never entered while post-match dismissal is
    # active; keep this fixture aligned with that lifecycle invariant.
    controller.dismiss = False
    controller.tick_dismiss = Mock()
    with patch.object(main_loop, "window_is_capturable", return_value=True), \
         patch.object(main_loop, "classify", return_value=(None, {})), \
         patch.object(main_loop.time, "sleep"), patch.object(main_loop, "log"):
        controller.run()
    controller.handle_in_game.assert_called_once()
    controller.handle_state.assert_not_called()
    controller.tick_dismiss.assert_not_called()

with patch.object(order_choice, "ENABLE_SELECTION_STAGE", False):
    assert not orders.is_choice("呼叫殖民地")
    assert not any(orders.is_three_order(name) for name in orders._CARDS)
    disabled_click = Mock()
    disabled = order_choice.SelectionFlow("", now=0)
    assert disabled.tick(first_three, normal_visible=lambda _: True,
                         click_client=disabled_click, can_act=lambda: True,
                         now=1, log=lambda _: None)[0] == "blocked"
    disabled_click.assert_not_called()

print(f"selection offline OK: 2 and 3-card screenshots, {negatives} negative"
      " frames, consecutive menus, unit/action triggers, unknown-page routing and stop path")
