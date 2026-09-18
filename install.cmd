@echo off
setlocal enabledelayedexpansion

rem 把控制台代码页锁成 936。这个文件本身是 GBK,输出也按 936 走,
rem 三者一致才不会乱码。不写这行的话,输出编码会跟着运行环境的代码页跑。
chcp 936 >nul

rem ===========================================================================
rem  install.cmd -- 一键装好这个项目需要的 Python 依赖
rem
rem  双击就行。它会做四件事:
rem    1. 找一个能用的 Python
rem    2. 在项目目录下建一个 .venv 虚拟环境
rem    3. 把依赖装进去
rem    4. 自检一遍,确认装完真的能 import,而不是"装完了但其实是坏的"
rem
rem  为什么要写这个:这个项目的依赖有十几个,光看 requirements.txt 就劝退了。
rem  这里一次装完,不用你一条条 pip install。
rem
rem  用法:
rem    install.cmd                     默认,装完整功能,含 GUI 面板和打包工具
rem    install.cmd minimal             只装跑引擎必需的那几个,最快
rem    install.cmd mirror              国内网络用,走清华镜像
rem    install.cmd minimal mirror      两个一起用也行
rem
rem  装完之后怎么跑,看 README.md。
rem
rem  ==========================================================================
rem  ★ 维护这个文件时注意两件事,都踩过:
rem
rem  一、文件必须是 GBK 编码,不要改成 UTF-8。
rem      cmd.exe 在 chcp 65001 下读批处理是按字节偏移找的,中文一多就会把行
rem      读错位,报一堆 "xxx is not recognized"。中文 Windows 默认代码页是 936,
rem      正好对得上,所以这样就稳。改完记得转回 GBK。
rem
rem  二、echo 的内容里不要出现半角括号。
rem      写在 if/else 块里面的 echo,内容里的半角括号会被当成块的边界,
rem      把整个块拆坏。实测症状是脚本跑到一半就退出,什么也不说。
rem      要写括号就用全角,或者用 ^ 转义。
rem  ==========================================================================

cd /d "%~dp0"

set "MODE=full"
set "USEMIRROR=0"

:parseargs
if "%~1"=="" goto :start
if /i "%~1"=="minimal"   set "MODE=minimal"
if /i "%~1"=="--minimal" set "MODE=minimal"
if /i "%~1"=="mirror"    set "USEMIRROR=1"
if /i "%~1"=="--mirror"  set "USEMIRROR=1"
shift
goto :parseargs

:start
echo.
echo   ==========================================================
echo     KARDS AUTO -- 依赖安装
echo   ==========================================================
echo.
if "%MODE%"=="minimal" echo     模式: 最小安装,只装引擎需要的
if "%MODE%"=="full"    echo     模式: 完整安装
if "%USEMIRROR%"=="1"  echo     下载源: 清华镜像
if "%USEMIRROR%"=="0"  echo     下载源: PyPI 官方
echo.

rem ---------------------------------------------------------------------------
rem  1) 找 Python
rem ---------------------------------------------------------------------------
echo   [1/4] 找 Python ...

set "PYEXE="

rem 优先用 Windows 的 py 启动器,它能自动挑最新的 3.x
where py >nul 2>nul
if not errorlevel 1 set "PYEXE=py -3"

rem 没有 py 启动器就退回 PATH 里的 python
if not defined PYEXE (
    where python >nul 2>nul
    if not errorlevel 1 set "PYEXE=python"
)

if not defined PYEXE goto :nopython

rem 版本要 3.10 以上。代码里用了 X | None 这种类型标注,虽然大部分文件有
rem from __future__ import annotations 兜着,但要求 3.10 稳妥些。
rem 版本号和路径都让 Python 自己打印,不用 for /f 去接,那玩意的引号很难配对。
%PYEXE% -c "import sys;print('        Python',sys.version.split()[0]);print('       ',sys.executable)"
if errorlevel 1 goto :nopython

%PYEXE% -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)"
if errorlevel 1 goto :oldpython

rem ---------------------------------------------------------------------------
rem  2) 建虚拟环境
rem ---------------------------------------------------------------------------
echo.
echo   [2/4] 准备 .venv ...

if exist ".venv\Scripts\python.exe" goto :venvok

echo         正在创建,这一步大概十几秒 ...
%PYEXE% -m venv .venv
if errorlevel 1 goto :venvfail
echo         建好了
goto :venvdone

:venvok
echo         已经有一个了,直接用,不重建

:venvdone
set "VPY=.venv\Scripts\python.exe"
if not exist "%VPY%" goto :venvfail

rem ---------------------------------------------------------------------------
rem  3) 装依赖
rem ---------------------------------------------------------------------------
echo.
echo   [3/4] 装依赖 ...
echo.

set "PIPFLAGS="
if "%USEMIRROR%"=="1" set "PIPFLAGS=-i https://pypi.tuna.tsinghua.edu.cn/simple"

rem 先把 pip 自己升一下,老 pip 装新包容易出各种怪问题
echo         -- 升级 pip
"%VPY%" -m pip install --upgrade pip %PIPFLAGS% --quiet
if errorlevel 1 echo         pip 没升上去,不影响,继续

echo         -- 引擎必需: mss / opencv / numpy / pywin32
"%VPY%" -m pip install -r requirements.txt %PIPFLAGS%
if errorlevel 1 goto :pipfail

if /i "%MODE%"=="minimal" goto :selfcheck

echo.
echo         -- OCR,可选
"%VPY%" -m pip install rapidocr_onnxruntime %PIPFLAGS%
if errorlevel 1 echo         装不上也不影响跑,只是少个读卡牌描述的功能

echo.
echo         -- 面板和打包工具,可选
"%VPY%" -m pip install pywebview Pillow requests %PIPFLAGS%
if errorlevel 1 echo         这几个是可选的,没装上也还能跑引擎

rem ---------------------------------------------------------------------------
rem  4) 自检
rem ---------------------------------------------------------------------------
:selfcheck
echo.
echo   [4/4] 自检 ...
echo.

set "FAILED=0"

"%VPY%" -c "import cv2,numpy,mss;print('        cv2',cv2.__version__,' numpy',numpy.__version__)"
if errorlevel 1 set "FAILED=1"
if errorlevel 1 echo         [X] 引擎核心 import 失败

"%VPY%" -c "import win32api,win32con,win32gui;print('        pywin32 OK')"
if errorlevel 1 set "FAILED=1"
if errorlevel 1 echo         [X] pywin32 import 失败

"%VPY%" -c "import rapidocr_onnxruntime;print('        OCR OK')"
if errorlevel 1 echo         [!] OCR 没装上,读卡牌描述那个功能会不可用,不影响跑

if /i "%MODE%"=="full" goto :checkgui
goto :aftercheck

:checkgui
"%VPY%" -c "import webview;print('        面板 OK')"
if errorlevel 1 echo         [!] 面板没装上,只能命令行跑 src\main_loop.py

:aftercheck
echo.
if "%FAILED%"=="1" goto :selffail

echo   ==========================================================
echo     装好了
echo   ==========================================================
echo.
echo     下一步:
echo       - 打开 KARDS,停在主界面
echo       - 双击 KARDS AUTO.exe
echo.
echo     想先不动鼠标、看看它认屏认不认得对,就在面板上把
echo     "只看不动"勾上再点开始。细节看 README.md。
echo.
pause
exit /b 0


rem ===========================================================================
rem  出错分支
rem ===========================================================================

:nopython
echo.
echo   [X] 没找到 Python。
echo.
echo       去 python.org 下一个装上,装的时候记得勾上
echo       "Add python.exe to PATH" 那一项,然后重开一个窗口再跑这个脚本。
echo.
echo       https://www.python.org/downloads/windows/
echo.
pause
exit /b 1

:oldpython
echo.
echo   [X] Python 版本太旧,要 3.10 以上。
echo.
echo       去 python.org 下个新的,或者用 py -3.12 这种指定版本。
echo.
pause
exit /b 1

:venvfail
echo.
echo   [X] 建虚拟环境失败。
echo.
echo       常见原因:项目目录没有写权限,或者被杀毒软件拦了。
echo       换个目录,比如 D:\kards-auto,再试一次。
echo.
pause
exit /b 1

:pipfail
echo.
echo   [X] 装依赖失败。
echo.
echo       如果是网络超时,换镜像再试一次:
echo           install.cmd mirror
echo.
echo       如果是某个包编译失败,把上面的报错整段发出来。
echo.
pause
exit /b 1

:selffail
echo   ==========================================================
echo     装完了,但自检有项目没通过,见上面的 [X]
echo   ==========================================================
echo.
echo     标 [X] 的是必需的,标 [!] 的缺了也还能跑,只是少个功能。
echo.
echo     先把报错整段发出来看看。
echo.
pause
exit /b 1
