"""``lx download repair`` —— 批量重下失败曲（CLI 自己下载）。

本命令是 ``download failed-all`` 的**同义更短入口**（保留向后兼容）。
两者共用 ``download.batch`` 引擎。

★ 默认预演，加 ``--apply`` 才真正下载。
"""
from __future__ import annotations

import sys

import click

from ..download import batch
from ._common import Ctx, emit, json_option, pass_ctx, wrap_errors
from .download import _require_node, _resolve_script
from .download_batch import _progress_printer, _summary


@click.command("repair")
@click.option("--out", "-o", "out_dir", required=True, help="下载目录。")
@click.option("--quality", "-q", default=None,
              help="重下时请求的音质（默认沿用原记录音质）。")
@click.option("--script", "script_name", default=None,
              help="指定音源脚本（默认用当前启用的）。")
@click.option("--limit", "-n", type=int, default=None,
              help="最多处理几首（默认全部）。")
@click.option("--source", "-s", default=None, help="只处理某个平台。")
@click.option("--apply", "apply_", is_flag=True,
              help="真正下载（默认只预演）。")
@click.option("--overwrite", is_flag=True, help="已存在也覆盖。")
@click.option("--report", "report_path", default=None,
              help="把结果清单写成 JSON 文件。")
@json_option
@pass_ctx
@wrap_errors
def dl_repair(ctx: Ctx, out_dir: str, quality: str | None,
              script_name: str | None, limit: int | None, source: str | None,
              apply_: bool, overwrite: bool, report_path: str | None) -> None:
    """批量重下失败曲（CLI 自己下载，不走 LX）。

    与 ``download failed-all`` 等价；默认只预演。
    """
    items = batch.items_from_failed(source=source, quality=quality,
                                    limit=limit,
                                    db_override=ctx.db_override,
                                    exe_path=ctx.exe)
    if not items:
        emit(ctx, "没有需要修复的失败曲。", {"total": 0, "items": []})
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
