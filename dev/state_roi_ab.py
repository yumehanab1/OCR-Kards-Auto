"""
state_roi_ab.py - 只读:状态识别 `ui_state.classify` 的 **RDI A/B**(整帧 vs 按 region 搜)。

背景(2026-09-13 第九个会话):
  `main_loop` **每个 tick** 都调一次 `classify`,而它原来对 **17 个模板**都在
  **整帧 1280x720** 上跑 `cv2.matchTemplate` —— 实测 **1.63s/tick**。
  可 `config/templates.json` 里**每个模板都带 `region`**(录制时它所在的小方块),
  在 region(外放 `ROI_PAD`)里搜就够了 -> 实测 **0.045s**,快 ~39 倍。

  ★ 但"快"不是判据,**"结果一样"才是**。所以这个工具把两种行为并排跑,
    逐帧比 **state**(真正驱动行为的那个)和 **命中集合 matches**。

用法:
  .venv\\Scripts\\python.exe src\\state_roi_ab.py
"""

from __future__ import annotations

import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2  # noqa: E402

import ui_state  # noqa: E402
from ui_state import classify, load_meta, load_templates  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATTERNS = (
    "shots/*.png",
    "shots/attack_frames/*.png",
    "shots/board_samples/*.png",
    "shots/turn_pairs/*.png",
    "shots/deploy_probe/*.png",
    "shots/turn_obs/*.png",
    "shots/frontline/*.png",
    "shots/hoverdump/*.png",
)


def frames():
    seen, out = set(), []
    for pat in PATTERNS:
        for p in sorted(glob.glob(os.path.join(PROJECT_ROOT, pat)))[:40]:
            if p in seen:
                continue
            seen.add(p)
            f = cv2.imread(p)
            if f is None or f.shape[:2] != (720, 1280):
                continue
            out.append((os.path.relpath(p, PROJECT_ROOT), f))
    return out


def main() -> int:
    meta = load_meta(os.path.join(PROJECT_ROOT, "config", "templates.json"))
    tpl = load_templates(meta)
    states = json.load(open(os.path.join(PROJECT_ROOT, "config", "states.json"),
                           encoding="utf-8"))["states"]
    print(f"模板 {len(tpl)} 个;带 region 的 {len(ui_state.TEMPLATE_REGIONS)} 个;"
          f"ROI_PAD={ui_state.ROI_PAD}")
    fr = frames()
    print(f"真实帧 {len(fr)} 张\n")

    t_old = t_new = 0.0
    state_diff, match_diff = [], []
    for name, f in fr:
        ui_state.ROI_MATCH = False
        t0 = time.perf_counter()
        s_old, m_old = classify(f, tpl, states)
        t_old += time.perf_counter() - t0
        ui_state.ROI_MATCH = True
        t0 = time.perf_counter()
        s_new, m_new = classify(f, tpl, states)
        t_new += time.perf_counter() - t0
        if s_old != s_new:
            state_diff.append((name, s_old, s_new))
        if set(m_old) != set(m_new):
            match_diff.append((name, sorted(set(m_old) ^ set(m_new))))

    n = max(1, len(fr))
    print(f"老(整帧) 总 {t_old:6.2f}s  平均 {t_old / n:.3f}s/帧")
    print(f"新(ROI)  总 {t_new:6.2f}s  平均 {t_new / n:.3f}s/帧"
          f"   -> 快 {t_old / max(t_new, 1e-9):.1f}x")
    print()
    print(f"★ state 不同的帧:{len(state_diff)} / {n}   ← 这个必须是 0"
          f"(state 才驱动行为)")
    for d in state_diff[:20]:
        print("   ", d)
    print(f"  命中集合不同的帧:{len(match_diff)} / {n}"
          f"   ← 只影响诊断打印(差异都在 states.json 不引用的模板上)")
    for d in match_diff[:10]:
        print("   ", d)
    if not state_diff:
        print("\n✅ state 零差异 —— ROI 只是更快,不改变任何决策输入。")
    return 0 if not state_diff else 1


if __name__ == "__main__":
    sys.exit(main())
