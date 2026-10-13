"""Open API 客户端测试。

核心回归点：

* **`status` 是字符串不是布尔** —— 旧版 CLI 用 ``if st.get("status")`` 判断，
  导致 ``lx toggle`` 永远只暂停。
* **连接 host 永远是 127.0.0.1** —— 0.0.0.0 是监听通配符，不能作为客户端连接目标。
* **本机端点必须绕过系统代理** —— 否则会被 Clash/v2rayN 拦截 → 502。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lx_cli.core.openapi_client import (
    STATUS_ERROR, STATUS_PAUSED, STATUS_PLAYING, STATUS_STOPPED,
    Endpoints, endpoints_from_config, get_status, is_playing, set_mute,
    set_volume, toggle, _local_session,
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


class TestEndpointsHost:
    """★ 连接 host 永远固定 127.0.0.1，不受 bindLan 影响。"""

    def test_bindLan_true_uses_127(self, tmp_path, monkeypatch):
        """即便 bindLan=true（LX 监听 0.0.0.0），CLI 仍用 127.0.0.1 连。"""
        from lx_cli.core import openapi_client as mod
        cfg = tmp_path / "config_v2.json"
        cfg.write_text('{"setting":{"openAPI":{"enable":true,"port":"23330","bindLan":true}}}',
                       encoding="utf-8")
        fake_exe = tmp_path / "lx.exe"
        fake_exe.write_bytes(b"")
        monkeypatch.setattr(mod, "config_v2_path", lambda *a, **kw: cfg)
        ep = mod.endpoints_from_config(fake_exe)
        assert ep.base == "http://127.0.0.1:23330"
        assert "0.0.0.0" not in ep.base, \
            "0.0.0.0 不能作为客户端连接目标（WinError 10049）"

    def test_bindLan_false_uses_127(self, tmp_path, monkeypatch):
        from lx_cli.core import openapi_client as mod
        cfg = tmp_path / "config_v2.json"
        cfg.write_text('{"setting":{"openAPI":{"enable":true,"port":"23330","bindLan":false}}}',
                       encoding="utf-8")
        fake_exe = tmp_path / "lx.exe"
        fake_exe.write_bytes(b"")
        monkeypatch.setattr(mod, "config_v2_path", lambda *a, **kw: cfg)
        ep = mod.endpoints_from_config(fake_exe)
        assert ep.base == "http://127.0.0.1:23330"


class TestProxyInteraction:
    """★ 代理与本机请求的真实关系（实测证据，防误诊）。

    关键事实（在系统代理 127.0.0.1:7890 环境下实测）：

        proxy_bypass('127.0.0.1') = True    -> requests 自动豁免本机
        proxy_bypass('0.0.0.0')   = False   -> 0.0.0.0 **会走代理**
        连 127.0.0.1:23330 -> 200（即便强制走代理也 200）
        连 0.0.0.0:23330   -> 502  ★ 真凶

    所以 502 的根因是"host 用了 0.0.0.0"，不是"没绕过代理"。
    这组测试锁定该认知，避免以后误改回 0.0.0.0 或误删 host 修复。
    """

    def test_127_is_proxy_bypassed_but_0000_is_not(self):
        """requests 对 127.0.0.1 豁免代理，对 0.0.0.0 不豁免。

        ⚠️ 仅在**系统代理开启时**才有意义：没配代理时 getproxies()={}，
        proxy_bypass() 对所有地址都返回 False（无代理可绕过）。
        所以这里先探测环境，无代理则跳过 —— 不能假设测试机一定开着代理。
        """
        import urllib.request
        if not urllib.request.getproxies():
            pytest.skip("系统未配置代理，proxy_bypass 语义不适用")
        assert urllib.request.proxy_bypass("127.0.0.1") is True
        assert urllib.request.proxy_bypass("localhost") is True
        # 0.0.0.0 不豁免 -> 会被发给系统代理 -> 代理连不上 -> 502
        assert urllib.request.proxy_bypass("0.0.0.0") is False, \
            "若此断言变了，说明 0.0.0.0 已能豁免代理，需重新评估 host 策略"

    def test_endpoints_never_use_0000(self, tmp_path, monkeypatch):
        """不论 bindLan 为何，端点 host 都不能是 0.0.0.0。

        这是 502 的唯一充分条件，务必锁死。
        """
        from lx_cli.core import openapi_client as mod
        for bind_lan in (True, False):
            cfg = tmp_path / f"c{bind_lan}.json"
            cfg.write_text(
                '{"setting":{"openAPI":{"enable":true,"port":"23330",'
                f'"bindLan":{str(bind_lan).lower()}}}}}',
                encoding="utf-8")
            monkeypatch.setattr(mod, "config_v2_path", lambda *a, **kw: cfg)
            ep = mod.endpoints_from_config(tmp_path / "lx.exe")
            assert "0.0.0.0" not in ep.base, \
                f"bindLan={bind_lan} 时端点含 0.0.0.0 -> 必致 502：{ep.base}"
            assert ep.base.startswith("http://127.0.0.1:")


class TestLocalSessionBypassesProxy:
    """★ 本机会话必须 trust_env=False（绕过系统代理）。"""

    def test_local_session_trust_env_false(self):
        s = _local_session()
        assert s.trust_env is False, \
            "本机 Open API 会话必须 trust_env=False，否则会走系统代理 → 502"

    def test_get_does_not_use_global_session(self, monkeypatch):
        """_get() 必须用 _local_session()，不能用全局 get_session()。

        这是关键的"本机永远绕过代理，外网搜索永远走代理"分工的护栏。
        任何回归（包括有人想"统一会话"）都会被这里抓住。
        """
        from lx_cli.core import openapi_client as mod
        called = {"global": 0, "local": 0}

        def fake_global(*a, **kw):
            called["global"] += 1
            raise AssertionError("_get 不应调用全局 get_session()")

        class FakeResp:
            status_code = 200
            text = "{}"
            def raise_for_status(self): pass

        def fake_local_get(url, **kw):
            called["local"] += 1
            assert "127.0.0.1" in url
            return FakeResp()

        class FakeLocal:
            def get(self, url, **kw): return fake_local_get(url, **kw)

        monkeypatch.setattr("lx_cli.core.http.get_session", fake_global)
        monkeypatch.setattr(mod, "_local_session", lambda: FakeLocal())

        mod._get(_ep(), "/status", timeout=1.0)
        assert called["local"] == 1
        assert called["global"] == 0

    def test_subscribe_does_not_use_global_session(self, monkeypatch):
        """SSE 订阅同样必须用本机会话。"""
        from lx_cli.core import openapi_client as mod

        def fake_global(*a, **kw):
            raise AssertionError("SSE 不应调用全局 get_session()")

        class FakeResp:
            def raise_for_status(self): pass
            def iter_lines(self, **kw): return iter([])
            def close(self): pass

        class FakeLocal:
            def get(self, url, **kw):
                assert "/subscribe-player-status" in url
                return FakeResp()

        monkeypatch.setattr("lx_cli.core.http.get_session", fake_global)
        monkeypatch.setattr(mod, "_local_session", lambda: FakeLocal())

        # 触发一次迭代就会立刻遇到 iter_lines 结束
        list(mod.subscribe_player_status(_ep(), idle_timeout=0.1))
