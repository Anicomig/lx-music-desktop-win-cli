"""歌单读写命令（需求 D：对比现有歌单后插入 / 新建歌单）。

★ 核心是 ``lx playlist add --from-search``：
    搜索（平台元数据接口） → 与现有歌单比对 → 插入

**默认 ``--dry-run``**：先给出"将新增 N 首 / 已存在 M 首 / 疑似重复 K 首"的报告，
确认后再 ``--apply``。

去重口径（``--dedupe-by``）：

* ``id``（默认，保守）—— 按可落库的复合 id 比对（kg 为 ``<songId>_<hash>``）
* ``name+singer`` —— 按歌名+歌手比对（跨平台同曲识别）
* ``fuzzy`` —— 用 ``core.matcher``（±5s 时长 + 版本词判定）

比对是"是否已在目标歌单中"，与 LX 的 dislike 判据（``歌名@歌手``）思路一致。
"""
from __future__ import annotations

import json
from pathlib import Path

import click

from ..core import db_reader, db_writer
from ..core.matcher import find_duplicates
from ..core.musicinfo import decode_meta, source_label
from ..core.config_store import source_name_type
from ..errors import LxRunningError, NoSuchListError, UsageError
from ..sources.base import PLATFORMS, SourceError, SongRecord
from ..sources.search import search as do_search
from ._common import Ctx, emit, json_option, pass_ctx, wrap_errors


@click.group("playlist")
def playlist_group() -> None:
    """歌单查询与读写。"""


# --------------------------------------------------------------- 只读


@playlist_group.command("list")
@click.option("--user-only", is_flag=True, help="隐藏内置 default/love。")
@json_option
@pass_ctx
@wrap_errors
def list_cmd(ctx: Ctx, user_only: bool) -> None:
    """列出所有歌单。"""
    # ⚠️ 必须用关键字传参：list_lists 的第一个位置参数是 include_virtual，
    # 位置传参会把 db 路径当成 include_virtual，从而读到**默认库**而非 --db 指定的库。
    rows = db_reader.list_lists(db_override=ctx.db_override, exe_path=ctx.exe)
    if user_only:
        rows = [r for r in rows if not r["isVirtual"]]
    lines = ["  id".ljust(46) + "歌曲数  平台  名称"]
    lines.append("  " + "-" * 70)
    for r in rows:
        tag = "(内置)" if r["isVirtual"] else (r["source"] or "-")
        lines.append(f"  {r['id'].ljust(44)} {str(r['songCount']).rjust(5)}  "
                     f"{tag:6s} {r['name']}")
    emit(ctx, "\n".join(lines), {"lists": rows})


@playlist_group.command("show")
@click.argument("list_id")
@click.option("--limit", "-n", type=int, default=None)
@click.option("--offset", type=int, default=0)
@json_option
@pass_ctx
@wrap_errors
def show_cmd(ctx: Ctx, list_id: str, limit: int | None, offset: int) -> None:
    """显示歌单内容（按 LX 展示顺序）。"""
    info = db_reader.get_list(list_id, ctx.db_override, ctx.exe)
    if info is None:
        raise NoSuchListError(f"歌单不存在：{list_id}")
    songs = db_reader.songs_in_list(list_id, limit=limit, offset=offset,
                                    db_override=ctx.db_override, exe_path=ctx.exe)
    ntype = _name_type(ctx)
    lines = [f"# {info['name']}  ({info['id']})  共 {len(songs)} 首", ""]
    for i, s in enumerate(songs, 1 + (offset or 0)):
        meta = decode_meta(s.get("meta"))
        label = source_label(s.get("source"), name_type=ntype)
        lines.append(f"  {i:4d}. {s['name']}  —  {s['singer']}"
                     f"  · {meta.get('albumName') or '(无专辑)'}"
                     f"  [{s.get('source')}/{label}]  {s.get('interval') or ''}")
    emit(ctx, "\n".join(lines),
         {"list": info, "count": len(songs), "songs": songs})


@playlist_group.command("find")
@click.argument("pattern")
@click.option("--source", "-s", "sources", multiple=True, help="限定平台（可重复）。")
@click.option("--list", "list_id", default=None, help="限定歌单。")
@click.option("--limit", "-n", type=int, default=100, show_default=True)
@json_option
@pass_ctx
@wrap_errors
def find_cmd(ctx: Ctx, pattern: str, sources: tuple[str, ...],
             list_id: str | None, limit: int) -> None:
    """在**本地歌单**里搜索歌名/歌手。"""
    rows = db_reader.find_songs(pattern, sources=list(sources) or None,
                                list_id=list_id, limit=limit,
                                db_override=ctx.db_override, exe_path=ctx.exe)
    lines = [f"# 本地库匹配 {pattern!r}：{len(rows)} 条", ""]
    for r in rows:
        lines.append(f"  {r['name']}  —  {r['singer']}  [{r['source']}]"
                     f"  in {r['listId']}")
    emit(ctx, "\n".join(lines), {"count": len(rows), "songs": rows})


# --------------------------------------------------------------- 写


@playlist_group.command("create")
@click.argument("name")
@click.option("--position", type=int, default=None, help="侧栏位置（默认末尾）。")
@click.option("--force", is_flag=True, help="LX 运行时也写（危险）。")
@json_option
@pass_ctx
@wrap_errors
def create_cmd(ctx: Ctx, name: str, position: int | None, force: bool) -> None:
    """新建空歌单。"""
    db_writer.assert_lx_closed(force=force)
    row = db_writer.create_list(name, position=position,
                                db_override=ctx.db_override, exe_path=ctx.exe)
    emit(ctx, f"已新建歌单 {row['id']}  ({name!r})", row)


@playlist_group.command("rename")
@click.argument("list_id")
@click.argument("new_name")
@click.option("--force", is_flag=True)
@json_option
@pass_ctx
@wrap_errors
def rename_cmd(ctx: Ctx, list_id: str, new_name: str, force: bool) -> None:
    """重命名歌单（内置歌单不可改名）。"""
    db_writer.assert_lx_closed(force=force)
    ok = db_writer.rename_list(list_id, new_name,
                               db_override=ctx.db_override, exe_path=ctx.exe)
    if not ok:
        raise NoSuchListError(f"歌单不存在：{list_id}")
    emit(ctx, f"已改名：{list_id} → {new_name!r}", {"id": list_id, "name": new_name})


@playlist_group.command("delete")
@click.argument("list_id")
@click.option("--force", is_flag=True)
@json_option
@pass_ctx
@wrap_errors
def delete_cmd(ctx: Ctx, list_id: str, force: bool) -> None:
    """删除歌单（连同其中歌曲）。"""
    db_writer.assert_lx_closed(force=force)
    ok = db_writer.delete_list(list_id, db_override=ctx.db_override, exe_path=ctx.exe)
    if not ok:
        raise NoSuchListError(f"歌单不存在：{list_id}")
    emit(ctx, f"已删除歌单 {list_id}", {"id": list_id, "deleted": True})


@playlist_group.command("remove")
@click.argument("list_id")
@click.argument("song_ids", nargs=-1, required=True)
@click.option("--force", is_flag=True)
@json_option
@pass_ctx
@wrap_errors
def remove_cmd(ctx: Ctx, list_id: str, song_ids: tuple[str, ...],
               force: bool) -> None:
    """从歌单移除歌曲。"""
    db_writer.assert_lx_closed(force=force)
    n = db_writer.remove_songs(list_id, list(song_ids),
                               db_override=ctx.db_override, exe_path=ctx.exe)
    emit(ctx, f"已移除 {n} 首", {"listId": list_id, "removed": n})


# --------------------------------------------------------------- ★ 需求 D 主路径


def _name_type(ctx: Ctx) -> str:
    try:
        return source_name_type(ctx.exe)
    except Exception:
        return "real"


def _load_songs_from_json(path: str) -> list[SongRecord]:
    """从 ``lx search --json`` 的输出（或 ``-`` 表示 stdin）读取歌曲。"""
    import sys
    raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise UsageError(f"不是合法 JSON：{exc}") from exc

    items = data.get("songs") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise UsageError("JSON 里找不到歌曲数组（期望 {'songs': [...]} 或直接是数组）")

    out: list[SongRecord] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        platform = it.get("source") or ""
        songmid = str(it.get("songmid") or "")
        hash_ = None
        # kg 的 id 形如 <songId>_<hash>
        sid = it.get("id") or ""
        if platform == "kg":
            body = sid[3:] if sid.startswith("kg_") else sid
            if "_" in body:
                songmid, _, hash_ = body.partition("_")
        out.append(SongRecord(
            platform=platform, songmid=songmid,
            name=it.get("name") or "", singer=it.get("singer") or "",
            album_name=it.get("albumName") or "",
            album_id=str(it.get("albumId") or ""),
            interval=it.get("interval") or "",
            hash=hash_,
            types=[t for t in (it.get("types") or []) if isinstance(t, dict)],
        ))
    return out


def _existing_songs(ctx: Ctx, list_id: str) -> list[dict]:
    return db_reader.songs_in_list(list_id, db_override=ctx.db_override,
                                   exe_path=ctx.exe)


@playlist_group.command("add")
@click.argument("list_id")
@click.option("--from-search", "query", default=None,
              help="★ 先搜索再加：给出关键字（默认聚合全部平台）。")
@click.option("--from", "from_file", default=None,
              help="从 lx search --json 的输出文件导入（`-` 表示标准输入）。")
@click.option("--source", "-s", "source_one", default=None,
              help="限定单个平台。")
@click.option("--sources", "source_many", default=None,
              help="限定多个平台，逗号分隔。")
@click.option("--limit", "-n", type=int, default=30, show_default=True,
              help="搜索时每平台取多少条。")
@click.option("--dedupe-by", type=click.Choice(["id", "name+singer", "fuzzy"]),
              default="id", show_default=True, help="比对口径。")
@click.option("--top", is_flag=True, help="插到歌单开头（默认末尾）。")
@click.option("--apply", "apply_", is_flag=True,
              help="实际写入（**默认只 dry-run 报告**）。")
@click.option("--force", is_flag=True, help="LX 运行时也写（危险）。")
@json_option
@pass_ctx
@wrap_errors
def add_cmd(ctx: Ctx, list_id: str, query: str | None, from_file: str | None,
            source_one: str | None, source_many: str | None, limit: int,
            dedupe_by: str, top: bool, apply_: bool, force: bool) -> None:
    """把歌曲加入歌单。

    \b
    两种来源（二选一）：
      --from-search <关键字>   搜索后加入（默认聚合全部平台）
      --from <文件|->          从 lx search --json 的输出导入

    \b
    ★ 默认是 **dry-run**：只报告"将新增/已存在/疑似重复"，不写库。
      确认无误后加 --apply 才真正写入。

    \b
    示例：
      lx playlist add mylist --from-search "yorushika" --source kg      # 先看报告
      lx playlist add mylist --from-search "yorushika" --source kg --apply
      lx search "yorushika" --json | lx playlist add mylist --from - --apply
    """
    if bool(query) == bool(from_file):
        raise UsageError("必须（且只能）提供 --from-search 或 --from 之一")

    # ---- 1. 取候选歌曲 ----
    if query:
        if source_one and source_many:
            raise UsageError("--source 与 --sources 不能同时使用")
        plats = ([source_one.strip().lower()] if source_one
                 else ([p.strip().lower() for p in source_many.split(",") if p.strip()]
                       if source_many else None))
        unknown = [p for p in (plats or []) if p not in PLATFORMS]
        if unknown:
            raise UsageError(f"未知平台 {unknown[0]!r}（可用：{', '.join(PLATFORMS)}）")
        result = do_search(query, platforms=plats, page=1, limit=limit)
        candidates: list[SongRecord] = result["songs"]
        origin = {"kind": "search", "query": query,
                  "platforms": result["platforms"], "mode": result["mode"]}
    else:
        candidates = _load_songs_from_json(from_file)      # type: ignore[arg-type]
        origin = {"kind": "file", "path": from_file}

    # ---- 2. 目标歌单必须存在 ----
    info = db_reader.get_list(list_id, ctx.db_override, ctx.exe)
    if info is None:
        raise NoSuchListError(f"歌单不存在：{list_id}")

    # ---- 3. 与现有歌单比对 ----
    existing = _existing_songs(ctx, list_id)
    report = compare(candidates, existing, by=dedupe_by)

    # ---- 4. dry-run 或写入 ----
    ntype = _name_type(ctx)
    payload = {
        "listId": list_id,
        "listName": info["name"],
        "origin": origin,
        "dedupeBy": dedupe_by,
        "dryRun": not apply_,
        "existingCount": len(existing),
        "wouldAdd": report["wouldAdd"],
        "alreadyIn": report["alreadyIn"],
        "suspectDuplicates": report["suspectDuplicates"],
        "items": {
            "toAdd": [s.to_json(name_type=ntype) for s in report["to_add"]],
            "skipped": report["skipped_ids"],
            "suspect": report["suspect_info"],
        },
    }

    lines = [
        f"# {'[预演] ' if not apply_ else ''}歌单 {info['name']} ({list_id})",
        f"  现有 {len(existing)} 首；候选 {len(candidates)} 首（{origin['kind']}）",
        f"  比对口径：{dedupe_by}",
        "",
        f"  将新增      {report['wouldAdd']} 首",
        f"  已存在跳过  {report['alreadyIn']} 首",
        f"  疑似重复    {report['suspectDuplicates']} 首",
    ]
    if report["to_add"]:
        lines.append("")
        lines.append("  新增明细：")
        for s in report["to_add"][:20]:
            lines.append(f"    + [{s.platform}] {s.name} — {s.singer}")
        if len(report["to_add"]) > 20:
            lines.append(f"    … 其余 {len(report['to_add']) - 20} 首")
    if report["suspect_info"]:
        lines.append("")
        lines.append("  疑似重复（同名同歌手，可能已在列表中）：")
        for x in report["suspect_info"][:10]:
            lines.append(f"    ? {x['name']} — {x['singer']}")

    if not apply_:
        lines += ["", "这是预演，未写入任何数据。确认后加 --apply 执行。"]
    else:
        db_writer.assert_lx_closed(force=force)
        if not report["to_add"]:
            lines += ["", "没有需要新增的歌曲。"]
        else:
            res = db_writer.add_songs(
                list_id, [s.to_db_row(list_id) for s in report["to_add"]],
                position="top" if top else "bottom",
                db_override=ctx.db_override, exe_path=ctx.exe)
            payload["added"] = res["added"]
            lines += ["", f"已写入 {res['added']} 首。"]

    emit(ctx, "\n".join(lines), payload)


# --------------------------------------------------------------- 比对逻辑


def compare(candidates: list[SongRecord], existing: list[dict], *,
            by: str = "id") -> dict:
    """候选歌曲 vs 现有歌单 → 分类。

    :param by: ``id`` | ``name+singer`` | ``fuzzy``
    :returns: ``{to_add, wouldAdd, alreadyIn, suspectDuplicates, skipped_ids}``
    """
    existing_ids = {r.get("id") for r in existing}
    existing_keys = {
        ((r.get("name") or "").strip(), (r.get("singer") or "").strip())
        for r in existing
    }

    to_add: list[SongRecord] = []
    skipped: list[str] = []
    suspect: list[dict] = []
    seen: set[str] = set()

    for s in candidates:
        sid = s.to_song_id()
        if sid in seen:                       # 候选内部去重
            continue
        seen.add(sid)

        if by == "id":
            if sid in existing_ids:
                skipped.append(sid)
                continue
        else:
            key = ((s.name or "").strip(), (s.singer or "").strip())
            if by == "name+singer" and key in existing_keys:
                skipped.append(sid)
                continue
            if by == "fuzzy":
                from ..core.matcher import is_same_song
                if any(is_same_song(s.name, s.singer, s.interval,
                                    r.get("name") or "", r.get("singer") or "",
                                    r.get("interval") or "")
                       for r in existing):
                    skipped.append(sid)
                    continue

        to_add.append(s)

    # 疑似重复：待新增里，与现有同名同歌手但 id 不同的（跨平台同曲）
    for s in to_add:
        key = ((s.name or "").strip(), (s.singer or "").strip())
        if key in existing_keys:
            suspect.append({"name": s.name, "singer": s.singer,
                            "id": s.to_song_id()})

    return {
        "to_add": to_add,
        "wouldAdd": len(to_add),
        "alreadyIn": len(skipped),
        "skipped_ids": skipped,
        "suspectDuplicates": len(suspect),
        "suspect_info": suspect,
    }
