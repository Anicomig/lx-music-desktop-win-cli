"""修正文档搬移后的失效相对引用。

把 ``docs/planning/*.md`` 里指向调研报告的引用
（``./research/0X-*.md`` 等）改为新位置 ``../internals/research/0X-*.md``。

用法::

    python scripts/fix_doc_links.py [--check]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

# 匹配 ./research/xxx.md、research/xxx.md（但跳过已带 ../internals/ 的）
RESEARCH_REF = re.compile(r"(?<!internals/)(?<![\w/])\.?/?research/([\w\-.]+\.md)")
LINK_RE = re.compile(r"\]\(([^)#\s]+?)(?:#[^)]*)?\)")


def fix_research_refs() -> list[str]:
    """把失效的 ``research/xxx.md`` 引用改成相对于本文件的正确路径。

    只处理**当前确实失效**的引用（目标不存在时才改），避免误改已正确的路径。
    """
    changed: list[str] = []
    for md in DOCS.rglob("*.md"):
        if md.parent.name == "research":
            continue                       # 调研文档自身不动

        def repl(m: re.Match) -> str:
            raw = m.group(0)
            if (md.parent / raw).exists():
                return raw                 # 已正确，别动
            target = "internals/research/" + m.group(1)
            # 计算从 md 所在目录到 docs/ 的相对前缀
            try:
                rel = md.parent.relative_to(DOCS)
            except ValueError:
                rel = Path("")
            prefix = "../" * len(rel.parts) if rel.parts else ""
            return prefix + target

        text = md.read_text(encoding="utf-8")
        new = RESEARCH_REF.sub(repl, text)
        if new != text:
            changed.append(str(md.relative_to(ROOT)))
            if "--check" not in sys.argv:
                md.write_text(new, encoding="utf-8")
    return changed


def find_broken_links() -> list[tuple[str, str]]:
    """返回 [(文件, 失效目标)]。"""
    bad: list[tuple[str, str]] = []
    for md in ROOT.rglob("*.md"):
        if "__pycache__" in md.parts or ".pytest_cache" in md.parts:
            continue
        text = md.read_text(encoding="utf-8", errors="ignore")
        # 去掉代码块，避免把 JS/示例里的括号当链接
        text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        text = re.sub(r"`[^`]*`", "", text)
        for m in LINK_RE.finditer(text):
            target = m.group(1).strip()
            if not target or target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            if any(ch in target for ch in "()[]'\"; "):
                continue                    # 疑似代码片段
            if not (md.parent / target).exists():
                bad.append((str(md.relative_to(ROOT)), target))
    return bad


def main() -> int:
    changed = fix_research_refs()
    if changed:
        verb = "需修正" if "--check" in sys.argv else "已修正"
        print(f"[{verb}] research 引用：{len(changed)} 个文件")
        for c in changed:
            print(f"  - {c}")
    else:
        print("[OK] research 引用无需修正")

    broken = find_broken_links()
    if broken:
        print(f"\n[FAIL] 发现 {len(broken)} 处失效链接：")
        for f, t in broken[:20]:
            print(f"  {f}  ->  {t}")
        return 1
    print("[OK] 无失效链接")
    return 0


if __name__ == "__main__":
    sys.exit(main())
