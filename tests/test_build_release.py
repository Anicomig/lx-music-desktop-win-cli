"""build_release.py 的自检测试。

覆盖打包/排除/校验的逻辑（不涉及 gh 上传、zip 体积断言等网络/环境依赖）。
"""
import os
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_release  # noqa: E402


# ---------- should_exclude 的所有规则 ----------

def test_exclude_planning_dir():
    assert build_release.should_exclude(ROOT / "docs" / "planning" / "x.md")

def test_exclude_backup_dir():
    assert build_release.should_exclude(ROOT / "_backup" / "x.zip")
    assert build_release.should_exclude(ROOT / "sub" / "_backup" / "x")

def test_exclude_pycache():
    assert build_release.should_exclude(ROOT / "src" / "x" / "__pycache__" / "a.pyc")

def test_exclude_pyc_file():
    assert build_release.should_exclude(ROOT / "src" / "x.pyc")

def test_exclude_user_data_files():
    assert build_release.should_exclude(ROOT / "user_api.json")
    assert build_release.should_exclude(ROOT / "config_v2.json")
    assert build_release.should_exclude(ROOT / "data.json")

def test_exclude_wal_shm():
    assert build_release.should_exclude(ROOT / "lx.data.db-wal")
    assert build_release.should_exclude(ROOT / "lx.data.db-shm")

def test_exclude_syncauth():
    assert build_release.should_exclude(ROOT / "syncAuthKey_xxx.json")

def test_KEEP_gitignore():
    """⚠️ .gitignore 必须保留（用户要能看到排除规则）。"""
    assert not build_release.should_exclude(ROOT / ".gitignore")

def test_KEEP_fixtures_db():
    """脱敏测试夹具是合成数据，须保留。"""
    assert not build_release.should_exclude(ROOT / "tests" / "fixtures" / "lx.data.db")

def test_KEEP_normal_files():
    assert not build_release.should_exclude(ROOT / "src" / "lx_cli" / "cli.py")
    assert not build_release.should_exclude(ROOT / "README.md")
    assert not build_release.should_exclude(ROOT / "docs" / "guide" / "功能与操作.md")


def test_exclude_releases_dir():
    """releases/ 是本地发布包缓存，绝不能进新 zip（否则 zip 套 zip）。"""
    assert build_release.should_exclude(
        ROOT / "releases" / "lx-music-desktop-win-cli-v0.2.0.zip")
    assert build_release.should_exclude(ROOT / "releases" / "anything")


# ---------- 端到端：打 zip 实际校验内容 ----------

def test_built_zip_excludes_forbidden(tmp_path, monkeypatch):
    """真实打一个临时 zip，验证内容不包含排除项。"""
    import zipfile
    out = tmp_path / "test.zip"
    files = []
    for p in ROOT.rglob("*"):
        if p.is_file() and not build_release.should_exclude(p):
            files.append(p)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            zf.write(p, p.relative_to(ROOT).as_posix())

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()

    # 排除项必须一个都没有
    for n in names:
        parts = set(n.split("/"))
        for forbidden in build_release.EXCLUDE_PATH_FRAGMENTS:
            assert forbidden not in parts, f"zip 含禁止目录: {n}"
        assert not n.endswith(("user_api.json", "config_v2.json",
                              "data.json", ".db-wal", ".db-shm")), \
            f"zip 含禁止文件: {n}"

    # 必须包含的关键文件
    must_have = ["README.md", "pyproject.toml", "run.py", "lx.bat",
                 ".gitignore", "src/lx_cli/__init__.py",
                 "tests/fixtures/lx.data.db"]
    for m in must_have:
        assert m in names, f"zip 缺少关键文件: {m}"


# ---------- 版本管理 ----------

def test_pyproject_version_format():
    """版本号应为 PEP 440：x.y.z（可后接 rc/dev 等）。"""
    import re
    v = build_release.read_version_from_pyproject()
    assert re.fullmatch(r"\d+\.\d+\.\d+[a-zA-Z0-9._+\-]*", v), \
        f"版本号格式不合 PEP 440: {v!r}"
