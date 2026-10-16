"""Current resource context, including a horizontal display-safe-area inset."""
import cv2
import numpy as np


def inspect(frame, hsv=None):
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV) if hsv is None else hsv
    orange = ((hsv[:, :, 0] >= 5) & (hsv[:, :, 0] <= 35)
              & (hsv[:, :, 1] >= 80) & (hsv[:, :, 2] >= 80))
    scale = h / 720
    bands = ((.12, .31), (.68, .87))
    def fixed(top, bottom):
        roi = orange[round(top*h):round(bottom*h), round(20*scale):round(115*scale)]
        return roi.size > 0 and float(roi.mean()) >= .025
    if all(fixed(*band) for band in bands):
        return dict(ok=True, basis='original_resource_bands')

    # An inset shifts both resource boxes together. Do not infer a viewport
    # from black pixels or expand a bare orange-pixel search over the board.
    left_width = min(round(w*.20), round(h*.34))
    gray = cv2.cvtColor(frame[:, :left_width], cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 40, 100)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    pad = max(3, round(h*4/720))
    rows = [[], []]
    for contour in contours:
        x, y, bw, bh = cv2.boundingRect(contour)
        if not (.085*h < bw < .14*h and .085*h < bh < .14*h
                and .90 < bw/bh < 1.15 and x+bw < left_width):
            continue
        row = next((i for i, (top, bottom) in enumerate(bands)
                    if top*h < y and y+bh < bottom*h), None)
        if row is None:
            continue
        strips = (edges[max(0, y-pad):y+pad+1, x:x+bw],
                  edges[y+bh-pad:y+bh+pad+1, x:x+bw],
                  edges[y:y+bh, max(0, x-pad):x+pad+1],
                  edges[y:y+bh, x+bw-pad:x+bw+pad+1])
        coverage = [float((s > 0).any(axis=0 if i < 2 else 1).mean())
                    for i, s in enumerate(strips)]
        content = float(orange[y:y+bh, x:x+bw].mean())
        if min(coverage) < .94 or content < .025:
            continue
        candidate = dict(bounds=[x, y, bw, bh], edge_coverage=coverage,
                         orange_fraction=content)
        if not any(max(abs(a-b) for a, b in zip(candidate['bounds'], old['bounds'])) <= pad*2
                   for old in rows[row]):
            rows[row].append(candidate)
    # Touching opening-card edges can merge a resource contour. Use the other
    # currently observed box only to propose geometry, then verify every side.
    if sorted(len(row) for row in rows) == [0, 1]:
        observed_row = 0 if rows[0] else 1
        target_row = 1-observed_row
        x, _, bw, bh = rows[observed_row][0]['bounds']
        top, bottom = bands[target_row]
        proposals = []
        for y in range(round(top*h), round(bottom*h)-bh):
            strips = (edges[max(0,y-pad):y+pad+1,x:x+bw],
                      edges[y+bh-pad:y+bh+pad+1,x:x+bw],
                      edges[y:y+bh,max(0,x-pad):x+pad+1],
                      edges[y:y+bh,x+bw-pad:x+bw+pad+1])
            coverage = [float((s>0).any(axis=0 if i<2 else 1).mean()) for i,s in enumerate(strips)]
            content = float(orange[y:y+bh,x:x+bw].mean())
            if min(coverage)>=.94 and content>=.025:
                proposals.append(dict(bounds=[x,y,bw,bh],edge_coverage=coverage,
                                      orange_fraction=content,proposal_basis='other_current_resource_box'))
        groups = []
        for proposal in proposals:
            if not groups or proposal['bounds'][1]-groups[-1][-1]['bounds'][1]>pad*2+1:
                groups.append([])
            groups[-1].append(proposal)
        if len(groups)==1 and groups[0][-1]['bounds'][1]-groups[0][0]['bounds'][1]<=h*.025:
            rows[target_row].append(groups[0][len(groups[0])//2])
    if any(len(row) != 1 for row in rows):
        return dict(ok=False, basis='resource_pair_unconfirmed', candidates=rows)
    own, enemy = rows[1][0], rows[0][0]
    a, b = own['bounds'], enemy['bounds']
    aligned = abs(a[0]-b[0]) <= h*.015 and max(abs(a[i]-b[i]) for i in (2, 3)) <= h*.012
    return dict(ok=aligned, basis='current_aligned_resource_boxes' if aligned
                else 'resource_pair_misaligned', own=own, enemy=enemy)
