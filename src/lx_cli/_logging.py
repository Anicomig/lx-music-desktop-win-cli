"""结构化日志。

修复旧版缺陷：旧版全用 ``print()``，且 **stdout 被日志污染** 会破坏 ``--json`` 契约
（AI 消费方无法解析）。这里强制：

* 日志一律走 **stderr**
* 默认级别 WARNING；``-v`` INFO；``-vv`` DEBUG
* 提供 :func:`get_logger` 给各模块使用
"""
from __future__ import annotations

import logging
import sys

LOGGER_NAME = "lx_cli"

_configured = False


def setup_logging(verbosity: int = 0, *, stream=None) -> logging.Logger:
    """按 verbosity 配置根 logger（幂等）。

    :param verbosity: 0=WARNING, 1=INFO, >=2=DEBUG
    :param stream: 默认 stderr —— **绝不能用 stdout**，否则污染 --json 输出
    """
    global _configured
    logger = logging.getLogger(LOGGER_NAME)
    level = (logging.WARNING, logging.INFO, logging.DEBUG)[min(verbosity, 2)]
    logger.setLevel(level)

    if not _configured:
        handler = logging.StreamHandler(stream or sys.stderr)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S",
        ))
        logger.addHandler(handler)
        logger.propagate = False
        _configured = True

    return logger


def get_logger() -> logging.Logger:
    """取得 lx_cli logger（模块级使用）。"""
    return logging.getLogger(LOGGER_NAME)
