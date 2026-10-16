"""Build a PC card DB from a captured official snapshot plus reviewed patches.

Dry run by default. No network, game input, rule generation or publishing.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / 'card_db/patches/2026-10-15.json'


def get_field(record, path):
    value = record
    for key in path.split('.'):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def set_field(record, path, value):
    keys = path.split('.')
    for key in keys[:-1]:
        record = record.setdefault(key, {})
    record[keys[-1]] = copy.deepcopy(value)


def build(snapshot, patch):
    result = copy.deepcopy(snapshot)
    cards = result['cards']
    index = {card['cardId']: card for card in cards}
    if len(index) != len(cards):
        raise ValueError('Duplicate cardId in official snapshot')
    for change in patch['cards']:
        record = index[change['cardId']]['json']
        for path, values in change['fields'].items():
            current = get_field(record, path)
            if current not in (values['before'], values['after']):
                raise ValueError(f"Unreviewed upstream change: {change['cardId']}.{path}")
            set_field(record, path, values['after'])
        if change.get('runtime'):
            index[change['cardId']]['runtime'] = copy.deepcopy(change['runtime'])
    # Base entries precede their veteran forms when names and costs coincide.
    # This preserves card_match's first-entry name index deterministically.
    result['cards'] = sorted(cards, key=lambda c: (
        c['json'].get('kredits', 99), c['cardId']))
    result['metadata'] = dict(source=patch['snapshot_source'],
        game_version_id=patch['base_game_version_id'],
        reviewed_patch=patch['effective_date'], reviewed_languages=['zh-Hans', 'en-EN'],
        note='Other localized descriptions retain the official API snapshot; PC uses simplified Chinese.',
        patch_source=patch['announcement'], patch_file='patches/2026-10-15.json')
    result['metadata']['retired_hash_names'] = patch.get('retired_hash_names', [])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--patch', type=Path, default=PATCH)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    raw = args.snapshot.read_bytes()
    patch = json.loads(args.patch.read_text(encoding='utf8'))
    if hashlib.sha256(raw).hexdigest() != patch['snapshot_sha256']:
        raise ValueError('Snapshot hash differs from reviewed source')
    data = build(json.loads(raw), patch)
    if args.write:
        destination = ROOT / 'card_db/kards_data.json'
        destination.write_text(json.dumps(data, ensure_ascii=False) + '\n', encoding='utf8')
    print(json.dumps(dict(cards=len(data['cards']), patched=len(patch['cards']), written=args.write)))


if __name__ == '__main__':
    main()
