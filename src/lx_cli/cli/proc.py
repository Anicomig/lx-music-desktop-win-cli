"""进程控制与配置命令。"""
from __future__ import annotations

import json
from pathlib import Path

import click

from ..core import config_store as cfg
from ..core import launcher
from ..core.openapi_client import endpoints_from_config, wait_ready
from ..errors import PathError
from ..paths import (
    config_v2_path, data_json_path, db_path, find_exe, lx_datas_dir,
    scripts_meta_path, user_api_path, user_data_dir,
)
from ._common import Ctx, emit, json_option, pass_ctx, wrap_errors


# --------------------------------------------------------------- 进程


@click.command("start")
@click.option("--hidden/--show", default=True, show_default=True,
              help="--hidden 走托盘（默认），--show 显示窗口。")
@click.option("--wait/--no-wait", default=True, show_default=True,
              help="等待开放 API 就绪。")
@click.option("--wait-timeout", type=float, default=30.0, show_default=True)
@json_option
@pass_ctx
@wrap_errors
def start_cmd(ctx: Ctx, hidden: bool, wait: bool, wait_timeout: float) -> None:
    """启动 LX Music。"""
    if launcher.is_running():
        emit(ctx, "已在运行", {"running": True, "started": False})
        return
    launcher.start(ctx.exe, hidden=hidden)
    if wait:
        wait_ready(endpoints_from_config(ctx.exe), timeout=wait_timeout)
    emit(ctx, "已启动" + ("（托盘）" if hidden else ""),
         {"running": True, "started": True, "hidden": hidden})


@click.command("stop")
@click.option("--timeout", type=float, default=5.0, show_default=True)
@click.option("--force", is_flag=True, help="强制结束进程树。")
@json_option
@pass_ctx
@wrap_errors
def stop_cmd(ctx: Ctx, timeout: float, force: bool) -> None:
    """停止 LX Music（优雅退出失败会自动升级为强制）。"""
    if not launcher.is_running():
        emit(ctx, "未在运行", {"running": False})
        return
    ok = launcher.stop(timeout=timeout, force=force)
    if not ok and not force:
        ok = launcher.stop(timeout=timeout, force=True)
    emit(ctx, "已停止" if ok else "停止失败",
         {"running": not ok, "stopped": ok})


@click.command("is-running")
@json_option
@pass_ctx
@wrap_errors
def is_running_cmd(ctx: Ctx) -> None:
    """LX 是否在运行。"""
    running = launcher.is_running()
    emit(ctx, "yes" if running else "no", {"running": running})


# --------------------------------------------------------------- 配置


@click.command("config-show")
@json_option
@pass_ctx
@wrap_errors
def config_show_cmd(ctx: Ctx) -> None:
    """显示开放 API 与音源相关配置。"""
    s = cfg.load_config(ctx.exe)
    payload = {
        "openAPI.enable": bool(s.get("openAPI.enable", False)),
        "openAPI.port": str(s.get("openAPI.port") or ""),
        "openAPI.bindLan": bool(s.get("openAPI.bindLan", False)),
        "common.apiSource": s.get("common.apiSource"),
        "common.sourceNameType": s.get("common.sourceNameType"),
    }
    human = "\n".join(f"  {k} = {v}" for k, v in payload.items())
    emit(ctx, human, payload)


@click.command("config-enable")
@click.option("--port", default=None, help="端口（默认 23330）。")
@click.option("--bind-lan", is_flag=True, help="绑定 0.0.0.0（**无鉴权**，慎用）。")
@json_option
@pass_ctx
@wrap_errors
def config_enable_cmd(ctx: Ctx, port: str | None, bind_lan: bool) -> None:
    """启用开放 API（需重启 LX 生效）。"""
    if launcher.is_running():
        raise PathError("LX 正在运行：请先 lx stop，改完再 lx start（否则会被覆盖）")
    s = cfg.load_config(ctx.exe)
    s["openAPI.enable"] = True
    if port:
        s["openAPI.port"] = str(port)
    if bind_lan:
        s["openAPI.bindLan"] = True
    cfg.save_config(s, ctx.exe)
    emit(ctx, "已启用开放 API，请重启 LX", {
        "openAPI.enable": True,
        "openAPI.port": str(s.get("openAPI.port")),
        "openAPI.bindLan": bool(s.get("openAPI.bindLan")),
        "restart_required": True})


@click.command("config-disable")
@json_option
@pass_ctx
@wrap_errors
def config_disable_cmd(ctx: Ctx) -> None:
    """禁用开放 API。"""
    if launcher.is_running():
        raise PathError("LX 正在运行：请先 lx stop")
    s = cfg.load_config(ctx.exe)
    s["openAPI.enable"] = False
    cfg.save_config(s, ctx.exe)
    emit(ctx, "已禁用开放 API，请重启 LX",
         {"openAPI.enable": False, "restart_required": True})


# --------------------------------------------------------------- 路径


@click.command("where")
@json_option
@pass_ctx
@wrap_errors
def where_cmd(ctx: Ctx) -> None:
    """显示用到的数据路径。"""
    exe, _ = find_exe(ctx.exe)
    payload = {
        "exe": str(exe) if exe else "(未找到)",
        "userData": str(user_data_dir(ctx.exe)),
        "LxDatas": str(lx_datas_dir(ctx.exe)),
        "config_v2.json": str(config_v2_path(ctx.exe)),
        "data.json": str(data_json_path(ctx.exe)),
        "user_api.json": str(user_api_path(ctx.exe)),
        "lx.data.db": str(db_path(ctx.exe, ctx.db_override)),
        "scripts_meta.json": str(scripts_meta_path(ctx.exe)),
    }
    emit(ctx, "\n".join(f"  {k:20s} {v}" for k, v in payload.items()), payload)


# --------------------------------------------------------------- 备份


@click.command("backup")
@click.argument("dest_dir", type=click.Path(file_okay=False))
@click.option("--tag", default=None, help="自定义后缀（默认时间戳）。")
@json_option
@pass_ctx
@wrap_errors
def backup_cmd(ctx: Ctx, dest_dir: str, tag: str | None) -> None:
    """备份数据库（含 WAL）+ 配置 + 音源脚本。"""
    import datetime
    import hashlib
    import shutil

    src_db = db_path(ctx.exe, ctx.db_override)
    if not src_db.exists():
        raise PathError(f"找不到数据库：{src_db}")

    suffix = tag or datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(dest_dir) / f"lx-backup-{suffix}"
    out.mkdir(parents=True, exist_ok=True)

    files: dict[str, dict] = {}
    for f in (src_db, src_db.with_name(src_db.name + "-wal"),
              src_db.with_name(src_db.name + "-shm"),
              config_v2_path(ctx.exe), user_api_path(ctx.exe),
              data_json_path(ctx.exe)):
        if f.exists():
            shutil.copy2(f, out / f.name)
            files[f.name] = {
                "bytes": (out / f.name).stat().st_size,
                "sha256": hashlib.sha256(f.read_bytes()).hexdigest(),
            }

    meta = {
        "lx_running": launcher.is_running(),
        "userData": str(user_data_dir(ctx.exe)),
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "files": files,
    }
    (out / "MANIFEST.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    emit(ctx, f"已备份到 {out}\n" + "\n".join(f"  - {n}" for n in files),
         {"backup_dir": str(out), **meta})
