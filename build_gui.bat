@echo off
chcp 65001 > nul
rem ===========================================================================
rem  build_gui.bat - 把面板重新打包成 dist\KARDS AUTO.exe(双击就能跑这个文件)
rem
rem  什么时候要重新跑它:改了 src\gui.py 之后(界面/逻辑都在里面)。
rem  什么时候**不用**:改引擎(src\*.py 其它文件)—— 那些是 exe 之外运行的真代码,
rem  面板每次「开始」都是去跑项目里的 src\main_loop.py,不是打包进去的副本。
rem
rem  ★ 两条容易踩的:
rem    ① `--icon` 必须给**绝对路径** —— 我们用了 --specpath build,相对路径会被
rem       解析成 build\assets\app.ico,报 "Icon input file ... not found";
rem    ② `--collect-all pythonnet / clr_loader` 不能省 —— pywebview 在 Windows 上是
rem       靠 pythonnet 调 WebView2 的,不收集这些运行时文件,exe 一开就崩。
rem ===========================================================================
cd /d "%~dp0"

echo [1/3] 画图标 ...
".venv\Scripts\python.exe" src\make_icon.py || goto :fail

echo [2/3] PyInstaller 打包(约 1 分钟)...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --onefile --windowed ^
  --name "KARDS AUTO" ^
  --icon "%~dp0assets\app.ico" ^
  --paths src ^
  --collect-all webview --collect-all pythonnet --collect-all clr_loader ^
  --distpath dist --workpath build\pyinstaller --specpath build ^
  src\gui.py || goto :fail

echo [3/3] 自检(exe 内部路径找得对不对)...
del /q logs\gui_selftest.txt 2>nul
"dist\KARDS AUTO.exe" --selftest
type logs\gui_selftest.txt

echo.
echo 完成: dist\KARDS AUTO.exe
pause
exit /b 0

:fail
echo.
echo **打包失败** —— 看上面的报错(常见:图标路径、依赖没收集全)
pause
exit /b 1
