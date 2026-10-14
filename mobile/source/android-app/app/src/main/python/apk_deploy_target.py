"""Select an observed clear support-row landing area, without changing G8.

No input is performed. A unique HQ shield anchors a complete, evenly spaced,
centred row; every original occupied candidate must have a recognized type.
A single intact high-score type plate can locate a unit independently of its
numerals. An empty unit list alone never establishes a clear landing.
"""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
import cv2
import numpy as np

ROW_STEP = 144
LANDING_Y = 505
HALF_WIDTH = 58
PATCH_Y0, PATCH_Y1 = 435, 580
TYPES = frozenset(("infantry", "tank", "artillery", "fighter", "bomber"))
# Current card/HQ/UI geometry excludes occupied references before texture
# inspection. A reference overlapping the proposed landing patch is never
# evidence for that landing. Two full references, with a 32 px gap, must agree.
BACKGROUND_REFERENCES = {
    "wood": ((292, 270, 408, 415), (868, 270, 984, 415),
             (242, 270, 358, 415), (390, 270, 506, 415)),
    "japanese_cloth": ((362, 180, 478, 325), (802, 180, 918, 325),
                       (242, 270, 358, 415), (390, 270, 506, 415),
                       (732, 270, 848, 415),
                       (242, 362, 358, 507), (390, 362, 506, 507)),
    "painted_green": ((362, 180, 478, 325), (802, 180, 918, 325)),
    "blueprint_aircraft": ((240, 180, 356, 325), (390, 180, 506, 325),
                           (730, 180, 846, 325), (870, 180, 986, 325),
                           (370, 435, 486, 580), (920, 435, 1036, 580)),
}
# Only reviewed clean drawing pixels from the aircraft blueprint board exist
# in this atlas. Its initial HQs, card/hand/UI/prop regions are never templates
# for a clear slot. Position is absolute: a matching picture elsewhere is not
# a match. The mask must equal these rectangles, so it cannot silently grow.
BLUEPRINT_ATLAS_REGIONS = ((240, 180, 506, 325), (730, 130, 1000, 325),
                           (365, 435, 575, 580), (715, 435, 1058, 580))
# The two calibrated painted-green references sit exactly where the enemy's
# support row and mid row place cards, and the frontline divider moves into
# them, so on a fully developed green board every fixed reference can be
# occupied at once. A reference is only evidence of the surface, never of a
# slot, so the same calibrated box may be resolved per frame from a reviewed
# list of positions: the first candidate that is completely free of observed
# geometry (divider included) and still confirms the identical paint signature
# is used. Nothing about the signature, the patch size or the separation rule
# changes, and each candidate is verified on the frame in hand.
PAINTED_GREEN_FALLBACKS = ((390, 270, 506, 415),   # right of the left mid slot
                           (242, 270, 358, 415),   # left mid slot
                           (732, 270, 848, 415))   # right mid slot
REFERENCE_UI_BOUNDS = ((0, 0, 280, 165), (0, 165, 225, 275),
                       (280, 0, 1000, 100), (0, 300, 135, 425),
                       (940, 0, 1280, 265), (1000, 265, 1280, 440),
                       (1050, 450, 1280, 550),
                       (0, 495, 225, 720), (225, 515, 365, 720),
                       (0, 595, 1280, 720))


def _valid(frame):
    return (isinstance(frame, np.ndarray) and frame.shape == (720, 1280, 3)
            and frame.dtype == np.uint8)


def _row(frame):
    import mobile_board as mb
    evidence = {"hq": None, "units": [], "bounds": [], "centers": []}
    if not _valid(frame):
        return None, "invalid_frame", evidence
    transition = mb.board_transition_reason(frame)
    if transition:
        return None, "board_transition:" + transition, evidence
    front = mb.frontline_state(frame)
    evidence["frontline"] = front
    if front.get("owner") not in ("our", "enemy", "empty"):
        return None, "frontline_unknown", evidence
    anchors = []
    for candidate in mb._support_row_bright_cards(frame, "our"):
        shield, box = mb.hq_hp.find_shield(frame, candidate)
        if shield is not None and mb._hq_shield_geometry(candidate, box):
            anchors.append(candidate)
    if len(anchors) != 1:
        return None, "support_hq_structure_not_unique", evidence
    hq = dict(anchors[0], row_kind="hq")
    evidence["hq"] = hq
    detected = mb.cards_from_stats(frame, field=(200, 415, 1120, 595))
    if any(not 425 <= c["y"] <= 470 for c in detected):
        return None, "unclassified_support_geometry", evidence
    typed = None
    for card in detected:
        # Keep every raw occupied candidate. Only a single proven type plate
        # may repair its footprint; never count a filtered type list as empty.
        if card.get("n_stats") == 1:
            boxes = card.get("stat_boxes", [])
            if len(boxes) == 1 and mb._type_stat_plate(frame, boxes[0]):
                if typed is None:
                    typed = mb.cards_from_types(frame, field=(200, 415, 1120, 595))
                matches = [candidate for candidate in typed
                           if candidate.get("type") in TYPES and
                           tuple(boxes[0]) in [tuple(box) for box in candidate.get("stat_boxes", [])]]
                if len(matches) == 1:
                    card = dict(matches[0])
                else:
                    return None, "support_single_type_not_unique", evidence
            else:
                return None, "support_unit_evidence_incomplete", evidence
        unit_type = mb.unit_combat_type(frame, {"card": card, "row": "support"})
        observation = dict(card, type=unit_type, row_kind="unit")
        evidence["units"].append(observation)
        if card.get("n_stats", 0) < 1 or unit_type not in TYPES:
            return None, "support_unit_evidence_incomplete", evidence
    cards = sorted([hq] + evidence["units"], key=lambda c: c["cx"])
    centers = [int(c["cx"]) for c in cards]
    evidence["centers"] = centers
    # The game re-centres the whole support row after each deployment/death.
    # Missing an outer unit moves this observed centre; missing an inner unit
    # breaks spacing. Both are refusals, not free deployment slots.
    if abs(float(np.mean(centers)) - 640) > 12:
        return None, "support_row_not_completely_centered", evidence
    if any(not 132 <= b-a <= 156 for a, b in zip(centers, centers[1:])):
        return None, "support_row_has_missing_or_overlapping_slot", evidence
    if any(abs(c["y"] - hq["y"]) > 12 for c in cards):
        return None, "support_row_vertical_geometry_disagrees", evidence
    for card in cards:
        # Stats inference is narrower than the physical card; include its rim
        # and tabs. The HQ brightness crop ends at560, but the body ends~584.
        evidence["bounds"].append([int(card["x"])-10, int(card["y"])-8,
                                    int(card["x"]+card["w"])+20,
                                    max(586, int(card["y"]+card["h"])+8)])
    return cards, "complete_support_row", evidence


def _landing_pixels(frame, point, evidence, *, background_profile=None):
    x, y = point
    result = {"point": [x, y], "patch": [x-HALF_WIDTH, PATCH_Y0, x+HALF_WIDTH, PATCH_Y1]}
    if y != LANDING_Y or not 260 <= x <= 1060:
        return False, "point_outside_calibrated_support_landing", result
    x0, y0, x1, y1 = result["patch"]
    if any(max(x0, a) < min(x1, c) and max(y0, b) < min(y1, d)
           for a, b, c, d in evidence["bounds"]):
        return False, "landing_patch_intersects_observed_card", result
    patch = frame[y0:y1, x0:x1]
    hsv, gray, metrics = _pixel_metrics(patch)
    result["pixels"] = metrics
    observed = _background_profile(frame) if background_profile is None else background_profile
    profile = _profile_for_landing(observed, result["patch"])
    result["background_profile"] = profile
    if profile["profile"] is None:
        return False, "background_profile_not_confirmed", result
    # Once independently identified, a surface has exactly one landing test.
    # A dim/blurred card failing the cloth signature must never reach wood.
    if profile["profile"] == "japanese_cloth":
        clear, detail = _woven_background(hsv, gray, metrics)
        result["woven_background"] = detail
        return clear, ("card_sized_woven_background_confirmed" if clear
                       else "landing_pixels_not_confirmed_background"), result
    if profile["profile"] == "painted_green":
        clear, detail = _painted_green_background(hsv, gray, metrics)
        result["painted_green_background"] = detail
        return clear, ("card_sized_painted_green_background_confirmed" if clear
                       else "landing_pixels_not_confirmed_background"), result
    if profile["profile"] == "blueprint_aircraft":
        clear, detail = _blueprint_background(frame, result["patch"])
        result["blueprint_background"] = detail
        return clear, ("card_sized_blueprint_background_confirmed" if clear
                       else "landing_pixels_not_confirmed_background"), result
    clear, detail = _wood_background(hsv, gray, metrics, reference=False)
    result["wood_background"] = detail
    return clear, ("card_sized_background_patch_confirmed" if clear
                   else "landing_pixels_not_confirmed_background"), result


def _pixel_metrics(patch):
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 40, 100) > 0
    metrics = {"bright_fraction": float((hsv[:, :, 2] >= 135).mean()),
               "edge_fraction": float(edges.mean()),
               "vertical_edge_peak": float(edges.mean(axis=0).max()),
               "gray_std": float(gray.std())}
    # Two separated vertical discontinuities can be a dark/occluded card even
    # when no high-value pixels survive. Low thresholds intentionally abstain.
    column_jumps = np.mean(np.abs(np.diff(gray.astype(np.int16), axis=1)) > 14, axis=0)
    metrics["vertical_color_jump_peak"] = float(column_jumps.max())
    return hsv, gray, metrics


def _background_profile(frame):
    result = {"profile": None, "references": {}, "obstacles": []}
    try:
        obstacles = _reference_obstacles(frame)
    except (KeyError, TypeError, ValueError):
        result["reason"] = "invalid_reference_geometry"
        return result
    result["obstacles"] = obstacles
    for name, boxes in BACKGROUND_REFERENCES.items():
        observations = []
        for x0, y0, x1, y1 in boxes:
            box = [x0, y0, x1, y1]
            # Existing full-size wood samples may include the positively
            # located frontline divider. Keep that calibrated pixel behavior;
            # cards, HQs and UI still exclude both profiles. Cloth excludes
            # the divider too, since its weave must cover the whole patch.
            permitted_structure = [item for item in obstacles
                if name == "wood" and item["kind"] == "frontline_divider"
                and _overlap(box, item["box"])]
            overlaps = [item for item in obstacles if _overlap(box, item["box"])
                        and item not in permitted_structure]
            if overlaps:
                observations.append({"box": box, "confirmed": False,
                    "detail": {"rejection": "reference_intersects_observed_geometry",
                               "obstacles": overlaps}})
                continue
            hsv, gray, raw = _pixel_metrics(frame[y0:y1, x0:x1])
            if name == "blueprint_aircraft":
                clear, detail = _blueprint_background(frame, box)
            elif name == "japanese_cloth":
                clear, detail = _woven_background(hsv, gray, raw)
            elif name == "painted_green":
                clear, detail = _painted_green_background(hsv, gray, raw)
            else:
                clear, detail = _wood_background(hsv, gray, raw, reference=True)
            observations.append({"box": [x0, y0, x1, y1], "confirmed": clear, "detail": detail,
                                 "permitted_board_structure": permitted_structure})
        if name == "painted_green":
            observations.extend(_painted_green_fallbacks(frame, obstacles, observations))
        result["references"][name] = observations
    selected = _profile_for_landing(result)
    selected["frame"] = frame
    return selected


def _painted_green_fallbacks(frame, obstacles, primary):
    """Resolve the calibrated paint box at the reviewed free position.

    Only the position may vary: the box size, the paint signature and the
    independence rule are unchanged, and a fallback is reported exactly like a
    primary reference so the selection logic treats it identically. Skipped
    only when a calibrated painted-green position itself already holds; other
    profiles' references are a different surface and must not suppress it.

    A reviewed position that is occupied is not abandoned: the band is scanned
    at the same calibrated box size, because the enemy support row and the mid
    row sit exactly on those positions late in a match. Every probe is verified
    on this frame, so an occupied or non-paint patch is still refused - a scan
    can never turn a card into evidence for the surface.
    """
    if any(item["confirmed"] and not item.get("fallback") for item in primary):
        return []
    observations = []
    seen = set()
    confirmed = 0
    # The landing slot sits inside this band, so boxes that overlap either
    # landing position are excluded here: they could never serve as evidence
    # for that landing, and accepting one would waste the independence pair.
    landing_boxes = [[x - HALF_WIDTH, PATCH_Y0, x + HALF_WIDTH, PATCH_Y1]
                     for x in (min(1060, 640 + ROW_STEP), max(260, 640 - ROW_STEP),
                               640, 640 + ROW_STEP, 640 - ROW_STEP, 640 + 2 * ROW_STEP,
                               640 - 2 * ROW_STEP)]
    # Bounded scan of the support band at the one calibrated box size. Offsets
    # repeat across the reviewed positions, so each box is tested once. The row
    # heights cover the reviewed positions plus the lower band that stays clear
    # once both support rows fill up.
    for y0 in (270, 200, 340, 420, 130):
        for x0 in range(200, 1061, 40):
            box = [x0, y0, x0 + 116, y0 + 145]
            key = tuple(box)
            if key in seen:
                continue
            seen.add(key)
            if any(_overlap(box, landing) for landing in landing_boxes):
                continue
            # Two separated confirmations already satisfy the independence
            # rule; further probing cannot change the outcome for this frame.
            if confirmed >= 2:
                break
            overlaps = [item for item in obstacles if _overlap(box, item["box"])]
            if overlaps:
                continue
            hsv, gray, raw = _pixel_metrics(frame[box[1]:box[3], box[0]:box[2]])
            clear, detail = _painted_green_background(hsv, gray, raw)
            observations.append({"box": box, "confirmed": clear, "detail": detail,
                                 "fallback": True, "permitted_board_structure": []})
            if clear:
                confirmed += 1
    return observations


def _profile_for_landing(observed, landing_patch=None):
    """Select independent evidence without rescanning this frame's pixels.

    Lower cloth candidates can enter the support strip, but overlapping the
    proposed landing disqualifies a complete reference, not merely its overlap.
    """
    result = {"profile": None, "references": {}, "obstacles": observed.get("obstacles", [])}
    if observed.get("reason") == "invalid_reference_geometry":
        result["reason"] = "invalid_reference_geometry"
        return result
    positive_profiles = []
    usable_pairs = {}
    for name, references in observed["references"].items():
        observations = []
        for reference in references:
            if landing_patch is not None and (_overlap(reference["box"], landing_patch)
                    or (name == "blueprint_aircraft"
                        and not _separated(reference["box"], landing_patch))):
                observations.append(dict(reference, confirmed=False, detail={
                    "rejection": "reference_intersects_landing_patch",
                    "landing_patch": list(landing_patch)}))
            else:
                observations.append(reference)
        result["references"][name] = observations
        positives = [item["box"] for item in observations if item["confirmed"]]
        if positives:
            positive_profiles.append(name)
        # Nearby overlapping candidates cannot count as independent evidence.
        # Prefer the widest available separation when more than two pass.
        pairs = []
        for index, a in enumerate(positives):
            for b in positives[index+1:]:
                if _separated(a, b):
                    distance = ((a[0]+a[2]-b[0]-b[2])**2
                                + (a[1]+a[3]-b[1]-b[3])**2)
                    pairs.append((distance, a, b))
        if pairs:
            _, a, b = max(pairs, key=lambda item: item[0])
            usable_pairs[name] = [a, b]
    # Even one positive region from a conflicting surface makes this unknown.
    if len(positive_profiles) == 1 and positive_profiles[0] in usable_pairs:
        result["profile"] = positive_profiles[0]
        result["selected_references"] = usable_pairs[positive_profiles[0]]
    elif (len(positive_profiles) == 1 and positive_profiles[0] == "painted_green"
            and landing_patch is not None and observed.get("frame") is not None):
        # A developed green board can leave only one free painted region: the
        # calibrated box is 116x145 with a required 32 px clear gap, and the
        # enemy support/mid rows plus the moving divider cover the rest. The
        # second, independent observation then comes from the landing patch
        # itself: it must pass the identical paint signature before the surface
        # is selected, so the decision still rests on two separated paint
        # observations and no threshold, patch size or gap is relaxed.
        single = [item["box"] for item in result["references"]["painted_green"]
                  if item["confirmed"] and not _overlap(item["box"], landing_patch)]
        if single:
            frame = observed["frame"]
            x0, y0, x1, y1 = landing_patch
            hsv, gray, raw = _pixel_metrics(frame[y0:y1, x0:x1])
            clear, detail = _painted_green_background(hsv, gray, raw)
            result["landing_paint"] = detail
            if clear:
                # Prefer the free region furthest from the landing so the two
                # paint observations are as independent as this frame allows.
                best = max(single, key=lambda box: (box[0] - x0) ** 2 + (box[1] - y0) ** 2)
                result["profile"] = "painted_green"
                result["selected_references"] = [best, list(landing_patch)]
    if result["profile"] is None:
        result["reason"] = ("conflicting_background_evidence" if len(positive_profiles) > 1
                            else "insufficient_separated_references")
    return result


@lru_cache(maxsize=1)
def _blueprint_atlas():
    """Load Chaquopy-packaged data beside this module; missing data abstains."""
    directory = Path(__file__).resolve().parent / "deploy-fixtures"
    try:
        # imdecode also handles host paths containing non-ASCII characters.
        atlas = cv2.imdecode(np.frombuffer(
            (directory / "blueprint-aircraft-atlas.png").read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        mask = cv2.imdecode(np.frombuffer(
            (directory / "blueprint-aircraft-mask.png").read_bytes(), np.uint8), cv2.IMREAD_GRAYSCALE)
    except (OSError, ValueError, cv2.error):
        return None
    if not _valid(atlas) or mask is None or mask.shape != (720, 1280):
        return None
    expected = np.zeros((720, 1280), np.uint8)
    for x0, y0, x1, y1 in BLUEPRINT_ATLAS_REGIONS:
        expected[y0:y1, x0:x1] = 255
    if not np.array_equal(mask, expected) or np.any(atlas[mask == 0]):
        return None
    atlas.setflags(write=False)
    mask.setflags(write=False)
    return atlas, mask


def _blueprint_background(frame, box):
    """Confirm the full same-coordinate drawing, never a generic blue patch.

    This narrow profile recognizes one reviewed board and scale. Two separate
    unobstructed reference patches are still mandatory; this function separately
    verifies the landing's complete 116x145 pixels against the clean atlas.
    """
    detail = {"profile": "blueprint_aircraft_1280x720", "confirmed": False,
              "box": list(box)}
    if (not _valid(frame) or len(box) != 4
            or any(type(value) is not int for value in box)):
        detail["rejection"] = "blueprint_invalid_geometry"
        return False, detail
    x0, y0, x1, y1 = box
    if not (0 <= x0 < x1 <= 1280 and 0 <= y0 < y1 <= 720
            and x1-x0 == 116 and y1-y0 == 145):
        detail["rejection"] = "blueprint_invalid_geometry"
        return False, detail
    loaded = _blueprint_atlas()
    if loaded is None:
        detail["rejection"] = "blueprint_atlas_unavailable"
        return False, detail
    atlas, mask = loaded
    if not bool((mask[y0:y1, x0:x1] == 255).all()):
        detail["rejection"] = "blueprint_unreviewed_coordinates"
        return False, detail
    expected = atlas[y0:y1, x0:x1]
    patch = frame[y0:y1, x0:x1]
    difference = np.abs(patch.astype(np.int16) - expected.astype(np.int16))
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    expected_gray = cv2.cvtColor(expected, cv2.COLOR_BGR2GRAY)
    # A flat/near-flat atlas region could not establish a drawing's identity.
    detail["template_gray_std"] = float(expected_gray.std())
    if detail["template_gray_std"] < 3:
        detail["rejection"] = "blueprint_template_not_distinctive"
        return False, detail
    detail["mean_absolute_color_difference"] = float(difference.mean())
    detail["pixel_error_fraction"] = float((difference.max(axis=2) > 12).mean())
    detail["drawing_correlation"] = float(cv2.matchTemplate(
        gray, expected_gray, cv2.TM_CCOEFF_NORMED)[0, 0])
    tile_errors = []
    for rows in np.array_split(np.arange(145), 5):
        for columns in np.array_split(np.arange(116), 4):
            tile_errors.append(float(difference[
                rows[0]:rows[-1]+1, columns[0]:columns[-1]+1].mean()))
    detail["tile_maximum_color_difference"] = max(tile_errors)
    if (detail["mean_absolute_color_difference"] > 1
            or detail["pixel_error_fraction"] > .004
            or not math.isfinite(detail["drawing_correlation"])
            or detail["drawing_correlation"] < .985
            or detail["tile_maximum_color_difference"] > 2):
        detail["rejection"] = "blueprint_same_coordinate_drawing_mismatch"
        return False, detail
    detail["confirmed"] = True
    return True, detail


def _overlap(a, b):
    return max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3])


def _separated(a, b):
    return (a[2] + 32 <= b[0] or b[2] + 32 <= a[0]
            or a[3] + 32 <= b[1] or b[3] + 32 <= a[1])


def _reference_obstacles(frame):
    """Observed obstacles exclude references; their absence never proves clear."""
    import mobile_board as mb
    obstacles = [{"kind": "ui_or_prop", "box": list(box)} for box in REFERENCE_UI_BOUNDS]
    # Include every detected card in all three rows, irrespective of identity,
    # actionability or ownership. Unknown type is still an occupied rectangle.
    cards = list(mb.cards_from_stats(frame, field=(130, 85, 1150, 595)))
    for side in ("our", "enemy"):
        for candidate in mb._support_row_bright_cards(frame, side):
            shield, box = mb.hq_hp.find_shield(frame, candidate)
            if shield is not None and mb._hq_shield_geometry(candidate, box):
                cards.append(candidate)
    for card in cards:
        numbers = [card[key] for key in ("x", "y", "w", "h")]
        if any(not isinstance(n, (int, float)) or not math.isfinite(n) for n in numbers):
            raise ValueError("invalid_card_geometry")
        x, y, w, h = numbers
        if w <= 0 or h <= 0:
            raise ValueError("invalid_card_geometry")
        obstacles.append({"kind": "observed_card_or_hq",
                          "box": [int(x)-10, int(y)-8, int(x+w)+20, int(y+h)+8]})
    front = mb.frontline_state(frame)
    line = front.get("evidence", {}).get("line_y")
    if front.get("owner") not in ("our", "enemy", "empty") or not isinstance(line, (int, float)):
        raise ValueError("unknown_frontline_geometry")
    obstacles.append({"kind": "frontline_divider", "box": [315, int(line)-8, 965, int(line)+8]})
    return obstacles


def _wood_background(hsv, gray, raw, *, reference):
    """Require brown horizontal grain throughout; low edge count is insufficient."""
    detail = {"profile": "wood_1280x720", "confirmed": False}
    if (raw["bright_fraction"] > .025 or raw["gray_std"] < 2
            or (not reference and (raw["edge_fraction"] > .08
                or raw["vertical_edge_peak"] > .20 or raw["vertical_color_jump_peak"] > .20))):
        detail["rejection"] = "raw_clearance"
        return False, detail
    brown = ((hsv[:, :, 0] >= 8) & (hsv[:, :, 0] <= 18)
             & (hsv[:, :, 1] >= 100) & (hsv[:, :, 1] <= 210))
    detail["brown_fraction"] = float(brown.mean())
    if detail["brown_fraction"] < .96:
        detail["rejection"] = "wood_color_not_confirmed"
        return False, detail
    tiles, tile_regions = [], []
    for rows in np.array_split(np.arange(gray.shape[0]), 4):
        for columns in np.array_split(np.arange(gray.shape[1]), 4):
            region = np.s_[rows[0]:rows[-1]+1, columns[0]:columns[-1]+1]
            tile_regions.append(region)
            g = gray[region].astype(np.float64)
            dx = float(np.abs(np.diff(g, axis=1)).mean())
            dy = float(np.abs(np.diff(g, axis=0)).mean())
            tiles.append([dx, dy, dy / max(dx, .01), float(g.std()), float(brown[region].mean())])
    values = np.asarray(tiles)
    detail["tile_columns"] = ["dx", "dy", "grain_ratio", "gray_std", "brown_fraction"]
    detail["tile_minima"] = values.min(axis=0).tolist()
    detail["tile_maxima"] = values.max(axis=0).tolist()
    # Front-row reference grain is stronger than the shadowed support strip.
    # These are separate positive profiles, not relaxed landing thresholds.
    min_dy, min_ratio, max_std, min_brown = (2.5, 1.75, 24, .80) if reference else (1.2, 1.35, 12, .90)
    valid = ((values[:, 0] >= .4) & (values[:, 0] <= 2.5)
             & (values[:, 1] >= min_dy) & (values[:, 1] <= 7)
             & (values[:, 2] >= min_ratio) & (values[:, 3] >= 2)
             & (values[:, 3] <= max_std) & (values[:, 4] >= min_brown))
    if reference and not bool(valid.all()):
        # Dim/smoothed wood can retain directional grain below the original
        # absolute dy=2.5 reference threshold. Only those weak-energy tiles may
        # use dimensionless evidence; all other original conditions remain.
        eligible = ((values[:, 0] >= .4) & (values[:, 0] <= 2.5)
                    & (values[:, 1] >= 1.2) & (values[:, 1] < min_dy)
                    & (values[:, 2] >= min_ratio) & (values[:, 3] >= 2)
                    & (values[:, 3] <= max_std) & (values[:, 4] >= min_brown))
        if bool(eligible.any()):
            residual = gray.astype(np.float64) - cv2.GaussianBlur(gray, (9, 9), 2.0)
            recovered = []
            for index in np.flatnonzero(eligible):
                r = residual[tile_regions[index]]
                dy_ratio = float(values[index, 1] / values[index, 3])
                residual_ratio = float(r.std() / values[index, 3])
                x_corr = _correlation(r[:, :-3], r[:, 3:])
                y_corr = _correlation(r[:-3, :], r[3:, :])
                confirmed = (dy_ratio >= .40 and residual_ratio >= .44
                             and x_corr >= .20 and y_corr <= -.20)
                recovered.append({"tile": int(index), "dy_over_std": dy_ratio,
                    "residual_over_std": residual_ratio, "x_lag3_correlation": x_corr,
                    "y_lag3_correlation": y_corr, "confirmed": confirmed})
                valid[index] = confirmed
            detail["contrast_normalized_reference_tiles"] = recovered
    if not bool(valid.all()):
        detail["rejection"] = "incomplete_wood_grain"
        detail["rejected_tiles"] = np.flatnonzero(~valid).tolist()
        return False, detail
    detail["confirmed"] = True
    return True, detail


def _correlation(a, b):
    a = a.ravel().astype(np.float64)
    b = b.ravel().astype(np.float64)
    a -= a.mean()
    b -= b.mean()
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denominator) if denominator > 0 else 0.0


def _painted_green_background(hsv, gray, raw):
    """Positive signature of the calibrated dark green painted board.

    Both references and landing use the complete 116x145 patch. Every tile
    must retain the low-contrast mottling and narrow, non-flat pigment color;
    a dim card, smooth fill or failed cloth/wood check is never evidence.
    Strong scratches are intentionally unknown, even on this same board.
    """
    detail = {"profile": "painted_green_1280x720", "confirmed": False}
    if (gray.shape != (145, 116) or raw["bright_fraction"] > .001
            or raw["edge_fraction"] > .008 or raw["vertical_edge_peak"] > .05
            or raw["vertical_color_jump_peak"] > .04):
        detail["rejection"] = "paint_structure_or_patch_size"
        return False, detail
    colors = ((hsv[:, :, 0] >= 31) & (hsv[:, :, 0] <= 41)
              & (hsv[:, :, 1] >= 55) & (hsv[:, :, 1] <= 90))
    detail["paint_color_fraction"] = float(colors.mean())
    if detail["paint_color_fraction"] < .985:
        detail["rejection"] = "paint_color_not_confirmed"
        return False, detail
    low = cv2.GaussianBlur(gray, (9, 9), 2.0)
    residual = gray.astype(np.float64) - low.astype(np.float64)
    tiles = []
    for rows in np.array_split(np.arange(gray.shape[0]), 5):
        for columns in np.array_split(np.arange(gray.shape[1]), 4):
            region = np.s_[rows[0]:rows[-1]+1, columns[0]:columns[-1]+1]
            g, h, r = gray[region].astype(np.float64), hsv[region], residual[region]
            tiles.append([float(np.median(h[:, :, 0])), float(np.median(h[:, :, 1])),
                          float(np.median(h[:, :, 2])), float(colors[region].mean()),
                          float(g.std()), float(low[region].std()), float(r.std()),
                          float(np.abs(np.diff(g, axis=0)).mean()),
                          float(np.abs(np.diff(g, axis=1)).mean()),
                          _correlation(r[:, :-1], r[:, 1:]),
                          _correlation(r[:-1, :], r[1:, :]),
                          float(h[:, :, 0].std()), float(h[:, :, 1].std())])
    values = np.asarray(tiles)
    detail["tile_count"] = len(tiles)
    detail["tile_columns"] = ["hue_median", "saturation_median", "value_median",
                              "paint_color_fraction", "gray_std", "low_std", "residual_std",
                              "dy", "dx", "x_lag1_correlation", "y_lag1_correlation",
                              "hue_std", "saturation_std"]
    detail["tile_minima"] = values.min(axis=0).tolist()
    detail["tile_maxima"] = values.max(axis=0).tolist()
    valid = ((values[:, 0] >= 34) & (values[:, 0] <= 39)
             & (values[:, 1] >= 62) & (values[:, 1] <= 82)
             & (values[:, 2] >= 35) & (values[:, 2] <= 88) & (values[:, 3] >= .97)
             & (values[:, 4] >= .8) & (values[:, 4] <= 6.5)
             & (values[:, 5] >= .5) & (values[:, 5] <= 6)
             & (values[:, 6] >= .45) & (values[:, 6] <= 2.2)
             & (values[:, 7] >= .25) & (values[:, 7] <= 1.3)
             & (values[:, 8] >= .25) & (values[:, 8] <= 1.3)
             & (values[:, 9] >= .15) & (values[:, 9] <= .85)
             & (values[:, 10] >= .15) & (values[:, 10] <= .85)
             & (values[:, 11] >= .5) & (values[:, 11] <= 1.9)
             & (values[:, 12] >= 1.1) & (values[:, 12] <= 3.5))
    if not bool(valid.all()):
        detail["rejection"] = "incomplete_paint_signature"
        detail["rejected_tiles"] = np.flatnonzero(~valid).tolist()
        return False, detail
    detail["confirmed"] = True
    return True, detail


def _woven_background(hsv, gray, raw):
    """Positive signature of the 1280x720 Japanese cloth, never generic texture.

    Low-pass structure must be clear AND every subregion must retain the
    observed weave's high-frequency energy, color and repeating x/y pattern.
    An untextured/dim/blurred card cannot pass solely because its edges fade.
    The caller has already required complete HQ/unit geometry and clearance.
    """
    detail = {"profile": "japanese_cloth_1280x720", "confirmed": False}
    if (raw["bright_fraction"] > .025 or raw["edge_fraction"] < .25
            or raw["vertical_color_jump_peak"] < .35):
        detail["rejection"] = "not_dense_dark_weave"
        return False, detail
    low = cv2.GaussianBlur(gray, (9, 9), 2.0)
    edges = cv2.Canny(low, 25, 60) > 0
    colors = ((hsv[:, :, 0] >= 29) & (hsv[:, :, 0] <= 39)
              & (hsv[:, :, 1] >= 75) & (hsv[:, :, 1] <= 150))
    metrics = {"low_edge_fraction": float(edges.mean()),
               "low_vertical_edge_peak": float(edges.mean(axis=0).max()),
               "low_gray_std": float(low.std()),
               "weave_color_fraction": float(colors.mean())}
    detail["metrics"] = metrics
    if (metrics["low_edge_fraction"] > .015
            or metrics["low_vertical_edge_peak"] > .10
            or not 3 <= metrics["low_gray_std"] <= 12
            or metrics["weave_color_fraction"] < .95):
        detail["rejection"] = "low_frequency_structure_or_color"
        return False, detail
    residual = gray.astype(np.float64) - low.astype(np.float64)
    tiles = []
    # Split the complete patch, including its right/bottom remainder. No card
    # rim, title or stat region may be excluded by a hand-picked centre crop.
    for rows in np.array_split(np.arange(gray.shape[0]), 8):
        for columns in np.array_split(np.arange(gray.shape[1]), 7):
            region = np.s_[rows[0]:rows[-1]+1, columns[0]:columns[-1]+1]
            r, l, h = residual[region], low[region], hsv[region]
            tiles.append([float(r.std()), float(l.std()),
                          float(np.median(h[:, :, 0])), float(np.median(h[:, :, 1])),
                          _correlation(r[:, :-2], r[:, 2:]),
                          _correlation(r[:, :-5], r[:, 5:]),
                          _correlation(r[:-3, :], r[3:, :])])
    values = np.asarray(tiles)
    detail["tile_count"] = len(tiles)
    detail["tile_columns"] = ["residual_std", "low_std", "hue_median", "saturation_median",
                              "x_lag2_correlation", "x_lag5_correlation", "y_lag3_correlation"]
    detail["tile_minima"] = values.min(axis=0).tolist()
    detail["tile_maxima"] = values.max(axis=0).tolist()
    valid = ((values[:, 0] >= 8) & (values[:, 0] <= 21) & (values[:, 1] <= 10)
             & (values[:, 2] >= 30) & (values[:, 2] <= 38)
             & (values[:, 3] >= 90) & (values[:, 3] <= 140)
             & (values[:, 4] <= -.10) & (values[:, 5] >= .10) & (values[:, 6] >= .30))
    if not bool(valid.all()):
        detail["rejection"] = "incomplete_weave_signature"
        detail["rejected_tiles"] = np.flatnonzero(~valid).tolist()
        return False, detail
    detail["confirmed"] = True
    return True, detail


def inspect_clear(frame, point):
    """Recheck current geometry and the entire landing patch on a fresh frame."""
    result = {"clear": False, "point": None, "reason": "invalid_point", "evidence": {}}
    if (not isinstance(point, (tuple, list)) or len(point) != 2
            or any(type(v) not in (int, float) or not math.isfinite(v) or int(v) != v for v in point)):
        return result
    point = [int(v) for v in point]
    result["point"] = point
    cards, reason, evidence = _row(frame)
    result["evidence"]["row"] = evidence
    if cards is None:
        result["reason"] = reason
        return result
    clear, reason, pixels = _landing_pixels(frame, point, evidence)
    result.update(clear=clear, reason=reason)
    result["evidence"]["landing"] = pixels
    return result


def is_clear(frame, point):
    """Boolean guard for the final input boundary; UNKNOWN always means False."""
    return inspect_clear(frame, point)["clear"]


def choose_drop(frame):
    """Return {point, reason, evidence}; point=None never authorizes a gesture."""
    cards, reason, evidence = _row(frame)
    result = {"point": None, "reason": reason, "evidence": {"row": evidence, "candidates": []}}
    if cards is None:
        return result
    # Prefer outside the rightmost observed card, then the left side. Clamping
    # is bounded to the board; the full patch still must clear every card.
    candidates = [(min(1060, int(cards[-1]["cx"])+ROW_STEP), LANDING_Y),
                  (max(260, int(cards[0]["cx"])-ROW_STEP), LANDING_Y)]
    # Both candidates inspect this exact frame. Share only this call's result;
    # inspect_clear at the input boundary still re-observes its fresh frame.
    profile = _background_profile(frame)
    for point in candidates:
        clear, why, patch = _landing_pixels(frame, point, evidence, background_profile=profile)
        result["evidence"]["candidates"].append(dict(patch, clear=clear, reason=why))
        if clear:
            result.update(point=list(point), reason="observed_clear_outer_support_slot")
            return result
    # Keep either original point whenever it passes. On confirmed wood only,
    # a knot or seam may intersect that exact full-size patch. Probe one small
    # outward shift per original empty outer slot; never shrink the patch or
    # relax its pixels. The final inspect_clear checks this exact chosen point.
    if profile["profile"] == "wood":
        for index, original in enumerate(candidates):
            offset = 24 if index == 0 else -24
            point = (original[0] + offset, LANDING_Y)
            if not 260 <= point[0] <= 1060:
                continue
            clear, why, patch = _landing_pixels(frame, point, evidence, background_profile=profile)
            result["evidence"]["candidates"].append(dict(patch, clear=clear, reason=why,
                                                        outer_slot_offset=offset))
            if clear:
                result.update(point=list(point), reason="observed_clear_outer_support_slot")
                return result
    result["reason"] = "no_confirmed_clear_outer_support_slot"
    return result
