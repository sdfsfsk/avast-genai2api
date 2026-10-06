@echo off
setlocal enabledelayedexpansion
title Avast Assistant - Chat
cd /d "%~dp0"

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
    set "CAND=%APPDATA%\uv\python\cpython-3.12.13-windows-x86_64-none\python.exe"
    if exist "!CAND!" set "PY=!CAND!"
)
if not defined PY (
    echo [ERROR] Python not found.
    pause
    exit /b 1
)

echo ============================================================
echo    Avast Assistant  -  chat console
echo ============================================================
echo.
echo   Requires the gateway to be running (??.cmd).
echo   If it is not, this window will still work by talking to
echo   Avast directly once you answer Y below.
echo.

set "DIRECT="
set /p ANS="Talk to Avast directly instead of the gateway? [y/N] "
if /i "%ANS%"=="y" set "DIRECT=--direct"

cd /d "%~dp0src"
"%PY%" -u cli.py %DIRECT%
pause
