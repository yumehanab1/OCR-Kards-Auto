"""Bounded production source-pixel observation probe. It never dispatches."""
import hashlib,json,time
from pathlib import Path
import cv2,numpy as np
from .pipeline import Pipeline,load_banks
from .ocr_bridge import NativeOCR

def run(bridge,core,menu,opening,evidence,max_frames=12):
    ocr=NativeOCR(bridge);pipeline=Pipeline(*load_banks(core,menu,opening),ocr)
    rows=[];last_id=-1;out=Path(evidence).resolve()
    reason='native_observation_complete'
    try:
        while len(rows)<int(max_frames) and not bridge.isCancelled():
            if int(bridge.elapsedRealtime())>=int(bridge.deadlineElapsedRealtime())-5000:
                reason='time_budget';break
            packet=json.loads(str(bridge.captureNative()))
            if packet.get('ok') is not True:
                if packet.get('reason')=='waiting_for_new_game_foreground':
                    time.sleep(.2);continue
                reason='capture_rejected:'+packet.get('reason','unknown');break
            path=Path(packet['png_path']).resolve()
            if out not in path.parents:raise ValueError('capture_outside_session_evidence')
            if packet['frame_id']<=last_id:raise ValueError('native_capture_sequence')
            raw=path.read_bytes();frame=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)
            if packet.get('coordinate_space')!='source_pixels' or frame.shape[:2]!=(packet['source_height'],packet['source_width']):
                raise ValueError('native_capture_geometry')
            if packet['width']!=packet['source_width'] or packet['height']!=packet['source_height']:
                raise ValueError('native_capture_was_resampled')
            last_id=packet['frame_id'];ocr.bind(packet)
            started=time.perf_counter();observed=pipeline.observe(frame)
            observed.update(capture=packet,source_sha256=hashlib.sha256(raw).hexdigest(),
                            observation_ms=(time.perf_counter()-started)*1000)
            rows.append(observed)
            bridge.emit(json.dumps({'kind':'native_observation','value':{
                'state':observed['state'],'frame_id':packet['frame_id'],
                'shape':observed['source_shape'],'timings_ms':observed['timings_ms'],
                'device_inputs':0}},default=encode))
            time.sleep(.5)
    except Exception as error:
        reason='native_observation_error:'+str(error)
    if bridge.isCancelled():reason='cancelled'
    result={'stop_reason':reason,'result_verified':False,'game_inputs':0,'inputs':[],'hooks':[],
            'captures':len(rows),'frames':rows,'scope':'read_only_live_source_pixels_not_match_validation'}
    (out/'native-observations.json').write_text(json.dumps(result,default=encode,ensure_ascii=False,indent=2),encoding='utf8')
    return json.dumps(result,default=encode,ensure_ascii=False)

def encode(value):
    if isinstance(value,np.ndarray):return value.tolist()
    if isinstance(value,np.generic):return value.item()
    raise TypeError(type(value).__name__)
