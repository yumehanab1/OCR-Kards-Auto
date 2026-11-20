"""Opt-in Route B vision adapter. No capture, dispatch, session lease or file writes.

Use with a reviewed session Vision, not as an independent card selector. The
caller still owns the two-frame, freshness, action and game-effect gates.
"""
from __future__ import annotations

from contextvars import ContextVar
from functools import wraps
import os
from pathlib import Path
from threading import Lock

import cv2
import numpy as np


# The two plate detectors interpret contours differently; only their exact
# full-frame HSV and identical binary component masks can be shared.
_HSV = object()
_COMPONENTS = object()
_MAX_COMPONENT_MASKS = 3


# The mobile landing detector re-enters mobile_board through module imports.
# Keep that call graph and its vetoes, but share identical pure calls *only*
# within a synchronous observe() on the exact same frame object. Ordinary
# callers, different frame objects and other threads take the original path.
_observation = ContextVar('route_b_observation', default=None)
_install_lock = Lock()


def _active(frame, key):
    scope = _observation.get()
    return scope[1] if scope is not None and frame is scope[0] and key in scope[2] else None


def _share(module, name):
    original = getattr(module, name)
    if getattr(original, '_route_b_shared', False):
        return
    key = (module, name)

    @wraps(original)
    def shared(frame, *args, **kwargs):
        memo = _active(frame, key)
        if memo is None or args or kwargs:
            return original(frame, *args, **kwargs)
        if key not in memo:
            memo[key] = original(frame)
        return memo[key]

    shared._route_b_shared = True
    setattr(module, name, shared)


class _PlateCv:
    """Per-module OpenCV proxy; do not change cv2 functions process-wide."""

    def __init__(self, original, *, plate_components):
        self.original = original
        self.plate_components = plate_components

    def __getattr__(self, name):
        return getattr(self.original, name)

    def cvtColor(self, frame, code, *args, **kwargs):
        memo = _active(frame, _HSV)
        if memo is None or code != cv2.COLOR_BGR2HSV or args or kwargs:
            return self.original.cvtColor(frame, code, *args, **kwargs)
        if _HSV not in memo:
            hsv = self.original.cvtColor(frame, code)
            hsv.setflags(write=False)
            memo[_HSV] = hsv
        return memo[_HSV]

    def connectedComponentsWithStats(self, mask, *args, **kwargs):
        scope = _observation.get()
        if (not self.plate_components or scope is None or _COMPONENTS not in scope[2]
                or not isinstance(mask, np.ndarray) or mask.dtype != np.uint8
                or mask.shape != scope[0].shape[:2] or args != (8,) or kwargs):
            return self.original.connectedComponentsWithStats(mask, *args, **kwargs)
        # The two reviewed plate detectors use three identical full-frame dark
        # masks. Exact comparison also handles a different threshold safely.
        masks = scope[1].setdefault(_COMPONENTS, [])
        for saved, output in masks:
            if np.array_equal(saved, mask):
                return output
        output = self.original.connectedComponentsWithStats(mask, *args, **kwargs)
        if len(masks) < _MAX_COMPONENT_MASKS:
            for array in output[1:]:
                array.setflags(write=False)
            masks.append((mask.copy(), output))
        return output


class SameFrameVision:
    """Mixin for the unchanged vision/planner path, including verify_deploy."""

    def _install_frame_reuse(self):
        pure_reads = ((self.board, 'board_transition_reason'),
                      (self.board, 'frontline_state'),
                      (self.board, '_hsv'),  # read-only planes used by support-row scans
                      (self.available, '_geometry_plates'))
        self._shared_reads = frozenset((*pure_reads, _HSV, _COMPONENTS))
        with _install_lock:
            for module, name in pure_reads:
                _share(module, name)
            for module in (self.hand, self.native_hand, self.available, self.board):
                if not isinstance(module.cv2, _PlateCv):
                    module.cv2 = _PlateCv(module.cv2, plate_components=module in (self.native_hand, self.available))

    def observe(self, pixels, *, mode='plan'):
        token = _observation.set((pixels, {}, self._shared_reads))
        try:
            return super().observe(pixels, mode=mode)
        finally:
            _observation.reset(token)


class CpuOcr:
    """Same PP-OCRv6 models, crop sizes, resize, and score thresholds.

    Use dedicated CPU sessions with bounded workers and reusable tensor
    allocations. No recognition result is cached. prepare() can be called
    before receiving a frame to leave model setup outside the sample window.
    """

    def __init__(self):
        self.engine = None

    def prepare(self):
        if self.engine is not None:
            return
        from onnxruntime import InferenceSession
        from rapidocr_onnxruntime import RapidOCR, __file__ as rapid_file

        root = Path(rapid_file).parent
        config = root / 'config_ppocrv6.yaml'
        dictionary = root / 'models' / 'ppocrv6_dict.txt'
        for path in (config, dictionary):
            if not path.is_file():
                raise FileNotFoundError(path)
        engine = RapidOCR(config_path=str(config), rec_keys_path=str(dictionary),
                          intra_op_num_threads=min(6, os.cpu_count() or 1), inter_op_num_threads=1)
        # Leave tensor shape and numerical processing unchanged. With this
        # pinned RapidOCR implementation, allocator/spinning are only exposed
        # through underlying session options. No global OCR object is altered.
        for part in (engine.text_det.infer, engine.text_cls.infer, engine.text_rec.session):
            original = part.session
            if original.get_providers() != ['CPUExecutionProvider']:
                raise RuntimeError('route_b_fast_ocr_requires_cpu_sessions')
            opts = original.get_session_options()
            opts.enable_cpu_mem_arena = True
            opts.add_session_config_entry('session.intra_op.allow_spinning', '0')
            opts.add_session_config_entry('session.inter_op.allow_spinning', '0')
            part.session = InferenceSession(original._model_path, sess_options=opts,
                                            providers=original.get_providers(),
                                            provider_options=[original.get_provider_options()['CPUExecutionProvider']])
        self.engine = engine

    def __call__(self, roi):
        self.prepare()
        result, _ = self.engine(roi)
        words = []
        for box, text, conf, *_ in result or ():
            xs, ys = zip(*box)
            words.append(dict(text=str(text), conf=float(conf), x=min(xs), y=min(ys),
                              w=max(xs)-min(xs), h=max(ys)-min(ys), cx=sum(xs)/4, cy=sum(ys)/4))
        return words


def adapt(session_vision, read_current_credits):
    """Return a drop-in subclass of the given reviewed session Vision.

    Pass its original, *uncached* HUD method. The same frame is still checked
    for card title, printed cost, current credits, board, landing and overlays.
    This adapter never changes a Pilot/Device or grants permission to use one.
    """

    class Vision(SameFrameVision, session_vision):
        def __init__(self, refs, *, ocr=None):
            super().__init__(refs)
            self.ocr = CpuOcr() if ocr is None else ocr
            self._ocr = self.right.regular.ocr = self.right.opening.ocr = self.ocr
            self._install_frame_reuse()

        def credits(self, pixels):
            return read_current_credits(self, pixels)

    return Vision
