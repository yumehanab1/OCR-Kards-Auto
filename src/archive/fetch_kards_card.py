"""
fetch_kards_card.py - query the official KARDS GraphQL API for one or more
cards (zh language) and download their images, for style-comparison against
in-game hover screenshots.

Usage:
  python fetch_kards_card.py --q 轻步兵
  python fetch_kards_card.py --q "Light Infantry" --lang en
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse

import requests

API = "https://herokuapi.kards.com/graphql"
HEADERS = {
    "accept": "*/*",
    "content-type": "application/json",
    "origin": "https://www.kards.com",
    "referer": "https://www.kards.com/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

QUERY = """query getCards($language: String, $offset: Int, $q: String) {
  cards(language: $language, first: 20, offset: $offset, q: $q) {
    pageInfo { count hasNextPage __typename }
    edges {
      node {
        id cardId importId reserved
        json
        imageUrl: image(language: $language)
        thumbUrl: image(type: thumb, language: $language)
        __typename
      }
      __typename
    }
    __typename
  }
}"""


def fetch(q: str, lang: str) -> dict:
    payload = {
        "operationName": "getCards",
        "variables": {"language": lang, "offset": 0, "q": q},
        "query": QUERY,
    }
    r = requests.post(API, headers=HEADERS, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def parse_json_field(node: dict) -> dict:
    jf = node.get("json")
    if isinstance(jf, str):
        try:
            return json.loads(jf)
        except Exception:
            return {}
    return jf or {}


def download(url: str, dest: str) -> bool:
    r = requests.get(url, headers={"User-Agent": HEADERS["user-agent"]}, timeout=30)
    if r.status_code != 200:
        print(f"  download failed {r.status_code}: {url}")
        return False
    with open(dest, "wb") as f:
        f.write(r.content)
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--q", required=True, help="search query (name)")
    ap.add_argument("--lang", default="zh")
    ap.add_argument("--out", default="card_db_test")
    ap.add_argument("--download", action="store_true", help="also download images")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    data = fetch(args.q, args.lang)
    try:
        edges = data["data"]["cards"]["edges"]
        total = data["data"]["cards"]["pageInfo"]["count"]
    except Exception:
        print("unexpected response:", json.dumps(data, ensure_ascii=False)[:800])
        return 1
    print(f"query '{args.q}' -> {total} results")
    for edge in edges:
        node = edge["node"]
        meta = parse_json_field(node)
        print(f"\nid={node['id']} cardId={node['cardId']}")
        print(f"  json keys: {list(meta.keys())[:20]}")
        # common fields
        for k in ("name", "type", "rarity", "kredits", "nation", "set", "cardId"):
            if k in meta:
                print(f"  {k}: {meta[k]}")
        print(f"  imageUrl: {node['imageUrl']}")
        print(f"  thumbUrl: {node['thumbUrl']}")
        if args.download and node.get("thumbUrl"):
            fn = os.path.join(args.out, f"{node['cardId'] or node['id']}_thumb.png")
            if download(node["thumbUrl"], fn):
                print(f"  downloaded -> {fn}")
        if args.download and node.get("imageUrl"):
            fn = os.path.join(args.out, f"{node['cardId'] or node['id']}_full.png")
            if download(node["imageUrl"], fn):
                print(f"  downloaded -> {fn}")
        time.sleep(0.3)
    return 0


if __name__ == "__main__":
    sys.exit(main())
