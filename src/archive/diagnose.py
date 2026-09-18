"""diagnose.py - list visible windows with pid, process name and title.
Helps identify the exact window/process of the game for automation config.
"""
import ctypes
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import win32con
import win32process
import win32gui
from win import find_windows

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def proc_name(pid: int) -> str:
    h = None
    try:
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return "?"
        buf = ctypes.create_unicode_buffer(260)
        size = ctypes.c_ulong(260)
        ctypes.windll.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
        return os.path.basename(buf.value)
    except Exception:
        return "?"
    finally:
        if h:
            ctypes.windll.kernel32.CloseHandle(h)


def main() -> None:
    for w in find_windows(""):
        title = w["title"].strip()
        if not title:
            continue
        pid = win32process.GetWindowThreadProcessId(w["hwnd"])[1]
        print(f"pid={pid:<7} {proc_name(pid):<24} hwnd={w['hwnd']:<9} {title!r}")


if __name__ == "__main__":
    main()
