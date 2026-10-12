"""从真实 ``--help`` 生成命令参考文档（保证文档与实现不漂移）。

用法::

    python scripts/gen_commands_doc.py            # 覆盖写 docs/reference/commands.md
    python scripts/gen_commands_doc.py --check     # 只校验是否与文档一致（CI 用）
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "reference" / "commands.md"
ENV = {**os.environ, "PYTHONPATH": str(ROOT / "src"),
       "PYTHONIOENCODING": "utf-8"}

HEADER = """# 命令参数参考

> **本文件由 `scripts/gen_commands_doc.py` 从真实 `--help` 自动生成，请勿手改。**
> 改代码后重新生成：`python scripts/gen_commands_doc.py`
> 校验是否过期：`python scripts/gen_commands_doc.py --check`

## 全局约定

| 项 | 说明 |
|---|---|
| 全局选项 | 需放在子命令**之前**（如 `lx --db x.db playlist list`） |
| `--json` | 每个输出命令都支持；stdout 只有 JSON，日志走 stderr |
| `-v / -vv` | 日志级别（INFO / DEBUG），走 stderr |
| 退出码 | `0` 成功 · `1` 运行时 · `2` 用法 · `3` 需关 LX · `4` 上游 |

"""


def run_help(args: list[str]) -> str:
    p = subprocess.run([sys.executable, "-m", "lx_cli", *args, "--help"],
                       capture_output=True, text=True, encoding="utf-8",
                       env=ENV, cwd=str(ROOT))
    return (p.stdout or p.stderr).rstrip()


def groups() -> list[tuple[str, list[str]]]:
    """返回 [(组名, [子命令…])]。"""
    out: list[tuple[str, list[str]]] = []
    for g in ("playlist", "script", "db"):
        p = subprocess.run([sys.executable, "-m", "lx_cli", g, "--help"],
                           capture_output=True, text=True, encoding="utf-8",
                           env=ENV, cwd=str(ROOT))
        subs = []
        in_cmds = False
        for line in (p.stdout or "").splitlines():
            if line.strip().startswith("Commands:"):
                in_cmds = True
                continue
            if in_cmds and line.startswith("  ") and line.strip():
                subs.append(line.strip().split()[0])
        out.append((g, subs))
    return out


def top_level_commands() -> list[str]:
    p = subprocess.run([sys.executable, "-m", "lx_cli", "--help"],
                       capture_output=True, text=True, encoding="utf-8",
                       env=ENV, cwd=str(ROOT))
    cmds, in_cmds = [], False
    for line in (p.stdout or "").splitlines():
        if line.strip().startswith("Commands:"):
            in_cmds = True
            continue
        if in_cmds and line.startswith("  ") and line.strip():
            cmds.append(line.strip().split()[0])
    return cmds


def build() -> str:
    parts = [HEADER]

    parts.append("---\n\n## 顶层命令\n\n```\n")
    parts.append(run_help([]))
    parts.append("\n```\n")

    parts.append("\n---\n\n## 各命令详解\n")
    for cmd in top_level_commands():
        parts.append(f"\n### `lx {cmd}`\n\n```text\n")
        parts.append(run_help([cmd]))
        parts.append("\n```\n")

    parts.append("\n---\n\n## 命令组\n")
    for g, subs in groups():
        parts.append(f"\n### `lx {g}`\n\n```text\n")
        parts.append(run_help([g]))
        parts.append("\n```\n")
        for sub in subs:
            parts.append(f"\n#### `lx {g} {sub}`\n\n```text\n")
            parts.append(run_help([g, sub]))
            parts.append("\n```\n")

    parts.append("\n---\n\n")
    parts.append(_footer())
    return "".join(parts)


def _footer() -> str:
    return """## 备注

* 上表由真实 `--help` 生成，**参数以实际运行为准**。
* 需要"机器可读 + 稳定形状"时一律加 `--json`，其 schema 见
  [`../guide/ai-usage.md`](../guide/ai-usage.md)。
* 写操作（歌单/配置/音源脚本）默认或强制要求**关闭 LX**，否则返回退出码 `3`。
"""


def main() -> int:
    # Windows 控制台默认可能是 GBK，直接 print 非 ASCII（✓ 等）会抛
    # UnicodeEncodeError。统一切到 UTF-8 并容错，避免脚本在中文环境下崩溃。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    text = build()
    check = "--check" in sys.argv
    if check:
        if not OUT.exists():
            print(f"[FAIL] 文档不存在：{OUT}")
            return 1
        if OUT.read_text(encoding="utf-8") != text:
            print("[FAIL] docs/reference/commands.md 已过期，请重新生成：")
            print("       python scripts/gen_commands_doc.py")
            return 1
        print("[OK] commands.md 与实现一致")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"[OK] 已生成 {OUT}  ({len(text):,} 字符)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
