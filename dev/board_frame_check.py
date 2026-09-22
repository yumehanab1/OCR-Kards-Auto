"""board_frame_check.py - 只读:拿**引擎自己的读盘器**量任意几帧,核对"某一行几张"。

为什么需要它(2026-09-15 实机 J9):日志里 7 次
`[move] 没动成:我方支援 2->2,前线 X->X+1` —— 前线 +1、支援却没 −1,
判据("两边都变")于是全记成失败。到底是①拖拽真被拒了,还是②读数是错的?
光看日志分不出来,**必须用同一个读盘器去量"动作前那一帧"和"动作后那一帧"**:

```
.venv\\Scripts\\python.exe dev\\board_frame_check.py ^
    shots\\attack_frames\\0915_184233_attack.png shots\\scan_frames\\0915_184240_scan.png
```
它会把每一帧的:卡框锚点 `card_boxes`、徽章锚点 `badge_boxes`(每个都带来源和
state/n/S/V)、`find_cost_badges` 的 debug 原文、行结构(cy/side/每张卡的框)、
`我方支援/我方前线` 张数、两个总部的血量 —— 全部打出来,
并在 `shots/_boxes_<帧名>` 上把检出的框画出来(红框),人眼一次就能看清
"多出来的那张卡到底是什么"。

★ 只用来看,**不改任何东西**(连 dump 都不写进 shots 的正式目录,只写 `_boxes_` 前缀)。

用法:
  .venv\\Scripts\\python.exe dev\\board_frame_check.py <帧1.png> [帧2.png ...]
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2  # noqa: E402

from board import badge_boxes, card_boxes, read_field, rows_from_boxes  # noqa: E402
from ui_state import load_meta, load_templates  # noqa: E402
from unit_state import find_cost_badges  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
META = os.path.join(ROOT, "config", "templates.json")


def check(path: str, tpl) -> None:
    print("=" * 78)
    frame = cv2.imread(path)
    if frame is None:
        print("读不到:", path)
        return
    print(os.path.basename(path), frame.shape)

    cb = card_boxes(frame)
    print(f"  [卡框锚点 card_boxes] {len(cb)} 张:")
    for b in cb:
        print(f"      x={int(b['x'])} y={int(b['y'])} "
              f"w={int(b['w'])} h={int(b['h'])}")

    rr = rows_from_boxes(cb)
    print("  [find_cost_badges debug 原文]")
    _ = find_cost_badges(frame, rows=rr, debug=True)

    bb = badge_boxes(frame, rows=rr)
    print(f"  [徽章锚点 badge_boxes] {len(bb)} 张:")
    for b in bb:
        bg = b.get("badge") or {}
        print(f"      x={int(b['x'])} y={int(b['y'])} <- 徽章 "
              f"x={bg.get('x')} y={bg.get('y')} state={b.get('state')}")

    f = read_field(frame, templates=tpl)
    for r in (f.get("rows") or []):
        xs = [int(u.get("cx", -1)) for u in (r.get("units") or [])]
        print(f"  行 cy={r.get('cy')} side={r.get('side')} "
              f"卡数={len(r.get('boxes') or [])} 单位x={xs}")
        for b in (r.get("boxes") or []):
            print(f"      框 x={int(b['x'])} y={int(b['y'])} "
                  f"w={int(b['w'])} h={int(b['h'])}")
            cv2.rectangle(frame, (int(b["x"]), int(b["y"])),
                          (int(b["x"]) + int(b["w"]), int(b["y"]) + int(b["h"])),
                          (0, 0, 255), 2)
    print(f"  -> 我方支援 {len(f.get('our_support') or [])} 张 / "
          f"我方前线 {len(f.get('frontline') or [])} 张 / "
          f"敌方支援 {len(f.get('enemy_support') or [])}")
    for k in ("hq_our", "hq_enemy"):
        u = f.get(k)
        print(f"  {k}: " + ("无" if not u else
                            f"cx={int(u.get('cx'))} cy={int(u.get('cy'))} "
                            f"hp={u.get('hp')}"))
    out = os.path.join(ROOT, "shots", "_boxes_" + os.path.basename(path))
    cv2.imwrite(out, frame)
    print("  画的框 ->", out)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    tpl = load_templates(load_meta(META))
    for p in sys.argv[1:]:
        check(p, tpl)
    return 0


if __name__ == "__main__":
    sys.exit(main())
