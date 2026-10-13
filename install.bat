@echo off
REM ===================================================================
REM  lx-music-desktop-win-cli 安装 / 更新脚本
REM
REM  特点：
REM    * 自动识别"已装旧版" -> 就地更新（pip install -e . 会覆盖旧版本）
REM    * 完全离线装依赖（用内置 wheels/，不联网、不走 pip 索引）
REM    * 自动探测 Python（py / python3 / python），可用 %PYTHON% 覆盖
REM    * 自动选择可用的临时目录（规避 TEMP 不可写）
REM    * 装完跑 lx doctor + lx status-install 验证
REM
REM  用法：双击本文件；或在命令行运行 install.bat
REM        （首次与升级用同一个脚本，无需区分）
REM ===================================================================
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo.
echo ============================================================
echo   LX Music Desktop CLI - 安装 / 更新
echo ============================================================
echo.

REM ---------- 0. 检测是否已装旧版 ----------
set "OLD_VER="
for /f "tokens=2 delims=: " %%V in ('python -m pip show lx-cli 2^>nul ^| findstr /i "^Version:"') do set "OLD_VER=%%V"
if not defined OLD_VER (
    for /f "tokens=2 delims=: " %%V in ('py -m pip show lx-cli 2^>nul ^| findstr /i "^Version:"') do set "OLD_VER=%%V"
)
if defined OLD_VER (
    echo [检测到旧版] 已安装 lx-cli v!OLD_VER! —— 本次将就地更新到新版。
    echo.
) else (
    echo [全新安装] 未检测到已安装的 lx-cli。
    echo.
)

REM ---------- 1. 找 Python ----------
set "PY="
for %%C in (py python3 python) do (
    if not defined PY (
        %%C -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
        if !errorlevel! equ 0 (
            set "PY=%%C"
            for /f "delims=" %%V in ('%%C -c "import sys;print(sys.version.split()[0])" 2^>nul') do set "PYVER=%%V"
        )
    )
)

if defined PYTHON (
    "%PYTHON%" -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
    if !errorlevel! equ 0 (
        set "PY=%PYTHON%"
        for /f "delims=" %%V in ('"%PYTHON%" -c "import sys;print(sys.version.split()[0])" 2^>nul') do set "PYVER=%%V"
    )
)

if not defined PY (
    echo [X] 找不到可用的 Python 3.10+
    echo.
    echo     请先安装 Python: https://www.python.org/downloads/
    echo     安装时勾选 "Add python.exe to PATH"
    echo     若已安装但仍找不到，手动指定：
    echo        set PYTHON=C:\Path\to\python.exe
    echo        install.bat
    echo.
    pause
    exit /b 1
)

echo [1/5] Python: !PY!  (版本 !PYVER!)
echo.

REM ---------- 2. 修 TEMP ----------
set "TEMP_OK="
if defined TEMP (
    echo test > "%TEMP%\.lx_write_test" 2>nul
    if exist "%TEMP%\.lx_write_test" (
        del "%TEMP%\.lx_write_test" >nul 2>&1
        set "TEMP_OK=1"
    )
)
if not defined TEMP_OK (
    set "TEMP=%LOCALAPPDATA%\Temp"
    set "TMP=!TEMP!"
    if not exist "!TEMP!" mkdir "!TEMP!" >nul 2>&1
    echo [!] 原 TEMP 不可写，已临时切到: !TEMP!
    echo.
)

REM ---------- 3. 装依赖（优先离线）----------
echo [2/5] 安装依赖...
if exist "wheels\MANIFEST.json" (
    echo       使用内置 wheels（离线，不联网）
    !PY! -m pip install --no-index --find-links "wheels" click requests --quiet --disable-pip-version-check
    if !errorlevel! neq 0 (
        echo       [!] 离线安装失败，回退到联网安装...
        !PY! -m pip install click requests --quiet --disable-pip-version-check
    )
) else (
    echo       [!] 未找到内置 wheels，改用联网安装
    !PY! -m pip install click requests --quiet --disable-pip-version-check
)

if !errorlevel! neq 0 (
    echo.
    echo [X] 依赖安装失败
    echo     手动执行： !PY! -m pip install click requests
    echo     国内加速： !PY! -m pip install click requests -i https://pypi.tuna.tsinghua.edu.cn/simple
    echo.
    pause
    exit /b 1
)
echo       依赖就绪
echo.

REM ---------- 4. 安装为 lx 命令（核心：旧版会被自动覆盖更新）----------
echo [3/5] 安装为全局 lx 命令...
if defined OLD_VER (
    echo       覆盖更新旧版 v!OLD_VER! ...
)
!PY! -m pip install -e . --quiet --disable-pip-version-check
if !errorlevel! neq 0 (
    echo       [!] editable 安装失败，尝试普通安装...
    !PY! -m pip install . --quiet --disable-pip-version-check
)
if !errorlevel! neq 0 (
    echo       [!] 未能装成 lx 命令（不影响免安装方式 run.py / lx.bat）
) else (
    echo       ✓ lx 命令可用
)
echo.

REM ---------- 5. 验证 ----------
echo [4/5] 验证 CLI...
!PY! run.py --version
if !errorlevel! neq 0 (
    echo.
    echo [X] CLI 无法启动
    pause
    exit /b 1
)
echo.

REM ---------- 6. 自检 ----------
echo [5/5] 自检...
echo ------------------------------------------------------------
!PY! run.py status-install
echo ------------------------------------------------------------
!PY! run.py doctor --no-network
echo.
echo ============================================================
if defined OLD_VER (
    echo   更新完成！v!OLD_VER! -^> 见上方版本号
) else (
    echo   安装完成！
)
echo ============================================================
echo.
echo 现在可直接使用： lx --help
echo 提示：首次使用前请确保 LX Music Desktop 已启动过至少一次。
echo.
pause
endlocal
