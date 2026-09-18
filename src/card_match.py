"""
card_match.py - 卡名匹配 / 费用兜底 / 放大卡图像指纹(M3 修复 + M4 基础)。

为什么单独一个模块
------------------
`hand_scanner_v2._classify` 里原来塞了三件事:类型图标匹配、卡名 OCR 匹配、
查库拿费用。其中"卡名匹配"这一块有两个长期缺陷(见 PROJECT_STATE.md 第 35/37 条),
而且很难离线测。抽到这里之后:
  - 匹配规则可以纯函数化,不需要游戏也不需要 OCR 引擎就能跑单测;
  - 费用兜底、图像指纹这些新能力有地方放。

三个能力
--------
1. `match_name(text)`  —— 卡名匹配(四级打分)
     ① 归一化后精确命中
     ② 去掉装饰字符(★ # + 数字 空格 标点)后再精确命中
     ③ 候选包含:OCR 文本里含有某张卡名,或某张卡名含有 OCR 文本
        短卡名(<4 字)只允许"被包含",不允许"包含别人",防止
        "伤害,且能攻击被守护的单位" 里的 "攻击" 被当成卡名(第 33/37 条)
     ④ 前缀命中:OCR 文本正好是某张卡名的开头 —— 修正截断读不全的情况
        (实测 "长轻型榴弹炮" 是 "105 毫米轻型榴弹炮" 的尾部,不适用;
         而 "强袭指令" 之类的后缀噪声由 ③ 的"被包含"覆盖)

     长卡名优先:候选按长度从长到短试,先命中的胜出。
     歧义(多个等长候选同时命中)一律返回 None —— 宁可读不出,不要读错。

2. `read_cost_badge(lines)` —— 费用徽章 OCR 兜底
     悬停放大的卡左上角有 "NK" 徽章(实测 OCR 能读到 3K / 2K / 5K)。
     卡名读不出时(纯英文+数字卡名、被"友方回合"横幅挡住)用它拿费用,
     上限 24。分不清时返回 None(不猜)。

3. `CardHashDB` —— 放大卡图像指纹库
     卡名 OCR 失败是常态(实测 6 帧里有 4 帧读不出或读错)。但同一张卡的
     放大图在同一分辨率下是像素级重复的,所以可以:
       扫描时顺手把"卡名读出来了"的那几张的指纹存下来(自动学习);
       以后遇到读不出的卡,用指纹查表认出来。
     指纹用 16x16 dHash(64 位),纯 numpy 实现(本机 opencv 没编 img_hash)。
"""

from __future__ import annotations

import json
import os
import re

import cv2
import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_JSON = os.path.join(PROJECT_ROOT, "card_db_test", "kards_data.json")
HASH_DB = os.path.join(PROJECT_ROOT, "config", "card_hashes.json")

# 装饰字符:OCR 会把卡面装饰、分隔符、罗马数字角标读进来。
# 实测例子:"喷烟者42型+" -> 卡名 "喷烟者 42 型";"强袭★" -> "强袭";
#           "105毫米轻型榴弹炮+D2" -> "105 毫米轻型榴弹炮"。
NOISE_CHARS = "★☆✦✧✪✫✬✭✮✯◆◇○●◎＊*+#＃↑↓←→「」『』《》〈〉·．。、，,：:;；!！?？'\"“”‘’"
# 方括号内容(卡名角标)一起删掉
NOISE_GROUP = re.compile(r"[（(\[【][^）)\]】]{0,6}[）)\]】]")

# 费用徽章:"3K" / "3 K" / "3Kredits"。只在卡面上部找,且限制 0-24。
COST_BADGE_RE = re.compile(r"^(\d{1,2})\s*K", re.I)
MAX_COST = 24

# 前缀匹配时,OCR 文本至少要占候选卡名这么长的比例。
# 目的是修"截断读不全",不是"猜" —— 实测卡名带会被 HUD 横幅挡掉一截。
# 若把比例放太松("105" 就能命中 "105 毫米轻型榴弹炮"),会把同一系列的
# 多张卡混成一张(T-34-85 / T-34-85 1944 / T-34-85 1945 都在库里),风险太大。
PREFIX_MIN_RATIO = 0.5
PREFIX_MIN_CHARS = 5

# 「卡名 + 少量尾随噪声」允许的最大噪声长度。
# 实测 "强袭指令"(卡名"强袭"+ 类型名"指令")、"强袭."(标点)。
# ★ 必须同时要求卡名出现在【文本开头】,否则描述句
#   "炮兵在攻击时不会受到反击" 里的 "攻击"(位置 5)会被误当卡名
#   —— PROJECT_STATE 第 33 条踩过这个坑。
CONTAINS_HEAD_SLACK = 2

_NAME_SET = None
_NAME_LIST = None
_CARD_BY_NAME = None


def load_db(path: str = DATA_JSON):
    """载入卡名集合、按长度降序的卡名表、卡名 -> 卡数据。"""
    global _NAME_SET, _NAME_LIST, _CARD_BY_NAME
    if _NAME_SET is not None:
        return
    names = set()
    by_name = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for c in data.get("cards", []):
            j = c.get("json", {})
            zh = (j.get("title") or {}).get("zh-Hans", "")
            if not zh:
                continue
            names.add(zh)
            by_name.setdefault(zh, {
                "kredits": j.get("kredits"),
                "type": j.get("type"),
                "cardId": c.get("cardId"),
            })
    except Exception as e:                       # 数据库缺失不该让扫描崩掉
        print(f"card_match: 卡库载入失败 {e}")
    _NAME_SET = names
    _NAME_LIST = sorted(names, key=len, reverse=True)
    _CARD_BY_NAME = by_name


def card_by_name(name):
    load_db()
    return _CARD_BY_NAME.get(name)


def norm(t: str) -> str:
    """归一化:去掉所有空白。"""
    return re.sub(r"\s+", "", t or "")


def strip_noise(t: str) -> str:
    """
    去掉 OCR 噪声,再归一化。

    只删【明确不是卡名一部分】的东西:装饰符号、标点、括号角标。
    ★ 不删数字 —— 卡名里就有数字("105 毫米轻型榴弹炮""T-34-85 1945"),
    删了会把同一系列的卡混成一张("T-34-85 1945" -> "T-34-85")。
    首尾多余的 HUD 数字由 `strip_edge_digits` 单独处理,而且只在"完整文本
    已经在库里查不到"时才用。
    """
    s = NOISE_GROUP.sub("", t or "")
    s = "".join(ch for ch in s if ch not in NOISE_CHARS)
    return re.sub(r"\s+", "", s)


# 结尾几位数很可能只是 HUD 数字("18" 回合数、"32")粘上来的。
# 只削 1-4 位,而且至少留 2 个字符。
_TRAIL_DIGITS = re.compile(r"^(.*?[\D])\d{1,4}$")


def strip_edge_digits(t: str) -> str:
    """
    "3512毫谷榴弹炮" 这种先不处理(数字在中间);这里只削【结尾】的纯数字,
    且必须还剩至少 2 个字符。用于"完整文本查不到"时的第二次尝试。
    """
    s = strip_noise(t)
    m = _TRAIL_DIGITS.match(s)
    if m and len(m.group(1)) >= 2:
        return m.group(1)
    return s



def match_name(text: str, debug: bool = False):
    """
    OCR 文本 -> 库里的规范卡名,匹配不到返回 None。

    debug=True 时返回 (name, tier),tier 说明是哪一级命中的(诊断用)。

    四级顺序(每一级内部都是"长卡名优先",保证最长匹配胜出):
      ① exact        归一化后精确命中
      ② exact-noise  去掉装饰字符后精确命中  —— 修 "强袭★" / "喷烟者42型+"
      ③ 包含关系     OCR 文本含完整卡名(修 "强袭指令"),或卡名含 OCR 文本
      ④ prefix       OCR 文本是卡名的开头(修截断)
    """
    load_db()
    tn = norm(text)
    if not tn:
        return (None, "empty") if debug else None

    # ① 精确
    if tn in _NAME_SET:
        return (tn, "exact") if debug else tn

    # ② 去噪声后精确
    sn = strip_noise(tn)
    if sn and sn in _NAME_SET:
        return (sn, "exact-noise") if debug else sn

    # ③④ 候选匹配。先在"去噪声"版本上试,再退回原文。
    seen = []
    for key in (sn, tn, strip_edge_digits(tn)):
        if key and key not in seen:
            seen.append(key)

    for key in seen:
        klen = len(key)
        for cand in _NAME_LIST:
            if cand == key:
                continue
            c = norm(cand)
            clen = len(c)
            if clen < 2 or clen > klen + 8:      # 差太多的候选不可能相关
                continue
            # ③a 被包含 + 位于开头 + 只多了一点点噪声。
            #     修 "强袭指令" / "强袭." 这种"卡名 + 尾随装饰"的 OCR;
            #     ★ 严格要求卡名出现在文本【开头】且尾随噪声很短,否则
            #     描述句 "炮兵在攻击时不会受到反击" 里的 "攻击" 会被误当卡名
            #     (PROJECT_STATE 第 33 条踩过)。
            if c in key:
                head = key.find(c)
                if head == 0 and klen - clen <= CONTAINS_HEAD_SLACK:
                    return (cand, f"head:{cand}") if debug else cand
                # ③b 卡名本身够长时,允许出现在文本任意位置
                #     (卡名较长,不会和描述里的常用词撞)
                if clen >= 4:
                    return (cand, f"contains:{cand}") if debug else cand
            # ③c 包含别人:两边都得够长,否则短文本会乱吃长卡名
            if klen >= 4 and clen >= 4 and key in c:
                return (cand, f"in:{cand}") if debug else cand
            # ④ 前缀(只修截断)。要求 OCR 文本够长且已覆盖候选的一半以上,
            #    否则 "105" 这种短前缀会把整个系列混成一张。
            if (klen >= PREFIX_MIN_CHARS and c.startswith(key)
                    and klen >= clen * PREFIX_MIN_RATIO):
                return (cand, f"prefix:{cand}") if debug else cand
    return (None, "no-hit") if debug else None


def read_cost_badge(lines):
    """
    从 OCR 行里读悬停卡的费用徽章("NK")。

    lines: [{'text','conf','x','y','w','h','cx','cy'}, ...]
    返回 (cost, evidence) 或 (None, reason)。

    只认行首完整的 "数字+K",这样 "105毫米轻型榴弹炮+02" 不会被误当成费用;
    多个不同的值 -> 分不清就不猜(None)。
    """
    found = {}
    for ln in lines:
        if ln.get("conf", 0) < 0.5:
            continue
        m = COST_BADGE_RE.match(norm(ln.get("text", "")))
        if not m:
            continue
        v = int(m.group(1))
        if 0 <= v <= MAX_COST:
            found.setdefault(v, []).append(ln)
    if not found:
        return None, "no-badge"
    if len(found) > 1:
        return None, f"ambiguous{ sorted(found) }"
    v = next(iter(found))
    return v, f"badge:{v}"


# ---------------------------------------------------------------- 图像指纹
def dhash(bgr, size: int = 16):
    """
    16x16 dHash -> 256 位布尔数组(十六进制字符串由 hash_to_hex 给)。

    卡面放大图在同一分辨率下是像素级重复的,所以 dHash 足够区分不同卡,
    且对压缩噪声稳健。opencv 5 没编 img_hash,这里用手写实现。
    """
    if bgr is None or bgr.size == 0:
        return None
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    small = cv2.resize(gray, (size + 1, size), interpolation=cv2.INTER_AREA)
    return small[:, 1:] > small[:, :-1]


def hash_to_hex(bits) -> str:
    if bits is None:
        return ""
    return np.packbits(bits.reshape(-1)).tobytes().hex()


def hex_to_bits(hexstr: str, size: int = 16):
    raw = np.frombuffer(bytes.fromhex(hexstr), dtype=np.uint8)
    return np.unpackbits(raw)[: size * size].astype(bool)


def hamming(a: str, b: str) -> int:
    """两个十六进制指纹的汉明距离;长度不一致返回 10**6。"""
    if not a or not b or len(a) != len(b):
        return 10 ** 6
    x = int(a, 16) ^ int(b, 16)
    return bin(x).count("1")


def crop_card_name_band(frame, box):
    """
    从悬停面板里裁出"放大的卡"整块(± 一点余量),给指纹用。

    box 是 diff_bbox 给的 (x, y, w, h)。指纹要的是【卡面图像】,不是文字,
    所以这里不做任何 y 裁剪 —— 卡面美术在卡的中下部。
    """
    x, y, w, h = box
    fh, fw = frame.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(fw, x + w), min(fh, y + h)
    return frame[y0:y1, x0:x1]


class CardHashDB:
    """
    放大卡指纹库:自动学习 + 查表识别。

    学习时机:扫描时卡名 OCR 读出来了 -> 记下 (指纹 -> 卡名)。
    使用时机:卡名读不出 -> 拿指纹找最近的(汉明距离 <= threshold)。
    """

    def __init__(self, path: str = HASH_DB, threshold: int = 12):
        self.path = path
        self.threshold = threshold
        self.entries = []          # [{'hash': hex, 'name': str, 'type': str}]
        self.load()

    def load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self.entries = json.load(f).get("entries", [])
        except Exception as e:
            print(f"CardHashDB: {self.path} 读取失败 {e}")
            self.entries = []

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"entries": self.entries}, f, ensure_ascii=False, indent=1)

    def learn(self, bits, name, type_=None, max_per_name: int = 4):
        """记一条指纹(同一个卡名最多留 max_per_name 条,避免库无限膨胀)。"""
        if bits is None or not name:
            return False
        hexstr = hash_to_hex(bits)
        same = [e for e in self.entries if e.get("name") == name]
        for e in same:
            if hamming(e["hash"], hexstr) <= 2:
                return False                       # 已经有一模一样的了
        if len(same) >= max_per_name:
            return False
        self.entries.append({"hash": hexstr, "name": name, "type": type_})
        return True

    def lookup(self, bits):
        """返回 (name, type, distance) 或 (None, None, None)。"""
        if bits is None or not self.entries:
            return None, None, None
        hexstr = hash_to_hex(bits)
        best, best_d = None, 10 ** 6
        for e in self.entries:
            d = hamming(e["hash"], hexstr)
            if d < best_d:
                best, best_d = e, d
        if best is None or best_d > self.threshold:
            return None, None, None
        return best["name"], best.get("type"), best_d

    def __len__(self):
        return len(self.entries)
