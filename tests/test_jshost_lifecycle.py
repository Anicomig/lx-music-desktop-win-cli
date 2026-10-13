"""★ 资源释放测试 —— 用户明确要求"不使用时要释放"。

这些测试是本阶段最重要的验收项：
  任何路径（成功 / 失败 / 超时 / 异常 / Ctrl+C）都**不得残留 Node 进程**。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from lx_cli.download import jshost  # noqa: E402


def _node_procs() -> list[int]:
    """当前 node 进程 PID 列表（Windows）。"""
    if os.name != "nt":
        return []
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-Process node -ErrorAction SilentlyContinue).Id -join ','"],
            capture_output=True, text=True, timeout=20).stdout.strip()
        return [int(x) for x in out.split(",") if x.strip().isdigit()]
    except Exception:
        return []


#: 一个最小可用的假脚本：不发网络请求，直接同步回 URL
FAKE_SCRIPT = """
lx.on('request', function(req, send) {
  if (req.action === 'musicUrl') {
    send('https://example.invalid/audio.mp3')
  }
})
lx.send('inited', { status: true, sources: { kw: { qualitys: ['320k'] } } })
"""

#: 故意报错的脚本
FAIL_SCRIPT = """
lx.on('request', function(req, send) {
  send({ code: -1, msg: '测试用失败' })
})
lx.send('inited', { status: true, sources: { kw: { qualitys: ['320k'] } } })
"""

#: 永不返回的脚本（测超时强杀）
HANG_SCRIPT = """
lx.on('request', function(req, send) { /* 永不回调 */ })
lx.send('inited', { status: true, sources: { kw: { qualitys: ['320k'] } } })
"""


requires_node = pytest.mark.skipif(
    not jshost.node_available(), reason="需要 Node 运行时")


@requires_node
class TestNoLeak:
    """所有路径都不得残留进程。"""

    def test_success_leaves_no_process(self):
        before = set(_node_procs())
        r = jshost.fetch_url(FAKE_SCRIPT, source="kw", songmid="1",
                             quality="320k", timeout=20)
        assert r.ok, r.error
        assert r.url == "https://example.invalid/audio.mp3"
        time.sleep(1.0)
        leaked = set(_node_procs()) - before
        assert not leaked, f"成功后残留 Node 进程: {leaked}"

    def test_handler_error_leaves_no_process(self):
        before = set(_node_procs())
        r = jshost.fetch_url(FAIL_SCRIPT, source="kw", songmid="1",
                             quality="320k", timeout=20)
        assert not r.ok
        time.sleep(1.0)
        leaked = set(_node_procs()) - before
        assert not leaked, f"失败后残留 Node 进程: {leaked}"

    def test_timeout_is_killed(self):
        """★ 关键：超时必须强杀，不能挂着。

        两种都可能：宿主内部兜底超时（stage=request，更快更干净）
        或父进程强杀（stage=timeout）。两者都要**无残留**。
        """
        before = set(_node_procs())
        t0 = time.time()
        r = jshost.fetch_url(HANG_SCRIPT, source="kw", songmid="1",
                             quality="320k", timeout=3)
        dur = time.time() - t0
        assert not r.ok
        assert r.stage in ("timeout", "host", "request"), \
            f"意外 stage={r.stage}"
        assert dur < 15, f"超时未生效，耗时 {dur:.1f}s"
        time.sleep(1.5)
        leaked = set(_node_procs()) - before
        assert not leaked, f"超时后残留 Node 进程: {leaked}"

    def test_bad_script_leaves_no_process(self):
        before = set(_node_procs())
        r = jshost.fetch_url("this is not valid javascript {{{",
                             source="kw", songmid="1", timeout=15)
        assert not r.ok
        time.sleep(1.0)
        leaked = set(_node_procs()) - before
        assert not leaked

    def test_keyboard_interrupt_cleans_up(self, monkeypatch):
        """模拟 Ctrl+C：`communicate` 抛 KeyboardInterrupt 时也要杀进程。"""
        before = set(_node_procs())
        import subprocess as sp

        real_popen = sp.Popen
        created: list = []

        class TrackingPopen(real_popen):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                created.append(self)

            def communicate(self, *a, **kw):
                raise KeyboardInterrupt()

        monkeypatch.setattr(sp, "Popen", TrackingPopen)
        try:
            jshost.fetch_url(FAKE_SCRIPT, source="kw", songmid="1", timeout=10)
        except KeyboardInterrupt:
            pass
        finally:
            monkeypatch.undo()
        for p in created:
            assert p.poll() is not None, "KeyboardInterrupt 后子进程仍在运行"
        time.sleep(1.0)
        leaked = set(_node_procs()) - before
        assert not leaked, f"Ctrl+C 后残留: {leaked}"


@requires_node
class TestNoTempLeak:
    def test_temp_script_deleted_after_success(self):
        import tempfile
        tmpdir = Path(tempfile.gettempdir())
        before = {p.name for p in tmpdir.glob("lxjs_*.js")}
        jshost.fetch_url(FAKE_SCRIPT, source="kw", songmid="1", timeout=20)
        after = {p.name for p in tmpdir.glob("lxjs_*.js")}
        assert after == before, f"临时脚本残留: {after - before}"

    def test_temp_script_deleted_after_failure(self):
        import tempfile
        tmpdir = Path(tempfile.gettempdir())
        before = {p.name for p in tmpdir.glob("lxjs_*.js")}
        jshost.fetch_url("invalid {{{", source="kw", songmid="1", timeout=15)
        after = {p.name for p in tmpdir.glob("lxjs_*.js")}
        assert after == before, f"失败后临时脚本残留: {after - before}"

    def test_temp_script_deleted_after_timeout(self):
        import tempfile
        tmpdir = Path(tempfile.gettempdir())
        before = {p.name for p in tmpdir.glob("lxjs_*.js")}
        jshost.fetch_url(HANG_SCRIPT, source="kw", songmid="1", timeout=3)
        after = {p.name for p in tmpdir.glob("lxjs_*.js")}
        assert after == before, f"超时后临时脚本残留: {after - before}"


class TestMemoryLimit:
    def test_max_old_space_flag_applied(self, monkeypatch):
        """确认给 Node 传了堆上限，防止内存失控。"""
        captured = {}

        class FakeProc:
            def __init__(self, cmd, *a, **kw):
                captured["cmd"] = cmd
                self._done = False

            def communicate(self, timeout=None):
                return ('{"ok":true,"url":"https://x/y.mp3"}', "")

            def poll(self):
                return 0

            def kill(self):
                pass

        import subprocess as sp
        monkeypatch.setattr(sp, "Popen", FakeProc)
        jshost.fetch_url(FAKE_SCRIPT, source="kw", songmid="1", timeout=5)
        cmd = captured.get("cmd") or []
        assert any("--max-old-space-size=" in str(c) for c in cmd), \
            f"未传内存上限: {cmd[:3]}"


class TestResultParsing:
    """不依赖 Node：直接测解析逻辑。"""

    def test_last_json_line_picks_final(self):
        text = ('script log line\n'
                '{"ok":true,"url":"https://a/b.mp3"}\n')
        assert jshost._last_json_line(text) == '{"ok":true,"url":"https://a/b.mp3"}'

    def test_last_json_line_none_when_absent(self):
        assert jshost._last_json_line("no json here\nplain text") is None

    def test_last_json_line_ignores_partial(self):
        assert jshost._last_json_line('{"ok":true') is None
