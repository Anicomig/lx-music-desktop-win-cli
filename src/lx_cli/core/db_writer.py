"""数据库**写入**（歌单增删改）。

修复旧版 ``db_writer.py`` 的缺陷：

1. ``inserted += 1`` 无条件自增 —— 与自身 docstring "excluding dupes" 矛盾，
   重复 id 也会被计入。改为按 ``rowcount`` 统计。
2. ``_gen_userlist_id`` = ``userlist_{毫秒}`` —— 同一毫秒内两次创建会**主键冲突崩溃**。
   改为毫秒 + 递增序号 + 随机后缀，并检查唯一性。
3. **无事务隔离** —— 读-改-写（读 existing → 算 combined → 删 order → 重插）
   在并发下会丢失更新。改为 ``BEGIN IMMEDIATE`` 立即取写锁。
4. ``order`` 行重建时假定 id 唯一 —— 用字典去重，避免重复插入。

写入纪律（硬要求）：

* **必须 LX 关闭**（LX 是内存缓存 + 全量回写，运行时写入会被覆盖）
* 每次调用一个事务，失败整体回滚
* 幂等：同 id 重复添加不产生重复行
"""
from __future__ import annotations

import random
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

from .._logging import get_logger
from ..errors import DbError, LxRunningError, NoSuchListError
from ..paths import db_path

log = get_logger()

#: LX 内置虚拟歌单（无 my_list 行，不可重命名/删除）
VIRTUAL_LISTS = ("default", "love")


# ------------------------------------------------------------------ 连接


def write_connect(db_override: Path | str | None = None,
                  exe_path: Path | None = None) -> sqlite3.Connection:
    """打开**可写**连接（不带 ``mode=ro``）。"""
    p = db_path(exe_path, override=db_override)
    if not Path(p).exists():
        raise DbError(f"找不到数据库：{p}", detail={"path": str(p)})
    conn = sqlite3.connect(str(p), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def assert_lx_closed(*, force: bool = False) -> None:
    """写库前确认 LX 已关闭。

    LX 把歌单缓存在内存、退出/变更时全量回写；运行时改库会被覆盖。
    """
    if force:
        return
    from .launcher import is_running
    if is_running():
        raise LxRunningError(
            "LX Music 正在运行，写库可能被它覆盖。请先关闭 LX，或加 --force。",
        )


# ------------------------------------------------------------------ 工具


def _now_ms() -> int:
    return int(time.time() * 1000)


def _gen_userlist_id(conn: sqlite3.Connection) -> str:
    """生成唯一的用户歌单 id（``userlist_{ms}{seq}``）。

    旧版用纯毫秒，同毫秒两次创建会撞主键。
    """
    base = _now_ms()
    for i in range(1000):
        cand = f"userlist_{base}{i:03d}" if i else f"userlist_{base}"
        exists = conn.execute(
            "SELECT 1 FROM my_list WHERE id = ?", (cand,)).fetchone()
        if not exists:
            return cand
        base = _now_ms()          # 换一个毫秒再试
    # 极端兜底
    return f"userlist_{base}_{random.randint(0, 0xFFFFFF):06x}"


def _existing_ordered_ids(conn: sqlite3.Connection, list_id: str) -> list[str]:
    """取该歌单当前的 id 顺序（保持展示顺序，缺 order 的排最后）。"""
    rows = conn.execute(
        'SELECT m.id FROM my_list_music_info m '
        'LEFT JOIN my_list_music_info_order o '
        '  ON o.musicInfoId = m.id AND o.listId = m.listId '
        'WHERE m.listId = ? ORDER BY (o."order" IS NULL), o."order"',
        (list_id,),
    ).fetchall()
    seen: set[str] = set()
    out: list[str] = []
    for r in rows:
        sid = r["id"]
        if sid not in seen:          # 去重：order 表无唯一约束，可能有重复行
            seen.add(sid)
            out.append(sid)
    return out


def _rewrite_order(conn: sqlite3.Connection, list_id: str,
                   ordered_ids: list[str]) -> None:
    """整表重写该歌单的 order 行（0..n-1）。"""
    conn.execute('DELETE FROM my_list_music_info_order WHERE listId = ?', (list_id,))
    for i, sid in enumerate(ordered_ids):
        conn.execute(
            'INSERT INTO my_list_music_info_order (listId, musicInfoId, "order") '
            'VALUES (?, ?, ?)', (list_id, sid, i))


def _list_exists(conn: sqlite3.Connection, list_id: str) -> bool:
    if list_id in VIRTUAL_LISTS:
        return True
    return conn.execute(
        "SELECT 1 FROM my_list WHERE id = ?", (list_id,)).fetchone() is not None


def _touch_list(conn: sqlite3.Connection, list_id: str) -> None:
    """更新 locationUpdateTime（虚拟歌单没有 my_list 行，跳过）。"""
    if list_id in VIRTUAL_LISTS:
        return
    conn.execute(
        "UPDATE my_list SET locationUpdateTime = ? WHERE id = ?",
        (_now_ms(), list_id),
    )


# ------------------------------------------------------------------ 歌单 CRUD


def create_list(name: str, *, position: int | None = None,
                source: str | None = None, source_list_id: str | None = None,
                db_override=None, exe_path=None) -> dict[str, Any]:
    """新建空歌单。返回新行。"""
    if not name or not name.strip():
        raise DbError("歌单名不能为空")
    with write_connect(db_override, exe_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        new_id = _gen_userlist_id(conn)
        if position is None:
            row = conn.execute(
                "SELECT COALESCE(MAX(position), -1) AS p FROM my_list").fetchone()
            position = int(row["p"]) + 1
        ts = _now_ms()
        conn.execute(
            "INSERT INTO my_list "
            "(id, name, source, sourceListId, position, locationUpdateTime) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (new_id, name, source, source_list_id, position, ts),
        )
        conn.commit()
    return {"id": new_id, "name": name, "source": source,
            "sourceListId": source_list_id, "position": position,
            "locationUpdateTime": ts, "isVirtual": False}


def rename_list(list_id: str, new_name: str, *, db_override=None,
                exe_path=None) -> bool:
    """重命名歌单。虚拟歌单不可重命名（与 LX 行为一致）。"""
    if list_id in VIRTUAL_LISTS:
        raise DbError(f"{list_id} 是内置歌单，LX 不允许重命名")
    if not new_name or not new_name.strip():
        raise DbError("歌单名不能为空")
    with write_connect(db_override, exe_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "UPDATE my_list SET name = ?, locationUpdateTime = ? WHERE id = ?",
            (new_name, _now_ms(), list_id))
        conn.commit()
        return cur.rowcount > 0


def delete_list(list_id: str, *, db_override=None, exe_path=None) -> bool:
    """删除歌单（级联删除其歌曲与 order 行）。"""
    if list_id in VIRTUAL_LISTS:
        raise DbError(f"{list_id} 是内置歌单，不可删除")
    with write_connect(db_override, exe_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute("DELETE FROM my_list WHERE id = ?", (list_id,))
        if cur.rowcount == 0:
            conn.rollback()
            return False
        conn.execute("DELETE FROM my_list_music_info WHERE listId = ?", (list_id,))
        conn.execute("DELETE FROM my_list_music_info_order WHERE listId = ?", (list_id,))
        conn.commit()
        return True


# ------------------------------------------------------------------ 歌曲写入


def add_songs(list_id: str, songs: list[dict[str, Any]], *,
              position: str = "bottom",
              db_override=None, exe_path=None) -> dict[str, Any]:
    """把歌曲加入歌单。

    :param songs: 每项需含 ``id`` ``name`` ``singer`` ``source``；
                  可选 ``interval`` ``meta``（dict 或 JSON 字符串）
    :param position: ``"bottom"`` 或 ``"top"``
    :returns: ``{"added": n, "skipped": n, "addedIds": [...], "skippedIds": [...]}``

    幂等：同 id 已存在则跳过（不计入 added）。
    """
    if position not in ("bottom", "top"):
        raise DbError(f"position 必须是 'top' 或 'bottom'，收到 {position!r}")

    result = {"added": 0, "skipped": 0, "addedIds": [], "skippedIds": []}
    if not songs:
        return result

    with write_connect(db_override, exe_path) as conn:
        conn.execute("BEGIN IMMEDIATE")     # ★ 立即取写锁，避免读-改-写丢失
        if not _list_exists(conn, list_id):
            raise NoSuchListError(f"歌单不存在：{list_id}", detail={"listId": list_id})

        existing = _existing_ordered_ids(conn, list_id)
        existing_set = set(existing)

        # 1) 插入新歌（跳过已存在）
        new_ids: list[str] = []
        for s in songs:
            sid = s.get("id")
            if not sid:
                raise DbError(f"歌曲缺少 id 字段：{s!r}")
            if sid in existing_set:
                result["skipped"] += 1
                result["skippedIds"].append(sid)
                continue
            meta = s.get("meta", "{}")
            from .musicinfo import encode_meta
            meta_str = meta if isinstance(meta, str) else encode_meta(meta)
            cur = conn.execute(
                "INSERT OR IGNORE INTO my_list_music_info "
                "(id, listId, name, singer, source, interval, meta) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (sid, list_id, s.get("name") or "", s.get("singer") or "",
                 s.get("source") or "", s.get("interval") or "", meta_str),
            )
            if cur.rowcount > 0:
                result["added"] += 1
                result["addedIds"].append(sid)
                existing_set.add(sid)
                new_ids.append(sid)
            else:
                result["skipped"] += 1
                result["skippedIds"].append(sid)

        # 2) 重写顺序
        if position == "top":
            ordered = new_ids + existing
        else:
            ordered = existing + new_ids
        _rewrite_order(conn, list_id, ordered)
        _touch_list(conn, list_id)
        conn.commit()

    return result


def remove_songs(list_id: str, song_ids: Iterable[str], *,
                 db_override=None, exe_path=None) -> int:
    """从歌单移除歌曲，返回实际移除数。"""
    ids = [i for i in song_ids if i]
    if not ids:
        return 0
    with write_connect(db_override, exe_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        ph = ",".join("?" for _ in ids)
        cur = conn.execute(
            f"DELETE FROM my_list_music_info WHERE listId = ? AND id IN ({ph})",
            [list_id, *ids])
        removed = cur.rowcount
        conn.execute(
            f"DELETE FROM my_list_music_info_order WHERE listId = ? AND musicInfoId IN ({ph})",
            [list_id, *ids])
        # 重新压实 order（保持连续 0..n-1）
        _rewrite_order(conn, list_id, _existing_ordered_ids(conn, list_id))
        _touch_list(conn, list_id)
        conn.commit()
    return removed


def reorder_songs(list_id: str, song_ids: list[str], *,
                  db_override=None, exe_path=None) -> int:
    """按给定顺序重排歌单。返回写入行数。"""
    with write_connect(db_override, exe_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        if not _list_exists(conn, list_id):
            raise NoSuchListError(f"歌单不存在：{list_id}")
        _rewrite_order(conn, list_id, list(song_ids))
        _touch_list(conn, list_id)
        conn.commit()
    return len(song_ids)
