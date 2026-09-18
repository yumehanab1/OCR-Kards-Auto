@echo off
rem Interactive ROI calibration on the captured KARDS screenshot.
rem Default names cover the M1 needs; you can add more after --names.
cd /d "%~dp0"
".venv\Scripts\python.exe" src\calibrate.py --image shots\kards_720p.png --out config\roi.json
echo.
echo Saved config\roi.json  (hand_area / end_turn_btn / kredits_roi / play_btn / surrender_btn)
pause
