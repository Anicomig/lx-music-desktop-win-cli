"""① 平台元数据接口（sources/）。

⚠️ 术语（见 ``lx-cli-v2/docs/CONVENTIONS.md``）：

* **本包 = 平台"元数据"接口**，直连各平台**官方域名**
  （`songsearch.kugou.com` / `search.kuwo.cn` / `u.y.qq.com` /
  `music.163.com` / `jadeite.migu.cn`），实现源自
  ``lx-music-desktop-2.12.5/src/renderer/utils/musicSdk/<platform>/``
* **不是** JS 音源脚本（那些在 ``lx_cli.scripts`` 里，只管安装/更新）
* **不提供**取播放 URL —— 那是 JS 音源脚本的唯一职责，由 LX 自己完成

对外只暴露 :func:`get_source` / :func:`list_sources` / :func:`search`。
"""
from __future__ import annotations

from .base import (
    PLATFORMS, AlbumInfo, Comment, HotKeyword, LeaderboardEntry,
    PlatformSource, SearchResult, SourceError, SongRecord,
)

#: 注册表：platform id → 实例
REGISTRY: dict[str, PlatformSource] = {}


def _register(instance: PlatformSource) -> PlatformSource:
    REGISTRY[instance.platform] = instance
    return instance


def get_source(platform: str) -> PlatformSource:
    """按平台 id 取查询实现。"""
    src = REGISTRY.get(platform)
    if src is None:
        valid = ", ".join(sorted(REGISTRY))
        raise SourceError(platform, f"未知平台 {platform!r}（可用：{valid}）")
    return src


def list_sources() -> dict[str, PlatformSource]:
    return dict(REGISTRY)


def list_platforms() -> list[str]:
    return sorted(REGISTRY)


def available_features() -> dict[str, set[str]]:
    return {pid: set(s.features) for pid, s in REGISTRY.items()}


# 各平台模块在导入时自注册（顺序无关）
from . import kg  # noqa: E402,F401
from . import kw  # noqa: E402,F401
from . import mg  # noqa: E402,F401
from . import tx  # noqa: E402,F401
from . import wy  # noqa: E402,F401
