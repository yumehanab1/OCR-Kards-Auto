import json
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

import bench

ASSETS = bench.ROOT / 'mobile/source/android-app/app/src/main/assets'
MULLIGAN = ASSETS / 'mulligan-one-shot'
SELECTED = (bench.CASES[0], bench.CASES[1], bench.CASES[4])
SHORT = ('cf', 'ti', 'et')
REAL = (
    ('atlas', bench.ROOT / 'mobile/source/android-app/app/src/main/python/deploy-fixtures/blueprint-aircraft-atlas.png'),
    ('promo', ASSETS / 'match-entry/home_promo.png'),
)
SIGMAS = (0, 4, 8, 14, 22, 32, 44)
SHIFTS = (-18, 0, 18)
SEEDS = (20261106, 20261107)
SCALES = (90, 110)
OCCLUSIONS = (15, 30, 45)
BLURS = (1, 3)


def backgrounds():
    out = [('synthetic', bench.background(np.random.default_rng(20261108)))]
    for name, path in REAL:
        image = Image.open(path).convert('RGB').resize((1280, 720), Image.Resampling.BILINEAR)
        out.append((name, np.asarray(image)))
    return out


def label_of(**fields):
    return ','.join('%s=%s' % item for item in fields.items())


def emit(work, lines, label, template_file, frame, roi, ex, ey):
    path = work / (label.replace(',', '_').replace('=', '-') + '.bin')
    bench.write_raw(path, bench.as_argb(frame))
    l, t, r, b = roi
    lines.append('%s|%s|%s|%d|%d|%d|%d|%d|%d' % (label, template_file, path.name, l, t, r, b, ex, ey))


def place(frame, rgb, x, y):
    th, tw = rgb.shape[:2]
    frame[y:y + th, x:x + tw] = rgb
    return frame


def position(rng, roi, tw, th):
    l, t, r, b = roi
    max_x, max_y = min(r, 1280) - tw, min(b, 720) - th
    return int(rng.integers(l, max_x + 1)), int(rng.integers(t, max_y + 1))


def prepare(work):
    lines = []
    templates = []
    for (name, filename, roi), short in zip(SELECTED, SHORT):
        rgb = np.asarray(Image.open(MULLIGAN / filename).convert('RGB'))
        path = work / (short + '_template.bin')
        bench.write_raw(path, bench.as_argb(rgb))
        templates.append((short, rgb, roi, path.name))
    bgs = backgrounds()
    for bg_name, bg in bgs:
        for short, rgb, roi, template_file in templates:
            th, tw = rgb.shape[:2]
            for seed in SEEDS:
                rng = np.random.default_rng(seed)
                for sigma in SIGMAS:
                    for shift in SHIFTS:
                        x, y = position(rng, roi, tw, th)
                        frame = bg.copy()
                        patch = np.clip(rgb.astype(np.int16)
                                        + rng.normal(0, sigma, rgb.shape)
                                        + shift, 0, 255).astype(np.uint8)
                        place(frame, patch, x, y)
                        label = label_of(bg=bg_name, tpl=short, s=sigma, h=shift,
                                         c=100, o=0, b=0, d=seed)
                        emit(work, lines, label, template_file, frame, roi, x, y)
            rng = np.random.default_rng(seed + 100)
            for scale in SCALES:
                sw, sh = round(tw * scale / 100), round(th * scale / 100)
                scaled = cv2.resize(rgb, (sw, sh), interpolation=cv2.INTER_LINEAR)
                x, y = position(rng, roi, sw, sh)
                emit(work, lines,
                     label_of(bg=bg_name, tpl=short, s=0, h=0, c=scale, o=0, b=0, d=seed),
                     template_file, place(bg.copy(), scaled, x, y), roi, x, y)
            for occ in OCCLUSIONS:
                x, y = position(rng, roi, tw, th)
                frame = place(bg.copy(), rgb, x, y)
                start, end = x + round(tw * .2), x + round(tw * (.2 + occ / 100))
                frame[y:y + th, start:end] = bg[y:y + th, start:end]
                emit(work, lines,
                     label_of(bg=bg_name, tpl=short, s=0, h=0, c=100, o=occ, b=0, d=seed),
                     template_file, frame, roi, x, y)
            for blur in BLURS:
                x, y = position(rng, roi, tw, th)
                frame = cv2.GaussianBlur(place(bg.copy(), rgb, x, y), (blur * 2 + 1, blur * 2 + 1), 0)
                emit(work, lines,
                     label_of(bg=bg_name, tpl=short, s=0, h=0, c=100, o=0, b=blur, d=seed),
                     template_file, frame, roi, x, y)
        emit(work, lines,
             label_of(bg=bg_name, tpl='none', s=0, h=0, c=100, o=0, b=0, d=0),
             templates[0][3], bg.copy(), templates[0][2], -1, -1)
    (work / 'cases.txt').write_text('\n'.join(lines) + '\n', encoding='utf8')
    return len(lines)


def parse(row):
    f = row.split('|')
    return dict(label=f[0], fast=float(f[1]), base=float(f[2]), fs=float(f[3]),
                bs=float(f[4]), fx=int(f[5]), fy=int(f[6]), bx=int(f[7]),
                by=int(f[8]), ex=int(f[9]), ey=int(f[10]), hit=f[11] == 'true')


def summarize(tag, rows):
    if not rows:
        return None
    count = len(rows)
    fast = sum(r['fast'] for r in rows) / count
    base = sum(r['base'] for r in rows) / count
    positives = [r for r in rows if r['ex'] >= 0]
    return dict(group=tag, cases=count, fast_ms=round(fast, 4), base_ms=round(base, 4),
                ratio=round(base / fast, 3),
                hit_fast=sum(r['hit'] for r in positives),
                hit_base=sum(r['fx'] == r['bx'] and r['fy'] == r['by'] and r['hit'] for r in positives),
                positives=len(positives),
                position_equal=sum(r['fx'] == r['bx'] and r['fy'] == r['by'] for r in rows),
                regressions=sum(r['fs'] < r['bs'] - 1e-6 for r in rows),
                improvements=sum(r['fs'] > r['bs'] + 1e-6 for r in rows),
                score_below_085=sum(r['fs'] < .85 for r in rows),
                score_below_090=sum(r['fs'] < .90 for r in rows),
                score_below_095=sum(r['fs'] < .95 for r in rows))


def main():
    with tempfile.TemporaryDirectory(prefix='kards-matcher-ext-') as folder:
        work = Path(folder)
        count = prepare(work)
        output = bench.run(work)
    rows = [parse(line) for line in output.strip().splitlines() if not line.startswith('SUMMARY|')]
    summary = next(line for line in output.strip().splitlines() if line.startswith('SUMMARY|'))
    groups = defaultdict(list)
    for row in rows:
        fields = dict(part.split('=', 1) for part in row['label'].split(','))
        groups['all'].append(row)
        groups['bg=' + fields['bg']].append(row)
        groups['sigma=' + fields['s']].append(row)
        groups['scale=' + fields['c']].append(row)
        groups['occ=' + fields['o']].append(row)
        groups['blur=' + fields['b']].append(row)
        groups['tpl=' + fields['tpl']].append(row)
    print('cases=%d parsed=%d' % (count, len(rows)))
    print(summary)
    report = []
    for tag in sorted(groups):
        item = summarize(tag, groups[tag])
        if item:
            report.append(item)
            print('GROUP|' + '|'.join('%s=%s' % kv for kv in item.items()))
    if '--json' in sys.argv:
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
