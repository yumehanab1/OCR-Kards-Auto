"""Identify same-name weather orders by their printed effect, never by art/name alone."""
from pathlib import Path
from functools import lru_cache
from difflib import SequenceMatcher
import json,re

ENABLED = True

@lru_cache(maxsize=1)
def records():
    path=Path(__file__).resolve().parents[1]/'config/weather_variants.json'
    return json.loads(path.read_text(encoding='utf-8'))['cards']

def names():
    return {r['name'] for r in records()}

def norm(text):
    return re.sub(r'[^\u4e00-\u9fff0-9+\-]', '', text or '')

def resolve_text(name, text):
    """Require a substantial, unique match within the printed-name family."""
    text=norm(text)
    if not ENABLED or len(text)<6:
        return None
    ranked=[]
    for r in records():
        if r['name']!=name:continue
        expected=norm(r['text'])
        if len(expected)<12 and text!=expected:
            continue
        matched=sum(b.size for b in SequenceMatcher(None,expected,text).get_matching_blocks())
        coverage=matched/len(expected)
        precision=matched/len(text)
        if precision < .80:
            continue
        score=2*coverage*precision/(coverage+precision) if coverage+precision else 0
        ranked.append((score,coverage,r))
    ranked.sort(key=lambda x:x[0],reverse=True)
    if not ranked or ranked[0][0]<.72 or ranked[0][1]<.65:
        return None
    if len(ranked)>1 and ranked[0][0]-ranked[1][0]<.18:
        return None
    return ranked[0][2]

def identify(info, region, ocr):
    name=info.get('name')
    if name not in names() or info.get('type')!='order':
        return info
    # Always reread effect, including a name-hash hit. Same art and title do
    # not identify the version. The orange cache includes this effect band.
    lines=ocr(region)
    titles=[ln for ln in lines if norm(ln.get('text'))==norm(name)]
    if not titles:
        return dict(info,weather_unresolved=True)
    title=max(titles,key=lambda ln:ln.get('h',0))
    tx=title.get('x',0)+title.get('w',0)/2
    ty=title.get('y',0)+title.get('h',0)
    width=max(85,min(320,title.get('h',20)*12))
    desc=sorted((ln for ln in lines if ln.get('conf',0)>=.5
        and ln.get('y',0)>=ty-2 and ln.get('y',0)<ty+max(130,title.get('h',20)*7)
        and abs(ln.get('x',0)+ln.get('w',0)/2-tx)<width/2),
        key=lambda ln:(ln.get('y',0)//8,ln.get('x',0)))
    # Description lines form one paragraph immediately below the title.
    # Stop at the blank card footer instead of reading the separate hand fan.
    paragraph=[]
    bottom=ty
    line_height=title.get('h',20)
    for ln in desc:
        if ln.get('y',0)-bottom > max(12,1.5*line_height):
            break
        paragraph.append(ln)
        bottom=max(bottom,ln.get('y',0)+ln.get('h',0))
        line_height=ln.get('h',line_height)
    text=''.join(ln['text'] for ln in paragraph)
    rec=resolve_text(name,text)
    result=dict(info,printed_name=name,weather_text=text,weather_unresolved=rec is None)
    if rec:
        result.update(name=rec['rule_name'],weather_id=rec['cardId'],cost=rec['cost'],type='order')
    return result
