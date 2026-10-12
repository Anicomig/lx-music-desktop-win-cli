"""音源仓库适配层（**声明式**，仓库变化时只改本文件）。

对应仓库：``https://github.com/pdone/lx-music-source``

⚠️ 为什么做成声明式：该仓库的结构可能变化（加/删源目录、改 ``latest.js`` 约定），
所以把"目录名 → 显示名 → 下载地址"全部放进 :data:`REPO_SOURCES` 数据里，
而不是散落在代码逻辑中。**仓库变了就改这张表。**

仓库事实【已核实 2026-10-12】：

* 布局：10 个目录，每个含版本文件 + ``latest.js``
* **``latest.js`` = 最高版本文件的物理副本**（``CreateLatest.py`` 用 ``shutil.copy2``），
  不是 symlink；10/10 目录 md5 一致
* 权威版本指针在 ``CreateLatest.py`` 的 ``VERSIONS`` 字典（**人工维护，可能滞后**）
* **不能靠 ``@version`` 判断是否需要更新** —— 实测仓库 ``lx/latest.js`` 与本机已装 v6
  内容不同但 ``@version`` 都是 6（该源会就地重新混淆）→ 必须用**内容哈希**
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .._logging import get_logger
from ..errors import ScriptDownloadError, ScriptError
from .metadata import MAX_SCRIPT_CHARS, parse_script_meta

log = get_logger()

OWNER = "pdone"
REPO = "lx-music-source"
BRANCH = "main"

#: 直链模板
RAW_TEMPLATE = "https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"

#: 国内镜像（按顺序回退）。``{url}`` 为原始直链。
MIRRORS: tuple[str, ...] = (
    "https://ghproxy.net/{url}",
    "https://gh-proxy.com/{url}",
    "https://ghfast.top/{url}",
    "https://ghproxy.cc/{url}",
    "https://mirror.ghproxy.com/{url}",
)


@dataclass(frozen=True)
class RepoSource:
    """仓库里的一个音源。"""

    key: str            # 目录名（仓库内路径）
    label: str          # 中文显示名（仅用于展示，**不是**来源标识）
    note: str = ""      # 备注


#: ★ 仓库音源清单 —— **仓库结构变化时改这里**
REPO_SOURCES: tuple[RepoSource, ...] = (
    RepoSource("sixyin", "六音音源", "体积最大，含多平台"),
    RepoSource("huibq", "Huibq 源"),
    RepoSource("flower", "野花🌷"),
    RepoSource("lx", "洛雪官方源", "JSVMP 混淆"),
    RepoSource("changqing", "长青 SVIP 音源"),
    RepoSource("huanyin", "幻音音源", "含 mg 搜索"),
    RepoSource("ikun", "ikun 音源"),
    RepoSource("grass", "野草🌾"),
    RepoSource("juhe", "聚合 API 源"),
    RepoSource("qdy", "qdy 源"),
)

#: 便捷索引
BY_KEY: dict[str, RepoSource] = {s.key: s for s in REPO_SOURCES}
#: 显示名 → key（允许用中文名指定）
BY_LABEL: dict[str, str] = {s.label: s.key for s in REPO_SOURCES}


def resolve(name: str) -> RepoSource | None:
    """把用户给的标识解析成 :class:`RepoSource`。

    支持：目录名（``flower``）、中文显示名（``野花🌷``）、
    以及含 ``latest.js`` 的完整 URL 中的目录名。
    """
    key = (name or "").strip()
    if not key:
        return None
    if key in BY_KEY:
        return BY_KEY[key]
    if key in BY_LABEL:
        return BY_KEY[BY_LABEL[key]]
    # 从 URL 里猜目录名
    for s in REPO_SOURCES:
        if f"/{s.key}/" in key or key.endswith(f"/{s.key}/latest.js"):
            return s
    return None


def raw_url(source: RepoSource | str, *, filename: str = "latest.js") -> str:
    """原始直链。"""
    key = source.key if isinstance(source, RepoSource) else source
    path = f"{key}/{filename}"
    return RAW_TEMPLATE.format(owner=OWNER, repo=REPO, branch=BRANCH, path=path)


def url_candidates(source: RepoSource | str) -> list[str]:
    """下载候选地址：直链优先，其后是各镜像。"""
    direct = raw_url(source)
    return [direct, *[m.format(url=direct) for m in MIRRORS]]


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------- 下载


def fetch_text(url: str, *, timeout: float = 30.0,
               max_redirects: int = 3) -> str:
    """下载脚本文本。

    防护（照 LX 的导入限制）：
    * 必须 ``^https?://``
    * 限制重定向次数
    * 拒绝非 UTF-8
    * 超长即报错（LX 上限 9,000,000 字符）
    * **拒绝 HTML**（镜像失效常返回 404 页面，不能当脚本存进去）
    """
    if not url.lower().startswith(("http://", "https://")):
        raise ScriptDownloadError(f"只支持 http(s) URL：{url}")

    from ..core.http import get_session
    try:
        resp = get_session().get(
            url, timeout=timeout, allow_redirects=True,
            headers={"Accept": "text/plain, application/javascript, */*"},
        )
    except Exception as exc:                        # noqa: BLE001
        raise ScriptDownloadError(f"下载失败：{url}: {exc}",
                                 detail={"url": url}, cause=exc) from exc

    if resp.status_code >= 400:
        raise ScriptDownloadError(
            f"下载失败 HTTP {resp.status_code}：{url}",
            detail={"url": url, "status": resp.status_code})

    if len(resp.history) > max_redirects:
        raise ScriptDownloadError(
            f"重定向次数过多（{len(resp.history)} > {max_redirects}）：{url}")

    try:
        text = resp.content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScriptDownloadError(
            f"内容不是 UTF-8（可能是错误页）：{url}") from exc

    head = text.lstrip()[:200].lower()
    if head.startswith("<!doctype") or head.startswith("<html"):
        raise ScriptDownloadError(
            f"下载到的是 HTML 页面而非脚本（镜像可能已失效）：{url}")

    if len(text) > MAX_SCRIPT_CHARS:
        raise ScriptDownloadError(
            f"脚本过大：{len(text):,} 字符（上限 {MAX_SCRIPT_CHARS:,}）：{url}")

    return text


def fetch_script(name: str, *, timeout: float = 30.0) -> tuple[str, str, str]:
    """按音源名下载脚本，自动回退镜像。

    :returns: ``(script_text, url_used, source_key)``
    :raises ScriptDownloadError: 全部候选都失败
    """
    src = resolve(name)
    if src is None:
        raise ScriptError(
            f"未知音源 {name!r}。可用：{', '.join(s.key for s in REPO_SOURCES)}"
            f"（或中文名：{', '.join(s.label for s in REPO_SOURCES)}）")

    errors: list[str] = []
    for url in url_candidates(src):
        try:
            text = fetch_text(url, timeout=timeout)
            # 基础校验：必须是合法脚本
            from .metadata import is_valid_script
            if not is_valid_script(text):
                errors.append(f"{url}: 内容不是合法音源脚本")
                continue
            return text, url, src.key
        except ScriptDownloadError as exc:
            errors.append(f"{url}: {exc}")
            log.debug("mirror failed: %s", exc)

    raise ScriptDownloadError(
        f"下载 {src.label}（{src.key}）失败，已尝试 {len(url_candidates(src))} 个地址：\n"
        + "\n".join(f"  - {e}" for e in errors[:5])
        + "\n可手动下载后用 --file 指定本地文件。",
        detail={"source": src.key, "tried": len(url_candidates(src))})


# --------------------------------------------------------------- 信息


def describe(source: RepoSource, *, remote_text: str | None = None) -> dict[str, Any]:
    """描述一个仓库音源（可选带远端脚本信息）。"""
    out: dict[str, Any] = {
        "key": source.key,
        "label": source.label,
        "note": source.note,
        "url": raw_url(source),
        "mirrors": len(MIRRORS),
    }
    if remote_text is not None:
        meta = parse_script_meta(remote_text)
        out["remote"] = {
            **meta.to_dict(),
            "sha256": sha256_of(remote_text),
            "chars": len(remote_text),
        }
    return out
