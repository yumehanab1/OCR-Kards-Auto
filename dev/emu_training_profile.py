"""Optional local Route B first-turn profile. No ADB, input, or mutable recognition database.

The caller must bind the two operator-reviewed empty-row captures to this training
session. They can veto/confirm only the existing outer-slot geometry. A card
requires an exact, spatially paired unit title as well as the normal unit markers.
"""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import re
from types import SimpleNamespace

import cv2
import numpy as np

from emu_battle_pilot import Vision, Halt, match

UNIT_TYPES = {'tank', 'infantry', 'fighter', 'bomber', 'artillery'}


def overlaps(a, b):
    return max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3])


def same_patch(a, b, *, mean_limit, fraction_limit, tile_limit):
    if a.shape != b.shape or a.size == 0:
        return False
    delta = cv2.absdiff(a, b)
    return (float(delta.mean()) <= mean_limit and float((delta.max(axis=2) > 16).mean()) <= fraction_limit
            and all(float(tile.mean()) <= tile_limit for row in np.array_split(delta, 3, axis=0)
                    for tile in np.array_split(row, 4, axis=1)))


class ReviewedSurface:
    def __init__(self, native, frames):
        self.native = native
        self._row = native._row
        if len(frames) != 2:
            raise Halt('two_reviewed_first_turn_frames_required')
        self.frames, self.excluded = frames, []
        for frame in frames:
            cards, why, row = self._row(frame)
            if (why != 'complete_support_row' or cards is None or len(cards) != 1 or row['units']
                    or abs(row['hq']['cx'] - 640) > 8 or row['frontline']['owner'] != 'empty'):
                raise Halt('reference_is_not_empty_own_support')
            self.excluded.extend(row['bounds'])

    def slot_matches(self, current, box):
        x0, y0, x1, y1 = box
        if not (310 <= x0 < x1 <= 1000 and (x1-x0, y0, y1) == (116, 435, 580)):
            return False
        if any(overlaps(box, occupied) for occupied in self.excluded):
            return False
        patch = current[y0:y1, x0:x1]
        for ref in self.frames:
            bg = ref[y0:y1, x0:x1]
            if (cv2.cvtColor(bg, cv2.COLOR_BGR2GRAY).std() < 4 or
                    not same_patch(bg, patch, mean_limit=3., fraction_limit=.005, tile_limit=5.)):
                return False
        return True

    def choose_drop(self, frame):
        # Let the original recognizer handle its known backgrounds. Only one
        # specific rejection can be resolved by this session's visual evidence.
        r = self.native.choose_drop(frame)
        if r['reason'] != 'no_confirmed_clear_outer_support_slot' or r['point']:
            return r
        row = r['evidence']['row']
        if not row['centers'] or len(row['units']) >= 4:
            return r
        for c in r['evidence']['candidates']:
            if c['reason'] != 'background_profile_not_confirmed':
                continue
            box = c['patch']
            if any(overlaps(box, a) for a in row['bounds']) or not self.slot_matches(frame, box):
                continue
            r['evidence']['reviewed_first_turn_patch'] = box
            r.update(point=c['point'], reason='observed_clear_outer_support_slot')
            break
        return r


class UnitTitles:
    def __init__(self, rows, ocr):
        types = defaultdict(set)
        for c in rows:
            item = c['json']
            name = self.norm(item.get('title', {}).get('zh-Hans', ''))
            if name:
                types[name].add(item.get('type'))
        self.units = {k for k, v in types.items() if len(k) >= 3 and v and v <= UNIT_TYPES}
        self.ocr = ocr
        self.samples = []
        self.last = None

    @staticmethod
    def norm(s):
        return re.sub(r'\s+', '', s).upper()

    def on_frame(self, frame, seen):
        anchors = [tuple(item['anchor']) for item in seen if 'grab' in item]
        if not anchors:
            return {}
        proven = {}
        for ax, ay in anchors:
            for name, dx, dy, img in self.samples:
                x, y = ax + dx, ay + dy
                h, w = img.shape[:2]
                if x < 0 or y < 0 or y+h > 720 or x+w > 1280:
                    continue
                if same_patch(img, frame[y:y+h, x:x+w], mean_limit=1.8, fraction_limit=.006, tile_limit=3.8):
                    proven[(ax, ay)] = name
                    break
        # Repeated unknown text is a veto, never an invitation to re-run OCR
        # forever. Cached positive titles still have to match their visible pixels.
        current = frame[580:720, 200:1110]
        if len(proven) == len(anchors) or (self.last is not None and same_patch(self.last, current, mean_limit=1.4, fraction_limit=.005, tile_limit=3.)):
            return proven
        self.last = current.copy()
        words = self.ocr(current)
        for ax, ay in anchors:
            if (ax, ay) in proven:
                continue
            hits = []
            for z in words:
                name = self.norm(z['text'])
                x, y = round(200+z['x']), round(580+z['y'])
                cx, cy = 200+z['cx'], 580+z['cy']
                w, h = round(z['w']), round(z['h'])
                if not (.95 <= z['conf'] <= 1. and 15 <= cx-ax <= 100 and abs(cy-ay) <= 24
                        and 28 <= w <= 154 and 11 <= h <= 69 and x >= 200 and x+w <= 1110 and y+h <= 720):
                    continue
                # An OCR token joining the printed cost to the title can only
                # lose ONE digit, and must actually start on this cost badge.
                if name not in self.units and -17 <= x-ax <= 6 and re.match(r'^\d[^\d]', name):
                    name = name[1:]
                elif not 12 <= x-ax <= 48:
                    continue
                if name in self.units:
                    hits.append((name, x, y, w, h))
            if len(hits) == 1:
                name, x, y, w, h = hits[0]
                patch = frame[y:y+h, x:x+w]
                if cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY).std() >= 16:
                    self.samples = (self.samples + [(name, x-ax, y-ay, patch.copy())])[-64:]
                    proven[(ax, ay)] = name
        return proven


class RightmostUnitTitles:
    """Optional single-title read for a fully exposed right edge; never reuse OCR.

    The caller still has to check the budget, two separate frames, the outer
    landing and the game effect. Middle or unproved cards produce no candidate.
    """

    def __init__(self, unit_names, ocr):
        self.units, self.ocr = frozenset(unit_names), ocr

    def on_frame(self, frame, seen, plates):
        if frame.shape != (720, 1280, 3) or not plates:
            return {}
        hits = []
        for item in seen:
            if 'grab' not in item or item.get('kind') != 'unit_marker':
                continue
            ax, ay = item['anchor']
            if not (820 <= ax <= 990 and 590 <= ay <= 665 and item['grab'] == [ax+25, ay+25]):
                continue
            if any(other['anchor'][0] > ax+12 for other in seen):
                continue
            if (not any(abs(p['cx']-ax) <= 9 and abs(p['cy']-ay) <= 9 for p in plates)
                    or any(p['cx'] > ax+12 for p in plates)):
                continue
            hits.append((ax, ay))
        if len(hits) != 1:
            return {}
        ax, ay = hits[0]
        words = self.ocr(frame[ay-17:ay+53, ax+10:ax+174])
        if len(words) != 1:
            return {}
        w = words[0]
        name = UnitTitles.norm(w['text'])
        if (name not in self.units or not .98 <= w['conf'] <= 1. or not 1 <= w['x'] <= 38
                or w['y'] < 1 or w['x']+w['w'] >= 163 or w['y']+w['h'] >= 69
                or not 28 <= w['w'] <= 154 or not 11 <= w['h'] <= 65
                or not 25 <= 10+w['cx'] <= 112 or abs(w['cy']-17) > 24):
            return {}
        return {(ax, ay): name}


class TrainingVision(Vision):
    def __init__(self, root, frames, *, card_db, ocr):
        super().__init__(root)
        self.titles = UnitTitles(json.loads(Path(card_db).read_text('utf-8'))['cards'], ocr)
        self.drop = ReviewedSurface(self.drop, frames)
        self._old_foe = self.opponent.inspect_opponent_turn
        self._foe_shape = cv2.resize(self.opponent._template('standard'), (80, 41), interpolation=cv2.INTER_CUBIC)
        self._ocr, self._foe_patch = ocr, None
        self.opponent = SimpleNamespace(inspect_opponent_turn=self.opponent_turn)

    def hands(self, pixels):
        origins, seen = super().hands(pixels)
        approved = self.titles.on_frame(pixels, seen)
        keep = set()
        for item in seen:
            if 'grab' not in item:
                continue
            anchor = tuple(item['anchor'])
            if anchor in approved:
                item['exact_unit_title'] = approved[anchor]
                keep.add(tuple(item['grab']))
            else:
                item.pop('grab')
                item.update(kind='unknown', reason='local_unit_title_not_proved')
        return [p for p in origins if p in keep], seen

    def opponent_turn(self, pixels):
        old = self._old_foe(pixels)
        if old['present']:
            return old
        gray = cv2.cvtColor(pixels, cv2.COLOR_BGR2GRAY)
        edges = [gray[y0:y1, x0:x1] for x0, y0, x1, y1 in (
            (1062,490,1234,491), (1062,539,1234,540), (1057,495,1058,535), (1238,495,1239,535))]
        if min(float((e >= 75).mean()) for e in edges) < .88:
            return old
        score, (x,y,w,h) = match(gray, self._foe_shape, (1104,491,90,49))
        if score < .90:
            return old
        stamp = pixels[490:540,1102:1191]
        if self._foe_patch is None or not same_patch(self._foe_patch, stamp, mean_limit=1.5, fraction_limit=.005, tile_limit=3.):
            words = self._ocr(pixels[482:548,1045:1252])
            if len(words) != 1:
                return old
            t = words[0]
            if not (t['text'].strip() == '敌方' and t['conf'] >= .98 and 92 <= t['cx'] <= 110 and 26 <= t['cy'] <= 40
                    and 69 <= t['w'] <= 110 and 30 <= t['h'] <= 65):
                return old
            self._foe_patch = stamp.copy()
        return dict(present=True, score=score, layout='zh_2714_bordered_exact_enemy', box=(x,y,w,h))
