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

    # ★ 用**二进制**打开再自己解码:文本模式 + 从中间 seek 会把多字节字符切断
    #   (第一版就是在这里抛的 TypeError,顺手也避开了"半个汉字"的坑)。
    #   日志才几百 KB,直接整读一遍取末尾 N 行最简单,不用手写分块回退。
    with open(path, "rb") as f:
        head = f.read().decode("utf-8", "replace").splitlines()
        for ln in head[-max(0, tail):] if tail > 0 else []:
            if not only_key or any(w in ln for w in KEY_WORDS):
                # ★ 每一行都 flush:输出被重定向到文件时 stdout 是**块缓冲**,
                #   不 flush 的话前面这段历史要等缓冲区满才出现(实测"预览是空的")。
                print(ln, flush=True)
        f.seek(0, os.SEEK_END)

        print("-" * 70, flush=True)
        print(f"实时跟随中:{path}   (Ctrl+C 退出)", flush=True)
        print("-" * 70, flush=True)
        buf = b""
        while True:
            chunk = f.read()
            if chunk:
                buf += chunk
                # 只按完整的行输出,最后一段残行留到下一次(避免打出半个字符)
                *lines, buf = buf.split(b"\n")
                for raw in lines:
                    line = raw.decode("utf-8", "replace").rstrip("\r")
                    if not only_key or any(w in line for w in KEY_WORDS):
                        print(line, flush=True)
            else:
                time.sleep(poll)


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
