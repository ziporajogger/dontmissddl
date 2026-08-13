@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ================================================
echo   dontmissddl 一键部署
echo ================================================
echo.

rem 检查 Python 是否安装
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 没检测到 Python。
    echo   请到 https://www.python.org/downloads/ 下载安装，
    echo   安装时务必勾选 "Add Python to PATH"，装好后重新双击本文件。
    pause
    exit /b 1
)

rem 检查 Python 版本（需要 3.9+）
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,9) else 1)"
if errorlevel 1 (
    echo [错误] Python 版本太旧，需要 3.9 或更高。当前版本：
    python --version
    pause
    exit /b 1
)

rem 安装 setup.py 所需的依赖（requests，几秒搞定）
python -c "import requests" >nul 2>nul
if errorlevel 1 (
    echo 首次运行，正在安装依赖 requests...
    python -m pip install requests
)

echo.
python setup.py
if errorlevel 1 pause
