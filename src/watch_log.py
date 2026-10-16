"""
watch_log.py - 实时看 main_loop 的日志(只读,不碰游戏)。

为什么不用 `Get-Content -Wait`:
  `logs/main_loop.log` 是 **UTF-8**,而中文 Windows 的控制台默认是 **GBK** ——
  直接 tail 出来中文全是乱码(`╬╥╨╘` 那种),等于看不见。
  这个脚本自己把控制台代码页设成 UTF-8 再输出,所以中文是正常的。

用法(在**你自己的**终端里开一个窗口,然后就不用管了):
    .venv\\Scripts\\python.exe src\\watch_log.py
    .venv\\Scripts\\python.exe src\\watch_log.py --tail 60      # 一开始多显示几行
    .venv\\Scripts\\python.exe src\\watch_log.py --only-key     # 只看关键行

按键:回车/Ctrl+C 退出。
★ 它**只读日志文件**,不会动鼠标、不会碰游戏窗口,和主循环不冲突。
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import log_io

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(PROJECT_ROOT, "logs", "main_loop.log")


def _force_utf8_console():
    """把控制台代码页设成 65001(UTF-8),否则中文会是乱码。"""
    try:
        os.system("chcp 65001 > nul")
    except Exception:
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


# ---- 关键行:默认全打;--only-key 时只留这些(盯实机验证时用) ----
KEY_WORDS = (
    "[turn] our turn starts",
    "战场基准",
    "支援阵线已满",
    "落点参考行",
    "deployed",
    "部署成功",
    "部署被拒绝",
    "[attack]",
    "[move]",
    "攻击阶段结束",
    "上前线阶段结束",
    "round",
    "state ->",
    "main_loop start",
    "⚠️",
    "Traceback",
)


def follow(path, tail, only_key, poll=0.4):
    # 等日志文件出现(主循环刚起时可能还没有)
    for _ in range(100):
        if os.path.exists(path):
            break
        time.sleep(0.2)
    else:
        print(f"等不到日志文件:{path}")
        return 1

    print("-" * 70, flush=True)
    print(f"实时跟随中:{path}   (Ctrl+C 退出)", flush=True)
    print("-" * 70, flush=True)
    for line in iter_follow(path, tail, poll):
        if not only_key or any(w in line for w in KEY_WORDS):
            print(line, flush=True)


def iter_follow(path, tail=30, poll=0.4, sleep=time.sleep):
    """Read short-lived handles so Windows writers can archive old sessions."""
    with open(path, 'rb') as stream:
        head = log_io.tail_stream(stream, tail)
        offset = stream.tell()
        stat = os.fstat(stream.fileno())
        identity = (stat.st_dev, stat.st_ino)
    yield from head
    buf = b''
    while True:
        rotated = False
        try:
            with open(path, 'rb') as stream:
                stat = os.fstat(stream.fileno())
                current = (stat.st_dev, stat.st_ino)
                if current != identity or stat.st_size < offset:
                    head = log_io.tail_stream(stream, tail)
                    offset = stream.tell()
                    identity = current
                    buf = b''
                    rotated = True
                else:
                    stream.seek(offset)
                    chunk = stream.read(log_io.READ_BLOCK_BYTES)
                    offset = stream.tell()
        except FileNotFoundError:
            sleep(poll)
            continue
        if rotated:
            yield from head
        elif chunk:
            buf += chunk
            *lines, buf = buf.split(b'\n')
            for raw in lines:
                yield log_io.display_line(raw.decode('utf-8', 'replace').rstrip('\r'))
            if len(buf) > log_io.MAX_TAIL_BYTES:
                buf = buf[-log_io.MAX_TAIL_BYTES:]
        else:
            sleep(poll)


def main():
    ap = argparse.ArgumentParser(description="实时看 KARDS main_loop 日志(只读)")
    ap.add_argument("--tail", type=int, default=30, help="一开始先显示多少行历史")
    ap.add_argument("--only-key", action="store_true",
                    help="只显示关键行(回合/部署/攻击/上前线),滤掉扫描噪音")
    args = ap.parse_args()
    _force_utf8_console()
    try:
        return follow(LOG, args.tail, args.only_key)
    except KeyboardInterrupt:
        print("\n(退出)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
