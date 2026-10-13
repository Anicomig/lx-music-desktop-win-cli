"""只读数据库访问（``lx.data.db``）。

修复旧版缺陷：

1. ``songs_in_list`` 用 ``ORDER BY COALESCE(o."order", 0)`` **无 tie-breaker** ——
   稀疏 order 会把缺失行全塌到 0 并排到最前，**静默错序**。
   本模块改为 ``ORDER BY (o."order" IS NULL), o."order"``，并把缺 order 的行排在最后。
2. ``find_songs`` 用 ``LOWER(name) LIKE ?`` —— 对中文**无效**（SQLite 的 LOWER 只处理 ASCII），
   且未转义 ``%`` / ``_``。本模块改用 **SQLite 的 LIKE 默认不区分大小写** 特性 +
   ``ESCAPE`` 转义通配符。
3. 表名硬编码 —— 改为从 ``sqlite_master`` 反射。

分页/排序相关事实（来自真实库）：
* ``order`` 可能**稀疏**（实测某歌单缺 226/227）
* ``my_list_music_info_order`` **无主键无唯一约束**
* ``order`` 是 SQL 保留字，**必须加引号**
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .._logging import get_logger
from ..errors import DbError, NoSuchListError
from ..paths import db_path

log = get_logger()

_VALID_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: 排序表达式：有 order 的按 order 升序，**缺 order 的排最后**（旧版会塌到 0 排最前）
_ORDER_EXPR = '(o."order" IS NULL), o."order"'


def connect(db_override: Path | str | None = None,
            exe_path: Path | None = None) -> sqlite3.Connection:
    """以**只读**模式打开数据库（URI ``?mode=ro``）。

    只读是硬要求：CLI 的读命令必须能在 LX 运行时安全执行。
    """
    p = db_path(exe_path, override=db_override)
    if not Path(p).exists():
        raise DbError(f"找不到数据库：{p}", detail={"path": str(p)})
    try:
        conn = sqlite3.connect(f"file:{Path(p).as_posix()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise DbError(f"打开数据库失败：{p}: {exc}",
                      detail={"path": str(p)}, cause=exc) from exc
    conn.row_factory = sqlite3.Row
    return conn


def _check_name(name: str) -> str:
    if not _VALID_NAME.match(name):
        raise DbError(f"非法表名/列名：{name!r}")
    return name


# ------------------------------------------------------------------ 结构


def list_tables(db_override=None, exe_path=None) -> list[str]:
    with connect(db_override, exe_path) as c:
        rows = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    return [r["name"] for r in rows]


def table_info(table: str, db_override=None, exe_path=None) -> list[dict[str, Any]]:
    t = _check_name(table)
    with connect(db_override, exe_path) as c:
        rows = c.execute(f'PRAGMA table_info("{t}")').fetchall()
    return [dict(r) for r in rows]


def row_counts(tables: Iterable[str] | None = None, db_override=None,
               exe_path=None) -> dict[str, int]:
    names = list(tables) if tables else list_tables(db_override, exe_path)
    out: dict[str, int] = {}
    with connect(db_override, exe_path) as c:
        for t in names:
            out[t] = c.execute(f'SELECT COUNT(*) AS n FROM "{_check_name(t)}"').fetchone()["n"]
    return out


def query(sql: str, params: Iterable[Any] = (),
          db_override=None, exe_path=None) -> list[dict[str, Any]]:
    """执行**只读** SQL。写语句会被 SQLite 的只读模式拒绝。"""
    with connect(db_override, exe_path) as c:
        try:
            rows = c.execute(sql, tuple(params)).fetchall()
        except sqlite3.Error as exc:
            raise DbError(f"SQL 执行失败：{exc}", detail={"sql": sql[:200]}, cause=exc) from exc
    return [dict(r) for r in rows]


# ------------------------------------------------------------------ 歌单


def list_lists(include_virtual: bool = True, db_override=None,
               exe_path=None) -> list[dict[str, Any]]:
    """全部歌单：``my_list`` 的用户歌单 + 虚拟歌单 ``default``/``love``。

    虚拟歌单**没有** ``my_list`` 行，只存在于歌曲表里（名称是 i18n key）。
    """
    out: list[dict[str, Any]] = []

    if include_virtual:
        for vid, label in (("default", "默认列表"), ("love", "我喜欢")):
            out.append({
                "id": vid, "name": label, "source": None,
                "sourceListId": None, "position": -1 if vid == "default" else -2,
                "locationUpdateTime": None, "isVirtual": True, "songCount": 0,
            })

    with connect(db_override, exe_path) as c:
        rows = c.execute(
            "SELECT id, name, source, sourceListId, position, locationUpdateTime "
            "FROM my_list ORDER BY position"
        ).fetchall()
        counts = {
            r["listId"]: r["n"]
            for r in c.execute(
                "SELECT listId, COUNT(*) AS n FROM my_list_music_info GROUP BY listId"
            )
        }

    for r in rows:
        d = dict(r)
        d["isVirtual"] = False
        d["songCount"] = counts.get(d["id"], 0)
        out.append(d)

    # 给虚拟歌单填真实计数
    for item in out:
        if item["isVirtual"]:
            item["songCount"] = counts.get(item["id"], 0)
    return out


def get_list(list_id: str, db_override=None, exe_path=None) -> dict[str, Any] | None:
    if list_id in ("default", "love"):
        name = "默认列表" if list_id == "default" else "我喜欢"
        return {"id": list_id, "name": name, "source": None,
                "sourceListId": None, "position": None,
                "locationUpdateTime": None, "isVirtual": True}
    with connect(db_override, exe_path) as c:
        r = c.execute(
            "SELECT id, name, source, sourceListId, position, locationUpdateTime "
            "FROM my_list WHERE id = ?", (list_id,)
        ).fetchone()
    if r is None:
        return None
    d = dict(r)
    d["isVirtual"] = False
    return d


def songs_in_list(list_id: str, limit: int | None = None, offset: int = 0,
                  db_override=None, exe_path=None) -> list[dict[str, Any]]:
    """按 LX 展示顺序取歌单内的歌。

    ★ 排序修复：缺 ``order`` 的行**排到最后**，而不是被 ``COALESCE(...,0)`` 拉到最前。
    """
    sql = (
        "SELECT m.id, m.listId, m.name, m.singer, m.source, m.interval, m.meta, "
        "       o.\"order\" AS sort_order "
        "FROM my_list_music_info m "
        "LEFT JOIN my_list_music_info_order o "
        "  ON o.musicInfoId = m.id AND o.listId = m.listId "
        f"WHERE m.listId = ? ORDER BY {_ORDER_EXPR}"
    )
    params: list[Any] = [list_id]
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params += [limit, offset]
    elif offset:
        sql += " LIMIT -1 OFFSET ?"
        params.append(offset)

    with connect(db_override, exe_path) as c:
        return [dict(r) for r in c.execute(sql, params)]


def count_songs(list_id: str, db_override=None, exe_path=None) -> int:
    with connect(db_override, exe_path) as c:
        return c.execute(
            "SELECT COUNT(*) AS n FROM my_list_music_info WHERE listId = ?",
            (list_id,),
        ).fetchone()["n"]


# ------------------------------------------------------------------ 搜索


def _escape_like(s: str) -> str:
    """转义 LIKE 通配符（``%`` ``_`` ``\\``）。"""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def find_songs(pattern: str, *, sources: Iterable[str] | None = None,
               list_id: str | None = None, limit: int = 100,
               db_override=None, exe_path=None) -> list[dict[str, Any]]:
    """在**本地库**里按歌名/歌手做子串搜索。

    ★ 修复：
    * 去掉 ``LOWER()`` —— SQLite 的 ``LOWER`` 只处理 ASCII，对中文无意义；
      直接用 ``LIKE``（SQLite 的 LIKE 对 ASCII 本就大小写不敏感）。
    * 用 ``ESCAPE '\\'`` 转义 ``%`` / ``_``，避免用户输入被当通配符。
    """
    like = f"%{_escape_like(pattern)}%"
    sql = (
        "SELECT id, listId, name, singer, source, interval, meta "
        "FROM my_list_music_info "
        "WHERE (name LIKE ? ESCAPE '\\' OR singer LIKE ? ESCAPE '\\')"
    )
    params: list[Any] = [like, like]

    srcs = [s for s in (sources or []) if s]
    if srcs:
        sql += f" AND source IN ({','.join('?' for _ in srcs)})"
        params += srcs
    if list_id:
        sql += " AND listId = ?"
        params.append(list_id)

    sql += " ORDER BY name LIMIT ?"
    params.append(limit)

    with connect(db_override, exe_path) as c:
        return [dict(r) for r in c.execute(sql, params)]


def stats(db_override=None, exe_path=None) -> dict[str, Any]:
    with connect(db_override, exe_path) as c:
        total_lists = c.execute("SELECT COUNT(*) AS n FROM my_list").fetchone()["n"]
        total_songs = c.execute("SELECT COUNT(*) AS n FROM my_list_music_info").fetchone()["n"]
        distinct = c.execute(
            "SELECT COUNT(DISTINCT id) AS n FROM my_list_music_info").fetchone()["n"]
        ordering = c.execute(
            "SELECT COUNT(*) AS n FROM my_list_music_info_order").fetchone()["n"]
        by_source = {
            (r["source"] or "(none)"): r["n"]
            for r in c.execute(
                "SELECT source, COUNT(*) AS n FROM my_list_music_info "
                "GROUP BY source ORDER BY n DESC")
        }
        return {
            "lists": total_lists,
            "songs": total_songs,
            "distinctSongs": distinct,
            "ordering": ordering,
            "songsBySource": by_source,
        }


def list_dislikes(db_override=None, exe_path=None) -> list[dict[str, Any]]:
    with connect(db_override, exe_path) as c:
        return [dict(r) for r in c.execute(
            "SELECT type, content, meta FROM dislike_list")]


def list_downloads(*, limit: int = 20, db_override=None, exe_path=None
                   ) -> list[dict[str, Any]]:
    with connect(db_override, exe_path) as c:
        return [dict(r) for r in c.execute(
            "SELECT id, status, progress_downloaded, progress_total, fileName, filePath "
            "FROM download_list ORDER BY position LIMIT ?", (limit,))]


# --------------------------------------------------------------- 下载（download_list）

#: ``download_list.status`` 取值（来自 LX 常量 DOWNLOAD_STATUS）
DL_COMPLETED = "completed"
DL_ERROR = "error"
DL_RUN = "run"
DL_WAITING = "waiting"
DL_PAUSE = "pause"


def _download_select() -> str:
    return ("SELECT id, isComplate, status, statusText, quality, ext, "
            "progress_downloaded, progress_total, fileName, filePath, "
            "musicInfo, position FROM download_list")


def _parse_music_info(raw: str | None) -> dict[str, Any]:
    """``musicInfo`` 是 JSON 字符串，解析失败时返回空 dict（不抛）。"""
    import json
    if not raw:
        return {}
    try:
        v = json.loads(raw)
        return v if isinstance(v, dict) else {}
    except (ValueError, TypeError):
        return {}


def _download_row(r: sqlite3.Row) -> dict[str, Any]:
    mi = _parse_music_info(r["musicInfo"])
    total = r["progress_total"] or 0
    done = r["progress_downloaded"] or 0
    raw_id = mi.get("id") or ""
    source = mi.get("source") or ""
    # ★ 供 JS 音源脚本使用的**裸** songmid（去掉 source 前缀）。
    #   实测：带前缀的 kw_223088839 会让脚本取链失败，裸 223088839 才行。
    songmid = (mi.get("songmid") or "") if isinstance(mi, dict) else ""
    if not songmid and raw_id:
        try:
            from .musicinfo import parse_song_id
            if source:
                songmid = parse_song_id(raw_id, source).songmid
            else:
                songmid = raw_id
        except Exception:                          # noqa: BLE001
            songmid = raw_id
    return {
        "id": r["id"],
        "musicId": raw_id,                         # 原始（可能带前缀）
        "name": mi.get("name") or _name_from_file(r["fileName"]),
        "singer": mi.get("singer") or "",
        "source": source,
        "songmid": songmid or raw_id,              # 裸 id，可直接给下载用
        "quality": r["quality"],
        "ext": r["ext"],
        "status": r["status"],
        "statusText": r["statusText"],
        "isComplete": bool(r["isComplate"]),
        "progress": {"downloaded": done, "total": total},
        "percent": round(done / total * 100, 1) if total else (100.0 if r["isComplate"] else 0.0),
        "fileName": r["fileName"],
        "filePath": r["filePath"],
        "position": r["position"],
    }


def _name_from_file(file_name: str) -> str:
    """从 '歌名 - 歌手.ext' 兜底解析歌名。"""
    if not file_name:
        return ""
    stem = file_name.rsplit(".", 1)[0] if "." in file_name else file_name
    return stem.split(" - ", 1)[0].strip()


def downloads(*, status: str | None = None, source: str | None = None,
              quality: str | None = None, limit: int | None = None,
              db_override=None, exe_path=None) -> list[dict[str, Any]]:
    """列出下载记录（可按 status / source / quality 过滤）。

    :param status: ``completed`` / ``error`` / ``run`` … 或 ``incomplete``（未完成）
    """
    sql = _download_select()
    where: list[str] = []
    params: list[Any] = []
    if status == "incomplete":
        where.append("isComplate = 0")
    elif status:
        where.append("status = ?")
        params.append(status)
    if quality:
        where.append("quality = ?")
        params.append(quality)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY position"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)

    with connect(db_override, exe_path) as c:
        rows = [_download_row(r) for r in c.execute(sql, params)]
    # source 在 musicInfo JSON 里，SQL 过滤不了 —— 这里内存过滤
    if source:
        rows = [r for r in rows if r["source"] == source]
    return rows


def download_stats(*, db_override=None, exe_path=None) -> dict[str, Any]:
    """下载总览：计数、按状态/质量/平台分布、总字节。"""
    with connect(db_override, exe_path) as c:
        rows = [_download_row(r) for r in c.execute(_download_select())]

    by_status: dict[str, int] = {}
    by_quality: dict[str, int] = {}
    by_source: dict[str, int] = {}
    total_bytes = 0
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        by_quality[r["quality"]] = by_quality.get(r["quality"], 0) + 1
        if r["source"]:
            by_source[r["source"]] = by_source.get(r["source"], 0) + 1
        total_bytes += r["progress"]["downloaded"] or 0

    completed = by_status.get(DL_COMPLETED, 0)
    return {
        "total": len(rows),
        "completed": completed,
        "failed": by_status.get(DL_ERROR, 0),
        "incomplete": sum(1 for r in rows if not r["isComplete"]),
        "byStatus": by_status,
        "byQuality": by_quality,
        "bySource": by_source,
        "totalBytes": total_bytes,
        "totalMB": round(total_bytes / 1024 / 1024, 1),
    }


def verify_downloads(*, check_size: bool = True, size_tolerance: float = 0.10,
                     db_override=None, exe_path=None) -> dict[str, Any]:
    """校验 ``filePath`` 是否真实存在（找出"记录在但文件没了"）。

    :param check_size: 是否额外比对磁盘大小与 ``progress_total``
    :param size_tolerance: 大小允许的相对误差（默认 10%）

    ⚠️ 为什么默认 10% 而不是 1%：实测发现**正常文件也会有小幅差异**——
    LX 下载后会补写 ID3 标签（实测差异 -1.5% ~ +12.9%，65/70 是"实际更大"）。
    用 1% 会把 70 个正常文件误报成异常；10% 才能筛出**真正损坏**的（如半截文件）。
    """
    with connect(db_override, exe_path) as c:
        rows = [_download_row(r) for r in c.execute(_download_select())]

    missing, size_mismatch, present = [], [], []
    for r in rows:
        p = Path(r["filePath"]) if r["filePath"] else None
        if not p or not p.is_file():
            missing.append(r)
            continue
        if check_size:
            actual = p.stat().st_size
            expect = r["progress"]["total"] or 0
            if expect and abs(actual - expect) > expect * size_tolerance:
                r = {**r, "actualSize": actual, "expectedSize": expect}
                size_mismatch.append(r)
                continue
        present.append(r)

    return {
        "total": len(rows),
        "present": len(present),
        "missing": len(missing),
        "sizeMismatch": len(size_mismatch),
        "missingItems": missing,
        "sizeMismatchItems": size_mismatch,
    }
