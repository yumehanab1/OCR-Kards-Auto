"""Instrumentation-only path lease; never included in the public application."""
import hashlib
import importlib
import json
import os
import re
import sys


def _inside(path, root):
    try:
        return os.path.commonpath([os.path.abspath(path), root]) == root
    except (TypeError, ValueError):
        return False


def install(directory):
    root = os.path.abspath(directory)
    with open(os.path.join(root, 'manifest.json'), encoding='utf8') as stream:
        manifest = json.load(stream)
    if manifest.get('schema') != 1:
        raise ValueError('public_test_support_manifest_schema')
    names = []
    seen = set()
    for item in manifest['files']:
        relative = item['path']
        parts = relative.split('/')
        allowed = (relative == 'public_release_test_support.py' or
                   re.fullmatch(r'(?:apk_native/)?[A-Za-z_][A-Za-z0-9_]*_test\.py', relative) is not None)
        if not allowed or relative in seen:
            raise ValueError('public_test_support_invalid_module')
        seen.add(relative)
        path = os.path.join(root, *parts)
        if not _inside(path, root):
            raise ValueError('public_test_support_outside_root')
        with open(path, 'rb') as stream:
            content = stream.read()
        if len(content) != item['bytes'] or hashlib.sha256(content).hexdigest() != item['sha256']:
            raise ValueError('public_test_support_hash_mismatch')
        if relative.endswith('_test.py'):
            names.append(relative[:-3].replace('/', '.'))
    if 'public_release_test_support.py' not in seen:
        raise ValueError('public_test_support_bootstrap_missing')
    if any(name in sys.modules for name in names):
        raise ValueError('public_test_module_already_loaded')
    package = importlib.import_module('apk_native')
    if not list(package.__path__) or _inside(package.__file__, root):
        raise ValueError('public_test_support_shadowed_production_package')
    state = dict(root=root, package=package, package_origin=package.__file__,
                 package_paths=list(package.__path__), sys_paths=list(sys.path), names=names)
    # No production module or __init__.py is present here. Append preserves all
    # target APK paths ahead of the support modules, including root-level tests.
    sys.path.append(root)
    package.__path__.append(os.path.join(root, 'apk_native'))
    importlib.invalidate_caches()
    return state


def describe(state):
    return dict(installed=True, test_module_count=len(state['names']),
                production_package_origin=state['package_origin'],
                production_package_paths=state['package_paths'], support_directory=state['root'],
                appended_only=True)


def cleanup(state):
    package = state['package']
    removed = []
    unexpected = []
    for name, module in list(sys.modules.items()):
        if module is None or not _inside(getattr(module, '__file__', None), state['root']):
            continue
        if name not in state['names']:
            unexpected.append(name)
        sys.modules.pop(name, None)
        if name.startswith('apk_native.'):
            attribute = name.rsplit('.', 1)[1]
            if getattr(package, attribute, None) is module:
                delattr(package, attribute)
        removed.append(name)
    sys.path[:] = state['sys_paths']
    package.__path__[:] = state['package_paths']
    importlib.invalidate_caches()
    origin_unchanged = package.__file__ == state['package_origin']
    return dict(paths_restored=sys.path == state['sys_paths'] and list(package.__path__) == state['package_paths'],
                production_origin_unchanged=origin_unchanged, removed_test_modules=sorted(removed),
                unexpected_support_modules=sorted(unexpected),
                passed=origin_unchanged and not unexpected)
