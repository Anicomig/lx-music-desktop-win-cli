"""校验 skills 是否符合 skill-creator 规范。

规则来源（skill-creator）：
* ``SKILL.md`` 文件名全大写
* frontmatter 有 ``name`` / ``description``
* ``name`` 匹配 ``^[a-z0-9]+(-[a-z0-9]+)*$``（1–64 字符，无首尾/连续连字符）
* ``description`` 1–1024 字符
* 正文建议 < 500 行
* ``@path`` 引用的文件必须**真实存在**
* 目录结构只含 SKILL.md + scripts/ + assets/ + references/

用法::

    python scripts/check_skills.py            # 校验（退出码 0/1）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
REF_RE = re.compile(r"@([A-Za-z0-9_./-]+\.(?:md|sh|py|js|json|ya?ml))")
ALLOWED_SUBDIRS = {"scripts", "assets", "references"}


def _parse_frontmatter(text: str) -> dict[str, str]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" in line and not line.startswith((" ", "-")):
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip()
    return out


def check_skill(skill_dir: Path) -> list[str]:
    errs: list[str] = []
    md = skill_dir / "SKILL.md"
    if not md.exists():
        # 大小写敏感检查（规范要求全大写 SKILL.md）
        alt = [p.name for p in skill_dir.glob("*.md")]
        errs.append(f"{skill_dir.name}: 缺少 SKILL.md（找到：{alt}）")
        return errs

    text = md.read_text(encoding="utf-8")
    fm = _parse_frontmatter(text)

    # --- frontmatter ---
    name = fm.get("name", "")
    desc = fm.get("description", "")
    if not name:
        errs.append(f"{skill_dir.name}: frontmatter 缺少 name")
    else:
        if not NAME_RE.match(name):
            errs.append(f"{skill_dir.name}: name 不合规（应 ^[a-z0-9]+(-[a-z0-9]+)*$）：{name!r}")
        if not (1 <= len(name) <= 64):
            errs.append(f"{skill_dir.name}: name 长度应为 1-64，实际 {len(name)}")
        if name != skill_dir.name:
            errs.append(f"{skill_dir.name}: name({name!r}) 与目录名不一致")
    if not desc:
        errs.append(f"{skill_dir.name}: frontmatter 缺少 description")
    elif not (1 <= len(desc) <= 1024):
        errs.append(f"{skill_dir.name}: description 长度应为 1-1024，实际 {len(desc)}")

    # --- 正文长度 ---
    body = FRONTMATTER_RE.sub("", text, count=1)
    lines = body.count("\n") + 1
    if lines > 500:
        errs.append(f"{skill_dir.name}: 正文 {lines} 行，建议 < 500（用 references/ 拆分）")

    # --- @path 引用必须存在 ---
    for ref in sorted(set(REF_RE.findall(body))):
        if not (skill_dir / ref).exists():
            errs.append(f"{skill_dir.name}: @{ref} 引用不存在")

    # --- 目录结构 ---
    for child in skill_dir.iterdir():
        if child.is_dir() and child.name not in ALLOWED_SUBDIRS:
            errs.append(f"{skill_dir.name}: 非规范子目录 {child.name}"
                        f"（允许：{sorted(ALLOWED_SUBDIRS)}）")
    return errs


def main() -> int:
    if not SKILLS.is_dir():
        print(f"[FAIL] 找不到 skills 目录：{SKILLS}")
        return 1

    skill_dirs = [d for d in sorted(SKILLS.iterdir())
                  if d.is_dir() and not d.name.startswith(".")]
    if not skill_dirs:
        print("[FAIL] skills 下没有 skill 目录")
        return 1

    all_errs: list[str] = []
    for d in skill_dirs:
        errs = check_skill(d)
        status = "OK  " if not errs else "FAIL"
        print(f"[{status}] {d.name}")
        all_errs.extend(errs)

    if all_errs:
        print("\n发现问题：")
        for e in all_errs:
            print(f"  - {e}")
        return 1

    print(f"\n[OK] {len(skill_dirs)} 个 skill 全部符合规范")
    return 0


if __name__ == "__main__":
    sys.exit(main())
