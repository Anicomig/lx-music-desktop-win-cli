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

    def test_uninstall_dry_run_is_default(self):
        """★ 默认必须是 dry-run —— 不加 --apply 绝不删任何东西。

        ⚠️ 历史教训：早期版本的 `test_uninstall_apply_requires_yes` 会真的
        执行 `uninstall --apply`，在非 TTY 环境下 Click 的 confirm 不会阻止，
        结果**真的把开发机上的 lx-cli 卸载了**。
        任何测试都**不得**对真实安装执行 `--apply`。
        """
        p = _run("uninstall", "--json", timeout=20)
        assert p.returncode in (0, 1)
        data = json.loads(p.stdout)
        # dry-run 下不应出现"已完成"的动作
        actions = [it.get("action") for it in data["plan"]]
        assert "edit-done" not in actions, \
            "默认（无 --apply）不应执行任何删除动作"
        # 且 pip 包必须还在
        check = subprocess.run(
            [sys.executable, "-m", "pip", "show", "lx-cli"],
            capture_output=True, text=True, env=ENV, timeout=20)
        assert check.returncode == 0, \
            "dry-run 不应卸载 pip 包（开发机上真的有 lx-cli！）"

    def test_uninstall_plan_never_touches_real_install(self):
        """计划里列出的待删项必须指向**真实安装**，且我们绝不执行它。

        本测试只做静态检查：确保 plan 的 `keep` 项包含 LX 本体与数据。
        """
        p = _run("uninstall", "--json", timeout=20)
        data = json.loads(p.stdout)
        targets = {it["target"] for it in data["plan"]}
        keeps = {it["target"] for it in data["plan"]
                 if it.get("action") == "keep"}
        assert any("LX Music Desktop" in t for t in keeps), \
            "必须明确保留 LX 本体"
        assert any("LX 数据" in t for t in keeps), \
            "必须明确保留 LX 数据"
        # 不允许出现"待删 LX 数据"这种危险计划
        for it in data["plan"]:
            if it.get("action") == "edit":
                assert "LxDatas" not in it["target"], \
                    f"计划里不应有删除 LxDatas 的动作: {it['target']}"

    def test_uninstall_does_not_touch_lx_data(self):
        """dry-run 后 LX 数据应原样（脚本不能误删 LxDatas 内容）。"""
        from lx_cli.paths import lx_datas_dir
        d = lx_datas_dir()
        before = sorted(p.name for p in d.iterdir())
        _run("uninstall", "--json")
        after = sorted(p.name for p in d.iterdir())
        assert before == after, f"LX 数据目录被改动：before={before} after={after}"

    def test_restore_config_plan_is_gated(self):
        """★ `--restore-config` 的计划必须标注"需先关 LX"。

        ⚠️ 历史教训：早期版本会真的执行
        `uninstall --apply --yes --restore-config`，那会**真的卸载 lx-cli
        并改写用户真实的 config_v2.json**。
        测试只能用 dry-run 检查计划内容，绝不执行 apply。
        """
        p = _run("uninstall", "--restore-config", "--json", timeout=20)
        assert p.returncode in (0, 1)
        data = json.loads(p.stdout)
        # 找到还原配置那一项
        items = [it for it in data["plan"]
                 if "openAPI" in (it.get("target") or "")
                 or "开放 API" in (it.get("target") or "")]
        if items:
            it = items[0]
            assert it.get("action") != "edit-done", \
                "dry-run 不应执行还原配置"
            note = it.get("note") or ""
            assert "关 LX" in note, f"必须提示需先关 LX，实际 note={note!r}"

    def test_restore_config_without_flag_is_skipped(self):
        """不加 --restore-config 时，计划里应是"跳过"而不是"待执行"。"""
        p = _run("uninstall", "--json", timeout=20)
        data = json.loads(p.stdout)
        for it in data["plan"]:
            if "还原" in (it.get("target") or ""):
                assert it.get("action") == "skip", \
                    f"不传 --restore-config 时应 skip，实际 {it.get('action')}"
