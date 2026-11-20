"""Read-only board veto for the Route B prototype; no input or game state.

A positive witness means that the reviewed zh-Hans “选择目标” prompt is
visible, NOT that a deployment is committed or a target is legal. A miss says
nothing about other prompts, layouts, or languages. Do not use it to relax
any existing foreground, phase, freshness, or effect-verification gate.
"""
from __future__ import annotations

import base64
import zlib

import cv2
import numpy as np

# 1280x720 KARDS Android zh-Hans capture, 1.61.27589. Only the four bright
# glyph silhouettes (no board artwork) from battle-E-resolved-deploy/
# v-004-0034.png, SHA-256 243e24a66702f7c3d3eeecac526f192b3b7c16aee63dab10aeef90cc8e91cb57.
# Derived with S<=55 and V>=200 in this exact box; rail pixels are not in it.
_BOX = (563, 262, 717, 301)  # x0, y0, x1, y1
_ROI = (559, 247, 721, 316)
_GLYPHS = (slice(0, 52), slice(52, 80), slice(80, 115), slice(115, 154))
_BITS = (
    b'c-n1}v5wR*5Qcwi5T-cAEk#IPfpU?o^{eb7gf0al4isB%O9ijuh~i$u%N5re(HODHFm`sgx)jd'
    b'HWB>F0o&jF|RJcXj*PjK_JsD*=&`EX;UobHzjOC1a3NXa%dzSr9@oM~-K!G`GW)`uD=j0?QOH#'
    b'5GRO~tKjU=rKw&;kM=BytjX|U_imFit7yu=K5F{VHnh>Cp4!mxVw0!6`bWi=oUE>tnY#mZ|6;G'
    b'`o88S!SNkWoe@GqW&mHsx+5qd2kDlgQHFtIbQ#tJLFUOm?x7O-JS*Pepdglq*@EDCk^d|GY<A$'
    b'@Gdrt@s_`#8oAuf4&8IJHpBN&E`62AT}Lbo;Xx7_f0L>>7zHPzrNYKU-n~Y)H%{cUmKvurX9$q'
    b'@o<tOo6YZZ><~Y7t*EDJQ$5e;pMJO3N7=BbWFO)%q{ex%i7VN|*tV8V!6hTNs!i1yt#J+})55&'
    b'j)L-W%+JlmAPP|qzVH(E1ytowvzm3MwHm3AS+7hshMr-IKjd{3}L4Tp}c$P?4vTZaZ7SlXmZe$'
    b'px+D@`@kK3Dd_>5Oj8E@`0s{Pv+=lVZkiW~_'
)
_WIDTH, _HEIGHT = _BOX[2] - _BOX[0], _BOX[3] - _BOX[1]
_STROKES = np.unpackbits(np.frombuffer(zlib.decompress(base64.b85decode(_BITS)), np.uint8),
                         count=_HEIGHT*_WIDTH).reshape(_HEIGHT, _WIDTH).astype(bool)
_STROKES.setflags(write=False)
_OFFSETS = (0, -1, 1, -2, 2)


def target_selection_witness(pixels: np.ndarray) -> dict | None:
    """Return a journal-ready positive veto, or None; BGR uint8 at 1280x720.

    Require both bright border rails and four independently matching glyphs
    at one common offset. A center-text hit, score, or rail alone is not proof.
    """
    if (not isinstance(pixels, np.ndarray) or pixels.shape != (720, 1280, 3)
            or pixels.dtype != np.uint8):
        return None
    x0, y0, x1, y1 = _ROI
    hsv = cv2.cvtColor(pixels[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    white = (hsv[:, :, 1] <= 55) & (hsv[:, :, 2] >= 200)
    if np.count_nonzero(white) < 2000:
        return None
    left, top, right, bottom = _BOX
    for dy in _OFFSETS:
        for dx in _OFFSETS:
            rails = tuple(float(white[a-y0+dy:b-y0+dy, 600-x0+dx:675-x0+dx].mean(axis=1).max())
                          for a, b in ((250, 254), (309, 314)))
            if min(rails) < .80:
                continue
            bright = white[top-y0+dy:bottom-y0+dy, left-x0+dx:right-x0+dx]
            overlap, union = bright & _STROKES, bright | _STROKES
            scores = tuple(float(overlap[:, s].sum() / union[:, s].sum()) for s in _GLYPHS)
            if min(scores) >= .86:
                return dict(proof="reviewed_zh_select_target_banner", label="选择目标",
                            box=(left+dx, top+dy, right+dx, bottom+dy),
                            glyph_iou=tuple(round(s, 4) for s in scores),
                            rail_coverage=tuple(round(s, 4) for s in rails))
    return None
