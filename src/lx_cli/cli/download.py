"""``lx download`` —— 下载记录查询（只读）。

只读 ``download_list`` / ``music_url`` 表，**不发起下载、不修改任何数据**。
LX 运行时也安全。

> 注：LX 的下载动作只能在 GUI 里发起（Open API / Scheme URL 均无下载端点）。
> 本命令族负责"看清下载状况"，并把失败项整理成可操作的清单。
"""
from __future__ import annotations

import click

from ..core import db_reader
from ._common import Ctx, emit, json_option, pass_ctx, wrap_errors


@click.group("download")
def download_group() -> None:
    """下载记录查询与校验（只读）。"""


def _fmt_bytes(n: int) -> str:
    if not n:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} GB"


# --------------------------------------------------------------- stats

@download_group.command("stats")
@json_option
@pass_ctx
@wrap_errors
def dl_stats(ctx: Ctx) -> None:
    """下载总览（计数/状态/质量/来源/总字节）。"""
    s = db_reader.download_stats(db_override=ctx.db_override, exe_path=ctx.exe)

    lines = [
        f"下载记录: {s['total']} 条",
        f"  完成: {s['completed']}   失败: {s['failed']}   "
        f"未完成: {s['incomplete']}",
        f"  合计: {s['totalMB']} MB",
        "",
        "按状态:",
    ]
    for k, v in sorted(s["byStatus"].items(), key=lambda kv: -kv[1]):
        lines.append(f"  {k:12s} {v:4d}")
    lines.append("按质量:")
    for k, v in sorted(s["byQuality"].items(), key=lambda kv: -kv[1]):
        lines.append(f"  {k:12s} {v:4d}")
    if s["bySource"]:
        lines.append("按来源:")
        for k, v in sorted(s["bySource"].items(), key=lambda kv: -kv[1]):
            lines.append(f"  {k:12s} {v:4d}")
    emit(ctx, "\n".join(lines), s)


# --------------------------------------------------------------- list

@download_group.command("list")
@click.option("--status", default=None,
              help="过滤状态：completed/error/incomplete（未完成）等。")
@click.option("--source", "-s", default=None,
              help="过滤平台来源：kg/kw/tx/wy/mg。")
@click.option("--quality", "-q", default=None, help="过滤音质。")
@click.option("--limit", "-n", type=int, default=50, show_default=True,
              help="最多显示条数。")
@json_option
@pass_ctx
@wrap_errors
def dl_list(ctx: Ctx, status: str | None, source: str | None,
            quality: str | None, limit: int) -> None:
    """列出下载记录（逐条）。"""
    rows = db_reader.downloads(status=status, source=source, quality=quality,
                               limit=limit, db_override=ctx.db_override,
                               exe_path=ctx.exe)
    lines = [f"共 {len(rows)} 条", ""]
    for r in rows:
        mark = {"completed": "✓", "error": "✗"}.get(r["status"], "·")
        lines.append(f"  {mark} {r['name']} — {r['singer']}")
        lines.append(f"      [{r['source']}/{r['quality']}] {r['statusText']}"
                     f"  {r['percent']}%")
        lines.append(f"      {r['filePath']}")
    emit(ctx, "\n".join(lines), {"count": len(rows), "items": rows})


# --------------------------------------------------------------- failed

@download_group.command("failed")
@click.option("--limit", "-n", type=int, default=100, show_default=True,
              help="最多显示条数。")
@json_option
@pass_ctx
@wrap_errors
def dl_failed(ctx: Ctx, limit: int) -> None:
    """只列失败/未完成的下载（含原因与建议）。"""
    rows = db_reader.downloads(status="incomplete", limit=limit,
                               db_override=ctx.db_override, exe_path=ctx.exe)
    # 未完成里再分：error 与其它
    errs = [r for r in rows if r["status"] == db_reader.DL_ERROR]
    others = [r for r in rows if r["status"] != db_reader.DL_ERROR]

    lines = [f"失败 {len(errs)} 条，其它未完成 {len(others)} 条", ""]
    if errs:
        lines.append("失败明细（原因 → 建议）：")
        for r in errs:
            lines.append(f"  ✗ {r['name']} — {r['singer']}")
            lines.append(f"      [{r['source']}/{r['quality']}] {r['statusText']}")
            lines.append(f"      建议: {_hint(r['statusText'])}")
        lines.append("")
    if others:
        lines.append("其它未完成:")
        for r in others:
            lines.append(f"  · {r['name']}  [{r['status']}] {r['percent']}%")
    emit(ctx, "\n".join(lines), {
        "failed": len(errs),
        "incomplete": len(others),
        "items": rows,
    })


def _hint(status_text: str) -> str:
    """按错误文案给下一步建议（可操作的指引）。"""
    t = status_text or ""
    if "音乐链接" in t or "url" in t.lower() or "Invalid" in t:
        return ("脚本拿不到播放地址 → 检查【当前启用的音源脚本】是否有效"
                "（lx script doctor），可换脚本后重下")
    if "404" in t or "失效" in t:
        return "链接已失效 → 重新获取链接后重下"
    if "同名文件" in t:
        return "已存在同名文件被跳过 → 如需覆盖，先在 GUI 删除该文件再下"
    if "权限" in t or "占用" in t:
        return "文件被占用或无写权限 → 关闭占用程序或更换下载目录"
    return "在 LX GUI 中重新下载该曲（CLI 无法发起下载）"


# --------------------------------------------------------------- verify

@download_group.command("verify")
@click.option("--no-size", is_flag=True,
              help="只检查文件是否存在，不比对大小。")
@json_option
@pass_ctx
@wrap_errors
def dl_verify(ctx: Ctx, no_size: bool) -> None:
    """校验下载的文件是否真实存在（找出记录在但文件没了）。"""
    v = db_reader.verify_downloads(check_size=not no_size,
                                   db_override=ctx.db_override,
                                   exe_path=ctx.exe)
    lines = [
        f"记录 {v['total']} 条：存在 {v['present']}，"
        f"缺失 {v['missing']}，大小异常 {v['sizeMismatch']}",
    ]
    if v["missingItems"]:
        lines.append("")
        lines.append("文件缺失（记录在但磁盘没有）:")
        for r in v["missingItems"]:
            lines.append(f"  ✗ {r['name']} — {r['singer']}")
            lines.append(f"      {r['filePath']}")
    if v["sizeMismatchItems"]:
        lines.append("")
        lines.append("大小异常:")
        for r in v["sizeMismatchItems"]:
            lines.append(f"  ! {r['name']}  实际={_fmt_bytes(r['actualSize'])} "
                         f"期望={_fmt_bytes(r['expectedSize'])}")
    emit(ctx, "\n".join(lines), v)
