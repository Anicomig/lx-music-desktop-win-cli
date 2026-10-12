"""CLI 契约测试 —— 锁住 AI 消费方依赖的**行为契约**。

这些用例直接调用 ``lx_cli.cli.main()``（同进程，快），验证：

1. **退出码**约定：0 成功 / 1 运行时 / 2 用法 / 3 需关 LX / 4 上游
2. **``--json`` 契约**：成功有输出、形状稳定、stdout 不被日志污染
3. **错误也有输出**（旧版会出现"exit 1 但 stdout/stderr 全空"）
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lx_cli.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "lx.data.db"


def run(capsys, *args: str) -> tuple[int, str, str]:
    """跑一次 CLI，返回 (exit_code, stdout, stderr)。"""
    code = main(list(args))
    cap = capsys.readouterr()
    return code, cap.out, cap.err


# --------------------------------------------------------------- 退出码


class TestExitCodes:
    def test_version_ok(self, capsys):
        code, out, _ = run(capsys, "--version")
        assert code == 0
        assert "lx" in out.lower() or "0.2" in out

    def test_help_ok(self, capsys):
        code, out, _ = run(capsys, "--help")
        assert code == 0 and "search" in out

    def test_unknown_command_is_usage_error(self, capsys):
        code, _, err = run(capsys, "nosuchcmd")
        assert code == 2
        assert err.strip(), "用法错误也必须有输出"

    def test_unknown_platform_is_usage_error(self, capsys):
        code, _, err = run(capsys, "search", "x", "--source", "nope")
        assert code == 2
        assert "nope" in err

    def test_db_tables_on_fixture(self, capsys):
        code, out, _ = run(capsys, "--db", str(FIXTURE), "db", "tables")
        assert code == 0
        assert "my_list" in out

    def test_write_sql_rejected(self, capsys):
        """只读保证：写 SQL 必须失败（exit 1）且有明确输出。"""
        code, _, err = run(capsys, "--db", str(FIXTURE), "db", "query",
                           "DELETE FROM my_list")
        assert code == 1
        assert "readonly" in err.lower() or "只读" in err


# --------------------------------------------------------------- --json 契约


class TestJsonContract:
    def test_db_stats_json_is_valid(self, capsys):
        code, out, _ = run(capsys, "--db", str(FIXTURE), "db", "stats", "--json")
        assert code == 0
        data = json.loads(out)
        assert data["lists"] == 15
        assert data["songs"] == 1892
        assert "songsBySource" in data

    def test_db_query_json_shape(self, capsys):
        code, out, _ = run(capsys, "--db", str(FIXTURE), "db", "query",
                           "SELECT id FROM my_list LIMIT 2", "--json")
        assert code == 0
        data = json.loads(out)
        assert "rows" in data and "count" in data
        assert data["count"] == 2

    def test_error_json_shape(self, capsys):
        """错误在 --json 下必须是结构化 JSON（带 error.code）。"""
        code, out, _ = run(capsys, "search", "x", "--source", "nope", "--json")
        assert code == 2
        data = json.loads(out)
        assert "error" in data
        assert "code" in data["error"] and "message" in data["error"]

    def test_json_output_not_empty(self, capsys):
        """★ 修旧版 bug：``playlist export -o --json`` 曾输出空 stdout。"""
        code, out, _ = run(capsys, "--db", str(FIXTURE), "db", "info", "--json")
        assert code == 0
        assert out.strip(), "成功时 stdout 不得为空"
        json.loads(out)

    def test_where_json(self, capsys):
        code, out, _ = run(capsys, "where", "--json")
        assert code == 0
        data = json.loads(out)
        for key in ("LxDatas", "lx.data.db", "user_api.json"):
            assert key in data


# --------------------------------------------------------------- 平台/来源


class TestPlatformContract:
    def test_source_list_json_uses_platform_ids(self, capsys):
        """需求：来源用 kg/kw…而不是 Flower/SixYin。"""
        code, out, _ = run(capsys, "source-list", "--json")
        assert code == 0
        data = json.loads(out)
        ids = [s["platform"] for s in data["sources"]]
        assert set(ids) == {"kg", "kw", "tx", "mg", "wy"}
        blob = json.dumps(data, ensure_ascii=False)
        for bad in ("Flower", "SixYin", "flower", "sixyin"):
            assert bad not in blob

    def test_source_list_labels_are_chinese(self, capsys):
        code, out, _ = run(capsys, "source-list", "--json")
        data = json.loads(out)
        labels = {s["platform"]: s["label"] for s in data["sources"]}
        assert labels["kg"] == "酷狗音乐"
        assert labels["tx"] == "企鹅音乐"       # 不是 QQ音乐


# --------------------------------------------------------------- 帮助文本


class TestDbOverrideHonored:
    """★ ``--db`` 必须真正生效。

    回归：``playlist list`` 曾把 ``--db`` 路径位置传给了 ``list_lists`` 的
    第一个参数 ``include_virtual``，导致读取**默认库**而非指定库
    （表面正常，实际串了库 —— 对写操作尤其危险）。
    """

    def test_db_tables_uses_given_db(self, capsys, tmp_path):
        import shutil
        target = tmp_path / "x.db"
        shutil.copy2(FIXTURE, target)
        code, out, _ = run(capsys, "--db", str(target), "db", "tables", "--json")
        assert code == 0
        assert "my_list" in json.loads(out)["tables"]

    def test_playlist_list_reads_given_db(self, capsys, tmp_path):
        """在副本里新建歌单后，list 必须能看到它（证明读的是副本）。"""
        import shutil
        import sqlite3
        target = tmp_path / "y.db"
        shutil.copy2(FIXTURE, target)

        code, out, _ = run(capsys, "--db", str(target), "playlist", "create",
                           "只应出现在副本里", "--force")
        assert code == 0

        code, out, _ = run(capsys, "--db", str(target), "playlist", "list", "--json")
        assert code == 0
        names = [x["name"] for x in json.loads(out)["lists"]]
        assert "只应出现在副本里" in names, "list 没有反映 --db 指定的库"

        # 反向确认：默认库（真实库）不应被写
        code, out, _ = run(capsys, "playlist", "list", "--json")
        if code == 0:
            default_names = [x["name"] for x in json.loads(out)["lists"]]
            assert "只应出现在副本里" not in default_names, "写串到了默认库！"

    def test_db_stats_uses_given_db(self, capsys, tmp_path):
        import shutil
        target = tmp_path / "z.db"
        shutil.copy2(FIXTURE, target)
        code, out, _ = run(capsys, "--db", str(target), "db", "stats", "--json")
        assert code == 0
        assert json.loads(out)["songs"] == 1892


class TestHelp:
    @pytest.mark.parametrize("cmd", [
        "search", "song", "album", "play", "status", "play-song",
        "search-play", "db", "where", "backup",
    ])
    def test_command_has_help(self, capsys, cmd):
        code, out, _ = run(capsys, cmd, "--help")
        assert code == 0
        assert "Usage" in out or "用法" in out
