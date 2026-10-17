"""Orange hover digit calibration A/B. Offline files only; no OCR or game input.

Use --template logs/5_hover_20261017.png before installing a reviewed sample.
An 8_hover_*.png template compares the existing 5 support with added 8 support.
--full-corpus also checks every retained local fee frame in the listed sources.
"""
from pathlib import Path
from unittest.mock import patch
import argparse
import hashlib
import json
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import cv2
import numpy as np
import hand_cost_filter as hcf
from kredits_templates import normalize_glyph

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_NAME = '5_hover_20261017.png'
LABELLED = [
    ('logs/pc_speed_fix2b_20261017_132651/profile_01_hover_cost_mismatch.png',
     dict(x=412, y=341, w=17, h=25), 'F4U-1C 海盗', 5),
    ('logs/pc_speed_fix2b_20261017_132651/profile_02_hover_cost_mismatch.png',
     dict(x=533, y=325, w=17, h=24), 'A-26 入侵者', 5),
    ('logs/pc_speed_fix3_20261017_134702/profile_01_hover_cost_mismatch.png',
     dict(x=406, y=347, w=18, h=24), 'B-17 飞行堡垒', 8),
]


def banks(extra):
    digit_added = int(extra.stem.split('_')[0])
    sample_name = f'{digit_added}_hover_20261017.png'
    base = {}
    old = {}
    for path in sorted((ROOT / 'config/hand_cost_digits').glob('[0-9]*.png')):
        if path.name == sample_name:
            continue
        digit = int(path.stem.split('_')[0])
        normalized = normalize_glyph(cv2.imread(str(path), cv2.IMREAD_GRAYSCALE))
        if normalized is not None:
            old.setdefault(digit, []).append(normalized)
            if '_hover_' not in path.stem:
                base.setdefault(digit, []).append(normalized)
    new = {digit: list(templates) for digit, templates in old.items()}
    normalized = normalize_glyph(cv2.imread(str(extra), cv2.IMREAD_GRAYSCALE))
    assert normalized is not None, 'Missing or invalid reviewed hover template: ' + str(extra)
    new.setdefault(digit_added, []).append(normalized)
    return base, old, new


def read(frame, candidate, bank, *, enlarged=False, legacy_bank=None):
    candidate = dict(candidate)
    def select_bank(*, enlarged=False):
        return bank if enlarged else (legacy_bank if legacy_bank is not None else bank)
    with patch.object(hcf, '_normalized_templates', side_effect=select_bank):
        value = hcf.read_candidate_cost(frame, candidate, enlarged=enlarged)
    return value, candidate.get('digit_scores', {})


def rotated_cases(base, old, new):
    rows = []
    for path in sorted((ROOT / 'config/hand_cost_digits').glob('[0-9]*.png')):
        digit = int(path.stem.split('_')[0])
        template = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        enlarged = '_hover_' in path.stem
        for angle in (-24, -18, -9, 0, 9, 18, 24):
            mask = cv2.copyMakeBorder(template, 20, 20, 20, 20, cv2.BORDER_CONSTANT)
            height, width = mask.shape
            rotated = cv2.warpAffine(mask, cv2.getRotationMatrix2D(
                (width / 2, height / 2), angle, 1), (width, height),
                flags=cv2.INTER_NEAREST)
            ys, xs = np.where(rotated > 0)
            tight = rotated[ys.min():ys.max()+1, xs.min():xs.max()+1]
            frame = np.zeros((720, 1280, 3), np.uint8)
            height, width = tight.shape
            y = 330 if enlarged else 630
            frame[y:y+height, 500:500+width][tight > 0] = (0, 150, 230)
            candidate = dict(x=500, y=y, w=width, h=height)
            before, _ = read(frame, candidate, old if enlarged else base,
                             enlarged=enlarged, legacy_bank=base)
            after, scores = read(frame, candidate, new if enlarged else base,
                                 enlarged=enlarged, legacy_bank=base)
            assert after in (None, digit), (path.name, angle, before, after, scores)
            if before is not None:
                assert after == before, (path.name, angle, before, after, scores)
            if angle == 0:
                assert after == digit, (path.name, angle, after, scores)
            rows.append(dict(sample=path.name, angle=angle, before=before, after=after))
    return rows


def real_cases(base, old, new, paths, digit_added):
    rows, seen, frames = [], set(), 0
    for path in paths:
        if not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        frame = cv2.imread(str(path))
        if frame is None or frame.shape[:2] != (720, 1280):
            continue
        frames += 1
        candidates = [(candidate, False) for candidate in hcf.candidates(frame)]
        candidates += [(candidate, True) for candidate in hcf.candidates(
            frame, zone=(340, 250, 960, 600), height_range=(20, 50))]
        for candidate, enlarged in candidates:
            before, old_scores = read(frame, candidate, old if enlarged else base,
                                      enlarged=enlarged, legacy_bank=base)
            after, new_scores = read(frame, candidate, new if enlarged else base,
                                     enlarged=enlarged, legacy_bank=base)
            row = dict(path=str(path), box=[candidate[k] for k in ('x','y','w','h')],
                       enlarged=enlarged, before=before, after=after,
                       old_scores=old_scores, new_scores=new_scores)
            if before is not None:
                assert after == before, ('Known real-frame digit changed', row)
            elif after is not None:
                assert after == digit_added, ('Unexpected newly accepted digit', row)
            rows.append(row)
    return dict(frames=frames, candidates=rows,
                previously_known=sum(r['before'] is not None for r in rows),
                newly_accepted=[r for r in rows if r['before'] is None and r['after'] == digit_added],
                newly_accepted_fives=[r for r in rows if r['before'] is None and r['after'] == 5])


def corpus(full):
    paths = [ROOT / rel for rel, _, _, _ in LABELLED]
    paths += sorted((ROOT / 'shots/orange_hover_roi_20261016').glob('*.png'))
    paths += [ROOT / 'shots/orange_pc_20261013' / name
              for name in ('neutral.png', 'check.png', 'hover640.png', 'hover722.png')]
    paths += sorted((ROOT / 'logs/pc_speed_fix1_20261017_131846').glob('*.png'))
    if full:
        paths += sorted((ROOT / 'shots/orange_pc_20261013').rglob('*.png'))
        paths += sorted((ROOT / 'logs/orange_speed_20261016_frames').glob('*.png'))
        for directory in sorted((ROOT / 'logs').glob('pc_speed_*')):
            if directory.is_dir():
                paths += sorted(directory.glob('*.png'))
        desktop = Path.home() / 'Desktop/kards-auto-repo/shots'
        for name in ('scan_frames', 'deploy_drag'):
            paths += sorted((desktop / name).glob('*.png'))
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--template', type=Path, default=ROOT / 'config/hand_cost_digits' / SAMPLE_NAME)
    parser.add_argument('--full-corpus', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    start = time.perf_counter()
    digit_added = int(args.template.stem.split('_')[0])
    base, old, new = banks(args.template)
    labelled = []
    for rel, candidate, name, expected in LABELLED:
        path = ROOT / rel
        if not path.is_file():
            continue
        frame = cv2.imread(str(path))
        before, old_scores = read(frame, candidate, old, enlarged=True, legacy_bank=base)
        after, new_scores = read(frame, candidate, new, enlarged=True, legacy_bank=base)
        if expected == digit_added or expected in old:
            assert after == expected, (name, before, after, new_scores)
        else:
            assert after is None, (name, before, after, new_scores)
        labelled.append(dict(path=rel, card=name, before=before, after=after,
                             expected=expected, old_scores=old_scores, new_scores=new_scores))
    rotation = rotated_cases(base, old, new)
    real = real_cases(base, old, new, corpus(args.full_corpus), digit_added)
    # Known orange artwork fragment must stay unresolved even with a real 5.
    art_path = ROOT / 'logs/pc_speed_fix1_20261017_131846/profile_01_hover_cost_mismatch.png'
    if art_path.is_file():
        assert read(cv2.imread(str(art_path)), dict(x=653,y=480,w=13,h=25), new,
                    enlarged=True, legacy_bank=base)[0] is None
    production = []
    installed = ROOT / 'config/hand_cost_digits' / f'{digit_added}_hover_20261017.png'
    if installed.is_file() and args.template.resolve() == installed.resolve():
        assert len(hcf._templates(enlarged=True)[digit_added]) == len(hcf._templates(enlarged=False).get(digit_added, [])) + 1
        for rel, candidate, name, expected in LABELLED:
            if expected != digit_added:
                continue
            path = ROOT / rel
            if not path.is_file():
                continue
            frame = cv2.imread(str(path))
            base = hcf.read_candidate_cost(frame, dict(candidate))
            enlarged = dict(candidate)
            value = hcf.read_candidate_cost(frame, enlarged, enlarged=True)
            assert base is None and value == expected, (name, base, value, enlarged)
            assert enlarged['digit_profile'] == 'hover_supplement'
            production.append(dict(card=name, base=base, enlarged=value,
                                   profile=enlarged['digit_profile']))
    result = dict(template=str(args.template), template_sha256=hashlib.sha256(args.template.read_bytes()).hexdigest(),
                  threshold_score=.72, threshold_margin=.10, ocr=False, input_or_capture=False,
                  policy='Keep a confident original-bank result; consult hover supplements only after original-bank rejection. A globally merged hover 5 otherwise invalidates accepted fan and hover 6 readings by reducing their lead.',
                  digit_added=digit_added, elapsed_s=time.perf_counter()-start, labelled=labelled,
                  rotated=rotation, real=real, production=production)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(passed=True, digit_added=digit_added, labelled_cases=len(labelled), rotations=len(rotation),
        real_frames=real['frames'], real_candidates=len(real['candidates']),
        unchanged_known=real['previously_known'], newly_accepted=len(real['newly_accepted']),
        elapsed_s=result['elapsed_s']), ensure_ascii=False))


if __name__ == '__main__':
    main()
