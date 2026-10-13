"""``lx download list-all`` / ``lx download failed-all`` —— 批量下载。

* ``download list-all <list>` —— 下载整个歌单
* ``download failed-all``       —— 批量重下失败/丢失的曲目

两者共用 ``download.batch`` 的批量引擎。
★ Node 宿主仍是一次性调用（每首一次），批量之间**无常驻进程**。
"""
from __future__ import annotations

import sys

import click

from ..download import batch
from ._common import Ctx, emit, json_option, pass_ctx, wrap_errors
from .download import _require_node, _resolve_script


def _summary(rep: batch.BatchReport, title: str) -> str:
    lines = [f"{title}", ""]
    if rep.dry_run:
        # 预演：只报告"将要处理什么"，不报成功/失败（没执行过）
        by_src: dict[str, int] = {}
        for it in rep.items:
            by_src[it.source] = by_src.get(it.source, 0) + 1
        lines.append(f"  将处理 {rep.total} 首（预演，未下载）")
        if by_src:
            dist = " · ".join(f"{k} {v}" for k, v in sorted(by_src.items()))
            lines.append(f"  来源分布: {dist}")
        lines.append("")
        lines.append("  前 20 首:")
        for it in rep.items[:20]:
            lines.append(f"    · {it.name} — {it.singer}  "
                         f"[{it.source}/{it.quality}]")
        if rep.total > 20:
            lines.append(f"    … 另有 {rep.total - 20} 首")
        lines.append("")
        lines.append("确认后加 --apply 执行。")
        return "\n".join(lines)

    lines.append(f"  共 {rep.total} 首 · 成功 {rep.ok_count} · "
                 f"跳过 {rep.skip_count} · 失败 {len(rep.fail_items)}")
    lines.append(f"  耗时 {rep.elapsed_s:.1f}s · 输出 {rep.out_dir}")
    lines.append("")
    fails = rep.fail_items
    if fails:
        lines.append("失败明细:")
        for it in fails[:30]:
            lines.append(f"  ✗ {it.name} — {it.singer}  [{it.source}]")
            lines.append(f"      {it.error}")
        if len(fails) > 30:
            lines.append(f"  … 另有 {len(fails)-30} 条，见 --report 输出")
    return "\n".join(lines)


def _progress_printer(total: int):
    """返回一个进度回调（人类可读模式下用）。"""
    state = {"last": 0}

    def cb(idx: int, tot: int, item: batch.BatchItem) -> None:
        if idx - state["last"] >= 1 or idx == tot:
            click.echo(f"  [{idx}/{tot}] {item.name} — {item.singer}",
                       err=True)
            state["last"] = idx
    return cb


# --------------------------------------------------------------- list-all

@click.command("list-all")
@click.argument("list_ref")
@click.option("--out", "-o", "out_dir", required=True, help="下载目录。")
@click.option("--quality", "-q", default="320k", show_default=True,
              help="请求音质（脚本不支持时会失败并记录）。")
@click.option("--script", "script_name", default=None,
              help="音源脚本（默认当前启用的）。")
@click.option("--apply", "apply_", is_flag=True,
              help="真正下载（默认只预演）。")
@click.option("--limit", "-n", type=int, default=None, help="只处理前 N 首。")
@click.option("--overwrite", is_flag=True, help="已存在也重新下载。")
@click.option("--report", "report_path", default=None,
              help="把结果清单写成 JSON 文件。")
@json_option
@pass_ctx
@wrap_errors
def dl_list_all(ctx: Ctx, list_ref: str, out_dir: str, quality: str,
                script_name: str | None, apply_: bool, limit: int | None,
                overwrite: bool, report_path: str | None) -> None:
    """批量下载**整个歌单**到目录。

    LIST_REF 可以是歌单 id 或名称。
    """
    # 支持传名称
    target = list_ref
    if not list_ref.startswith(("userlist_", "kg_", "kw_", "tx_", "wy_", "mg_",
                                "default", "love")):
        rows = db_reader_find(ctx, list_ref)
        if len(rows) == 1:
            target = rows[0]["id"]
        elif len(rows) > 1:
            names = ", ".join(f"{r['name']}({r['id']})" for r in rows[:5])
            raise click.UsageError(
                f"歌单名 {list_ref!r} 匹配到多个：{names}\n请用 id 精确指定。")
        else:
            raise click.UsageError(f"找不到歌单：{list_ref}")

    items = batch.items_from_playlist(target, quality=quality,
                                      db_override=ctx.db_override,
                                      exe_path=ctx.exe)
    if not items:
        emit(ctx, "该歌单没有可下载的在线歌曲。",
             {"total": 0, "items": []})
        return

    if apply_:
        _require_node()
        sname, code = _resolve_script(ctx, script_name)
    else:
        sname, code = (script_name or "(当前启用)"), ""

    rep = batch.run_batch(
        items, out_dir, script_code=code, script_name=sname,
        apply_=apply_, overwrite=overwrite, limit=limit,
        on_item=None if ctx.json else _progress_printer(len(items)))

    if report_path and apply_:
        p = batch.save_report(rep, report_path)

    if ctx.json:
        emit(ctx, "", rep.to_json())
    else:
        txt = _summary(rep, f"歌单「{items[0].list_name or target}」批量下载")
        if report_path and apply_:
            txt += f"\n\n清单已写出：{report_path}"
        emit(ctx, txt, rep.to_json())

    if rep.fail_items and apply_:
        sys.exit(4)


def db_reader_find(ctx: Ctx, name: str):
    """按名称模糊找歌单。"""
    from ..core import db_reader
    all_lists = db_reader.list_lists(db_override=ctx.db_override,
                                     exe_path=ctx.exe)
    return [x for x in all_lists if name in (x.get("name") or "")]


# --------------------------------------------------------------- failed-all

@click.command("failed-all")
@click.option("--out", "-o", "out_dir", required=True, help="下载目录。")
@click.option("--quality", "-q", default=None,
              help="请求音质（默认沿用每条记录的原始音质）。")
@click.option("--script", "script_name", default=None)
@click.option("--source", "-s", default=None, help="只处理某个平台。")
@click.option("--limit", "-n", type=int, default=None, help="最多处理几首。")
@click.option("--apply", "apply_", is_flag=True,
              help="真正下载（默认只预演）。")
@click.option("--overwrite", is_flag=True)
@click.option("--report", "report_path", default=None,
              help="把结果清单写成 JSON 文件。")
@json_option
@pass_ctx
@wrap_errors
def dl_failed_all(ctx: Ctx, out_dir: str, quality: str | None,
                  script_name: str | None, source: str | None,
                  limit: int | None, apply_: bool, overwrite: bool,
                  report_path: str | None) -> None:
    """批量重下**所有失败/丢失**的歌曲。

    涵盖两类：下载报错的、以及记录在但文件已丢失的。
    """
    items = batch.items_from_failed(source=source, quality=quality,
                                    limit=limit,
                                    db_override=ctx.db_override,
                                    exe_path=ctx.exe)
    if not items:
        emit(ctx, "没有需要修复的歌曲。", {"total": 0, "items": []})
        return

    if apply_:
        _require_node()
        sname, code = _resolve_script(ctx, script_name)
    else:
        sname, code = (script_name or "(当前启用)"), ""

    rep = batch.run_batch(
        items, out_dir, script_code=code, script_name=sname,
        apply_=apply_, overwrite=overwrite,
        on_item=None if ctx.json else _progress_printer(len(items)))

    if report_path and apply_:
        batch.save_report(rep, report_path)

    if ctx.json:
        emit(ctx, "", rep.to_json())
    else:
        txt = _summary(rep, "失败曲批量重下")
        if report_path and apply_:
            txt += f"\n\n清单已写出：{report_path}"
        emit(ctx, txt, rep.to_json())

    if rep.fail_items and apply_:
        sys.exit(4)
