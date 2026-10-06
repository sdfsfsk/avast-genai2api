@echo off
setlocal enabledelayedexpansion
title Avast 助手 - 聊天
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
    echo [错误] 找不到 Python，请先安装 Python 3.10+ 并加入 PATH。
    pause
    exit /b 1
)

echo ============================================================
echo    Avast 助手  -  聊天窗口
echo ============================================================
echo.

if not exist "src\config.json" (
    echo [错误] 还没有 src\config.json，请先运行 启动.cmd 生成配置。
    pause
    exit /b 1
)

echo   要直连 Avast 吗？也就是不走网关、直接连服务器。
echo   输入 y 然后回车 = 直连；直接回车 = 走网关。
echo.

set "DIRECT="
set "ANS="
set /p ANS="  请选择: "

rem 只取第一个字符判断：不用 for /f 归一化，多行输入会取到最后一行
if /i "!ANS:~0,1!"=="y" set "DIRECT=--direct"

echo.
cd /d "%~dp0src"
"%PY%" -u cli.py %DIRECT%
pause
