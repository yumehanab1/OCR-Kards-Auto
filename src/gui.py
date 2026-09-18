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

用法:
    .venv\\Scripts\\python.exe src\\gui.py
    .venv\\Scripts\\python.exe src\\gui.py --debug      # 打开 WebView 的开发者工具
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

from watch_log import KEY_WORDS  # noqa: E402  (关键行只有一份,别抄第二遍)


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


def engine_python() -> str:
    """
    起引擎(`main_loop.py`)该用哪个解释器。

    ★ 冻结成 exe 之后 `sys.executable` 是**那个 exe 自己**,不是 python ——
      直接拿它去跑 main_loop 会变成"用面板 exe 去执行一个 .py",必然失败。
      所以冻结形态下要找**项目自带的解释器**(`.venv\\Scripts\\python.exe`);
      开发形态下就是当前解释器(原行为不变)。
    """
    if not getattr(sys, "frozen", False):
        return sys.executable
    for rel in (os.path.join(".venv", "Scripts", "python.exe"),
                os.path.join(".venv", "Scripts", "pythonw.exe"),
                os.path.join("venv", "Scripts", "python.exe")):
        p = os.path.join(PROJECT_ROOT, rel)
        if os.path.exists(p):
            return p
    from shutil import which
    return which("python") or which("pythonw") or sys.executable


PROJECT_ROOT = project_root()
SRC = os.path.join(PROJECT_ROOT, "src")
MAIN_LOOP = os.path.join(SRC, "main_loop.py")
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
LOG = os.path.join(LOG_DIR, "main_loop.log")
GUI_RUN_LOG = os.path.join(LOG_DIR, "gui_run.log")
VERSION_FILE = os.path.join(PROJECT_ROOT, "config", "app_version.json")

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
    try:
        with open(VERSION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"version": "0.0.0", "update_url": ""}


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
        }

    # ---- 开关控制 ----
    def start(self, opts: dict) -> dict:
        if self.proc is not None and self.proc.poll() is None:
            return {"ok": False, "msg": "已经在跑了"}
        argv = build_argv(opts or {})
        if not argv:
            return {"ok": False, "msg": "一个功能都没勾 —— 至少勾一个再开始"}
        os.makedirs(LOG_DIR, exist_ok=True)
        py = engine_python()
        if not os.path.exists(MAIN_LOOP):
            return {"ok": False, "msg": f"找不到引擎脚本:{MAIN_LOOP}"}
        if not os.path.exists(py):
            return {"ok": False, "msg": f"找不到解释器:{py}"
                                        f"(面板 exe 需要项目里的 .venv)"}
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
        ★ 现在**只报本地版本**:本项目还不是 git 仓库,"更新源"没定
          (2026-09-15 记进 PROJECT_STATE 的那个待定问题),所以这里**不假装**能更新。
        """
        ver = read_version()
        url = (ver.get("update_url") or "").strip()
        if not url:
            return {"ok": False, "version": ver.get("version", "?"),
                    "msg": "本地版本 " + str(ver.get("version", "?"))
                           + " —— 更新源还没配置(项目不是 git 仓库,机制待定)"}
        return {"ok": False, "version": ver.get("version", "?"),
                "msg": f"更新源已配 {url},但检查逻辑还没实现(下一步)"}


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
    toast(r.ok ? ('已启动:'+r.argv.join(' ')) : r.msg); poll();
  };
  $('#btnStop').onclick = async ()=>{ const r = await window.pywebview.api.stop(); toast(r.msg); poll(); };
  $('#btnUpdate').onclick = async ()=>{ const r = await window.pywebview.api.check_update();
    toast(`v${r.version} · ${r.msg}`, 5200); };
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
        info = {
            "frozen": bool(getattr(sys, "frozen", False)),
            "exe": os.path.abspath(sys.executable),
            "project_root": PROJECT_ROOT,
            "main_loop": MAIN_LOOP,
            "main_loop_exists": os.path.exists(MAIN_LOOP),
            "engine_python": engine_python(),
            "engine_python_exists": os.path.exists(engine_python()),
            "log": LOG,
            "log_exists": os.path.exists(LOG),
            "version": read_version(),
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

    try:
        window.events.closing += _remember
    except Exception:
        pass          # 记不住尺寸不该挡住"能开面板"这件事

    print(f"{APP_NAME} 面板已启动(窗口标题 {APP_NAME!r});关闭窗口即退出。")
    webview.start(debug=args.debug, gui="edgechromium")
    _remember()       # 有的后端 closing 事件不触发,退出前再记一次
    return 0


if __name__ == "__main__":
    sys.exit(main())
