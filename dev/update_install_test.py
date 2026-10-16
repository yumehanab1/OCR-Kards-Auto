"""File update transactions and HTTPS range ZIP replay; no game/window input."""
from pathlib import Path
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
import update_install as ui
import gui


def meta(data): return {'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}


class Response(io.BytesIO):
    def __init__(self, data, status=200, headers=None):
        super().__init__(data); self.status=status; self.headers=headers or {}
    def geturl(self): return 'https://example.com/download'


class Fixture:
    def __init__(self, root, mode='range', corrupt=False):
        self.root=root; self.mode=mode; self.requests=[]
        self.files={'src/a.txt': b'new A', 'src/b.txt': b'new B',
                    'config/app_version.json': b'{"version":"0.3.0"}',
                    'python/unchanged.bin': os.urandom(500000),
                    'config/gui_options.json': b'remote settings',
                    'config/card_hashes.json': b'remote learned data',
                    'mobile/source.txt': b'mobile'}
        self.manifest={'schema':1,'version':'0.3.0','files':{k:meta(v) for k,v in self.files.items()}}
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
            for k,v in self.files.items(): z.writestr('package/'+k,b'WRONG' if corrupt and k=='src/a.txt' else v)
        self.zip=buf.getvalue(); self.raw=json.dumps(self.manifest).encode()
        self.release={'remote':'0.3.0','asset':{'name':'kards-auto_v0.3.0_x86_64.zip',
                     'browser_download_url':'https://example.com/package.zip','size':len(self.zip),
                     'digest':'sha256:'+hashlib.sha256(self.zip).hexdigest()},
                     'manifest_asset':{'name':'kards-auto_v0.3.0_x86_64.manifest.json',
                     'browser_download_url':'https://example.com/manifest.json'}}
        self.put('src/a.txt',b'old A'); self.put('src/b.txt',b'old B')
        self.put('config/app_version.json',b'{"version":"0.2.1"}')
        self.put('python/unchanged.bin',self.files['python/unchanged.bin'])
        self.put('config/gui_options.json',b'my settings')
        self.put('config/card_hashes.json',b'my learned data')
        self.put('mobile/source.txt',b'my mobile'); self.put('src/unlisted.txt',b'keep extra')
    def put(self,rel,data):
        p=self.root/rel; p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    def opener(self,req,timeout):
        if req.full_url.endswith('manifest.json'): return Response(self.raw)
        self.requests.append(req.headers.get('Range'))
        if self.mode=='fail': raise OSError('network interrupted')
        if self.mode=='full': return Response(self.zip)
        begin,end=map(int,req.headers['Range'][6:].split('-'))
        data=self.zip[begin:end+1]
        if self.mode=='truncated': data=data[:-1]
        return Response(data,206,{'Content-Range':f'bytes {begin}-{end}/{len(self.zip)}'})
    def stage(self): return ui.stage_update(self.root,self.release,opener=self.opener)


class Updates(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
    def tearDown(self): self.temp.cleanup()
    def unchanged(self, f):
        self.assertEqual((self.root/'python/unchanged.bin').read_bytes(),f.files['python/unchanged.bin'])
        self.assertEqual((self.root/'config/gui_options.json').read_bytes(),b'my settings')
        self.assertEqual((self.root/'config/card_hashes.json').read_bytes(),b'my learned data')
        self.assertEqual((self.root/'mobile/source.txt').read_bytes(),b'my mobile')
        self.assertEqual((self.root/'src/unlisted.txt').read_bytes(),b'keep extra')
    def test_range_only_changed_and_new(self):
        f=Fixture(self.root); (self.root/'src/b.txt').unlink()
        before=(self.root/'python/unchanged.bin').stat().st_mtime_ns
        job=f.stage(); plan=json.loads((job/'plan.json').read_text())
        self.assertLess(plan['downloaded_bytes'],len(f.zip)*.4)
        self.assertEqual(plan['download_mode'],'range')
        self.assertEqual((self.root/'src/a.txt').read_bytes(),b'old A')
        self.assertTrue(ui.apply_job(job)['ok'])
        self.assertEqual((self.root/'src/a.txt').read_bytes(),b'new A')
        self.assertEqual((self.root/'src/b.txt').read_bytes(),b'new B')
        self.assertEqual((self.root/'python/unchanged.bin').stat().st_mtime_ns,before)
        self.unchanged(f)
        self.assertEqual(ui.latest_status(self.root)['status'],'completed')
    def test_full_fallback_once(self):
        f=Fixture(self.root,'full'); job=f.stage()
        self.assertEqual(len(f.requests),1)
        self.assertEqual(json.loads((job/'plan.json').read_text())['download_mode'],'full')
        self.assertTrue(ui.apply_job(job)['ok']); self.unchanged(f)
    def test_network_truncation_hash_fail_leave_old(self):
        for mode,corrupt in [('fail',False),('truncated',False),('range',True)]:
            with self.subTest(mode=mode,corrupt=corrupt):
                f=Fixture(self.root,mode,corrupt)
                with self.assertRaises((OSError,ValueError,zipfile.BadZipFile)): f.stage()
                self.assertEqual((self.root/'src/a.txt').read_bytes(),b'old A')
                self.unchanged(f)
    def test_locked_file_rolls_back_prior_replacements(self):
        f=Fixture(self.root);job=f.stage(); replace=ui.os.replace
        def locked(src,dst):
            if Path(dst)==self.root/'src/b.txt' and '.update-' in str(src):
                raise PermissionError('locked file')
            return replace(src,dst)
        with patch.object(ui.os,'replace',side_effect=locked): r=ui.apply_job(job)
        self.assertEqual(r['status'],'rolled_back')
        self.assertEqual((self.root/'src/a.txt').read_bytes(),b'old A')
        self.assertEqual((self.root/'config/app_version.json').read_bytes(),b'{"version":"0.2.1"}')
        self.unchanged(f)
    def test_local_changed_after_detection_kept(self):
        f=Fixture(self.root);job=f.stage();f.put('src/b.txt',b'edited after check')
        r=ui.apply_job(job);self.assertFalse(r['ok'])
        self.assertEqual((self.root/'src/b.txt').read_bytes(),b'edited after check')
        self.assertEqual((self.root/'src/a.txt').read_bytes(),b'old A')
    def test_crash_recovery_journal(self):
        f=Fixture(self.root);job=f.stage();replace=ui.os.replace
        def crash(src,dst):
            result=replace(src,dst)
            if Path(dst)==self.root/'src/a.txt' and '.update-' in str(src): raise KeyboardInterrupt()
            return result
        with patch.object(ui.os,'replace',side_effect=crash):
            with self.assertRaises(KeyboardInterrupt):ui.apply_job(job)
        self.assertEqual(ui.latest_status(self.root)['phase'],'recovery')
        with self.assertRaises(RuntimeError):f.stage()
        self.assertTrue(ui.recover_job(job)['ok'])
        self.assertEqual((self.root/'src/a.txt').read_bytes(),b'old A')
    def test_paths_and_manifest_version(self):
        for path in ('../a','C:/a','a:b','/a','a\\b','a/CON.txt','a/foo.','a//b'):
            with self.subTest(path=path),self.assertRaises(ValueError):ui.relative(path)
        f=Fixture(self.root);f.manifest['version']='9.9.9';f.raw=json.dumps(f.manifest).encode()
        with self.assertRaises(ValueError):f.stage()
    def test_mobile_asset_rejected(self):
        f=Fixture(self.root);f.release['asset']['name']='KARDS-AUTO-Mobile-v0.3.0.zip'
        with self.assertRaises(ValueError):f.stage()
    @unittest.skipUnless(os.name=='nt','Windows mutex')
    def test_engine_mutex_and_parent_wait(self):
        with ui.engine_guard():
            with self.assertRaises(RuntimeError):
                with ui.engine_guard():pass
            code = '''import ctypes
k=ctypes.WinDLL('kernel32',use_last_error=True)
k.CreateMutexW.restype=ctypes.c_void_p
k.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_wchar_p]
k.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint32]
print(k.WaitForSingleObject(k.CreateMutexW(None,True,'kards_auto_main_loop'),0))'''
            got=subprocess.check_output([sys.executable,'-c',code],text=True).strip()
            self.assertEqual(got,'258')
        parent=subprocess.Popen([sys.executable,'-c','import time;time.sleep(.4)'])
        ui.wait_parent(parent.pid,5);parent.wait(timeout=5)
    @unittest.skipUnless(os.name=='nt','Windows helper')
    def test_real_detached_helper_wait_apply_restart(self):
        f=Fixture(self.root);job=f.stage()
        shutil.copy2(Path(ui.__file__),self.root/'src/update_install.py')
        marker=self.root/'restarted.txt'
        parent=subprocess.Popen([sys.executable,'-c','import time;time.sleep(.8)'])
        command=[sys.executable,'-c',f'import os;from pathlib import Path;Path({str(marker)!r}).write_text(str(os.getpid()))']
        helper=ui.launch_helper(job,sys.executable,parent.pid,{'argv':command,'cwd':str(self.root)})
        self.assertEqual(helper.wait(timeout=15),0);parent.wait(timeout=5)
        for _ in range(30):
            if marker.exists():break
            time.sleep(.1)
        self.assertTrue(marker.exists())
        # The restart marker is written before Python exits. Wait for that
        # process too, otherwise its cwd can still lock the temporary root.
        ui.wait_parent(int(marker.read_text()), 5)
        self.assertEqual((self.root/'src/a.txt').read_bytes(),b'new A')
    def test_gui_blocks_running_engine_and_duplicate_update(self):
        api=gui.Api(); api.proc=type('Proc',(),{'poll':lambda self:None})()
        self.assertFalse(api.install_update()['ok'])
        api.proc=None;api.window=object();api._update_release={};api._update_state={'phase':'recovery'}
        api._update_lock.acquire()
        try:self.assertFalse(api.install_update()['ok'])
        finally:api._update_lock.release()
    def test_same_version_revision_requires_installed_build(self):
        f=Fixture(self.root)
        remote=dict(f.manifest,build={'id':'revision-new','epoch':200})
        self.assertFalse(ui.newer_build(self.root,remote))
        f.put('config/update_manifest.json',json.dumps(f.manifest).encode())
        self.assertTrue(ui.newer_build(self.root,remote))
        f.put('config/update_manifest.json',json.dumps(dict(f.manifest,build={'id':'revision-new','epoch':100})).encode())
        self.assertFalse(ui.newer_build(self.root,remote))
        f.put('config/update_manifest.json',json.dumps(dict(f.manifest,build={'id':'revision-newer','epoch':300})).encode())
        self.assertFalse(ui.newer_build(self.root,remote))


if __name__=='__main__':unittest.main(verbosity=2)
