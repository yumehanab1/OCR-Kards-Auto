"""
hand_edge_diag.py - **只读**诊断"手牌扇形左边缘为什么测出来是这个数"。

背景(2026-09-11 傍晚实机):整局每一回合都是同一行日志
    `惰性扫描 #N: 左边缘 277 与最近布局(8 张,357)差 80px > 容差 22`
于是**整局一张牌都没出**(0.3s = 根本没扫,查表失败就放弃)。

`hand_calibrate.detect_left_edge` 的判据(见该函数):
  ① 拿 **固定区域 x∈[150,250]、y∈[680,715]** 的平均色当"桌面色"参考
  ② 从 x=150 往右扫,找第一段**连续 6 列**与参考色差 > 45 的位置,当作扇形左边缘
这个判据的两个弱点正好都能被这个脚本看见:
  ① 参考区本身不是桌面(那儿有装饰/卡面)→ 整条曲线的基线就偏了
  ② 左边缘左边还有别的东西(装饰、别的 UI)→ 第一个 6 列run 根本不是扇形

用法(需要在**对局中**、鼠标停在安全点时跑):
  .venv\\Scripts\\python.exe src\\hand_edge_diag.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import hand_calibrate as hc  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    from win import capture_client_bgr, find_by_process, set_dpi_aware

    set_dpi_aware()
    wins = find_by_process("kards")
    if not wins:
        print("找不到 kards 窗口")
        return 1
    frame = capture_client_bgr(wins[0]["hwnd"])
    if frame is None:
        print("截图失败(窗口被盖住?)")
        return 1

    y0, y1 = hc.EDGE_Y0, hc.EDGE_Y1
    x0, x1 = hc.BG_SAMPLE
    bg = frame[y0:y1, x0:x1].reshape(-1, 3).mean(axis=0)
    strip = frame[y0:y1, :].astype(np.int16)
    diff = np.abs(strip - bg).mean(axis=(0, 2))

    print(f"帧 {frame.shape};边缘带 y{y0}-{y1};参考区 x{x0}-{x1} "
          f"平均色 BGR={np.round(bg, 1)}(它就是被当桌面色用的那个)")
    print(f"EDGE_THRESH={hc.EDGE_THRESH}  要求连续 6 列")
    left = hc.detect_left_edge(frame)
    print(f"detect_left_edge -> {left}")
    try:
        print(f"detect_right_edge -> {hc.detect_right_edge(frame)}")
    except Exception as exc:
        print(f"detect_right_edge 出错: {exc}")

    # 把所有"连续 >=6 列超阈值"的 run 都列出来 —— 第一个 run 才是被判成左边缘的
    runs = []
    run = 0
    for x in range(hc.EDGE_X_MIN, min(hc.EDGE_X_MAX, frame.shape[1])):
        if diff[x] > hc.EDGE_THRESH:
            run += 1
        else:
            if run >= 6:
                runs.append((x - run, x - 1, run))
            run = 0
    if run >= 6:
        runs.append((min(hc.EDGE_X_MAX, frame.shape[1]) - run,
                     min(hc.EDGE_X_MAX, frame.shape[1]) - 1, run))
    print(f"共 {len(runs)} 段'连续>=6 列超阈值'的区域(前 8 段):")
    for a, b, n in runs[:8]:
        print(f"    x {a:4d}..{b:4d}  (宽 {n})   该段内平均差 "
              f"{diff[a:b + 1].mean():.0f}")

    # 参考区自身的内部差异:如果它内部就很不均匀,说明那儿不是纯桌面
    print(f"参考区自身标准差: {frame[y0:y1, x0:x1].std(axis=(0, 1)).round(1)}"
          f"  (越小越像纯桌面)")

    outdir = os.path.join(ROOT, "shots", "hand_edge")
    os.makedirs(outdir, exist_ok=True)
    cv2.imwrite(os.path.join(outdir, "band.png"),
                cv2.resize(frame[660:720, :], None, fx=1.0, fy=2.4,
                           interpolation=cv2.INTER_NEAREST))
    # 把 diff 曲线画出来(只画有意义的区间),人眼一眼看出峰在哪
    plot = np.zeros((200, 1100, 3), np.uint8)
    for x in range(hc.EDGE_X_MIN, min(hc.EDGE_X_MAX, 1250)):
        v = int(min(199, diff[x]))
        cv2.line(plot, (x - hc.EDGE_X_MIN, 199), (x - hc.EDGE_X_MIN, 199 - v),
                 (0, 255, 0), 1)
    cv2.line(plot, (0, 199 - hc.EDGE_THRESH), (1099, 199 - hc.EDGE_THRESH),
             (0, 0, 255), 1)
    for a, b, _n in runs:
        cv2.line(plot, (a - hc.EDGE_X_MIN, 0), (a - hc.EDGE_X_MIN, 199),
                 (255, 255, 0), 1)
    cv2.imwrite(os.path.join(outdir, "diff_profile.png"), plot)
    cv2.imwrite(os.path.join(outdir, "full.png"), frame)
    print(f"存图 -> {outdir}(band.png / diff_profile.png / full.png;"
          f"曲线里红线=阈值,青线=每段 run 的起点)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
