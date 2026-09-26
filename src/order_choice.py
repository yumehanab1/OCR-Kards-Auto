"""Card selection stage, calibrated for a 1280 x 720 game client.

Only orders.selection_pick() supplies a position. Recognition checks the card
borders and text panels. A second option set is handled in the same stage.
All mouse/window access is provided by the caller so tests stay offline.
"""

from __future__ import annotations

import json
import re
import time
from functools import lru_cache

import cv2

import orders

CLIENT_SIZE = (1280, 720)
ENABLE_SELECTION_STAGE = True
CHOICE_POINTS = {"1": (531, 375), "3": (750, 375)}
CARD_LEFTS = (434, 653)
THREE_LEFTS = (324, 543, 762)
THREE_POINTS = {"1": (420, 375), "2": (640, 375), "3": (859, 375)}
NORMAL_SETTLE_S = 2.5
OPEN_TIMEOUT_S = 6.0
NEXT_SET_GAP_S = 0.8
CONFIRM_GAP_S = 0.15
TITLE_UNREADABLE_TIMEOUT_S = 6.0
TITLE_MISMATCH_CONFIRM_S = 1.0
TITLE_TOTAL_TIMEOUT_S = 6.0
TITLE_MIN_CONF = 0.72  # portable OCR reads the real 19:25 choice titles at .78/.83
THREE_TITLE_MIN_CONF = 0.50  # portable OCR reads real weather titles at .54-.78
THREE_TITLE_CONFIRM_FRAMES = 2


def calibrated(frame) -> bool:
    return (frame is not None and frame.ndim == 3
            and frame.shape == (720, 1280, 3))


def panel_evidence(frame, count: int = 2) -> tuple[bool, str]:
    """Fixed option cards must have light panels and continuous edges."""
    if not calibrated(frame):
        return False, "客户区不是已校准的 1280x720"
    if count not in (2, 3):
        return False, "未知选项数"
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    metrics = []
    for x in (CARD_LEFTS if count == 2 else THREE_LEFTS):
        panel = gray[440:502, x + 7:x + 184]
        edge = gray[272:502, x + 2:x + 6]
        bottom = gray[505:508, x + 7:x + 184]
        outside = gray[275:500, x - 7:x - 2]
        mean = float(panel.mean())
        light = float((panel > 145).mean())
        edge_light = float((edge > 145).mean())
        bottom_light = float((bottom > 145).mean())
        contrast = float(edge.mean() - outside.mean())
        ok = (mean >= 155 and light >= 0.70
              and edge_light >= (0.65 if count == 3 else 0.70)
              and bottom_light >= 0.78 and contrast >= 25)
        metrics.append((ok, mean, light, edge_light, bottom_light, contrast))
    why = "; ".join(
        f"{('左', '中', '右')[i if count == 3 else (0 if i == 0 else 2)]}:"
        f"亮度={m[1]:.1f} 亮面={m[2]:.2f} "
        f"边={m[3]:.2f} 底={m[4]:.2f} 边界差={m[5]:.1f}"
        for i, m in enumerate(metrics))
    return all(m[0] for m in metrics), why


def visible(frame) -> bool:
    return panel_evidence(frame)[0]


def detect_count(frame) -> tuple[int | None, str]:
    two, two_note = panel_evidence(frame, 2)
    three, three_note = panel_evidence(frame, 3)
    if two and three:
        return -1, "两牌和三牌布局同时命中,不点击"
    if two:
        return 2, two_note
    if three:
        return 3, three_note
    return None, f"非已校准选牌画面(双牌:{two_note};三牌:{three_note})"


def unknown_center_modal(frame) -> bool:
    """Suspicious light card-like region around the choice area.

    It is not used to choose a position. It only prevents a non-matching menu
    from being misreported as a normal board after a selection click.
    """
    if not calibrated(frame):
        return True
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    light = (gray[430:525, 330:950] > 155).astype("uint8")
    return float(light.mean()) > 0.45


def selection_image(frame):
    """Pixels used to distinguish a new option set from the one just clicked."""
    return frame[285:505, 324:956].copy() if calibrated(frame) else None


def changed_since(before, after) -> bool:
    current = selection_image(after)
    return (before is not None and current is not None
            and float(cv2.absdiff(before, current).mean()) >= 12.0)


def new_three_set(before, after) -> bool:
    """Require broad changes in at least two cards, not one hover highlight."""
    current = selection_image(after)
    if before is None or current is None:
        return False
    if float(cv2.absdiff(before, current).mean()) < 25.0:
        return False
    changed_cards = sum(
        float(cv2.absdiff(before[:, x:x + 190],
                          current[:, x:x + 190]).mean()) >= 20.0
        for x in (0, 219, 438))
    return changed_cards >= 2


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _title_strips(frame, lefts, min_conf: float) -> list[str]:
    from hover_card_reader import _ocr

    seen = []
    for x in lefts:
        crop = frame[430:457, x + 8:x + 184]
        crop = cv2.resize(crop, None, fx=2, fy=2)
        crop = cv2.copyMakeBorder(crop, 12, 12, 12, 12,
                                  cv2.BORDER_CONSTANT, value=(200, 200, 200))
        lines = _ocr(crop)
        good = [ln for ln in lines if ln.get("conf", 0) >= min_conf]
        seen.append("".join(ln["text"] for ln in sorted(good,
                                                          key=lambda ln: ln["x"])))
    return seen


@lru_cache(maxsize=1)
def _known_titles() -> frozenset[str]:
    from card_match import DATA_JSON

    with open(DATA_JSON, encoding="utf-8") as source:
        cards = json.load(source)["cards"]
    return frozenset(_norm(card.get("json", {}).get("title", {}).get("zh-Hans", ""))
                     for card in cards)


def titles_match(frame, name: str) -> tuple[bool | None, str]:
    """Read both title strips; None means OCR has not found both titles yet."""
    if not calibrated(frame):
        return False, "标题帧尺寸不匹配"
    seen = _title_strips(frame, CARD_LEFTS, TITLE_MIN_CONF)
    note = f"选项标题={seen!r};预期={name!r}"
    if not all(_norm(text) for text in seen):
        return None, note
    return all(_norm(text) == _norm(name) for text in seen), note


def three_titles_match(frame) -> tuple[bool | None, tuple[str, ...], str]:
    """Require three readable option names from the bundled card database."""
    if not calibrated(frame):
        return False, (), "三牌标题帧尺寸不匹配"
    seen = tuple(_norm(text) for text in _title_strips(
        frame, THREE_LEFTS, THREE_TITLE_MIN_CONF))
    note = f"三牌选项标题={seen!r}"
    if not all(seen):
        return None, seen, note
    unknown = [title for title in seen if title not in _known_titles()]
    if unknown:
        return False, seen, f"{note};卡库中未找到={unknown!r}"
    return True, seen, note


class SelectionFlow:
    """One modal selection stage across any number of consecutive option sets.

    tick returns waiting/clicked/complete/blocked. A click never completes the
    stage by itself; only a stable normal game screen does. An unchanged modal
    is never clicked twice. Unknown follow-up screens remain in this stage.
    """

    def __init__(self, name: str, *, allow_no_popup: bool = False,
                 now: float | None = None):
        self.name = name
        self.allow_no_popup = allow_no_popup
        self.started_at = time.monotonic() if now is None else now
        self.steps = 0
        self.last_click_at = None
        self.last_clicked_count = None
        self.last_clicked_image = None
        self.candidate_count = None
        self.candidate_frames = 0
        self.candidate_since = None
        self.candidate_image = None
        self.normal_since = None
        self.normal_frames = 0
        self.title_failure_kind = None
        self.title_failure_since = None
        self.title_kind_since = None
        self.title_failure_frames = 0
        self.three_title_candidate = None
        self.three_title_frames = 0
        self.three_title_started_at = None

    def tick(self, frame, *, normal_visible, click_client, can_act,
             read_titles=titles_match, read_three_titles=three_titles_match,
             now: float | None = None,
             log=print) -> tuple[str, str]:
        now = time.monotonic() if now is None else now
        if not ENABLE_SELECTION_STAGE:
            return "blocked", "选牌阶段总开关已关闭,不点击"
        if not can_act():
            return "waiting", "游戏窗口暂不可操作"
        count, evidence = detect_count(frame)
        if count == -1:
            return "blocked", evidence
        if count is None:
            self.candidate_count = None
            self.candidate_frames = 0
            self.candidate_since = None
            self.candidate_image = None
            self.title_failure_kind = None
            self.title_failure_since = None
            self.title_kind_since = None
            self.title_failure_frames = 0
            self.three_title_candidate = None
            self.three_title_frames = 0
            self.three_title_started_at = None
            if ((self.steps or self.allow_no_popup)
                    and calibrated(frame) and float(frame.mean()) >= 20
                    and not unknown_center_modal(frame)
                    and normal_visible(frame)):
                self.normal_since = now if self.normal_since is None else self.normal_since
                self.normal_frames += 1
                if (self.normal_frames >= 2
                        and now - self.normal_since >= 0.3):
                    # A real board gap separates two menus even if the second
                    # happens to show the same three cards as the first.
                    self.last_clicked_count = None
                    self.last_clicked_image = None
                if (self.normal_frames >= 2
                        and now - (self.last_click_at or self.started_at) >= NORMAL_SETTLE_S
                        and now - self.normal_since >= NORMAL_SETTLE_S):
                    return "complete", ("连续选牌结束,已稳定回到对局画面"
                                        if self.steps else "未出现选牌,已稳定回到对局画面")
            else:
                self.normal_since = None
                self.normal_frames = 0
            if self.steps == 0 and now - self.started_at >= OPEN_TIMEOUT_S:
                return "blocked", "拖牌后未见已校准的选牌画面或稳定对局;" + evidence
            return "waiting", "等待下一组选牌或正常对局画面"

        self.normal_since = None
        self.normal_frames = 0
        if count == 2 and not orders.is_choice(self.name):
            return "blocked", "双牌抉择没有已标注的选边规则"
        if self.last_clicked_count == count:
            if not changed_since(self.last_clicked_image, frame):
                return "waiting", "上一次选牌画面尚未变化,不重复点击"
            if count == 3 and not new_three_set(self.last_clicked_image, frame):
                return "blocked", ("同张数选项只发生局部变化,不能确认是新一组;"
                                   "为避免重复点击而停手")
        if (self.last_click_at is not None
                and now - self.last_click_at < NEXT_SET_GAP_S):
            return "waiting", "上一次点击动画尚未稳定"
        current_image = selection_image(frame)
        stable = (count == self.candidate_count
                  and self.candidate_image is not None
                  and float(cv2.absdiff(self.candidate_image, current_image).mean()) < 6)
        self.candidate_frames = self.candidate_frames + 1 if stable else 1
        if not stable:
            self.candidate_since = now
            self.three_title_candidate = None
            self.three_title_frames = 0
            if count != self.candidate_count:
                self.three_title_started_at = None
                self.title_failure_kind = None
                self.title_failure_since = None
                self.title_kind_since = None
                self.title_failure_frames = 0
        self.candidate_image = current_image
        self.candidate_count = count
        if (self.candidate_frames < 2
                or now - self.candidate_since < CONFIRM_GAP_S):
            return "waiting", f"检测到 {count} 张选项,等待稳定画面确认"

        title_note = ""
        if count == 2 and self.steps == 0:
            matched, title_note = read_titles(frame, self.name)
            if matched is not True:
                kind = "unreadable" if matched is None else "mismatch"
                if self.title_failure_since is None:
                    self.title_failure_since = now
                if kind != self.title_failure_kind:
                    self.title_failure_kind = kind
                    self.title_kind_since = now
                    self.title_failure_frames = 0
                    log(f"[selection] {self.name}: 双牌标题"
                        f"{'尚未读全,等待动画结束' if kind == 'unreadable' else '与出牌名不符,复读确认'};"
                        f"{title_note}")
                self.title_failure_frames += 1
                limit = (TITLE_UNREADABLE_TIMEOUT_S if kind == "unreadable"
                         else TITLE_MISMATCH_CONFIRM_S)
                if (now - self.title_failure_since < TITLE_TOTAL_TIMEOUT_S
                        and (self.title_failure_frames < 2
                             or now - self.title_kind_since < limit)):
                    return "waiting", "双牌标题待复读;" + title_note
                return "blocked", "双牌标题未能核对白名单;" + title_note
            if self.title_failure_kind is not None:
                log(f"[selection] {self.name}: 动画后双牌标题已核对;{title_note}")
            self.title_failure_kind = None
            self.title_failure_since = None
            self.title_kind_since = None
            self.title_failure_frames = 0
        if count == 3:
            # A valid reading is still provisional until it agrees twice.
            # Keep one deadline across valid, blank and mismatched reads.
            if self.three_title_started_at is None:
                self.three_title_started_at = now
            if now - self.three_title_started_at >= TITLE_TOTAL_TIMEOUT_S:
                return "blocked", "三牌标题在限时内未能连续核对,停手"
            matched, titles, title_note = read_three_titles(frame)
            if matched is not True:
                kind = "unreadable" if matched is None else "mismatch"
                if self.title_failure_since is None:
                    self.title_failure_since = now
                if kind != self.title_failure_kind:
                    self.title_failure_kind = kind
                    self.title_kind_since = now
                    self.title_failure_frames = 0
                    log(f"[selection] 三牌标题"
                        f"{'尚未读全,等待动画结束' if kind == 'unreadable' else '未通过卡库核对,复读确认'};"
                        f"{title_note}")
                self.title_failure_frames += 1
                self.three_title_candidate = None
                self.three_title_frames = 0
                limit = (TITLE_UNREADABLE_TIMEOUT_S if kind == "unreadable"
                         else TITLE_MISMATCH_CONFIRM_S)
                if (now - self.title_failure_since < TITLE_TOTAL_TIMEOUT_S
                        and (self.title_failure_frames < 2
                             or now - self.title_kind_since < limit)):
                    return "waiting", "三牌标题待复读;" + title_note
                return "blocked", "三牌标题未能核对白名单;" + title_note
            if titles == self.three_title_candidate:
                self.three_title_frames += 1
            else:
                self.three_title_candidate = titles
                self.three_title_frames = 1
            if self.title_failure_kind is not None:
                log(f"[selection] 动画后三牌标题已核对;{title_note}")
            self.title_failure_kind = None
            self.title_failure_since = None
            self.title_kind_since = None
            self.title_failure_frames = 0
            if self.three_title_frames < THREE_TITLE_CONFIRM_FRAMES:
                return "waiting", "三牌标题等待连续核对;" + title_note
        side = orders.selection_pick(self.name, count, self.steps)
        points = CHOICE_POINTS if count == 2 else THREE_POINTS
        if side not in points:
            return "blocked", (f"第 {self.steps + 1} 次出现 {count} 张选项,"
                               "但没有标注选哪张;保持停手")
        if not can_act():
            return "waiting", "点击前游戏窗口暂不可操作"
        point = points[side]
        log(f"[selection] 第 {self.steps + 1} 次:{self.name} {count} 张选项,"
            f"选 {side} 客户区{point};{title_note}")
        if not click_client(*point):
            return "blocked", "选牌点击失败,不重复点击"
        self.steps += 1
        self.last_click_at = now
        self.last_clicked_count = count
        self.last_clicked_image = selection_image(frame)
        self.candidate_frames = 0
        self.candidate_since = None
        self.candidate_image = None
        self.candidate_count = None
        self.three_title_candidate = None
        self.three_title_frames = 0
        self.three_title_started_at = None
        return "clicked", f"第 {self.steps} 次选牌已点击,继续观察下一阶段"
