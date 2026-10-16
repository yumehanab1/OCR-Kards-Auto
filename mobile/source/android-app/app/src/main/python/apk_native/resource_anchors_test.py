"""Saved physical-phone replay and resource-context rejection checks."""
import json
from pathlib import Path
import cv2
import numpy as np
from .resource_anchors import inspect
from .opening import OpeningRecognizer


def run(source, assets):
    frame = cv2.imdecode(np.frombuffer(Path(source).read_bytes(), np.uint8), 1)
    checks = []
    def check(name, valid):
        if not valid:
            raise AssertionError(name)
        checks.append(name)
    h, w = frame.shape[:2]
    packet = dict(coordinate_space='source_pixels', source_height=h, source_width=w)
    observed = OpeningRecognizer(assets).observe(frame, packet)
    check('saved_phone_own_turn', observed['phase'] == 'CONFIRMED_MY_TURN')
    anchors = observed['resource_anchors']
    check('phone_current_pair', anchors['ok'] and anchors['basis'] == 'current_aligned_resource_boxes')
    check('source_coordinates_restored', all(0 < row['bounds'][0] < w*.2
          and row['bounds'][2] > 100 for row in (anchors['own'], anchors['enemy'])))
    for name, box in [('own', anchors['own']['bounds']), ('enemy', anchors['enemy']['bounds'])]:
        x, y, bw, bh = box
        removed = frame.copy()
        removed[max(0,y-10):y+bh+10,max(0,x-10):x+bw+10] = 0
        check('missing_'+name+'_resource', not inspect(removed)['ok'])
    check('black_screen_rejected', not inspect(np.zeros_like(frame))['ok'])

    # Synthetic evidence is independent of any saved screen/template pixel.
    def pair(xs=(108,), missing_side=None, orange=True, shift_bottom=0):
        canvas = np.zeros((720,1584,3), np.uint8)
        for x in xs:
            for i, y in enumerate((130,510)):
                a=x+(shift_bottom if i else 0)
                cv2.rectangle(canvas,(a,y),(a+80,y+80),(210,210,210),2)
                if orange:
                    canvas[y+25:y+45,a+35:a+47]=(0,140,255)
                if missing_side=='top':canvas[y-5:y+8,a-5:a+86]=0
                if missing_side=='left':canvas[y-5:y+86,a-5:a+8]=0
        return canvas
    check('inset_pair_geometry', inspect(pair())['ok'])
    check('missing_top_side_rejected', not inspect(pair(missing_side='top'))['ok'])
    check('missing_left_side_rejected', not inspect(pair(missing_side='left'))['ok'])
    check('empty_frames_rejected', not inspect(pair(orange=False))['ok'])
    check('misaligned_pair_rejected', not inspect(pair(shift_bottom=24))['ok'])
    check('duplicate_pairs_rejected', not inspect(pair(xs=(10,160)))['ok'])
    bare = pair()
    bare[130:212,108:191] = 0
    bare[510:592,108:191] = 0
    bare[155:175,143:155] = (0,140,255)
    bare[535:555,143:155] = (0,140,255)
    check('bare_orange_rejected', not inspect(bare)['ok'])
    return json.dumps(dict(passed=True, scope='saved_lossy_physical_phone_replay_and_generated_negatives',
                           checks=checks, opening=observed, device_inputs=0, captures=0))
