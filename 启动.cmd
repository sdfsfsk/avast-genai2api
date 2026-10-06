@echo off
setlocal enabledelayedexpansion
title avast-genai2api - Avast Assistant Gateway
cd /d "%~dp0"

echo ============================================================
echo    avast-genai2api  /  Avast Assistant  OpenAI Gateway
echo ============================================================
echo.

rem ---- locate python (do not use ">nul": it fails on some hosts) ----
set "PY="
for /f "delims=" %%P in ('where python') do (
    if not defined PY set "PY=%%P"
)
if not defined PY (
    for /f "delims=" %%P in ('where py') do (
        if not defined PY set "PY=%%P"
    )
)

if not defined PY (
    set "CAND=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    if exist "!CAND!" set "PY=!CAND!"
)
if not defined PY (
    set "CAND=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    if exist "!CAND!" set "PY=!CAND!"
)
if not defined PY (
    set "CAND=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    if exist "!CAND!" set "PY=!CAND!"
)
if not defined PY (
    set "CAND=%APPDATA%\uv\python\cpython-3.12.13-windows-x86_64-none\python.exe"
    if exist "!CAND!" set "PY=!CAND!"
)
if not defined PY (
    if exist "C:\Python312\python.exe" set "PY=C:\Python312\python.exe"
)
if not defined PY (
    if exist "C:\Python311\python.exe" set "PY=C:\Python311\python.exe"
)
if not defined PY (
    if exist "C:\Python310\python.exe" set "PY=C:\Python310\python.exe"
)

if not defined PY (
    echo [ERROR] Python not found.
    echo.
    echo   Install Python 3.10+ from https://www.python.org/downloads/
    echo   and tick "Add python.exe to PATH" during setup.
    echo.
    pause
    exit /b 1
)

echo [1/3] Python interpreter:
echo       %PY%
"%PY%" -c "import sys;print('      version '+sys.version.split()[0])"

"%PY%" -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)"
if errorlevel 1 (
    echo.
    echo [ERROR] Python 3.10 or newer is required.
    pause
    exit /b 1
)

echo [2/3] Checking files...
if not exist "src\config.json" (
    echo [ERROR] src\config.json not found - keep the folder layout intact.
    pause
    exit /b 1
)
if not exist "src\server.py" (
    echo [ERROR] src\server.py not found.
    pause
    exit /b 1
)
echo       OK

echo [3/3] Starting gateway...
echo.
echo   Base URL : http://127.0.0.1:8787/v1
echo   Model    : avast-assistant
echo   API Key  : any value is accepted
echo   Chat CLI : open another window and run
echo                cd /d "%~dp0src"
echo                "%PY%" cli.py
echo   Stop     : Ctrl+C
echo.
echo ------------------------------------------------------------
cd /d "%~dp0src"
"%PY%" -u server.py
echo.
echo ------------------------------------------------------------
echo Gateway stopped.
pause
