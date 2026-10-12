"""pytest 配置：让测试**在任何情况下**都能导入 ``lx_cli``。

必要性：
* 未 ``pip install`` 时，``src/`` 不在 ``sys.path``
* pre-commit 钩子、IDE、CI 的工作目录与 env 各不相同
* 直接 ``pytest`` 不应要求先设 ``PYTHONPATH``

做法：把项目根的 ``src`` 插入 ``sys.path``（按本文件位置推导，
所以**换目录/改名后依然有效**）。
"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
