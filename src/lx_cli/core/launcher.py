"""LX 进程控制（启动 / 停止 / 检测是否运行）。

复用并整理自旧版 ``lx-cli/src/lx_cli/launcher.py``（逻辑经实测可用）。
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from .._logging import get_logger
from ..errors import LxNotRunningError, PathError
from ..paths import EXE_NAME, default_exe_path, find_exe

log = get_logger()

PROCESS_NAME = EXE_NAME


def exe_path(explicit: str | Path | None = None, *, search: bool = True) -> Path:
    """定位 LX 可执行文件（P4：支持主动搜索）。

    :param search: 是否启用注册表/目录扫描（找不到时）
    """
    if explicit:
        p = Path(explicit)
        if not p.exists():
            raise PathError(
                f"指定的 LX 不存在：{p}\n请检查 --exe 的值。",
                detail={"path": str(p)})
        return p

    found, how = find_exe(search=search)
    if found:
        log.debug("found LX exe via %s: %s", how, found)
        return found

    raise PathError(
        "找不到 lx-music-desktop.exe。\n"
        "解决办法（任选其一）：\n"
        "  1. 用 --exe 指定：lx --exe \"D:\\...\\lx-music-desktop.exe\" where\n"
        "  2. 设置环境变量：setx LX_EXE \"D:\\...\\lx-music-desktop.exe\"\n"
        f"  3. 已自动尝试：默认候选路径、PATH、注册表、常见安装目录扫描\n"
        f"     （候选示例：{default_exe_path()}）",
        detail={"searched": True},
    )


def is_running() -> bool:
    """LX 是否在运行。"""
    try:
        if sys.platform == "win32":
            out = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {PROCESS_NAME}", "/NH"],
                capture_output=True, text=True, timeout=5,
                encoding="utf-8", errors="replace",
            )
            return PROCESS_NAME.lower() in (out.stdout or "").lower()
        out = subprocess.run(["pgrep", "-f", PROCESS_NAME],
                             capture_output=True, text=True, timeout=5)
        return bool((out.stdout or "").strip())
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("is_running check failed: %s", exc)
        return False


def start(exe: str | Path | None = None, *, hidden: bool = True,
          extra_args: list[str] | None = None) -> None:
    """启动 LX（``--hidden`` 走托盘，不弹主窗口）。"""
    p = exe_path(exe)
    args = [str(p)]
    if hidden:
        args.append("--hidden")
    if extra_args:
        args.extend(extra_args)
    log.debug("start: %s", args)
    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    except OSError as exc:
        raise PathError(f"启动失败：{p}: {exc}",
                        detail={"path": str(p)}, cause=exc) from exc


def stop(*, timeout: float = 5.0, force: bool = False,
         exe: str | Path | None = None) -> bool:
    """优雅停止 LX；``force=True`` 时强制结束进程树。

    返回是否已停止。
    """
    if not is_running():
        return True

    if sys.platform == "win32":
        if force:
            subprocess.run(["taskkill", "/IM", PROCESS_NAME, "/T", "/F"],
                           capture_output=True, timeout=15)
        else:
            subprocess.run(["taskkill", "/IM", PROCESS_NAME, "/T"],
                           capture_output=True, timeout=15)
    else:
        subprocess.run(["pkill", "-f", PROCESS_NAME],
                       capture_output=True, timeout=15)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_running():
            return True
        time.sleep(0.3)
    return not is_running()
