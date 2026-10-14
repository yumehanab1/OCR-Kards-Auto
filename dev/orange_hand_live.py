"""Bounded PC training-game validation; --play authorizes existing engine input.

Does not start or queue a match. Saves raw per-tick frames and scan statistics.
"""
import argparse
import json
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
import cv2
from win import (set_dpi_aware,find_by_process,bring_to_front,capture_client_bgr,
                 acquire_single_instance_lock,window_is_capturable)
from ui_state import load_meta,load_templates,match_one
from hand_scanner_v2 import HandScannerV2
from turn_engine import TurnEngine


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--play',action='store_true')
    ap.add_argument('--seconds',type=int,default=180)
    args=ap.parse_args()
    root=Path(__file__).resolve().parents[1]
    out=root/'shots/orange_pc_20261013'/time.strftime('live_%H%M%S')
    out.mkdir(parents=True,exist_ok=True)
    set_dpi_aware()
    ok,reason=acquire_single_instance_lock()
    if not ok:raise RuntimeError(reason)
    wins=find_by_process('kards')
    if len(wins)!=1:raise RuntimeError('Expected one PC game window')
    hwnd=wins[0]['hwnd']
    bring_to_front(hwnd)
    templates=load_templates(load_meta(str(root/'config/templates.json')))
    if not args.play:
        scanner=HandScannerV2(hwnd,templates)
        cards=scanner.scan_orange(20)
        print(json.dumps({'cards':[{k:c[k] for k in ('name','type','cost','x')}
                                   for c in cards or []], 'stats':scanner.last_orange},ensure_ascii=False))
        return
    engine=TurnEngine(hwnd,templates,log=lambda s:print(s,flush=True),use_fast=True)
    start=time.monotonic()
    tick=0
    results=[]
    while time.monotonic()-start<args.seconds:
        if not window_is_capturable(hwnd,quiet=True):
            print('Window obscured; stop',flush=True)
            break
        frame=capture_client_bgr(hwnd)
        if frame is None:break
        tick+=1
        cv2.imwrite(str(out/f'{tick:03d}.png'),frame)
        if any(match_one(frame,templates[name])[0]>.82
               for name in ('victory_btn','defeat_btn') if name in templates):
            print('Game result detected; stop without queuing another match',flush=True)
            break
        status=engine.think()
        results.append(dict(tick=tick,status=status,phase=engine.phase,
                            budget=engine.kredits_left,orange=engine.scanner.last_orange))
        (out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        print(f'LIVE tick={tick} status={status} phase={engine.phase}',flush=True)
        if status=='selection_blocked':break
        time.sleep(1.2)
    print('Bounded live validation stopped',flush=True)


if __name__=='__main__':main()
