"""评估"并集探针去重"这件事能不能靠坐标做对(离线,不碰游戏)。

为什么留这个脚本
----------------
用户 2026-09-21:*"这一局跑下来光扫卡扫了好久"* —— 并集补探把每张牌读了两遍。
根因: `_probes_for` 的去重门槛 `LAYOUT_PROBE_UNION_DEDUP_PX` 原为 15,
而 7/8/9 三条布局在**同一张牌**上的探针错开约 17px ⇒ 一根都去不掉。

★ 这个脚本是那次判断的**判据出处**,以后要动那个门槛先跑它:
  它把三套真实布局摊开,逐张算出"同一张牌的偏移",再和
  "同一条布局里最小的相邻针距"(那是**上界**,超过就会把真牌并掉)对照。

★★ 它同时记录了**为什么这件事靠坐标做不到干净**:
     7 vs 8 同一张牌的偏移: 17 23 27 34 40 46 77   (逐张递增)
     7 vs 9:                16 29 47 57 71 91 131
   而所有布局里最小相邻针距 = 46px( count=9 那条)。
   ⇒ "同一张的偏移"(最大 131)**比**"不同牌的最小间距"(46)**还大**,
     两个区间**重叠**,所以**不存在固定门槛**能同时做对两件事。
   ⇒ 门槛提到 35 只是"在不并错的前提下尽量多去"的折中(止血),
     真正的修法是**按牌的身份对齐**(用 `left_edge` 归一),留在下一轮。

用法:  python dev\\_probe_dedup_eval.py
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LAY = os.path.join(_ROOT, "config", "hand_layout.json")

lay = json.load(open(_LAY, encoding="utf-8"))
if isinstance(lay, dict) and "layouts" in lay:
    lay = lay["layouts"]
by_count = {}
for k, v in (lay.items() if isinstance(lay, dict) else enumerate(lay)):
    if isinstance(v, dict) and v.get("count"):
        by_count[int(v["count"])] = {
            "left": v.get("left_edge"), "right": v.get("right_edge"),
            "probes": [int(x) for x in (v.get("probes") or [])],
        }

print("=== 各条布局自己的最小相邻针距(真牌之间)===")
for n in sorted(by_count):
    p = by_count[n]["probes"]
    if len(p) < 2:
        continue
    gaps = [p[i + 1] - p[i] for i in range(len(p) - 1)]
    print(f"  count={n}: 针距 min={min(gaps)} max={max(gaps)} "
          f"均值={sum(gaps)/len(gaps):.1f}")

print()
print("=== 7/8/9 三条:逐张比『同一张牌上两根针差多少』 ===")


def cmp2(a, b):
    pa, pb = by_count[a]["probes"], by_count[b]["probes"]
    n = min(len(pa), len(pb))
    print(f"  {a} 张 vs {b} 张(取前 {n} 张):")
    for i in range(n):
        print(f"    第{i+1}张: {pa[i]:>4} vs {pb[i]:>4}  差 {abs(pa[i]-pb[i]):>3}")
    if len(pa) != len(pb):
        print(f"    (多出来的第 {n+1} 张: "
              f"{pa[n] if len(pa) > n else '-'} / {pb[n] if len(pb) > n else '-'})")


cmp2(7, 8)
cmp2(8, 9)
cmp2(7, 9)

print()
print("=== 用不同门槛去重会剩几根(三条并集)===")
union = sorted(set(by_count[7]["probes"] + by_count[8]["probes"]
                   + by_count[9]["probes"]))
print("并集原始:", union, f"({len(union)} 根)")


def dedup(seq, thr):
    out = []
    for x in seq:
        if out and abs(x - out[-1]) <= thr:
            continue
        out.append(x)
    return out


for thr in (15, 20, 25, 30, 35, 40):
    kept = dedup(union, thr)
    print(f"  门槛 {thr:>2}: 剩 {len(kept):>2} 根  {kept}")

print()
print("=== 上界:门槛不能超过多少(否则并掉同一条布局里的两张真牌)===")
worst = 999
for n in sorted(by_count):
    p = by_count[n]["probes"]
    for i in range(len(p) - 1):
        worst = min(worst, p[i + 1] - p[i])
print(f"  所有布局里最小的相邻针距 = {worst}px  ⇒ 门槛必须 < {worst}")
print("  当前门槛(hand_scanner_v2.LAYOUT_PROBE_UNION_DEDUP_PX):")
try:
    sys.path.insert(0, os.path.join(_ROOT, "src"))
    import hand_scanner_v2 as hs
    cur = hs.LAYOUT_PROBE_UNION_DEDUP_PX
    print(f"    {cur}  ->  {'✅ 在上界之内' if cur < worst else '❌ 超了上界!'}")
except Exception as e:
    print(f"    (读不到:{type(e).__name__}: {e})")

