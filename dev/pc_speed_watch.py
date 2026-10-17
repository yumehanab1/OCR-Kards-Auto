"""Observe production PC training/casual games with buffered timing spans.

Running main DOES focus/resize KARDS and issue the normal production inputs.
Import/help do not start a game. Default: current strategy, eight observed own
turns, at most five matches. No alternate card policy, forced end or recovery.
Outputs logs/pc_speed_<label>_<timestamp>/{events,status,profile}.json/log.
"""
from pathlib import Path
import argparse
from collections import Counter
from functools import wraps
import hashlib
import json
import re
import sys
import threading
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'dev')]
import pc_campaign_watch as campaign
import main_loop as ml
import hand_scanner_v2 as hs
import hover_card_reader as reader
import turn_engine as te
import attack
import board
import actions
import kredits
import order_choice
import weather_cards
import win
import cv2


class ObservationLimit(Exception):
    pass


class Profiler:
    def __init__(self,out,stats,slow=3.0,max_images=6):
        self.out,self.stats,self.slow,self.max_images=out,stats,slow,max_images
        self.controller=None;self.engine=None;self.stack=[];self.restore=[]
        self.main_thread=threading.get_ident();self.in_flush=False
        self.clock=time.perf_counter;self.original_sleep=time.sleep
        self.active=None;self.force_flush=False;self.scan_id=0;self.in_scan=None
        self.last_frame=None;self.images=[];self.image_count=0
        self.scan_hovers={}
        self.data=stats.setdefault('performance',{'methods':{},'turns':[],
            'scans':[],'classifications':[],'slow_calls':[],'ocr':[],
            'limits':['First observed own-turn button begins timing; attaching mid-turn can produce a partial first turn.',
                      'Button loss is distinct from voluntary end, but does not by itself prove a timeout.',
                      'Spans include nested calls; use self_s to avoid double counting.',
                      'Images reuse existing capture/crop arrays; no additional screenshot is taken for profiling.']})
        self.data.pop('active_turn',None)
        self.scan_id=max((row.get('scan') or 0 for row in self.data['scans']),default=0)
        self.image_count=max(int(self.data.get('image_count',0)),len(list(out.glob('profile_*.png'))))
        self.data.setdefault('hover_mismatch_samples',[])
        self.mismatch_seen={tuple(row['key']) for row in self.data['hover_mismatch_samples']}

    def completed_turns(self):
        return sum(t.get('end_kind')!='stopped_incomplete' for t in self.data['turns'])

    def context(self):
        e=self.engine
        return {'phase':getattr(e,'phase',None),'budget':getattr(e,'kredits_left',None),
                'turn':self.active['id'] if self.active else None,'scan':self.in_scan}

    @staticmethod
    def add(bucket,name,elapsed,own):
        row=bucket.setdefault(name,{'count':0,'wall_s':0.0,'self_s':0.0,'max_s':0.0})
        row['count']+=1;row['wall_s']+=elapsed;row['self_s']+=own
        row['max_s']=max(row['max_s'],elapsed)

    def start_turn(self,engine):
        if self.active:return
        now=self.clock()
        entry=next((s['start'] for s in reversed(self.stack) if s['name']=='turn.think'),now)
        self.active={'id':len(self.data['turns'])+1,'start_epoch':time.time()-(now-entry),
                     '_start':entry,'methods':{},'ticks':[],'budget_changes':[],
                     'start_detection':'first observed own-turn button','occlusion_events':0}
        self.engine=engine

    def finish_turn(self,kind):
        if not self.active:return
        row=self.active;row['duration_s']=self.clock()-row.pop('_start')
        row.update(end_epoch=time.time(),end_kind=kind,
                   timeout='not_proven' if kind=='button_lost' else False)
        self.data['turns'].append(row);self.active=None;self.force_flush=True
        if kind=='button_lost':self.queue_image('button_lost',self.last_frame)

    def queue_image(self,tag,frame):
        if frame is None or self.image_count>=self.max_images:return
        self.image_count+=1
        name=f'profile_{self.image_count:02d}_{tag}.png'
        self.images.append((name,frame.copy()))
        return name

    def sample_hover_mismatch(self,detail):
        if len(self.data['hover_mismatch_samples'])>=2:return
        for rejected in detail.get('rejected') or ():
            if len(self.data['hover_mismatch_samples'])>=2:return
            if rejected.get('reason')!='hover cost/color mismatch':continue
            hover=self.scan_hovers.get(rejected.get('probe_x'))
            if hover is None or hover['scan']!=self.in_scan:continue
            frame=hover['frame']
            if frame is None or tuple(frame.shape[:2])!=(720,1280):continue
            key=(rejected.get('probe_x'),rejected.get('fan_cost'),rejected.get('hover_cost'))
            if key in self.mismatch_seen:continue
            name=self.queue_image('hover_cost_mismatch',frame)
            if name:
                self.mismatch_seen.add(key)
                self.data['hover_mismatch_samples'].append(dict(
                    self.context(),key=list(key),image=name,rejection=rejected))
            else:return

    def wrap(self,name,fn):
        @wraps(fn)
        def call(*args,**kwargs):
            if self.in_flush or threading.get_ident()!=self.main_thread:
                return fn(*args,**kwargs)
            if name=='turn.think':self.engine=args[0]
            old_scan=self.in_scan
            if name=='scanner.scan_orange':
                self.scan_id+=1;self.in_scan=self.scan_id
                self.scan_hovers={}
            context=self.context();cache_before=None
            if name=='scanner.scan_orange':cache_before=len(getattr(args[0],'orange_cache',()))
            span={'name':name,'start':self.clock(),'child':0.0}
            self.stack.append(span);result=None;error=None
            try:
                result=fn(*args,**kwargs)
                return result
            except BaseException as exc:
                error=type(exc).__name__;raise
            finally:
                elapsed=self.clock()-span['start'];self.stack.pop()
                if self.stack:self.stack[-1]['child']+=elapsed
                own=max(0,elapsed-span['child'])
                self.add(self.data['methods'],name,elapsed,own)
                if self.active:self.add(self.active['methods'],name,elapsed,own)
                if elapsed>=self.slow:
                    self.data['slow_calls'].append(dict(context,method=name,seconds=elapsed,error=error,epoch=time.time()))
                    self.data['slow_calls']=sorted(self.data['slow_calls'],key=lambda r:r['seconds'],reverse=True)[:80]
                if name=='capture' and result is not None:self.last_frame=result
                if name=='scanner.hover_frame' and self.in_scan is not None and result is not None:
                    probe_x=args[1] if len(args)>1 else kwargs.get('x')
                    # Keep the first three distinct actual hover frames. A
                    # successful later candidate must not erase earlier fee
                    # failures; a same-probe retry replaces its own reference.
                    if probe_x in self.scan_hovers or len(self.scan_hovers)<3:
                        self.scan_hovers[probe_x]={'scan':self.in_scan,'frame':result}
                if name=='turn.end_visible' and result and getattr(args[0],'phase',None)=='wait_our_turn':
                    self.start_turn(args[0])
                if name=='turn.think':
                    tick=dict(context,result=result,seconds=elapsed,phase_after=getattr(args[0],'phase',None),
                              budget_after=getattr(args[0],'kredits_left',None))
                    if self.active:
                        self.active['ticks'].append(tick)
                        if context['budget']!=tick['budget_after']:self.active['budget_changes'].append(tick)
                    if result=='ended_turn':self.finish_turn('voluntary_end')
                    elif result=='turn_switched':self.finish_turn('button_lost')
                if name=='scanner.scan_orange':
                    detail=getattr(args[0],'last_orange',None) or {}
                    self.sample_hover_mismatch(detail)
                    row=dict(context,scan=self.in_scan,seconds=elapsed,cache_before=cache_before,
                             cache_after=len(getattr(args[0],'orange_cache',())),
                             budget=kwargs.get('budget',args[1] if len(args)>1 else None),
                             detail={k:detail.get(k) for k in ('anchors','ocr','cached','probed','rejected','records',
                                                                  'cost_s','hover_s','identity_s','deadline','aborted')})
                    self.data['scans'].append(row);self.in_scan=old_scan
                    self.scan_hovers={}
                if name=='scanner.classify' and isinstance(result,dict):
                    row=dict(context,seconds=elapsed,probe=getattr(args[0],'_last_client',None),
                             shape=list(args[1].shape),info={k:result.get(k) for k in ('name','cost','type','printed_name',
                                    'weather_id','weather_unresolved','ocr_window','name_tier','hover_retried')})
                    self.data['classifications'].append(row)
                    if elapsed>=self.slow:self.queue_image('slow_card',args[1])
                if name=='ocr':
                    self.data['ocr'].append(dict(context,seconds=elapsed,shape=list(args[0].shape),
                                                lines=len(result or ()),parent=self.stack[-1]['name'] if self.stack else None))
        return call

    def patch(self,obj,name,label=None):
        if not hasattr(obj,name):return
        original=getattr(obj,name);wrapped=self.wrap(label or name,original)
        self.restore.append((obj,name,original));setattr(obj,name,wrapped)

    def alias(self,fn,label):
        wrapped=self.wrap(label,fn)
        for module in list(sys.modules.values()):
            path=str(getattr(module,'__file__','') or '')
            if not (path.startswith(str(ROOT/'src')) or module is campaign):continue
            for name,value in list(vars(module).items()):
                if value is fn:
                    self.restore.append((module,name,value));setattr(module,name,wrapped)

    def install(self):
        self.alias(reader._ocr,'ocr');self.alias(win.capture_client_bgr,'capture')
        for cls,names,prefix in (
            (hs.HandScannerV2,('_classify','_classify_name','_classify_core','scan_orange','find_playable','scan_fast','scan','_baseline','_hover_frame','recheck_card'),'scanner'),
            (te.TurnEngine,('think','_end_turn_visible','_field','_panel_at','_current_kredits','_kredits_now','_kredits_recheck','_judge_deploy','_resync_kredits_after_actions'),'turn'),
            (attack.Attacker,('run_turn','_watch_hp_for_drop'),'attack'),
            (attack.FrontMover,('run_turn',),'move'),
            (kredits.KreditsTracker,('read_turn_start','_wait_until_settled'),'kredits'),
            (ml.Controller,('handle_in_game','run'),'controller')):
            for name in names:
                label=prefix+'.'+name.lstrip('_')
                if cls is te.TurnEngine and name=='_end_turn_visible':label='turn.end_visible'
                self.patch(cls,name,label)
        self.patch(weather_cards,'identify','weather.identify')
        self.patch(board,'read_field','board.read_field')
        self.patch(board,'battlefield_snapshot','board.snapshot')
        self.patch(order_choice,'detect_count','selection.detect_count')
        self.patch(ml,'classify','state.classify')
        self.alias(actions.move_drag,'input.move_drag')
        self.patch(time,'sleep','sleep')
        # KreditsTracker captures sleep=time.sleep when imported, before this
        # wrapper exists. Preserve supplied custom clocks/sleep in other tools.
        original=kredits.KreditsTracker.__init__
        profiler=self
        @wraps(original)
        def init(tracker,*args,**kwargs):
            original(tracker,*args,**kwargs)
            if tracker._sleep is profiler.original_sleep:tracker._sleep=time.sleep
        self.restore.append((kredits.KreditsTracker,'__init__',original))
        kredits.KreditsTracker.__init__=init
        self.patch(SpeedController,'persist','monitor.persist')

    def flush(self,images=False):
        self.in_flush=True
        try:
            payload={k:v for k,v in self.data.items()}
            if self.active:payload['active_turn']={k:v for k,v in self.active.items() if k!='_start'}
            payload.update(updated_epoch=time.time(),image_count=self.image_count)
            temporary=self.out/'profile.tmp'
            temporary.write_text(json.dumps(payload,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
            temporary.replace(self.out/'profile.json')
            if images:
                for name,frame in self.images:cv2.imwrite(str(self.out/name),frame)
                self.images=[]
        finally:self.in_flush=False

    def uninstall(self):
        for obj,name,original in reversed(self.restore):setattr(obj,name,original)
        self.restore=[]


class SpeedController(campaign.ObservedController):
    def __init__(self,out,stats,total,profiler,flush_seconds=15,max_turns=8,classic=False):
        self.profiler=profiler;profiler.controller=self
        self.flush_seconds=flush_seconds;self.last_flush=0.0;self.max_turns=max_turns
        self.classic_strategy=classic
        super().__init__(out,stats,total)
        self.classic_strategy=classic

    def persist(self,force=False):
        now=time.perf_counter()
        if force or self.profiler.force_flush or now-self.last_flush>=self.flush_seconds:
            self.profiler.force_flush=False;self.last_flush=now
            # performance is written separately: never duplicate its expanding
            # trace into every status write performed by the base monitor.
            performance=self.stats.pop('performance',None)
            try:super().persist()
            finally:
                if performance is not None:self.stats['performance']=performance
            self.profiler.flush(images=force or self.profiler.active is None)

    def handle_in_game(self):
        super().handle_in_game()
        done=self.profiler.completed_turns()
        if self.max_turns and done>=self.max_turns:
            raise ObservationLimit(f'Observed {done} completed own turns; current game retained')

    def finish_round(self,result):
        self.profiler.finish_turn('match_result')
        super().finish_round(result)
        self.persist(force=True)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--rounds',type=int,default=5)
    ap.add_argument('--max-turns',type=int,default=8,help='0 disables; stop after completed observed own turns')
    ap.add_argument('--label',default='baseline',help='output directory label, e.g. baseline or fix')
    ap.add_argument('--resume',type=Path)
    ap.add_argument('--game-version',default='unverified')
    ap.add_argument('--mode',choices=('training','casual'),default='training',
                    help='Manually select this game mode first; ranked is never selected.')
    ap.add_argument('--classic-strategy',action='store_true',help='explicit comparison only; default is production orange strategy')
    ap.add_argument('--flush-seconds',type=float,default=15)
    ap.add_argument('--slow-method-s',type=float,default=3)
    ap.add_argument('--max-images',type=int,default=6)
    args=ap.parse_args()
    if args.rounds<1 or args.max_turns<0 or args.flush_seconds<1 or args.max_images<0:
        ap.error('rounds>=1, max-turns>=0, flush-seconds>=1 and max-images>=0 required')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,32}',args.label):ap.error('Invalid output label')
    if args.resume:
        out=args.resume.resolve();stats=json.loads((out/'status.json').read_text(encoding='utf-8-sig'))
        if stats.get('attention'):
            stats.setdefault('incidents',[]).append({'epoch':time.time(),
                'message':stats.pop('attention'),'action':'resumed after review'})
        profile=out/'profile.json'
        if profile.exists():stats['performance']=json.loads(profile.read_text(encoding='utf-8'))
        if len(stats['rounds'])>=args.rounds:raise RuntimeError('Requested match count already complete')
        if stats.get('mode')!=args.mode:raise RuntimeError('Resume mode must match the recorded campaign')
        done=sum(t.get('end_kind')!='stopped_incomplete' for t in stats.get('performance',{}).get('turns',()))
        if args.max_turns and done>=args.max_turns:
            raise RuntimeError('Requested turn count already complete; raise --max-turns to continue')
    else:
        out=ROOT/'logs'/time.strftime('pc_speed_'+args.label+'_%Y%m%d_%H%M%S')
        out.mkdir(parents=True,exist_ok=False)
        stats={'run_id':out.name,'system':'runtime-test','volume_serial':'7A77-760D',
               'game_version':args.game_version,'mode':args.mode,'target':args.rounds,
               'start_epoch':time.time(),'rounds':[],'current':None,'segments':[]}
    win.set_dpi_aware();ok,why=win.acquire_single_instance_lock()
    if not ok:raise RuntimeError(why)
    wins=win.find_by_process('kards')
    if len(wins)!=1:raise RuntimeError('Expected exactly one PC KARDS window')
    hwnd=wins[0]['hwnd'];win.set_window_client_size(hwnd,1280,720);win.bring_to_front(hwnd)
    if args.resume and stats.get('current'):actions.park_cursor(hwnd)
    ml.LOG=str(out/'events.log');ml.MODE_BTNS=(args.mode+'_mode_btn',)
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in list((ROOT/'src').glob('*.py'))+list((ROOT/'config/hand_cost_digits').glob('*'))
                     +[Path(__file__),ROOT/'config/order_plays.json',ROOT/'config/weather_variants.json',
                       ROOT/'config/app_version.json',ROOT/'card_db/kards_data.json'] if p.is_file()}
    stats['segments'].append({'start_epoch':time.time(),'hashes':hashes,'strategy':'classic' if args.classic_strategy else 'current',
                              'python':sys.version,'label':args.label})
    stats.update(status='running',minimal_shots=True)
    profiler=Profiler(out,stats,args.slow_method_s,args.max_images);profiler.install()
    controller=SpeedController(out,stats,args.rounds,profiler,args.flush_seconds,args.max_turns,args.classic_strategy)
    controller.hwnd=hwnd
    original_log=ml.log
    def log(message):
        original_log(message);controller.observe_log(message)
        if profiler.active and '窗口不可见/被遮挡' in message:profiler.active['occlusion_events']+=1
    ml.log=log
    # Routine screenshots are disabled; anomalies reuse a previously captured
    # array and are saved from the same small global image budget.
    attack.DUMP_ATTACK_FRAMES=False;te.DUMP_SCAN_FRAMES=False
    original_dump=te.TurnEngine._dump_frame;original_hp=attack.Attacker._dump_hp_bogus
    def dump_frame(engine,tag,name='',subdir='deploy_drag',cap=None):
        if tag in {'ambiguous','blocked','deploy_uncertain','cost_uncertain','drag_error','drag_failed'}:
            profiler.queue_image(tag,profiler.last_frame)
    te.TurnEngine._dump_frame=dump_frame
    attack.Attacker._dump_hp_bogus=lambda engine,frame,*a:profiler.queue_image('hp_bogus',frame)
    # Base monitor result/attention saving must also reuse existing frames.
    controller.save_frame=lambda tag,frame=None:profiler.queue_image(tag,frame if frame is not None else profiler.last_frame)
    print('SPEED_STATUS='+str(out/'status.json'),flush=True)
    print('SPEED_PROFILE='+str(out/'profile.json'),flush=True)
    try:
        controller.run()
        stats['status']='completed' if len(stats['rounds'])==args.rounds else 'stopped_incomplete'
    except ObservationLimit as error:stats.update(status='stopped_max_turns',attention=str(error))
    except campaign.Attention as error:stats.update(status='attention',attention=str(error))
    except KeyboardInterrupt:stats['status']='interrupted'
    except Exception:stats.update(status='error',exception=traceback.format_exc());original_log(stats['exception'])
    finally:
        if profiler.active:profiler.finish_turn('stopped_incomplete')
        stats['segments'][-1]['end_epoch']=time.time();controller.persist(force=True)
        ml.log=original_log;te.TurnEngine._dump_frame=original_dump;attack.Attacker._dump_hp_bogus=original_hp
        profiler.uninstall()
    print('SPEED_END '+stats['status'],flush=True)
    return 1 if stats['status']=='error' else 0


if __name__=='__main__':raise SystemExit(main())
