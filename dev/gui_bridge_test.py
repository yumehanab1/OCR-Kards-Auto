"""Exercise real pywebview reflection without a native window or game input."""
from pathlib import Path
from types import SimpleNamespace
import json
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import gui
from webview.util import inject_pywebview, js_bridge_call


class NativeTrap:
    def __dir__(self):
        raise AssertionError('Native/process state must never be reflected')


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.api = gui.Api()
        self.api.window = NativeTrap()
        self.api.proc = NativeTrap()
        self.bridge = gui.make_js_api(self.api)

    def test_real_bridge_initialization_exposes_only_methods(self):
        scripts = []
        loaded = threading.Event()
        window = SimpleNamespace(
            _js_api=self.bridge, _functions={}, _expose_lock=threading.Lock(),
            run_js=scripts.append,
            events=SimpleNamespace(before_load=threading.Event(),
                _pywebviewready=threading.Event(), loaded=loaded))
        with patch('webview.util.load_js_files', return_value=('', '%(functions)s')):
            inject_pywebview('edgechromium', window)
            self.assertTrue(loaded.wait(3), 'Bridge initialization timed out')
        methods = {item['func']: item['params'] for item in json.loads(scripts[-1])}
        self.assertEqual(set(methods), set(gui.JS_API_METHODS))
        self.assertEqual(methods['snapshot'], ['only_key', 'tail', 'since_rev'])
        self.assertEqual(methods['start'], ['opts'])
        self.assertEqual(methods['stop'], [])
        self.assertTrue(window.events._pywebviewready.is_set())

    def test_real_bridge_dispatch_preserves_binding_and_arguments(self):
        done = threading.Event()
        results = []
        def evaluate(script):
            results.append(script)
            done.set()
        window = SimpleNamespace(_js_api=self.bridge, _functions={},
                                 evaluate_js=evaluate)
        with patch.object(gui, 'save_options', return_value={'play': True}) as save:
            js_bridge_call(window, 'save_settings', [{'play': True}], 'test')
            self.assertTrue(done.wait(3), 'Bridge response timed out')
            save.assert_called_once_with({'play': True})
        self.assertEqual(self.api.saved_options, {'play': True})
        self.assertIn('配置已自动保存'.encode('unicode_escape').decode().replace('\\', '\\\\'), results[0])


if __name__ == '__main__':
    unittest.main()
