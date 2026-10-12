#!/usr/bin/env python
"""免安装启动器（P1/P2）—— 不依赖 pip install，也不依赖当前工作目录。

用法::

    python run.py search "yorushika"
    python run.py --help
    <任意路径>/lx-cli-v2/run.py playlist list

原理：按**本文件位置**推导 ``src/`` 并加入 ``sys.path``，
因此把整个文件夹改名/搬到别处后仍然可用。
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "src"
if not SRC.is_dir():
    sys.stderr.write(
        f"lx: 找不到 src 目录：{SRC}\n"
        "     请确认 run.py 与 src/ 在同一层（本文件不要单独复制出去）。\n")
    raise SystemExit(2)

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lx_cli.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
