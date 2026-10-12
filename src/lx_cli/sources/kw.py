"""酷我音乐平台元数据接口。

⚠️ 酷我 ``search.kuwo.cn/r.s`` 返回**单引号 JSON**（非标准），需要修复。
本模块使用**状态机**版本（移植自旧版 lx-cli 的 ``_parse_kuwo_json``），
比正则替换更稳 —— 能正确处理字符串内的转义与结构性引号。

分页口径：酷我上游是 **0-based**（``pn = page - 1``），CLI 对外统一 1-based。
"""
from __future__ import annotations

import json
import re
import urllib.parse
from typing import Any

from .._logging import get_logger
from .base import (
    AlbumInfo, Comment, HotKeyword, LeaderboardEntry, PlatformSource,
    SearchResult, SongRecord, SourceError,
)
from .http import request_text

log = get_logger()

PLATFORM = "kw"

_BOARDS = [
    LeaderboardEntry("kw__93", "飙升榜", "93", "kw"),
    LeaderboardEntry("kw__17", "新歌榜", "17", "kw"),
    LeaderboardEntry("kw__16", "热歌榜", "16", "kw"),
    LeaderboardEntry("kw__158", "抖音热歌榜", "158", "kw"),
]


def parse_kuwo_json(raw: str) -> dict[str, Any]:
    """解析酷我的单引号 JSON。

    优先标准 ``json.loads``；失败则用状态机把单引号字符串转成双引号形式：

    * 非字符串区域：``'`` → ``"`` 并进入字符串态
    * 字符串内部：``"`` 转义为 ``\\"``；``'`` 后跟 ``,``/``:``/``}``/``]``/EOF
      视为结束，否则视为字面单引号
    * 处理 JS 风格的 ``''`` 转义
    """
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    out: list[str] = []
    in_str = False
    i = 0
    n = len(raw)
    while i < n:
        c = raw[i]
        if not in_str:
            if c == "'":
                out.append('"')
                in_str = True
            else:
                out.append(c)
            i += 1
        else:
            if c == "'":
                nxt = raw[i + 1] if i + 1 < n else ""
                if nxt == "'":
                    out.append("\\'")
                    i += 2
                elif nxt in (",", ":", "}", "]", ""):
                    out.append('"')
                    in_str = False
                    i += 1
                else:
                    out.append("\\'")
                    i += 1
            elif c == '"':
                out.append('\\"')
                i += 1
            else:
                out.append(c)
                i += 1
    try:
        return json.loads("".join(out))
    except ValueError as exc:
        raise SourceError(PLATFORM, f"酷我 JSON 解析失败：{raw[:160]!r}",
                          cause=exc) from exc


def _fmt_duration(secs: Any) -> str:
    try:
        s = int(float(secs or 0))
    except (TypeError, ValueError):
        return ""
    if s <= 0:
        return ""
    return f"{s // 60}:{s % 60:02d}"


def _types_from_nminfo(nminfo: str) -> list[dict[str, Any]]:
    """从 ``N_MINFO`` 解析音质，形如 ``level:xxx,bitrate:320,format:mp3,size:7.8MB``。"""
    out: list[dict[str, Any]] = []
    for token in (nminfo or "").split(";"):
        m = re.match(
            r"level:(\w+),bitrate:(\d+),format:(\w+),size:([\w.]+)", token.strip())
        if not m:
            continue
        bitrate, size_raw = m.group(2), m.group(4)
        qtype = {"4000": "flac24bit", "2000": "flac",
                 "320": "320k", "128": "128k"}.get(bitrate)
        if not qtype:
            continue
        item: dict[str, Any] = {"type": qtype}
        if size_raw and size_raw not in ("0", ""):
            # 酷我的 size 是 "7.8MB" 形式，统一加空格
            size = re.sub(r"([\d.]+)([A-Za-z]+)", r"\1 \2", size_raw)
            item["size"] = size
        out.append(item)
    # 去重（同一音质可能出现多次）
    seen: set[str] = set()
    dedup: list[dict[str, Any]] = []
    for t in out:
        if t["type"] in seen:
            continue
        seen.add(t["type"])
        dedup.append(t)
    return dedup


def _song(raw: dict) -> SongRecord:
    rid = str(raw.get("MUSICRID") or raw.get("musicrid") or "").replace("MUSIC_", "")
    singer = (raw.get("ARTIST") or raw.get("artist") or "")
    # 酷我用 '&' 连接多歌手；DB 口径是 '、'
    if "&" in singer and "、" not in singer:
        singer = singer.replace("&", "、")
    return SongRecord(
        platform=PLATFORM,
        songmid=rid,
        name=(raw.get("SONGNAME") or raw.get("name") or raw.get("NAME") or "").strip(),
        singer=singer.strip(),
        album_name=(raw.get("ALBUM") or raw.get("album") or "").strip(),
        album_id=str(raw.get("ALBUMID") or raw.get("albumid") or raw.get("albumId") or ""),
        interval=_fmt_duration(raw.get("DURATION") or raw.get("duration")),
        hash=None,
        img=None,
        types=_types_from_nminfo(raw.get("N_MINFO") or raw.get("MINFO") or ""),
    )


class KwSource(PlatformSource):
    platform = PLATFORM
    features = ("search", "song", "album", "leaderboard", "hot",
                "songlist", "comment", "lyric", "tip")

    def search(self, keyword: str, page: int = 1, limit: int = 30) -> SearchResult:
        url = (
            "http://search.kuwo.cn/r.s?client=kt&all="
            + urllib.parse.quote(keyword)
            + f"&pn={page - 1}&rn={limit}"          # ★ 上游 0-based
            "&uid=794762570&ver=kwplayer_ar_9.2.2.1&vipver=1"
            "&show_copyright_off=1&newver=1&ft=music&cluster=0"
            "&strategy=2012&encoding=utf8&rformat=json&vermerge=1&mobi=1&issubtitle=1"
        )
        raw = request_text(url, platform=PLATFORM)
        d = parse_kuwo_json(raw)
        items = d.get("abslist") or []
        total = int(d.get("TOTAL") or 0)
        songs = [_song(s) for s in items if isinstance(s, dict)]
        return SearchResult(
            platform=PLATFORM, list=songs, total=total, page=page,
            all_page=max(1, -(-total // limit)) if limit else 1, limit=limit,
        )

    def song(self, songmid: str) -> SongRecord:
        rid = str(songmid).replace("MUSIC_", "")
        url = (f"http://search.kuwo.cn/r.s?client=kt&all={rid}&pn=0&rn=1"
               "&uid=794762570&ver=kwplayer_ar_9.2.2.1&vipver=1"
               "&show_copyright_off=1&newver=1&ft=music&cluster=0"
               "&strategy=2012&encoding=utf8&rformat=json&vermerge=1&mobi=1")
        d = parse_kuwo_json(request_text(url, platform=PLATFORM))
        items = d.get("abslist") or []
        if not items:
            raise SourceError(PLATFORM, f"未找到歌曲：{songmid}")
        return _song(items[0])

    def album(self, album_id: str) -> AlbumInfo:
        url = (f"http://search.kuwo.cn/r.s?client=kt&all={album_id}&pn=0&rn=50"
               "&uid=794762570&ver=kwplayer_ar_9.2.2.1&vipver=1"
               "&show_copyright_off=1&newver=1&ft=album&cluster=0"
               "&strategy=2012&encoding=utf8&rformat=json&vermerge=1&mobi=1")
        d = parse_kuwo_json(request_text(url, platform=PLATFORM))
        items = d.get("abslist") or []
        if not items:
            raise SourceError(PLATFORM, f"专辑 {album_id} 返回空")
        songs = [_song(s) for s in items if isinstance(s, dict)]
        return AlbumInfo(id=str(album_id),
                         name=(songs[0].album_name if songs else f"album {album_id}"),
                         artist=(songs[0].singer if songs else ""),
                         pic_url=None, size=len(songs), songs=songs)

    def leaderboard(self, board: str | None = None, page: int = 1,
                    limit: int = 100) -> SearchResult:
        bangid = "16"
        if board:
            for b in _BOARDS:
                if board in (b.id, b.name, b.bangid):
                    bangid = b.bangid
                    break
            else:
                if str(board).isdigit():
                    bangid = str(board)
        # 酷我榜单用 offset/size（非 pn）
        offset = (page - 1) * limit
        url = (f"http://kbangserver.kuwo.cn/ksong.s?from=pc&fmt=json&pn=0"
               f"&rn={limit}&type=bang&data=content&id={bangid}"
               f"&show_copyright_off=0&pcmp4=1&isbang=1&offset={offset}")
        d = parse_kuwo_json(request_text(url, platform=PLATFORM))
        items = d.get("musiclist") or d.get("abslist") or []
        songs = [_song(s) for s in items if isinstance(s, dict)]
        return SearchResult(platform=PLATFORM, list=songs, total=len(songs),
                            page=page, all_page=1, limit=limit)

    def songlist(self, list_id: str, page: int = 1, limit: int = 36) -> SearchResult:
        offset = (page - 1) * limit
        url = (f"http://nplserver.kuwo.cn/pl.svc?op=getlistinfo&pid={list_id}"
               f"&pn=0&rn={limit}&encode=utf8&keyset=pl2012&identity=kuwo"
               f"&pcmp4=1&vipver=1&newver=1&offset={offset}")
        d = parse_kuwo_json(request_text(url, platform=PLATFORM))
        items = d.get("musiclist") or []
        total = int(d.get("total") or len(items))
        songs = [_song(s) for s in items if isinstance(s, dict)]
        return SearchResult(
            platform=PLATFORM, list=songs, total=total, page=page,
            all_page=max(1, -(-total // limit)) if limit else 1, limit=limit,
        )

    def lyric(self, songmid: str) -> dict[str, Any]:
        rid = str(songmid).replace("MUSIC_", "")
        url = (f"http://newlyric.kuwo.cn/newlyric.lrc?{rid}")
        text = request_text(url, platform=PLATFORM)
        return {"lyric": text, "tlyric": "", "rlyric": "", "lxlyric": ""}

    def comment(self, songmid: str, page: int = 1,
                limit: int = 20) -> list[Comment]:
        url = (f"http://comment.kuwo.cn/com.s?type=get_comment&f=web"
               f"&prod=kwplayer_ar_9.2.2.1&digest=15&sid={songmid}"
               f"&page={page}&rows={limit}&uid=0&prod=kwplayer_ar_9.2.2.1")
        d = parse_kuwo_json(request_text(url, platform=PLATFORM))
        items = d.get("rows") or []
        return [Comment(author=str(c.get("u_name", "")),
                        content=str(c.get("msg", "")),
                        time=str(c.get("time", "")))
                for c in items if isinstance(c, dict)]

    def hot(self) -> list[HotKeyword]:
        """酷我无公开热搜接口。

        桌面端 ``musicSdk/kw/hotSearch.js`` 用的是榜单派生，语义上不是"热搜词"，
        故这里**明确返回空**并让 CLI 报告"该平台不支持 hot"，
        而不是拿榜单歌名冒充。
        """
        return []

    def tip(self, keyword: str, limit: int = 10) -> list[SongRecord]:
        url = (f"http://search.kuwo.cn/r.s?client=kt&all={urllib.parse.quote(keyword)}"
               f"&pn=0&rn={limit}&uid=794762570&ver=kwplayer_ar_9.2.2.1"
               "&vipver=1&show_copyright_off=1&newver=1&ft=music&cluster=0"
               "&strategy=2012&encoding=utf8&rformat=json&vermerge=1&mobi=1")
        d = parse_kuwo_json(request_text(url, platform=PLATFORM))
        return [_song(s) for s in (d.get("abslist") or []) if isinstance(s, dict)]

    def boards(self) -> list[LeaderboardEntry]:
        return list(_BOARDS)


from . import _register  # noqa: E402

_register(KwSource())
