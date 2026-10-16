"""Saved phone weak-template victory and current semantic/identity negatives."""
import copy,json,time
from pathlib import Path
import cv2,numpy as np
from .pipeline import Pipeline,load_banks
from .result import ResultRecognizer
from .runtime import ResultProof
from .recognition_scale import shrink,coordinates
from .ocr_bridge import NativeOCR

def run(source,core,menu,opening,ocr):
    full=cv2.imdecode(np.frombuffer(Path(source).read_bytes(),np.uint8),1)
    frame,factors=shrink(full);checks=[]
    def check(name,valid):
        if not valid:raise AssertionError(name)
        checks.append(name)
    pipe=Pipeline(*load_banks(core,menu,opening),ocr)
    started=time.perf_counter();observed=pipe.observe(full);elapsed=(time.perf_counter()-started)*1000
    page=coordinates(observed['page'],1/factors[0],1/factors[1])
    check('actual_weak_result_proposed',observed['state']=='result_victory' and page['evidence']['victory_btn']['score']<.86)
    check('actual_current_three_regions_verified',page['result_proof']['ready'] and page['result_ocr']['scope']=='result_controls')
    check('actual_result_ocr_reported',page['ocr_used'] and len(page['result_ocr']['regions'])==3)
    packet=dict(frame_id=1,captured_elapsed_ms=1000,foreground_generation=3,source_width=full.shape[1],source_height=full.shape[0])
    proof=ResultProof()
    check('first_result_frame_does_not_finish',not proof.observe(observed,packet))
    check('second_fresh_result_frame_finishes',proof.observe(observed,dict(packet,frame_id=2,captured_elapsed_ms=2000)))
    for name,change in [('same_frame',dict(frame_id=1)),('generation_change',dict(frame_id=2,foreground_generation=4)),
                        ('shape_change',dict(frame_id=2,source_width=1920)),('too_close',dict(frame_id=2,captured_elapsed_ms=1100)),
                        ('too_old',dict(frame_id=2,captured_elapsed_ms=7000))]:
        proof=ResultProof();proof.observe(observed,packet)
        check(name+'_refused',not proof.observe(observed,dict(packet,**change)))
    before=copy.deepcopy(observed);before['page']['result_proof']={'ready':False}
    proof=ResultProof();check('old_unverified_result_not_promoted',not proof.observe(before,packet) and not proof.observe(before,dict(packet,frame_id=2,captured_elapsed_ms=2000)))
    template=pipe.page.results.continue_template
    for word in ('胜利','继续'):
        for variant in ('missing','weak','duplicate'):
            bad=copy.deepcopy(page)
            if variant=='missing':bad['ocr_items']=[r for r in bad['ocr_items'] if r['text'].replace(' ','')!=word]
            elif variant=='weak':
                for row in bad['ocr_items']:
                    if row['text'].replace(' ','')==word:row['score']=.89
            else:bad['ocr_items'].append(copy.deepcopy(next(r for r in bad['ocr_items'] if r['text'].replace(' ','')==word)))
            check(variant+'_'+word+'_refused',not ResultRecognizer(template).inspect(frame,bad,ocr)['ready'])
        damaged=frame.copy();pts=np.asarray(page['result_proof']['labels']['result' if word=='胜利' else word]['box'])
        x,y=np.floor(pts.min(0)).astype(int);a,b=np.ceil(pts.max(0)).astype(int)
        damaged[max(0,y-6):min(frame.shape[0],b+6),max(0,x-6):min(frame.shape[1],a+6)]=0
        bad=copy.deepcopy(page);bad.pop('ocr_items',None);bad.pop('result_ocr',None)
        check('erased_current_'+word+'_pixels_refused',not ResultRecognizer(template).inspect(damaged,bad,ocr)['ready'])
    bad=copy.deepcopy(page);bad['ocr_items'].append(dict(text='失败',score=.999,box=page['ocr_items'][0]['box']))
    check('conflicting_result_refused',not ResultRecognizer(template).inspect(frame,bad,ocr)['ready'])
    # Viewing the battlefield is optional; its OCR/position cannot veto the
    # current result title and continue control under the two-control contract.
    bad=copy.deepcopy(page);bad['ocr_items']=[r for r in bad['ocr_items'] if r['text'].replace(' ','')!='查看战场']
    check('missing_optional_view_does_not_block',ResultRecognizer(template).inspect(frame,bad,ocr)['ready'])
    bad=copy.deepcopy(page);next(r for r in bad['ocr_items'] if r['text'].replace(' ','')=='查看战场')['box']=[[0,0],[60,0],[60,30],[0,30]]
    check('optional_view_geometry_does_not_block',ResultRecognizer(template).inspect(frame,bad,ocr)['ready'])
    class Bridge:
        def __init__(self,change=None):self.change=change or {};self.requests=[]
        def recognizeNativeText(self,encoded):
            request=json.loads(encoded);self.requests.append(request)
            result=dict(request,ok=True,scope=request['ocr_scope'],coordinate_space='source_pixels',width=request['source_width'],height=request['source_height'],items=[])
            result.update(self.change);return json.dumps(result)
    bound=dict(packet,png_path='/current.png',coordinate_space='source_pixels')
    bridge=Bridge();native=NativeOCR(bridge);native.bind(bound)
    native.regions(frame,page['result_ocr']['regions'],scope='result_controls')
    check('result_request_exact_capture_bound',all(bridge.requests[0][k]==bound[k] for k in bound) and bridge.requests[0]['ocr_scope']=='result_controls')
    for key,value in [('frame_id',0),('captured_elapsed_ms',0),('foreground_generation',9),('png_path','/old.png'),('scope','opening_controls')]:
        native=NativeOCR(Bridge({key:value}));native.bind(bound)
        try:native.regions(frame,page['result_ocr']['regions'],scope='result_controls');rejected=False
        except ValueError:rejected=True
        check('mismatched_'+key+'_refused',rejected)
    return dict(passed=True,checks=checks,device_inputs=0,captures=0,result_page=page,original_recognition_ms=elapsed)

def run_device(source,core,menu,opening,engine,characters_json):
    from .onnx_ocr import OriginalModelOCR,java_inference
    offset=lambda box,distance:json.loads(str(engine.offsetPolygon(json.dumps(np.asarray(box).tolist()),float(distance))))
    return json.dumps(run(source,core,menu,opening,OriginalModelOCR(java_inference(engine),json.loads(str(characters_json)),offset)),ensure_ascii=False)
