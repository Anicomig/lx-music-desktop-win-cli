"""下载模块（P3：借 JS 音源脚本取直链并下载）。

⚠️ 模块职责边界：
  * ``jshost``  —— 执行 JS 音源脚本取播放地址（Node sidecar）
  * ``fetcher`` —— 用取到的直链做 HTTP 下载
  * 只读查询仍在 ``core.db_reader``
"""
from .jshost import (
    JsHostError, JsResult, NodeNotFoundError, doctor_report, fetch_url,
    find_node, host_script, node_available,
)

__all__ = [
    "JsHostError", "JsResult", "NodeNotFoundError", "doctor_report",
    "fetch_url", "find_node", "host_script", "node_available",
]
