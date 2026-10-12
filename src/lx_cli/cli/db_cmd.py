"""数据库只读命令（``lx db`` / 歌单查询在 ``playlist.py``）。"""
from __future__ import annotations

import click

from ..core import db_reader
from ..errors import NoSuchListError
from ._common import Ctx, emit, json_option, pass_ctx, wrap_errors


@click.group("db")
def db_group() -> None:
    """数据库只读查询（LX 运行时也安全）。"""


@db_group.command("tables")
@json_option
@pass_ctx
@wrap_errors
def db_tables(ctx: Ctx) -> None:
    """列出所有表。"""
    tables = db_reader.list_tables(ctx.db_override, ctx.exe)
    emit(ctx, "\n".join(f"  {t}" for t in tables), {"tables": tables})


@db_group.command("info")
@json_option
@pass_ctx
@wrap_errors
def db_info(ctx: Ctx) -> None:
    """显示各表行数。"""
    tables = db_reader.list_tables(ctx.db_override, ctx.exe)
    counts = db_reader.row_counts(tables, ctx.db_override, ctx.exe)
    width = max((len(t) for t in counts), default=0)
    emit(ctx, "\n".join(f"  {t.ljust(width)}  {n}" for t, n in counts.items()),
         {"tables": counts})


@db_group.command("schema")
@click.argument("table")
@json_option
@pass_ctx
@wrap_errors
def db_schema(ctx: Ctx, table: str) -> None:
    """显示表结构。"""
    info = db_reader.table_info(table, ctx.db_override, ctx.exe)
    if not info:
        raise NoSuchListError(f"没有该表：{table}")
    lines = []
    for c in info:
        flags = []
        if c.get("pk"):
            flags.append("PK")
        if c.get("notnull"):
            flags.append("NOT NULL")
        if c.get("dflt_value") is not None:
            flags.append(f"DEFAULT {c['dflt_value']!r}")
        suffix = (" " + " ".join(flags)) if flags else ""
        lines.append(f"  {c['name']}: {c['type']}{suffix}")
    emit(ctx, "\n".join(lines), {"table": table, "columns": info})


@db_group.command("query")
@click.argument("sql")
@json_option
@pass_ctx
@wrap_errors
def db_query(ctx: Ctx, sql: str) -> None:
    """执行只读 SQL（写语句会被拒绝）。"""
    rows = db_reader.query(sql, db_override=ctx.db_override, exe_path=ctx.exe)
    if ctx.json:
        emit(ctx, "", {"rows": rows, "count": len(rows)})
        return
    if not rows:
        emit(ctx, "(无结果)", {"rows": [], "count": 0})
        return
    cols = list(rows[0])
    lines = [" | ".join(cols), "-" * (4 * len(cols))]
    for r in rows:
        lines.append(" | ".join(str(r.get(c, "")) for c in cols))
    emit(ctx, "\n".join(lines), {"rows": rows, "count": len(rows)})


@db_group.command("stats")
@json_option
@pass_ctx
@wrap_errors
def db_stats(ctx: Ctx) -> None:
    """库总体统计。"""
    st = db_reader.stats(ctx.db_override, ctx.exe)
    lines = [
        "总计:",
        f"  歌单数      {st['lists']}",
        f"  歌曲条目    {st['songs']}  （去重 {st['distinctSongs']}）",
        f"  排序行      {st['ordering']}",
        "",
        "按平台:",
    ]
    for src, n in st["songsBySource"].items():
        lines.append(f"  {src:8s} {n}")
    emit(ctx, "\n".join(lines), st)
