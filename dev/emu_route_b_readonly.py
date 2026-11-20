"""Inspect saved 1280x720 Route B PNGs; no ADB, game input or session output.

Only the reviewed lobby battle-01 profile is loaded as a vision dependency.
JSONL timings and evidence go to stdout. This is not an action/continuation CLI.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack, contextmanager
from dataclasses import asdict
from functools import wraps
import hashlib
from importlib import import_module
from importlib.metadata import version
import json
from pathlib import Path
import sys
from time import perf_counter, process_time
from unittest.mock import patch

import cv2

from emu_route_b_fast_vision import adapt


# The unmodified source archive, not an executable launcher or new session.
_FROZEN = {
    'lobby_bound_battle': 'c6f3c69c629e45ad03e3635279362b2c3a5fa64f13f6402109924aadd63d2ab1',
    'lobby_first_edge': 'b36559b62dca140cea48a1bf3dbd80791f87d554f0623acfeedfc5fbd0cfc0f1',
    'lobby_session_run': 'c15c2993bdd018883c29fb1861b2fcb5baa181a6166c999ebcdb14937eccab80',
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def load_profile(root):
    """Read the archived vision and its two bound opening references, no pilot."""
    root = root.resolve(strict=True)
    source = root / 'battle-01' / 'source'
    for name, digest in _FROZEN.items():
        if sha256((source / (name + '.py')).read_bytes()) != digest:
            raise ValueError(f'archived_session_source_mismatch:{name}')
    sys.path.insert(0, str(source))
    try:
        bound, composed = (import_module(name) for name in ('lobby_bound_battle', 'lobby_session_run'))
    finally:
        sys.path.remove(str(source))
    for name in _FROZEN:
        if Path(sys.modules[name].__file__).resolve() != source / (name + '.py'):
            raise ValueError(f'session_module_origin_mismatch:{name}')
    if root != bound.SESSION_ROOT:
        raise ValueError('this archived profile is pinned to its recorded session')
    return bound, composed, bound.load_session(root)


def vision_for(bound, composed, refs, variant):
    cls = composed.Vision if variant == 'original' else adapt(composed.Vision, bound.Vision.credits)
    return cls([frame.pixels for frame in refs])


def description(reading):
    """Keep full journal semantics as well as the HQ anchor absent in brief()."""
    return dict(observation=reading.brief(), support=asdict(reading.support) if reading.support else None)


def emit(**row):
    print(json.dumps(row, ensure_ascii=False, allow_nan=False), flush=True)


class Spans:
    def __init__(self):
        self.ms, self.calls = Counter(), Counter()

    def wrap(self, function, name):
        @wraps(function)
        def timed(*args, **kwargs):
            label = name(*args, **kwargs) if callable(name) else name
            self.calls[label] += 1
            start = perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                self.ms[label] += (perf_counter() - start) * 1e3
        return timed

    @contextmanager
    def trace(self, vision):
        def stage(roi):
            return {(70, 164): 'ocr_title', (152, 136): 'ocr_available',
                    (105, 114): 'ocr_maximum', (66, 207): 'ocr_opponent'}.get(roi.shape[:2], 'ocr_other')

        ocr = self.wrap(vision._ocr, stage)
        with ExitStack() as stack:
            for obj, attr in ((vision, '_ocr'), (vision.right.regular, 'ocr'), (vision.right.opening, 'ocr')):
                stack.enter_context(patch.object(obj, attr, ocr))
            for obj, attr, label in (
                (vision, 'hands', 'hand'), (vision.hand, 'find_hand', 'core_hand'),
                (vision.native_hand, 'inspect', 'native_hand'), (vision, 'credits', 'credits'),
                (vision.available, '_geometry_plates', 'plate_geometry'), (vision.available, '_read_cost', 'printed_cost'),
                (vision.drop, 'choose_drop', 'landing'), (vision.drop.native, '_row', 'support_row'),
                (vision.drop.native, '_background_profile', 'landing_background'),
                (vision.drop, 'slot_matches', 'slot_reference'), (vision.board, 'board_transition_reason', 'transition'),
                (vision.board, 'frontline_state', 'frontline'), (vision.board, 'choice_modal', 'choice_modal'),
                (vision.opponent, 'inspect_opponent_turn', 'opponent'),
            ):
                stack.enter_context(patch.object(obj, attr, self.wrap(getattr(obj, attr), label)))
            yield

    def reset(self):
        self.ms.clear()
        self.calls.clear()

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session-root', type=Path, required=True)
    parser.add_argument('--frame', type=Path, required=True, action='append', help='saved raw PNG (repeatable)')
    parser.add_argument('--variant', choices=('fast', 'original'), default='fast')
    parser.add_argument('--mode', choices=('plan', 'end_only', 'verify_deploy'), default='plan')
    parser.add_argument('--rounds', type=int, default=1)
    parser.add_argument('--entry-check', action='store_true', help='separately check the archived opening pair first')
    parser.add_argument('--profile', action='store_true', help='record nested vision stage timings')
    args = parser.parse_args(argv)
    if not 1 <= args.rounds <= 20:
        parser.error('--rounds must be in 1..20')

    start = perf_counter()
    bound, composed, session = load_profile(args.session_root)
    loaded = perf_counter()
    vision = vision_for(bound, composed, session.refs, args.variant)
    built = perf_counter()
    emit(event='environment', variant=args.variant, mode=args.mode, python=sys.version, opencv=cv2.__version__,
         opencv_threads=cv2.getNumThreads(), rapidocr=version('rapidocr-onnxruntime'), ort=version('onnxruntime'),
         profile_load_ms=round((loaded-start)*1e3, 3), vision_init_ms=round((built-loaded)*1e3, 3),
         plan_limit_ms=round(bound.PLAN_MAX_AGE*1e3), dispatch_limit_ms=round(bound.host.FRESHNESS*1e3),
         scope='saved_png_observe_only_no_capture_no_guard_no_dispatch')
    if args.entry_check:
        t = perf_counter()
        proof = bound.entry_pair(vision, *session.refs)
        emit(event='offline_entry_check', ms=round((perf_counter()-t)*1e3, 3), **proof)
        if not proof['accepted']:
            return 2

    spans = Spans()
    with ExitStack() as stack:
        if args.profile:
            stack.enter_context(spans.trace(vision))
        for repeat in range(args.rounds):
            for i, path in enumerate(args.frame):
                t = perf_counter()
                data = path.read_bytes()
                read = perf_counter()
                pixels, size = bound.host.decode_png(data)
                if size != bound.SIZE:
                    raise ValueError(f'expected_native_1280x720:{path}')
                decoded = perf_counter()
                spans.reset()
                cpu, t0 = process_time(), perf_counter()
                reading = vision.observe(pixels, mode=args.mode)
                t1, cpu1 = perf_counter(), process_time()
                witness = bound.deploy_witness(reading, reading.deploy) if reading.deploy else None
                emit(event='frame', repeat=repeat, index=i, path=str(path), sha256=sha256(data), mode=args.mode,
                     file_read_ms=round((read-t)*1e3, 3), decode_ms=round((decoded-read)*1e3, 3),
                     observe_ms=round((t1-t0)*1e3, 3), observe_cpu_ms=round((cpu1-cpu)*1e3, 3),
                     deploy_witness=witness, **description(reading),
                     stage_ms={k: round(v, 3) for k, v in spans.ms.items()}, stage_calls=dict(spans.calls))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
