"""Node sidecar 管理 —— 执行 LX 的 JS 音源脚本取播放地址。

★ 资源管理（用户明确要求"不用时要释放"）：
  * **一次性进程**：每次调用启动 Node，取到结果后进程自行退出
  * **绝不常驻**：不保留 daemon
  * **超时强杀**：``subprocess.run(timeout=…)`` + ``finally`` 兜底 kill
  * **内存上限**：``--max-old-space-size=256``
  * **异常兜底**：任何路径（成功/失败/超时/KeyboardInterrupt）都终止子进程
  * **不写临时文件**：脚本源码通过临时文件传入（用完即删）

⚠️ 安全说明：Node 的 ``vm`` **不是安全沙箱**（脚本理论上可经原型链逃逸）。
本模块只做到"限制能力"（宿主内不暴露 fs/child_process/net），
**请只运行你信任的音源脚本**。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .._logging import get_logger
from ..errors import LxCliError

log = get_logger()

#: 单次调用超时（秒）
DEFAULT_TIMEOUT = 30.0
#: Node 堆上限（MB）——留余量给 C++ 堆，峰值仍远低于 300MB
NODE_MAX_OLD_SPACE = 256


class JsHostError(LxCliError):
    """JS 宿主相关错误。"""

    code = "jshost"


class NodeNotFoundError(JsHostError):
    code = "node_missing"


@dataclass
class JsResult:
    ok: bool
    url: str = ""
    source: str = ""
    quality: str = ""
    elapsed_ms: int = 0
    error: str = ""
    stage: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "ok": self.ok, "url": self.url, "source": self.source,
            "quality": self.quality, "elapsedMs": self.elapsed_ms,
            "error": self.error, "stage": self.stage,
        }


def find_node() -> tuple[Path | None, str]:
    """定位 Node 可执行文件。

    顺序：
      1. 环境变量 ``LX_NODE``
      2. 随包内置的 ``tools/node/node.exe``（便携版）
      3. 系统 PATH
    """
    env = os.environ.get("LX_NODE")
    if env:
        p = Path(env)
        if p.is_file():
            return p, "env:LX_NODE"
        return None, f"env:LX_NODE 指向的文件不存在：{p}"

    bundled = host_script().parent / "node" / (
        "node.exe" if os.name == "nt" else "node")
    if bundled.is_file():
        return bundled, "bundled"

    on_path = shutil.which("node")
    if on_path:
        return Path(on_path), "PATH"
    return None, "not found"


def host_script() -> Path:
    """``tools/lx-script-host.js`` 的路径（按包位置推导，搬家仍可用）。"""
    # 本文件在 <root>/src/lx_cli/download/jshost.py
    here = Path(__file__).resolve()
    root = here.parent.parent.parent.parent      # -> <root>
    return root / "tools" / "lx-script-host.js"


def node_available() -> bool:
    node, _ = find_node()
    return node is not None and host_script().is_file()


def _build_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def fetch_url(script_source: str, *, source: str, songmid: str,
              quality: str = "", script_name: str = "",
              timeout: float = DEFAULT_TIMEOUT,
              node: Path | None = None) -> JsResult:
    """执行脚本取播放直链。

    :param script_source: 脚本源码（明文）
    :param source: 平台标识 kg/kw/tx/wy/mg
    :param songmid: 平台歌曲 id
    :param quality: 期望音质（空则由脚本选）
    :param timeout: 超时秒数（到点强杀）
    """
    node_path, how = find_node() if node is None else (node, "explicit")
    if node_path is None:
        raise NodeNotFoundError(
            "未找到 Node 运行时。\n"
            "  • 便携版应位于 <cli-root>/tools/node/node.exe\n"
            "  • 或安装 Node 后确保在 PATH 中\n"
            "  • 也可用环境变量 LX_NODE 指定完整路径",
            detail={"searched": how})

    hs = host_script()
    if not hs.is_file():
        raise JsHostError(f"缺少宿主脚本：{hs}", detail={"path": str(hs)})

    # 脚本源码写入临时文件（Node 需要文件路径）
    tmp_fd, tmp_name = tempfile.mkstemp(prefix="lxjs_", suffix=".js")
    os.close(tmp_fd)
    tmp_path = Path(tmp_name)
    proc: subprocess.Popen | None = None
    try:
        tmp_path.write_text(script_source, encoding="utf-8")

        cmd = [
            str(node_path),
            f"--max-old-space-size={NODE_MAX_OLD_SPACE}",
            str(hs),
            "--script", str(tmp_path),
            "--source", source,
            "--id", str(songmid),
            "--timeout", str(int(timeout * 1000)),
        ]
        if quality:
            cmd += ["--quality", quality]
        if script_name:
            cmd += ["--name", script_name]

        log.debug("jshost: %s", " ".join(cmd[:3]) + " …")
        # ★ 关键：用 asyncio 之外的最简单方式 —— run + timeout
        #   timeout 到点 subprocess 会 kill 子进程并抛 TimeoutExpired
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            env=_build_env(),
            creationflags=(subprocess.CREATE_NO_WINDOW
                           if os.name == "nt" else 0),
        )
        try:
            out, err = proc.communicate(timeout=timeout + 5)
        except subprocess.TimeoutExpired:
            _kill(proc)
            return JsResult(ok=False, error=f"超时（>{timeout:.0f}s）",
                            stage="timeout")

        line = _last_json_line(out or "")
        if line is None:
            msg = (err or out or "").strip().splitlines()
            tail = msg[-1] if msg else "无输出"
            return JsResult(ok=False, error=f"宿主无有效输出：{tail[:200]}",
                            stage="host")
        try:
            data = json.loads(line)
        except ValueError:
            return JsResult(ok=False, error=f"输出非 JSON：{line[:200]}",
                            stage="host")

        return JsResult(
            ok=bool(data.get("ok")),
            url=str(data.get("url") or ""),
            source=str(data.get("source") or source),
            quality=str(data.get("quality") or quality),
            elapsed_ms=int(data.get("elapsedMs") or 0),
            error=str(data.get("error") or ""),
            stage=str(data.get("stage") or ""),
        )
    finally:
        # ★ 无论成功/失败/异常/KeyboardInterrupt，都确保：
        #   1) 子进程已终止  2) 临时脚本已删除
        if proc is not None and proc.poll() is None:
            _kill(proc)
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _kill(proc: subprocess.Popen) -> None:
    """尽力终止子进程（含 Windows 上的子进程树）。"""
    try:
        proc.kill()
    except Exception:                               # noqa: BLE001
        pass
    try:
        proc.wait(timeout=5)
    except Exception:                               # noqa: BLE001
        pass


def _last_json_line(text: str) -> str | None:
    """取最后一个像 JSON 对象的行（脚本可能往 stdout 打印日志）。"""
    for line in reversed((text or "").splitlines()):
        s = line.strip()
        if s.startswith("{") and s.endswith("}"):
            return s
    return None


def doctor_report() -> dict[str, Any]:
    """给 ``lx doctor`` 用：报告 Node 宿主的可用性。"""
    node, how = find_node()
    hs = host_script()
    return {
        "node": str(node) if node else "",
        "nodeSource": how,
        "hostScript": str(hs),
        "hostScriptExists": hs.is_file(),
        "available": bool(node) and hs.is_file(),
        "bundled": how == "bundled",
    }
