"""Open API 客户端（播放控制 / 状态 / 歌词）。

端点来自官方文档 + ``lx-music-desktop-2.12.5/src/main/modules/openApi/index.ts``：

    GET /status                    播放器状态（JSON，可 filter）
    GET /lyric                     当前 LRC 文本
    GET /lyric-all                 {lyric,tlyric,rlyric,lxlyric}
    GET /play /pause /skip-next /skip-prev
    GET /seek?offset=<sec>         0 <= offset <= duration
    GET /collect /uncollect        仅作用于**当前播放曲**
    GET /volume?volume=<1-100>
    GET /mute?mute=<true|false>
    GET /subscribe-player-status   SSE

⚠️ 重要：``status`` 是**字符串**（``playing``/``paused``/``error``/``stoped``），
**不是布尔**。旧版 CLI 用 ``if st.get("status")`` 判断，导致 ``lx toggle`` 永远只暂停。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import requests

from .._logging import get_logger
from ..errors import (
    OpenApiBadRequest, OpenApiDisabled, OpenApiError, OpenApiServerError,
    OpenApiTimeout, PathError,
)
from ..paths import config_v2_path

log = get_logger()

#: 官方文档定义的 status 取值（``stoped`` 是 LX 自己的拼写，勿"修正"）
STATUS_PLAYING = "playing"
STATUS_PAUSED = "paused"
STATUS_ERROR = "error"
STATUS_STOPPED = "stoped"


@dataclass(frozen=True)
class Endpoints:
    base: str
    enabled: bool
    port: str
    bind_lan: bool

    def url(self, path: str) -> str:
        return f"{self.base}{path}"


def read_open_api_settings(exe_path: Path | None = None) -> dict[str, Any]:
    """读 ``config_v2.json`` 的开放 API 设置。

    ⚠️ ``setting`` 里的键是**扁平点号形式**（``openAPI.enable``），
    不是嵌套对象 ``{"openAPI": {"enable": ...}}``。
    """
    from .config_store import load_config          # 局部导入避免环
    cfg = load_config(exe_path)
    return {
        "enable": bool(cfg.get("openAPI.enable", False)),
        "port": str(cfg.get("openAPI.port") or "23330"),
        "bindLan": bool(cfg.get("openAPI.bindLan", False)),
    }


def endpoints_from_config(exe_path: Path | None = None) -> Endpoints:
    """从 config_v2.json 推导 Open API 端点。

    ⚠️ **连接目标 host 永远固定为 127.0.0.1**：
    0.0.0.0 是"监听所有网卡"的通配符，**只能用于服务器监听**，
    不能作为客户端连接目标（连它会报 ``WinError 10049 / 无效地址``）。
    即便 ``bindLan=true`` 让 LX 监听在 0.0.0.0，本机用 127.0.0.1 仍能连上；
    跨机访问才需要 LAN IP（不在本 CLI 职责范围）。
    """
    s = read_open_api_settings(exe_path)
    host = "127.0.0.1"
    return Endpoints(
        base=f"http://{host}:{s['port']}",
        enabled=s["enable"],
        port=s["port"],
        bind_lan=s["bindLan"],
    )


# --------------------------------------------------------------- 传输


def _local_session() -> requests.Session:
    """专用于本机 Open API 的会话。

    ⚠️ **必须绕过系统代理**：LX 开放 API 监听在 127.0.0.1（本机），
    而 Windows 上 ``requests`` 会自动读取"Internet 设置"里的系统代理
    （如 Clash / v2rayN 的 127.0.0.1:7890），把本机请求发到代理 → 502。
    全局会话（搜索用）仍需代理访问外网，故这里单独建一个绕过代理的会话。

    强制分工：**本机端点永远绕过代理，外网搜索始终走代理**。
    改回共享会话会导致这两类互相干扰。
    """
    s = requests.Session()
    s.trust_env = False
    s.headers["User-Agent"] = "lx-cli/0.2.0"
    try:
        from urllib3.util.retry import Retry
        retry = Retry(
            total=2, connect=2, read=2, backoff_factor=0.5,
            backoff_jitter=0.3,
            status_forcelist=(429, 500, 502, 503, 504),
            respect_retry_after_header=True,
            allowed_methods=frozenset({"GET", "HEAD", "POST", "OPTIONS"}),
        )
        from requests.adapters import HTTPAdapter
        adapter = HTTPAdapter(max_retries=retry,
                              pool_connections=10, pool_maxsize=10)
        s.mount("http://", adapter)
        s.mount("https://", adapter)
    except Exception:
        pass
    return s


def _get(ep: Endpoints, path: str, *, timeout: float = 5.0,
         params: dict | None = None) -> requests.Response:
    """单次 GET，把 HTTP 层异常翻译成我们的异常树。

    使用 ``_local_session()``（绕过系统代理），见该函数说明。
    """
    url = ep.url(path)
    try:
        resp = _local_session().get(url, timeout=timeout, params=params)
    except requests.exceptions.ConnectionError as exc:
        raise OpenApiDisabled(
            f"无法连接开放 API（{url}）。\n"
            "可能原因：LX 未运行，或「设置 → 开放 API 服务」未启用。\n"
            "启用后可运行 `lx config enable` 并重启 LX。",
            detail={"url": url}, cause=exc,
        ) from exc
    except requests.exceptions.Timeout as exc:
        raise OpenApiTimeout(f"请求超时：{url}", detail={"url": url}, cause=exc) from exc
    except requests.exceptions.RequestException as exc:
        raise OpenApiError(f"请求失败：{url}: {exc}", detail={"url": url}, cause=exc) from exc

    if resp.status_code == 401:
        raise OpenApiDisabled(
            f"开放 API 返回 401（{url}）—— 服务未启用或路径不可用。",
            detail={"url": url, "status": 401},
        )
    if resp.status_code >= 500:
        raise OpenApiServerError(
            f"开放 API 服务错误 {resp.status_code}：{resp.text[:200]}",
            detail={"url": url, "status": resp.status_code},
        )
    if resp.status_code >= 400:
        raise OpenApiBadRequest(
            f"开放 API 请求错误 {resp.status_code}：{resp.text[:200]}",
            detail={"url": url, "status": resp.status_code},
        )
    return resp


def _get_text(ep: Endpoints, path: str, *, timeout: float = 5.0,
              params: dict | None = None) -> str:
    return _get(ep, path, timeout=timeout, params=params).text


def _get_json(ep: Endpoints, path: str, *, timeout: float = 5.0,
              params: dict | None = None) -> Any:
    text = _get_text(ep, path, timeout=timeout, params=params)
    try:
        return json.loads(text)
    except ValueError as exc:
        raise OpenApiError(f"开放 API 返回非 JSON：{text[:200]!r}",
                           detail={"path": path}, cause=exc) from exc


# --------------------------------------------------------------- 只读


def get_status(ep: Endpoints, filter_keys: list[str] | None = None,
               *, timeout: float = 5.0) -> dict[str, Any]:
    """取播放器状态。

    :param filter_keys: 仅返回这些字段（对应官方 ``filter`` 参数）
    """
    params = {"filter": ",".join(filter_keys)} if filter_keys else None
    data = _get_json(ep, "/status", timeout=timeout, params=params)
    if not isinstance(data, dict):
        raise OpenApiError(f"/status 返回非对象：{type(data).__name__}")
    return data


def is_playing(status: dict[str, Any] | None) -> bool:
    """**正确**判断是否正在播放 —— 旧版把字符串当布尔，是 bug。"""
    return bool(status) and status.get("status") == STATUS_PLAYING


def get_lyric(ep: Endpoints, *, timeout: float = 5.0) -> str:
    return _get_text(ep, "/lyric", timeout=timeout)


def get_lyric_all(ep: Endpoints, *, timeout: float = 5.0) -> dict[str, Any]:
    data = _get_json(ep, "/lyric-all", timeout=timeout)
    return data if isinstance(data, dict) else {}


# --------------------------------------------------------------- 控制


def play(ep: Endpoints) -> None:
    _get(ep, "/play")


def pause(ep: Endpoints) -> None:
    _get(ep, "/pause")


def skip_next(ep: Endpoints) -> None:
    _get(ep, "/skip-next")


def skip_prev(ep: Endpoints) -> None:
    _get(ep, "/skip-prev")


def toggle(ep: Endpoints) -> str:
    """按**字符串**状态正确切换，返回实际执行的动作。

    修复旧版 bug：旧版 ``if st.get("status")`` 把 ``"paused"`` 也当真值。
    """
    st = get_status(ep)
    if is_playing(st):
        pause(ep)
        return "pause"
    play(ep)
    return "play"


def seek(ep: Endpoints, offset: float) -> None:
    _get(ep, "/seek", params={"offset": offset})


def set_volume(ep: Endpoints, volume: int) -> None:
    if not 0 <= volume <= 100:
        raise OpenApiBadRequest(f"音量必须在 0-100，收到 {volume}",
                                detail={"volume": volume})
    _get(ep, "/volume", params={"volume": volume})


def set_mute(ep: Endpoints, mute: bool) -> None:
    _get(ep, "/mute", params={"mute": "true" if mute else "false"})


def collect(ep: Endpoints) -> None:
    _get(ep, "/collect")


def uncollect(ep: Endpoints) -> None:
    _get(ep, "/uncollect")


# --------------------------------------------------------------- 就绪等待


def wait_ready(ep: Endpoints, *, timeout: float = 30.0,
               poll: float = 0.5) -> None:
    """轮询直到开放 API 可用。

    区分"还没起来"（继续等）与"起来了但服务没开"（立即抛）。
    """
    import time
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            get_status(ep, timeout=min(3.0, poll + 2.0))
            return
        except OpenApiDisabled as exc:
            # 端口通了但服务没启用（401）→ 不必再等
            if "401" in (exc.message or ""):
                raise
            last = exc
        except (OpenApiTimeout, OpenApiServerError) as exc:
            last = exc
        time.sleep(poll)
    raise OpenApiTimeout(
        f"开放 API 在 {timeout}s 内未就绪" + (f"：{last}" if last else ""),
        detail={"timeout": timeout},
    )


# --------------------------------------------------------------- SSE


def subscribe_player_status(ep: Endpoints, filter_keys: list[str] | None = None,
                            *, idle_timeout: float = 30.0
                            ) -> Iterator[dict[str, Any]]:
    """订阅播放器状态（SSE），逐条 yield ``{event, data}``。

    ``idle_timeout`` 秒内无事件则结束。
    """
    params = {"filter": ",".join(filter_keys)} if filter_keys else None
    url = ep.url("/subscribe-player-status")
    try:
        resp = _local_session().get(url, params=params, stream=True, timeout=None)
        resp.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise OpenApiError(f"SSE 连接失败：{url}: {exc}",
                           detail={"url": url}, cause=exc) from exc

    import time
    event = None
    last = time.monotonic()
    try:
        for raw in resp.iter_lines(decode_unicode=True):
            if time.monotonic() - last > idle_timeout:
                break
            if raw is None:
                continue
            line = raw.strip()
            if not line:
                event = None
                continue
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                payload = line[5:].strip()
                try:
                    dec = json.loads(payload)
                except ValueError:
                    dec = payload
                last = time.monotonic()
                yield {"event": event, "data": dec}
    finally:
        resp.close()
