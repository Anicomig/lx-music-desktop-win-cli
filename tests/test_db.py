"""DB 读写测试 —— 用**脱敏夹具**（真实库的结构，合成的内容）。

夹具由 ``scripts/make_fixture.py`` 从备份真实库生成，保留了关键边界：
* kg 裸 id（934）+ kg 二次前缀变体（24）
* local 的 id 是路径
* 稀疏 order（某歌单 246 行但 max=247，缺 226/227）
* 虚拟歌单 default/love 无 my_list 行
"""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from lx_cli.core import db_reader, db_writer
from lx_cli.core.musicinfo import decode_meta, encode_meta
from lx_cli.errors import DbError, NoSuchListError

FIXTURE = Path(__file__).parent / "fixtures" / "lx.data.db"
KG_SPARSE_LIST = "tx_01f8d8ef9ba89ef43cb1c28c289d2a9f"


@pytest.fixture()
def db(tmp_path) -> Path:
    """每个用例一份可写副本（夹具本身只读）。"""
    dst = tmp_path / "lx.data.db"
    shutil.copy2(FIXTURE, dst)
    return dst


# --------------------------------------------------------------- 只读层


class TestReader:
    def test_list_tables(self, db):
        tables = db_reader.list_tables(db_override=db)
        assert "my_list" in tables
        assert "my_list_music_info" in tables

    def test_lists_include_virtual(self, db):
        lists = db_reader.list_lists(db_override=db)
        ids = [x["id"] for x in lists]
        assert "default" in ids and "love" in ids
        virt = {x["id"]: x for x in lists}
        assert virt["default"]["isVirtual"] is True
        assert virt["default"]["songCount"] == 164
        assert virt["love"]["songCount"] == 188

    def test_virtual_lists_absent_from_my_list(self, db):
        names = {x["id"] for x in db_reader.list_lists(db_override=db)}
        assert {"default", "love"} <= names          # 以虚拟条目出现
        with db_reader.connect(db) as c:
            n = c.execute(
                "SELECT COUNT(*) FROM my_list WHERE id IN ('default','love')"
            ).fetchone()[0]
        assert n == 0                                # 但 my_list 里没有行

    def test_sparse_order_does_not_collapse_to_front(self, db):
        """★ 修复回归：缺 order 的行必须排最后，而不是被 COALESCE 塌到 0 排最前。

        夹具里该歌单 246 首歌但 order 最大 247（缺 226/227）。
        """
        songs = db_reader.songs_in_list(KG_SPARSE_LIST, db_override=db)
        assert len(songs) == 246
        orders = [s["sort_order"] for s in songs]
        # 前 246 个里的 order 应严格升序（无 NULL 在前）
        non_null = [o for o in orders if o is not None]
        assert non_null == sorted(non_null)
        assert orders[0] is not None, "首行不应是缺 order 的行（旧版 bug）"

    def test_find_songs_chinese(self, db):
        """中文子串搜索必须能用（旧版用 LOWER() 对中文无效）。"""
        rows = db_reader.find_songs("曲目", db_override=db, limit=5)
        assert rows, "中文关键字应能搜到夹具数据"

    def test_find_songs_escapes_wildcards(self, db):
        """用户输入 '%' 不应变成通配符。"""
        rows = db_reader.find_songs("%", db_override=db)
        assert rows == [], "未转义的 % 会匹配全部；应为空"

    def test_stats_shape(self, db):
        st = db_reader.stats(db_override=db)
        assert st["lists"] == 15
        assert st["songs"] == 1892
        assert sum(st["songsBySource"].values()) == 1892

    def test_reader_is_readonly(self, db):
        """只读连接必须拒绝写。"""
        with pytest.raises(DbError):
            db_reader.query("DELETE FROM my_list", db_override=db)

    def test_rejects_bad_table_name(self, db):
        with pytest.raises(DbError):
            db_reader.table_info("my_list; DROP TABLE x", db_override=db)


# --------------------------------------------------------------- 写入层


class TestWriterListCrud:
    def test_create_list(self, db):
        row = db_writer.create_list("新歌单", db_override=db)
        assert row["id"].startswith("userlist_")
        assert db_reader.get_list(row["id"], db_override=db)["name"] == "新歌单"

    def test_create_ids_unique_in_same_ms(self, db):
        """★ 修复回归：旧版用纯毫秒，同毫秒创建会撞主键。"""
        ids = {db_writer.create_list(f"l{i}", db_override=db)["id"] for i in range(25)}
        assert len(ids) == 25

    def test_create_empty_name_rejected(self, db):
        with pytest.raises(DbError):
            db_writer.create_list("   ", db_override=db)

    def test_rename(self, db):
        row = db_writer.create_list("old", db_override=db)
        assert db_writer.rename_list(row["id"], "new", db_override=db) is True
        assert db_reader.get_list(row["id"], db_override=db)["name"] == "new"

    def test_rename_virtual_list_rejected(self, db):
        """虚拟歌单不可重命名（与 LX 行为一致）。"""
        with pytest.raises(DbError):
            db_writer.rename_list("love", "x", db_override=db)

    def test_delete_cascades(self, db):
        row = db_writer.create_list("t", db_override=db)
        db_writer.add_songs(row["id"], [
            {"id": "wy_1", "name": "n", "singer": "s", "source": "wy"}],
            db_override=db)
        assert db_writer.delete_list(row["id"], db_override=db) is True
        assert db_reader.get_list(row["id"], db_override=db) is None
        assert db_reader.count_songs(row["id"], db_override=db) == 0

    def test_delete_virtual_rejected(self, db):
        with pytest.raises(DbError):
            db_writer.delete_list("default", db_override=db)

    def test_delete_missing_returns_false(self, db):
        assert db_writer.delete_list("userlist_nope", db_override=db) is False


class TestWriterSongs:
    @staticmethod
    def _song(sid="wy_1", name="n", singer="a、b", source="wy"):
        return {"id": sid, "name": name, "singer": singer, "source": source,
                "interval": "03:00", "meta": {"songId": sid}}

    def test_add_to_new_list(self, db):
        row = db_writer.create_list("t", db_override=db)
        res = db_writer.add_songs(row["id"], [self._song()], db_override=db)
        assert res["added"] == 1 and res["skipped"] == 0
        assert db_reader.count_songs(row["id"], db_override=db) == 1

    def test_add_is_idempotent(self, db):
        """★ 修复回归：重复添加不应重复插入。"""
        row = db_writer.create_list("t", db_override=db)
        db_writer.add_songs(row["id"], [self._song()], db_override=db)
        res = db_writer.add_songs(row["id"], [self._song()], db_override=db)
        assert res["added"] == 0 and res["skipped"] == 1
        assert res["skippedIds"] == ["wy_1"]
        assert db_reader.count_songs(row["id"], db_override=db) == 1

    def test_added_count_excludes_dupes(self, db):
        """★ 修复回归：旧版 inserted 无条件自增，重复也会计入。"""
        row = db_writer.create_list("t", db_override=db)
        res = db_writer.add_songs(
            row["id"], [self._song("wy_1"), self._song("wy_1")], db_override=db)
        assert res["added"] == 1
        assert res["skipped"] == 1

    def test_position_top(self, db):
        row = db_writer.create_list("t", db_override=db)
        db_writer.add_songs(row["id"], [self._song("wy_1")], db_override=db)
        db_writer.add_songs(row["id"], [self._song("wy_2")],
                            position="top", db_override=db)
        songs = db_reader.songs_in_list(row["id"], db_override=db)
        assert [s["id"] for s in songs] == ["wy_2", "wy_1"]

    def test_position_bottom(self, db):
        row = db_writer.create_list("t", db_override=db)
        db_writer.add_songs(row["id"], [self._song("wy_1")], db_override=db)
        db_writer.add_songs(row["id"], [self._song("wy_2")], db_override=db)
        songs = db_reader.songs_in_list(row["id"], db_override=db)
        assert [s["id"] for s in songs] == ["wy_1", "wy_2"]

    def test_order_is_dense_after_add(self, db):
        row = db_writer.create_list("t", db_override=db)
        db_writer.add_songs(row["id"], [self._song(f"wy_{i}") for i in range(5)],
                            db_override=db)
        with db_reader.connect(db) as c:
            orders = [r[0] for r in c.execute(
                'SELECT "order" FROM my_list_music_info_order WHERE listId=? '
                'ORDER BY "order"', (row["id"],))]
        assert orders == [0, 1, 2, 3, 4]

    def test_add_to_virtual_list(self, db):
        """default/love 无 my_list 行，但可以写歌。"""
        res = db_writer.add_songs("love", [self._song("wy_virtual")], db_override=db)
        assert res["added"] == 1
        assert db_reader.count_songs("love", db_override=db) == 189

    def test_add_to_missing_list_raises(self, db):
        with pytest.raises(NoSuchListError):
            db_writer.add_songs("userlist_nope", [self._song()], db_override=db)

    def test_meta_roundtrip(self, db):
        row = db_writer.create_list("t", db_override=db)
        db_writer.add_songs(row["id"], [{
            "id": "kg_1_AB", "name": "n", "singer": "s", "source": "kg",
            "meta": {"songId": 1, "hash": "AB", "albumName": "专辑"},
        }], db_override=db)
        songs = db_reader.songs_in_list(row["id"], db_override=db)
        meta = decode_meta(songs[0]["meta"])
        assert meta["hash"] == "AB" and meta["albumName"] == "专辑"

    def test_meta_accepts_json_string(self, db):
        row = db_writer.create_list("t", db_override=db)
        db_writer.add_songs(row["id"], [{
            "id": "wy_9", "name": "n", "singer": "s", "source": "wy",
            "meta": encode_meta({"songId": 9}),
        }], db_override=db)
        assert decode_meta(
            db_reader.songs_in_list(row["id"], db_override=db)[0]["meta"]
        )["songId"] == 9

    def test_remove(self, db):
        row = db_writer.create_list("t", db_override=db)
        db_writer.add_songs(row["id"], [self._song(f"wy_{i}") for i in range(3)],
                            db_override=db)
        assert db_writer.remove_songs(row["id"], ["wy_1"], db_override=db) == 1
        songs = db_reader.songs_in_list(row["id"], db_override=db)
        assert [s["id"] for s in songs] == ["wy_0", "wy_2"]

    def test_remove_then_order_stays_dense(self, db):
        row = db_writer.create_list("t", db_override=db)
        db_writer.add_songs(row["id"], [self._song(f"wy_{i}") for i in range(4)],
                            db_override=db)
        db_writer.remove_songs(row["id"], ["wy_1", "wy_2"], db_override=db)
        with db_reader.connect(db) as c:
            orders = [r[0] for r in c.execute(
                'SELECT "order" FROM my_list_music_info_order WHERE listId=? '
                'ORDER BY "order"', (row["id"],))]
        assert orders == [0, 1]

    def test_reorder(self, db):
        row = db_writer.create_list("t", db_override=db)
        db_writer.add_songs(row["id"], [self._song(f"wy_{i}") for i in range(3)],
                            db_override=db)
        db_writer.reorder_songs(row["id"], ["wy_2", "wy_0", "wy_1"], db_override=db)
        songs = db_reader.songs_in_list(row["id"], db_override=db)
        assert [s["id"] for s in songs] == ["wy_2", "wy_0", "wy_1"]

    def test_touch_updates_location_time(self, db):
        row = db_writer.create_list("t", db_override=db)
        before = db_reader.get_list(row["id"], db_override=db)["locationUpdateTime"]
        db_writer.add_songs(row["id"], [self._song()], db_override=db)
        after = db_reader.get_list(row["id"], db_override=db)["locationUpdateTime"]
        assert after >= before


class TestWriterGuards:
    def test_add_song_without_id_rejected(self, db):
        row = db_writer.create_list("t", db_override=db)
        with pytest.raises(DbError):
            db_writer.add_songs(row["id"], [{"name": "x", "singer": "s",
                                             "source": "wy"}], db_override=db)

    def test_bad_position_rejected(self, db):
        row = db_writer.create_list("t", db_override=db)
        with pytest.raises(DbError):
            db_writer.add_songs(row["id"], [], position="middle", db_override=db)

    def test_assert_lx_closed_force_skips_check(self):
        db_writer.assert_lx_closed(force=True)     # 不应抛

    def test_rollback_on_missing_list(self, db):
        """异常时不应留下半成品数据。"""
        with pytest.raises(NoSuchListError):
            db_writer.add_songs("nope", [{"id": "x", "name": "n",
                                          "singer": "s", "source": "wy"}],
                                db_override=db)
        with db_reader.connect(db) as c:
            n = c.execute(
                "SELECT COUNT(*) FROM my_list_music_info WHERE id='x'").fetchone()[0]
        assert n == 0
