"""Read-only supplied-reference regression; generated cases are never live evidence."""
import hashlib,json,time
from pathlib import Path
import cv2,numpy as np
from .pipeline import load_banks,support
from .native_objects import Objects
from .native_hq import inspect as hq
from .native_board import board
from .frame_features import FrameFeatures

def run(directory,core,menu,opening):
    directory=Path(directory);manifest=json.loads((directory/'manifest.json').read_text(encoding='utf8'))
    _,bank=load_banks(core,menu,opening);objects=Objects(bank);results=[];failures=[]
    for item in manifest:
        raw=(directory/item['file']).read_bytes();assert hashlib.sha256(raw).hexdigest()==item['sha256']
        frame=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR);started=time.perf_counter()
        features=FrameFeatures(frame);scene=board(frame,objects.inspect(frame,features),features)
        own=[c for c in hq(frame,features) if c['structural_candidate']]
        enemy=[c for c in hq(frame,features,row='enemy_support') if c['structural_candidate']]
        probe=support(frame,scene,features)
        values=dict(own_hq=len(own)==1,enemy_hq=len(enemy)==1,front=scene['frontline']['owner'],vacancy=probe['vacancy_candidate'])
        checks={key:values[key]==item[key] for key in values if key in item}
        result=dict(file=item['file'],id=item['id'],kind=item['kind'],actual=values,checks=checks,
                    passed=all(checks.values()),elapsed_ms=(time.perf_counter()-started)*1000,
                    frontline_basis=scene['frontline']['basis'],coverage_basis=probe['coverage_basis'])
        results.append(result)
        if not result['passed']:failures.append(result)
    return json.dumps(dict(passed=not failures,fixture_count=len(manifest),results=results,failures=failures,
                           input_count=0,touch_count=0,live_games=0))
