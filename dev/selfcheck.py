"""
selfcheck.py - M0 smoke test. Verifies:
  1) we can enumerate windows,
  2) screen capture works,
  3) window capture path compiles (capture of a chosen window, if any).

Usage:  python selfcheck.py [--fragment KARDS]
"""

from __future__ import annotations

import argparse
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from capture import cmd_list  # noqa: E402
from win import (  # noqa: E402
    acquire_single_instance_lock,
    capture_client_bgr,
    capture_screen_bgr,
    find_windows,
    set_dpi_aware,
)


def check_single_instance() -> bool:
    """
    ★ 单实例锁自检 —— **必须跨进程测**。

    实测踩过:两个 main_loop 同时跑,互相把对方的光标移走,于是双方的让行判据
    一路为真,扫描全在第一个探针中止(日志 `hand scan: 0 cards in 0.8s`,
    看起来像功能坏了)。

    ★★ 而且第一版的锁**在同一个进程里自测是通过的,跨进程却不生效**:
      它用 `GetLastError() == ERROR_ALREADY_EXISTS` 判断,而 GetLastError 是
      线程级的,CreateMutex 之后任何 Win32 调用都会覆盖它 —— 我在后面写了
      `import win32api`,首次导入会加载 DLL,直接把"已存在"吃掉了。
      所以自检必须真的**起一个子进程**去持有锁,再由父进程申请,才测得出来。

    做法:子进程拿到锁后把一个标记文件写出来,父进程等它写出来后申请锁 ——
    此时父进程必须**拿不到**。子进程随后退出,父进程再申请必须**拿得到**
    (证明进程退出后系统会自动释放,不会有残留锁)。
    """
    import subprocess
    import tempfile
    import time

    src_dir = os.path.dirname(os.path.abspath(__file__))
    name = "kards_auto_selfcheck_probe"
    flag = os.path.join(tempfile.gettempdir(), "kards_lock_probe.txt")
    if os.path.exists(flag):
        os.remove(flag)

    child_code = (
        "import sys, time\n"
        f"sys.path.insert(0, r'{src_dir}')\n"
        "from win import acquire_single_instance_lock\n"
        f"ok, why = acquire_single_instance_lock({name!r})\n"
        f"open(r'{flag}', 'w').write(('HELD' if ok else 'BUSY') + ' ' + why)\n"
        "time.sleep(6)\n"
    )
    # ★ 用文件而不是管道跟子进程通气:在被限制的环境里管道容易踩到权限问题
    proc = subprocess.Popen([sys.executable, "-c", child_code])
    deadline = time.time() + 20
    while time.time() < deadline and not os.path.exists(flag):
        time.sleep(0.1)
    if not os.path.exists(flag):
        proc.kill()
        print("   FAIL: 子进程没在 20 秒内写出标记(子进程起不来?)")
        return False
    with open(flag, "r", encoding="utf-8") as f:
        child_state = f.read().strip()
    os.remove(flag)
    if not child_state.startswith("HELD"):
        proc.kill()
        print(f"   FAIL: 子进程自己都没拿到锁({child_state})")
        return False
    print(f"   (子进程说自己:{child_state})")

    # ① 子进程正持有 -> 父进程必须拿不到
    ok, why = acquire_single_instance_lock(name)
    held_ok = (not ok) and why == "held-by-other"
    print(f"   {'OK ' if held_ok else 'FAIL'} 子进程持锁时,父进程申请 -> "
          f"ok={ok} why={why!r} "
          f"{'(被正确拒绝)' if held_ok else '(锁没生效!)'}")

    # ② 子进程退出后 -> 锁必须自动释放(不留残留锁)
    proc.terminate()
    proc.wait(timeout=15)
    deadline = time.time() + 10
    freed_ok = False
    while time.time() < deadline:
        ok2, why2 = acquire_single_instance_lock(name)
        if ok2:
            freed_ok = True
            break
        time.sleep(0.3)
    print(f"   {'OK ' if freed_ok else 'FAIL'} 子进程退出后,父进程申请 -> "
          f"{'拿到(系统已自动释放)' if freed_ok else '仍拿不到(可能留了残留锁)'}")
    return held_ok and freed_ok


def main() -> int:
    set_dpi_aware()
    ap = argparse.ArgumentParser()
    ap.add_argument("--fragment", default="", help="window title fragment")
    ap.add_argument("--outdir", default="shots")
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    ok = True

    print("== 0) single-instance lock ==")
    ok &= check_single_instance()

    print("== 1) window enumeration ==")
    wins = find_windows(args.fragment) if args.fragment else find_windows("")
    print(f"visible windows: {len(wins)}")
    for w in wins[:15]:
        print(f"   hwnd={w['hwnd']} {w['title'][:60]}")
    if not wins:
        print("   WARNING: no visible windows (running in a non-interactive session?)")

    print("== 2) screen capture ==")
    shot = capture_screen_bgr(0)
    if shot is None:
        print("   FAIL: screen capture returned None")
        ok = False
    else:
        p = os.path.join(args.outdir, "screen_test.png")
        import cv2

        cv2.imwrite(p, shot)
        print(f"   OK: {shot.shape[1]}x{shot.shape[0]} -> {p}")

    print("== 3) window client capture ==")
    target = None
    if args.fragment:
        cand = find_windows(args.fragment)
        if cand:
            target = cand[0]
    if target is None:
        # fallback: any non-trivial window
        for w in wins:
            r = w["rect"]
            if r[2] - r[0] > 200 and r[3] - r[1] > 150:
                target = w
                break
    if target is None:
        print("   SKIP: no suitable window to test")
    else:
        import cv2

        img = capture_client_bgr(target["hwnd"])
        if img is None:
            print(f"   WARN: client capture None for '{target['title'][:40]}'")
        else:
            p = os.path.join(args.outdir, "win_test.png")
            cv2.imwrite(p, img)
            print(f"   OK: '{target['title'][:40]}' {img.shape[1]}x{img.shape[0]} -> {p}")

    print("== done ==")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
