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
# ★★★ 2026-09-19(实机第二局)**"K 在前"那条规则已经删掉,而且必须记住为什么**。
#
# 徽章的真实长相(存帧 `shots/deploy_drag/0919_145114_x602.png` 放大 4 倍看的,
# 那张牌是**2 费**的 哈奇开斯 H35):
#         ┌─────────┐
#         │ 2   K   │   <- 大数字 = 费用(2);右上角小 K = Kredits 符号
#         │     1   │   <- 右下角**更小**的数字 = 这副牌里还剩几张(1 张)
#         └─────────┘
#   ⇒ 整个徽章里有**两个数字**。OCR 常常只抓到那个**小的**(它和 K 挨着),
#     于是读出 `'K1'` / `'K2'` / `'K-3'` 这种形状。
#
# 我上一轮(同一天早些时候)看到 `shots/diffdiag` 里有 `'K-3'`,就补了一条
# "K 在前"的正则 —— **那是错的**:实测把上面那块徽章喂给 OCR 得到 `'K1'`,
# 新正则会返回 **费用 1**,而这张牌其实是 **2 费**。
# 也就是说它读的是"牌库剩几张",不是费用。
# 后果比"读不出"更坏:费用读小 -> 引擎会**去拖一张其实出不起的牌**
# (白拖一次,还占掉一个动作),而本项目一贯的取舍是"**宁可少打一次**"。
# ⇒ 所以这条规则删掉,cost 回到 None(由名字查库那条主路负责费用)。
COST_BADGE_K_FIRST_RE = None
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

# ---- 第 ⑤ 级(近似命中)的参数。判据与实测见 match_name 里那一段注释 ----
#: 卡名**字面上**够长才参与近似匹配(短碎片属于"没读到",不许硬凑)
FUZZY_MIN_LEN = 5
#: 长度差超过这个数就不是"认错一两个字"了
FUZZY_LEN_SLACK = 2
#: 相似度下限(1 - 编辑距离/较长长度)
FUZZY_MIN_RATIO = 0.75
#: 最佳必须比次佳好这么多,否则宁可不认(歧义时认错比认不出更坏)
FUZZY_MARGIN = 0.10

_NAME_SET = None
_NAME_LIST = None
_CARD_BY_NAME = None
# ★★★ 2026-09-19(实机第二局):**归一化后的卡名 -> 规范卡名**。
#
# 为什么非要有这张表:规则 ① 原来写的是 `if tn in _NAME_SET`,而 `tn = norm(text)`
# 是**去掉所有空白**的,`_NAME_SET` 里装的却是**库里的原样名字** ——
# 库里有 **659/1558** 张卡名带空格(KARDS 在数字和拉丁字母两边插空格:
# "第 5 步兵旅" / "丘吉尔 Mk IV" / "105 毫米轻型榴弹炮")。
# 于是这些卡**永远走不到"精确命中"那一级**,掉进模糊规则里,而模糊规则
# 是按"卡名长的优先"遍历候选的 —— 一条更长的、恰好包含 OCR 文本的卡名会先命中。
#
# 实机判据(2026-09-19 第二局,`logs/main_loop.log`):
#   手牌里那张 `第 5 步兵旅`(徽章 **2**)被认成 `维尔纽斯第 5 步兵旅`(**6**)
#   -> 预算 3 的那一回合判成"出不起" -> **能出的牌不出**(用户报的就是这个)。
#   全域自检:`match_name(库里每一条卡名)` 有 **21/1558** 认错自己,其中 **9 条费用被读错**。
_NAME_NORM = None
#: 上一次 load_db 为什么没载进来(载进来了就是空串)。**必须留痕** ——
#: 卡库缺失不会让引擎崩,只会让它悄悄退化成"费用全靠徽章 OCR 兜底",
#: 而那正是"整回合一张牌不出"的根(见 2026-09-19 实机)。
_DB_ERROR = ""


def load_db(path: str = DATA_JSON):
    """载入卡名集合、按长度降序的卡名表、卡名 -> 卡数据。"""
    global _NAME_SET, _NAME_LIST, _CARD_BY_NAME, _DB_ERROR, _NAME_NORM
    if _NAME_SET is not None:
        return
    names = set()
    by_name = {}
    _DB_ERROR = ""
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
        _DB_ERROR = f"{type(e).__name__}: {e}"
        print(f"card_match: 卡库载入失败 {e}")
    if not names and not _DB_ERROR:
        _DB_ERROR = "文件在,但里面一条中文卡名都没有"
    _NAME_SET = names
    _NAME_LIST = sorted(names, key=len, reverse=True)
    _CARD_BY_NAME = by_name
    # ★ 归一化索引:OCR 那边一律是 `norm()` 过的,所以这里也必须归一化,
    #   否则带空格的名字永远精确命中不了(见 _NAME_NORM 处的实机判据)。
    _NAME_NORM = {}
    for zh in _NAME_LIST:            # 长名先入,短名撞车时不覆盖(与 by_name 一致)
        key = norm(zh)
        if key and key not in _NAME_NORM:
            _NAME_NORM[key] = zh


def db_status() -> str:
    """
    一行说清"卡库到底载进来了没有" —— 给引擎启动时打进日志用。

    ★ 为什么要专门做这件事:这个故障**不报错、不崩、只是每张牌都少一条判据**。
      2026-09-19 实机那一局就是这么过去的:发布包里漏了
      `card_db_test/kards_data.json`,于是 `match_name()` 永远返回 None,
      费用只剩"徽章 OCR"这一条**本来就不稳**的兜底路 -> 大部分牌 cost=None
      -> 惰性扫描认为"一张都出不起" -> 第 1/2/4/6 回合一张牌没出。
      日志里只有一行 `识别依据[... **卡名没读出**]`,看不出是"卡库没载入"。
    """
    load_db()
    n = len(_NAME_SET or [])
    if n:
        return f"卡库:{n} 张卡名(卡名 -> 费用 这条路可用)"
    return (f"⚠️⚠️ 卡库没载入({_DB_ERROR or '未知原因'}) —— "
            f"卡名匹配**整条失效**,费用只能靠徽章 OCR 兜底(不稳,"
            f"会导致'有牌不出');文件应在 {DATA_JSON}")


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

    # ① 精确(★ 用**归一化**索引比对,不然带空格的卡名一条都命中不了,见 _NAME_NORM)
    if tn in _NAME_NORM:
        hit = _NAME_NORM[tn]
        return (hit, "exact") if debug else hit

    # ② 去噪声后精确
    sn = strip_noise(tn)
    if sn and sn in _NAME_NORM:
        hit = _NAME_NORM[sn]
        return (hit, "exact-noise") if debug else hit

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

    # ⑤ ★★★ 2026-09-19(实机第三局)近似命中:**只修"OCR 认错一两个字"**。
    #
    # 为什么非要这一级(实机日志原样,判据全在这里):
    #   15:17:51  x596=fighter(fighter/None,✗){徽章=无 OCR行=['19','喷火Mkla','战斗机','喷火'] 图标=0.949}
    #   15:21:22  x620=infantry(infantry/None,✗){徽章=无 OCR行=['兰开夏燃发枪兵团','步兵',...]}
    #   —— 卡名**读出来了**,只是差一个字符:
    #        '喷火Mkla'      vs 库里 '喷火 Mk Ia'       (OCR 把罗马数字 I 读成小写 l)
    #        '兰开夏燃发枪兵团' vs 库里 '兰开夏燧发枪兵团'   (燧 -> 燃,字形近)
    #   上一级(③④)全是**子串/前缀**判据,差一个字符就一条都不成立 ->
    #   名字=None -> 费用只能靠徽章(而徽章里有两个数字,见上面的实测)->
    #   cost=None -> **这张牌一辈子出不去**(用户报的"喷火从头到尾没打出过")。
    #
    # 安全边界(每一条都是为了"不许乱认"):
    #   · 只看长度差 ≤ 2 的候选(差太多不可能只是认错字);
    #   · 相似度 = 1 - 编辑距离/较长长度,要求 ≥ FUZZY_MIN_RATIO;
    #   · **最佳必须明显优于次佳**(FUZZY_MARGIN),否则宁可不认 ——
    #     歧义时返回错的那张比认不出更坏(费用会跟着错);
    #   · 太短的文本(≤ FUZZY_MIN_LEN)不参与 —— '战斗机'/'19'/'TRCK' 这种
    #     短碎片本来就属于"没读到",不该硬凑一张牌。
    best, best_r, second_r = None, 0.0, 0.0
    for cand in _NAME_LIST:
        c = norm(cand)
        if abs(len(c) - klen) > FUZZY_LEN_SLACK or len(c) < FUZZY_MIN_LEN:
            continue
        r = _similar(key, c)
        if r > best_r:
            best, second_r, best_r = cand, best_r, r
        elif r > second_r:
            second_r = r
    if best is not None and best_r >= FUZZY_MIN_RATIO \
            and best_r - second_r >= FUZZY_MARGIN:
        return (best, f"fuzzy:{best}({best_r:.2f})") if debug else best
    return (None, "no-hit") if debug else None


def _levenshtein(a: str, b: str) -> int:
    """编辑距离(纯 python,只用来比卡名,几十个字符以内)。"""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1,          # 删
                           cur[j - 1] + 1,       # 插
                           prev[j - 1] + (ca != cb)))   # 换
        prev = cur
    return prev[-1]


def _similar(a: str, b: str) -> float:
    """1 - 编辑距离/较长长度(1.0 = 一模一样)。"""
    m = max(len(a), len(b))
    if not m:
        return 0.0
    return 1.0 - _levenshtein(a, b) / m


def read_cost_badge(lines):
    """
    从 OCR 行里读悬停卡的费用徽章("NK")。

    lines: [{'text','conf','x','y','w','h','cx','cy'}, ...]
    返回 (cost, evidence) 或 (None, reason)。

    只认"数字+K"这一种形状,**既**不认光秃秃的数字(卡面上还有攻击/防御/血量
    一堆数字,实测画面上就有 '18'/'32'/'152'),**也**不认"K 在前"
    (那是徽章里那个"牌库剩几张"的小数字,见 COST_BADGE_K_FIRST_RE 处的实测)。
    多个不同的值 -> 分不清就不猜(None)。
    """
    found = {}
    for ln in lines:
        if ln.get("conf", 0) < 0.5:
            continue
        text = norm(ln.get("text", ""))
        m = COST_BADGE_RE.match(text)
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
