"""Bound log startup, polling, giant lines and rotation; no game input."""
from pathlib import Path
import concurrent.futures
import io
import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import log_io
import gui
import watch_log


class Tracked(io.BytesIO):
    def __init__(self,data):super().__init__(data);self.read_sizes=[]
    def read(self,n=-1):
        if n < 0:raise AssertionError('Unbounded log read')
        self.read_sizes.append(n)
        return super().read(n)


class LongLog(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.path=self.root/'main_loop.log'
    def tearDown(self):self.temp.cleanup()

    def test_large_log_bounds_bytes_lines_and_utf8(self):
        data=('完整中文日志\n'*100000+'2026-10-16 14:00:00 state -> in_game\n').encode()
        stream=Tracked(data)
        lines=log_io.tail_stream(stream,10**9)
        self.assertLessEqual(sum(stream.read_sizes),log_io.MAX_TAIL_BYTES)
        self.assertEqual(len(lines),400)
        self.assertIn('state -> in_game',lines[-1])
        self.assertTrue(all('�' not in line for line in lines))

    def test_giant_line_and_zero_tail(self):
        stream=Tracked(('超长一行'*100000).encode())
        lines=log_io.tail_stream(stream)
        self.assertEqual(len(lines),1)
        self.assertLess(len(lines[0]),log_io.MAX_LINE_CHARS+100)
        self.assertNotIn('�',lines[0])
        self.assertEqual(log_io.tail_stream(stream,0),[])
        self.assertEqual(log_io.tail_lines(self.path),[])

    def test_snapshot_reads_once_per_revision_and_skips_transfer(self):
        self.path.write_text('state -> in_game\n[attack] 打中了\n普通日志\n',encoding='utf-8')
        with patch.object(gui,'LOG',str(self.path)),patch.object(gui,'tail_lines',wraps=gui.tail_lines) as read:
            api=gui.Api()
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
                results=list(pool.map(lambda _:api.snapshot(),range(12)))
            self.assertEqual(read.call_count,1)
            rev=results[0]['log_rev']
            self.assertTrue(results[0]['log_lines'])
            self.assertEqual(api.snapshot(since_rev=rev)['log_lines'],[])
            api.snapshot(True)
            self.assertEqual(read.call_count,1)
            with self.path.open('ab') as stream:stream.write('state -> victory\n'.encode())
            result=api.snapshot(since_rev=rev)
            self.assertEqual(read.call_count,2)
            self.assertEqual(result['status']['state'],'victory')
            self.assertTrue(result['log_lines'])

    def test_rotation_preserves_old_contents_and_invalidates_cache(self):
        original='旧日志中文\n'.encode()*1000;self.path.write_bytes(original)
        before=gui.log_rev(self.path)
        archived=log_io.archive_large(self.path,100)
        self.assertEqual(archived.read_bytes(),original)
        self.assertFalse(self.path.exists())
        self.path.write_text('新日志\n',encoding='utf-8')
        self.assertNotEqual(gui.log_rev(self.path),before)
        self.assertIsNone(log_io.archive_large(self.path,100))

    def test_follower_startup_append_truncate_and_rotate(self):
        self.path.write_text('旧历史\n最新历史\n',encoding='utf-8')
        follower=watch_log.iter_follow(self.path,1,poll=0,sleep=lambda _:None)
        try:
            self.assertEqual(next(follower),'最新历史')
            with self.path.open('ab') as stream:stream.write('追加中文\n'.encode())
            self.assertEqual(next(follower),'追加中文')
            self.path.write_text('截短后\n',encoding='utf-8')
            self.assertEqual(next(follower),'截短后')
            archived=log_io.archive_large(self.path,1)
            self.path.write_text('轮换后\n',encoding='utf-8')
            self.assertEqual(next(follower),'轮换后')
            self.assertEqual(archived.read_text(encoding='utf-8'),'截短后\n')
        finally:follower.close()

    def test_128mb_snapshot_payload_and_speed(self):
        with self.path.open('wb') as stream:
            stream.truncate(128*1024*1024)
            stream.seek(0,os.SEEK_END)
            stream.write(('中文历史\n'*1000+'state -> in_game\n').encode())
        with patch.object(gui,'LOG',str(self.path)):
            api=gui.Api();started=time.perf_counter();result=api.snapshot();elapsed=time.perf_counter()-started
            self.assertLess(elapsed,1.0)
            self.assertLess(len(json.dumps(result,ensure_ascii=False).encode()),150000)
            self.assertEqual(result['status']['state'],'in_game')

    def test_frontend_one_inflight_and_filter_switch_race_guard(self):
        self.assertIn('if(polling) return;',gui.HTML)
        self.assertIn('polling = true;',gui.HTML)
        self.assertIn('polling = false;',gui.HTML)
        self.assertIn('if(filter !== onlyKey)',gui.HTML)
        self.assertIn('snapshot(filter, 400, lastRev)',gui.HTML)


if __name__=='__main__':unittest.main(verbosity=2)
