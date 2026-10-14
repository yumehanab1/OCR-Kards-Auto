"""Positive opponent-label evidence for observed Chinese compact/standard HUDs.

This never authorizes input. A missing own button is not opponent evidence.
The tiny grayscale PNG is embedded in Python so Chaquopy needs no asset path.
Compact source: live-02 frame 00009, 2026-10-05, crop [1164,450,1218,477].
Standard source: live-11 frame 00007, 2026-10-06, crop [1120,486,1191,523].
Both are KARDS 1.60.27292, normalized 1280x720. Only the two explicit fixed
label geometries are supported; other languages/positions remain unknown.
"""
from __future__ import annotations

import base64
from functools import lru_cache

import cv2
import numpy as np

_GLYPH_BOX = (1164, 450, 1218, 477)
_LABEL_BOX = (1130, 447, 1254, 481)
_PNG = 'iVBORw0KGgoAAAANSUhEUgAAADYAAAAbCAAAAAASHCPpAAADxElEQVQ4EUXB7VNUZQDG4d/97NlzdmFBEKGiUuzFUMG3srKmJMVmmnGa/sr60NT0pZqpLcvIiqE3a8yMCsatBCV5EVjYs8/dWZjqupRhCjIyHcEWYGyEjRAoa0Z2GaQMAwIGD84uAadqq7+uUTCFaAS6/1DPF0sULDCoAiRpVrtvuNv3ppZIXhzUB3ckBCYaELrYS+OyzS6jLpJjWaW7vNmMpWTtq1b1pV6/lZuCHMEgOHhG/nABxC5V0FMPoFAK9xZuLrbpO58tvw8YZBvLiOqFns2ff6RDFJTB4NPLdw/0hCvzBobPanYaZFDveCkgIIa95c01A47S18soY8f5QV1uGPn4YXs7lEU+Mz8wUQoCjMV/XF9AKQqYiSFNNSLoYle+XCsHQnt6buBcWRbEXCXxL3+4iDKSgYoYqYWbq7Aez7l5t6w91urVP9OhgMnGK55vgGV2LDRRRu1UstGq9pZCwLf0IHc/a/FqWLmcR4yhe7LGzHUjwOxSRs/p9c1S/54kEOP6dqr21Fr3RRqfSwZD7UKVqTn+Z1BG6N5O0uOD4YdFe3hI7fDd7eHTvn5D7HDfZMq3f0NEoPbfOaCMHSf7Bq40CA/viRpYunpkJPl0hYKBvefLohBjkFivrwFKEYUX9iVTf0A20BrZu/XF2b3x7dzCGIbPEqPLAQtYq68DSlGty3G8r3Ttdt5eKfvgAOuPdN2u02HD0eNqrpg2JaX9LNe3DMpgbDTPHUqKLb8r957eE5LW97NYGOOXh/jhqilo/wss1VuAqvjoeLvVbrclJe9gXumnfffLFUvYUH0txI8WMaAnTsXFSwYrg7Hx1p9zka4TqV7HHDgjL13KowIGThxmvX7PdDw5SuMTCsrQ2Fg++52pTXTpDeP+c6WNW99EdlUne5mfiuyYeIgb0xRUNUfHmZ02vZMZr+Pkxftaefh8ASPgxBH53WXTkVzYx8xPFFR1HD0eZ7+FnmdVeo/0mYewQ/PjFVsO+5+H368YjOie7KF+yyCl8OipzTurlWopbZXrfSf7y6WbQxkbMzeBA6dTb3y8gjHigYlSfLNlQCk6egx3KPDToVLO718/fjK4fWmxcmTUjjO/QXbY2zF5vJu/PqJDqTQ2DnFry2kWfn1E3Pg+57Ej4dp173u2a3P75zlhPTdCR/uzBh0qBx06FmZn5PL+jF/OVK41KOx/cHpbjJ64d3WegkeeE+TNuR+jDagcqFRprsuRQk9rS6KQbCNr5PaqsHC5XyZvbgAGlAQ5GoKNERYSBhxsA0IYDGaHzD84SNZY9idPqwAAAABJRU5ErkJggg=='


_STANDARD_PNG = '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'
_LAYOUTS = {
    "compact": {
        "glyph": _GLYPH_BOX, "label": _LABEL_BOX, "split": 27,
        "edges": ((1133, 447, 1252, 448), (1133, 479, 1252, 480),
                  (1131, 450, 1132, 478), (1252, 450, 1253, 478)),
    },
    "standard": {
        "glyph": (1120, 486, 1191, 523), "label": (1069, 481, 1244, 530), "split": 35,
        "edges": ((1074, 482, 1239, 483), (1074, 527, 1239, 528),
                  (1070, 486, 1071, 524), (1241, 486, 1242, 524)),
    },
}


@lru_cache(maxsize=2)
def _template(layout="compact"):
    png = {"compact": _PNG, "standard": _STANDARD_PNG}.get(layout)
    if not png:
        return None
    return cv2.imdecode(np.frombuffer(base64.b64decode(png), np.uint8), cv2.IMREAD_GRAYSCALE)


def _inspect_layout(gray, layout):
    spec = _LAYOUTS[layout]
    result = {"present": False, "score": 0.0, "box": None,
              "layout": layout, "reason": "opponent_label_border_unknown", "evidence": {}}
    # All four sides support the observed label frame. No resource-digit or
    # color-of-own-button inference participates in this positive marker.
    edges = [gray[y0:y1, x0:x1] for x0, y0, x1, y1 in spec["edges"]]
    border = [float(np.mean(edge >= 75)) for edge in edges]
    result["evidence"]["border_coverage"] = border
    if min(border) < .85:
        result["reason"] = "opponent_label_border_unknown"
        return result
    x0, y0, x1, y1 = spec["glyph"]
    glyph = gray[y0:y1, x0:x1]
    contrast, deviation = float(np.ptp(glyph)), float(glyph.std())
    result["evidence"].update(contrast=contrast, deviation=deviation)
    if contrast < 40 or deviation < 20:
        result["reason"] = "opponent_glyph_contrast_unknown"
        return result
    template = _template(layout)
    if template is None or template.shape != glyph.shape:
        result["reason"] = "opponent_template_unavailable"
        return result
    score = float(cv2.matchTemplate(glyph, template, cv2.TM_CCOEFF_NORMED)[0, 0])
    characters = [float(cv2.matchTemplate(glyph[:, a:b], template[:, a:b],
                                         cv2.TM_CCOEFF_NORMED)[0, 0])
                  for a, b in ((0, spec["split"]), (spec["split"], glyph.shape[1]))]
    result.update(score=score)
    result["evidence"]["character_scores"] = characters
    if (not np.isfinite(score) or not all(np.isfinite(v) for v in characters)
            or score < .95 or min(characters) < .93):
        result["reason"] = "opponent_glyphs_unknown"
        return result
    x0, y0, x1, y1 = spec["label"]
    result["evidence"]["roi_xyxy"] = list(spec["label"])
    result.update(present=True, box=[x0, y0, x1 - x0, y1 - y0], reason="explicit_opponent_label")
    return result


def inspect_opponent_turn(frame):
    """Return positive label evidence only; false means unknown, not our turn.

    There is no negative-own-button inference or search/scale fallback. The
    caller still owns foreground, HUD consistency and two-frame confirmation.
    """
    result = {"present": False, "score": 0.0, "box": None, "layout": "unknown",
              "reason": "invalid_frame", "evidence": {}}
    if (not isinstance(frame, np.ndarray) or frame.shape != (720, 1280, 3)
            or frame.dtype != np.uint8):
        return result
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    candidates = [_inspect_layout(gray, layout) for layout in _LAYOUTS]
    present = [item for item in candidates if item["present"]]
    if len(present) == 1:
        return present[0]
    result["reason"] = ("conflicting_opponent_label_layouts" if present
                        else "opponent_label_unknown")
    result["score"] = max(item["score"] for item in candidates)
    result["evidence"]["layouts"] = {item["layout"]: item for item in candidates}
    return result
