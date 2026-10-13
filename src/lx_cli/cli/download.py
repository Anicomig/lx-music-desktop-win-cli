"""``lx download`` —— 下载记录查询 + 借 JS 音源下载。

* **只读子命令**（``stats`` / ``list`` / ``failed`` / ``verify``）：
  只读 ``download_list`` 表，LX 运行时也安全。
* **执行子命令**（``url`` / ``get``）：调用 Node sidecar 执行 JS 音源脚本
  取直链并下载。**一次性进程，用完即释放**。

> 注：LX 界面本身的下载动作 CLI 无法触发（Open API / Scheme URL
> 均无下载端点）。``url``/``get`` 是**CLI 自己下载**，不走 LX。
"""
from __future__ import annotations

import sys

import click

from ..core import db_reader
from ..download import fetcher, jshost
from ..errors import UsageError
from ..scripts import service as script_service
from ._common import Ctx, emit, json_option, pass_ctx, wrap_errors


@click.group("download")
def download_group() -> None:
    """下载：记录查询（只读）+ 借 JS 音源下载。

    只读：stats / list / failed / verify
    执行：url / get / repair（调用 Node 执行 JS 音源脚本）
    """


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


# --------------------------------------------------------------- 执行 JS 音源

def _resolve_script(ctx: Ctx, want: str | None) -> tuple[str, str]:
    """返回 (脚本名, 源码)。want 为空时用当前启用的。"""
    rows = script_service.list_scripts(exe_path=ctx.exe)
    if not rows:
        raise UsageError("没有已安装的音源脚本。先跑 lx script install <名字> --apply")

    target = None
    if want:
        for r in rows:
            if want in (r.get("id"), r.get("name")):
                target = r
                break
        if target is None:
            names = ", ".join(r.get("name", "?") for r in rows)
            raise UsageError(f"找不到脚本 {want!r}。已装：{names}")
    else:
        active = script_service.get_active_source(exe_path=ctx.exe)
        for r in rows:
            if r.get("id") == active:
                target = r
                break
        if target is None:
            target = rows[0]

    # 取明文源码
    from ..scripts import store as script_store
    code = ""
    for e in script_store.load_entries(exe_path=ctx.exe):
        if getattr(e, "id", None) == target.get("id"):
            code = getattr(e, "script", "") or ""
            break
    if not code:
        raise UsageError(f"无法读取脚本源码：{target.get('name')}")
    return target.get("name", ""), code


def _suggest_filename(ctx: Ctx, songmid: str, source: str,
                      url: str) -> str | None:
    """用库里的歌曲信息生成文件名（'歌名 - 歌手.mp3'）。

    库里查不到就返回 None，让 fetcher 从 URL 推断。
    """
    try:
        sid = f"{source}_{songmid}" if source != "kg" else songmid
        rows = db_reader.query(
            "SELECT name, singer, interval FROM my_list_music_info "
            "WHERE id = ? LIMIT 1", (sid,),
            db_override=ctx.db_override, exe_path=ctx.exe)
        # 兜底：kg 的 id 形如 <songmid>_<hash>
        if not rows and source == "kg":
            rows = db_reader.query(
                "SELECT name, singer, interval FROM my_list_music_info "
                "WHERE id LIKE ? LIMIT 1", (f"{songmid}_%",),
                db_override=ctx.db_override, exe_path=ctx.exe)
        if rows:
            name = rows[0].get("name") or ""
            singer = rows[0].get("singer") or ""
            if name:
                ext = fetcher.guess_ext(url)
                return fetcher.safe_filename(
                    f"{name} - {singer}" if singer else name, ext)
    except Exception:                               # noqa: BLE001
        pass
    return None


def _require_node() -> None:
    if not jshost.node_available():
        rep = jshost.doctor_report()
        raise UsageError(
            "未找到可用的 Node 运行时（执行 JS 音源脚本必需）。\n"
            f"  宿主脚本: {rep['hostScript']}  "
            f"{'✓' if rep['hostScriptExists'] else '✗ 缺失'}\n"
            f"  Node    : {rep['node'] or '✗ 未找到'}  ({rep['nodeSource']})\n"
            "  解决：\n"
            "    • 安装 Node 并确保在 PATH 中，或\n"
            "    • 把便携版放到 <cli-root>/tools/node/node.exe，或\n"
            "    • 设置环境变量 LX_NODE=<node.exe 完整路径>")


@download_group.command("url")
@click.argument("songmid")
@click.option("--source", "-s", "source", required=True,
              help="平台标识：kg/kw/tx/wy/mg。")
@click.option("--quality", "-q", default="320k", show_default=True,
              help="期望音质：flac24bit/flac/320k/128k。")
@click.option("--script", "script_name", default=None,
              help="指定用哪个音源脚本（默认当前启用的）。")
@json_option
@pass_ctx
@wrap_errors
def dl_url(ctx: Ctx, songmid: str, source: str, quality: str,
           script_name: str | None) -> None:
    """取播放直链（不下载）。用 JS 音源脚本执行。

    用于排查"某首歌能不能取到地址"。
    """
    _require_node()
    name, code = _resolve_script(ctx, script_name)
    r = jshost.fetch_url(code, source=source, songmid=songmid,
                         quality=quality, script_name=name)
    payload = {**r.to_json(), "script": name}
    if r.ok:
        emit(ctx, f"直链: {r.url}\n  脚本: {name}  音质: {r.quality}  "
                  f"耗时: {r.elapsed_ms}ms", payload)
    else:
        emit(ctx, f"取直链失败（{r.stage}）: {r.error}\n  脚本: {name}",
             payload)
        sys.exit(4)


@download_group.command("get")
@click.argument("songmid")
@click.option("--source", "-s", "source", required=True,
              help="平台标识：kg/kw/tx/wy/mg。")
@click.option("--quality", "-q", default="320k", show_default=True)
@click.option("--out", "-o", "out_dir", required=True,
              help="下载目录。")
@click.option("--name", "fname", default=None,
              help="文件名（默认从直链推断）。")
@click.option("--script", "script_name", default=None,
              help="指定用哪个音源脚本（默认当前启用的）。")
@click.option("--overwrite", is_flag=True, help="已存在时覆盖。")
@json_option
@pass_ctx
@wrap_errors
def dl_get(ctx: Ctx, songmid: str, source: str, quality: str, out_dir: str,
           fname: str | None, script_name: str | None,
           overwrite: bool) -> None:
    """下载一首歌（CLI 自己下载，不走 LX）。

    流程：JS 音源取直链 → HTTP 下载 → 写盘。
    Node 进程**一次性使用，用完即释放**。
    """
    _require_node()
    name, code = _resolve_script(ctx, script_name)

    r = jshost.fetch_url(code, source=source, songmid=songmid,
                         quality=quality, script_name=name)
    if not r.ok:
        emit(ctx, f"取直链失败（{r.stage}）: {r.error}",
             {"ok": False, "stage": r.stage, "error": r.error,
              "script": name})
        sys.exit(4)

    # 文件名：优先用库里的"歌名 - 歌手"，否则从直链推断
    if not fname:
        fname = _suggest_filename(ctx, songmid, source, r.url)

    d = fetcher.download(r.url, out_dir, filename=fname,
                         overwrite=overwrite)
    payload = {
        "ok": d.ok, "path": d.path, "bytes": d.bytes, "error": d.error,
        "url": r.url, "source": source, "quality": r.quality, "script": name,
    }
    if d.ok:
        kind = fetcher.detect_audio_kind(d.path)
        payload["detectedFormat"] = kind
        warn = ""
        if r.quality.startswith("flac") and kind == "mp3":
            warn = ("\n  ⚠️ 注意：请求 flac 但实际是 MP3（音源脚本可能未真正提供无损）")
        emit(ctx, f"已下载: {d.path}  ({d.bytes/1024/1024:.2f} MB)"
                  f"\n  格式: {kind}{warn}", payload)
    else:
        emit(ctx, f"下载失败: {d.error}", payload)
        sys.exit(1)
