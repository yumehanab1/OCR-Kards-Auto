"""make_icon.py - 给面板画一个图标(`assets/app.ico`),只跑一次就够。

为什么自己画:市面上找不到"KARDS AUTO"的现成图标,而打包成 exe 之后
没有图标会很难看(而且一眼分不清哪个是我们的面板)。
配色沿用面板:CSS 里的 `--bg:#0a0e13`、`--orange:#ff8a1f`。

用法:
    .venv\\Scripts\\python.exe src\\make_icon.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image, ImageDraw  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "app.ico")
BG = (10, 14, 19, 255)
ORANGE = (255, 138, 31, 255)
ORANGE_DIM = (176, 92, 16, 255)
FG = (219, 228, 238, 255)


def draw(size: int) -> Image.Image:
    s = size * 4                      # 先画大图再缩小 -> 边缘平滑
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(s * 0.18)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=r, fill=BG,
                        outline=ORANGE_DIM, width=max(2, s // 64))
    # 准星(科技感 + "自动瞄准"的意思)
    cx, cy, rad = s * 0.5, s * 0.5, s * 0.30
    w = max(3, s // 40)
    d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], outline=ORANGE, width=w)
    d.line([cx - rad * 1.35, cy, cx - rad * 0.45, cy], fill=ORANGE, width=w)
    d.line([cx + rad * 0.45, cy, cx + rad * 1.35, cy], fill=ORANGE, width=w)
    d.line([cx, cy - rad * 1.35, cx, cy - rad * 0.45], fill=ORANGE, width=w)
    d.line([cx, cy + rad * 0.45, cx, cy + rad * 1.35], fill=ORANGE, width=w)
    d.ellipse([cx - rad * 0.22, cy - rad * 0.22, cx + rad * 0.22,
               cy + rad * 0.22], fill=FG)
    return img.resize((size, size), Image.LANCZOS)


def main() -> int:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    imgs = [draw(n) for n in sizes]
    imgs[-1].save(OUT, format="ICO",
                  sizes=[(n, n) for n in sizes], append_images=imgs[:-1])
    print("图标 ->", OUT, os.path.getsize(OUT), "B")
    # 顺手存一张 256 的 png,方便在文档/预览里看
    png = os.path.join(os.path.dirname(OUT), "app_icon.png")
    imgs[-1].save(png)
    print("预览 ->", png)
    return 0


if __name__ == "__main__":
    sys.exit(main())
