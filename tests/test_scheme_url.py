"""Scheme URL 构造与校验测试（纯离线，不派发）。"""
from __future__ import annotations

import urllib.parse

import pytest

from lx_cli.core.scheme_url import (
    SchemeError, build_url, open_songlist, parse_url, play_song, play_songlist,
    search_play, simple,
)


class TestBuildUrl:
    def test_simple_no_data(self):
        assert build_url("player/skipNext") == "lxmusic://player/skipNext"

    def test_data_is_url_encoded_json(self):
        url = build_url("music/search", {"keywords": "测试"})
        assert url.startswith("lxmusic://music/search?data=")
        # 必须是 URL 编码过的 JSON
        raw = urllib.parse.unquote(url.split("data=", 1)[1])
        assert '"keywords"' in raw

    def test_empty_data_dict_treated_as_no_data(self):
        assert build_url("player/play", {}) == "lxmusic://player/play"


class TestParseUrl:
    def test_roundtrip_chinese_and_nested(self):
        data = {"name": "时序花圃", "singer": "塞壬唱片-MSR",
                "types": [{"type": "320k", "size": "7 MB"}]}
        parsed = parse_url(build_url("music/play", data))
        assert parsed["path"] == "music/play"
        assert parsed["data"] == data

    def test_no_data(self):
        assert parse_url("lxmusic://player/togglePlay") == {
            "path": "player/togglePlay", "data": None}

    def test_rejects_non_lxmusic(self):
        with pytest.raises(SchemeError):
            parse_url("http://example.com")

    def test_rejects_bad_json(self):
        with pytest.raises(SchemeError):
            parse_url("lxmusic://a/b?data=not-json")


class TestPlaySongValidation:
    def test_rejects_unknown_source(self):
        with pytest.raises(SchemeError, match="source"):
            play_song(name="n", singer="s", source="xx", songmid="1",
                      types=[{"type": "320k"}])

    def test_rejects_empty_types(self):
        with pytest.raises(SchemeError, match="types"):
            play_song(name="n", singer="s", source="wy", songmid="1", types=[])

    def test_kg_requires_hash(self):
        with pytest.raises(SchemeError, match="hash"):
            play_song(name="n", singer="s", source="kg", songmid="1",
                      types=[{"type": "320k"}])

    def test_tx_requires_str_media_mid(self):
        with pytest.raises(SchemeError, match="strMediaMid"):
            play_song(name="n", singer="s", source="tx", songmid="1",
                      types=[{"type": "320k"}])

    def test_mg_requires_copyright_id(self):
        with pytest.raises(SchemeError, match="copyrightId"):
            play_song(name="n", singer="s", source="mg", songmid="1",
                      types=[{"type": "320k"}])


class TestPlaySongPayload:
    """不真的派发：验证构造出的 URL 内容正确。"""

    @staticmethod
    def _capture(monkeypatch):
        sent: list[str] = []
        import lx_cli.core.scheme_url as mod
        monkeypatch.setattr(mod, "dispatch", lambda url, **kw: sent.append(url))
        return sent

    def test_wy_payload(self, monkeypatch):
        sent = self._capture(monkeypatch)
        play_song(name="n", singer="s", source="wy", songmid="123",
                  types=[{"type": "320k"}], album_name="alb")
        parsed = parse_url(sent[0])
        assert parsed["path"] == "music/play"
        d = parsed["data"]
        assert d["source"] == "wy" and d["songmid"] == "123"
        assert d["albumName"] == "alb"
        assert "hash" not in d            # 非 kg 不应带 hash

    def test_kg_includes_hash(self, monkeypatch):
        sent = self._capture(monkeypatch)
        play_song(name="n", singer="s", source="kg", songmid="631",
                  hash_="ABC123", types=[{"type": "320k"}])
        d = parse_url(sent[0])["data"]
        assert d["hash"] == "ABC123"

    def test_omits_empty_optionals(self, monkeypatch):
        sent = self._capture(monkeypatch)
        play_song(name="n", singer="s", source="wy", songmid="1",
                  types=[{"type": "320k"}], img="", album_id=None)
        d = parse_url(sent[0])["data"]
        assert "img" not in d and "albumId" not in d


class TestSearchPlay:
    def test_basic(self, monkeypatch):
        sent = []
        import lx_cli.core.scheme_url as mod
        monkeypatch.setattr(mod, "dispatch", lambda url, **kw: sent.append(url))
        search_play(name="镜花水月", singer="A")
        d = parse_url(sent[0])["data"]
        assert d == {"name": "镜花水月", "singer": "A"}

    def test_play_later_flag(self, monkeypatch):
        sent = []
        import lx_cli.core.scheme_url as mod
        monkeypatch.setattr(mod, "dispatch", lambda url, **kw: sent.append(url))
        search_play(name="x", play_later=True)
        assert parse_url(sent[0])["data"]["playLater"] is True


class TestSonglist:
    def test_open_requires_exactly_one_id_or_url(self, monkeypatch):
        import lx_cli.core.scheme_url as mod
        monkeypatch.setattr(mod, "dispatch", lambda url, **kw: None)
        with pytest.raises(SchemeError):
            open_songlist(source="kw")                    # 都没给
        with pytest.raises(SchemeError):
            open_songlist(source="kw", list_id="1", url_="http://x")  # 都给

    def test_play_list_with_index(self, monkeypatch):
        sent = []
        import lx_cli.core.scheme_url as mod
        monkeypatch.setattr(mod, "dispatch", lambda url, **kw: sent.append(url))
        play_songlist(source="kw", list_id="3373919903", index=2)
        assert parse_url(sent[0]) == {
            "path": "songlist/play",
            "data": {"source": "kw", "id": "3373919903", "index": 2},
        }


class TestSimple:
    @pytest.mark.parametrize("act", ["play", "pause", "skipNext", "skipPrev",
                                     "togglePlay", "collect", "uncollect", "dislike"])
    def test_allowed(self, act, monkeypatch):
        sent = []
        import lx_cli.core.scheme_url as mod
        monkeypatch.setattr(mod, "dispatch", lambda url, **kw: sent.append(url))
        simple(act)
        assert sent[0] == f"lxmusic://player/{act}"

    def test_rejects_unknown(self, monkeypatch):
        import lx_cli.core.scheme_url as mod
        monkeypatch.setattr(mod, "dispatch", lambda url, **kw: None)
        with pytest.raises(SchemeError):
            simple("explode")
