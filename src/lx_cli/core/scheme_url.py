"""Scheme URL 客户端（``lxmusic://``）—— 补足 Open API 缺失的能力。

官方文档：https://lxmusic.toside.cn/desktop/scheme-url
参考实现：``LX Music 辅助脚本`` 的 ``openApp()``::

    href = `lxmusic://${type}/${action}?data=${encodeURIComponent(JSON.stringify(data))}`

**为什么需要它**：Open API 只能控制"当前播放状态"，无法：
* 播放**指定**歌曲
* 搜索并播放
* 打开/播放歌单
* 标记"不喜欢"

Scheme URL 提供了这些，但对**单向**调用（无返回值）。

**单实例机制**（``src/main/app.ts:83-105``）：LX 已在运行时，新的
``lxmusic://`` 调用会走 ``second-instance`` 分支被转交给现有实例，
**不会**抢占窗口焦点。

**实测**（2026-10-12）：LX 关闭状态下
``Start-Process "lxmusic://player/togglePlay"`` 成功冷启动 LX 并开始播放。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any

from .._logging import get_logger
from ..errors import LxCliError, PathError
from ..paths import default_exe_path

log = get_logger()

SCHEME = "lxmusic"

#: 官方允许的源（Scheme URL 文档）
SCHEME_SOURCES = ("kw", "kg", "tx", "wy", "mg")

#: 官方允许的音质
SCHEME_QUALITIES = ("128k", "320k", "flac", "flac24bit")


class SchemeError(LxCliError):
    code = "scheme"


def build_url(path: str, data: dict[str, Any] | None = None) -> str:
    """构造 ``lxmusic://`` URL。

    :param path: 形如 ``"music/play"``、``"player/togglePlay"``
    :param data: 需要 JSON+URL 编码的参数；None 则走简式 URL

    >>> build_url("player/skipNext")
    'lxmusic://player/skipNext'
    >>> build_url("music/search", {"keywords": "测试"})
    'lxmusic://music/search?data=%7B%22keywords%22%3A%20%22...'
    """
    base = f"{SCHEME}://{path}"
    if not data:
        return base
    encoded = urllib.parse.quote(json.dumps(data, ensure_ascii=False), safe="")
    return f"{base}?data={encoded}"


def parse_url(url: str) -> dict[str, Any]:
    """解析 ``lxmusic://`` URL（便于测试与调试）。"""
    if not url.startswith(f"{SCHEME}://"):
        raise SchemeError(f"不是 lxmusic:// URL: {url!r}")
    rest = url[len(SCHEME) + 3:]
    path, _, query = rest.partition("?")
    data: dict[str, Any] | None = None
    if query:
        qs = urllib.parse.parse_qs(query)
        if "data" in qs:
            try:
                data = json.loads(qs["data"][0])
            except ValueError as exc:
                raise SchemeError(f"data 参数不是合法 JSON: {exc}") from exc
    return {"path": path, "data": data}


# ------------------------------------------------------------------ 派发


def dispatch(url: str, *, exe_path: Path | None = None,
             wait: bool = False, wait_timeout: float = 30.0) -> None:
    """把 Scheme URL 交给 LX（必要时冷启动）。

    :param wait: 为 True 时等待 Open API 就绪（用于"发完要读状态"的场景）
    """
    if not url.startswith(f"{SCHEME}://"):
        raise SchemeError(f"不是 lxmusic:// URL: {url!r}")

    log.debug("dispatch scheme: %s", url[:160])
    try:
        if sys.platform == "win32":
            # 优先走 shell 关联（注册表已确认指向 LX exe）
            subprocess.Popen(["cmd", "/c", "start", "", url],
                             shell=False,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", url],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(["xdg-open", url],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
    except OSError as exc:
        raise SchemeError(f"无法派发 Scheme URL（{url}）：{exc}",
                          detail={"url": url}, cause=exc) from exc

    if wait:
        from .openapi_client import endpoints_from_config, wait_ready
        wait_ready(endpoints_from_config(exe_path), timeout=wait_timeout)


def dispatch_and_confirm(url: str, *, exe_path: Path | None = None,
                         timeout: float = 10.0, poll: float = 0.6) -> bool:
    """派发并等待"有反应"。

    ⚠️ Scheme URL **没有返回值**，且状态变更**非同步**
    （实测：``/play`` 后立即读 ``/status`` 仍可能是旧值，约 1s 后才变）。
    所以这里只做"Open API 可达"确认，**不**断言状态已按预期改变。
    """
    from .openapi_client import endpoints_from_config, get_status, OpenApiDisabled
    dispatch(url, exe_path=exe_path)
    ep = endpoints_from_config(exe_path)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            get_status(ep, timeout=2.0)
            return True
        except OpenApiDisabled:
            time.sleep(poll)
        except Exception:
            time.sleep(poll)
    return False


# ------------------------------------------------------------------ 高层封装


def play_song(*, name: str, singer: str, source: str, songmid: str,
              types: list[dict], hash_: str | None = None,
              img: str | None = None, album_id: str | None = None,
              album_name: str | None = None, interval: str | None = None,
              str_media_mid: str | None = None,
              album_mid: str | None = None,
              copyright_id: str | None = None,
              exe_path: Path | None = None) -> str:
    """播放**指定歌曲**（``music/play``）—— Open API 做不到的能力。

    必传：``name`` ``singer`` ``source`` ``songmid`` ``types``
    平台特定：kg 需 ``hash_``；tx 需 ``str_media_mid``；mg 需 ``copyright_id``

    返回派发出去的 URL（便于 `--json` 回显与调试）。
    """
    if source not in SCHEME_SOURCES:
        raise SchemeError(f"不支持的 source: {source!r}（可用 {SCHEME_SOURCES}）")
    if not types:
        raise SchemeError("types 不能为空（歌曲可用音质数组）")
    if source == "kg" and not hash_:
        raise SchemeError("kg 源播放必须提供 hash")
    if source == "tx" and not str_media_mid:
        raise SchemeError("tx 源播放必须提供 strMediaMid")
    if source == "mg" and not copyright_id:
        raise SchemeError("mg 源播放必须提供 copyrightId")

    data: dict[str, Any] = {
        "name": name, "singer": singer, "source": source,
        "songmid": songmid, "types": types,
    }
    for key, val in (("hash", hash_), ("img", img), ("albumId", album_id),
                     ("albumName", album_name), ("interval", interval),
                     ("strMediaMid", str_media_mid), ("albumMid", album_mid),
                     ("copyrightId", copyright_id)):
        if val not in (None, ""):
            data[key] = val

    url = build_url("music/play", data)
    dispatch(url, exe_path=exe_path)
    return url


def search_play(*, name: str, singer: str | None = None,
                album_name: str | None = None, interval: str | None = None,
                play_later: bool = False,
                exe_path: Path | None = None) -> str:
    """搜索并播放（``music/searchPlay``）—— 模糊匹配，无需 songmid。"""
    data: dict[str, Any] = {"name": name}
    if singer:
        data["singer"] = singer
    if album_name:
        data["albumName"] = album_name
    if interval:
        data["interval"] = interval
    if play_later:
        data["playLater"] = True
    url = build_url("music/searchPlay", data)
    dispatch(url, exe_path=exe_path)
    return url


def open_songlist(*, source: str, list_id: str | None = None,
                  url_: str | None = None,
                  exe_path: Path | None = None) -> str:
    """打开歌单（``songlist/open``）。``list_id`` 与 ``url_`` 二选一。"""
    if bool(list_id) == bool(url_):
        raise SchemeError("list_id 与 url 必须且只能提供一个")
    data: dict[str, Any] = {"source": source}
    if list_id:
        data["id"] = list_id
    else:
        data["url"] = url_
    u = build_url("songlist/open", data)
    dispatch(u, exe_path=exe_path)
    return u


def play_songlist(*, source: str, list_id: str | None = None,
                  url_: str | None = None, index: int | None = None,
                  exe_path: Path | None = None) -> str:
    """播放歌单（``songlist/play``）。``index`` 从 0 开始。"""
    if bool(list_id) == bool(url_):
        raise SchemeError("list_id 与 url 必须且只能提供一个")
    data: dict[str, Any] = {"source": source}
    if list_id:
        data["id"] = list_id
    else:
        data["url"] = url_
    if index is not None:
        data["index"] = index
    u = build_url("songlist/play", data)
    dispatch(u, exe_path=exe_path)
    return u


def simple(player_action: str, *, exe_path: Path | None = None) -> str:
    """简式控制：``player/play|pause|skipNext|skipPrev|togglePlay|collect|uncollect|dislike``。"""
    allowed = {"play", "pause", "skipNext", "skipPrev", "togglePlay",
               "collect", "uncollect", "dislike"}
    if player_action not in allowed:
        raise SchemeError(f"不支持的动作 {player_action!r}（可用 {sorted(allowed)}）")
    url = build_url(f"player/{player_action}")
    dispatch(url, exe_path=exe_path)
    return url
