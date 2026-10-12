"""平台元数据源的协议与领域类型。

设计要点（对比旧版 ``lx-cli/sources/base.py``）：

1. 旧的 ``SongRecord`` **没有 ``id`` 字段**（只有 ``songmid``），
   而 DB 的 id 是**复合**的（kg 为 ``<songId>_<hash>``）。
   这直接导致"搜索结果无法落库" —— 本版用 :meth:`SongRecord.to_song_id`
   复用 ``core.musicinfo.make_song_id`` 补上。
2. 旧的 ``types`` 是 ``list[str]``，丢了尺寸/hash；本版保留为 ``list[dict]``
   （与 DB 的 ``meta.qualitys`` 同构，可直接落库）。
3. 补 ``singer_list``（按**存储口径** ``、`` 拆分）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.musicinfo import (
    make_song_id, source_label, split_singers,
)
from ..errors import EXIT_UPSTREAM, LxCliError


class SourceError(LxCliError):
    """平台接口错误。带平台 id，便于上层区分。

    ⚠️ 继承自 :class:`lx_cli.errors.LxCliError`（而不是裸 ``Exception``），
    这样 CLI 层能统一把它翻译成稳定的错误 JSON 与退出码；
    否则会退化成"未预期异常"，打印出 ``SourceError: …`` 这种裸 repr。
    """

    exit_code = EXIT_UPSTREAM
    code = "source"

    def __init__(self, platform: str, message: str, *,
                 cause: BaseException | None = None,
                 detail: dict | None = None) -> None:
        super().__init__(f"{platform}: {message}", cause=cause, detail=detail)
        self.platform = platform
        self.message = f"{platform}: {message}"


#: 支持的平台（与桌面端 ``musicSdk/index.js`` 注册表一致；bd/xm 未注册故不含）
PLATFORMS: tuple[str, ...] = ("kg", "kw", "tx", "mg", "wy")


@dataclass
class SongRecord:
    """一首歌的元数据（跨平台统一形态）。

    ``id`` 是**可落库的复合 id**（见 ``core.musicinfo.make_song_id``），
    这是需求"搜索 → 插入歌单"的关键。
    """

    platform: str
    songmid: str
    name: str
    singer: str
    album_name: str = ""
    album_id: str = ""
    interval: str = ""
    hash: str | None = None            # kg 必需
    img: str | None = None
    types: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------

    @property
    def id(self) -> str:
        """可落库的歌曲 id（kg 为 ``<songmid>_<hash>``，无前缀）。"""
        return self.to_song_id()

    @property
    def singer_list(self) -> list[str]:
        return split_singers(self.singer)

    @property
    def source_label(self) -> str:
        return source_label(self.platform)

    def to_song_id(self) -> str:
        return make_song_id(self.platform, self.songmid, self.hash)

    # ------------------------------------------------------------

    def to_meta(self) -> dict[str, Any]:
        """构造 DB ``meta`` 列的内容（与桌面端 ``toNewMusicInfo`` 对齐）。

        * 公共：``songId`` ``albumName`` ``picUrl`` ``qualitys`` ``_qualitys`` ``albumId``
        * kg：``hash``（必填）
        """
        meta: dict[str, Any] = {
            "songId": self.songmid,
            "albumName": self.album_name,
            "picUrl": self.img or "",
            "qualitys": list(self.types),
            "_qualitys": {
                str(t.get("type")): {k: v for k, v in t.items() if k != "type"}
                for t in self.types if isinstance(t, dict) and t.get("type")
            },
        }
        if self.album_id:
            meta["albumId"] = self.album_id
        if self.platform == "kg" and self.hash:
            meta["hash"] = self.hash
        # 平台特有字段（tx 的 strMediaMid / mg 的 copyrightId 等）
        for key in ("strMediaMid", "albumMid", "id", "copyrightId",
                    "lrcUrl", "trcUrl", "mrcUrl", "albumAudioId"):
            if key in self.extra and self.extra[key] not in (None, ""):
                meta[key] = self.extra[key]
        return meta

    def to_db_row(self, list_id: str) -> dict[str, Any]:
        """可直接交给 ``db_writer.add_songs`` 的行。"""
        from ..core.musicinfo import encode_meta
        return {
            "id": self.to_song_id(),
            "listId": list_id,
            "name": self.name,
            "singer": self.singer,
            "source": self.platform,          # ★ 平台标识，不是脚本名
            "interval": self.interval,
            "meta": encode_meta(self.to_meta()),
        }

    def to_json(self, *, name_type: str = "real") -> dict[str, Any]:
        """CLI ``--json`` 输出（需求 C：作者/名/专辑/来源）。"""
        return {
            "id": self.to_song_id(),
            "songmid": self.songmid,
            "name": self.name,
            "singer": self.singer,
            "singerList": self.singer_list,
            "albumName": self.album_name,
            "albumId": self.album_id,
            "interval": self.interval,
            "source": self.platform,                                   # ③ 平台标识
            "sourceLabel": source_label(self.platform, name_type=name_type),
            "origin": "musicSdk",                                      # ① 数据来源
            "types": list(self.types),
            "img": self.img,
        }


@dataclass
class SearchResult:
    platform: str
    list: list[SongRecord]
    total: int = 0
    page: int = 1
    all_page: int = 1
    limit: int = 30

    def to_json(self, *, name_type: str = "real") -> dict[str, Any]:
        return {
            "source": self.platform,
            "sourceLabel": source_label(self.platform, name_type=name_type),
            "page": self.page,
            "allPage": self.all_page,
            "total": self.total,
            "limit": self.limit,
            "list": [s.to_json(name_type=name_type) for s in self.list],
        }


@dataclass
class AlbumInfo:
    id: str
    name: str
    artist: str = ""
    pic_url: str | None = None
    size: int = 0
    songs: list[SongRecord] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "artist": self.artist,
                "picUrl": self.pic_url, "size": self.size,
                "songs": [s.to_json() for s in self.songs]}


@dataclass
class LeaderboardEntry:
    id: str
    name: str
    bangid: str = ""
    platform: str = ""

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "bangid": self.bangid,
                "source": self.platform}


@dataclass
class Comment:
    author: str
    content: str
    time: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {"author": self.author, "content": self.content, "time": self.time}


@dataclass
class HotKeyword:
    keyword: str
    score: int = 0

    def to_json(self) -> dict[str, Any]:
        return {"keyword": self.keyword, "score": self.score}


class PlatformSource:
    """一个平台官方接口客户端的协议。

    子类声明 :attr:`features` 并实现其中的方法；未实现的方法抛
    :class:`SourceError`（由 CLI 转成"该平台不支持此功能"）。
    """

    platform: str = ""
    features: tuple[str, ...] = ()

    # ---- 查询 ----

    def search(self, keyword: str, page: int = 1, limit: int = 30) -> SearchResult:
        raise SourceError(self.platform, "search 不支持")

    def song(self, songmid: str) -> SongRecord:
        raise SourceError(self.platform, "song 不支持")

    def album(self, album_id: str) -> AlbumInfo:
        raise SourceError(self.platform, "album 不支持")

    def leaderboard(self, board: str | None = None, page: int = 1,
                    limit: int = 100) -> SearchResult:
        raise SourceError(self.platform, "leaderboard 不支持")

    def songlist(self, list_id: str, page: int = 1, limit: int = 36) -> SearchResult:
        raise SourceError(self.platform, "songlist 不支持")

    def singer(self, singer_id: str, page: int = 1, limit: int = 30) -> SearchResult:
        raise SourceError(self.platform, "singer 不支持")

    def lyric(self, songmid: str) -> dict[str, Any]:
        raise SourceError(self.platform, "lyric 不支持")

    def comment(self, songmid: str, page: int = 1, limit: int = 20) -> list[Comment]:
        raise SourceError(self.platform, "comment 不支持")

    def hot(self) -> list[HotKeyword]:
        raise SourceError(self.platform, "hot 不支持")

    def tip(self, keyword: str, limit: int = 10) -> list[SongRecord]:
        raise SourceError(self.platform, "tip 不支持")

    # ---- 元信息 ----

    def boards(self) -> list[LeaderboardEntry]:
        return []
