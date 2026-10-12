"""``lx search`` / ``lx song`` / ``lx album`` / ``lx lyric`` 等查询命令。

★ 需求 C：查询结果必须含 **作者 / 歌名 / 专辑 / 来源（kg,kw…）**。

搜索默认 **聚合全部平台**（与桌面端"全部"档一致），也可指定单平台或多平台。
数据来自 ① **平台元数据接口**（``sources/``），与 ② JS 音源脚本无关。
"""
from __future__ import annotations

import click

from ..core.config_store import source_name_type
from ..errors import UsageError
from ..sources import get_source, list_platforms
from ..sources.base import PLATFORMS, SourceError
from ..sources.search import search as do_search
from ._common import Ctx, emit, json_option, pass_ctx, wrap_errors

def _name_type(ctx: Ctx) -> str:
    try:
        return source_name_type(ctx.exe)
    except Exception:
        return "real"


# --------------------------------------------------------------- search


@click.command("search")
@click.argument("keyword")
@click.option("--source", "-s", "source_one", default=None,
              help="只查一个平台（kg/kw/tx/mg/wy）。")
@click.option("--sources", "source_many", default=None,
              help="查多个平台，逗号分隔（如 kg,wy）。")
@click.option("--all", "all_platforms", is_flag=True,
              help="聚合全部平台（默认行为）。")
@click.option("--limit", "-n", type=int, default=30, show_default=True,
              help="每平台返回条数。")
@click.option("--page", "-p", type=int, default=1, show_default=True)
@json_option
@pass_ctx
@wrap_errors
def search_cmd(ctx: Ctx, keyword: str, source_one: str | None,
               source_many: str | None, all_platforms: bool,
               limit: int, page: int) -> None:
    """搜索歌曲。

    默认聚合全部平台；用 --source 指定单平台，--sources 指定多平台。

    \b
    示例：
      lx search "yorushika"                 # 聚合全部平台
      lx search "yorushika" --source kg     # 只看酷狗
      lx search "yorushika" --sources kg,wy # 看酷狗+网易
      lx search "yorushika" --json          # 机器可读
    """
    if source_one and source_many:
        raise UsageError("--source 与 --sources 不能同时使用")

    if source_one:
        platforms = [source_one.strip().lower()]
    elif source_many:
        platforms = [p.strip().lower() for p in source_many.split(",") if p.strip()]
    else:
        platforms = None                      # None → 聚合全部

    unknown = [p for p in (platforms or []) if p not in PLATFORMS]
    if unknown:
        # 参数问题 → UsageError（退出码 2），不是平台接口错误（否则会报 4）
        raise UsageError(
            f"未知平台 {unknown[0]!r}（可用：{', '.join(PLATFORMS)}）",
            detail={"unknown": unknown, "available": list(PLATFORMS)},
        )

    result = do_search(keyword, platforms=platforms, page=page, limit=limit)
    ntype = _name_type(ctx)

    payload = {
        "keyword": keyword,
        "mode": result["mode"],
        "page": page,
        "count": len(result["songs"]),
        "platforms": result["platforms"],
        "failedPlatforms": result["failed"],
        "songs": [s.to_json(name_type=ntype) for s in result["songs"]],
    }

    # ---- 人类可读 ----
    lines: list[str] = []
    mode_label = {"single": "单平台", "multi": "多平台",
                  "aggregate": "聚合全部"}[result["mode"]]
    lines.append(f"# 搜索 {keyword!r} — {mode_label}（{len(result['songs'])} 首）")
    if result["failed"]:
        lines.append(f"# 注意：以下平台无结果或失败：{', '.join(result['failed'])}")
    lines.append("")
    for i, s in enumerate(result["songs"], 1):
        label = s.to_json(name_type=ntype)["sourceLabel"]
        lines.append(
            f"  {i:3d}. {s.name}  —  {s.singer or '(未知歌手)'}"
            f"  · {s.album_name or '(无专辑)'}"
            f"  [{s.platform}/{label}]  {s.interval or '--:--'}"
        )
        lines.append(f"       id={s.to_song_id()}")
    if not result["songs"]:
        lines.append("  (无结果)")

    emit(ctx, "\n".join(lines), payload)


# --------------------------------------------------------------- song


@click.command("song")
@click.argument("songmid")
@click.option("--source", "-s", "platform", required=True,
              type=click.Choice(list(PLATFORMS)),
              help="平台（kg/kw/tx/mg/wy）。")
@click.option("--hash", "hash_", default=None,
              help="kg 平台取单曲详情需要 hash（形状 <songId>_<hash> 的前半段可用 id）。")
@json_option
@pass_ctx
@wrap_errors
def song_cmd(ctx: Ctx, songmid: str, platform: str,
             hash_: str | None) -> None:
    """取单曲详情。

    \b
    示例：
      lx song 116989871 --source kg --hash 8B4D0B91A150C3BE70058F5D8A668876
      lx song kw_561640590 --source kw
    """
    # 允许直接传完整 id（形如 116989871_8B4D... 或 kw_561640590）
    sid = songmid
    if platform == "kg":
        if hash_ is None and "_" in sid:
            left, _, right = sid.partition("_")
            if sid.startswith("kg_"):
                left, _, right = sid[3:].partition("_")
            if right:
                sid, hash_ = left, right
        rec = get_source(platform).song(sid, hash_=hash_)      # type: ignore[call-arg]
    else:
        if sid.startswith(f"{platform}_"):
            sid = sid[len(platform) + 1:]
        rec = get_source(platform).song(sid)

    ntype = _name_type(ctx)
    j = rec.to_json(name_type=ntype)
    human = (f"# {rec.name}  —  {rec.singer}\n"
             f"  专辑：{rec.album_name or '(无)'}\n"
             f"  时长：{rec.interval or '(未知)'}\n"
             f"  来源：{rec.platform} ({j['sourceLabel']})\n"
             f"  音质：{', '.join(t.get('type', '') for t in rec.types) or '(无)'}\n"
             f"  id：{rec.to_song_id()}")
    emit(ctx, human, j)


# --------------------------------------------------------------- album


@click.command("album")
@click.argument("album_id")
@click.option("--source", "-s", "platform", required=True,
              type=click.Choice(list(PLATFORMS)))
@json_option
@pass_ctx
@wrap_errors
def album_cmd(ctx: Ctx, album_id: str, platform: str) -> None:
    """取专辑曲目。"""
    info = get_source(platform).album(album_id)
    ntype = _name_type(ctx)
    lines = [f"# {info.name}  —  {info.artist}  ({info.size} 首)", ""]
    for i, s in enumerate(info.songs, 1):
        lines.append(f"  {i:3d}. {s.name}  —  {s.singer}  {s.interval}")
    emit(ctx, "\n".join(lines), info.to_json())


# --------------------------------------------------------------- lyric


@click.command("lyric")
@click.argument("songmid")
@click.option("--source", "-s", "platform", required=True,
              type=click.Choice(list(PLATFORMS)))
@json_option
@pass_ctx
@wrap_errors
def lyric_cmd(ctx: Ctx, songmid: str, platform: str) -> None:
    """取歌词（从平台元数据接口，不是当前播放曲）。"""
    if platform not in get_source(platform).features and \
            "lyric" not in get_source(platform).features:
        raise SourceError(platform, "该平台不支持 lyric")
    data = get_source(platform).lyric(songmid)
    emit(ctx, data.get("lyric", ""), data)


# --------------------------------------------------------------- 其它


@click.command("leaderboard")
@click.option("--source", "-s", "platform", default="kw",
              type=click.Choice(list(PLATFORMS)), show_default=True)
@click.option("--board", "-b", default=None, help="榜单名或 id。")
@click.option("--limit", "-n", type=int, default=30, show_default=True)
@json_option
@pass_ctx
@wrap_errors
def leaderboard_cmd(ctx: Ctx, platform: str, board: str | None,
                    limit: int) -> None:
    """排行榜。"""
    src = get_source(platform)
    if "leaderboard" not in src.features:
        raise SourceError(platform, "该平台不支持 leaderboard")
    res = src.leaderboard(board, page=1, limit=limit)
    ntype = _name_type(ctx)
    lines = [f"# {platform} 排行榜（{len(res.list)} 首）", ""]
    for i, s in enumerate(res.list, 1):
        lines.append(f"  {i:3d}. {s.name}  —  {s.singer}  {s.interval}")
    emit(ctx, "\n".join(lines),
         {"source": platform, "count": len(res.list),
          "songs": [s.to_json(name_type=ntype) for s in res.list]})


@click.command("hot")
@click.option("--source", "-s", "platform", default="kg",
              type=click.Choice(list(PLATFORMS)), show_default=True)
@json_option
@pass_ctx
@wrap_errors
def hot_cmd(ctx: Ctx, platform: str) -> None:
    """热搜词。"""
    src = get_source(platform)
    if "hot" not in src.features:
        raise SourceError(platform, "该平台不支持 hot")
    words = src.hot()
    if not words:
        raise SourceError(platform, "该平台当前无热搜词数据")
    emit(ctx, "\n".join(f"  {w.keyword}  ({w.score})" for w in words),
         {"source": platform, "hot": [w.to_json() for w in words]})


@click.command("source-list")
@click.option("--features", is_flag=True, help="同时列出每平台支持的能力。")
@json_option
@pass_ctx
@wrap_errors
def source_list_cmd(ctx: Ctx, features: bool) -> None:
    """列出可用的平台元数据接口及其能力。"""
    from ..core.musicinfo import source_label
    ntype = _name_type(ctx)
    rows = []
    for p in list_platforms():
        s = get_source(p)
        rows.append({
            "platform": p,
            "label": source_label(p, name_type=ntype),
            "features": list(s.features),
        })

    lines = [f"# {len(rows)} 个平台元数据接口（来源：musicSdk 直连各平台官方域名）", ""]
    for r in rows:
        if features:
            lines.append(f"  {r['platform']:4s} {r['label']:8s}  [{','.join(r['features'])}]")
        else:
            lines.append(f"  {r['platform']:4s} {r['label']}")
    emit(ctx, "\n".join(lines), {"sources": rows})
