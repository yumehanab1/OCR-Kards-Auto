"""
guard.py - ★★★ 守护(guard)标记识别(2026-09-12 第七个会话,用户给的正样本)

判据的全部来源(用户 2026-09-12 亲口指出 + 帧级证据)
-----------------------------------------------------
  ① "对面总部被守护,右边那个步兵带守护"                -> 正样本 `shots/live_probe.png`
  ② "总部的盾牌标不是被挤得只剩一半,而是那是**被守护的标识**:
      **半个盾牌加上半个盾牌外框**"

盘面上有两种盾牌标记,都挂在卡的**右边缘、和费用徽章同高**那条带上
(实测:相对卡框 = **卡右边 −15px / 卡顶边 +12~13px**),外面是一块深色圆角 tab:

    ┌──────────┐ ╔════╗
    │ 卡面右半 │ ║ 🛡 ║   ├─ **实心盾牌**    = 这张**单位**带【守护】
    └──────────┘ ╚════╝   ├─ **半盾+盾牌外框** = 这张卡(总部)**正被守护**
                          └─ 别的字形(`+`/`⊕`) = 别的特性,**不是守护**

★★ 为什么**不需要**区分这两种盾:`is_hq` 已经告诉我们这张卡是不是总部 ——
   · **总部卡**上有盾 -> 总部被守护(别打它,先打掉守护单位);
   · **单位卡**上有盾 -> 这张单位就是守护单位(先打它)。
   所以判据只回答一个问题:**"这张卡的右边有没有盾牌字形"**。

★★ A/B(实测分数,**分开得很干净**)—— 语料 = `shots/attack_frames` +
   `shots/board_samples` + `shots/live_probe.png`,466 个候选卡:

   | 区域 | 打分 |
   |---|---|
   | 真盾牌(实心盾 / 半盾) | **0.982 ~ 1.000** |
   | `+` 那个 tab(191712 敌方战斗机) | 0.603 |
   | `⊕` 那个 tab(191712 敌方战斗机) | 0.750 |
   | 桌面/卡面等其它区域 | < 0.80 |

   -> 门槛取 **0.90**,落在空档里(0.75 -> 0.98)。

★★★ **它其实很常见 —— 我上一轮说"盘面卡上看不出守护标记"是错的**:
   带 `guard` 的卡在卡库里就有 **122 张**,语料里命中盾牌标记的卡**很多**
   (包括 0911_122530 那批旧帧里的敌方前线卡、0912_1927xx 帧里的卡)。
   上一轮我只把 4 张卡摊开看(它们正好都不带守护:两张是 `+`/`⊕`),
   就下了"没有标记"的结论 —— 这正是 §7 第 63/78 条那条教训的又一次重演。

⚠️ 诚实的局限:正样本**只有两个字形**,而且它们是从 `live_probe.png` 裁出来的;
   本帧的自匹配必然是 1.000。上面那张表里 0.982 那些**是别的帧**(算真验证),
   但"守护"这一族目前**帧数还少**。所以这里 **fail-soft**:
   认不出就当"没有守护"(见 `read_guard` 的说明),别让它把攻击卡死。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL_UNIT = os.path.join(ROOT, "config", "guard_unit.png")   # 实心盾 = 单位带守护
TPL_HQ = os.path.join(ROOT, "config", "guard_hq.png")       # 半盾+外框 = 这张卡被守护

# ★ 搜索窗:相对**卡框右边缘** / **卡框顶边**(实测命中都落在 dx≈-15, dy≈+12)
DX0, DX1 = -60, 40
DY0, DY1 = -10, 50
# ★★ 2026-09-12(第七个会话,第二局实机)**加 3x3 高斯模糊再匹配** —— 这一条是被实机
#    逼出来的:20:51 那两帧的敌方总部盾牌**人眼看着和模板一模一样**,可分数只有
#    **0.894**,差 0.006 卡在门槛下面 -> `未见守护标记` -> 那一发打总部**没掉血**
#    (19->19)。量过之后加模糊:
#      · 边缘正样本 `0.894 -> 0.927`(**过了门槛**);
#      · 已知反例(只带 `⚡` 的敌方坦克)`0.645 -> 0.723`(仍然远在门槛下)。
#    模糊压掉的是"亚像素/渲染抖动",不是把判据放松 —— 正负两侧的**间距反而更大**了。
BLUR = (3, 3)
# ★★★ 门槛 = **0.85**(2026-09-12 第二局实机之后重定,依据是"**只看 read_guard 真正会查的
#     那些卡**"的分数分布 —— 总部卡 + 敌方支援线卡,共 **175 张**):
#
#        真盾牌   0.897 ~ 0.964      (从 0.964 一路排下来,**没有断点**)
#        ---- **空档 0.781 ~ 0.897(宽 0.116)** ----
#        非盾牌   0.781 ~ 0.5x       (只带 `⚡`/`+`/`⊕` 的卡、卡面美术)
#
#     ★ 0.85 落在空档正中(两侧各留 ~0.07)。
#     ★★ 为什么**不能**用"全部卡"的分布来定门槛:把**我方那一行 / 前线**的卡也算进来时,
#        0.80~0.90 会混进卡面美术(士兵/绿叶/白边)的假阳性 —— 但 `read_guard`
#        **根本不看那两行**(只看总部 + 敌方支援线),所以那些假阳性进不了决策。
#        这条门槛是**按它真实的输入分布**定的,不是按整帧。
MATCH_MIN = 0.85

_BANK = None


def bank():
    """两个盾牌字形模板(已模糊)。读不到就返回空 dict(调用方一律当"认不出")。"""
    global _BANK
    if _BANK is None:
        _BANK = {}
        for key, p in (("unit", TPL_UNIT), ("hq", TPL_HQ)):
            img = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
            if img is not None and img.size:
                _BANK[key] = cv2.GaussianBlur(img, BLUR, 0)
    return _BANK


def glyph_at(frame, box, debug=False):
    """
    这张卡的**右边缘**有没有盾牌字形。返回 (score, detail)。

    判据只有一条:**模板匹配(NCC)分数 >= MATCH_MIN** ——
    实测正样本 0.982~1.000、反例(`+`/`⊕`)0.603/0.750,中间是空档(§7 第 67 条 C 那种好运)。
    """
    if frame is None or box is None:
        return 0.0, {"why": "没有帧/卡框"}
    bx = int(box["x"] + box["w"])
    by = int(box["y"])
    x0 = max(0, bx + DX0)
    x1 = min(frame.shape[1], bx + DX1)
    y0 = max(0, by + DY0)
    y1 = min(frame.shape[0], by + DY1)
    if x1 - x0 < 30 or y1 - y0 < 30:
        return 0.0, {"why": "搜索窗太小(卡框贴着画面边)"}
    win = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    win = cv2.GaussianBlur(win, BLUR, 0)      # ★ 和模板一样先模糊(见 BLUR 的说明)
    scores = {}
    for name, t in bank().items():
        if win.shape[0] < t.shape[0] or win.shape[1] < t.shape[1]:
            continue
        res = cv2.matchTemplate(win, t, cv2.TM_CCOEFF_NORMED)
        _, mx, _, ml = cv2.minMaxLoc(res)
        scores[name] = (float(mx), (x0 + ml[0], y0 + ml[1]))
    if not scores:
        return 0.0, {"why": "没有模板(config/guard_*.png 缺)"}
    name, (score, loc) = max(scores.items(), key=lambda kv: kv[1][0])
    d = {"which": name, "at": loc, "score": round(score, 3),
         "all": {k: round(v[0], 3) for k, v in scores.items()},
         "ok": bool(score >= MATCH_MIN)}
    return (score if d["ok"] else 0.0), d


def has_guard(frame, box, debug=False):
    s, d = glyph_at(frame, box, debug=debug)
    return bool(s > 0), d


def read_guard(frame, field, hq=None, debug=False):
    """
    读一帧的守护信息:
      {
        "hq_guarded": bool,        # **总部卡上有盾** -> 总部被守护,别打它
        "guard_units": [unit...],  # 敌方**单位**卡上有盾 -> 这些是守护单位(先打它们)
        "detail": {...}            # 逐卡分数(诊断)
      }

    ★ fail-soft 的取向(有意):**认不出就当"没有守护"**。
      理由:两条错误代价不对称 ——
        · "以为有守护"会**放着总部不打**(少伤害、拖长对局,而且这是凭空丢掉的确定性收益);
        · "漏掉守护"的代价被 `attack.HQ_BLOCK_AFTER_MISS` 兜住(打一次没掉血就封这一档)。
      两条一起用:认得出 -> **一次都不白拖**;认不出 -> **最多白拖一次**。
    """
    out = {"hq_guarded": False, "guard_units": [], "detail": {}}
    if frame is None:
        return out
    cards = []
    hq_keys = set()
    if hq:
        cards.append(("hq", hq))
        hq_keys.add((int(hq["x"]), int(hq["y"])))
    for u in (field.get("enemy_support") or []):
        # ★ `is_hq` 是可用的(2026-09-12 修过"一行两个总部"那个 FP,见 board.read_field);
        #   实在没有 is_hq 时才退回"调用方给的那张总部卡"。
        key = (int(u["x"]), int(u["y"]))
        if u.get("is_hq") or key in hq_keys:
            cards.append(("hq", u))
        else:
            cards.append(("unit", u))
    for kind, b in cards:
        _s, d = glyph_at(frame, b, debug=debug)
        out["detail"][f"{kind}@x{int(b['x'])}"] = d
        if not d.get("ok"):
            continue
        if kind == "hq":
            out["hq_guarded"] = True
        else:
            b["guard"] = True        # ★ 给调用方一个记号,选目标时优先打它
            out["guard_units"].append(b)
    return out


def _main():
    """只读预检:把一帧里**每张卡**的守护判据打出来(不写盘、不动作)。"""
    import argparse
    import board
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", required=True)
    ap.add_argument("--row", default="enemy", choices=["enemy", "frontline", "our", "all"])
    a = ap.parse_args()
    f = cv2.imread(a.frame)
    if f is None:
        print("读不到", a.frame)
        return
    field = board.read_field(f, templates=None)
    hq = board.find_enemy_hq(f, field=field, templates=None)
    info = read_guard(f, field, hq=hq, debug=True)
    print(f"模板 {list(bank().keys())}  门槛 {MATCH_MIN}")
    print(f"总部被守护 = {info['hq_guarded']}   守护单位 {len(info['guard_units'])} 个")
    rows = field.get("rows") or []
    for r in rows:
        if a.row != "all" and r.get("side") != a.row:
            continue
        print(f"\n行 {r.get('side')} cy={r.get('cy')} 卡数={len(r.get('boxes') or [])}")
        for b in sorted(r.get("boxes") or [], key=lambda z: z["x"]):
            s, d = glyph_at(f, b)
            mark = "盾牌 ✔" if s > 0 else "    -"
            print(f"   x{int(b['x']):<4} y{int(b['y']):<4} {int(b['w'])}x{int(b['h'])} "
                  f"is_hq={b.get('is_hq')} {mark} score={d.get('score')} {d.get('all')}")
    if hq:
        s, d = glyph_at(f, hq)
        print(f"\n（总部卡）x{int(hq['x'])} score={d.get('score')} {d.get('all')} "
              f"-> {'被守护' if s > 0 else '没有守护标记'}")


if __name__ == "__main__":
    _main()
