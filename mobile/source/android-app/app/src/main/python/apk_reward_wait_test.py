"""Narrow settlement wait regressions; virtual clocks, zero device calls."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import cv2
import numpy as np
import apk_reward_wait as reward
import apk_settle as settle


class RewardWaitTests(unittest.TestCase):
    def setUp(self):
        self.specs={};self.templates={}
        for index,name in enumerate((*reward.REWARD_NAMES,'task_title',*reward.TASK_SUBTITLES)):
            bounds=[100+index*160,100,130,35]
            template=np.full((35,130,3),10,np.uint8)
            cv2.putText(template,str(index)+' WORD',(2,24),cv2.FONT_HERSHEY_SIMPLEX,.65,(210,210,210),2)
            self.specs[name]={'bounds':bounds}
            self.templates[name]=template
        self.now=0.;self.taps=[]

    def frame(self,*names):
        frame=np.full((720,1280,3),10,np.uint8)
        for name in names:
            x,y,w,h=self.specs[name]['bounds'];frame[y:y+h,x:x+w]=self.templates[name]
        return frame

    def gate(self,verified=True,deadline=90.):
        return reward.RewardWaitGate(self.templates,self.specs,session_epoch='test',
                                     result_verified=verified,deadline=deadline)

    def decision(self,gate,frame,now=0.,state='unknown',reason=''):
        return gate.decide(frame,{'state':state,'reason':reason},now)

    def test_both_word_markers_required_for_claim_ready(self):
        label=self.decision(self.gate(),self.frame('diamond_label'))
        self.assertTrue(label['wait']);self.assertFalse(label.get('claim_ready'))
        hint=self.decision(self.gate(),self.frame('tap_claim'))
        self.assertFalse(hint['wait']);self.assertFalse(hint.get('claim_ready'))
        ready=self.decision(self.gate(),self.frame(*reward.REWARD_NAMES))
        self.assertFalse(ready['wait']);self.assertTrue(ready['claim_ready'])

    def test_only_completed_claim_arms_exit_phase(self):
        for accepted,completed in ((True,False),(False,True),(False,False)):
            gate=self.gate();self.decision(gate,self.frame(*reward.REWARD_NAMES))
            gate.note_dispatch(accepted,completed,.1);self.assertIsNone(gate.phase)
        gate=self.gate();self.decision(gate,self.frame(*reward.REWARD_NAMES))
        gate.note_dispatch(True,True,.1)
        self.assertEqual('after_claim',gate.phase)
        self.assertTrue(self.decision(gate,self.frame(),.2)['wait'])

    def test_unchanged_claim_after_completed_input_never_repeats(self):
        gate=self.gate();frame=self.frame(*reward.REWARD_NAMES)
        self.decision(gate,frame);gate.note_dispatch(True,True,.1)
        self.assertTrue(self.decision(gate,frame,1.)['wait'])

    def test_stalled_reward_phases_fail_after_eight_seconds(self):
        for after in (False,True):
            gate=self.gate();frame=self.frame(*reward.REWARD_NAMES if after else ('diamond_label',))
            self.decision(gate,frame)
            if after:gate.note_dispatch(True,True,0.)
            decision=self.decision(gate,self.frame(),8.)
            self.assertTrue(decision['stop']);self.assertEqual('settle_reward_phase_timeout',decision['reason'])

    def test_task_pair_only_releases_wait_and_does_not_name_menu(self):
        gate=self.gate();self.decision(gate,self.frame('diamond_label'))
        self.assertTrue(self.decision(gate,self.frame('task_title'),1.)['wait'])
        result=self.decision(gate,self.frame('task_title','task_subtitle'),2.)
        self.assertFalse(result['wait']);self.assertEqual('new_task_text_pair_releases_wait',result['reason'])
        self.assertNotIn('final_state',result)

    def test_other_unknowns_preserve_original_path(self):
        result=self.decision(self.gate(),self.frame())
        self.assertFalse(result['wait']);self.assertFalse(result['stop'])

    def test_explicit_result_and_session_admission(self):
        result=self.decision(self.gate(False),self.frame('diamond_label'))
        self.assertFalse(result['wait'])
        gate=self.gate();self.decision(gate,self.frame('diamond_label'))
        result=gate.decide(self.frame(*reward.REWARD_NAMES),{'state':'unknown'},1.,session_epoch='other')
        self.assertFalse(result['wait']);self.assertFalse(gate.result_verified);self.assertIsNone(gate.phase)

    def test_black_transition_wait_requires_original_black_reason(self):
        black=np.zeros((720,1280,3),np.uint8)
        self.assertFalse(self.decision(self.gate(),black)['wait'])
        gate=self.gate();self.assertTrue(self.decision(gate,black,reason='black_transition')['wait'])
        self.assertTrue(self.decision(gate,black,8.,reason='black_transition')['stop'])

    def test_global_deadline_and_original_known_state_priority(self):
        gate=self.gate();self.decision(gate,self.frame('diamond_label'))
        self.assertEqual('settle_deadline',self.decision(gate,self.frame(),90.)['reason'])
        gate=self.gate();self.decision(gate,self.frame('diamond_label'))
        decision=self.decision(gate,self.frame(),9.,state='deck_ready')
        self.assertFalse(decision['wait']);self.assertIsNone(gate.phase)

    def loop(self,rows,*,clicks=0,accepted=True,deadline=90.):
        index=[0];gate=self.gate(deadline=deadline);self.now=0.;self.taps=[]
        def capture():
            current=min(index[0],len(rows)-1);index[0]+=1
            return rows[current][0]
        def classify(frame):return rows[min(index[0]-1,len(rows)-1)][1]
        def tap(point):self.taps.append((point,self.now));return accepted
        def sleep(seconds):self.now+=seconds
        machine=settle.Settle(capture,tap,classify,now=lambda:self.now,sleep=sleep,
                               timeout_seconds=deadline,reward_wait=gate,rng=np.random.default_rng(4))
        machine.clicks=clicks
        return machine.run(),gate

    def test_fifteenth_point_can_read_black_then_known_menu_without_sixteenth(self):
        black=np.zeros((720,1280,3),np.uint8)
        report,_=self.loop([(black,{'state':'unknown','reason':'black_transition'}),
                            (self.frame(),{'state':'deck_ready'})],clicks=15)
        self.assertEqual('settle_screen_known:deck_ready',report['reason'])
        self.assertEqual(15,report['clicks']);self.assertEqual([],self.taps)

    def test_fifteenth_point_unknown_tail_cannot_become_sixteenth(self):
        black=np.zeros((720,1280,3),np.uint8)
        report,_=self.loop([(black,{'state':'unknown','reason':'black_transition'}),
                            (self.frame(),{'state':'unknown'})],clicks=15)
        self.assertEqual('settle_click_budget',report['reason']);self.assertEqual([],self.taps)

    def test_missing_claim_hint_can_stop_without_spending_input(self):
        report,_=self.loop([(self.frame('diamond_label'),{'state':'unknown'})])
        self.assertEqual('settle_reward_phase_timeout',report['reason']);self.assertEqual([],self.taps)
        self.assertLess(self.now,9.)

    def test_refused_input_retains_original_stop_and_no_arm(self):
        report,gate=self.loop([(self.frame(*reward.REWARD_NAMES),{'state':'unknown'})],accepted=False)
        self.assertEqual('settle_input_refused',report['reason']);self.assertEqual(1,len(self.taps))
        self.assertNotEqual('after_claim',gate.phase)

    def test_ninety_second_original_loop_deadline_still_bounds_wait(self):
        black=np.zeros((720,1280,3),np.uint8)
        report,_=self.loop([(black,{'state':'unknown','reason':'black_transition'})],deadline=.5)
        self.assertEqual('settle_deadline',report['reason']);self.assertEqual([],self.taps)

    def test_optional_assets_are_hash_checked_and_missing_falls_back(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary);specs={}
            for name,template in self.templates.items():
                filename=name+'.png';cv2.imwrite(str(directory/filename),template)
                specs[name]={'file':filename,'bounds':self.specs[name]['bounds'],
                    'sha256':hashlib.sha256((directory/filename).read_bytes()).hexdigest()}
            manifest={'reward_wait':{'schema':1,'markers':{name:specs[name] for name in reward.REWARD_NAMES}},
                      'templates':{name:spec for name,spec in specs.items() if name not in reward.REWARD_NAMES}}
            (directory/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
            gate,reason=reward.load_gate(directory,session_epoch='test',result_verified=True,deadline=90.)
            self.assertIsNotNone(gate);self.assertEqual('optional_text_assets_verified',reason)
            (directory/'diamond_label.png').write_bytes(b'wrong')
            gate,reason=reward.load_gate(directory,session_epoch='test',result_verified=True,deadline=90.)
            self.assertIsNone(gate);self.assertEqual('unavailable:ValueError',reason)
            manifest.pop('reward_wait');(directory/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
            self.assertIsNone(reward.load_gate(directory,session_epoch='test',result_verified=True,deadline=90.)[0])
        self.assertEqual((None,'not_admitted'),reward.load_gate('missing',session_epoch='test',result_verified=False,deadline=90.))

    def test_run_receipt_completion_arms_actual_gate_once(self):
        for completed in (False,True):
            self.now=0.;gate=self.gate();owner=self
            class Bridge:
                def __init__(self):self.cursor=0;self.taps=[]
                def capture(self):
                    self.cursor+=1
                    return {'ok':True,'frame_id':self.cursor,'captured_elapsed_ms':1000+self.cursor,
                        'foreground_generation':4,'source_width':1920,'source_height':1080,'png_path':'/frames/%05d.png'%self.cursor}
                def observeMenu(self,request):return {'state':'unknown' if self.cursor==1 else 'deck_ready'}
                def dispatchSettle(self,request):self.taps.append(json.loads(request));return {'accepted':True,'completed':completed}
            bridge=Bridge();original=settle.Settle
            def window(*args,**kwargs):return original(*args,now=lambda:owner.now,sleep=lambda s:setattr(owner,'now',owner.now+s),**kwargs)
            with patch.object(settle,'Settle',window),patch.object(settle.time,'monotonic',lambda:self.now), \
                 patch('apk_match_entry.read_frame',return_value=(self.frame(*reward.REWARD_NAMES),'mock')), \
                 patch.object(reward,'load_gate',return_value=(gate,'mock')) as loader, \
                 patch.object(gate,'note_dispatch',wraps=gate.note_dispatch) as note:
                report=json.loads(settle.run(bridge,assets_dir='test-assets',verified_result=True))
            self.assertIs(loader.call_args.kwargs['result_verified'],True)
            self.assertEqual(1,len(bridge.taps))
            self.assertEqual(1 if completed else 0,note.call_count)
            self.assertEqual('settle_screen_known:deck_ready' if completed else 'settle_input_refused',report['reason'])
            self.assertTrue(report['reward_wait']['verified_result'])


if __name__=='__main__':unittest.main()
