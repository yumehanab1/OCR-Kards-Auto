"""
vision_ask.py - send a screenshot to a vision model and print its description.

Uses the DEEPSEEK_API_KEY stored in ~/.dsh/.credentials.yaml and the model
name deepseek-v4-flash-vision-exp (configurable via --model).

Usage:
  python vision_ask.py --image shots/x.png --prompt "describe the layout"
  python vision_ask.py --dir C:\\path\\to\\pngs --prompt "..."   (all pngs)
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import sys

import cv2
import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CRED = os.path.expanduser("~/.dsh/.credentials.yaml")
API = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-v4-flash-vision-exp"


def read_key() -> str:
    with open(CRED, "r", encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"DEEPSEEK_API_KEY:\s*\"?([A-Za-z0-9_.\-]+)", text)
    if not m:
        raise SystemExit("DEEPSEEK_API_KEY not found in credentials")
    return m.group(1)


def image_to_data_url(path: str, max_side: int = 1024) -> str:
    img = cv2.imread(path)
    if img is None:
        raise SystemExit(f"cannot read image {path}")
    h, w = img.shape[:2]
    if max(h, w) > max_side:
        scale = max_side / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)),
                         interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    if not ok:
        raise SystemExit("encode failed")
    b64 = base64.b64encode(buf.tobytes()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def ask(key: str, data_url: str, prompt: str, model: str) -> str:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        # reasoning model: give it room to think AND answer
        "max_tokens": 4000,
    }
    r = requests.post(
        API, headers={"Authorization": f"Bearer {key}"},
        json=payload, timeout=300,
    )
    if r.status_code != 200:
        return f"HTTP {r.status_code}: {r.text[:500]}"
    msg = r.json()["choices"][0]["message"]
    content = msg.get("content")
    if content:
        return content
    # fall back to reasoning trace if content empty
    return msg.get("reasoning_content") or "(no content)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default="", help="one image path")
    ap.add_argument("--dir", default="", help="directory; ask for every png inside")
    ap.add_argument("--prompt", required=True, help="question for the vision model")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--max-side", type=int, default=1024)
    args = ap.parse_args()

    key = read_key()
    images = []
    if args.image:
        images = [args.image]
    elif args.dir:
        images = sorted(
            os.path.join(args.dir, f)
            for f in os.listdir(args.dir)
            if f.lower().endswith(".png")
        )
    if not images:
        print("no images given")
        return 1

    for path in images:
        print(f"\n===== {os.path.basename(path)} =====")
        try:
            data_url = image_to_data_url(path, args.max_side)
            print(ask(key, data_url, args.prompt, args.model))
        except Exception as e:
            print(f"ERROR: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
