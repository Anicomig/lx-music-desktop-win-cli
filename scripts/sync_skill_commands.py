"""把 docs/reference/commands.md 同步到 skills/lx-cli/references/。

为什么需要同步：skill 目录是给 AI 加载的独立副本，commands.md 必须与 CLI
保持一致（否则 AI 拿到过期命令）。

⚠️ 副本里的相对链接会错位：
   docs/reference/commands.md 里的 `../guide/ai-usage.md`
   在 skills/lx-cli/references/ 下会解析成 skills/lx-cli/guide/ai-usage.md（不存在）。
   所以同步时要改写为指向 CLI 包内文档的真实相对路径。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "reference" / "commands.md"
DST = ROOT / "skills" / "lx-cli" / "references" / "commands.md"

# 从 skills/lx-cli/references/ 回到 cli-root 需要 **3 级**（references→lx-cli→
# skills→lx-cli-v2），所以是 ../../../docs/…，不是 4 级。
FIXES = {
    "../guide/": "../../../docs/guide/",
    "../internals/": "../../../docs/internals/",
    "../reference/": "../../../docs/reference/",
}


def main() -> int:
    if not SRC.is_file():
        print(f"[FAIL] 缺少源文件: {SRC}")
        return 1
    text = SRC.read_text(encoding="utf-8")
    for old, new in FIXES.items():
        text = text.replace(old, new)
    DST.parent.mkdir(parents=True, exist_ok=True)
    DST.write_text(text, encoding="utf-8")
    print(f"[OK] 已同步 {SRC.relative_to(ROOT)} -> {DST.relative_to(ROOT)}"
          f"  ({len(text):,} 字符)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
