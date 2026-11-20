"""Read-only veto for the reviewed zh-Hans deployment-rejection banner.

This witnesses a visible message, not a successful effect, the selected card,
or the cause of a drag. Use only on already bound, fresh post-deploy frames;
this function does not check session, phase or freshness. A miss is unknown,
never permission to proceed, retry or fall back. No capture, input, or I/O.
"""
from __future__ import annotations

import base64
import zlib

import cv2
import numpy as np

LABEL = "指挥点数不足，无法使用此卡牌"
STOP_REASON = "deploy_rejected_insufficient_kredits"

# 1280x720 KARDS zh-Hans (1.61.27589/code2714). Half-resolution binary glyph
# silhouettes only, not a PNG, pixel colors, or board artwork. Calibrated on
# pc_emu_b_20261119_reboot_0224/live-01/read-0023.png, SHA-256
# d93a07ad5c311c08a68aca4d88573c78fcc37f2f6e9c7c9ec45c07c171bf4cff.
# read-0024.png independently checks the brighter rendering of the same toast.
_BOX = (204, 310, 1076, 374)  # x0, y0, x1, y1; exclusive right/bottom
_INTERIOR = (126, 303, 1154, 379)
_RAIL_X = slice(496, 784)
_RAIL_AND_GUTTER_Y = ((300, 304), (379, 374))  # 3px rail, 5px dark gutter
_GLYPH_SHAPE = (32, 436)
_GLYPH_STARTS = (0, 32, 63, 93, 125, 156, 189, 214, 249, 279, 311, 341, 373, 403)
_BITS = (
    'c-oznF>f0;6vrPy!(0NfV+QpuTh?y90<12bvUchmphJ;Og$tBI4IdK$)n<PIL;4^s9I6LITeWrw5*ixR'
    '%?v#F472z8-kszkDB2;1gLF9Z@yGXn|HlLPsLL3D$Pe^0QU4l#Bmz8;zI)Cz06mIeKra0wonr&^>bvuC'
    'H(X)6k5X>fP2)=hTG@bjOQB|%!+S&r*d836L5`RdV&G}Vh`tpbGU)}<O2Z!Z#Rj9S*G&(@@Iw)482t{W'
    'QkhiDK+;OIS`gtgfU*^DD|DvBJxm_y4`3CokkOP9amlbQGmM{ZvB|Fy$~R-nFid#KFbf$+F$A7sqh9S{'
    'lv#<AU{m}R)L(1mNX8tm5JV&qMCf&6VggH<1)ItF9yYh-9c|-HEJ#MqD#8e02LldP*l1@UQ!m0KMAymK'
    '!NfLIE!RxrI|La%goz+-5nm8Y&9z|}%NuND9Y&h6(xgfLe&gZfpPEtdkV4A^2|$@m+M7Tyi7aD|KGHO#'
    '74X7<{uA~xQiO;iNQRM&YH^i%*twNUOj`9Y{AJ?=MeJY%z}#g}-NTTS#f_h=oYCl_@eIo+RYB@9jP2Ly'
    '(;%*H>s1e12P$7{NF(_NfPOlM0m-nP-8g#1mfOSR0@LT`#`ZEcJ&ddG0MaBtAkClsXaTnYc2-9&FXC^L'
    'dl@_bFf6~rR9#_Yn3fgf7iHH(okJ26lcLOaHRFBAwwy_Pg{y?fnQ5Fwb$v+%*~wUWZW);DWSsZbFT;&1'
    'Yiufwv6C^CB8{|XU-#Yzcw#~AWn|cw1k0>UMy{wZJ!~5CX*eNR*XD5NVL$*|J8=(d!E9Gf*4}8UDZ|V-'
    '6LBQ{F~JIo(iR{@uQChwu(FZAKeRym@v(QGoI!XX!$Vd3PDye71hOmxd*ehW<KTd;UtD3L{UlvdLxFH7'
    'k$g}03CZ{kEi*C$`BjK&*1(Wtd>-N$Of@|vCz!|Ruc>Rdr$)9avi0?~2gS`&`)G^;TN1m2DLSWm*b)kY'
    'HJRN6?deD$7<DZFK~rcoT^4HEK*2R@<JVx6{FzK)4y0p$ug)^S{Fq^b%6FZaPhGUt)<G4OBN$$3&bV;O'
    '$thKeWHdI$vfc!yd`nv&&=!MkmBw^Pr<qlYOKjJX45CiKil)SxU}`oy%U`FQVFh`KjzmZjL#)sr-QwE)'
    ')aE#A8D@iW`Se{H5v;Iw+$hH|>9}jDWG+vKDh$<yYQ}1@q^|c28&GD^$SIvhQoTH+Z5=S|6X3%J;29ip'
    'ySa%|FX8)Uz$CiI1pBXVNc^ZT&%ytX{|y}(s^I'
)
_GLYPH_MASK = np.unpackbits(np.frombuffer(zlib.decompress(base64.b85decode(_BITS)), np.uint8))
_GLYPH_MASK = _GLYPH_MASK.reshape(_GLYPH_SHAPE).astype(bool)
_GLYPH_MASK.setflags(write=False)


def deployment_rejection_witness(pixels: np.ndarray) -> dict | None:
    """Return a journal-ready veto for the full centered toast, otherwise None.

    Accepts a 1280x720 BGR uint8 array. Require both warm-gray rails against
    dark gutters, then every glyph (including the comma) at its exact layout
    position. This deliberately does not search other positions, scales,
    themes, or languages. A veto may label an existing stop, not advance play.
    """
    if (not isinstance(pixels, np.ndarray) or pixels.shape != (720, 1280, 3)
            or pixels.dtype != np.uint8):
        return None

    rail_coverage = []
    for rail_y, gutter_y in _RAIL_AND_GUTTER_Y:
        gutter = pixels[gutter_y:gutter_y+5, _RAIL_X]
        dark = cv2.inRange(gutter, (0, 0, 0), (45, 45, 45))
        if cv2.countNonZero(dark) < .85 * dark.size:
            return None
        rail = cv2.cvtColor(pixels[rail_y:rail_y+3, _RAIL_X], cv2.COLOR_BGR2HSV)
        warm_gray = cv2.inRange(rail, (12, 5, 100), (38, 66, 200))
        coverage = float(np.count_nonzero(warm_gray, axis=1).min() / warm_gray.shape[1])
        if coverage < .85:
            return None
        rail_coverage.append(round(coverage, 4))

    left, top, right, bottom = _BOX
    ax, ay, bx, by = _INTERIOR
    hsv = cv2.cvtColor(pixels[ay:by, ax:bx], cv2.COLOR_BGR2HSV)
    x0, y0, x1, y1 = left-ax, top-ay, right-ax, bottom-ay
    value = hsv[:, :, 2]
    margins = (value[:y0], value[y1:], value[y0:y1, :x0], value[y0:y1, x1:])
    # Do not mistake a matching substring plus visible extra text for a toast.
    if sum(np.count_nonzero(margin >= 145) for margin in margins) > 8:
        return None
    ink = cv2.inRange(hsv[y0:y1, x0:x1], (17, 10, 155), (36, 44, 255))
    strokes = cv2.resize(ink, _GLYPH_SHAPE[::-1], interpolation=cv2.INTER_AREA) >= 128
    overlap = np.count_nonzero(strokes & _GLYPH_MASK, axis=0)
    union = np.count_nonzero(strokes | _GLYPH_MASK, axis=0)
    iou = np.add.reduceat(overlap, _GLYPH_STARTS) / np.add.reduceat(union, _GLYPH_STARTS)
    if iou.min() < .90:
        return None
    return dict(veto=True, stop_reason=STOP_REASON, label=LABEL, box=_BOX,
                proof="reviewed_zh_insufficient_kredits_banner",
                glyph_iou=tuple(round(float(score), 4) for score in iou),
                rail_coverage=tuple(rail_coverage))
