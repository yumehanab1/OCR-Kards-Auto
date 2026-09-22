"""
hq_hp_test.py - **离线真实帧回归**:总部血量盾牌读取(`src/hq_hp.py`)。

为什么要有它:
    "15 读成 16" 这个错**没有任何日志会暴露它** —— 读错和读对长得一模一样,
    而且它会让"打中了没有"这条判据撒谎(§7 第 46 条最忌讳的那类错)。
    所以把**人眼核对过的帧 + 期望值**钉死成用例;帧就在仓库里,不需要游戏。

★★ 样本放在 `shots/hq_hp/regress/`(**冻结目录**)—— 不要直接引用 `shots/attack_frames/`:
   那个目录是生产转储,`DUMP_MAX_FRAMES=40` 会**按修改时间把旧的删掉**
    (本项目真踩过:第一版用例引用的 `0912_162931` / `0912_165639` 被转储删了,
     测试报"文件缺失")。要用新帧当样本,先 `Copy-Item` 进 regress 并改名字。

★ 期望值是人眼从盾牌上读出来的(见 `shots/hq_hp/labels.json` 的历史),
  **不是**用检测器自己的输出当标准答案。
★ 每条用例都做**留一验证**:先把这一帧自己贡献的模板原型从库里拿掉
  (`hq_hp.bank(exclude=原始帧名)`),否则分数全是 1.00,那种"验证"什么也证明不了。

用法:  .venv\\Scripts\\python.exe dev\\hq_hp_test.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2  # noqa: E402

import board  # noqa: E402
import hq_hp  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "shots", "hq_hp", "regress")
problems = 0


def check(name, cond, extra=""):
    global problems
    print(f"  {'OK ' if cond else 'FAIL'} {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        problems += 1


# (regress 里的样本, 它来自哪一帧(留一排除用), 期望敌方总部血量, 期望颜色)
ENEMY_CASES = [
    ("enemy_7red.png", "0912_162931_attack", 7, "red"),    # TRUK 7 血(单数字,OCR 读不出)
    ("enemy_13red.png", "0912_170140_attack", 13, "red"),  # ★ 留一之后曾读成 18(3 的原型太薄)
    ("enemy_8red.png", "0912_170207_attack", 8, "red"),    # 单数字
    ("enemy_6red.png", "0912_170342_attack", 6, "red"),    # 单数字
    ("enemy_2red.png", "0912_170747_attack", 2, "red"),    # 单数字
    ("board_enemy20_our15.png", "0911_122530_001", 20, "white"),
    ("board2_enemy20_our15.png", "0911_122530_005", 20, "white"),
]
# (样本, 来源帧, 期望**我方**总部血量, 期望颜色)
OUR_CASES = [
    ("board_enemy20_our15.png", "0911_122530_001", 15, "red"),   # ★ "15 读成 16" 那次的主角
    ("board2_enemy20_our15.png", "0911_122530_005", 15, "red"),
]


def _hq_card(img, row, leavemeout=None):
    """这一行里带盾牌(能读出血量)的那张卡 —— 也就是总部。"""
    b = hq_hp.bank(exclude=leavemeout) if leavemeout else None
    for u in sorted(row.get("units") or [], key=lambda x: x["x"]):
        if hq_hp.read(img, u, bank_=b) is not None:
            return u
    return None


def _run(cases, row_index, title):
    print()
    print(f"-- {title}(留一验证)--")
    for fname, stem, hp, col in cases:
        path = os.path.join(FIX, fname)
        img = cv2.imread(path)
        if img is None:
            check(f"{fname} 存在", False, f"缺样本 {path}(见文件头的说明)")
            continue
        b = hq_hp.bank(exclude=stem)
        field = board.read_field(img)
        if not field["rows"]:
            check(f"{fname} 读得出行结构", False)
            continue
        row = field["rows"][row_index] if row_index < len(field["rows"]) \
            else field["rows"][-1]
        card = _hq_card(img, row, leavemeout=stem)
        got = hq_hp.read(img, card, bank_=b) if card is not None else None
        ok = got is not None and got["hp"] == hp and got["state"] == col
        check(f"{fname:<26} 期望 {hp} {col}", ok, str(got))


def main() -> int:
    print("=" * 78)
    print("总部血量读取:真实帧回归(样本冻结在 shots/hq_hp/regress,期望值人眼读的)")
    print("=" * 78)
    print(f"模板库:{ {k: len(v) for k, v in sorted(hq_hp.bank().items())} }")
    check("模板库 0-9 齐了", sorted(hq_hp.bank()) == list(range(10)))
    check("每个数字至少 1 个原型",
          all(len(v) >= 1 for v in hq_hp.bank().values()))

    _run(ENEMY_CASES, 0, "敌方总部")
    _run(OUR_CASES, -1, "我方总部(盾牌同样适用)")

    print()
    print("-- find_enemy_hq 必须返回**卡框 + 血量 + 盾牌框** --")
    img = cv2.imread(os.path.join(FIX, ENEMY_CASES[0][0]))
    hq = board.find_enemy_hq(img)
    check("找得到敌方总部", hq is not None)
    if hq:
        check("带血量", hq.get("hp") == ENEMY_CASES[0][2], str(hq.get("hp")))
        check("带颜色状态", hq.get("state") == ENEMY_CASES[0][3], str(hq.get("state")))
        check("宽度是卡宽(>100),不是旧的 60", hq.get("w", 0) > 100, str(hq.get("w")))
        check("带盾牌框(攻击后复核要用它)", hq.get("shield_box") is not None,
              str(hq.get("shield_box")))
        # ★ 攻击之后**照这个框读**必须和重新找一遍得到同一个值(实机"血量读不到"的修法)
        again = board.read_hq_hp(img, hq)
        check("read_hq_hp(走 shield_box)值一致", again == hq.get("hp"),
              f"{again} vs {hq.get('hp')}")

    print()
    print("=" * 78)
    print("全部通过" if problems == 0 else f"有 {problems} 项失败")
    print("=" * 78)
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
