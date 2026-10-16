"""API denial -> Atom -> public attachments -> GUI diff, without network/input."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import gui
import update_check as uc
import update_install as ui

TAG = 'v0.2.2'
STEM = 'kards-auto_v0.2.2_x86_64'
PREFIX = 'https://github.com/yumehanab1/OCR-Kards-Auto/releases/download/v0.2.2/'
FEED = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>v0.2.2</title>
<link href="https://github.com/yumehanab1/OCR-Kards-Auto/releases/tag/v0.2.2"/>
</entry></feed>'''
PAYLOAD = b'new source'
MANIFEST = json.dumps(dict(schema=1, version='0.2.2', files={
    'src/example.py': dict(size=len(PAYLOAD), sha256=hashlib.sha256(PAYLOAD).hexdigest())
})).encode()
DIGEST = 'sha256:' + hashlib.sha256(MANIFEST).hexdigest()
HTML = (f'<a href="{PREFIX}{STEM}.zip">PC</a>'
        f'<a href="{PREFIX}{STEM}.manifest.json">Manifest</a>'
        f'<clipboard-copy aria-label="Copy to clipboard digest for {STEM}.manifest.json" '
        f'value="{DIGEST}"></clipboard-copy>').encode()


class Response(io.BytesIO):
    def geturl(self):
        return PREFIX + STEM + '.manifest.json'


class FeedAssets(unittest.TestCase):
    def route(self, code=403, html=HTML, asset_code=200):
        calls = []
        def fetch(url, timeout):
            calls.append(url)
            if url == uc.DEFAULT_API:
                if code == 'timeout':
                    raise TimeoutError()
                return code, b'{}'
            if url == uc.DEFAULT_FEED:
                return 200, FEED
            if url == uc.DEFAULT_ASSETS + TAG:
                return asset_code, html
            raise AssertionError('Unexpected request: ' + url)
        return fetch, calls

    def test_denial_and_timeout_recover_paired_assets_without_zip_download(self):
        for code in (403, 429, 'timeout'):
            fetch, calls = self.route(code)
            result = uc.check('0.2.1', _fetch=fetch, _head=lambda url, timeout: 1234)
            self.assertTrue(result['has_update'])
            self.assertEqual(result['via'], 'feed')
            self.assertEqual(result['asset']['name'], STEM + '.zip')
            self.assertEqual(result['asset']['size'], 1234)
            self.assertEqual(result['manifest_asset']['digest'], DIGEST)
            self.assertFalse(result['asset_error'])
            self.assertTrue(result['api_error'])
            self.assertEqual(calls, [uc.DEFAULT_API, uc.DEFAULT_FEED, uc.DEFAULT_ASSETS + TAG])

    def test_wrong_host_tag_source_zip_mobile_and_pending_are_rejected(self):
        bad = [PREFIX.replace('github.com', 'evil.example') + STEM + '.zip',
               PREFIX.replace('/v0.2.2/', '/v0.2.1/') + STEM + '.zip',
               PREFIX + STEM + '.zip.pending', PREFIX + 'KARDS-AUTO-Mobile-v0.2.2.apk',
               PREFIX + STEM + '.zip?redirect=1', PREFIX + STEM + '.zip#fragment',
               'https://github.com/yumehanab1/OCR-Kards-Auto/archive/refs/tags/v0.2.2.zip']
        html = ''.join(f'<a href="{url}">bad</a>' for url in bad).encode()
        self.assertEqual(uc.parse_release_assets(html, TAG), {})
        self.assertEqual(uc.parse_release_assets(HTML, '../bad'), {})
        relative = HTML.replace(b'https://github.com', b'')
        self.assertEqual(uc.parse_release_assets(relative, TAG)['manifest_asset']['digest'], DIGEST)

    def test_unavailable_html_reports_lookup_failure(self):
        fetch, _ = self.route(asset_code=503)
        result = uc.check('0.2.1', _fetch=fetch)
        self.assertTrue(result['ok'])
        self.assertIsNone(result['manifest_asset'])
        self.assertIn('HTTP 503', result['asset_error'])

    def test_missing_actual_manifest_is_not_invented(self):
        fetch, _ = self.route(html=HTML.split(b'<a href=', 2)[0])
        result = uc.check('0.2.1', _fetch=fetch)
        self.assertIsNone(result['manifest_asset'])
        self.assertIn('未找到', result['asset_error'])

    def test_custom_source_does_not_use_default_repository_fallback(self):
        calls = []
        def fetch(url, timeout):
            calls.append(url)
            return 403, b'{}'
        self.assertFalse(uc.check('0.2.1', 'https://example.com/update', _fetch=fetch)['ok'])
        self.assertEqual(calls, ['https://example.com/update'])

    def test_gui_reads_verified_manifest_and_enables_apply(self):
        fetch, _ = self.route()
        read_manifest = ui.read_manifest
        def read(asset, version):
            return read_manifest(asset, version, opener=lambda *a, **kw: Response(MANIFEST))
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(gui, 'PROJECT_ROOT', directory), \
                patch.object(gui, 'read_version', return_value={'version': '0.2.1'}), \
                patch.object(gui, 'log_update'), patch.object(uc, '_http_get', side_effect=fetch), \
                patch.object(uc, '_http_head', return_value=1234), \
                patch.object(ui, 'read_manifest', side_effect=read):
            result = gui.Api().check_update()
        self.assertTrue(result['can_apply'])
        self.assertTrue(result['file_changes']['ok'])
        self.assertEqual(result['file_changes']['missing'], ['src/example.py'])
        self.assertNotIn('没有文件清单', result['msg'])
        with self.assertRaisesRegex(ValueError, '校验失败'):
            read_manifest(dict(result['manifest_asset'], digest='sha256:'+'0'*64), '0.2.2',
                          opener=lambda *a, **kw: Response(MANIFEST))

    def test_exact_size_required_before_offering_install(self):
        for size in (None, 0, -1, 3*1024*1024*1024):
            fetch, _ = self.route()
            result = uc.check('0.2.1', _fetch=fetch, _head=lambda url, timeout: size)
            self.assertIsNone(result['asset'])
            self.assertIn('有效字节大小', result['asset_error'])

    def test_gui_failure_does_not_claim_release_has_no_manifest(self):
        fetch, _ = self.route(asset_code=503)
        with patch.object(gui, 'read_version', return_value={'version': '0.2.1'}), \
                patch.object(gui, 'log_update'), patch.object(uc, '_http_get', side_effect=fetch):
            result = gui.Api().check_update()
        self.assertFalse(result['can_apply'])
        self.assertIn('附件列表读取失败', result['msg'])
        self.assertNotIn('该 Release 没有文件清单', result['msg'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
