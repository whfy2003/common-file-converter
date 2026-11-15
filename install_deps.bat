@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo.
echo 正在安装运行需要的组件（Pillow、img2pdf）...
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo 未找到 Python，请先安装 Python 3.9 或更高版本。
    pause
    exit /b 1
)

python -m pip install --upgrade -r "requirements.txt"
if errorlevel 1 (
    echo.
    echo 安装失败，请检查网络后重试。
    pause
    exit /b 1
)

echo.
echo 安装完成，双击「启动 PDF 合并工具.bat」即可使用。
echo.
pause
