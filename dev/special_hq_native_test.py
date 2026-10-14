"""Offline A/B on saved native PC frames; writes differences for visual review."""
from pathlib import Path
import sys,json,time,statistics
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import cv2,board

root=Path(__file__).resolve().parents[1]
out=root/'logs/special_hq_native'
out.mkdir(exist_ok=True)
frames=sorted((root/'logs/pc_five_20261013_171141').glob('*periodic.png'))[::3]
assert len(frames)>=20
results=[]
for path in frames:
    frame=cv2.imread(str(path))
    assert frame.shape==(720,1280,3)
    record={'name':path.name}
    for mode in ('before','after'):
        board.EDGE_HQ_RECOVERY=board.TABLE_OUTLINE_GUARD=(mode=='after')
        t=time.perf_counter()
        field=board.read_field(frame)
        record[mode]={'seconds':time.perf_counter()-t,
                      'hq_enemy':field['hq_enemy'],'hq_our':field['hq_our'],
                      'units':[{k:b.get(k) for k in ('x','y','w','h','is_hq','hp','side')}
                               for row in field['rows'] for b in row['units']]}
    a,b=record['before'],record['after']
    changed=(len(a['units'])!=len(b['units']) or
             any(bool(a[k])!=bool(b[k]) or (a[k] and b[k] and a[k]['hp']!=b[k]['hp'])
                 for k in ('hq_enemy','hq_our')))
    record['review']=changed
    expected={
        'm02_0012_periodic.png': (5,20,20),
        'm03_0031_periodic.png': (None,14,20),
        'm03_0043_periodic.png': (None,1,13),
        'm05_1791885490124194000_0026_periodic.png': (7,20,21),
    }.get(path.name)
    if expected:
        n,enemy_hp,our_hp=expected
        assert n is None or len(b['units'])==n,(path.name,'unit count',b)
        assert b['hq_enemy'] and b['hq_enemy']['hp']==enemy_hp,(path.name,'enemy',b)
        assert b['hq_our'] and b['hq_our']['hp']==our_hp,(path.name,'our',b)
    if path.name=='m05_1791885403478844500_0023_periodic.png':
        assert b['hq_enemy'] is None,'Moving unit attack stat must not become an HQ'
    if changed:
        marked=frame.copy()
        for mode,col in [('before',(0,0,255)),('after',(0,255,0))]:
            for box in record[mode]['units']:
                x,y,w,h=(int(box[k]) for k in ('x','y','w','h'))
                cv2.rectangle(marked,(x,y),(x+w,y+h),col,1)
        cv2.imwrite(str(out/path.name),marked)
    results.append(record)
board.EDGE_HQ_RECOVERY=board.TABLE_OUTLINE_GUARD=True
(out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
print('native frames',len(results),'review',sum(r['review'] for r in results))
print('median seconds',{mode:round(statistics.median(r[mode]['seconds'] for r in results),3)
                        for mode in ('before','after')})
for r in results:
    if r['review']:print(r['name'],len(r['before']['units']),len(r['after']['units']))
