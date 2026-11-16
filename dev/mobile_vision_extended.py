import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

import mobile_vision_bench as base

ASSETS = base.ASSETS
PYTHON = base.PYTHON
REAL = (
    ('atlas', base.ROOT / 'mobile/source/android-app/app/src/main/python/deploy-fixtures/blueprint-aircraft-atlas.png'),
    ('promo', ASSETS / 'match-entry/home_promo.png'),
)
SIGMAS = (0, 8, 16, 32, 48)
DELTAS = (-30, 0, 30)


def frames():
    out = []
    index = 0
    for bg_name, path in REAL:
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image.shape[:2] != (720, 1280):
            image = cv2.resize(image, (1280, 720))
        for sigma in SIGMAS:
            for delta in DELTAS:
                rng = np.random.default_rng(20261110 + index)
                index += 1
                frame = image.copy()
                if sigma:
                    frame = np.clip(frame.astype(np.int16)
                                    + rng.normal(0, sigma, frame.shape), 0, 255).astype(np.uint8)
                if delta:
                    frame = np.clip(frame.astype(np.int16) + delta, 0, 255).astype(np.uint8)
                out.append((dict(bg=bg_name, sigma=sigma, delta=delta), frame))
    return out


def timed(fn, repeat):
    samples = []
    for _ in range(repeat):
        start = time.perf_counter()
        value = fn()
        samples.append((time.perf_counter() - start) * 1000)
    return statistics.median(samples), value


def detector_bench(data):
    old = base.original_module('old_page_detector_ext',
                               'mobile/source/android-app/app/src/main/python/apk_native/page_detector.py')
    new = base.current_module('new_page_detector_ext', PYTHON / 'page_detector.py')
    names = ('defeat_banner', 'defeat_btn', 'victory_btn', 'mulligan_ok_btn',
             'mulligan_ok_btn_compact', 'end_turn_btn', 'end_turn_btn_white',
             'opponent_compact', 'opponent_standard', 'queue_cancel', 'home_play',
             'home_tasks', 'home_play_selected', 'battle_selected',
             'training_unselected', 'detail_start')
    template = cv2.imread(str(ASSETS / 'mulligan-one-shot' / 'mulligan_ok_btn.png'), cv2.IMREAD_COLOR)
    bank = {name: template for name in names}
    instances = {label: module.Detector(bank, 'filtered', refine=True)
                 for label, module in (('old', old), ('new', new))}
    rows = []
    for meta, frame in data:
        times, outputs = {}, {}
        for label, detector in instances.items():
            elapsed, output = timed(lambda: detector.observe(frame), 2)
            times[label] = elapsed
            outputs[label] = dict(output)
        outputs['old'].pop('timings_ms', None)
        outputs['new'].pop('timings_ms', None)
        rows.append(dict(meta, old=times['old'], new=times['new'],
                         equal=outputs['old'] == outputs['new']))
    return rows


def objects_bench(data):
    old = base.original_module('old_native_objects_ext',
                               'mobile/source/android-app/app/src/main/python/apk_native/native_objects.py')
    new = base.current_module('new_native_objects_ext', PYTHON / 'native_objects.py')
    rng = np.random.default_rng(7)
    bank = {name: rng.integers(0, 256, (24, 24, 3), dtype=np.uint8) for name in old.TYPES}
    instances = {label: module.Objects(bank) for label, module in (('old', old), ('new', new))}
    rows = []
    for meta, frame in data:
        times, outputs = {}, {}
        for label, objects in instances.items():
            elapsed, output = timed(lambda: objects.inspect(frame), 3)
            times[label] = elapsed
            outputs[label] = output
        equal = len(outputs['old']) == len(outputs['new']) and all(
            a['box'] == b['box'] and a['type'] == b['type'] and abs(a['score'] - b['score']) < 1e-6
            for a, b in zip(outputs['old'], outputs['new']))
        rows.append(dict(meta, old=times['old'], new=times['new'], equal=equal))
    return rows


def guards_bench(data):
    old = base.original_module('old_native_guard_ext',
                               'mobile/source/android-app/app/src/main/python/apk_native/native_guard.py')
    new = base.current_module('new_native_guard_ext', PYTHON / 'native_guard.py')
    rng = np.random.default_rng(13)
    bank = {name: rng.integers(0, 256, (22, 22, 3), dtype=np.uint8)
            for name in ('guard_unit', 'guard_hq')}
    instances = {label: module.Guards(bank) for label, module in (('old', old), ('new', new))}
    box = [400, 300, 120, 160]

    class Features:
        def __init__(self, gray):
            self.gray = gray

        def get(self, name):
            return self.gray

    rows = []
    for meta, frame in data:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        features = Features(gray)
        times, outputs = {}, {}
        for label, guards in instances.items():
            elapsed, output = timed(lambda: guards.inspect(frame, box, features), 3)
            times[label] = elapsed
            outputs[label] = output
        rows.append(dict(meta, old=times['old'], new=times['new'],
                         equal=outputs['old'] == outputs['new']))
    return rows


def report(name, rows):
    old = sum(r['old'] for r in rows)
    new = sum(r['new'] for r in rows)
    equal = sum(r['equal'] for r in rows)
    print('%s_frames=%d old_total_ms=%.3f new_total_ms=%.3f ratio=%.3f equal=%d/%d'
          % (name, len(rows), old, new, old / new, equal, len(rows)))
    groups = defaultdict(list)
    for row in rows:
        groups['bg=' + row['bg']].append(row)
        groups['sigma=' + str(row['sigma'])].append(row)
        groups['delta=' + str(row['delta'])].append(row)
    for tag in sorted(groups):
        part = groups[tag]
        o, n = sum(r['old'] for r in part), sum(r['new'] for r in part)
        print('%s_GROUP|%s|frames=%d|old_ms=%.3f|new_ms=%.3f|ratio=%.3f|equal=%d'
              % (name.upper(), tag, len(part), o, n, o / n, sum(r['equal'] for r in part)))
    return dict(frames=len(rows), old_total_ms=round(old, 3), new_total_ms=round(new, 3),
                ratio=round(old / new, 3), equal=equal)


def main():
    data = frames()
    result = {name: report(name, fn(data))
              for name, fn in (('detector', detector_bench), ('objects', objects_bench),
                              ('guards', guards_bench))}
    if '--json' in sys.argv:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
