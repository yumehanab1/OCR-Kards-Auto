"""
frontline_line.py - 标定【前线归属】那条黑线(用户 2026-09-12 指出的判据)。

为什么需要它
------------
用户确认的游戏规则(§7 第 69 条 / §10):
  · 我方支援线上的**任意单位**都能打【敌方前线那一行】—— 步兵/坦克也算;
  · 但**前线被敌方占着,我方就上不去**(实机弹过「前线已被敌方占领。」);
  · 所以顺序是"先能打相邻战线 -> 才能清掉前线 -> 才能上前线"。
要落地第一条,必须先能**可靠地判出"前线那一行是谁的"** ——
判错的后果是**去打自己人**,而 §10 把"把敌方单位当成自己人拖"记成
本项目最危险的错误,这条正是它的镜像。所以这一条**不许猜**。

用户给的判据(原话)
------------------
  "前线有一个黑色的线表示,这根线**靠上代表前线是友方的**,
   **在下边代表是敌方的**,我可以框给你,你不需要摸瞎找。"

★ 为什么不能靠"颜色/亮度"自动找它(已经试过并失败,记下来免得再走一遍):
  · 纯亮度:木桌有很多**横向木纹接缝**,整行都很暗,实测最暗的行里
    y=152/289/353/441/557 全是接缝,分不出哪一条是前线标记;
  · 纯饱和度:那条线是**又暗又偏棕**的(和木桌同色系),`V<90 & S<70`
    在 y335~365 上一个像素都没有 —— 颜色判据在这块桌面上根本不成立。
  → 所以:① **让用户框出它可能出现的范围**(排除掉大部分干扰),
          ② 在框内用"比上下邻居都暗得多的**横向长条**"这个**结构**判据去找。
    这不是"换个阈值",是换掉"用什么特征去找它"。

三种用法
--------
1) 先框一次(**只做一次**,弹出的是**静止图片**,所以盖住游戏无所谓):
     .venv\\Scripts\\python.exe src\\frontline_line.py --action box
   把那条黑线**可能出现的整个范围**框进去:横向盖住整条线,
   纵向盖住它上下移动的全部行程。存进 `config/frontline_line.json`。

2) 标定(★ 需要你做的那一步):
     .venv\\Scripts\\python.exe src\\frontline_line.py --action calib
   ★ **这个循环里没有任何窗口** —— 它只在终端里每 2 秒打一次结果。
     为什么不弹预览窗:本项目截图走 mss **屏幕抓取**,窗口一旦压住 KARDS,
     抓到的就是我们自己的窗口(§7 第 55 条,踩过)。所以标定时要把终端窗口
     **挪到不挡战场的位置**,让 KARDS 完整可见。
   流程:
     · 每 2 秒打印一行 `line y=... score=...`;
     · **按 o** = 现在前线是**我方**的;**按 e** = 现在是**敌方**的;
     · 两种状态各按 3~5 次,按 q 结束。
   样本存 `shots/frontline/labels.jsonl`,每次的整帧也存下来(便于我回头看)。

3) 看标定结果(离线,不需要游戏):
     .venv\\Scripts\\python.exe src\\frontline_line.py --action report
   它会算出那条 y 门槛,并检查两类样本有没有重叠
   (重叠 = 这个特征不成立,必须换特征,而不是硬调门槛)。

另:`.venv\\Scripts\\python.exe src\\frontline_line.py --action probe`
   只读探一次(不开窗口),把标注图存到 `shots/frontline/probe.png`。

★ 纪律(§7 第 67 条 D):换判据/定门槛之后,必须把**两类样本各切出来看图**。
  这个脚本把每次的整帧都存下来了,就是为了这一步。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import cv2
import cv_io  # noqa: F401  (开关:让 cv2 认中文路径,见 cv_io.py)
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# ★ 必须和其他脚本一样把 stdout 设成 utf-8:否则在中文 Windows 的 GBK 控制台上,
#   日志里的 ✅/❌/⚠️ 会直接抛 UnicodeEncodeError **把脚本打崩**
#   (实测踩到过一次 —— 报错发生在"要告诉你标定结果"的那一行,最不该崩的地方)。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from win import capture_client_bgr, find_by_process, set_dpi_aware  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config", "frontline_line.json")
SHOT_DIR = os.path.join(PROJECT_ROOT, "shots", "frontline")
LABELS_PATH = os.path.join(SHOT_DIR, "labels.jsonl")

# ---- 检测参数(结构判据,不是颜色阈值) ----
REF_DY = 16          # 参考行取"上下各 16 px":黑线本体约 5px + 齿约 10px,16 落在外面
DARK_MIN = 25        # 比上下参考都暗这么多,才算"这条线的一部分"
ROW_FRAC_MIN = 0.35  # 一行里至少这个比例的 x 都比参考暗,才算"一条横向长条"
                     # (单张卡/木纹的暗块不会横跨 35% 的宽度)


def load_region():
    if not os.path.exists(CONFIG_PATH):
        return None
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("region")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 判据:黑线在"前线那一行"的**上面**还是**下面**(用户:靠上=友方 / 在下边=敌方)
#
# ★★ 必须用**相对**量,不能用绝对 y。
#   理由:行带会随对局漂移(§12 实测一局 135/295/435,另一局 175/350/525)——
#   写死"y<=350 判我方"在另一局就会全判错。标定数据也证明确实是相对的:
#   同一局里 我方 黑线 y≈269(比前线行中心 350 高 **81px**),
#             敌方 黑线 y≈431(比前线行中心 350 低 **81px**)。
#   偏移量对称且远大于噪声,所以门槛取 ±25px 很安全。
FRONTLINE_MARGIN = 25


def front_reference(frame):
    """
    "前线那一行"的参照 y(中线)。

    优先用**中间那一行**的中心;如果卡框只给了两行(前线空着 / 卡框漏了),
    退回"最上面一行与最下面一行的中点" —— 两者在实测里都≈350。
    取不到就返回 None(调用方 fail-closed)。
    """
    try:
        import board
        rows = board.rows_from_boxes(board.merged_card_boxes(frame))
    except Exception:
        return None, "行结构读不出"
    cys = sorted(float(r["cy"]) for r in rows)
    if len(cys) >= 3:
        return (cys[0] + cys[-1]) / 2.0, f"行数 {len(cys)}(用最上/最下中点)"
    if len(cys) == 2:
        return (cys[0] + cys[-1]) / 2.0, "只有两行(没检出前线行)-> 用中点"
    if len(cys) == 1:
        return None, "只有一行 -> 参照不可信"
    return None, "一行都没有"


def owner_from(band_y, front_y, frow_cards, margin=FRONTLINE_MARGIN):
    """
    最终归属 = 语义判据 + 线位置判据,**语义优先**。

    ★★ 用户 2026-09-12 纠正:"这段时间的前线识别判定是我方的,**其实这段时间
      前线谁都没有占**"。所以:
        · **前线那一行一张卡都没有** -> `empty`(没人占)—— 直接下结论,不看线。
          这比调阈值可靠:线落在中立位附近时我原来靠 ±25px 容差,
          实测它会偏到"我方"那一侧。
        · 有卡时才看线:上面 `our` / 下面 `enemy` / 夹中间 `neutral`。
        · `frow_cards is None`(行结构读不出)-> 退回纯线判据(不假装知道有没有卡)。
      ★ `empty` 和 `neutral` 对调用方是**同一种处置**(能上前线、但没敌人可打),
        分开只是为了让日志说真话(§7 反复吃过"诊断在撒谎"的亏)。
    """
    if frow_cards == 0:
        return "empty"
    return classify_owner(band_y, front_y, margin=margin)


def classify_owner(band_y, front_y, margin=FRONTLINE_MARGIN):
    """
    黑线在参照线**上面** -> 'our';在**下面** -> 'enemy';夹在中间 -> 'neutral';
    读不到 -> None。

    ★ 'neutral' 是**真实存在的一种状态**,不是"读不准":前线是争夺线,
      两边都没站上去时,那条黑线就落在正中(实测:前线空着时
      band=352 / front=354,偏移只有 -2)。所以必须和 None(读不出来)分开:
        · 'neutral' -> 前线空着(或我方没被挡)-> **可以上前线**,但没有敌人可打;
        · None      -> 判据不成立/读不到 -> 调用方**一律 fail-closed**。

    ★ 判错的后果是去打自己人(§10),所以中间那条带一定返回"拿不准"而不是任何一方。
    """
    if band_y is None or front_y is None:
        return None
    d = float(band_y) - float(front_y)
    if d < -margin:
        return "our"
    if d > margin:
        return "enemy"
    return "neutral"


def read_frontline_owner(frame=None, hwnd=None, debug=False, field=None):
    """
    读一次"前线归属"。返回 {'owner','band_y','front_y','delta','score','why'}。

    owner ∈ {'our','enemy','neutral','empty',None};None = 判据不成立/拿不准
    -> 调用方必须 fail-closed。

    ★★ 2026-09-12 用户纠正后新增 **`empty`(没人占)**,并且**优先级高于线位置**:
      用户原话:"这段时间的前线识别判定是我方的,**其实这段时间前线谁都没有占**"。
      所以只要**前线那一行一张卡都没有**,就直接判"没人占",不去看线 ——
      这比调阈值可靠(线在中立位附近时,我原来是靠 ±25px 的容差,
      实测它会落在"我方"那侧)。
      ★ `empty` 和 `neutral` 对调用方是**同一种处置**(可以上前线、但没有敌人可打),
        分开只是为了让日志说真话(§7 反复吃过"诊断在撒谎"的亏)。
    """
    region = load_region()
    out = {"owner": None, "band_y": None, "front_y": None, "delta": None,
           "score": 0.0, "why": ""}
    if not region:
        out["why"] = f"还没框过({CONFIG_PATH} 不存在)"
        return out
    if frame is None:
        if hwnd is None:
            wins = find_by_process("kards")
            if not wins:
                out["why"] = "找不到 kards 窗口"
                return out
            hwnd = wins[0]["hwnd"]
        frame = capture_client_bgr(hwnd)
    if frame is None:
        out["why"] = "截图失败"
        return out

    # ★ 先问一句语义问题:前线那一行**有没有卡**?
    frow_cards = None
    try:
        import board
        if field is None:
            field = board.read_field(frame)
        fr = board.front_row(field)
        frow_cards = 0 if fr is None else len(fr.get("boxes") or [])
    except Exception:
        frow_cards = None

    band_y, score, _n = detect_line_y(frame, region, debug=debug)
    front_y, why_front = front_reference(frame)
    out.update({"band_y": band_y, "score": score, "front_y": front_y})
    if band_y is None:
        out["why"] = f"框内找不到黑线({why_front})"
        return out
    if front_y is None:
        out["why"] = f"拿不到前线参照行({why_front})"
        return out
    out["delta"] = round(band_y - front_y, 1)

    if frow_cards == 0:
        # 前线那一行**一张卡都没有** -> 谁都没占(语义判据,优先于线位置)
        out["owner"] = "empty"
        out["why"] = (f"黑线 y={band_y}(偏移 {out['delta']:+.0f}),但**前线那一行没有卡**"
                      f" -> 没人占(不看线位置)")
        return out

    out["owner"] = owner_from(band_y, front_y, frow_cards)
    out["why"] = (f"黑线 y={band_y}(横跨 {score:.0%}),前线参照 y={front_y:.0f},"
                  f"偏移 {out['delta']:+.0f};前线那一行 {frow_cards} 张卡")
    return out


def save_region(region):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({"region": region,
                   "note": "用户框出的'黑线可能出现的范围'(client 1280x720 坐标)"},
                  f, ensure_ascii=False, indent=2)


def detect_line_y(frame, region, debug=False):
    """
    在 region 里找那条黑线,返回 (y, score, n_rows)。

    判据(结构):**一行像素,比它上下各 REF_DY 处的参考都明显更暗,
    并且这种"更暗"横跨足够宽的比例** —— 那就是一条横贯的黑线。
    这样木纹接缝会被 REF_DY 这一步削掉(接缝上下也是木纹,参考只暗一点),
    而单张卡/装饰的暗块又过不了 ROW_FRAC_MIN(它们不横贯)。

    ★★★ 取哪一条:必须取**最暗(横跨比例最高)**的那一条,
    **不能取"最靠下的那一簇"** —— 这个错误实测踩过一次,而且很值得记:
      第一版写的是"把所有 ≥ 阈值的行聚成簇,取最靠下的那一簇"
      (当时的理由:线的**基准横条**在齿的下面,取最下的更稳)。
      标定回来 12 个样本,`our_03` / `our_04` 判成 y=435(和 7 个"敌方"样本重叠),
      看起来像**标错了**,其实是我选错了带:
      那个框里**同时存在两条带** —— 真标记在 y≈269(横跨 0.90),
      另有一条弱得多的木纹/接缝在 y≈435(横跨 0.47)。
      "取最靠下"这个启发式在**只有一条带**时没问题,两条带时**系统性地选错**,
      而且它输出的还是一个看起来很有把握的数字(最坏的一类错误)。
      → 改成 **argmax**:谁横跨得最宽就是谁。同一批 12 帧立刻 12/12 全对
        (我方 269 / 敌方 431,中间隔着 162px)。
    """
    x0, y0, w, h = region
    x0 = max(0, int(x0))
    y0 = max(0, int(y0))
    x1 = min(frame.shape[1], x0 + int(w))
    y1 = min(frame.shape[0], y0 + int(h))
    if x1 - x0 < 40 or y1 - y0 < 2 * REF_DY:
        # 框太小的话"上下参考"会落在框外/线自身上,判据就不成立了。
        # 与其返回一个可疑的值,不如明说"框太小"(诊断不许说谎)。
        if debug:
            print(f"    框太小({x1 - x0}x{y1 - y0}):横向要盖住整条线,"
                  f"纵向至少 {2 * REF_DY}px(建议再宽一些,盖住它全部行程)")
        return None, 0.0, 0
    gray = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(np.int16)
    n = gray.shape[0]
    # 上下参考:各平移 REF_DY 行后取平均;越界处用自身(等于"没有证据",不误判)
    up = np.vstack([gray[:1]] * REF_DY + [gray[:-REF_DY]]) if n > REF_DY else gray
    dn = np.vstack([gray[REF_DY:]] + [gray[-1:]] * REF_DY) if n > REF_DY else gray
    ref = (up + dn) // 2
    dark = (ref - gray) > DARK_MIN
    counts = dark.sum(axis=1)
    width = gray.shape[1]
    frac = counts / float(width)

    i = int(np.argmax(frac))            # ★ 取最暗的一条,不是最靠下的一条
    if frac[i] < ROW_FRAC_MIN:
        if debug:
            print(f"    (框内最强的一条只横跨 {frac[i]:.0%} < "
                  f"{ROW_FRAC_MIN:.0%};很可能线跑出框了)")
        return None, float(frac[i]), 0
    if debug:
        order = np.argsort(frac)[::-1]
        peaks, seen = [], []
        for j in order:
            if frac[j] < ROW_FRAC_MIN:
                break
            jj = int(j) + y0
            if all(abs(jj - p) > 12 for p in peaks):
                peaks.append(jj)
                seen.append(round(float(frac[j]), 2))
            if len(peaks) >= 4:
                break
        print(f"    框内候选带(按横跨比例):{list(zip(peaks, seen))}"
              f"  -> 选最暗的 y={i + y0}")
    # 赢家所在那一小簇有几行(诊断用)
    lo = i
    while lo > 0 and frac[lo - 1] >= ROW_FRAC_MIN:
        lo -= 1
    hi = i
    while hi < n - 1 and frac[hi + 1] >= ROW_FRAC_MIN:
        hi += 1
    return i + y0, float(frac[i]), hi - lo + 1


# ---------------------------------------------------------------------------
# 一次性:框出"黑线可能出现的范围"
#
# ★ 这里弹窗是**安全的**:窗口里显示的是**一张静止的截图**,不需要再去抓屏。
#   标定循环里就**不能**弹窗了 —— 那时要反复抓屏,窗口会把自己抓进去。
# ---------------------------------------------------------------------------
def action_box(proc):
    wins = find_by_process(proc)
    if not wins:
        print(f"找不到进程 '{proc}' 的窗口")
        return 1
    img = capture_client_bgr(wins[0]["hwnd"])
    if img is None:
        print("截图失败")
        return 1
    state = {"sel": None, "start": None}
    win = "frontline_line_box"

    def on_mouse(event, x, y, _f, _p):
        if event == cv2.EVENT_LBUTTONDOWN:
            state["start"] = (x, y)
        elif event == cv2.EVENT_LBUTTONUP and state["start"]:
            x0, y0 = state["start"]
            state["start"] = None
            if abs(x - x0) < 20 or abs(y - y0) < 32:
                print("框太小:横向要盖住整条线,纵向至少 32px(建议更宽,盖住全部行程)")
                return
            state["sel"] = (min(x0, x), min(y0, y), abs(x - x0), abs(y - y0))

    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, img.shape[1], img.shape[0])
    cv2.setMouseCallback(win, on_mouse)
    print("拖一个框:把那条黑线**可能出现的整个范围**框进去(横向盖住整条线,")
    print("纵向盖住它上下移动的全部行程)。框好后按 **空格/回车** 保存,按 q 取消。")
    while True:
        vis = img.copy()
        x0, y0, w, h = load_region() or (0, 0, 0, 0)
        if w:
            cv2.rectangle(vis, (x0, y0), (x0 + w, y0 + h), (0, 200, 255), 1)
        if state["sel"]:
            x, y, sw, sh = state["sel"]
            cv2.rectangle(vis, (x, y), (x + sw, y + sh), (0, 255, 0), 2)
        cv2.putText(vis, "drag a box, then SPACE/ENTER to save, q to cancel",
                    (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.imshow(win, vis)
        key = cv2.waitKey(30) & 0xFF
        if key in (ord("q"), 27):
            cv2.destroyAllWindows()
            print("已取消,没有改 region")
            return 1
        if key in (13, 10, 32) and state["sel"]:
            save_region(state["sel"])
            print(f"region 已保存:{state['sel']} -> {CONFIG_PATH}")
            cv2.destroyAllWindows()
            return 0


# ---------------------------------------------------------------------------
# 标定循环(★ 无窗口 —— 见文件头"为什么不弹预览窗")
# ---------------------------------------------------------------------------
def action_calib(proc):
    region = load_region()
    if not region:
        print(f"还没有 region({CONFIG_PATH} 不存在)。")
        print("先跑:  python src\\frontline_line.py --action box")
        return 2
    try:
        import msvcrt
    except ImportError:
        print("这个循环需要 Windows 的 msvcrt(非阻塞读键)。")
        return 2
    os.makedirs(SHOT_DIR, exist_ok=True)
    n = {"our": 0, "enemy": 0}
    if os.path.exists(LABELS_PATH):
        with open(LABELS_PATH, "r", encoding="utf-8") as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                    n[r.get("label")] = n.get(r.get("label"), 0) + 1
                except Exception:
                    pass
    print(f"region={region}")
    print("★ 把终端窗口挪到**不挡战场**的位置,让 KARDS 完整可见(截图是屏幕抓取)。")
    print("★ 每 2 秒打一行结果。按 **o**=前线是我方的 / **e**=前线是敌方的 / **q**=结束")
    if any(n.values()):
        print(f"(已有样本:我方 {n.get('our',0)} / 敌方 {n.get('enemy',0)})")
    wins = find_by_process(proc)
    if not wins:
        print(f"找不到进程 '{proc}' 的窗口")
        return 1
    hwnd = wins[0]["hwnd"]
    last = 0.0
    cur = (None, 0.0)
    try:
        while True:
            now = time.time()
            if now - last >= 2.0:
                last = now
                img = capture_client_bgr(hwnd)
                if img is None:
                    print("  截图失败(窗口被盖住/最小化?)—— 这一轮跳过")
                else:
                    y, sc, _rows = detect_line_y(img, region)
                    cur = (y, sc, img)
                    if y is None:
                        print("  line NOT FOUND in region  <- 线跑出框了,或者判据不成立;"
                              "这一轮**不要按键**")
                    else:
                        print(f"  line y={y}  score={sc:.2f}   [o]=我方 [e]=敌方")
            if msvcrt.kbhit():
                ch = msvcrt.getch().decode("utf-8", "ignore").lower()
                if ch == "q":
                    break
                if ch in ("o", "e"):
                    label = "our" if ch == "o" else "enemy"
                    y, sc, img = cur if len(cur) == 3 else (None, 0.0, None)
                    if y is None or img is None:
                        print("  ✗ 现在没找到线,这一按不记(等下一轮找到再按)")
                        continue
                    n[label] = n.get(label, 0) + 1
                    name = f"{label}_{n[label]:02d}_y{y}.png"
                    cv2.imwrite(os.path.join(SHOT_DIR, name), img)
                    with open(LABELS_PATH, "a", encoding="utf-8") as f:
                        f.write(json.dumps({"label": label, "y": y, "score": sc,
                                            "region": list(region), "frame": name,
                                            "ts": time.time()},
                                           ensure_ascii=False) + "\n")
                    print(f"  ✓ 记下 {label}: y={y}(score {sc:.2f})-> {name}")
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    tot = n.get("our", 0) + n.get("enemy", 0)
    print(f"结束:共 {tot} 个样本(我方 {n.get('our', 0)} / 敌方 {n.get('enemy', 0)})")
    print("下一步:python src\\frontline_line.py --action report")
    return 0


# ---------------------------------------------------------------------------
# 只读探针 + 离线报告
# ---------------------------------------------------------------------------
def action_probe(proc):
    region = load_region()
    if not region:
        print(f"还没有框过({CONFIG_PATH} 不存在)。先跑 --action calib。")
        return 2
    wins = find_by_process(proc)
    if not wins:
        print(f"找不到进程 '{proc}' 的窗口")
        return 1
    img = capture_client_bgr(wins[0]["hwnd"])
    if img is None:
        print("截图失败")
        return 1
    y, sc, n = detect_line_y(img, region, debug=True)
    print(f"region={region}  ->  黑线 y={y} (score={sc:.2f}, {n} 行)")
    if y is None:
        print("框内没找到黑线 —— 要么它跑出框了,要么判据在这个画面上不成立。")
    os.makedirs(SHOT_DIR, exist_ok=True)
    vis = img.copy()
    x0, y0, w, h = region
    cv2.rectangle(vis, (x0, y0), (x0 + w, y0 + h), (0, 200, 255), 1)
    if y is not None:
        cv2.line(vis, (x0, y), (x0 + w, y), (0, 0, 255), 2)
    out = os.path.join(SHOT_DIR, "probe.png")
    cv2.imwrite(out, vis)
    print(f"标注图 -> {out}")
    return 0


def action_report():
    if not os.path.exists(LABELS_PATH):
        print(f"还没有样本({LABELS_PATH} 不存在)。先跑 --action calib。")
        return 2
    recs = []
    bad = 0
    with open(LABELS_PATH, "r", encoding="utf-8-sig") as f:   # utf-8-sig:容忍 BOM
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                recs.append(json.loads(ln))
            except Exception:
                bad += 1
    if bad:
        # ★ 不许悄悄丢样本:丢掉的那几条可能正好是某一类,于是"分得开"是假的。
        print(f"⚠️ 有 {bad} 行解析失败(已跳过)—— 如果后面看起来'只有一类样本',"
              f"先怀疑这几行")
    if not recs:
        print("样本文件是空的(或者一行都没解析成功)")
        return 2
    region = load_region()
    if not region:
        print(f"还没有 region({CONFIG_PATH} 不存在)-> 没法在存下来的帧上重算。")
        return 2
    our, enemy = [], []
    for r in recs:
        # ★★ 不直接信样本里存的 y —— **用当前检测器在存下来的整帧上重算一遍**。
        #   理由很实在:这一版检测器就改过选择规则(取最暗的带,而不是最靠下的带),
        #   存下来的旧 y 里有两个是错的。把整帧存下来的意义就在这里:
        #   **标定数据要能被重新分析**,而不是把当时那个版本的结论焊死。
        frame = r.get("frame")
        path = os.path.join(SHOT_DIR, frame) if frame else None
        im = cv2.imread(path) if path and os.path.exists(path) else None
        if im is None:
            rec = {"src": "存下来的 y", "y": r.get("y"), "score": r.get("score"),
                   "front_y": None, "delta": None, "frame": frame}
        else:
            band_y, score, _n = detect_line_y(im, region)
            front_y, _why = front_reference(im)
            rec = {"src": "重算", "y": band_y, "score": score,
                   "front_y": front_y,
                   "delta": (None if (band_y is None or front_y is None)
                             else round(band_y - front_y, 1)),
                   "frame": frame, "stored_y": r.get("y")}
        rec["label"] = r["label"]
        # 按**相对偏移**分组才是对的:行带会漂移,绝对 y 只在同一局里可比
        key = rec["delta"] if rec["delta"] is not None else rec["y"]
        (our if r["label"] == "our" else enemy).append((rec, key))
    print(f"样本:{len(recs)} 条  我方 {len(our)} / 敌方 {len(enemy)}")
    for name, grp in (("我方(应为负偏移=靠上)", our), ("敌方(应为正偏移=靠下)", enemy)):
        if not grp:
            continue
        ys = [r["y"] for r, _ in grp if r["y"] is not None]
        ds = [r["delta"] for r, _ in grp if r["delta"] is not None]
        print(f"  {name}:")
        print(f"    黑线 y   = {sorted(ys)}")
        print(f"    相对偏移 = {sorted(ds)}  (相对前线参照行,正=靠下)")
        stale = [(r["frame"], r["stored_y"], r["y"]) for r, _ in grp
                 if r.get("stored_y") is not None and r["y"] is not None
                 and abs(r["stored_y"] - r["y"]) > 5]   # >5px 才算"选择规则变了"
        if stale:
            print(f"    ⚠️ 有 {len(stale)} 条存下来的 y 和重算差了 5px 以上"
                  f"(检测器改进过;±3px 是基准横条自身的抖动,不算):{stale}")
    okeys = [k for _, k in our if k is not None]
    ekeys = [k for _, k in enemy if k is not None]
    if not our or not enemy:
        print("\n还差一类样本 —— 两种状态都要标几次(否则定不出门槛)。")
        return 1
    if not okeys or not ekeys:
        print("\n有一类的关键量全读不出来(帧丢了/检测失败)-> 定不出门槛。")
        return 1
    print(f"\n按**相对偏移**判定:我方 {min(okeys)}~{max(okeys)}  敌方 {min(ekeys)}~{max(ekeys)}")
    if max(okeys) < min(ekeys):
        thr = (max(okeys) + min(ekeys)) / 2.0
        print(f"✅ 分得开:我方 ≤{max(okeys)} < 敌方 ≥{min(ekeys)}(隔了 "
              f"{min(ekeys) - max(okeys):.0f}px)")
        print(f"   -> 判据:**偏移 < {thr:+.0f} 判我方;偏移 > {thr:+.0f} 判敌方**")
        print(f"   -> 已写进代码:`frontline_line.classify_owner` "
              f"(FRONTLINE_MARGIN={FRONTLINE_MARGIN},取的就是这个空档)")
        return 0
    if max(ekeys) < min(okeys):
        print("\n⚠️ 分得开,但**方向和用户的说法相反**(敌方在上、我方在下)。")
        print("   先别写代码 —— 把两类的整帧图各看一遍,确认是按对了还是标反了。")
        return 1
    print(f"\n❌ 两类**重叠**:我方 {min(okeys)}~{max(okeys)} 与 敌方 {min(ekeys)}~{max(ekeys)}")
    print("   重叠意味着这个特征分不开两种状态 —— 不要硬调门槛。")
    print("   换特征的候选:①齿的方向 ②线的长短/粗细 ③线旁边有没有别的标记。")
    return 1


def main():
    set_dpi_aware()
    ap = argparse.ArgumentParser(description="标定/读取【前线归属】那条黑线")
    ap.add_argument("--action", default="report",
                    choices=["box", "calib", "probe", "report"],
                    help="box=框一次范围 | calib=标定(无窗口,按 o/e) | "
                         "probe=只读探一次 | report=看标定结果")
    ap.add_argument("--proc", default="kards")
    args = ap.parse_args()
    if args.action == "box":
        return action_box(args.proc)
    if args.action == "calib":
        return action_calib(args.proc)
    if args.action == "probe":
        return action_probe(args.proc)
    return action_report()


if __name__ == "__main__":
    sys.exit(main())
