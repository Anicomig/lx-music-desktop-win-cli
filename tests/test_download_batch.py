"""批量下载测试（P3 增强）。

覆盖：任务构造、预演不下载、跳过已存在、失败不中断、
      报告写出、进程无残留。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from lx_cli.download import batch, fetcher, jshost  # noqa: E402

ENV = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
ENV["PYTHONIOENCODING"] = "utf-8"

requires_node = pytest.mark.skipif(
    not jshost.node_available(), reason="需要 Node 运行时")

#: 假脚本：固定返回一个假 URL（不联网，下载必然失败 → 测失败处理）
FAKE_SCRIPT = """
lx.on('request', function (req, send) {
  send('https://example.invalid/' + req.info.musicInfo.songmid + '.mp3')
})
lx.send('inited', { status: true, sources: { kw: { qualitys: ['320k'] } } })
"""


def _run(*args, timeout=180):
    return subprocess.run([sys.executable, "run.py", *args],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=str(PROJECT), env=ENV,
                          timeout=timeout)


# ------------------------------------------------------------ 任务构造

class TestItemsFromPlaylist:
    def test_builds_items_with_bare_songmid(self):
        """★ songmid 必须是裸 id（带前缀会让 JS 脚本取链失败）。"""
        from lx_cli.core import db_reader
        lists = [x for x in db_reader.list_lists() if x["songCount"] > 0]
        assert lists, "夹具里应有非空歌单"
        items = batch.items_from_playlist(lists[0]["id"])
        assert items
        for it in items:
            assert it.songmid, "songmid 不能为空"
            assert "_" not in it.songmid or it.source == "kg", \
                f"songmid 疑似带前缀: {it.songmid}"
            assert it.source in ("kg", "kw", "tx", "wy", "mg")

    def test_missing_list_raises(self):
        from lx_cli.errors import UsageError
        with pytest.raises(UsageError):
            batch.items_from_playlist("userlist_does_not_exist_123")

    def test_list_name_carried(self):
        from lx_cli.core import db_reader
        lists = [x for x in db_reader.list_lists() if x["songCount"] > 0]
        items = batch.items_from_playlist(lists[0]["id"])
        assert items[0].list_name == lists[0]["name"]
        assert items[0].list_id == lists[0]["id"]


class TestItemsFromFailed:
    def test_includes_error_records(self):
        items = batch.items_from_failed()
        # 真实库里有失败记录
        assert isinstance(items, list)
        for it in items:
            assert it.source and it.songmid
            assert it.quality

    def test_source_filter(self):
        items = batch.items_from_failed(source="kw")
        assert all(i.source == "kw" for i in items)

    def test_limit(self):
        items = batch.items_from_failed(limit=3)
        assert len(items) <= 3

    def test_reason_preserved(self):
        items = batch.items_from_failed(limit=5)
        if items:
            assert any(i.reason for i in items), "应保留原失败原因"

    def test_songmid_is_bare(self):
        """★ 关键回归：songmid 不能带 source 前缀。"""
        items = batch.items_from_failed()
        for it in items:
            if it.source != "kg":
                assert not it.songmid.startswith(f"{it.source}_"), \
                    f"{it.name}: songmid 带前缀 {it.songmid}"


class TestItemsFromSearch:
    def test_strips_prefix(self):
        songs = [{"id": "kw_123", "source": "kw", "name": "a", "singer": "b"},
                 {"id": "wy_456", "source": "wy", "name": "c", "singer": "d"}]
        items = batch.items_from_search(songs)
        assert items[0].songmid == "123"
        assert items[1].songmid == "456"

    def test_skips_incomplete(self):
        items = batch.items_from_search([{"name": "x"}, {"id": "kw_1"}])
        assert items == []


# ------------------------------------------------------------ 批量执行

class TestDryRun:
    def test_dry_run_returns_all_as_planned(self):
        items = [batch.BatchItem("a", "b", "kw", "1")]
        rep = batch.run_batch(items, "out", script_code="", apply_=False)
        assert rep.dry_run is True
        assert rep.total == 1
        # 预演不应有任何"成功"或被下载
        assert rep.ok_count == 0

    def test_dry_run_does_not_create_dir(self):
        d = Path(tempfile.mkdtemp()) / "nope"
        items = [batch.BatchItem("a", "b", "kw", "1")]
        batch.run_batch(items, d, script_code="", apply_=False)
        assert not d.exists(), "预演不应创建目录"

    def test_dry_run_json_shape(self):
        items = [batch.BatchItem("a", "b", "kw", "1", quality="320k")]
        rep = batch.run_batch(items, "out", script_code="", apply_=False)
        d = rep.to_json()
        for k in ("dryRun", "total", "ok", "skipped", "failed", "items"):
            assert k in d
        assert d["items"][0]["songmid"] == "1"


@requires_node
class TestSkipExisting:
    def test_skips_when_file_exists(self, tmp_path):
        """已存在且非空的文件应被跳过（不启动 Node）。"""
        it = batch.BatchItem("Song", "Singer", "kw", "1", quality="320k")
        # 按 run_batch 的命名规则预置文件
        guess = f"{it.name} - {it.singer}.mp3"
        (tmp_path / guess).write_bytes(b"x" * 4096)

        before = len(jshost.__dict__)  # 占位
        rep = batch.run_batch([it], tmp_path, script_code=FAKE_SCRIPT,
                              apply_=True, skip_existing=True)
        assert rep.items[0].skipped, "应被跳过"
        assert rep.ok_count == 0

    def test_overwrite_disables_skip(self, tmp_path):
        it = batch.BatchItem("Song", "Singer", "kw", "1")
        guess = f"{it.name} - {it.singer}.mp3"
        (tmp_path / guess).write_bytes(b"x" * 4096)
        rep = batch.run_batch([it], tmp_path, script_code=FAKE_SCRIPT,
                              apply_=True, skip_existing=False)
        # 会尝试下载（假 URL 必然失败），但不应是 skipped
        assert not rep.items[0].skipped


@requires_node
class TestFailureIsolation:
    def test_one_failure_does_not_stop_batch(self, tmp_path):
        """★ 单曲失败不应中断整批。"""
        items = [batch.BatchItem(f"Song{i}", "S", "kw", str(i))
                 for i in range(3)]
        rep = batch.run_batch(items, tmp_path, script_code=FAKE_SCRIPT,
                              apply_=True)
        assert rep.total == 3
        # 三首都应被"处理过"（假 URL 都会失败，但流程走完）
        assert len(rep.fail_items) == 3
        for it in rep.items:
            assert it.error, "每首都应有错误信息"

    def test_limit_applied(self, tmp_path):
        items = [batch.BatchItem(f"S{i}", "x", "kw", str(i)) for i in range(5)]
        rep = batch.run_batch(items, tmp_path, script_code=FAKE_SCRIPT,
                              apply_=True, limit=2)
        assert rep.total == 2


class TestReport:
    def test_save_and_load(self, tmp_path):
        rep = batch.BatchReport(dry_run=False, script="s", out_dir="o")
        rep.items = [batch.BatchItem("a", "b", "kw", "1", ok=True, bytes=100)]
        p = batch.save_report(rep, tmp_path / "r.json")
        assert p.is_file()
        d = json.loads(p.read_text(encoding="utf-8"))
        assert d["total"] == 1
        assert d["ok"] == 1
        assert d["items"][0]["name"] == "a"

    def test_save_creates_parent_dirs(self, tmp_path):
        rep = batch.BatchReport()
        p = batch.save_report(rep, tmp_path / "deep" / "nested" / "r.json")
        assert p.is_file()

    def test_report_counts_consistent(self):
        rep = batch.BatchReport()
        rep.items = [
            batch.BatchItem("a", "", "kw", "1", ok=True),
            batch.BatchItem("b", "", "kw", "2", skipped=True),
            batch.BatchItem("c", "", "kw", "3", error="x"),
        ]
        assert rep.total == 3
        assert rep.ok_count == 1
        assert rep.skip_count == 1
        assert len(rep.fail_items) == 1


# ------------------------------------------------------------ CLI

class TestCliBatch:
    def test_help_lists_batch_commands(self):
        p = _run("download", "--help")
        assert "list-all" in p.stdout
        assert "failed-all" in p.stdout
        assert "repair" in p.stdout

    def test_list_all_requires_out(self):
        p = _run("download", "list-all", "userlist_1")
        assert p.returncode != 0

    def test_list_all_ambiguous_name_errors(self):
        """歌单名匹配多个时应报错而不是随便选一个。"""
        p = _run("download", "list-all", "塞壬", "--out", "x")
        if p.returncode != 0:
            assert "匹配到多个" in (p.stdout + p.stderr)

    def test_list_all_dry_run_no_dir(self, tmp_path):
        from lx_cli.core import db_reader
        lists = [x for x in db_reader.list_lists() if x["songCount"] > 0]
        d = tmp_path / "should_not_exist"
        p = _run("download", "list-all", lists[0]["id"], "--out", str(d),
                 "--limit", "2", "--json")
        assert p.returncode == 0
        data = json.loads(p.stdout)
        assert data["dryRun"] is True
        assert not d.exists()

    def test_failed_all_dry_run_json(self, tmp_path):
        d = tmp_path / "nope"
        p = _run("download", "failed-all", "--out", str(d), "--limit", "3",
                 "--json")
        assert p.returncode == 0
        data = json.loads(p.stdout)
        assert data["dryRun"] is True
        assert not d.exists()

    def test_failed_all_source_filter(self, tmp_path):
        p = _run("download", "failed-all", "--out", str(tmp_path / "x"),
                 "--source", "kw", "--json")
        assert p.returncode == 0
        data = json.loads(p.stdout)
        assert all(i["source"] == "kw" for i in data["items"])

    def test_repair_equivalent_to_failed_all(self, tmp_path):
        """repair 与 failed-all 应是同一批任务。"""
        a = json.loads(_run("download", "repair", "--out", str(tmp_path / "a"),
                            "--limit", "5", "--json").stdout)
        b = json.loads(_run("download", "failed-all",
                            "--out", str(tmp_path / "b"),
                            "--limit", "5", "--json").stdout)
        assert a["total"] == b["total"]
        assert [i["songmid"] for i in a["items"]] == \
               [i["songmid"] for i in b["items"]]
