"""Offline regressions for ten-match failures. No input or game capture."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from unittest.mock import Mock,patch
from types import SimpleNamespace
import cv2,numpy as np
import board,kredits,turn_engine,hand_scanner_v2 as hs,hand_cost_filter as hcf
import weather_cards,orders,order_target

root=Path(__file__).resolve().parents[1]
e=turn_engine.TurnEngine.__new__(turn_engine.TurnEngine)
e.afford=kredits.Affordability();e.kredits_left=3;e._kredits_recheck=Mock(return_value=None)
e._reconcile_failed_deploy(9,True)
assert e.kredits_left==9 and e.afford.max_cost is None and e.afford.can_afford(8)
e.kredits_left=3;e._kredits_recheck=Mock(return_value=7)
e._reconcile_failed_deploy(9,False);assert e.kredits_left==7
e.kredits_left=3;e._kredits_recheck=Mock(return_value=None)
e._reconcile_failed_deploy(9,False);assert e.kredits_left==3
# Unconfirmed zero budget never enters the legacy blind scanner.
e.kredits_left=0;e._orange_enabled=lambda:True;e._kredits_measured=lambda:True
e.attempted_x=set();e.debug=False;e.log=print
e.scanner=SimpleNamespace(scan_orange=Mock(return_value=None),measure_edges=Mock(side_effect=AssertionError('blind scan')))
assert e._lazy_find_playable() is None
# No numeral bank entry for 0: hover an unknown orange cost and confirm zero.
frame=np.zeros((720,1280,3),np.uint8);frame[300:600,400:650]=200
scanner=hs.HandScannerV2.__new__(hs.HandScannerV2)
scanner._baseline=lambda:np.zeros_like(frame);scanner._hover_frame=lambda x:frame
scanner._move=lambda *a:None;scanner.user_took_over=lambda:False
scanner.safe=(1270,360);scanner.orange_cache=[]
scanner._classify=lambda *a,**k:dict(name='蓝天',type='order',cost=0)
anchor=dict(x=500,y=630,w=12,h=18,probe_x=528)
large=dict(x=420,y=300,w=20,h=32,probe_x=452)
with patch.object(hcf,'candidates',side_effect=[[anchor],[large]]),patch.object(hcf,'read_candidate_cost',return_value=None),patch.object(hs.time,'sleep'):
    cards=scanner.scan_orange(0)
    assert len(cards)==1 and cards[0]['cost']==0
with patch.object(hcf,'candidates',return_value=[]):
    assert scanner.scan_orange(0)==[]
# Enemy destroyed: do not use our only remaining HQ row as the enemy.
path=root/'logs/pc_campaign_20261014_004509/m04_1791912218984495100_0003_anomaly_hp_bogus.png'
f=cv2.imread(str(path));assert f is not None
assert board.find_enemy_hq(f) is None
assert board.read_hq_hp(f,{'side':'enemy','shield_box':(550,195,40,40)}) is None
print('Destroyed HQ real-frame replay PASSED')
# Friendly target variant chooses a real friendly unit; no unit means no drag.
def unit(x,y,hq=False):return dict(x=x-55,y=y-70,w=110,h=140,cx=x,cy=y,is_hq=hq)
def row(side,y,us):return dict(side=side,cy=y,y0=y-70,y1=y+70,units=us,boxes=us)
friend=unit(500,525);hq=unit(650,525,True)
field={'rows':[row('our',525,[friend,hq])],'our_support':[friend,hq],'frontline':[],'enemy_support':[]}
rule=next(r['rule_name'] for r in weather_cards.records() if r['cardId']=='temp_jungle_fever_2')
with patch.object(order_target.frontline_line,'read_frontline_owner',return_value={'owner':'empty'}):
    got=order_target.pick(rule,field,frame=np.zeros((720,1280,3),np.uint8))
    assert got and got['x']==500 and got['y']==525,got
    field['rows']=[row('our',525,[hq])];field['our_support']=[hq]
    assert order_target.pick(rule,field,frame=np.zeros((720,1280,3),np.uint8)) is None
print('Pending fixes PASSED')

# A nested blind fallback shares the outer budget, without touching a cursor.
class BudgetScanner(hs.HandScannerV2):
    @hs.bounded_scan
    def scan(self):
        self._check_scan_deadline()
        raise AssertionError('deadline not enforced')
    @hs.bounded_scan
    def find_playable(self):
        return self.scan()
b=BudgetScanner.__new__(BudgetScanner)
with patch.object(hs.time,'monotonic',side_effect=[0,13]):
    assert b.find_playable()==([],None)
assert b._scan_deadline is None and b.last_hand_count is None
print('Nested scan deadline PASSED')

# First hover only exposes board text/no cost; a fresh same-position hover
# can recover the hand card without walking more unrelated coordinates.
b=hs.HandScannerV2.__new__(hs.HandScannerV2)
b.y=700;b._last_client=(500,700);b.user_took_over=lambda:False
b._baseline=lambda:np.zeros_like(frame);b._hover_frame=Mock(return_value=frame)
b._classify_name=Mock(side_effect=[{'type':'order','name':None,'cost':None},
                                  {'type':'infantry','name':'第 104 步兵团','cost':4}])
got=b._classify(frame,frame=frame)
assert got['name']=='第 104 步兵团' and got['hover_retried']
b._hover_frame.assert_called_once_with(500)
print('Missing hover retry PASSED')
