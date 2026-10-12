"""CLI 共用设施：上下文、输出、错误处理、装饰器。

修复旧版缺陷：

1. 旧版 ``main()`` 的 except 分支是**死代码**（Click standalone 模式先 ``sys.exit``），
   导致未捕获异常时"exit 1 + stdout/stderr 全空"。这里用 ``standalone_mode=False``
   自己接管退出码。
2. 旧版 ``--json`` 有 3 种实现风格、5 处违规。这里统一由 :func:`emit` 处理，
   并保证：**``--json`` 时 stdout 只有 JSON，日志一律走 stderr**。
3. 旧版 ``_jp``/``_j`` 重复定义。这里只留一组。
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click

from .._logging import setup_logging
from ..errors import LxCliError, UsageError, exit_code_for


@dataclass
class Ctx:
    """全局上下文（放 ``click.Context.obj``）。"""

    json: bool = False
    exe_path: Path | None = None
    db_path: Path | None = None
    data_dir: Path | None = None
    show_secrets: bool = False

    # ---- 便捷取用 ----

    @property
    def db_override(self) -> Path | None:
        return self.db_path

    @property
    def exe(self) -> Path | None:
        return self.exe_path


def pass_ctx(f):
    """注入 :class:`Ctx`（比裸 ``click.pass_context`` 更好用）。"""
    def wrapper(*args, **kwargs):
        ctx = click.get_current_context()
        obj = ctx.ensure_object(Ctx)
        return f(obj, *args, **kwargs)
    wrapper.__name__ = getattr(f, "__name__", "wrapper")
    wrapper.__doc__ = getattr(f, "__doc__", None)
    return click.pass_context(lambda c, *a, **k: wrapper(*a, **k))


def json_option(f):
    """给子命令挂 ``--json``，值存进 ``ctx.obj.json``。"""
    def _cb(ctx, _param, value):
        if value:
            ctx.ensure_object(Ctx).json = True
        return value
    return click.option(
        "--json", is_flag=True, default=False, is_eager=True,
        expose_value=False, callback=_cb,
        help="输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。",
    )(f)


def emit(ctx: Ctx, human: str, payload: Any) -> None:
    """统一输出。

    * ``--json`` → ``json.dumps(payload)``（**绝不掺日志**）
    * 否则       → 人类可读文本
    """
    if ctx.json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        click.echo(human)


def fail(ctx: Ctx, exc: LxCliError) -> int:
    """统一错误输出，返回退出码。"""
    if ctx.json:
        click.echo(json.dumps(exc.to_json(), ensure_ascii=False, indent=2))
    else:
        click.echo(f"lx: {exc.message}", err=True)
    return exit_code_for(exc)


def wrap_errors(fn):
    """把领域异常翻译成 Click 异常（保留退出码）。

    这样命令体里可以自由 raise ``LxCliError`` 子类，由这里统一收口。
    """
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except LxCliError as exc:
            ctx = click.get_current_context(silent=True)
            obj = ctx.ensure_object(Ctx) if ctx else Ctx()
            if obj.json:
                click.echo(json.dumps(exc.to_json(), ensure_ascii=False, indent=2))
            else:
                click.echo(f"lx: {exc.message}", err=True)
            raise click.exceptions.Exit(exit_code_for(exc)) from exc
    wrapper.__name__ = getattr(fn, "__name__", "wrapper")
    wrapper.__doc__ = getattr(fn, "__doc__", None)
    wrapper.__click_params__ = getattr(fn, "__click_params__", [])
    return wrapper


# --------------------------------------------------------------- 时间解析


def parse_offset(text: str) -> float:
    """解析 ``30`` / ``1:30`` / ``0:30.5`` 为秒。

    >>> parse_offset("30")
    30.0
    >>> parse_offset("1:30")
    90.0
    """
    s = text.strip()
    if ":" not in s:
        return float(s)
    parts = s.split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    raise UsageError(f"无法解析时间：{text!r}（可用 30 / 1:30 / 0:30.5）")


def parse_platforms(value: str | None) -> list[str] | None:
    """解析 ``--source`` / ``--sources`` 的值。

    ``None`` / ``"all"`` → 返回 ``None`` 表示"全部平台"。
    """
    if value is None:
        return None
    val = value.strip().lower()
    if val in ("", "all", "*"):
        return None
    return [p.strip() for p in val.split(",") if p.strip()]
