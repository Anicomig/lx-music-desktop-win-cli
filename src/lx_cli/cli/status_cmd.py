"""``lx status-install`` —— 显示**安装状态**。

与 ``--version``（只显示版本号）不同，本命令回答的是"我装的是什么、装在哪、
是否全局可用、环境对不对"。AI/脚本用 ``--json`` 消费。

检测维度：
  * CLI 版本 + 包位置 + 安装方式（pip editable / pip site-packages / 免安装 run.py）
  * Python 解释器与版本
  * 关键依赖是否齐全
  * lx.exe 解析结果与来源
  * LX 数据目录是否存在
  * ``lx`` 是否在 PATH 上（全局可用性）
  * wheels/ 是否随包发布（离线安装能力）
"""
from __future__ import annotations

import json as _json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import click

from ..paths import (
    ensure_importable, find_exe, lx_datas_dir, package_root, src_dir,
)
from ._common import Ctx, pass_ctx, wrap_errors


@dataclass
class InstallStatus:
    cli_version: str = ""
    package_location: str = ""
    install_mode: str = ""            # editable | site-packages | portable
    project_root: str = ""
    python_executable: str = ""
    python_version: str = ""
    architecture: str = ""
    deps_ok: bool = True
    deps_missing: list[str] = field(default_factory=list)
    exe_found: str = ""
    exe_source: str = ""
    datas_dir: str = ""
    datas_exists: bool = False
    global_lx_on_path: bool = False
    global_lx_path: str = ""
    offline_wheels_available: bool = False
    notes: list[str] = field(default_factory=list)


def _detect_install_mode() -> tuple[str, str]:
    """判断当前是怎么跑的：editable / site-packages / portable(run.py)。

    ⚠️ 顺序很关键：**先问 pip**，再退回路径推断。
    因为 editable 安装的包也是从 ``src/`` 加载的，若先看路径会把
    "已 pip editable 安装"误判成"免安装"。只有 pip 完全不知道 lx-cli
    （纯 run.py 直跑）时，才归为 portable。
    """
    here = Path(__file__).resolve()            # .../lx_cli/cli/status_cmd.py
    pkg_dir = here.parent.parent               # .../lx_cli
    root = pkg_dir.parent                      # .../src 或 site-packages

    # 1) 先问 pip：能查到就是 pip 装的（editable 或普通）
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "show", "lx-cli"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=15)
        if r.returncode == 0:
            txt = r.stdout or ""
            if "Editable project location" in txt:
                loc = [ln.split(":", 1)[1].strip()
                       for ln in txt.splitlines()
                       if ln.startswith("Editable project location")]
                return "editable", (loc[0] if loc else str(root))
            return "site-packages", str(root)
    except Exception:
        pass

    # 2) pip 查不到 → 看是不是从项目 src/ 直跑（run.py 免安装）
    if root.name == "src":
        return "portable", str(root)

    return "unknown", str(root)


def _check_deps() -> tuple[bool, list[str]]:
    missing = []
    for mod, pkg in (("click", "click"), ("requests", "requests")):
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    return (not missing), missing


def _find_global_lx(project_root: str) -> tuple[bool, str]:
    """在 PATH 里找**真正的全局** lx 可执行文件。

    排除两类假阳性：
      * 当前目录 / 项目目录内的 ``lx.bat``（本地脚本，不算全局安装）
      * 相对路径命中（shutil.which 会优先返回 ``.\\lx.BAT``）

    做法：遍历 ``os.environ['PATH']`` 的每个目录，找绝对路径下的
    ``lx.exe``/``lx``/``lx.bat``；跳过项目根内部的目录。
    """
    try:
        root = Path(project_root).resolve()
    except Exception:
        root = None
    path_sep = os.pathsep
    names = ["lx"]
    if os.name == "nt":
        exts = (os.environ.get("PATHEXT") or ".EXE;.BAT;.CMD").split(";")
        names = [f"lx{e}" for e in exts] + ["lx"]
    for d in os.environ.get("PATH", "").split(path_sep):
        if not d:
            continue
        try:
            dd = Path(d).resolve()
        except Exception:
            dd = Path(d)
        if root is not None:
            try:
                if dd == root or root in dd.parents or dd in root.parents:
                    continue                 # 项目内或项目父级，跳过
            except Exception:
                pass
        for name in names:
            cand = dd / name
            try:
                if cand.is_file():
                    return True, str(cand)
            except OSError:
                continue
    return False, ""


def build_status(ctx: Ctx) -> InstallStatus:
    st = InstallStatus()
    from lx_cli import __version__
    st.cli_version = __version__

    mode, loc = _detect_install_mode()
    st.install_mode = mode
    st.package_location = loc
    st.project_root = str(src_dir().parent) if src_dir().exists() else loc

    st.python_executable = sys.executable
    st.python_version = platform.python_version()
    st.architecture = platform.architecture()[0]      # '64bit'/'32bit'

    ok, missing = _check_deps()
    st.deps_ok = ok
    st.deps_missing = missing
    if not ok:
        st.notes.append(f"缺少依赖：{', '.join(missing)}；跑 install.bat 或 pip install {' '.join(missing)}")

    # lx.exe
    exe, source = find_exe(ctx.exe)
    st.exe_found = str(exe) if exe else ""
    st.exe_source = source
    if not exe:
        st.notes.append("未找到 lx-music-desktop.exe；用 --exe 或设 LX_EXE 指定")

    # 数据目录
    d = lx_datas_dir(ctx.exe)
    st.datas_dir = str(d)
    st.datas_exists = d.is_dir()
    if not st.datas_exists:
        st.notes.append("LX 数据目录不存在；至少打开一次 LX 生成配置")

    # 全局 lx 是否可用（真正装到 PATH 上，而非当前目录的 lx.bat）
    # ⚠️ shutil.which 会优先命中**当前目录**的 ./lx.bat（相对路径），
    #    那是本地脚本不是全局安装。所以要遍历 PATHEXT/PATH，找真正的
    #    绝对路径 lx.exe，且排除项目目录内的。
    st.global_lx_on_path, st.global_lx_path = _find_global_lx(st.project_root)
    if mode == "portable" and not st.global_lx_on_path:
        st.notes.append("当前为免安装运行；如需全局 `lx`，跑 install.bat 选 y 或 pip install -e .")

    # 离线安装能力
    wheels = Path(st.project_root) / "wheels" / "MANIFEST.json"
    st.offline_wheels_available = wheels.is_file()

    return st


_MODE_LABEL = {
    "editable": "pip 可编辑安装（改代码即时生效）",
    "site-packages": "pip 正式安装",
    "portable": "免安装（run.py / 源码目录直跑）",
    "unknown": "未知",
}


def _format_human(st: InstallStatus) -> str:
    lines = ["", "lx-cli 安装状态", "=" * 44, ""]
    rows = [
        ("CLI 版本", st.cli_version),
        ("安装方式", _MODE_LABEL.get(st.install_mode, st.install_mode)),
        ("包位置", st.package_location),
        ("项目根", st.project_root),
        ("Python", f"{st.python_version} ({st.architecture})"),
        ("解释器", st.python_executable),
        ("依赖", "齐全 ✓" if st.deps_ok else f"缺失 ✗ {st.deps_missing}"),
        ("lx.exe", f"{st.exe_found}  [{st.exe_source}]" if st.exe_found else "(未找到)"),
        ("数据目录", f"{st.datas_dir}  {'✓存在' if st.datas_exists else '✗不存在'}"),
        ("全局 lx", f"在 PATH ✓  ({st.global_lx_path})" if st.global_lx_on_path
                    else "不在 PATH（仅本地/run.py 可用）"),
        ("离线安装包", "内置 wheels ✓" if st.offline_wheels_available else "无"),
    ]
    for k, v in rows:
        lines.append(f"  {k:10s}  {v}")
    if st.notes:
        lines.append("")
        lines.append("  提示：")
        for n in st.notes:
            lines.append(f"    • {n}")
    return "\n".join(lines)


@click.command("status-install")
@click.option("--json", "as_json", is_flag=True, help="输出结构化 JSON")
@pass_ctx
@wrap_errors
def status_install_cmd(ctx: Ctx, as_json: bool) -> None:
    """显示安装状态（版本/安装方式/位置/Python/exe/数据目录/全局可用性）。

    区别于 `--version`（只显示版本号）。
    """
    st = build_status(ctx)
    if as_json:
        click.echo(_json.dumps(asdict(st), ensure_ascii=False, indent=2))
    else:
        click.echo(_format_human(st))
