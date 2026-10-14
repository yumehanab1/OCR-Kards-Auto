"""Guard protection and target routing regression; no game input."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from unittest.mock import patch
import cv2,numpy as np
import guard,attack,board

def card(x,hq=False):
    return dict(x=x,y=100,w=110,h=145,cx=x+55,cy=172,is_hq=hq)
hq=card(650,True);g=card(510);other=card(370)
f=np.zeros((720,1280,3),np.uint8)
def glyph(frame,b,**kw):
    ok=b is g
    return (1 if ok else 0),dict(ok=ok,which='unit',score=1 if ok else 0)
with patch.object(guard,'glyph_at',side_effect=glyph):
    field={'enemy_support':[g,hq],'frontline':[]}
    info=guard.read_guard(f,field)
    assert info['hq_guarded'] and info['guard_units']==[g]
    a=attack.Attacker.__new__(attack.Attacker)
    a.templates={};a.log=lambda s:None;a.hq_blocked=False;a.blocked_hq_skips=0
    a._interceptors=lambda field:[]
    got=a._pick_target(f,field,dict(type='fighter',targets={attack.TARGET_ENEMY_HQ,attack.TARGET_ENEMY_SUPPORT}), 'enemy',info)
    assert got and got['kind']==attack.TARGET_ENEMY_SUPPORT and got['cx']==g['cx'],got
    # A card between guard and HQ prevents adjacency protection.
    hq2=card(790,True)
    assert not guard.read_guard(f,{'enemy_support':[g,card(650),hq2]})['hq_guarded']
    assert not guard.read_guard(f,{'enemy_support':[other,hq],'frontline':[g]})['hq_guarded']
    # Random bomber branch must filter protected frontline targets too.
    a._drop_protected=lambda units,frame:([g],1)
    with patch.object(attack.random,'random',return_value=0):
        got=a._pick_target(f,{'enemy_support':[],'frontline':[other,g]},
                          dict(type='bomber',targets={attack.TARGET_ENEMY_FRONT}), 'enemy',{})
        assert got['cx']==g['cx']
# The current raw frame has frontline guards, not a guarded rear HQ.
root=Path(__file__).resolve().parents[1]
current=cv2.imread(str(root/'logs/weather_guard_current_20261014.png'))
assert current is not None
field=board.read_field(current)
assert not guard.read_guard(current,field)['hq_guarded']
print('Guard adjacency, target routing and real negative frame PASSED')
