"""内置 wheels / 安装脚本的一致性测试。

这些测试保证：**发布的 zip 一定能在无网络的新电脑上装起来**。
"""

from __future__ import annotations

from conftest import version_major_minor as _vmm
_VERSION_MM = _vmm()

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parent.parent
WHEELS = PROJECT / "wheels"


def test_wheels_dir_exists():
    assert WHEELS.is_dir(), "缺少 wheels/ 目录（请跑 scripts/prepare_wheels.py）"


def test_manifest_exists_and_parses():
    mf = WHEELS / "MANIFEST.json"
    assert mf.is_file()
    data = json.loads(mf.read_text(encoding="utf-8"))
    assert data["wheels"], "MANIFEST 里没有 wheel"
    assert "sha256" in data["wheels"][0]


def test_direct_dependencies_present():
    """click 与 requests 必须在内置 wheels 里（离线安装的最低要求）。"""
    names = {p.name.lower() for p in WHEELS.glob("*.whl")}
    joined = " ".join(names)
    assert "click" in joined, f"缺少 click wheel：{names}"
    assert "requests" in joined, f"缺少 requests wheel：{names}"


def test_all_wheels_hash_match_manifest():
    """哈希必须与 MANIFEST 一致（防篡改 / 防损坏）。"""
    data = json.loads((WHEELS / "MANIFEST.json").read_text(encoding="utf-8"))
    bad = []
    for w in data["wheels"]:
        p = WHEELS / w["name"]
        if not p.is_file():
            bad.append(f"缺失 {w['name']}")
            continue
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        if h != w["sha256"]:
            bad.append(f"哈希不符 {w['name']}")
    assert not bad, f"wheels 校验失败：{bad}"


def test_transitive_deps_bundled():
    """requests 的传递依赖也要在，否则离线装会缺包。"""
    names = {p.name.lower() for p in WHEELS.glob("*.whl")}
    joined = " ".join(names)
    for dep in ("urllib3", "certifi", "idna"):
        assert dep in joined, f"缺少传递依赖 {dep}：{names}"


def test_universal_wheels_are_version_agnostic():
    """核心 wheel 应是 py3-none-any（跨 Python 版本通用）。

    charset_normalizer 是版本绑定的（cpXXX-winYY），它**不是必需的**
    —— requests 有纯 Python 回退。若它缺失也不应导致失败。
    """
    any_wheels = [p.name for p in WHEELS.glob("*py3-none-any.whl")]
    assert len(any_wheels) >= 3, f"通用 wheel 太少：{any_wheels}"


# ---- 安装脚本 ----

def test_install_bat_exists():
    assert (PROJECT / "install.bat").is_file()


def test_uninstall_bat_exists():
    assert (PROJECT / "uninstall.bat").is_file()


def test_install_bat_uses_offline_first():
    """install.bat 必须优先用内置 wheels（--no-index），而不是直接联网。"""
    text = (PROJECT / "install.bat").read_text(encoding="utf-8", errors="ignore")
    assert "--no-index" in text, "install.bat 应优先离线安装"
    assert "--find-links" in text, "install.bat 应用 --find-links 指向 wheels/"
    assert "wheels" in text


def test_install_bat_detects_python_variants():
    text = (PROJECT / "install.bat").read_text(encoding="utf-8", errors="ignore")
    for c in ("py", "python3", "python"):
        assert c in text, f"install.bat 未探测 {c}"


def test_install_bat_handles_temp():
    """TEMP 不可写应有回退（这是文档 §1.3 的坑）。"""
    text = (PROJECT / "install.bat").read_text(encoding="utf-8", errors="ignore")
    assert "TEMP" in text
    assert "LOCALAPPDATA" in text or "Temp" in text


def test_install_bat_has_network_fallback():
    """离线装失败时应回退联网（避免完全卡死）。"""
    text = (PROJECT / "install.bat").read_text(encoding="utf-8", errors="ignore")
    assert "回退" in text or "fallback" in text.lower()
    assert "pypi" in text.lower() or "-i https" in text


def test_uninstall_bat_warns_about_data():
    """卸载脚本必须明确告知"不删 LX 数据"。"""
    text = (PROJECT / "uninstall.bat").read_text(encoding="utf-8", errors="ignore")
    assert "不会" in text or "不删" in text
    assert "LX" in text


# ---- 端到端离线安装（较慢，标记为 slow 时可用 -m "not slow" 跳过）----

@pytest.mark.slow
def test_offline_install_in_clean_venv():
    """在全新 venv 里做一次真实离线安装。

    这是"发布包能否在新电脑装上"的最终验收。
    """
    import tempfile
    import venv
    import shutil

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        pkg = tmp / "pkg"
        shutil.copytree(PROJECT, pkg, ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", ".pytest_cache", ".git", "dist"))
        vdir = tmp / "venv"
        venv.create(vdir, with_pip=True)
        vpy = vdir / "Scripts" / "python.exe" if os.name == "nt" else vdir / "bin" / "python"

        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        env["PYTHONIOENCODING"] = "utf-8"

        # 离线装
        r = subprocess.run(
            [str(vpy), "-m", "pip", "install", "--no-index",
             "--find-links", "wheels", "click", "requests", "--quiet",
             "--disable-pip-version-check"],
            cwd=str(pkg), capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=env, timeout=600)
        assert r.returncode == 0, f"离线安装失败：{r.stderr[-300:]}"

        # 能跑
        r = subprocess.run([str(vpy), "run.py", "--version"], cwd=str(pkg),
                           capture_output=True, text=True, encoding="utf-8",
                           env=env, timeout=60)
        assert r.returncode == 0
        assert _VERSION_MM in r.stdout
