"""``lx status-install`` 测试。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
ENV = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
ENV["PYTHONIOENCODING"] = "utf-8"


def _run(*args, timeout=60):
    return subprocess.run([sys.executable, "run.py", *args],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=str(PROJECT), env=ENV,
                          timeout=timeout)


class TestStatusInstall:
    def test_help(self):
        p = _run("status-install", "--help")
        assert p.returncode == 0
        assert "--json" in p.stdout

    def test_runs_human(self):
        p = _run("status-install")
        assert p.returncode == 0
        assert "安装状态" in p.stdout
        assert "CLI 版本" in p.stdout

    def test_json_shape(self):
        p = _run("status-install", "--json")
        assert p.returncode == 0
        d = json.loads(p.stdout)
        for key in ("cli_version", "install_mode", "package_location",
                    "python_version", "deps_ok", "exe_found", "datas_dir",
                    "global_lx_on_path", "offline_wheels_available"):
            assert key in d, f"JSON 缺字段 {key}"

    def test_version_matches_package(self):
        """status-install 的版本应与 --version 一致。"""
        a = _run("--version").stdout.strip()
        b = json.loads(_run("status-install", "--json").stdout)["cli_version"]
        assert b in a, f"--version={a!r} 与 status-install={b!r} 不一致"

    def test_install_mode_valid(self):
        mode = json.loads(_run("status-install", "--json").stdout)["install_mode"]
        assert mode in ("editable", "site-packages", "portable", "unknown")

    def test_deps_reported(self):
        d = json.loads(_run("status-install", "--json").stdout)
        assert isinstance(d["deps_ok"], bool)
        assert isinstance(d["deps_missing"], list)

    def test_offline_wheels_detected(self):
        """wheels/MANIFEST.json 存在时应报告离线能力。"""
        d = json.loads(_run("status-install", "--json").stdout)
        expect = (PROJECT / "wheels" / "MANIFEST.json").is_file()
        assert d["offline_wheels_available"] == expect

    def test_global_lx_not_false_positive(self):
        """当前目录的 lx.bat 不应被误判为全局 lx。"""
        d = json.loads(_run("status-install", "--json").stdout)
        # 项目根下有 lx.bat；若 which 命中它，绝不能算全局
        if d.get("global_lx_on_path"):
            gp = Path(d["global_lx_path"]).resolve()
            root = Path(d["project_root"]).resolve()
            assert not str(gp).startswith(str(root)), \
                "把项目内的 lx.bat 误判成了全局 lx"


class TestVersionUnchanged:
    """--version 仍只显示版本号（用户要求保持简单）。"""

    def test_version_is_single_line(self):
        out = _run("--version").stdout.strip()
        assert "\n" not in out
        assert "0.2" in out
        # 不应包含安装状态那些字段
        for forbidden in ("安装方式", "Python", "数据目录", "PATH"):
            assert forbidden not in out
