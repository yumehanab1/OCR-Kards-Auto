"""
ui_state.py - classify the current KARDS screen state by template matching.

State is decided from the set of UI templates that are *visible* right now.
You teach the classifier which templates imply which state in config/states.json:

{
  "states": {
    "main_menu":   {"any_of": ["play_btn", "store_btn"]},
    "queueing":    {"any_of": ["cancel_queue_btn"]},
    "in_game":     {"any_of": ["end_turn_btn"]},
    "defeat":      {"any_of": ["defeat_continue_btn"]},
    "victory":     {"any_of": ["victory_continue_btn"]}
  }
}

A state fires when any template in its any_of list matches above threshold.
Templates are matched against the live window capture.
"""

from __future__ import annotations

import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from win import capture_client_bgr, find_by_process, set_dpi_aware  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_THRESHOLD = 0.82

# ★★★ 2026-09-13(第九个会话):**每个模板按它自己录制时的 `region` 去搜,不再整帧搜。**
#
# 为什么(实测):`classify` 原来对**每一个**模板都在**整帧 1280x720** 上跑
# `cv2.matchTemplate`。这个函数被 main_loop **每个 tick 调一次**,
# 而 config 里有 17 个模板 —— 实测一次 **1.63s**。
# 于是"一个 tick" = 1.63s(状态识别) + 0.8s(主循环 sleep)+ 两次抓帧
# ≈ **2.7s**,而**一个阶段要占一个 tick**:实机日志里"攻击阶段结束"与
# "上前线阶段结束"两行之间稳定是 **4 秒**(那一段其实什么都没做)。
#
# 每个模板在 `config/templates.json` 里都带 `region`(录制时它所在的小方块,
# 实测只有 100x40 ~ 230x100 那么大)。**模板一定在那块 region 里**,
# 所以在那块 region(再放 `ROI_PAD` 余量)里搜就够了:
# 面积比约 1/30 -> 一次 classify 从 1.63s 降到 ~0.1s。
#
# ★ 安全性:`ROI_PAD` 给了余量;真要是某个 UI 挪了位置,那个模板就搜不到,
#   状态判不出来 —— 而这**不是 fail-silent**:`state` 会变成 None,
#   主循环会打 `state -> None` 并走"未知画面"分支(不会乱点)。
#   留 `--full-frame` / `ROI_MATCH=False` 一键退回老行为。
ROI_PAD = 40
ROI_MATCH = True
# classify 用:模板名 -> (x, y, w, h),由 load_templates 从 meta 里带出来
TEMPLATE_REGIONS: dict = {}


def load_meta(meta_path: str) -> dict:
    with open(meta_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_templates(meta: dict) -> dict[str, np.ndarray]:
    """Return {name: template_bgr} loading from meta entries."""
    out = {}
    TEMPLATE_REGIONS.clear()
    for name, entry in meta.get("templates", {}).items():
        path = entry["path"]
        abs_path = path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)
        img = cv2.imread(abs_path, cv2.IMREAD_COLOR)
        if img is None:
            print(f"WARN cannot load template {name}: {abs_path}")
            continue
        out[name] = img
        # ★ 顺手把录制位置留下来给 classify 用(见 ROI_MATCH 的说明)
        r = entry.get("region")
        if r:
            TEMPLATE_REGIONS[name] = (int(r["x"]), int(r["y"]),
                                      int(r["w"]), int(r["h"]))
    return out


def match_one(haystack: np.ndarray, needle: np.ndarray) -> tuple[float, tuple[int, int, int, int] | None]:
    """Return (max_score, region(x,y,w,h)) or score<0 if sizes invalid."""
    hh, hw = haystack.shape[:2]
    nh, nw = needle.shape[:2]
    if nh > hh or nw > hw:
        return -1.0, None
    res = cv2.matchTemplate(haystack, needle, cv2.TM_CCOEFF_NORMED)
    _, maxv, _, maxloc = cv2.minMaxLoc(res)
    return float(maxv), (int(maxloc[0]), int(maxloc[1]), nw, nh)


def match_roi(frame: np.ndarray, name: str, tpl: np.ndarray):
    """
    在模板自己录制的那块 region(外放 `ROI_PAD`)里匹配;没有 region 信息就整帧。

    ★ 返回的坐标**换算回整帧坐标**,所以调用方拿到的东西和整帧匹配时一致。
    """
    r = TEMPLATE_REGIONS.get(name) if ROI_MATCH else None
    if r is None:
        return match_one(frame, tpl)
    fh, fw = frame.shape[:2]
    x0 = max(0, r[0] - ROI_PAD)
    y0 = max(0, r[1] - ROI_PAD)
    x1 = min(fw, r[0] + r[2] + ROI_PAD)
    y1 = min(fh, r[1] + r[3] + ROI_PAD)
    if x1 - x0 < tpl.shape[1] or y1 - y0 < tpl.shape[0]:
        return match_one(frame, tpl)
    score, reg = match_one(frame[y0:y1, x0:x1], tpl)
    if reg is not None:
        reg = (reg[0] + x0, reg[1] + y0, reg[2], reg[3])
    return score, reg


def classify(
    frame: np.ndarray,
    templates: dict[str, np.ndarray],
    states: dict,
    threshold: float = DEFAULT_THRESHOLD,
) -> tuple[str | None, dict]:
    """
    Returns (state_name_or_None, matches) where matches = {template: score}
    for every template that fired at/above threshold.
    """
    matches: dict[str, float] = {}
    for name, tpl in templates.items():
        # ★ 2026-09-13:有 region 就在 region 里搜(快 ~15 倍),见 ROI_MATCH 的说明
        score, _ = match_roi(frame, name, tpl)
        if score >= threshold:
            matches[name] = score

    # Evaluate states: a state fires when any_of templates present (all in list? any_of)
    # We use "any_of" semantics: first state whose any template matched wins.
    for state, rule in states.items():
        names = rule.get("any_of", [])
        for nm in names:
            if nm in matches:
                return state, matches
        if not names and rule.get("all_of"):
            if all(n in matches for n in rule["all_of"]):
                return state, matches
    return None, matches


def load_states(states_path: str) -> dict:
    if not os.path.exists(states_path):
        return {}
    with open(states_path, "r", encoding="utf-8") as f:
        return json.load(f).get("states", {})


def snapshot_live(proc: str = "kards") -> np.ndarray | None:
    wins = find_by_process(proc)
    if not wins:
        return None
    return capture_client_bgr(wins[0]["hwnd"])


def main() -> int:
    set_dpi_aware()
    import argparse

    ap = argparse.ArgumentParser(description="KARDS screen state classifier (M1)")
    ap.add_argument("--proc", default="kards")
    ap.add_argument(
        "--meta", default=os.path.join(PROJECT_ROOT, "config", "templates.json")
    )
    ap.add_argument(
        "--states", default=os.path.join(PROJECT_ROOT, "config", "states.json")
    )
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    ap.add_argument("--image", default="", help="classify an image file instead of live window")
    ap.add_argument("--show", action="store_true", help="show matched boxes in a window")
    args = ap.parse_args()

    if not os.path.exists(args.meta):
        print("no templates.json yet - run src/template_capture.py first")
        return 1

    meta = load_meta(args.meta)
    templates = load_templates(meta)
    states = load_states(args.states)
    if not templates:
        print("no templates defined - run src/template_capture.py first")
        return 1

    frame = cv2.imread(args.image) if args.image else snapshot_live(args.proc)
    if frame is None:
        print("no frame to classify")
        return 1

    state, matches = classify(frame, templates, states, args.threshold)
    print(f"state: {state}")
    if not matches:
        print("  (no template matched at threshold %.2f)" % args.threshold)
    for name, score in sorted(matches.items(), key=lambda kv: -kv[1]):
        print(f"  matched {name}: {score:.3f}")

    # optionally show frame with boxes
    if args.image or args.show:
        vis = frame.copy()
        for name, tpl in templates.items():
            s, reg = match_one(frame, tpl)
            if s >= args.threshold and reg:
                x, y, w, h = reg
                cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 255, 0), 2)
                cv2.putText(vis, name, (x, max(12, y - 4)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)
        cv2.imshow("classify", vis)
        cv2.waitKey(0)
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
