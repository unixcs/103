@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
echo ============================================
echo   verify-lab 一键运行
echo ============================================
echo.
where python >nul 2>nul
if errorlevel 1 goto nopython
python demo.py
if errorlevel 1 goto failed
echo.
echo [成功] 证书已生成，在 outputs 文件夹里，可以双击打开 PNG。
goto end
:failed
echo.
echo [出错] 请把上面的错误信息复制下来发给我。
goto end
:nopython
echo [错误] 没有找到 python，请先安装 https://www.python.org/downloads/ 并勾选 Add to PATH。
:end
echo.
echo 按任意键关闭窗口...
pause >nul
