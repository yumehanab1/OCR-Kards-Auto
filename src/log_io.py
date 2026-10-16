"""Bounded UTF-8 log tails and lossless startup archiving."""
from __future__ import annotations

import os
from pathlib import Path
import time

MAX_TAIL_BYTES = 128 * 1024
MAX_TAIL_LINES = 400
MAX_LINE_CHARS = 2048
READ_BLOCK_BYTES = 64 * 1024
ARCHIVE_BYTES = 8 * 1024 * 1024
TRUNCATED = ' …[显示已截断，完整内容保留在日志]'


def display_line(line):
    return line if len(line) <= MAX_LINE_CHARS else line[:MAX_LINE_CHARS]+TRUNCATED


def tail_stream(stream, n=400):
    """Read at most 128 KiB, even for a single giant line or huge n."""
    n = max(0, min(int(n), MAX_TAIL_LINES))
    stream.seek(0, os.SEEK_END)
    end = stream.tell()
    if n == 0: return []
    back = min(end, MAX_TAIL_BYTES, max(4096, n*512))
    stream.seek(end-back)
    data = stream.read(back)
    partial = end > back
    if partial:
        newline = data.find(b'\n')
        if newline >= 0:
            data = data[newline+1:]
        else:
            # No boundary in the window: show a bounded suffix of the giant line.
            return ['[超长日志行尾部] '+display_line(data.decode('utf-8', 'ignore'))]
    return [display_line(line) for line in data.decode('utf-8', 'replace').splitlines()[-n:]]


def tail_lines(path, n=400):
    try:
        with open(path, 'rb') as stream:
            return tail_stream(stream, n)
    except OSError:
        # File may be absent or temporarily renamed during a new session.
        return []


def revision(path):
    try:
        stat = os.stat(path)
        return f'{stat.st_dev}:{stat.st_ino}:{stat.st_size}:{stat.st_mtime_ns}'
    except OSError:
        return ''


def archive_large(path, limit=ARCHIVE_BYTES):
    """Rename oversized idle logs; no copying, truncation, or deletion."""
    path = Path(path)
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return None
    if size < limit: return None
    folder = path.parent/'archive'
    folder.mkdir(exist_ok=True)
    stamp = time.strftime('%Y%m%d_%H%M%S')+f'_{time.time_ns()}'
    destination = folder/f'{path.stem}_{stamp}{path.suffix}'
    path.rename(destination)
    return destination
