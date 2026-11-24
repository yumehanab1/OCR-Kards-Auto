"""P-01..P-06 offline regressions and Python-generated Java guard fixtures."""
import copy
import gc
import json
import struct
import tempfile
import unittest
import weakref
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

from apk_battle_runtime import Replan, Stop
from apk_match_entry import MenuFlow
from .action_chain import select
from .action_request import request
from .daily_reward import ticket_return_evidence
from .executor import ActionExecutor
from .menu import NativeMenuRecognizer
from . import opening

ASSETS=Path(__file__).resolve().parents[2]/'assets'


def row(text,x=340,y=220,w=250,h=70):
    return dict(text=text,score=.99,box=[[x,y],[x+w,y],[x+w,y+h],[x,y+h]])


def packet(w=1280,h=720,index=3,captured=2000):
    return dict(ok=True,frame_id=index,captured_elapsed_ms=captured,foreground_generation=7,
                width=w,height=h,source_width=w,source_height=h,coordinate_space='source_pixels')


class OCR:
    bridge=True
    def __init__(self,items=(),ok=True):self.items=items;self.ok=ok;self.last_metrics={};self.calls=0
    def bind(self,packet):pass
    def __call__(self,frame):
        self.calls+=1;self.last_metrics={'ok':self.ok}
        return [(r['box'],r['text'],r['score']) for r in self.items],0
    def regions(self,frame,regions,scope):return self(frame)


def menu(items=(),home=False):
    recognizer=NativeMenuRecognizer(ASSETS/'match-entry',None,startup=True)
    recognizer.ocr=OCR(items)
    recognizer.detector.match=lambda gray,name:dict(score=.99 if home and name in
        ('home_play','home_tasks') else 0.,bounds=[90,100,60,30],factor=1.)
    recognizer.detector.refine_home_entry=lambda *args:None
    return recognizer


def battle(w=1280,h=720):
    return dict(state='battle',source_shape=[h,w,3],planning_complete=True,
        scene=dict(frontline={'owner':'enemy'},cards=[],support_full_confirmed=False),
        support_probe=dict(vacancy_candidate=True),hand=[],
        page=dict(state='battle',evidence={'end_turn_btn':dict(score=.99,bounds=[w*.85,h*.7,w*.1,h*.05])}),
        turn_preparation=dict(ready=True),plan=dict(action='skip_deploy'),
        combat=dict(options=[dict(kind='bomber_choice',unit=dict(card=dict(cx=w*.4,cy=h*.6)),
            target=dict(hq=dict(cx=w*.5,cy=h*.15),enemy_front=dict(cx=w*.6,cy=h*.4,guard_state='clear')))]))


def deployment_fixtures():
    for w,h in ((2112,1320),(1280,720),(1920,1080),(2400,1080),(1280,960),(1600,1000)):
        for y in (h*.91,620*(h/720.0),560*(h/720.0)):
            observed=battle(w,h)
            observed['selected_action']=dict(action='blind_middle',grab_source=[w/2,y],drop_source=[w*.35,h*.69])
            p=packet(w,h);plan=request(observed,p,2100,20000)
            yield dict(frame=p,plan=plan,lift_bits=struct.pack('>d',plan['path_points'][1][1]).hex())


def pass_observation(large=False,missing=None,blank=False):
    r=menu([row('10月战场通票')])
    frame=np.zeros((720,1280,3),np.uint8)
    if blank:
        cv2.rectangle(frame,(310,194),(970,527),(200,200,200),2)
        r.ocr.items.append(row('现已上架商店',350,350,220,30))
    else:
        for suffix in ('title','close','edge_top','edge_bottom','edge_left','edge_right'):
            if suffix==missing:continue
            name=('pass_' if suffix in ('title','close') else 'starter_')+suffix
            x,y,w,h=r.specs[name]['bounds'];frame[y:y+h,x:x+w]=r.promotions[name]
    # Integer 2x lets the real shrink path recover the exact anchor pixels.
    if large:frame=cv2.resize(frame,(2560,1440),interpolation=cv2.INTER_NEAREST)
    p=packet(frame.shape[1],frame.shape[0])
    return r.observe(frame,p),p


def menu_request(observed,p):
    _,requests=run_menu_observations([(observed,p)])
    assert len(requests)==1,requests
    return requests[0]


def run_menu_observations(rows):
    """Actual menu loop/request builder with scripted captures; no live bridge."""
    import apk_match_entry
    class Bridge:
        def __init__(self):self.rows=iter(rows);self.now=0;self.cancelled=False;self.requests=[]
        def elapsedRealtime(self):return self.now
        def deadlineElapsedRealtime(self):return 200000
        def isCancelled(self):return self.cancelled
        def emit(self,value):pass
        def captureNative(self):
            try:self.observed,p=next(self.rows)
            except StopIteration:
                self.cancelled=True;return json.dumps(dict(ok=False,reason='fixture_complete'))
            self.now=p['captured_elapsed_ms']+50
            return json.dumps(dict(p,png_path='synthetic.png'))
        def dispatchMenu(self,encoded):
            self.requests.append(json.loads(encoded));return json.dumps(dict(accepted=True,completed=True))
    bridge=Bridge();recognizer=mock.Mock()
    recognizer.observe.side_effect=lambda *args:copy.deepcopy(bridge.observed)
    with mock.patch('apk_native.menu.NativeMenuRecognizer',return_value=recognizer), \
         mock.patch.object(apk_match_entry,'read_frame',return_value=(np.zeros((720,1280,3),np.uint8),'synthetic')), \
         mock.patch.object(apk_match_entry.time,'sleep'):
        result=json.loads(apk_match_entry.run(bridge,'unused','casual',native=True))
    return result,bridge.requests


def pass_fixtures():
    for large in (False,True):
        obs,p=pass_observation(large=large);plan=menu_request(obs,p)
        yield dict(frame=p,plan=plan,expected=None)
        for anchor in ('title','edge_top','edge_bottom','edge_left','edge_right'):
            bad=copy.deepcopy(plan);del bad['promotion_evidence'][anchor]
            yield dict(frame=p,plan=bad,expected='native_promotion_close_unverified')
        obs,p=pass_observation(large=large,blank=True);plan=menu_request(obs,p)
        yield dict(frame=p,plan=plan,expected=None)
        bad=copy.deepcopy(plan);bad['target_bounds'][0]-=50
        yield dict(frame=p,plan=bad,expected='popup_blank_bounds_mismatch')


class ContractRegressions(unittest.TestCase):
    def collected(self):
        r=menu();frame=np.zeros((720,1440,3),np.uint8)
        cv2.fillConvexPoly(frame,np.array([[985,191],[972,197],[942,257],[991,289],[1032,220]]),(0,170,240))
        r.ocr.items=[row('每日登录奖励',580,42,277,46),row('奖励现可领取',648,645,144,29),
                     row('领取',954,116,70,43),row('1竞技场门票',914,316,150,30)]
        flow=MenuFlow('casual',0,direct_controls=True)
        obs=r.observe(frame,packet(1440,720,1,1000))
        self.daily_observations=[(copy.deepcopy(obs),packet(1440,720,1,1000))]
        self.assertEqual('menu_claim_daily',flow.observe(obs,1,1050)['action'])
        flow.accepted('menu_claim_daily',1100)
        r.daily_phase=True;r.ocr.items=[row('第7天',650,14,112,44),row('轻触领取',680,683,80,23)]
        obs=r.observe(np.zeros_like(frame),packet(1440,720,2,1300))
        self.daily_observations.append((copy.deepcopy(obs),packet(1440,720,2,1300)))
        self.assertEqual('menu_collect_daily',flow.observe(obs,2,1350)['action'])
        flow.accepted('menu_collect_daily',1400)
        return flow

    def returned(self,r,index,captured):
        p=packet(1440,720,index,captured)
        obs=r.observe(np.zeros((720,1440,3),np.uint8),p)
        obs['daily_ticket_return']=ticket_return_evidence(obs,obs['daily_reward_probe'],p,
                                                         captured+50,obs['daily_scoped_ocr'])
        return obs

    def test_daily_ticket_real_recognition_reaches_home_pair(self):
        flow=self.collected();r=menu(home=True);r.daily_phase=True
        obs=self.returned(r,3,2000)
        self.assertEqual('home',obs['state']);self.assertTrue(obs['daily_scoped_ocr'])
        self.assertEqual([],obs['daily_reward_probe']);self.assertEqual(1,r.ocr.calls)
        self.assertIn('wait',flow.observe(obs,3,2050));self.assertIsNotNone(flow.daily_pending)
        obs=self.returned(r,4,2600)
        self.assertEqual('menu_home_start',flow.observe(obs,4,2650)['action'])
        self.assertIsNone(flow.daily_pending);self.assertTrue(flow.daily_no_continue_verified)
        self.assertEqual({'menu_claim_daily','menu_collect_daily'},flow.daily_issued)

    def test_daily_ticket_actual_menu_loop_consumes_scoped_metadata(self):
        for prompt in (False,True):
            self.collected();r=menu([row('轻触继续')] if prompt else [],home=True);r.daily_phase=True
            rows=list(self.daily_observations)
            for index,captured in ((3,2000),(4,2600)):
                p=packet(1440,720,index,captured)
                rows.append((r.observe(np.zeros((720,1440,3),np.uint8),p),p))
            result,requests=run_menu_observations(rows)
            self.assertEqual(not prompt,result['daily_ticket_no_continue_verified'])
            expected=['menu_claim_daily','menu_collect_daily']+([] if prompt else ['menu_home_start'])
            self.assertEqual(expected,[r['context'] for r in requests])

    def test_daily_unknown_prompt_and_failed_scoped_ocr_stay_pending(self):
        for home,items,ok in ((False,[],True),(True,[row('轻触继续')],True),
                             (True,[row('立即购买')],True),(True,[],False)):
            with self.subTest(home=home,items=items,ok=ok):
                flow=self.collected();r=menu(items,home);r.daily_phase=True;r.ocr.ok=ok
                for index,captured in ((3,2000),(4,2600)):
                    obs=self.returned(r,index,captured)
                    self.assertIn('wait',flow.observe(obs,index,captured+50))
                self.assertIsNotNone(flow.daily_pending);self.assertFalse(flow.daily_no_continue_verified)

    def test_daily_probe_survives_early_destination_return_and_resets(self):
        r=menu();r.daily_phase=True;p=packet();frame=np.zeros((720,1280,3),np.uint8)
        with mock.patch('apk_native.menu.deck_regions',return_value=[[0,0,100,100]]), \
             mock.patch('apk_native.menu.menu_from_text',return_value=dict(state='deck_list',targets={},selected_mode='')):
            obs=r.observe(frame,p)
        self.assertEqual('deck_list',obs['state']);self.assertTrue(obs['daily_scoped_ocr'])
        obs=r.observe_pixels(None,p)
        self.assertNotIn('daily_scoped_ocr',obs);self.assertIsNone(r.daily_return_probe)

    def test_bomber_rng_explicit_and_default(self):
        for roll,category,action in ((.25,'hq','attack_hq'),(.75,'enemy_front','attack_unit')):
            rng=mock.Mock(return_value=roll);chosen=select(battle(),rng=rng)
            rng.assert_called_once_with();self.assertEqual(roll,chosen['bomber_roll'])
            self.assertEqual(category,chosen['combat_plan']['target_category']);self.assertEqual(action,chosen['action'])
            rng.reset_mock();self.assertEqual(chosen,select(battle(),bomber_roll=roll,rng=rng));rng.assert_not_called()
            with mock.patch('apk_native.action_chain.random.random',return_value=roll) as fallback:
                self.assertEqual(chosen,select(battle()));fallback.assert_called_once_with()
        entry=battle();entry['combat']['options']*=2;rng=mock.Mock(return_value=.75)
        select(entry,rng=rng);rng.assert_called_once_with()

    def test_pipeline_passes_rng_to_plan(self):
        from .pipeline import Pipeline
        with mock.patch('apk_native.pipeline.FastPage'),mock.patch('apk_native.pipeline.Objects'),mock.patch('apk_native.pipeline.Guards'):
            rng=mock.Mock(return_value=.75);pipe=Pipeline({}, {},None,rng=rng)
        obs=battle();frame=np.zeros((720,1280,3),np.uint8)
        with mock.patch('apk_native.pipeline.inspect',return_value=[]), \
             mock.patch('apk_native.pipeline.deployment',return_value=obs['plan']), \
             mock.patch('apk_native.pipeline.combat',return_value=obs['combat']):
            result=pipe._finish(frame,None,obs['page'],obs['scene'],{'ready':False},{'ready':False},
                                {'total':0},obs['support_probe'])
        self.assertEqual('enemy_front',result['selected_action']['combat_plan']['target_category'])
        rng.assert_called_once_with()

    def test_executor_reselection_and_dispatch_do_not_reroll(self):
        for roll in (.25,.75):
            with tempfile.TemporaryDirectory() as directory:
                bridge=mock.Mock();bridge.elapsedRealtime.return_value=2100;bridge.isCancelled.return_value=False
                bridge.dispatch.return_value=json.dumps(dict(accepted=False,completed=False,reason='temporary_game_window_occluded'))
                rng=mock.Mock(side_effect=AssertionError('execution rerolled'))
                engine=ActionExecutor(bridge,None,None,directory,50000,20,rng=rng)
                obs=battle();obs['selected_action']=select(obs,bomber_roll=roll);p=packet()
                engine.shape=(720,1280,3);engine.last_id=3;engine.last_capture_time=2000;engine.foreground_generation=7
                engine.ready_observation=(obs,p)
                chosen,p=engine.take_ready_observation()
                self.assertEqual(obs['selected_action'],chosen['selected_action'])
                with self.assertRaisesRegex(Replan,'temporary_game_window_occluded'):engine.execute(chosen,p)
                sent=json.loads(bridge.dispatch.call_args.args[0]);target=chosen['selected_action']['combat_plan']['target']
                self.assertEqual([target['cx'],target['cy']],sent['to']);rng.assert_not_called()
                self.assertEqual(0,engine.report['game_inputs']);self.assertEqual(1,len(engine.report['inputs']))
                self.assertNotIn(3,engine.consumed)
                for accepted,completed in ((True,False),(False,True)):
                    bridge.dispatch.return_value=json.dumps(dict(accepted=accepted,completed=completed,reason='temporary_game_window_occluded'))
                    with self.assertRaises(Stop) as error:engine.execute(chosen,p)
                    self.assertNotIsInstance(error.exception,Replan)
                    engine.consumed.clear()

    def test_deployment_exact_java_arithmetic(self):
        for case in deployment_fixtures():
            p=case['plan'];scale=case['frame']['height']/720.0
            expected=min(575*scale,p['from'][1]-60*scale)
            self.assertEqual(struct.pack('>d',expected).hex(),case['lift_bits'])
        self.assertNotEqual(1320*575/720,575*(1320/720.0))

    def test_pass_close_and_blank_contracts(self):
        for large in (False,True):
            obs,p=pass_observation(large=large)
            self.assertEqual('pass_popup',obs['state']);self.assertEqual('promotion_six_anchor_close',obs['popup_basis'])
            self.assertEqual(6,len(obs['promotion_evidence']))
            self.assertEqual(obs['promotion_evidence']['close']['bounds'],obs['targets']['menu_dismiss_pass'])
            self.assertEqual('menu_dismiss_pass',menu_request(obs,p)['context'])
            obs,p=pass_observation(large=large,blank=True)
            self.assertEqual('pass_title_subtitle_and_panel',obs['popup_basis'])
            self.assertEqual('menu_dismiss_pass',menu_request(obs,p)['context'])
        for missing in ('title','edge_top','edge_bottom','edge_left','edge_right'):
            obs,_=pass_observation(missing=missing)
            self.assertNotIn('menu_dismiss_pass',obs['targets'],missing)

    def test_opening_cache_lru_eviction_and_release(self):
        opening._recognizers.clear()
        try:
            with tempfile.TemporaryDirectory() as directory:
                dirs=[];refs=[]
                # Use real recognizers/templates under distinct campaign directories.
                import shutil
                for i in range(opening.MAX_RECOGNIZER_CACHE+3):
                    path=Path(directory)/str(i);shutil.copytree(ASSETS/'mulligan-one-shot',path);dirs.append(path)
                    refs.append(weakref.ref(opening._recognizer(path)))
                    self.assertLessEqual(len(opening._recognizers),opening.MAX_RECOGNIZER_CACHE)
                    if i==opening.MAX_RECOGNIZER_CACHE-1:
                        self.assertIs(refs[0](),opening._recognizer(dirs[0]))
                gc.collect();self.assertIsNone(refs[1]());self.assertIsNotNone(refs[0]())
                self.assertEqual(opening.MAX_RECOGNIZER_CACHE,len(opening._recognizers))
                opening.release_recognizer(dirs[-1]);gc.collect();self.assertIsNone(refs[-1]())
                opening.release_recognizer(dirs[-1])
        finally:opening._recognizers.clear()


if __name__=='__main__':
    import sys
    if len(sys.argv)==3 and sys.argv[1]=='--fixtures':
        out=Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=True)
        for name,cases in (('deploy',deployment_fixtures()),('pass',pass_fixtures())):
            rows=list(cases)
            (out/(name+'.jsonl')).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf8')
            print(name,len(rows))
    else:unittest.main()
