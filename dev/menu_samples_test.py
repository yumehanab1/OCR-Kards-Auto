"""Regression check for the KARDS start-menu state machine on real screenshots.

Point KARDS_SAMPLES at a directory of 2340x1080 menu screenshots (the files keep
their descriptive Chinese names) and run:

    python dev/menu_samples_test.py

It prints one JSON row per image: the detected state, the action targets, and the
selected-row evidence. A correct run maps the "开始页" to deck_list and the
"选择训练模式" page to mode_menu, with the orange-pixel counts on the expected row.
"""
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[1]
ANDROID = REPO / 'mobile' / 'source' / 'android-app' / 'app' / 'src' / 'main'
sys.path.insert(0, str(ANDROID / 'python'))

from apk_native.menu import NativeMenuRecognizer  # noqa: E402

ASSETS = ANDROID / 'assets' / 'match-entry'
SAMPLES = Path(os.environ.get('KARDS_SAMPLES', REPO / 'dev' / 'samples'))


def main():
    if not SAMPLES.is_dir():
        raise SystemExit('set KARDS_SAMPLES to the screenshot directory')
    observer = NativeMenuRecognizer(str(ASSETS), None)
    for path in sorted(SAMPLES.glob('*/*.jpg')) + sorted(SAMPLES.glob('*.jpg')):
        frame = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            print(json.dumps({'file': path.name, 'state': 'unreadable'}, ensure_ascii=False))
            continue
        height, width = frame.shape[:2]
        result = observer.observe(frame, {'coordinate_space': 'source_pixels',
                                          'source_width': width, 'source_height': height})
        color = (result.get('evidence') or {}).get('standard_mode_color') or {}
        print(json.dumps({
            'file': path.name[:40],
            'state': result.get('state'),
            'targets': sorted((result.get('targets') or {}).keys()),
            'profile': result.get('layout_profile'),
            'selected': color.get('selected_tab'),
            'orange_battle': (color.get('battle') or {}).get('orange_pixels'),
            'orange_training': (color.get('training') or {}).get('orange_pixels'),
        }, ensure_ascii=False))


if __name__ == '__main__':
    main()
