"""Convert native action plans to source-pixel bridge requests; no dispatch."""
import math
from .turn_ui import end_control
from .end_audit import unknown_frontline_skip_ready

FRAME_KEYS=('frame_id','captured_elapsed_ms','foreground_generation','source_width','source_height')

def point(value,width,height):
    if not isinstance(value,(list,tuple)) or len(value)!=2:
        raise ValueError('native_action_point_missing')
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in value):
        raise ValueError('native_action_point_nonfinite')
    x,y=value
    if not (0<x<width and 0<y<height):raise ValueError('native_action_point_outside_capture')
    return [float(x),float(y)]

def request(observed,packet,now,remaining_ms):
    if observed.get('planning_complete') is False:
        raise ValueError('native_action_requires_complete_planning')
    if packet.get('ok') is not True or packet.get('coordinate_space')!='source_pixels':
        raise ValueError('native_action_requires_source_capture')
    width,height=packet['source_width'],packet['source_height']
    if observed.get('source_shape')!=[height,width,3]:raise ValueError('native_action_geometry_mismatch')
    if observed.get('state')!='battle':raise ValueError('native_action_requires_own_turn')
    choice=observed.get('selected_action',{}).get('action')=='choice_middle'
    if observed.get('choice_modal') and not choice:raise ValueError('native_action_choice_modal')
    if not choice and (observed.get('card_display',{}).get('ready') or observed.get('turn_preparation',{}).get('ready') is False):
        raise ValueError('native_action_draw_not_settled')
    current_control=end_control(observed.get('page',{}))
    if current_control is None:
        raise ValueError('native_action_current_turn_control_unconfirmed')
    age=now-packet['captured_elapsed_ms']
    if age<0 or age>3000:raise ValueError('native_action_frame_expired')
    if remaining_ms<8000:raise ValueError('native_action_verification_budget')
    selected=observed.get('selected_action') or {};action=selected.get('action')
    if choice:
        evidence=observed.get('choice_evidence') or {};boxes=evidence.get('boxes',[])
        if (not observed.get('choice_modal') or evidence.get('ready') is not True
                or evidence.get('selected_index')!=1 or len(boxes)!=3):
            raise ValueError('native_three_choice_unconfirmed')
        for x,y,w,h in boxes:
            if not (0<x<x+w<width and 0<y<y+h<height and .35*height<w<.48*height and .50*height<h<.70*height):
                raise ValueError('native_three_choice_geometry')
        x,y,w,h=boxes[1];origin=point([x+w/2,y+h/2],width,height);target=origin
        context='choice_select';duration=60;kind='tap'
    elif action in ('deploy','blind_middle'):
        probe=observed.get('support_probe') or {};scene=observed.get('scene') or {}
        if not probe.get('vacancy_candidate') or scene.get('support_full_confirmed'):
            raise ValueError('native_action_support_vacancy_unconfirmed')
        origin=point(selected.get('grab_source'),width,height)
        if origin[1]<height*560/720:raise ValueError('native_action_deployment_origin_not_hand')
        if action=='blind_middle':
            from .native_hand import blind_allowed
            if not blind_allowed(origin,observed.get('hand') or [],height,width):
                raise ValueError('native_blind_grab_overlaps_order_or_unavailable_card')
        target=point(selected.get('drop_source'),width,height)
        context='deploy';duration=900;kind='drag'
    elif action in ('attack_hq','attack_unit','movefront'):
        plan=selected.get('combat_plan') or {};actor=plan.get('unit') or {}
        location=actor.get('card') or actor
        origin=point([location.get('cx'),location.get('cy')],width,height)
        if action=='movefront':
            owner=(observed.get('scene') or {}).get('frontline',{}).get('owner')
            if owner not in ('our','empty'):raise ValueError('native_action_frontline_unavailable')
            target=point([origin[0],height*.44],width,height)
            context='move_front'
        else:
            enemy=plan.get('target') or {};target=point([enemy.get('cx'),enemy.get('cy')],width,height)
            if (action=='attack_unit' and enemy.get('guard_state')=='unknown'
                    and plan.get('guard_policy')!='attempt_unknown_once'):
                raise ValueError('native_action_guard_unconfirmed')
            context=action
        kind='drag';duration=650
    elif action=='end_turn_verified':
        evidence=selected.get('end_turn_evidence') or {}
        unknown_skip=unknown_frontline_skip_ready(evidence,packet)
        if ((evidence.get('unresolved_frontline_skipped') is True
                or evidence.get('reason')=='bounded_unknown_frontline_skipped') and (not unknown_skip
                or (observed.get('scene') or {}).get('frontline',{}).get('owner') in ('our','enemy','empty'))):
            raise ValueError('native_end_turn_unknown_skip_unconfirmed')
        if (evidence.get('ready') is not True or not (evidence.get('stable_pair') is True
                or evidence.get('current_frame_exhausted') is True or unknown_skip)
                or evidence.get('frame_id')!=packet['frame_id']):raise ValueError('native_end_turn_audit_unconfirmed')
        control=evidence.get('control') or {}
        if control.get('score',0)<.93:raise ValueError('native_end_turn_control_unconfirmed')
        if unknown_skip and control.get('bounds')!=current_control.get('bounds'):
            raise ValueError('native_end_turn_unknown_skip_control_mismatch')
        x,y,w,h=control['bounds'];origin=point([x+w/2,y+h/2],width,height);target=origin
        kind='tap';duration=60;context='end_turn'
    else:
        # End turn, opening and settlement have their own explicit evidence
        # contracts; absence of recalled cards never authorizes an end turn.
        raise ValueError('native_action_not_ready:'+str(action))
    result={key:packet[key] for key in FRAME_KEYS}
    result.update(coordinate_space='source_pixels',context=context,kind=kind,duration_ms=duration,
                  **{'from':origin,'to':target})
    if choice:result['choice_boxes']=boxes
    if context=='deploy':
        result['path_points']=[origin,[origin[0],min(height*575/720,origin[1]-height*60/720)],target]
    return result
