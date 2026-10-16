"""Orange candidate, rotated digit, combination and engine regressions. No input."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import cv2
import numpy as np
import hand_cost_filter as hcf


def card(x, cost, kind='infantry'):
    return dict(x=x, cost=cost, type=kind, name=str(x))


def main():
    assert [c['cost'] for c in hcf.best_combo([card(1,5),card(2,4),card(3,3)],7)] == [3,4]
    assert len(hcf.best_combo([card(1,2),card(2,2),card(3,4)],4)) == 2
    assert sum(c['cost'] for c in hcf.best_combo([card(1,4),card(2,3)],6)) == 4
    assert hcf.best_combo([card(1,1)],None) == []
    assert hcf.best_combo([card(1,2)],1) == []
    assert hcf.best_combo([card(1,2)],3,0) == []
    assert [c['cost'] for c in hcf.best_combo([card(1,2,'order')],3,0)] == [2]
    assert len(hcf.best_combo([card(1,0),card(2,0)],0,2)) == 2
    assert hcf.candidates(np.zeros((720,1280,3),np.uint8)) == []
    assert hcf.candidates(np.zeros((576,1024,3),np.uint8)) == []
    # A partial scan must not engage positional memory or the old two-play cap.
    from turn_engine import TurnEngine
    engine=TurnEngine(0,{})
    class Scanner:
        last_orange={'anchors':2,'ocr':2,'cached':0,'rejected':[]}
        def scan_orange(self,*args,**kwargs):
            assert kwargs['first_only'] is True
            return [dict(card(500,3),orange=True,panel=np.zeros((20,20,3),np.uint8))]
    engine.scanner=Scanner()
    engine.kredits_left=7
    engine.kredits_info={'measured':True}
    engine.log=lambda message:None
    engine._lazy_find_playable()
    assert [c['cost'] for c in engine.cards]==[3]
    assert all(c['_before'] is not None for c in engine.cards)
    engine.deployed_this_turn=2
    engine.hand_count_this_turn=7
    assert not engine._deploy_capped()
    root = Path(__file__).resolve().parents[1]
    for filename in ('neutral.png','check.png'):
        frame=cv2.imread(str(root/'shots/orange_pc_20261013'/filename))
        if frame is None:
            raise AssertionError('Missing real PC fixture: '+filename)
        found=hcf.candidates(frame)
        assert len(found)==1, (filename,found)
        value=hcf.read_candidate_cost(frame,found[0])
        assert value in (None,1), (filename,found)
        if filename=='neutral.png':
            assert value==1, (filename,found)
    # Tilting a numeral must preserve its value; no UI input is involved.
    for digit, templates in hcf._templates().items():
        template = templates[0]
        for angle in (-18,-9,0,9,18):
            mask=cv2.copyMakeBorder(template,15,15,15,15,cv2.BORDER_CONSTANT)
            hh,ww=mask.shape
            rotated=cv2.warpAffine(mask,cv2.getRotationMatrix2D((ww/2,hh/2),angle,1),
                                   (ww,hh),flags=cv2.INTER_NEAREST)
            ys,xs=np.where(rotated>0)
            # Use measured numeral geometry, not an invented fan anchor.
            tight=rotated[ys.min():ys.max()+1,xs.min():xs.max()+1]
            f=np.zeros((720,1280,3),np.uint8)
            h,w=tight.shape
            f[630:630+h,500:500+w][tight>0]=(0,150,230)
            anchor=dict(x=500,y=630,w=w,h=h)
            value=hcf.read_candidate_cost(f,anchor)
            assert value in (None,digit), (digit,angle,anchor)
            if angle==0:
                assert value==digit, (digit,angle,anchor)
    # This later, unseen hand has a real 2 and an orange artwork fragment.
    later=cv2.imread(str(root/'shots/orange_pc_20261013/live_153033/075.png'))
    if later is not None:
        values=[hcf.read_candidate_cost(later,c) for c in hcf.candidates(later)]
        assert values==[2,None],values
    print('Orange hand: combinations, engine integration, PC frames and rotated glyphs PASSED')


if __name__=='__main__':
    main()
