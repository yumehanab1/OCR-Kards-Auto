"""Offline Phase 2 checks: python/python.exe -B dev/emu_worker_test.py -v."""
from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
import uuid
from unittest.mock import Mock, patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.dont_write_bytecode = True


def mobile_inventory():
    return {str(p.relative_to(ROOT)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in (ROOT / "mobile").rglob("*") if p.is_file()}


BEFORE_IMPORT = mobile_inventory()
import make_release
import emu_vision
import emu_worker
from emu_vision import EmuVision, ActionPlan, ScreenObservation, frame_motion, load_mobile_modules
from emu_worker import EmuWorker, WorkerConfig


@contextlib.contextmanager
def test_directory():
    # Python 3.14's Windows mode=0700 temp directories exclude the sandbox's
    # restricted token. New test directories inherit the temp parent's ACL.
    directory = Path(tempfile.gettempdir()) / ("kards-emu-test-" + uuid.uuid4().hex)
    directory.mkdir()
    try:
        yield str(directory)
    finally:
        # Only outputs beneath this newly created test directory.
        for child in sorted(directory.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if child.is_dir():
                child.rmdir()
            else:
                child.unlink()
        directory.rmdir()


def text(value, x, y, w=100, h=24):
    return ((x-w//2, y-h//2, x+w//2, y+h//2), value, .99)


class RuntimePackagingTests(unittest.TestCase):
    def test_packaged_runtime_loads_templates_without_mobile(self):
        files = list(make_release.iter_emu_runtime_files(str(ROOT)))
        self.assertTrue(files)
        targets = [rel for _, rel in files]
        self.assertEqual(len(targets), len(set(targets)))
        for full, rel in files:
            self.assertTrue(Path(full).is_file(), full)
            self.assertTrue(rel.startswith("src/emu_runtime/"), rel)
            self.assertNotIn("/mobile/", rel)
            self.assertNotIn("__pycache__", Path(rel).parts)
            self.assertFalse(rel.endswith(("_test.py", ".pyc", ".pyo") + make_release.SKIP_SUFFIXES), rel)
        with test_directory() as tmp:
            root = Path(tmp)
            for full, rel in files:
                destination = root / rel
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(full, destination)
            self.assertFalse((root / "mobile").exists())
            self.assertEqual(emu_vision.runtime_root(root), root / "src/emu_runtime")
            vision = EmuVision(root=root, load_core=False)
            self.assertEqual(set(vision.templates), {
                "end_turn_btn", "end_turn_btn_white",
                "victory_btn", "defeat_btn", "defeat_banner", "end_turn_btn_110"})
            for color, gray, roi in vision.templates.values():
                self.assertGreater(color.size, 0)
                self.assertEqual(color.shape[:2], gray.shape)
                self.assertEqual(len(roi), 4)
            self.assertFalse((root / "mobile").exists())

    def test_runtime_root_missing_and_development_precedence(self):
        with test_directory() as tmp:
            root = Path(tmp)
            with self.assertRaises(FileNotFoundError) as error:
                emu_vision.runtime_root(root)
            self.assertEqual(str(error.exception), f"Emulator vision runtime not found under {root}")
            packaged = root / "src/emu_runtime"
            development = root / "mobile/source/android-app/app/src/main"
            (packaged / "assets/mobile-core").mkdir(parents=True)
            development.mkdir(parents=True)
            self.assertEqual(emu_vision.runtime_root(root), packaged)
            (development / "assets/mobile-core").mkdir(parents=True)
            self.assertEqual(emu_vision.runtime_root(root), development)
        self.assertEqual(emu_vision.runtime_root(), ROOT / "mobile/source/android-app/app/src/main")

    def test_runtime_iterator_filters_nested_sources(self):
        with test_directory() as tmp:
            main = Path(tmp) / "mobile/source/android-app/app/src/main"
            keep = {"python/z.py", "python/nested/a.py",
                    "assets/mobile-core/src/reader.py", "assets/mobile-core/config/data.json",
                    "assets/match-entry/defeat_banner.png"}
            excluded = {"python/notes.txt", "python/reader_test.py",
                        "python/__pycache__/hidden.py", "python/nested/a.pyc",
                        "assets/mobile-core/src/reader_test.py",
                        "assets/mobile-core/__pycache__/hidden.json",
                        "assets/mobile-core/src/reader.pyc", "assets/mobile-core/src/reader.pyo"}
            excluded.update("assets/mobile-core/config/data.json" + suffix
                            for suffix in make_release.SKIP_SUFFIXES)
            for rel in keep | excluded:
                path = main / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fixture")
            files = list(make_release.iter_emu_runtime_files(tmp))
            self.assertEqual({rel for _, rel in files}, {"src/emu_runtime/" + rel for rel in keep})
            self.assertEqual(files, list(make_release.iter_emu_runtime_files(tmp)))


class MenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Independent synthetic OCR fixtures reuse identical background pixels.
        cls.vision = EmuVision(load_core=False, ocr_cache_ttl=0)

    def classify(self, entries, mode="training", deck="", orange=()):
        frame = np.full((720, 1280, 3), 35, np.uint8)
        for e in entries:
            if e[1] in orange:
                x0, y0, x1, y1 = e[0]
                frame[y0:y1, x0:x1] = (0, 140, 255)
        self.vision.ocr_fn = lambda f: entries
        return self.vision.classify_screen(frame, target_mode=mode, deck_name=deck)

    def test_menu_states(self):
        cases = [
            ([text("每日登录奖励", 640, 100), text("领取", 640, 540)], "login_reward", (640, 600)),
            ([text("每日登录奖励", 640, 100), text("领取", 640, 620)], "login_reward", (640, 655)),
            ([text("开始", 100, 240), text("商店", 100, 330)], "home", (100, 240)),
            ([text("正在寻找对手", 640, 250)], "queueing", None),
            ([text("已发现对手", 640, 250)], "queueing", None),
            ([text("取消", 640, 500)], "queueing", None),
            ([text("选择要替换的卡牌", 640, 100)], "mulligan", (640, 648)),
            ([text("确认", 640, 650)], "mulligan", (640, 650)),
            ([text("胜利", 640, 350), text("继续", 640, 660)], "victory", (640, 660)),
            ([text("失败", 640, 350)], "defeat", (640, 665)),
            ([text("查看战场", 640, 350)], "defeat", (640, 665)),
            ([text("断开连接", 640, 200), text("重新连接", 640, 420)], "disconnected", (640, 420)),
            ([text("Reconnect", 640, 420)], "disconnected", (640, 420)),
            ([text("断开连接", 640, 200)], "disconnected", (640, 402)),
            ([text("完成所有入伍任务", 640, 350)], "task_popup", (640, 665)),
            ([text("任务", 640, 100), text("战争经济", 640, 350)], "task_popup", (640, 665)),
            ([text("增援", 640, 350)], "task_popup", (640, 665)),
            ([text("关闭", 1000, 650)], "promo_popup", (1000, 650)),
            ([text("轻触任意位置", 640, 650)], "promo_popup", (640, 665)),
            ([text("选择目标", 640, 300)], "target_selection", None),
            ([text("陌生页面", 640, 300)], "unknown", None),
        ]
        for entries, state, target in cases:
            with self.subTest(state=state, entries=entries):
                result = self.classify(entries)
                self.assertEqual((result.state, result.target), (state, target))
                self.assertEqual(result.ocr_texts, [e[1] for e in entries])

    def test_live_network_error_restart(self):
        result = self.classify([
            text("NETWORKERROR", 640, 250),
            text("请检查网络连接并选择“重启”。", 640, 320),
            ((604, 380, 677, 424), "重启", .99),
        ])
        self.assertEqual((result.state, result.target), ("disconnected", (640, 402)))

    def tabs(self, detail=False):
        entries = [text("对战模式", 180, 250), text("训练模式", 180, 350)]
        if detail:
            entries += [text("开始", 1080, 610), text("休闲", 930, 510), text("排位", 1110, 510)]
        return entries

    def test_login_reward_skips_claimed_and_prefers_exact(self):
        header = text("每日登录奖励", 640, 100)
        claimed = [text("已领取", x, 540) for x in (200, 350, 500, 650, 800)]
        result = self.classify([header, *claimed, text("点击领取", 900, 540), text("领取", 1050, 540)])
        self.assertEqual((result.state, result.target), ("login_reward", (1050, 600)))
        self.assertEqual(self.classify([header, *claimed]).target, (640, 655))
        self.assertEqual(self.classify([header, *claimed, text("领取", 1050, 600)]).target, (640, 655))

    def test_deck_list(self):
        entries = self.tabs() + [text("日本初始", 624, 416), text("德国初始", 840, 416)]
        result = self.classify(entries, orange=("对战模式",))
        self.assertEqual((result.state, result.target), ("deck_list", (180, 350)))
        self.assertEqual(self.classify(entries, orange=("训练模式",)).target, (624, 310))
        self.assertEqual(self.classify(entries, deck="德国初始", orange=("训练模式",)).target, (840, 336))
        self.assertEqual(self.classify(self.tabs(), orange=("训练模式",)).target, (625, 290))
        self.assertEqual(self.classify(entries, "casual", orange=("训练模式",)).target, (180, 250))
        self.assertEqual(self.classify(entries, "ranked", orange=("对战模式",)).target, (624, 310))

    def test_deck_detail_modes(self):
        entries = self.tabs(True)
        for mode in ("training", "casual", "ranked"):
            with self.subTest(mode=mode):
                wrong = "对战模式" if mode == "training" else "训练模式"
                expected = (180, 350) if mode == "training" else (180, 250)
                result = self.classify(entries, mode, orange=(wrong, "排位"))
                self.assertEqual((result.state, result.target), ("deck_detail", expected))
        self.assertEqual(self.classify(entries, orange=("训练模式", "排位")).target, (1080, 610))
        self.assertEqual(self.classify(entries, "casual", orange=("对战模式", "排位")).target, (930, 510))
        self.assertEqual(self.classify(entries, "casual", orange=("对战模式", "休闲")).target, (1080, 610))
        self.assertEqual(self.classify(entries, "ranked", orange=("对战模式", "休闲")).target, (1110, 510))
        self.assertEqual(self.classify(entries, "ranked", orange=("对战模式", "排位")).target, (1080, 610))
        self.assertEqual(self.classify(entries, "casual", orange=("对战模式",)).target, (930, 510))
        self.assertIsNone(self.classify(entries[:3], "casual", orange=("对战模式",)).target)

    def test_configured_deck_never_falls_back_or_starts_wrong_detail(self):
        for entries in (self.tabs(), self.tabs() + [text('德国初始', 840, 416)]):
            obs = self.classify(entries, deck='日本初始', orange=('训练模式',))
            self.assertEqual((obs.state, obs.target, obs.reason), ('deck_list', None, 'deck_not_found'))
        for back in ([], [text('返回', 80, 50)]):
            entries = self.tabs(True) + [text('德国初始', 840, 416)] + back
            obs = self.classify(entries, deck='日本初始', orange=('训练模式',))
            self.assertEqual((obs.state, obs.reason), ('deck_detail', 'wrong_deck_selected'))
            self.assertEqual(obs.target, (80, 50) if back else (55, 55))
            entries.append(text('日本初始', 840, 150))
            obs = self.classify(entries, deck='日本初始', orange=('训练模式',))
            self.assertEqual((obs.target, obs.reason), ((1080, 610), 'start_selected_mode'))

    def test_live_reward_card_and_popup(self):
        result = self.classify([text("每日登录奖励", 640, 100), text("已领取", 400, 389),
                                text("领取", 650, 389)])
        self.assertEqual(result.target, (650, 479))
        for value in ("轻触领取", "轻触继续", "轻触任意位置", "点击任意位置", "点击继续"):
            self.assertEqual(self.classify([text(value, 640, 650)]).state, "promo_popup")

    def test_ocr_enemy_turn_region(self):
        for x, y in ((1000, 440), (1110, 500), (1200, 590)):
            result = self.classify([text("敌方", x, y)])
            self.assertEqual((result.state, result.reason, result.target),
                             ("opponent_turn", "ocr_opponent_turn", None))
        for x, y in ((999, 500), (1100, 439), (1100, 591), (400, 200)):
            self.assertEqual(self.classify([text("敌方", x, y)]).state, "unknown")

    def test_ocr_end_turn_roi_case_and_priority(self):
        for label in ('结束回合', 'End Turn', 'END TURN', 'end turn'):
            for x, y in ((1100, 500), (980, 420), (980, 620)):
                with self.subTest(label=label, point=(x, y)), \
                        patch.object(self.vision, 'classify_battle', return_value=None):
                    button = text(label, x, y)
                    enemy = text('敌方', 1150, 510)
                    result = self.classify([button, enemy])
                    self.assertEqual((result.state, result.reason, result.target),
                                     ('own_turn', 'ocr_end_turn', (x, y)))
                    for mulligan in (text('确认', 640, 648), text('选择要替换的卡牌', 640, 100)):
                        self.assertEqual(self.classify([button, enemy, mulligan]).state, 'mulligan')

    def test_ocr_end_turn_outside_roi_never_starts_turn(self):
        for label in ('结束回合', 'End Turn'):
            for x, y in ((979, 500), (1100, 419), (1100, 621), (640, 350)):
                with self.subTest(label=label, point=(x, y)), \
                        patch.object(self.vision, 'classify_battle', return_value=None):
                    self.assertNotEqual(self.classify([text(label, x, y)]).state, 'own_turn')

    def test_fast_path_never_ocr(self):
        self.vision.ocr_fn = lambda f: self.fail("Unexpected OCR")
        self.assertEqual(self.vision.classify_screen(None).reason, "invalid_frame")
        self.assertEqual(self.vision.classify_screen(np.zeros((720, 1280, 3), np.uint8)).state, "blank")
        sentinel = ScreenObservation("own_turn", "test", (1110, 500))
        with patch.object(self.vision, "classify_battle", return_value=sentinel):
            self.assertIs(self.vision.classify_screen(np.ones((1, 1, 3))), sentinel)

    def test_going_second_mulligan_precedes_ocr_enemy_turn(self):
        title = text("选择要替换的卡牌", 640, 100)
        confirm = text("确认", 640, 650)
        for overlay, target in (([title], (640, 648)), ([confirm], (640, 650)),
                                ([title, confirm], (640, 650))):
            with self.subTest(overlay=overlay):
                result = self.classify([text("敌方", 1120, 500), *overlay])
                self.assertEqual((result.state, result.target), ("mulligan", target))

    def test_motion_and_rejection(self):
        a = np.zeros((720, 1280, 3), np.uint8)
        b = a.copy()
        b[500:600, 400:500] = 255
        self.assertEqual(frame_motion(a, a), 0)
        self.assertGreater(frame_motion(a, b), .004)
        self.assertEqual(frame_motion(a, b, (0, 0, 100, 100)), 0)
        self.vision.ocr_fn = lambda f: [text("指挥点数不足，无法使用此卡牌", 300, 70)]
        self.assertTrue(self.vision.detect_insufficient_kredits(b))


class CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vision = EmuVision()

    def test_loader_idempotent_and_no_mobile_writes(self):
        before = sys.modules["win"]
        modules = load_mobile_modules(ROOT)
        self.assertIs(modules.mobile_board, self.vision.core.mobile_board)
        self.assertIs(before, sys.modules["win"])
        kt = importlib.import_module("kredits_templates")
        self.assertFalse(Path(kt.TEMPLATES_DIR).is_relative_to(ROOT / "mobile"))
        kt.build_templates()
        self.assertEqual(BEFORE_IMPORT, mobile_inventory())

    def test_mulligan_precedes_choice_modal(self):
        frame = np.full((720, 1280, 3), 35, np.uint8)
        entries = [text("选择要替换的卡牌", 640, 100), text("确认", 640, 648)]
        with patch.object(self.vision.core.mobile_board, "choice_modal", return_value=(True, {})), \
                patch.object(self.vision, "run_ocr", return_value=entries):
            self.assertIsNone(self.vision.classify_battle(frame))
            result = self.vision.classify_screen(frame)
            self.assertEqual((result.state, result.target), ("mulligan", (640, 648)))
        # The second OCR fixture represents a different screen.
        frame[:] = 70
        with patch.object(self.vision.core.mobile_board, "choice_modal", return_value=(True, {})), \
                patch.object(self.vision, "run_ocr", return_value=[text("卡牌", 640, 200)]):
            result = self.vision.classify_screen(frame)
            self.assertEqual((result.state, result.target, result.ocr_texts),
                             ("choice_modal", (640, 360), ["卡牌"]))

    def test_real_saved_mulligan(self):
        path = ROOT / "logs/pc_emu_b_lobby_20261119_073422/nav-01/read-025.png"
        if not path.exists():
            self.skipTest("Saved mulligan frame not available")
        frame = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        self.assertTrue(self.vision.core.mobile_board.choice_modal(frame)[0])
        self.assertIsNone(self.vision.classify_battle(frame))
        self.assertEqual(self.vision.classify_screen(frame).state, "mulligan")

    def test_battle_fast_paths_without_ocr(self):
        frame = np.full((720, 1280, 3), 35, np.uint8)
        for state in ("victory", "defeat", "own_turn", "opponent_turn"):
            name = {"victory": "victory_btn", "defeat": "defeat_btn",
                    "own_turn": "end_turn_btn"}.get(state)
            with self.subTest(state=state), \
                    patch.object(self.vision, "run_ocr", side_effect=AssertionError("Unexpected OCR")), \
                    patch.object(self.vision, "_match", side_effect=lambda f, n: (.99 if n == name else 0, (1000, 480, 100, 50))), \
                    patch.object(self.vision.core.mobile_end_button, "_stroke_color", return_value=("white", {})), \
                    patch.object(self.vision.core.apk_enemy_turn, "inspect_opponent_turn", return_value={"present": state == "opponent_turn"}):
                self.assertEqual(self.vision.classify_screen(frame).state, state)

    def test_real_saved_frame(self):
        path = ROOT / "logs/pc_emu_b_lobby_20261119_073422/status-readonly-081156/now-1.png"
        if not path.exists():
            self.skipTest("Saved 1.61.27589 frame not available")
        frame = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        result = self.vision.classify_battle(frame)
        self.assertIsNotNone(result)
        self.assertEqual(result.state, "own_turn")
        self.assertEqual(result.reason, "end_turn_btn_110")
        self.assertGreaterEqual(result.evidence["score"], .86)
        hq = self.vision.core.mobile_board.hq_card(frame, "enemy")
        self.assertTrue(hq["geometry_verified"])
        combat = self.vision.plan_combat_action(frame)
        self.assertIsNotNone(combat)
        self.assertIn(combat.kind, ("attack_hq", "attack_unit", "move_front"))
        slot = self.vision.find_open_support_slot(frame)
        self.assertIsNotNone(slot)
        self.assertTrue(350 <= slot[0] <= 930 and 485 <= slot[1] <= 515)
        deploy = self.vision.plan_deploy_action(frame)
        self.assertIsNotNone(deploy)
        self.assertEqual(deploy.path, [deploy.origin, (deploy.origin[0], min(575, deploy.origin[1]-60)), deploy.target])
        next_plan = self.vision.plan_deploy_action(frame, {deploy.key})
        self.assertTrue(next_plan is None or next_plan.key != deploy.key)
        self.assertEqual(BEFORE_IMPORT, mobile_inventory())

    def test_real_saved_end_turn_ocr_fallback(self):
        path = ROOT / 'logs/pc_emu_b_lobby_20261119_073422/status-readonly-081156/now-1.png'
        if not path.exists():
            self.skipTest('Saved 1.61.27589 frame not available')
        frame = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        self.vision.invalidate_ocr_cache()
        with patch.object(self.vision, 'classify_battle', return_value=None):
            result = self.vision.classify_screen(frame)
        self.assertEqual((result.state, result.reason), ('own_turn', 'ocr_end_turn'))
        self.assertGreaterEqual(result.target[0], 980)
        self.assertTrue(420 <= result.target[1] <= 620)

    def test_going_second_mulligan_can_skip_fast_opponent(self):
        frame = np.full((720, 1280, 3), 35, np.uint8)
        entries = [text("敌方", 1120, 500), text("选择要替换的卡牌", 640, 100),
                   text("确认", 640, 648)]
        vision = EmuVision(load_core=False)
        vision.core = Mock()
        vision.core.apk_enemy_turn.inspect_opponent_turn.return_value = {"present": True}
        enemy = vision.core.apk_enemy_turn.inspect_opponent_turn
        with patch.object(vision, "_match", return_value=(0, (1000, 480, 100, 50))), \
                patch.object(vision, "run_ocr", return_value=entries) as ocr:
            result = vision.classify_screen(frame, allow_fast_opponent=False)
            self.assertEqual((result.state, result.target), ("mulligan", (640, 648)))
            enemy.assert_not_called()
            ocr.assert_called_once_with(frame)
            ocr.reset_mock()
            result = vision.classify_screen(frame, allow_fast_opponent=True)
            self.assertEqual((result.state, result.reason), ("opponent_turn", "enemy_turn_label"))
            enemy.assert_called_once_with(frame)
            ocr.assert_not_called()

    def test_full_row_refused_and_incomplete_row_falls_back(self):
        frame = np.full((720, 1280, 3), 30, np.uint8)
        row = dict(hq={"cy": 505}, centers=[640], bounds=[[580, 435, 700, 585]], units=[])
        with patch.object(self.vision.core.apk_deploy_target, "_row", return_value=([], "ok", row)):
            self.assertEqual(self.vision.find_open_support_slot(frame), (784, 505))
            row["units"] = [{}]*4
            self.assertIsNone(self.vision.find_open_support_slot(frame))
        with patch.object(self.vision.core.apk_deploy_target, "_row", return_value=(None, "incomplete", row)), \
                patch.object(self.vision.core.mobile_board, "hq_card", return_value=None), \
                patch.object(self.vision.core.mobile_board, "cards_from_stats", return_value=[]):
            self.assertEqual(self.vision.find_open_support_slot(frame), (855, 505))
        with patch.object(self.vision.core.mobile_board, "actionable_units", side_effect=ValueError("partial")):
            self.assertIsNone(self.vision.plan_combat_action(frame))


class DeployTests(unittest.TestCase):
    def setUp(self):
        self.vision = EmuVision(load_core=False)
        self.assertEqual(self.vision.last_deploy_reason, "")
        self.core = self.vision.core = Mock()
        self.core.apk_deploy_target._row.return_value = None
        self.core.mobile_board.hq_card.return_value = None
        self.core.mobile_board.cards_from_stats.return_value = []
        self.frame = np.full((720, 1280, 3), 35, np.uint8)

    @staticmethod
    def card(cx, cy=505, w=80, h=100):
        return dict(x=cx-w//2, y=cy-h//2, w=w, h=h, cx=cx, cy=cy)

    @staticmethod
    def hand(cx=700, cy=625, **kwargs):
        return dict(cx=cx, cy=cy, kind="unit", state="orange",
                    ad_info=dict(plate_confirmed=True, ad=[1, 2]), **kwargs)

    def test_slot_fallback_on_missing_invalid_or_raising_row(self):
        row = dict(hq=self.card(640), units=[], centers=[640], bounds=[])
        for raw in (None, (None, "incomplete", row), dict(row, hq=None), dict(row, centers=[])):
            with self.subTest(raw=raw):
                self.core.apk_deploy_target._row.return_value = raw
                self.assertEqual(self.vision.find_open_support_slot(self.frame), (855, 505))
        self.core.apk_deploy_target._row.side_effect = ValueError("occluded HQ")
        self.core.mobile_board.hq_card.return_value = self.card(640, cy=530)
        self.assertEqual(self.vision.find_open_support_slot(self.frame), (784, 515))
        self.core.mobile_board.hq_card.assert_called_with(self.frame, "our")
        self.core.mobile_board.cards_from_stats.assert_called_with(self.frame, field=(200, 415, 1120, 595))

    def test_slot_tier_one_preferred_and_full_row_never_falls_back(self):
        row = dict(hq=self.card(640, cy=470), units=[], centers=[640], bounds=[(600, 420, 680, 520)])
        self.core.apk_deploy_target._row.return_value = ([], "ok", row)
        self.assertEqual(self.vision.find_open_support_slot(self.frame), (784, 485))
        row["units"] = [self.card(x) for x in (350, 480, 800, 920)]
        self.assertIsNone(self.vision.find_open_support_slot(self.frame))
        self.core.mobile_board.hq_card.assert_not_called()

    def test_fallback_deduplicates_hq_and_refuses_four_units(self):
        hq = self.card(640, w=120)
        units = [self.card(x) for x in (350, 480, 800)]
        self.core.mobile_board.hq_card.return_value = hq
        for duplicate in (hq.copy(), self.card(710, w=40)):
            with self.subTest(duplicate=duplicate):
                self.core.mobile_board.cards_from_stats.return_value = units + [duplicate]
                self.assertEqual(self.vision.find_open_support_slot(self.frame), (920, 505))
        self.core.mobile_board.cards_from_stats.return_value = units + [self.card(920)]
        self.assertIsNone(self.vision.find_open_support_slot(self.frame))
        self.core.mobile_board.hq_card.return_value = None
        self.assertIsNone(self.vision.find_open_support_slot(self.frame))

    def test_slot_brightness_prefers_dark_then_lowest_bright_candidate(self):
        # Every 90px-high patch has 18 white rows: bright fraction is .20.
        self.frame[460:478] = 220
        self.assertEqual(self.vision.find_open_support_slot(self.frame), (855, 505))
        # Later strict candidate wins over the earlier relaxed candidate.
        self.frame[460:478, 385:465] = 35
        self.assertEqual(self.vision.find_open_support_slot(self.frame), (425, 505))
        self.frame[460:474, 385:465] = 220  # 14/90, still below .28.
        self.assertEqual(self.vision.find_open_support_slot(self.frame), (425, 505))
        self.frame[460:487] = 220  # .30: no safe candidate.
        self.assertIsNone(self.vision.find_open_support_slot(self.frame))

    def test_slot_margin_and_brightness_cutoffs(self):
        # Bounds leave only x=855; x=425 is exactly on the 15px margin.
        row = dict(hq=self.card(640), centers=[640], units=[],
                   bounds=[(350, 450, 410, 560), (480, 450, 800, 560), (900, 450, 940, 560)])
        self.core.apk_deploy_target._row.return_value = ([], "ok", row)
        for fraction, expected in ((.12, (855, 505)), (.28, None)):
            with self.subTest(fraction=fraction):
                patch_pixels = np.full((90*80, 3), 35, np.uint8)
                patch_pixels[:round(fraction*90*80)] = 220
                self.frame[460:550, 815:895] = patch_pixels.reshape(90, 80, 3)
                self.assertEqual(self.vision.find_open_support_slot(self.frame), expected)

    def prepare_hand(self, hand, native=()):
        self.vision.find_open_support_slot = Mock(return_value=(855, 505))
        self.core.mobile_hand.find_hand.return_value = hand
        self.core.native_hand.inspect.return_value = list(native)
        self.core.apk_hand_availability._geometry_plates.return_value = []

    def assert_plan(self, plan, origin, reason):
        self.assertIsNotNone(plan)
        self.assertEqual(plan.kind, "deploy")
        self.assertEqual(plan.origin, origin)
        self.assertEqual(plan.target, (855, 505))
        self.assertEqual(plan.path, [origin, (origin[0], min(575, origin[1]-60)), plan.target])
        self.assertEqual(plan.key, (origin[0]//24, origin[1]//24))
        self.assertEqual(plan.reason, reason)
        self.assertEqual(self.vision.last_deploy_reason, "ok:" + reason)

    def test_deploy_fallback_without_native_and_after_native_error(self):
        self.prepare_hand([self.hand()])
        self.assert_plan(self.vision.plan_deploy_action(self.frame), (725, 650), "deploy_orange_unit_fallback")
        self.core.mobile_hand.find_hand.assert_called_with(
            self.frame, zone=self.core.mobile_hand.DEFAULT_ZONE, want="orange")
        self.core.native_hand.inspect.side_effect = ValueError("native unavailable")
        self.assert_plan(self.vision.plan_deploy_action(self.frame), (725, 650), "deploy_orange_unit_fallback")
        self.core.apk_hand_availability.inspect_unit.assert_not_called()

    def test_corroborated_deploy_preferred_over_earlier_fallback(self):
        native = dict(center=(700, 625), orange=True, operation_numeral=True, suspected_order=False)
        self.prepare_hand([self.hand(500), self.hand()], [native])
        availability = self.core.apk_hand_availability
        availability._safe_grab.return_value = {"point": (730, 650)}
        self.assert_plan(self.vision.plan_deploy_action(self.frame), (730, 650), "deploy_orange_unit")
        availability.inspect_unit.assert_called_once_with(self.frame, self.hand(), _geometry=[])
        availability._safe_grab.assert_called_once_with(self.frame, self.hand(), availability.inspect_unit.return_value)

    def test_fallback_rejects_orders_unconfirmed_nonorange_and_nonunits(self):
        good = self.hand()
        for hand, native in (([dict(good, kind="order")], []),
                             ([dict(good, state="gray")], []),
                             ([dict(good, ad_info={})], []),
                             ([good], [dict(center=(709, 634), suspected_order=True)])):
            with self.subTest(hand=hand, native=native):
                self.prepare_hand(hand, native)
                self.assertIsNone(self.vision.plan_deploy_action(self.frame))
                self.assertEqual(self.vision.last_deploy_reason, "all_hand_filtered(n=1)")
        self.prepare_hand([good], [dict(center=(710, 625), suspected_order=True)])
        self.assert_plan(self.vision.plan_deploy_action(self.frame), (725, 650), "deploy_orange_unit_fallback")

    def test_deploy_reasons_update_and_skipped_candidates(self):
        self.prepare_hand([self.hand()])
        self.assertIsNone(self.vision.plan_deploy_action(self.frame, {(725//24, 650//24)}))
        self.assertEqual(self.vision.last_deploy_reason, "all_skipped")
        self.core.mobile_hand.find_hand.return_value = []
        self.assertIsNone(self.vision.plan_deploy_action(self.frame))
        self.assertEqual(self.vision.last_deploy_reason, "no_orange_hand")
        self.vision.find_open_support_slot.return_value = None
        self.assertIsNone(self.vision.plan_deploy_action(self.frame))
        self.assertEqual(self.vision.last_deploy_reason, "no_open_slot")
        self.vision.find_open_support_slot.side_effect = ValueError("invalid frame")
        self.assertIsNone(self.vision.plan_deploy_action(self.frame))
        self.assertEqual(self.vision.last_deploy_reason, "error:ValueError")

    def test_corroborated_skipped_candidate_reports_all_skipped(self):
        native = dict(center=(700, 625), orange=True, operation_numeral=True, suspected_order=False)
        self.prepare_hand([self.hand()], [native])
        self.core.apk_hand_availability._safe_grab.return_value = {"point": (725, 650)}
        self.assertIsNone(self.vision.plan_deploy_action(self.frame, {(725//24, 650//24)}))
        self.assertEqual(self.vision.last_deploy_reason, "all_skipped")

    def test_fallback_grab_clamping_and_skip_continuation(self):
        self.prepare_hand([self.hand(100, 540), self.hand(1190, 700)])
        self.assert_plan(self.vision.plan_deploy_action(self.frame), (200, 580), "deploy_orange_unit_fallback")
        self.assert_plan(self.vision.plan_deploy_action(self.frame, {(200//24, 580//24)}),
                         (1150, 705), "deploy_orange_unit_fallback")


class OcrCacheTests(unittest.TestCase):
    def test_static_cache_invalidation_and_copy(self):
        for state, entries in (("unknown", []),
                               ("opponent_turn", [text("敌方", 1110, 500)]),
                               ("queueing", [text("正在寻找对手", 640, 250)])):
            with self.subTest(state=state):
                clock = FakeClock()
                ocr = Mock(return_value=entries)
                vision = EmuVision(load_core=False, ocr_fn=ocr, clock_fn=clock)
                frame = np.full((720, 1280, 3), 35, np.uint8)
                first = vision.classify_screen(frame)
                first.ocr_texts.append("caller mutation")
                first.evidence["caller"] = True
                for _ in range(2):
                    clock.sleep(.5)
                    cached = vision.classify_screen(frame.copy())
                    self.assertEqual(cached.state, state)
                    self.assertIsNot(cached, first)
                    self.assertNotIn("caller mutation", cached.ocr_texts)
                    self.assertEqual(cached.evidence, {})
                self.assertEqual(ocr.call_count, 1)
                frame[100:300, 100:300] = 200
                vision.classify_screen(frame)
                self.assertEqual(ocr.call_count, 2)
                clock.sleep(vision.ocr_cache_ttl)
                vision.classify_screen(frame)
                self.assertEqual(ocr.call_count, 3)
                vision.classify_screen(frame, target_mode="casual")
                self.assertEqual(ocr.call_count, 4)
                vision.classify_screen(frame, target_mode="casual", deck_name="new deck")
                self.assertEqual(ocr.call_count, 5)

    def test_battle_transitions_preempt_cache(self):
        for state in ("own_turn", "victory", "defeat"):
            with self.subTest(state=state):
                ocr = Mock(return_value=[])
                vision = EmuVision(load_core=False, ocr_fn=ocr)
                frame = np.full((720, 1280, 3), 35, np.uint8)
                vision.classify_screen(frame)
                result = ScreenObservation(state, "fast template")
                with patch.object(vision, "classify_battle", return_value=result) as battle:
                    self.assertIs(vision.classify_screen(frame), result)
                    battle.assert_called_once_with(frame, allow_opponent_turn=True)
                self.assertEqual(ocr.call_count, 1)
                self.assertIsNone(vision._ocr_cache)

    def test_rapidocr_lazy_thread_limits_and_legacy_fallback(self):
        for threads in (2, 3):
            with self.subTest(threads=threads):
                engine = Mock(return_value=([], None))
                factory = Mock(return_value=engine)
                with patch.dict(sys.modules, {"rapidocr_onnxruntime": Mock(RapidOCR=factory)}):
                    kwargs = {} if threads == 2 else {"ocr_threads": threads}
                    vision = EmuVision(load_core=False, **kwargs)
                    factory.assert_not_called()
                    frame = np.full((720, 1280, 3), 35, np.uint8)
                    vision.run_ocr(frame)
                    vision.run_ocr(frame)
                    factory.assert_called_once_with(intra_op_num_threads=threads, inter_op_num_threads=1)
        factory = Mock(side_effect=[TypeError("legacy constructor"), engine])
        with patch.dict(sys.modules, {"rapidocr_onnxruntime": Mock(RapidOCR=factory)}):
            EmuVision(load_core=False).run_ocr(frame)
        self.assertEqual(factory.call_count, 2)
        self.assertEqual(factory.call_args_list[0].kwargs,
                         dict(intra_op_num_threads=2, inter_op_num_threads=1))
        self.assertEqual(factory.call_args_list[1].kwargs, {})


class FakeClock:
    def __init__(self):
        self.now = 0.
    def __call__(self):
        return self.now
    def sleep(self, seconds):
        self.now += seconds


STATES = ["login_reward", "home", "deck_list", "deck_detail", "mulligan", "own_turn",
          "opponent_turn", "victory", "home"]


class FakeTransport:
    backend_name = "fake"
    def __init__(self, clock):
        self.clock, self.index = clock, 0
        self.inputs, self.packages = [], []
        self.combat = self.deployed = self.closed = False
        self.opponent_reads = 0
        self.foreground, self.launches = True, 0
    def capture_bgr(self):
        if STATES[self.index] == "opponent_turn":
            self.opponent_reads += 1
            if self.opponent_reads >= 3:
                self.index += 1
        value = 30 + self.index*10 + (2 if self.deployed else 0)
        return np.full((720, 1280, 3), value, np.uint8)
    def tap(self, x, y):
        self.inputs.append(("tap", (x, y)))
        if self.index < len(STATES)-1:
            self.index += 1
    def drag(self, points, duration_ms):
        self.inputs.append(("drag", points, duration_ms))
        if len(points) == 2:
            self.combat = True
        else:
            self.deployed = True
    def force_stop_package(self, package):
        self.packages.append(package)
        return True
    def is_kards_foreground(self):
        return self.foreground, "com.android1939.kards"
    def launch_kards(self):
        self.launches += 1
        return True
    def close(self):
        self.closed = True


class FakeVision:
    def __init__(self, transport):
        self.transport = transport
        self.skips = []
    def classify_screen(self, frame, **kwargs):
        state = STATES[self.transport.index]
        return ScreenObservation(state, "fake", (1100, 500))
    classify_battle = classify_screen
    def plan_combat_action(self, frame, skip_actors):
        self.skips.append(set(skip_actors))
        key = ("support", 20, 20)
        if key not in skip_actors:
            return ActionPlan("attack_hq", (500, 500), (640, 180), key=key)
    def plan_deploy_action(self, frame, skip_grabs):
        key = (30, 27)
        if key not in skip_grabs and not self.transport.deployed:
            return ActionPlan("deploy", (730, 650), (850, 500), [(730, 650), (730, 575), (850, 500)], key)
    def detect_insufficient_kredits(self, frame):
        return False
    def enemy_hq(self, frame):
        return (640, 180)


class WorkerTests(unittest.TestCase):
    def make(self, directory, **kwargs):
        clock = FakeClock()
        transport = FakeTransport(clock)
        vision = FakeVision(transport)
        cfg = WorkerConfig("mumu:7", log_file=str(Path(directory)/"worker.log"),
                           status_file=str(Path(directory)/"status.json"), **kwargs)
        worker = EmuWorker(cfg, transport, vision, clock.sleep, clock)
        return worker, transport, vision, clock

    def test_worker_locks_before_status_or_input_and_releases_on_error(self):
        from update_install import acquire_instance_lock, any_emu_worker_running
        with test_directory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            worker, transport, _, _ = self.make(tmp, acquire_lock=True, project_root=tmp)
            status = Path(worker.cfg.status_file)
            status.write_text('owner status', encoding='utf-8')
            with acquire_instance_lock('mumu:7', tmp):
                result = worker.run()
                self.assertTrue(result['last_error'])
                self.assertEqual(status.read_text(encoding='utf-8'), 'owner status')
                self.assertEqual(transport.inputs, [])
                self.assertEqual(transport.packages, [])
            for dry in (False, True):
                worker, _, _, _ = self.make(tmp, acquire_lock=True, project_root=tmp, dry_run=dry)
                def fail_step():
                    self.assertTrue(any_emu_worker_running(tmp))
                    raise ValueError('startup failure')
                worker.step = fail_step
                self.assertIn('startup failure', worker.run()['last_error'])
                self.assertFalse(any_emu_worker_running(tmp))
            worker, _, _, _ = self.make(tmp, acquire_lock=True, project_root=tmp)
            worker._run_locked = Mock(side_effect=RuntimeError('cleanup failure'))
            with self.assertRaises(RuntimeError):
                worker.run()
            self.assertFalse(any_emu_worker_running(tmp))

    def test_cli_enables_project_scoped_lock_even_for_dry_run(self):
        with patch.object(emu_worker, 'EmuWorker') as factory, patch.object(emu_worker.signal, 'signal'):
            factory.return_value.run.return_value = {'last_error': ''}
            self.assertEqual(emu_worker.main(['--instance', 'mumu:7', '--project-root', 'test-root', '--dry-run']), 0)
            cfg = factory.call_args.args[0]
            self.assertTrue(cfg.acquire_lock and cfg.dry_run)
            self.assertEqual(cfg.project_root, 'test-root')

    def test_watchdog_stops_resolved_package(self):
        with test_directory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            worker, transport, _, clock = self.make(tmp, watchdog_seconds=10)
            transport.resolve_kards_package = Mock(return_value='com.android1939.kardsapk')
            clock.now = 20
            self.assertTrue(worker._check_watchdog('unknown'))
            self.assertEqual(transport.packages, ['com.android1939.kardsapk'])
            transport.resolve_kards_package.assert_called_once_with()

    def test_observe_gates_fast_opponent_until_first_match_turn(self):
        with test_directory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            worker, transport, _, _ = self.make(tmp, deck_name="日本初始")
            frame = np.full((720, 1280, 3), 35, np.uint8)
            transport.capture_bgr = Mock(return_value=frame)
            ocr = Mock(return_value=[text("敌方", 1120, 500),
                                     text("选择要替换的卡牌", 640, 100), text("确认", 640, 648)])
            vision = worker.vision = EmuVision(load_core=False, ocr_fn=ocr, ocr_cache_ttl=0)
            vision.core = Mock()
            enemy = vision.core.apk_enemy_turn.inspect_opponent_turn
            enemy.return_value = {"present": True}
            worker.status["turns"] = 9  # Previous matches must not enable the fast path.
            with patch.object(vision, "_match", return_value=(0, (1000, 480, 100, 50))), \
                    patch.object(vision, "classify_screen", wraps=vision.classify_screen) as classify:
                self.assertEqual(worker._match_turns, 0)
                self.assertEqual(worker._observe(frame).state, "mulligan")
                classify.assert_called_once_with(frame, target_mode="training", deck_name="日本初始",
                                                  allow_fast_opponent=False)
                enemy.assert_not_called()
                ocr.assert_called_once_with(frame)
                classify.reset_mock()
                worker.step()
                self.assertEqual(transport.inputs, [("tap", (640, 648))])
                self.assertEqual(classify.call_count, 2)
                self.assertTrue(all(call.kwargs["allow_fast_opponent"] is False
                                    for call in classify.call_args_list))
                enemy.assert_not_called()
                ocr.reset_mock()
                for turns in (1, 3):
                    worker._match_turns = turns
                    classify.reset_mock()
                    enemy.reset_mock()
                    self.assertEqual(worker._observe(frame).state, "opponent_turn")
                    classify.assert_called_once_with(frame, target_mode="training", deck_name="日本初始",
                                                      allow_fast_opponent=True)
                    enemy.assert_called_once_with(frame)
                    ocr.assert_not_called()

    def test_idle_poll_intervals(self):
        for state, intervals in (("opponent_turn", [1.0]), ("queueing", [1.5]),
                                 ("unknown", [1.0, 1.0, 2.0]),
                                 ("blank", [1.0, 1.0, 2.0])):
            with self.subTest(state=state), test_directory() as tmp, contextlib.redirect_stdout(io.StringIO()):
                worker, _, vision, clock = self.make(tmp)
                vision.classify_screen = lambda *a, **k: ScreenObservation(state, "test")
                for interval in intervals:
                    before = clock()
                    worker.step()
                    self.assertAlmostEqual(clock() - before, interval)

    def test_full_match_and_atomic_status(self):
        with test_directory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            worker, transport, vision, clock = self.make(tmp, max_rounds=1, max_seconds=60)
            import os
            original = os.replace
            replacements = []
            def replace(source, dest):
                payload = json.loads(Path(source).read_text(encoding="utf-8"))
                self.assertEqual(Path(source).parent, Path(dest).parent)
                self.assertIn("running", payload)
                replacements.append(payload)
                original(source, dest)
            with patch("emu_worker.os.replace", side_effect=replace):
                status = worker.run()
            self.assertEqual((status["rounds_done"], status["victories"], status["defeats"]), (1, 1, 0))
            self.assertEqual((status["turns"], status["attacks"], status["deploys"]), (1, 1, 1))
            self.assertEqual(status["state"], "home")
            self.assertFalse(status["running"])
            self.assertEqual(status["last_error"], "")
            self.assertLess(clock(), 60)
            self.assertTrue(transport.closed)
            self.assertEqual(transport.packages, ["com.kards.mobilert"])
            self.assertTrue(any(("support", 20, 20) in skip for skip in vision.skips))
            self.assertGreater(len(replacements), 8)
            self.assertEqual(json.loads(Path(worker.cfg.status_file).read_text(encoding="utf-8")), status)
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])
            self.assertTrue({"instance_id", "name", "pid", "backend", "running", "state", "mode",
                             "rounds_done", "victories", "defeats", "turns", "deploys", "attacks", "last_action",
                             "last_error", "avg_capture_ms", "started_at", "updated_at"} <= status.keys())
            log = Path(worker.cfg.log_file).read_text(encoding="utf-8")
            for marker in ("state -> home", "our turn starts", "[attack]", "[deploy]", "== round 1 finished (victory)"):
                self.assertIn(marker, log)
            self.assertRegex(log, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")

    def test_status_write_retries_transient_permission_errors(self):
        with test_directory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            worker, _, _, clock = self.make(tmp)
            worker._write_status()
            worker.status["turns"] = 2
            import os
            original = os.replace
            attempts = []
            def replace(source, dest):
                attempts.append(source)
                self.assertTrue(Path(source).exists())
                self.assertEqual(json.loads(Path(source).read_text(encoding="utf-8"))["turns"], 2)
                if len(attempts) < 3:
                    self.assertEqual(json.loads(Path(dest).read_text(encoding="utf-8"))["turns"], 0)
                    raise PermissionError("reader holds status")
                original(source, dest)
            with patch("emu_worker.os.replace", side_effect=replace), patch.object(worker, "log") as log:
                worker._write_status()
                log.assert_not_called()
            self.assertEqual(len(attempts), 3)
            self.assertEqual(len(set(attempts)), 1)
            self.assertAlmostEqual(clock(), .06)
            self.assertEqual(json.loads(Path(worker.cfg.status_file).read_text(encoding="utf-8")), worker.status)
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])

    def test_status_write_exhaustion_warns_cleans_up_and_worker_continues(self):
        with test_directory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            worker, transport, _, clock = self.make(tmp, max_seconds=2)
            worker._write_status()
            previous = Path(worker.cfg.status_file).read_text(encoding="utf-8")
            with patch("emu_worker.os.replace", side_effect=PermissionError("reader holds status")) as replace:
                worker._write_status()
                self.assertEqual(replace.call_count, 6)
                self.assertAlmostEqual(clock(), .46)
                self.assertEqual(list(Path(tmp).glob("*.tmp")), [])
                result = worker.run()
            self.assertEqual(result["last_error"], "")
            self.assertFalse(result["running"])
            self.assertTrue(transport.closed)
            self.assertTrue(transport.inputs)
            self.assertEqual(Path(worker.cfg.status_file).read_text(encoding="utf-8"), previous)
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])
            self.assertIn("warning: status write skipped: reader holds status",
                          Path(worker.cfg.log_file).read_text(encoding="utf-8"))

    def test_main_uses_pointer_sized_priority_prototypes(self):
        import ctypes
        import emu_worker
        kernel32 = Mock()
        handle = 0x1234567887654321
        kernel32.GetCurrentProcess.return_value = handle
        def set_priority(process, priority):
            self.assertIs(kernel32.GetCurrentProcess.restype, ctypes.c_void_p)
            self.assertEqual(kernel32.SetPriorityClass.argtypes, [ctypes.c_void_p, ctypes.c_uint32])
            self.assertIs(kernel32.SetPriorityClass.restype, ctypes.c_int)
            self.assertEqual((process, priority), (handle, 0x00004000))
            return 1
        kernel32.SetPriorityClass.side_effect = set_priority
        with patch("emu_worker.os.name", "nt"), \
                patch.object(ctypes, "windll", Mock(kernel32=kernel32), create=True), \
                patch("emu_worker.cv2.setNumThreads"), patch("emu_worker.signal.signal"), \
                patch("emu_worker.EmuWorker") as factory:
            factory.return_value.run.return_value = {"last_error": ""}
            self.assertEqual(emu_worker.main(["--instance", "mumu:7", "--dry-run"]), 0)
        kernel32.SetPriorityClass.assert_called_once_with(handle, 0x00004000)

    def test_max_rounds_stops_at_deck_detail_after_settlement(self):
        with test_directory() as tmp, contextlib.redirect_stdout(io.StringIO()), \
                patch(__name__ + ".STATES", ["victory", "deck_detail", "mulligan"]):
            worker, transport, _, clock = self.make(tmp, max_rounds=1, max_seconds=60)
            status = worker.run()
            self.assertEqual(status["rounds_done"], 1)
            self.assertEqual(status["victories"], 1)
            self.assertEqual(status["state"], "deck_detail")
            self.assertFalse(status["running"])
            self.assertEqual(status["last_error"], "")
            self.assertEqual(transport.inputs, [("tap", (640, 665))])
            self.assertEqual(transport.index, 1)
            self.assertTrue(transport.closed)
            self.assertLess(clock(), 60)

    def test_dry_run_zero_inputs_in_all_states(self):
        for index in range(len(STATES)):
            with self.subTest(index=index), test_directory() as tmp, contextlib.redirect_stdout(io.StringIO()):
                worker, transport, _, _ = self.make(tmp, dry_run=True, max_seconds=2)
                transport.index = index
                worker.run()
                self.assertEqual(transport.inputs, [])
                self.assertEqual(transport.packages, [])
                self.assertEqual(transport.launches, 0)
                self.assertEqual(worker.status["attacks"], 0)

    def test_stop_file_during_wait(self):
        with test_directory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            stop = Path(tmp)/"stop"
            worker, transport, _, clock = self.make(tmp, stop_file=str(stop))
            def sleep(seconds):
                clock.sleep(seconds)
                stop.touch()
            worker.sleep_fn = sleep
            transport.index = 5
            worker.run()
            self.assertEqual(transport.inputs, [])
            self.assertTrue(transport.closed)
            self.assertLess(clock(), .2)

    def test_preexisting_stop_and_event(self):
        with test_directory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            worker, transport, _, _ = self.make(tmp)
            worker.stop()
            worker.run()
            self.assertEqual(transport.inputs+transport.packages, [])

    def test_foreground_launch_throttling(self):
        with test_directory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            worker, transport, _, _ = self.make(tmp, max_seconds=22)
            transport.foreground = False
            worker.run()
            self.assertEqual(transport.launches, 2)
            self.assertEqual(transport.inputs, [])

    def test_stop_between_planning_and_input(self):
        with test_directory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            worker, transport, vision, _ = self.make(tmp, max_seconds=10)
            transport.index = 5
            original = vision.plan_combat_action
            def plan(frame, skips):
                worker.stop()
                return original(frame, skips)
            vision.plan_combat_action = plan
            worker.run()
            self.assertEqual(transport.inputs, [])

    def test_rejected_deploy_quarantined(self):
        with test_directory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            worker, transport, vision, _ = self.make(tmp, allow_attack=False, allow_end_turn=False)
            transport.index = 5
            vision.detect_insufficient_kredits = lambda frame: True
            worker.step()
            self.assertIn((30, 27), worker.skip_grabs)
            self.assertEqual(worker.deploys_this_turn, 1)
            self.assertEqual(transport.inputs[0][2], 900)

    def test_end_turn_retry_warning(self):
        with test_directory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            worker, transport, _, _ = self.make(tmp, allow_attack=False, allow_deploy=False)
            transport.index = 5
            transport.tap = lambda *args: transport.inputs.append(args)
            for _ in range(3):
                worker.step()
            self.assertEqual(worker.end_retries, 3)
            self.assertEqual(len(transport.inputs), 3)
            self.assertIn("end turn still unconfirmed", Path(worker.cfg.log_file).read_text(encoding="utf-8"))

    def test_choice_target_and_cancel(self):
        for state, hq, expected in (("choice_modal", None, (640, 360)),
                                    ("target_selection", (640, 180), (640, 180)),
                                    ("target_selection", None, (1200, 680))):
            with self.subTest(state=state, hq=hq), test_directory() as tmp, contextlib.redirect_stdout(io.StringIO()):
                worker, transport, vision, _ = self.make(tmp)
                vision.classify_screen = lambda *a, **k: ScreenObservation(state, "fake")
                vision.enemy_hq = lambda frame: hq
                worker.status["turns"] = 1
                worker._match_turns = 1
                worker.step()
                self.assertEqual(transport.inputs, [("tap", expected)])

    def assert_turn_cleared(self, worker):
        self.assertFalse(worker._in_own_turn)
        self.assertEqual(worker._actor_attempts, {})
        self.assertEqual(worker.skip_actors, set())
        self.assertEqual(worker.skip_grabs, set())
        self.assertEqual((worker.deploys_this_turn, worker.attacks_this_turn, worker.end_retries), (0, 0, 0))

    def seed_turn(self, worker):
        worker._in_own_turn = True
        worker.status["turns"] = 1
        worker.skip_actors.add(("support", 20, 20))
        worker._actor_attempts[("support", 20, 20)] = 2
        worker.skip_grabs.add((30, 27))
        worker.deploys_this_turn = worker.attacks_this_turn = 2

    def test_end_turn_disappearance_resets_before_next_observation(self):
        for result in (None, ScreenObservation("opponent_turn", "test")):
            with self.subTest(result=result), test_directory() as tmp, contextlib.redirect_stdout(io.StringIO()):
                worker, transport, vision, _ = self.make(tmp, allow_attack=False, allow_deploy=False)
                self.seed_turn(worker)
                transport.index = 5
                vision.classify_battle = lambda frame: result
                worker.step()
                self.assert_turn_cleared(worker)
                self.assertEqual(worker.status["turns"], 1)
                transport.index = 5
                worker.cfg.allow_end_turn = False
                worker.step()
                self.assertEqual(worker.status["turns"], 2)

    def test_template_miss_checks_ocr_but_confirmed_end_skips_it(self):
        with test_directory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            worker, transport, _, clock = self.make(tmp, allow_attack=False, allow_deploy=False)
            self.seed_turn(worker)
            before = np.full((720, 1280, 3), 35, np.uint8)
            after = before.copy()
            after[440:470, 1000:1100] = 135
            ocr = Mock(return_value=[text('结束回合', 1100, 500)])
            vision = worker.vision = EmuVision(load_core=False, ocr_fn=ocr,
                                               ocr_cache_ttl=100, clock_fn=clock)
            transport.tap = Mock()
            transport.capture_bgr = Mock(return_value=after)
            with patch.object(vision, 'classify_battle', return_value=None):
                worker._observe(before)  # Cached OCR must not mask the local glow change.
                obs = ScreenObservation('own_turn', 'end_turn_btn', (1100, 500))
                worker._own_turn(before, obs)
                self.assertTrue(worker._in_own_turn)
                self.assertEqual(worker.end_retries, 1)
                self.assertGreater(ocr.call_count, 1)
                self.assertEqual(worker._actor_attempts, {('support', 20, 20): 2})
            for state in ('opponent_turn', 'victory', 'defeat'):
                self.seed_turn(worker)
                with patch.object(vision, 'classify_battle', return_value=ScreenObservation(state, 'test')), \
                        patch.object(worker, '_observe', side_effect=AssertionError('unneeded OCR')):
                    worker._own_turn(before, obs)
                    self.assert_turn_cleared(worker)

    def test_ocr_end_turn_confirmation_refreshes_local_button_changes(self):
        for changed_but_still_own in (False, True):
            with self.subTest(changed_but_still_own=changed_but_still_own), \
                    test_directory() as tmp, contextlib.redirect_stdout(io.StringIO()):
                worker, transport, _, clock = self.make(tmp, allow_attack=False, allow_deploy=False)
                self.seed_turn(worker)
                before = np.full((720, 1280, 3), 35, np.uint8)
                glowing = before.copy()
                glowing[440:470, 1000:1100] = 135
                gone = before.copy()
                gone[440:470, 1000:1100] = 235
                after = glowing if changed_but_still_own else before
                self.assertLess(frame_motion(before, gone), .005)
                self.assertGreaterEqual(frame_motion(before, glowing, (980, 420, 1275, 620)), .02)
                ocr = Mock(side_effect=lambda f: [text('敌方', 1100, 500)]
                           if f[450, 1050, 0] == 235 else [text('End Turn', 1100, 500)])
                vision = worker.vision = EmuVision(load_core=False, ocr_fn=ocr,
                                                   ocr_cache_ttl=100, clock_fn=clock)
                transport.tap = Mock()  # A dropped tap must not clear turn state.
                transport.capture_bgr = Mock(return_value=after)
                with patch.object(vision, 'classify_battle', return_value=None):
                    obs = worker._observe(before)  # Prime a long-lived own-turn cache.
                    self.assertEqual(obs.reason, 'ocr_end_turn')
                    worker._own_turn(before, obs)
                    self.assertTrue(worker._in_own_turn)
                    self.assertEqual(worker.end_retries, 1)
                    self.assertEqual(worker._actor_attempts, {('support', 20, 20): 2})
                    self.assertEqual(worker.skip_grabs, {(30, 27)})
                    if changed_but_still_own:
                        self.assertGreater(ocr.call_count, 1)
                        self.assertIs(ocr.call_args.args[0], after)
                    else:
                        self.assertEqual(ocr.call_count, 1)
                    reads = ocr.call_count
                    transport.capture_bgr.return_value = gone
                    worker._own_turn(after, obs)
                    self.assertEqual(ocr.call_count, reads + 1)
                    self.assertIs(ocr.call_args.args[0], gone)
                    self.assert_turn_cleared(worker)
                    self.assertEqual(worker.status['turns'], 1)
                    self.assertEqual(transport.tap.call_count, 2)

    def test_combat_actor_quarantined_after_two_attempts_despite_motion(self):
        for kind in ('attack_hq', 'move_front'):
            with self.subTest(kind=kind), test_directory() as tmp, contextlib.redirect_stdout(io.StringIO()):
                worker, transport, vision, clock = self.make(tmp, allow_deploy=False)
                worker._in_own_turn = True
                transport.index = 5
                key = ('support', 20, 20)
                plan = ActionPlan(kind, (500, 500), (640, 180), key=key)
                vision.plan_combat_action = Mock(side_effect=lambda frame, skip: None if key in skip else plan)
                frame = np.zeros((720, 1280, 3), np.uint8)
                after = np.full_like(frame, 100)
                self.assertGreaterEqual(frame_motion(frame, after), .004)
                transport.capture_bgr = Mock(return_value=after)
                obs = ScreenObservation('own_turn', 'end_turn_btn', (1100, 500))
                for count in (1, 2):
                    worker._own_turn(frame, obs)
                    self.assertEqual(worker._actor_attempts[key], count)
                    self.assertEqual(key in worker.skip_actors, count == 2)
                self.assertEqual(len(transport.inputs), 2)
                worker._own_turn(after, obs)
                self.assertEqual([entry[0] for entry in transport.inputs], ['drag', 'drag', 'tap'])
                self.assert_turn_cleared(worker)
                self.assertLess(clock(), 4.)

    def test_unsent_combat_does_not_consume_actor_attempt(self):
        with test_directory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            worker, transport, _, _ = self.make(tmp, dry_run=True)
            worker._in_own_turn = True
            worker._own_turn(transport.capture_bgr(), ScreenObservation('own_turn', 'test'))
            self.assertEqual(worker._actor_attempts, {})
            self.assertEqual(worker.skip_actors, set())

    def test_three_unknown_frames_reset_and_known_frame_breaks_streak(self):
        with test_directory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            worker, transport, vision, _ = self.make(tmp, allow_attack=False, allow_deploy=False, allow_end_turn=False)
            self.seed_turn(worker)
            state = "unknown"
            vision.classify_screen = lambda *a, **k: ScreenObservation(state, "test")
            worker.step(); worker.step()
            self.assertTrue(worker._in_own_turn)
            state = "own_turn"
            worker.step()
            self.assertEqual(worker._unknown_streak, 0)
            state = "unknown"
            worker.step(); worker.step()
            self.assertTrue(worker._in_own_turn)
            worker.step()
            self.assert_turn_cleared(worker)
            state = "own_turn"
            worker.step()
            self.assertEqual(worker.status["turns"], 2)
            self.assertEqual(transport.inputs, [])

    def test_opening_choice_waits_then_mulligan_and_later_choice_works(self):
        with test_directory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            worker, transport, vision, clock = self.make(tmp)
            vision.classify_screen = lambda *a, **k: ScreenObservation("choice_modal", "test")
            worker.step()
            self.assertEqual(transport.inputs, [])
            self.assertAlmostEqual(clock(), .6)
            vision.classify_screen = lambda *a, **k: ScreenObservation("mulligan", "test", (640, 648))
            worker.step()
            self.assertEqual(transport.inputs, [("tap", (640, 648))])
            vision.classify_screen = lambda *a, **k: ScreenObservation("choice_modal", "test")
            worker._match_turns = 1
            for active in (True, False):
                worker._in_own_turn = active
                worker.step()
                self.assertEqual(transport.inputs[-1], ("tap", (640, 360)))
            self.assertEqual(len(transport.inputs), 3)

    def test_new_match_resets_turns_and_opening_choice_never_taps(self):
        for state in ("queueing", "deck_detail", "mulligan"):
            with self.subTest(state=state), test_directory() as tmp, contextlib.redirect_stdout(io.StringIO()):
                worker, transport, vision, _ = self.make(tmp, allow_attack=False, allow_deploy=False,
                                                        allow_end_turn=False)
                worker.status["rounds_done"] = 1
                worker.status["turns"] = worker._match_turns = 9
                self.seed_turn(worker)
                worker.status["turns"] = 9
                vision.classify_screen = lambda *a, **k: ScreenObservation(state, "test")
                worker.step()
                self.assertEqual(worker._match_turns, 0)
                self.assertEqual(worker.status["turns"], 9)
                self.assert_turn_cleared(worker)
                vision.classify_screen = lambda *a, **k: ScreenObservation("choice_modal", "test")
                worker.step(); worker.step()
                self.assertEqual(transport.inputs, [])
                vision.classify_screen = lambda *a, **k: ScreenObservation("own_turn", "test")
                worker.step()
                self.assertEqual(worker._match_turns, 1)
                self.assertEqual(worker.status["turns"], 10)
                vision.classify_screen = lambda *a, **k: ScreenObservation("choice_modal", "test")
                worker.step()
                self.assertEqual(transport.inputs, [("tap", (640, 360))])

    def test_mulligan_and_choice_require_stable_matching_second_frame(self):
        for state, target, threshold in (("mulligan", (640, 648), .02),
                                         ("choice_modal", (640, 360), .015)):
            for motion, second_state, taps in ((threshold, state, []), (0, "own_turn", []),
                                               (threshold-.001, state, [("tap", target)])):
                with self.subTest(state=state, motion=motion, second=second_state), \
                        test_directory() as tmp, contextlib.redirect_stdout(io.StringIO()):
                    worker, transport, vision, clock = self.make(tmp)
                    worker._match_turns = 1
                    before = np.full((720, 1280, 3), 35, np.uint8)
                    after = before.copy()
                    after.reshape(-1, 3)[:round(motion*720*1280)] = 100
                    transport.capture_bgr = Mock(side_effect=[before, after])
                    vision.classify_screen = Mock(side_effect=[ScreenObservation(state, "first", target),
                                                               ScreenObservation(second_state, "second", target)])
                    worker.step()
                    self.assertEqual(transport.inputs, taps)
                    self.assertEqual(transport.capture_bgr.call_count, 2)
                    self.assertGreaterEqual(clock(), .6)

    def test_empty_turn_rechecks_once_then_ends_or_deploys_newly_lit_unit(self):
        for lights_up in (False, True):
            with self.subTest(lights_up=lights_up), test_directory() as tmp, contextlib.redirect_stdout(io.StringIO()):
                worker, transport, vision, clock = self.make(tmp)
                transport.index = 5
                # Keep the fake screen on our turn to exercise an unconfirmed end.
                transport.tap = lambda x, y: transport.inputs.append(("tap", (x, y)))
                vision.plan_combat_action = Mock(return_value=None)
                before = np.full((720, 1280, 3), 35, np.uint8)
                fresh = np.full((720, 1280, 3), 70, np.uint8)
                transport.capture_bgr = Mock(side_effect=lambda: before if clock() < 2 else fresh)
                plan = ActionPlan("deploy", (730, 650), (850, 500),
                                  [(730, 650), (730, 575), (850, 500)], (30, 27))
                def deploy(frame, skips):
                    vision.last_deploy_reason = "ok:deploy_orange_unit" if lights_up and frame is fresh else "no_orange_hand"
                    return plan if lights_up and frame is fresh else None
                vision.plan_deploy_action = Mock(side_effect=deploy)
                vision.classify_battle = Mock(return_value=ScreenObservation("own_turn", "test"))
                with patch.object(worker, "_sleep", wraps=worker._sleep) as sleep:
                    worker.step()
                    self.assertTrue(worker._turn_rechecked)
                    self.assertEqual(transport.inputs, [])
                    self.assertAlmostEqual(clock(), 2.0)  # 1.2s settle + .8s re-check.
                    self.assertEqual(sleep.call_args_list[0].args, (1.2,))
                    self.assertEqual(sleep.call_args_list[1].args, (.8,))
                    self.assertIs(vision.plan_deploy_action.call_args.args[0], before)
                    worker.step()
                    self.assertIs(vision.plan_deploy_action.call_args.args[0], fresh)
                    self.assertEqual(worker._match_turns, 1)
                    self.assertEqual(worker.status["turns"], 1)
                    if lights_up:
                        self.assertEqual(transport.inputs, [("drag", plan.path, 900)])
                        self.assertEqual(worker.deploys_this_turn, 1)
                    else:
                        self.assertEqual(transport.inputs, [("tap", (1100, 500))])
                        worker.step()
                        self.assertEqual(len(transport.inputs), 2)
                    self.assertEqual(sum(call.args == (.8,) for call in sleep.call_args_list), 1)
                log = Path(worker.cfg.log_file).read_text(encoding="utf-8")
                self.assertIn("[turn] no deploy/attack (deploy=no_orange_hand)", log)
                self.assertIn("[deploy]" if lights_up else "[turn] ending turn", log)

    def test_disabled_attack_and_deploy_do_not_recheck(self):
        with test_directory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            worker, transport, _, _ = self.make(tmp, allow_attack=False, allow_deploy=False)
            transport.index = 5
            with patch.object(worker, "_sleep", wraps=worker._sleep) as sleep:
                worker.step()
            self.assertEqual(transport.inputs, [("tap", (1100, 500))])
            self.assertFalse(any(call.args == (.8,) for call in sleep.call_args_list))

    def test_transport_error_closes_and_reports(self):
        with test_directory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            worker, transport, _, _ = self.make(tmp)
            def fail():
                raise RuntimeError("capture unavailable")
            transport.capture_bgr = fail
            result = worker.run()
            self.assertEqual(result["last_error"], "RuntimeError: capture unavailable")
            self.assertFalse(result["running"])
            self.assertTrue(transport.closed)

    def test_result_count_and_settlement_bounded(self):
        with test_directory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            worker, transport, vision, _ = self.make(tmp, max_seconds=20)
            vision.classify_screen = lambda *a, **k: ScreenObservation("defeat", "fake")
            transport.tap = lambda *args: transport.inputs.append(args)
            worker.run()
            self.assertEqual(worker.status["rounds_done"], 1)
            self.assertEqual(worker.status["defeats"], 1)
            self.assertEqual(len(transport.inputs), 15)

    def test_unknown_never_blind_clicks(self):
        with test_directory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            worker, transport, vision, _ = self.make(tmp, max_seconds=2)
            vision.classify_screen = lambda *a, **k: ScreenObservation("unknown", "fake")
            worker.run()
            self.assertEqual(transport.inputs, [])

    def test_unknown_ocr_logging_throttled_and_bounded(self):
        with test_directory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            worker, transport, vision, clock = self.make(tmp)
            obs = ScreenObservation("unknown", "fake", ocr_texts=[])
            vision.classify_screen = lambda *a, **k: obs
            with patch.object(worker, "log") as log:
                worker.step()
                log.assert_not_called()
                obs.ocr_texts = ["NETWORKERROR", "请检查网络连接并选择“重启”。", "重启"]
                worker.step()
                log.assert_called_once_with("unknown OCR: NETWORKERROR | 请检查网络连接并选择“重启”。 | 重启")
                worker.step()
                self.assertEqual(log.call_count, 1)
                clock.now = worker._last_unknown_ocr + 15
                worker.step()
                self.assertEqual(log.call_count, 2)
                obs.state = "blank"
                worker.step()
                obs.state = "unknown"
                obs.ocr_texts = ["a\nb"] * 6 + ["excluded"]
                worker.step()
                self.assertEqual(log.call_args.args[0], "unknown OCR: " + " | ".join(["a b"] * 6))
                obs.ocr_texts = ["x" * 200]
                clock.now = worker._last_unknown_ocr + 15
                worker.step()
                self.assertEqual(log.call_args.args[0], "unknown OCR: " + "x" * 140)
            self.assertEqual(transport.inputs, [])


class Wave2Tests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(test_directory()))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.day = "2026-11-20"
        self.usage = self.root / "emu_daily_usage.json"

    def make(self, **options):
        self.clock = FakeClock()
        self.transport = FakeTransport(self.clock)
        self.vision = FakeVision(self.transport)
        self.worker = EmuWorker(WorkerConfig("mumu:7", **options), self.transport,
                                self.vision, self.clock.sleep, self.clock,
                                today_fn=lambda: self.day)
        return self.worker

    def observe(self, state, target=None):
        self.vision.classify_screen = Mock(return_value=ScreenObservation(state, "test", target))

    def save_usage(self, rounds=0, minutes=0):
        self.usage.write_text(json.dumps({self.day: {"mumu:7": {
            "rounds": rounds, "minutes": minutes}}}), encoding="utf-8")

    def counts(self, day=None, instance="mumu:7"):
        return emu_worker.load_daily_usage(self.usage, day or self.day, instance)

    def test_watchdog_unknown_blank_and_unchanged_known_state(self):
        for state in ("unknown", "blank", "queueing", "opponent_turn", "home"):
            with self.subTest(state=state):
                worker = self.make(watchdog_seconds=10, stop_mobile_helper=False)
                self.observe(state)
                worker.step()
                self.clock.now = 9.9
                worker.step()
                self.assertEqual(self.transport.packages, [])
                self.clock.now = 10
                worker.step()
                self.assertEqual(self.transport.packages, ["com.android1939.kards"])
                self.assertEqual(self.transport.launches, 1)
                self.assertEqual(worker.status["restarts"], 1)
                self.assertEqual(self.transport.inputs, [])

    def test_watchdog_no_frame_and_no_foreground(self):
        for missing in ("capture", "foreground"):
            with self.subTest(missing=missing):
                worker = self.make(watchdog_seconds=10, stop_mobile_helper=False)
                if missing == "capture":
                    self.transport.capture_bgr = Mock(return_value=None)
                else:
                    self.transport.foreground = False
                self.clock.now = 10
                worker.step()
                self.assertEqual(self.transport.packages, ["com.android1939.kards"])
                launches = self.transport.launches
                worker.step()
                self.assertEqual(self.transport.launches, launches)

    def test_watchdog_cooldown_both_branches(self):
        for threshold in (10, 200):
            with self.subTest(threshold=threshold):
                worker = self.make(watchdog_seconds=threshold)
                self.clock.now = threshold
                self.assertTrue(worker._check_watchdog("unknown"))
                cooldown = max(60.0, threshold * .5)
                # Isolate the cooldown from the separate stall-time gate.
                worker._last_progress_at = -1000
                self.clock.now = threshold + cooldown - .001
                self.assertFalse(worker._check_watchdog("unknown"))
                self.clock.now = threshold + cooldown
                self.assertTrue(worker._check_watchdog("unknown"))
                self.assertEqual(self.transport.launches, 2)

    def test_watchdog_budget_stops_cleanly_and_closes(self):
        for budget in (0, 2):
            with self.subTest(budget=budget):
                worker = self.make(watchdog_seconds=1, watchdog_max_restarts=budget,
                                   stop_mobile_helper=False, max_seconds=200)
                self.observe("unknown")
                result = worker.run()
                self.assertEqual(result["restarts"], budget)
                self.assertEqual(self.transport.packages, ["com.android1939.kards"] * budget)
                self.assertEqual(self.transport.launches, budget)
                self.assertIn("max restarts", result["last_error"])
                self.assertFalse(result["running"])
                self.assertTrue(self.transport.closed)
                self.assertTrue(worker.should_stop())

    def test_watchdog_disabled_and_cancelled(self):
        for options in ({"dry_run": True}, {"auto_launch_kards": False},
                        {"watchdog_seconds": 0}):
            with self.subTest(options=options):
                worker = self.make(**{"watchdog_seconds": 1, "stop_mobile_helper": False, **options})
                self.observe("unknown")
                self.transport.foreground = "watchdog_seconds" in options
                self.clock.now = 1000
                worker.step()
                self.assertEqual(self.transport.packages, [])
                self.assertEqual(self.transport.launches, 0)
                self.assertEqual(worker.status["last_error"], "")
        worker = self.make(watchdog_seconds=1)
        self.clock.now = 10
        worker.stop()
        self.assertFalse(worker._check_watchdog("unknown"))
        self.assertEqual(self.transport.packages, [])

    def test_watchdog_stop_during_restart_wait_never_launches(self):
        worker = self.make(watchdog_seconds=1)
        self.clock.now = 10
        worker.sleep_fn = lambda seconds: worker.stop()
        self.assertTrue(worker._check_watchdog("blank"))
        self.assertEqual(self.transport.packages, ["com.android1939.kards"])
        self.assertEqual(self.transport.launches, 0)

    def test_watchdog_transport_failures_are_bounded_and_reset_turn(self):
        worker = self.make(watchdog_seconds=1)
        self.transport.force_stop_package = Mock(side_effect=emu_worker.EmuTransportError("stop failed"))
        self.transport.launch_kards = Mock(side_effect=emu_worker.EmuTransportError("launch failed"))
        worker._in_own_turn = worker._settling = True
        worker._match_turns = worker._settle_clicks = 5
        worker.skip_actors.add((1, 2))
        self.clock.now = 10
        self.assertTrue(worker._check_watchdog("unknown"))
        self.assertFalse(worker._in_own_turn or worker._settling)
        self.assertEqual((worker._match_turns, worker._settle_clicks), (0, 0))
        self.assertEqual(worker.skip_actors, set())
        self.assertEqual(worker.status["last_error"], "")

    def test_watchdog_state_progress_only_for_known_transitions(self):
        worker = self.make(watchdog_seconds=100)
        for state, now, expected in (("blank", 20, 0), ("unknown", 30, 0),
                                     ("queueing", 40, 40), ("queueing", 50, 40),
                                     ("opponent_turn", 60, 60)):
            self.observe(state)
            self.clock.now = now
            worker.step()
            self.assertEqual(worker._last_progress_at, expected)
        self.assertEqual(self.transport.launches, 0)

    def test_watchdog_actions_reset_only_after_progress(self):
        for action in ("attack_hq", "move_front", "deploy", "end_turn"):
            for changed in (False, True):
                with self.subTest(action=action, changed=changed):
                    worker = self.make(watchdog_seconds=100, allow_attack=False,
                                       allow_deploy=False, allow_end_turn=False)
                    worker._in_own_turn = True
                    self.clock.now = 30
                    frame = np.zeros((720, 1280, 3), np.uint8)
                    after = np.full_like(frame, 100) if changed else frame
                    self.transport.capture_bgr = Mock(return_value=after)
                    plan = ActionPlan(action, (500, 500), (640, 180),
                                      [(500, 500), (500, 450), (640, 180)], (1, 2))
                    if action in ("attack_hq", "move_front"):
                        worker.cfg.allow_attack = True
                        self.vision.plan_combat_action = Mock(return_value=plan)
                    elif action == "deploy":
                        worker.cfg.allow_deploy = True
                        self.vision.plan_deploy_action = Mock(return_value=plan)
                    else:
                        worker.cfg.allow_end_turn = True
                        self.vision.classify_battle = Mock(return_value=ScreenObservation(
                            "opponent_turn" if changed else "own_turn", "test"))
                    worker._own_turn(frame, ScreenObservation("own_turn", "test", (1100, 500)))
                    self.assertEqual(len(self.transport.inputs), 1)
                    if changed:
                        self.assertEqual(worker._last_progress_at, self.clock())
                    else:
                        self.assertEqual(worker._last_progress_at, 0)

    def test_rejected_deploy_and_dry_run_are_not_watchdog_progress(self):
        for dry in (False, True):
            worker = self.make(allow_attack=False, allow_end_turn=False, dry_run=dry)
            worker._in_own_turn = True
            self.clock.now = 30
            frame = np.zeros((720, 1280, 3), np.uint8)
            self.transport.capture_bgr = Mock(return_value=np.full_like(frame, 100))
            self.vision.detect_insufficient_kredits = Mock(return_value=True)
            worker._own_turn(frame, ScreenObservation("own_turn", "test"))
            self.assertEqual(worker._last_progress_at, 0)

    def test_round_finish_progress_and_usage_only_once(self):
        worker = self.make(daily_usage_file=str(self.usage))
        self.observe("victory")
        self.clock.now = 60
        worker.step()
        self.assertEqual(worker._last_progress_at, 60)
        self.assertEqual(self.counts(), (1, 1.0))
        worker.step()
        self.assertEqual(worker._last_progress_at, 60)
        self.assertEqual(worker.status["daily_rounds"], 1)
        self.observe("queueing")
        worker.step()
        self.observe("defeat")
        worker.step()
        self.assertEqual(self.counts()[0], 2)

    def test_sleep_jitter_bounds_minimum_and_zero_exact(self):
        for ratio, seconds, factor, expected in ((.2, 2, .8, 1.6), (.2, 2, 1.2, 2.4),
                                                  (.5, .01, .5, .05), (0, .01, 1, .01),
                                                  (0, 2, 1, 2), (.2, 0, 1, 0)):
            with self.subTest(ratio=ratio, seconds=seconds, factor=factor):
                worker = self.make(jitter_ratio=ratio)
                worker._rng = Mock()
                worker._rng.uniform.return_value = factor
                worker._sleep(seconds)
                self.assertAlmostEqual(self.clock(), expected)
                if ratio and seconds:
                    worker._rng.uniform.assert_called_once_with(1-ratio, 1+ratio)
                else:
                    worker._rng.uniform.assert_not_called()

    def test_tap_jitter_all_offsets_and_clamping_drag_unchanged(self):
        worker = self.make(jitter_ratio=.15)
        worker._rng = Mock()
        for target in ((640, 360), (1, 1), (1278, 718)):
            for dx in range(-3, 4):
                for dy in range(-3, 4):
                    worker._rng.randint.side_effect = [dx, dy]
                    worker._input("test", target)
                    self.assertEqual(self.transport.inputs[-1], ("tap", (
                        max(1, min(1278, target[0]+dx)), max(1, min(718, target[1]+dy)))))
        self.assertTrue(all(call.args == (-3, 3) for call in worker._rng.randint.call_args_list))
        worker._rng.reset_mock()
        path = [(0, 0), (500, 400), (1279, 719)]
        worker._input("deploy", path=path, duration_ms=900)
        self.assertEqual(self.transport.inputs[-1], ("drag", path, 900))
        self.assertIs(self.transport.inputs[-1][1], path)
        worker._rng.randint.assert_not_called()
        worker.cfg.jitter_ratio = 0
        worker._input("test", (0, 719))
        self.assertEqual(self.transport.inputs[-1], ("tap", (0, 719)))
        worker._rng.randint.assert_not_called()

    def test_daily_startup_limits_do_not_connect_or_input(self):
        for rounds, minutes, limits in ((3, 0, {"daily_max_rounds": 3}),
                                        (4, 0, {"daily_max_rounds": 3}),
                                        (0, 60, {"daily_max_minutes": 60}),
                                        (0, 61, {"daily_max_minutes": 60})):
            with self.subTest(rounds=rounds, minutes=minutes):
                self.save_usage(rounds, minutes)
                worker = self.make(daily_usage_file=str(self.usage), **limits)
                with patch.object(worker, "_startup") as startup:
                    result = worker.run()
                startup.assert_not_called()
                self.assertEqual(result["state"], "daily_limit")
                self.assertEqual(result["last_error"], "")
                self.assertFalse(result["running"])
                self.assertEqual(self.transport.inputs + self.transport.packages, [])
                self.assertEqual(self.transport.launches, 0)
                self.assertEqual(self.counts(), (rounds, minutes))

    def test_daily_limits_wait_for_every_lobby_after_active_match(self):
        for lobby in ("home", "deck_list", "deck_detail"):
            for limit in ("rounds", "minutes"):
                with self.subTest(lobby=lobby, limit=limit):
                    worker = self.make(**{"daily_max_" + limit: 1})
                    self.observe("queueing")
                    worker.step()
                    if limit == "rounds":
                        worker._daily_session_rounds = 1
                    else:
                        self.clock.now = 60
                    for state in ("mulligan", "own_turn", "opponent_turn", "in_game", "unknown", "victory"):
                        self.observe(state)
                        # Exercise routing without the battle fake moving screens.
                        with patch.object(worker, "_own_turn"):
                            self.assertTrue(worker.step())
                        self.assertFalse(worker.should_stop())
                    self.observe(lobby, (100, 100))
                    before = list(self.transport.inputs)
                    self.assertFalse(worker.step())
                    self.assertEqual(worker.status["state"], "daily_limit")
                    self.assertEqual(self.transport.inputs, before)
                    self.assertEqual(worker.status["last_error"], "")

    def test_daily_zero_limits_unlimited_and_fractional_minutes_not_rounded_for_quota(self):
        worker = self.make()
        worker._daily_session_rounds = 10000
        self.clock.now = 1000000
        self.assertFalse(worker._daily_limit_hit())
        worker = self.make(daily_max_minutes=1)
        self.clock.now = 59.9
        self.assertEqual(worker._update_daily_usage()[0], 0)
        self.assertEqual(worker.status["daily_minutes"], 1.0)
        self.assertFalse(worker._daily_limit_hit())
        self.clock.now = 60
        self.assertTrue(worker._daily_limit_hit())

    def test_daily_elapsed_time_delta_persistence_and_restart(self):
        self.save_usage(2, 10)
        worker = self.make(daily_usage_file=str(self.usage))
        self.clock.now = 60
        worker._daily_session_rounds = 1
        worker._persist_daily_usage()
        worker._persist_daily_usage()
        self.assertEqual(self.counts(), (3, 11))
        self.clock.now = 90
        worker.stop()
        result = worker.run()
        self.assertEqual(self.counts(), (3, 11.5))
        self.assertEqual((result["daily_rounds"], result["daily_minutes"]), (3, 11.5))
        restarted = self.make(daily_usage_file=str(self.usage), daily_max_rounds=3)
        self.assertEqual(restarted.run()["state"], "daily_limit")

    def test_daily_new_date_reloads_quota_and_preserves_old_day(self):
        self.save_usage(2, 10)
        worker = self.make(daily_usage_file=str(self.usage), daily_max_rounds=3)
        worker._daily_session_rounds = 1
        self.clock.now = 60
        self.assertTrue(worker._daily_limit_hit())
        self.day = "2026-11-21"
        self.assertFalse(worker._daily_limit_hit())
        self.assertEqual(worker._update_daily_usage(), (0, 0))
        self.assertEqual(self.counts("2026-11-20"), (3, 11))
        self.clock.now = 90
        worker._daily_session_rounds = 1
        worker._persist_daily_usage()
        self.assertEqual(self.counts(), (1, .5))
        self.assertEqual(self.counts("2026-11-20"), (3, 11))

    def test_daily_locked_rollover_keeps_pending_delta_until_retry(self):
        worker = self.make(daily_usage_file=str(self.usage))
        self.clock.now = 60
        worker._daily_session_rounds = 2
        self.day = "2026-11-21"
        with patch.object(emu_worker.os, "replace", side_effect=PermissionError("locked")), \
                self.assertLogs("emu_worker", level="WARNING"):
            worker._update_daily_usage()
        self.assertEqual(worker.status["daily_rounds"], 0)
        self.assertFalse(worker.should_stop())
        self.clock.now = 90
        worker._daily_session_rounds = 1
        worker._persist_daily_usage()
        worker._persist_daily_usage()
        self.assertEqual(self.counts("2026-11-20"), (2, 1))
        self.assertEqual(self.counts(), (1, .5))
        self.assertEqual(worker._pending_daily_usage, {})

    def test_daily_rollover_loads_existing_new_day_quota(self):
        self.usage.write_text(json.dumps({"2026-11-21": {"mumu:7": {
            "rounds": 5, "minutes": 20}}}), encoding="utf-8")
        worker = self.make(daily_usage_file=str(self.usage), daily_max_rounds=5)
        self.observe("opponent_turn")
        self.assertTrue(worker.step())
        self.clock.now = 60
        self.day = "2026-11-21"
        self.assertTrue(worker.step())  # The new day's quota still waits for the lobby.
        self.assertEqual(worker.status["daily_rounds"], 5)
        self.assertEqual(self.counts("2026-11-20"), (0, 1))
        self.observe("home", (100, 100))
        self.assertFalse(worker.step())
        self.assertEqual(worker.status["state"], "daily_limit")
        self.assertEqual(self.transport.inputs, [])

    def test_daily_transient_read_lock_does_not_bypass_startup_quota(self):
        self.save_usage(3, 10)
        original = Path.read_text
        attempts = []
        def read(path, *args, **kwargs):
            attempts.append(path)
            if len(attempts) < 3:
                raise PermissionError("writer holds usage")
            return original(path, *args, **kwargs)
        with patch.object(Path, "read_text", read):
            worker = self.make(daily_usage_file=str(self.usage), daily_max_rounds=3)
        self.assertEqual(len(attempts), 3)
        self.assertAlmostEqual(self.clock(), .06)
        self.assertEqual(worker.run()["state"], "daily_limit")
        self.assertEqual(self.transport.inputs + self.transport.packages, [])

    def test_daily_dry_run_never_writes_usage(self):
        worker = self.make(dry_run=True, daily_usage_file=str(self.usage), max_seconds=2)
        self.observe("victory")
        worker.run()
        self.assertFalse(self.usage.exists())
        self.assertFalse(self.usage.with_suffix(".json.lock").exists())

    def test_daily_atomic_replace_retries_permission_error_without_double_count(self):
        self.save_usage(2, 10)
        original = os.replace
        attempts, sleeps = [], []
        def replace(source, target):
            attempts.append(source)
            self.assertEqual(Path(source).parent, self.usage.parent)
            self.assertEqual(Path(target), self.usage)
            self.assertEqual(self.counts(), (2, 10))
            payload = json.loads(Path(source).read_text(encoding="utf-8"))
            self.assertEqual(payload[self.day]["mumu:7"], {"rounds": 3, "minutes": 12.5})
            if len(attempts) < 3:
                raise PermissionError("reader holds destination")
            original(source, target)
        with patch.object(emu_worker.os, "replace", side_effect=replace):
            self.assertTrue(emu_worker.record_daily_usage(self.usage, self.day, "mumu:7", 1, 2.5, sleeps.append))
        self.assertEqual(len(attempts), 3)
        self.assertEqual(sleeps, [.02, .04])
        self.assertEqual(self.counts(), (3, 12.5))
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_daily_write_lock_exhaustion_nonfatal_retries_unrecorded_delta(self):
        self.save_usage(2, 10)
        worker = self.make(daily_usage_file=str(self.usage))
        worker._daily_session_rounds = 1
        self.clock.now = 60
        with patch.object(emu_worker.os, "replace", side_effect=PermissionError("locked")) as replace, \
                self.assertLogs("emu_worker", level="WARNING"):
            worker._persist_daily_usage()
        self.assertEqual(replace.call_count, 6)
        self.assertEqual(self.counts(), (2, 10))
        self.assertFalse(worker.should_stop())
        self.assertEqual(worker.status["last_error"], "")
        self.assertEqual(list(self.root.glob("*.tmp")), [])
        worker._persist_daily_usage()
        self.assertEqual(self.counts()[0], 3)
        self.assertAlmostEqual(self.counts()[1], 10 + self.clock()/60)

    def test_daily_sidecar_lock_contention_is_nonfatal(self):
        self.save_usage(1, 2)
        lock = self.usage.with_suffix(".json.lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertLogs("emu_worker", level="WARNING"):
                self.assertFalse(emu_worker.record_daily_usage(self.usage, self.day, "mumu:7", 1, 1, lambda _: None))
            self.assertEqual(self.counts(), (1, 2))
        finally:
            lock.close()
        self.assertTrue(emu_worker.record_daily_usage(self.usage, self.day, "mumu:7", 1, 1, lambda _: None))
        self.assertEqual(self.counts(), (2, 3))

    def test_daily_concurrent_writers_preserve_instances_and_dates(self):
        self.save_usage(3, 4)
        barrier = threading.Barrier(3)
        results = []
        def write(iid):
            barrier.wait(timeout=5)
            for _ in range(8):
                results.append(emu_worker.record_daily_usage(self.usage, "2026-11-21", iid,
                                                              1, .25, emu_worker.time.sleep))
        threads = [threading.Thread(target=write, args=(iid,)) for iid in ("mumu:7", "mumu:8")]
        for thread in threads:
            thread.start()
        barrier.wait(timeout=5)
        for thread in threads:
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive())
        self.assertEqual(results, [True] * 16)
        self.assertEqual(self.counts(), (3, 4))
        for iid in ("mumu:7", "mumu:8"):
            self.assertEqual(self.counts("2026-11-21", iid), (8, 2))

    def test_daily_missing_locked_and_malformed_reads_are_nonfatal(self):
        self.assertEqual(self.counts(), (0, 0))
        with patch.object(Path, "read_text", side_effect=PermissionError("locked")), \
                self.assertLogs("emu_worker", level="WARNING"):
            self.assertEqual(self.counts(), (0, 0))
        for payload in ("{", "[]", json.dumps({self.day: []}),
                        json.dumps({self.day: {"mumu:7": []}}),
                        *[json.dumps({self.day: {"mumu:7": {key: value}}})
                          for key, value in (("rounds", -1), ("rounds", True),
                                             ("minutes", -1), ("minutes", float("nan"))) ]):
            with self.subTest(payload=payload):
                self.usage.write_text(payload, encoding="utf-8")
                with self.assertLogs("emu_worker", level="WARNING"):
                    self.assertEqual(self.counts(), (0, 0))
                    self.assertFalse(emu_worker.record_daily_usage(
                        self.usage, self.day, "mumu:7", 1, 1, lambda _: None))
                self.assertEqual(self.usage.read_text(encoding="utf-8"), payload)

    def test_cli_wave2_flags_defaults_and_errors(self):
        import ctypes
        with patch.object(ctypes, "windll", Mock(), create=True), \
                patch.object(emu_worker.cv2, "setNumThreads"), \
                patch.object(emu_worker.signal, "signal"), \
                patch.object(emu_worker, "EmuWorker") as factory:
            factory.return_value.run.return_value = {"last_error": ""}
            self.assertEqual(emu_worker.main(["--instance", "mumu:7"]), 0)
            cfg = factory.call_args.args[0]
            self.assertEqual((cfg.watchdog_seconds, cfg.watchdog_max_restarts, cfg.jitter_ratio,
                              cfg.daily_max_rounds, cfg.daily_max_minutes, cfg.daily_usage_file),
                             (0, 4, 0, 0, 0, None))
            flags = ["--watchdog-seconds", "120.5", "--watchdog-max-restarts", "2", "--jitter", ".25",
                     "--daily-max-rounds", "12", "--daily-max-minutes", "90.5",
                     "--daily-usage-file", str(self.usage), "--dry-run", "--no-auto-launch"]
            self.assertEqual(emu_worker.main(["--instance", "mumu:7", *flags]), 0)
            cfg = factory.call_args.args[0]
            self.assertEqual((cfg.watchdog_seconds, cfg.watchdog_max_restarts, cfg.jitter_ratio,
                              cfg.daily_max_rounds, cfg.daily_max_minutes, cfg.daily_usage_file),
                             (120.5, 2, .25, 12, 90.5, str(self.usage)))
            self.assertTrue(cfg.dry_run)
            self.assertFalse(cfg.auto_launch_kards)
            factory.return_value.run.return_value = {"last_error": "Watchdog: stalled after max restarts"}
            self.assertEqual(emu_worker.main(["--instance", "mumu:7"]), 1)
            for flag, value in (("--watchdog-seconds", "nan"), ("--watchdog-seconds", "-1"),
                                ("--watchdog-max-restarts", "-1"), ("--watchdog-max-restarts", "1.5"),
                                ("--jitter", ".51"), ("--jitter", "inf"),
                                ("--daily-max-rounds", "-1"), ("--daily-max-rounds", "1.5"),
                                ("--daily-max-minutes", "-1"), ("--daily-max-minutes", "nan")):
                with self.subTest(flag=flag, value=value), contextlib.redirect_stderr(io.StringIO()):
                    factory.reset_mock()
                    with self.assertRaises(SystemExit) as error:
                        emu_worker.main(["--instance", "mumu:7", flag, value])
                    self.assertEqual(error.exception.code, 2)
                    factory.assert_not_called()

    def test_worker_wave2_config_rejects_bad_types(self):
        for key in ("watchdog_seconds", "watchdog_max_restarts", "jitter_ratio",
                    "daily_max_rounds", "daily_max_minutes"):
            for value in (True, "1", None, -1, float("nan"), float("inf")):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    WorkerConfig("mumu:7", **{key: value})


def tearDownModule():
    if mobile_inventory() != BEFORE_IMPORT:
        raise AssertionError("mobile/ changed during the test suite")


if __name__ == "__main__":
    unittest.main()
