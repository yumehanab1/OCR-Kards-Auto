"""
turn_test.py - run one full automated turn via TurnEngine (M3 integration test).

Flow: while in a game, this waits for your turn, scans, deploys affordable
units (cheap first, skipping orders), then clicks end turn.

It moves the mouse and plays cards for real. Only run during a game you are
OK with auto-playing (e.g. casual).

Usage:
  .venv\\Scripts\\python.exe src\\turn_test.py --seconds 180
  .venv\\Scripts\\python.exe src\\turn_test.py --seconds 180 --no-wait

While it runs it also samples the end-turn button area once a second into
shots/turn_obs/ and prints its template score. That is the data needed to tell
YOUR turn from the OPPONENT's turn (the current engine assumes the end-turn
button is only present on your turn - must be confirmed live).
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2  # noqa: E402

from hand_scanner_v2 import _load_db  # noqa: E402
from turn_engine import END_TURN_MIN_SCORE, TurnEngine  # noqa: E402
from ui_state import classify, load_meta, load_states, load_templates, match_one  # noqa: E402
from win import (  # noqa: E402
    bring_to_front,
    capture_client_bgr,
    find_by_process,
    set_dpi_aware,
    set_window_client_size,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OBS_DIR = os.path.join(PROJECT_ROOT, "shots", "turn_obs")

# Client-coord box around the end-turn button, from config/templates.json.
BTN_BOX = (1090, 430, 200, 90)


def describe_region(frame):
    """Cheap colour stats of the end-turn button box - the live discriminator."""
    x, y, w, h = BTN_BOX
    reg = frame[y:y + h, x:x + w]
    hsv = cv2.cvtColor(reg, cv2.COLOR_BGR2HSV)
    score, _ = match_one(frame, _TPL["end_turn_btn"])
    return {
        "score": score,
        "mean_bgr": tuple(int(v) for v in reg.mean(axis=(0, 1))),
        "sat": float(hsv[:, :, 1].mean()),
        "val": float(hsv[:, :, 2].mean()),
    }


def window_is_capturable(hwnd) -> bool:
    """
    True when the kards window is on screen (not minimised, not fully hidden
    behind another window). The mss capture fallback needs this.

    ★ 实现已挪到 win.window_is_capturable —— 主循环(main_loop)也要在**每个
    tick 动作之前**用它:机器上只要有另一个自动化在跑(ALAS/MAA 那类),它就会
    移动鼠标 + 抢前台焦点,于是截图抓到别人的窗口、让行判据一路为真,
    表现成"扫描 0.8 秒返回 0 张牌"。这里保留同名包装是为了不破坏老脚本。
    """
    from win import window_is_capturable as _impl

    return _impl(hwnd)


def wait_for_game(hwnd, states, timeout=600.0):
    """Block until the classifier says we are in a match. Returns True on success."""
    print(f"waiting for you to enter a match (up to {timeout:.0f}s)...")
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout:
        frame = capture_client_bgr(hwnd)
        if frame is not None:
            state, _ = classify(frame, _TPL, states)
            if state != last:
                print(f"    [{time.time() - t0:5.0f}s] screen state: {state}")
                last = state
            if state == "in_game":
                # give the mulligan/intro animation a moment to finish
                print("    in_game detected - starting in 4s")
                time.sleep(4.0)
                return True
        time.sleep(1.5)
    print("timed out waiting for a match")
    return False


def main() -> int:
    global _TPL
    set_dpi_aware()
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=150, help="run duration")
    ap.add_argument("--no-wait", action="store_true",
                    help="skip the interactive Enter prompt (for unattended runs)")
    ap.add_argument("--wait-for-game", action="store_true",
                    help="with --no-wait: poll until the classifier sees in_game, "
                         "then start automatically (fully unattended)")
    ap.add_argument("--wait-timeout", type=float, default=600.0,
                    help="how long to wait for a match with --wait-for-game")
    ap.add_argument("--observe", action="store_true", default=True,
                    help="save end-turn button samples (default on)")
    ap.add_argument("--debug", action="store_true",
                    help="verbose per-probe scan output (bbox + classification)")
    ap.add_argument("--record-kredits", action="store_true",
                    help="dump every isolated Kredits numeral to "
                         "shots/kredits/numerals/ for building a digit template bank")
    args = ap.parse_args()

    wins = find_by_process("kards")
    if not wins:
        print("no kards window (游戏没在运行?)")
        return 1
    hwnd = wins[0]["hwnd"]
    print(f"kards hwnd={hwnd} title={wins[0].get('title')!r}")

    # Capture relies on an mss screen grab (PrintWindow gives black for this
    # GPU window), so the window MUST be visible and unobstructed. A minimised
    # or covered window makes hover-diff report bogus full-screen panels and
    # the scanner invents cards - that wasted a whole live run.
    if not window_is_capturable(hwnd):
        print("!! 游戏窗口被最小化或被遮挡,截图不可信。")
        print("!! 请把 KARDS 窗口恢复并保持在前台,然后重跑。")
        return 1

    bring_to_front(hwnd)
    time.sleep(0.5)
    set_window_client_size(hwnd, 1280, 720, 100, 100)
    time.sleep(1.0)
    frame = capture_client_bgr(hwnd)
    print(f"client frame: {None if frame is None else frame.shape}")
    if frame is None:
        print("截图失败 - 窗口可能不可见")
        return 1

    _load_db()
    meta = load_meta(os.path.join(PROJECT_ROOT, "config", "templates.json"))
    _TPL = load_templates(meta)
    states = load_states(os.path.join(PROJECT_ROOT, "config", "states.json"))

    eng = TurnEngine(hwnd, _TPL, debug=args.debug,
                     record_kredits=args.record_kredits)
    print(f"=== turn engine test ({args.seconds}s, "
          f"end-turn threshold {END_TURN_MIN_SCORE}) ===")

    if args.wait_for_game:
        if not wait_for_game(hwnd, states, args.wait_timeout):
            return 1
    elif args.no_wait:
        print("starting immediately (--no-wait, no --wait-for-game)")
    else:
        print("Get into a game; it will play your turns automatically.")
        input("Press Enter when you're inside a match "
              "(it will wait for your turn)... ")

    os.makedirs(OBS_DIR, exist_ok=True)
    obs_n = 0
    turns_seen = 0
    total_deploys = 0
    deadline = time.time() + args.seconds
    last_state = None
    prev_et = None
    while time.time() < deadline:
        t0 = time.time()
        frame = capture_client_bgr(hwnd)
        if frame is None:
            print("[no frame]")
            time.sleep(1.0)
            continue

        # --- observation: end-turn button presence + colour ---
        d = describe_region(frame)
        et = d["score"] >= END_TURN_MIN_SCORE
        if et != prev_et:
            print(f"    >> end-turn button {'APPEARED' if et else 'GONE'} "
                  f"(score {d['score']:.3f}, sat {d['sat']:.0f}, val {d['val']:.0f})")
            prev_et = et
            if args.observe:
                # keep one sample per transition - both states are what we need
                cv2.imwrite(os.path.join(OBS_DIR, f"obs_{obs_n:04d}_et{int(et)}.png"),
                            frame[BTN_BOX[1]:BTN_BOX[1] + BTN_BOX[3],
                                  BTN_BOX[0]:BTN_BOX[0] + BTN_BOX[2]])
                obs_n += 1

        st = eng.think()
        if st == "deployed":
            total_deploys += 1
        if st == "our_turn":
            turns_seen += 1
        if st != last_state:
            print(f"[{st}]  (phase={eng.phase} btn_score={d['score']:.3f} "
                  f"sat={d['sat']:.0f})")
            last_state = st
        elapsed = time.time() - t0
        time.sleep(max(0.2, 1.0 - elapsed))

    print(f"time up. end-turn samples saved to {OBS_DIR} ({obs_n} frames)")
    print(f"totals over the run: turns_detected={turns_seen} "
          f"deploy_attempts={total_deploys} "
          f"last_turn_deployed={eng.deployed_this_turn}")
    return 0


_TPL: dict = {}

if __name__ == "__main__":
    sys.exit(main())
