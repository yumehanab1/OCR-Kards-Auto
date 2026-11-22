"""Offline emulator GUI integration: python/python.exe -B dev/gui_emu_test.py -v."""
from pathlib import Path
from types import SimpleNamespace
import inspect
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import gui
import emu_manager


class NativeTrap:
    def __dir__(self):
        raise AssertionError("Native manager must never be reflected")


class GuiEmuTests(unittest.TestCase):
    def setUp(self):
        # Inherit the parent's ACL for Windows restricted-token test runs.
        self.root = Path(tempfile.gettempdir()) / ("gui-emu-test-" + uuid.uuid4().hex)
        self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root)
        patcher = patch.object(gui, "PROJECT_ROOT", str(self.root))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.api = gui.Api()
        self.mgr = Mock(spec=emu_manager.EmuManager)
        self.mgr.has_running_workers.return_value = False
        factory = patch.object(emu_manager, "EmuManager", return_value=self.mgr)
        self.factory = factory.start()
        self.addCleanup(factory.stop)

    def tearDown(self):
        self.assertFalse((self.root / "config/gui_options.json").exists())

    def test_lazy_bridge_methods_only_and_exact_pc_signatures(self):
        self.factory.assert_not_called()
        self.api._emu_manager = self.api.window = self.api.proc = NativeTrap()
        bridge = gui.make_js_api(self.api)
        self.assertEqual(set(vars(bridge)), set(gui.JS_API_METHODS))
        self.assertTrue({"emu_snapshot", "emu_save_options", "emu_start", "emu_stop", "emu_control"}
                        <= set(vars(bridge)))
        self.assertTrue(all(inspect.ismethod(v) and v.__self__ is self.api for v in vars(bridge).values()))
        from webview.util import inject_pywebview
        scripts, loaded = [], threading.Event()
        window = SimpleNamespace(_js_api=bridge, _functions={}, _expose_lock=threading.Lock(),
                                 run_js=scripts.append,
                                 events=SimpleNamespace(before_load=threading.Event(),
                                     _pywebviewready=threading.Event(), loaded=loaded))
        with patch("webview.util.load_js_files", return_value=("", "%(functions)s")):
            inject_pywebview("edgechromium", window)
            self.assertTrue(loaded.wait(3), "NativeTrap bridge initialization timed out")
        self.assertEqual({m["func"] for m in json.loads(scripts[-1])}, set(gui.JS_API_METHODS))
        for name, params in {"snapshot": ["only_key", "tail", "since_rev"],
                             "start": ["opts"], "stop": [], "save_settings": ["opts"]}.items():
            self.assertEqual(list(inspect.signature(getattr(bridge, name)).parameters), params)

    def test_save_options_normalizes_without_pc_file(self):
        result = self.api.emu_save_options({"mode": "casual", "extra_serials": ["a", "a"]})
        self.assertTrue(result["ok"])
        self.assertEqual(result["options"]["extra_serials"], ["a"])
        path = self.root / "config/emu_options.json"
        before = path.read_bytes()
        self.assertFalse(self.api.emu_save_options({"max_rounds": 100})["ok"])
        self.assertEqual(path.read_bytes(), before)
        self.factory.assert_not_called()

    def test_existing_pc_options_are_untouched(self):
        path = self.root / "config/gui_options.json"
        path.parent.mkdir()
        before = b'{"max_rounds":7}\r\n'
        path.write_bytes(before)
        try:
            self.assertTrue(self.api.emu_save_options({"max_rounds": 9})["ok"])
            self.assertEqual(path.read_bytes(), before)
        finally:
            path.unlink()

    def test_wave3_options_roundtrip_and_invalid_values(self):
        options = dict(shared_ocr=False, watchdog_seconds=3600, daily_max_rounds=999,
                       daily_max_minutes=1440, jitter_ratio=.5,
                       instance_overrides={'ldplayer:2': dict(mode='casual', deck_name='日本',
                           max_rounds=0, daily_max_rounds=10, daily_max_minutes=60, allow_attack=False)})
        saved = self.api.emu_save_options(options)
        self.assertTrue(saved['ok'])
        self.assertEqual(emu_manager.load_emu_options(self.root), saved['options'])
        for key, value in options.items():
            self.assertEqual(saved['options'][key], value)
        for key, value in [('shared_ocr', 'yes'), ('watchdog_seconds', 3601),
                           ('daily_max_rounds', 1000), ('daily_max_minutes', 1441),
                           ('jitter_ratio', .51), ('watchdog_seconds', 1.5),
                           ('instance_overrides', {'adb:x': {'max_rounds': 100}})]:
            self.assertFalse(self.api.emu_save_options({**options, key: value})['ok'])
            self.assertEqual(emu_manager.load_emu_options(self.root), saved['options'])

    def test_selftest_wave3_metadata(self):
        # Run the real entry point; redirect its report to the isolated test root.
        with patch.object(sys, 'argv', ['gui.py', '--selftest']), \
                patch.object(gui, 'LOG_DIR', str(self.root / 'logs')):
            self.assertEqual(gui.main(), 0)
        report = json.loads((self.root / 'logs/gui_selftest.txt').read_text(encoding='utf-8'))
        self.assertEqual(report['yield_to_user'], dict(available=True, default=True, flag='--yield-to-user'))
        self.assertEqual(report['emulator_multi_instance']['providers'], ['mumu', 'ldplayer', 'bluestacks', 'adb'])

    def test_yield_stop_uses_cooperative_marker(self):
        self.api.proc = Mock(returncode=0)
        self.api.proc.poll.side_effect = [None, 0]
        self.api.last_opts = {'yield_to_user': True, 'message_input': False}
        self.api._stop_file = str(self.root / 'yield.stop')
        self.assertTrue(self.api.stop()['ok'])
        self.assertEqual((self.root / 'yield.stop').read_text(), 'stop\n')
        self.api.proc.terminate.assert_not_called()
        self.api.proc.kill.assert_not_called()

    def test_gui_yield_launch_opt_in_and_legacy_bridge(self):
        script = self.root / 'main_loop.py'
        script.write_text('# test fixture', encoding='utf-8')
        with patch.object(gui, 'MAIN_LOOP', str(script)), \
                patch.object(gui, 'LOG_DIR', str(self.root / 'logs')), \
                patch.object(gui, 'GUI_RUN_LOG', str(self.root / 'logs/run.log')), \
                patch.object(gui, 'engine_python', return_value=sys.executable), \
                patch.object(gui.time, 'sleep'), patch.object(gui.subprocess, 'Popen') as launch:
            child = launch.return_value
            child.poll.return_value = None
            child.pid = 42
            try:
                self.assertTrue(self.api.start({'play': True, 'yield_to_user': True})['ok'])
                self.assertIn('--yield-to-user', launch.call_args.args[0])
                self.assertEqual(launch.call_args.kwargs['env']['KARDS_AUTO_STOP_FILE'], self.api._stop_file)
                self.assertFalse(Path(self.api._stop_file).exists())
                self.api.proc = None
                self.assertTrue(self.api.start({'play': True})['ok'])
                self.assertNotIn('--yield-to-user', launch.call_args.args[0])
                self.assertNotIn('KARDS_AUTO_STOP_FILE', launch.call_args.kwargs['env'])
            finally:
                self.api._close_run_log()
                (self.root / 'config/gui_options.json').unlink(missing_ok=True)

    def test_snapshot_marks_log_and_passes_revision(self):
        original = {"instances": [], "running_count": 0, "options": {},
                    "log": {"changed": True, "rev": "r2", "lines": ["state -> own_turn", "our turn starts"]}}
        self.mgr.snapshot.return_value = original
        result = self.api.emu_snapshot("mumu:7", "r1")
        self.mgr.snapshot.assert_called_once_with(selected_log_id="mumu:7", log_since_rev="r1")
        self.assertEqual(result["log"]["log_lines"], [["state", "state -> own_turn"], ["turn", "our turn starts"]])
        self.assertNotIn("log_lines", original["log"])
        self.assertEqual(self.factory.call_args.args, (str(self.root),))
        self.assertEqual(self.factory.call_args.kwargs, {"python_exe": sys.executable})
        self.api.emu_snapshot()
        self.factory.assert_called_once()
        self.mgr.snapshot.return_value = {"log": {"changed": False, "rev": "r2", "lines": []}}
        self.assertEqual(self.api.emu_snapshot("mumu:7", "r2")["log"]["log_lines"], [])

    def test_rebind_root_without_orphaning_worker(self):
        self.api._get_emu_manager()
        with patch.object(gui, "PROJECT_ROOT", str(self.root / "other")):
            self.mgr.has_running_workers.return_value = True
            with self.assertRaises(RuntimeError):
                self.api._get_emu_manager()
            self.factory.assert_called_once()
            self.mgr.has_running_workers.return_value = False
            self.api._get_emu_manager()
            self.assertEqual(self.factory.call_count, 2)

    def test_start_saves_before_delegation_and_returns_partial_results(self):
        def start(ids, opts):
            saved = json.loads((self.root / "config/emu_options.json").read_text(encoding="utf-8"))
            self.assertEqual(opts, saved)
            return {"ok": True, "started": [ids[0]], "failed": [ids[1]],
                    "results": {ids[0]: {"ok": True}, ids[1]: {"ok": False}}}
        self.mgr.start_many.side_effect = start
        result = self.api.emu_start(["mumu:7", "adb:test"], {"mode": "training"})
        self.assertEqual(result["started"], ["mumu:7"])
        self.assertEqual(result["failed"], ["adb:test"])
        self.assertIn("msg", result)
        self.assertEqual(self.mgr.start_many.call_args.kwargs["opts"]["mode"], "training")

    def test_start_update_gate_and_invalid_options(self):
        for phase in ("preparing", "closing", "recovery"):
            self.api._update_state = {"phase": phase}
            self.assertFalse(self.api.emu_start(["mumu:7"], {})["ok"])
        self.factory.assert_not_called()
        self.api._update_state = {}
        self.assertFalse(self.api.emu_start(["mumu:7"], {"mode": "invalid"})["ok"])
        self.factory.assert_not_called()

    def test_stop_all_and_selected(self):
        self.assertEqual(self.api.emu_stop()["stopped"], [])
        self.factory.assert_not_called()
        self.api._get_emu_manager()
        self.mgr.stop_all.return_value = {"ok": True, "stopped": ["mumu:7"]}
        self.assertEqual(self.api.emu_stop()["stopped"], ["mumu:7"])
        self.api.emu_stop([])
        self.assertEqual(self.mgr.stop_all.call_count, 2)
        self.mgr.stop_instance.return_value = {"ok": True}
        self.assertEqual(self.api.emu_stop(["mumu:7", "mumu:7"])["stopped"], ["mumu:7"])
        self.mgr.stop_instance.assert_called_once_with("mumu:7")

    def test_control_whitelist(self):
        self.assertFalse(self.api.emu_control("mumu:7", "__dict__")["ok"])
        self.factory.assert_not_called()
        for action, method in (("launch", "launch_emulator"), ("shutdown", "shutdown_emulator")):
            getattr(self.mgr, method).return_value = {"ok": True}
            self.assertTrue(self.api.emu_control("mumu:7", action)["ok"])
            getattr(self.mgr, method).assert_called_once_with("mumu:7")

    def test_update_refuses_running_workers(self):
        self.api._get_emu_manager()
        self.mgr.has_running_workers.return_value = True
        result = self.api.install_update()
        self.assertFalse(result["ok"])
        self.assertEqual(result["msg"], "请先停止自动对局，再应用更新")

    def test_html_preserves_pc_and_adds_emu_ids(self):
        ids = re.findall(r'id="([^"]+)"', gui.HTML)
        self.assertEqual(len(ids), len(set(ids)))
        pc = {"ver", "btnUpdate", "btnApplyUpdate", "btnRelease", "switches", "rounds",
              "saveStatus", "btnStart", "btnStop", "pill", "pilltxt", "stSub", "elapsed",
              "stKre", "stBoard", "stAct", "stIssues", "stState", "stRounds", "stArgv",
              "btnKey", "btnBottom", "log", "logtag", "toast", "settings-title",
              "overview-title", "journal-title"}
        emu = {"pcView", "emuView", "tabPc", "tabEmu", "emuMode", "emuDeck", "emuRounds",
               "emuStagger", "emuPreferIpc", "emuDeploy", "emuAttack", "emuEndTurn",
               "emuAutoLaunch", "emuDryRun", "emuExtraSerials", "btnEmuRefresh",
               "btnEmuStartSel", "btnEmuStopAll", "emuLog", "emuLogTag"}
        emu |= {'emuSharedOcr', 'emuWatchdog', 'emuDailyRounds', 'emuDailyMinutes', 'emuJitter', 'emuAdvBox'}
        self.assertTrue(pc | emu <= set(ids))
        self.assertIn('<main id="emuView" style="display:none">', gui.HTML)
        for token in ("--bg:#141416", "--panel:#222225", "--iris:#ac9af7"):
            self.assertIn(token, gui.HTML)

    @unittest.skipUnless(shutil.which("node"), "Node is needed for DOM interaction tests")
    def test_frontend_interactions_and_log_revision_races(self):
        script = gui.HTML.split("<script>", 1)[1].split("</script>", 1)[0]
        harness = r"""
const assert=require('node:assert/strict'), vm=require('node:vm');
const payload=JSON.parse(require('node:fs').readFileSync(0,'utf8')), source=payload.script;
class Element {
 constructor(tag='div'){this.tagName=tag;this.value='';this.checked=false;this.disabled=false;this.style={};this.children=[];this.events={};this.attrs={};this.textContent='';this.scrollHeight=300;this.clientHeight=100;this.scrollTop=0;this.open=false;}
 append(...items){for(const i of items){if(i.tagName==='fragment'){this.append(...[...i.children]);continue;} if(i.parentNode)i.parentNode.children=i.parentNode.children.filter(c=>c!==i);i.parentNode=this;this.children.push(i);}}
 appendChild(item){this.append(item);return item;}
 replaceChildren(...items){for(const c of this.children)c.parentNode=null;this.children=[];this.append(...items);}
 get childElementCount(){return this.children.length;}
 querySelector(s){return this.querySelectorAll(s)[0] || null;}
 querySelectorAll(s){return descendants(this).filter(e=>s.startsWith('#')?e.id===s.slice(1):e.tagName===s);}
 addEventListener(name,fn){this.events[name]=fn;}
 setAttribute(k,v){this.attrs[k]=v;}
}
function descendants(e){return e.children.flatMap(c=>[c,...descendants(c)]);}
const elements={}, listeners=[], calls=[];
global.document={querySelector:s=>Object.values(elements).flatMap(e=>[e,...descendants(e)]).find(e=>'#'+e.id===s) || (elements[s]??=new Element()),
 querySelectorAll:s=>s.split(',').flatMap(part=>{const [root,tag]=part.trim().split(' ');return document.querySelector(root).querySelectorAll(tag);}),
 createElement:t=>new Element(t),createDocumentFragment:()=>new Element('fragment'),createTextNode:t=>Object.assign(new Element('text'),{textContent:t})};
global.setInterval=()=>0;
global.window={addEventListener:(name,fn)=>listeners.push(fn),confirm:()=>false};
const options={mode:'training',deck_name:'',max_rounds:3,stagger_seconds:1.5,extra_serials:[],selected_instances:['mumu:7'],prefer_ipc:true,allow_deploy:true,allow_attack:true,allow_end_turn:true,auto_launch_kards:true,dry_run:false,
 shared_ocr:true,watchdog_seconds:240,daily_max_rounds:8,daily_max_minutes:90,jitter_ratio:.15,
 instance_overrides:{'mumu:7':{deck_name:'日本',allow_attack:false},'adb:other':{mode:'casual'}}};
const instance={instance_id:'mumu:7',name:'MuMu 7',provider:'mumu',android_version:'15',running:true,ipc_available:true,worker_running:true,worker_state:'own_turn',rounds_done:2,victories:1,defeats:1,avg_capture_ms:6,daily_rounds:3,daily_minutes:12.5};
let pending=null, saveFails=false;
window.pywebview={api:{
 emu_snapshot:async(id,rev)=>{calls.push(['snapshot',id,rev]);if(pending)return await pending;return {options,instances:[instance],running_count:1,shared_ocr_running:true,log:{changed:rev!=='r1',rev:'r1',log_lines:[['state','state -> own_turn']]}};},
 emu_save_options:async(o)=>{calls.push(['save',o]);return {ok:!saveFails,msg:saveFails?'save failed':'saved'};},
 emu_start:async(ids,o)=>{calls.push(['start',ids,o]);return {ok:true,msg:'started'};},
 emu_stop:async(ids)=>{calls.push(['stop',ids]);return {ok:true,msg:'stopped'};}
}};
vm.runInThisContext(source);
// Toast animation is outside this DOM harness.
toast=()=>{};
(async()=>{
 listeners.at(-1)();
 renderSwitches(payload.switches,payload.pcOptions);
 const drawer=document.querySelector('#switches').children.find(e=>e.tagName==='details');
 assert.ok(drawer.className.includes('adv-switches')); assert.equal(drawer.open,false);
 assert.ok(drawer.querySelector('#sw_message_input'));
 assert.equal(document.querySelector('#sw_yield_to_user').checked,true);
 assert.equal(collectOptions().message_input,false);
 lockOptionControls(true); assert.equal(document.querySelector('#sw_message_input').disabled,true);
 lockOptionControls(false);
 document.querySelector('#btnJumpEmu').onclick();
 assert.equal(document.querySelector('#emuView').style.display,'');
 await new Promise(setImmediate);
 await emuPoll(true);
 assert.equal(document.querySelector('#tabEmu').textContent,'模拟器多开 (1)');
 assert.equal(document.querySelector('#emuFields').disabled,false);
 assert.match(document.querySelector('#emuCount').textContent,/共享OCR运行中/);
 assert.deepEqual(emuCollect().instance_overrides,options.instance_overrides);
 for(const [id,key] of [['emuSharedOcr','shared_ocr'],['emuWatchdog','watchdog_seconds'],['emuDailyRounds','daily_max_rounds'],['emuDailyMinutes','daily_max_minutes'],['emuJitter','jitter_ratio']]){
   assert.equal(emuCollect()[key],options[key]);
 }
 function textTree(e){return [e.textContent,...e.children.map(textTree)].join(' ');}
 assert.match(textTree(document.querySelector('#emuInstances')),/今日 3局 \/ 12.5分/);
 assert.match(textTree(document.querySelector('#emuInstances')),/已自定义/);
 for(const [provider,label] of [['mumu','MuMu'],['ldplayer','雷电'],['bluestacks','蓝叠'],['adb','ADB']]){
   emuRenderInstances([{...instance,provider}]); assert.ok(textTree(document.querySelector('#emuInstances')).includes(label));
 }
 const edit=descendants(document.querySelector('#emuInstances')).find(e=>e.textContent==='独立配置'); edit.onclick();
 const editor=emuEditors.get('mumu:7'), panel=editor.panel;
 assert.equal(panel.hidden,false);
 editor.fields.deck_name.value='英国'; editor.fields.mode.value='ranked'; editor.fields.mode.onchange();
 assert.equal(editor.fields.mode.value,'');
 editor.fields.mode.value='casual'; editor.fields.max_rounds.value='0';
 editor.fields.daily_max_rounds.value='15'; editor.fields.daily_max_minutes.value='120';
 emuRenderInstances([{...instance,rounds_done:4}]);
 assert.equal(emuEditors.get('mumu:7').panel,panel); assert.equal(editor.fields.deck_name.value,'英国');
 editor.fields.max_rounds.value='100';
 const savesBefore=calls.filter(c=>c[0]==='save').length;
 await emuSaveOverride('mumu:7'); assert.equal(calls.filter(c=>c[0]==='save').length,savesBefore);
 editor.fields.max_rounds.value='0'; saveFails=true;
 await emuSaveOverride('mumu:7'); await new Promise(setImmediate);
 assert.equal(emuOverrides['mumu:7'].deck_name,'日本'); assert.equal(panel.hidden,false);
 saveFails=false;
 await emuSaveOverride('mumu:7'); await new Promise(setImmediate);
 assert.deepEqual(emuOverrides['mumu:7'],{deck_name:'英国',allow_attack:false,mode:'casual',max_rounds:0,daily_max_rounds:15,daily_max_minutes:120});
 assert.deepEqual(emuOverrides['adb:other'],{mode:'casual'}); assert.equal(panel.hidden,true);
 document.querySelector('#emuSharedOcr').checked=false;
 document.querySelector('#emuWatchdog').value='300'; document.querySelector('#emuDailyRounds').value='25';
 document.querySelector('#emuDailyMinutes').value='180'; document.querySelector('#emuJitter').value='.25';
 emuPersist(); await emuSaveQueue;
 const saved=calls.filter(c=>c[0]==='save').at(-1)[1];
 assert.equal(saved.shared_ocr,false); assert.equal(saved.watchdog_seconds,300);
 assert.equal(saved.daily_max_rounds,25); assert.equal(saved.daily_max_minutes,180); assert.equal(saved.jitter_ratio,.25);
 assert.deepEqual(saved.instance_overrides,emuOverrides);
 for(const [id,bad] of [['emuWatchdog','3601'],['emuWatchdog','1.5'],['emuDailyRounds','1000'],['emuDailyMinutes','1441'],['emuJitter','.51'],['emuJitter',''],['emuRounds','-1'],['emuStagger','NaN']]){
   const el=document.querySelector('#'+id), old=el.value; el.value=bad; assert.equal(emuValid(),false,id+bad); el.value=old;
 }
 assert.equal(emuValid(),true);
 await emuSaveOverride('mumu:7',true); await new Promise(setImmediate);
 assert.equal(emuOverrides['mumu:7'],undefined); assert.deepEqual(emuOverrides['adb:other'],{mode:'casual'});
 document.querySelector('#tabEmu').onclick(); await new Promise(setImmediate);
 assert.equal(document.querySelector('#pcView').style.display,'none');
 assert.equal(document.querySelector('#emuView').style.display,'');
 emuChooseLog('mumu:7'); await new Promise(setImmediate);
 assert.equal(emuLogRev,'r1');
 const logChildren=document.querySelector('#emuLog').children;
 await emuPoll(true);
 assert.equal(document.querySelector('#emuLog').children,logChildren);
 assert.deepEqual(calls.at(-1),['snapshot','mumu:7','r1']);
 document.querySelector('#emuExtraSerials').value='127.0.0.1:5555, 127.0.0.1:5557';
 document.querySelector('#emuMode').value='ranked';
 // Give the mock target the same ID as the browser element, then confirm cancellation.
 document.querySelector('#emuMode').id='emuMode';
 document.querySelector('#emuFields').events.change({target:document.querySelector('#emuMode')});
 assert.equal(document.querySelector('#emuMode').value,'training');
 await emuSaveQueue;
 await document.querySelector('#btnEmuStartSel').onclick();
 const start=calls.find(c=>c[0]==='start');
 assert.deepEqual(start[1],['mumu:7']);
 assert.deepEqual(start[2].extra_serials,['127.0.0.1:5555','127.0.0.1:5557']);
 assert.equal(start[2].mode,'training');
 document.querySelector('#emuRounds').value='100';
 assert.equal((await emuStart(['mumu:7'])).ok,false);
 assert.equal(calls.filter(c=>c[0]==='start').length,1);
 await document.querySelector('#btnEmuStopAll').onclick();
 assert.ok(calls.some(c=>c[0]==='stop'));
 await new Promise(setImmediate);
 let resolve;
 pending=new Promise(r=>resolve=r);
 const request=emuPoll(true), count=calls.length;
 await emuPoll(true); assert.equal(calls.length,count);
 emuChooseLog('adb:other');
 resolve({options,instances:[instance],running_count:1,log:{changed:true,rev:'stale',log_lines:[['bad','wrong instance']]}});
 await request; pending=null;
 assert.equal(emuLogRev,'');
 assert.equal(document.querySelector('#emuLog').children.length,0);
 document.querySelector('#tabPc').onclick();
 assert.equal(document.querySelector('#emuView').style.display,'none');
 const before=calls.length; await emuPoll(); assert.equal(calls.length,before);
 console.log('Frontend interactions, independent polling and stale-log guard passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
        result = subprocess.run([shutil.which("node"), "-e", harness], input=json.dumps({
            'script': script, 'switches': gui.SWITCHES, 'pcOptions': gui.normalize_options({})}),
                                text=True, encoding="utf-8", capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
