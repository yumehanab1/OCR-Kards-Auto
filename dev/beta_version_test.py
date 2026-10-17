"""Beta version ordering, stable-feed isolation and verified PC beta staging."""
from pathlib import Path
import hashlib
import io
import json
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import update_check as uc
import update_install as ui

TAG = 'v0.2.2_beta'
VERSION = TAG[1:]
API = uc.DEFAULT_TAG_API + TAG
STEM = 'kards-auto_' + TAG + '_x86_64'
PREFIX = 'https://github.com/yumehanab1/OCR-Kards-Auto/releases/download/' + TAG + '/'
HTML = (f'<a href="{PREFIX}{STEM}.zip">PC</a>'
        f'<a href="{PREFIX}{STEM}.manifest.json">Manifest</a>').encode()


def entry(tag, link=True):
    href = f'<link href="{uc.RELEASES_PAGE}/tag/{tag}"/>' if link else ''
    return f'<entry><title>KARDS AUTO {tag}</title>{href}</entry>'


def feed(*entries):
    return ('<feed xmlns="http://www.w3.org/2005/Atom">'
            + ''.join(entries) + '</feed>').encode()


class Response(io.BytesIO):
    status = 200
    headers = {}

    def geturl(self):
        return PREFIX + STEM + '.zip'


class BetaVersions(unittest.TestCase):
    def test_stable_numeric_parser_contract_and_beta_order(self):
        self.assertEqual(uc.parse_version('v0.1.10'), (0, 1, 10))
        self.assertEqual(uc.parse_version('1.0'), (1, 0))
        self.assertEqual(uc.parse_version('0.2.2_beta'), (0, 2, 2))
        self.assertEqual(uc.parse_version(None), ())
        for remote, local, expected in (
                ('0.2.2', VERSION, True), (VERSION, '0.2.2', False),
                (VERSION, '0.2.1', True), ('0.2.1', VERSION, False),
                (VERSION, VERSION, False), ('v0.2.2', VERSION, True),
                ('0.2.2.0', VERSION, True), (VERSION, '0.2.2.0', False),
                ('0.3.0_beta', '0.2.9', True), ('0.1.10', '0.1.9', True)):
            with self.subTest(remote=remote, local=local):
                self.assertEqual(uc.is_newer(remote, local), expected)

    def test_default_feed_skips_beta_and_other_prerelease_tags(self):
        xml = feed(entry(TAG), entry('v0.3.0-rc.1'), entry(TAG, link=False),
                   entry('v0.2.2'))
        self.assertEqual(uc.parse_feed(xml)['tag'], 'v0.2.2')
        self.assertEqual(uc.parse_feed(feed(entry(TAG))), {})
        self.assertEqual(uc.parse_feed(feed(entry(TAG, link=False))), {})

    def test_default_latest_rejects_beta_and_feed_finds_stable(self):
        calls = []
        def fetch(url, timeout):
            calls.append(url)
            if url == uc.DEFAULT_API:
                return 200, json.dumps(dict(tag_name=TAG, prerelease=True)).encode()
            if url == uc.DEFAULT_FEED:
                return 200, feed(entry(TAG), entry('v0.2.2'))
            return 200, b''
        result = uc.check('0.2.1', _fetch=fetch)
        self.assertTrue(result['ok'])
        self.assertEqual(result['remote'], '0.2.2')
        self.assertIn(uc.DEFAULT_ASSETS + 'v0.2.2', calls)
        self.assertNotIn(uc.DEFAULT_ASSETS + TAG, calls)

    def test_beta_assets_allow_only_exact_paired_names_host_and_tag(self):
        assets = uc.parse_release_assets(HTML, TAG)
        self.assertEqual(assets['asset']['name'], STEM + '.zip')
        self.assertEqual(assets['manifest_asset']['name'], STEM + '.manifest.json')
        for html, tag in ((HTML.replace(b'github.com', b'evil.example'), TAG),
                          (HTML, 'v0.2.2'), (HTML, '../' + TAG),
                          (HTML.replace(b'.zip', b'.zip.pending'), TAG)):
            self.assertNotIn('asset', uc.parse_release_assets(html, tag))
        self.assertEqual(uc.parse_release_assets(HTML, 'v0.2.2_beta1'), {})

    def route(self, code=403, html=HTML, size=1234):
        calls = []
        def fetch(url, timeout):
            calls.append(url)
            if url == API:
                if code == 'timeout':
                    raise TimeoutError()
                return code, b'{}'
            if url == uc.DEFAULT_ASSETS + TAG:
                return 200, html
            raise AssertionError('Unexpected request: ' + url)
        def head(url, timeout):
            calls.append(('HEAD', url))
            return size
        return fetch, head, calls

    def test_official_beta_api_quota_fallback_needs_actual_paired_assets(self):
        for code in (403, 429, 'timeout'):
            fetch, head, calls = self.route(code)
            result = uc.check(VERSION, API, _fetch=fetch, _head=head)
            self.assertTrue(result['ok'])
            self.assertEqual(result['remote'], VERSION)
            self.assertEqual(result['via'], 'tag_assets')
            self.assertEqual(result['asset']['size'], 1234)
            self.assertFalse(result['has_update'])
            self.assertTrue(result['api_error'])
            self.assertEqual(calls, [API, uc.DEFAULT_ASSETS + TAG,
                                    ('HEAD', PREFIX + STEM + '.zip')])

    def test_beta_fallback_does_not_invent_missing_or_unverified_assets(self):
        zip_only = HTML[:HTML.index(b'<a href=', 1)]
        for html, size in ((b'', 1234), (zip_only, 1234),
                           (HTML, 0), (HTML, None)):
            fetch, head, _ = self.route(html=html, size=size)
            result = uc.check(VERSION, API, _fetch=fetch, _head=head)
            self.assertFalse(result['ok'])
            self.assertIsNone(result['asset'])
            self.assertIsNone(result['manifest_asset'])
            self.assertNotIn('已是最新', result['msg'])

    def test_custom_and_spoofed_beta_sources_never_use_default_fallback(self):
        for url in ('https://example.com/releases/tags/' + TAG,
                    API + '?redirect=1', API + '/',
                    API.replace('api.github.com', 'api.github.com.evil.example'),
                    API.replace('OCR-Kards-Auto', 'another-repo'),
                    uc.DEFAULT_TAG_API + 'v0.2.2'):
            calls = []
            def fetch(requested, timeout):
                calls.append(requested)
                return 403, b'{}'
            self.assertFalse(uc.check(VERSION, url, _fetch=fetch)['ok'])
            self.assertEqual(calls, [url])

    def test_beta_api_tag_mismatch_is_not_trusted(self):
        def fetch(url, timeout):
            if url == API:
                return 200, json.dumps(dict(tag_name='v0.3.0_beta')).encode()
            return 404, b''
        result = uc.check(VERSION, API, _fetch=fetch)
        self.assertFalse(result['ok'])
        self.assertIn('标签不一致', result['msg'])

    def test_beta_zip_can_stage_and_apply_verified_temp_files(self):
        payload = b'new beta engine'
        version = json.dumps(dict(version=VERSION)).encode()
        files = {'src/beta.txt': payload, 'config/app_version.json': version}
        manifest = dict(schema=1, version=VERSION, files={
            rel: dict(size=len(data), sha256=hashlib.sha256(data).hexdigest())
            for rel, data in files.items()})
        raw = json.dumps(manifest).encode()
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as package:
            for rel, data in files.items():
                package.writestr('kards-auto/' + rel, data)
        zipped = archive.getvalue()
        release = dict(remote=VERSION,
            asset=dict(name=STEM + '.zip', browser_download_url=PREFIX + STEM + '.zip',
                       size=len(zipped), digest='sha256:' + hashlib.sha256(zipped).hexdigest()),
            manifest_asset=dict(name=STEM + '.manifest.json',
                browser_download_url=PREFIX + STEM + '.manifest.json',
                digest='sha256:' + hashlib.sha256(raw).hexdigest()))
        def opener(request, timeout):
            return Response(raw if request.full_url.endswith('.manifest.json') else zipped)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = ui.stage_update(root, release, opener=opener)
            self.assertFalse((root / 'src/beta.txt').exists())
            self.assertTrue(ui.apply_job(job)['ok'])
            self.assertEqual((root / 'src/beta.txt').read_bytes(), payload)
            self.assertEqual(json.loads((root / 'config/app_version.json').read_text())['version'], VERSION)


if __name__ == '__main__':
    unittest.main(verbosity=2)
