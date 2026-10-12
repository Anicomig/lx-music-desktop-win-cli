"""可移植性测试（P1–P4）。

覆盖：

* P1 换 CLI 目录/改名后可用
* P2 免安装也能跑（run.py）
* P3 跨机器定位 LX 数据目录（不硬编码用户名）
* P4 主动查找 LX 安装目录
* 文档齐备性、以及公开仓库的合规性（无真实数据 / 无断链）
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from lx_cli import paths

PROJECT = Path(__file__).resolve().parent.parent      # lx-cli-v2/
SRC = PROJECT / "src"


# --------------------------------------------------------- P1：自身位置


class TestSelfLocation:
    def test_package_root_is_real_dir(self):
        assert paths.package_root().is_dir()
        assert (paths.package_root() / "__init__.py").exists()

    def test_project_root_contains_src(self):
        root = paths.project_root()
        assert (root / "src" / "lx_cli").is_dir()
        assert (root / "pyproject.toml").exists()

    def test_src_dir_is_package_parent(self):
        assert paths.src_dir() == paths.package_root().parent
        assert paths.src_dir().name == "src"

    def test_ensure_importable_adds_src(self):
        """P1：把 src 加进 sys.path，使脚本可自举。

        ⚠️ 不能依赖仓库目录名（可能是 lx-cli-v2、lx-music-desktop-win-cli、
        或用户随意改的名字），所以用 PROJECT 推导而非硬编码字符串。
        """
        import sys as _sys
        saved = list(_sys.path)
        src = str(PROJECT / "src")
        try:
            _sys.path = [p for p in _sys.path if os.path.abspath(p) != src]
            changed = paths.ensure_importable()
            assert changed is True
            assert any(os.path.abspath(p) == src for p in _sys.path), \
                f"未把 {src} 加入 sys.path"
            # 再调一次不应重复添加
            assert paths.ensure_importable() is False
        finally:
            _sys.path = saved

    def test_ensure_importable_noop_when_installed(self, monkeypatch, tmp_path):
        """已 pip install（site-packages 布局）时不应改 sys.path。"""
        fake_pkg = tmp_path / "site-packages" / "lx_cli"
        fake_pkg.mkdir(parents=True)
        monkeypatch.setattr(paths, "package_root", lambda: fake_pkg)
        assert paths.ensure_importable() is False

    def test_no_absolute_self_path_hardcoded(self):
        """P1 核心：源码里不得出现写死的本机路径。"""
        bad_patterns = ["C:\\Users\\EDY", "D:\\Program Files", "/home/edy"]
        offenders = []
        for py in (SRC / "lx_cli").rglob("*.py"):
            text = py.read_text(encoding="utf-8", errors="ignore")
            for pat in bad_patterns:
                # 允许出现在注释/文档字符串里作为示例
                if pat in text and "paths.py" not in py.name:
                    offenders.append((py.name, pat))
        assert not offenders, f"源码里发现写死的本机路径：{offenders}"


def _clean_env() -> dict:
    """去掉 PYTHONPATH 的环境（验证"不依赖安装"）。

    同时保留其它变量（尤其 APPDATA/TEMP），否则子进程找不到数据目录/临时目录。
    """
    return {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}


def _run(args: list[str], cwd: Path, timeout: float = 120) -> subprocess.CompletedProcess:
    """统一的子进程调用（带超时，避免卡死；失败时给出诊断信息）。"""
    return subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8",
        errors="replace", cwd=str(cwd), env=_clean_env(), timeout=timeout)


class TestPortableLauncher:
    """P2：免安装启动器。"""

    def test_run_py_exists(self):
        assert (PROJECT / "run.py").exists()

    def test_lx_bat_exists(self):
        assert (PROJECT / "lx.bat").exists()

    def test_run_py_works_from_other_cwd(self, tmp_path):
        """从任意工作目录用绝对路径调用 run.py。"""
        p = _run([sys.executable, str(PROJECT / "run.py"), "--version"], tmp_path)
        assert p.returncode == 0, f"stderr={p.stderr!r}"
        assert "0.2" in p.stdout, f"应输出新版本号，实际：{p.stdout!r} {p.stderr!r}"

    def test_run_py_after_relocate_and_rename(self, tmp_path):
        """P1+P2：整个目录改名/搬家后仍可用。"""
        dst = tmp_path / "完全不同的名字"
        shutil.copytree(PROJECT, dst,
                        ignore=shutil.ignore_patterns(
                            "__pycache__", "*.pyc", ".pytest_cache",
                            "tests", ".git"))
        p = _run([sys.executable, str(dst / "run.py"), "--version"], tmp_path)
        assert p.returncode == 0, f"stderr={p.stderr!r}"
        assert "0.2" in p.stdout

    def test_run_py_help_lists_commands(self, tmp_path):
        p = _run([sys.executable, str(PROJECT / "run.py"), "--help"], tmp_path)
        assert p.returncode == 0, f"stderr={p.stderr!r}"
        for cmd in ("search", "playlist", "script", "where"):
            assert cmd in p.stdout, f"--help 缺少 {cmd}"

    def test_run_py_missing_src_gives_clear_error(self, tmp_path):
        """单独复制 run.py 出去时应给出明确提示，而不是 ImportError。"""
        lone = tmp_path / "run.py"
        lone.write_text((PROJECT / "run.py").read_text(encoding="utf-8"),
                        encoding="utf-8")
        p = _run([sys.executable, str(lone), "--version"], tmp_path)
        assert p.returncode == 2, f"stdout={p.stdout!r} stderr={p.stderr!r}"
        assert "src" in (p.stderr or "")


# --------------------------------------------------------- P3：数据目录


class TestDataLocation:
    def test_uses_appdata_env_not_hardcoded(self, monkeypatch, tmp_path):
        """P3 核心：通过 APPDATA 环境变量定位，换电脑/换账号自动适配。"""
        fake = tmp_path / "FakeRoaming"
        monkeypatch.setenv("APPDATA", str(fake))
        if sys.platform != "win32":
            pytest.skip("仅 Windows 默认路径走 APPDATA")
        got = paths.user_data_dir()
        assert got == fake / "lx-music-desktop"
        assert str(fake) in str(paths.lx_datas_dir())

    def test_lx_data_dir_env_override(self, monkeypatch, tmp_path):
        """极端情况下可用 LX_DATA_DIR 直接指定。

        注意：tmp_path 本身含用户名（pytest-of-EDY），所以这里只验证
        **拼接逻辑**，不断言路径里没有用户名（见下一个用例）。
        """
        # 已是 LxDatas 结尾 → 原样使用
        target = tmp_path / "LxDatas"
        monkeypatch.setenv("LX_DATA_DIR", str(target))
        assert paths.lx_datas_dir() == target
        # 大小写不敏感
        target2 = tmp_path / "lxdatas"
        monkeypatch.setenv("LX_DATA_DIR", str(target2))
        assert paths.lx_datas_dir() == target2
        # 给的是父目录 → 自动补 LxDatas
        parent = tmp_path / "parent"
        monkeypatch.setenv("LX_DATA_DIR", str(parent))
        assert paths.lx_datas_dir() == parent / "LxDatas"
        monkeypatch.delenv("LX_DATA_DIR", raising=False)

    def test_portable_mode_detected(self, tmp_path, monkeypatch):
        """<exe 同级>/portable 存在时走 portable 布局。"""
        exe_dir = tmp_path / "app"
        (exe_dir / "portable" / "userData").mkdir(parents=True)
        exe = exe_dir / "lx-music-desktop.exe"
        exe.write_bytes(b"")
        got = paths.user_data_dir(exe)
        assert got == exe_dir / "portable" / "userData"
        assert paths.lx_datas_dir(exe) == exe_dir / "portable" / "userData" / "LxDatas"

    def test_does_not_use_home_literal(self, monkeypatch, tmp_path):
        """P3：应只依赖 APPDATA 环境变量，而非 ``Path.home()`` 硬拼。

        做法：把 APPDATA 指到远离 home 的地方，验证结果跟着 APPDATA 走。
        （不能用"结果里没有用户名"来断言 —— pytest 的 tmp_path 本身含用户名。）
        """
        monkeypatch.delenv("LX_DATA_DIR", raising=False)
        fake = tmp_path / "TotallyDifferent" / "Roaming"
        monkeypatch.setenv("APPDATA", str(fake))
        if sys.platform != "win32":
            pytest.skip("Windows only")
        got = paths.lx_datas_dir()
        assert got == fake / "lx-music-desktop" / "LxDatas"
        assert str(paths.user_data_dir().parent) == str(fake)

class TestWrongPackageGuard:
    """防"静默加载旧版/残缺版 lx_cli"。

    本机若另有 editable 安装的旧版，不带本项目 src 时会优先加载它，
    表现为"命令莫名变少"。启动自检必须明确报错。
    """

    def test_self_check_passes_for_real_package(self, capsys):
        from lx_cli.cli import _self_check
        _self_check()          # 不应抛

    def test_self_check_detects_missing_commands(self, monkeypatch, capsys):
        """关键命令缺失时应 SystemExit(2) 并给出可操作提示。"""
        from lx_cli.cli import _self_check, cli
        fake = {k: v for k, v in cli.commands.items() if k != "script"}
        monkeypatch.setattr(cli, "commands", fake)
        with pytest.raises(SystemExit) as ei:
            _self_check()
        assert ei.value.code == 2
        err = capsys.readouterr().err
        assert "script" in err
        assert "run.py" in err or "PYTHONPATH" in err

    def test_console_encoding_does_not_crash(self):
        """GBK 控制台下输出中文/符号不应抛 UnicodeEncodeError。"""
        from lx_cli.cli import _fix_console_encoding
        _fix_console_encoding()      # 不应抛


class TestDataDirReport:
    def test_data_dir_report_shape(self):
        rep = paths.data_dir_report()
        for key in ("platform", "APPDATA", "resolved_userData",
                    "resolved_LxDatas", "exists"):
            assert key in rep


class TestDocsConsistency:
    """文档与实现不能漂移。"""

    def test_commands_doc_matches_help(self):
        """docs/reference/commands.md 应由 --help 生成且未过期。"""
        gens = PROJECT / "scripts" / "gen_commands_doc.py"
        assert gens.exists(), "缺少命令文档生成器"
        p = _run([sys.executable, str(gens), "--check"], PROJECT)
        assert p.returncode == 0, (
            "commands.md 与实现不一致，请重新生成：\n"
            f"{p.stdout}\n{p.stderr}")

    def test_required_docs_exist(self):
        """用户要求的文档结构必须齐备。"""
        required = [
            "README.md",
            "docs/guide/功能与操作.md",
            "docs/guide/ai-usage.md",
            "docs/guide/skills-usage.md",
            "docs/reference/commands.md",
            "docs/internals/README.md",
            "docs/internals/architecture.md",
            "docs/internals/contracts.md",
            "docs/internals/sources.md",
            "docs/internals/scripts.md",
            "docs/internals/database.md",
            "docs/internals/conventions.md",
            "skills/lx-cli/SKILL.md",
            "skills/README.md",
        ]
        missing = [r for r in required if not (PROJECT / r).exists()]
        assert not missing, f"缺少文档：{missing}"

    def test_skill_has_frontmatter(self):
        text = (PROJECT / "skills/lx-cli/SKILL.md").read_text(encoding="utf-8")
        assert text.startswith("---")
        assert "name:" in text and "description:" in text

    def test_planning_docs_archived(self):
        """计划类文档若存在，应放在 docs/planning。

        注意：公开仓库**有意排除** docs/planning（生产/计划文档不随代码开源），
        所以这里在缺失时跳过，而不是失败。
        """
        planning = PROJECT / "docs" / "planning"
        if not planning.is_dir():
            pytest.skip("docs/planning 未随仓库发布（公开仓库有意排除）")
        names = {p.name for p in planning.glob("*.md")}
        assert any("需求" in n or "01-" in n for n in names)
        assert any("改进" in n or "02-" in n for n in names)

    def test_research_archived(self):
        """调研报告应放在 docs/internals/research。"""
        res = PROJECT / "docs" / "internals" / "research"
        assert res.is_dir()
        assert len(list(res.glob("*.md"))) >= 6

    def test_no_planning_links_when_excluded(self):
        """公开仓库里若排除了 docs/planning，就不应存在指向它的链接。"""
        planning = PROJECT / "docs" / "planning"
        if planning.is_dir():
            pytest.skip("本副本含 docs/planning")
        offenders = []
        for md in PROJECT.rglob("*.md"):
            if ".git" in md.parts or "__pycache__" in md.parts:
                continue
            txt = md.read_text(encoding="utf-8", errors="ignore")
            if "docs/planning" in txt or "../planning/" in txt:
                offenders.append(str(md.relative_to(PROJECT)))
        assert not offenders, f"含指向已排除目录的链接：{offenders}"

    def test_no_secrets_or_real_data(self):
        """公开仓库不得含真实数据/密钥。"""
        bad = []
        for p in PROJECT.rglob("*"):
            if not p.is_file() or ".git" in p.parts:
                continue
            rel = str(p.relative_to(PROJECT))
            if p.suffix in (".db-wal", ".db-shm"):
                bad.append(rel)
            if p.name in ("user_api.json", "config_v2.json", "data.json"):
                bad.append(rel)
            if "syncAuthKey" in p.name:
                bad.append(rel)
        assert not bad, f"疑似真实数据/密钥：{bad}"


# --------------------------------------------------------- P4：查找 exe


class TestFindExe:
    def test_env_var_wins(self, monkeypatch, tmp_path):
        fake = tmp_path / "lx-music-desktop.exe"
        fake.write_bytes(b"")
        monkeypatch.setenv("LX_EXE", str(fake))
        got, how = paths.find_exe(search=False)
        assert got == fake and how == "env:LX_EXE"

    def test_env_var_missing_reported(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LX_EXE", str(tmp_path / "nope.exe"))
        got, how = paths.find_exe(search=False)
        assert got is None
        assert "不存在" in how

    def test_candidates_cover_multiple_drives(self):
        """P4：候选应覆盖多个盘符（换电脑后盘符常变）。"""
        cands = [str(p) for p in paths._candidate_paths()]
        assert any("C:" in c for c in cands)
        assert len(cands) >= 4

    def test_no_search_does_not_touch_registry(self, monkeypatch):
        """search=False 时不应访问注册表（应更快也更安全）。"""
        called = {"n": 0}
        monkeypatch.setattr(paths, "_find_in_windows_registry",
                            lambda: called.__setitem__("n", called["n"] + 1))
        monkeypatch.setenv("LX_EXE", "")
        paths.find_exe(search=False)
        assert called["n"] == 0

    def test_search_uses_registry_fallback(self, monkeypatch, tmp_path):
        """固定候选都找不到时，回退注册表。"""
        fake = tmp_path / "lx-music-desktop.exe"
        fake.write_bytes(b"")
        monkeypatch.delenv("LX_EXE", raising=False)
        monkeypatch.setattr(paths, "_candidate_paths", lambda: [tmp_path / "no.exe"])
        monkeypatch.setattr(paths, "_find_on_path", lambda: None)
        monkeypatch.setattr(paths, "_find_in_windows_registry", lambda: fake)
        got, how = paths.find_exe(search=True)
        assert got == fake and how == "registry"

    def test_not_found_returns_message(self, monkeypatch, tmp_path):
        monkeypatch.delenv("LX_EXE", raising=False)
        monkeypatch.setattr(paths, "_candidate_paths", lambda: [tmp_path / "no.exe"])
        monkeypatch.setattr(paths, "_find_on_path", lambda: None)
        monkeypatch.setattr(paths, "_find_in_windows_registry", lambda: None)
        monkeypatch.setattr(paths, "_scan_common_roots", lambda: None)
        got, how = paths.find_exe(search=True)
        assert got is None and how == "not-found"


# --------------------------------------------------------- launcher 集成


class TestLauncherDiscovery:
    def test_exe_path_explicit_missing_raises(self, tmp_path):
        from lx_cli.core.launcher import exe_path
        from lx_cli.errors import PathError
        with pytest.raises(PathError) as ei:
            exe_path(tmp_path / "nope.exe")
        assert "--exe" in str(ei.value)

    def test_exe_path_finds_real(self):
        """本机应能找到 LX（走候选或注册表）。"""
        from lx_cli.core.launcher import exe_path
        p = exe_path()
        assert p.exists()
        assert p.name.lower().endswith(".exe")
