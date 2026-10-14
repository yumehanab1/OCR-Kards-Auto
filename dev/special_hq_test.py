"""Offline special HQ regression. Source JPGs retain their original aspect ratio.

Expected HQ positions and unit counts were labelled from the source scenes,
not generated from detector output. Swaps and asset renders are synthetic.
"""
import argparse
import json
from pathlib import Path
import sys
import time
import cv2
import numpy as np
from special_hq_probe import load,normalize
import board

ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('--assets',type=Path,required=True)
ap.add_argument('--out',type=Path,default=Path('logs/special_hq_test'))
args=ap.parse_args()
args.out.mkdir(parents=True,exist_ok=True)
failures=[]
results=[]

def check(frame,name,enemy_x=639,our_x=642,counts=None):
    t=time.perf_counter()
    field=board.read_field(frame)
    enemy=board.find_enemy_hq(frame,field=field)
    got=[]
    for side,hq,x,y in [('enemy',enemy,enemy_x,172),('our',field['hq_our'],our_x,527)]:
        ok=(hq is not None and hq.get('hp')==20 and
            abs(hq['x']+hq['w']/2-x)<=10 and abs(hq['y']+hq['h']/2-y)<=12 and
            95<=hq['w']<=132 and 130<=hq['h']<=170)
        if not ok:failures.append((name,side,hq))
        if side=='enemy' and hq and not(hq['x']<=hq['cx']<=hq['x']+hq['w'] and
                                        hq['y']<=hq['cy']<=hq['y']+hq['h']):
            failures.append((name,'target_outside_card',hq))
        got.append(ok)
    if counts:
        actual=(len(field['enemy_support']),len(field['our_support']),len(field['frontline']))
        if actual!=counts:failures.append((name,'counts',actual,counts))
        support=board.support_line_units(frame,rows=field['rows'])
        if support['n']!=counts[1]-1:
            failures.append((name,'support_slots',support['n'],counts[1]-1))
    results.append(dict(name=name,ok=all(got),seconds=round(time.perf_counter()-t,4)))
    if not all(got) or (counts and actual!=counts):
        cv2.imwrite(str(args.out/(name+'.png')),frame)
    return field

scenes=sorted(args.assets.rglob('*.jpg'))
assert len(scenes)==19
for path in scenes:
    name=path.parent.name.replace('KARDS_HQ_card_location_','')
    frame=normalize(load(path))
    enemy_x=567 if name in ('moscow','supply_train_neutral') else 639
    check(frame,'real_'+name,enemy_x,counts=(2 if enemy_x==567 else 1,1,0))
    # Transplant full card patches without distorting them. Preserve every
    # surrounding unit and table; special HQ becomes the enemy attack target.
    swapped=frame.copy()
    ex=int(enemy_x)-60
    a=frame[92:252,ex:ex+120].copy()
    b=frame[447:607,582:702].copy()
    swapped[92:252,ex:ex+120]=b
    swapped[447:607,582:702]=a
    check(swapped,'enemy_special_'+name,enemy_x,counts=(2 if enemy_x==567 else 1,1,0))

# Artwork PNGs are collection cards (they include a caption and a printed 20),
# not battle screenshots. Test their colour/texture separately by placing the
# undistorted upper art on a standard battle card with a real dynamic shield.
# This is explicitly a synthetic layout test, not evidence of live skins.
reference=normalize(load(next((args.assets/'KARDS_HQ_card_location_concrete_bunker_neutral').glob('*.jpg'))))
shield=reference[539:590,619:666].copy()
tables={}
for folder in sorted(p for p in args.assets.iterdir() if p.is_dir()):
    table_path=folder/'tablecloth_clean.png'
    if not table_path.exists():table_path=folder/'tablecloth_with_shadow.png'
    raw=load(table_path)
    # Crop after uniform resizing: never squash the table image.
    scale=max(1280/raw.shape[1],720/raw.shape[0])
    tile=cv2.resize(raw,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA)
    ty,tx=(tile.shape[0]-720)//2,(tile.shape[1]-1280)//2
    table=tile[ty:ty+720,tx:tx+1280].copy()
    tables[folder]=table
    empty=board.read_field(table)
    if any(empty[k] for k in ('enemy_support','our_support','frontline')):
        failures.append(('empty_table_'+folder.name,'phantom_cards',empty['rows']))
        cv2.imwrite(str(args.out/('empty_table_'+folder.name+'.png')),table)

assets=sorted(args.assets.rglob('headquarter*.png'))
assert len(assets)==46 and len(tables)==21
for index,path in enumerate(assets):
    raw=load(path)
    # Fill lower caption area with the skin's own background tone, then put
    # back the dynamic battle HP. Preserve all upper-art pixels' aspect ratio.
    tone=np.median(raw[20:330,20:-20].reshape(-1,3),axis=0).astype(np.uint8)
    portrait=cv2.resize(raw,(107,150),interpolation=cv2.INTER_AREA)
    portrait[72:148,2:105]=tone
    portrait[88:139,30:77]=shield
    scene=tables[path.parent].copy()
    scene[98:248,586:693]=portrait
    scene[452:602,589:696]=portrait
    check(scene,f'asset_{index:02d}_{path.parent.name}',counts=(1,1,0))
    if index%6==0:cv2.imwrite(str(args.out/f'asset_preview_{index:02d}.png'),scene)

(args.out/'results.json').write_text(json.dumps(dict(results=results,failures=failures),ensure_ascii=False,indent=2,default=str),encoding='utf-8')
print('cases',len(results),'empty tables',len(tables),'failures',len(failures),flush=True)
for f in failures:print(f,flush=True)
assert not failures
