"""酷狗音乐平台元数据接口。

endpoint 移植自桌面端 ``musicSdk/kg/``（打酷狗**官方**域名
``songsearch.kugou.com`` / ``gateway.kugou.com`` / ``mobilecdn.kugou.com``），
并经旧版 lx-cli 实际调通。

⚠️ **kg 的歌曲 id 是 ``<songId>_<hash>``（无 ``kg_`` 前缀）** ——
见 ``core/musicinfo.make_song_id``；本模块负责同时产出 ``songmid`` 与 ``hash``，
由 ``SongRecord.to_song_id()`` 组合。

输出的 ``types`` 保留为 ``list[dict]``（含 size/hash），以便直接落库到 ``meta.qualitys``。
"""
from __future__ import annotations

import urllib.parse
from typing import Any

from .._logging import get_logger
from .base import (
    AlbumInfo, Comment, HotKeyword, LeaderboardEntry, PlatformSource,
    SearchResult, SongRecord, SourceError,
)
from .http import request_json

log = get_logger()

PLATFORM = "kg"

_HEADERS = {
    "KG-THash": "13a3164", "KG-RC": "1", "KG-Fake": "0", "KG-RF": "00869891",
    "User-Agent": "Android712-AndroidPhone-11451-376-0-FeeCacheUpdate-wifi",
    "x-router": "kmr.service.kugou.com",
}

_BOARDS = [
    LeaderboardEntry("kg__8888", "TOP500", "8888", "kg"),
    LeaderboardEntry("kg__6666", "飙升榜", "6666", "kg"),
    LeaderboardEntry("kg__23784", "网络红歌榜", "23784", "kg"),
    LeaderboardEntry("kg__21101", "分享榜", "21101", "kg"),
]


def _fmt_duration(secs: Any) -> str:
    try:
        s = int(float(secs or 0))
    except (TypeError, ValueError):
        return ""
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
    f = float(v)
    i = 0
    while f >= 1024 and i < len(units) - 1:
        f /= 1024
        i += 1
    return f"{f:.2f} {units[i]}"


def _build_types(raw: dict) -> list[dict[str, Any]]:
    """构造音质数组（含 size + hash）。

    组合顺序与桌面端 ``kg/musicInfo.js`` 的 checks 顺序一致：低→高，
    即 ``128k, 320k, flac, flac24bit``。
    """
    out: list[dict[str, Any]] = []
    # 128k：FileHash / 搜索结果的 FileHash
    if raw.get("FileSize") or raw.get("FileHash"):
        item: dict[str, Any] = {"type": "128k"}
        sz = _size_str(raw.get("FileSize"))
        if sz:
            item["size"] = sz
        h = raw.get("FileHash") or raw.get("hash")
        if h:
            item["hash"] = h
        out.append(item)
    if raw.get("HQFileSize") or raw.get("HQFileHash"):
        item = {"type": "320k"}
        sz = _size_str(raw.get("HQFileSize"))
        if sz:
            item["size"] = sz
        h = raw.get("HQFileHash")
        if h:
            item["hash"] = h
        out.append(item)
    if raw.get("SQFileSize") or raw.get("SQFileHash"):
        item = {"type": "flac"}
        sz = _size_str(raw.get("SQFileSize"))
        if sz:
            item["size"] = sz
        h = raw.get("SQFileHash")
        if h:
            item["hash"] = h
        out.append(item)
    if raw.get("ResFileSize") or raw.get("ResFileHash"):
        item = {"type": "flac24bit"}
        sz = _size_str(raw.get("ResFileSize"))
        if sz:
            item["size"] = sz
        h = raw.get("ResFileHash")
        if h:
            item["hash"] = h
        out.append(item)
    return out


def _build_types_from_audio_info(ai: dict) -> list[dict[str, Any]]:
    """从 ``audio_info``（gateway.kugou.com 响应）构造音质数组。"""
    out: list[dict[str, Any]] = []
    pairs = (
        ("128k", "filesize", "hash"),
        ("320k", "filesize_320", "hash_320"),
        ("flac", "filesize_flac", "hash_flac"),
        ("flac24bit", "filesize_high", "hash_high"),
    )
    for qtype, size_key, hash_key in pairs:
        raw_size = ai.get(size_key)
        if raw_size in (None, "0", 0, ""):
            continue
        item: dict[str, Any] = {"type": qtype}
        sz = _size_str(raw_size)
        if sz:
            item["size"] = sz
        if ai.get(hash_key):
            item["hash"] = ai[hash_key]
        out.append(item)
    return out


def _song_from_search(raw: dict) -> SongRecord:
    """搜索结果 → SongRecord（注意 kg 的 songmid 与 hash 是两个字段）。"""
    singers = "、".join(
        (s or {}).get("name", "") for s in (raw.get("Singers") or [])
    ).strip("、")
    if not singers:
        singers = raw.get("SingerName") or ""

    songmid = str(raw.get("Audioid") or raw.get("audio_id") or "").strip()
    hash_ = raw.get("FileHash") or raw.get("hash") or None

    # 兜底：个别响应没有 Audioid，用 hash 当 songmid（此时 id 会是 hash_hash）
    if not songmid:
        songmid = str(hash_ or "")

    return SongRecord(
        platform=PLATFORM,
        songmid=songmid,
        name=(raw.get("SongName") or raw.get("songname") or "").strip(),
        singer=singers,
        album_name=(raw.get("AlbumName") or raw.get("album_name") or "").strip(),
        album_id=str(raw.get("AlbumID") or raw.get("album_id") or ""),
        interval=_fmt_duration(raw.get("Duration") or raw.get("timelength", 0)),
        hash=hash_,
        img=None,
        types=_build_types(raw),
        extra={"albumAudioId": raw.get("AlbumAudioID") or raw.get("audio_group_id")},
    )


def _song_from_audio_info(item: dict) -> SongRecord:
    """``gateway.kugou.com/v3/album_audio/audio`` 响应 → SongRecord。"""
    ai = item.get("audio_info") or {}
    album = item.get("album_info") or {}
    songmid = str(ai.get("audio_id") or "")
    hash_ = ai.get("hash") or None
    tl = ai.get("timelength")
    try:
        interval = _fmt_duration(int(tl) / 1000) if tl else ""
    except (TypeError, ValueError):
        interval = ""
    return SongRecord(
        platform=PLATFORM,
        songmid=songmid,
        name=(item.get("songname") or item.get("ori_audio_name") or "").strip(),
        singer=(item.get("author_name") or "").strip(),
        album_name=(album.get("album_name") or "").strip(),
        album_id=str(album.get("album_id") or ""),
        interval=interval,
        hash=hash_,
        img=None,
        types=_build_types_from_audio_info(ai),
        extra={"albumAudioId": ai.get("audio_group_id")},
    )


class KgSource(PlatformSource):
    platform = PLATFORM
    features = ("search", "song", "album", "leaderboard", "hot",
                "songlist", "comment", "singer")

    # ---------------------------------------------------------- search

    def search(self, keyword: str, page: int = 1, limit: int = 30) -> SearchResult:
        url = (
            "https://songsearch.kugou.com/song_search_v2?keyword="
            + urllib.parse.quote(keyword)
            + f"&page={page}&pagesize={limit}&userid=0&clientver="
            "&platform=WebFilter&filter=2&iscorrection=1"
            "&privilege_filter=0&area_code=1"
        )
        body = request_json(url, platform=PLATFORM)
        data = body.get("data") or {}
        items = data.get("lists") or []
        total = int(data.get("total") or 0)
        songs = [_song_from_search(it) for it in items if isinstance(it, dict)]
        return SearchResult(
            platform=PLATFORM, list=songs, total=total, page=page,
            all_page=max(1, -(-total // limit)) if limit else 1, limit=limit,
        )

    # ---------------------------------------------------------- song

    def song(self, songmid: str, hash_: str | None = None) -> SongRecord:
        """取单曲详情。

        ⚠️ kg 的这个接口按 **hash** 查（不是 audio_id），
        所以要拿完整信息应传 hash；只传 songmid 时结果可能为空。
        """
        target = hash_ or songmid
        body = request_json(
            "http://gateway.kugou.com/v3/album_audio/audio",
            method="POST",
            headers={**_HEADERS, "Content-Type": "application/json"},
            json_body=[{
                "data": [{"hash": target, "audio_id": 0}],
                "area_code": "1", "show_privilege": 1, "show_album_info": "1",
                "is_publish": "", "appid": 1005, "clientver": 11451,
                "mid": "1", "dfid": "-", "clienttime": 1700000000000,
                "key": "OIlwieks28dk2k092lksi2UIkp",
                "fields": ("album_info,author_name,audio_info,ori_audio_name,"
                           "base,songname,classification"),
            }],
            platform=PLATFORM,
        )
        flat: list[Any] = []
        for inner in (body or []):
            if isinstance(inner, list):
                flat.extend(inner)
            elif inner:
                flat.append(inner)
        if not flat:
            raise SourceError(PLATFORM, f"未找到歌曲：{target}")
        first = flat[0]
        if isinstance(first, list):
            first = first[0] if first else {}
        if not isinstance(first, dict):
            raise SourceError(PLATFORM, f"响应结构异常：{target}")
        return _song_from_audio_info(first)

    # ---------------------------------------------------------- album

    def album(self, album_id: str) -> AlbumInfo:
        body = request_json(
            "http://mobiles.kugou.com/api/v3/album/song?version=9108"
            f"&albumid={urllib.parse.quote(str(album_id))}&plat=0"
            "&pagesize=200&area_code=0&page=1&with_res_tag=0",
            platform=PLATFORM,
        )
        info = body.get("info") or []
        if not info:
            raise SourceError(PLATFORM, f"专辑 {album_id} 返回空")
        songs = [_song_from_search(s) for s in info if isinstance(s, dict)]
        # 专辑名/艺人从曲目推断（该接口不直接给专辑元信息）
        name = songs[0].album_name if songs else ""
        artist = songs[0].singer if songs else ""
        return AlbumInfo(id=str(album_id), name=name or f"album {album_id}",
                         artist=artist, pic_url=None, size=len(songs),
                         songs=songs)

    # ---------------------------------------------------------- leaderboard

    def leaderboard(self, board: str | None = None, page: int = 1,
                    limit: int = 100) -> SearchResult:
        bangid = "8888"
        if board:
            for b in _BOARDS:
                if board in (b.id, b.name, b.bangid):
                    bangid = b.bangid
                    break
            else:
                if str(board).isdigit():
                    bangid = str(board)
        body = request_json(
            f"http://mobile.kugou.com/rank/info/?rankid={bangid}"
            f"&ranktype=2&page={page}&pagesize={limit}",
            platform=PLATFORM,
        )
        rank = body.get("rank") or {}
        songs = [_song_from_search(s) for s in (rank.get("songs") or [])
                 if isinstance(s, dict)]
        return SearchResult(platform=PLATFORM, list=songs, total=len(songs),
                            page=page, all_page=1, limit=limit)

    # ---------------------------------------------------------- hot

    def hot(self) -> list[HotKeyword]:
        body = request_json(
            "http://gateway.kugou.com/api/v3/search/hot_tab"
            "?signature=ee44edb9d7155821412d220bcaf509dd"
            "&appid=1005&clientver=10026&plat=0",
            platform=PLATFORM,
        )
        data = body.get("data") or {}
        words: list[Any] = []
        if isinstance(data, dict) and "hot_tab" in data:
            tabs = data.get("hot_tab") or []
            words = ((tabs[0] or {}).get("words") if tabs else []) or \
                (data.get("hotwords") or [])
        elif isinstance(data, list):
            words = data
        elif isinstance(data, dict):
            words = data.get("hotwords") or []
        out: list[HotKeyword] = []
        for w in words or []:
            if isinstance(w, dict):
                out.append(HotKeyword(str(w.get("keyword", "")),
                                      int(w.get("score") or 0)))
            else:
                out.append(HotKeyword(str(w), 0))
        return out

    # ---------------------------------------------------------- songlist

    def songlist(self, list_id: str, page: int = 1, limit: int = 36) -> SearchResult:
        body = request_json(
            "https://mobilecdn.kugou.com/api/v3/special/song?version=9108"
            f"&specialid={urllib.parse.quote(str(list_id))}&plat=0"
            f"&pagesize={limit}&area_code=0&page={page}&with_res_tag=0",
            platform=PLATFORM,
        )
        info = body.get("info") or []
        songs = [_song_from_search(s) for s in info if isinstance(s, dict)]
        total = int(body.get("total") or len(songs))
        return SearchResult(
            platform=PLATFORM, list=songs, total=total, page=page,
            all_page=max(1, -(-total // limit)) if limit else 1, limit=limit,
        )

    # ---------------------------------------------------------- comment

    def comment(self, songmid: str, page: int = 1,
                limit: int = 20) -> list[Comment]:
        body = request_json(
            "http://mobile.service.kugou.com/comments/v2/getCommentNew"
            f"?p={page}&pagesize={limit}&business=2&type=0&subtype=0"
            f"&sid={urllib.parse.quote(str(songmid))}&plat=0&format=json",
            platform=PLATFORM,
        )
        items = ((body.get("commentlist") or {}).get("list") or [])
        return [Comment(author=(c.get("user") or {}).get("nickname", ""),
                        content=c.get("content", ""),
                        time=str(c.get("addtime", "")))
                for c in items if isinstance(c, dict)]

    # ---------------------------------------------------------- singer

    def singer(self, singer_id: str, page: int = 1,
               limit: int = 30) -> SearchResult:
        body = request_json(
            "https://mobilecdn.kugou.com/api/v3/singer/song"
            f"?singerid={urllib.parse.quote(str(singer_id))}&plat=0"
            f"&pagesize={limit}&area_code=0&page={page}",
            platform=PLATFORM,
        )
        info = body.get("info") or []
        songs = [_song_from_search(s) for s in info if isinstance(s, dict)]
        return SearchResult(platform=PLATFORM, list=songs, total=len(songs),
                            page=page, all_page=1, limit=limit)

    def boards(self) -> list[LeaderboardEntry]:
        return list(_BOARDS)


from . import _register  # noqa: E402

_register(KgSource())
