"""APK-only default drag dispatch without constructing a simulated mouse path.

The Accessibility bridge executes the complete 900 ms Android gesture. Core
mouse sleeps would only delay submitting that gesture: no touch is in flight
until Runtime.dispatch. Explicit timing/callback arguments retain the original core.
"""
from __future__ import annotations

import math
from time import sleep

CONTEXTS = frozenset(("deploy", "attack_unit", "attack_hq", "move_front"))
DURATION_MS = 900


class DirectDrag:
    def __init__(self, runtime, actions):
        self.runtime = runtime
        self.actions = actions
        self.original = actions._apk_original_move_drag

    def __call__(self, sx, sy, ex, ey, *timing_args, **timing_kwargs):
        runtime, actions = self.runtime, self.actions
        reason = None
        # Even an explicitly supplied default value belongs to the original
        # interface. Only its four-coordinate call is reviewed for this path.
        if timing_args or timing_kwargs:
            reason = "explicit_timing_or_callback"
        elif runtime.context not in CONTEXTS:
            reason = "unreviewed_hook"
        elif (actions.PRESS_DELAY != .20 or actions.DWELL != .40 or
              actions.DWELL_JIGGLE != 3 or actions.RELEASE_SETTLE != .20):
            reason = "core_default_constants_changed"
        elif (not hasattr(runtime, "platform") or actions._plat() is not runtime.platform or
              getattr(runtime.platform, "runtime", None) is not runtime or
              runtime.platform._down_ms is not None):
            reason = "different_platform_or_partial_pointer"
        elif (any(type(value) not in (int, float) or not math.isfinite(value)
                  for value in (sx, sy, ex, ey)) or
              (int(sx), int(sy)) == (int(ex), int(ey))):
            reason = "nonordinary_coordinates"
        if reason is not None:
            runtime.event("drag_dispatch_path", {"path": "core_fallback", "reason": reason,
                "context": runtime.context})
            return self.original(sx, sy, ex, ey, *timing_args, **timing_kwargs)

        origin, target = [int(sx), int(sy)], [int(ex), int(ey)]
        runtime.event("drag_dispatch_path", {"path": "direct_android", "context": runtime.context,
            "from": origin, "to": target, "duration_ms": DURATION_MS,
            "release_settle_seconds": actions.RELEASE_SETTLE})
        # Runtime.dispatch still performs cancellation, source-age, foreground,
        # budgets, destination and Java bridge checks. It adds the reviewed lift
        # path for deployment. An accepted incomplete gesture raises; never retry.
        runtime.dispatch({"kind": "drag", "from": origin, "to": target,
                          "duration_ms": DURATION_MS})
        runtime.platform._position = tuple(target)
        sleep(actions.RELEASE_SETTLE)
        return True


def install(runtime, actions):
    """Rebind retained actions to this session; never wrap an older Runtime."""
    if not hasattr(actions, "_apk_original_move_drag"):
        actions._apk_original_move_drag = actions.move_drag
    actions.move_drag = DirectDrag(runtime, actions)
    return {"installed": True, "contexts": sorted(CONTEXTS), "duration_ms": DURATION_MS,
            "explicit_timing": "original_core_fallback", "post_verification": "unchanged"}
