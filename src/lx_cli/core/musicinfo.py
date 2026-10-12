"""歌曲 id 构造与 meta 编解码 —— **本项目最关键的契约模块**。

依据：``lx-music-desktop-2.12.5/src/common/utils/tools.ts:3-56`` (``toNewMusicInfo``)。

id 规则（务必逐条遵守）::

    kw / tx / wy / mg :  <source>_<songmid>
    kg                :  <songmid>_<hash>          ← 无 source 前缀！
    local             :  文件绝对路径

真实用户库统计（1892 行）印证：``kg`` 有 934 行是**无前缀**形态，
仅有 24 行 ``kg_<songId>_<hash>``（运行时 ``${source}_${id}`` 二次拼接的产物，
见 ``core/music/utils.ts:44``）。

因此：

* **绝不能** 用 ``id.split('_')[0]`` 反推 source —— 一律读 ``source`` 字段
* ``local`` 的 id 是路径，**禁止按 ``_`` 切分**
* 读取需**容忍**两种 kg 形态；写入一律用**规范形态**（无前缀）

参考：``LX-CLI-project/research/05-kg-id-定论与文档更正.md``
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable

# 内置源 id（与桌面端 sources 注册表一致；bd/xm 未注册故不列入）
ONLINE_SOURCES: tuple[str, ...] = ("kg", "kw", "tx", "mg", "wy")
LOCAL_SOURCE = "local"
ALL_DB_SOURCES: tuple[str, ...] = (*ONLINE_SOURCES, LOCAL_SOURCE)

#: source id → 中文显示名（照 ``src/lang/zh-cn.json:629-635`` 的 ``source_*`` 键）
#: 注意 ``tx`` 是「企鹅音乐」，不是「QQ音乐」（后者是 SDK 里的未使用硬编码串）
SOURCE_LABELS: dict[str, str] = {
    "kg": "酷狗音乐",
    "kw": "酷我音乐",
    "tx": "企鹅音乐",
    "wy": "网易音乐",
    "mg": "咪咕音乐",
    "local": "本地音乐",
    "bd": "百度音乐",   # 桌面端存在但未注册；保留映射以备将来
}

#: ``common.sourceNameType == 'alias'`` 时的别名（``source_alias_*``）
SOURCE_ALIASES: dict[str, str] = {
    "wy": "小芸音乐",
    "xm": "小霞音乐",
}

#: 多歌手分隔符 —— **存储/展示口径** 只有顿号。
#: 注意：模糊匹配时 LX 用的是更大的一组（见 ``matcher.py``），两者不可混用。
SINGER_SEPARATOR = "、"


def source_label(source: str | None, *, name_type: str = "real") -> str:
    """返回 source 的显示名。

    :param name_type: ``config_v2.json`` 的 ``common.sourceNameType``（``real``|``alias``）
    """
    if not source:
        return ""
    if name_type == "alias" and source in SOURCE_ALIASES:
        return SOURCE_ALIASES[source]
    return SOURCE_LABELS.get(source, source)


# ---------------------------------------------------------------- id 构造


def make_song_id(source: str, songmid: str | int | None,
                 hash_: str | None = None) -> str:
    """按桌面端规则构造歌曲 id。

    >>> make_song_id('wy', '2635292773')
    'wy_2635292773'
    >>> make_song_id('kg', '631537655', '5A86012526BD981CD3AF1125E3FE234A')
    '631537655_5A86012526BD981CD3AF1125E3FE234A'
    >>> make_song_id('local', r'C:\\Music\\a.flac')
    'C:\\\\Music\\\\a.flac'
    """
    if songmid is None:
        raise ValueError(f"songmid required to build id (source={source!r})")

    if source == LOCAL_SOURCE:
        return str(songmid)

    if source == "kg":
        # tools.ts:39 —— kg 覆写为 songmid_hash，**不带 source 前缀**
        if not hash_:
            raise ValueError(
                "kg id requires both songmid and hash "
                "(id = '<songId>_<hash>'); missing hash would produce an "
                "id LX never generates"
            )
        return f"{songmid}_{hash_}"

    return f"{source}_{songmid}"


@dataclass(frozen=True)
class ParsedId:
    """解析结果。``songmid``/``hash`` 为 None 表示该形态无法拆出。"""
    source: str
    songmid: str | None
    hash: str | None
    raw: str
    is_canonical: bool          # 是否符合当前 source 的规范形态


def parse_song_id(song_id: str, source: str) -> ParsedId:
    """按 source **解析**（而非猜测）歌曲 id。

    必须显式传入 ``source``：因为 id 前缀不可靠（kg 无前缀、local 是路径）。
    """
    if source == LOCAL_SOURCE:
        # 路径里含 '_'，绝不切分
        return ParsedId(source, song_id, None, song_id, True)

    if source == "kg":
        # 兼容三种形态：
        #   规范       631537655_5A86...
        #   二次前缀   kg_631537655_5A86...
        #   仅有 id    kg_631537655
        body = song_id
        if body.startswith("kg_"):
            body = body[3:]
        if "_" in body:
            songmid, _, hash_ = body.partition("_")
            return ParsedId(source, songmid, hash_, song_id,
                            is_canonical=not song_id.startswith("kg_"))
        return ParsedId(source, body, None, song_id,
                        is_canonical=not song_id.startswith("kg_"))

    prefix = f"{source}_"
    if song_id.startswith(prefix):
        return ParsedId(source, song_id[len(prefix):], None, song_id, True)
    return ParsedId(source, song_id, None, song_id, False)


# ---------------------------------------------------------------- 歌手


def split_singers(singer: str | None) -> list[str]:
    """按**存储口径**拆分歌手（只按 ``、``）。

    不要用 ``;`` / ``&`` / ``,`` 拆 —— 实测它们是歌手名的一部分
    （如 ``Raven & Kreyn、RudeLies、Nino Lucarelli`` 是 3 个歌手）。
    """
    if not singer:
        return []
    return [s.strip() for s in singer.split(SINGER_SEPARATOR) if s.strip()]


# ---------------------------------------------------------------- meta


def encode_meta(meta: dict[str, Any] | None) -> str:
    """meta dict → DB 存储的 JSON 字符串。"""
    if meta is None:
        return "{}"
    return json.dumps(meta, ensure_ascii=False)


def decode_meta(raw: str | None) -> dict[str, Any]:
    """DB 的 meta JSON 字符串 → dict。**宽容**：损坏时返回空 dict 而非抛错。"""
    if not raw:
        return {}
    if isinstance(raw, dict):        # 容错：某些路径可能已是 dict
        return raw
    try:
        val = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return val if isinstance(val, dict) else {}


def normalize_songmid(value: Any) -> str:
    """``meta.songId`` / ``songmid`` 统一转字符串。

    实测类型不稳定：kg 有 int 89 / str 869；kw int 287 / str 14。
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def quality_types(meta: dict[str, Any] | None) -> list[str]:
    """可用音质列表（仅取 ``type``，按 ``qualitys`` 数组顺序）。

    ⚠️ 判**能否播放**要用 ``meta._qualitys[q]``（字典），
    而 ``qualitys`` 数组是给 UI 角标/展示用的。
    """
    if not meta:
        return []
    out = []
    for q in (meta.get("qualitys") or []):
        if isinstance(q, dict) and q.get("type"):
            out.append(str(q["type"]))
    return out


def has_quality(meta: dict[str, Any] | None, quality: str) -> bool:
    """该曲是否**真正可播**指定音质 —— 用 ``_qualitys`` 字典判定。"""
    if not meta:
        return False
    qs = meta.get("_qualitys")
    return isinstance(qs, dict) and qs.get(quality) is not None


# ---------------------------------------------------------------- 领域对象


@dataclass
class SongRecord:
    """统一歌曲记录 —— 搜索/DB 读取的共同形态。

    ★ 相比旧版新增 ``id``：旧版 ``SongRecord`` 只有 ``songmid``，
    导致"搜索结果无法落库"（见 01 契约 §8 的 D 需求障碍）。
    """

    id: str
    name: str
    singer: str
    source: str
    songmid: str = ""
    album_name: str = ""
    album_id: str = ""
    interval: str = ""
    hash: str | None = None
    img: str | None = None
    types: list[dict] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def singer_list(self) -> list[str]:
        return split_singers(self.singer)

    def to_json(self, *, name_type: str = "real") -> dict[str, Any]:
        return {
            "id": self.id,
            "songmid": self.songmid,
            "name": self.name,
            "singer": self.singer,
            "singerList": self.singer_list,
            "albumName": self.album_name,
            "albumId": self.album_id,
            "interval": self.interval,
            "source": self.source,
            "sourceLabel": source_label(self.source, name_type=name_type),
            "types": list(self.types),
            "img": self.img,
        }

    def to_db_row(self, list_id: str) -> dict[str, Any]:
        """转为 ``my_list_music_info`` 的一行（可直接交给 db_writer）。"""
        return {
            "id": self.id,
            "listId": list_id,
            "name": self.name,
            "singer": self.singer,
            "source": self.source,
            "interval": self.interval,
            "meta": encode_meta(self.meta),
        }


def from_db_row(row: dict[str, Any] | Iterable) -> SongRecord:
    """从 ``my_list_music_info`` 行构造 SongRecord。"""
    d = dict(row) if not isinstance(row, dict) else row
    meta = decode_meta(d.get("meta"))
    source = d.get("source") or ""
    song_id = d.get("id") or ""
    parsed = parse_song_id(song_id, source) if source else None
    return SongRecord(
        id=song_id,
        name=d.get("name") or "",
        singer=d.get("singer") or "",
        source=source,
        songmid=normalize_songmid(meta.get("songId"))
        or (parsed.songmid if parsed else ""),
        album_name=meta.get("albumName") or "",
        album_id=normalize_songmid(meta.get("albumId")),
        interval=d.get("interval") or "",
        hash=meta.get("hash") or (parsed.hash if parsed else None),
        img=meta.get("picUrl") or None,
        types=list(meta.get("qualitys") or []),
        meta=meta,
    )
