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
  · **检测更新** = 版本号 + 远端清单(清单地址还没定,所以现在只报"未配置")。

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
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
# ★ stderr 也要:它在 Windows 上默认跟控制台代码页走,引擎的报错里有中文路径时
#   会变成一串 \ufffd —— 那正好是最需要看清的部分。
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from watch_log import KEY_WORDS  # noqa: E402  (关键行只有一份,别抄第二遍)
import update_check  # noqa: E402  (只依赖标准库,用例 import 本模块时不需要联网)


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
    {"key": "fast_scan", "flag": "--fast-scan", "label": "惰性扫描",
     "hint": "找到第一张可出的牌就停(省时间)"},
    {"key": "end_turn", "flag": "--end-turn", "label": "结束回合",
     "hint": "出完牌点『结束回合』"},
    {"key": "dry_run", "flag": "--dry-run", "label": "只看不动(dry-run)",
     "hint": "只记决策、不点鼠标 —— 第一次开面板建议先开它"},
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
    if not os.path.exists(path):
        return []
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        back = min(size, max(4096, n * 240))
        f.seek(size - back)
        data = f.read()
    lines = data.decode("utf-8", "replace").splitlines()
    if back < size and lines:
        lines = lines[1:]          # 第一行多半是半截的
    return lines[-n:]


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
class Api:
    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.started_at: float | None = None
        self.last_opts: dict = {}
        self.error: str | None = None
        self._fh = None

    # ---- 状态 ----
    def snapshot(self, only_key: bool = False, tail: int = 400) -> dict:
        running = self.proc is not None and self.proc.poll() is None
        lines = tail_lines(LOG, tail)
        if only_key:
            lines = [ln for ln in lines if any(w in ln for w in KEY_WORDS)]
        st = parse_status(tail_lines(LOG, tail))
        ver = read_version()
        return {
            "running": running,
            "pid": self.proc.pid if running else None,
            "elapsed": (round(time.time() - self.started_at)
                        if (running and self.started_at) else None),
            "argv": self.last_opts.get("argv") or [],
            "log_lines": [[mark_line(ln), ln] for ln in lines[-400:]],
            "status": st,
            "version": ver.get("version", "?"),
            "switches": SWITCHES,
            "default_on": sorted(DEFAULT_ON),
            "error": self.error,
            "exit_code": (None if running or self.proc is None
                          else self.proc.returncode),
            # 鼠标停在小圆点上时把退出码翻译成人话(v0.1.0 只显示一个裸数字)
            "exit_hint": ("" if running or self.proc is None
                          else explain_exit_code(self.proc.returncode)),
        }

    # ---- 开关控制 ----
    def start(self, opts: dict) -> dict:
        if self.proc is not None and self.proc.poll() is None:
            return {"ok": False, "msg": "已经在跑了"}
        argv = build_argv(opts or {})
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
            self._fh = open(GUI_RUN_LOG, "ab", buffering=0)
            self._fh.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} "
                           f"{' '.join(cmd)} ===\n".encode("utf-8"))
            self.proc = subprocess.Popen(
                cmd, cwd=PROJECT_ROOT, stdout=self._fh,
                stderr=subprocess.STDOUT, creationflags=flags)
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
                self.error = (f"启动失败(退出码 {rc})。"
                              + explain_exit_code(rc, "\n".join(tail)))
                return {"ok": False, "msg": self.error, "exit_code": rc,
                        "argv": argv, "log_tail": tail[-12:]}

            return {"ok": True, "msg": f"已启动 pid={self.proc.pid}",
                    "argv": argv}
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            return {"ok": False, "msg": self.error}

    def stop(self) -> dict:
        if self.proc is None or self.proc.poll() is not None:
            return {"ok": False, "msg": "没在跑"}
        try:
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

    # ---- 检测更新 ----
    def check_update(self) -> dict:
        """
        ★★ 2026-09-19(v0.1.2):**真去查了**。

        v0.1.0~v0.1.1 这里写的是"项目不是 git 仓库,更新源没定,所以不假装能更新" ——
        那是诚实,但等于没这功能。现在项目在 GitHub 上有 Release 了,机制定了:
        查 `releases/latest`,和 `config/app_version.json` 里的版本号比。

        ★ 三条纪律照抄 `update_check` 里的:查不到就说查不到(不许说成"已是最新")、
        **不自动装**(130 MB 的便携目录,替换正在运行的自己会换个坏包出来)、
        纯逻辑离线可测。
        ★ `update_url` 仍然有用:填了就用填的那个地址(别的地方发的包也能查)。
        """
        ver = read_version()
        local = str(ver.get("version") or "0.0.0")
        r = update_check.check(local, ver.get("update_url"))
        # 记住发布页地址:第二次点按钮就是"打开发布页"(用系统默认浏览器)
        self._release_url = r.get("url") or update_check.RELEASES_PAGE
        self._has_update = bool(r.get("has_update"))
        log_update(f"[手动] 本地 v{local} ok={r.get('ok')} "
                   f"has_update={r.get('has_update')} remote={r.get('remote')} "
                   f"via={r.get('via')} | {r.get('msg')}")
        return dict(r, version=local)

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
<html lang="zh"><head><meta charset="utf-8">
<title>KARDS AUTO</title>
<style>
 :root{
   --bg:#0a0e13; --panel:#111823; --panel2:#0d141c; --line:#1d2836;
   --fg:#dbe4ee; --dim:#7b8899; --orange:#ff8a1f; --grey:#67727f;
   --ok:#39d98a; --warn:#ffc24b; --bad:#ff5c78; --accent:#38bdf8;
 }
 *{box-sizing:border-box}
 html,body{height:100%}
 body{margin:0;background:
     radial-gradient(1100px 520px at 12% -12%, #16222f 0%, transparent 60%),
     radial-gradient(900px 500px at 100% 0%, #1a1622 0%, transparent 55%),
     var(--bg);
   color:var(--fg);font:13px/1.55 "Microsoft YaHei UI","Microsoft YaHei",system-ui,sans-serif;
   display:flex;flex-direction:column;overflow:hidden;user-select:none}
 header{display:flex;align-items:center;gap:14px;padding:11px 16px;
   border-bottom:1px solid var(--line);background:linear-gradient(180deg,rgba(255,138,31,.05),transparent)}
 .logo{font:700 15px/1 Consolas,"Cascadia Mono",monospace;letter-spacing:.2em;color:#fff}
 .logo b{color:var(--orange);text-shadow:0 0 14px rgba(255,138,31,.5)}
 .ver{font:11px/1 Consolas,monospace;color:var(--dim)}
 .spacer{flex:1}
 .pill{display:inline-flex;align-items:center;gap:7px;padding:5px 11px;border-radius:999px;
   border:1px solid var(--line);background:var(--panel2);font-size:12px}
 .dot{width:8px;height:8px;border-radius:50%;background:var(--grey);box-shadow:0 0 8px currentColor}
 .pill.run{border-color:rgba(57,217,138,.45);color:var(--ok)}
 .pill.run .dot{background:var(--ok);color:var(--ok);animation:pulse 1.4s infinite}
 .pill.idle .dot{background:var(--grey);color:var(--grey)}
 @keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
 button{font:600 13px/1 "Microsoft YaHei UI","Microsoft YaHei",sans-serif;color:#0a0e13;
   background:linear-gradient(180deg,#ffa03d,#f07d10);border:0;border-radius:8px;
   padding:10px 18px;cursor:pointer;letter-spacing:.05em;
   box-shadow:0 4px 14px rgba(255,138,31,.25)}
 button:hover{filter:brightness(1.08)}
 button:disabled{opacity:.35;cursor:not-allowed;filter:none;box-shadow:none}
 button.ghost{background:transparent;color:var(--fg);border:1px solid var(--line);
   box-shadow:none;font-weight:500}
 button.ghost:hover{border-color:var(--accent);color:#fff}
 button.danger{background:linear-gradient(180deg,#ff6b85,#e03050);color:#fff;
   box-shadow:0 4px 14px rgba(224,48,80,.25)}
 main{flex:1;display:grid;grid-template-columns:330px minmax(280px,1fr) 1.35fr;
   gap:12px;padding:12px;min-height:0}
 .card{background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--line);
   border-radius:11px;display:flex;flex-direction:column;min-height:0;overflow:hidden}
 .card>h2{margin:0;padding:9px 13px;font-size:11px;font-weight:600;letter-spacing:.18em;
   color:var(--dim);border-bottom:1px solid var(--line);background:rgba(255,255,255,.015);
   display:flex;align-items:center;gap:8px}
 .card>h2 .tag{margin-left:auto;font:10px/1 Consolas,monospace;color:var(--dim);
   border:1px solid var(--line);border-radius:5px;padding:2px 6px}
 .body{padding:11px 13px;overflow:auto;min-height:0;flex:1}
 .sw{display:flex;gap:10px;align-items:flex-start;padding:7px 0;border-bottom:1px dashed rgba(255,255,255,.045)}
 .sw:last-child{border-bottom:0}
 .sw input{appearance:none;width:36px;height:19px;border-radius:999px;background:#20293a;
   border:1px solid var(--line);position:relative;cursor:pointer;flex:0 0 auto;margin-top:2px;
   transition:background .18s}
 .sw input:checked{background:linear-gradient(90deg,#f07d10,#ffa03d);border-color:#ffa03d}
 .sw input::after{content:"";position:absolute;top:2px;left:2px;width:13px;height:13px;
   border-radius:50%;background:#8b96a6;transition:left .18s,background .18s}
 .sw input:checked::after{left:19px;background:#0a0e13}
 .sw .txt{min-width:0}
 .sw .lbl{font-weight:600}
 .sw .hint{color:var(--dim);font-size:11.5px;line-height:1.4}
 .row{display:flex;align-items:center;gap:9px;margin:10px 0}
 .row label{color:var(--dim);font-size:12px}
 input[type=number]{width:70px;background:#0b1219;color:var(--fg);border:1px solid var(--line);
   border-radius:7px;padding:7px 9px;font:13px/1 Consolas,monospace}
 input[type=number]:focus{outline:0;border-color:var(--orange)}
 .kv{display:grid;grid-template-columns:88px 1fr;gap:4px 10px;font-size:12.5px}
 .kv .k{color:var(--dim)}
 .kv .v{font-family:Consolas,monospace;word-break:break-all}
 .big{font:700 22px/1.15 Consolas,monospace;letter-spacing:.04em}
 .sub{color:var(--dim);font-size:11.5px}
 .badge{display:inline-block;padding:2px 7px;border-radius:5px;font:11px/1.5 Consolas,monospace;
   border:1px solid var(--line);color:var(--dim);margin-right:5px}
 .badge.ok{color:var(--ok);border-color:rgba(57,217,138,.4)}
 .badge.bad{color:var(--bad);border-color:rgba(255,92,120,.4)}
 #log{font:12px/1.5 Consolas,"Cascadia Mono",monospace;white-space:pre-wrap;
   word-break:break-all;padding:9px 12px}
 #log div{padding:1px 0;border-left:2px solid transparent;padding-left:8px}
 #log .ok{color:var(--ok)}
 #log .warn{color:var(--warn)}
 #log .bad{color:var(--bad)}
 #log .turn{color:var(--orange);font-weight:600}
 #log .state{color:var(--accent)}
 #log .act{color:#cfe0f0}
 #log .dim{color:#5d6a7a}
 .toast{position:fixed;right:16px;bottom:16px;background:var(--panel);border:1px solid var(--line);
   border-left:3px solid var(--orange);border-radius:9px;padding:10px 14px;font-size:12.5px;
   box-shadow:0 10px 30px rgba(0,0,0,.45);opacity:0;transform:translateY(8px);
   transition:opacity .2s,transform .2s;pointer-events:none;max-width:380px}
 .toast.show{opacity:1;transform:none}
 .note{color:var(--dim);font-size:11.5px;line-height:1.5;margin-top:10px;
   border-top:1px dashed rgba(255,255,255,.06);padding-top:9px}
</style></head><body>
<header>
  <div class="logo">KARDS<b>·</b>AUTO</div>
  <div class="ver" id="ver">v?</div>
  <div class="pill idle" id="pill"><span class="dot"></span><span id="pilltxt">空闲</span></div>
  <div class="spacer"></div>
  <button class="ghost" id="btnUpdate">检测更新</button>
  <button id="btnStart">开始</button>
  <button class="danger" id="btnStop" disabled>停止</button>
</header>
<main>
  <section class="card">
    <h2>功能选择<span class="tag">命令行开关</span></h2>
    <div class="body" id="switches"></div>
    <div class="body" style="flex:0 0 auto;border-top:1px solid var(--line)">
      <div class="row"><label>跑几局</label>
        <input type="number" id="rounds" min="0" max="99" value="3">
        <span class="sub">0 = 一直跑</span></div>
      <div class="note">跑的时候别让面板盖住 KARDS —— 窗口被盖住时引擎会
        fail-closed 不动作(它本来就这么设计)。</div>
    </div>
  </section>
  <section class="card">
    <h2>实时状态<span class="tag" id="elapsed">—</span></h2>
    <div class="body">
      <div class="big" id="stState">—</div>
      <div class="sub" id="stSub">等待日志…</div>
      <div style="height:12px"></div>
      <div class="kv">
        <div class="k">费用读数</div><div class="v" id="stKre">—</div>
        <div class="k">我方支援</div><div class="v" id="stBoard">—</div>
        <div class="k">最近动作</div><div class="v" id="stAct">—</div>
        <div class="k">本段局数</div><div class="v" id="stRounds">—</div>
        <div class="k">启动参数</div><div class="v" id="stArgv">—</div>
      </div>
      <div id="stIssues" style="margin-top:10px"></div>
    </div>
  </section>
  <section class="card">
    <h2>日志<span class="tag" id="logtag">main_loop.log</span>
      <button class="ghost" style="margin-left:8px;padding:4px 9px;font-size:11px"
        id="btnKey">只看关键行</button>
      <button class="ghost" style="padding:4px 9px;font-size:11px" id="btnBottom">到底部</button>
    </h2>
    <div class="body" id="log" style="padding:0"></div>
  </section>
</main>
<div class="toast" id="toast"></div>
<script>
let onlyKey = false, autoscroll = true, lastLen = -1;
let updUrl = '';   // 查到新版本后存发布页地址,按钮第二次点就是打开它
const $ = s => document.querySelector(s);
function toast(msg, ms=3200){ const t=$('#toast'); t.textContent=msg; t.classList.add('show');
  clearTimeout(t._h); t._h=setTimeout(()=>t.classList.remove('show'), ms); }
function renderSwitches(list, on){
  const box = $('#switches');
  if(box.childElementCount) return;
  for(const s of list){
    const d = document.createElement('label'); d.className='sw';
    d.innerHTML = `<input type="checkbox" id="sw_${s.key}" ${on.includes(s.key)?'checked':''}>
      <span class="txt"><span class="lbl">${s.label}</span>
      <span class="hint">${s.hint}<br>${s.flag}</span></span>`;
    box.appendChild(d);
  }
}
function render(s){
  const run = s.running;
  $('#pill').className = 'pill ' + (run?'run':'idle');
  $('#pilltxt').textContent = run ? `运行中 pid=${s.pid}` : (s.exit_code===null?'空闲':`已停止(退出码 ${s.exit_code})`);
  // 退出码本身说明不了什么(103 尤其),把翻译好的那句话挂成悬停提示
  $('#pill').title = (!run && s.exit_hint) ? s.exit_hint : '';
  $('#btnStart').disabled = run; $('#btnStop').disabled = !run;
  $('#ver').textContent = 'v' + s.version;
  $('#elapsed').textContent = run && s.elapsed!=null ? (s.elapsed+'s') : '—';
  const st = s.status || {};
  const stMap = {in_game:'对局中', deck_select:'选牌', mulligan:'换牌', queueing:'排队',
    victory:'胜利', defeat:'失败', None:'—'};
  $('#stState').textContent = run ? (stMap[st.state] ?? (st.state||'启动中…')) : '空闲';
  const rr = (st.rounds||[]).slice(-3).map(r=>`第${r.n}局 ${r.result} ${r.min}min`).join(' · ');
  $('#stSub').textContent = st.waiting
      ? '⚠ 引擎在等窗口 —— KARDS 没开、或被别的窗口盖住了(下面是上一局的旧状态)'
      : (rr || (run ? '等第一局结束…' : '点右上角「开始」'));
  $('#stSub').style.color = st.waiting ? 'var(--warn)' : '';
  $('#stKre').textContent = st.kredits!=null ? `${st.kredits}  ${st.kredits_how?('['+st.kredits_how+']'):''}` : '—';
  $('#stBoard').textContent = st.board ? `${st.board.our} 张(单位 ${st.board.our_units}) / 前线 ${st.board.front}` : '—';
  $('#stAct').textContent = st.last_action ? `[${st.last_action.tag}] ${st.last_action.text}` : '—';
  $('#stRounds').textContent = rr || '—';
  $('#stArgv').textContent = (s.argv&&s.argv.length) ? s.argv.join(' ') : '—';
  const iss = st.issues ? `<span class="badge bad">值得看一眼 ${st.issues}</span>` : '<span class="badge ok">本段干净</span>';
  $('#stIssues').innerHTML = iss + (s.error?`<span class="badge bad">${s.error}</span>`:'');
  const log = $('#log');
  if(s.log_lines.length !== lastLen){
    lastLen = s.log_lines.length;
    log.innerHTML = s.log_lines.map(([cls,ln])=>
      `<div class="${cls}">${ln.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}</div>`).join('');
    if(autoscroll) log.scrollTop = log.scrollHeight;
  }
}
async function poll(){
  try{
    const s = await window.pywebview.api.snapshot(onlyKey, 400);
    renderSwitches(s.switches, s.default_on); render(s);
  }catch(e){}
}
window.addEventListener('pywebviewready', async ()=>{
  poll(); setInterval(poll, 1000);
  $('#btnStart').onclick = async ()=>{
    const opts = {max_rounds: $('#rounds').value};
    for(const sw of document.querySelectorAll('#switches input'))
      opts[sw.id.slice(3)] = sw.checked;
    const r = await window.pywebview.api.start(opts);
    // 启动失败时那条消息是要人读的(可能两三行、还带操作步骤),3.2 秒根本看不完
    toast(r.ok ? ('已启动:'+r.argv.join(' ')) : r.msg, r.ok ? 3200 : 12000); poll();
  };
  $('#btnStop').onclick = async ()=>{ const r = await window.pywebview.api.stop(); toast(r.msg); poll(); };
  $('#btnUpdate').onclick = async ()=>{
    // 第二次点 = 打开发布页(第一次查完之后 JS 把按钮文字改掉了)
    if (updUrl) { const r = await window.pywebview.api.open_release(); toast(r.msg, 7000); return; }
    const r = await window.pywebview.api.check_update();
    toast(r.msg, r.ok ? 7000 : 11000);       // 查不到/要人照做的消息留久一点
    if (r.has_update && r.url) { updUrl = r.url; $('#btnUpdate').textContent = '打开发布页'; }
  };
  $('#btnKey').onclick = ()=>{ onlyKey=!onlyKey; lastLen=-1;
    $('#btnKey').textContent = onlyKey?'看全部':'只看关键行'; poll(); };
  $('#btnBottom').onclick = ()=>{ autoscroll=true; $('#log').scrollTop=$('#log').scrollHeight; };
  $('#log').addEventListener('scroll', ()=>{ const l=$('#log');
    autoscroll = l.scrollTop + l.clientHeight >= l.scrollHeight - 30; });
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
            "version": read_version(),
            # ★★ 2026-09-19(v0.1.3):把"更新检测这次真的打进 exe 了"写进自检里。
            #   为什么非要这一条:面板是 **onefile exe**,`gui.py` 是**编进去**的 ——
            #   改了 gui.py 不重打包,用户那边看到的还是旧面板(新功能等于没发)。
            #   而"没生效"和"生效了但网络不通"在界面上长得一样。
            #   ⇒ 自检里写死一个只有新代码才有的字段,`--selftest` 一跑就知道。
            "update_check": {"api": update_check.DEFAULT_API,
                             "feed": update_check.DEFAULT_FEED,
                             "timeout": update_check.TIMEOUT},
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
        APP_NAME, html=HTML, js_api=api, width=w, height=h, x=x, y=y,
        min_size=WIN_MIN, background_color="#0a0e13", text_select=False)

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
                log_update(f"[面板] 关窗口时把引擎一起停了:{r.get('msg')}")
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
