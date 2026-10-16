"""Opposite-direction marker proofs; synthetic pixels/fake facts, no device API."""
import hashlib
import json
from pathlib import Path
from unittest import mock

import cv2
import numpy as np
from . import native_board, frontline_pattern


def _board(height=720,width=1280,*,triangle=False,up=False,line_ratio=.59):
    frame=np.full((height,width,3),180,np.uint8);scale=height/720
    left,right=round(width*.30),round(width*.70);line=round(height*line_ratio)
    frame[line:line+max(1,round(2*scale)),round(width*.25):round(width*.75)]=20
    if triangle:
        for x in range(round(width*.25)+round(14*scale),round(width*.75),max(1,round(29*scale))):
            points=([[x-round(11*scale),line],[x+round(11*scale),line],[x,line+round(9*scale)]]
                    if not up else [[x-round(11*scale),line],[x+round(11*scale),line],[x,line-round(9*scale)]])
            cv2.fillConvexPoly(frame,np.array(points,np.int32),(20,20,20))
    # A competing structural row retains the original .20 ambiguity.
    rival=round(height*(.49 if abs(line_ratio-.49)>.04 else .36))
    frame[rival:rival+max(1,round(2*scale)),left:left+round((right-left)*.78)]=20
    # Nonuniform rail, not a perfectly continuous plank stroke.
    gap=max(1,round((right-left)*.01))
    for fraction in (.34,.50,.66):
        x=round(width*fraction);frame[line:line+max(1,round(2*scale)),x:x+gap]=180
    return frame


def run():
    checks=[]
    def check(name,condition):
        if not condition:raise AssertionError(name)
        checks.append(dict(name=name,passed=True))
    proof=lambda y:dict(line_y=y,steps=12,period_fit=1.,span=.4,direction_coverage=.95,
                        gradient_threshold=40,basis='distributed_inverted_triangle_phase_marker')

    aligned=[(29*i,.95,0) for i in range(12)]
    noisy=aligned+[(19+29*i,.90,0) for i in range(4)]
    check('phase_majority_preserves_lattice',len(frontline_pattern._phase_consistent_points(noisy,29))==12)
    check('eight_chosen_from_mostly_clutter_rejected',not frontline_pattern._phase_consistent_points(
        aligned[:8]+[(7+29*i,.9,0) for i in range(5)],29))
    check('seven_points_never_sufficient',not frontline_pattern._phase_consistent_points(aligned[:7],29))
    check('empty_phase_candidate_rejected',not frontline_pattern._phase_consistent_points([],29))

    # Exact attachment-independent mirror formulas, including top and bottom boxes.
    for h in (720,1264,1296):
        image=np.zeros((h,64,3),np.uint8);boxes=[[0,0,8,5],[20,h-9,7,9]];seen=[]
        def fake(frame,masked,**options):
            seen.append((frame,masked,options));return [proof(0),proof(h-1),proof(-1),proof(h)]
        with mock.patch.object(frontline_pattern,'inspect',side_effect=fake):
            found=native_board._inverted_triangle_markers(image,boxes)
        check('mirror_card_boxes_'+str(h),seen[0][1]==[[0,h-5,8,5],[20,0,7,9]])
        check('mirror_line_boundary_'+str(h),[p['line_y'] for p in found]==[h-1,0])
        check('mirror_uses_triangle_majority_'+str(h),seen[0][2]==dict(
            triangular=True,phase_consensus=True,search_y_fraction=(.36,.73)))

    seam=_board();old=native_board.frontline(seam)
    check('near_97_percent_seam_keeps_unknown',old['owner']=='unknown' and old['score']>.93
          and .15<old['score']-old['rival_score']<.20)
    check('perfect_continuous_seam_keeps_unknown',native_board.frontline(
        np.concatenate([np.full((425,1280,3),180,np.uint8),np.full((2,1280,3),20,np.uint8),
                        np.full((293,1280,3),180,np.uint8)]))['owner']=='unknown')
    check('flat_background_keeps_unknown',native_board.frontline(np.full((720,1280,3),180,np.uint8))['owner']=='unknown')
    with mock.patch.object(native_board,'_inverted_triangle_markers',return_value=[proof(425)]):
        found=native_board.frontline(seam)
    check('current_high_coverage_peak_plus_shape_admits',found['owner']=='enemy' and found['marker_proof'] is not None)
    with mock.patch.object(native_board,'_inverted_triangle_markers',return_value=[proof(400)]):
        check('shape_far_from_current_peak_rejected',native_board.frontline(seam)['owner']=='unknown')
    with mock.patch.object(native_board,'_inverted_triangle_markers',return_value=[proof(425),proof(353)]):
        check('two_legal_marker_rows_rejected',native_board.frontline(seam)['owner']=='unknown')
    with mock.patch.object(frontline_pattern,'inspect',return_value=[dict(proof(260),basis='old_up_marker')]), \
            mock.patch.object(native_board,'_inverted_triangle_markers',return_value=[proof(425)]):
        check('opposite_direction_row_conflict_rejected',native_board.frontline(seam)['owner']=='unknown')
    with mock.patch.object(native_board,'_inverted_triangle_markers',return_value=[proof(310)]):
        check('unsupported_marker_row_rejected',native_board.frontline(seam)['owner']=='unknown')
    high_margin=seam.copy();high_margin[353:355]=180
    with mock.patch.object(native_board,'_inverted_triangle_markers',side_effect=AssertionError('unneeded mirror scan')):
        check('existing_confident_owner_skips_extra_scan',native_board.frontline(high_margin)['owner']=='enemy')
    low_coverage=seam.copy();low_coverage[:,384:500]=180
    with mock.patch.object(native_board,'_inverted_triangle_markers',side_effect=AssertionError('weak coverage')):
        check('weak_three_segment_peak_not_compensated',native_board.frontline(low_coverage)['owner']=='unknown')

    for width in (1280,1584):
        image=_board(width=width,triangle=True)
        with mock.patch.object(native_board,'_repeated_frontline_ticks',return_value=False):
            with mock.patch.object(native_board,'_inverted_triangle_markers',return_value=[]):
                baseline=native_board.frontline(image)
            actual=native_board.frontline(image)
        check('synthetic_down_marker_'+str(width),actual['owner']=='enemy'
              and actual['marker_proof'] is not None
              and actual['marker_proof']['period_fit']>=.85)
        check('synthetic_ambiguous_peak_baseline_'+str(width),baseline['owner']=='unknown')
        check('default_triangle_api_unchanged_'+str(width),frontline_pattern.inspect(image,triangular=True)
              ==frontline_pattern.inspect(image,triangular=True,phase_consensus=False))
        masked=native_board._inverted_triangle_markers(image,[[round(width*.25),410,round(width*.50),40]])
        check('opposite_marker_inside_card_mask_rejected_'+str(width),not masked)
    for height,width,ratio,expected in ((720,1584,.345,'our'),(720,1584,.465,'empty'),
            (720,1584,.615,'enemy'),(1264,2780,.345,'our'),(1296,2304,.505,'empty')):
        image=_board(height,width,triangle=True,line_ratio=ratio)
        with mock.patch.object(native_board,'_repeated_frontline_ticks',return_value=False):
            actual=native_board.frontline(image)
        check('mirrored_pixel_band_%d_%s'%(height,ratio),actual['owner']==expected
              and actual['marker_proof'] is not None)
    return dict(passed=True,check_count=len(checks),checks=checks,device_inputs=0,
                host_new_captures=0,global_margin_unchanged=True,default_phase_consensus=False,
                scope='synthetic_pixels_and_fact_gates_not_device_match_validation')


def replay_archive(jpeg_path,observation_path):
    """Offline JPEG replay with the archived verified card contour masks."""
    from .recognition_scale import shrink
    raw=Path(jpeg_path).read_bytes();original=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)
    row=json.loads(Path(observation_path).read_text(encoding='utf8'));scene=row['observation']['scene']
    frame,factors=shrink(original);boxes=[]
    for obj in scene['cards']:
        x,y,bw,bh=obj['box'];matches=[r for r in scene['rectangles'] if r[0]<=x<x+bw<=r[0]+r[2]
            and r[1]<=y<y+bh<=r[1]+r[3] and y>r[1]+r[3]*.65]
        if len(matches)==1 and matches[0] not in boxes:boxes.append(matches[0])
    boxes=[[round(x/factors[0]),round(y/factors[1]),round(w/factors[0]),round(h/factors[1])] for x,y,w,h in boxes]
    with mock.patch.object(native_board,'_inverted_triangle_markers',return_value=[]):baseline=native_board.frontline(frame,verified_card_boxes=boxes)
    actual=native_board.frontline(frame,verified_card_boxes=boxes)
    if baseline['owner']!='unknown' or actual['owner']!='enemy':raise AssertionError('JPEG marker replay did not resolve')
    return dict(passed=True,jpeg_sha256=hashlib.sha256(raw).hexdigest(),source_png_retired=True,
                image_kind='archived_lossy_review_jpeg_not_original_png',mask_boxes=boxes,
                baseline=baseline,actual=actual,live_verified=False)
