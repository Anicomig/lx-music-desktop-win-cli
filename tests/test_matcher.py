"""比对与匹配测试（离线，不联网）。

覆盖需求 D 的核心："对比现有歌单" 的判定逻辑。
"""
from __future__ import annotations

import pytest

from lx_cli.cli.playlist import compare
from lx_cli.core.matcher import (
    find_duplicates, is_same_song, normalize_text, parse_interval,
    version_flags,
)
from lx_cli.sources.base import SongRecord


def song(platform="kw", songmid="1", name="n", singer="s", interval="03:00",
         **kw):
    return SongRecord(platform=platform, songmid=songmid, name=name,
                      singer=singer, interval=interval, **kw)


def row(sid, name="n", singer="s", interval="03:00", source="kw"):
    return {"id": sid, "name": name, "singer": singer,
            "interval": interval, "source": source}


# --------------------------------------------------------- 时长解析


class TestParseInterval:
    @pytest.mark.parametrize("text,expect", [
        ("03:11", 191), ("3:11", 191), ("0:30", 30),
        ("1:02:03", 3723), ("184:23", 11063), ("", 0), (None, 0),
        ("garbage", 0),
    ])
    def test_parse(self, text, expect):
        assert parse_interval(text) == expect

    def test_long_duration(self):
        """实测库里有 184:23 这种超长时长。"""
        assert parse_interval("184:23") == 184 * 60 + 23


# --------------------------------------------------------- 文本归一化


class TestNormalize:
    def test_strips_punctuation(self):
        assert normalize_text("Hello, World!") == "helloworld"

    def test_keeps_chinese(self):
        assert normalize_text("老人と海") == "老人と海"

    def test_handles_none(self):
        assert normalize_text(None) == ""


class TestVersionFlags:
    def test_detects_live(self):
        assert "live" in version_flags("Song (Live)")

    def test_detects_banzou(self):
        assert "伴奏" in version_flags("歌曲 伴奏")

    def test_plain_song_has_none(self):
        assert version_flags("普通歌曲") == set()


# --------------------------------------------------------- 同曲判定


class TestIsSameSong:
    def test_identical(self):
        assert is_same_song("老人と海", "ヨルシカ", "04:15",
                            "老人と海", "ヨルシカ", "04:15")

    def test_duration_gate_rejects(self):
        """★ ±5 秒硬门槛：差 10 秒不算同曲（对齐桌面端 findMusic）。"""
        assert not is_same_song("n", "s", "03:00", "n", "s", "03:10")

    def test_duration_within_tolerance(self):
        assert is_same_song("n", "s", "03:00", "n", "s", "03:04")

    def test_duration_unknown_skips_check(self):
        assert is_same_song("n", "s", "", "n", "s", "")

    def test_version_mismatch_rejected(self):
        """★ 不能把 Live 版当原版。"""
        assert not is_same_song("Song", "A", "03:00",
                                "Song (Live)", "A", "03:00")

    def test_banzou_mismatch_rejected(self):
        assert not is_same_song("歌曲", "A", "03:00",
                                "歌曲 伴奏", "A", "03:00")

    def test_singer_containment_ok(self):
        assert is_same_song("n", "A", "03:00", "n", "A、B", "03:00")

    def test_empty_singer_passes(self):
        assert is_same_song("n", "", "03:00", "n", "A", "03:00")

    def test_different_singers_rejected(self):
        assert not is_same_song("n", "A", "03:00", "n", "B", "03:00")

    def test_name_containment_ok(self):
        """一方名称是另一方的前缀（无版本词差异）→ 同曲。"""
        assert is_same_song("老人と海", "A", "03:00",
                            "老人と海 完整版", "A", "03:00")

    def test_remaster_is_treated_as_different_version(self):
        """★ Remaster 属于版本词，**故意**判为不同曲（对齐桌面端版本词校验）。"""
        assert not is_same_song("老人と海", "A", "03:00",
                                "老人と海 (Remaster)", "A", "03:00")

    def test_not_same(self):
        assert not is_same_song("a", "s", "03:00", "b", "s", "03:00")


class TestFindDuplicates:
    def test_finds(self):
        cand = {"name": "n", "singer": "s", "interval": "03:00"}
        existing = [row("kw_1"), row("kw_2", name="other")]
        assert len(find_duplicates(cand, existing)) == 1

    def test_empty(self):
        assert find_duplicates({"name": "x", "singer": "y", "interval": ""}, []) == []


# --------------------------------------------------------- 对比报告


class TestCompareById:
    def test_all_new(self):
        r = compare([song(songmid="1"), song(songmid="2")], existing=[])
        assert r["wouldAdd"] == 2 and r["alreadyIn"] == 0

    def test_skips_existing(self):
        r = compare([song(songmid="1")], existing=[row("kw_1")])
        assert r["wouldAdd"] == 0 and r["alreadyIn"] == 1
        assert r["skipped_ids"] == ["kw_1"]

    def test_dedupes_candidates(self):
        """候选内部重复只算一次。"""
        r = compare([song(songmid="1"), song(songmid="1")], existing=[])
        assert r["wouldAdd"] == 1

    def test_kg_id_uses_hash(self):
        """kg 的 id 是 <songId>_<hash>，比对要用复合 id。"""
        s = song(platform="kg", songmid="631", hash="ABC")
        r = compare([s], existing=[row("631_ABC", source="kg")])
        assert r["wouldAdd"] == 0 and r["alreadyIn"] == 1

    def test_kg_not_matched_by_bare_songmid(self):
        s = song(platform="kg", songmid="631", hash="ABC")
        r = compare([s], existing=[row("631", source="kg")])
        assert r["wouldAdd"] == 1


class TestCompareByKey:
    def test_name_singer_matches_across_platform(self):
        """跨平台同曲：id 不同但同名同歌手 → 跳过。"""
        s = song(platform="wy", songmid="9", name="老人と海", singer="ヨルシカ")
        r = compare([s], existing=[row("kw_1", name="老人と海", singer="ヨルシカ")],
                    by="name+singer")
        assert r["wouldAdd"] == 0 and r["alreadyIn"] == 1

    def test_id_mode_does_not_cross_match(self):
        s = song(platform="wy", songmid="9", name="老人と海", singer="ヨルシカ")
        r = compare([s], existing=[row("kw_1", name="老人と海", singer="ヨルシカ")],
                    by="id")
        assert r["wouldAdd"] == 1
        # 但会被标为"疑似重复"
        assert r["suspectDuplicates"] == 1


class TestCompareFuzzy:
    def test_fuzzy_matches_with_duration(self):
        s = song(platform="wy", songmid="9", name="老人と海", singer="ヨルシカ",
                 interval="04:15")
        r = compare([s], existing=[row("kw_1", name="老人と海", singer="ヨルシカ",
                                       interval="04:15")], by="fuzzy")
        assert r["wouldAdd"] == 0

    def test_fuzzy_rejects_version_mismatch(self):
        s = song(platform="wy", songmid="9", name="Song", singer="A",
                 interval="03:00")
        r = compare([s], existing=[row("kw_1", name="Song (Live)", singer="A",
                                       interval="03:00")], by="fuzzy")
        assert r["wouldAdd"] == 1
