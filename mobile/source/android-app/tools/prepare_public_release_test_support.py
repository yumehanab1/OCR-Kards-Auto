"""Stage source-only Python checks in AndroidTest assets, after clean, before its build."""
import ast
import hashlib
import json
from pathlib import Path
import re
from verify_release_smoke_assets import verify

OUT = Path(__file__).resolve().parent
PROJECT = OUT.parent
SOURCE = PROJECT / 'app/src/main/python'
GENERATED = PROJECT / 'app/build/generated/deviceTestAssets'
DEST = GENERATED / 'public-test-support'


def allowed(relative):
    return (relative.as_posix() == 'public_release_test_support.py' or
            re.fullmatch(r'(?:apk_native/)?[A-Za-z_][A-Za-z0-9_]*_test\.py', relative.as_posix()) is not None)


def main():
    fixture_preflight = verify()
    DEST.resolve().relative_to(GENERATED.resolve())
    sources = [(p.relative_to(SOURCE), p) for p in sorted(SOURCE.glob('*_test.py'))]
    sources += [(p.relative_to(SOURCE), p) for p in sorted((SOURCE / 'apk_native').glob('*_test.py'))]
    sources += [(Path('public_release_test_support.py'), OUT / 'public_release_test_support.py')]
    assert sources and all(allowed(relative) for relative, _ in sources)
    files = []
    payload = {}
    for relative, source in sources:
        data = source.read_bytes()
        ast.parse(data.decode('utf8'), filename=str(source))
        payload[relative.as_posix()] = data
        files.append(dict(path=relative.as_posix(), bytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
    previous = []
    if (DEST / 'manifest.json').is_file():
        previous = json.loads((DEST / 'manifest.json').read_text(encoding='utf8'))['files']
    known = {item['path'] for item in previous} | {'manifest.json'}
    if DEST.exists():
        assert all(p.relative_to(DEST).as_posix() in known for p in DEST.rglob('*') if p.is_file()), 'Unexpected generated support file'
    for item in previous:
        relative = Path(item['path']);assert allowed(relative)
        target = DEST / relative;target.resolve().relative_to(DEST.resolve())
        assert hashlib.sha256(target.read_bytes()).hexdigest() == item['sha256'], 'Changed generated support file'
        if item['path'] not in payload:
            target.unlink()
    for relative, data in payload.items():
        target = DEST / relative;target.parent.mkdir(parents=True, exist_ok=True);target.write_bytes(data)
    manifest = dict(schema=1, purpose='android_test_only_public_release_python_support', files=files)
    (DEST / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf8')
    print(json.dumps(dict(generated=str(DEST), files=len(files), bytes=sum(item['bytes'] for item in files),
                          fixture_images=0, production_modules=0, device_commands=0,
                          fixture_preflight=fixture_preflight)))


if __name__ == '__main__':
    main()
