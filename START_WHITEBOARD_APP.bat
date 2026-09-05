@echo off
setlocal
cd /d "%~dp0"
title SRT Whiteboard Studio
echo.
echo ==================================================
echo   SRT WHITEBOARD STUDIO - KHOI DONG LOCAL
echo ==================================================
echo.
where py >nul 2>&1
if %errorlevel%==0 (
  py -3 -X utf8 scripts\prepare_env.py
) else (
  python -X utf8 scripts\prepare_env.py
)
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -X utf8 -m app.server
goto :end
:failed
echo.
echo Khong the chuan bi moi truong. Xem HUONG-DAN-APP.md.
pause
:end
endlocal
