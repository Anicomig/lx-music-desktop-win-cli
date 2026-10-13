@echo off
REM ===================================================================
REM  lx-music-desktop-win-cli 卸载脚本
REM
REM  **只清 CLI 自己的痕迹**：
REM    * pip 包 lx-cli（如装过）
REM    * lx.exe（如装过）
REM    * CLI 写的元数据
REM
REM  **不删**：LX Music Desktop 本体、LX 数据（歌单/配置/音源脚本）
REM
REM  用法：双击本文件，或 install.bat 的反向操作
REM ===================================================================
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo.
echo ============================================================
echo   LX Music Desktop CLI - 卸载
echo ============================================================
echo.
echo 本脚本只删除 CLI 自身的痕迹。
echo LX Music Desktop 本体与你的数据（歌单/配置/音源脚本）不会被删除。
echo.

set "PY="
for %%C in (py python3 python) do (
    if not defined PY (
        %%C -c "import sys" >nul 2>&1
        if !errorlevel! equ 0 set "PY=%%C"
    )
)
if not defined PY (
    echo [X] 找不到 Python；无法调用 CLI 的卸载逻辑。
    echo     可手动执行： python -m pip uninstall lx-cli
    pause
    exit /b 1
)

echo 将要执行的操作预览（dry-run）：
echo.
%PY% run.py uninstall
echo.
echo ------------------------------------------------------------
set /p DOIT="确认执行卸载？[y/N] "
if /i not "%DOIT%"=="y" (
    echo 已取消，未做任何更改。
    pause
    exit /b 0
)
echo.
echo 执行中...
%PY% run.py uninstall --apply --yes
echo.

set /p RESTORE="是否同时关闭 LX 的开放 API？[y/N] "
if /i "%RESTORE%"=="y" (
    echo.
    echo 注意：需要先关闭 LX，否则设置会被 LX 覆盖。
    set /p LXCLOSED="LX 已关闭？[y/N] "
    if /i "!LXCLOSED!"=="y" (
        %PY% run.py uninstall --apply --yes --restore-config
    ) else (
        echo 跳过。请关闭 LX 后运行：
        echo   %PY% run.py uninstall --apply --restore-config
    )
)

echo.
echo ============================================================
echo   卸载完成
echo ============================================================
echo.
echo 保留的内容（需要时请手动处理）：
echo   * LX Music Desktop 本体
echo   * LX 数据目录（含你的歌单与音源脚本）
echo   * 本解压目录（可直接删除）
echo.
pause
endlocal
