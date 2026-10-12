"""Open API 客户端测试。

核心回归点：**`status` 是字符串不是布尔** ——
旧版 CLI 用 ``if st.get("status")`` 判断，导致 ``lx toggle`` 永远只暂停。
"""
from __future__ import annotations

import pytest

from lx_cli.core.openapi_client import (
    STATUS_ERROR, STATUS_PAUSED, STATUS_PLAYING, STATUS_STOPPED,
    Endpoints, get_status, is_playing, set_mute, set_volume, toggle,
)


def _ep() -> Endpoints:
    return Endpoints(base="http://127.0.0.1:23330", enabled=True,
                     port="23330", bind_lan=False)


class TestIsPlaying:
    """★ 字符串状态判定 —— 旧版 bug 的回归测试。"""

    @pytest.mark.parametrize("status,expected", [
        (STATUS_PLAYING, True),
        (STATUS_PAUSED, False),      # ← 字符串 "paused" 是 truthy，旧版会误判
        (STATUS_ERROR, False),
        (STATUS_STOPPED, False),
        (None, False),
        ("", False),
    ])
    def test_is_playing(self, status, expected):
        assert is_playing({"status": status}) is expected

    def test_paused_is_truthy_but_not_playing(self):
        """明确记录这个陷阱：布尔判定会错。"""
        st = {"status": STATUS_PAUSED}
        assert bool(st.get("status")) is True     # 陷阱：truthy
        assert is_playing(st) is False            # 正确判据

    def test_none_status_dict(self):
        assert is_playing(None) is False
        assert is_playing({}) is False


class TestToggle:
    """toggle 必须按**字符串**状态决定动作。"""

    def test_paused_does_play(self, monkeypatch):
        """旧版 bug：paused 时也会调 pause()，永远播不了。"""
        calls = []
        import lx_cli.core.openapi_client as mod
        monkeypatch.setattr(mod, "get_status", lambda ep, **kw: {"status": STATUS_PAUSED})
        monkeypatch.setattr(mod, "play", lambda ep: calls.append("play"))
        monkeypatch.setattr(mod, "pause", lambda ep: calls.append("pause"))
        assert mod.toggle(_ep()) == "play"
        assert calls == ["play"]

    def test_playing_does_pause(self, monkeypatch):
        calls = []
        import lx_cli.core.openapi_client as mod
        monkeypatch.setattr(mod, "get_status", lambda ep, **kw: {"status": STATUS_PLAYING})
        monkeypatch.setattr(mod, "play", lambda ep: calls.append("play"))
        monkeypatch.setattr(mod, "pause", lambda ep: calls.append("pause"))
        assert mod.toggle(_ep()) == "pause"
        assert calls == ["pause"]

    def test_error_state_tries_play(self, monkeypatch):
        import lx_cli.core.openapi_client as mod
        monkeypatch.setattr(mod, "get_status", lambda ep, **kw: {"status": STATUS_ERROR})
        monkeypatch.setattr(mod, "play", lambda ep: None)
        monkeypatch.setattr(mod, "pause", lambda ep: None)
        assert mod.toggle(_ep()) == "play"


class TestVolumeValidation:
    def test_rejects_out_of_range(self, monkeypatch):
        import lx_cli.core.openapi_client as mod
        from lx_cli.errors import OpenApiBadRequest
        with pytest.raises(OpenApiBadRequest):
            set_volume(_ep(), 101)
        with pytest.raises(OpenApiBadRequest):
            set_volume(_ep(), -1)


class TestEndpoints:
    def test_url_join(self):
        assert _ep().url("/status") == "http://127.0.0.1:23330/status"


class TestGetStatusParsing:
    def test_non_dict_response_is_error(self, monkeypatch):
        import lx_cli.core.openapi_client as mod
        from lx_cli.errors import OpenApiError
        monkeypatch.setattr(mod, "_get_json", lambda *a, **kw: ["not", "a", "dict"])
        with pytest.raises(OpenApiError):
            get_status(_ep())

    def test_real_response_shape(self, monkeypatch):
        """用本机实测的真实响应做回归。"""
        real = {
            "status": "paused", "name": "时序花圃",
            "singer": "塞壬唱片-MSR;原田萌喜 (Moeki Harada)",
            "albumName": "音律联觉 - 熠曲丰碑原声EP",
            "lyricLineText": "", "duration": 207.672521,
            "progress": 4.101333, "playbackRate": 1,
        }
        import lx_cli.core.openapi_client as mod
        monkeypatch.setattr(mod, "_get_json", lambda *a, **kw: real)
        st = get_status(_ep())
        assert st["status"] == "paused"
        assert is_playing(st) is False
        # Open API 的 singer 用 ';' 分隔（与 DB 的 '、' 不同）
        assert ";" in st["singer"]
