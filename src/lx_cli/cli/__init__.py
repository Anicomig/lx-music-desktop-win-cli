"""``lx`` 命令入口。

分层：

* 查询音乐 → ``sources/``（① 平台元数据接口）
* 播放控制 → Open API（当前状态）/ Scheme URL（指定歌曲）
* 歌单读写 → 直接操作 ``lx.data.db``
* 音源脚本 → ``scripts/``（② 只管安装/更新，不执行）

设计要点：

1. **不用 Click 的 standalone_mode**，自己接管退出码 —— 修掉旧版
   "except 分支是死代码、未捕获异常时 stdout/stderr 全空"的问题。
2. ``--json`` 时 stdout **只有 JSON**，日志走 stderr。
3. 每个命令的领域异常都会被翻译成稳定的错误 JSON + 退出码。
"""
from __future__ import annotations

import sys
from pathlib import Path

import click

from .. import __version__
from .._logging import setup_logging
from ..errors import EXIT_RUNTIME, exit_code_for
from ._common import Ctx
from . import (db_cmd, doctor, download, download_repair, music, player,
               playlist, proc, script, script_doctor, status_cmd, uninstall)

CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"],
                        max_content_width=100)


@click.group(context_settings=CONTEXT_SETTINGS,
             help="LX Music 桌面版命令行工具（AI 友好）。")
@click.option("--exe", "exe", default=None, type=click.Path(),
              help="lx-music-desktop.exe 路径（默认自动探测，或环境变量 LX_EXE）。")
@click.option("--db", "db_path", default=None, type=click.Path(),
              help="覆盖 lx.data.db 路径（测试夹具用）。")
@click.option("--data-dir", "data_dir", default=None, type=click.Path(),
              help="覆盖 LxDatas 目录。")
@click.option("-v", "--verbose", count=True,
              help="日志级别：-v INFO，-vv DEBUG（日志走 stderr）。")
@click.option("--show-secrets", is_flag=True,
              help="显示密钥类字段（默认脱敏）。")
@click.version_option(__version__, prog_name="lx")
@click.pass_context
def cli(ctx: click.Context, exe: str | None, db_path: str | None,
        data_dir: str | None, verbose: int, show_secrets: bool) -> None:
    setup_logging(verbose)
    ctx.obj = Ctx(
        exe_path=Path(exe) if exe else None,
        db_path=Path(db_path) if db_path else None,
        data_dir=Path(data_dir) if data_dir else None,
        show_secrets=show_secrets,
    )


# ---- 音乐查询（需求 C）----
cli.add_command(music.search_cmd, "search")
cli.add_command(music.song_cmd, "song")
cli.add_command(music.album_cmd, "album")
cli.add_command(music.leaderboard_cmd, "leaderboard")
cli.add_command(music.hot_cmd, "hot")
cli.add_command(music.source_list_cmd, "source-list")

# ---- 播放与状态 ----
cli.add_command(player.play_cmd, "play")
cli.add_command(player.pause_cmd, "pause")
cli.add_command(player.toggle_cmd, "toggle")
cli.add_command(player.next_cmd, "next")
cli.add_command(player.prev_cmd, "prev")
cli.add_command(player.seek_cmd, "seek")
cli.add_command(player.volume_cmd, "volume")
cli.add_command(player.mute_cmd, "mute")
cli.add_command(player.status_cmd, "status")
cli.add_command(player.lyric_cmd, "lyric")
cli.add_command(player.lyric_all_cmd, "lyric-all")   # 别名：与 Open API 端点同名
cli.add_command(player.collect_cmd, "collect")
cli.add_command(player.uncollect_cmd, "uncollect")

# ---- Scheme URL（播放指定歌曲等）----
cli.add_command(player.play_song_cmd, "play-song")
cli.add_command(player.search_play_cmd, "search-play")
cli.add_command(player.dislike_cmd, "dislike")
cli.add_command(player.open_list_cmd, "open-list")
cli.add_command(player.play_list_cmd, "play-list")

# ---- 进程与配置 ----
cli.add_command(proc.start_cmd, "start")
cli.add_command(proc.stop_cmd, "stop")
cli.add_command(proc.is_running_cmd, "is-running")
cli.add_command(proc.config_show_cmd, "config-show")
cli.add_command(proc.config_enable_cmd, "config-enable")
cli.add_command(proc.config_disable_cmd, "config-disable")
cli.add_command(proc.where_cmd, "where")
cli.add_command(proc.backup_cmd, "backup")

# ---- 歌单（需求 D）----
cli.add_command(playlist.playlist_group, "playlist")

# ---- 音源脚本（需求 B）----
cli.add_command(script.script_group, "script")
# 脚本体检：挂到 `lx script doctor` 下
script.script_group.add_command(script_doctor.script_doctor_cmd, "doctor")

# ---- 数据库 ----
cli.add_command(db_cmd.db_group, "db")

# ---- 自检与卸载 ----
cli.add_command(doctor.doctor_cmd, "doctor")
cli.add_command(status_cmd.status_install_cmd, "status-install")
cli.add_command(uninstall.uninstall_cmd, "uninstall")

# ---- 下载记录查询（只读）+ 借 JS 音源下载 ----
cli.add_command(download.download_group, "download")
download.download_group.add_command(download_repair.dl_repair, "repair")


def _fix_console_encoding() -> None:
    """Windows 控制台默认可能是 GBK，输出中文/符号会抛 UnicodeEncodeError。

    统一切到 UTF-8 + ``errors="replace"``，让 CLI 在任何中文 Windows 下都不崩
    （实测：``chcp 936`` 的 cmd 里跑 ``lx script list`` 会因 ``✓`` 之类字符崩溃）。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass          # 已被重定向到非文本流等，忽略


def _self_check() -> None:
    """启动自检：确认关键命令齐备，防"静默加载了旧版"。

    最常见的部署事故：本机若另有 editable 安装的**旧版** ``lx_cli``，
    不带本项目 ``src`` 时 Python 会优先找到旧版，
    表现为"命令莫名变少"（旧版没有 ``script``/``playlist add`` 等）。

    这里在关键命令缺失时**明确报错**，而不是让用户面对 "No such command"。
    包位置与版本记录到 DEBUG 日志（``-vv`` 可见）。
    """
    import logging
    import os
    logger = logging.getLogger("lx_cli")
    logger.debug("package: %s  version: %s",
                 os.path.abspath(__file__), __version__)

    required = {"search", "playlist", "script", "db", "where"}
    missing = required - set(cli.commands)
    if missing:
        sys.stderr.write(
            "lx: 错误：命令不完整，缺少 %s\n"
            "    这通常意味着加载到了**旧版** lx_cli。\n"
            "    请改用：python <cli-root>/run.py ...\n"
            "    或设置环境变量 PYTHONPATH=<cli-root>/src\n"
            % ", ".join(sorted(missing)))
        raise SystemExit(2)


def main(argv: list[str] | None = None) -> int:
    """程序入口。

    **不使用** Click 的 standalone 模式：自己捕获异常并映射退出码，
    保证任何失败都有明确输出（修旧版"静默 exit 1"的问题）。
    """
    _fix_console_encoding()
    _self_check()
    try:
        # standalone_mode=False 让 Click 抛异常而不是自己 sys.exit。
        # ⚠️ 注意：Click 会**内部消化** click.exceptions.Exit，
        # 并把退出码作为**返回值**给出 —— 所以必须用它的返回值当退出码，
        # 否则 wrap_errors 抛出的 Exit(2) 会被吞掉，进程仍返回 0。
        rv = cli.main(args=argv, prog_name="lx", standalone_mode=False)
        return int(rv) if isinstance(rv, int) else 0
    except click.UsageError as exc:
        click.echo(f"lx: {exc.format_message()}", err=True)
        return 2
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code
    except click.exceptions.Exit as exc:          # 兜底（正常不会走到）
        return exc.exit_code
    except click.Abort:
        click.echo("lx: 已中止", err=True)
        return 130
    except KeyboardInterrupt:
        click.echo("lx: 已中断", err=True)
        return 130
    except Exception as exc:                     # noqa: BLE001
        # 兜底：任何未预期异常都必须有输出（旧版这里会静默退出）
        code = exit_code_for(exc)
        click.echo(f"lx: {type(exc).__name__}: {exc}", err=True)
        if "--debug-trace" in (argv or sys.argv):
            raise
        return code if code != 0 else EXIT_RUNTIME


if __name__ == "__main__":
    sys.exit(main())
