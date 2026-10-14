"""Offline PC HQ/table sample audit; never opens or controls a game window."""
from pathlib import Path
import argparse
import json
import sys
import time
import cv2
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import board
import ui_state

def load(path):
    return cv2.imdecode(np.fromfile(path,dtype=np.uint8),cv2.IMREAD_COLOR)

def normalize(raw):
    scale=min(1280/raw.shape[1],720/raw.shape[0])
    width,height=round(raw.shape[1]*scale),round(raw.shape[0]*scale)
    resized=cv2.resize(raw,(width,height),interpolation=cv2.INTER_AREA)
    frame=np.zeros((720,1280,3),np.uint8)
    x0,y0=(1280-width)//2,(720-height)//2
    frame[y0:y0+height,x0:x0+width]=resized
    return frame
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--assets',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    templates=ui_state.load_templates(ui_state.load_meta('config/templates.json'))
    results=[]
    for path in sorted(args.assets.rglob('*.jpg')):
        raw=load(path)
        frame=normalize(raw)
        started=time.perf_counter()
        field=board.read_field(frame,templates=templates)
        enemy=board.find_enemy_hq(frame,field=field,templates=templates)
        row=dict(sample=path.parent.name,source=str(path),original_size=list(raw.shape[:2][::-1]),
                 normalization='uniform scale with black padding (offline only)',
                 elapsed_s=round(time.perf_counter()-started,3),
                 enemy=enemy,our=field['hq_our'],
                 boxes=board.card_boxes(frame),rows=field['rows'])
        results.append(row)
        marked=frame.copy()
        for name,hq,color in [('enemy',enemy,(0,0,255)),('our',field['hq_our'],(0,255,0))]:
            if hq:
                x,y,w,h=(int(hq[k]) for k in ('x','y','w','h'))
                cv2.rectangle(marked,(x,y),(x+w,y+h),color,2)
                cv2.putText(marked,f'{name} hp={hq.get("hp")}',(x,y-6),0,.5,color,1)
        cv2.imwrite(str(args.out/(path.parent.name+'.png')),marked)
        print(path.parent.name,'enemy=',None if not enemy else (enemy.get('hp'),enemy['x'],enemy['y']),
              'our=',None if not field['hq_our'] else (field['hq_our'].get('hp'),field['hq_our']['x'],field['hq_our']['y']),flush=True)
        (args.out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2,default=lambda x:x.item() if isinstance(x,np.generic) else str(x)),encoding='utf-8')

if __name__=='__main__':main()
