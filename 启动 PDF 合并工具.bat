@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

where pythonw >nul 2>nul
if not errorlevel 1 (
    start "" pythonw "main.py"
    exit /b 0
)

where python >nul 2>nul
if not errorlevel 1 (
    start "" python "main.py"
    exit /b 0
)

echo.
echo 未找到 Python，请先安装 Python 3.9 或更高版本。
echo 下载地址：https://www.python.org/downloads/
echo.
pause
exit /b 1
