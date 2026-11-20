"""Offline Phase 2 checks: python/python.exe -B dev/emu_worker_test.py -v."""
from __future__ import annotations

import contextlib
import importlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
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
        self.assertEqual(worker.skip_actors, set())
        self.assertEqual(worker.skip_grabs, set())
        self.assertEqual((worker.deploys_this_turn, worker.attacks_this_turn, worker.end_retries), (0, 0, 0))

    def seed_turn(self, worker):
        worker._in_own_turn = True
        worker.status["turns"] = 1
        worker.skip_actors.add(("support", 20, 20))
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


def tearDownModule():
    if mobile_inventory() != BEFORE_IMPORT:
        raise AssertionError("mobile/ changed during the test suite")


if __name__ == "__main__":
    unittest.main()
