import json
import statistics
import sys
import time

import cv2
import numpy as np

import mobile_vision_bench as base

ASSETS = base.ASSETS
PYTHON = base.PYTHON
TYPES = ('infantry', 'tank', 'artillery', 'fighter', 'bomber')


def normalized(crop):
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    return cv2.resize(gray[2:-2, 2:-2], (32, 32), interpolation=cv2.INTER_AREA)


class Variant:
    def __init__(self, bank, dtype=np.float64):
        self.dtype = dtype
        needles = np.stack([normalized(bank[n]).astype(dtype).ravel() for n in TYPES])
        self.centered = needles - needles.mean(axis=1, keepdims=True)
        self.norms = np.sqrt(np.einsum('ij,ij->i', self.centered, self.centered))

    def candidates(self, frame):
        h, w = frame.shape[:2]
        scale = h / 720
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = (hsv[:, :, 2] < 65).astype(np.uint8)
        _, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        items = []
        for x, y, bw, bh, area in stats[1:]:
            if not (18 * scale <= bw <= 42 * scale and 18 * scale <= bh <= 44 * scale
                    and area >= .55 * bw * bh):
                continue
            items.append(([int(x), int(y), int(bw), int(bh)],
                          normalized(frame[y:y + bh, x:x + bw]).astype(self.dtype).ravel()))
        return items

    def emit(self, box, first, second, score, margin):
        return {'box': box, 'type': TYPES[first], 'score': float(score),
                'margin': float(margin), 'side': 'unknown', 'input_authorized': False}


class Current(Variant):
    def inspect(self, frame):
        result = []
        for box, glyph in self.candidates(frame):
            centered = glyph - glyph.mean()
            norm = float(np.sqrt(centered @ centered))
            if norm <= 0:
                continue
            denominator = self.norms * norm
            scores = np.divide(self.centered @ centered, denominator,
                               out=np.full(len(TYPES), -1.), where=denominator > 0)
            names = sorted(range(len(TYPES)), key=lambda i: -scores[i])
            first, second = names[0], names[1]
            if scores[first] >= .90 and scores[first] - scores[second] >= .12:
                result.append(self.emit(box, first, second, scores[first],
                                        scores[first] - scores[second]))
        return result


class Simplified(Variant):
    def inspect(self, frame):
        result = []
        for box, glyph in self.candidates(frame):
            centered = glyph - glyph.mean()
            norm = float(np.sqrt(centered @ centered))
            if norm <= 0:
                continue
            scores = (self.centered @ centered) / (self.norms * norm)
            names = sorted(range(len(TYPES)), key=lambda i: -scores[i])
            first, second = names[0], names[1]
            if scores[first] >= .90 and scores[first] - scores[second] >= .12:
                result.append(self.emit(box, first, second, scores[first],
                                        scores[first] - scores[second]))
        return result


class Batched(Variant):
    def inspect(self, frame):
        items = self.candidates(frame)
        if not items:
            return []
        arr = np.stack([glyph for _, glyph in items])
        centered = arr - arr.mean(axis=1, keepdims=True)
        norms = np.sqrt(np.einsum('ij,ij->i', centered, centered))
        denominator = norms[:, None] * self.norms[None, :]
        scores = np.divide(centered @ self.centered.T, denominator,
                           out=np.full((len(items), len(TYPES)), -1.), where=denominator > 0)
        order = np.argsort(-scores, axis=1, kind='stable')
        result = []
        for i, (box, _) in enumerate(items):
            first, second = int(order[i, 0]), int(order[i, 1])
            if scores[i, first] >= .90 and scores[i, first] - scores[i, second] >= .12:
                result.append(self.emit(box, first, second, scores[i, first],
                                        scores[i, first] - scores[i, second]))
        return result


class Float32(Simplified):
    def __init__(self, bank):
        super().__init__(bank, np.float32)


def synthetic(count, seed):
    rng = np.random.default_rng(seed)
    image = np.stack([120 + rng.integers(0, 20, (720, 1280)),
                      140 + rng.integers(0, 20, (720, 1280)),
                      160 + rng.integers(0, 20, (720, 1280))], axis=2).astype(np.uint8)
    for i in range(count):
        x, y = 10 + (i % 40) * 32, 10 + (i // 40) * 40
        if x + 30 >= 1280 or y + 32 >= 720:
            continue
        cv2.rectangle(image, (x, y), (x + 30, y + 32), (8, 8, 8), -1)
    return image


def frames():
    out = []
    for name, path in (('atlas', base.ROOT / 'mobile/source/android-app/app/src/main/python/deploy-fixtures/blueprint-aircraft-atlas.png'),
                       ('promo', ASSETS / 'match-entry/home_promo.png')):
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image.shape[:2] != (720, 1280):
            image = cv2.resize(image, (1280, 720))
        out.append((name, image))
    out.append(('synthetic_30', synthetic(30, 11)))
    out.append(('synthetic_120', synthetic(120, 13)))
    return out


def timed(fn, repeat):
    samples = []
    for _ in range(repeat):
        start = time.perf_counter()
        value = fn()
        samples.append((time.perf_counter() - start) * 1000)
    return statistics.median(samples), value


def equal(a, b):
    if len(a) != len(b):
        return False
    return all(x['box'] == y['box'] and x['type'] == y['type']
               and abs(x['score'] - y['score']) < 1e-6
               and abs(x['margin'] - y['margin']) < 1e-6 for x, y in zip(a, b))


def main():
    old_module = base.original_module('old_objects_variant',
                                      'mobile/source/android-app/app/src/main/python/apk_native/native_objects.py')
    rng = np.random.default_rng(7)
    bank = {name: rng.integers(0, 256, (24, 24, 3), dtype=np.uint8) for name in TYPES}
    variants = {
        'old': old_module.Objects(bank),
        'current': Current(bank),
        'simplified': Simplified(bank),
        'batched': Batched(bank),
        'float32': Float32(bank),
    }
    totals = {name: 0.0 for name in variants}
    report = []
    for label, frame in frames():
        times, outputs = {}, {}
        for name, instance in variants.items():
            elapsed, output = timed(lambda: instance.inspect(frame), 5)
            times[name] = elapsed
            totals[name] += elapsed
            outputs[name] = output
        row = dict(frame=label, candidates=len(variants['current'].candidates(frame)),
                   times={k: round(v, 3) for k, v in times.items()},
                   equal={k: equal(outputs['old'], outputs[k]) for k in variants if k != 'old'})
        report.append(row)
        print('FRAME|%s|candidates=%d|%s|equal=%s' % (
            label, row['candidates'],
            '|'.join('%s_ms=%.3f' % kv for kv in times.items()),
            '|'.join('%s=%s' % (k, int(v)) for k, v in row['equal'].items())))
    print('TOTAL|' + '|'.join('%s_ms=%.3f' % kv for kv in totals.items()))
    print('RATIO_VS_OLD|' + '|'.join('%s=%.3f' % (k, totals['old'] / v)
                                     for k, v in totals.items() if k != 'old'))
    print('EQUAL_ALL|' + '|'.join('%s=%d/%d' % (k, sum(r['equal'][k] for r in report), len(report))
                                 for k in report[0]['equal']))
    if '--json' in sys.argv:
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
