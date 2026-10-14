"""pytest 配置：让测试**在任何情况下**都能导入 ``lx_cli`` 与测试工具。

必要性：
* 未 ``pip install`` 时，``src/`` 不在 ``sys.path``
* pre-commit 钩子、IDE、CI 的工作目录与 env 各不相同
* 直接 ``pytest`` 不应要求先设 ``PYTHONPATH``

做法：把 ``src`` 与 ``tests`` 都插入 ``sys.path``（按本文件位置推导，
所以**换目录/改名后依然有效**）。插入 ``tests`` 是为了让
``from _version import …`` 在各测试文件里都能用。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

for sub in ("src", "tests"):
    p = ROOT / sub
    if p.is_dir() and str(p) not in sys.path:
        sys.path.insert(0, str(p))


# --------------------------------------------------------------- 版本工具

def current_version() -> str:
    """从 ``src/lx_cli/__init__.py`` 读 ``__version__``（唯一事实来源）。

    测试**不应硬编码版本号** —— v0.2.1 → v0.3.0 时曾有 5 处因此失败。
    """
    m = re.search(r'^__version__\s*=\s*"([^"]+)"',
                  (ROOT / "src" / "lx_cli" / "__init__.py")
                  .read_text(encoding="utf-8"), re.M)
    if not m:
        raise RuntimeError("无法读取 __version__")
    return m.group(1)


def version_major_minor() -> str:
    """如 ``0.3`` —— 用于"输出里应含版本前缀"这类宽松断言。"""
    parts = current_version().split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else current_version()
