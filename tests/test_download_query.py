"""P1 下载记录查询 + P2 脚本体检 测试。

只读命令，用脱敏夹具，不碰真实数据。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parent.parent
ENV = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
ENV["PYTHONIOENCODING"] = "utf-8"


def _run(*args, timeout=90):
    return subprocess.run([sys.executable, "run.py", *args],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=str(PROJECT), env=ENV,
                          timeout=timeout)


def _jrun(*args, timeout=90):
    p = _run(*args, timeout=timeout)
    assert p.returncode == 0, f"命令失败: {p.stdout}\n{p.stderr}"
    return json.loads(p.stdout)


# ------------------------------------------------------------ P1: download

class TestDownloadGroup:
    def test_help_lists_subcommands(self):
        p = _run("download", "--help")
        assert p.returncode == 0
        for sub in ("stats", "list", "failed", "verify"):
            assert sub in p.stdout, f"缺少子命令 {sub}"

    def test_stats_runs(self):
        p = _run("download", "stats")
        assert p.returncode == 0
        assert "下载记录" in p.stdout

    def test_stats_json_shape(self):
        d = _jrun("download", "stats", "--json")
        for k in ("total", "completed", "failed", "incomplete",
                  "byStatus", "byQuality", "bySource", "totalBytes"):
            assert k in d, f"缺字段 {k}"
        # 计数自洽
        assert d["total"] >= d["completed"]
        assert d["total"] == sum(d["byStatus"].values())

    def test_list_json_shape(self):
        d = _jrun("download", "list", "--limit", "3", "--json")
        assert "items" in d and isinstance(d["items"], list)
        if d["items"]:
            r = d["items"][0]
            for k in ("name", "singer", "source", "quality", "status",
                      "statusText", "filePath", "percent"):
                assert k in r, f"条目缺字段 {k}"

    def test_list_limit_respected(self):
        d = _jrun("download", "list", "--limit", "2", "--json")
        assert len(d["items"]) <= 2

    def test_list_status_filter(self):
        d = _jrun("download", "list", "--status", "completed",
                  "--limit", "5", "--json")
        assert all(i["status"] == "completed" for i in d["items"])

    def test_list_incomplete_filter(self):
        d = _jrun("download", "list", "--status", "incomplete",
                  "--limit", "5", "--json")
        assert all(not i["isComplete"] for i in d["items"])

    def test_failed_runs_and_hints(self):
        p = _run("download", "failed", "--limit", "5")
        assert p.returncode == 0
        assert "失败" in p.stdout

    def test_failed_json_shape(self):
        d = _jrun("download", "failed", "--limit", "5", "--json")
        assert "failed" in d and "items" in d
        # 所有返回项都应是未完成
        assert all(not i["isComplete"] for i in d["items"])

    def test_verify_runs(self):
        p = _run("download", "verify")
        assert p.returncode == 0
        assert "缺失" in p.stdout

    def test_verify_json_shape(self):
        d = _jrun("download", "verify", "--json")
        for k in ("total", "present", "missing", "sizeMismatch",
                  "missingItems", "sizeMismatchItems"):
            assert k in d, f"缺字段 {k}"
        # 计数与明细一致
        assert d["missing"] == len(d["missingItems"])
        assert d["sizeMismatch"] == len(d["sizeMismatchItems"])
        assert d["total"] == d["present"] + d["missing"] + d["sizeMismatch"]

    def test_verify_no_size_flag(self):
        d = _jrun("download", "verify", "--no-size", "--json")
        assert d["sizeMismatch"] == 0, "--no-size 时不应报大小异常"


class TestDownloadReader:
    """直接测 core 层（不经 CLI）。"""

    def test_downloads_returns_list(self):
        from lx_cli.core import db_reader
        rows = db_reader.downloads(limit=5)
        assert isinstance(rows, list)
        assert len(rows) <= 5

    def test_stats_consistency(self):
        from lx_cli.core import db_reader
        s = db_reader.download_stats()
        assert s["total"] == sum(s["byStatus"].values())
        assert s["completed"] == s["byStatus"].get("completed", 0)

    def test_verify_counts_add_up(self):
        from lx_cli.core import db_reader
        v = db_reader.verify_downloads()
        assert v["total"] == v["present"] + v["missing"] + v["sizeMismatch"]

    def test_size_tolerance_is_lenient(self):
        """10% 容差：正常文件（补写 ID3 后差 1-2%）不应被报异常。"""
        from lx_cli.core import db_reader
        v = db_reader.verify_downloads()
        # 实测真实库：34 missing / 2 mismatch（1% 阈值会误报 70 条）
        assert v["sizeMismatch"] < 10, \
            f"大小异常过多（{v['sizeMismatch']}），可能是阈值过严"


# ------------------------------------------------------------ P2: script doctor

class TestScriptDoctor:
    def test_registered_under_script(self):
        p = _run("script", "--help")
        assert p.returncode == 0
        assert "doctor" in p.stdout

    def test_runs(self):
        p = _run("script", "doctor")
        assert p.returncode == 0
        assert "体检报告" in p.stdout

    def test_json_shape(self):
        d = _jrun("script", "doctor", "--json")
        for k in ("active", "count", "shellThreshold", "scripts"):
            assert k in d, f"缺字段 {k}"
        assert d["count"] == len(d["scripts"])
        assert d["shellThreshold"] > 0

    def test_shell_script_flagged(self):
        """字符数低于阈值的脚本必须被标为异常。"""
        d = _jrun("script", "doctor", "--json")
        for s in d["scripts"]:
            if s["scriptChars"] < d["shellThreshold"]:
                assert s["status"] in ("warn", "fail"), \
                    f"{s['name']} 只有 {s['scriptChars']} 字符却未被标记"
                assert any("空壳" in i for i in s["issues"])

    def test_healthy_script_not_failed(self):
        """字符数充足的脚本不应被判 fail。"""
        d = _jrun("script", "doctor", "--json")
        for s in d["scripts"]:
            if s["scriptChars"] >= d["shellThreshold"]:
                assert s["status"] != "fail", \
                    f"{s['name']}（{s['scriptChars']} 字符）被误判 fail: {s['issues']}"

    def test_active_marked(self):
        d = _jrun("script", "doctor", "--json")
        active = [s for s in d["scripts"] if s["active"]]
        assert len(active) <= 1, "最多一个脚本应被标为当前启用"
        if d["active"]:
            assert len(active) == 1

    def test_no_false_modified_alarm(self):
        """非 CLI 安装的脚本不应因 modified 被误报（实测全部误报）。"""
        d = _jrun("script", "doctor", "--json")
        for s in d["scripts"]:
            for issue in s["issues"]:
                assert "哈希不符" not in issue or s["modified"], \
                    f"{s['name']} 报了哈希问题但 modified=False"


class TestScriptDoctorExtraction:
    """测源码线索提取（纯函数）。"""

    def test_extract_sources(self):
        from lx_cli.cli.script_doctor import _extract_from_source
        code = "sources: {'kg': {}, 'wy': {}} // 'kw'"
        info = _extract_from_source(code)
        assert "kg" in info["sources"] and "wy" in info["sources"]

    def test_extract_qualities(self):
        from lx_cli.cli.script_doctor import _extract_from_source
        code = "qualitys: ['flac', '320k', '128k']"
        info = _extract_from_source(code)
        assert "flac" in info["qualities"]
        assert "320k" in info["qualities"]

    def test_detect_proxy_kind(self):
        from lx_cli.cli.script_doctor import _extract_from_source
        code = "fetch('https://my-backend.example.com/api/url')"
        info = _extract_from_source(code)
        assert info["kind"] == "proxy"
        assert "my-backend.example.com" in info["externalHosts"]

    def test_detect_self_contained(self):
        from lx_cli.cli.script_doctor import _extract_from_source
        code = "fetch('http://www.kuwo.cn/api')"
        info = _extract_from_source(code)
        assert info["kind"] == "self-contained"

    def test_ignore_github_hosts(self):
        from lx_cli.cli.script_doctor import _extract_from_source
        code = "https://raw.githubusercontent.com/x/y/master/package.json"
        info = _extract_from_source(code)
        assert info["externalHosts"] == [], "GitHub 不应算后端依赖"

    def test_meta_block_detection(self):
        from lx_cli.cli.script_doctor import _extract_from_source
        assert _extract_from_source("/*! @name A @version 1 */")["hasMetaBlock"]
        assert not _extract_from_source("var x = 1")["hasMetaBlock"]

    def test_empty_code_safe(self):
        from lx_cli.cli.script_doctor import _extract_from_source
        info = _extract_from_source("")
        assert info["sources"] == []
        assert info["kind"] == "unknown"
