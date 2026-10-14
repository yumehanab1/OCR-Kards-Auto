"""Explicit deployment/combat exhaustion audit, separate from plan absence."""
from .turn_ui import end_control

def audit(observed,allow,failed_deploys=0,*,allow_local_unknown=False):
    refusal=lambda reason:dict(ready=False,reason=reason)
    if observed.get('state')!='battle':return refusal('not_own_turn')
    if observed.get('choice_modal'):return refusal('choice_modal')
    if observed.get('card_display',{}).get('ready'):return refusal('central_card_display')
    if observed.get('turn_preparation',{}).get('ready') is False:return refusal('draw_not_settled')
    scene=observed.get('scene') or {};probe=observed.get('support_probe') or {};combat=observed.get('combat') or {}
    unknown_front=scene.get('frontline',{}).get('owner') not in ('our','enemy','empty')
    if unknown_front and not allow_local_unknown:return refusal('frontline_unknown')
    if unknown_front and any(a.get('state')=='orange' and any(
            allow(dict(kind=kind,unit=a)) for kind in ('attack_hq','attack_unit','movefront'))
            for a in combat.get('actors',[])):
        # An explicitly ready actor with an unresolved global prerequisite
        # was not exhausted. Reacquire instead of silently ending its turn.
        return refusal('ready_actor_frontline_unconfirmed')
    control=end_control(observed.get('page',{}))
    if control is None:return refusal('current_end_control_unconfirmed')
    plan=observed.get('plan') or {};deploy=plan.get('action')
    if failed_deploys>=2:deploy_basis='same_turn_two_failed_deploys'
    elif deploy=='skip_deploy' and plan.get('reason') in ('four_support_units_observed','all_observed_fee_numerals_unavailable'):
        deploy_basis=plan['reason']
    elif deploy in ('deploy','blind_middle') and not allow(plan):deploy_basis='current_card_isolated_after_completed_touch'
    elif (allow_local_unknown and deploy=='skip_deploy' and plan.get('grab_source') is None
          and plan.get('reason')=='all_blind_candidates_overlap_suspected_orders'
          and plan.get('blind_selection',{}).get('point') is None
          and plan.get('blind_selection',{}).get('basis')=='all_blind_candidates_overlap_suspected_orders'
          and (plan.get('blind_selection',{}).get('avoided_suspected',0)>0
               or plan.get('blind_selection',{}).get('avoided_unavailable',0)>0)):
        deploy_basis='all_blind_candidates_overlap_suspected_orders'
    elif (allow_local_unknown and deploy=='wait'
          and plan.get('reason')=='support_vacancy_or_frontline_unconfirmed'):
        if observed.get('turn_preparation',{}).get('local_vacancy_skip_ready') is False:
            return refusal('local_support_vacancy_recheck')
        deploy_basis='local_support_vacancy_unknown_skipped'
    else:return refusal('deployment_scan_not_exhausted')
    actors=combat.get('actors',[])
    local_unknown=['frontline_unknown_combat_locally_skipped'] if unknown_front else []
    if any(actor.get('state')=='unknown' for actor in actors):
        if not allow_local_unknown:return refusal('actor_color_unknown')
        local_unknown.append('actor_color_unknown')
    # A missing action list alone never proves a battlefield is exhausted.
    # Each recalled own card must have an independently associated action plate;
    # a genuinely empty row additionally requires complete support structure.
    cards=[card for card in scene.get('cards',[]) if card.get('side')=='our' and card.get('card_edges_verified')]
    for card in cards:
        x,y,w,h=card['card_box_estimate']
        if not any(x<=a.get('card',{}).get('cx',-1)<=x+w and y<=a.get('card',{}).get('cy',-1)<=y+h for a in actors):
            if not allow_local_unknown:return refusal('own_card_action_plate_unconfirmed')
            local_unknown.append('own_card_action_plate_unconfirmed')
    if not cards and not probe.get('coverage_candidate'):
        if not allow_local_unknown:return refusal('empty_own_rows_unconfirmed')
        local_unknown.append('empty_own_rows_unconfirmed')
    if not probe.get('coverage_candidate') and not scene.get('support_full_confirmed'):
        if not allow_local_unknown:return refusal('support_scan_incomplete')
        local_unknown.append('support_scan_incomplete')
    for option in combat.get('options',[]):
        if option.get('kind')=='pending':continue # Existing policy locally skips unknown guard/target.
        if allow(option):return refusal('remaining_combat_candidate')
    return dict(ready=True,reason='current_action_candidates_exhausted_with_local_unknowns' if local_unknown else 'current_deployment_and_actor_scans_exhausted',control=control,
                locally_unknown=local_unknown,
                deployment_basis=deploy_basis,actors_scanned=len(actors),locally_pending=sum(o.get('kind')=='pending' for o in combat.get('options',[])))

class StableAudit:
    def __init__(self):self.previous=None
    def observe(self,evidence,packet,turn):
        current=dict(evidence=evidence,packet=packet,turn=turn)
        previous=self.previous;self.previous=current if evidence.get('ready') else None
        if not evidence.get('ready') or previous is None:return False
        old,prior=previous['evidence'],previous['packet']
        keys=('foreground_generation','source_width','source_height')
        if (previous['turn']!=turn or any(packet.get(k)!=prior.get(k) for k in keys)
                or packet['frame_id']<=prior['frame_id'] or not 250<=packet['captured_elapsed_ms']-prior['captured_elapsed_ms']<=5000):return False
        if any(evidence.get(k)!=old.get(k) for k in ('deployment_basis','actors_scanned','locally_pending')):return False
        tolerance=packet['source_height']*2/720
        return max(abs(a-b) for a,b in zip(evidence['control']['bounds'],old['control']['bounds']))<=tolerance
