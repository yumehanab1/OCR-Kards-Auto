"""make_release.py - 打发布用的 zip。

★ 为什么要把这件事写成脚本,而不是"自己右键压缩一下":
  发布包**绝对不能**包含 `.venv`。Python 的 venv 里记着建它那台机器的绝对路径
  (`pyvenv.cfg` 的 `home = C:\\Python314`),换台机器就是死的 —— v0.1.0 正是
  这么发出去的,于是**每个下载的人**点"开始"都立刻以退出码 103 结束,日志里
  一个字都没有。手动压缩太容易顺手把 .venv 一起压进去了,所以把规则固定下来。

  同理还要排掉:PyInstaller 的中间产物、git 仓库、排查用的存帧目录、本机的
  窗口位置和面板口令。

用法(在项目根目录下):
    python\\python.exe make_release.py
    .venv\\Scripts\\python.exe make_release.py      # 改代码时用这个也行

产出:桌面上一个 kards-auto_v<版本>_x86_64.zip,并当场自检一遍内容。
"""
from __future__ import annotations

import json
import os
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.basename(ROOT) or "kards-auto"

#: 这些目录名出现在**任何层级**都要跳过。
SKIP_DIRS = {".venv", "venv", "build", "dist", ".git", "shots",
             "shots_hp_bogus", "hp_bogus", "__pycache__"}

#: 这些文件名是"这台机器专属"的,别人拿了没用,而且 panel_token 是口令。
SKIP_FILES = {"gui_window.json", "panel_token.txt"}


def read_version() -> str:
    try:
        with open(os.path.join(ROOT, "config", "app_version.json"),
                  encoding="utf-8") as f:
            return str(json.load(f).get("version", "0.0.0"))
    except Exception:
        return "0.0.0"


def main() -> int:
    ver = read_version()
    out = os.path.join(os.path.expanduser("~"), "Desktop",
                       f"kards-auto_v{ver}_x86_64.zip")

    # ★ 先挡住最要命的那个:仓库根下有 .venv 就说明这是开发目录,
    #   脚本会跳过它 —— 但如果它**存在于**要打包的树里,那正是事故的起点。
    if os.path.isdir(os.path.join(ROOT, ".venv")):
        print("  注意:根目录下有 .venv,已自动排除(它不可移植,进包就是 103)")

    if os.path.exists(out):
        print(f"  覆盖已存在的 {os.path.basename(out)}")
        os.remove(out)

    t0 = time.time()
    n = 0
    skipped = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, dirs, files in os.walk(ROOT):
            keep = [d for d in dirs if d not in SKIP_DIRS]
            skipped += len(dirs) - len(keep)
            dirs[:] = sorted(keep)
            for f in sorted(files):
                if f in SKIP_FILES or f.endswith((".pyc", ".pyo")):
                    skipped += 1
                    continue
                full = os.path.join(root, f)
                rel = os.path.relpath(full, ROOT).replace(os.sep, "/")
                z.write(full, f"{BASE}/{rel}")
                n += 1

    size = os.path.getsize(out) / 1048576
    print(f"  打进 {n} 个文件(跳过 {skipped} 个目录/文件),"
          f"耗时 {time.time() - t0:.1f} 秒")
    print(f"  产出:{out}")
    print(f"  体积:{size:.1f} MB")

    # ---- 自检:每次都要跑,这是最后一道关 ----
    print("\n  自检:")
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        problems = []
        if z.testzip():
            problems.append("zip 有损坏条目")
        if any("\\" in x for x in names):
            problems.append("条目名里有反斜杠(ZIP 规范要求正斜杠)")
        if any(".venv/" in x for x in names):
            problems.append("**包里混进了 .venv** —— 这会让下载的人退 103")
        if any("panel_token" in x for x in names):
            problems.append("**包里混进了面板口令 panel_token.txt**")
        if any("__pycache__" in x for x in names):
            problems.append("混进了 __pycache__")
        need = [f"{BASE}/python/python.exe", f"{BASE}/src/main_loop.py",
                f"{BASE}/KARDS AUTO.exe", f"{BASE}/config/app_version.json"]
        for w in need:
            if w not in names:
                problems.append(f"缺少 {w}")
        for p in problems:
            print(f"    [!!] {p}")
        if not problems:
            print(f"    [OK] {len(names)} 个条目,结构、关键文件、该排掉的都排掉了")

    print("\n  下一步:到 GitHub 上新建 Release,把上面那个 zip 传成附件。")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
