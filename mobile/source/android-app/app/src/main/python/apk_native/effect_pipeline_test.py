"""Same-source partial evidence and planning completion; no device APIs."""
import copy
from collections import Counter
from contextlib import ExitStack
from unittest import mock

import numpy as np

from . import pipeline as module
from .pipeline import Pipeline


def run():
    checks=[]

    def check(name,value):
        if not value:raise AssertionError(name)
        checks.append(dict(name=name,passed=True))

    def fails(call,reason):
        try:call()
        except ValueError as error:return str(error)==reason
        return False

    class Fixture:
        def __init__(self,state='battle',choice=False,display=False):
            self.state=state;self.choice=choice;self.display=display;self.calls=Counter();self.features=[]
            self.pipeline=Pipeline.__new__(Pipeline)
            self.pipeline.page=self;self.pipeline.objects=self;self.pipeline.guards=object()

        def seen(self,name,features):
            self.calls[name]+=1;self.features.append(features)
            return features.frame

        def observe(self,frame,features):
            self.seen('page',features)
            return dict(state=self.state,evidence={},plan={'action':'wait'})

        def inspect(self,frame,features):
            self.seen('objects',features)
            # Identical same-side candidates must remain in the full inventory.
            return [dict(box=[100,120,20,20],type='infantry'),
                    dict(box=[220,120,20,20],type='infantry'),
                    dict(box=[340,120,20,20],type='infantry')]

        def board(self,frame,icons,features):
            self.seen('board',features)
            return dict(frontline={'owner':'our'},support_full_confirmed=False,support_observed=2,
                        cards=[dict(icon,side='our' if i<2 else 'enemy',row='front',
                                    card_edges_verified=True,card_box_estimate=icon['box'])
                               for i,icon in enumerate(icons)])

        def hand(self,frame,features):
            self.seen('hand',features)
            return [dict(box=[40,650,25,25],kind='unit',orange=bool(frame[0,0,0]),grab_source=[80,675])]

        def support(self,frame,scene,features):
            self.seen('support',features)
            return dict(coverage_candidate=True,vacancy_candidate=True,hq_box=[100,400,70,100],
                        unknown_rectangles=[],unaccounted_edge_fraction=0.)

        def combat(self,frame,entry,features,guards):
            self.seen('combat',features)
            return dict(options=[dict(kind='movefront',unit={'card':{'cx':120,'cy':160}}),
                                 dict(kind='attack_hq',unit={'card':{'cx':240,'cy':160}},
                                      target={'cx':600,'cy':150})],actors=[])

        def deploy(self,frame,page,scene,hand,probe):
            self.calls['deployment']+=1
            if hand is None or probe is None:raise AssertionError('incomplete evidence used for deployment')
            return dict(action='deploy',grab_source=hand[0]['grab_source'])

        def modal(self,frame,features):
            self.seen('choice',features);return {'ready':self.choice}

        def card_display(self,frame,features):
            self.seen('display',features);return {'ready':self.display}

        def patches(self):
            stack=ExitStack()
            for name in ('board','support','combat','deployment'):
                stack.enter_context(mock.patch.object(module,name,getattr(self,'deploy' if name=='deployment' else name)))
            stack.enter_context(mock.patch.object(module,'inspect',self.hand))
            stack.enter_context(mock.patch('apk_native.choice.inspect',self.modal))
            stack.enter_context(mock.patch('apk_native.turn_preparation.card_display',self.card_display))
            return stack

    def frame(shape=(720,1280,3)):
        return np.full(shape,32,np.uint8)

    contexts=('deploy','move_front','attack_unit','attack_hq')
    for shape in ((720,1280,3),(900,2000,3),(1264,2780,3)):
        for context in contexts:
            fixture=Fixture();source=frame(shape);suffix='%s_%sx%s'%(context,shape[1],shape[0])
            with fixture.patches():
                partial=fixture.pipeline.observe_effect(source,context)
                check('partial_no_hand_or_planning_'+suffix,
                      partial['hand'] is None and partial['combat'] is None
                      and partial['current_state_key'] is None and partial['planning_complete'] is False
                      and not partial['hand_scanned'] and not partial['combat_scanned']
                      and partial['selected_action']['action']=='wait' and partial['plan']['action']=='wait'
                      and fixture.calls['hand']==fixture.calls['combat']==fixture.calls['deployment']==0)
                check('partial_complete_unique_inventory_'+suffix,len(partial['scene']['cards'])==3
                      and sum(c['side']=='our' for c in partial['scene']['cards'])==2
                      and fixture.calls['support']==int(context=='deploy'))
                original=copy.deepcopy(partial)
                partial['source']={'path':'same.png','sha256':'source-byte-hash','shape':list(shape),
                                   'frame_id':91,'elapsed_ms':1234}
                full=fixture.pipeline.complete_planning(source.copy(),partial)
                check('same_source_completion_'+suffix,full['planning_complete'] and full['hand_scanned']
                      and full['combat_scanned'] and full['selected_action']['action']=='attack_hq'
                      and bool(full['current_state_key']) and full['source']==partial['source']
                      and full['source_shape']==list(shape) and full['completed_from_scope']=='effect_'+context)
                check('cached_evidence_not_rescanned_'+suffix,
                      all(fixture.calls[k]==1 for k in ('page','objects','board','hand','support','combat','deployment'))
                      and len({id(f) for f in fixture.features})==1)
                check('paired_partial_not_rewritten_'+suffix,partial['scene']==original['scene']
                      and partial['hand'] is None and partial['combat'] is None
                      and partial['planning_complete'] is False and full is not partial)
                check('completion_once_'+suffix,fails(lambda:fixture.pipeline.complete_planning(source,partial),
                                                      'effect_planning_cache_miss'))

    for name,change in (
            ('changed_pixels',lambda a:a.__setitem__((0,0,0),a[0,0,0]+1)),
            ('changed_shape',None)):
        fixture=Fixture();source=frame()
        with fixture.patches():
            partial=fixture.pipeline.observe_effect(source,'attack_unit')
            other=source.copy()
            if change:change(other)
            else:other=frame((720,1290,3))
            check(name+'_cannot_complete',fails(lambda:fixture.pipeline.complete_planning(other,partial),
                                               'effect_planning_source_changed'))
            check(name+'_no_hand_scanned',fixture.calls['hand']==0)

    fixture=Fixture();source=frame()
    with fixture.patches():
        old=fixture.pipeline.observe_effect(source,'move_front')
        current=fixture.pipeline.observe_effect(source,'move_front')
        check('different_partial_identity_rejected',fails(lambda:fixture.pipeline.complete_planning(source,old),
                                                        'effect_planning_cache_miss'))
        check('failed_completion_consumes_cache',fails(lambda:fixture.pipeline.complete_planning(source,current),
                                                      'effect_planning_cache_miss'))
        partial=fixture.pipeline.observe_effect(source,'move_front')
        partial['scene']['cards']=[];partial['page']['state']='unknown';partial['support_probe']={}
        full=fixture.pipeline.complete_planning(source,partial)
        check('caller_cannot_replace_cached_recognition',full['state']=='battle' and len(full['scene']['cards'])==3
              and full['support_probe']['coverage_candidate'])
        partial=fixture.pipeline.observe_effect(source,'deploy')
        source[0,0,0]=0
        check('mutated_caller_array_rejected',fails(lambda:fixture.pipeline.complete_planning(source,partial),
                                                  'effect_planning_source_changed'))
        partial=fixture.pipeline.observe_effect(source,'deploy')
        check('cloned_partial_rejected',fails(lambda:fixture.pipeline.complete_planning(source,copy.deepcopy(partial)),
                                             'effect_planning_cache_miss'))
        fixture.pipeline.observe_effect(source,'deploy')
        partial=fixture.pipeline.observe_effect(source,'attack_unit')
        check('new_context_cache_has_no_prior_support',partial['support_probe'] is None)
        complete=fixture.pipeline.complete_planning(source,partial)
        check('new_context_completes_own_scope',complete['completed_from_scope']=='effect_attack_unit'
              and complete['support_probe']['coverage_candidate'])
        partial=fixture.pipeline.observe_effect(source,'deploy')
        fixture.pipeline.observe_turn_ui(source)
        check('turn_ui_observation_invalidates_partial',fails(lambda:fixture.pipeline.complete_planning(source,partial),
                                                            'effect_planning_cache_miss'))

    keys=[]
    for orange in (False,True):
        fixture=Fixture();source=frame();source[0,0,0]=int(orange)
        with fixture.patches():
            partial=fixture.pipeline.observe_effect(source,'move_front')
            completed=fixture.pipeline.complete_planning(source,partial)
            check('current_hand_scanned_for_completion_'+str(orange),completed['hand'][0]['orange'] is orange)
            keys.append(completed['current_state_key'])
    check('current_hand_change_changes_retry_identity',keys[0]!=keys[1])

    for state,choice,display in (('opponent_turn',False,False),('unknown',False,False),
                                ('result_victory',False,False),('battle',True,False),('battle',False,True)):
        fixture=Fixture(state,choice,display);source=frame()
        with fixture.patches():
            partial=fixture.pipeline.observe_effect(source,'attack_hq')
            full=fixture.pipeline.complete_planning(source,partial)
            check('interrupted_observation_completes_'+state+str(choice)+str(display),full['state']==state
                  and full['planning_complete'] and full['choice_modal']==choice
                  and full['card_display']['ready']==display)

    fixture=Fixture();source=frame()
    with fixture.patches():
        partial=fixture.pipeline.observe_effect(source,'deploy')
        full=fixture.pipeline.observe(source)
        check('ordinary_full_still_plans',full['planning_complete'] and full['hand_scanned']
              and full['selected_action']['action']=='attack_hq')
        check('new_full_capture_invalidates_cache',fails(lambda:fixture.pipeline.complete_planning(source,partial),
                                                       'effect_planning_cache_miss'))
        check('unsupported_context_rejected',fails(lambda:fixture.pipeline.observe_effect(source,'end_turn'),
                                                  'unsupported_effect_observation_context'))
        check('invalid_dtype_rejected',fails(lambda:fixture.pipeline.observe_effect(source.astype(np.float32),'deploy'),
                                            'invalid_native_capture'))
    return dict(passed=True,checks=checks,check_count=len(checks),device_inputs=0,host_captures=0)
