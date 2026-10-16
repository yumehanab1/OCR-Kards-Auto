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
    ready_actor_unknown_front=unknown_front and any(a.get('state')=='orange' and any(
            allow(dict(kind=kind,unit=a)) for kind in ('attack_hq','attack_unit','movefront'))
            for a in combat.get('actors',[]))
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
    result=dict(ready=True,reason='current_action_candidates_exhausted_with_local_unknowns' if local_unknown else 'current_deployment_and_actor_scans_exhausted',control=control,
                locally_unknown=local_unknown,
                deployment_basis=deploy_basis,actors_scanned=len(actors),locally_pending=sum(o.get('kind')=='pending' for o in combat.get('options',[])))
    if ready_actor_unknown_front:
        # No claim that these orange actors were exhausted. A bounded series
        # of fresh observations may separately permit ending despite this
        # unresolved local prerequisite, after all other checks above pass.
        result.update(ready=False,reason='ready_actor_frontline_unconfirmed',frontline_recheck_eligible=True)
    return result


_RECHECK_KEYS=('frame_id','captured_elapsed_ms','foreground_generation','source_width','source_height')
_RECHECK_FRAMES=3
_RECHECK_GAP_MS=250
_RECHECK_SPAN_MS=1500


def unknown_frontline_skip_ready(evidence,packet):
    """Validate the explicit unknown-skip proof without declaring exhaustion."""
    if (packet.get('coordinate_space')!='source_pixels'
            or any(type(packet.get(key)) is not int for key in _RECHECK_KEYS)):return False
    if (evidence.get('ready') is not True or evidence.get('unresolved_frontline_skipped') is not True
            or evidence.get('frontline_recheck_eligible') is not True
            or evidence.get('reason')!='bounded_unknown_frontline_skipped'
            or evidence.get('current_frame_exhausted') is True or evidence.get('stable_pair') is True):return False
    proof=evidence.get('frontline_recheck') or {}
    if not isinstance(proof,dict):return False
    samples=proof.get('samples')
    if (not isinstance(samples,list) or len(samples)<_RECHECK_FRAMES
            or proof.get('sample_count')!=len(samples)
            or type(proof.get('source_turn')) is not int or proof['source_turn']<0):return False
    previous=None
    for sample in samples:
        if (not isinstance(sample,dict) or any(type(sample.get(key)) is not int for key in _RECHECK_KEYS)
                or sample['frame_id']<=0 or sample['captured_elapsed_ms']<0
                or sample['foreground_generation']<0 or sample['source_width']<=0 or sample['source_height']<=0
                or sample.get('coordinate_space')!='source_pixels'
                or any(sample[key]!=packet.get(key) for key in ('foreground_generation','source_width','source_height'))):return False
        if previous is not None and (sample['frame_id']<=previous['frame_id']
                or sample['captured_elapsed_ms']-previous['captured_elapsed_ms']<_RECHECK_GAP_MS):return False
        previous=sample
    span=samples[-1]['captured_elapsed_ms']-samples[0]['captured_elapsed_ms']
    return (span>=_RECHECK_SPAN_MS and proof.get('capture_span_ms')==span
            and all(samples[-1][key]==packet.get(key) for key in _RECHECK_KEYS))


class UnknownFrontlineRecheck:
    """A limited, same-turn recheck of one explicitly unresolved prerequisite."""
    def __init__(self):self.reset()

    def reset(self):self.key=None;self.samples=[]

    def observe(self,evidence,packet,turn,now_ms):
        eligible=(evidence.get('ready') is False and evidence.get('frontline_recheck_eligible') is True
                  and evidence.get('reason')=='ready_actor_frontline_unconfirmed')
        valid=(all(type(packet.get(key)) is int for key in _RECHECK_KEYS)
               and packet['frame_id']>0 and packet['captured_elapsed_ms']>=0
               and packet['foreground_generation']>=0 and packet['source_width']>0 and packet['source_height']>0
               and packet.get('coordinate_space')=='source_pixels' and type(turn) is int and turn>=0
               and 0<=now_ms-packet['captured_elapsed_ms']<=3000)
        if not eligible or not valid:
            self.reset();return evidence
        key=(turn,packet['foreground_generation'],packet['source_width'],packet['source_height'])
        if key!=self.key:self.reset();self.key=key
        sample={key:packet[key] for key in _RECHECK_KEYS};sample['coordinate_space']='source_pixels'
        current=False
        if not self.samples:
            self.samples.append(sample);current=True
        else:
            previous=self.samples[-1]
            if sample==previous:current=True # Reuse is the same sample, never a new one.
            elif (sample['frame_id']<=previous['frame_id']
                    or sample['captured_elapsed_ms']<=previous['captured_elapsed_ms']):
                self.reset();return evidence
            elif sample['captured_elapsed_ms']-previous['captured_elapsed_ms']>=_RECHECK_GAP_MS:
                self.samples.append(sample);current=True
        proof=dict(source_turn=turn,sample_count=len(self.samples),samples=[dict(row) for row in self.samples],
                   capture_span_ms=self.samples[-1]['captured_elapsed_ms']-self.samples[0]['captured_elapsed_ms'])
        result=dict(evidence,frontline_recheck=proof)
        if current and len(self.samples)>=_RECHECK_FRAMES and proof['capture_span_ms']>=_RECHECK_SPAN_MS:
            result.update(ready=True,reason='bounded_unknown_frontline_skipped',unresolved_frontline_skipped=True)
        return result

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
