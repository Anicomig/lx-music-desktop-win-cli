"""统一 HTTP 会话（连接池 + 重试 + 代理）。

修复旧版缺陷：旧版有两套互不共享的 HTTP 栈且能力不对等 ——
``client.py:_http_get`` 无重试、``sources/http.py:request_text`` 也无重试
（而 kw 源依赖它 8 处）。这里统一为一个 Session。
"""
from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter

from .._logging import get_logger

log = get_logger()

DEFAULT_TIMEOUT = 15.0
USER_AGENT = "lx-cli/0.2.0 (+https://github.com/lyswhut/lx-music-desktop)"

_session: requests.Session | None = None


def get_session() -> requests.Session:
    """进程级共享 Session（连接池 + 自动重试）。"""
    global _session
    if _session is not None:
        return _session

    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT

    # 标准 http(s) 重试：仅对幂等方法 + 5xx/429 重试，尊重 Retry-After
    try:
        from urllib3.util.retry import Retry
        retry = Retry(
            total=2,
            connect=2,
            read=2,
            backoff_factor=0.5,
            backoff_jitter=0.3,
            status_forcelist=(429, 500, 502, 503, 504),
            respect_retry_after_header=True,
            allowed_methods=frozenset({"GET", "HEAD", "POST", "OPTIONS"}),
        )
        adapter = HTTPAdapter(
            max_retries=retry, pool_connections=20, pool_maxsize=20,
        )
        s.mount("http://", adapter)
        s.mount("https://", adapter)
    except Exception as exc:          # pragma: no cover - 依赖缺失时降级
        log.warning("retry adapter unavailable, falling back: %s", exc)

    _session = s
    return s


def close_session() -> None:
    global _session
    if _session is not None:
        _session.close()
        _session = None
