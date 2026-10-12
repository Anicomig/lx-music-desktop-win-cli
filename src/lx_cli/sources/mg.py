"""咪咕音乐平台元数据接口。

打咪咕**官方**域名 ``jadeite.migu.cn`` / ``music.migu.cn`` / ``app.c.nf.migu.cn``。
搜索接口需要 **MD5 sign 头部**（``uiVersion``/``deviceId``/``timestamp``/``sign``）。

⚠️ 咪咕的 ``duration`` 单位不稳定（有时是秒、有时是毫秒），本模块自动判断。
"""
from __future__ import annotations

import hashlib
import time
import urllib.parse
from typing import Any

from .._logging import get_logger
from .base import (
    AlbumInfo, Comment, HotKeyword, LeaderboardEntry, PlatformSource,
    SearchResult, SongRecord, SourceError,
)
from .http import request_json

log = get_logger()

PLATFORM = "mg"

_DEVICE_ID = "963B7AA0D21511ED807EE5846EC87D20"
_SIG_MD5 = "6cdc72a439cef99a3418d2a78aa28c73"
_SIG_SECRET = "yyapp2d16148780a1dcc7408e06336b98cfd50"

_BOARDS = [
    LeaderboardEntry("mg__27553319", "新歌榜", "27553319", "mg"),
    LeaderboardEntry("mg__27186466", "热歌榜", "27186466", "mg"),
    LeaderboardEntry("mg__19190036", "欧美榜", "19190036", "mg"),
    LeaderboardEntry("mg__23189399", "内地榜", "23189399", "mg"),
]

_SEARCH_SWITCH = ("%7B%22song%22%3A1%2C%22album%22%3A0%2C%22singer%22%3A0"
                  "%2C%22tagSong%22%3A1%2C%22mvSong%22%3A0"
                  "%2C%22bestShow%22%3A1%2C%22songlist%22%3A0"
                  "%2C%22lyricSong%22%3A0%7D")


def sign(text: str, ts: str) -> tuple[str, str]:
    """生成咪咕搜索接口的 ``sign`` 与 ``deviceId``。"""
    md = hashlib.md5(
        f"{text}{_SIG_MD5}{_SIG_SECRET}{_DEVICE_ID}{ts}".encode()).hexdigest()
    return md, _DEVICE_ID


def _search_headers(text: str) -> dict[str, str]:
    ts = str(int(time.time() * 1000))
    sg, did = sign(text, ts)
    return {
        "uiVersion": "A_music_3.6.1", "deviceId": did,
        "timestamp": ts, "sign": sg, "channel": "0146921",
        "User-Agent": "Mozilla/5.0 (Linux; U; Android 11.0.0; zh-cn; MI 11)",
    }


def _fmt_duration(secs: Any) -> str:
    if not secs:
        return ""
    try:
        v = float(secs)
    except (TypeError, ValueError):
        return ""
    if v > 10000:            # 毫秒
        v /= 1000
    s = int(v)
    if s <= 0:
        return ""
    return f"{s // 60}:{s % 60:02d}"


def _size_str(n: Any) -> str:
    try:
        v = int(n)
    except (TypeError, ValueError):
        return ""
    if v <= 0:
        return ""
    units = ["B", "KB", "MB", "GB"]
    f, i = float(v), 0
    while f >= 1024 and i < len(units) - 1:
        f /= 1024
        i += 1
    return f"{f:.2f} {units[i]}"


def _build_types(raw: dict) -> list[dict[str, Any]]:
    """从 ``audioFormats`` / ``newRateFormats`` 构造音质（含 size）。"""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    formats = raw.get("audioFormats") or raw.get("newRateFormats") or []
    for f in formats:
        if not isinstance(f, dict):
            continue
        ftype = f.get("formatType")
        qtype = {"PQ": "128k", "HQ": "320k", "SQ": "flac",
                 "ZQ": "flac24bit", "ZQ24": "flac24bit"}.get(ftype)
        if not qtype or qtype in seen:
            continue
        seen.add(qtype)
        item: dict[str, Any] = {"type": qtype}
        sz = _size_str(f.get("size") or f.get("fileSize"))
        if sz:
            item["size"] = sz
        out.append(item)
    # 统一为高→低
    order = {"flac24bit": 0, "flac": 1, "320k": 2, "192k": 3, "128k": 4}
    out.sort(key=lambda t: order.get(t["type"], 9))
    return out


def _song(raw: dict) -> SongRecord:
    singers = "、".join(
        (s or {}).get("name", "") for s in (raw.get("singerList") or [])
        if isinstance(s, dict)
    ).strip("、")
    return SongRecord(
        platform=PLATFORM,
        songmid=str(raw.get("songId") or raw.get("id") or ""),
        name=(raw.get("name") or raw.get("songName") or "").strip(),
        singer=singers,
        album_name=(raw.get("album") or raw.get("albumName") or "").strip(),
        album_id=str(raw.get("albumId") or ""),
        interval=_fmt_duration(raw.get("duration") or raw.get("length") or 0),
        img=(raw.get("img3") or raw.get("img2") or raw.get("img1")),
        types=_build_types(raw),
        extra={
            # ★ 播放（Scheme URL）需要 copyrightId
            "copyrightId": raw.get("copyrightId") or "",
            "lrcUrl": raw.get("lrcUrl") or raw.get("lyricUrl") or "",
            "trcUrl": raw.get("trcUrl") or "",
            "mrcUrl": raw.get("mrcUrl") or "",
        },
    )


class MgSource(PlatformSource):
    platform = PLATFORM
    features = ("search", "song", "album", "leaderboard", "hot",
                "songlist", "comment", "lyric")

    # ---------------------------------------------------------- search

    def search(self, keyword: str, page: int = 1, limit: int = 30) -> SearchResult:
        url = ("https://jadeite.migu.cn/music_search/v3/search/searchAll"
               f"?isCorrect=0&isCopyright=1&searchSwitch={_SEARCH_SWITCH}"
               f"&pageSize={limit}&text={urllib.parse.quote(keyword)}"
               f"&pageNo={page}&sort=0&sid=USS")
        body = request_json(url, headers=_search_headers(keyword),
                            platform=PLATFORM)
        if body.get("code") not in (None, "000000"):
            raise SourceError(PLATFORM, f"搜索失败（code={body.get('code')}）")
        data = body.get("songResultData") or {}
        groups = data.get("resultList") or []
        flat: list[dict] = []
        for grp in groups:
            for s in (grp if isinstance(grp, list) else [grp]):
                if isinstance(s, dict):
                    flat.append(s)
        songs = [_song(s) for s in flat]
        total = int(data.get("totalCount") or len(songs))
        return SearchResult(
            platform=PLATFORM, list=songs, total=total, page=page,
            all_page=max(1, -(-total // limit)) if limit else 1, limit=limit)

    # ---------------------------------------------------------- song

    def song(self, songmid: str) -> SongRecord:
        body = request_json(
            "https://c.musicapp.migu.cn/MIGUM2.0/v1.0/content/"
            "resourceinfo.do?resourceType=2",
            method="POST", platform=PLATFORM,
            data={"resourceId": songmid},
        )
        items = body.get("resource") or []
        if not items:
            raise SourceError(PLATFORM, f"未找到歌曲：{songmid}")
        first = items[0]
        if isinstance(first, list) and first:
            first = first[0]
        if not isinstance(first, dict):
            raise SourceError(PLATFORM, f"响应结构异常：{songmid}")
        return _song(first)

    # ---------------------------------------------------------- album

    def album(self, album_id: str) -> AlbumInfo:
        body = request_json(
            "http://app.c.nf.migu.cn/MIGUM2.0/v1.0/content/queryAlbumSong"
            f"?albumId={urllib.parse.quote(str(album_id))}&pageNo=1",
            platform=PLATFORM,
        )
        # ⚠️ 实测：字段在 data.songList 里，不是顶层 songList
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        songs_raw = (data.get("songList") or body.get("songList")
                     or (body.get("data") if isinstance(body.get("data"), list) else [])
                     or [])
        songs = [_song(s) for s in songs_raw if isinstance(s, dict)]
        if not songs:
            raise SourceError(PLATFORM, f"专辑 {album_id} 返回空")
        return AlbumInfo(
            id=str(album_id),
            name=(songs[0].album_name or f"album {album_id}"),
            artist=songs[0].singer, pic_url=songs[0].img,
            size=len(songs), songs=songs)

    # ---------------------------------------------------------- leaderboard

    def leaderboard(self, board: str | None = None, page: int = 1,
                    limit: int = 100) -> SearchResult:
        bangid = "27553319"
        if board:
            for b in _BOARDS:
                if board in (b.id, b.name, b.bangid):
                    bangid = b.bangid
                    break
            else:
                if str(board).isdigit():
                    bangid = str(board)
        body = request_json(
            "http://app.c.nf.migu.cn/MIGUM3.0/resource/bang/v3.0"
            f"?bangId={bangid}&pageNo={page}&pageSize={limit}",
            platform=PLATFORM,
        )
        data = body.get("data") or {}
        songs_raw = data.get("contentList") or data.get("songList") or []
        songs = [_song(s) for s in songs_raw if isinstance(s, dict)]
        return SearchResult(platform=PLATFORM, list=songs, total=len(songs),
                            page=page, all_page=1, limit=limit)

    # ---------------------------------------------------------- songlist

    def songlist(self, list_id: str, page: int = 1, limit: int = 36) -> SearchResult:
        body = request_json(
            "http://app.c.nf.migu.cn/MIGUM2.0/v1.0/content/getSongListById"
            f"?songListId={urllib.parse.quote(str(list_id))}"
            f"&pageNo={page}&pageSize={limit}",
            platform=PLATFORM,
        )
        data = body.get("data") or {}
        songs_raw = data.get("songList") or data.get("contentList") or []
        songs = [_song(s) for s in songs_raw if isinstance(s, dict)]
        total = int(data.get("totalCount") or len(songs))
        return SearchResult(
            platform=PLATFORM, list=songs, total=total, page=page,
            all_page=max(1, -(-total // limit)) if limit else 1, limit=limit)

    # ---------------------------------------------------------- lyric

    def lyric(self, songmid: str) -> dict[str, Any]:
        body = request_json(
            f"https://music.migu.cn/lrc/lyric?copyrightId={songmid}",
            platform=PLATFORM,
        )
        data = body.get("data") or {}
        return {"lyric": data.get("lyric") or "",
                "tlyric": data.get("tlyric") or "",
                "rlyric": "", "lxlyric": ""}

    # ---------------------------------------------------------- comment

    def comment(self, songmid: str, page: int = 1,
                limit: int = 20) -> list[Comment]:
        body = request_json(
            "https://music.migu.cn/comment/v3/list"
            f"?resourceType=2&resourceId={songmid}&pageNo={page}"
            f"&pageSize={limit}",
            platform=PLATFORM,
        )
        data = body.get("data") or {}
        items = data.get("list") or data.get("comments") or []
        return [Comment(author=str(c.get("nickName") or c.get("userName") or ""),
                        content=str(c.get("content") or ""),
                        time=str(c.get("createTime") or ""))
                for c in items if isinstance(c, dict)]

    # ---------------------------------------------------------- hot

    def hot(self) -> list[HotKeyword]:
        body = request_json(
            "http://jadeite.migu.cn/music_search/v3/search/hotword",
            platform=PLATFORM,
        )
        data = body.get("data") or body
        items = data.get("hotwords") or data.get("list") or []
        out: list[HotKeyword] = []
        for h in items:
            if isinstance(h, dict):
                out.append(HotKeyword(str(h.get("keyword") or h.get("text") or ""), 0))
            elif isinstance(h, str):
                out.append(HotKeyword(h, 0))
        return out

    def boards(self) -> list[LeaderboardEntry]:
        return list(_BOARDS)


from . import _register  # noqa: E402

_register(MgSource())
