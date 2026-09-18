"""cv_io.py - 让 cv2 能读写带中文(非 ASCII)的路径。

★ 为什么需要这个,不是洁癖,是实测出来的:
  Windows 上 `cv2.imread` 走的是窄字符 fopen,**路径里只要有一个非 ASCII 字符就
  返回 None,而且不抛异常**。同一个文件,同一份代码:

      cv2.imread(r"...\\新建文件夹\\e2e\\kards-auto\\ui_templates\\cost_num.png") -> None
      cv2.imread(r"...\\Temp\\cost_num_ascii.png")                              -> 数组

  对中文用户这几乎必然踩中:压缩包解压到「D:\\游戏\\kards-auto」,或者 Windows
  用户名本身就是中文(`C:\\Users\\张三\\Desktop\\...`)。踩中的表现是引擎
  **一个模板都加载不了**,日志里飘一片

      WARN cannot load template deck_ok_btn: ...ui_templates/deck_ok_btn.png

  看起来像模板文件丢了,其实是读不到。引擎不会崩 —— 它会安静地什么都认不出来,
  这正是这个项目最怕的那种失败(报了成功,其实什么都没干)。

★ 做法:在**本模块被 import 的时候**就把 `cv2.imread` / `cv2.imwrite` 换掉,
  而不是去改那二十多个调用点 —— 漏一个就是一处静默失效,而且以后新写的代码还会
  再踩一次。Python 的模块是单例,所以**只要有一个地方在任何读图之前 import 过本
  模块,整个进程的 `cv2.imread` 就都是能读中文的版本了**。

★ 谁该 import 它:所有会被单独执行的入口(`main_loop.py`、`gui.py`,以及各个
  `*_calibrate.py` / `capture.py` / `board.py` / `frontline_line.py` …)。
  它们里那行 `import cv_io  # noqa: F401` 看着像个没用的 import,其实是总开关。

★ 读和写都不走原版(除了先试一下):
  · 读 —— 原版失败会返回 None,正好拿来当"要不要绕路"的判据;
  · 写 —— 原版在中文路径下**返回 False 而不抛异常**,直接用它等于把图悄悄丢了
    (这个坑本项目在手机端 `mobile_hand.py` 里已经单独踩过一次)。
"""

from __future__ import annotations

import os

import cv2
import numpy as np

#: 留一份原版函数。★ 必须在打补丁**之前**取,而且下面用标记防止重复打补丁 ——
#  万一有人 reload 本模块,第二次取到的就是自己的版本,那就无限递归了。
_orig_imread = cv2.imread
_orig_imwrite = cv2.imwrite

_PATCHED_FLAG = "__kards_cv_io__"


def _ascii_only(path) -> bool:
    """
    这个路径是不是纯 ASCII?是的话原版就能处理,不用绕路。

    ★ 为什么要判在前面,而不是"先试原版、失败再绕":原版在中文路径下失败时会在
      stderr 上吐一行 `cv::findDecoder imread_('...'): can't open/read file`,
      日志里看着像真出了问题。直接绕过去就没这行噪声了。
    """
    try:
        p = os.fspath(path)
    except TypeError:
        return False
    if isinstance(p, bytes):
        return True            # 已经是字节路径,原版自己能处理
    try:
        p.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _imread_unicode(path, flags):
    """绕路读:自己把文件读成字节,再交给 `cv2.imdecode`。"""
    try:
        buf = np.fromfile(path, dtype=np.uint8)   # numpy 走的是 Python 的文件 API,认中文
    except Exception:
        return None
    if buf.size == 0:
        return None
    try:
        return cv2.imdecode(buf, flags)
    except Exception:
        return None


def imread(path, flags=cv2.IMREAD_COLOR):
    """
    读一张图,支持非 ASCII 路径。语义和 `cv2.imread` 一致:失败返回 None。

    ★ 纯 ASCII 路径优先走原版(行为跟以前完全一样,也更快);含非 ASCII 的直接
      绕路,免得原版先吐一行 `can't open/read file` 的警告。
    ★ 但 ASCII 那条路失败之后**还要再绕一次**:路径字符串本身是 ASCII、而当前
      工作目录含中文(相对路径的情形)时,原版照样读不到,只有绕路才行。
    """
    if path is None:
        return None
    if _ascii_only(path):
        try:
            img = _orig_imread(path, flags)
            if img is not None:
                return img
        except Exception:
            pass
    return _imread_unicode(path, flags)


def imwrite(path, img, params=None):
    """
    写一张图,支持非 ASCII 路径。返回值语义和 `cv2.imwrite` 一致:成功 True。

    ★ 非 ASCII 路径不走原版,理由和 imread 一样 —— 而且原版在那条路上是**返回
      False 而不抛异常**的,直接用它等于把图悄悄丢了(手机端已经踩过一次)。
    """
    if path is None or img is None:
        return False
    if _ascii_only(path):
        try:
            if _orig_imwrite(path, img, params or []):
                return True
        except Exception:
            pass
    ext = os.path.splitext(str(path))[1] or ".png"
    try:
        ok, buf = cv2.imencode(ext, img, params or [])
        if not ok:
            return False
        buf.tofile(path)
        return True
    except Exception:
        return False


# ---- 打补丁 ---------------------------------------------------------------
# ★ 用标记防重复:reload 本模块时若再包一层,`_orig_imread` 就成了自己的包装,
#   调用会无限递归。
if not getattr(cv2.imread, _PATCHED_FLAG, False):
    setattr(imread, _PATCHED_FLAG, True)
    setattr(imwrite, _PATCHED_FLAG, True)
    cv2.imread = imread
    cv2.imwrite = imwrite
