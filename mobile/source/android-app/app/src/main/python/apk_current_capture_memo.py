"""Pure board recognition reuse for one exact, registered APK capture.

This never captures, dispatches, dates an observation, or counts a sample.
Only the two default single-frame board recognizers may use the memo.
"""
from copy import deepcopy
import hashlib
from pathlib import PurePath

import numpy as np


FIELDS = ("frame_id", "captured_elapsed_ms", "foreground_generation",
          "source_width", "source_height")
NAMES = ("board_transition_reason", "frontline_state")
_OWNER_ATTRIBUTE = "_apk_current_capture_memo"


def _constant(value):
    if value is None or type(value) in (bool, int, float, str, bytes):
        return (type(value).__name__, value)
    if isinstance(value, PurePath):
        return (type(value).__name__, str(value))
    if isinstance(value, (tuple, list)):
        return (type(value).__name__, tuple(_constant(item) for item in value))
    if isinstance(value, dict):
        return ("dict", tuple(sorted((_constant(k), _constant(v))
                                     for k, v in value.items())))
    if isinstance(value, np.ndarray):
        return ("ndarray", value.shape, value.dtype.str, value.strides,
                hashlib.blake2b(value.tobytes(), digest_size=16).digest())
    raise TypeError("unsupported_recognition_configuration")


def configuration_epoch(modules):
    """Notice bound callbacks and literal recognition configuration changes.

    Unsupported configuration disables reuse, retaining the original path.
    Modules are session-local dependencies chosen after APK adapters install.
    """
    try:
        snapshots = []
        for module in modules:
            values = []
            for name, value in sorted(vars(module).items()):
                if callable(value):
                    values.append((name, "callback", id(value)))
                elif name.isupper():
                    values.append((name, "constant", _constant(value)))
            snapshots.append((id(module), tuple(values)))
        return tuple(snapshots)
    except (TypeError, ValueError):
        return None


class CurrentCaptureMemo:
    def __init__(self, originals, *, session_epoch, config_epoch,
                 eligible=lambda: True):
        if set(originals) != set(NAMES):
            raise ValueError("only_default_board_recognizers_may_be_cached")
        self.originals = dict(originals)
        self.session_epoch = session_epoch
        self.config_epoch = config_epoch
        self.eligible = eligible
        self.capture = self.info = self.initial = None
        self.memo = {}
        self.module = None
        self.bindings = {}
        self._last_token = None
        self.raw_calls = {name: 0 for name in NAMES}
        self.raw_current_calls = {name: 0 for name in NAMES}
        self.hits = {name: 0 for name in NAMES}

    def clear(self):
        self.capture = self.info = self.initial = None
        self.memo.clear()
        self._last_token = None

    def register(self, frame, info):
        # A capture attempt is an independent observation even if byte-identical.
        self.clear()
        self.capture, self.info = frame, info
        self.initial = self._description(frame, info)

    @staticmethod
    def _description(frame, info):
        if (not isinstance(frame, np.ndarray) or frame.shape != (720, 1280, 3)
                or frame.dtype != np.uint8 or not frame.flags.c_contiguous
                or not isinstance(info, dict)
                or any(type(info.get(k)) is not int for k in FIELDS)
                or any(info[k] < 0 for k in FIELDS[:3])
                or info["source_width"] <= 0 or info["source_height"] <= 0):
            return None
        return (id(frame), *(info[k] for k in FIELDS), frame.shape,
                frame.dtype.str, frame.strides, frame.flags.c_contiguous,
                hashlib.blake2b(memoryview(frame), digest_size=16).digest())

    def _token(self, frame):
        if frame is not self.capture or self.initial is None:
            return None
        current = self._description(frame, self.info)
        if current != self.initial:
            # Restoration cannot resurrect a registration once it was tainted.
            self.initial = None
            self.memo.clear()
            return None
        epoch = self.config_epoch() if callable(self.config_epoch) else self.config_epoch
        if epoch is None:
            self.memo.clear()
            return None
        token = (self.session_epoch, current, epoch,
                 tuple((name, id(function)) for name, function in sorted(self.originals.items())))
        if token != self._last_token:
            self.memo.clear()
            self._last_token = token
        return token

    def call(self, name, frame, *args, **kwargs):
        function = self.originals[name]
        # Artwork proof temporarily changes candidates. Its provisional nested
        # recognition must never hit or populate the ordinary board memo.
        busy = self.module is not None and (getattr(self.module, "_apk_artwork_filter_busy", False)
                                            or getattr(self.module, "_apk_hq_row_split_busy", False))
        allowed = self.eligible()
        if not allowed:
            self.clear()
        token = self._token(frame) if allowed and not busy and not args and not kwargs else None
        key = (name, id(function), token)
        if token is not None and key in self.memo:
            self.hits[name] += 1
            return deepcopy(self.memo[key])
        self.raw_calls[name] += 1
        if frame is self.capture:
            self.raw_current_calls[name] += 1
        try:
            value = function(frame, *args, **kwargs)
        except BaseException:
            self.clear()
            raise
        if token is not None:
            still_allowed = self.eligible()
            still_busy = self.module is not None and (getattr(self.module, "_apk_artwork_filter_busy", False)
                                                       or getattr(self.module, "_apk_hq_row_split_busy", False))
            if not still_allowed:
                self.clear()
            elif not still_busy and self._token(frame) == token:
                self.memo[key] = deepcopy(value)
        return value

    def bind(self, module):
        previous = getattr(module, _OWNER_ATTRIBUTE, None)
        if previous is not None:
            previous.uninstall()
        self.module = module
        self.originals = {name: getattr(module, name) for name in NAMES}
        for name in NAMES:
            def wrapper(frame, *args, _name=name, **kwargs):
                return self.call(_name, frame, *args, **kwargs)
            self.bindings[name] = wrapper
            setattr(module, name, wrapper)
        setattr(module, _OWNER_ATTRIBUTE, self)
        return self

    def uninstall(self):
        if self.module is not None:
            for name, wrapper in self.bindings.items():
                if getattr(self.module, name) is wrapper:
                    setattr(self.module, name, self.originals[name])
            if getattr(self.module, _OWNER_ATTRIBUTE, None) is self:
                delattr(self.module, _OWNER_ATTRIBUTE)
        self.module = None
        self.bindings.clear()
        self.clear()
