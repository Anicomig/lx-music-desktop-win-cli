"""音源脚本模块测试（离线，全部在临时目录里跑）。

★ 安全约束：**绝不触碰真实 ``%APPDATA%`` 路径** —— 所有用例显式传
``path=`` / ``meta_path=``。曾因 CLI 默认读真实路径而误写真实文件。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lx_cli.scripts import repo as repo_mod
from lx_cli.scripts import service, store
from lx_cli.scripts.metadata import (
    MAX_SCRIPT_CHARS, TAG_LIMITS, is_valid_script, parse_script_meta,
    validate_script_size,
)

SAMPLE = """/*!
 * @name 测试音源
 * @description 一个用于测试的音源
 * @version v1.2.3
 * @author 测试者
 * @homepage https://example.invalid
 */
(function(){ return 1 })();
"""


@pytest.fixture()
def paths(tmp_path):
    """返回 (user_api 路径, meta 路径)，均指向临时目录。"""
    return tmp_path / "user_api.json", tmp_path / "scripts_meta.json"


# --------------------------------------------------------- 编码（最关键）


class TestEncoding:
    def test_encode_has_gz_prefix(self):
        assert store.encode_script(SAMPLE).startswith("gz_")

    def test_roundtrip(self):
        assert store.decode_script(store.encode_script(SAMPLE)) == SAMPLE

    def test_roundtrip_unicode(self):
        text = "/*\n * @name 野花🌷\n */\nconsole.log('塞壬唱片、日本語、한국어')"
        assert store.decode_script(store.encode_script(text)) == text

    def test_is_zlib_not_gzip(self):
        """★ ``gz_`` 前缀有误导性 —— 实际是 zlib，不是 gzip。

        用 gzip 解压必须失败（否则说明编码选错了）。
        """
        import base64
        import gzip
        import zlib
        encoded = store.encode_script(SAMPLE)
        raw = base64.b64decode(encoded[3:])
        # zlib 可用
        assert zlib.decompress(raw).decode("utf-8") == SAMPLE
        # gzip 不可用
        with pytest.raises(OSError):
            gzip.decompress(raw)

    def test_decode_bad_raises(self):
        from lx_cli.errors import ScriptParseError
        with pytest.raises(ScriptParseError):
            store.decode_script("gz_!!!not-base64!!!")

    def test_decode_plaintext_passthrough(self):
        assert store.decode_script("plain text") == "plain text"

    def test_empty(self):
        assert store.decode_script("") == ""


# --------------------------------------------------------- 元数据头


class TestMetadata:
    def test_parse_all_tags(self):
        m = parse_script_meta(SAMPLE)
        assert m.name == "测试音源"
        assert m.version == "v1.2.3"
        assert m.author == "测试者"
        assert m.homepage == "https://example.invalid"

    def test_requires_block_at_index_zero(self):
        """★ LX 要求注释块在**索引 0**，前面有内容即非法。"""
        assert parse_script_meta(SAMPLE).name
        assert not parse_script_meta("\n" + SAMPLE).name
        assert not parse_script_meta("// hi\n" + SAMPLE).name
        assert not parse_script_meta("\ufeff" + SAMPLE).name      # BOM 也不行

    def test_strict_raises_without_header(self):
        from lx_cli.errors import ScriptParseError
        with pytest.raises(ScriptParseError):
            parse_script_meta("no header", strict=True)

    def test_unknown_tags_ignored(self):
        m = parse_script_meta("/*\n * @name n\n * @weird x\n */")
        assert m.name == "n"
        assert "weird" in m.raw_tags            # 记录但不当字段
        assert not hasattr(m, "weird")

    def test_truncation_lengths(self):
        long_name = "n" * 50
        m = parse_script_meta(f"/*\n * @name {long_name}\n */")
        assert len(m.name) == TAG_LIMITS["name"] + 3        # + '...'
        assert m.name.endswith("...")

    def test_is_valid_script(self):
        assert is_valid_script(SAMPLE)
        assert not is_valid_script("")
        assert not is_valid_script("no header")

    def test_size_limit(self):
        from lx_cli.errors import ScriptParseError
        with pytest.raises(ScriptParseError):
            validate_script_size("x" * (MAX_SCRIPT_CHARS + 1))


# --------------------------------------------------------- 存储读写


class TestStore:
    def test_load_missing_returns_empty(self, paths):
        ua, _ = paths
        assert store.load_entries(path=ua) == []

    def test_save_and_load(self, paths):
        ua, _ = paths
        e = store.ScriptEntry(id="user_api_1_x", name="n", version="1",
                              script=SAMPLE, script_encoded=store.encode_script(SAMPLE))
        store.save_entries([e], path=ua, check_running=False)
        got = store.load_entries(path=ua)
        assert len(got) == 1
        assert got[0].name == "n"
        assert got[0].script == SAMPLE

    def test_saved_file_uses_tab_indent(self, paths):
        """★ LX 写的是 Tab 缩进，保持一致。"""
        ua, _ = paths
        store.save_entries([store.ScriptEntry(id="i", name="n", script=SAMPLE,
                                              script_encoded=store.encode_script(SAMPLE))],
                           path=ua, check_running=False)
        text = ua.read_text(encoding="utf-8")
        assert "\t" in text
        assert json.loads(text)["userApis"][0]["id"] == "i"

    def test_storage_has_8_keys(self, paths):
        """条目必须是 LX 期望的 8 个键。"""
        e = store.ScriptEntry(id="i", script=SAMPLE)
        assert set(e.to_storage()) == {
            "id", "name", "description", "version", "author",
            "homepage", "allowShowUpdateAlert", "script"}

    def test_sha256_stable(self):
        a = store.ScriptEntry(id="1", script=SAMPLE)
        b = store.ScriptEntry(id="2", script=SAMPLE)
        assert a.sha256 == b.sha256

    def test_atomic_write_leaves_no_tmp(self, paths):
        ua, _ = paths
        store.save_entries([store.ScriptEntry(id="i", script=SAMPLE,
                                              script_encoded=store.encode_script(SAMPLE))],
                           path=ua, check_running=False)
        leftovers = list(ua.parent.glob("user_api.json.tmp*"))
        assert leftovers == []


# --------------------------------------------------------- 哈希清单 / 手改检测


class TestModificationDetection:
    def test_modified_when_no_record(self, paths):
        e = store.ScriptEntry(id="i", script=SAMPLE)
        assert store.is_modified(e, {}) is True

    def test_not_modified_when_hash_matches(self, paths):
        e = store.ScriptEntry(id="i", script=SAMPLE)
        meta = {"i": {"installedSha256": e.sha256}}
        assert store.is_modified(e, meta) is False

    def test_modified_when_hash_differs(self, paths):
        e = store.ScriptEntry(id="i", script=SAMPLE)
        meta = {"i": {"installedSha256": "deadbeef"}}
        assert store.is_modified(e, meta) is True

    def test_record_roundtrip(self, paths):
        ua, mp = paths
        e = store.ScriptEntry(id="i", name="n", script=SAMPLE)
        store.record_install(e, source="flower", url="http://x", path=mp)
        meta = store.load_meta(path=mp)
        assert meta["i"]["installedSha256"] == e.sha256
        assert meta["i"]["source"] == "flower"


# --------------------------------------------------------- 仓库适配


class TestRepo:
    def test_ten_sources(self):
        assert len(repo_mod.REPO_SOURCES) == 10

    def test_resolve_by_key(self):
        assert repo_mod.resolve("flower").label == "野花🌷"

    def test_resolve_by_label(self):
        assert repo_mod.resolve("野花🌷").key == "flower"

    def test_resolve_from_url(self):
        assert repo_mod.resolve(
            "https://raw.githubusercontent.com/pdone/lx-music-source/main/lx/latest.js"
        ).key == "lx"

    def test_resolve_unknown(self):
        assert repo_mod.resolve("nope") is None

    def test_raw_url_shape(self):
        url = repo_mod.raw_url("flower")
        assert url == ("https://raw.githubusercontent.com/pdone/"
                       "lx-music-source/main/flower/latest.js")

    def test_url_candidates_direct_first_then_mirrors(self):
        urls = repo_mod.url_candidates("lx")
        assert urls[0] == repo_mod.raw_url("lx")
        assert len(urls) == 1 + len(repo_mod.MIRRORS)
        assert all(u.startswith("https://") for u in urls)

    def test_fetch_rejects_non_http(self):
        from lx_cli.errors import ScriptDownloadError
        with pytest.raises(ScriptDownloadError):
            repo_mod.fetch_text("file:///etc/passwd")


# --------------------------------------------------------- 服务层


class TestService:
    def test_install_then_list(self, paths):
        ua, mp = paths
        src = ua.parent / "fake.js"
        src.write_text(SAMPLE, encoding="utf-8")
        plan = service.install_from_file(src, path=ua, meta_path=mp,
                                         force=True, dry_run=False)
        assert plan.action == "install"
        rows = service.list_scripts(path=ua, meta_path=mp)
        assert len(rows) == 1
        assert rows[0]["name"] == "测试音源"
        assert rows[0]["modified"] is False      # 刚由 CLI 安装，有记录

    def test_install_dry_run_writes_nothing(self, paths):
        ua, mp = paths
        src = ua.parent / "fake.js"
        src.write_text(SAMPLE, encoding="utf-8")
        service.install_from_file(src, path=ua, meta_path=mp,
                                  force=True, dry_run=True)
        assert store.load_entries(path=ua) == []

    def test_update_preserves_id(self, paths):
        """★ 更新必须保留原 id，否则用户的 common.apiSource 会跳变。"""
        ua, mp = paths
        src = ua.parent / "fake.js"
        src.write_text(SAMPLE, encoding="utf-8")
        p1 = service.install_from_file(src, path=ua, meta_path=mp,
                                       force=True, dry_run=False)
        src.write_text(SAMPLE.replace("v1.2.3", "v2.0.0"), encoding="utf-8")
        p2 = service.install_from_file(src, path=ua, meta_path=mp,
                                       force=True, dry_run=False)
        assert p2.action == "update"
        assert p2.entry_id == p1.entry_id
        assert len(store.load_entries(path=ua)) == 1

    def test_update_identical_is_skip(self, paths):
        ua, mp = paths
        src = ua.parent / "fake.js"
        src.write_text(SAMPLE, encoding="utf-8")
        service.install_from_file(src, path=ua, meta_path=mp, force=True, dry_run=False)
        p = service.install_from_file(src, path=ua, meta_path=mp, force=True, dry_run=False)
        assert p.action == "skip"

    def test_hand_edit_requires_force(self, paths):
        """★ 被手改过的脚本，不带 --force 必须拒绝覆盖。"""
        from lx_cli.errors import ScriptModifiedError
        ua, mp = paths
        src = ua.parent / "fake.js"
        src.write_text(SAMPLE, encoding="utf-8")
        service.install_from_file(src, path=ua, meta_path=mp, force=True, dry_run=False)

        # 模拟用户手改（改内容但不动 CLI 记录的哈希）
        entries = store.load_entries(path=ua)
        entries[0].script += "\n// user edit"
        entries[0].script_encoded = store.encode_script(entries[0].script)
        store.save_entries(entries, path=ua, check_running=False)

        src.write_text(SAMPLE.replace("v1.2.3", "v9.9.9"), encoding="utf-8")
        with pytest.raises(ScriptModifiedError):
            service.install_from_file(src, path=ua, meta_path=mp,
                                      force=False, dry_run=False)
        # 带 force 则应成功
        p = service.install_from_file(src, path=ua, meta_path=mp,
                                      force=True, dry_run=False)
        assert p.action == "update"

    def test_remove(self, paths):
        ua, mp = paths
        src = ua.parent / "fake.js"
        src.write_text(SAMPLE, encoding="utf-8")
        service.install_from_file(src, path=ua, meta_path=mp, force=True, dry_run=False)
        service.remove("测试音源", path=ua, meta_path=mp, force=True)
        assert store.load_entries(path=ua) == []

    def test_remove_unknown_raises(self, paths):
        from lx_cli.errors import ScriptError
        ua, mp = paths
        with pytest.raises(ScriptError):
            service.remove("nope", path=ua, meta_path=mp, force=True)

    def test_remove_dry_run_keeps(self, paths):
        ua, mp = paths
        src = ua.parent / "fake.js"
        src.write_text(SAMPLE, encoding="utf-8")
        service.install_from_file(src, path=ua, meta_path=mp, force=True, dry_run=False)
        service.remove("测试音源", path=ua, meta_path=mp, force=True, dry_run=True)
        assert len(store.load_entries(path=ua)) == 1

    def test_max_scripts_limit(self, paths):
        from lx_cli.errors import TooManyScriptsError
        ua, mp = paths
        entries = [
            store.ScriptEntry(id=f"user_api_{i}", name=f"s{i}", script=SAMPLE,
                              script_encoded=store.encode_script(SAMPLE))
            for i in range(20)
        ]
        store.save_entries(entries, path=ua, check_running=False)
        src = ua.parent / "fake.js"
        src.write_text(SAMPLE.replace("测试音源", "新源"), encoding="utf-8")
        with pytest.raises(TooManyScriptsError):
            service.install_from_file(src, path=ua, meta_path=mp,
                                      force=True, dry_run=False)

    def test_backup_created_on_write(self, paths):
        ua, mp = paths
        src = ua.parent / "fake.js"
        src.write_text(SAMPLE, encoding="utf-8")
        service.install_from_file(src, path=ua, meta_path=mp, force=True, dry_run=False)
        src.write_text(SAMPLE.replace("v1.2.3", "v2"), encoding="utf-8")
        service.install_from_file(src, path=ua, meta_path=mp, force=True, dry_run=False)
        backups = list(ua.parent.glob("user_api.json.bak-*"))
        assert backups, "写前应生成 .bak 备份"
