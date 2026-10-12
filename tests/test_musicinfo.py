"""歌曲 id / meta 契约测试 —— 本项目最重要的测试文件。

每一条用例都对应一个**真实踩过的坑**，依据真实用户库统计与
``lx-music-desktop-2.12.5/src/common/utils/tools.ts``。
"""
from __future__ import annotations

import pytest

from lx_cli.core.musicinfo import (
    SongRecord, decode_meta, encode_meta, from_db_row, has_quality,
    make_song_id, normalize_songmid, parse_song_id, quality_types,
    source_label, split_singers,
)


# --------------------------------------------------- id 构造（核心契约）

class TestMakeSongId:
    def test_wy_uses_source_prefix(self):
        assert make_song_id("wy", "2635292773") == "wy_2635292773"

    def test_kw_uses_source_prefix(self):
        assert make_song_id("kw", "26275820") == "kw_26275820"

    def test_tx_uses_mid(self):
        assert make_song_id("tx", "001SxL503C84XM") == "tx_001SxL503C84XM"

    def test_kg_has_NO_source_prefix(self):
        """★ 最关键的一条：kg 的 id 是 <songmid>_<hash>，**没有 kg_ 前缀**。

        依据 tools.ts:39；真实库 934/958 的 kg 行都是这个形态。
        任何"顺手补 kg_ 前缀"的实现都会写出 LX 不认识、无法播放的 id。
        """
        got = make_song_id("kg", "631537655", "5A86012526BD981CD3AF1125E3FE234A")
        assert got == "631537655_5A86012526BD981CD3AF1125E3FE234A"
        assert not got.startswith("kg_")

    def test_kg_requires_hash(self):
        """kg 缺 hash 必须报错，而不是产出残缺 id。"""
        with pytest.raises(ValueError, match="hash"):
            make_song_id("kg", "631537655")

    def test_local_is_path(self):
        p = r"C:\Users\EDY\Music\a.flac"
        assert make_song_id("local", p) == p

    def test_none_songmid_rejected(self):
        with pytest.raises(ValueError):
            make_song_id("wy", None)


# --------------------------------------------------- id 解析（必须容忍异常形态）

class TestParseSongId:
    def test_parse_kg_canonical_bare(self):
        pid = parse_song_id("631537655_5A86012526BD981CD3AF1125E3FE234A", "kg")
        assert pid.songmid == "631537655"
        assert pid.hash == "5A86012526BD981CD3AF1125E3FE234A"
        assert pid.is_canonical is True

    def test_parse_kg_double_prefixed_variant(self):
        """真实库里有 24 行 kg_<songId>_<hash>（二次拼接产物），读取必须容忍。"""
        pid = parse_song_id("kg_500951349_EF93F2291FE39466A16E4B795C235933", "kg")
        assert pid.songmid == "500951349"
        assert pid.hash == "EF93F2291FE39466A16E4B795C235933"
        assert pid.is_canonical is False

    def test_parse_wy(self):
        pid = parse_song_id("wy_2635292773", "wy")
        assert pid.songmid == "2635292773"
        assert pid.is_canonical is True

    def test_parse_local_path_with_underscores_not_split(self):
        """★ local 的 id 是路径且**含下划线** —— 绝不能按 '_' 切分。"""
        p = (r"/storage/emulated/0/Music/ASMR/SnapTube Audio/"
             r"[ASMR] a_b_c (M4A_1.m4a")
        pid = parse_song_id(p, "local")
        assert pid.songmid == p
        assert pid.hash is None

    def test_never_infer_source_from_id_prefix(self):
        """kg 的 id 不带前缀 —— 解析必须靠传入的 source，而不是猜前缀。"""
        pid = parse_song_id("631537655_5A86012526BD981CD3AF1125E3FE234A", "kg")
        assert pid.source == "kg"      # 来自参数，不是从 id 猜的


# --------------------------------------------------- 歌手

class TestSingers:
    def test_split_by_ideographic_comma(self):
        assert split_singers("陈致逸、HOYO-MiX") == ["陈致逸", "HOYO-MiX"]

    def test_ampersand_is_part_of_name(self):
        """★ 实测 6 行含 '&'，它是歌手名的一部分，不能当分隔符。"""
        got = split_singers("Raven & Kreyn、RudeLies、Nino Lucarelli")
        assert got == ["Raven & Kreyn", "RudeLies", "Nino Lucarelli"]
        assert len(got) == 3          # 按 '&' 拆会错成 4

    def test_semicolon_is_part_of_name(self):
        """★ 实测 217 行含 ';'，不能当分隔符。"""
        assert split_singers("A;B、C") == ["A;B", "C"]

    def test_three_singers(self):
        assert split_singers("塞壬唱片-MSR、Dazbee、*Luna") == \
            ["塞壬唱片-MSR", "Dazbee", "*Luna"]

    def test_empty(self):
        assert split_singers("") == []
        assert split_singers(None) == []


# --------------------------------------------------- 显示名（需求：用 kg 不用 Flower）

class TestSourceLabel:
    @pytest.mark.parametrize("sid,expected", [
        ("kg", "酷狗音乐"), ("kw", "酷我音乐"),
        ("tx", "企鹅音乐"),   # ★ 不是 "QQ音乐"
        ("wy", "网易音乐"), ("mg", "咪咕音乐"),
    ])
    def test_real_names(self, sid, expected):
        assert source_label(sid, name_type="real") == expected

    def test_alias_mode(self):
        assert source_label("wy", name_type="alias") == "小芸音乐"

    def test_unknown_falls_back_to_id(self):
        assert source_label("zzz") == "zzz"

    def test_empty(self):
        assert source_label(None) == ""


# --------------------------------------------------- meta 编解码

class TestMeta:
    def test_roundtrip_chinese(self):
        meta = {"albumName": "塞壬唱片", "songId": 123}
        assert decode_meta(encode_meta(meta)) == meta

    def test_encode_none(self):
        assert encode_meta(None) == "{}"

    def test_decode_corrupt_returns_empty(self):
        """宽容解析：坏数据不能让上层崩。"""
        assert decode_meta("{not json") == {}
        assert decode_meta("") == {}
        assert decode_meta(None) == {}
        assert decode_meta("[1,2,3]") == {}   # 非 dict 也视为无效

    def test_songmid_type_is_unstable(self):
        """实测 songId 有 int/str 两种类型，必须统一。"""
        assert normalize_songmid(631537655) == "631537655"
        assert normalize_songmid("631537655") == "631537655"
        assert normalize_songmid(None) == ""

    def test_quality_types_order_preserved(self):
        meta = {"qualitys": [{"type": "128k"}, {"type": "flac"}]}
        assert quality_types(meta) == ["128k", "flac"]

    def test_playability_uses_underscore_qualitys(self):
        """★ 判可否播放要用 _qualitys 字典，不是 qualitys 数组。"""
        meta = {"qualitys": [{"type": "320k"}], "_qualitys": {"320k": {"size": "1 MB"}}}
        assert has_quality(meta, "320k") is True
        assert has_quality(meta, "flac") is False

    def test_playability_false_when_only_array_present(self):
        assert has_quality({"qualitys": [{"type": "320k"}]}, "320k") is False


# --------------------------------------------------- DB 行往返

class TestDbRoundTrip:
    def test_from_db_row_kg_bare(self):
        """真实库样本：kg 裸 id + 完整 meta。"""
        row = {
            "id": "631537655_5A86012526BD981CD3AF1125E3FE234A",
            "name": "Amnesia (DJ阿虎)",
            "singer": "DJ亚哲、DJ阿虎",
            "source": "kg",
            "interval": "03:11",
            "meta": encode_meta({
                "songId": 631537655,
                "albumName": "Amnesia(DJ阿虎版)",
                "albumId": "201445175",
                "hash": "5A86012526BD981CD3AF1125E3FE234A",
                "picUrl": "http://example/x.jpg",
                "qualitys": [{"type": "320k", "size": "7.31 MB"}],
            }),
        }
        s = from_db_row(row)
        assert s.id == "631537655_5A86012526BD981CD3AF1125E3FE234A"
        assert s.songmid == "631537655"
        assert s.hash == "5A86012526BD981CD3AF1125E3FE234A"
        assert s.album_name == "Amnesia(DJ阿虎版)"
        assert s.singer_list == ["DJ亚哲", "DJ阿虎"]

    def test_from_db_row_local_path(self):
        row = {
            "id": r"C:\Users\EDY\Music\x_a_b.flac",
            "name": "t", "singer": "s", "source": "local",
            "interval": "03:00", "meta": encode_meta({"filePath": r"C:\x_a_b.flac"}),
        }
        s = from_db_row(row)
        assert s.id == row["id"]
        assert "\\" in s.id              # 路径未被破坏

    def test_to_db_row_shape(self):
        s = SongRecord(id="wy_1", name="n", singer="a、b", source="wy",
                       interval="03:00", meta={"songId": 1})
        r = s.to_db_row("love")
        assert set(r) == {"id", "listId", "name", "singer", "source", "interval", "meta"}
        assert r["listId"] == "love"
        assert decode_meta(r["meta"])["songId"] == 1

    def test_to_json_has_required_search_fields(self):
        """需求 C：查询结果必须含 作者/名/专辑/来源。"""
        s = SongRecord(id="kg_1_AB", name="n", singer="a、b", source="kg",
                       album_name="alb", album_id="9", interval="03:00",
                       songmid="1", hash="AB")
        j = s.to_json()
        for key in ("id", "name", "singer", "singerList", "albumName",
                    "albumId", "source", "sourceLabel", "interval"):
            assert key in j, key
        assert j["sourceLabel"] == "酷狗音乐"
        assert j["singerList"] == ["a", "b"]

    def test_from_db_row_tolerates_broken_meta(self):
        row = {"id": "wy_1", "name": "n", "singer": "s", "source": "wy",
               "interval": "", "meta": "{broken"}
        s = from_db_row(row)
        assert s.meta == {}
        assert s.songmid == "1"      # 回退到 id 解析
