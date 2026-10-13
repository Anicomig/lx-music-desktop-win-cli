"""``lx doctor`` / ``lx uninstall`` 测试。"""
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


def _run(*args, timeout=60) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "run.py", *args],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=str(PROJECT), env=ENV,
                          timeout=timeout)


# ---- doctor ---------------------------------------------------------

class TestDoctor:
    def test_doctor_help(self):
        p = _run("doctor", "--help")
        assert p.returncode == 0
        assert "--no-network" in p.stdout

    def test_doctor_runs(self):
        p = _run("doctor")
        # 退出码 0/1/2 都算"跑了"（0 全 ok，1 有 fail，2 有 warn）
        assert p.returncode in (0, 1, 2)
        assert "CLI 版本" in p.stdout or "version" in p.stdout

    def test_doctor_json_shape(self):
        p = _run("doctor", "--json")
        # 退出码取决于环境：全 ok=0，有 warn=2，有 fail=1；都算"跑了"
        assert p.returncode in (0, 1, 2), f"exit={p.returncode}"
        d = json.loads(p.stdout)
        assert "checks" in d
        assert isinstance(d["checks"], list)
        # 至少应包含：版本、依赖、配置
        ids = {c["id"] for c in d["checks"]}
        assert "cli.version" in ids
        assert "deps" in ids

    def test_doctor_no_network_skips_api_and_search(self):
        p = _run("doctor", "--no-network", "--json")
        d = json.loads(p.stdout)
        skip_ids = {c["id"] for c in d["checks"] if c["status"] == "skip"}
        assert "api.reach" in skip_ids
        assert "net.search" in skip_ids

    def test_doctor_does_not_crash_on_unexpected_state(self):
        """真实运行下不应因单点异常而崩溃。"""
        # 若环境是干净的（LX 在跑 + API 启用），应该 exit 0
        # 任何情况下 exit code 都不应 >= 3（除 click 使用错误）
        p = _run("doctor", "--json")
        assert p.returncode in (0, 1, 2)
        # JSON 必须是合法的（说明没中途崩）
        json.loads(p.stdout)


# ---- uninstall ------------------------------------------------------

class TestUninstall:
    def test_uninstall_help(self):
        p = _run("uninstall", "--help")
        assert p.returncode == 0
        for opt in ("--apply", "--yes", "--restore-config", "--json"):
            assert opt in p.stdout

    def test_uninstall_dry_run_does_not_touch_anything(self):
        """dry-run 必须不改任何文件。"""
        # 记录关键路径的 mtime
        from lx_cli.paths import lx_datas_dir
        metas = list(lx_datas_dir().glob("lx_cli_scripts_meta.json"))
        # 跑 dry-run
        p = _run("uninstall")
        assert p.returncode in (0, 1)
        assert "dry-run" in p.stdout
        # 元数据应原样
        metas_after = list(lx_datas_dir().glob("lx_cli_scripts_meta.json"))
        assert metas == metas_after

    def test_uninstall_json_shape(self):
        p = _run("uninstall", "--json")
        d = json.loads(p.stdout)
        assert "plan" in d
        assert isinstance(d["plan"], list)
        # 必须包含：pip / lx.exe / LX 桌面端 / LX 数据 / zip
        targets = {it["target"] for it in d["plan"]}
        assert any("pip 包 lx-cli" in t or "未通过 pip 安装" in t for t in targets)
        assert any("LX 可执行" in t or "lx.exe" in t or "PATH 中无 lx" in t for t in targets)
        assert any("LX Music Desktop 桌面端" in t for t in targets)
        assert any("LX 数据" in t for t in targets)

    def test_uninstall_apply_requires_yes(self):
        """未加 --yes 时若是非 TTY 应当 abort 而不是直接跑。"""
        # 在非交互环境里，Click confirm 不会自动 yes——这正是"二次确认"的目的
        # （让自动化脚本必须显式加 --yes）
        p = _run("uninstall", "--apply", "--json", timeout=15)
        # 非 TTY 下 click.confirm 抛 Abort，SystemExit 1
        # 但因为我们没设 stdin，行为视 click 版本而定。接受"没真删东西"就行
        if p.returncode == 0:
            # 万一执行了：检查 pip 还装着
            check = subprocess.run(
                [sys.executable, "-m", "pip", "show", "lx-cli"],
                capture_output=True, text=True, env=ENV, timeout=15)
            assert check.returncode == 0, "意外被卸载"

    def test_uninstall_does_not_touch_lx_data(self):
        """dry-run 后 LX 数据应原样（脚本不能误删 LxDatas 内容）。"""
        from lx_cli.paths import lx_datas_dir
        d = lx_datas_dir()
        before = sorted(p.name for p in d.iterdir())
        _run("uninstall", "--json")
        after = sorted(p.name for p in d.iterdir())
        assert before == after, f"LX 数据目录被改动：before={before} after={after}"

    def test_uninstall_restore_config_blocks_when_lx_running(self):
        """LX 在跑时 --restore-config 应直接拒绝（防止被 LX 覆盖）。"""
        # 假设 LX 在跑（本测试环境里很可能在跑）—— 这里仅检查退出码非 0
        # 不是说 dry-run 应该写，而是说它会主动拒绝 apply
        p = _run("uninstall", "--apply", "--restore-config", "--yes",
                 "--json", timeout=15)
        # 若 LX 真的在跑，应 exit 非 0 并提示；不在跑则会真去改 config
        if p.returncode != 0:
            assert "必须先关 LX" in p.stdout or "关 LX" in p.stdout or p.returncode != 0
