"""``lx download repair`` —— 批量重下失败曲（CLI 自己下载）。

从 ``download_list`` 里挑出失败/缺失的曲目，
用 JS 音源脚本重新取直链并下载到指定目录。

★ 默认 **预演**（``--dry-run`` 语义），加 ``--apply`` 才真正下载。
"""
from __future__ import annotations

import sys
import time

import click

from ..core import db_reader
from ..download import fetcher, jshost
from ._common import Ctx, emit, json_option, pass_ctx, wrap_errors
from .download import _require_node, _resolve_script, _suggest_filename


@click.command("repair")
@click.option("--out", "-o", "out_dir", required=True, help="下载目录。")
@click.option("--quality", "-q", default="320k", show_default=True,
              help="重下时请求的音质。")
@click.option("--script", "script_name", default=None,
              help="指定音源脚本（默认用当前启用的）。")
@click.option("--limit", "-n", type=int, default=20, show_default=True,
              help="最多处理几首。")
@click.option("--source", "-s", default=None,
              help="只处理某个平台。")
@click.option("--apply", "apply_", is_flag=True,
              help="真正下载（默认只预演）。")
@click.option("--overwrite", is_flag=True, help="已存在也覆盖。")
@json_option
@pass_ctx
@wrap_errors
def dl_repair(ctx: Ctx, out_dir: str, quality: str, script_name: str | None,
              limit: int, source: str | None, apply_: bool,
              overwrite: bool) -> None:
    """批量重下失败曲（CLI 自己下载，不走 LX）。

    默认只预演；确认后加 --apply。
    """
    rows = db_reader.downloads(status="incomplete", limit=limit,
                               db_override=ctx.db_override, exe_path=ctx.exe)
    errs = [r for r in rows if r["status"] == db_reader.DL_ERROR]
    if source:
        errs = [r for r in errs if r["source"] == source]
    if not errs:
        emit(ctx, "没有需要修复的失败曲。", {"count": 0, "items": []})
        return

    plan = [{"id": r["id"], "name": r["name"], "singer": r["singer"],
             "source": r["source"], "songmid": r["songmid"],
             "quality": r["quality"], "reason": r["statusText"]}
            for r in errs]

    if not apply_:
        lines = [f"预演：将重下 {len(errs)} 首到 {out_dir}", ""]
        for i, p in enumerate(plan, 1):
            lines.append(f"  {i:2d}. {p['name']} — {p['singer']}")
            lines.append(f"      [{p['source']}/{p['quality']}] "
                         f"原失败原因: {p['reason']}")
        lines.append("")
        lines.append("确认后加 --apply 执行。")
        emit(ctx, "\n".join(lines), {"dryRun": True, "count": len(plan),
                                     "items": plan})
        return

    _require_node()
    sname, code = _resolve_script(ctx, script_name)

    results = []
    ok_n = 0
    for p in plan:
        songmid = p["songmid"] or p["id"]
        r = jshost.fetch_url(code, source=p["source"], songmid=songmid,
                             quality=quality or p["quality"],
                             script_name=sname)
        if not r.ok:
            results.append({**p, "ok": False, "stage": r.stage,
                            "error": r.error})
            continue
        fname = _suggest_filename(ctx, songmid, p["source"], r.url)
        d = fetcher.download(r.url, out_dir, filename=fname,
                             overwrite=overwrite)
        results.append({**p, "ok": d.ok, "path": d.path,
                        "bytes": d.bytes, "error": d.error})
        if d.ok:
            ok_n += 1
        # 温和节流，避免触发平台限流
        time.sleep(0.3)

    fails = [x for x in results if not x["ok"]]
    lines = [f"完成：成功 {ok_n} / {len(results)}", ""]
    for x in results:
        mark = "✓" if x["ok"] else "✗"
        lines.append(f"  {mark} {x['name']} — {x['singer']}")
        if x["ok"]:
            lines.append(f"      → {x['path']}")
        else:
            lines.append(f"      失败: {x.get('error') or x.get('stage')}")
    emit(ctx, "\n".join(lines),
         {"ok": ok_n, "total": len(results), "items": results})
    if fails:
        sys.exit(4)
