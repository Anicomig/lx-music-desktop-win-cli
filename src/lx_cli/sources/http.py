"""平台接口的 HTTP 辅助（JSON 请求 + 宽容解码）。

修复旧版缺陷：旧版 ``http.py`` 的 ``request_text`` **既无重试也无 UA**，
而 kw 源有 8 处依赖它 —— 等于整个酷我源没有重试保护。
本模块的 :func:`request_text` 与 :func:`request_json` 共用同一套重试 Session
（``core/http.py``）。
"""
from __future__ import annotations

import json
import re
from typing import Any

import requests

from .._logging import get_logger
from .base import SourceError

log = get_logger()

DEFAULT_TIMEOUT = 15.0
MAX_ATTEMPTS = 3

#: 各平台常见 UA（避免被识别为爬虫）
_UA = {
    "kg": "Android712-AndroidPhone-11451-376-0-FeeCacheUpdate-wifi",
    "kw": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "tx": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "wy": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "mg": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36",
}

#: kw 的接口会返回**单引号 JSON**（非标准），需要修复
_KW_SINGLE_QUOTE = re.compile(r"(?<=[:,\[{])\s*'([^']*)'")


def _fix_kuwo_json(text: str) -> str:
    """修复酷我接口返回的单引号 JSON。

    酷我 ``search.kuwo.cn/r.s`` 返回形如 ``{'key':'value'}`` 的非标准 JSON。
    这里做**保守**替换：只把"位于 ``:``/``,``/``[``/``{`` 之后、
    由单引号包裹、内部无未转义单引号"的片段换成双引号形式。
    """
    return _KW_SINGLE_QUOTE.sub(lambda m: '"' + m.group(1) + '"', text)


def request_text(url: str, *, method: str = "GET", headers: dict | None = None,
                 data: Any = None, json_body: Any = None,
                 timeout: float = DEFAULT_TIMEOUT, platform: str = "?",
                 max_attempts: int = MAX_ATTEMPTS,
                 fix_single_quotes: bool = False,
                 referer: str | None = None) -> str:
    """带重试的文本请求。"""
    from ..core.http import get_session

    h: dict[str, str] = {}
    if platform in _UA:
        h["User-Agent"] = _UA[platform]
    if referer:
        h["Referer"] = referer
    h.update(headers or {})

    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            resp = get_session().request(
                method, url, headers=h, timeout=timeout,
                data=data if data is not None else None,
                json=json_body if json_body is not None else None,
            )
            if resp.status_code >= 400:
                raise SourceError(
                    platform, f"HTTP {resp.status_code}：{url[:120]}")
            text = resp.text
            if fix_single_quotes:
                text = _fix_kuwo_json(text)
            return text
        except SourceError:
            raise
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            log.debug("%s 请求失败（第 %d 次）：%s", platform, attempt + 1, exc)
        except Exception as exc:                       # noqa: BLE001
            last_exc = exc
            log.debug("%s 异常（第 %d 次）：%s", platform, attempt + 1, exc)

    raise SourceError(platform, f"请求失败（重试 {max_attempts} 次）：{last_exc}",
                      cause=last_exc)


def request_json(url: str, *, method: str = "GET", headers: dict | None = None,
                 data: Any = None, json_body: Any = None,
                 timeout: float = DEFAULT_TIMEOUT, platform: str = "?",
                 max_attempts: int = MAX_ATTEMPTS,
                 fix_single_quotes: bool = False,
                 referer: str | None = None) -> Any:
    """带重试的 JSON 请求。"""
    text = request_text(
        url, method=method, headers=headers, data=data, json_body=json_body,
        timeout=timeout, platform=platform, max_attempts=max_attempts,
        fix_single_quotes=fix_single_quotes, referer=referer,
    )
    text = text.strip()
    # 有些接口会包 JSONP / 前后有杂字符
    try:
        return json.loads(text)
    except ValueError:
        pass
    start = min((i for i in (text.find("{"), text.find("[")) if i >= 0),
                default=-1)
    end = max(text.rfind("}"), text.rfind("]"))
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except ValueError as exc:
            raise SourceError(
                platform, f"响应不是合法 JSON：{text[:200]!r}", cause=exc) from exc
    raise SourceError(platform, f"响应不是合法 JSON：{text[:200]!r}")
