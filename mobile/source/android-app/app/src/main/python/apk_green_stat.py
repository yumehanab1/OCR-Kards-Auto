"""Recover omitted green support stats from the original dark plate and glyph.

The core plate/type/row gates remain authoritative. Fixed half-pixel sampling
uses the unchanged digit bank, mask geometry, .86 score and .12 margin. This
adapter recognizes current pixels; its diagnostics never authorize an action.
"""
import cv2
import numpy as np
import hashlib

OFFSETS = (-.5, -.25, 0., .25, .5)
SCORE_MIN = .86
DIGIT_MARGIN_MIN = .12
SUPPORT_STAT_Y = (540, 586)
DIAGNOSTIC_LIMIT = 16
OWNER_ATTRIBUTE = "_apk_green_stat_adapter"
FIELDS = ("frame_id", "captured_elapsed_ms", "foreground_generation", "source_width", "source_height")


def _valid(frame):
    return isinstance(frame, np.ndarray) and frame.shape == (720, 1280, 3) and frame.dtype == np.uint8


def _field(value):
    if (not isinstance(value, (tuple, list)) or len(value) != 4
            or any(type(v) is not int for v in value)):
        return None
    x0, y0, x1, y1 = value
    return tuple(value) if 0 <= x0 < x1 <= 1280 and 0 <= y0 < y1 <= 720 else None


def _inside_with_donors(box, field):
    x, y, w, h = box; x0, y0, x1, y1 = field
    return x0 <= x-1 and y0 <= y-1 and x+w+1 <= x1 and y+h+1 <= y1


def _pixel_hash(frame):
    data = memoryview(frame) if frame.flags.c_contiguous else frame.tobytes()
    return hashlib.blake2b(data, digest_size=16).hexdigest()


def _read_green_digit(crop, bank):
    import kredits_templates as kt
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h, s, v = (hsv[:, :, i] for i in range(3))
    red = (s >= 120) & (v >= 90) & ((h <= 12) | (h >= 170))
    green = (s >= 120) & (v >= 90) & (h >= 35) & (h <= 85)
    # Match the original mask's excluded plate rim. No participating red or
    # mixed ink may gain a new approval through this green-buff path.
    for ink in (red, green):
        ink[:2] = 0; ink[-2:] = 0; ink[:, :3] = 0; ink[:, -3:] = 0
    if np.any(red) or not np.any(green):
        return None
    mask = green.astype(np.uint8) * 255
    ys, xs = np.where(mask > 0)
    if len(xs) < 50 or len(xs) > .42 * mask.size:
        return None
    gh, gw = int(ys.max()-ys.min()+1), int(xs.max()-xs.min()+1)
    if not (12 <= gh <= 25 and 5 <= gw <= 22
            and abs((xs.min()+xs.max())/2-mask.shape[1]/2) <= 5
            and abs((ys.min()+ys.max())/2-mask.shape[0]/2) <= 5):
        return None
    glyph = kt.normalize_glyph(mask)
    scores = sorted(((digit, max(kt.score_against(glyph, template) for template in templates))
                     for digit, templates in bank.items()), key=lambda item:item[1], reverse=True)
    if len(scores) < 2:
        return None
    return {"digit": scores[0][0], "score": float(scores[0][1]),
            "margin": float(scores[0][1]-scores[1][1])}


def _residual_digit(frame, box, bank):
    x, y, w, h = box
    raw = _read_green_digit(frame[y:y+h, x:x+w], bank)
    if raw is None:
        return False
    mx, my = np.meshgrid(np.arange(x, x+w, dtype=np.float32),
                         np.arange(y, y+h, dtype=np.float32))
    passing = set()
    for dy in OFFSETS:
        for dx in OFFSETS:
            read = _read_green_digit(cv2.remap(frame, mx+dx, my+dy, cv2.INTER_LINEAR), bank)
            if read is not None and read["score"] >= SCORE_MIN and read["margin"] >= DIGIT_MARGIN_MIN:
                passing.add(read["digit"])
    return passing == {raw["digit"]}


class GreenStatAdapter:
    def __init__(self, board):
        self.board = board
        self.original = board.stat_boxes
        self.callback = self.stat_boxes
        self.clear()

    def clear(self):
        self._frame = None
        self._info = self._source_hash = None
        self._diagnostic_tainted = False
        self._diagnostic_boxes = set()
        self._diagnostic_truncated = False

    def register(self, frame, info=None):
        # Capture registration scopes diagnostics only. Metadata/counters are
        # deliberately absent from the pixel decision and add no authority.
        self.clear()
        if (_valid(frame) and isinstance(info, dict)
                and all(type(info.get(key)) is int for key in FIELDS)
                and all(info[key] >= 0 for key in FIELDS[:3])
                and all(info[key] > 0 for key in FIELDS[3:])):
            self._frame = frame
            self._info = {key: info[key] for key in FIELDS}
            self._source_hash = _pixel_hash(frame)

    def _registration_current(self):
        if self._frame is None or self._diagnostic_tainted:
            return False
        if not _valid(self._frame) or _pixel_hash(self._frame) != self._source_hash:
            self._diagnostic_tainted = True
            self._diagnostic_boxes.clear()
            self._diagnostic_truncated = False
            return False
        return True

    def _remember(self, frame, box):
        if frame is not self._frame or not self._registration_current() or box in self._diagnostic_boxes:
            return
        if len(self._diagnostic_boxes) < DIAGNOSTIC_LIMIT:
            self._diagnostic_boxes.add(box)
        else:
            self._diagnostic_truncated = True

    def diagnostics(self):
        current = self._registration_current()
        return {"frame_id": self._info["frame_id"] if self._info is not None else None,
                "capture": dict(self._info) if self._info is not None else None,
                "source_hash": self._source_hash,
                "registered_frame_consistent": current,
                "recovered_plate_count": len(self._diagnostic_boxes),
                "recovered_plate_boxes": [list(box) for box in sorted(self._diagnostic_boxes)],
                "truncated": self._diagnostic_truncated}

    def uninstall(self):
        # An unrelated later wrapper must never be overwritten during cleanup.
        if self.board.stat_boxes is self.callback:
            self.board.stat_boxes = self.original
        if getattr(self.board, OWNER_ATTRIBUTE, None) is self:
            delattr(self.board, OWNER_ATTRIBUTE)
        self.clear()

    def stat_boxes(self, frame, field=None):
        board = self.board
        field = _field(board.FIELD if field is None else field)
        if not _valid(frame) or field is None:
            return []
        original = self.original(frame, field)
        x0, y0, x1, y1 = field
        if y0 > SUPPORT_STAT_Y[1] or y1 < SUPPORT_STAT_Y[0]:
            return original
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        dark = (hsv[:, :, 2] < board.STAT_DARK_V).astype(np.uint8)
        keep = np.zeros_like(dark); keep[y0:y1, x0:x1] = 1; dark &= keep
        _, _, stats, _ = cv2.connectedComponentsWithStats(dark, 8)
        recovered, bank = [], None
        for x, y, w, h, area in stats[1:]:
            x, y, w, h, area = (int(value) for value in (x, y, w, h, area))
            box = (x, y, w, h)
            # Original accepted boxes take their original path without a new
            # glyph call, score or type test.
            if box in original:
                continue
            if not (SUPPORT_STAT_Y[0] <= y and y+h <= SUPPORT_STAT_Y[1]
                    and board.STAT_SIZE[0] <= w <= board.STAT_SIZE[1]
                    and board.STAT_SIZE[0] <= h <= board.STAT_SIZE[1]
                    and area >= .55*w*h and _inside_with_donors(box, field)):
                continue
            crop = hsv[y:y+h, x:x+w]
            if int(((crop[:, :, 2] > board.STAT_BRIGHT_V) & (crop[:, :, 1] < 120)).sum()) >= board.STAT_BRIGHT_MIN:
                continue
            type_boxes = [candidate for candidate in original
                          if abs(candidate[1]-y) <= 5
                          and 27 <= abs(candidate[0]+candidate[2]/2-x-w/2) <= 40
                          and _inside_with_donors(candidate, field)
                          and board._type_stat_plate(frame, candidate)]
            if len(type_boxes) != 1:
                continue
            if bank is None:
                import kredits_templates as kt
                bank = kt.build_templates()
            if not _residual_digit(frame, box, bank):
                continue
            recovered.append(box)
            self._remember(frame, box)
        return sorted(set((*original, *recovered)), key=lambda box:(box[1], box[0])) if recovered else original


def install(board=None):
    if board is None:
        import mobile_board as board
    previous = getattr(board, OWNER_ATTRIBUTE, None)
    if previous is not None and getattr(previous, "board", None) is board:
        previous.uninstall()
    adapter = GreenStatAdapter(board)
    board.stat_boxes = adapter.callback
    setattr(board, OWNER_ATTRIBUTE, adapter)
    return adapter
