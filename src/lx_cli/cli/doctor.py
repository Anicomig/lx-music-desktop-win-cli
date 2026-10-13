"""``lx doctor`` —— 安装/配置/连通性自检。

按依赖顺序逐项检查；任何失败都给出**可执行的下一步**，不只是报错。
支持 ``--no-network``（跳过 search 连通检查）与 ``--json``（结构化输出）。
"""
from __future__ import annotations

import json as _json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

import click

from ..core import config_store, openapi_client
from ..core.launcher import is_running
from ..paths import config_v2_path, lx_datas_dir
from ._common import Ctx, pass_ctx, wrap_errors


# ------- 状态机 -------

OK = "ok"
WARN = "warn"
FAIL = "fail"
SKIP = "skip"


@dataclass
class Check:
    id: str
    name: str
    status: str
    detail: dict[str, Any] = field(default_factory=dict)
    fix_hint: str = ""
    fix_cmd: str = ""

    def to_row(self) -> str:
        sym = {"ok": "✓ OK ", "warn": "! WARN", "fail": "✗ FAIL",
               "skip": "- SKIP"}.get(self.status, "? ????")
        return f"  {sym}  {self.name}"


# ------- 各检查实现 -------

def _check_cli_version() -> Check:
    from lx_cli import __version__
    return Check("cli.version", f"CLI 版本 ({__version__})", OK,
                 {"version": __version__})


def _check_paths_resolve(ctx: Ctx) -> Check:
    """路径解析（LX exe / 数据目录）。"""
    from ..paths import find_exe
    exe, source = find_exe(ctx.exe)  # find_exe 接受 exe 作为关键字参数
    if not exe:
        return Check(
            "path.exe", "LX 可执行文件", FAIL,
            detail={"searched_via": source},
            fix_hint="找不到 LX Music Desktop 安装位置",
            fix_cmd="export LX_EXE=<path-to-lx-music-desktop.exe>")
    datas = lx_datas_dir()
    if not datas.is_dir():
        return Check(
            "path.data", "LX 数据目录", FAIL,
            detail={"datas": str(datas)},
            fix_hint="数据目录不存在；至少打开一次 LX 让它生成",
            fix_cmd="lx start --hidden")
    return Check("path.locate", "路径解析（exe + 数据目录）", OK,
                 {"exe": str(exe), "datas": str(datas)})


def _check_dependencies() -> Check:
    missing = []
    for mod, pkg in (("click", "click"), ("requests", "requests")):
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    if missing:
        return Check(
            "deps", "Python 依赖", FAIL,
            detail={"missing": missing},
            fix_hint=f"安装缺失包：{', '.join(missing)}",
            fix_cmd=f"python -m pip install {' '.join(missing)}")
    return Check("deps", "Python 依赖 (click + requests)", OK)


def _check_config_exists(ctx: Ctx) -> Check:
    try:
        p = config_v2_path(ctx.exe)
    except Exception as exc:
        return Check("config.path", "config_v2.json 路径解析", FAIL,
                     detail={"error": str(exc)},
                     fix_hint="LX 可能没安装或路径异常",
                     fix_cmd="lx where --json")
    if not p.is_file():
        return Check(
            "config.exists", "config_v2.json 存在", FAIL,
            detail={"path": str(p)},
            fix_hint="至少打开一次 LX 让它生成配置",
            fix_cmd="lx start --hidden")
    try:
        cfg = config_store.load_config(ctx.exe)
    except Exception as exc:
        return Check(
            "config.parse", "config_v2.json 可解析", FAIL,
            detail={"error": str(exc)},
            fix_hint="配置文件损坏；备份后让 LX 重写",
            fix_cmd="lx backup <dir>")
    return Check("config.read", "config_v2.json 可读", OK,
                 detail={"path": str(p), "keys": len(cfg)})


def _check_openapi_enabled(ctx: Ctx) -> Check:
    try:
        s = openapi_client.read_open_api_settings(ctx.exe)
    except Exception as exc:
        return Check("api.enabled", "开放 API 已启用", SKIP,
                     detail={"reason": str(exc)},
                     fix_hint="无法读 config，跳过",
                     fix_cmd="")
    if not s["enable"]:
        return Check(
            "api.enabled", "开放 API 已启用", FAIL,
            detail={"enable": False, "port": s["port"]},
            fix_hint="开放 API 未启用；需先关 LX 再启用",
            fix_cmd="lx config enable  # 需先关 LX；之后 lx start --hidden")
    return Check("api.enabled", f"开放 API 已启用 (port={s['port']})", OK,
                 detail={"port": s["port"], "bindLan": s["bindLan"]})


def _check_lx_running() -> Check:
    running = is_running()
    if not running:
        return Check("lx.running", "LX 进程在跑", WARN,
                     detail={"running": False},
                     fix_hint="LX 未运行；播放/状态功能不可用",
                     fix_cmd="lx start --hidden")
    return Check("lx.running", "LX 进程在跑", OK, detail={"running": True})


def _check_openapi_reachable(ctx: Ctx) -> Check:
    try:
        s = openapi_client.read_open_api_settings(ctx.exe)
    except Exception as exc:
        return Check("api.reach", "开放 API 连通", SKIP,
                     detail={"reason": str(exc)})
    if not s["enable"]:
        return Check("api.reach", "开放 API 连通", SKIP,
                     detail={"reason": "未启用"},
                     fix_cmd="lx config enable")
    ep = openapi_client.endpoints_from_config(ctx.exe)
    try:
        st = openapi_client.get_status(ep, timeout=3.0)
        if not ep.base.startswith("http://127.0.0.1"):
            return Check("api.reach", "开放 API 连通", FAIL,
                         detail={"host": ep.base},
                         fix_hint="连接目标非 127.0.0.1（应禁止 0.0.0.0）",
                         fix_cmd="lx --version  # 确认 ≥ 0.2.0（含 host 修复）")
        return Check("api.reach", f"开放 API 连通 (status={st.get('status')})",
                     OK, detail={"host": ep.base, "status": st.get("status")})
    except openapi_client.OpenApiDisabled as exc:
        return Check(
            "api.reach", "开放 API 连通", FAIL,
            detail={"error": str(exc)},
            fix_hint="端口没起来或服务未开；先关 LX → config enable → lx start",
            fix_cmd="lx stop && lx config enable && lx start --hidden")
    except openapi_client.OpenApiTimeout as exc:
        return Check(
            "api.reach", "开放 API 连通", FAIL,
            detail={"error": str(exc)},
            fix_hint="API 慢或没起来；可能 LX 启动中，等几秒再试",
            fix_cmd="lx start --wait")
    except Exception as exc:
        return Check(
            "api.reach", "开放 API 连通", FAIL,
            detail={"error": f"{type(exc).__name__}: {exc}"},
            fix_hint="连接异常；可能是代理或防火墙",
            fix_cmd="set NO_PROXY=127.0.0.1,localhost  # 临时兜底；新版已自动绕过代理")


def _check_search_reachable() -> Check:
    """反向代理检查：search 走外网，能通 = 代理仍可用。"""
    try:
        from ..sources import get_source
        result = get_source("kg").search("test", 1)
        n = len(result.list) if hasattr(result, "list") else 0
        if n == 0:
            return Check(
                "net.search", "外网搜索可达", WARN,
                detail={"platforms": getattr(result, "platform", "?")},
                fix_hint="搜索返回 0 结果；可能限流或代理异常；几秒后重试",
                fix_cmd="lx search 'test' --json")
        return Check("net.search", f"外网搜索可达 (kg {n} 首)", OK,
                     detail={"platforms": getattr(result, "platform", "?")})
    except Exception as exc:
        return Check(
            "net.search", "外网搜索可达", FAIL,
            detail={"error": f"{type(exc).__name__}: {exc}"},
            fix_hint="网络/代理/防火墙问题；检查系统代理设置",
            fix_cmd="lx search 'test' --json")


CHECKS: list[Callable[[Ctx], Check]] = [
    _check_cli_version,
    _check_paths_resolve,
    _check_dependencies,
    _check_config_exists,
    _check_openapi_enabled,
    _check_lx_running,
    _check_openapi_reachable,
    _check_search_reachable,
]


def _run(ctx: Ctx, no_network: bool) -> list[Check]:
    skip_ids = set()
    if no_network:
        skip_ids = {"api.reach", "net.search"}
    results: list[Check] = []
    for c in CHECKS:
        try:
            # 既支持 _check(ctx) 也支持 _check()（无参）
            import inspect
            chk = c(ctx) if inspect.signature(c).parameters else c()
        except Exception as exc:
            chk = Check(c.__name__, c.__doc__ or c.__name__, FAIL,
                        detail={"error": f"{type(exc).__name__}: {exc}"},
                        fix_hint="检查实现异常",
                        fix_cmd="lx --version")
        if chk.id in skip_ids:
            chk.status = SKIP
        results.append(chk)
    return results


def _format_human(checks: list[Check]) -> str:
    lines = ["", "lx-cli 自检报告：", ""]
    for c in checks:
        lines.append(c.to_row())
        if c.detail:
            for k, v in c.detail.items():
                v = str(v)
                if len(v) > 80:
                    v = v[:77] + "…"
                lines.append(f"          {k}: {v}")
        if c.status in (FAIL, WARN) and c.fix_hint:
            lines.append(f"          → {c.fix_hint}")
            if c.fix_cmd:
                lines.append(f"          运行: {c.fix_cmd}")
    n_ok = sum(1 for c in checks if c.status == OK)
    n_warn = sum(1 for c in checks if c.status == WARN)
    n_fail = sum(1 for c in checks if c.status == FAIL)
    n_skip = sum(1 for c in checks if c.status == SKIP)
    lines.append("")
    lines.append(
        f"汇总: {n_ok} ok  {n_warn} warn  {n_fail} fail  {n_skip} skip")
    if n_fail:
        lines.append("  退出码 1：有 fail，按上方建议逐项修复")
    elif n_warn:
        lines.append("  退出码 2：仅 warn，CLI 可用但有提示项")
    else:
        lines.append("  退出码 0：全部正常")
    return "\n".join(lines)


# ------- Click 命令 -------

@click.command("doctor")
@click.option("--no-network", is_flag=True,
              help="只做本地检查（跳过 API 连通与外网搜索）")
@click.option("--json", "as_json", is_flag=True, help="输出结构化 JSON")
@pass_ctx
@wrap_errors
def doctor_cmd(ctx: Ctx, no_network: bool, as_json: bool) -> None:
    """自检安装/配置/连通性；失败项给出可执行的下一步。"""
    checks = _run(ctx, no_network)
    if as_json:
        payload = {"checks": [asdict(c) for c in checks]}
        click.echo(_json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        click.echo(_format_human(checks))

    n_fail = sum(1 for c in checks if c.status == FAIL)
    n_warn = sum(1 for c in checks if c.status == WARN)
    if n_fail:
        raise SystemExit(1)
    if n_warn:
        raise SystemExit(2)
