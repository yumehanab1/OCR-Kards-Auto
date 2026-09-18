"""
board.py - 读战场:找出双方场上的单位 + 总部,供 M4 攻击逻辑用。

为什么需要
----------
M4 要能攻击,就得先知道"我方哪个单位在哪个格子、敌方目标在哪"。

怎么认(实测 shots/live/ingame_now.png + shots/diff_base.png)
----------------------------------------------------------
1. **卡 = 与桌面显著不同的规整矩形**。桌面是暗色木纹/暗绿,单位卡是亮卡面,
   所以"到桌面主色的距离"能干净地把卡和桌面分开(比 Canny 稳:Canny 会把
   木纹、桌面装饰也当成边)。
2. **是敌是我**:两边的卡面图案完全不同 —— 敌方(苏)卡面是大片**红色**
   (红五星 + 红色宣传画),我方(德)是**灰/米色 + 铁十字**。所以用
   "卡面里红像素占比"分阵营,比按 y 分区更可靠(y 分区在中线附近会含糊)。
3. **总部(HQ)**:常驻、位置固定 —— 敌方在 y~101-252、我方在 y~377-505,
   都是那一列里最大的一张卡(20 点血量牌)。

★ 这是"够用就行"的几何法:认错一个单位不会崩,只是白打一次拖拽。
  真机验证时看 dump 出来的标注图(文件末尾 CLI)。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2
import cv_io  # noqa: F401  (开关:让 cv2 认中文路径,见 cv_io.py)
import numpy as np

import hq_hp          # ★ 总部血量盾牌读取(纯图像处理,见 hq_hp.py 文件头)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---- 战场分区(client 1280x720) ----
BOARD_Y0, BOARD_Y1 = 80, 610     # 战场纵向范围(避开顶部手牌堆与底部手牌)
# 战场区域的**下边界**:再往下就是我们的手牌扇形了(实测手牌约从 y600 起)。
# 第二代读取用它把"我们的支援线"和"手牌"分开。
FIELD_TOP_MAX = 600
BOARD_X0, BOARD_X1 = 120, 1160   # 横向范围(避开左右两侧的装饰/HUD)
MIDLINE_Y = 355                  # 中线附近(用于兜底判阵营)
HAND_MIN_Y = 600                 # 这个 y 以下是我方手牌,不是战场

# ---- 卡面判据(实测采样两个不同棋盘) ----
#   桌面(暗)  R 通道:中央 72 / 左下 62 / 左上 92(木桌) — 39~96 之间浮动
#   单位卡面  R:112~145      HQ 卡面 R:110~155
# 固定阈值会被"不同棋盘的桌面亮度差"拖累(木桌左上就比暗绿桌亮),所以用
# **自适应阈值**:卡 = 比它周围一大片桌面明显更亮。
LOCAL_BLOCK = 81          # 局部参照窗口(要明显大于一张卡,取卡宽的 ~70%)
CARD_MIN_CONTRAST = 28    # 比"局部最暗桌面"亮这么多才算卡面
COL_FRAC_MIN = 0.5        # 一列里半数以上像素是卡面,才算这一列有卡
GREEN_TABLE_MAX = 26      # 排除"绿占优"的暗绿桌面(g - r 很大)
FILL_KERNEL = 15          # 闭运算核:把卡内部的暗色美术填平

UNIT_MIN_AREA_FILL = 0.5  # 卡面像素在包围盒里的占比下限


def _card_mask(frame):
    """
    卡面掩码 = 自适应亮度阈值 ∩ 非绿桌面。

    自适应(而不是固定阈值)的理由:不同棋盘的桌面亮度能差 30 以上
    (实测暗绿桌 R≈66,木桌左下 R≈62、左上 R≈92),固定阈值在亮桌面上
    会把木纹当成卡、在暗桌面上会把卡漏掉。
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    local = cv2.erode(gray, np.ones((LOCAL_BLOCK, LOCAL_BLOCK), np.uint8))
    bright = (gray.astype(np.int16) - local.astype(np.int16)) > CARD_MIN_CONTRAST
    b, g, r = (frame[:, :, i].astype(np.int16) for i in range(3))
    not_green = (g - r) < GREEN_TABLE_MAX
    mask = (bright & not_green).astype(np.uint8) * 255
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                            np.ones((FILL_KERNEL, FILL_KERNEL), np.uint8))


# ---- 单位卡几何(实测单位卡约 121x151,总部牌约 108x128) ----
UNIT_MIN_W, UNIT_MAX_W = 80, 175
UNIT_MIN_H, UNIT_MAX_H = 85, 185

# ---- 四条战线的 y 带(实测,client 1280x720) ----
# ★ 不要用"中线"猜敌我:敌方单位会出现在中线【下方】(敌方前线),
#   我方单位会出现在中线【上方】(我方前线)。要按行带认。
#
# ★★ 行带**必须互不重叠**:实测行带一重叠,同一张卡会被相邻两条线各算一次
#    (支撑带与敌方前线带曾经重叠 60px),卡数直接虚高一倍。
#    所以每条带都取"卡面中段"那一小条,而不是整张卡的高度。
#    这些值是用 fix_bands.py 在真实帧上标定出来的(见该脚本)。
OUR_SUPPORT_BAND = (300, 340)      # 我方支援线(部署落点 y420-500 的上一行)
OUR_FRONT_BAND = (390, 430)        # 我方前线
ENEMY_FRONT_BAND = (470, 515)      # 敌方前线(离我们最近的那一行)
ENEMY_SUPPORT_BAND = (150, 190)    # 敌方支援线
ENEMY_HQ_BAND = (100, 250)         # 敌方总部

# 单张卡的"有效亮宽"(px)。实测单位卡外框约 108-121 宽,
# 但卡两侧有暗边框、卡面亮区比外框窄,所以除的时候用 92。
CARD_WIDTH_PX = 92.0

# ---- 阵营判据:卡面里"红像素"的占比 ----
# 敌方(苏)卡面有大片红色(红五星 + 红色宣传画);我方(德)几乎没有。
RED_DOMINANCE = 0.06             # r - max(g,b) > 40 的像素占比
RED_MARGIN = 40


def _red_ratio(frame, x, y, w, h):
    """卡面里"明显偏红"的像素占比(敌方苏卡有红五星/红色宣传画)。"""
    crop = frame[y:y + h, x:x + w].astype(np.int16)
    b, g, r = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]
    red = (r - np.maximum(g, b)) > RED_MARGIN
    return float(red.mean())


def count_row(frame, y0, y1, debug=False):
    """
    数某一条"战线"上有几张卡 —— **按行内的亮列数估算,不做连通域分割**。

    为什么不用 find_units:
      实测连通域法在实机帧上会失败 —— bot 自己扫描/出牌时鼠标停在画面上,
      悬停高亮会把相邻的卡**连成一大块**(实测合出 560x224、1280x474 的巨块),
      于是 find_units 返回 0 张。而这一条线要的恰恰只是"数数量",
      所以用更朴素也稳得多的办法:在卡面高度的那条带上,统计每一列是不是卡面,
      把亮的列数加起来除以单卡宽度。

    实测(shots/deploy_probe/f041.png):我支援 1 / 我前线 2 / 敌前线 2 / 敌支援 1,
    和肉眼看那一帧完全一致。

    返回 (estimated_count, detail_dict)。detail 里有亮列占比等诊断信息。
    """
    band = frame[y0:y1, BOARD_X0:BOARD_X1]
    if band.size == 0:
        return 0, {"reason": "empty band"}
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    # ★ 参照用**局部最小值**(腐蚀),不用局部均值。
    # 实测踩坑:用 81x81 的局部均值时,窗口把卡和周围桌面一起平均了,
    # 对比度被摊平 —— 卡面 V≈118、桌面 V≈67,而局部均值和卡面差不多,
    # `gray - local` 反而接近 0,于是一整行都量不出来(实测 diff 只有 15)。
    # 局部最小值近似"这张卡附近最暗的桌面",卡面减它就稳定在 30~40,
    # 在地形起伏大的棋盘(亮暗差 20~90)上也压得住。
    local = cv2.erode(gray, np.ones((LOCAL_BLOCK, LOCAL_BLOCK), np.uint8))
    bright = (gray.astype(np.int16) - local.astype(np.int16)) > CARD_MIN_CONTRAST
    col_frac = bright.mean(axis=0)                    # 每列"是卡面"的比例
    bright_cols = int((col_frac > COL_FRAC_MIN).sum())
    est = bright_cols / float(CARD_WIDTH_PX)
    detail = {"bright_cols": bright_cols, "est": round(est, 2),
              "band_h": y1 - y0}
    if debug:
        print(f"    row y{y0}-{y1}: 亮列 {bright_cols} / {col_frac.size} "
              f"-> 估 {est:.2f} 张")
    return int(round(est)), detail


def count_our_support(frame, debug=False):
    """我方支援阵线上的卡数(我们部署的位置)。"""
    return count_row(frame, *OUR_SUPPORT_BAND, debug=debug)


def count_our_front(frame, debug=False):
    """我方前线上的卡数。"""
    return count_row(frame, *OUR_FRONT_BAND, debug=debug)


def count_enemy_support(frame, debug=False):
    """敌方支援阵线上的卡数。"""
    return count_row(frame, *ENEMY_SUPPORT_BAND, debug=debug)


def count_enemy_front(frame, debug=False):
    """敌方前线上的卡数。"""
    return count_row(frame, *ENEMY_FRONT_BAND, debug=debug)


def battlefield_snapshot(frame, debug=False):
    """
    一次读四条线 + 敌方总部。
    用于"部署到底成没成功"的判定:只要场上卡数变了,部署就是真的成功了。

    ★★ 2026-09-11 中午改成**第二代卡检测**(自适应行带),不再用旧的
    `count_row`。旧版实测在真实棋盘上把桌面/地形也算成卡面 ——
    实机日志反复出现"总卡数 25~29"(棋盘上一共才十来张卡),
    于是判据频繁落进"卡数异常,改用面板判据"那条不可靠的退路。

    每条线返回 (张数, 诊断),total 是全场卡数之和。

    ★★ 2026-09-11 下午:`card_boxes` -> `merged_card_boxes`。
    离线实测(9 帧 `shots/attack_probe`)证明 **`card_boxes` 会漏掉单位卡**:
    同一行真实 3 张(2 个单位 + 总部)时它只报 1 张(只有那个总部)。
    而"部署成功判据 = 场上卡数变没变"正是靠这个函数 —— 数少一张,
    部署判据就会把成功当失败。现在两套锚点合并,见 `merged_card_boxes`。
    """
    boxes = merged_card_boxes(frame, debug=debug)
    rows = rows_from_boxes(boxes)
    by_side = {}
    for r in rows:
        by_side.setdefault(r.get("side"), []).extend(r["boxes"])
    # ★ 这里不需要区分敌我,只需要"两边各几张"和"总数" —— 部署成功
    #   一定让总数 +1,而总数不会因为认错阵营而变化。
    n = len(rows)
    if n == 0:
        counts = {"our": 0, "enemy": 0, "frontline": 0}
    elif n == 1:
        cy = rows[0]["cy"]
        side = "enemy" if cy < (FIELD_Y0 + FIELD_TOP_MAX) / 2 else "our"
        counts = {"our": 0, "enemy": 0, "frontline": 0}
        counts[side] = len(rows[0]["boxes"])
    else:
        counts = {"enemy": len(rows[0]["boxes"]), "our": len(rows[-1]["boxes"]),
                  "frontline": sum(len(r["boxes"]) for r in rows[1:-1])}
    total = len(boxes)
    detail = {"rows": [(round(r["cy"]), len(r["boxes"])) for r in rows],
              "boxes": total}
    # ★★ 2026-09-12:额外给一个**真正的"我方支援线单位数"**(不含总部)。
    #   上面那个 `our_support` 是"那一行有几张卡",它**一定把总部算进去**
    #   (用户确认总部和单位画在同一行)。用它判"线满没满"会**永远早判一格**。
    su = support_line_units(frame, rows=rows, debug=debug)
    detail["support_units_why"] = su["why"]
    if debug:
        print(f"    field: {total} 张, 行 {detail['rows']}, 分边 {counts}, "
              f"我支援单位={su['n']}")
    return {
        "our_support": (counts["our"], detail),
        # ★ 单位数(不含总部);None = 判据不可信,调用方必须 fail-closed
        "our_support_units": (su["n"], {"why": su["why"],
                                        "x": [u["box"]["cx"] for u in su["units"]]}),
        "our_front": (counts["frontline"], detail),
        "enemy_support": (counts["enemy"], detail),
        "enemy_front": (0, detail),
        "total": total,
        "by_side": counts,
    }


def battlefield_snapshot_legacy(frame, debug=False):
    """旧版(按行带数亮列)。保留仅用于对比与回归,新代码不要用。"""
    us = count_our_support(frame, debug)
    uf = count_our_front(frame, debug)
    es = count_enemy_support(frame, debug)
    ef = count_enemy_front(frame, debug)
    return {
        "our_support": us,
        "our_front": uf,
        "enemy_support": es,
        "enemy_front": ef,
        "total": us[0] + uf[0] + es[0] + ef[0],
    }


def find_units(frame, debug=False):
    """
    找出战场上的卡(单位 + 总部)。
    返回 [{'x','y','w','h','cx','cy','side'('our'/'enemy'),'red_ratio','is_hq'}]
    按 y、x 排序。
    """
    mask = _card_mask(frame)
    mask[:BOARD_Y0, :] = 0
    mask[BOARD_Y1:, :] = 0
    mask[:, :BOARD_X0] = 0
    mask[:, BOARD_X1:] = 0
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))

    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    units = []
    for i in range(1, n):
        x, y, w, h, area = (int(stats[i, 0]), int(stats[i, 1]), int(stats[i, 2]),
                            int(stats[i, 3]), int(stats[i, 4]))
        if not (UNIT_MIN_W <= w <= UNIT_MAX_W):
            continue
        if not (UNIT_MIN_H <= h <= UNIT_MAX_H):
            continue
        fill = area / float(w * h)
        if fill < UNIT_MIN_AREA_FILL:
            continue
        cx, cy = x + w // 2, y + h // 2
        rr = _red_ratio(frame, x, y, w, h)
        # ★ 阵营判据以【中线】为主,**不能靠红占比**。
        # 实测踩坑:敌方单位卡(苏军步兵,卡面是土黄+一点红)红占比只有 0.022,
        # 比阈值 0.06 低,于是被判成我方。红占比只在"中线附近含糊"时当兜底 ——
        # 敌人在中线上方、我方在下方,这是规则本身决定的,最可靠。
        if abs(cy - MIDLINE_Y) > 45:
            side = "enemy" if cy < MIDLINE_Y else "our"
        elif rr >= RED_DOMINANCE:
            side = "enemy"
        elif rr <= RED_DOMINANCE / 3:
            side = "our"
        else:
            side = "enemy" if cy < MIDLINE_Y else "our"
        units.append({"x": x, "y": y, "w": w, "h": h, "cx": cx, "cy": cy,
                      "side": side, "fill": round(fill, 2),
                      "red_ratio": round(rr, 3), "area": area})
    units.sort(key=lambda u: (u["cy"], u["cx"]))
    if debug:
        for u in units:
            print(f"    {u['side']:<5} x{u['x']}-{u['x'] + u['w']} "
                  f"y{u['y']}-{u['y'] + u['h']} ({u['w']}x{u['h']}) "
                  f"fill {u['fill']} red {u['red_ratio']}")
    return units


def find_hq(frame, side="enemy", units=None):
    """
    找总部。总部是那一方里最大的一张卡(20 血牌,尺寸约 108x128)。
    """
    pool = [u for u in (units if units is not None else find_units(frame))
            if u["side"] == side]
    if not pool:
        return None
    hq = max(pool, key=lambda u: u["w"] * u["h"])
    return hq


def our_units(frame, units=None):
    return [u for u in (units if units is not None else find_units(frame))
            if u["side"] == "our"]


def enemy_units(frame, units=None):
    return [u for u in (units if units is not None else find_units(frame))
            if u["side"] == "enemy"]


def annotate(frame, units=None, hq_enemy=None, hq_our=None):
    """把检测结果画到帧上,存图人工核对。"""
    out = frame.copy()
    for u in (units if units is not None else find_units(frame)):
        color = (0, 0, 255) if u["side"] == "enemy" else (0, 255, 0)
        cv2.rectangle(out, (u["x"], u["y"]),
                      (u["x"] + u["w"], u["y"] + u["h"]), color, 2)
        cv2.putText(out, f"{u['side'][:3]} r{u['red_ratio']:.2f}",
                    (u["x"], max(12, u["y"] - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
    for hq, color, tag in ((hq_enemy, (255, 0, 255), "HQ-E"),
                           (hq_our, (255, 255, 0), "HQ-O")):
        if hq:
            cv2.rectangle(out, (hq["x"], hq["y"]),
                          (hq["x"] + hq["w"], hq["y"] + hq["h"]), color, 3)
            cv2.putText(out, tag, (hq["x"], hq["y"] - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    cv2.line(out, (0, MIDLINE_Y), (1280, MIDLINE_Y), (0, 255, 255), 1)
    return out


ICON_NORM = 32            # 类型图标统一归一化到这个尺寸再比


def _type_icon_crop(frame, unit, debug=False):
    """
    从一张单位卡里裁出**类型图标**那一小块。

    卡面解剖(实测,见 shots/type_zoom/*_bottombar.png):
      卡底部那条深色带是三个深色小牌子:`攻击力 | 类型图标 | 防御力`。
      **中间那块**才是类型图标(步兵剪影/坦克/飞机…)。

    ★ 为什么不能按比例硬切:实测按 `x+0.34w..0.68w` 切会**偏右 25px**,
      正好把图标切掉、把右边的防御盾切进来(于是模板匹配全乱)。
      所以改成**结构化地找那三个深色小牌子,取中间那个** ——
      不依赖任何比例常数。
    """
    x, y, w, h = unit["x"], unit["y"], unit["w"], unit["h"]
    fh, fw = frame.shape[:2]
    y0 = max(0, int(y + h * 0.68))
    y1 = min(fh, int(y + h) + 4)
    x0, x1 = max(0, int(x)), min(fw, int(x + w))
    bar = frame[y0:y1, x0:x1]
    if bar.size == 0:
        return None
    hsv = cv2.cvtColor(bar, cv2.COLOR_BGR2HSV)
    dark = (hsv[:, :, 2] < 120).astype(np.uint8) * 255
    n, labels, stats, _ = cv2.connectedComponentsWithStats(dark, 8)
    boxes = []
    for i in range(1, n):
        bx, by, bw, bh, area = (int(stats[i, 0]), int(stats[i, 1]),
                                int(stats[i, 2]), int(stats[i, 3]),
                                int(stats[i, 4]))
        if not (16 <= bw <= 46 and 16 <= bh <= 46):
            continue
        if area / float(bw * bh) < 0.5:
            continue
        boxes.append((bx, by, bw, bh))
    if not boxes:
        return None
    # ★★★ 2026-09-12(第六个会话,实机抓到):**卡面美术本身也会在 bar 上边缘切出暗块**,
    #   而旧代码"按 x 排序取中间"会被这些假牌子顶偏 —— 实测那一张卡(三轮摩托/装甲车):
    #       bar 上边缘(by=0):40x16 / 22x16 / 33x17   <- **美术/路面**切出来的假牌子
    #       bar 下部(by=17~19):23x24 / 23x23 / 23x24 <- 真的 攻击|类型图标|防御
    #   6 个框按 x 排序取中间 -> 取到 `bx=46 by=0` 那个假的 -> 图标打分全是负数
    #   -> `classify_unit_type` 返回 None -> 引擎报"类型认不出" -> **整回合一次攻击都不发**
    #   (实机连续 6 个回合都是这一个单位挡住的,用户看到的"有单位能行动却不打"它就是另一半原因)。
    #
    # ★ 判据(有物理含义,不是调参):真牌子是**同一行、尺寸几乎一致**的 3 个;
    #   美术切出来的假块大小参差(40/22/33 宽)。所以先按 y 分行,再取
    #   "**牌数最多、且尺寸最一致**"的那一行,最后取该行中间那个。
    rows_of_boxes: list[list[tuple]] = []
    for b in sorted(boxes, key=lambda b: b[1]):
        for r in rows_of_boxes:
            if abs(r[0][1] - b[1]) <= 6:
                r.append(b)
                break
        else:
            rows_of_boxes.append([b])

    def _row_quality(r):
        ws = [b[2] for b in r]
        hs = [b[3] for b in r]
        spread = ((max(ws) - min(ws)) / max(1.0, sum(ws) / len(ws))
                  + (max(hs) - min(hs)) / max(1.0, sum(hs) / len(hs)))
        return (len(r), -spread)

    row = max(rows_of_boxes, key=_row_quality)
    row.sort(key=lambda b: b[0])
    if debug:
        print(f"      候选牌子 {len(boxes)} 个,分成 {len(rows_of_boxes)} 行;"
              f"选中那行 {len(row)} 个: {row}")
    # 三个牌子里取**中间**那个;数量不对时取最接近卡横向中心的
    if len(row) >= 3:
        pick = row[len(row) // 2]
    else:
        cx_bar = bar.shape[1] / 2
        pick = min(row, key=lambda b: abs(b[0] + b[2] / 2 - cx_bar))
    bx, by, bw, bh = pick
    crop = bar[by:by + bh, bx:bx + bw]
    if crop.size == 0:
        return None
    if debug:
        print(f"      类型图标块 (卡内) x{bx} y{by} {bw}x{bh} "
              f"(共找到 {len(boxes)} 个牌子)")
    return crop


def _norm_icon(img, size=ICON_NORM):
    """把图标归一化到固定大小(直接缩放;图标都是方形的)。"""
    return cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)


_ICON_CACHE = {}


def _icon_bank(templates):
    key = id(templates)
    if key not in _ICON_CACHE:
        bank = {}
        for name, tpl in templates.items():
            if name.endswith("_icon"):
                bank[name.replace("_icon", "")] = _norm_icon(tpl)
        _ICON_CACHE[key] = bank
    return _ICON_CACHE[key]


def classify_unit_type(frame, unit, templates, min_score: float = 0.55,
                       debug=False):
    """
    认一张场上单位卡的**类型**(infantry/tank/fighter/bomber/artillery/order/counter)。

    为什么需要:攻击规则依赖类型 —— 只有 fighter/bomber/artillery 能从支援阵线
    直接攻击,步兵必须先上前线。所以拖之前必须知道这是什么单位。

    ★★ 2026-09-11 中午连修两处,两处都是"静默错":
      1. 旧版在**整张卡**上跑 7 个模板。实机预检把两个单位都认成 `order`,
         于是攻击一个都不打,日志却只说"没有能直接攻击的我方单位"。
         苗头其实早就在 `live_probe` 里露过:`order_icon=0.977` 在一整帧上都
         能匹配 —— **那个模板几乎匹配任何东西**。
      2. 改成按比例裁"底部中间"后仍不对:实测裁块**偏右 25px**,把图标切掉了;
         而且**模板是在放大卡上采的(33x33),盘面上的图标只有 ~25x22**,
         尺度对不上,`matchTemplate` 自然乱给分。
      → 现在:①结构化地找"底部三个深色小牌子的中间那个" ②两边都归一化到
      32x32 再比。认错只会导致"少打一次"或"多拖一次";
      `min_score` 以下返回 None(不知道就别拖)。
    """
    if templates is None or not hasattr(frame, "shape"):
        return None
    crop = _type_icon_crop(frame, unit, debug=debug)
    if crop is None:
        return None
    bank = _icon_bank(templates)
    if not bank:
        return None
    got = _norm_icon(crop)
    best, best_s = None, 0.0
    for name, tpl in bank.items():
        try:
            res = cv2.matchTemplate(got, tpl, cv2.TM_CCOEFF_NORMED)
            s = float(res.max())
        except Exception:
            continue
        if s > best_s:
            best_s, best = s, name
    if debug:
        scores = []
        for name, tpl in bank.items():
            try:
                scores.append((name, float(cv2.matchTemplate(
                    got, tpl, cv2.TM_CCOEFF_NORMED).max())))
            except Exception:
                pass
        scores.sort(key=lambda kv: -kv[1])
        print("      类型打分 " + ", ".join(f"{n}={s:.2f}" for n, s in scores[:4]))
    return best if best_s >= min_score else None


def read_board(frame, debug=False, templates=None):
    """
    一次读完:units / our / enemy / 双方总部。

    templates: ui_templates 模板字典(含 *_icon)。给了就顺带认每张卡的**类型**
    (攻击规则需要);不给则 type 为 None —— 这时攻击逻辑会拒绝拖拽(安全)。

    ⚠️ **`find_units` 目前在"蓝图"棋盘上会把地形装饰也当成卡**
    (实测一条线上数出 10 张,而肉眼只有 1~2 张)。所以本函数的输出
    **现在不可用于"数数量"** —— 卡数请用 `count_row`/`battlefield_snapshot`
    (它们按行带统计,已避开这个问题)。逐张定位仍在修(见 PROJECT_STATE §8)。
    """
    units = find_units(frame, debug=debug)
    if templates:
        for u in units:
            u["type"] = classify_unit_type(frame, u, templates)
    return {
        "units": units,
        "our": [u for u in units if u["side"] == "our"],
        "enemy": [u for u in units if u["side"] == "enemy"],
        "hq_enemy": find_hq(frame, "enemy", units),
        "hq_our": find_hq(frame, "our", units),
    }


# ===========================================================================
# ★★ 第二代战场读取(2026-09-11 中午,用真实帧重新标定)
# ===========================================================================
# 为什么推倒重来(实测数据,见 shots/board_samples/):
#
# 1. **战场上只有 3 个卡行,不是 4 条线。**
#    多帧纵向剖面显示卡行中心稳定落在 y≈175 / 350 / 525(间距 175),
#    逻辑上的"双方前线"在画面里是**中间那一行**(争夺线,只有一方占)。
#    而旧代码有 OUR_SUPPORT/OUR_FRONT/ENEMY_FRONT/ENEMY_SUPPORT 四条硬编码带,
#    既数不对也不存在。
#
# 2. **行带位置会随对局漂移。** 实测两帧:一帧 135/295/435,另一帧 175/350/525。
#    所以**任何写死的 y 常数都会错** —— 必须每次从画面里现找行。
#
# 3. **旧的 `_card_mask`(自适应局部对比)在这张棋盘上会把桌面判成卡面**
#    —— 实机日志 `我支援 8`(上限只有 4)就是这么来的。
#    实测:卡面 V=140~225 且低饱和,桌面 V=20~90(深青底图),
#    **绝对亮度阈值在这张棋盘上是干净的**;旧判据的"局部最暗参照"在
#    大片暗底上会把整片都判成"比参照亮 28"。改用绝对阈值 + 形态学。
#
# 4. **卡面解剖(实测)**:左上角 = 费用;底部 = `攻击力 [类型图标] 防御力`;
#    总部(HQ)卡在**底部中央有一个大号血量数字**(实测字号 h≈27~33),
#    而单位卡底部的攻防数字明显更小(h≈19~21)—— 这是认总部的可靠判据。

CARD_V_MIN = 120          # 卡面的最低亮度(V):实测卡面 140~225,桌面 20~90
CARD_S_MAX = 150          # 卡面的最高饱和度:卡面偏灰白,桌面偏青绿
FIELD_X0, FIELD_X1 = 240, 1010    # 战场横向范围(避开两侧 HUD 与装饰)
FIELD_Y0, FIELD_Y1 = 80, FIELD_TOP_MAX   # 战场纵向范围(下方是手牌)
CARD_W_MIN, CARD_W_MAX = 62, 200
CARD_H_MIN, CARD_H_MAX = 80, 210
CARD_FILL_MIN = 0.45      # 卡面像素占包围盒的比例
MERGE_SPLIT_RATIO = 1.45  # 宽度超过"单卡宽 x 这个比例"就拆(两张卡粘一起了)
# 完整卡的高度实测 142~150px。★ 但**不能拿高度当完整性判据**:
# 卡底部那条攻/防条是深色的,有些卡的美术图也偏暗,于是"亮部掩码"切出来的框
# 高度会在 110~150 之间浮动(实测同一行里就有 115 和 147 两种)。
# 只用它**丢掉明显是碎片的框**(实测碎框 83~95),不要用它判断"完整不完整"。
# ★ 真正稳定的锚点是**左上角**:实测卡的上边框就在检测框顶 dy=+1 处
# (边缘强度 63.8),所以 (x, y) 就是卡的左上角 —— 取"左上角费用徽章"只用它。
CARD_H_MIN_COMPLETE = 96
# ★★★ A/B 开关(2026-09-13,第八个会话):`read_field` 里"总部判定"的 OCR 兜底怎么跑。
#   · `"auto"`(默认,新):**先只做便宜的盾牌判据**(0.085s/张);
#     **有费用徽章的卡 = 单位卡,一律不 OCR**;只有"没徽章 + 盾牌也没读出来"的卡
#     (也就是"可能的总部")才花 0.33s 的 OCR 兜底。
#   · `"per_card"`(旧行为,留作 A/B):盾牌读不出就**每张卡**都 OCR ——
#     实测一次 `read_field` 因此要 2.77s(其中 OCR 1.6s),
#     而攻击阶段每发攻击要读两次、一个回合读好几次。
#   · `"off"`:完全不跑 OCR 兜底(只剩盾牌判据)—— 用来量"上限能多快"。
READ_FIELD_OCR = "auto"
# ★★ 拆粘连用的两个阈值(见 `_split_blob`):超过它就一定不止一张卡。
#   实测单卡包围盒宽 99~157 / 高 125~167;横着粘 269~272、竖着粘 322(`0912_204135`)。
CARD_SPLIT_W = 175        # 横向:沿用原来那个实测值
CARD_SPLIT_H = 200        # 纵向:2026-09-12 新增(木桌上"总部 + 下面的单位"会连成 322)
# ★★ "真实的腰部"阈值(见 `_split_blob._cuts`):一刀两侧的剖面最低值必须低于
#    "该块剖面中位数 × 这个比例",否则认为**卡里没有缝**,不切也不发框。
#    实测空档:真缝 0.04~0.57 / 假缝 0.62~1.01 -> 取 0.60。
WAIST_MAX = 0.60
# ★★★ A/B 开关:`True` = 2026-09-12 的新行为(粗筛 -> **横竖都拆**(且要求真缝)
#     -> 再按**单卡**查实心度);`False` = 老行为(先按实心度筛 -> 只横着拆)。
#     留开关是为了能一句话对比两边,以及万一新行为在别的棋盘上翻车能立刻退回去
#     (§7 第 59/67 条的纪律)。
SPLIT_2D = True
# ★★ 把"亮部美术区"扩成"整张卡"。
#   实测踩坑:亮度掩码只框住了卡中间的**美术图**(亮),而卡的顶部(费用条)
#   和底部(攻/防条)是深色的,于是检测框比真卡**上下各少约 20px**。
#   后果很严重:所有"按相对位置取卡的一小块"的判据(左上角费用徽章、
#   底部攻防数字、拖拽落点)全都会取偏 —— 这正是 §10 里"按比例取左上角
#   取到了卡面美术"那个坑的**根本原因**(当时以为是框偏下,其实是框只有美术区)。
#   做法:从美术区边界往外扫,找第一条"横贯整卡宽度"的强边缘,就是卡的外框。
SNAP_MAX_UP = 46          # 往上最多找多少像素
SNAP_MAX_DOWN = 46
SNAP_MAX_SIDE = 26
SNAP_EDGE_MIN = 16.0      # 边缘强度阈值(灰度梯度的行/列均值)


def _snap_card_box(gray, x, y, w, h, debug=False):
    """
    把"亮部美术区"的框往外扩成**整张卡**的框。

    从美术区边界往外扫,取**第一条足够强的、横贯整卡宽度的边缘**:
      上边:行 y-1, y-2, ... 的 |gray[r]-gray[r-1]| 在 [x, x+w] 上的均值
      下边/左边/右边同理。
    这样卡的外框(深色描边)会被抓到,而卡内部的线条因为"从外往里扫、
    遇到的第一个强边缘"而不会被误取。
    """
    fh, fw = gray.shape[:2]
    xs0, xs1 = max(0, x), min(fw, x + w)
    if xs1 - xs0 < 20:
        return x, y, w, h
    band = gray[:, xs0:xs1].astype(np.int16)

    top = y
    for r in range(y - 1, max(0, y - SNAP_MAX_UP) - 1, -1):
        if r < 1:
            break
        g = float(np.abs(band[r] - band[r - 1]).mean())
        if g > SNAP_EDGE_MIN:
            top = r
            break

    bottom = y + h
    for r in range(y + h + 1, min(fh - 1, y + h + SNAP_MAX_DOWN) + 1):
        if r + 1 >= fh:
            break
        g = float(np.abs(band[r + 1] - band[r]).mean())
        if g > SNAP_EDGE_MIN:
            bottom = r
            break

    # 竖直方向:用卡框的 y 范围找左右边界
    ys0, ys1 = max(0, top), min(fh, bottom)
    if ys1 - ys0 < 20:
        return x, top, w, bottom - top
    hband = gray[ys0:ys1, :].astype(np.int16)

    left = x
    for c in range(x - 1, max(0, x - SNAP_MAX_SIDE) - 1, -1):
        if c < 1:
            break
        g = float(np.abs(hband[:, c] - hband[:, c - 1]).mean())
        if g > SNAP_EDGE_MIN:
            left = c
            break

    right = x + w
    for c in range(x + w + 1, min(fw - 1, x + w + SNAP_MAX_SIDE) + 1):
        if c + 1 >= fw:
            break
        g = float(np.abs(hband[:, c + 1] - hband[:, c]).mean())
        if g > SNAP_EDGE_MIN:
            right = c
            break

    nx, ny = left, top
    nw, nh = max(1, right - left), max(1, bottom - top)
    if debug:
        print(f"      snap ({x},{y},{w},{h}) -> ({nx},{ny},{nw},{nh})")
    return nx, ny, nw, nh


def card_boxes(frame, debug=False, snap=False):
    """
    找出战场上所有的**卡矩形**(单位 + 总部),不区分阵营。

    判据:亮(V>120)+ 低饱和(S<150)+ 尺寸像卡 + 够"实心"。
    粘连处理:相邻两张卡有时会被形态学闭运算粘成一条宽块(实测出现 269px、
    272px 宽,而单卡只有 ~135px),这时按宽度比例拆成两张。

    ★★ 关于"检测框是不是整张卡"(这里踩过一个大坑):
      我一度以为亮部掩码只框住了卡中间的美术图、上下各少 20px,于是加了一套
      "往外找卡外框"的 snap。**实测证明那是错的**:量卡周围横向边缘强度,
      卡的上边框出现在检测框顶 dy=+1(强度 63.8)、下边框出现在框底 dy=0
      (强度 58.1)—— **检测框本来就和真卡的上下边框对齐**。加了 snap 反而
      把框撑成 177/203px,更糟。
      真正的问题是**有些框是"不完整的卡"**(被手牌/别的卡挡住,实测高度只有
      83~125px),它们才是"按相对位置取左上角会取偏"的元凶。
      所以正确做法是 `snap=False`(默认) + **按高度把这些不完整的框筛掉**。

    CARD_H_MIN_COMPLETE 以下的一律丢弃:宁可漏一张,也不要拿一个残缺框去
    推算"卡内部的相对位置"。

    返回 [{'x','y','w','h','cx','cy','area'}],按 (y, x) 排序。
    """
    if frame is None or not hasattr(frame, "shape"):
        return []
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    V, S = hsv[:, :, 2], hsv[:, :, 1]
    mask = ((V > CARD_V_MIN) & (S < CARD_S_MAX)).astype(np.uint8) * 255
    mask[:FIELD_Y0, :] = 0
    mask[FIELD_Y1:, :] = 0
    mask[:, :FIELD_X0] = 0
    mask[:, FIELD_X1:] = 0
    # 开运算去掉桌面上的细亮装饰线(卡是大块实心,细线会被抹掉)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    # 闭运算把卡面内部的暗色美术(人脸/坦克)填平,免得一张卡被切成几块
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((17, 17), np.uint8))

    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)

    # ★★★ 2026-09-12(第七个会话)"粘连"这条链重排 —— 两个真实故障都是**结构**问题,
    #     不是颜色阈值问题(量过:卡面 S p90=123 / 桌面 S p50=115,**分布是重叠的**,
    #     所以"调 S_MAX 把桌面滤掉"这条路走不通)。实测的两个故障:
    #       ① **竖着粘**:木桌 `0912_204135`,敌方总部 + 下面那辆坦克连成
    #          `134x322` 一个块 -> 被"高 ≤210"整块丢掉,**两张卡一起消失**
    #          (那一局于是 `find_enemy_hq` 返回 None、行结构也塌了);
    #       ② **横着粘之后被实心度拒掉**:蓝图 `0912_192728` 的 `263x146`
    #          实心度 0.44 < 0.45 -> 在**拆粘连之前**就被丢掉;
    #          而拆粘连的代码本来就在那条过滤**后面**。
    #     ⇒ 改成三步:**粗筛(尺寸放宽到 3 倍,先不看实心度)-> 拆(横向 + 纵向)
    #       -> 对拆完的**每一块**单独做单卡检查(尺寸 + 实心度)**。
    #       这样"实心度"是在真正的单卡上量的,才有意义。
    coarse = []
    for i in range(1, n):
        x, y, w, h, area = (int(stats[i, 0]), int(stats[i, 1]), int(stats[i, 2]),
                            int(stats[i, 3]), int(stats[i, 4]))
        if not (CARD_W_MIN <= w <= CARD_W_MAX * 3):
            continue
        if not (CARD_H_MIN <= h <= CARD_H_MAX * 3):
            continue
        coarse.append([x, y, w, h])

    blobs = []
    if SPLIT_2D:
        for x, y, w, h in coarse:
            for px, py, pw, ph in _split_blob(mask, x, y, w, h, debug=debug):
                if not (CARD_W_MIN <= pw <= CARD_W_MAX):
                    continue
                if not (CARD_H_MIN <= ph <= CARD_H_MAX):
                    continue
                sub = mask[py:py + ph, px:px + pw] > 0
                if sub.mean() < CARD_FILL_MIN:
                    continue
                blobs.append([px, py, pw, ph])
    else:
        # ---- A/B 开关的另一侧:**2026-09-12 之前的老行为**(只横着拆;实心度先筛)----
        for x, y, w, h in coarse:
            if not (CARD_W_MIN <= w <= CARD_W_MAX * 2):
                continue
            if not (CARD_H_MIN <= h <= CARD_H_MAX):
                continue
            if x is not None:
                sub0 = mask[y:y + h, x:x + w] > 0
                if sub0.mean() < CARD_FILL_MIN:
                    continue
            k = 1
            while w > 175 * k:
                k += 1
            if k <= 1:
                blobs.append([x, y, w, h])
                continue
            sub = mask[y:y + h, x:x + w] > 0
            col = sub.mean(axis=0)
            cuts = []
            for j in range(1, k):
                lo = int(w * j / k - w / (2 * k))
                hi = int(w * j / k + w / (2 * k))
                seg = col[max(0, lo):max(1, hi)]
                if len(seg):
                    cuts.append(x + max(0, lo) + int(np.argmin(seg)))
            edges = [x] + sorted(cuts) + [x + w]
            if len(edges) != k + 1:
                blobs.append([x, y, w, h])
                continue
            for a, b in zip(edges[:-1], edges[1:]):
                if b - a >= CARD_W_MIN:
                    blobs.append([a, y, b - a, h])

    out = [{"x": x, "y": y, "w": w, "h": h} for x, y, w, h in blobs]

    for b in out:
        if snap:
            # 默认关闭 —— 见上面 card_boxes 的说明:实测检测框已经和真卡对齐,
            # 往外找边缘只会把框撑大。留着这个开关是为了以后换棋盘时能再验证。
            g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            nx, ny, nw, nh = _snap_card_box(g, b["x"], b["y"], b["w"], b["h"],
                                            debug=debug)
            b["x"], b["y"], b["w"], b["h"] = nx, ny, nw, nh
        b["cx"] = b["x"] + b["w"] // 2
        b["cy"] = b["y"] + b["h"] // 2
        b["area"] = b["w"] * b["h"]
    if not snap:
        # ★ 丢掉"不完整的卡"(被手牌/别的卡挡住),它们的框不代表整张卡,
        #   拿它推算卡内部的相对位置(比如左上角费用徽章)必然取偏。
        before = len(out)
        out = [b for b in out if b["h"] >= CARD_H_MIN_COMPLETE]
        if debug and len(out) != before:
            print(f"      (丢掉 {before - len(out)} 个不完整的框:"
                  f"高 < {CARD_H_MIN_COMPLETE})")
    out.sort(key=lambda b: (b["y"], b["x"]))
    if debug:
        for b in out:
            print(f"    box x{b['x']:4d}-{b['x'] + b['w']:4d} (w{b['w']:3d}) "
                  f"y{b['y']:4d}-{b['y'] + b['h']:4d} (h{b['h']:3d})")
    return out


def _split_blob(mask, x, y, w, h, debug=False):
    """
    把一个"粘在一起的块"按**列/行亮占比的谷底**切成单卡大小的若干块(横 + 纵都切)。

    ★ 阈值来历(实测,沿用原来的横向值):
      · 单张卡的包围盒宽 **99~157px**,两张横着粘是 269/272 -> 横向阈值 **175**;
      · 单张卡的高 **125~167px**(木桌上 HQ 148 / 单位 146;蓝图 125~148),
        两张竖着粘是 **322**(`0912_204135`)-> 纵向阈值 **200**。
    ★ 切法:在第 j 份的中心附近找"亮占比最低"的那一行/列当缝(和原来横向切法一致)。
      ★ 切完**不在这里**做尺寸/实心度检查 —— 那些检查要落在**真正的单卡**上才有意义
        (见 `card_boxes` 里那段说明)。
    """
    kx = 1
    while w > CARD_SPLIT_W * kx:
        kx += 1
    ky = 1
    while h > CARD_SPLIT_H * ky:
        ky += 1
    if kx == 1 and ky == 1:
        return [(x, y, w, h)]
    sub = mask[y:y + h, x:x + w] > 0

    def _cuts(k, length, prof, base):
        """返回 (切点列表, 是不是每一刀都落在**真实的腰部**上)。

        ★★★ 2026-09-12(第七个会话)加"腰部"这一条,起因是 A/B 里量出来的**过度切分**:
          只看"块够宽就切"时,`board_geom_test` 从 0 处可疑涨到 **9 处**
          (`卡间距 3/69/80/86/87`、`最后两行太近 77/78`)—— 也就是**一刀切在卡里面**了。
          把每一刀的"剖面最低占比 ÷ 剖面中位"打出来看,**分得很干净**:

              真缝(该切)  0.04 ~ 0.57      <- 竖着粘的总部+单位是 0.24
              假缝(不该切)0.62 ~ 1.01      <- 1.00 = 剖面根本没有凹陷

          ⇒ 取 `WAIST_MAX = 0.60` 落在空档里;**某一刀找不到真缝 -> 整块不切也不发框**
            (fail-closed:宁可不报这张卡,也不发一个"一刀切在卡里"的假框)。
        """
        if k <= 1:
            return [], True
        cuts, ok = [], True
        for j in range(1, k):
            lo = int(length * j / k - length / (2 * k))
            hi = int(length * j / k + length / (2 * k))
            seg = prof[max(0, lo):max(1, hi)]
            if not len(seg):
                return [], False
            i = int(np.argmin(seg))
            cuts.append(base + max(0, lo) + i)
            if float(seg[i]) > WAIST_MAX * max(1e-6, float(np.median(prof))):
                ok = False
        return sorted(cuts), ok

    cx, okx = _cuts(kx, w, sub.mean(axis=0), x)
    cy, oky = _cuts(ky, h, sub.mean(axis=1), y)
    if not (okx and oky):
        if debug:
            print(f"      (块 {w}x{h} 找不到真实腰部 -> 不切、不报框)")
        return []
    xs = [x] + cx + [x + w]
    ys = [y] + cy + [y + h]
    out = []
    for yy0, yy1 in zip(ys[:-1], ys[1:]):
        for xx0, xx1 in zip(xs[:-1], xs[1:]):
            if xx1 > xx0 and yy1 > yy0:
                out.append((xx0, yy0, xx1 - xx0, yy1 - yy0))
    if debug and (kx > 1 or ky > 1):
        print(f"      (拆粘连 {w}x{h} -> {kx}x{ky} = {len(out)} 块)")
    return out


def rows_from_boxes(boxes, min_gap=60, debug=False):
    """
    把卡矩形按 y 聚成"行"。

    为什么要聚类而不是用固定 y 带:实测行带位置会随对局漂移
    (一帧 135/295/435,另一帧 175/350/525),**写死的 y 常数一定会错**。
    聚类出来的行按 y 从小到大排,就是从上到下的四条线。

    返回 [{'cy','y0','y1','boxes':[...]}],按 cy 升序。
    """
    rows = []
    for b in sorted(boxes, key=lambda b: b["cy"]):
        hit = None
        for r in rows:
            # 和这一行已有卡的 y 中心够近就算同一行
            if abs(r["cy"] - b["cy"]) <= min_gap:
                hit = r
                break
        if hit is None:
            rows.append({"cy": float(b["cy"]), "y0": b["y"],
                         "y1": b["y"] + b["h"], "boxes": [b]})
        else:
            hit["boxes"].append(b)
            hit["cy"] = sum(x["cy"] for x in hit["boxes"]) / len(hit["boxes"])
            hit["y0"] = min(hit["y0"], b["y"])
            hit["y1"] = max(hit["y1"], b["y"] + b["h"])
    rows.sort(key=lambda r: r["cy"])
    for r in rows:
        r["boxes"].sort(key=lambda b: b["x"])
        r["n"] = len(r["boxes"])
    if debug:
        for i, r in enumerate(rows):
            print(f"    行{i} cy≈{r['cy']:.0f} y{r['y0']}-{r['y1']} "
                  f"{r['n']} 张 中心x={[b['cx'] for b in r['boxes']]}")
    return rows


# ---------------------------------------------------------------------------
# ★★ 两套锚点合并(2026-09-11 下午,离线实测后新增)
#
# 为什么必须合并:`card_boxes` 和"费用徽章"**各漏一半,而且是互补的**。
# 实测 9 帧 `shots/attack_probe`(见 `board_anchor_probe.py`):
#
#   帧 0911_131247(我方支援线 = 2 个单位 + 我方总部):
#     卡框  最下面一行 1 张 @x725      <- 只找到**总部**(总部没有费用徽章)
#     徽章  最下面一行 2 个 @x385/528  <- 只找到**两个单位**(它们的亮部掩码漏了)
#     -> 同一行真实是 3 张,任何单一一套锚点都数不对。
#
#   帧 0911_131214 / 131302 同样是"卡框 1 张 / 徽章 2 个"。
#
# 所以判据是:**卡框 ∪ 徽章**,同一张卡只记一次(按"徽章估出的卡框"和已有
# 卡框的中心距离去重)。总部天然由卡框提供,单位卡天然由徽章提供。
# ---------------------------------------------------------------------------
BADGE_MERGE_DX = 60      # 中心 x 差这么久以内 = 同一张卡(实测同一张 ~42px)
BADGE_MERGE_DY = 70      # 中心 y 差这么久以内 = 同一张卡(实测同一张 ~6px)


def badge_boxes(frame, rows=None, debug=False):
    """
    用**费用徽章**反推出"单位卡"的框(总部没有徽章,所以这里永远不含总部)。

    徽章 = 每张单位卡左上角的深色小方块 + 亮色数字。它**不会被相邻卡粘连吞掉**,
    实测比亮度掩码可靠(见 §12)。检测逻辑复用 `unit_state.find_cost_badges`。

    rows: 可选,`rows_from_boxes()` 的结果。**热路径上一定要传** ——
          `find_cost_badges` 的"行带补检"需要行信息,不传它就要自己再算一遍
          `card_boxes`(实测 13ms,不至于崩,但没必要付两次)。
    """
    try:
        from unit_state import find_cost_badges, unit_box_from_badge
    except Exception:
        return []
    out = []
    for b in find_cost_badges(frame, rows=rows, debug=debug):
        box = unit_box_from_badge(b)
        box = {"x": box["x"], "y": box["y"], "w": box["w"], "h": box["h"],
               "cx": box["cx"], "cy": box["cy"], "area": box["w"] * box["h"],
               "from": "badge", "state": b["state"], "badge": b}
        out.append(box)
    return out


def merge_boxes(primary, extra, dx=BADGE_MERGE_DX, dy=BADGE_MERGE_DY,
                debug=False):
    """
    把两套锚点并成一套:extra 里凡是"和 primary 里的某张已经是同一张卡"的丢掉。

    ★ 去重必须用**两个方向**都比:只用 x 会把上下两行的卡判成同一张,
      只用 y 会把同一行相邻的两张判成同一张。
    """
    merged = list(primary)
    added = 0
    for e in extra:
        dup = False
        for p in merged:
            if abs(p["cx"] - e["cx"]) <= dx and abs(p["cy"] - e["cy"]) <= dy:
                dup = True
                # ★★ 2026-09-13(第八个会话):合并时**给被合并的那张打个记号**
                #   `has_badge = True` —— 也就是"这张卡左上角有费用徽章",
                #   而**总部没有徽章**。`read_field` 用它来跳掉昂贵的 OCR 兜底
                #   (见那里"先便宜后昂贵"的说明):单位卡一律不用 OCR。
                #   ★ 为什么要在这里打:两套锚点都检到同一张卡时,合并后留下的
                #     是**卡框那条**(没有 `from` 字段),徽章的证据就丢了。
                p["has_badge"] = True
                p.setdefault("badge_state", e.get("state"))
                p.setdefault("badge", e.get("badge"))
                break
        if not dup:
            merged.append(e)
            added += 1
    if debug:
        print(f"    merge: 卡框 {len(primary)} + 徽章补检 {added} "
              f"= {len(merged)} 张")
    return merged


def _drop_badges_on_card_body(merged, debug=False):
    """
    把"落在**别的卡片下半部分**"的徽章锚点从并集里去掉(判据见
    `unit_state.badge_on_card_body`)。

    ★★★ 2026-09-15(实机 J9):这一步**必须在这里做**,不能在 `find_cost_badges`
      里做完就算 —— 那里能看到的只有**卡框锚点**,不够用。
      证据帧 `shots/scan_frames/0915_184240_scan.png`:假徽章 (771,217) 是敌方单位卡
      **底部的类型图标**,它反推出的卡 (768,213) 落进**前线行** -> `我前线 1`(其实
      空着),"上前线成没成"的张数判据被整歪(那一轮 7 次假 `没动成` 的成因之一);
      而那一帧卡框锚点**恰恰没检出**敌方那两张步兵卡 —— 是它们自己的真徽章补出了
      卡框。⇒ 只有并集里才同时有"假徽章"和"能把它关住的那个真卡框"。
    """
    try:
        from unit_state import STAT_GUARD, STAT_GUARD_H_MAX, badge_on_card_body
    except Exception:
        return merged
    if not STAT_GUARD:
        return merged
    boxes = [b for b in merged if int(b.get("h") or 0) <= STAT_GUARD_H_MAX]
    out = []
    for b in merged:
        if b.get("from") != "badge":
            out.append(b)          # 卡框锚点找到的卡不动(它自带卡框证据)
            continue
        others = [x for x in boxes if x is not b]
        if badge_on_card_body(b.get("badge") or b, others, debug=debug):
            continue
        out.append(b)
    return out


def merged_card_boxes(frame, debug=False, snap=False, rows=None):
    """
    ★ 推荐的"场上所有卡"读法:`card_boxes`(含总部)∪ `badge_boxes`(含被
    掩码漏掉的单位卡),按 (y, x) 排序。每一张都带 `from` 字段说明来源。

    ★★ 2026-09-11 晚:`rows` 只算一次,并且**传给** `badge_boxes` ——
       `unit_state.find_cost_badges` 的"行带补检"就是靠行信息才敢出手的
       (见 unit_state.find_cost_badges_band)。不传的话它自己会再算一遍
       `card_boxes`,不但白花时间,更要紧的是**两处用的行可能不一致**。
    """
    boxes = card_boxes(frame, debug=debug, snap=snap)
    if rows is None:
        rows = rows_from_boxes(boxes)
    extra = badge_boxes(frame, rows=rows, debug=debug)
    out = merge_boxes(boxes, extra, debug=debug)
    out = _drop_badges_on_card_body(out, debug=debug)
    out.sort(key=lambda b: (b["y"], b["x"]))
    return out


# ---------------------------------------------------------------------------
# ★★ 我方支援线上的**单位卡张数**(2026-09-12 新增;用户当场确认了规则)
#
# 为什么不能"数我方那一行有几张卡":
#   用户 2026-09-12 确认:**支援线最多 4 个【单位卡】,总部不占位** ——
#   而**总部卡就画在同一行里**。实测 `shots/board_samples/0911_122530_001.png`:
#   那一行是 `单位 / STALINGRAD(15血总部) / 单位 / 单位` 共 4 张。
#   所以"数这一行"**永远多算一个总部**:3 个单位时报 4、4 个单位时报 5。
#   ★ 文档里一直当成"读数抖动/判据坏了"的 `我支援 5`,真相很可能就是
#     **满线(4 个单位 + 总部)** —— 错的不是读数,是我们拿它当了"单位数"。
#   后果:_support_line_full() 完全不敢用场上读数,只能靠"本回合部署了几个"兜,
#   于是"上个回合就满了的线,这个回合还会白拖一次"。
#
# 正解:**数费用徽章**。
#   每张单位卡左上角**恰好一个**费用徽章,而**总部没有徽章**(它的左下角是大号
#   血量数字,实测总部卡上找不到徽章)。徽章同时是已知最可靠的定位器
#   (§12:卡框会粘连/漏卡,徽章是独立小方块,不会被粘走)。
#   所以"我方那一行的徽章数" = "我方支援线上的单位数",**天然把总部排除掉**。
#
# 安全约束(用户已确认上限就是 4,所以 >4 必然是判据坏了):
#   数出 >SUPPORT_LINE_MAX 个 -> 返回 None,调用方 fail-closed 退回保守判据。
#   绝不让一个虚高的读数把"线满了"写死 —— 那会让引擎整局不出牌(文档记过这个坑)。
# ---------------------------------------------------------------------------
SUPPORT_LINE_MAX = 4          # 用户确认:支援阵线最多 4 个单位卡(总部不占位)


# ---------------------------------------------------------------------------
# ★★★ 哪一行才配叫"我方支援线"(2026-09-12 实机抓到的真 bug)
#
# 现象(实机日志原文,一局里 9 次部署有 3 次):
#   `落点参考行: cy=350 side=our | 行结构[cy178/enemy n2; cy350/our n3]`
#   —— 我方支援线**没被检出**时,`read_field` 的规则"最后一行 = 我方"
#   就把**前线那一行**认成了我方,然后 `deploy_candidates` 把它的 cy 夹到
#   `DROP_Y_LIMIT[0]=400` -> 落点变成 400(第一局那个"落点 y 全是 400"的谜团)。
#
# 为什么不只是"落点难看":`side == "our"` 还被下游当成"自己人"的判据 ——
#   `attack._in_our_row()`(决定哪些卡能被拖出去当攻击者)、
#   `board.support_line_units()`(支援线单位数)。把敌人的行认成我方,
#   正是 §10 记的"**把敌方单位当成自己人拖**"那条最危险的错误的前一步。
#
# 判据:我方支援线**必须贴着我们的手牌**。KARDS 镜头固定,手牌永远在屏幕下方,
#   所以"我方那一行"的 cy 一定在下半场。实测 cy ∈ {435, 521, 524, 526, 538},
#   而前线/其他行 ∈ {286, 295, 320, 349, 350, 351, 354, 373, 380} —— 分得很开。
#   ★ 用"离手牌多远"来表达,而不是写死 425:`HAND_MIN_Y` 才是那个不变的锚。
#   ★ 拿不准就**返回 None**(fail-closed),让调用方退回兜底/不动作 ——
#     绝不硬认一行当自己人。
# ---------------------------------------------------------------------------
OUR_ROW_MIN_CY = HAND_MIN_Y - 180      # = 420;实测我方支援线最低见过 435


def pick_our_row(rows):
    """
    这些行里,哪一行是我方支援线。**拿不准返回 None**(fail-closed)。

    规则就一条:最后一行(最靠下)且 cy 在下半场。否则说明"我方那一行没检出来"。
    """
    if not rows:
        return None
    r = rows[-1]
    if float(r.get("cy") or 0) < OUR_ROW_MIN_CY:
        return None
    return r


def support_line_units(frame, rows=None, badges=None, debug=False):
    """
    我方支援阵线上的单位卡(**不含总部**),按 x 排序。

    返回 {"row": row|None, "units": [...], "n": int|None, "why": str}
      units[i] = {"badge","box","src","state"}   state: orange/grey/None
      **n = None 表示判据不可信**(读不到我方那一行 / 数出 >4)——
        调用方必须 fail-closed,不许把 None 当成 0 或 4。

    ★ 判据的来源是"徽章落在哪一行",不是"徽章的 y 落在哪个固定带":
      行带会随对局漂移(实测一局 135/295/435,另一局 175/350/525),
      所以这里用 `rows_from_boxes` 现找行,再把每个徽章按"它推出来的卡中心"
      归给最近的那一行 —— 和 `read_field` 的定阵营规则一致(最下面一行 = 我方)。
    """
    out = {"row": None, "units": [], "n": None, "why": ""}
    if frame is None or not hasattr(frame, "shape"):
        out["why"] = "没有帧"
        return out
    if rows is None:
        try:
            rows = rows_from_boxes(card_boxes(frame))
        except Exception as e:
            out["why"] = f"卡框/行聚类失败({type(e).__name__}: {e})"
            return out
    rows = list(rows or [])
    if not rows:
        out["why"] = "一行都没聚出来(卡框全空)"
        return out
    our = pick_our_row(rows)          # ★ 拿不准就 None(见 OUR_ROW_MIN_CY 的说明)
    if our is None:
        out["why"] = (f"最靠下那一行 cy≈{rows[-1].get('cy'):.0f} 在下半场以外"
                      f"(<{OUR_ROW_MIN_CY})-> **我方那一行没检出来**,不许硬认")
        return out
    out["row"] = our

    try:
        from unit_state import find_cost_badges, unit_box_from_badge, drag_from_point
    except Exception as e:
        out["why"] = f"徽章模块不可用({type(e).__name__}: {e})"
        return out
    if badges is None:
        try:
            badges = find_cost_badges(frame, rows=rows)
        except Exception as e:
            out["why"] = f"徽章检测出错({type(e).__name__}: {e})"
            return out

    for b in badges:
        box = unit_box_from_badge(b)
        # 这个徽章属于哪一行:按"徽章推出来的卡中心"离哪一行的 cy 最近
        owner = min(rows, key=lambda r: abs(r["cy"] - box["cy"]))
        if owner is not our:
            continue
        out["units"].append({"badge": b, "box": box,
                             "src": drag_from_point(b), "state": b.get("state")})
    out["units"].sort(key=lambda u: u["box"]["x"])
    n_badge = len(out["units"])

    # ★★ 再用"那一行有几张卡"给一个**下限**:一行里除总部之外都是单位,
    #   所以 (卡数 - 1) 是单位数的下限(卡框会漏卡/合并,所以它只是下限,不是估计值)。
    #   为什么要有这个下限 —— 两个方向的错误代价**不对称**:
    #     · **少数**一个单位 -> 引擎以为还没满 -> 多拖一张 -> 被拒 -> 白拖 2 秒,
    #       而这正是本项目最想消除的"乱拖打不出去的牌";
    #     · **多数**一个单位 -> 引擎以为满了 -> 少部署一个单位 -> 这一回合少出牌。
    #   取 max 是有意偏向"不要多拖"。实测干净帧两者完全一致
    #   (`0911_122530_001`:卡数 4 / 徽章 3 -> 都是 3 个单位),不一致只会出现在
    #   **鼠标停在画面上**的污染帧(实测 `0911_122530_004`:徽章被悬停面板挡掉读成 0,
    #   而那一行真实是 2 个单位 + 总部)。
    n_row = max(0, len(our["boxes"]) - 1)
    n = max(n_badge, n_row)

    if n > SUPPORT_LINE_MAX:
        # 用户已确认硬上限是 4 -> 超过就是判据坏了。**绝不让它变成"线满了"**:
        # 文档记过这个坑(卡数读成 10 -> 线永远满 -> 一整局一张牌都不出)。
        out["n"] = None
        out["why"] = (f"数出 {n} 个(徽章 {n_badge} / 行卡数-1 {n_row})> 上限 "
                      f"{SUPPORT_LINE_MAX} -> 判据不可信(fail-closed;很可能是把"
                      f"上一行或卡面美术数进来了)")
    else:
        out["n"] = n
        out["why"] = (f"我方那一行(cy≈{our['cy']:.0f})单位 {n} 个"
                      f"(徽章 {n_badge} / 行卡数 {len(our['boxes'])} 含总部)"
                      f" -> 不含总部")
    if debug:
        print(f"    支援线单位: n={out['n']} {out['why']} "
              f"x={[u['box']['cx'] for u in out['units']]}")
    return out


# ---------------------------------------------------------------------------
# 前线那一行(2026-09-12 新增,给"上前线"用)
#
# 为什么需要它:用户确认的顺序是"先能打相邻战线 -> 才能清掉前线 -> 才能上前线",
# 而"上前线"要把单位拖到**前线那一行的空槽位**上。
# ★ 落点 y **必须现算**:
#   · 前线有卡时 -> 取那一行的 cy;
#   · 前线**空着**时(最常见!)那一行根本不会出现在 `rows` 里 ——
#     这时用"最上一行与最下一行的**中点**":实测某帧 183/524 -> 353.5,
#     而同一帧前线那一行在 351,差 2.5px,够用。
#   · **绝不能写死 y**(旧代码的 `FRONT_LINE_DROP_Y=500` 就落在**我方支援线**上,
#     拖了等于原地放下 —— §12 实测记录里踩过)。
# ---------------------------------------------------------------------------
def front_row(field):
    """前线那一行(`side == 'frontline'`)。前线空着时**没有这一行**,返回 None。"""
    rows = (field or {}).get("rows") or []
    fr = [r for r in rows if r.get("side") == "frontline"]
    return fr[0] if fr else None


def front_line_cy(field):
    """前线那一行的 y 中心(行不存在就用最上/最下两行的中点);算不出返回 None。"""
    r = front_row(field)
    if r is not None:
        return float(r["cy"])
    cys = sorted(float(x["cy"]) for x in ((field or {}).get("rows") or []))
    if len(cys) >= 2:
        return (cys[0] + cys[-1]) / 2.0
    return None


def _ocr_big_number(frame, box, min_h=24.0):
    """
    卡面里有没有一个**大号独立数字** —— 总部(HQ)的血量。
    实测:总部卡底部中央的血量数字字号 h≈27~33,而单位卡底部的攻/防数字
    只有 h≈19~21,而且单位卡那里是 `数字 + 图标 + 数字` 三段。
    所以"一个够大的、纯数字的、高置信度的行"就是总部。
    """
    from hover_card_reader import _ocr

    x, y, w, h = box["x"], box["y"], box["w"], box["h"]
    crop = frame[max(0, y):y + h, max(0, x):x + w]
    if crop.size == 0:
        return None
    try:
        lines = _ocr(crop)
    except Exception:
        return None
    best = None
    for ln in lines:
        t = str(ln.get("text", "")).strip()
        if not t.isdigit():
            continue
        if float(ln.get("conf", 0)) < 0.5:
            continue
        if float(ln.get("h", 0)) < min_h:
            continue
        # 血量数字在卡的下半部
        if float(ln.get("y", 0)) < h * 0.45:
            continue
        if best is None or float(ln.get("h", 0)) > best[1]:
            best = (int(t), float(ln.get("h", 0)))
    return best      # (血量, 字号) 或 None


def read_field(frame, templates=None, debug=False):
    """
    一次读完战场:**自适应地形**版的单位/总部识别。

    返回:
      {
        'rows':       [{cy, y0, y1, boxes, side}]  从上到下,
        'our_support':[unit...],   # 最下面那一行(紧挨我们的手牌)
        'enemy_support':[unit...], # 最上面那一行
        'frontline': [unit...],    # 中间的行(争夺线)
        'our_units': [...], 'enemy_units': [...],
        'hq_our': unit|None, 'hq_enemy': unit|None,
      }

    ★★ 阵营怎么定(不再猜颜色、也不再按绝对 y 猜):
      KARDS 的镜头是固定的:**我们的手牌永远在屏幕下方**,
      所以"紧挨手牌的那一行"一定是**我方支援线**,最上面那一行是**敌方支援线**。
      中间的行是**前线**(争夺线,同一时刻只有一方占)。
      这个判据只用**行之间的相对顺序**,所以行带漂移不影响它。
      (旧的"中线以下就是我方""红占比分阵营"都已被实测否定,见 §10。)
    """
    # ★ 用合并锚点(卡框 ∪ 费用徽章):单用卡框会漏单位卡 —— 离线实测
    #   同一行真实 3 张时只报 1 张(见 merged_card_boxes 的说明)。
    #   卡框只算一次,行结构传给徽章补检(见 merged_card_boxes)。
    boxes_raw = card_boxes(frame, debug=debug)
    rows = rows_from_boxes(boxes_raw, debug=debug)
    boxes = merged_card_boxes(frame, debug=debug, rows=rows)
    rows = rows_from_boxes(boxes, debug=debug)
    out = {"rows": rows, "our_support": [], "enemy_support": [],
           "frontline": [], "our_units": [], "enemy_units": [],
           "hq_our": None, "hq_enemy": None}
    if not rows:
        return out

    n = len(rows)
    our_row = pick_our_row(rows)       # ★ 拿不准 -> None(见 OUR_ROW_MIN_CY 的说明)
    if n == 1:
        # ★ 只有一行时,"最上面=敌方、最下面=我方"这两条规则会同时命中同一行,
        #   于是同一行被当成"我方支援"又是"敌方支援"(实测 f005 就报出
        #   "我方支援 2 张 / 敌方支援 2 张",其实是同一行的同一批卡)。
        #   这时只能按"它离我们的手牌有多远"判断:上半场是敌方的,下半场是我方的。
        rows[0]["side"] = "our" if our_row is not None else "enemy"
    else:
        for i, r in enumerate(rows):
            if i == 0:
                r["side"] = "enemy"
            elif i == n - 1:
                # ★★ 2026-09-12:以前这里**无条件**写 "our" —— 于是"我方那一行
                #   没检出来"时,最后一行(实测是**前线那一行**,cy 286/350)
                #   会被认成我方。现在必须过 `pick_our_row` 那道闸。
                #   判不过就记成 frontline:既不冒认自己人,也不冤枉成敌方
                #   (它多半就是争夺中的前线)。
                r["side"] = "our" if our_row is not None else "frontline"
            else:
                r["side"] = "frontline"
    for i, r in enumerate(rows):
        r["units"] = []
        # ★ 只有最上面一行(敌方支援)和最下面一行(我方支援)可能放总部;
        #   中间的前线行不可能有总部,所以**不对它跑 OCR** ——
        #   单张 OCR 约 1.1 秒,少跑一行就少几秒。
        may_have_hq = (i == 0 or i == len(rows) - 1)
        # ★★★ 2026-09-13(第八个会话)**把这条链拆成"先便宜、后昂贵"两步**。
        #     用户这一轮的要求是"压缩识别时间"(对局太长、不够拟人),而我量出来的
        #     头号热点就在这里:一次 `read_field` **2.77s**,其中
        #       · 盾牌判据 `hq_hp.read`       **0.085s/张**(便宜,实测 8 张 0.68s)
        #       · OCR 兜底 `_ocr_big_number`  **0.33s/张**(贵)
        #     而旧写法对**每一张非总部卡**都跑 OCR 兜底(盾牌只长在总部卡上,
        #     所以单位卡必然全部落到 OCR)-> 一次 `read_field` 光这一项就 ~1.6s,
        #     而攻击阶段**每发攻击要读两次**、一个回合读好几次。
        #   ⇒ 改成:**先只做盾牌(便宜)**;只有当这一行**一张盾牌都没读出来**时,
        #     才动用 OCR 兜底(那正是它本来的用途 —— 盾牌读不出时找总部)。
        #     常规帧(盾牌读得出)因此**一次 OCR 都不跑**。
        shields = {}
        if may_have_hq:
            for bi, b in enumerate(r["boxes"]):
                got = hq_hp.read(frame, b)
                if got is not None:
                    shields[bi] = got["hp"]
        need_ocr = may_have_hq
        for bi, b in enumerate(r["boxes"]):
            u = dict(b)
            u["side"] = r["side"]
            u["row_idx"] = i
            # ★★ 2026-09-12:总部判定改成**盾牌优先、OCR 兜底**。
            #   为什么:① 盾牌(血量圆牌)只长在总部卡上,是**结构判据**,
            #   实测 45 帧 91/92 都能读出来,而旧路(逐卡 OCR 找 h>=24 的数字)
            #   在 20 张存帧里只有 3 张读得到 —— 于是 `is_hq` 常年是 False,
            #   `find_enemy_hq` 的"卡框兜底"跟着失效;
            #   ② 顺带**省掉每张卡一次 OCR**,`read_field` 快一大截。
            hp = shields.get(bi)
            # ★★★ 2026-09-13:**有费用徽章的卡一定是单位,不用 OCR**。
            #   盾牌只长在总部卡上,所以单位卡**必然**读不到盾牌 ——
            #   旧写法于是给**每一张**单位卡都跑一次 0.33s 的 OCR 兜底
            #   (一次 read_field 里 5 张 = 1.6s,而一个回合要读好几次)。
            #   改用"这张卡有没有徽章"来分流:有徽章 -> 单位,直接跳过;
            #   没徽章 -> 可能是总部,才值得花 OCR。
            has_badge = bool(b.get("from") == "badge" or b.get("has_badge"))
            if hp is None and need_ocr and (not has_badge
                                            or READ_FIELD_OCR == "per_card"):
                big = _ocr_big_number(frame, b)
                hp = big[0] if big else None
            u["is_hq"] = hp is not None
            u["hp"] = hp
            u["type"] = None
            r["units"].append(u)
        if debug:
            print(f"    行{i} side={r['side']} cy≈{r['cy']:.0f}: "
                  + ", ".join(f"x{u['cx']}{'/HQ' + str(u['hp']) if u['is_hq'] else ''}"
                              for u in r["units"]))

    # ★★★ 2026-09-12(第七个会话):**一行只该有一个总部** —— 判出多个时,用
    #     "单位卡左上角一定有**费用徽章**、总部**没有**"把单位摘掉。
    #
    # 为什么必须修(实机帧 + 用户给的正样本):
    #   带【守护】的那个步兵卡(`shots/live_probe.png` x643)底部的
    #   `2 | 步兵图标 | 2` 三个牌子被 `hq_hp.read` 读成了"盾牌 + 血量 22",
    #   于是它 `is_hq=True` —— 和真总部(TRUK)一起凑成"一行两个总部"。
    #   实测频率:57 帧 / 142 行里 **4 行**出现(2.8%),其中两行就是这个守护步兵卡。
    # ★ 这条 FP 的后果不只是"多一个总部":
    #   · `attack._pick_target` 会把判定成总部的卡从"可打的敌方支援线单位"里
    #     **排除**(`not u.get("is_hq")`)-> **该打的那个守护单位永远选不中**;
    #   · `find_enemy_hq` 的"卡框自带 is_hq"那条兜底还可能把**单位卡**当成总部去打。
    # ★ 修法是**只在异常时**才动手(一行有 ≥2 个 is_hq),所以对正常帧是**零改动**;
    #   而这一层判据本身是结构性的(总部没有费用徽章),不是调阈值。
    for r in rows:
        hqs = [u for u in r.get("units", []) if u.get("is_hq")]
        if len(hqs) < 2:
            continue
        try:
            badges = badge_boxes(frame, rows=rows)      # 只在这条罕见的路上算
        except Exception:
            badges = []
        def _has_badge(u):
            return any(abs(b["cx"] - u["cx"]) < BADGE_MERGE_DX
                       and abs(b["cy"] - u["cy"]) < BADGE_MERGE_DY
                       for b in badges)
        no_badge = [u for u in hqs if not _has_badge(u)]
        keeper = (no_badge or hqs)[0]        # 没徽章的那个才是总部;都拿不准就留第一个
        for u in hqs:
            if u is keeper:
                continue
            u["is_hq"] = False
            u["hp"] = None
            u["is_hq_cleared"] = True        # 诊断:这一张是被这条规则摘掉的
        if debug:
            print(f"    ★ 一行 {len(hqs)} 个总部 -> 只留 x{keeper['cx']}"
                  f"(其余 {[u['cx'] for u in hqs if u is not keeper]} 被当成单位)")

    by_side = {}
    for r in rows:
        by_side.setdefault(r["side"], []).extend(r["units"])
    out["enemy_support"] = by_side.get("enemy", [])
    out["our_support"] = by_side.get("our", [])
    out["frontline"] = by_side.get("frontline", [])
    # ★★ 我方单位**只取我方那一行**,绝不把前线那一行算进来。
    #   前线的归属是"争夺"的:如果敌方控制前线,那一行全是敌方的卡 ——
    #   把它们当成"我方单位"去拖,等于拖敌人的单位,是最危险的错误。
    #   在能判出前线归属之前(见 敌方/我方 标签检测),前线一律不当自己人。
    out["our_units"] = out["our_support"]
    out["enemy_units"] = out["enemy_support"]
    for u in out["enemy_support"]:
        if u["is_hq"]:
            out["hq_enemy"] = u
            break
    for u in out["our_support"]:
        if u["is_hq"]:
            out["hq_our"] = u
            break

    if templates:
        for u in out["our_units"] + out["enemy_units"]:
            u["type"] = classify_unit_type(frame, u, templates)
    return out


def find_enemy_hq(frame, field=None, templates=None):
    """
    找敌方总部(攻击的目标),并**顺带读它的血量**。

    ★★★ 2026-09-12 第六个会话重写(用户提出"打总部还不完善"):
      旧版只有一条路 —— 对敌方那一行**整行 OCR**,找 "h>=24 的纯数字"。
      实测它**时好时坏**:20 张存帧里只有 3 张读得到;而且**单个数字**(7/8/2)
      在这个分辨率下 RapidOCR 一个都读不出来(裁出来放大 3x/5x、加白边都试过)。
      而 `is_hq` 用的是同一个 OCR,所以"卡框兜底"同样失效 ->
      站在前线的单位**一个目标都挑不到** -> 整回合 0 次攻击。

      新顺序(**便宜且可靠的在前面**):
        ① **盾牌**(`hq_hp.read`,纯图像处理,不花 OCR 时间):
           **血量盾牌只长在总部卡上**(单位卡底部是"攻|类型|防"三个小牌子),
           所以"敌方那一行里哪张卡读得出盾牌数字"本身就是**总部的判据**;
        ② 整行 OCR 的数字(老路)—— 拿它定位"包含这个数字的卡框";
        ③ 卡名 OCR(总部卡是盘面上**唯一印名字**的卡);
        ④ 卡框自带的 `is_hq`。
      血量:**盾牌优先**,读不到才用 ② 的数字。返回的目标点取**盾牌中心**
      (在卡的下半部,"拖到它上面"就是打到总部),没有盾牌就用卡中心。

    返回 dict(x,y,w,h,cx,cy,hp,state,from,is_hq,...) 或 None。
    """
    if field is None:
        field = read_field(frame, templates=templates)
    rows = field.get("rows") or []
    if not rows:
        return None
    row = rows[0]                      # 最上面那一行 = 敌方支援线
    units = list(row.get("units") or [])

    def _ret(card, hp, state, source, shield_box=None):
        box, sbox = hq_hp.find_shield(frame, card)
        if sbox is not None:
            sx, sy, sw, sh = sbox
            cx, cy = sx + sw / 2.0, sy + sh / 2.0
        else:
            cx, cy = card["cx"], card["cy"]
        return {"x": int(card["x"]), "y": int(card["y"]),
                "w": int(card["w"]), "h": int(card["h"]),
                "cx": int(cx), "cy": int(cy), "side": "enemy", "is_hq": True,
                "hp": hp, "state": state, "row_idx": 0, "type": None,
                # ★ 盾牌框(整帧坐标)—— 攻击之后复核血量时**直接照这个框读**,
                #   不用重新找总部(那时画面上正放伤害动画,盾牌常被盖住)。
                "shield_box": tuple(sbox) if sbox is not None else None,
                "from": source}

    # ---- ① 盾牌:直接认总部(最可靠,而且不用 OCR)----
    for u in sorted(units, key=lambda x: x["x"]):
        got = hq_hp.read(frame, u)
        if got is not None:
            return _ret(u, got["hp"], got.get("state"), "shield",
                        shield_box=got.get("shield_box"))

    # ---- ② / ③ 整行 OCR:先是数字,再是卡名 ----
    y0 = max(0, int(row["y0"]) - 14)
    y1 = min(frame.shape[0], int(row["y1"]) + 14)
    band = frame[y0:y1, FIELD_X0:FIELD_X1]
    lines = []
    if band.size:
        from hover_card_reader import _ocr
        try:
            lines = _ocr(band)
        except Exception:
            lines = []

    def _card_at(abs_x):
        """哪张卡的横向范围包含这个绝对 x(留 10px 余量)。"""
        for u in units:
            if u["x"] - 10 <= abs_x <= u["x"] + u["w"] + 10:
                return u
        return None

    def _synth_card(abs_x, kind):
        """
        OCR 的文字**对不上任何卡框**时的兜底:按行的 y 带 + 标准卡宽现造一个卡框。

        ★ 为什么需要:实测 `0912_162750` 那一帧,敌方那一行的**卡框整体偏了 ~70px**
          (屏幕上明明有 4 张,`card_boxes` 给的 3 个框都不在卡上),
          于是"整行 OCR 读到的数字/卡名"谁都对不上 -> `find_enemy_hq` 返回 None。
          同一个坑在 §12 清单第 1 条里记过(卡框会漏卡/粘连)。
          OCR 那两行文字的**位置**是准的(它是全帧扫描出来的),用它反推卡的位置
          比"什么都不返回"强;日志里会带 `_synth` 后缀,能一眼看出走的是兜底。
        """
        ry0 = int(row["y0"])
        ry1 = int(row["y1"])
        w = 132                                   # 实测卡宽
        h = max(60, ry1 - ry0)
        x = int(abs_x - w / 2) if kind == "digit" else int(abs_x - 8)
        return {"x": max(0, x), "y": max(0, ry0), "w": w, "h": h,
                "cx": max(0, x) + w // 2, "cy": max(0, ry0) + h // 2}

    best = None
    for ln in lines:
        t = str(ln.get("text", "")).strip()
        if not t.isdigit() or len(t) > 2:
            continue
        if float(ln.get("conf", 0)) < 0.5:
            continue
        h = float(ln.get("h", 0))
        if h < 24:                     # 单位卡的攻/防数字只有 ~20
            continue
        if best is None or h > best[1]:
            best = (int(t), h, ln)
    if best is not None:
        hp_ocr, _h, ln = best
        cx = FIELD_X0 + float(ln.get("x", 0)) + float(ln.get("w", 0)) / 2
        card = _card_at(cx)
        if card is None:
            card = _synth_card(cx, "digit")
            return _ret(card, hp_ocr, None, "row_ocr_synth")
        return _ret(card, hp_ocr, None, "row_ocr")

    for ln in lines:
        t = str(ln.get("text", "")).strip()
        if len(t) < 3 or t.isdigit():
            continue
        if float(ln.get("conf", 0)) < 0.4:
            continue
        tx_left = FIELD_X0 + float(ln.get("x", 0))
        tcx = tx_left + float(ln.get("w", 0)) / 2
        card = _card_at(tcx)
        if card is None:
            card = _synth_card(tx_left, "name")
            return _ret(card, None, None, "row_name_ocr_synth")
        return _ret(card, None, None, "row_name_ocr")

    for u in units:
        if u.get("is_hq"):
            return _ret(u, u.get("hp"), None, "is_hq_flag")
    return None


def read_hq_hp(frame, hq_unit=None, min_h=24.0):
    """
    重读敌方总部的血量(用于"这次攻击到底打中没有"的**语义判据**)。

    ★★★ 2026-09-12(第六个会话)改:优先用**已知的盾牌框**读,而不是重新找总部。
      实机第一发就是:出手前读到 `血量 18`,出手后 `被拒绝(血量读不到)` ——
      因为攻击落地那一刻画面上正放**伤害动画/飘字**,`find_enemy_hq` 那一帧找不到盾牌。
      而"总部卡这一回合不会动"是已知的,`hq_unit["shield_box"]` 里就有它的位置,
      照那个框读**又快又稳**(`hq_hp.read_box`)。框读不出来才退回"重新找总部"。

    ★ 顺带把整套盾牌读取的注释留在下面那句上(旧实现的历史):
      旧版是"用一个 60x60 的合成框 OCR",实测**永远返回 None**,
      于是"打中了没有"会退化回画面差异那条不可靠的路。
    """
    if hq_unit:
        sbox = hq_unit.get("shield_box")
        if sbox:
            got = hq_hp.read_box(frame, sbox)
            if got is not None:
                return got["hp"]
    hq = find_enemy_hq(frame, field=None)
    return hq.get("hp") if hq else None


def dump(hwnd=None, out_path=None):
    """截一帧 -> 检测 -> 存标注图 + 打印。只读,不动游戏。"""
    from win import capture_client_bgr, find_by_process, set_dpi_aware

    if hwnd is None:
        set_dpi_aware()
        wins = find_by_process("kards")
        if not wins:
            print("找不到 kards 窗口")
            return None
        hwnd = wins[0]["hwnd"]
    frame = capture_client_bgr(hwnd)
    if frame is None:
        print("截图失败")
        return None
    b = read_board(frame, debug=True)
    print(f"\n我方 {len(b['our'])} 个: "
          + ", ".join(f"x{u['cx']}@y{u['cy']}" for u in b["our"]))
    print(f"敌方 {len(b['enemy'])} 个: "
          + ", ".join(f"x{u['cx']}@y{u['cy']}" for u in b["enemy"]))
    for tag, hq in (("敌方总部", b["hq_enemy"]), ("我方总部", b["hq_our"])):
        if hq:
            print(f"{tag}: x{hq['cx']} y{hq['cy']} ({hq['w']}x{hq['h']})")
    out_path = out_path or os.path.join(ROOT, "shots", "board_annotated.png")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    cv2.imwrite(out_path, annotate(frame, b["units"], b["hq_enemy"],
                                   b["hq_our"]))
    print(f"标注图: {out_path}")
    return b


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="战场只读探测(不点任何东西)")
    ap.add_argument("--out", default=None, help="标注图输出路径")
    ap.add_argument("--frame", default=None, help="改用本地图片离线测试")
    args = ap.parse_args()
    if args.frame:
        img = cv2.imread(args.frame)
        if img is None:
            print(f"读不到 {args.frame}")
            raise SystemExit(1)
        b = read_board(img, debug=True)
        out = args.out or os.path.join(ROOT, "shots", "board_annotated.png")
        cv2.imwrite(out, annotate(img, b["units"], b["hq_enemy"], b["hq_our"]))
        print(f"\n我方 {len(b['our'])} 张, 敌方 {len(b['enemy'])} 张")
        print(f"标注图: {out}")
    else:
        dump(out_path=args.out)
