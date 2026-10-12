"""音源脚本元数据头解析（照 ``lx-music-desktop`` 的 ``userApi/utils.ts:53-89``）。

规则：

* 注释块必须**位于文件索引 0**（正则 ``/^\\/\\*[\\S|\\s]+?\\*\\//``），
  前面有任何字符（含 BOM、空行）都算"无效的自定义源文件"
* 逐行匹配 ``^\\s?\\*\\s?@(\\w+)\\s(.+)$``
* **白名单只有 5 个键**：``name`` ``description`` ``author`` ``homepage`` ``version``
  （其它 ``@xxx`` 静默忽略）
* 超长截断为 ``substring(0, len) + '...'``：
  name≤24、description≤36、author≤56、homepage≤1024、version≤36
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..errors import ScriptParseError

# 与 LX 一致：注释块必须在最开头
_COMMENT_BLOCK = re.compile(r"^/\*[\S\s]+?\*/")
_TAG_LINE = re.compile(r"^\s?\*\s?@(\w+)\s(.+)$", re.MULTILINE)

#: 白名单与截断长度（照 utils.ts）
TAG_LIMITS: dict[str, int] = {
    "name": 24,
    "description": 36,
    "author": 56,
    "homepage": 1024,
    "version": 36,
}

#: LX 单脚本上限（字符数）
MAX_SCRIPT_CHARS = 9_000_000
#: LX 最多音源数
MAX_SCRIPTS = 20


@dataclass
class ScriptMeta:
    name: str = ""
    description: str = ""
    author: str = ""
    homepage: str = ""
    version: str = ""
    raw_tags: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "description": self.description,
            "author": self.author,
            "homepage": self.homepage,
            "version": self.version,
        }


def _truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit] + "..."


def parse_script_meta(script: str, *, strict: bool = False) -> ScriptMeta:
    """解析脚本元数据头。

    :param strict: 为 True 时，缺少 ``/* */`` 头直接抛错（安装时用）；
                   为 False 时返回空元数据（列表展示容错用）。
    """
    if not script:
        if strict:
            raise ScriptParseError("脚本内容为空")
        return ScriptMeta()

    m = _COMMENT_BLOCK.match(script)
    if not m:
        if strict:
            raise ScriptParseError(
                "不是有效的音源脚本：文件开头必须是 /* ... */ 注释块"
                "（LX 要求注释块位于索引 0）")
        return ScriptMeta()

    block = m.group(0)
    meta = ScriptMeta()
    for key, value in _TAG_LINE.findall(block):
        k = key.lower()
        meta.raw_tags[k] = value.strip()
        if k in TAG_LIMITS:
            setattr(meta, k, _truncate(value.strip(), TAG_LIMITS[k]))

    if not meta.name and strict:
        meta.name = "未命名音源"
    return meta


def is_valid_script(script: str) -> bool:
    """是否为合法音源脚本（有头部注释块且在索引 0）。"""
    if not script or len(script) > MAX_SCRIPT_CHARS:
        return False
    return _COMMENT_BLOCK.match(script) is not None


def validate_script_size(script: str) -> None:
    if len(script) > MAX_SCRIPT_CHARS:
        raise ScriptParseError(
            f"脚本过大：{len(script):,} 字符（LX 上限 {MAX_SCRIPT_CHARS:,}）")
