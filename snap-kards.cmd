@echo off
rem One-shot: capture the KARDS game window (matched by its process name
rem "kards", NOT by title — so a folder named "kards-auto" can never be caught),
rem force its client area to 1280x720, and save a screenshot.
cd /d "%~dp0"
".venv\Scripts\python.exe" src\capture.py snap --proc kards --client 1280x720 --out shots\kards_720p.png
echo.
echo Saved to shots\kards_720p.png  (open it, verify it shows the GAME, not a folder)
pause
