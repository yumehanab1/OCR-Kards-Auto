"""Latency and correctness bench for the KARDS menu recognizer on real screenshots.

    python dev/menu_bench.py            # timing + verdict per sample
    python dev/menu_bench.py --profile   # cProfile hot spots for one sample
"""
import cProfile
import json
import os
import pstats
import sys
import time
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[1]
ANDROID = REPO / 'mobile' / 'source' / 'android-app' / 'app' / 'src' / 'main'
sys.path.insert(0, str(ANDROID / 'python'))
sys.path.insert(0, str(ANDROID / 'assets' / 'mobile-core' / 'src'))

from apk_native.menu import NativeMenuRecognizer  # noqa: E402

ASSETS = ANDROID / 'assets' / 'match-entry'
SAMPLES = Path(os.environ.get('KARDS_SAMPLES', REPO / 'dev' / 'samples'))

EXPECTED = {
    '训练模式': 'mode_menu',
    '点击开始': 'deck_list',
    '浮窗（休闲）': 'deck_ready',
    '浮窗（排位）': 'deck_ready',
    '首页': 'home',
}


def expected_state(name):
    for key, state in EXPECTED.items():
        if key in name:
            return state
    return None


def load(path):
    return cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)


def run(profile=False):
    paths = sorted(SAMPLES.glob('*/*.jpg')) + sorted(SAMPLES.glob('*.jpg'))
    rows, times, warm_times, correct, checked = [], [], [], 0, 0
    for path in paths:
        frame = load(path)
        if frame is None:
            continue
        height, width = frame.shape[:2]
        packet = {'coordinate_space': 'source_pixels', 'source_width': width,
                  'source_height': height}
        # Cold: a fresh recognizer, exactly what a page change costs in a session.
        observer = NativeMenuRecognizer(str(ASSETS), None)
        started = time.perf_counter()
        result = observer.observe(frame, packet)
        elapsed = (time.perf_counter() - started) * 1000
        times.append(elapsed)
        # Warm: the same unchanged frame observed again.
        started = time.perf_counter()
        observer.observe(frame, packet)
        warm_times.append((time.perf_counter() - started) * 1000)
        want = expected_state(path.name)
        got = result.get('state')
        if want:
            checked += 1
            correct += int(got == want)
        rows.append((round(elapsed), got, want or '-', path.name[:34]))
        if profile:
            profiler = cProfile.Profile()
            profiler.enable()
            observer.observe(frame, packet)
            profiler.disable()
            pstats.Stats(profiler).sort_stats('cumulative').print_stats(18)
            break
    for row in rows:
        print('{:>5}ms  {:<12} want={:<11} {}'.format(*row))
    if times:
        print('samples={} cold_median={:.0f}ms cold_p90={:.0f}ms warm_median={:.1f}ms acc={}/{}'.format(
            len(times), float(np.median(times)), float(np.percentile(times, 90)),
            float(np.median(warm_times)), correct, checked))


if __name__ == '__main__':
    run('--profile' in sys.argv)
