"""Saved source-frame inspector used by the existing bounded opening session."""
_components={}
def inspect_component(path,assets,engine,characters_json):
    import json
    import cv2,numpy as np
    from pathlib import Path
    from .onnx_ocr import OriginalModelOCR,java_inference
    from .opening import OpeningRecognizer
    offset=lambda box,distance:json.loads(str(engine.offsetPolygon(json.dumps(np.asarray(box).tolist()),float(distance))))
    key=str(assets)
    if key not in _components:
        _components[key]=(OpeningRecognizer(assets),OriginalModelOCR(java_inference(engine),json.loads(str(characters_json)),offset))
    recognizer,ocr=_components[key]
    frame=cv2.imdecode(np.frombuffer(Path(path).read_bytes(),np.uint8),1)
    if frame is None:raise ValueError('native_opening_decode_failed')
    h,w=frame.shape[:2]
    result=recognizer.observe(frame,dict(coordinate_space='source_pixels',source_width=w,source_height=h),ocr)
    return json.dumps(result,ensure_ascii=False)
