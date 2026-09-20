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
#: ★★★ 2026-09-19(v0.1.2):**"logs" 必须在这里**。
#:   它以前不在,于是打包时把 `logs\main_loop.log`(那几局的完整对局记录,里面有
#:   对手昵称)、`logs\gui_run.log`(里面有**本机的绝对路径**,实测是
#:   `C:\Users\<用户名>\Desktop\...`)和 `gui_selftest.txt` 一起**发到公开包里**。
#:   别人的日志 + 自己的目录结构都不该进发布包;仓库那边本来就靠 .gitignore
#:   排掉了(`logs/*` 只留 `.gitkeep`),只有打包脚本漏了这一条。
#:   ★ 排掉不会让新装的人出问题:`main_loop.py` 和 `gui.py` 都自己
#:     `os.makedirs(..., exist_ok=True)` 建 logs 目录(实测 main_loop.py:85 /
#:     gui.py:464,787),空目录本来也不进 zip。
SKIP_DIRS = {".venv", "venv", "build", "dist", ".git", "shots",
             "shots_hp_bogus", "hp_bogus", "__pycache__", "logs"}

#: 这些文件名是"这台机器专属"的,别人拿了没用,而且 panel_token 是口令。
SKIP_FILES = {"gui_window.json", "panel_token.txt"}

#: 这些后缀是备份/半成品,**一律不进包**。
#: ★★★ 2026-09-20:本机根目录下躺着一个 `KARDS AUTO.exe.bak`(上一版面板,15 MB),
#:   而打包脚本只排目录、不排后缀 —— 于是它会被原样打进发布包:用户解压后看到
#:   两个 exe 不知道该点哪个,包还白胖一大截。跟 `logs` 那次一样,靠人记得删是靠不住的,
#:   把规则写死在这里,并在自检里再拦一道。
SKIP_SUFFIXES = (".bak", ".old", ".orig", ".tmp", ".rej", "~")


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
                if (f in SKIP_FILES or f.endswith((".pyc", ".pyo"))
                        or f.endswith(SKIP_SUFFIXES)):
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
        # ★ 2026-09-20:备份文件也不许进包(见 SKIP_SUFFIXES 的说明)。
        #   自检和"排除"必须是两条独立的关:排除那条写错了,这里还能拦住。
        _bak = [x for x in names if x.endswith(SKIP_SUFFIXES)]
        if _bak:
            problems.append(f"混进了备份文件:{', '.join(_bak[:3])}")
        need = [f"{BASE}/python/python.exe", f"{BASE}/src/main_loop.py",
                f"{BASE}/KARDS AUTO.exe", f"{BASE}/config/app_version.json",
                # ★★★ 2026-09-19:v0.1.1 的包里**漏了这个文件**,而引擎硬依赖它。
                #   后果不是崩,是**静默退化**:match_name() 永远返回 None ->
                #   "卡名 -> 费用"整条失效 -> 费用只剩徽章 OCR 兜底(本来就不稳)
                #   -> 大部分牌 cost=None -> 惰性扫描认为一张都出不起
                #   -> 一局里好几个回合**一张牌没出**(实机 0919 那一局
                #      第 1/2/4/6 回合都是 0 次尝试)。
                #   所以把它加进"缺了就报"的清单。
                f"{BASE}/card_db/kards_data.json",
                # ★★★ 2026-09-19(v0.1.5):**同一类坑的第二次。**
                #   费用数字模板原来在 `shots/kredits/samples_r1/` 下,而 `shots`
                #   在 SKIP_DIRS 里 -> 每个发布包都载入 0 个模板 -> 费用永远读不出
                #   -> 每回合按"上一回合+1"推算 -> **没费用还去拖牌被拒绝**。
                #   现在已经搬到 `config/kredits_digits/`,这里加一条"缺了就报"。
                f"{BASE}/config/kredits_digits/n_00_mask.png"]
        for w in need:
            if w not in names:
                problems.append(f"缺少 {w}")
        for p in problems:
            print(f"    [!!] {p}")
        if not problems:
            print(f"    [OK] {len(names)} 个条目,结构、关键文件、该排掉的都排掉了")

    if problems:
        # ★ 自检没过就把产出**改名**,让它不可能被顺手传上 Release。
        #   历史上有两次事故都是"发布包少文件、引擎静默变笨"(v0.1.2 漏卡库、
        #   v0.1.5 漏费用数字模板),而当时的自检只是打印一行 [!!] 就继续往下走了。
        bad = out[:-4] + "_SELFTEST_FAILED.zip" if out.endswith(".zip") else out + ".FAILED"
        if os.path.exists(bad):
            os.remove(bad)
        os.replace(out, bad)
        print(f"\n  ⚠️ 自检没过({len(problems)} 项)—— 产出已改名,**别发这个包**:")
        print(f"     {bad}")
        return 1

    print("\n  下一步:到 GitHub 上新建 Release,把上面那个 zip 传成附件。")
    print("  ★ 传之前把包解压到一个空目录再验一次:版本号 / 卡库张数 / 费用数字模板 10/10。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
