"""Deterministic multi-step own-turn policy regressions; no device input."""
import copy
import tempfile
from .action_chain import select
from .end_audit import audit
from .executor import ActionExecutor


def run():
    checks=[]
    def check(name,value):
        assert value,name
        checks.append(dict(name=name,passed=True))
    class Bridge:
        def elapsedRealtime(self):return 1000
        def isCancelled(self):return False
        def emit(self,value):pass
    card=lambda x:dict(action='deploy',grab_source=[x,660],drop_source=[448,497])
    actor=lambda x,kind:dict(kind=kind,unit=dict(card=dict(cx=x,cy=400)),target=dict(cx=640,cy=120))
    plans=[card(400),card(600)]
    obs=dict(state='battle',plan=dict(plans[0],candidates=plans),
             scene=dict(frontline={'owner':'our'},cards=[],support_full_confirmed=False),
             support_probe=dict(coverage_candidate=True),combat=dict(actors=[],options=[
                 actor(300,'attack_hq'),actor(500,'movefront'),actor(700,'attack_unit')]),
             page=dict(state='battle',evidence={'end_turn_btn':dict(score=.99,bounds=[1100,500,140,40])}))
    with tempfile.TemporaryDirectory() as directory:
        engine=ActionExecutor(Bridge(),None,None,directory,50000,120)
        engine.shape=(720,1280,3)
        observed=copy.deepcopy(obs);sequence=[]
        # Simulate independent successful reobservations, never a macro from old coordinates.
        for _ in range(5):
            step=select(observed,engine.allow);sequence.append(step['action'])
            if step['action']=='deploy':
                point=step['grab_source'];observed['plan']['candidates']=[p for p in observed['plan']['candidates'] if p['grab_source']!=point]
                if not observed['plan']['candidates']:
                    observed['plan']=dict(action='skip_deploy',reason='all_observed_fee_numerals_unavailable')
            else:
                chosen=step['combat_plan'];observed['combat']['options'].remove(chosen)
        check('hand_then_every_board_actor',sequence==['deploy','deploy','attack_unit','movefront','attack_hq'])
        check('end_only_after_both_scans',select(observed,engine.allow)['action']=='end_turn_candidate' and audit(observed,engine.allow)['ready'])
        engine.isolated=[('deploy',[400,660])]
        check('failed_first_card_does_not_hide_second',select(obs,engine.allow)['grab_source']==[600,660])
        check('audit_rejects_remaining_second_card',audit(obs,engine.allow)['reason']=='remaining_deployment_candidate')
        engine.failed_deploys=2
        check('deploy_failure_budget_still_activates_board',select(obs,engine.allow)['action']=='attack_unit')
        engine.isolated=[('attack_unit',[700,400])]
        check('unknown_actor_cannot_switch_action_to_retry',not engine.allow(actor(700,'attack_hq')) and not engine.allow(actor(700,'movefront')))
        check('other_actor_not_quarantined',engine.allow(actor(500,'movefront')))
        engine.isolated=[];engine.planning_state_key='stable';engine.report['hooks']=[{}]
        engine.action_attempts[(0,'stable','attack_hq',(300,400))]=2
        check('confirmed_but_unchanged_repeat_is_bounded',not engine.allow(actor(300,'attack_hq')))
        engine.turn=1
        check('next_turn_rearms_repeat_budget',engine.allow(actor(300,'attack_hq')))
        check('opponent_never_acts',select(dict(obs,state='opponent_turn'),engine.allow)['action']=='wait')
    return dict(passed=True,check_count=len(checks),checks=checks,device_inputs=0)
