"""网易云音乐平台元数据接口。

使用 **eapi** 加密协议（AES-ECB + MD5 摘要），打网易**官方**域名
``interface.music.163.com``。

⚠️ 已知源码怪癖：桌面端 ``wy/musicSearch.js`` 的 ``types`` 顺序在
search 与 song/album 之间**相反**（search 里有 ``.reverse()``）。
本模块**统一**为「高音质在前」（与 DB ``meta.qualitys`` 的常见顺序一致），
避免不同入口给出不一致的顺序。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .._logging import get_logger
from .base import (
    AlbumInfo, Comment, HotKeyword, LeaderboardEntry, PlatformSource,
    SearchResult, SongRecord, SourceError,
)
from .http import request_json

log = get_logger()

PLATFORM = "wy"

EAPI_URL = "http://interface.music.163.com/eapi/batch"
EAPI_KEY = b"e82ckenh8dichen8"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/60.0.3112.90 Safari/537.36")

_BOARDS = [
    LeaderboardEntry("wy__19723756", "飙升榜", "19723756", "wy"),
    LeaderboardEntry("wy__3779629", "新歌榜", "3779629", "wy"),
    LeaderboardEntry("wy__2884035", "原创榜", "2884035", "wy"),
    LeaderboardEntry("wy__3778678", "热歌榜", "3778678", "wy"),
]


def _aes_ecb_encrypt(data: bytes, key: bytes) -> bytes:
    from cryptography.hazmat.primitives import padding as sym_pad
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    padder = sym_pad.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    enc = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return enc.update(padded) + enc.finalize()


def eapi_encrypt(path: str, payload: Any) -> dict[str, str]:
    """eapi 加密：``params = hex(AES-ECB(key, path-md5-text-md5))``。"""
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.md5(
        f"nobody{path}use{text}md5forencrypt".encode()).hexdigest()
    data = f"{path}-36cd479b6b5-{text}-36cd479b6b5-{digest}"
    return {"params": _aes_ecb_encrypt(data.encode(), EAPI_KEY).hex().upper()}


def _eapi_post(path: str, payload: Any) -> dict[str, Any]:
    form = eapi_encrypt(path, payload)
    body = "&".join(f"{k}={v}" for k, v in form.items())
    raw = request_json_post(EAPI_URL, body)
    return raw if isinstance(raw, dict) else {}


def request_json_post(url: str, body: str) -> Any:
    from .http import request_text
    text = request_text(
        url, method="POST", platform=PLATFORM, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": UA, "Origin": "https://music.163.com"},
    )
    try:
        return json.loads(text)
    except ValueError as exc:
        raise SourceError(PLATFORM, f"响应非 JSON：{text[:160]!r}", cause=exc) from exc


def _fmt_duration(ms: Any) -> str:
    try:
        s = int(float(ms or 0) // 1000)
    except (TypeError, ValueError):
        return ""
    if s <= 0:
        return ""
    return f"{s // 60}:{s % 60:02d}"


def _types_from_maxbr(maxbr: int) -> list[dict[str, Any]]:
    """按 maxbr 推断可用音质（高→低，统一顺序）。"""
    out: list[dict[str, Any]] = []
    if maxbr >= 999000:
        out.append({"type": "flac"})
    if maxbr >= 320000:
        out.append({"type": "320k"})
    if maxbr >= 192000:
        out.append({"type": "192k"})
    if maxbr >= 128000:
        out.append({"type": "128k"})
    return out


def _join_singers(ar: Any) -> str:
    return "、".join(
        (a or {}).get("name", "") for a in (ar or []) if isinstance(a, dict)
    ).strip("、")


def _song_from_simple(s: dict) -> SongRecord:
    al = s.get("al") or {}
    maxbr = int((s.get("privilege") or {}).get("maxbr") or 0)
    return SongRecord(
        platform=PLATFORM,
        songmid=str(s.get("id", "")),
        name=(s.get("name") or "").strip(),
        singer=_join_singers(s.get("ar")),
        album_name=(al.get("name") or "").strip(),
        album_id=str(al.get("id") or ""),
        interval=_fmt_duration(s.get("dt")),
        img=al.get("picUrl"),
        types=_types_from_maxbr(maxbr),
    )


class WySource(PlatformSource):
    platform = PLATFORM
    features = ("search", "song", "album", "leaderboard", "hot",
                "songlist", "comment", "singer", "lyric")

    # ---------------------------------------------------------- search

    def search(self, keyword: str, page: int = 1, limit: int = 30) -> SearchResult:
        offset = (page - 1) * limit
        res = _eapi_post("/api/cloudsearch/pc", {
            "s": keyword, "type": 1, "limit": limit, "offset": offset,
            "total": "true", "csrf_token": "",
        })
        result = res.get("result") or {}
        items = result.get("songs") or []
        total = int(result.get("songCount") or 0)
        songs = [_song_from_simple(x) for x in items if isinstance(x, dict)]
        return SearchResult(
            platform=PLATFORM, list=songs, total=total, page=page,
            # ⚠️ 源码用模块默认 limit 算 allPage（bug），这里按真实 limit 修
            all_page=max(1, -(-total // limit)) if limit else 1, limit=limit,
        )

    # ---------------------------------------------------------- song

    def song(self, songmid: str) -> SongRecord:
        res = _eapi_post("/api/v3/song/detail", {
            "c": json.dumps([{"id": int(songmid)}]),
        })
        songs = res.get("songs") or []
        if not songs:
            raise SourceError(PLATFORM, f"未找到歌曲：{songmid}")
        return _song_from_simple(songs[0])

    # ---------------------------------------------------------- album

    def album(self, album_id: str) -> AlbumInfo:
        res = _eapi_post("/api/v1/album/" + str(album_id), {})
        album = res.get("album") or {}
        songs = res.get("songs") or []
        return AlbumInfo(
            id=str(album_id),
            name=(album.get("name") or f"album {album_id}"),
            artist=_join_singers(album.get("artists")),
            pic_url=album.get("picUrl"),
            size=len(songs),
            songs=[_song_from_simple(s) for s in songs if isinstance(s, dict)],
        )

    # ---------------------------------------------------------- leaderboard

    def leaderboard(self, board: str | None = None, page: int = 1,
                    limit: int = 100) -> SearchResult:
        bangid = "3778678"
        if board:
            for b in _BOARDS:
                if board in (b.id, b.name, b.bangid):
                    bangid = b.bangid
                    break
            else:
                if str(board).isdigit():
                    bangid = str(board)
        res = _eapi_post("/api/v6/playlist/detail", {
            "id": int(bangid), "n": limit, "offset": (page - 1) * limit,
            "total": "true",
        })
        playlist = res.get("playlist") or {}
        tracks = playlist.get("tracks") or []
        songs = [_song_from_simple(t) for t in tracks if isinstance(t, dict)]
        return SearchResult(platform=PLATFORM, list=songs,
                            total=int(playlist.get("trackCount") or len(songs)),
                            page=page, all_page=1, limit=limit)

    # ---------------------------------------------------------- songlist

    def songlist(self, list_id: str, page: int = 1, limit: int = 36) -> SearchResult:
        res = _eapi_post("/api/v6/playlist/detail", {
            "id": int(list_id), "n": limit, "offset": (page - 1) * limit,
            "total": "true",
        })
        playlist = res.get("playlist") or {}
        tracks = playlist.get("tracks") or []
        songs = [_song_from_simple(t) for t in tracks if isinstance(t, dict)]
        total = int(playlist.get("trackCount") or len(songs))
        return SearchResult(
            platform=PLATFORM, list=songs, total=total, page=page,
            all_page=max(1, -(-total // limit)) if limit else 1, limit=limit)

    # ---------------------------------------------------------- singer

    def singer(self, singer_id: str, page: int = 1, limit: int = 30) -> SearchResult:
        res = _eapi_post("/api/v1/artist/" + str(singer_id), {})
        hot = res.get("hotSongs") or []
        songs = [_song_from_simple(s) for s in hot if isinstance(s, dict)]
        return SearchResult(platform=PLATFORM, list=songs, total=len(songs),
                            page=page, all_page=1, limit=limit)

    # ---------------------------------------------------------- lyric

    def lyric(self, songmid: str) -> dict[str, Any]:
        res = _eapi_post("/api/song/lyric", {
            "id": int(songmid), "lv": -1, "kv": -1, "tv": -1,
        })
        return {
            "lyric": ((res.get("lrc") or {}).get("lyric") or ""),
            "tlyric": ((res.get("tlyric") or {}).get("lyric") or ""),
            "rlyric": ((res.get("romalrc") or {}).get("lyric") or ""),
            "lxlyric": ((res.get("yrc") or {}).get("lyric") or ""),
        }

    # ---------------------------------------------------------- comment

    def comment(self, songmid: str, page: int = 1,
                limit: int = 20) -> list[Comment]:
        res = _eapi_post("/api/v1/resource/comments/R_SO_4_" + str(songmid), {
            "rid": str(songmid), "limit": limit, "offset": (page - 1) * limit,
        })
        items = res.get("comments") or []
        return [Comment(author=((c.get("user") or {}).get("nickname") or ""),
                        content=str(c.get("content") or ""),
                        time=str(c.get("time") or ""))
                for c in items if isinstance(c, dict)]

    # ---------------------------------------------------------- hot

    def hot(self) -> list[HotKeyword]:
        res = _eapi_post("/api/search/hot", {"type": 1111})
        data = res.get("result") or {}
        items = data.get("hots") or []
        out: list[HotKeyword] = []
        for h in items:
            if isinstance(h, dict):
                word = (h.get("first") or "")
                out.append(HotKeyword(str(word), 0))
        return out

    def boards(self) -> list[LeaderboardEntry]:
        return list(_BOARDS)


from . import _register  # noqa: E402

_register(WySource())
