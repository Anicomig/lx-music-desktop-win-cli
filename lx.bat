@echo off
REM 免安装启动器（P1/P2）—— 双击或命令行均可，支持换目录/改名。
REM 用法: lx.bat search "yorushika"
setlocal
set "HERE=%~dp0"
REM 优先用 py 启动器，其次 python
where py >nul 2>nul && (
  py -3 "%HERE%run.py" %*
) || (
  python "%HERE%run.py" %*
)
endlocal
