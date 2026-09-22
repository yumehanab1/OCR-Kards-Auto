"""win_capture_test.py - 窗口截图判据的离线用例(**不需要游戏窗口**)。

钉住的证据帧(`shots/win_capture/`,都是 2026-09-15 实机抓的):
  · `printwindow_shell.png`   —— PrintWindow 在 KARDS(`UnrealWindow`)上返回的**空壳图**:
       纯白 40.5% + 纯黑 58.7% = **99.2%**;mean=105、**std=125**(所以它**不是平坦图**)。
  · `game_frame_scan.png` / `game_frame_attack.png` —— 同一天同一局的**真实画面**:
       纯白 **0.0%**、纯黑 <= 7.1%。

这个 bug 的形状值得钉死:那张空壳图 mean/std 都"正常",`_is_blank` 的"平坦"判据
**按设计放它过去** -> 永远轮不到"按矩形抓屏"那条实机主路 -> 主循环每一 tick 拿到的
都是垃圾图 -> 判不出界面 -> 一直 `state -> None`,**一次都不动作**,而日志里只有一行
`state -> None`(看不出来)。所以用例要同时守住两件事:
  ① 空壳图必须被 `_is_shell_fill` 判掉,**且 `_is_blank` 仍然放它过去**
     (把这个"为什么需要第二道判据"钉住,免得以后有人把两道判据合并回去);
  ② 真实画面两道判据都必须放行;
  ③ `capture_client_bgr` 的**选择逻辑**:PrintWindow 给空壳时必须走屏幕退路;
     PrintWindow 给真画面时不该白花那一次抓屏(用替身函数数调用次数)。

用法:
  .venv\\Scripts\\python.exe dev\\win_capture_test.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import win  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIN = os.path.join(ROOT, "shots", "win_capture")
SHELL = os.path.join(PIN, "printwindow_shell.png")
REAL = [os.path.join(PIN, "game_frame_scan.png"),
        os.path.join(PIN, "game_frame_attack.png")]

FAILS = []


def check(ok: bool, msg: str) -> None:
    print(("  OK  " if ok else "  ✗   ") + msg)
    if not ok:
        FAILS.append(msg)


def frac_white_black(img) -> float:
    gray = img.mean(axis=2) if img.ndim == 3 else img.astype(np.float32)
    return float(((gray >= 250.0) | (gray <= 5.0)).mean())


def main() -> int:
    for p in [SHELL] + REAL:
        if not os.path.exists(p):
            print("缺证据帧:", p)
            return 1
    shell = cv2.imread(SHELL)
    print("=" * 74)
    print(f"空壳图 {os.path.basename(SHELL)}:纯白+纯黑 = "
          f"{frac_white_black(shell) * 100:.1f}%  "
          f"mean={shell.mean():.1f} std={shell.std():.1f}")

    # ① 空壳图:第一道判据放行(这是这个 bug 的成因),第二道必须挡掉
    check(not win._is_blank(shell),
          "空壳图**不是**平坦图 -> `_is_blank` 按设计放行(否则这个 bug 不会发生)")
    check(win._is_shell_fill(shell),
          "空壳图被 `_is_shell_fill` 挡掉  <- 修的就是这一条")

    # ② 真实画面:两道判据都放行
    for p in REAL:
        img = cv2.imread(p)
        print(f"真画面 {os.path.basename(p)}:纯白+纯黑 = "
              f"{frac_white_black(img) * 100:.1f}%  "
              f"mean={img.mean():.1f} std={img.std():.1f}")
        check(not win._is_blank(img), f"{os.path.basename(p)} 不是平坦图")
        check(not win._is_shell_fill(img), f"{os.path.basename(p)} 不被当成空壳")

    # ③ 选择逻辑(替身,不需要窗口)
    calls = {"screen": 0}
    real = cv2.imread(REAL[0])

    def fake_pw(hwnd):
        return shell.copy()

    def fake_screen(hwnd):
        calls["screen"] += 1
        return real.copy()

    keep_pw, keep_scr = win._capture_client_printwindow, win._capture_client_screenrect
    try:
        win._capture_client_printwindow = fake_pw
        win._capture_client_screenrect = fake_screen
        got = win.capture_client_bgr(1234)
        check(got is not None and got.shape == real.shape
              and np.array_equal(got, real),
              "PrintWindow 给空壳 -> `capture_client_bgr` 走**屏幕退路**(返回真画面)")
        check(calls["screen"] == 1, f"屏幕退路正好被调用 1 次(实得 {calls['screen']})")

        # PrintWindow 给真画面 -> 直接用,不该再抓一次屏
        calls["screen"] = 0
        win._capture_client_printwindow = lambda hwnd: real.copy()
        got = win.capture_client_bgr(1234)
        check(got is not None and np.array_equal(got, real),
              "PrintWindow 给真画面 -> 直接采用")
        check(calls["screen"] == 0,
              f"这种时候不该白花一次抓屏(实得 {calls['screen']} 次)")

        # 两条路都给空壳 -> 返回 PrintWindow 那张(调用方靠它判"看不见")
        calls["screen"] = 0
        win._capture_client_printwindow = lambda hwnd: shell.copy()
        win._capture_client_screenrect = lambda hwnd: shell.copy()
        got = win.capture_client_bgr(1234)
        check(got is not None and np.array_equal(got, shell),
              "两条路都拿不到真画面 -> 原样返回(不许假装成功)")
        check(calls["screen"] == 0, "这条路上屏幕退路被跳过(它给的也是空壳)")
    finally:
        win._capture_client_printwindow = keep_pw
        win._capture_client_screenrect = keep_scr

    print("\n⑤ 找游戏窗口:名字里有 kards 的**不许**被当成游戏(2026-09-16 用户实测)")
    print("    现象:点面板「开始」之后,面板自己被引擎强制成 1280x720 ——")
    print("    因为面板 exe 叫 `KARDS AUTO.exe`,也包含 'kards'。")
    check(win.looks_like_game("kards-Win64-Shipping.exe", "UnrealWindow") is True,
          "游戏本体(精确名 + UnrealWindow)-> 是游戏")
    check(win.looks_like_game("kards.exe", "") is True,
          "启动器 kards.exe 也认(精确名)")
    check(win.looks_like_game("KARDS AUTO.exe",
                              "WindowsForms10.Window.8.app.0.34f5582") is False,
          "★ 我们的面板 exe -> **不是**游戏(这条就是那个 bug)")
    check(win.looks_like_game("python.exe", "TkTopLevel") is False,
          "python.exe(探针/工具)-> 不是游戏")
    check(win.looks_like_game("某游戏.exe", "UnrealWindow") is True,
          "换了 exe 名但窗口类还是 UnrealWindow -> 仍认(给游戏更新留余地)")
    check(win.looks_like_game("KARDS AUTO.exe", "UnrealWindow") is False,
          "★ 精确名/排除名单**优先于**窗口类(面板就算类名撞上也不认)")
    check(win.looks_like_game("", "UnrealWindow") is False, "空进程名 -> 不是")
    # 真的去枚举一遍:面板现在开着时,它**不该**出现在结果里
    try:
        found = win.find_by_process("kards")
        names = sorted({w.get("exe", "") for w in found})
        check(all("kards auto" not in n for n in names),
              f"实枚举一遍:结果里不许有我们的面板 exe(实得 {names or '空'})")
    except Exception as e:
        check(False, f"枚举失败:{type(e).__name__}: {e}")

    print("=" * 74)
    if FAILS:
        print(f"{len(FAILS)} 条不通过")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
