"""Check locally supplied AndroidTest fixtures; never copy or generate images."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import struct

PROJECT = Path(__file__).resolve().parent.parent
ASSET_ROOTS = (PROJECT / 'app/src/androidTest/assets',
               PROJECT / 'app/build/generated/deviceTestAssets')
DIRECT = (
    'replay/game_opening.png',
    'native-pipeline-probe/live-opening-2772.png',
    'native-pipeline-probe/live-own-2772.png',
    'native-pipeline-probe/daily-popup-2772.png',
    'phone-inset-probe/phone114-battle-review.jpg',
    'phone-inset-probe/phone114-menu-review.jpg',
    'phone-inset-probe/phone116-mulligan-review.jpg',
    'phone-inset-probe/phone121-settle-review.jpg',
    'phone-result-probe/original.png',
    'opening-opponent-wait-probe/code139-frame0008-review.jpg',
    'dynamic-menu-probe/code125-home-720-review.jpg',
    'dynamic-menu-probe/code128-promotion-review.jpg',
    'dynamic-menu-probe/code129-daily-review.jpg',
    'dynamic-menu-probe/code130-starter-original.png',
)
MANIFESTS = ('native-pipeline-probe/manifest.json', 'aspect-169-probe/manifest.json',
             'opening-retention-probe/manifest.json')


def verify(asset_roots=None):
    roots = tuple(Path(root).resolve() for root in (asset_roots or ASSET_ROOTS))
    checked = {}
    missing = set()

    def read(relative):
        name = PurePosixPath(relative)
        if name.is_absolute() or '..' in name.parts or '\\' in relative:
            raise ValueError('Unsafe AndroidTest asset path: ' + relative)
        matches = []
        for root in roots:
            path = root.joinpath(*name.parts)
            path.resolve().relative_to(root)
            if path.is_file():
                matches.append(path)
        if not matches:
            missing.add(relative)
            return None
        if len(matches) != 1:
            raise ValueError('Duplicate AndroidTest asset: ' + relative)
        data = matches[0].read_bytes()
        checked[relative] = dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        return data

    for relative in DIRECT:
        read(relative)
    manifest_entries = 0
    for relative in MANIFESTS:
        raw = read(relative)
        if raw is None:
            continue
        manifest = json.loads(raw)
        entries = manifest if isinstance(manifest, list) else manifest['files']
        if not entries:
            raise ValueError('Empty AndroidTest fixture manifest: ' + relative)
        seen = set()
        for item in entries:
            name = item['file']
            if name in seen:
                raise ValueError('Duplicate fixture manifest entry: ' + relative)
            seen.add(name)
            child = (PurePosixPath(relative).parent / name).as_posix()
            data = read(child)
            if data is not None:
                if checked[child]['sha256'] != item['sha256']:
                    raise ValueError('AndroidTest fixture hash mismatch: ' + child)
                if 'bytes' in item and len(data) != item['bytes']:
                    raise ValueError('AndroidTest fixture byte count mismatch: ' + child)
            manifest_entries += 1
    if missing:
        raise FileNotFoundError('Provide local AndroidTest fixtures listed in TEST_FIXTURES.md: ' +
                                ', '.join(sorted(missing)))
    opening = read('replay/game_opening.png')
    if len(opening) < 24 or opening[:8] != b'\x89PNG\r\n\x1a\n' or opening[12:16] != b'IHDR':
        raise ValueError('replay/game_opening.png must be an original PNG')
    width, height = struct.unpack('>II', opening[16:24])
    if (width, height) not in ((1280, 720), (1920, 1080)):
        raise ValueError('replay/game_opening.png requires 1280x720 or 1920x1080')
    wait = 'opening-opponent-wait-probe/code139-frame0008-review.jpg'
    if checked[wait]['sha256'] != 'ff743846098fd3ec23ddfda81249c5a94b9b69df0e10a327d07f881ab7e79655':
        raise ValueError('Opponent wait fixture differs from the AndroidTest contract')
    return dict(passed=True, fixture_files=len(checked), manifest_entries=manifest_entries,
                lifecycle_fixture=dict(checked['replay/game_opening.png'], width=width, height=height,
                                       expected_android_state='IN_GAME'),
                image_files_copied=0, device_commands=0)


if __name__ == '__main__':
    print(json.dumps(verify()))
