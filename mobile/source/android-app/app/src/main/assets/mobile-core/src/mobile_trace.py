# -*- coding: utf-8 -*-
"""
mobile_trace.py —— **引擎每一步的录像**(手机端)。

起因是用户那句话:*"能不能也像电脑端一样每一步操作前后截一张图,那样省得我一直盯着"*。

★ 为什么需要它(先量过现状,不是凭感觉加的):
  手机上原来**只有"真拖出去了"才存证据** ——
    · `mobile_hand.dump_deploy`  —— 每次出牌尝试:before/after/overlay/decision;
    · `mobile_attack._dump`      —— 上前线/打单位/打总部:before/after/decision。
  而**下面这些一步都没存**,偏偏是"盯着屏幕才看得见"的那一类:
    · **拒拖**("橙色可下 N 张,其中单位 0 张 -> 不拖");
    · **出不动了** / **点结束回合**;
    · **被门控挡下**("等它稳一稳"/"不是我们的回合")。
  ⇒ 这一层补的就是**证据最少的那一段**,而且是**每一步都存**。

★★ `look.png` 是这里最关键的一样(和 `dump_deploy` 里 `overlay.png` 同一个道理):
  只留原图,下一次还得重新推一遍判据;**把当时看到的框/颜色/分数画上去**,
  才可能一眼看出"它为什么这么判"。这个项目已经四次栽在"检测看起来合理、其实是错的"上。

★ 两条硬规矩(都是这个项目踩出来的):
  ① **存帧绝不许弄崩引擎** —— 全程 try/except,失败只打一行,动作照做
     (`dump_deploy` 当年就是为了这个才把整段包起来);
  ② **磁盘不许无限涨** —— 只留最近 `MAX_STEPS` 步(用户选的方案),
     而且是**按整个会话为单位**删旧的:当前这一局的上下文永远完整,
     删掉的是"更早的那几局"。另有每会话上限兜底(一局太长的极端情况)。

用法(引擎自己会调,也可以单独看):
    python src\\mobile_trace.py --status    看看现在占了多少、有多少步
    python src\\mobile_trace.py --prune     手动清到上限
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import mobile_hand as mh                      # noqa: E402

#: 默认根目录(和 `mobile_hand.dump_root()` 一个地方:`~/Desktop/手机版截图/`)。
DEFAULT_ROOT = os.path.join(os.path.dirname(mh.DUMP_ROOT_DEFAULT), "trace")

#: 一共留多少步(跨会话)。用户选的"只留最近 N 步"。
#: ★★ 这个数**实测改过**(2026-09-20 真机):原来按 1.1MB/张估的是 600 步,
#:   实测一步里三张 1280x720 PNG 加起来约 **2.4MB**(before/look/after),
#:   600 步就是 **1.4GB** —— 太大。现在给 250 步 ≈ 600MB。
#:   要留更多就设 `KARDS_TRACE_MAX_STEPS`(设之前先按 2.4MB/步 算一下)。
MAX_STEPS = 250

#: 单个会话最多留多少步(一局打太久时的第二道闸)。
MAX_STEPS_PER_SESSION = 150

#: 名字:`20260919_181530`(会话)/ `step_0007_出牌成功`(步)
_SESSION_RE = re.compile(r"^\d{8}_\d{6}$")
_STEP_RE = re.compile(r"^step_(\d+)_(.*)$")


def trace_root() -> str:
    """录像根目录。`KARDS_TRACE_DIR` 能覆盖(设备上跑的时候用得上)。"""
    return os.environ.get("KARDS_TRACE_DIR") or DEFAULT_ROOT


def enabled() -> bool:
    """
    总开关。★ 用户要的是"做 GUI 的时候保留一个开关"——
      现在先用命令行 `--no-trace` 和这个环境变量顶上:
        `KARDS_TRACE=0` / `off` / `no` / `false` 都关。
    """
    v = (os.environ.get("KARDS_TRACE") or "").strip().lower()
    return v not in ("0", "off", "no", "false")


def _max_steps() -> int:
    try:
        return max(1, int(os.environ.get("KARDS_TRACE_MAX_STEPS", MAX_STEPS)))
    except (TypeError, ValueError):
        return MAX_STEPS


def start_recording() -> bool:
    """
    **明确要求开始录像**(不管 `KARDS_TRACE` 现在是不是关的)。

    ★ 为什么需要它:离线用例必须**默认不录像** —— 它们会构造很多 `MobileTurnEngine`,
      一跑就是几十个"步",**直接把生产录像目录(`~/Desktop/手机版截图/trace/`)塞满**。
      (实测:一次全量回归就往里写了三个 55 步的会话,内容全是 `_frame` 那种测试帧。)
      ⇒ 用例开头把 `KARDS_TRACE=0`,要考录像的那几节再调这个函数 + 配临时目录。
    """
    os.environ["KARDS_TRACE"] = "1"
    return True


def _safe(name: str, limit: int = 28) -> str:
    """把中文/空格/符号压成一个能当目录名的短标签(中文保留 —— Windows 上没事)。"""
    s = re.sub(r'[\\/:*?"<>|\s]+', "", str(name or ""))[:limit]
    return s or "step"


def _pngs(d: str) -> int:
    try:
        return sum(1 for f in os.listdir(d) if f.endswith(".png"))
    except OSError:
        return 0


# ---------------------------------------------------------------------------
# ★★ 全局"当前录像器" —— 让 `mobile_hand` / `mobile_attack` 能**在动作做完的那一刻**
#    把"之后那一帧"交上来。
#
# 为什么必须是"那一刻":`think()` 返回之后引擎就接着干别的,下一个决策点是十几秒后 ——
# 那时候再抓一帧,画面早就变了,**存下来的 after.png 不是这一步的结果**。
# 只有**做动作的那个人**知道"我刚做完、现在这一帧就是结果"。
#
# ★ 和 `mobile_attack.LAST_ACTOR` 同一个套路(模块级旁路):这样**不用改任何签名**,
#   所有拿替身注入的用例一个都不用动。
# ---------------------------------------------------------------------------
_RECORDER = None


def set_recorder(tr):
    """引擎启动时把当前录像器挂上(`None` = 没录像,所有上报都是空操作)。"""
    global _RECORDER
    _RECORDER = tr
    return tr


def get_recorder():
    return _RECORDER


def report_after(frame):
    """
    动作**刚做完**时把自己抓到的那一帧交上去(没录像时是空操作,**绝不抛出**)。
    """
    r = _RECORDER
    if r is None or frame is None:
        return
    try:
        r.note_after(frame)
    except Exception:                             # noqa: BLE001
        pass


def sessions() -> list:
    """所有会话目录,按名字(即时间)排序 —— 老的在前。"""
    root = trace_root()
    if not os.path.isdir(root):
        return []
    return sorted(os.path.join(root, n) for n in os.listdir(root)
                  if _SESSION_RE.match(n) and os.path.isdir(os.path.join(root, n)))


def _count_steps(s: str) -> int:
    try:
        return sum(1 for n in os.listdir(s)
                   if _STEP_RE.match(n) and os.path.isdir(os.path.join(s, n)))
    except OSError:
        return 0


def _steps_sorted(s: str) -> list:
    """一个会话里的步目录,按步号排序(老的在前)。"""
    try:
        ps = [os.path.join(s, n) for n in os.listdir(s)
              if _STEP_RE.match(n) and os.path.isdir(os.path.join(s, n))]
    except OSError:
        return []
    return sorted(ps, key=lambda p: int(_STEP_RE.match(os.path.basename(p)).group(1)))


def _rm_steps(paths) -> int:
    n = 0
    for p in paths:
        try:
            shutil.rmtree(p, ignore_errors=True)
            n += 1
        except OSError:
            pass
    return n


def prune(verbose: bool = False) -> dict:
    """
    删到上限以内。★ **按会话为单位**:先删最旧的**整个会话**,当前这一局不动。

    ★★ 第一版这里有两个真 bug(被 `shots/_trace_prune_test` 那种"多会话"场景当场抓出来):
      ① **删的时候只减了自己记的账,没重新数磁盘** —— 一旦有一次没删干净,
         账面和实际就分家了,而这个函数**越算越错**;
      ② **删完步之后没看结果** —— 一个会话可能被删光了步却剩个空壳,
         而调用方按"目录还在"算它,于是"保留的会话数"是错的。
      ⇒ 现在每一步都**以磁盘为准**:删完就重新数,数到不超为止。

    返回 `{steps, sessions, deleted_sessions, deleted_steps}`(给日志用)。
    """
    out = {"steps": 0, "sessions": 0, "deleted_sessions": 0, "deleted_steps": 0}
    try:
        # ---- ① 超了就从**最旧的会话**开始整个删 ----
        while True:
            ss = sessions()
            total = sum(_count_steps(s) for s in ss)
            if total <= _max_steps() or len(ss) <= 1:
                break
            victim = ss[0]
            out["deleted_steps"] += _count_steps(victim)
            shutil.rmtree(victim, ignore_errors=True)
            out["deleted_sessions"] += 1

        # ---- ② 每个会话内部再兜一道 ----
        for s in sessions():
            steps = _steps_sorted(s)
            excess = len(steps) - MAX_STEPS_PER_SESSION
            if excess > 0:
                out["deleted_steps"] += _rm_steps(steps[:excess])
            tv = os.path.join(s, "turns")
            if os.path.isdir(tv):
                try:
                    fs = sorted((os.path.join(tv, f) for f in os.listdir(tv)
                                 if f.endswith(".png")), key=os.path.getmtime)
                    for old in fs[:-MAX_STEPS_PER_SESSION]:
                        os.remove(old)
                except OSError:
                    pass
            # ---- ③ 一个**一步都没剩**的会话目录 = 空壳,顺手清掉 ----
            if _count_steps(s) == 0:
                try:
                    if not os.listdir(tv):
                        os.rmdir(tv)
                except OSError:
                    pass
                try:
                    os.rmdir(s)
                except OSError:
                    pass          # turns/ 里还有图就不动它,留着也有用

        out["sessions"] = len(sessions())
        out["steps"] = sum(_count_steps(s) for s in sessions())
        if verbose:
            print(f"录像目录 {trace_root()}")
            print(f"  会话 {out['sessions']} 个,步 {out['steps']}(上限 {_max_steps()})")
            if out["deleted_sessions"] or out["deleted_steps"]:
                print(f"  删掉:会话 {out['deleted_sessions']} 个 / 步 "
                      f"{out['deleted_steps']} 个")
    except Exception as e:                        # noqa: BLE001
        if verbose:
            print(f"  (prune 出错,忽略:{type(e).__name__}: {e})")
    return out


class MobileTrace:
    """
    一个会话的录像。**每一步一个目录**:

        <root>/<会话>/
            step_0001_出牌成功/  before.png / after.png / look.png / decision.txt
            step_0002_拒拖/      before.png / look.png / decision.txt
            turns/  turn_0001_support.png ...     ← 每回合一张**全景**
            session.txt                            ← 这次跑的说明(模板表/平台/开关)

    `look.png` = before 上**画出引擎当时看到了什么**(手牌候选/场上能行动的单位/
    按钮颜色/状态)—— 这是最值钱的一张,理由见文件头。

    ★ 所有写入都包在 try 里:**存帧失败绝不许弄崩引擎**。
    """

    def __init__(self, log=print, root: str = None, every_step: bool = True):
        self.log = log or (lambda m: None)
        self.every_step = every_step
        self.on = bool(every_step) and enabled()
        self.step = 0
        self.turn = 0
        self.dir = ""
        self.error = ""
        # 手机模板在一个录像会话内不会变化。`_look()` 每一步都会画结束回合
        # 按钮，如果每次都重新读 JSON 和 PNG，会把录像开销放大成大量重复 I/O，
        # 还会反复清空 ui_state.TEMPLATE_REGIONS。延迟到第一次真正需要绘制时
        # 加载，并在本会话内复用；录像关闭时不会触发任何加载。
        self._android_templates = None
        self._android_templates_loaded = False
        #: 动作**刚做完**那一帧(由 `report_after` 放进来;`record` 用它当 after)。
        self.after = None
        if self.on:
            # ★ **只算目录名,先不建** —— 真要写东西时 `_ensure_dir()` 才建。
            #   理由见 `_ensure_dir`:引擎一构造就挂录像器,而只读工具
            #   (`mobile_verify20.py`)也会构造引擎 —— 早建就会留下"步=0"的空壳。
            self.dir = os.path.join(root or trace_root(),
                                    time.strftime("%Y%m%d_%H%M%S"))

    def _get_android_templates(self):
        """返回本录像会话复用的手机模板表。失败时缓存空表，避免每步重试。"""
        if self._android_templates_loaded:
            return self._android_templates or {}
        self._android_templates_loaded = True
        try:
            import ui_state
            meta, _note = ui_state.load_platform_meta("android")
            self._android_templates = ui_state.load_templates(meta)
        except Exception as e:                    # noqa: BLE001
            self._android_templates = {}
            self.log(f"[trace] 手机模板加载失败(look 退回无按钮框):"
                     f"{type(e).__name__}: {e}")
        return self._android_templates

    # -- 内部 ----------------------------------------------------------
    def _ensure_dir(self) -> bool:
        """
        ★★ **按需**建会话目录(第一次真要写东西的时候才建)。

        为什么:引擎一构造就会挂上录像器,而 `mobile_verify20.py` 这类**只读**工具
        也会构造引擎 —— 如果构造函数里就建目录,那**跑一次只读复验就留下一个空会话**。
        实测就是这么冒出来的:目录里躺着一堆"步=0"的空壳,和真录像混在一起分不清。
        """
        if self.dir and os.path.isdir(self.dir):
            return True
        try:
            os.makedirs(self.dir, exist_ok=True)
            os.makedirs(os.path.join(self.dir, "turns"), exist_ok=True)
            return True
        except Exception as e:                    # noqa: BLE001
            self.log(f"[trace] 建会话目录失败(不影响引擎):{type(e).__name__}: {e}")
            return False

    def _w(self, path, img, what):
        if img is None:
            return False
        try:
            mh._w(path, img, what)
            return True
        except Exception as e:                    # noqa: BLE001
            self.log(f"[trace] 存帧失败(不影响引擎):{what} {type(e).__name__}: {e}")
            return False

    def session_note(self, lines):
        """把"这次是怎么跑的"写进 session.txt(模板表、平台、开关)——复盘时先看它。"""
        if not self.on or not self._ensure_dir():
            return
        try:
            with open(os.path.join(self.dir, "session.txt"), "w",
                      encoding="utf-8") as f:
                f.write("\n".join(str(x) for x in lines) + "\n")
        except Exception:                         # noqa: BLE001
            pass

    def note_after(self, frame):
        """动作刚做完的那一刻,把结果帧交上来(见文件头那段"为什么必须是那一刻")。"""
        self.after = frame

    def turn_overview(self, frame, state=None, note=""):
        """每回合留一张**全景** —— 相当于一条进度条,不用一帧帧翻。"""
        if not self.on or frame is None or not self._ensure_dir():
            return
        self.turn += 1
        try:
            look = self._look(frame, state, f"T{self.turn} {note}")
            p = os.path.join(self.dir, "turns",
                             f"turn_{self.turn:03d}_{_safe(note)}.png")
            self._w(p, look if look is not None else frame, "回合全景")
        except Exception as e:                    # noqa: BLE001
            self.log(f"[trace] 回合全景失败:{type(e).__name__}: {e}")

    def _look(self, frame, state=None, note=""):
        """
        画出**引擎当时看到了什么**。失败返回 None(调用方自己退回原图)。
        """
        try:
            import cv2
            import mobile_board as mb
            vis = frame.copy()
            n_hand = n_unit = 0
            zone = mh._zone_for(frame, None)
            cards = mh.find_hand(frame, zone=zone, debug=False)
            n_hand = len(cards)
            for b in cards:
                col = (0, 220, 0) if b["kind"] == "unit" else (
                    (0, 140, 255) if b["kind"] == "unknown" else (0, 0, 255))
                cv2.rectangle(vis, (b["x"], b["y"]),
                              (b["x"] + b["w"], b["y"] + b["h"]), col, 1)
                cv2.putText(vis, b["kind"][:3], (b["x"], max(10, b["y"] - 3)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.34, col, 1, cv2.LINE_AA)
            try:
                units = mb.actionable_units(frame)
                n_unit = len(units)
                for u in units:
                    c = u["card"]
                    cv2.rectangle(vis, (c["x"], c["y"]),
                                  (c["x"] + c["w"], c["y"] + c["h"]),
                                  (255, 0, 255) if u["row"] == "front" else (255, 200, 0),
                                  1)
            except Exception:                     # noqa: BLE001
                pass
            btn = ""
            try:
                # `end_turn_state` accepts a preloaded template table. Reuse the
                # same table for both the colour decision and the box overlay;
                # otherwise each step would parse all Android templates twice.
                tpls = self._get_android_templates()
                st = mb.end_turn_state(frame, tpls)
                btn = {"white": "白(还有余量)", "orange": "橙(费用用完)",
                       None: "没显示(对方回合?)"}.get(st, "")
                if st is not None:
                    sc, reg = None, None
                    import ui_state
                    tpl = ("end_turn_btn_white" if st == "white" else "end_turn_btn")
                    if tpl in tpls:
                        sc, reg = ui_state.match_roi(frame, tpl, tpls[tpl])
                    if reg is not None and sc is not None and sc >= 0.82:
                        x, y, w, h = (reg["x"], reg["y"], reg["w"], reg["h"]) \
                            if isinstance(reg, dict) else (int(v) for v in reg[:4])
                        cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 255, 255), 2)
                        cv2.putText(vis, f"end_turn {st} {sc:.2f}", (x, max(12, y - 4)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1,
                                    cv2.LINE_AA)
            except Exception:                     # noqa: BLE001
                pass
            head = (f"state={state}  按钮={btn}  手牌候选={n_hand}  "
                    f"场上能行动={n_unit}")
            cv2.rectangle(vis, (0, 0), (vis.shape[1], 26), (0, 0, 0), -1)
            cv2.putText(vis, (head + "  " + note)[:118], (6, 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)
            cv2.putText(vis, "绿=单位 橙=拿不准 红=指令  紫=前线单位 黄=支援线单位",
                        (6, vis.shape[0] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                        (200, 200, 200), 1, cv2.LINE_AA)
            return vis
        except Exception as e:                    # noqa: BLE001
            self.log(f"[trace] look.png 画不出来(退回原图):{type(e).__name__}: {e}")
            return None

    # -- 对外:记一步 ----------------------------------------------------
    def record(self, tag: str, before, after=None, state=None, lines=None,
               turn: int = None):
        """
        记一步。`tag` 是给人看的短标签(如"出牌成功"/"拒拖"),会进目录名。

        ★ `after=None` 是**正常情况**:拒拖 / 等门控 / 找不到按钮 —— 这些步"
          做了决定但没有动作",`after` 本来就不存在。不要为了凑齐两帧去抓一张。
        """
        if not self.on:
            return ""
        if after is None:
            after = self.after                # 动作自己交上来的那一帧(可能还是 None)
        # ★★ **用完就清** —— 这一步的 after 绝不许漏给下一步。
        #   这个洞是 CASE 17 钉出来的:上一步"出牌成功"交上来的帧,
        #   被下一步"拒拖"当成了自己的 after,于是拒拖也长出了一张 after.png。
        self.after = None
        if not self._ensure_dir():
            return ""
        self.step += 1
        try:
            name = f"step_{self.step:04d}_{_safe(tag)}"
            d = os.path.join(self.dir, name)
            os.makedirs(d, exist_ok=True)
            self._w(os.path.join(d, "before.png"), before, "before.png")
            if after is not None:
                self._w(os.path.join(d, "after.png"), after, "after.png")
            look = self._look(before, state, f"#{self.step} {tag}")
            if look is not None:
                self._w(os.path.join(d, "look.png"), look, "look.png")
            body = {
                "step": self.step,
                "turn": turn if turn is not None else self.turn,
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "tag": tag,
                "state": state,
                "has_after": after is not None,
                "lines": [str(x) for x in (lines or [])],
            }
            with open(os.path.join(d, "decision.txt"), "w", encoding="utf-8") as f:
                f.write(json.dumps(body, ensure_ascii=False, indent=1) + "\n")
                f.write("\n".join(body["lines"]) + "\n")
            # 每记若干步清一次(不用每步都扫目录)
            if self.step % 25 == 0:
                prune()
            return d
        except Exception as e:                    # noqa: BLE001
            self.log(f"[trace] 记这一步失败(不影响引擎):{type(e).__name__}: {e}")
            return ""


def status():
    root = trace_root()
    ss = sessions()
    print(f"录像目录: {root}")
    print(f"开关: {'开' if enabled() else '关(KARDS_TRACE=0)'}"
          f"   上限: {_max_steps()} 步(每会话 {MAX_STEPS_PER_SESSION})")
    if not ss:
        print("  还没有任何会话")
        return 0
    total = 0
    for s in ss:
        steps = _count_steps(s)
        total += steps
        print(f"  {os.path.basename(s)}  步={steps:4d}  "
              f"回合全景={_pngs(os.path.join(s, 'turns')):3d}")
    size = 0
    for dp, _dn, fn in os.walk(root):
        for f in fn:
            try:
                size += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    print(f"  合计 {total} 步,占用 {size / 1024 / 1024:.0f} MB")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--prune" in sys.argv:
        prune(verbose=True)
    sys.exit(status())
