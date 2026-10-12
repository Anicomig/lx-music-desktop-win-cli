"""skills 规范性测试（符合 skill-creator 规范）。

规范要点：SKILL.md 全大写、frontmatter 有 name/description、
name 匹配 ``^[a-z0-9]+(-[a-z0-9]+)*$`` 且与目录名一致、
description ≤1024、正文建议 <500 行、``@path`` 引用必须存在、
子目录只允许 scripts/assets/references。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parent.parent
SKILLS = PROJECT / "skills"
CHECKER = PROJECT / "scripts" / "check_skills.py"


def test_checker_exists():
    assert CHECKER.exists(), "缺少 skills 规范校验器"


def test_all_skills_pass_spec():
    """用校验器统一检查（与 CI/提交钩子一致）。"""
    p = subprocess.run([sys.executable, str(CHECKER)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=str(PROJECT), timeout=60)
    assert p.returncode == 0, f"skills 不合规：\n{p.stdout}\n{p.stderr}"
    assert "[OK]" in p.stdout


def test_skill_md_is_uppercase_filename():
    for d in SKILLS.iterdir():
        if d.is_dir() and not d.name.startswith("."):
            assert (d / "SKILL.md").exists(), f"{d.name} 缺少 SKILL.md（须全大写）"


def test_skill_name_matches_dir():
    import re
    from lx_cli.cli import __file__ as _  # noqa: F401  确保包可用
    for d in SKILLS.iterdir():
        if not d.is_dir() or d.name.startswith("."):
            continue
        text = (d / "SKILL.md").read_text(encoding="utf-8")
        m = re.search(r"^name:\s*(\S+)\s*$", text, re.M)
        assert m, f"{d.name}: frontmatter 缺 name"
        assert m.group(1) == d.name, f"name({m.group(1)}) != 目录名({d.name})"


def test_skill_body_under_500_lines():
    for d in SKILLS.iterdir():
        if not d.is_dir() or d.name.startswith("."):
            continue
        text = (d / "SKILL.md").read_text(encoding="utf-8")
        # 去掉 frontmatter
        parts = text.split("---", 2)
        body = parts[2] if len(parts) >= 3 else text
        lines = body.count("\n") + 1
        assert lines < 500, f"{d.name}: 正文 {lines} 行（建议 <500，用 references/ 拆分）"


def test_description_mentions_triggers():
    """description 应包含触发词，否则 AI 不会加载。"""
    text = (SKILLS / "lx-cli" / "SKILL.md").read_text(encoding="utf-8")
    head = text[:1200]
    for trigger in ("搜歌", "playlist", "play"):
        assert trigger in head, f"description 缺触发词：{trigger}"


def test_referenced_files_exist():
    """@path 引用的文件必须真实存在（校验器也会查，这里再显式断言一次）。"""
    import re
    skill = SKILLS / "lx-cli"
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    refs = re.findall(r"@([A-Za-z0-9_./-]+\.(?:md|sh|py))", text)
    assert refs, "SKILL.md 应通过 @path 引用 references（渐进披露）"
    missing = [r for r in refs if not (skill / r).exists()]
    assert not missing, f"引用的文件不存在：{missing}"


def test_helper_script_is_documented_and_executable_source():
    sh = SKILLS / "lx-cli" / "scripts" / "lx.sh"
    assert sh.exists()
    text = sh.read_text(encoding="utf-8")
    assert "LX_CLI_ROOT" in text, "helper 应支持显式指定根目录"
    assert "run.py" in text, "helper 应调用 run.py（免安装、路径无关）"


def test_no_hardcoded_user_path_in_skill():
    """skill 不得写死本机路径（换电脑后必须仍可用）。"""
    for p in (SKILLS / "lx-cli").rglob("*"):
        if p.is_file() and p.suffix in (".md", ".sh"):
            text = p.read_text(encoding="utf-8", errors="ignore")
            for bad in ("C:\\Users\\EDY", "D:\\Program Files", "/home/edy"):
                assert bad not in text, f"{p.name} 含写死的本机路径：{bad}"


def test_doc_links_not_broken():
    """全仓库文档的相对链接不得失效（文档搬移后容易断链）。"""
    checker = PROJECT / "scripts" / "fix_doc_links.py"
    assert checker.exists(), "缺少文档链接检查器"
    p = subprocess.run([sys.executable, str(checker), "--check"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=str(PROJECT), timeout=60)
    assert p.returncode == 0, f"存在失效文档链接：\n{p.stdout}\n{p.stderr}"
