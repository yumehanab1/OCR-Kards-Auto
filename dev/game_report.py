"""
game_report.py - 一局(或最近 N 局)的**对账报表**(只读,不碰游戏窗口)。

为什么要有它
------------
实机连跑几局找问题时,每局跑完都要回答同样一组问题,而这些问题散在几百行日志里:
  · 这一局赢没赢、多久、每回合几秒;
  · **费用读数对不对**(两位数还读错吗?有没有 `[不采信]`?)
  · 部署 成/拒、攻击/打中、零部署回合;
  · 那几条"静默浪费"的计数(不扫手牌 / 没找到橙色徽章 / 卡数异常 / 读不到我方那一行);
  · 手牌记忆有没有帮上忙;
  · **制胜一击**判出来了没有(`卡从画面上消失了`)。
手工贴一堆 one-liner 又慢又容易漏 —— 这个脚本一次全打出来,并且把**异常**标出来。

用法
----
  .venv\\Scripts\\python.exe dev\\game_report.py          # 最近 1 段 main_loop
  .venv\\Scripts\\python.exe dev\\game_report.py 3        # 最近 3 段(连跑几局后对账)
  .venv\\Scripts\\python.exe dev\\game_report.py --issues # 只打"值得查"的行(原文)

★ 段 = 一次 `main_loop start` 到下一次之前。**只读日志文件**,不动鼠标。
"""

from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, "logs", "main_loop.log")

#: 值得人工看一眼的"异常"行(原文照打,用 --issues)
ISSUE_WORDS = (
    "不采信",
    "读数器:",
    "卡数异常",
    "读不到我方那一行",
    "Traceback",
    "⚠️",
    "总部的框太宽",
    "结局判不出来",
    "判不出来",
    "结论不可信",
    "退回画面差异",
    "被拒绝",
)


def segments(lines):
    """按 `main_loop start` 切段,返回 [[line, ...], ...]。"""
    idx = [i for i, l in enumerate(lines) if "main_loop start" in l]
    out = []
    for k, i in enumerate(idx):
        j = idx[k + 1] if k + 1 < len(idx) else len(lines)
        out.append(lines[i:j])
    return out


def count(seg, needle):
    return sum(1 for l in seg if needle in l)


def _num(seg, pattern, group=1, cast=int, default=None):
    """取最后一次匹配里的第 group 组(没有就返回 default)。"""
    vals = []
    for l in seg:
        m = re.search(pattern, l)
        if m:
            vals.append(m.group(group))
    if not vals:
        return default
    try:
        return cast(vals[-1])
    except Exception:
        return default


def _time_of(line):
    m = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", line)
    return m.group(1) if m else None


def _sum_of(seg, pattern):
    """把每一行里匹配到的数字**累加**(例:"尝试 1 次" + "尝试 0 次" = 1)。

    ★ 不能像第一版那样只取最后一次匹配 —— 一个回合一行,最后一行常常是 0,
      于是报表把整局的攻击数打成了 0(实测踩过,差点误判成"这局一次都没打")。
    """
    return sum(int(m.group(1)) for l in seg
               for m in [re.search(pattern, l)] if m)


def report(seg, idx=None, total=None):
    head = f"第 {idx}/{total} 段" if idx else "本段"
    t0 = _time_of(seg[0]) if seg else None
    t1 = _time_of(seg[-1]) if seg else None
    fin = [l for l in seg if "finished" in l and "round" in l]
    print("=" * 88)
    print(f"{head}:{t0} -> {t1}")
    if fin:
        print("  " + (fin[-1].split("] ", 1)[-1] if "] " in fin[-1] else fin[-1]))
    else:
        print("  ⚠️ 这一段**没有结局行**(还在跑?或者中途退出了)")

    turns = count(seg, "[turn] our turn starts")
    scans = count(seg, "[turn] 惰性扫描")
    scan_secs = [float(m.group(1)) for l in seg
                 for m in [re.search(r"惰性扫描 #\d+: ([0-9.]+)s", l)] if m]
    deploys_ok = count(seg, "部署成功")
    deploys_rej = count(seg, "部署被拒绝")
    zero_deploy = sum(1 for l in seg if "出牌结束(尝试 0 次,成功 0 个)" in l)
    atk_try = _sum_of(seg, r"攻击阶段结束:尝试 (\d+) 次")
    atk_ok = _sum_of(seg, r"被接受 (\d+) 次")
    move_ok = _sum_of(seg, r"上前线阶段结束:挪上去 (\d+) 个")
    move_fail = _sum_of(seg, r"上前线阶段结束:挪上去 \d+ 个,没动成 (\d+) 个")
    deploys_tried = _sum_of(seg, r"出牌结束\(尝试 (\d+) 次")
    deploys_done = _sum_of(seg, r"出牌结束\(尝试 \d+ 次,成功 (\d+) 个\)")

    print(f"  我方回合 {turns} | 扫描 {scans} 次"
          + (f"(合计 {sum(scan_secs):.0f}s,平均 {sum(scan_secs)/len(scan_secs):.1f}s,"
             f"最慢 {max(scan_secs):.1f}s)" if scan_secs else "")
          + f" | 零部署回合 {zero_deploy}")
    print(f"  牌:出牌尝试 {deploys_tried} 次 -> 成功 {deploys_done}"
          f"(日志行 部署成功 {deploys_ok} / 部署被拒绝 {deploys_rej}"
          + ("  ⚠️ 对不上,要查)" if deploys_done != deploys_ok else ")"))
    print(f"  攻击:尝试 {atk_try} 次 -> 被接受 {atk_ok}"
          f" | 打中 {count(seg, '打中了')} | 没打中 {count(seg, '没打中')}"
          f" | 被拒绝(血量读不到) {count(seg, '被拒绝(血量读不到')}"
          f" | 结论不可信 {count(seg, '结论不可信')}")
    print(f"  上前线:挪上去 {move_ok} 个 | 没动成 {move_fail} 个"
          f" | 归属重读 {count(seg, '重读 ->')}")

    # ★ 本轮的验收面:费用读数
    starts = [l for l in seg if "[turn] our turn starts" in l]
    reads = []
    for l in starts:
        m = re.search(r"kredits read: (\d+|None) \[([^\]]+)\]", l)
        if m:
            reads.append((m.group(1), m.group(2)))
    print(f"  ★ 费用读数序列: {', '.join(v for v, _s in reads) or '(没有)'}")
    bad = [(v, s) for v, s in reads if "不采信" in s]
    print(f"  ★ 不采信 {len(bad)} 次" + (f"  <- {bad}" if bad else "  ✅")
          + f" | 读数器(读不出数字)的原因 {count(seg, '读数器:')} 次")
    two_digit = [v for v, _s in reads if v.isdigit() and int(v) >= 10]
    print(f"  ★ 两位数回合 {len(two_digit)} 个: {two_digit or '(这一局还没到两位数)'}")
    kill = [l for l in seg if "卡从画面上消失了" in l]
    print(f"  ★ 制胜一击判据(总部卡从画面上消失了):{len(kill)} 次"
          + ("  ✅ 本局出现过" if kill else "  (没撞上 / 或不是这么结束的)"))

    print(f"  静默浪费类: 不扫手牌 {count(seg, '不扫手牌')}"
          f" | 没找到橙色徽章 {count(seg, '没找到橙色费用徽章')}"
          f" | 卡数异常 {count(seg, '卡数异常')}"
          f" | 读不到我方那一行 {count(seg, '读不到我方那一行')}")
    print(f"  手牌记忆: 命中 {count(seg, '[记忆] 命中')}"
          f" | 失效 {count(seg, '[记忆] 失效')}"
          f" | 记忆行合计 {count(seg, '[记忆]')}")
    # ★ 失效的**原因**要分类:同一句"失效"可能是"保守正确"也可能是"读数抖了",
    #   修法完全不同(实测:一次出牌后立刻扫描会因为扇形还没重排而误失效)。
    fails: dict = {}
    for l in seg:
        if "[记忆] 失效" not in l:
            continue
        tail = l.split("失效:", 1)[-1] if "失效:" in l else l
        key = re.split(r"[(:]", tail.strip())[0].strip()[:22] or "(没写原因)"
        fails[key] = fails.get(key, 0) + 1
    if fails:
        print("     失效原因: " + "; ".join(
            f"{k} x{n}" for k, n in sorted(fails.items(), key=lambda kv: -kv[1])))
    issues = [(i, l) for i, l in enumerate(seg)
              if any(w in l for w in ISSUE_WORDS)]
    print(f"  被标记为'值得看一眼'的行: {len(issues)}(用 --issues 打原文)")
    return issues, len(seg)


def main() -> int:
    ap = argparse.ArgumentParser(description="一局的对账报表(只读)")
    ap.add_argument("n", nargs="?", type=int, default=1, help="看最近几段(默认 1)")
    ap.add_argument("--issues", action="store_true", help="额外打出被标记的行")
    args = ap.parse_args()

    if not os.path.exists(LOG):
        print(f"没有日志:{LOG}")
        return 1
    with open(LOG, "rb") as f:
        lines = f.read().decode("utf-8", "replace").splitlines()
    segs = segments(lines)
    if not segs:
        print("日志里没有 `main_loop start` —— 还没跑过?")
        return 1
    picked = segs[-max(1, args.n):]
    for k, seg in enumerate(picked):
        idx = len(segs) - len(picked) + k + 1
        issues, _n = report(seg, idx=idx, total=len(segs))
        if args.issues and issues:
            print("  " + "-" * 84)
            for _i, l in issues[:60]:
                print("    " + l.split("] ", 1)[-1][:170])
            if len(issues) > 60:
                print(f"    …还有 {len(issues) - 60} 行")
    print("=" * 88)
    print("提示:① 两位数回合里 `不采信` 必须是 0;② `读数器:` 只在滚动瞬间出现才正常;")
    print("      ③ 制胜一击那一行应该写'打中了(卡从画面上消失了)',不是'被拒绝'。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
