"""memory_ab.py - 只读:把「手牌记忆开/关」两段实机日志摊开对比。

用法:
  .venv\\Scripts\\python.exe dev\\memory_ab.py            # 最后两段 main_loop
  .venv\\Scripts\\python.exe dev\\memory_ab.py 3           # 最后三段
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(PROJECT_ROOT, "logs", "main_loop.log")


def seg_summary(seg, tag):
    scans = [l for l in seg if "惰性扫描 #" in l]
    times = [float(re.search(r"#\d+: ([\d.]+)s", l).group(1))
             for l in scans if re.search(r"#\d+: ([\d.]+)s", l)]
    none_aff = [t for t, l in
                ((float(re.search(r"#\d+: ([\d.]+)s", l).group(1)), l)
                 for l in scans if re.search(r"#\d+: ([\d.]+)s", l))
                if "没找到出得起的牌" in l]
    mem_hit = [l for l in seg if "[记忆] 命中" in l]
    saved = [int(re.search(r"跳过 (\d+) 个探针", l).group(1)) for l in mem_hit]
    bad = [l for l in seg if "[记忆] 失效" in l]
    okdep = [l for l in seg if "部署成功" in l]
    rej = [l for l in seg if "部署被拒绝" in l]
    mism = [l for l in okdep if "不符" in l]
    turns = [l for l in seg if "our turn starts" in l]
    res = [l for l in seg if "round 1 finished" in l]
    print(f"=== {tag} ===")
    print(f"  我方回合 {len(turns)} 个;{res[-1].split('==')[-2].strip() if res else '未结束'}")
    print(f"  扫描 {len(scans)} 次,合计 {sum(times):.0f}s,平均 {sum(times) / max(1, len(times)):.1f}s")
    print(f"  「一张都出不起」的扫描 {len(none_aff)} 次:耗时 {none_aff}")
    print(f"  记忆命中 {len(mem_hit)} 次 -> 共跳过 {sum(saved)} 个探针"
          f"(按 1.9s/探针算约 {sum(saved) * 1.9:.0f}s)")
    print(f"  记忆失效 {len(bad)} 次")
    for b in bad:
        print(f"     · {b.split('失效:')[-1][:70]}")
    print(f"  部署成功 {len(okdep)}(费用不符 {len(mism)})/ 被拒 {len(rej)}")
    for l in mem_hit:
        print(f"     + {l.split('[记忆] ')[-1][:90]}")


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    lines = open(LOG, encoding="utf-8").read().splitlines()
    starts = [i for i, l in enumerate(lines) if "main_loop start" in l]
    if not starts:
        print("日志里没有 main_loop start")
        return 1
    for k, idx in enumerate(starts[-n:]):
        end = starts[starts.index(idx) + 1] if starts.index(idx) + 1 < len(starts) \
            else len(lines)
        seg = lines[idx:end]
        t = lines[idx].split(" ")[1]
        seg_summary(seg, f"{t}(第 {len(starts) - len(starts[-n:]) + k + 1} 段)")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
