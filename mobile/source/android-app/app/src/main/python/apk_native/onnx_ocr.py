"""Original Paddle OCR preprocessing and decoding, with injectable inference.

The supplied frame remains in source pixels. Model preprocessing is aspect
preserving and its boxes are mapped back to the supplied frame by RapidOCR.
"""
import base64
import json
from pathlib import Path
import time

import cv2
import numpy as np

from .paddle.main import RapidOCR


class OriginalModelOCR:
    supports_turn_controls=True
    def __init__(self, infer, characters, offset_polygon=None):
        config = json.loads((Path(__file__).parent / 'paddle/config.json').read_text())
        # Packaged dictionary is already CTC-expanded; the original decoder
        # inserts blank and space itself, so supply only the model's raw chars.
        if characters[0] != 'blank' or characters[-1] != ' ':
            raise ValueError('native_ocr_character_contract')
        for key, model in [('Det', 'det'), ('Cls', 'cls'), ('Rec', 'rec')]:
            config[key].update(infer=infer, model=model)
        config['Rec']['characters'] = list(characters[1:-1])
        self.engine = RapidOCR(config)
        self.engine.text_det.postprocess_op.offset_polygon = offset_polygon
        import copy
        scoped=copy.deepcopy(config)
        # Small regions must not be inflated until their shortest side is 736.
        scoped['Det']['limit_type']='max'
        self.region_engine=RapidOCR(scoped)
        self.region_engine.text_det.postprocess_op.offset_polygon=offset_polygon

    def __call__(self, frame):
        if frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError('native_ocr_bgr_frame_required')
        return self.engine(frame)

    def regions(self,frame,regions,*,scope='opening_controls'):
        h,w=frame.shape[:2];items=[];times=np.zeros(3)
        if scope not in ('opening_controls','result_controls','menu_controls','turn_controls'):raise ValueError('native_ocr_region_scope')
        count_ok=(len(regions)==1 if scope=='turn_controls' else 1<=len(regions)<=2 if scope=='opening_controls' else len(regions)==2 if scope=='menu_controls' else len(regions)==3)
        if not count_ok:raise ValueError(scope+'_region_count')
        for x,y,bw,bh in regions:
            if not (0<=x<x+bw<=w and 0<=y<y+bh<=h):raise ValueError('opening_ocr_region_bounds')
            found,timing=self.region_engine(frame[y:y+bh,x:x+bw])
            for box,text,score in found or []:
                items.append(((np.asarray(box)+[x,y]).tolist(),text,float(score)))
            if timing:times+=np.asarray(timing)
        return items,times.tolist()


def java_inference(engine):
    def infer(model, array):
        data = np.ascontiguousarray(array, dtype='<f4')
        result = json.loads(str(engine.infer(model,
            base64.b64encode(data.tobytes()).decode('ascii'), json.dumps(list(data.shape)))))
        if result.get('ctc_compact') is True:
            if model!='rec':raise ValueError('native_ocr_compact_wrong_model')
            return {'indices': np.asarray(result['indices'],dtype=np.int64).reshape(result['shape']),
                    'scores': np.asarray(result['scores'],dtype=np.float32).reshape(result['shape'])}
        values = np.frombuffer(base64.b64decode(result['values']), dtype='<f4')
        return values.reshape(result['shape']).copy()
    return infer


_saved_engine = None

def inspect_saved_regions(path,engine,characters_json,regions_json,scope='opening_controls'):
    global _saved_engine
    started=time.perf_counter()
    if _saved_engine is None:
        offset=lambda box,distance:json.loads(str(engine.offsetPolygon(json.dumps(np.asarray(box).tolist()),float(distance))))
        _saved_engine=OriginalModelOCR(java_inference(engine),json.loads(str(characters_json)),offset)
    source=cv2.imdecode(np.fromfile(str(path),np.uint8),cv2.IMREAD_COLOR)
    if source is None:raise ValueError('native_ocr_invalid_saved_png')
    from .recognition_scale import shrink
    frame,factors=shrink(source)
    regions=json.loads(str(regions_json))
    reduced=[[round(v/(factors[0] if i%2==0 else factors[1])) for i,v in enumerate(box)] for box in regions]
    result,timings=_saved_engine.regions(frame,reduced,scope=scope)
    items=[dict(box=(np.asarray(box)*np.asarray(factors)).tolist(),text=text,score=float(score),score_available=True)
           for box,text,score in result or []]
    return json.dumps(dict(ok=True,width=source.shape[1],height=source.shape[0],coordinate_space='source_pixels',
                          items=items,elapsed_ms=(time.perf_counter()-started)*1000,
                          model_stage_ms=[float(v)*1000 for v in timings],scope=scope),ensure_ascii=False)


def inspect_saved(path, engine, characters_json, recognition_height=0):
    """Instrumentation-only entry: no capture, dispatch, or game interaction."""
    global _saved_engine
    started = time.perf_counter()
    if _saved_engine is None:
        offset = lambda box, distance: json.loads(str(engine.offsetPolygon(json.dumps(np.asarray(box).tolist()), float(distance))))
        _saved_engine = OriginalModelOCR(java_inference(engine), json.loads(str(characters_json)), offset)
    frame = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError('native_ocr_invalid_saved_png')
    source=frame
    if int(recognition_height)==720:
        from .recognition_scale import shrink
        frame,factors=shrink(frame)
    else:factors=(1.,1.)
    result, timings = _saved_engine(frame)
    items = [{'box': (np.asarray(box)*np.asarray(factors)).tolist(), 'text': text,
              'score': float(score), 'score_available': True}
             for box, text, score in (result or [])]
    return json.dumps({'ok': True, 'width': source.shape[1], 'height': source.shape[0],
        'coordinate_space': 'source_pixels', 'items': items,
        'elapsed_ms': (time.perf_counter() - started) * 1000,
        'model_stage_ms': [float(value) * 1000 for value in (timings or [])],
        'engine': 'original_paddle_onnxruntime_android'}, ensure_ascii=False)
