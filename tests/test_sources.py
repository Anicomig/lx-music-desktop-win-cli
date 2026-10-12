"""平台元数据源测试（离线：用 mock 替换 HTTP，不打真实接口）。

覆盖重点：
* ``SongRecord`` 的 id/meta 契约（尤其 kg 无前缀）
* 聚合搜索的**失败隔离**（单平台失败不影响其它）
* 单/多/聚合三种模式的选择与顺序正确性（曾因排序 bug 取错结果）
* kw 的单引号 JSON 状态机
"""
from __future__ import annotations

import pytest

from lx_cli.sources import get_source, list_platforms
from lx_cli.sources.base import (
    PLATFORMS, PlatformSource, SearchResult, SongRecord, SourceError,
)
from lx_cli.sources.kw import parse_kuwo_json
from lx_cli.sources.search import merge_results, search


# --------------------------------------------------------- SongRecord 契约


class TestSongRecordContract:
    def test_kg_id_has_no_prefix(self):
        r = SongRecord(platform="kg", songmid="631537655", name="n",
                       singer="s", hash="5A86ABC")
        assert r.to_song_id() == "631537655_5A86ABC"
        assert not r.to_song_id().startswith("kg_")

    def test_other_platforms_prefixed(self):
        for p in ("kw", "tx", "wy", "mg"):
            r = SongRecord(platform=p, songmid="123", name="n", singer="s")
            assert r.to_song_id() == f"{p}_123"

    def test_output_uses_platform_not_script_name(self):
        """需求：来源必须是 kg/kw…，不能是 Flower/SixYin。"""
        r = SongRecord(platform="kg", songmid="1", name="n", singer="s",
                       hash="H")
        j = r.to_json()
        assert j["source"] == "kg"
        assert j["sourceLabel"] == "酷狗音乐"
        assert j["origin"] == "musicSdk"
        for bad in ("Flower", "SixYin", "flower", "sixyin"):
            assert bad not in str(j)

    def test_to_json_has_required_fields(self):
        """需求 C：作者/名/专辑/来源。"""
        r = SongRecord(platform="wy", songmid="9", name="n", singer="a、b",
                       album_name="alb", album_id="7", interval="03:00")
        j = r.to_json()
        for k in ("id", "name", "singer", "singerList", "albumName",
                  "albumId", "interval", "source", "sourceLabel"):
            assert k in j
        assert j["singerList"] == ["a", "b"]

    def test_to_meta_includes_qualitys_dict(self):
        r = SongRecord(platform="kg", songmid="1", name="n", singer="s",
                       hash="H", types=[{"type": "320k", "size": "7 MB"}])
        meta = r.to_meta()
        assert meta["qualitys"] == [{"type": "320k", "size": "7 MB"}]
        assert meta["_qualitys"] == {"320k": {"size": "7 MB"}}
        assert meta["hash"] == "H"

    def test_to_meta_platform_specific(self):
        tx = SongRecord(platform="tx", songmid="001", name="n", singer="s",
                        extra={"strMediaMid": "MM", "albumMid": "AM"})
        meta = tx.to_meta()
        assert meta["strMediaMid"] == "MM" and meta["albumMid"] == "AM"

    def test_to_db_row(self):
        r = SongRecord(platform="kg", songmid="1", name="n", singer="s",
                       hash="H", interval="03:00")
        row = r.to_db_row("love")
        assert row["id"] == "1_H" and row["source"] == "kg"
        assert row["listId"] == "love"


# --------------------------------------------------------- 平台注册表


class TestRegistry:
    def test_all_five_platforms(self):
        assert set(list_platforms()) == set(PLATFORMS)

    def test_unknown_platform_raises(self):
        with pytest.raises(SourceError):
            get_source("nope")

    def test_platform_attr_matches_key(self):
        for p in list_platforms():
            assert get_source(p).platform == p

    def test_every_platform_supports_search(self):
        for p in list_platforms():
            assert "search" in get_source(p).features

    def test_bd_not_registered(self):
        """bd 在桌面端也被注释掉，CLI 保持不注册。"""
        assert "bd" not in list_platforms()


# --------------------------------------------------------- kw 单引号 JSON


class TestKuwoJson:
    def test_standard_json_passthrough(self):
        assert parse_kuwo_json('{"a": 1}') == {"a": 1}

    def test_single_quotes(self):
        assert parse_kuwo_json("{'a': 'b'}") == {"a": "b"}

    def test_nested_and_list(self):
        got = parse_kuwo_json("{'list': [{'x': 'y'}, {'x': 'z'}]}")
        assert got == {"list": [{"x": "y"}, {"x": "z"}]}

    def test_inner_double_quote_escaped(self):
        got = parse_kuwo_json("{'a': 'he said \"hi\"'}")
        assert got["a"] == 'he said "hi"'

    def test_chinese(self):
        assert parse_kuwo_json("{'n': 'ヨルシカ'}")["n"] == "ヨルシカ"

    def test_empty_string_value(self):
        assert parse_kuwo_json("{'a': ''}") == {"a": ""}


# --------------------------------------------------------- 搜索模式


class _Fake(PlatformSource):
    """记录调用并可配置行为的假平台。"""

    def __init__(self, platform: str, *, n: int = 2, fail: bool = False):
        self.platform = platform
        self.features = ("search",)
        self._n, self._fail = n, fail
        self.calls = 0

    def search(self, keyword, page=1, limit=30):
        self.calls += 1
        if self._fail:
            raise SourceError(self.platform, "boom")
        # kg 的 id 需要 hash（<songmid>_<hash>），否则 make_song_id 会拒绝 ——
        # 这里给 kg 补上 hash，模拟真实平台的产出。
        songs = []
        for i in range(self._n):
            kw = {"hash": f"H{i}"} if self.platform == "kg" else {}
            songs.append(SongRecord(
                platform=self.platform, songmid=f"{self.platform}{i}",
                name=f"{keyword}-{i}", singer="s", **kw))
        return SearchResult(platform=self.platform, limit=limit, page=page,
                            list=songs)


@pytest.fixture()
def fake_registry(monkeypatch):
    """用假平台替换真实注册表。"""
    import lx_cli.sources as src_pkg
    import lx_cli.sources.search as s_mod

    fakes = {p: _Fake(p) for p in ("kg", "kw", "wy")}
    monkeypatch.setattr(src_pkg, "REGISTRY", fakes)
    monkeypatch.setattr(src_pkg, "list_platforms", lambda: sorted(fakes))
    monkeypatch.setattr(s_mod, "list_platforms", lambda: sorted(fakes))
    monkeypatch.setattr(s_mod, "get_source", lambda p: fakes[p])
    return fakes


class TestSearchModes:
    def test_single_returns_that_platform(self, fake_registry):
        """回归：曾因结果排序 bug，platforms=['wy'] 取到 kg 的空结果。"""
        r = search("q", platforms=["wy"])
        assert r["mode"] == "single"
        assert r["results"][0].platform == "wy"
        assert len(r["songs"]) == 2
        assert all(s.platform == "wy" for s in r["songs"])

    def test_single_kg(self, fake_registry):
        r = search("q", platforms=["kg"])
        assert r["results"][0].platform == "kg"

    def test_multi_merges_and_dedupes(self, fake_registry):
        r = search("q", platforms=["kg", "wy"])
        assert r["mode"] == "multi"
        assert len(r["songs"]) == 4          # 2 + 2

    def test_aggregate_when_all_registered_platforms_requested(self, fake_registry):
        """请求全部已注册平台时 mode 应为 aggregate。"""
        r = search("q")                       # None → 全部（假表 3 个）
        assert r["mode"] == "aggregate"
        assert len(r["songs"]) == 6           # 3 平台 × 2

    def test_multi_when_subset(self, fake_registry):
        r = search("q", platforms=["kg", "wy"])
        assert r["mode"] == "multi"

    def test_unknown_platform_rejected(self, fake_registry):
        """未知平台是**用法错误**（exit 2），不是平台接口错误（exit 4）。"""
        from lx_cli.errors import UsageError
        with pytest.raises(UsageError):
            search("q", platforms=["nope"])

    def test_failure_isolation(self, fake_registry, monkeypatch):
        """★ 单平台失败不得影响其它平台（照抄桌面端 action.ts:99-105）。"""
        fake_registry["kw"]._fail = True
        r = search("q", platforms=["kg", "kw", "wy"])
        assert len(r["songs"]) == 4           # kg 2 + wy 2，kw 失败被隔离
        assert "kw" in r["failed"]
        kw_res = next(x for x in r["results"] if x.platform == "kw")
        assert kw_res.list == []

    def test_dedupe_by_id(self, fake_registry):
        # 让两个平台产出相同 id
        a = SearchResult(platform="kg", list=[
            SongRecord(platform="kg", songmid="1", name="n", singer="s", hash="H")])
        b = SearchResult(platform="kw", list=[
            SongRecord(platform="kg", songmid="1", name="n", singer="s", hash="H")])
        assert len(merge_results([a, b], dedupe=True)) == 1
        assert len(merge_results([a, b], dedupe=False)) == 2

    def test_result_order_follows_request(self, fake_registry):
        """results 顺序应与调用方传入的平台顺序一致。"""
        r = search("q", platforms=["wy", "kg"])
        assert [x.platform for x in r["results"]] == ["wy", "kg"]
