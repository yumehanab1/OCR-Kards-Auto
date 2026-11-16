import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
ASSETS = ROOT / 'mobile/source/android-app/app/src/main/assets/mulligan-one-shot'
MATCHER = ROOT / 'mobile/source/android-app/app/src/main/java/com/kards/mobilert/TemplateMatcher.java'

CASES = (
    ('confirm', 'mulligan_ok_btn.png', (426, 557, 854, 720)),
    ('title', 'mulligan_title.png', (425, 25, 870, 135)),
    ('compact_confirm', 'mulligan_ok_btn_compact.png', (489, 616, 791, 720)),
    ('compact_title', 'mulligan_title_compact.png', (482, 10, 801, 104)),
    ('end_turn', 'end_turn_btn.png', (1017, 415, 1280, 590)),
    ('end_turn_white', 'end_turn_btn_white.png', (1017, 415, 1280, 590)),
)


def as_argb(rgb):
    a = np.full(rgb.shape[:2], 255, np.uint32)
    return ((a << 24) | (rgb[:, :, 0].astype(np.uint32) << 16)
            | (rgb[:, :, 1].astype(np.uint32) << 8) | rgb[:, :, 2].astype(np.uint32))


def write_raw(path, pixels):
    with open(path, 'wb') as stream:
        stream.write(np.array([pixels.shape[1], pixels.shape[0]], '<i4').tobytes())
        stream.write(pixels.astype('<i4').tobytes())


def background(rng):
    h, w = 720, 1280
    yy, xx = np.mgrid[0:h, 0:w]
    base = np.stack([18 + (yy * 0.05).astype(np.uint8),
                     24 + (xx * 0.03).astype(np.uint8),
                     32 + ((yy + xx) * 0.01).astype(np.uint8)], axis=2)
    noise = rng.integers(0, 26, (h, w, 1), dtype=np.uint8)
    return np.clip(base.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def prepare(work):
    templates = {}
    lines = []
    for name, filename, (l, t, r, b) in CASES:
        rgb = np.asarray(Image.open(ASSETS / filename).convert('RGB'))
        th, tw = rgb.shape[:2]
        template_path = work / (name + '_template.bin')
        write_raw(template_path, as_argb(rgb))
        templates[name] = template_path.name
        max_x, max_y = min(r, 1280) - tw, min(b, 720) - th
        for seed in (20261106, 20261107, 20261108):
            rng = np.random.default_rng(seed)
            for sigma in (0, 6, 12, 20, 28):
                for shift in (-12, 0, 12):
                    x = int(rng.integers(l, max_x + 1))
                    y = int(rng.integers(t, max_y + 1))
                    frame = background(rng)
                    patch = np.clip(rgb.astype(np.int16)
                                    + rng.normal(0, sigma, rgb.shape)
                                    + shift, 0, 255).astype(np.uint8)
                    frame[y:y + th, x:x + tw] = patch
                    frame_path = work / (f'{name}_{seed}_{sigma}_{shift}.bin')
                    write_raw(frame_path, as_argb(frame))
                    lines.append(f'{name}_{seed}_{sigma}_{shift}|{template_path.name}|{frame_path.name}|{l}|{t}|{r}|{b}|{x}|{y}')
        rng = np.random.default_rng(20261109)
        x = int(rng.integers(l, max_x + 1))
        y = int(rng.integers(t, max_y + 1))
        frame = background(rng)
        frame[y:y + th, x:x + tw] = rgb
        cut_start, cut_end = x + round(tw * .3), x + round(tw * .5)
        frame[y:y + th, cut_start:cut_end] = frame[y:y + th, x:x + cut_end - cut_start]
        frame_path = work / (name + '_occluded.bin')
        write_raw(frame_path, as_argb(frame))
        lines.append(f'{name}_occluded|{template_path.name}|{frame_path.name}|{l}|{t}|{r}|{b}|{x}|{y}')
        frame = background(rng)
        frame_path = work / (name + '_blank.bin')
        write_raw(frame_path, as_argb(frame))
        lines.append(f'{name}_blank|{template_path.name}|{frame_path.name}|{l}|{t}|{r}|{b}|-1|-1')
    (work / 'cases.txt').write_text('\n'.join(lines) + '\n', encoding='utf8')
    return len(lines)


def run(work):
    classes = work / 'classes'
    classes.mkdir(exist_ok=True)
    sources = [HERE / 'android/graphics/Bitmap.java', HERE / 'android/graphics/Rect.java',
               MATCHER, HERE / 'BaselineMatcher.java', HERE / 'MatcherBench.java']
    javac = subprocess.run(['javac', '-encoding', 'UTF-8', '-d', str(classes)] + [str(p) for p in sources],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
    if javac.returncode:
        raise SystemExit('javac failed:\n' + (javac.stdout or '') + (javac.stderr or ''))
    return subprocess.run(['java', '-cp', str(classes), 'com.kards.mobilert.MatcherBench', str(work)],
                          capture_output=True, text=True, encoding='utf-8', errors='replace', check=True).stdout


def main():
    with tempfile.TemporaryDirectory(prefix='kards-matcher-bench-') as folder:
        work = Path(folder)
        count = prepare(work)
        output = run(work)
    rows, summary = [], ''
    for line in output.strip().splitlines():
        if line.startswith('SUMMARY|'):
            summary = line
        else:
            rows.append(line)
    print(f'cases={count}')
    for line in (rows if '--all' in sys.argv else rows[:6]):
        print(line)
    if '--all' not in sys.argv:
        print('...')
    print(summary)
    fields = dict(item.split('=', 1) for item in summary.split('|')[1:])
    print(json.dumps(fields, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
