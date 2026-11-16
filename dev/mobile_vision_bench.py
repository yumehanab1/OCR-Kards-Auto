import importlib.util
import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
BASE = 'f9dfc0e'
PYTHON = ROOT / 'mobile/source/android-app/app/src/main/python/apk_native'
ASSETS = ROOT / 'mobile/source/android-app/app/src/main/assets'


def original_module(name, relative):
    source = subprocess.run(['git', 'show', f'{BASE}:{relative}'], cwd=ROOT,
                            capture_output=True, check=True).stdout.decode('utf8')
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / (name + '.py')
        path.write_text(source, encoding='utf8')
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


def current_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def frame(rng, bright=False):
    h, w = 720, 1280
    yy, xx = np.mgrid[0:h, 0:w]
    lift = 120 if bright else 0
    image = np.stack([20 + lift + (yy * .04), 28 + lift + (xx * .02),
                      36 + lift + ((yy + xx) * .008)], axis=2).astype(np.uint8)
    image = np.clip(image.astype(np.int16) + rng.integers(0, 20, (h, w, 1)), 0, 255).astype(np.uint8)
    for _ in range(40):
        x, y = int(rng.integers(0, w - 120)), int(rng.integers(0, h - 60))
        bw, bh = int(rng.integers(30, 160)), int(rng.integers(12, 50))
        color = (int(rng.integers(150, 255)), int(rng.integers(120, 220)), 40) if not bright else (20, 30, 40)
        cv2.rectangle(image, (x, y), (x + bw, y + bh), color, -1)
    return image


def measure(fn, repeat):
    samples = []
    for _ in range(repeat):
        start = time.perf_counter()
        value = fn()
        samples.append((time.perf_counter() - start) * 1000)
        result = value
    return statistics.median(samples), result


def detector_bench():
    old = original_module('old_page_detector', 'mobile/source/android-app/app/src/main/python/apk_native/page_detector.py')
    new = current_module('new_page_detector', PYTHON / 'page_detector.py')
    templates = {}
    for name in ('mulligan_ok_btn.png', 'end_turn_btn.png', 'mulligan_title.png'):
        templates[name] = cv2.imread(str(ASSETS / 'mulligan-one-shot' / name), cv2.IMREAD_COLOR)
    names = ('defeat_banner', 'defeat_btn', 'victory_btn', 'mulligan_ok_btn',
             'mulligan_ok_btn_compact', 'end_turn_btn', 'end_turn_btn_white',
             'opponent_compact', 'opponent_standard', 'queue_cancel', 'home_play',
             'home_tasks', 'home_play_selected', 'battle_selected',
             'training_unselected', 'detail_start')
    bank = {name: templates['mulligan_ok_btn.png'] for name in names}
    rng = np.random.default_rng(20261106)
    frames = [frame(rng) for _ in range(6)]
    for mode in ('filtered', 'full'):
        results = {}
        times = {}
        for label, module in (('old', old), ('new', new)):
            detector = module.Detector(bank, mode, refine=True)
            samples = []
            for image in frames:
                elapsed, output = measure(lambda: detector.observe(image), 2)
                samples.append(elapsed)
                results.setdefault(label, []).append(output)
            times[label] = statistics.median(samples)
        print(f'detector_{mode}_old_median_ms={times["old"]:.3f}')
        print(f'detector_{mode}_new_median_ms={times["new"]:.3f}')
        print(f'detector_{mode}_ratio={times["old"] / times["new"]:.3f}')
        for a, b in zip(results['old'], results['new']):
            a.pop('timings_ms', None)
            b.pop('timings_ms', None)
            assert a == b, 'detector output differs'
        print(f'detector_{mode}_output_equal=6/6')


def objects_bench():
    old = original_module('old_native_objects', 'mobile/source/android-app/app/src/main/python/apk_native/native_objects.py')
    new = current_module('new_native_objects', PYTHON / 'native_objects.py')
    rng = np.random.default_rng(7)
    bank = {name: rng.integers(0, 256, (24, 24, 3), dtype=np.uint8) for name in old.TYPES}
    image = frame(np.random.default_rng(11), bright=True)
    for _ in range(30):
        x, y = int(rng.integers(0, 1240)), int(rng.integers(0, 680))
        cv2.rectangle(image, (x, y), (x + 30, y + 30), (8, 8, 8), -1)
    times = {}
    outputs = {}
    for label, module in (('old', old), ('new', new)):
        objects = module.Objects(bank)
        elapsed, output = measure(lambda: objects.inspect(image), 40)
        times[label] = elapsed
        outputs[label] = output
    print(f'objects_old_median_ms={times["old"]:.3f}')
    print(f'objects_new_median_ms={times["new"]:.3f}')
    print(f'objects_ratio={times["old"] / times["new"]:.3f}')
    print(f'objects_items_old={len(outputs["old"])} new={len(outputs["new"])}')
    assert len(outputs['old']) == len(outputs['new'])
    for a, b in zip(outputs['old'], outputs['new']):
        assert a['box'] == b['box'] and a['type'] == b['type']
        assert abs(a['score'] - b['score']) < 1e-6
    print('objects_output_equal=1/1')


def guards_bench():
    old = original_module('old_native_guard', 'mobile/source/android-app/app/src/main/python/apk_native/native_guard.py')
    new = current_module('new_native_guard', PYTHON / 'native_guard.py')
    rng = np.random.default_rng(13)
    bank = {name: rng.integers(0, 256, (22, 22, 3), dtype=np.uint8)
            for name in ('guard_unit', 'guard_hq')}
    image = frame(np.random.default_rng(17))
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    class Features:
        def get(self, name):
            return gray

    box = [400, 300, 120, 160]
    times = {}
    outputs = {}
    for label, module in (('old', old), ('new', new)):
        guards = module.Guards(bank)
        elapsed, output = measure(lambda: guards.inspect(image, box, Features()), 60)
        times[label] = elapsed
        outputs[label] = output
    print(f'guards_old_median_ms={times["old"]:.3f}')
    print(f'guards_new_median_ms={times["new"]:.3f}')
    print(f'guards_ratio={times["old"] / times["new"]:.3f}')
    assert outputs['old'] == outputs['new'], 'guards output differs'
    print('guards_output_equal=1/1')


if __name__ == '__main__':
    detector_bench()
    objects_bench()
    guards_bench()
