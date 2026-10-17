"""Stage verified PC file updates, then apply after the panel has exited.

Only uses the standard library. Run a copied helper with --job/--parent;
downloads never write installed files. Each job keeps a rollback journal.
"""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlparse
import uuid
import zipfile

PROTECTED_DIRS = {'.git', '.venv', 'venv', 'logs', 'shots', 'mobile', 'build',
                  'dist', '__pycache__', 'shots_hp_bogus', 'hp_bogus'}
PROTECTED_FILES = {'agents.md', 'system_handoff.md', 'config/gui_options.json',
                   'config/gui_window.json', 'config/panel_token.txt',
                   'config/card_hashes.json'}
MAX_FILE = 512 * 1024 * 1024
MAX_ARCHIVE = 2 * 1024 * 1024 * 1024


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def relative(raw):
    if not isinstance(raw, str) or '\\' in raw:
        raise ValueError('文件路径无效')
    parts = raw.split('/')
    for part in parts:
        if (part in ('', '.', '..') or part.endswith((' ', '.'))
                or re.search(r'[<>:"|?*\x00-\x1f]', part)
                or re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', part)):
            raise ValueError('文件路径无效：' + raw)
    return raw


def protected(rel):
    low = rel.lower()
    return (low in PROTECTED_FILES or any(p in PROTECTED_DIRS for p in low.split('/'))
            or low.startswith('docs/reports/') or low.endswith(('.pyc', '.pyo')))


def target(root, rel):
    rel = relative(rel)
    root = Path(root).absolute()
    path = root.joinpath(*rel.split('/'))
    for part in (root, *path.parents, path):
        if part.exists() or part.is_symlink():
            stat = part.lstat()
            if part.is_symlink() or getattr(stat, 'st_file_attributes', 0) & 0x400:
                raise ValueError('更新路径包含链接，已停止：' + rel)
    if path.exists() and not path.is_file():
        raise ValueError('目标不是普通文件：' + rel)
    return path


def url_ok(url):
    parsed = urlparse(url or '')
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('更新附件须使用 HTTPS')
    return url


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    os.replace(tmp, path)


def read_manifest(asset, version, opener=urllib.request.urlopen):
    req = urllib.request.Request(url_ok(asset.get('browser_download_url')),
                                 headers={'User-Agent': 'kards-auto-updater'})
    with opener(req, timeout=30) as response:
        url_ok(response.geturl())
        raw = response.read(8*1024*1024+1)
    if len(raw) > 8*1024*1024:
        raise ValueError('文件清单过大')
    digest = asset.get('digest')
    if digest and digest != 'sha256:'+hashlib.sha256(raw).hexdigest():
        raise ValueError('文件清单校验失败')
    data = json.loads(raw.decode('utf-8'))
    if data.get('schema') != 1 or data.get('version') != version:
        raise ValueError('清单版本与发布版本不一致')
    if not isinstance(data.get('files'), dict) or not data['files']:
        raise ValueError('文件清单为空')
    seen = set()
    for rel, meta in data['files'].items():
        relative(rel)
        if rel.lower() in seen:
            raise ValueError('文件清单有重复路径')
        seen.add(rel.lower())
        if (not isinstance(meta, dict)
                or not re.fullmatch(r'[0-9a-f]{64}', str(meta.get('sha256', '')))
                or type(meta.get('size')) is not int or not 0 <= meta['size'] <= MAX_FILE):
            raise ValueError('文件清单条目无效：'+rel)
    return data


def plan_update(root, manifest):
    files, skipped, same = [], [], 0
    for rel, meta in manifest['files'].items():
        relative(rel)
        if protected(rel) or rel == 'config/update_manifest.json':
            skipped.append(rel)
            continue
        path = target(root, rel)
        before = sha(path) if path.exists() else None
        if before == meta['sha256']:
            same += 1
        else:
            files.append(dict(path=rel, before=before, **meta))
    return {'files': files, 'skipped': skipped, 'same': same,
            'bytes': sum(x['size'] for x in files)}


def newer_build(root, remote):
    """Allow a same-version refresh only when an installed manifest proves age."""
    path = target(root, 'config/update_manifest.json')
    if not path.is_file(): return False
    try:
        installed = json.loads(path.read_text(encoding='utf-8'))
        new, old = remote.get('build') or {}, installed.get('build') or {}
        epoch, before = new.get('epoch'), old.get('epoch', 0)
        return (remote.get('version') == installed.get('version')
                and type(epoch) is int and type(before) is int and epoch > before >= 0
                and isinstance(new.get('id'), str) and bool(new['id'])
                and new['id'] != old.get('id'))
    except (OSError, ValueError, TypeError, AttributeError):
        return False


class ReleaseArchive(io.RawIOBase):
    """Seekable HTTPS ZIP: range reads, or one verified full fallback."""
    def __init__(self, asset, job, progress, opener=urllib.request.urlopen):
        self.url = url_ok(asset.get('browser_download_url'))
        self.size = asset.get('size')
        if type(self.size) is not int or not 0 < self.size <= MAX_ARCHIVE:
            raise ValueError('PC 附件大小无效')
        self.digest = asset.get('digest')
        self.job, self.progress, self.opener = Path(job), progress, opener
        self.pos, self.transferred = 0, 0
        self.cache_start, self.cache = 0, b''
        self.full = None

    def seekable(self): return True
    def readable(self): return True
    def tell(self): return self.pos

    def seek(self, offset, whence=0):
        self.pos = (0 if whence == 0 else self.pos if whence == 1 else self.size)+offset
        if self.pos < 0:
            raise ValueError('ZIP 偏移无效')
        return self.pos

    def read(self, n=-1):
        n = min(self.size-self.pos, n if n >= 0 else self.size)
        if n <= 0: return b''
        if self.full:
            self.full.seek(self.pos)
            data = self.full.read(n)
        elif self.cache_start <= self.pos and self.pos+n <= self.cache_start+len(self.cache):
            begin = self.pos-self.cache_start
            data = self.cache[begin:begin+n]
        else:
            start, end = self.pos, min(self.size-1, self.pos+max(n, 65536)-1)
            req = urllib.request.Request(self.url, headers={
                'User-Agent': 'kards-auto-updater', 'Accept-Encoding': 'identity',
                'Range': f'bytes={start}-{end}'})
            with self.opener(req, timeout=45) as response:
                url_ok(response.geturl())
                if response.status == 206:
                    if response.headers.get('Content-Range') != f'bytes {start}-{end}/{self.size}':
                        raise ValueError('下载分段范围不一致')
                    self.cache = response.read(end-start+2)
                    if len(self.cache) != end-start+1:
                        raise ValueError('下载分段不完整')
                    self.cache_start = start
                    self.transferred += len(self.cache)
                    data = self.cache[:n]
                elif response.status == 200:
                    self.progress('下载服务器不支持分段，正在下载完整包；安装仍只替换变更文件')
                    archive = self.job/'download.zip'
                    h, count = hashlib.sha256(), 0
                    with archive.open('wb') as stream:
                        while chunk := response.read(1024*1024):
                            count += len(chunk)
                            if count > self.size: raise ValueError('PC 附件大小不一致')
                            h.update(chunk); stream.write(chunk)
                    if count != self.size or (self.digest and self.digest != 'sha256:'+h.hexdigest()):
                        raise ValueError('PC 附件校验失败')
                    self.transferred += count
                    self.full = archive.open('rb')
                    self.full.seek(self.pos)
                    data = self.full.read(n)
                else:
                    raise ValueError(f'附件下载返回 HTTP {response.status}')
        self.pos += len(data)
        return data

    def close(self):
        if self.full: self.full.close()
        super().close()


def stage_update(root, release, progress=lambda msg: None, opener=urllib.request.urlopen):
    root = Path(root).absolute()
    if latest_status(root).get('phase') == 'recovery':
        raise RuntimeError('请先恢复上次中断的更新')
    asset, ma = release.get('asset') or {}, release.get('manifest_asset') or {}
    name = str(asset.get('name', ''))
    if not re.fullmatch(r'kards-auto_v[0-9]+(?:\.[0-9]+)+(?:_beta)?_x86_64\.zip', name):
        raise ValueError('缺少 PC 更新包，不能使用手机版或源码 ZIP')
    if ma.get('name') != name[:-4]+'.manifest.json':
        raise ValueError('PC 包与文件清单不配套')
    version = release['remote']
    manifest = read_manifest(ma, version, opener)
    progress('正在核对本地文件')
    plan = plan_update(root, manifest)
    if not plan['files']: return None
    # Never traverse an existing logs junction to create an update job.
    target(root, 'logs/updates/path-check')
    job = root/'logs/updates'/uuid.uuid4().hex
    (job/'new').mkdir(parents=True)
    try:
        with ReleaseArchive(asset, job, progress, opener) as remote, zipfile.ZipFile(remote) as archive:
            names = {}
            for info in archive.infolist():
                if info.is_dir(): continue
                parts = info.filename.split('/', 1)
                if len(parts) != 2: raise ValueError('PC 包根目录无效')
                relative(parts[0]); rel = relative(parts[1])
                if rel.lower() in names: raise ValueError('PC 包路径重复')
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('PC 包包含符号链接')
                names[rel.lower()] = info
            for i, item in enumerate(plan['files'], 1):
                rel = item['path']; info = names.get(rel.lower())
                if info is None or info.file_size != item['size']:
                    raise ValueError('PC 包缺少或大小不符：'+rel)
                progress(f'下载并校验 {i}/{len(plan["files"])}：{rel}')
                path = target(job/'new', rel); path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, path.open('wb') as dest:
                    shutil.copyfileobj(source, dest, 1024*1024)
                if sha(path) != item['sha256']: raise ValueError('文件校验失败：'+rel)
            plan['downloaded_bytes'] = remote.transferred
            plan['download_mode'] = 'full' if remote.full else 'range'
        mf = job/'new/config/update_manifest.json'
        atomic_json(mf, manifest)
        local_mf = target(root, 'config/update_manifest.json')
        plan['files'].append(dict(path='config/update_manifest.json',
            before=sha(local_mf) if local_mf.exists() else None, sha256=sha(mf), size=mf.stat().st_size))
        plan.update(root=str(root), version=version, status='ready', applied=[])
        atomic_json(job/'plan.json', plan)
        return job
    except Exception as error:
        atomic_json(job/'result.json', {'ok': False, 'status': 'download_failed', 'msg': str(error)})
        raise


def rollback(job, plan):
    for rel in reversed(plan['applied']):
        dst = target(plan['root'], rel)
        item = next(x for x in plan['files'] if x['path'] == rel)
        current = sha(dst) if dst.exists() else None
        if current == item['before']:
            continue
        if current != item['sha256']:
            raise ValueError('恢复期间文件又有变化：'+rel)
        backup = target(job/'backup', rel)
        if backup.exists():
            os.replace(backup, dst)
        elif dst.exists():
            dst.unlink()
    plan['applied'] = []


def latest_status(root):
    folder = Path(root)/'logs/updates'
    if not folder.exists(): return {}
    jobs = sorted(folder.glob('*/plan.json'), key=lambda p:p.stat().st_mtime, reverse=True)
    if not jobs: return {}
    for path in jobs:
        try:
            plan = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {'phase': 'error', 'msg': '更新记录损坏，请检查 logs/updates 中的备份'}
        if plan['status'] in ('applying', 'rollback_failed'):
            return {'phase': 'recovery', 'job': str(path.parent), 'msg': '上次更新中断，请点击“恢复旧文件”'}
    job = jobs[0].parent
    result = job/'result.json'
    return dict(json.loads(result.read_text(encoding='utf-8')), phase='done') if result.exists() else {}


def recover_job(job):
    job = Path(job).absolute()
    plan = json.loads((job/'plan.json').read_text(encoding='utf-8'))
    if job.parent != Path(plan['root']).absolute()/'logs/updates':
        raise ValueError('更新任务不属于目标目录')
    if plan['status'] not in ('applying', 'rollback_failed'):
        raise ValueError('该任务不需要恢复')
    rollback(job, plan)
    plan['status'] = 'rolled_back'; atomic_json(job/'plan.json', plan)
    result = {'ok': True, 'status': 'rolled_back', 'msg': '已恢复更新前的文件，请重新检测更新'}
    atomic_json(job/'result.json', result)
    return result


def apply_job(job):
    job = Path(job).absolute()
    plan = json.loads((job/'plan.json').read_text(encoding='utf-8'))
    if job.parent != Path(plan['root']).absolute()/'logs/updates':
        raise ValueError('更新任务不属于目标目录')
    if plan['status'] != 'ready': raise ValueError('更新任务状态不允许安装')
    try:
        for item in plan['files']:
            rel = item['path']
            if protected(rel): raise ValueError('任务不能更新本机配置：'+rel)
            dst, source = target(plan['root'], rel), target(job/'new', rel)
            if (sha(dst) if dst.exists() else None) != item['before']:
                raise ValueError('检测后本地文件又有变化，请重新检测：'+rel)
            if sha(source) != item['sha256']:
                raise ValueError('暂存文件校验失败：'+rel)
            if dst.exists():
                backup = target(job/'backup', rel)
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dst, backup)
        plan['status'] = 'applying'; atomic_json(job/'plan.json', plan)
        # Commit the version and installed manifest only after all code/data.
        for item in sorted(plan['files'], key=lambda v:v['path'] in
                           ('config/app_version.json', 'config/update_manifest.json')):
            rel = item['path']; dst = target(plan['root'], rel)
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(dst.name+'.update-'+job.name+'.tmp')
            shutil.copy2(target(job/'new', rel), tmp)
            # Write intent before mutation, so failure/crash retains rollback evidence.
            plan['applied'].append(rel); atomic_json(job/'plan.json', plan)
            try:
                os.replace(tmp, dst)
            finally:
                if tmp.exists(): tmp.unlink()
        plan['status'] = 'completed'; atomic_json(job/'plan.json', plan)
        result = {'ok': True, 'status': 'completed', 'version': plan['version'],
                  'msg': f'已更新至 v{plan["version"]}，替换 {len(plan["files"])-1} 个变更/新增文件'}
    except Exception as error:
        try:
            rollback(job, plan)
            plan['status'] = 'rolled_back'
            result = {'ok': False, 'status': 'rolled_back', 'msg': '更新失败，已恢复旧文件：'+str(error)}
        except Exception as rollback_error:
            plan['status'] = 'rollback_failed'
            result = {'ok': False, 'status': 'rollback_failed',
                      'msg': f'恢复未完成：{rollback_error}；备份位于 {job / "backup"}'}
        atomic_json(job/'plan.json', plan)
    atomic_json(job/'result.json', result)
    return result


@contextlib.contextmanager
def engine_guard():
    """Block updating while any production engine owns its named mutex."""
    if os.name != 'nt':
        yield; return
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateMutexW(None, True, 'kards_auto_main_loop')
    already = ctypes.get_last_error() == 183
    if not handle: raise OSError('无法检查引擎运行状态')
    try:
        if already: raise RuntimeError('请先停止正在运行的自动对局，再应用更新')
        yield
    finally:
        if not already:
            kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
            kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


def launch_helper(job, python, parent_pid, restart, recover=False):
    job = Path(job).absolute()
    plan = json.loads((job/'plan.json').read_text(encoding='utf-8'))
    helper = job/'helper.py'
    shutil.copy2(Path(plan['root'])/'src/update_install.py', helper)
    # A private interpreter avoids replacing loaded Python DLLs in-place.
    if any(x['path'].lower().startswith('python/') for x in plan['files']):
        runtime = Path(plan['root'])/'python'
        if not (runtime/'python.exe').is_file(): raise ValueError('缺少便携 Python，不能升级运行环境')
        if not (job/'helper-runtime/python.exe').is_file():
            shutil.copytree(runtime, job/'helper-runtime', dirs_exist_ok=True)
        python = str(job/'helper-runtime/python.exe')
    atomic_json(job/'restart.json', restart)
    log = open(job/'helper.log', 'ab', buffering=0)
    try:
        argv = [python, str(helper), '--job', str(job), '--parent', str(parent_pid)]
        if recover: argv.append('--recover')
        return subprocess.Popen(argv,
            cwd=job, stdout=log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    finally:
        log.close()


def panel_exit_pid():
    """PyInstaller onefile's launcher also holds the EXE until its child exits."""
    current = os.getpid()
    if not getattr(sys, 'frozen', False) or os.name != 'nt': return current
    parent = os.getppid()
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                                ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32)]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x1000, False, parent)
    if not handle: raise OSError('无法确认面板启动器状态')
    try:
        buffer = ctypes.create_unicode_buffer(32768); size = ctypes.c_uint32(len(buffer))
        if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            raise OSError('无法读取面板启动器路径')
        return parent if os.path.normcase(buffer.value) == os.path.normcase(sys.executable) else current
    finally:
        kernel.CloseHandle(handle)


def wait_parent(pid, timeout=90):
    if os.name != 'nt': raise RuntimeError('安装助手仅支持 Windows')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x100000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87: return
        raise OSError('无法确认面板已经退出')
    try:
        if kernel.WaitForSingleObject(handle, int(timeout*1000)) != 0:
            raise TimeoutError('面板尚未退出，已取消替换')
    finally:
        kernel.CloseHandle(handle)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--job', required=True)
    ap.add_argument('--parent', type=int, required=True)
    ap.add_argument('--recover', action='store_true'); args = ap.parse_args()
    job = Path(args.job)
    parent_exited = False
    try:
        wait_parent(args.parent)
        parent_exited = True
        with engine_guard(): result = recover_job(job) if args.recover else apply_job(job)
    except Exception as error:
        result = {'ok': False, 'status': 'rollback_failed' if args.recover else 'blocked', 'msg': str(error)}
        atomic_json(job/'result.json', result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    # Never restart into a partially restored installation.
    if parent_exited and result['status'] not in ('rollback_failed',):
        restart = json.loads((job/'restart.json').read_text(encoding='utf-8'))
        subprocess.Popen(restart['argv'], cwd=restart['cwd'],
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return 0 if result['ok'] else 1


if __name__ == '__main__': raise SystemExit(main())
