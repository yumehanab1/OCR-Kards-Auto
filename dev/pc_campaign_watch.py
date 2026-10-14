"""Run and observe a bounded PC training campaign using the production controller.

No alternative battle policy or recovery clicks. Stops for review on blocked
selection/exception; --resume preserves previous rounds and the current match.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import sys
import time
import traceback
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import cv2
import main_loop as ml
from actions import park_cursor
from win import (acquire_single_instance_lock,bring_to_front,find_by_process,
                 set_dpi_aware,set_window_client_size,capture_client_bgr)

ROOT=Path(__file__).resolve().parents[1]


class Attention(Exception):
    pass


class ObservedController(ml.Controller):
    def __init__(self,out,stats,total):
        super().__init__('kards',False,total,True,play=True,fast_scan=True,attack=True,lazy_scan=True)
        self.out,self.stats=out,stats
        self.max_ticks=0
        self.round_count=len(stats['rounds'])
        self.last_snapshot=0
        self.snapshot_count=0
        self.queue_epoch=None
        self.persist()

    def persist(self):
        self.stats.update(completed=len(self.stats['rounds']),updated_epoch=time.time(),
                          state=self.current_state,phase=getattr(self.turn_engine,'phase',None))
        target=self.out/'status.json'
        temporary=self.out/'status.tmp'
        temporary.write_text(json.dumps(self.stats,ensure_ascii=False,indent=2),encoding='utf-8')
        # Windows readers may briefly hold the destination without delete
        # sharing. Retry the atomic replace, never truncate the live status.
        for attempt in range(20):
            try:
                temporary.replace(target)
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(.025)
        (ROOT/'logs/pc_campaign_latest.json').write_text(json.dumps({'path':str(target),
            'run_id':self.stats['run_id'],'completed':self.stats['completed'],
            'status':self.stats['status']},ensure_ascii=False,indent=2),encoding='utf-8')

    def save_frame(self,tag,frame=None):
        if self.hwnd is None:return
        if frame is None:frame=capture_client_bgr(self.hwnd)
        if frame is None:return
        current=self.stats.get('current')
        match_id=current['id'] if current else len(self.stats['rounds'])+1
        self.snapshot_count+=1
        name=f'm{match_id:02d}_{time.time_ns()}_{self.snapshot_count:04d}_{tag}.png'
        cv2.imwrite(str(self.out/name),frame)
        return name

    def begin(self,stage):
        if self.stats.get('current') is None:
            self.stats['current']={'id':len(self.stats['rounds'])+1,'start_epoch':time.time(),
                'start_stage':stage,'queue_epoch':self.queue_epoch,'turns':0,
                'scans':[],'events':[],'successful_plays':0,'refused_plays':0,'legacy_fallbacks':0}
            self.persist()
        return self.stats['current']

    def grab_frame(self):
        frame=super().grab_frame()
        if frame is not None and time.monotonic()-self.last_snapshot>=25:
            self.last_snapshot=time.monotonic()
            if not self.stats.get('minimal_shots'):
                self.save_frame('periodic',frame)
            self.persist()
        if self.turn_engine is not None and self.turn_engine.phase=='selection_blocked':
            self.save_frame('selection_blocked',frame)
            raise Attention('selection_blocked: review current raw frame before resuming')
        current=self.stats.get('current')
        if current and time.time()-current['start_epoch']>1800:
            self.save_frame('match_timeout',frame)
            raise Attention('Current match exceeded 30 minutes')
        return frame

    def handle_queueing(self):
        if self.queue_epoch is None:self.queue_epoch=time.time()
        return super().handle_queueing()

    def handle_mulligan(self):
        self.begin('mulligan')
        return super().handle_mulligan()

    def handle_in_game(self):
        current=self.begin('in_game')
        current.setdefault('battle_epoch',time.time())
        started=time.perf_counter()
        super().handle_in_game()
        elapsed=time.perf_counter()-started
        if elapsed>15:
            current['events'].append({'epoch':time.time(),'kind':'slow_engine_tick',
                                      'seconds':elapsed,'phase':getattr(self.turn_engine,'phase',None)})
        self.persist()
        if self.turn_engine is not None and self.turn_engine.phase=='selection_blocked':
            self.save_frame('selection_blocked')
            raise Attention('selection_blocked: no recovery input issued')
        if getattr(self,'_te_err_n',0) or getattr(self,'_te_err_sig',None):
            self.save_frame('engine_error')
            raise Attention('Production turn engine reported an exception')

    def finish_round(self,result):
        current=self.stats.get('current')
        if current is None:
            raise Attention('Result without a new recorded match; do not double-count')
        self.save_frame('result_'+result)
        current.update(result=result,end_epoch=time.time(),
            elapsed_s=time.time()-current['start_epoch'],
            battle_s=time.time()-current.get('battle_epoch',current['start_epoch']))
        self.stats['rounds'].append(current)
        self.stats['current']=None
        self.queue_epoch=None
        super().finish_round(result)
        self.persist()

    def observe_log(self,msg):
        current=self.stats.get('current')
        if current is None:return
        if '[turn] our turn starts' in msg:current['turns']+=1
        scan=re.search(r'\[orange\] 扫描 ([\d.]+)s: 候选 (\d+), 可出 (\d+), 识别 (\d+), 缓存 (\d+)',msg)
        if scan:
            values=scan.groups()
            current['scans'].append(dict(epoch=time.time(),seconds=float(values[0]),
                anchors=int(values[1]),playable=int(values[2]),ocr=int(values[3]),cached=int(values[4])))
        if '回退原扫描' in msg:current['legacy_fallbacks']+=1
        if '部署成功' in msg or '指令打出 (' in msg or '已选边并确认完成' in msg:current['successful_plays']+=1
        if '部署被拒绝' in msg or '指令没打出去' in msg:current['refused_plays']+=1
        kinds={
            'selection_blocked':'停手','grab_identity_mismatch':'抓点复核失败',
            'refused_play':'部署被拒绝','unconfirmed_cost':'费用未能确认',
            'exception':'turn engine error','missing_cost':'费用读不出来',
            'recognition_fallback':'回退原扫描','selection_progress':'[selection]',
            'budget_combo':'[orange] 费用组合','candidate_rejection':'拒识 [',
        }
        for kind,fragment in kinds.items():
            if kind == 'candidate_rejection' and '拒识 []' in msg:
                continue
            if fragment in msg:
                current['events'].append(dict(epoch=time.time(),kind=kind,message=msg))
        self.persist()


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--rounds',type=int,default=5)
    ap.add_argument('--resume',type=Path)
    ap.add_argument('--minimal-shots',action='store_true')
    ap.add_argument('--game-version',default='unverified')
    ap.add_argument('--weather-audit',action='store_true')
    args=ap.parse_args()
    if args.resume:
        out=args.resume
        stats=json.loads((out/'status.json').read_text(encoding='utf-8-sig'))
        if len(stats['rounds'])>=args.rounds:raise RuntimeError('Requested campaign already complete')
    else:
        out=ROOT/'logs'/time.strftime('pc_campaign_%Y%m%d_%H%M%S')
        out.mkdir(parents=True,exist_ok=False)
        stats={'run_id':out.name,'system':'runtime-test','volume_serial':'7A77-760D',
               'game_version':args.game_version,'mode':'training','target':args.rounds,
               'start_epoch':time.time(),'rounds':[],'current':None,'segments':[]}
    set_dpi_aware()
    ok,why=acquire_single_instance_lock()
    if not ok:raise RuntimeError(why)
    wins=find_by_process('kards')
    if len(wins)!=1:raise RuntimeError('Expected one PC KARDS window')
    hwnd=wins[0]['hwnd']
    set_window_client_size(hwnd,1280,720)
    bring_to_front(hwnd)
    if args.resume and stats.get('current'):
        park_cursor(hwnd)
    ml.LOG=str(out/'events.log')
    # Training is manually selected first. Do not switch to casual or ranked.
    ml.MODE_BTNS=('training_mode_btn',)
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in list((ROOT/'src').glob('*.py'))+list((ROOT/'config/hand_cost_digits').glob('*'))
                     +[ROOT/'config/weather_variants.json',ROOT/'config/order_plays.json']
            if p.is_file()}
    stats['segments'].append({'start_epoch':time.time(),'hashes':hashes})
    stats['segments'][-1]['monitor_hash']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if stats.get('attention'):
        stats.setdefault('incidents',[]).append({'epoch':time.time(),
            'message':stats.pop('attention'),'action':'resumed after review'})
    if stats.get('exception'):
        stats.setdefault('incidents',[]).append({'epoch':time.time(),
            'message':stats.pop('exception'),'action':'resumed after monitor repair'})
    stats['status']='running'
    stats['minimal_shots']=args.minimal_shots or stats.get('minimal_shots',False)
    controller=ObservedController(out,stats,args.rounds)
    controller.hwnd=hwnd
    if stats['minimal_shots']:
        import attack
        import turn_engine
        attack.DUMP_ATTACK_FRAMES=False
        turn_engine.DUMP_SCAN_FRAMES=False
        seen=set()
        def anomaly_frame(tag,frame=None):
            key=(len(stats['rounds']),tag)
            if key not in seen:
                seen.add(key)
                controller.save_frame('anomaly_'+tag,frame)
        def dump_engine(engine,tag,name='',subdir='deploy_drag',cap=None):
            if tag in {'ambiguous','kredits_mismatch','invalid_rule','blocked',
                       'deploy_uncertain','cost_uncertain','drag_error','drag_failed'}:
                anomaly_frame(tag)
        turn_engine.TurnEngine._dump_frame=dump_engine
        # Preserve one HP anomaly per match, without routine attack images.
        def dump_hp(engine,frame,target,hp_before,hp_now,hp_late):
            anomaly_frame('hp_bogus',frame)
        attack.Attacker._dump_hp_bogus=dump_hp
    controller.save_frame('initial')
    original_log=ml.log
    def log(message):
        original_log(message)
        controller.observe_log(message)
    ml.log=log
    if args.weather_audit or stats.get('weather_audit'):
        import weather_cards
        stats['weather_audit']=True
        real_identify=weather_cards.identify
        weather_seen=set()
        weather_images=set(stats.get('weather_sample_keys',[]))
        def identify(info,region,ocr):
            result=real_identify(info,region,ocr)
            if info.get('name') not in weather_cards.names() or info.get('type')!='order':
                return result
            current=stats.get('current')
            if current is None:return result
            record=dict(epoch=time.time(),printed_name=info.get('name'),
                        variant=result.get('weather_id'),text=result.get('weather_text',''),
                        unresolved=result.get('weather_unresolved',False))
            key=(current['id'],record['printed_name'],record['variant'],record['text'])
            if key not in weather_seen:
                weather_seen.add(key)
                # Small crops, at most six unique samples per process segment.
                image_key=record['variant'] or ('unknown_'+record['printed_name'])
                if image_key not in weather_images and len(weather_images)<6:
                    weather_images.add(image_key)
                    stats['weather_sample_keys']=sorted(weather_images)
                    record['sample']=controller.save_frame('weather_'+str(len(weather_images)),region)
                current.setdefault('weather',[]).append(record)
                original_log('[weather_audit] '+json.dumps(record,ensure_ascii=False))
                controller.persist()
            return result
        weather_cards.identify=identify
    print('CAMPAIGN_STATUS='+str(out/'status.json'),flush=True)
    try:
        controller.run()
        stats['status']='completed' if len(stats['rounds'])==args.rounds else 'stopped_incomplete'
    except Attention as error:
        stats.update(status='attention',attention=str(error))
        original_log('CAMPAIGN_ATTENTION: '+str(error))
    except KeyboardInterrupt:
        stats['status']='interrupted'
    except Exception:
        stats.update(status='error',exception=traceback.format_exc())
        controller.save_frame('exception')
        original_log(stats['exception'])
    finally:
        stats['segments'][-1]['end_epoch']=time.time()
        controller.persist()
    print('CAMPAIGN_END '+stats['status'],flush=True)


if __name__=='__main__':main()
