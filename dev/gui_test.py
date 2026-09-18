"""gui_test.py - 面板的**离线**用例(不开窗口、不碰游戏)。

面板里真正会出错的是三件"纯逻辑"的事,所以只考这三件(其余是 HTML/CSS):
  ① `build_argv`:勾选 -> 命令行参数(勾错了就会用错的模式跑实机);
  ② `parse_status`:日志 -> 面板顶部那几个数(回合/费用/战场/最近动作/局数);
  ③ `tail_lines` + `mark_line`:日志尾巴与配色语义,以及"汉字不许被切一半"
     (`watch_log.py` 里踩过那个坑:文本模式从中间 seek 会把多字节字符切断)。

用法:
  .venv\\Scripts\\python.exe src\\gui_test.py
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import gui  # noqa: E402

FAILS = []


def check(ok: bool, msg: str) -> None:
    print(("  OK  " if ok else "  ✗   ") + msg)
    if not ok:
        FAILS.append(msg)


#: 从**真日志**里抄的一段(2026-09-15 19:20 那轮复验),含胜负/费用/战场/攻击判据。
SAMPLE = """2026-09-15 19:20:52 main_loop start (dry=False end_turn=False max_rounds=3)
2026-09-15 19:20:53 [deck_select] 用 'casual_mode_btn' 进了对局流程
2026-09-15 19:21:22 state -> mulligan
2026-09-15 19:21:25 state -> in_game
2026-09-15 19:21:27 [turn] our turn starts (kredits read: 1 [settled] 采样 [1, 1, 1]) | 本回合预算 1
2026-09-15 19:21:28 [turn] 战场基准: 我支援 1 张卡(单位 0) / 我前线 0 / 敌前线 0 / 敌支援 1
2026-09-15 19:24:42 [move] 动成功了(我方支援 3->2 且 前线 0->1)
2026-09-15 19:28:31 == round 1 finished (victory) after 7.7 min ==
2026-09-15 19:38:02 [attack] #1 结论不可信:打的是**单位**,读不到它的血量
2026-09-15 19:45:51 [turn] our turn starts (kredits read: 14 [settled] 采样 [14, 14])
2026-09-15 19:45:57 [attack] #2 打中了(敌方总部血量 14 -> 11)
2026-09-15 19:46:03 [turn] 战场基准: 我支援 3 张卡(单位 2) / 我前线 2 / 敌前线 0 / 敌支援 3
2026-09-15 19:48:39 [attack] #3 血量读数不一致(10 -> 87,变多不可能)
2026-09-15 19:58:24 == round 3 finished (victory) after 9.5 min ==
"""


def main() -> int:
    print("=" * 74)
    print("① build_argv:勾选 -> 命令行参数")
    check(gui.build_argv({"play": True, "attack": True, "fast_scan": True,
                          "max_rounds": "3"})
          == ["--play", "--attack", "--fast-scan", "--max-rounds", "3"],
          "默认三项 + 跑 3 局")
    check(gui.build_argv({"dry_run": True}) == ["--dry-run"],
          "只勾 dry-run 就只传 --dry-run")
    check(gui.build_argv({"play": True, "max_rounds": "0"}) == ["--play"],
          "跑 0 局 = 不传 --max-rounds(一直跑)")
    check(gui.build_argv({"play": True, "max_rounds": "abc"}) == ["--play"],
          "回合数写错字不炸,当成不传")
    check(gui.build_argv({}) == [], "什么都没勾 -> 空 argv(面板据此拒绝启动)")
    check(gui.DEFAULT_ON <= {s["key"] for s in gui.SWITCHES},
          "默认勾选必须是真实存在的开关(写错 key 会静默失效)")

    print("\n② parse_status:日志 -> 面板上的数")
    st = gui.parse_status(SAMPLE.splitlines())
    check(st["kredits"] == "14" and st["kredits_how"] == "settled",
          f"费用读数取**最后**一次:实得 {st['kredits']}/{st['kredits_how']}")
    check(st["board"] == {"our": 3, "our_units": "2", "front": 2,
                          "enemy_front": 0, "enemy": 3},
          f"战场基准取最后一次:实得 {st['board']}")
    check([r["n"] for r in st["rounds"]] == [1, 3] and
          st["rounds"][0]["result"] == "victory",
          f"两局的胜负都记下来了:实得 {st['rounds']}")
    check(st["state"] == "in_game", f"state:实得 {st['state']}")
    check(st["last_action"]["tag"] == "attack" and "87" in st["last_action"]["text"],
          f"最近动作 = 最后一条 [tag] 行:实得 {st['last_action']}")
    check(st["issues"] >= 2, f"⚠️/结论不可信/被拒绝 要计数:实得 {st['issues']}")
    check(st["started"] == {"dry": False, "end_turn": False, "max_rounds": 3},
          f"启动参数:实得 {st['started']}")

    st2 = gui.parse_status((SAMPLE + SAMPLE).splitlines())
    check([r["n"] for r in st2["rounds"]] == [1, 3],
          "看到新的 main_loop start 就把**上一段**的局数清掉(否则面板会把老账算进来)")

    # ★ 引擎在等窗口时,中间那块显示的是**上一局的旧状态** -> 必须挑明
    st3 = gui.parse_status((SAMPLE + "\n2026-09-16 18:08:36 KARDS window not "
                            "found - waiting\n").splitlines())
    check(st3["waiting"] is True and st3["kredits"] == "14",
          "『在等窗口』要单独标出来(此时 kredits/胜负 都是上一局的旧值)")
    check(gui.parse_status(SAMPLE.splitlines())["waiting"] is False,
          "正常跑的时候不许误报『在等窗口』")

    print("\n③ tail_lines / mark_line:日志尾巴与配色语义")
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "t.log")
        with open(p, "wb") as f:
            f.write("第一行中文占位\n".encode("utf-8") * 200)
            f.write("2026-09-15 19:58:24 == round 3 finished (victory) "
                    "after 9.5 min ==\n".encode("utf-8"))
        got = gui.tail_lines(p, 5)
        check(len(got) == 5 and "round 3 finished" in got[-1],
              f"只取末尾 5 行:实得 {len(got)} 行")
        check(all("�" not in ln for ln in got),
              "汉字不许被切成半个(二进制读 + 自己解码)")
    check(gui.mark_line("2026-09-15 19:45:57 [attack] #2 打中了(敌方总部血量 14 -> 11)") == "ok",
          "打中了 -> ok(绿)")
    check(gui.mark_line("2026-09-15 19:48:39 [attack] #3 血量读数不一致(10 -> 87,变多不可能)") == "warn",
          "血量读数不一致 -> warn(黄) —— 这种行正是要人看一眼的")
    check(gui.mark_line("2026-09-15 19:21:27 [turn] our turn starts (kredits read: 1)") == "turn",
          "回合开始 -> turn(橙,和游戏里『能行动』同一个语义)")
    check(gui.mark_line("2026-09-15 19:58:24 == round 3 finished (victory) after 9.5 min ==") == "state",
          "state/胜负 -> state(蓝)")
    check(gui.mark_line("2026-09-15 19:21:25 state -> in_game") == "state", "state -> -> state")
    check(gui.mark_line("2026-09-15 19:38:02 [attack] #1 结论不可信:打的是**单位**") == "warn",
          "结论不可信 -> warn(不许当结论,配色也要中性偏警示)")
    check(gui.mark_line("2026-09-15 19:24:42 [move] 动成功了(我方支援 3->2 且 前线 0->1)") == "ok",
          "动成功了 -> ok")

    print("\n④ 打包成 exe 之后最容易错的两条路径(冻结陷阱)")
    root = gui.project_root()
    check(os.path.exists(os.path.join(root, "src", "main_loop.py")),
          f"项目根要能找到 src/main_loop.py:实得 {root}")
    check(root == os.path.dirname(os.path.dirname(os.path.abspath(gui.__file__))),
          "开发形态下项目根 == src 的上一级(和冻结形态同一套判据)")
    py = gui.engine_python()
    check(os.path.exists(py), f"起引擎用的解释器必须真实存在:实得 {py}")
    check((not getattr(sys, "frozen", False)) or
          os.path.basename(py).lower().startswith("python"),
          "★ 冻结形态下 sys.executable 是 exe 自己 —— 必须换成项目自带的 python")
    check(not (getattr(sys, "frozen", False) and py == sys.executable),
          "冻结时不许拿面板 exe 去执行 main_loop.py(那是必崩的写法)")

    print("\n⑤ 版本文件与更新入口(不假装能更新)")
    v = gui.read_version()
    check(isinstance(v.get("version"), str) and v["version"],
          f"读得到本地版本:实得 {v}")
    check(v.get("update_url") == "",
          "更新源现在是空的 —— 面板必须**如实**说『还没配』,不许假装能更新")

    print("\n⑥ 窗口几何记忆(用户手动拖过窗口,不要每次重拖)")
    with tempfile.TemporaryDirectory() as d:
        keep = gui.WIN_STATE
        gui.WIN_STATE = os.path.join(d, "win.json")
        try:
            check(gui.load_win_state() == {}, "第一次没有记录 -> 空(用默认尺寸)")
            gui.save_win_state(1500, 900, 120, 60)
            got = gui.load_win_state()
            check(got == {"w": 1500, "h": 900, "x": 120, "y": 60},
                  f"存了能读回来:实得 {got}")
            gui.save_win_state(1500, 900)          # 只记尺寸(后端拿不到位置时)
            check(gui.load_win_state() == {"w": 1500, "h": 900},
                  "只给尺寸也能存(位置缺了就不写)")
            with open(gui.WIN_STATE, "w", encoding="utf-8") as f:
                f.write("{坏掉的 json")
            check(gui.load_win_state() == {}, "文件坏了不许炸,退回默认")
        finally:
            gui.WIN_STATE = keep
    # 位置夹回屏幕:拔了副屏之后不许开在看不见的地方
    x, y = gui.clamp_to_screen(-5000, 99999, 1240, 780)
    check(x <= 200 or x >= -1240, f"太靠左要夹回来:实得 x={x}")
    check(y < 99999, f"太靠下要夹回来:实得 y={y}")
    x2, y2 = gui.clamp_to_screen(100, 80, 1240, 780)
    check((x2, y2) == (100, 80), f"正常位置不许动:实得 {(x2, y2)}")

    print("=" * 74)
    if FAILS:
        print(f"{len(FAILS)} 条不通过")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
