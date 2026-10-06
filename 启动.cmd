@echo off
setlocal enabledelayedexpansion
title avast-genai2api - Avast 助手 OpenAI 网关
cd /d "%~dp0"

echo ============================================================
echo    avast-genai2api  /  Avast 助手 OpenAI 网关
echo ============================================================
echo.

rem ---- 找 python（不要用 >nul，某些机器上会报「系统找不到指定的路径」）----
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
    echo [错误] 找不到 Python。
    echo.
    echo   请从 https://www.python.org/downloads/ 安装 Python 3.10 或更高版本，
    echo   安装时记得勾选 "Add python.exe to PATH"。
    echo.
    pause
    exit /b 1
)

echo [1/3] Python 解释器:
echo       %PY%
"%PY%" -c "import sys;print('      版本 '+sys.version.split()[0])"

"%PY%" -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)"
if errorlevel 1 (
    echo.
    echo [错误] 需要 Python 3.10 或更高版本。
    pause
    exit /b 1
)

echo [2/3] 检查文件...
if not exist "src\config.json" (
    echo.
    echo [提示] 还没生成 src\config.json
    echo        正在从你本机的 Avast 读取配置...
    echo.
    pushd src
    "%PY%" init_config.py
    set "RC=!errorlevel!"
    popd
    if not "!RC!"=="0" (
        echo.
        echo [错误] 配置生成失败，请按上面的提示补齐参数后重试。
        pause
        exit /b 1
    )
    if not exist "src\config.json" (
        echo.
        echo [错误] config.json 仍未生成，请先补齐 account-id / subscription-id / tenant-id。
        pause
        exit /b 1
    )
)
if not exist "src\server.py" (
    echo [错误] 找不到 src\server.py
    pause
    exit /b 1
)
echo       OK

echo [3/3] 启动网关...
echo.
echo   接口地址 : http://127.0.0.1:8787/v1
echo   模型名称 : avast-assistant
echo   API Key  : 任意值
echo   聊天窗口 : 另开一个窗口运行 聊天.cmd，或者
echo                cd /d "%~dp0src"
echo                "%PY%" cli.py
echo   停止服务 : Ctrl+C
echo.
echo ------------------------------------------------------------
cd /d "%~dp0src"
"%PY%" -u server.py
echo.
echo ------------------------------------------------------------
echo 网关已停止。
pause
