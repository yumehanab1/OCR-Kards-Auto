"""Weather identity/target rules; optional user asset OCR replay. No game input."""
from pathlib import Path
import sys,argparse
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import weather_cards as w
import orders

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--assets',type=Path);args=ap.parse_args()
    rs=w.records();assert len(rs)==27
    for r in rs:
        assert w.resolve_text(r['name'],r['text'])==r,r
        assert not orders.playable('order',r['name']),r['name']
        assert orders.mode_of(r['rule_name'])==r['mode']
        assert w.resolve_text(r['name'],r['name']) is None
        assert w.resolve_text(r['name'],'本回合') is None
    for name in w.names():
        family=[r for r in rs if r['name']==name]
        assert w.resolve_text(name,''.join(r['text'] for r in family)) is None
    byid={r['cardId']:r for r in rs}
    assert orders.target_spec(byid['temp_jungle_fever_2']['rule_name'])['kind']=='4'
    assert orders.is_direct(byid['temp_thunderstorm_2']['rule_name']) # random, not targeted
    assert orders.target_spec(byid['temp_cyclone_2']['rule_name'])['kind']=='1'
    assert orders.is_blacklisted(byid['temp_torrential_rain_2']['rule_name'])
    # Name-only hash cache must not authorize an unresolved weather order.
    assert not orders.playable('order','旋风')
    assert orders.playable('fighter','旋风')
    import hand_cost_filter as hcf
    two_weather=[dict(name=byid[k]['rule_name'],cost=4,type='order',x=x)
                 for x,k in enumerate(('temp_jungle_fever_2','tropical_storm'))]
    normal=dict(name='第 104 步兵团',cost=4,type='infantry',x=3)
    combo=hcf.best_combo(two_weather+[normal],8)
    assert len(combo)==2 and sum(orders.is_weather(c['name']) for c in combo)==1
    import cv2
    from hover_card_reader import _ocr
    campaign=Path(__file__).resolve().parents[1]/'logs/pc_campaign_20261014_104905'
    for filename,name,variant in (
        ('m03_1791947955598891300_0003_weather_3.png','旋风','cyclone'),
        ('m04_1791948168465528000_0006_weather_5.png','骤雨','temp_torrential_rain_1')):
        path=campaign/filename
        if path.exists():
            got=w.identify(dict(name=name,type='order'),cv2.imread(str(path)),_ocr)
            assert got.get('weather_id')==variant,got
    if args.assets:
        import cv2,numpy as np
        from hover_card_reader import _ocr
        failed=[]
        for r in rs:
            f=cv2.imdecode(np.fromfile(args.assets/'images'/(r['cardId']+'.png'),np.uint8),cv2.IMREAD_COLOR)
            for width in (500,240):
                scaled=cv2.resize(f,(width,round(f.shape[0]*width/f.shape[1])))
                got=w.identify(dict(name=r['name'],type='order'),scaled,_ocr)
                print(r['cardId'],width,got.get('weather_id'),got.get('weather_text'),flush=True)
                if got.get('weather_id')!=r['cardId']:failed.append((r['cardId'],width,got))
        assert not failed,failed
    print('Weather variants PASSED')

if __name__=='__main__':main()
