"""QQ 音乐（企鹅音乐）平台元数据接口。

打腾讯**官方**域名 ``u.y.qq.com``：

* ``musicu.fcg`` —— 不需要签名，data 走 URL
* ``musics.fcg`` —— 需要 **zzcSign**（自定义签名算法），data 走 POST body

⚠️ ``tx`` 的 ``songmid`` 是 **MID 字符串**（如 ``001SxL503C84XM``），
不是数字 songId；id 形如 ``tx_<mid>``。
播放时需要 ``strMediaMid``（在 ``file.media_mid``），本模块放在 ``extra`` 里。
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
import urllib.parse
from typing import Any

from .._logging import get_logger
from .base import (
    Comment, HotKeyword, LeaderboardEntry, PlatformSource,
    SearchResult, SongRecord, SourceError,
)
from .http import request_json

log = get_logger()

PLATFORM = "tx"

# zzcSign 置换表（移植自桌面端 tx/util.js 的等价实现）
_P1 = [23, 14, 6, 36, 16, 40, 7, 19]
_P2 = [16, 1, 32, 12, 19, 27, 8, 5]
_SC = [89, 39, 179, 150, 218, 82, 58, 252, 177, 52, 186, 123,
       120, 64, 242, 133, 143, 161, 121, 179]

_BOARDS = [
    LeaderboardEntry("tx__4", "流行指数榜", "4", "tx"),
    LeaderboardEntry("tx__26", "热歌榜", "26", "tx"),
    LeaderboardEntry("tx__27", "新歌榜", "27", "tx"),
    LeaderboardEntry("tx__62", "飙升榜", "62", "tx"),
]


def zzc_sign(text: str) -> str:
    """腾讯 ``musics.fcg`` 的签名算法。"""
    h = hashlib.sha1(text.encode("utf-8")).hexdigest()
    p1 = "".join(h[i] if i < len(h) else "" for i in _P1)
    p2 = "".join(h[i] if i < len(h) else "" for i in _P2)
    sc = bytes(v ^ int(h[i * 2:i * 2 + 2], 16) for i, v in enumerate(_SC))
    b64 = (base64.b64encode(sc).decode()
           .replace("\\", "").replace("/", "").replace("+", "").replace("=", ""))
    return f"zzc{p1}{b64}{p2}".lower()


def _comm() -> dict[str, str]:
    return {"ct": "19", "cv": "1859", "uin": "0"}


def _musicu(module: str, method: str, param: dict) -> dict[str, Any]:
    """``musicu.fcg``（无需签名，GET + URL 编码的 data）。"""
    data = {"comm": _comm(),
            "req": {"module": module, "method": method, "param": param}}
    url = ("https://u.y.qq.com/cgi-bin/musicu.fcg?format=json&data="
           + urllib.parse.quote(json.dumps(data, separators=(",", ":"))))
    res = request_json(url, platform=PLATFORM)
    return (res.get("req") or {}).get("data") or {}


def _musics(module: str, method: str, param: dict) -> dict[str, Any]:
    """``musics.fcg``（需 zzcSign，POST JSON body）。"""
    data = {"comm": {**_comm(), "tmeAppID": "qqmusic"},
            "req": {"module": module, "method": method, "param": param}}
    body = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    sign = zzc_sign(body)
    url = "https://u.y.qq.com/cgi-bin/musics.fcg?sign=" + sign
    res = request_json(
        url, method="POST", platform=PLATFORM,
        data=body.encode("utf-8"),
        headers={"User-Agent": "QQMusic 14090508(android 12)",
                 "Content-Type": "application/json"},
    )
    return (res.get("req") or {}).get("data") or {}


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
    f, i = float(v), 0
    while f >= 1024 and i < len(units) - 1:
        f /= 1024
        i += 1
    return f"{f:.2f} {units[i]}"


def _build_types(file_obj: dict) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    pairs = (("128k", "size_128mp3"), ("320k", "size_320mp3"),
             ("flac", "size_flac"), ("flac24bit", "size_hires"))
    for qtype, key in pairs:
        raw = file_obj.get(key)
        if raw in (None, 0, "0", ""):
            continue
        item: dict[str, Any] = {"type": qtype}
        sz = _size_str(raw)
        if sz:
            item["size"] = sz
        out.append(item)
    return out


def _song(raw: dict) -> SongRecord:
    singers = "、".join(
        (s or {}).get("name", "") for s in (raw.get("singer") or [])
        if isinstance(s, dict)
    ).strip("、")
    file_obj = raw.get("file") or {}
    album = raw.get("album") or {}
    mid = raw.get("mid") or raw.get("songmid") or str(raw.get("id") or "")
    return SongRecord(
        platform=PLATFORM,
        songmid=str(mid),
        name=(raw.get("name") or raw.get("title") or "").strip(),
        singer=singers,
        album_name=(album.get("name") or "").strip(),
        album_id=str(album.get("mid") or ""),
        interval=_fmt_duration(raw.get("interval")),
        img=None,
        types=_build_types(file_obj),
        extra={
            # ★ 播放（Scheme URL）需要 strMediaMid
            "strMediaMid": file_obj.get("media_mid") or "",
            "albumMid": album.get("mid") or "",
            "id": raw.get("id") or "",
        },
    )


class TxSource(PlatformSource):
    platform = PLATFORM
    features = ("search", "song", "leaderboard", "hot",
                "songlist", "comment", "singer", "lyric")

    # ---------------------------------------------------------- search

    def search(self, keyword: str, page: int = 1, limit: int = 30) -> SearchResult:
        data = _musics(
            "music.search.SearchCgiService", "DoSearchForQQMusicMobile",
            {"search_type": 0,
             "searchid": str(int(time.time() * 1_000_000)),
             "query": keyword, "page_num": page, "num_per_page": limit,
             "highlight": 0, "nqc_flag": 0, "multi_zhida": 0,
             "cat": 2, "grp": 1, "sin": 0, "sem": 0},
        )
        body = data.get("body") or {}
        items = body.get("item_song") or []
        songs = [_song(it) for it in items if isinstance(it, dict)]
        meta = data.get("meta") or {}
        total = int(meta.get("estimate_sum") or len(songs))
        return SearchResult(
            platform=PLATFORM, list=songs, total=total, page=page,
            all_page=max(1, -(-total // limit)) if limit else 1, limit=limit)

    # ---------------------------------------------------------- song

    def song(self, songmid: str) -> SongRecord:
        data = _musicu("music.pf_song_detail_svr", "get_song_detail_yqq",
                       {"song_type": 0, "song_mid": songmid})
        ti = data.get("track_info") or {}
        if not ti:
            raise SourceError(PLATFORM, f"未找到歌曲：{songmid}")
        return _song(ti)

    # ---------------------------------------------------------- leaderboard

    def leaderboard(self, board: str | None = None, page: int = 1,
                    limit: int = 100) -> SearchResult:
        bangid = 26
        if board:
            for b in _BOARDS:
                if board in (b.id, b.name, b.bangid):
                    bangid = int(b.bangid)
                    break
            else:
                if str(board).isdigit():
                    bangid = int(board)
        data = _musicu("musicToplist.ToplistInfoServer", "GetDetail",
                       {"topid": bangid, "num": limit, "period": ""})
        songs_raw = (data.get("songlist") or []) if isinstance(data, dict) else []
        songs = [_song(s) for s in songs_raw if isinstance(s, dict)]
        return SearchResult(platform=PLATFORM, list=songs, total=len(songs),
                            page=page, all_page=1, limit=limit)

    # ---------------------------------------------------------- songlist

    def songlist(self, list_id: str, page: int = 1, limit: int = 36) -> SearchResult:
        data = _musicu("music.srfDissInfo.aiDissInfo", "uniform_get_Dissinfo",
                       {"disstid": int(list_id), "enc_host_uin": "",
                        "tag": 1, "userinfo": 1, "song_begin": (page - 1) * limit,
                        "song_num": limit})
        songs_raw = (data.get("songlist") or []) if isinstance(data, dict) else []
        songs = [_song(s) for s in songs_raw if isinstance(s, dict)]
        total = int(data.get("total_song_num") or len(songs)) \
            if isinstance(data, dict) else len(songs)
        return SearchResult(
            platform=PLATFORM, list=songs, total=total, page=page,
            all_page=max(1, -(-total // limit)) if limit else 1, limit=limit)

    # ---------------------------------------------------------- singer

    def singer(self, singer_id: str, page: int = 1,
               limit: int = 30) -> SearchResult:
        data = _musicu("musichall.song_list_server", "GetSingerSongList",
                       {"singerMid": singer_id, "begin": (page - 1) * limit,
                        "num": limit, "order": 1})
        songs_raw = (data.get("songList") or []) if isinstance(data, dict) else []
        songs: list[SongRecord] = []
        for item in songs_raw:
            if isinstance(item, dict) and isinstance(item.get("songInfo"), dict):
                songs.append(_song(item["songInfo"]))
            elif isinstance(item, dict):
                songs.append(_song(item))
        return SearchResult(platform=PLATFORM, list=songs, total=len(songs),
                            page=page, all_page=1, limit=limit)

    # ---------------------------------------------------------- lyric

    def lyric(self, songmid: str) -> dict[str, Any]:
        data = _musicu("music.musichallSong.PlayLyricInfo", "GetPlayLyricInfo",
                       {"songMID": songmid, "songID": 0, "format": "json"})
        return {
            "lyric": data.get("lyric") or "",
            "tlyric": data.get("trans") or "",
            "rlyric": data.get("roma") or "",
            "lxlyric": data.get("qrc") or "",
        }

    # ---------------------------------------------------------- comment

    def comment(self, songmid: str, page: int = 1,
                limit: int = 20) -> list[Comment]:
        data = _musicu("music.globalComment.CommentRead", "GetHotComments",
                       {"bizType": 1, "bizId": songmid, "pageSize": limit,
                        "pageNum": page})
        items = (data.get("comments") or data.get("hotComments") or []) \
            if isinstance(data, dict) else []
        out: list[Comment] = []
        for c in items:
            if not isinstance(c, dict):
                continue
            user = c.get("user") or c.get("nick") or ""
            if isinstance(user, dict):
                user = user.get("nick") or user.get("name") or ""
            out.append(Comment(author=str(user),
                               content=str(c.get("content") or ""),
                               time=str(c.get("time") or "")))
        return out

    # ---------------------------------------------------------- hot

    def hot(self) -> list[HotKeyword]:
        data = _musicu("music.search.HotSongServer", "GetHotkey", {"cat": 1})
        items = (data.get("vec_hotkey") or data.get("hotkey") or []) \
            if isinstance(data, dict) else []
        out: list[HotKeyword] = []
        for h in items:
            if isinstance(h, dict):
                kw = h.get("query") or h.get("k") or h.get("keyword") or ""
                out.append(HotKeyword(str(kw), 0))
            elif isinstance(h, str):
                out.append(HotKeyword(h, 0))
        return out

    def boards(self) -> list[LeaderboardEntry]:
        return list(_BOARDS)


from . import _register  # noqa: E402

_register(TxSource())
