@echo off
REM ===================================================================
REM  lx-music-desktop-win-cli 安装脚本
REM
REM  特点：
REM    * 完全离线装依赖（用内置 wheels/，不联网、不走 pip 索引）
REM    * 自动探测 Python（py / python3 / python）
REM    * 自动选择可用的临时目录（规避 TEMP 不可写的问题）
REM    * 装完自动跑 lx doctor 验证
REM
REM  用法：双击本文件，或在命令行运行 install.bat
REM ===================================================================
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo.
echo ============================================================
echo   LX Music Desktop CLI - 安装
echo ============================================================
echo.

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

if not defined PY (
    echo [X] 找不到可用的 Python 3.10+
    echo.
    echo     请先安装 Python: https://www.python.org/downloads/
    echo     安装时务必勾选 "Add python.exe to PATH"
    echo.
    echo     若已安装但仍找不到，可手动指定：
    echo        set PYTHON=C:\Path\to\python.exe
    echo        install.bat
    echo.
    pause
    exit /b 1
)

REM 允许用 %PYTHON% 显式覆盖
if defined PYTHON (
    "%PYTHON%" -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
    if !errorlevel! equ 0 (
        set "PY=%PYTHON%"
        for /f "delims=" %%V in ('"%PYTHON%" -c "import sys;print(sys.version.split()[0])" 2^>nul') do set "PYVER=%%V"
    )
)

echo [1/4] Python: %PY%  (版本 %PYVER%)
echo.

REM ---------- 2. 修 TEMP（规避"临时目录不可写"）----------
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
    set "TMP=%TEMP%"
    if not exist "!TEMP!" mkdir "!TEMP!" >nul 2>&1
    echo [!] 原 TEMP 不可写，已临时切到: !TEMP!
    echo.
)

REM ---------- 3. 装依赖（优先离线）----------
echo [2/4] 安装依赖...
if exist "wheels\MANIFEST.json" (
    echo       使用内置 wheels（离线，不联网）
    %PY% -m pip install --no-index --find-links "wheels" click requests --quiet --disable-pip-version-check
    if !errorlevel! neq 0 (
        echo       [!] 离线安装失败，回退到联网安装...
        %PY% -m pip install click requests --quiet --disable-pip-version-check
    )
) else (
    echo       [!] 未找到内置 wheels，改用联网安装
    %PY% -m pip install click requests --quiet --disable-pip-version-check
)

if !errorlevel! neq 0 (
    echo.
    echo [X] 依赖安装失败
    echo     可手动执行： %PY% -m pip install click requests
    echo     国内加速：   %PY% -m pip install click requests -i https://pypi.tuna.tsinghua.edu.cn/simple
    echo.
    pause
    exit /b 1
)
echo       依赖就绪
echo.

REM ---------- 4. 验证 ----------
echo [3/4] 验证 CLI...
%PY% run.py --version
if !errorlevel! neq 0 (
    echo.
    echo [X] CLI 无法启动
    pause
    exit /b 1
)
echo.

REM ---------- 5. 可选：装成 lx 命令 ----------
echo [4/4] 是否安装为全局 `lx` 命令？
echo       （可选的；不装也能用 `%PY% run.py ...` 调用）
set /p INSTALL_LX="      安装？[y/N] "
if /i "%INSTALL_LX%"=="y" (
    %PY% -m pip install -e . --quiet --disable-pip-version-check
    if !errorlevel! equ 0 (
        echo       已安装。现在可直接用: lx --help
    ) else (
        echo       [!] 安装为 lx 命令失败（不影响免安装使用）
    )
) else (
    echo       跳过。可用方式：
    echo         %PY% run.py --help
    echo         lx.bat --help
)
echo.

REM ---------- 6. 自检 ----------
echo ============================================================
echo   安装完成，运行自检：
echo ============================================================
%PY% run.py doctor
echo.
echo 若上方显示全部 OK 即可开始使用。
echo 提示：首次使用前请确保 LX Music Desktop 已启动过至少一次。
echo.
pause
endlocal
