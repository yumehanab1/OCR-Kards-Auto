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
        self.assertTrue(pc | emu <= set(ids))
        self.assertIn('<main id="emuView" style="display:none">', gui.HTML)
        for token in ("--bg:#141416", "--panel:#222225", "--iris:#ac9af7"):
            self.assertIn(token, gui.HTML)

    @unittest.skipUnless(shutil.which("node"), "Node is needed for DOM interaction tests")
    def test_frontend_interactions_and_log_revision_races(self):
        script = gui.HTML.split("<script>", 1)[1].split("</script>", 1)[0]
        harness = r"""
const assert=require('node:assert/strict'), vm=require('node:vm');
const source=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
class Element {
 constructor(){this.value='';this.checked=false;this.disabled=false;this.style={};this.children=[];this.events={};this.attrs={};this.textContent='';this.scrollHeight=300;this.clientHeight=100;this.scrollTop=0;}
 append(...items){this.children.push(...items);}
 replaceChildren(...items){this.children=items;}
 addEventListener(name,fn){this.events[name]=fn;}
 setAttribute(k,v){this.attrs[k]=v;}
}
const elements={}, listeners=[], calls=[];
global.document={querySelector:s=>elements[s]??=new Element(),querySelectorAll:()=>[],
 createElement:()=>new Element(),createDocumentFragment:()=>new Element(),createTextNode:t=>t};
global.setInterval=()=>0;
global.window={addEventListener:(name,fn)=>listeners.push(fn),confirm:()=>false};
const options={mode:'training',deck_name:'',max_rounds:3,stagger_seconds:1.5,extra_serials:[],selected_instances:['mumu:7'],prefer_ipc:true,allow_deploy:true,allow_attack:true,allow_end_turn:true,auto_launch_kards:true,dry_run:false};
const instance={instance_id:'mumu:7',name:'MuMu 7',provider:'mumu',android_version:'15',running:true,ipc_available:true,worker_running:true,worker_state:'own_turn',rounds_done:2,victories:1,defeats:1,avg_capture_ms:6};
let pending=null;
window.pywebview={api:{
 emu_snapshot:async(id,rev)=>{calls.push(['snapshot',id,rev]);if(pending)return await pending;return {options,instances:[instance],running_count:1,log:{changed:rev!=='r1',rev:'r1',log_lines:[['state','state -> own_turn']]}};},
 emu_save_options:async(o)=>{calls.push(['save',o]);return {ok:true,msg:'saved'};},
 emu_start:async(ids,o)=>{calls.push(['start',ids,o]);return {ok:true,msg:'started'};},
 emu_stop:async(ids)=>{calls.push(['stop',ids]);return {ok:true,msg:'stopped'};}
}};
vm.runInThisContext(source);
// Toast animation is outside this DOM harness.
toast=()=>{};
(async()=>{
 listeners.at(-1)();
 await emuPoll(true);
 assert.equal(document.querySelector('#tabEmu').textContent,'模拟器多开 (1)');
 assert.equal(document.querySelector('#emuFields').disabled,false);
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
        result = subprocess.run([shutil.which("node"), "-e", harness], input=json.dumps(script),
                                text=True, encoding="utf-8", capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
