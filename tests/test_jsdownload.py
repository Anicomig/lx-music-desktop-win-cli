"""P3：JS 音源宿主 + 下载器 测试。

分两类：
  * **不依赖 Node/网络**：协议解析、文件名、格式探测（纯函数）
  * **依赖 Node**：用本地假脚本跑通协议（不打网络）
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from lx_cli.download import fetcher, jshost  # noqa: E402

requires_node = pytest.mark.skipif(
    not jshost.node_available(), reason="需要 Node 运行时")


# ------------------------------------------------------------ 纯函数

class TestSafeFilename:
    def test_basic(self):
        assert fetcher.safe_filename("歌名 - 歌手", "mp3") == "歌名 - 歌手.mp3"

    def test_illegal_chars_replaced(self):
        got = fetcher.safe_filename('a/b\\c:d*e?f"g<h>i|j', "flac")
        assert "/" not in got and "\\" not in got and ":" not in got
        assert got.endswith(".flac")

    def test_trailing_dot_space_stripped(self):
        got = fetcher.safe_filename("name. ", "mp3")
        assert not got.startswith("name. .")
        assert got.endswith(".mp3")

    def test_empty_falls_back(self):
        assert fetcher.safe_filename("", "mp3") == "unknown.mp3"

    def test_long_name_truncated(self):
        got = fetcher.safe_filename("x" * 500, "mp3")
        assert len(got) < 220


class TestGuessExt:
    def test_from_content_type(self):
        assert fetcher.guess_ext("http://x/y", "audio/flac") == "flac"
        assert fetcher.guess_ext("http://x/y", "audio/mpeg") == "mp3"

    def test_from_url(self):
        assert fetcher.guess_ext("http://x/a.flac?token=1") == "flac"
        assert fetcher.guess_ext("http://x/a.m4a") == "m4a"

    def test_fallback(self):
        assert fetcher.guess_ext("http://x/noext", "", fallback="flac") == "flac"


class TestDetectAudioKind:
    def test_flac(self, tmp_path):
        p = tmp_path / "a.flac"
        p.write_bytes(b"fLaC" + b"\x00" * 20)
        assert fetcher.detect_audio_kind(p) == "flac"

    def test_mp3_id3(self, tmp_path):
        p = tmp_path / "a.mp3"
        p.write_bytes(b"ID3\x04\x00\x00" + b"\x00" * 20)
        assert fetcher.detect_audio_kind(p) == "mp3"

    def test_mp3_frame(self, tmp_path):
        p = tmp_path / "b.mp3"
        p.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 20)
        assert fetcher.detect_audio_kind(p) == "mp3"

    def test_m4a(self, tmp_path):
        p = tmp_path / "c.m4a"
        p.write_bytes(b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 10)
        assert fetcher.detect_audio_kind(p) == "m4a"

    def test_fake_flac_is_detected_as_mp3(self, tmp_path):
        """★ 关键：扩展名 flac 但内容是 MP3（实测 lxmusic 有此问题）。"""
        p = tmp_path / "fake.flac"
        p.write_bytes(b"ID3\x03\x00\x00" + b"\xff\xfb\x90\x00")
        assert fetcher.detect_audio_kind(p) == "mp3"

    def test_unknown(self, tmp_path):
        p = tmp_path / "x.bin"
        p.write_bytes(b"\x01\x02\x03\x04")
        assert fetcher.detect_audio_kind(p) == "unknown"

    def test_missing_file(self, tmp_path):
        assert fetcher.detect_audio_kind(tmp_path / "nope") == "unknown"


class TestNodeDiscovery:
    def test_find_node_returns_tuple(self):
        node, how = jshost.find_node()
        assert (node is None) or isinstance(node, Path)
        assert isinstance(how, str)

    def test_host_script_path_derived(self):
        """宿主脚本路径应按包位置推导（搬家仍可用）。"""
        hs = jshost.host_script()
        assert hs.name == "lx-script-host.js"
        assert hs.parent.name == "tools"

    def test_env_override_missing_file_reported(self, monkeypatch):
        monkeypatch.setenv("LX_NODE", r"C:\definitely\not\here\node.exe")
        node, how = jshost.find_node()
        assert node is None
        assert "LX_NODE" in how

    def test_doctor_report_shape(self):
        r = jshost.doctor_report()
        for k in ("node", "nodeSource", "hostScript", "hostScriptExists",
                  "available", "bundled"):
            assert k in r


# ------------------------------------------------------------ 需要 Node

GOOD_SCRIPT = """
lx.on('request', function (req, send) {
  if (req.action === 'musicUrl') send('https://cdn.example.invalid/a.mp3')
})
lx.send('inited', { status: true, sources: { kw: { qualitys: ['320k'] } } })
"""

OBJ_SCRIPT = """
lx.on('request', function (req, send) {
  send({ data: { url: 'https://cdn.example.invalid/obj.flac' } })
})
lx.send('inited', { status: true, sources: { kw: {} } })
"""

FAIL_SCRIPT = """
lx.on('request', function (req, send) { send({ code: -1, msg: 'paid' }) })
lx.send('inited', { status: true, sources: { kw: {} } })
"""

INIT_FAIL_SCRIPT = """
lx.on('request', function (req, send) { send('x') })
lx.send('inited', { status: false, message: '初始化失败' })
"""

STDOUT_NOISE_SCRIPT = """
console.log('some log line')
console.log('{"looks":"like json"}')
lx.on('request', function (req, send) { send('https://ok.invalid/x.mp3') })
lx.send('inited', { status: true, sources: {} })
"""


@requires_node
class TestProtocol:
    def test_string_result(self):
        r = jshost.fetch_url(GOOD_SCRIPT, source="kw", songmid="1", timeout=20)
        assert r.ok, r.error
        assert r.url == "https://cdn.example.invalid/a.mp3"

    def test_object_result(self):
        r = jshost.fetch_url(OBJ_SCRIPT, source="kw", songmid="1", timeout=20)
        assert r.ok, r.error
        assert r.url == "https://cdn.example.invalid/obj.flac"

    def test_error_result(self):
        r = jshost.fetch_url(FAIL_SCRIPT, source="kw", songmid="1", timeout=20)
        assert not r.ok
        assert "paid" in r.error

    def test_init_failure_detected(self):
        r = jshost.fetch_url(INIT_FAIL_SCRIPT, source="kw", songmid="1",
                             timeout=20)
        assert not r.ok
        assert r.stage in ("init", "request")

    def test_stdout_noise_still_parsed(self):
        """脚本往 stdout 打日志时仍应取到最后一个 JSON。"""
        r = jshost.fetch_url(STDOUT_NOISE_SCRIPT, source="kw", songmid="1",
                             timeout=20)
        assert r.ok, r.error
        assert r.url.endswith("x.mp3")

    def test_result_has_elapsed(self):
        r = jshost.fetch_url(GOOD_SCRIPT, source="kw", songmid="1", timeout=20)
        assert r.elapsed_ms >= 0

    def test_no_network_needed(self):
        """整个协议测试不依赖外网（用 example.invalid 假域名）。"""
        r = jshost.fetch_url(GOOD_SCRIPT, source="kw", songmid="1", timeout=20)
        assert r.ok
        assert ".invalid" in r.url


# ------------------------------------------------------------ CLI 集成

import subprocess  # noqa: E402

ENV = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
ENV["PYTHONIOENCODING"] = "utf-8"


def _run(*args, timeout=120):
    return subprocess.run([sys.executable, "run.py", *args],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=str(PROJECT), env=ENV,
                          timeout=timeout)


class TestCliRegistration:
    def test_download_help_lists_all(self):
        p = _run("download", "--help")
        assert p.returncode == 0
        for sub in ("stats", "list", "failed", "verify", "url", "get",
                    "repair"):
            assert sub in p.stdout, f"缺少子命令 {sub}"

    def test_url_requires_node_or_reports_clearly(self):
        """没有 Node 时应给出清晰指引，而不是崩栈。"""
        p = _run("download", "url", "1", "--source", "kw")
        # 有 Node：会尝试执行（可能取不到，但不应是 Python traceback）
        # 无 Node：应报"未找到 Node"
        assert "Traceback" not in p.stderr, p.stderr[:400]

    def test_get_requires_out(self):
        p = _run("download", "get", "1", "--source", "kw")
        assert p.returncode != 0
        assert "out" in (p.stdout + p.stderr).lower()

    def test_repair_dry_run_no_download(self):
        """repair 默认预演，不应创建目录或下载。"""
        import tempfile
        d = Path(tempfile.mkdtemp()) / "should_not_exist"
        p = _run("download", "repair", "--out", str(d), "--limit", "2")
        assert p.returncode == 0
        assert "预演" in p.stdout
        assert not d.exists(), "预演阶段不应创建目录"

    def test_repair_json_shape(self):
        import tempfile
        d = Path(tempfile.mkdtemp()) / "nope"
        p = _run("download", "repair", "--out", str(d), "--limit", "2",
                 "--json")
        assert p.returncode == 0
        data = json.loads(p.stdout)
        assert data.get("dryRun") is True
        assert "items" in data
