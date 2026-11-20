"""gui.py - KARDS AUTO 控制面板(**独立窗口**,pywebview + WebView2)。

为什么要这个:引擎现在是"命令行 + 日志",用起来得开终端、记参数、翻日志。
用户 2026-09-15 要的是一个 **ALAS 那种面板**:开关控制 / 功能选择 / 检测更新 / 日志查看,
外观简洁、有功能性、带点科技感;**要独立窗口,不要浏览器标签**。

技术选型(量过才定的,不是拍脑袋):
  · ALAS 那套壳是 `toolkit\\WebApp\\alas.exe` = Electron + Vue3 + Ant Design(154 MB),
    它本质上只是"打开 http://127.0.0.1:<port> 的薄 Chromium";照抄要改它**编译好的**
    `app.asar`,而且 ALAS 是 **GPL-3.0**(照抄源码 = 本项目成为派生作品)。
  · 本机 **WebView2 运行时已装**(153.0.4234.32),所以用 `pywebview` 起一个**原生窗口 +
    内嵌 Chromium**:没有 154 MB 的壳、不用开浏览器标签、页面照样能用 HTML/CSS 写。
  · ALAS 那份跑在 Python **3.7**,我们是 **3.14** —— 它 pin 的老依赖装不上,所以**只抄形**:
    左侧功能开关 / 中间状态 / 右侧日志,这套布局就是我们照着做的。

界面上的三块 = 用户要的四件事:
  · **功能选择** = 引擎那组命令行开关(`--play/--fast-scan/--attack/--no-lazy/--end-turn/
    --dry-run`)+ "跑几局"(`--max-rounds`);
  · **开关控制** = 开始 / 停止(起一个 `main_loop.py` 子进程;引擎自己有单实例锁,
    这里再挡一层"我自己已经在跑");
  · **日志查看** = 跟 `logs/main_loop.log`(**只读**),关键行高亮 + "只看关键行"过滤;
  · **检测更新** = 版本与文件清单核对；用户点击应用后，校验变更文件并退出面板替换。

★ 它**不碰游戏、不碰鼠标**:只读日志 + 起/停子进程。跑起来的时候别用面板盖住 KARDS
  (盖住了引擎会 fail-closed 不动作,这是它本来就有的规矩)。

用法(两种形态都行,发布包里用的是便携 Python):
    python\\python.exe src\\gui.py                  # 发布包自带的便携 Python
    .venv\\Scripts\\python.exe src\\gui.py          # 自己改代码时的 venv
    python\\python.exe src\\gui.py --debug          # 打开 WebView 的开发者工具
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
# ★ stderr 也要:它在 Windows 上默认跟控制台代码页走,引擎的报错里有中文路径时
#   会变成一串 \ufffd —— 那正好是最需要看清的部分。
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from watch_log import KEY_WORDS  # noqa: E402  (关键行只有一份,别抄第二遍)
import update_check  # noqa: E402  (只依赖标准库,用例 import 本模块时不需要联网)
import update_install  # noqa: E402
import log_io  # noqa: E402


def project_root() -> str:
    """
    项目根在哪 —— **开发形态和冻结成 exe 两种都要对**。

    ★ 为什么不能只写 `dirname(dirname(__file__))`:PyInstaller 打成 exe 之后,
      `__file__` 在**临时解包目录**里(`_MEIPASS`),拿它当项目根会找不到
      `src/main_loop.py`、`logs/`、`config/`。冻结时正确的根是**exe 自己所在的目录**
      (我们就把 exe 放在项目根旁边)。
    ★ 判据是"这个目录下有没有 `src/main_loop.py`",不是"路径长得像不像"。
    """
    cands = []
    if getattr(sys, "frozen", False):
        # exe 可能放在项目根,也可能在 dist\ 这种子目录里 -> 从它所在目录**往上找**
        d = os.path.dirname(os.path.abspath(sys.executable))
        for _ in range(3):
            cands.append(d)
            nd = os.path.dirname(d)
            if nd == d:
                break
            d = nd
    here = os.path.dirname(os.path.abspath(__file__))
    cands += [os.path.dirname(here), here]
    for c in cands:
        if os.path.exists(os.path.join(c, "src", "main_loop.py")):
            return c
    return cands[0]


#: 随发布包发出去的**便携 Python** 在哪(相对项目根)。
#  ★ 为什么必须带一个:Python 的 venv **不支持换机器** —— `pyvenv.cfg` 里写死的
#    是建它那台机器的绝对路径(`home = C:\Python314`)。v0.1.0 的发布包把 .venv
#    一起打了进去,于是**每个下载的人**点「开始」都立刻以 103 退出,见
#    `explain_exit_code`。便携 Python 不是 venv:它的 `sys.prefix` 是从 exe
#    自己的位置推出来的,解压到哪、路径带不带中文,都能跑。
PORTABLE_PYTHON = os.path.join("python", "python.exe")

#: 开发时自己建的虚拟环境,排在便携 Python 后面 —— 正式发布包里没有它。
VENV_PYTHONS = (
    os.path.join(".venv", "Scripts", "python.exe"),
    os.path.join(".venv", "Scripts", "pythonw.exe"),
    os.path.join("venv", "Scripts", "python.exe"),
)

#: `engine_python()` 上一轮为什么挑不出解释器 —— 每个元素是 (路径, 原因)。
#  面板报错时会把这张表念给使用者听,而不是只丢一个"找不到解释器"。
_PYTHON_DIAG: list[tuple[str, str]] = []


def explain_exit_code(code: int | None, output: str = "") -> str:
    """
    把裸的退出码翻译成"使用者看得懂、而且知道下一步做什么"的一句话。

    ★ 103 单列出来,因为它是 v0.1.0 那次事故的全部内容:Windows 上 venv 里的
      `python.exe` 只是个**重定向器**,它去执行 `pyvenv.cfg` 里 `home =` 记的那个
      解释器;那条路径在别人机器上不存在时,它**在 import 任何东西之前**就退 103,
      stdout/stderr 里连一行 Python 输出都没有。当时面板只显示
      「已停止(退出码 103)」,下载的人完全无从下手 —— 现在这句话会直接显示出来。
    """
    blob = output or ""
    if code == 103 or "did not find executable" in blob:
        return ("Python 环境坏了。这份 .venv 是在别的电脑上建的,它按记下来的"
                "绝对路径去找解释器,在你机器上找不到(退出码 103)。"
                "把项目里的 .venv 文件夹整个删掉,再双击 install.cmd 重建一次就好。")
    if code == 2:
        return ("引擎拒绝了启动(退出码 2),最常见的原因是**已经有一个实例在跑**。"
                "先确认没有残留的 python 进程,或者等它自己结束再点开始。")
    if "ModuleNotFoundError" in blob or "ImportError" in blob:
        m = re.search(r"No module named '([^']+)'", blob)
        name = m.group(1) if m else "某个依赖"
        return (f"这个 Python 里没装引擎要用的依赖({name})。"
                "发布包自带的 python\\ 文件夹是装好的;如果你在用自己装的那个 Python,"
                "先双击 install.cmd 把依赖装一遍。")
    if code is None or code == 0:
        return "引擎正常退出。"
    return f"引擎以退出码 {code} 结束,具体原因看面板下面的日志。"


#: 探针要 import 的东西 —— 就是引擎**真的必需**的那几个。
#  ★ 为什么不是只跑个 `print(1)`:一个 import 不了 cv2 的 Python 对引擎毫无用处。
#    "解释器能跑"和"它能干活"是两回事,而使用者要的是后者。少了这一层,PATH 里
#    随便一个裸 Python 都会被当成"找到了",然后在 import 阶段炸掉 —— 那又是一次
#    "报个看不懂的错"。所以宁可在这里判死,让他去装依赖。
PROBE_IMPORTS = "sys,cv2,numpy,mss,win32api"

#: 探针跑的那段代码。★ `print` 包在 try 里:候选里有 `pythonw.exe`,而它在没有
#  控制台时 `sys.stdout` 可能是 `None`,直接 print 会抛异常,把"能跑的解释器"
#  误判成坏的。版本号只是附带信息,拿不到也不该影响结论。
_PROBE_CODE = (
    "import sys\n"
    f"import {PROBE_IMPORTS}\n"
    "try:\n"
    "    print(sys.version.split()[0])\n"
    "except Exception:\n"
    "    pass\n"
)


def python_probe(py: str, timeout: float = 30.0) -> tuple[bool, str]:
    """
    这个解释器**真的能用**吗?返回 (能不能用, 一句话说明)。

    ★ 两道关,少一道都会被坑:
      1. 文件在 ≠ 能跑 —— venv 的 `python.exe` 只是个重定向器,它指向的基础
         解释器一没,文件还在、一跑就退 103(v0.1.0 的事故);
      2. 能跑 ≠ 能干活 —— 一个没装 cv2 的裸 Python 跑 `print(1)` 完全没问题,
         但它跑不了引擎(见 `PROBE_IMPORTS`)。
    """
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        r = subprocess.run([py, "-c", _PROBE_CODE],
                           capture_output=True, text=True, timeout=timeout,
                           creationflags=flags)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    if r.returncode == 0:
        return True, (r.stdout or "").strip() or "可以运行"
    return False, explain_exit_code(r.returncode, (r.stderr or "") + (r.stdout or ""))


def engine_python() -> str | None:
    """
    起引擎(`main_loop.py`)该用哪个解释器。一个能用的都没有时返回 `None`,
    原因记在 `_PYTHON_DIAG` 里。

    ★ 冻结成 exe 之后 `sys.executable` 是**那个 exe 自己**,不是 python ——
      直接拿它去跑 main_loop 会变成"用面板 exe 去执行一个 .py",必然失败。
      开发形态下就是当前解释器(原行为不变)。

    ★ 每一档都**真跑一次探针**,不是看文件在不在。坏的那档跳过、继续往下找 ——
      这样"某个 .venv 是从别的机器拷来的"不至于让面板整个用不了,
      而且使用者能拿到一条明确的出路(装过 Python 的话就走 PATH 里那个)。
    """
    if not getattr(sys, "frozen", False):
        return sys.executable

    cands = [os.path.join(PROJECT_ROOT, PORTABLE_PYTHON)]
    cands += [os.path.join(PROJECT_ROOT, r) for r in VENV_PYTHONS]
    from shutil import which
    cands += [w for w in (which("python"), which("pythonw")) if w]

    _PYTHON_DIAG.clear()
    for c in cands:
        if not os.path.exists(c):
            continue
        ok, why = python_probe(c)
        if ok:
            return c
        _PYTHON_DIAG.append((c, why))
    return None


PROJECT_ROOT = project_root()
SRC = os.path.join(PROJECT_ROOT, "src")
MAIN_LOOP = os.path.join(SRC, "main_loop.py")
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
LOG = os.path.join(LOG_DIR, "main_loop.log")
GUI_RUN_LOG = os.path.join(LOG_DIR, "gui_run.log")
VERSION_FILE = os.path.join(PROJECT_ROOT, "config", "app_version.json")
#: "检测更新"的留痕(每次查完追加一行,含开机那次静默的)—— 见 log_update()
UPDATE_LOG = os.path.join(LOG_DIR, "update_check.log")

APP_NAME = "KARDS AUTO"

#: 面板上的"功能选择" —— 每一项对应引擎的一个命令行开关。
#   `key` 同时是前端开关的 id;`flag` 是真正传给 main_loop 的参数。
SWITCHES = [
    {"key": "play", "flag": "--play", "label": "自动打完一局",
     "hint": "部署 + 出牌 + 结束回合(不开就是只看不动)"},
    {"key": "attack", "flag": "--attack", "label": "攻击",
     "hint": "按规则表挑攻击者与目标(含守护/拦截判据)"},
    {"key": "ranked", "flag": "--ranked", "label": "排位模式",
     "hint": "⚠️ 可能被游戏检测并有封号风险；需要确认后才启用"},
    {"key": "fast_scan", "flag": "--fast-scan", "label": "坐标表直扫",
     "hint": "使用已标定的手牌坐标(需先完成标定，速度更快)"},
    {"key": "classic_strategy", "flag": "--classic-strategy", "label": "传统策略",
     "hint": "绕过橙色筛选和凑费，使用传统扫描与出牌流程；停止后重新开始生效"},
    {"key": "message_input", "flag": "--message-input", "label": "不抢鼠标（实验）",
     "hint": "关=物理鼠标；开=窗口消息悬停/点击/拖拽。游戏须前台可见；可能不响应，不自动回退；停止后重启生效"},
    {"key": "end_turn", "flag": "--end-turn", "label": "结束回合",
     "hint": "只在未开启『自动打完一局』时单独点结束回合"},
    #  ★ 2026-09-21 用户要求改口径:干跑**是调试用的,平时不需要开**
    #    (原来写的是"第一次开面板建议先开它" —— 那会让人以为跑之前都该勾上,
    #     结果真打的时候忘了关,看起来就像"引擎不动")。
    {"key": "dry_run", "flag": "--dry-run", "label": "只看不动(调试用)",
     "hint": "调试用:只记决策、不点鼠标。平时不需要开 —— 要真打就得关掉它"},
]

#: 默认勾上的(和平时跑实机的命令行一致)。
DEFAULT_ON = {"play", "attack", "fast_scan"}

RE_ROUND = re.compile(r"== round (\d+) finished \((\w+)\) after ([\d.]+) min ==")
RE_STATE = re.compile(r"state -> (\w+)")
RE_KREDITS = re.compile(r"our turn starts \(kredits read: (\S+) \[(\w+)\]")
RE_BOARD = re.compile(r"战场基准: 我支援 (\d+) 张卡\(单位 (.+?)\) / "
                      r"我前线 (\d+) / 敌前线 (\d+) / 敌支援 (\d+)")
RE_ACTION = re.compile(r"\[(turn|attack|move|in_game|dismiss|记忆)\] (.*)")
RE_START = re.compile(r"main_loop start \(dry=(\w+) end_turn=(\w+) max_rounds=(\d+)\)")

#: "值得看一眼"的行 —— 这些行说明**某条判据当时没下成结论**、或者出了异常。
#  ★ 只收"异常",**不收正常结局**:`没打中` / `没动成` 都是如实记下的一种结果
#    (引擎按设计就会这么写),把它们算进计数会让面板一直红着,最后没人看。
#  ★ `读数不一致` / `不可能` 是 2026-09-15 那三次"晚读血量读到不可能的值"留下的词 ——
#    那种行正需要人看一眼。
ISSUE_WORDS = ("⚠️", "Traceback", "💥", "结论不可信", "被拒绝",
               "读数不一致", "不可能")


# ---------------------------------------------------------------------------
# 纯函数:日志 -> 面板要显示的东西(用例 `gui_test.py` 直接考这几个)
# ---------------------------------------------------------------------------
def tail_lines(path: str, n: int = 400) -> list[str]:
    """
    读日志**末尾 n 行**(文件可能几 MB,只从尾巴读)。

    ★ 用二进制读再自己解码:文本模式从中间 seek 会把多字节汉字切断
      (`watch_log.py` 里踩过同一个坑,那里留了说明)。
    """
    return log_io.tail_lines(path, n)


def log_rev(path: str) -> str:
    """
    日志"变没变"的指纹(大小 + 纳秒级 mtime),面板据此决定要不要重画日志区。

    ★★★ 为什么要专门做这么一个东西 —— 2026-09-19 用户报的 bug:
      **"日志滚到一定时候就不动了,向下翻也翻不下去。"**
      面板的尾巴只取 400 行,所以**日志一旦超过 400 行,`len(log_lines)` 就永远是 400**;
      而前端原来的判据是 `s.log_lines.length !== lastLen` —— 从那以后**恒为假**,
      日志区再也不重画。用户那边看起来就是"卡住了",而且往下翻也确实没有新内容。
      ⇒ 教训:**行数是会饱和的量,不能拿它判"变了没有"**。要用文件本身的变化。
      (这条和 §7 第 96 条那种"判据链退化"是同一类错:判据在边界外悄悄失效。)
    """
    return log_io.revision(path)


def parse_status(lines: list[str]) -> dict:
    """把日志末尾那几行解析成面板顶部/中间要显示的状态(读不出来就留空)。"""
    out = {
        "rounds": [], "state": None, "kredits": None, "kredits_how": None,
        "board": None, "last_action": None, "last_line": None,
        "started": None, "issues": 0,
    }
    for ln in lines:
        body = ln[20:] if len(ln) > 20 and ln[4] == "-" else ln
        m = RE_START.search(body)
        if m:
            out["started"] = {"dry": m.group(1) == "True",
                              "end_turn": m.group(2) == "True",
                              "max_rounds": int(m.group(3))}
            out["rounds"] = []            # 新的一段:局数清零
        m = RE_ROUND.search(body)
        if m:
            out["rounds"].append({"n": int(m.group(1)), "result": m.group(2),
                                  "min": float(m.group(3))})
        m = RE_STATE.search(body)
        if m:
            out["state"] = m.group(1)
        m = RE_KREDITS.search(body)
        if m:
            out["kredits"] = m.group(1)
            out["kredits_how"] = m.group(2)
        m = RE_BOARD.search(body)
        if m:
            out["board"] = {"our": int(m.group(1)), "our_units": m.group(2),
                            "front": int(m.group(3)), "enemy_front": int(m.group(4)),
                            "enemy": int(m.group(5))}
        m = RE_ACTION.search(body)
        if m:
            out["last_action"] = {"tag": m.group(1), "text": m.group(2)[:160]}
        if any(w in body for w in ISSUE_WORDS):
            out["issues"] += 1
        out["last_line"] = body
    # ★ 引擎"在等窗口"时,面板中间那块显示的其实是**上一局的旧状态**(实测:跑到
    #   `KARDS window not found - waiting` 时,中间还写着上次的 victory/费用 11)——
    #   不点出来的话很容易被当成"它正在打"。这一条专门把它挑明。
    ll = out.get("last_line") or ""
    out["waiting"] = any(w in ll for w in (
        "not found", "不可见", "被遮挡", "blank frame"))
    return out


def mark_line(line: str) -> str:
    """给日志行挑一个样式类(颜色语义跟着游戏走:橙=能行动 / 灰=已行动)。"""
    if "Traceback" in line or "💥" in line:
        return "bad"
    if "打中了" in line or "部署成功" in line or "动成功了" in line:
        return "ok"
    if any(w in line for w in ISSUE_WORDS) or "没打中" in line or "没动成" in line:
        return "warn"
    if "our turn starts" in line:
        return "turn"
    if "state ->" in line or ("round" in line and "finished" in line):
        return "state"
    if any(w in line for w in ("[attack]", "[move]", "deploying", "部署")):
        return "act"
    if line.startswith("     ") or "徽章全表" in line:
        return "dim"
    return ""


def build_argv(opts: dict) -> list[str]:
    """面板上的勾选 -> 真正要传给 `main_loop.py` 的参数(argv)。"""
    argv = []
    for sw in SWITCHES:
        if opts.get(sw["key"]):
            argv.append(sw["flag"])
    try:
        rounds = int(opts.get("max_rounds") or 0)
    except (TypeError, ValueError):
        rounds = 0
    if rounds > 0:
        argv += ["--max-rounds", str(rounds)]
    return argv


def options_path() -> str:
    # 动态跟随 --root；配置属于项目目录，不属于 onefile 的临时解包目录。
    return os.path.join(PROJECT_ROOT, "config", "gui_options.json")


def normalize_options(opts: dict) -> dict:
    """只保存已知开关和 0~99 局；保留 False 和 0 的含义。"""
    if not isinstance(opts, dict):
        raise ValueError("配置必须是对象")
    out = {}
    for sw in SWITCHES:
        key = sw["key"]
        value = opts.get(key, key in DEFAULT_ON)
        if not isinstance(value, bool):
            raise ValueError(f"{sw['label']} 必须为开或关")
        out[key] = value
    rounds = opts.get("max_rounds", 3)
    if (type(rounds) not in (int, str)
            or not re.fullmatch(r"[0-9]{1,2}", str(rounds))):
        raise ValueError("跑几局必须是 0~99 的整数（0 = 一直跑）")
    out["max_rounds"] = int(rounds)
    return out


def load_options() -> dict:
    try:
        with open(options_path(), encoding="utf-8-sig") as f:
            return normalize_options(json.load(f))
    except (OSError, ValueError, TypeError):
        return normalize_options({})


def save_options(opts: dict) -> dict:
    """先写临时文件再替换，失败时保留上一次配置并把异常交给面板。"""
    cleaned = normalize_options(opts)
    path = options_path()
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                         prefix="gui_options_", suffix=".tmp",
                                         delete=False) as f:
            tmp = f.name
            json.dump(cleaned, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)
    return cleaned


def read_version() -> dict:
    """
    读 `config/app_version.json`。

    ★★★ 2026-09-19(v0.1.3):必须用 **utf-8-sig** 读。
      这个文件是**给人改的**,而 Windows 上的记事本 / PowerShell 的
      `Set-Content -Encoding UTF8` 都会在开头写一个 **BOM**(EF BB BF)。
      用 `encoding="utf-8"` 读的话,`json.load` 会抛异常 -> 被下面那个
      `except` 吞掉 -> 版本号静默变成 **"0.0.0"**。
      以前这只是"面板上显示个 0.0.0",无所谓;现在版本号是**功能**了
      (检测更新拿它比大小),再静默变 0.0.0 就会变成"永远提示有新版本"。
      实测就踩到了:自检文件里写着 `版本: 0.0.0`,而文件里明明是 0.1.3。
      `utf-8-sig` 有 BOM 就吃掉、没有也照读,两种都安全。
    """
    try:
        with open(VERSION_FILE, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {"version": "0.0.0", "update_url": ""}


def log_update(line: str) -> None:
    """
    把一次"检测更新"的结果追加进 `logs/update_check.log`。

    ★★★ 2026-09-19(v0.1.3):**开机那次自动检查也非要留痕不可。**
      自动那一次是**静默**的(查到才改按钮、查不到什么都不说),于是
      "查到没有新版本"和"那个后台线程压根没跑起来"在界面上**长得一模一样** ——
      这正是这个项目反复踩的那类坑(空壳图、`sh -c` 包多一层、假 adbd、exe 里是旧代码)。
      留一行文件,两条路当场分得开;顺带把"走的是 API 还是备用源"也记下来。
      ★ 写在 `logs/` 里(不是 `gui_selftest.txt`):那个文件是自检专用的,
        而且 `logs/*` 既不进仓库也不进发布包。
    """
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(UPDATE_LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
    except Exception:
        pass          # 记不下来也绝不许影响面板


def auto_update_once(window=None) -> dict:
    """
    开机后台查一次(**静默**)。查到新版本就把按钮改成「有新版本 vX」;
    查不到 / 出错都**一句话都不说** —— 只有手动点按钮那条路才"必须如实回答"。

    返回查到的结果(测试和日志用)。`window=None` 时只查 + 记日志、不碰界面
    —— 这样这条逻辑能离线测(见 `dev/gui_test.py` ⑦)。

    ★ 为什么自动那次可以静默:手动那条路会**逐条说清**为什么查不到,
      所以"没提示"只意味着"没有新版本",不意味着"我们不知道"。
      但**必须留痕**(见 `log_update`),否则静默就等于"什么都可能发生"。
    """
    local = str(read_version().get("version") or "0.0.0")
    try:
        r = update_check.check(local)
    except Exception as e:                     # 自动这条路绝不许影响面板
        log_update(f"[自动] 出错({type(e).__name__}: {e})")
        return {}
    log_update(f"[自动] 本地 v{local} ok={r.get('ok')} "
               f"has_update={r.get('has_update')} remote={r.get('remote')} "
               f"via={r.get('via')} | {r.get('msg')}")
    if window is not None and r.get("has_update"):
        try:
            url = r.get("url") or update_check.RELEASES_PAGE
            label = f"有新版本 {r.get('remote') or ''}".strip()
            # updUrl 是页面脚本里的顶层 let,赋值会落到那个绑定上(不必挂到 window)
            window.evaluate_js(f"updUrl = {json.dumps(url)};"
                               f"document.getElementById('btnUpdate')"
                               f".textContent = {json.dumps(label)};")
        except Exception as e:                 # 改不动按钮只记一笔,别弹错
            log_update(f"[自动] 界面没改成({type(e).__name__}: {e})")
    return r


def _auto_update_thread(window, delay: float = 3.0) -> None:
    """给 `webview.start()` 用的那个后台线程入口:先让窗口画出来,再查。"""
    try:
        time.sleep(delay)          # 别跟"把窗口画出来"抢时间
        auto_update_once(window)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 窗口尺寸/位置记忆(2026-09-16 加)
#
# 为什么:用户是**手动拖窗口**的(他自己说的"我干的"),每次都重拖很烦;
# 而且以前出现过"面板被别的程序改了尺寸"的误会(那个真 bug 在 `win.find_by_process`,
# 这里只是让"尺寸不对"这件事更容易恢复)。
# 存哪儿:`config/gui_window.json`;关窗口时写,开窗口时读。
# ---------------------------------------------------------------------------
WIN_STATE = os.path.join(PROJECT_ROOT, "config", "gui_window.json")
WIN_MIN = (1020, 640)


def load_win_state() -> dict:
    """读上次的窗口几何(没有/坏了就返回空 dict,用默认值)。"""
    try:
        with open(WIN_STATE, "r", encoding="utf-8") as f:
            d = json.load(f)
        out = {}
        for k in ("w", "h", "x", "y"):
            if k in d and d[k] is not None:
                out[k] = int(d[k])
        return out
    except Exception:
        return {}


def save_win_state(w, h, x=None, y=None) -> None:
    """记下窗口几何。参数是**普通数字**,方便用例直接考(不需要真窗口)。"""
    try:
        d = {"w": int(w), "h": int(h)}
        if x is not None and y is not None:
            d["x"], d["y"] = int(x), int(y)
        os.makedirs(os.path.dirname(WIN_STATE), exist_ok=True)
        with open(WIN_STATE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except Exception:
        pass


def clamp_to_screen(x: int, y: int, w: int, h: int) -> tuple:
    """
    把记下来的位置夹回屏幕内 —— 否则换了显示器/拔了副屏之后,
    窗口会开在看不见的地方(那种"面板打不开"的假故障最难查)。
    """
    try:
        import ctypes
        sw = ctypes.windll.user32.GetSystemMetrics(0)
        sh = ctypes.windll.user32.GetSystemMetrics(1)
        if sw <= 0 or sh <= 0:
            return x, y
        x = max(-w + 200, min(int(x), sw - 200))
        y = max(0, min(int(y), sh - 120))
    except Exception:
        pass
    return int(x), int(y)


# ---------------------------------------------------------------------------
# 面板与 Python 之间的桥(pywebview 的 js_api)
# ---------------------------------------------------------------------------
JS_API_METHODS = (
    'snapshot', 'save_settings', 'start', 'stop',
    'check_update', 'install_update', 'open_release',
    'emu_snapshot', 'emu_save_options', 'emu_start', 'emu_stop', 'emu_control',
)


def make_js_api(api):
    """Expose methods only: pywebview recursively inspects public attributes.

    Passing Api itself traverses api.window.native.AccessibilityObject and can
    hang the native UI during bridge initialization. Keep runtime objects out
    of the object being reflected, including the process after engine start.
    """
    return SimpleNamespace(**{name: getattr(api, name) for name in JS_API_METHODS})


class Api:
    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.started_at: float | None = None
        self.last_opts: dict = {}
        self.saved_options = load_options()
        self.error: str | None = None
        self._fh = None
        self._stop_file = None
        self.window = None
        self._update_lock = threading.Lock()
        self._update_release = None
        self._update_state = update_install.latest_status(PROJECT_ROOT)
        self._log_lock = threading.Lock()
        self._log_cache = None
        self._emu_manager = None
        self._emu_root = None
        self._emu_lock = threading.RLock()

    def _get_emu_manager(self):
        import emu_manager
        with self._emu_lock:
            root = os.path.abspath(PROJECT_ROOT)
            if self._emu_manager is None or self._emu_root != root:
                if self._emu_manager is not None:
                    if self._emu_manager.has_running_workers():
                        raise RuntimeError("请先停止模拟器自动对局，再切换项目目录")
                self._emu_manager = emu_manager.EmuManager(PROJECT_ROOT, python_exe=engine_python())
                self._emu_root = root
            return self._emu_manager

    def emu_snapshot(self, selected_log_id: str = "", log_since_rev: str = "") -> dict:
        result = self._get_emu_manager().snapshot(
            selected_log_id=selected_log_id, log_since_rev=log_since_rev)
        result = dict(result)
        if result.get("log") is not None:
            result["log"] = dict(result["log"])
            result["log"]["log_lines"] = [[mark_line(ln), ln] for ln in result["log"]["lines"]]
        return result

    def emu_save_options(self, opts: dict) -> dict:
        try:
            import emu_manager
            saved = emu_manager.save_emu_options(opts, PROJECT_ROOT)
            return {"ok": True, "options": saved, "msg": "模拟器配置已保存"}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    def emu_start(self, instance_ids: list[str], opts: dict | None = None) -> dict:
        # Serialize starts with update preparation; PC method signatures stay unchanged.
        if self._update_state.get("phase") in ("preparing", "closing", "recovery"):
            return {"ok": False, "msg": "更新期间不能启动自动对局",
                    "started": [], "failed": list(instance_ids), "results": {}}
        with self._update_lock, self._emu_lock:
            if self._update_state.get("phase") in ("preparing", "closing", "recovery"):
                return {"ok": False, "msg": "更新期间不能启动自动对局",
                        "started": [], "failed": list(instance_ids), "results": {}}
            try:
                if opts is not None:
                    saved = self.emu_save_options(opts)
                    if not saved["ok"]:
                        raise ValueError(saved["msg"])
                    opts = saved["options"]
                result = self._get_emu_manager().start_many(instance_ids, opts=opts)
                return dict(result, msg=f"已启动 {len(result['started'])} 个实例；失败 {len(result['failed'])} 个")
            except Exception as exc:
                return {"ok": False, "msg": str(exc), "started": [],
                        "failed": list(instance_ids), "results": {}}

    def emu_stop(self, instance_ids: list[str] | None = None) -> dict:
        try:
            with self._emu_lock:
                # Closing a PC-only panel must not import or construct the emulator manager.
                if self._emu_manager is None:
                    return {"ok": True, "msg": "模拟器自动对局已停止", "stopped": []}
                mgr = self._emu_manager
                if not instance_ids:
                    result = mgr.stop_all()
                    return dict(result, msg="模拟器自动对局已停止")
                results = {iid: mgr.stop_instance(iid) for iid in dict.fromkeys(instance_ids)}
                stopped = [iid for iid, r in results.items() if r["ok"]]
                return {"ok": True, "msg": f"已停止 {len(stopped)} 个实例", "stopped": stopped}
        except Exception as exc:
            return {"ok": False, "msg": str(exc), "stopped": []}

    def emu_control(self, instance_id: str, action: str) -> dict:
        if action not in ("launch", "shutdown"):
            return {"ok": False, "msg": "不支持的模拟器操作"}
        try:
            mgr = self._get_emu_manager()
            result = (mgr.launch_emulator(instance_id) if action == "launch"
                      else mgr.shutdown_emulator(instance_id))
            return dict(result, msg=result.get("msg") or ("操作已完成" if result["ok"] else "操作失败"))
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    def _close_run_log(self) -> None:
        """Release the child log handle after the child has stopped."""
        fh, self._fh = self._fh, None
        if fh is not None:
            try:
                fh.close()
            except Exception:
                pass

    # ---- 状态 ----
    def snapshot(self, only_key: bool = False, tail: int = 400, since_rev=None) -> dict:
        running = self.proc is not None and self.proc.poll() is None
        if not running and self.proc is not None:
            # A child may exit on its own; do not retain one file descriptor
            # for every start/stop cycle until the panel itself closes.
            self._close_run_log()
        tail = max(0, min(int(tail), log_io.MAX_TAIL_LINES))
        with self._log_lock:
            rev = log_rev(LOG)
            key = (LOG, rev, tail)
            if self._log_cache is None or self._log_cache['key'] != key:
                lines = tail_lines(LOG, tail)
                self._log_cache = {'key': key, 'status': parse_status(lines),
                    'all': [[mark_line(ln), ln] for ln in lines],
                    'only_key': [[mark_line(ln), ln] for ln in lines
                                 if any(w in ln for w in KEY_WORDS)]}
            st = self._log_cache['status']
            marked = self._log_cache['only_key' if only_key else 'all']
            # An unchanged log needs no repeated bridge transfer or DOM rebuild.
            marked = [] if since_rev == rev else marked
        ver = read_version()
        return {
            "running": running,
            "pid": self.proc.pid if running else None,
            "elapsed": (round(time.time() - self.started_at)
                        if (running and self.started_at) else None),
            "argv": self.last_opts.get("argv") or [],
            "log_lines": marked,
            # ★ 面板靠这个判"日志变了没有"(**不是靠行数** —— 行数会饱和在 400,
            #   见 `log_rev()` 的说明)。空串 = 日志文件还不存在。
            "log_rev": rev,
            "status": st,
            "version": ver.get("version", "?"),
            "switches": SWITCHES,
            "default_on": sorted(DEFAULT_ON),
            "saved_options": dict(self.saved_options),
            "update_state": dict(self._update_state),
            "error": self.error,
            "exit_code": (None if running or self.proc is None
                          else self.proc.returncode),
            # 鼠标停在小圆点上时把退出码翻译成人话(v0.1.0 只显示一个裸数字)
            "exit_hint": ("" if running or self.proc is None
                          else explain_exit_code(self.proc.returncode)),
        }

    def save_settings(self, opts: dict) -> dict:
        try:
            self.saved_options = save_options(opts)
            return {"ok": True, "msg": "配置已自动保存"}
        except (OSError, ValueError, TypeError) as e:
            return {"ok": False, "msg": f"保存失败：{e}"}

    # ---- 开关控制 ----
    def start(self, opts: dict) -> dict:
        if self._update_state.get('phase') in ('preparing', 'closing', 'recovery'):
            return {"ok": False, "msg": "请先完成更新或恢复旧文件"}
        if self.proc is not None and self.proc.poll() is None:
            return {"ok": False, "msg": "已经在跑了"}
        self._close_run_log()
        saved = self.save_settings(opts or {})
        if not saved["ok"]:
            return saved
        opts = dict(self.saved_options)
        argv = build_argv(opts)
        if not argv:
            return {"ok": False, "msg": "一个功能都没勾 —— 至少勾一个再开始"}
        os.makedirs(LOG_DIR, exist_ok=True)
        if not os.path.exists(MAIN_LOOP):
            return {"ok": False, "msg": f"找不到引擎脚本:{MAIN_LOOP}"}
        py = engine_python()
        if py is None:
            detail = "\n".join(f"  · {p}\n      {why}" for p, why in _PYTHON_DIAG) \
                     or "  · 一个 Python 都没找到"
            self.error = ("找不到能用的 Python 解释器。试过这些:\n" + detail +
                          "\n\n发布包里本该自带一个 python\\ 文件夹(便携 Python);"
                          "如果项目里有 .venv,把它整个删掉再跑一次 install.cmd。")
            return {"ok": False, "msg": self.error}
        cmd = [py, "-u", MAIN_LOOP] + argv
        flags = 0
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            try:
                archived = log_io.archive_large(GUI_RUN_LOG)
                if archived: log_update('[日志] 旧运行日志已归档：'+str(archived))
            except OSError as error:
                log_update(f'[日志] 运行日志暂不能归档，继续追加：{error}')
            self._fh = open(GUI_RUN_LOG, "ab", buffering=0)
            self._fh.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} "
                           f"{' '.join(cmd)} ===\n".encode("utf-8"))
            env = os.environ.copy()
            env.pop('KARDS_AUTO_STOP_FILE', None)
            self._stop_file = None
            if opts.get('message_input'):
                controls = os.path.join(PROJECT_ROOT, 'logs', 'controls')
                os.makedirs(controls, exist_ok=True)
                self._stop_file = os.path.join(controls, uuid.uuid4().hex + '.stop')
                env['KARDS_AUTO_STOP_FILE'] = self._stop_file
            self.proc = subprocess.Popen(
                cmd, cwd=PROJECT_ROOT, stdout=self._fh,
                stderr=subprocess.STDOUT, creationflags=flags, env=env)
            self.started_at = time.time()
            self.error = None
            self.last_opts = {"argv": argv, **{k: bool(v) for k, v in (opts or {}).items()}}

            # ★ 起来之后**等一下再看它死没死**。
            #   引擎正常跑起来要好几秒才写第一行日志,而解释器坏掉、或者脚本在
            #   import 阶段就炸,都是**毫秒级**退出。v0.1.0 没有这一步,使用者看到
            #   的是"点开始后立刻停止(退出码 103)",一个字的上下文都没有 ——
            #   明明 gui_run.log 里就躺着 `did not find executable at '...'`。
            #   ★ 1.2 秒足够区分这两种情况:能跑的解释器在这段时间里绝不会退出。
            time.sleep(1.2)
            rc = self.proc.poll()
            if rc is not None:
                tail = tail_lines(GUI_RUN_LOG, 40)
                self._close_run_log()
                self.error = (f"启动失败(退出码 {rc})。"
                              + explain_exit_code(rc, "\n".join(tail)))
                return {"ok": False, "msg": self.error, "exit_code": rc,
                        "argv": argv, "log_tail": tail[-12:]}

            return {"ok": True, "msg": f"已启动 pid={self.proc.pid}",
                    "argv": argv}
        except Exception as e:
            self._close_run_log()
            self.error = f"{type(e).__name__}: {e}"
            return {"ok": False, "msg": self.error}

    def stop(self) -> dict:
        if self.proc is None or self.proc.poll() is not None:
            return {"ok": False, "msg": "没在跑"}
        try:
            if self.last_opts.get('message_input'):
                if not self._stop_file:
                    return {"ok": False, "msg": "缺少安全停止通道，未强杀消息输入进程"}
                with open(self._stop_file, 'w', encoding='utf-8') as marker:
                    marker.write('stop\n')
                try:
                    self.proc.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    return {"ok": True, "msg": "停止已请求，等待识别结束并安全释放；未强杀进程"}
                return {"ok": True, "msg": f"已安全停止(退出码 {self.proc.returncode})"}
            self.proc.terminate()
            try:
                self.proc.wait(timeout=6)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=4)
            return {"ok": True, "msg": f"已停止(退出码 {self.proc.returncode})"}
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            return {"ok": False, "msg": self.error}
        finally:
            if self.proc.poll() is not None:
                self._close_run_log()

    # ---- 检测更新 ----
    def check_update(self) -> dict:
        """
        ★★ 2026-09-19(v0.1.2):**真去查了**。

        v0.1.0~v0.1.1 这里写的是"项目不是 git 仓库,更新源没定,所以不假装能更新" ——
        那是诚实,但等于没这功能。现在项目在 GitHub 上有 Release 了,机制定了:
        查 `releases/latest`,和 `config/app_version.json` 里的版本号比。

        ★ 三条纪律照抄 `update_check` 里的:查不到就说查不到(不许说成"已是最新")、
        应用更新必须由用户点击，先校验，再退出面板替换文件、
        纯逻辑离线可测。
        ★ `update_url` 仍然有用:填了就用填的那个地址(别的地方发的包也能查)。
        """
        ver = read_version()
        local = str(ver.get("version") or "0.0.0")
        r = update_check.check(local, ver.get("update_url"))
        manifest_asset = r.get("manifest_asset") or {}
        manifest_url = manifest_asset.get("browser_download_url")
        if r.get("ok") and manifest_url:
            try:
                manifest = update_install.read_manifest(manifest_asset, r['remote'])
                plan = update_install.plan_update(PROJECT_ROOT, manifest)
                if r['remote'] == local and update_install.newer_build(PROJECT_ROOT, manifest):
                    r['has_update'] = True
                    r['msg'] = f'发现 v{local} 的修订更新'
                diff = dict(ok=True, changed=[x['path'] for x in plan['files'] if x['before']],
                            missing=[x['path'] for x in plan['files'] if not x['before']],
                            same=plan['same'], bytes=plan['bytes'], protected=plan['skipped'])
            except Exception as error:
                diff = dict(ok=False, msg=f'文件清单核对失败：{error}')
            r["file_changes"] = diff
            if diff.get("ok"):
                changed = diff.get("changed", [])
                missing = diff.get("missing", [])
                names = (changed + missing)[:12]
                suffix = "" if len(changed) + len(missing) <= 12 else " …"
                detail = "; ".join(names) + suffix if names else "无"
                r["msg"] += f"；本地文件差异 {len(changed)} 个变更、{len(missing)} 个缺失"
                if names:
                    r["msg"] += f"（{detail}）"
            else:
                r["msg"] += f"；{diff.get('msg', '文件清单不可用')}"
        elif r.get("ok"):
            reason = r.get('asset_error') or '该 Release 没有文件清单附件'
            r["file_changes"] = {"ok": False, "changed": [], "missing": [],
                                  "same": 0, "msg": reason}
            r["msg"] += f"；{reason}，无法列出文件差异"
        # 记住发布页地址:第二次点按钮就是"打开发布页"(用系统默认浏览器)
        self._release_url = r.get("url") or update_check.RELEASES_PAGE
        self._has_update = bool(r.get("has_update"))
        files = r.get('file_changes') or {}
        r['can_apply'] = bool(r.get('ok') and r.get('has_update') and files.get('ok')
            and (files.get('changed') or files.get('missing'))
            and not update_check.is_newer(local, r.get('remote'))
            and str((r.get('asset') or {}).get('name', '')).startswith('kards-auto_v'))
        self._update_release = dict(r) if r['can_apply'] else None
        log_update(f"[手动] 本地 v{local} ok={r.get('ok')} "
                   f"has_update={r.get('has_update')} remote={r.get('remote')} "
                   f"via={r.get('via')} | {r.get('msg')}")
        return dict(r, version=local)

    def install_update(self) -> dict:
        if self._emu_manager is not None and self._emu_manager.has_running_workers():
            return {"ok": False, "msg": "请先停止自动对局，再应用更新"}
        if self.proc is not None and self.proc.poll() is None:
            return {'ok': False, 'msg': '请先停止自动对局，再应用更新'}
        if not self.window:
            return {'ok': False, 'msg': '更新需要从独立面板应用'}
        if not self._update_release and self._update_state.get('phase') != 'recovery':
            return {'ok': False, 'msg': '请先检测更新'}
        if not self._update_lock.acquire(blocking=False):
            return {'ok': False, 'msg': '更新正在进行中'}
        if self._emu_manager is not None and self._emu_manager.has_running_workers():
            self._update_lock.release()
            return {"ok": False, "msg": "请先停止自动对局，再应用更新"}
        recovery = self._update_state if self._update_state.get('phase') == 'recovery' else None
        release = self._update_release
        self._update_state = {'phase': 'preparing', 'msg': '正在准备更新'}

        def worker():
            try:
                with update_install.engine_guard():
                    py = engine_python()
                    if not py: raise RuntimeError('找不到可运行的 Python')
                    if recovery:
                        job = recovery['job']
                    else:
                        def progress(msg): self._update_state = {'phase': 'preparing', 'msg': msg}
                        job = update_install.stage_update(PROJECT_ROOT, release, progress)
                    if job is None:
                        self._update_state = {'phase': 'done', 'msg': '文件已一致，无需替换'}
                        return
                    restart = {'cwd': PROJECT_ROOT, 'argv':
                        [sys.executable, '--root', PROJECT_ROOT] if getattr(sys, 'frozen', False) else
                        [py, os.path.join(SRC, 'gui.py'), '--root', PROJECT_ROOT]}
                    update_install.launch_helper(job, py, update_install.panel_exit_pid(), restart, recover=bool(recovery))
                    self._update_state = {'phase': 'closing', 'msg': '文件已校验，正在关闭面板并应用更新'}
                    log_update('[安装] '+self._update_state['msg'])
                    self.window.destroy()
            except Exception as error:
                self._update_state = {'phase': 'error', 'msg': f'更新未完成：{error}'}
                log_update('[安装] '+self._update_state['msg'])
            finally:
                self._update_lock.release()
        threading.Thread(target=worker, daemon=False).start()
        return {'ok': True, 'msg': '正在下载并校验；完成后面板会自动重启'}

    def open_release(self) -> dict:
        """用系统默认浏览器打开发布页(面板自己不去下载、更不去替换自己)。"""
        url = getattr(self, "_release_url", "") or update_check.RELEASES_PAGE
        try:
            import webbrowser
            ok = webbrowser.open(url)
        except Exception as e:                      # 打不开也要把地址给出来
            return {"ok": False, "msg": f"打不开浏览器({type(e).__name__}: {e})。"
                                        f"地址:{url}"}
        if not ok:
            return {"ok": False, "msg": f"系统没接住这个链接。地址:{url}"}
        return {"ok": True, "msg": f"已用浏览器打开:{url}"}


HTML = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>KARDS AUTO · 桌面控制台</title>
<style>
:root {
  color-scheme:dark; --bg:#141416; --panel:#222225; --subpanel:#29292d; --well:#19191c;
  --line:#39393e; --edge:#808088; --text:#f1efe9; --muted:#b1afb5; --iris:#ac9af7;
  --light:#c9bcff; --tint:#363046; --deep:#231b36; --warn:#ecbd7d; --bad:#f3a5ac; --info:#b2c1e8;
  --mono:Consolas,'Cascadia Mono',monospace; accent-color:var(--iris); font:14px/1.5 'Segoe UI','Microsoft YaHei UI',sans-serif;
}
* {box-sizing:border-box}
body {margin:0; height:100vh; display:flex; flex-direction:column; color:var(--text); background:var(--bg)}
h1,h2,p,dl,dd {margin:0} h1 {font-size:24px} h2 {font-size:20px} code {font-family:var(--mono)}
button,input {font:inherit} button {padding:6px 12px; background:#303035; border:1px solid var(--edge); color:var(--text); border-radius:6px; cursor:pointer; transition:background .14s,border-color .14s,color .14s}
button:not(:disabled):hover {background:#3b3b42; border-color:var(--muted)} button:not(:disabled):active {background:#484850} button:disabled {background:var(--subpanel); color:#97959c; border-color:var(--line); cursor:not-allowed}
button:focus-visible,input:focus-visible,summary:focus-visible,#log:focus-visible {outline:3px solid var(--light); outline-offset:2px}
header,.tools,.buttons,.title-line,.journal-head,.field {display:flex;align-items:center;gap:10px} header {min-height:60px; padding:8px 22px; background:var(--well);border-bottom:1px solid var(--line);flex:none}
.brand {display:flex;align-items:center;gap:9px} .brand svg {width:36px;height:36px;color:var(--iris)} .brand strong {display:block;font:750 20px/1.1 'Segoe UI',sans-serif;letter-spacing:.04em} .brand b {color:var(--iris)} .brand small,.eyebrow {display:block;font:650 10px/1.5 var(--mono);letter-spacing:.14em;color:var(--muted)}
.mast-title {border-left:1px solid var(--line);padding-left:16px;margin-left:6px;color:var(--muted)} .tools {margin-left:auto;flex-wrap:wrap;justify-content:flex-end} #ver {color:var(--muted);font-family:var(--mono)}
main {flex:1; min-height:0; padding:16px 22px; display:grid; grid-template-columns:clamp(275px,27vw,370px) minmax(0,1fr); gap:16px}
.panel {min-width:0; background:var(--panel); border:1px solid var(--line); border-radius:10px; overflow:hidden} .settings,.journal {display:flex;flex-direction:column;min-height:0}
.heading,.journal-head {padding:12px 17px;border-bottom:1px solid var(--line)} .journal-head {justify-content:space-between;flex-wrap:wrap}
#switches {overflow:auto;min-height:0;flex:1;padding:0 17px} .sw {display:flex;align-items:center;justify-content:space-between;gap:12px;padding:9px 0;border-bottom:1px solid var(--line);cursor:pointer} .sw:last-child {border-bottom:0}
.sw .txt {order:-1;min-width:0} .sw .lbl {display:block;font-weight:650} .sw .hint {display:block;font-size:12px;color:var(--muted);margin-top:1px} .sw input {appearance:none;flex:none;width:36px;height:21px;margin:0;padding:2px;border:1px solid var(--edge);border-radius:20px;background:#303035;cursor:pointer}
.sw input::before {content:'';display:block;width:15px;height:15px;border-radius:50%;background:var(--muted);transition:transform .16s ease,background .16s} .sw input {appearance:none;flex:none;width:36px;height:21px;margin:0;padding:2px;border:1px solid var(--edge);border-radius:20px;background:#303035;cursor:pointer;transition:background .16s,border-color .16s} .sw input:checked {background:var(--iris);border-color:var(--iris)} .sw input:checked::before {transform:translateX(15px);background:var(--deep)}
.launch {flex:none;padding:12px 17px;background:var(--subpanel);border-top:1px solid var(--line)} .field {justify-content:space-between;font-weight:600} #rounds {width:70px;padding:4px 6px;background:var(--well);border:1px solid var(--edge);border-radius:5px;color:var(--text)} .field small,.hint-text {color:var(--muted);font-size:12px;font-weight:400} #saveStatus {margin:6px 0 9px} .launch .hint-text:last-child {margin-top:5px}
#btnStart {flex:1;font-weight:650} #btnStart:not(:disabled) {background:var(--iris);color:var(--deep);border-color:var(--iris)} #btnStart:not(:disabled):hover {background:var(--light)} #btnStop:not(:disabled) {color:var(--bad);border-color:var(--bad)}
.workspace {display:grid;min-height:0;min-width:0;overflow:auto;grid-template-rows:auto minmax(170px,1fr);gap:14px} .hero {padding:13px 18px;background:linear-gradient(105deg,var(--subpanel) 40%,var(--tint))} .hero .eyebrow {color:var(--light)} .title-line {flex-wrap:wrap} #stSub {font-size:13px;color:var(--muted)}
.pill,.badge {display:inline-flex;align-items:center;gap:5px;font-size:12px;padding:2px 8px;border:1px solid var(--edge);border-radius:14px} .dot {width:7px;height:7px;border-radius:50%;background:currentColor} .pill.run,.badge.ok {color:var(--light);border-color:var(--iris);background:var(--tint)} .pill.run .dot {animation:dot-pulse 1.6s ease-in-out infinite} .badge.bad {color:var(--warn);margin-right:4px}
.metrics {display:grid;grid-template-columns:1fr 1fr 1.35fr; padding:12px 0} .metrics div {padding:0 18px;min-width:0;border-right:1px solid var(--line)} .metrics div:last-child {border:0} dt {color:var(--muted);font-size:13px} .metrics dd {font:600 16px/1.55 var(--mono),'Microsoft YaHei UI';overflow-wrap:anywhere}
.activity {margin:0 18px;padding:8px 0;border-top:1px solid var(--line);display:flex;gap:14px} .activity dt {flex:none} .activity dd {max-height:4.5em;overflow:auto;overflow-wrap:anywhere}
.details {padding:7px 18px;background:var(--subpanel);border-top:1px solid var(--line)} summary {cursor:pointer;font-size:13px;color:var(--muted)} summary:hover {color:var(--light)} .details dl {display:grid;grid-template-columns:auto minmax(0,1fr);gap:4px 12px;padding-top:7px} .details dd {overflow-wrap:anywhere} #stIssues {margin-left:8px}
#log {flex:1; min-height:0;overflow:auto;overflow-anchor:none;white-space:pre-wrap;overflow-wrap:anywhere;background:var(--well);padding:8px 15px; font:13px/1.6 var(--mono),'Microsoft YaHei UI';scrollbar-color:var(--edge) var(--well)} #log:focus-visible {outline-offset:-3px} #log:empty::before {content:'暂无符合条件的日志';display:block;padding:12px 0;color:var(--muted)} #log div {padding:3px 0;border-bottom:1px solid #ffffff0c} #log .ok {color:var(--light)} #log .warn {color:var(--warn)} #log .bad {color:var(--bad)} #log .state {color:var(--info)} #log .dim {color:var(--muted)} #log .turn {font-weight:650}
#btnKey[aria-pressed=true] {color:var(--light);background:var(--tint);border-color:var(--iris)} .journal-foot {padding:4px 15px;font:12px/1.6 var(--mono);color:var(--muted);background:var(--subpanel)}
@keyframes dot-pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.4;transform:scale(.7)}}
.toast {position:fixed;right:18px;bottom:16px;max-width:min(500px,90vw);padding:10px 15px;border:1px solid var(--edge);border-left:3px solid var(--iris);border-radius:6px;background:var(--subpanel);overflow-wrap:anywhere;box-shadow:0 4px 18px #0005;pointer-events:none;opacity:0;transform:translateY(8px);transition:opacity .18s,transform .18s} .toast.show {opacity:1;transform:none}
@media(max-width:820px),(max-height:510px){body{height:auto;min-height:100vh} main{grid-template-columns:1fr;padding:12px} .workspace{overflow:visible;grid-template-rows:auto minmax(280px,48vh)} .mast-title{display:none} #switches{max-height:45vh;flex:auto} header{flex-wrap:wrap}}

.mode-tabs {display:flex;gap:3px;padding:3px;background:var(--bg);border-radius:8px}
.mode-tabs button {border-color:transparent;white-space:nowrap}
.mode-tabs button[aria-pressed=true] {background:var(--tint);color:var(--light);border-color:var(--iris)}
.emu-fields {overflow:auto;min-height:0;flex:1;padding:8px 17px}
.emu-fields .field {margin:8px 0;flex-wrap:wrap}
.emu-fields select,.emu-fields input:not([type=checkbox]) {font:inherit;color:var(--text);background:var(--well);border:1px solid var(--edge);border-radius:5px;padding:6px;min-width:0}
.emu-fields input[type=text] {width:100%}
.emu-fields input[type=number] {width:80px}
#emuView .buttons {flex-wrap:wrap}
#btnEmuStartSel:not(:disabled) {background:var(--iris);color:var(--deep)}
#emuView .workspace {grid-template-rows:minmax(180px,1fr) minmax(180px,1fr)}
#emuInstances {overflow:auto;min-height:0;flex:1;padding:0 16px}
.emu-instance {padding:13px 0;border-bottom:1px solid var(--line);display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px 12px}
.emu-instance label {font-weight:650;display:flex;align-items:center;gap:8px;overflow-wrap:anywhere}
.emu-instance .hint-text {margin-top:5px}
.emu-instance .buttons {justify-content:flex-end;align-content:center}
#emuSaveStatus {margin-bottom:8px}
@media(max-width:1000px){.emu-instance{grid-template-columns:1fr}.emu-instance .buttons{justify-content:flex-start}}
#emuLog {flex:1; min-height:0;overflow:auto;overflow-anchor:none;white-space:pre-wrap;overflow-wrap:anywhere;background:var(--well);padding:8px 15px; font:13px/1.6 var(--mono),'Microsoft YaHei UI';scrollbar-color:var(--edge) var(--well)} #emuLog:focus-visible {outline-offset:-3px} #emuLog:empty::before {content:'暂无符合条件的日志';display:block;padding:12px 0;color:var(--muted)} #emuLog div {padding:3px 0;border-bottom:1px solid #ffffff0c} #emuLog .ok {color:var(--light)} #emuLog .warn {color:var(--warn)} #emuLog .bad {color:var(--bad)} #emuLog .state {color:var(--info)} #emuLog .dim {color:var(--muted)} #emuLog .turn {font-weight:650}
</style></head><body>
<header><div class="brand"><svg viewBox="0 0 42 42" aria-hidden="true"><rect x="5" y="11" width="20" height="25" rx="3" transform="rotate(-13 15 23)" fill="none" stroke="currentColor" stroke-width="2"/><rect x="15" y="5" width="21" height="29" rx="3" fill="currentColor"/><path d="m25 12 5 7-5 7-5-7z" fill="var(--well)"/></svg><div><strong>KARDS <b>AUTO</b></strong><small>DESKTOP CONTROL</small></div></div>
<span class="mast-title">桌面控制台</span><nav class="mode-tabs" aria-label="运行平台"><button id="tabPc" aria-pressed="true" aria-controls="pcView">PC 端游</button><button id="tabEmu" aria-pressed="false" aria-controls="emuView">模拟器多开</button></nav><div class="tools"><span id="ver">版本 —</span><button id="btnUpdate">检测更新</button><button id="btnApplyUpdate" style="display:none">应用更新</button><button id="btnRelease" style="display:none">发布页</button></div></header>
<main id="pcView">
  <section class="panel settings" aria-labelledby="settings-title"><div class="heading"><span class="eyebrow">CONFIGURATION</span><h2 id="settings-title">运行设置</h2></div><div id="switches"></div>
    <div class="launch"><div class="field"><label for="rounds">目标局数 <small>0 表示不限</small></label><input type="number" id="rounds" min="0" max="99" value="3" disabled></div>
      <p id="saveStatus" class="hint-text" role="status">选项与局数自动保存，重启后恢复。</p><div class="buttons"><button id="btnStart" disabled>开始运行</button><button id="btnStop" disabled>停止</button></div><p class="hint-text">运行时请勿遮挡 KARDS 游戏窗口。</p></div></section>
  <div class="workspace"><section class="panel" aria-labelledby="overview-title">
    <div class="hero"><span class="eyebrow">SESSION OVERVIEW</span><div class="title-line"><h1 id="overview-title">运行总览</h1><div id="pill" class="pill idle" role="status"><span class="dot"></span><span id="pilltxt">连接中</span></div></div><p id="stSub">正在读取状态…</p></div>
    <dl class="metrics"><div><dt>运行时长</dt><dd id="elapsed">—</dd></div><div><dt>费用读数</dt><dd id="stKre">—</dd></div><div><dt>我方支援 / 前线</dt><dd id="stBoard">—</dd></div></dl>
    <dl class="activity"><dt>最近动作</dt><dd id="stAct">—</dd></dl>
    <details class="details"><summary>会话详情 <span id="stIssues"></span></summary><dl><dt>对局阶段</dt><dd id="stState">—</dd><dt>最近三局</dt><dd id="stRounds">—</dd><dt>启动参数</dt><dd><code id="stArgv">—</code></dd></dl></details>
  </section><section class="panel journal" aria-labelledby="journal-title"><div class="journal-head"><div><span class="eyebrow">EVENT JOURNAL</span><h2 id="journal-title">运行日志</h2></div><div class="buttons"><button id="btnKey" aria-pressed="false">只看关键行</button><button id="btnBottom">回到底部 ↓</button></div></div><div id="log" tabindex="0" role="region" aria-label="日志内容"></div><div class="journal-foot" id="logtag">main_loop.log</div></section></div>
</main>
<main id="emuView" style="display:none">
  <section class="panel settings" aria-labelledby="emuSettingsTitle">
    <div class="heading"><span class="eyebrow">EMULATOR CONTROL</span><h2 id="emuSettingsTitle">模拟器多开设置</h2></div>
    <fieldset class="emu-fields" id="emuFields" disabled style="border:0;margin:0">
      <div class="field"><label for="emuMode">对战模式</label><select id="emuMode"><option value="training">训练模式</option><option value="casual">休闲对战</option><option value="ranked">排位模式</option></select></div>
      <div class="field"><label for="emuDeck">卡组名称</label><input type="text" id="emuDeck" placeholder="留空默认选首个卡组"></div>
      <div class="field"><label for="emuRounds">目标局数 <small>0 表示不限</small></label><input type="number" id="emuRounds" min="0" max="99" value="3"></div>
      <div class="field"><label for="emuStagger">启动间隔 <small>秒</small></label><input type="number" id="emuStagger" min="0" max="10" step="0.1" value="1.5"></div>
<label class="sw"><input type="checkbox" id="emuPreferIpc"><span class="txt"><span class="lbl">MuMu IPC 高速截图</span></span></label>
<label class="sw"><input type="checkbox" id="emuDeploy"><span class="txt"><span class="lbl">自动部署单位</span></span></label>
<label class="sw"><input type="checkbox" id="emuAttack"><span class="txt"><span class="lbl">自动进攻与上前线</span></span></label>
<label class="sw"><input type="checkbox" id="emuEndTurn"><span class="txt"><span class="lbl">自动结束回合</span></span></label>
<label class="sw"><input type="checkbox" id="emuAutoLaunch"><span class="txt"><span class="lbl">自动拉起 KARDS</span></span></label>
<label class="sw"><input type="checkbox" id="emuDryRun"><span class="txt"><span class="lbl">只看日志不点击 (Dry-Run)</span></span></label>

      <div class="field"><label for="emuExtraSerials">自定义 ADB 端点</label><input type="text" id="emuExtraSerials" placeholder="127.0.0.1:5555" aria-describedby="emuAdbHint"></div>
      <p class="hint-text" id="emuAdbHint">雷电/蓝叠等其他模拟器可填 ADB 端口，以逗号或空格分隔。</p>
    </fieldset>
    <div class="launch"><p id="emuSaveStatus" class="hint-text" role="status">正在读取模拟器配置…</p><div class="buttons"><button id="btnEmuRefresh">刷新实例</button><button id="btnEmuStartSel" disabled>启动已选</button><button id="btnEmuStopAll">全部停止</button></div></div>
  </section>
  <div class="workspace">
    <section class="panel settings" aria-labelledby="emuInstancesTitle"><div class="journal-head"><div><span class="eyebrow">INSTANCES</span><h2 id="emuInstancesTitle">模拟器实例列表</h2></div><span class="hint-text" id="emuCount">正在发现实例…</span></div><div id="emuInstances"></div></section>
    <section class="panel journal" aria-labelledby="emuJournalTitle"><div class="journal-head"><div><span class="eyebrow">INSTANCE JOURNAL</span><h2 id="emuJournalTitle">实例运行日志</h2></div><button id="btnEmuBottom">回到底部 ↓</button></div><div id="emuLog" tabindex="0" role="region" aria-label="实例日志内容"></div><div class="journal-foot" id="emuLogTag">请选择实例的「日志」</div></section>
  </div>
</main>
<div id="toast" class="toast" role="status"></div>
<script>
let onlyKey = false, autoscroll = true, lastRev = '', polling = false;
let updUrl = '', lastUpdateMessage = '', checkingUpdate=false;   // 查到新版本后存发布页地址,按钮第二次点就是打开它
const $ = s => document.querySelector(s);
function toast(msg, ms=3200){ const t=$('#toast'); t.textContent=msg; t.classList.add('show');
  clearTimeout(t._h); t._h=setTimeout(()=>t.classList.remove('show'), ms); }
function renderSwitches(list, opts){
  const box = $('#switches');
  if(box.childElementCount) return;
  $('#rounds').value = opts.max_rounds;
  $('#rounds').disabled = false;
  for(const s of list){
    const d = document.createElement('label'); d.className='sw';
    d.title = s.flag;
    d.innerHTML = `<input type="checkbox" id="sw_${s.key}" ${opts[s.key]?'checked':''}>
      <span class="txt"><span class="lbl">${s.label}</span>
      <span class="hint">${s.hint}</span></span>`;
    const input = d.querySelector('input');
    input.addEventListener('change', ()=>{
      if(s.key === 'ranked' && input.checked && !window.confirm(
        '警告：排位模式下的自动操作可能被游戏检测，存在封号风险。\n\n确认要启用排位模式吗？')){
        input.checked = false;
      }
      persistOptions();
    });
    box.appendChild(d);
  }
}
function render(s){
  const run = s.running;
  $('#pill').className = 'pill ' + (run?'run':'idle');
  $('#pilltxt').textContent = run ? `运行中 pid=${s.pid}` : (s.exit_code===null?'空闲':`已停止(退出码 ${s.exit_code})`);
  // 退出码本身说明不了什么(103 尤其),把翻译好的那句话挂成悬停提示
  $('#pill').title = (!run && s.exit_hint) ? s.exit_hint : '';
  const us = s.update_state || {}, updating = ['preparing','closing'].includes(us.phase);
  $('#btnStart').disabled = run || updating || us.phase==='recovery'; $('#btnStop').disabled = !run;
  $('#btnApplyUpdate').disabled = run || updating;
  $('#btnUpdate').disabled = updating || checkingUpdate;
  if(us.phase==='recovery'){
    $('#btnApplyUpdate').style.display=''; $('#btnApplyUpdate').textContent='恢复旧文件';
  }else if(updating){ $('#btnApplyUpdate').textContent='更新中…'; }
  else { $('#btnApplyUpdate').textContent='应用更新'; }
  if(us.msg && us.msg!==lastUpdateMessage){lastUpdateMessage=us.msg; toast(us.msg,10000);}
  $('#ver').textContent = 'v' + s.version;
  $('#elapsed').textContent = run && s.elapsed!=null ? (s.elapsed+'s') : '—';
  const st = s.status || {};
  const stMap = {in_game:'对局中', deck_select:'选牌', mulligan:'换牌', queueing:'排队',
    victory:'胜利', defeat:'失败', None:'—'};
  $('#stState').textContent = run ? (stMap[st.state] ?? (st.state||'启动中…')) : '空闲';
  const rr = (st.rounds||[]).slice(-3).map(r=>`第${r.n}局 ${r.result} ${r.min}min`).join(' · ');
  const waiting = run && st.waiting;
  $('#stSub').textContent = waiting
      ? '⚠ 引擎在等窗口 —— KARDS 没开、或被别的窗口盖住了(下面是上一局的旧状态)'
      : (run ? (stMap[st.state] || st.state || '正在等待游戏状态…') : (st.last_line ? '当前未运行，下方显示最近日志记录。' : '选择功能和目标局数后，点击「开始运行」。'));
  $('#stSub').style.color = waiting ? 'var(--warn)' : '';
  $('#stKre').textContent = st.kredits!=null ? `${st.kredits}  ${st.kredits_how?('['+st.kredits_how+']'):''}` : '—';
  $('#stBoard').textContent = st.board ? `${st.board.our} 张(单位 ${st.board.our_units}) / 前线 ${st.board.front}` : '—';
  $('#stAct').textContent = st.last_action ? `[${st.last_action.tag}] ${st.last_action.text}` : '—';
  $('#stRounds').textContent = rr || '—';
  $('#stArgv').textContent = (s.argv&&s.argv.length) ? s.argv.join(' ') : '—';
  const iss = st.issues ? `<span class="badge bad">值得看一眼 ${st.issues}</span>` : '<span class="badge ok">本段干净</span>';
  $('#stIssues').innerHTML = iss + (s.error?`<span class="badge bad">${s.error}</span>`:'');
  const log = $('#log');
  // ★★ 判据是"**日志文件**变了没有",不是"行数变了没有"。
  //   尾部只取 400 行 —— 行数会**饱和**,一旦日志超过 400 行就永远是 400,
  //   拿它当判据会让日志区永久冻结(用户 2026-09-19 报的就是这个:
  //   "滚到一定时候就不动了,向下翻也翻不下去")。
  const rev = s.log_rev || '';
  if(rev !== lastRev){
    lastRev = rev;
    log.innerHTML = s.log_lines.map(([cls,ln])=>
      `<div class="${cls}">${ln.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}</div>`).join('');
    if(autoscroll) log.scrollTop = log.scrollHeight;
  }
}
async function poll(){
  if(polling) return;
  polling = true;
  const filter = onlyKey;
  try{
    const s = await window.pywebview.api.snapshot(filter, 400, lastRev);
    if(filter !== onlyKey){ lastRev=''; return; }
    renderSwitches(s.switches, s.saved_options); render(s);
    $('#logtag').textContent = 'main_loop.log';
    $('#logtag').style.color = '';
  }catch(e){
    // ★ 以前这里是个空 catch:面板一旦读不到状态就**静静地冻住**,和"日志本来
    //   就没有新内容"长得一模一样 —— 用户看到的又是"日志不动了"。至少要让人看见。
    $('#logtag').textContent = 'main_loop.log · ⚠ 面板读不到状态';
    $('#logtag').style.color = 'var(--bad)';
  }finally{
    polling = false;
  }
}
function collectOptions(){
  const opts = {max_rounds: $('#rounds').value};
  for(const sw of document.querySelectorAll('#switches input'))
    opts[sw.id.slice(3)] = sw.checked;
  return opts;
}
// 串行写入，快速连续修改时旧配置不会晚于新配置落盘。
let saveQueue = Promise.resolve(), saveRevision = 0, starting = false;
async function flushOptionSaves(){
  // A save may enqueue another save while this await is in progress.  Keep
  // waiting until the revision observed before the await is still current.
  for(;;){
    const revision = saveRevision, queue = saveQueue;
    await queue;
    if(revision === saveRevision) return;
  }
}
function lockOptionControls(locked){
  document.querySelectorAll('#switches input, #rounds').forEach(x=>x.disabled=locked);
}
function persistOptions(){
  const revision = ++saveRevision;
  const opts = collectOptions();
  if(!/^[0-9]{1,2}$/.test(opts.max_rounds)){
    $('#saveStatus').textContent = '局数须为 0~99 的整数，尚未保存当前修改';
    return;
  }
  $('#saveStatus').textContent = '正在自动保存…';
  saveQueue = saveQueue.then(async ()=>{
    try {
      const r = await window.pywebview.api.save_settings(opts);
      if(revision === saveRevision) $('#saveStatus').textContent = r.msg;
    } catch(e) {
      if(revision === saveRevision) $('#saveStatus').textContent = '自动保存失败：' + e;
    }
  });
}
window.addEventListener('pywebviewready', async ()=>{
  poll(); setInterval(poll, 1000);
  let _rt; $('#rounds').addEventListener('input', ()=>{ clearTimeout(_rt); _rt=setTimeout(persistOptions, 350); });
  $('#btnStart').onclick = async ()=>{
    if(starting) return;
    starting = true;
    $('#btnStart').disabled = true;
    lockOptionControls(true);
    clearTimeout(_rt);
    try {
      await flushOptionSaves();
      // Controls stay locked through the Python start call, so the command
      // line and the final config file cannot diverge if startup takes 1.2s.
      const opts = collectOptions();
      const r = await window.pywebview.api.start(opts);
      // 启动失败时那条消息是要人读的(可能两三行、还带操作步骤),3.2 秒根本看不完
      toast(r.ok ? ('已启动:'+r.argv.join(' ')) : r.msg, r.ok ? 3200 : 12000); poll();
    } finally {
      lockOptionControls(false);
      starting = false;
      poll();
    }
  };
  $('#btnStop').onclick = async ()=>{ const r = await window.pywebview.api.stop(); toast(r.msg); poll(); };
  $('#btnUpdate').onclick = async ()=>{
    checkingUpdate=true; $('#btnUpdate').disabled=true; $('#btnUpdate').textContent='检测中…';
    try{
      const r = await window.pywebview.api.check_update();
      toast(r.msg, r.ok ? 10000 : 11000);
      updUrl=r.url||'';
      $('#btnRelease').style.display=updUrl?'':'none';
      $('#btnApplyUpdate').style.display=r.can_apply?'':'none';
      $('#btnApplyUpdate').textContent='应用更新';
    }catch(e){toast('检测更新失败：'+e,11000);}
    finally{checkingUpdate=false; $('#btnUpdate').disabled=false; $('#btnUpdate').textContent='检测更新';}
  };
  $('#btnRelease').onclick = async ()=>{const r=await window.pywebview.api.open_release();toast(r.msg);};
  $('#btnApplyUpdate').onclick = async ()=>{
    const r=await window.pywebview.api.install_update(); toast(r.msg,11000); poll();
  };
  $('#btnKey').onclick = ()=>{ onlyKey=!onlyKey; lastRev='';
    $('#btnKey').setAttribute('aria-pressed', String(onlyKey));
    $('#btnKey').textContent = onlyKey?'看全部':'只看关键行'; poll(); };
  $('#btnBottom').onclick = ()=>{ autoscroll=true; $('#log').scrollTop=$('#log').scrollHeight; };
  $('#log').addEventListener('scroll', ()=>{ const l=$('#log');
    autoscroll = l.scrollTop + l.clientHeight >= l.scrollHeight - 30; });
});

// Emulator requests and log revisions are independent of the PC viewer.
let emuActive=false, emuPolling=false, emuReady=false, emuBusy=false;
let emuSelected=new Set(), emuLogId='', emuLogRev='', emuAutoscroll=true;
let emuSaveQueue=Promise.resolve(), emuSaveRevision=0, emuLastPoll=0, emuListKey='';
const emuToggles={emuPreferIpc:'prefer_ipc',emuDeploy:'allow_deploy',emuAttack:'allow_attack',
  emuEndTurn:'allow_end_turn',emuAutoLaunch:'auto_launch_kards',emuDryRun:'dry_run'};
function emuCollect(){
  return {mode:$('#emuMode').value,deck_name:$('#emuDeck').value,
    max_rounds:Number($('#emuRounds').value),stagger_seconds:Number($('#emuStagger').value),
    extra_serials:$('#emuExtraSerials').value.split(/[,，\s]+/).filter(Boolean),
    selected_instances:[...emuSelected],
    ...Object.fromEntries(Object.entries(emuToggles).map(([id,key])=>[key,$('#'+id).checked]))};
}
function emuLoad(o){
  $('#emuMode').value=o.mode; $('#emuDeck').value=o.deck_name;
  $('#emuRounds').value=o.max_rounds; $('#emuStagger').value=o.stagger_seconds;
  $('#emuExtraSerials').value=o.extra_serials.join(', ');
  for(const [id,key] of Object.entries(emuToggles)) $('#'+id).checked=o[key];
  emuSelected=new Set(o.selected_instances); emuReady=true;
  $('#emuFields').disabled=emuBusy; $('#btnEmuStartSel').disabled=emuBusy;
  $('#emuSaveStatus').textContent='选项自动保存；停止后重新启动生效。';
}
function emuValid(){
  const rounds=Number($('#emuRounds').value), stagger=Number($('#emuStagger').value);
  return $('#emuRounds').value!=='' && $('#emuStagger').value!=='' &&
    Number.isInteger(rounds) && rounds>=0 && rounds<=99 &&
    Number.isFinite(stagger) && stagger>=0 && stagger<=10;
}
function emuPersist(){
  if(!emuReady) return;
  const revision=++emuSaveRevision, opts=emuCollect();
  if(!emuValid()){
    $('#emuSaveStatus').textContent='局数须为 0~99 的整数，间隔须为 0~10 秒。'; return;
  }
  $('#emuSaveStatus').textContent='正在自动保存…';
  emuSaveQueue=emuSaveQueue.then(async()=>{
    try{
      const r=await window.pywebview.api.emu_save_options(opts);
      if(revision===emuSaveRevision) $('#emuSaveStatus').textContent=r.msg;
    }catch(e){$('#emuSaveStatus').textContent='保存失败：'+e;}
  });
}
function emuChooseLog(id){
  emuLogId=id; emuLogRev=''; emuAutoscroll=true;
  $('#emuLog').replaceChildren(); $('#emuLogTag').textContent=id; emuListKey=''; emuPoll(true);
}
async function emuAction(action){
  if(emuBusy) return;
  emuBusy=true; $('#emuFields').disabled=true; $('#btnEmuStartSel').disabled=true;
  document.querySelectorAll('#emuInstances button, #emuInstances input').forEach(e=>e.disabled=true);
  try{
    await emuSaveQueue;
    const r=await action(); toast(r.msg || (r.ok?'操作已完成':'操作失败'),r.ok?3200:10000);
  }catch(e){toast('模拟器操作失败：'+e,10000);}
  finally{
    emuBusy=false; $('#emuFields').disabled=!emuReady; $('#btnEmuStartSel').disabled=!emuReady;
    emuListKey=''; emuPoll(true);
  }
}
function emuStart(ids){
  if(!ids.length) return {ok:false,msg:'请先选择模拟器实例'};
  if(!emuValid()) return {ok:false,msg:'请检查目标局数和启动间隔'};
  return window.pywebview.api.emu_start(ids,emuCollect());
}
function emuRenderInstances(instances){
  const key=JSON.stringify([instances,[...emuSelected],emuLogId,emuBusy]);
  if(key===emuListKey) return;
  emuListKey=key;
  const box=$('#emuInstances'), fragment=document.createDocumentFragment();
  for(const i of instances){
    const row=document.createElement('div'); row.className='emu-instance';
    const info=document.createElement('div'), label=document.createElement('label');
    const check=document.createElement('input'); check.type='checkbox'; check.checked=emuSelected.has(i.instance_id); check.disabled=emuBusy;
    check.onchange=()=>{if(check.checked) emuSelected.add(i.instance_id); else emuSelected.delete(i.instance_id); emuPersist();};
    label.append(check,document.createTextNode(i.name)); info.append(label);
    const badges=document.createElement('div'); badges.className='hint-text';
    const provider=i.provider==='mumu'?'MuMu'+(i.android_version?' '+i.android_version:''):'ADB';
    badges.textContent=provider+(i.ipc_available?' · IPC':'')+' · '+(i.running?'运行中':'未启动'); info.append(badges);
    const status=document.createElement('div'); status.className='hint-text';
    status.textContent=i.worker_running?('运行中 · '+i.worker_state+' · '+i.rounds_done+'局('+i.victories+'胜'+i.defeats+'负) · '+(i.avg_capture_ms==null?'—':Math.round(i.avg_capture_ms))+'ms'):'空闲';
    info.append(status);
    if(i.last_error){const err=document.createElement('div'); err.className='hint-text'; err.style.color='var(--bad)'; err.textContent=i.last_error; info.append(err);}
    const buttons=document.createElement('div'); buttons.className='buttons';
    function button(text,fn){const b=document.createElement('button'); b.textContent=text; b.disabled=emuBusy; b.onclick=fn; buttons.append(b); return b;}
    if(i.provider==='mumu' || i.extra?.controllable){
      button(i.running?'关机':'开机',()=>emuAction(async()=>{
        if(i.running && i.worker_running){const r=await window.pywebview.api.emu_stop([i.instance_id]); if(!r.ok) return r;}
        return window.pywebview.api.emu_control(i.instance_id,i.running?'shutdown':'launch');
      }));
    }
    button(i.worker_running?'停止':'启动',()=>emuAction(()=>i.worker_running?
      window.pywebview.api.emu_stop([i.instance_id]):emuStart([i.instance_id])));
    const logButton=button('日志',()=>emuChooseLog(i.instance_id)); logButton.setAttribute('aria-pressed',String(emuLogId===i.instance_id));
    row.append(info,buttons); fragment.append(row);
  }
  if(!instances.length){const empty=document.createElement('p'); empty.className='hint-text'; empty.style.padding='18px 0'; empty.textContent='未发现实例。请打开模拟器，或填写 ADB 端点后刷新。'; fragment.append(empty);}
  box.replaceChildren(fragment); $('#emuCount').textContent=instances.length+' 个实例';
}
async function emuPoll(force=false){
  if(emuPolling || (!force && !emuActive && Date.now()-emuLastPoll<3000)) return;
  emuPolling=true; emuLastPoll=Date.now();
  const id=emuActive?emuLogId:'', rev=emuActive?emuLogRev:'';
  try{
    const s=await window.pywebview.api.emu_snapshot(id,rev);
    $('#tabEmu').textContent='模拟器多开'+(s.running_count?' ('+s.running_count+')':'');
    if(!emuReady) emuLoad(s.options);
    emuRenderInstances(s.instances);
    if(emuActive && id && id===emuLogId && s.log){
      $('#emuLogTag').textContent=id;
      if(s.log.changed){
        emuLogRev=s.log.rev;
        const fragment=document.createDocumentFragment();
        for(const [cls,line] of s.log.log_lines){const div=document.createElement('div'); div.className=cls; div.textContent=line; fragment.append(div);}
        $('#emuLog').replaceChildren(fragment);
        if(emuAutoscroll) $('#emuLog').scrollTop=$('#emuLog').scrollHeight;
      }
    }
  }catch(e){$('#emuCount').textContent='读取失败，请刷新重试'; $('#emuLogTag').textContent='模拟器状态读取失败：'+e;}
  finally{emuPolling=false;}
}
window.addEventListener('pywebviewready',()=>{
  function mode(active){
    emuActive=active; $('#pcView').style.display=active?'none':''; $('#emuView').style.display=active?'':'none';
    $('#tabPc').setAttribute('aria-pressed',String(!active)); $('#tabEmu').setAttribute('aria-pressed',String(active));
    if(active) emuPoll(true);
  }
  $('#tabPc').onclick=()=>mode(false); $('#tabEmu').onclick=()=>mode(true);
  $('#emuFields').addEventListener('change',e=>{
    if(e.target.id==='emuMode' && e.target.value==='ranked' && !window.confirm(
      '警告：排位模式下的自动操作可能被游戏检测，存在封号风险。\n\n确认要启用排位模式吗？')) e.target.value='training';
    emuPersist();
  });
  $('#btnEmuRefresh').onclick=async()=>{await emuSaveQueue; emuPoll(true);};
  $('#btnEmuStartSel').onclick=()=>emuAction(()=>emuStart([...emuSelected]));
  $('#btnEmuStopAll').onclick=()=>emuAction(()=>window.pywebview.api.emu_stop());
  $('#btnEmuBottom').onclick=()=>{emuAutoscroll=true; $('#emuLog').scrollTop=$('#emuLog').scrollHeight;};
  $('#emuLog').addEventListener('scroll',()=>{const l=$('#emuLog'); emuAutoscroll=l.scrollTop+l.clientHeight>=l.scrollHeight-30;});
  setInterval(emuPoll,1000);
});
</script></body></html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="KARDS AUTO 控制面板")
    ap.add_argument("--debug", action="store_true", help="打开 WebView 开发者工具")
    ap.add_argument("--width", type=int, default=1240)
    ap.add_argument("--height", type=int, default=780)
    ap.add_argument("--root", default=None,
                    help="项目根(默认自动找;exe 放在别处时才需要)")
    ap.add_argument("--selftest", action="store_true",
                    help="**不开窗口**:把解析出来的路径/解释器写进 "
                         "logs/gui_selftest.txt 就退出(exe 打包后这样验)")
    args = ap.parse_args()

    if args.root:
        global PROJECT_ROOT, SRC, MAIN_LOOP, LOG_DIR, LOG, GUI_RUN_LOG, VERSION_FILE
        PROJECT_ROOT = os.path.abspath(args.root)
        SRC = os.path.join(PROJECT_ROOT, "src")
        MAIN_LOOP = os.path.join(SRC, "main_loop.py")
        LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
        LOG = os.path.join(LOG_DIR, "main_loop.log")
        GUI_RUN_LOG = os.path.join(LOG_DIR, "gui_run.log")
        VERSION_FILE = os.path.join(PROJECT_ROOT, "config", "app_version.json")

    if args.selftest:
        # ★ 打包成 exe 之后没有控制台,`print` 看不见 —— 所以把结论**写文件**,
        #   外面读 `logs/gui_selftest.txt` 就能验"exe 内部找的路径对不对"。
        os.makedirs(LOG_DIR, exist_ok=True)
        eng = engine_python()        # 只挑一次 —— 每次挑都要真跑探针,不便宜
        info = {
            "frozen": bool(getattr(sys, "frozen", False)),
            "exe": os.path.abspath(sys.executable),
            "project_root": PROJECT_ROOT,
            "main_loop": MAIN_LOOP,
            "main_loop_exists": os.path.exists(MAIN_LOOP),
            # ★ 这里以前是 `engine_python_exists: os.path.exists(...)`,而它正是
            #   v0.1.0 漏掉 103 的原因:文件在 ≠ 它能跑。probe 才是真结论。
            "engine_python": eng,
            "engine_python_probe": (python_probe(eng) if eng
                                    else (False, "一个能用的都没有")),
            "engine_python_diag": [list(d) for d in _PYTHON_DIAG],
            "portable_python": os.path.join(PROJECT_ROOT, PORTABLE_PYTHON),
            "portable_python_exists": os.path.exists(
                os.path.join(PROJECT_ROOT, PORTABLE_PYTHON)),
            "log": LOG,
            "log_exists": os.path.exists(LOG),
            # ★★ 2026-09-19:日志区"滚到一定时候就不动了"那个 bug 的判据。
            #   面板是 onefile exe、`gui.py` 是编进去的 —— 不重打包就等于没修。
            #   `log_rev` 只有新代码才有,所以自检里出现这个字段 = 新面板真的在 exe 里。
            "log_rev": log_rev(LOG),
            "log_reader": {"max_tail_bytes": log_io.MAX_TAIL_BYTES,
                           "max_line_chars": log_io.MAX_LINE_CHARS,
                           "cached": True, "serial_poll": True},
            "version": read_version(),
            "options_file": options_path(),
            "saved_options": load_options(),
            "emulator_multi_instance": {"available": True, "providers": ["mumu", "adb"], "ipc_supported": True},
            "classic_strategy": True,
            "message_input": {"available": True, "default": False,
                              "flag": "--message-input", "physical_fallback": False,
                              "cooperative_stop": True, "force_kill_on_stop": False},
            "beta_updates": {
                "stable_after_beta": update_check.is_newer('0.2.2', '0.2.2_beta'),
                "package_suffix": bool(update_check.parse_release_assets(
                    b'<a href="/yumehanab1/OCR-Kards-Auto/releases/download/v0.2.2_beta/kards-auto_v0.2.2_beta_x86_64.manifest.json">manifest</a>',
                    'v0.2.2_beta').get('manifest_asset'))},
            # ★★ 2026-09-19(v0.1.3):把"更新检测这次真的打进 exe 了"写进自检里。
            #   为什么非要这一条:面板是 **onefile exe**,`gui.py` 是**编进去**的 ——
            #   改了 gui.py 不重打包,用户那边看到的还是旧面板(新功能等于没发)。
            #   而"没生效"和"生效了但网络不通"在界面上长得一样。
            #   ⇒ 自检里写死一个只有新代码才有的字段,`--selftest` 一跑就知道。
            "update_check": {"api": update_check.DEFAULT_API,
                             "feed": update_check.DEFAULT_FEED,
                             "feed_assets": callable(update_check.parse_release_assets),
                             "timeout": update_check.TIMEOUT},
            "incremental_update": {"available": callable(update_install.stage_update),
                                   "helper_exists": os.path.isfile(os.path.join(SRC, 'update_install.py')),
                                   "wait_pid": update_install.panel_exit_pid(),
                                   "recovery": callable(update_install.recover_job)},
            "argv": build_argv({"play": True, "attack": True, "max_rounds": "3"}),
        }
        with open(os.path.join(LOG_DIR, "gui_selftest.txt"), "w",
                  encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False, indent=2)
        return 0

    import webview  # 只在真要开窗口时才 import(用例 import 本模块时不需要它)

    api = Api()
    st = load_win_state()
    w = max(WIN_MIN[0], int(st.get("w", args.width)))
    h = max(WIN_MIN[1], int(st.get("h", args.height)))
    x = st.get("x")
    y = st.get("y")
    if x is not None and y is not None:
        x, y = clamp_to_screen(x, y, w, h)
    window = webview.create_window(
        APP_NAME, html=HTML, js_api=make_js_api(api), width=w, height=h, x=x, y=y,
        min_size=WIN_MIN, background_color="#141416", text_select=True)
    api.window = window

    def _remember(*_a, **_k):
        try:
            save_win_state(window.width, window.height, window.x, window.y)
        except Exception:
            pass

    def _shutdown(*_a, **_k):
        """
        关面板 = **把引擎一起带走**。

        ★★★ 2026-09-19(v0.1.6):**这一步以前没有,于是留下孤儿进程占着单实例锁。**
          实机证据(用户的日志,`拒绝启动第二个实例` 出现 **48 次**):
            关掉面板 -> 引擎那个 python 进程**还活着**(它只是个 subprocess,
            面板退了它不会自己退)-> 它持有 `kards_auto_main_loop` 那把锁 ->
            下次点「开始」直接被拒:`❌ 已经有一个 main_loop 在跑了`。
          用户的原话就是:**"异常退出后,要去任务管理器把 Python 进程先关了,
          不然会判定有两个实例报错"** —— 手动去任务管理器,本来该由这里做掉。
          ★ 只有"面板自己起的那个子进程"会被停掉(`api.proc`),
            不会去动用户自己开的别的东西。
          ★ 失败也不许挡住关窗口(`try/except` + 超时),大不了回到老行为。
        """
        try:
            r = api.stop()
            if r.get("ok"):
                log_update(f"[面板] 关窗口停止请求:{r.get('msg')}")
        except Exception:
            pass

        try:
            api.emu_stop()
        except Exception:
            pass

    try:
        window.events.closing += _remember
        window.events.closing += _shutdown
    except Exception:
        pass          # 记不住尺寸/停不掉引擎,都不该挡住"能开面板"这件事

    print(f"{APP_NAME} 面板已启动(窗口标题 {APP_NAME!r});关闭窗口即退出。")
    # ★★ 2026-09-19(v0.1.3):开面板之后**后台静默查一次**更新。
    #   静默的含义:查到新版本才把按钮改成「有新版本 vX」,其余情况一句话不说 ——
    #   手动点按钮那条路才是"必须如实回答"的那条(它会逐条说清为什么查不到)。
    #   ★ 两条防身:① 起不来就退回"不自动查"(手动照旧能用);
    #     ② 那次查询自己**一定留痕**(logs/update_check.log),否则"没有新版本"
    #        和"线程根本没跑"分不出来。
    try:
        webview.start(_auto_update_thread, (window,), debug=args.debug,
                      gui="edgechromium")
    except TypeError:
        # 老版本 pywebview 的 start() 不收位置参数 -> 别为了"自动查"把面板搞开不了
        log_update("[自动] 这个 pywebview 不支持 start(func),已退回不自动查")
        webview.start(debug=args.debug, gui="edgechromium")
    _remember()       # 有的后端 closing 事件不触发,退出前再记一次
    _shutdown()       # ★ 同上:关面板必须把引擎一起带走(v0.1.6),别留孤儿占着锁
    return 0


if __name__ == "__main__":
    sys.exit(main())
