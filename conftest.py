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

import pytest

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


# --------------------------------------------------------------- 安全护栏

def pytest_configure(config):
    """注册自定义 marker。"""
    config.addinivalue_line(
        "markers",
        "allows_apply: 明确允许测试对真实环境执行 apply（慎用）")


def pytest_collection_modifyitems(config, items):
    """★ 预防性检查：拦下"可能真的卸载/改写真实环境"的**具体用例**。

    背景（真实事故）：早期 `test_uninstall_apply_requires_yes` 会执行
    `uninstall --apply`，在非 TTY 环境下 Click 的二次确认**不会**阻止，
    结果**真的把开发机上的 lx-cli 卸载了**，还差点改写 config_v2.json。

    判定粒度是**单个用例的函数体**（不是整个文件），
    规则：该用例源码里同时出现 `uninstall` 与 `--apply`（且未加
    `@pytest.mark.allows_apply`）即视为可疑，予以跳过并打印告警。
    """
    import pathlib
    import re as _re

    skipped: list[str] = []
    for item in items:
        if item.get_closest_marker("allows_apply"):
            continue
        try:
            whole = pathlib.Path(str(item.fspath)).read_text(encoding="utf-8")
        except OSError:
            continue

        # 截取该用例自身的源码段（从 def 到下一个 def）
        name = item.name
        m = _re.search(rf"^(\s*)def {_re.escape(name)}\b.*?(?=^\1def |\Z)",
                       whole, _re.M | _re.S)
        body = m.group(0) if m else ""
        if not body:
            continue

        has_uninstall = "uninstall" in body
        has_apply = '"--apply"' in body or "'--apply'" in body
        if has_uninstall and has_apply:
            item.add_marker(pytest.mark.skip(
                reason="安全护栏：该用例同时使用 uninstall 与 --apply，"
                       "可能在真实环境执行卸载。请改用 dry-run，"
                       "或加 @pytest.mark.allows_apply 并指向临时夹具。"))
            skipped.append(item.nodeid)

    if skipped:
        print(f"\n[conftest 安全护栏] 跳过 {len(skipped)} 个可疑用例：")
        for s in skipped:
            print(f"  - {s}")
