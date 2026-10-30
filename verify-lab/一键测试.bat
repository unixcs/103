@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
echo ============================================
echo   verify-lab 一键跑测试
echo ============================================
echo.
where python >nul 2>nul
if errorlevel 1 goto nopython
python -m unittest discover -s tests -t . -v
echo.
echo 看到 OK 就是全部通过；看到 FAILED 请把输出发给我。
goto end
:nopython
echo [错误] 没有找到 python，请先安装并勾选 Add to PATH。
:end
echo.
pause >nul
