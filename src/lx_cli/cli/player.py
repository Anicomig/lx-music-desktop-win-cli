"""播放控制与状态命令。

通道分工（见 ``docs/CONVENTIONS.md`` §4）：

* **Open API** —— 播放/暂停/切歌/音量/静音/收藏当前曲/读状态歌词（有返回值，快）
* **Scheme URL** —— 播放**指定**歌曲 / 搜索并播放 / 打开歌单 / 不喜欢（无返回值，慢）

⚠️ 状态相关的坑（实测）：
* Open API 的 ``status`` 是**字符串**（``playing``/``paused``/``error``/``stoped``）
* 控制命令发出后状态**不是立即**变化的（约 1s 后才生效）
* Scheme URL 切歌过程中 ``status`` 会短暂为 ``error``
"""
from __future__ import annotations

import click

from ..core import openapi_client as api
from ..core import scheme_url as scheme
from ..core.launcher import is_running
from ..errors import LxNotRunningError, UsageError
from ._common import Ctx, emit, json_option, parse_offset, pass_ctx, wrap_errors


def _ep(ctx: Ctx):
    return api.endpoints_from_config(ctx.exe)


def _require_running() -> None:
    if not is_running():
        raise LxNotRunningError(
            "LX Music 未在运行。\n"
            "启动：lx start --hidden\n"
            "或先启用开放 API：lx config enable")


# --------------------------------------------------------------- 播放控制


@click.command("play")
@json_option
@pass_ctx
@wrap_errors
def play_cmd(ctx: Ctx) -> None:
    """播放（恢复）。"""
    _require_running()
    api.play(_ep(ctx))
    emit(ctx, "OK (play)", {"action": "play",
                            "note": "状态变更非同步，稍后可用 lx status 确认"})


@click.command("pause")
@json_option
@pass_ctx
@wrap_errors
def pause_cmd(ctx: Ctx) -> None:
    """暂停。"""
    _require_running()
    api.pause(_ep(ctx))
    emit(ctx, "OK (pause)", {"action": "pause"})


@click.command("toggle")
@json_option
@pass_ctx
@wrap_errors
def toggle_cmd(ctx: Ctx) -> None:
    """切换播放/暂停。

    ★ 按 status **字符串**判断（旧版把它当布尔，导致永远只暂停）。
    """
    _require_running()
    action = api.toggle(_ep(ctx))
    emit(ctx, f"OK ({action})", {"action": action})


@click.command("next")
@json_option
@pass_ctx
@wrap_errors
def next_cmd(ctx: Ctx) -> None:
    """下一曲。"""
    _require_running()
    api.skip_next(_ep(ctx))
    emit(ctx, "OK (next)", {"action": "skip-next"})


@click.command("prev")
@json_option
@pass_ctx
@wrap_errors
def prev_cmd(ctx: Ctx) -> None:
    """上一曲。"""
    _require_running()
    api.skip_prev(_ep(ctx))
    emit(ctx, "OK (prev)", {"action": "skip-prev"})


@click.command("seek")
@click.argument("offset")
@json_option
@pass_ctx
@wrap_errors
def seek_cmd(ctx: Ctx, offset: str) -> None:
    """跳转到指定位置（秒 / m:ss / h:mm:ss）。"""
    _require_running()
    secs = parse_offset(offset)
    api.seek(_ep(ctx), secs)
    emit(ctx, f"OK (seek {secs}s)", {"action": "seek", "offset": secs})


@click.command("volume")
@click.argument("level", type=int)
@json_option
@pass_ctx
@wrap_errors
def volume_cmd(ctx: Ctx, level: int) -> None:
    """设置音量（0-100）。"""
    _require_running()
    if not 0 <= level <= 100:
        raise UsageError(f"音量必须在 0-100，收到 {level}")
    api.set_volume(_ep(ctx), level)
    emit(ctx, f"OK (volume {level})", {"action": "volume", "volume": level})


@click.command("mute")
@click.argument("state", type=click.Choice(["on", "off"]))
@json_option
@pass_ctx
@wrap_errors
def mute_cmd(ctx: Ctx, state: str) -> None:
    """静音开/关。"""
    _require_running()
    api.set_mute(_ep(ctx), state == "on")
    emit(ctx, f"OK (mute {state})", {"action": "mute", "mute": state == "on"})


# --------------------------------------------------------------- 状态


@click.command("status")
@click.option("--filter", "filter_keys", default=None,
              help="逗号分隔字段名，如 status,name,singer,progress")
@json_option
@pass_ctx
@wrap_errors
def status_cmd(ctx: Ctx, filter_keys: str | None) -> None:
    """显示当前播放状态。"""
    _require_running()
    keys = [k.strip() for k in filter_keys.split(",")] if filter_keys else None
    st = api.get_status(_ep(ctx), filter_keys=keys)

    playing = api.is_playing(st)
    name = st.get("name") or "(无歌曲)"
    singer = st.get("singer") or ""
    state = st.get("status") or ""

    parts = [name]
    if singer:
        parts.append(f"— {singer}")
    if state:
        parts.append(f"| {state}")
    prog, dur = st.get("progress"), st.get("duration")
    if prog is not None and dur:
        parts.append(f"  {prog:.1f}/{dur:.1f}s")
    if "volume" in st:
        vol = st["volume"]
        parts.append(f"  vol={vol:.2f}" + (" (静音)" if st.get("mute") else ""))

    emit(ctx, " ".join(str(p) for p in parts),
         {"playing": playing, **st})


@click.command("lyric")
@click.option("--all", "all_variants", is_flag=True, help="输出全部歌词类型。")
@json_option
@pass_ctx
@wrap_errors
def lyric_cmd(ctx: Ctx, all_variants: bool) -> None:
    """显示**当前播放曲**的歌词。

    注意：这是 Open API 的当前歌词；按 songmid 查歌词请用 ``lx lyric-source``。
    """
    _require_running()
    if all_variants:
        data = api.get_lyric_all(_ep(ctx))
        emit(ctx, "\n".join(f"[{k}]\n{v}" for k, v in data.items()
                            if isinstance(v, str) and v), data)
    else:
        text = api.get_lyric(_ep(ctx))
        emit(ctx, text, {"lyric": text})


# 别名：Open API 端点叫 /lyric-all，加个别名避免"端点名误当命令名"
lyric_all_cmd = lyric_cmd
lyric_all_cmd.name = "lyric-all"


# --------------------------------------------------------------- Scheme URL


@click.command("play-song")
@click.option("--name", required=True, help="歌曲名。")
@click.option("--singer", required=True, help="歌手名。")
@click.option("--source", "-s", "platform", required=True,
              help="平台（kg/kw/tx/mg/wy）。")
@click.option("--songmid", required=True, help="歌曲 songmid（或完整 id）。")
@click.option("--hash", "hash_", default=None, help="kg 平台必传。")
@click.option("--mediemid", "str_media_mid", default=None, help="tx 平台必传 strMediaMid。")
@click.option("--copyright-id", default=None, help="mg 平台必传 copyrightId。")
@click.option("--quality", default="320k", show_default=True,
              help="期望音质。")
@click.option("--no-types", is_flag=True,
              help="不自动探测音质（默认会先查一次以取得 types）。")
@json_option
@pass_ctx
@wrap_errors
def play_song_cmd(ctx: Ctx, name: str, singer: str, platform: str,
                  songmid: str, hash_: str | None, str_media_mid: str | None,
                  copyright_id: str | None, quality: str,
                  no_types: bool) -> None:
    """**播放指定歌曲**（Scheme URL）—— Open API 做不到的能力。

    \b
    示例：
      lx play-song --name 老人と海 --singer ヨルシカ --source kg \\
                   --songmid 116989871 --hash 8B4D0B91A150C3BE70058F5D8A668876
    """
    # 直接传完整 id 时自动拆出 songmid（kg 还要 hash）
    sid = songmid
    if platform == "kg":
        if sid.startswith("kg_"):
            sid = sid[3:]
        if hash_ is None and "_" in sid:
            sid, _, hash_ = sid.partition("_")
    elif sid.startswith(f"{platform}_"):
        sid = sid[len(platform) + 1:]

    # 自动补 types / 平台特有字段：查一次平台接口
    types: list[dict] = []
    if not no_types:
        try:
            from ..sources import get_source
            rec = (get_source(platform).song(sid, hash_=hash_)      # type: ignore[call-arg]
                   if platform == "kg" else get_source(platform).song(sid))
            types = [{"type": t.get("type")} for t in rec.types if t.get("type")]
            hash_ = hash_ or rec.hash
            str_media_mid = str_media_mid or rec.extra.get("strMediaMid")
            copyright_id = copyright_id or rec.extra.get("copyrightId")
            name = name or rec.name
            singer = singer or rec.singer
        except Exception as exc:                  # noqa: BLE001
            # 探测失败不阻断：用用户给的 quality 兜底
            types = [{"type": quality}]

    if not types:
        types = [{"type": quality}]

    url = scheme.play_song(
        name=name, singer=singer, source=platform, songmid=sid,
        types=types, hash_=hash_, str_media_mid=str_media_mid,
        copyright_id=copyright_id, exe_path=ctx.exe,
    )
    emit(ctx, f"OK 已请求播放：{name} — {singer}（{platform}）",
         {"action": "play-song", "url": url, "types": types,
          "note": "Scheme URL 无返回值；LX 需先启动，实际播放状态请用 lx status 确认"})


@click.command("search-play")
@click.argument("name")
@click.option("--singer", default=None, help="歌手名（提高匹配准确率）。")
@click.option("--album", "album_name", default=None)
@click.option("--later", is_flag=True, help="稍后播放（加入队列而非立即播放）。")
@json_option
@pass_ctx
@wrap_errors
def search_play_cmd(ctx: Ctx, name: str, singer: str | None,
                    album_name: str | None, later: bool) -> None:
    """**搜索并播放**（Scheme URL，模糊匹配，无需 songmid）。"""
    url = scheme.search_play(name=name, singer=singer, album_name=album_name,
                             play_later=later, exe_path=ctx.exe)
    emit(ctx, f"OK 已请求搜索并播放：{name}",
         {"action": "search-play", "url": url})


@click.command("dislike")
@json_option
@pass_ctx
@wrap_errors
def dislike_cmd(ctx: Ctx) -> None:
    """不喜欢当前播放的歌曲（Scheme URL —— Open API 无此能力）。"""
    url = scheme.simple("dislike", exe_path=ctx.exe)
    emit(ctx, "OK (dislike)", {"action": "dislike", "url": url})


@click.command("open-list")
@click.argument("platform")
@click.argument("list_id")
@json_option
@pass_ctx
@wrap_errors
def open_list_cmd(ctx: Ctx, platform: str, list_id: str) -> None:
    """打开歌单（Scheme URL）。"""
    url = scheme.open_songlist(source=platform, list_id=list_id, exe_path=ctx.exe)
    emit(ctx, f"OK 已请求打开歌单 {list_id}", {"action": "open-list", "url": url})


@click.command("play-list")
@click.argument("platform")
@click.argument("list_id")
@click.option("--index", type=int, default=None, help="从第几首开始（0 起）。")
@json_option
@pass_ctx
@wrap_errors
def play_list_cmd(ctx: Ctx, platform: str, list_id: str,
                  index: int | None) -> None:
    """播放歌单（Scheme URL）。"""
    url = scheme.play_songlist(source=platform, list_id=list_id, index=index,
                               exe_path=ctx.exe)
    emit(ctx, f"OK 已请求播放歌单 {list_id}", {"action": "play-list", "url": url})


# --------------------------------------------------------------- 收藏


@click.command("collect")
@json_option
@pass_ctx
@wrap_errors
def collect_cmd(ctx: Ctx) -> None:
    """收藏**当前播放**的歌曲（Open API）。"""
    _require_running()
    api.collect(_ep(ctx))
    emit(ctx, "OK (collect)", {"action": "collect"})


@click.command("uncollect")
@json_option
@pass_ctx
@wrap_errors
def uncollect_cmd(ctx: Ctx) -> None:
    """取消收藏**当前播放**的歌曲（Open API）。"""
    _require_running()
    api.uncollect(_ep(ctx))
    emit(ctx, "OK (uncollect)", {"action": "uncollect"})
