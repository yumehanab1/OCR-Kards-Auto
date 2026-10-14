"""
ui_state.py - classify the current KARDS screen state by template matching.

State is decided from the set of UI templates that are *visible* right now.
You teach the classifier which templates imply which state in config/states.json:

{
  "states": {
    "main_menu":   {"any_of": ["play_btn", "store_btn"]},
    "queueing":    {"any_of": ["cancel_queue_btn"]},
    "in_game":     {"any_of": ["end_turn_btn"]},
    "defeat":      {"any_of": ["defeat_continue_btn"]},
    "victory":     {"any_of": ["victory_continue_btn"]}
  }
}

A state fires when any template in its any_of list matches above threshold.
Templates are matched against the live window capture.
"""

from __future__ import annotations

import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from win import capture_client_bgr, find_by_process, set_dpi_aware  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_THRESHOLD = 0.82

# ★★★ 2026-09-13(第九个会话):**每个模板按它自己录制时的 `region` 去搜,不再整帧搜。**
#
# 为什么(实测):`classify` 原来对**每一个**模板都在**整帧 1280x720** 上跑
# `cv2.matchTemplate`。这个函数被 main_loop **每个 tick 调一次**,
# 而 config 里有 17 个模板 —— 实测一次 **1.63s**。
# 于是"一个 tick" = 1.63s(状态识别) + 0.8s(主循环 sleep)+ 两次抓帧
# ≈ **2.7s**,而**一个阶段要占一个 tick**:实机日志里"攻击阶段结束"与
# "上前线阶段结束"两行之间稳定是 **4 秒**(那一段其实什么都没做)。
#
# 每个模板在 `config/templates.json` 里都带 `region`(录制时它所在的小方块,
# 实测只有 100x40 ~ 230x100 那么大)。**模板一定在那块 region 里**,
# 所以在那块 region(再放 `ROI_PAD` 余量)里搜就够了:
# 面积比约 1/30 -> 一次 classify 从 1.63s 降到 ~0.1s。
#
# ★ 安全性:`ROI_PAD` 给了余量;真要是某个 UI 挪了位置,那个模板就搜不到,
#   状态判不出来 —— 而这**不是 fail-silent**:`state` 会变成 None,
#   主循环会打 `state -> None` 并走"未知画面"分支(不会乱点)。
#   留 `--full-frame` / `ROI_MATCH=False` 一键退回老行为。
ROI_PAD = 40
ROI_MATCH = True
# classify 用:模板名 -> (x, y, w, h),由 load_templates 从 meta 里带出来
TEMPLATE_REGIONS: dict = {}

# ★★★ 2026-09-17(手机端):**模板要按"显示比例"缩放再匹配。**
#
# 背景:用户指出"**按钮长得完全一样,只是显示比例问题**" —— 实测证实了。
# 在基准 1280x720 空间里扫模板缩放,`play_btn` 的匹配分是这样的:
#     k=1.0 -> 0.407   k=1.1 -> 0.521   k=1.2 -> 0.644
#     k=1.3 -> **0.776** ← 峰值        k=1.4 -> 0.583   k=1.5 -> 0.492
# 而**游戏自己的设置里写着 `UI 比例 1.4`**(存帧 `shots/android/settings/01_*.png`)——
# 峰值 1.3 和它是同一件事(差的 0.1 是重采样与平台渲染差异)。
#
# 为什么不能"把帧缩一缩凑上去":缩放**整帧**会把那些 22x22 的小徽章一起缩糊,
# 而费用徽章/类型图标那些判据对细节很敏感(§7 里为这个踩过好几次)。
# 所以在**模板这一侧**缩 —— 帧始终是它原样。
#
# 默认只有 `1.0` = **Windows 那边老行为一个字节没变**;手机端由 `--ui-scale` 传目标比例。
EXTRA_SCALES: tuple = (1.0,)
#: 缩放后的模板小于这个尺寸就没意义了(会退化成噪声匹配)
MIN_TPL_PX = 8


def scale_template(tpl: np.ndarray, k: float) -> np.ndarray:
    """
    把模板按 k 缩放。`k == 1.0` **原样返回**(不重采样 —— 老路径要一个字都不变)。

    ★ 缩小用 `INTER_AREA`、放大用 `INTER_CUBIC`:这是 OpenCV 各自的推荐做法,
      用错方向会让模板糊掉、匹配分整体下降。
    """
    if abs(k - 1.0) < 1e-6:
        return tpl
    h, w = tpl.shape[:2]
    nw = max(MIN_TPL_PX, int(round(w * k)))
    nh = max(MIN_TPL_PX, int(round(h * k)))
    interp = cv2.INTER_AREA if k < 1.0 else cv2.INTER_CUBIC
    return cv2.resize(tpl, (nw, nh), interpolation=interp)


def best_scale_match(haystack: np.ndarray, needle: np.ndarray, scales=None):
    """
    在几个候选缩放里挑**分数最高**的那个。

    返回 `(score, box, k)`。`scales` 缺省用模块级 `EXTRA_SCALES`。
    ★ 多比例会成倍增加匹配时间 —— 但 `ROI_MATCH` 已经把搜索区缩到 1/30,
      而且比例候选通常就两三个,实测开销可以接受(这条要按实机 tick 时间复验)。
    """
    scales = scales if scales is not None else EXTRA_SCALES
    best = (-1.0, None, 1.0)
    for k in scales:
        s, box = match_one(haystack, scale_template(needle, k))
        if s > best[0]:
            best = (s, box, k)
    return best


def load_meta(meta_path: str) -> dict:
    with open(meta_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_templates(meta: dict) -> dict[str, np.ndarray]:
    """Return {name: template_bgr} loading from meta entries."""
    out = {}
    TEMPLATE_REGIONS.clear()
    for name, entry in meta.get("templates", {}).items():
        path = entry["path"]
        abs_path = path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)
        img = cv2.imread(abs_path, cv2.IMREAD_COLOR)
        if img is None:
            print(f"WARN cannot load template {name}: {abs_path}")
            continue
        out[name] = img
        # ★ 顺手把录制位置留下来给 classify 用(见 ROI_MATCH 的说明)
        r = entry.get("region")
        if r:
            TEMPLATE_REGIONS[name] = (int(r["x"]), int(r["y"]),
                                      int(r["w"]), int(r["h"]))
    return out


def match_one(haystack: np.ndarray, needle: np.ndarray) -> tuple[float, tuple[int, int, int, int] | None]:
    """Return (max_score, region(x,y,w,h)) or score<0 if sizes invalid."""
    hh, hw = haystack.shape[:2]
    nh, nw = needle.shape[:2]
    if nh > hh or nw > hw:
        return -1.0, None
    res = cv2.matchTemplate(haystack, needle, cv2.TM_CCOEFF_NORMED)
    _, maxv, _, maxloc = cv2.minMaxLoc(res)
    return float(maxv), (int(maxloc[0]), int(maxloc[1]), nw, nh)


def match_roi(frame: np.ndarray, name: str, tpl: np.ndarray):
    """
    在模板自己录制的那块 region(外放 `ROI_PAD`)里匹配;没有 region 信息就整帧。

    ★ 返回的坐标**换算回整帧坐标**,所以调用方拿到的东西和整帧匹配时一致。
    ★ 2026-09-17:`EXTRA_SCALES` 不止一个比例时,在这里就把缩放一起试掉 ——
      调用方(classify / 各处 probe)**不用改**。
    """
    r = TEMPLATE_REGIONS.get(name) if ROI_MATCH else None
    if r is None:
        s, box, k = best_scale_match(frame, tpl)
        return s, box
    fh, fw = frame.shape[:2]
    x0 = max(0, r[0] - ROI_PAD)
    y0 = max(0, r[1] - ROI_PAD)
    x1 = min(fw, r[0] + r[2] + ROI_PAD)
    y1 = min(fh, r[1] + r[3] + ROI_PAD)
    # ★ ROI 是按**模板原始尺寸**算的;模板放大之后就未必放得下了 ——
    #   放不下就直接整帧(宁可慢一点,也不要"因为模板变大而搜不到")。
    biggest = max(EXTRA_SCALES) if EXTRA_SCALES else 1.0
    need_w = int(tpl.shape[1] * biggest)
    need_h = int(tpl.shape[0] * biggest)
    if x1 - x0 < need_w or y1 - y0 < need_h:
        s, box, k = best_scale_match(frame, tpl)
        return s, box
    score, reg, k = best_scale_match(frame[y0:y1, x0:x1], tpl)
    if reg is not None:
        reg = (reg[0] + x0, reg[1] + y0, reg[2], reg[3])
    return score, reg


def classify(
    frame: np.ndarray,
    templates: dict[str, np.ndarray],
    states: dict,
    threshold: float = DEFAULT_THRESHOLD,
) -> tuple[str | None, dict]:
    """
    Returns (state_name_or_None, matches) where matches = {template: score}
    for every template that fired at/above threshold.
    """
    matches: dict[str, float] = {}
    for name, tpl in templates.items():
        # ★ 2026-09-13:有 region 就在 region 里搜(快 ~15 倍),见 ROI_MATCH 的说明
        score, _ = match_roi(frame, name, tpl)
        if score >= threshold:
            matches[name] = score

    # Evaluate states: a state fires when any_of templates present (all in list? any_of)
    # We use "any_of" semantics: first state whose any template matched wins.
    for state, rule in states.items():
        names = rule.get("any_of", [])
        for nm in names:
            if nm in matches:
                return state, matches
        if not names and rule.get("all_of"):
            if all(n in matches for n in rule["all_of"]):
                return state, matches
    return None, matches


class StateGate:
    """
    **动作前的"稳一稳"闸门** —— 同一个状态要连续看到 `need` 帧才放行。

    ★★★ 为什么要有这个东西(2026-09-17 在真设备上量到的,不是想出来的):

      界面切换中间会抓到**过渡帧**,而过渡帧认出来的东西**是错的**。实测两例:

        · `shots/android/queue/q_b.png` —— **发牌动画**那一瞬间,牌还在飞。
          它认不出(返回 None),这是对的;
        · 牌组详情页**关闭动画**中间的那一帧 —— `casual_mode_btn` 和
          `mode_menu_btn` **同时**命中(1.000 / 0.9999),于是引擎以为
          "我在牌组详情页"。而真实情况是它正在回到列表。
          (那一帧把整机验收用例都骗了:前置条件判错,连点三次都没走到主菜单。)

      ⇒ 单帧的识别结果**不足以支撑动作**。要求"连续两帧认出同一个状态",
        过渡帧就自然被挡掉了:过渡帧要么认不出、要么和稳定后的状态不一致。

    ★ `need=1` 就是**老行为**(直接放行)—— 所以电脑端那条已经跑了几个月的路
      一个字节都没变,风险为零。

    ★ 语义上有一处刻意的选择:**认不出(None)会把计数清零**。
      因为"认不出"是 fail-closed 的,不该和某个状态凑成"连续两次"。
    """

    def __init__(self, need: int = 1):
        self.need = max(1, int(need))
        self._last = None
        self._count = 0

    def feed(self, state):
        """
        喂一帧的识别结果,返回**可以据以动作**的状态(还没稳就返回 None)。

        ★ 返回 None 在这里的意思是"**再等等**",和"这一屏认不出"是同一形状 ——
          调用方对两者的反应本来就该一样:什么都别做。
        """
        if state is None:
            self._last, self._count = None, 0
            return None
        if state == self._last:
            self._count += 1
        else:
            self._last, self._count = state, 1
        return state if self._count >= self.need else None

    def pending(self):
        """正在确认中、还差几帧的状态(只给日志用,不参与判断)。"""
        if self._last is None or self._count >= self.need:
            return None
        return f"{self._last}({self._count}/{self.need})"

    def reset(self) -> None:
        self._last, self._count = None, 0


def load_states(states_path: str) -> dict:
    if not os.path.exists(states_path):
        return {}
    with open(states_path, "r", encoding="utf-8") as f:
        return json.load(f).get("states", {})


# ---------------------------------------------------------------------------
# 按平台挑模板表(2026-09-17,用户定的方向:"两个项目分开、模板改一下")
#
# 为什么要有这个:
#   * 模板是在**电脑端**录的(`config/templates.json`,1280x720 空间)。
#   * 手机端的渲染和电脑**不一样**:实测把游戏的 `UI 比例` 调到 1.0 之后,
#     `play_btn` 也只到 **0.745**(阈值 0.82)—— 差的是抗锯齿/字体/贴图采样,
#     重采样补不回来。
#   * 所以两边**各录各的**:手机端那套由 `template_rebuild.py --state <屏>` 生成,
#     一屏一个文件(`config/templates.android.<屏>.json`),有哪个用哪个。
#
# ★ 合并而不是"二选一":`classify` 是"拿**全部**模板一起判当前是哪个状态",
#   所以状态机要的是**一张合并表** —— 每屏各贡献自己那部分。
# ★ 同名冲突时**后面的覆盖前面的**:屏的顺序由 `_ANDROID_STATE_ORDER` 固定,
#   保证可复现(不依赖 `os.listdir` 的顺序 —— 那种"今天和明天跑不一样"最难查)。
# ---------------------------------------------------------------------------
_ANDROID_STATE_ORDER = ("main_menu", "deck_select", "queueing", "mulligan",
                        "ingame", "victory", "defeat")


def android_meta_paths(config_dir: str = "") -> list:
    """手机端所有可用的分屏模板表(**按固定顺序**)。"""
    d = config_dir or os.path.join(PROJECT_ROOT, "config")
    out = []
    for state in _ANDROID_STATE_ORDER:
        p = os.path.join(d, f"templates.android.{state}.json")
        if os.path.exists(p):
            out.append((state, p))
    return out


def load_platform_meta(platform_name: str = "", config_dir: str = "") -> tuple:
    """
    按平台给出要用的模板表。返回 `(meta, 说明)`。

    ★ 那个"说明"是要写进日志的 —— **"这一局用的哪套模板"必须能一眼看见**,
      否则实机判错时第一件事就得猜这个(这个项目里"看不见的状态"踩过太多次)。

    * Windows / 其它:电脑端那一份(`config/templates.json`),**老行为不变**;
    * Android:把 `config/templates.android.<屏>.json` 全部**合并**;
      一张都没有就退回电脑端那份,而且**说明里写明是退回的** ——
      别让人误以为手机端模板已经录好了。
    """
    d = config_dir or os.path.join(PROJECT_ROOT, "config")
    pc_path = os.path.join(d, "templates.json")
    if platform_name != "android":
        return load_meta(pc_path), "电脑端模板(config/templates.json)"

    found = android_meta_paths(d)
    if not found:
        return (load_meta(pc_path),
                "⚠ 手机端**没有**分屏模板表,退回电脑端那份"
                "(用 template_rebuild.py --state <屏> 录)")

    merged = {"image_size": None, "templates": {}}
    used = []
    for state, p in found:
        m = load_meta(p)
        if merged["image_size"] is None:
            merged["image_size"] = m.get("image_size")
        merged["templates"].update(m.get("templates", {}))
        used.append(f"{state}({len(m.get('templates', {}))})")
    return merged, f"手机端模板:{' + '.join(used)}"


def snapshot_live(proc: str = "kards") -> np.ndarray | None:
    wins = find_by_process(proc)
    if not wins:
        return None
    return capture_client_bgr(wins[0]["hwnd"])


def main() -> int:
    set_dpi_aware()
    import argparse

    ap = argparse.ArgumentParser(description="KARDS screen state classifier (M1)")
    ap.add_argument("--proc", default="kards")
    ap.add_argument(
        "--meta", default=os.path.join(PROJECT_ROOT, "config", "templates.json")
    )
    ap.add_argument(
        "--states", default=os.path.join(PROJECT_ROOT, "config", "states.json")
    )
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    ap.add_argument("--image", default="", help="classify an image file instead of live window")
    ap.add_argument("--show", action="store_true", help="show matched boxes in a window")
    args = ap.parse_args()

    if not os.path.exists(args.meta):
        print("no templates.json yet - run src/template_capture.py first")
        return 1

    meta = load_meta(args.meta)
    templates = load_templates(meta)
    states = load_states(args.states)
    if not templates:
        print("no templates defined - run src/template_capture.py first")
        return 1

    frame = cv2.imread(args.image) if args.image else snapshot_live(args.proc)
    if frame is None:
        print("no frame to classify")
        return 1

    state, matches = classify(frame, templates, states, args.threshold)
    print(f"state: {state}")
    if not matches:
        print("  (no template matched at threshold %.2f)" % args.threshold)
    for name, score in sorted(matches.items(), key=lambda kv: -kv[1]):
        print(f"  matched {name}: {score:.3f}")

    # optionally show frame with boxes
    if args.image or args.show:
        vis = frame.copy()
        for name, tpl in templates.items():
            s, reg = match_one(frame, tpl)
            if s >= args.threshold and reg:
                x, y, w, h = reg
                cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 255, 0), 2)
                cv2.putText(vis, name, (x, max(12, y - 4)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)
        cv2.imshow("classify", vis)
        cv2.waitKey(0)
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
