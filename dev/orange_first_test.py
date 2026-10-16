"""Orange-only first-card scan boundaries. Fake frames; no game/cursor input."""
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import hand_scanner_v2 as hs
import hand_cost_filter as hcf
from turn_engine import TurnEngine
import weather_cards


class OrangeFirst(unittest.TestCase):
    def engine(self,budget,measured=True,enabled=True):
        e=TurnEngine(0,{})
        e.log=lambda msg:None;e.kredits_left=budget;e.kredits_info={'measured':measured}
        e._orange_enabled=lambda:enabled
        e.scanner=SimpleNamespace(scan_orange=Mock(return_value=None),last_orange={},
            measure_edges=Mock(side_effect=AssertionError('legacy edge probe')),
            scan=Mock(side_effect=AssertionError('blind scan')),
            scan_fast=Mock(side_effect=AssertionError('whole hand scan')))
        return e

    def test_zero_never_legacy_for_untrusted_or_disabled_filter(self):
        for enabled in (True,False):
            for measured in (True,False):
                e=self.engine(0,measured,enabled)
                self.assertIsNone(e._lazy_find_playable())
                self.assertEqual(e.cards,[])
                self.assertEqual(e._scan(),[])
                e.scanner.measure_edges.assert_not_called()
                e.scanner.scan.assert_not_called()
                e.scanner.scan_fast.assert_not_called()

    def test_positive_unknown_and_estimated_budgets_never_legacy(self):
        for budget in (None,1,12):
            e=self.engine(budget,False)
            self.assertIsNone(e._lazy_find_playable())
            e.scanner.scan_orange.assert_called_once()
            self.assertTrue(e.scanner.scan_orange.call_args.kwargs['first_only'])
            e.scanner.measure_edges.assert_not_called()

    def test_no_target_position_is_excluded_on_next_scan(self):
        e=self.engine(7);e.failed_x.add(528)
        e._lazy_find_playable()
        self.assertIn(528,e.scanner.scan_orange.call_args.kwargs['exclude'])

    def scanner(self,infos):
        b=hs.HandScannerV2.__new__(hs.HandScannerV2)
        b._baseline=lambda:np.zeros((720,1280,3),np.uint8)
        f=np.zeros((720,1280,3),np.uint8);f[300:600,400:650]=200
        b._hover_frame=Mock(return_value=f);b._move=Mock()
        b.user_took_over=lambda:False;b.safe=(1270,360);b.orange_cache=[]
        b._classify=Mock(side_effect=infos)
        return b

    def replay(self,b,first_only=True,budget=7,**kwargs):
        anchors=[dict(x=500+80*i,y=630,w=12,h=18,probe_x=528+80*i) for i in range(3)]
        large=dict(x=420,y=300,w=20,h=32,probe_x=452)
        def candidates(frame,**kw):return [large] if 'height_range' in kw else anchors
        with patch.object(hcf,'candidates',side_effect=candidates), \
             patch.object(hcf,'read_candidate_cost',return_value=1), \
             patch.object(hs.time,'sleep'):
            return b.scan_orange(budget,first_only=first_only,**kwargs)

    def test_first_card_stops_without_identifying_rest(self):
        info=dict(name='第 506 空降步兵团',type='infantry',cost=1)
        b=self.scanner([info]);self.assertEqual(len(self.replay(b)),1)
        self.assertEqual(b.last_orange['probed'],1)
        b._classify.assert_called_once();b._hover_frame.assert_called_once()

    def test_known_zero_card_is_still_playable(self):
        b=self.scanner([dict(name='蓝天',type='order',cost=0)])
        a=dict(x=500,y=630,w=12,h=18,probe_x=528)
        large=dict(x=420,y=300,w=20,h=32,probe_x=452)
        with patch.object(hcf,'candidates',side_effect=[[a],[large]]), \
             patch.object(hcf,'read_candidate_cost',return_value=None),patch.object(hs.time,'sleep'):
            cards=b.scan_orange(0,first_only=True)
        self.assertEqual(cards[0]['cost'],0)

    def test_unconfirmed_or_positive_card_at_zero_never_returned(self):
        for displayed in (None,1):
            b=self.scanner([dict(name='蓝天',type='order',cost=displayed)])
            a=dict(x=500,y=630,w=12,h=18,probe_x=528)
            large=dict(x=420,y=300,w=20,h=32,probe_x=452)
            with patch.object(hcf,'candidates',side_effect=[[a],[large]]), \
                 patch.object(hcf,'read_candidate_cost',return_value=None),patch.object(hs.time,'sleep'):
                self.assertEqual(b.scan_orange(0,first_only=True),[])

    def test_zero_real_fail_frames_need_no_hover(self):
        import cv2
        frames=Path(__file__).resolve().parents[1]/'logs/orange_speed_20261016_frames'
        paths=list(frames.glob('1016_*.png'))
        if not paths:self.skipTest('Local PC zero-budget screenshots are absent')
        # Existing PC zero-budget failure screenshots, optional on another system.
        for p in sorted(paths):
            frame=cv2.imread(str(p));self.assertEqual(hcf.candidates(frame),[])
            b=self.scanner([]);b._baseline=lambda:frame
            self.assertEqual(b.scan_orange(0,first_only=True),[])
            b._hover_frame.assert_not_called()

    def test_full_line_skips_unit_and_finds_order(self):
        unit=dict(name='第 506 空降步兵团',type='infantry',cost=1)
        order=dict(name='蓝天',type='order',cost=1)
        b=self.scanner([unit,order])
        # Different fingerprints prevent a synthetic identical-image cache hit.
        b.orange_cache=type('NoCache',(list,),{'append':lambda self,value:None})()
        cards=self.replay(b,allow_units=False)
        self.assertEqual(cards[0]['name'],'蓝天');self.assertEqual(b._hover_frame.call_count,2)

    def test_already_played_weather_does_not_hide_next_unit(self):
        name=weather_cards.records()[0]['rule_name']
        b=self.scanner([dict(name=name,type='order',cost=1,weather_id='weather'),
                        dict(name='第 506 空降步兵团',type='infantry',cost=1)])
        cards=self.replay(b,weather_played=True)
        self.assertEqual(cards[0]['type'],'infantry')

    def test_unknown_fan_digit_can_use_enlarged_orange_cost(self):
        b=self.scanner([dict(name='第 506 空降步兵团',type='infantry',cost=1)])
        a=dict(x=500,y=630,w=12,h=18,probe_x=528)
        large=dict(x=420,y=300,w=20,h=32,probe_x=452)
        with patch.object(hcf,'candidates',side_effect=[[a],[large]]), \
             patch.object(hcf,'read_candidate_cost',side_effect=[None,1]),patch.object(hs.time,'sleep'):
            cards=b.scan_orange(7,first_only=True)
        self.assertEqual(cards[0]['cost'],1)

    def test_deadline_stops_before_another_hover(self):
        b=self.scanner([])
        a=dict(x=500,y=630,w=12,h=18,probe_x=528)
        with patch.object(hcf,'candidates',return_value=[a]), \
             patch.object(hs.time,'perf_counter',side_effect=[0,5]),patch.object(hs.time,'sleep'):
            self.assertEqual(b.scan_orange(7,first_only=True),[])
        b._hover_frame.assert_not_called();self.assertTrue(b.last_orange['deadline'])

    def test_real_left_hover_fee_at_one_credit(self):
        import cv2
        samples=Path(__file__).resolve().parents[1]/'shots/orange_hover_roi_20261016'
        cases=[('1016_130701_x405.png',405),('1016_125431_x388.png',388),
               ('1016_123254_x455.png',455)]
        if not all((samples/name).exists() for name,_ in cases):
            self.skipTest('Local PC hover screenshots are absent')
        actual_candidates=hcf.candidates
        actual_cost=hcf.read_candidate_cost
        for name,px in cases:
            with self.subTest(name=name):
                frame=cv2.imread(str(samples/name))
                anchor=dict(x=px-27,y=680,w=11,h=17,probe_x=px)
                def candidates(image,**kwargs):
                    return actual_candidates(image,**kwargs) if image is frame else [anchor]
                def cost(image,candidate):
                    return actual_cost(image,candidate) if image is frame else 1
                for enabled,expected in ((False,0),(True,1)):
                    b=self.scanner([dict(name='丁格犬侦察车',type='tank',cost=1)])
                    b._hover_frame=Mock(return_value=frame)
                    with patch.object(hcf,'candidates',side_effect=candidates), \
                         patch.object(hcf,'read_candidate_cost',side_effect=cost), \
                         patch.object(hs,'ORANGE_HOVER_EDGE_FIX',enabled),patch.object(hs.time,'sleep'):
                        cards=b.scan_orange(1,first_only=True)
                    self.assertEqual(len(cards),expected)
                    if enabled:self.assertEqual(cards[0]['cost'],1)
                # The same real hover cannot authorize a different fan fee.
                def wrong_cost(image,candidate):
                    return actual_cost(image,candidate) if image is frame else 2
                b=self.scanner([]);b._hover_frame=Mock(return_value=frame)
                with patch.object(hcf,'candidates',side_effect=candidates), \
                     patch.object(hcf,'read_candidate_cost',side_effect=wrong_cost),patch.object(hs.time,'sleep'):
                    self.assertEqual(b.scan_orange(2,first_only=True),[])
                b._classify.assert_not_called()


if __name__=='__main__':unittest.main(verbosity=2)
