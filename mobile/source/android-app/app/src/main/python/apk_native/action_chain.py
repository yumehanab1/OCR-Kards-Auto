"""One offline action per fresh observation: attack, move, then deploy."""


def select(entry,allow=lambda action:True,bomber_roll=.25):
    state=entry['state']
    base={'dispatch':'offline_only','executable':False,
          'requires':['fresh_frame','foreground','cancel_check','turn_budget','real_touch_receipt','postcondition']}
    if state=='opponent_turn':return dict(base,action='wait',reason='explicit_opponent_turn')
    if state!='battle':return dict(base,**{k:v for k,v in entry.get('plan',{}).items() if k not in base})
    deploy=entry['plan']
    options=[];moves=[];skipped=[]
    if entry['scene']['frontline']['owner']=='unknown':skipped.append('frontline_unknown_combat_locally_skipped')
    for option in (entry.get('combat') or {}).get('options',[]):
        if option['kind']=='pending':skipped.append(option['reason']);continue
        current=dict(option)
        if current['kind']=='bomber_choice':
            if not 0<=bomber_roll<1:raise ValueError('bomber_roll outside [0,1)')
            category='hq' if bomber_roll<.5 else 'enemy_front'
            target=current['target'][category]
            if (category=='enemy_front' and target.get('guard_state')=='unknown'
                    and current.get('guard_policy')!='attempt_unknown_once'):
                skipped.append('bomber_target_guard_unknown');continue
            current.update(kind='attack_hq' if category=='hq' else 'attack_unit',target=target,
                           target_category=category,bomber_roll=bomber_roll)
        (moves if current['kind']=='movefront' else options).append(current)
    for action in options+moves:
        if allow(action):return dict(base,action=action['kind'],combat_plan=action,locally_skipped=skipped)
    if deploy.get('action') in ('deploy','blind_middle') and allow(deploy):
        return dict(base,**{k:v for k,v in deploy.items() if k not in base})
    # A provisional screenshot does not prove all objects/markers were recalled.
    # Therefore no end-turn is dispatched from absence of candidates alone.
    return dict(base,action='end_turn_candidate',locally_skipped=skipped,
                requires=base['requires']+['no_remaining_legal_actions_current_observation'],
                reason='candidate_only_not_authorized_by_incomplete_recall')

