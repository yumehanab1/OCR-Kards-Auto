"""Mobile combat glyphs: unit type and right-edge Guard/Protected markers.

Only calibrated 1280x720 mobile card geometry is accepted. No card artwork,
cost, nation emblem or historical action state is used to infer unit type.
"""
from __future__ import annotations
import json
from functools import lru_cache
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
TYPES = ('infantry', 'tank', 'artillery', 'fighter', 'bomber')
TYPE_MIN = 0.80
TYPE_MARGIN = 0.12
GUARD_MIN = 0.90
GUARD_UNKNOWN_MIN = 0.75
GUARD_MARGIN = 0.065
OTHER_MARKER_MIN = 0.92
OTHER_MARKER_MARGIN = 0.08


@lru_cache(maxsize=1)
def _bank():
    try:
        config = json.loads((ROOT/'config/templates.android.combat.json').read_text(encoding='utf8'))
        result = {}
        for name, item in config['templates'].items():
            image = cv2.imdecode(np.fromfile(ROOT/item['path'], dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
            if image is not None:
                result[name.removeprefix('combat_')] = image
        return result
    except (OSError, ValueError, KeyError, cv2.error):
        return {}


def _valid(frame):
    return (isinstance(frame, np.ndarray) and frame.shape == (720, 1280, 3)
            and frame.dtype == np.uint8)


def _geometry(card):
    if not isinstance(card, dict):
        return None
    try:
        values = tuple(int(card[k]) for k in ('x', 'y', 'w', 'h'))
        if any(float(card[k]) != value for k, value in zip(('x', 'y', 'w', 'h'), values)):
            return None
        return values
    except (TypeError, KeyError, ValueError, OverflowError):
        return None


def _normalized_icon(crop):
    # Remove the frame highlight; compare the complete type glyph and its dark plate.
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    return cv2.resize(gray[2:-2, 2:-2], (32, 32), interpolation=cv2.INTER_AREA)


def _raw_stat_plates(frame, field):
    """Complete original dark components; no numeral or color recognition."""
    if (not _valid(frame) or not isinstance(field, (tuple, list)) or len(field) != 4
            or any(type(value) is not int for value in field)):
        return []
    x0, y0, x1, y1 = field
    if not (0 <= x0 < x1 <= 1280 and 0 <= y0 < y1 <= 720):
        return []
    import mobile_board as mb
    mask = (cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)[:, :, 2] < mb.STAT_DARK_V).astype(np.uint8)
    # Detect the full component before restricting its footprint to the field.
    # A crop must never manufacture a smaller, apparently complete plate.
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    return [(int(x), int(y), int(w), int(h)) for x, y, w, h, area in stats[1:]
            if 23 <= w <= 34 and 23 <= h <= 35 and area >= .55*w*h
            and x0 <= x and y0 <= y and x+w <= x1 and y+h <= y1]


def type_stat_plates(frame, field=(200, 70, 1120, 595), min_score=.90):
    """Independent type anchors use the core's .90 corroboration threshold."""
    bank = _bank()
    if not _valid(frame) or not all(name in bank for name in TYPES):
        return []
    result = []
    for box in _raw_stat_plates(frame, field):
        x, y, w, h = box
        glyph = _normalized_icon(frame[y:y+h, x:x+w])
        scores = {name: float(cv2.matchTemplate(glyph, _normalized_icon(bank[name]),
                                               cv2.TM_CCOEFF_NORMED)[0, 0]) for name in TYPES}
        order = sorted(scores, key=scores.get, reverse=True)
        if scores[order[0]] >= min_score and scores[order[0]]-scores[order[1]] >= TYPE_MARGIN:
            result.append({'box': list(box), 'type': order[0], 'scores': scores})
    return result


def inspect_unit_type(frame, unit):
    out = {'type': 'unknown', 'scores': {}, 'icon_box': None, 'reason': '未确认类型图标'}
    if not _valid(frame):
        return dict(out, reason='未标定截图尺寸')
    card = unit.get('card', unit) if isinstance(unit, dict) else {}
    geometry = _geometry(card)
    if geometry is None:
        return out
    x, y, w, h = geometry
    if not (90 <= w <= 120 and 130 <= h <= 160 and 200 <= x < 1120 and 70 <= y <= 490):
        return dict(out, reason='未标定卡体几何')
    boxes = _raw_stat_plates(frame, (max(0,x-8), max(0,y+90), min(1280,x+w+12), min(610,y+h+12)))
    mid = [b for b in boxes if abs((b[0]+b[2]/2)-(x+w/2)) <= 12 and
           y+h-47 <= b[1] <= y+h-13 and 23 <= b[2] <= 34 and 23 <= b[3] <= 35]
    if len(mid) != 1:
        return dict(out, reason='卡底中间图标未唯一定位')
    bx, by, bw, bh = mid[0]
    # The calibrated card footprint and unique complete middle glyph establish
    # type. Unreadable attack/defense numerals do not invalidate that glyph.
    got = _normalized_icon(frame[by:by+bh,bx:bx+bw])
    bank = _bank()
    if not all(name in bank for name in TYPES):
        return dict(out, reason='类型模板不完整')
    scores = {name:float(cv2.matchTemplate(got, _normalized_icon(bank[name]), cv2.TM_CCOEFF_NORMED)[0,0])
              for name in TYPES}
    order = sorted(scores, key=scores.get, reverse=True)
    out.update(scores=scores, icon_box=list(mid[0]))
    if scores[order[0]] >= TYPE_MIN and scores[order[0]]-scores[order[1]] >= TYPE_MARGIN:
        out.update(type=order[0], reason='卡底中间类型图标匹配')
    return out


def unit_combat_type(frame, unit):
    return inspect_unit_type(frame, unit)['type']


def guard_glyph(frame, card):
    out = {'state':'unknown','scores':{},'reason':'未确认守护区域'}
    if not _valid(frame) or not card:
        return out
    geometry = _geometry(card)
    if geometry is None:
        return out
    x,y,w,h = geometry
    if not (90 <= w <= 120 and 125 <= h <= 165 and 200 <= x < 1100 and 70 <= y <= 490):
        return out
    bank = _bank()
    if not all(k in bank for k in ('guard_unit','guard_hq')):
        return dict(out,reason='守护模板不完整')
    # Green attack values may be absent from stats detection. In a two-plate
    # group the inferred card can start at its TYPE plate instead of ATTACK.
    # A confirmed type glyph supplies the true center without reading artwork.
    icon_centers=[]
    stat_boxes=card.get('stat_boxes', [])
    if not isinstance(stat_boxes, (list, tuple)):
        return dict(out,reason='攻防框几何无效')
    for box in stat_boxes:
        try:
            if len(box)!=4 or any(int(v)!=v for v in box):
                return dict(out,reason='攻防框几何无效')
            bx,by,bw,bh=(int(v) for v in box)
        except (TypeError, ValueError, OverflowError):
            return dict(out,reason='攻防框几何无效')
        if not (23<=bw<=35 and 23<=bh<=35 and x-8<=bx<=x+w+8 and
                y+h-50<=by<=y+h-13 and 0<=bx and 0<=by and
                bx+bw<=1280 and by+bh<=720):
            return dict(out,reason='攻防框不属于当前卡体')
        crop=frame[by:by+bh,bx:bx+bw]
        if crop.size and bw>4 and bh>4:
            got=_normalized_icon(crop)
            scores=sorted((float(cv2.matchTemplate(got,_normalized_icon(bank[t]),cv2.TM_CCOEFF_NORMED)[0,0])
                           for t in TYPES if t in bank),reverse=True)
            if len(scores)>=2 and scores[0]>=0.90 and scores[0]-scores[1]>=TYPE_MARGIN:
                icon_centers.append((bx+bw/2,by))
    if len(icon_centers)==1:
        center,stat_y=icon_centers[0]
        corrected_x=int(round(center-56));corrected_y=int(stat_y-111)
        if abs(corrected_x-x)>40 or abs(corrected_y-y)>12:
            return dict(out,reason='类型图标与卡体位置矛盾')
        x=corrected_x;w=112;y=corrected_y
    # A stats-inferred card is ~12px narrower than the outer card. Restrict the
    # search to its right-edge tab, excluding neighboring card cost/nation icons.
    x0,x1=max(0,x+w-5),min(1280,x+w+40)
    y0,y1=max(0,y),min(720,y+52)
    win=cv2.cvtColor(frame[y0:y1,x0:x1],cv2.COLOR_BGR2GRAY)
    if float(win.std())<5:
        return dict(out,reason='守护区域缺少有效画面')
    scores={}; locations={}
    for name in ('guard_unit','guard_hq'):
        template=bank[name]
        if win.shape[0]<template.shape[0] or win.shape[1]<template.shape[1]:
            return out
        variants=(template,cv2.flip(template,1)) if name=='guard_hq' else (template,)
        matches=[]
        for variant in variants:
            result=cv2.matchTemplate(win,variant,cv2.TM_CCOEFF_NORMED)
            _,score,_,location=cv2.minMaxLoc(result)
            matches.append((score,location))
        score,location=max(matches,key=lambda item:item[0])
        scores[name]=float(score); locations[name]=[x0+location[0],y0+location[1]]
    order=sorted(scores,key=scores.get,reverse=True)
    best,other=order
    out.update(scores=scores,at=locations[best])
    if scores[best]>=GUARD_MIN and scores[best]-scores[other]>=GUARD_MARGIN:
        out.update(state='guard' if best=='guard_unit' else 'protected',reason='右上守护字形匹配')
    else:
        # The orange skull shares the shield's dark tab, producing ~0.81 NCC
        # against Guard despite its visibly different inner glyph. Only a
        # separately annotated, high-margin known non-shield may clear this
        # ambiguity; missing templates and unfamiliar badges stay unknown.
        negative=bank.get('marker_skull')
        other_score=0.0
        if negative is not None and win.shape[0]>=negative.shape[0] and win.shape[1]>=negative.shape[1]:
            _,other_score,_,other_location=cv2.minMaxLoc(cv2.matchTemplate(win,negative,cv2.TM_CCOEFF_NORMED))
            out['other_scores']={'marker_skull':float(other_score)}
        if (scores[best]<GUARD_MIN and other_score>=OTHER_MARKER_MIN and
                other_score-scores[best]>=OTHER_MARKER_MARGIN):
            out.update(state='clear',reason='右上已确认骷髅标记，不是守护盾',
                       non_guard_marker='skull',at=[x0+other_location[0],y0+other_location[1]])
        elif scores[best]<GUARD_UNKNOWN_MIN:
            out.update(state='clear',reason='已标定标记窗未见守护字形')
        else:
            out['reason']='守护字形分数或类别间距不足'
    return out


def combat_guard_info(frame,hq=None):
    import mobile_board as mb
    if not _valid(frame):
        return {'status':'unknown','guards':[],'guard_units':[],'protected_units':[],
                'hq_guarded':False,'hq_guard_state':'unknown','detail':{},'complete':False}
    if hq is None:
        hq=mb.hq_card(frame,'enemy')
    observed=guard_glyph(frame,hq)
    state=observed['state']
    status='guarded' if state=='protected' else ('clear' if state=='clear' else 'unknown')
    out={'status':status,'guards':[],'protected_units':[],'hq_guarded':status=='guarded',
         'hq_guard_state':status,'detail':{'hq':observed},'complete':status!='unknown'}
    for row,cards in (('enemy_support',mb.enemy_support_cards(frame)),('enemy_front',mb.enemy_front_cards(frame))):
        for card in cards:
            glyph=guard_glyph(frame,card)
            out['detail'][f'{row}@{card["x"]},{card["y"]}']=glyph
            marked=dict(card,row=row)
            if glyph['state']=='guard':
                out['guards'].append(marked)
            elif glyph['state']=='protected':
                out['protected_units'].append(marked)
            elif glyph['state']=='unknown':
                out['complete']=False
    out['guard_units']=out['guards']
    return out
