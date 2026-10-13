"""用直链下载音频文件。

只负责"把 URL 变成文件"，取 URL 的行为在 ``jshost``。
下载走 `requests`（与项目其它 HTTP 一致，自动读系统代理）。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .._logging import get_logger
from ..errors import LxCliError
from ..core.http import get_session

log = get_logger()

#: 常见扩展名（按 Content-Type / URL 推断）
_EXT_BY_TYPE = {
    "audio/mpeg": "mp3", "audio/mp3": "mp3",
    "audio/flac": "flac", "audio/x-flac": "flac",
    "audio/mp4": "m4a", "audio/x-m4a": "m4a",
    "audio/ogg": "ogg", "audio/wav": "wav", "audio/x-wav": "wav",
}

#: 文件名非法字符（Windows）
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class DownloadError(LxCliError):
    code = "download"


@dataclass
class DownloadResult:
    ok: bool
    path: str = ""
    bytes: int = 0
    error: str = ""

    def to_json(self) -> dict[str, Any]:
        return {"ok": self.ok, "path": self.path,
                "bytes": self.bytes, "error": self.error}


def safe_filename(name: str, ext: str = "mp3") -> str:
    """把 '歌名 - 歌手' 变成合法文件名。"""
    base = _ILLEGAL.sub("_", (name or "unknown").strip())
    base = base.rstrip(" .")                     # Windows 不允许结尾空格/点
    if len(base) > 180:
        base = base[:180]
    if not base:
        base = "unknown"
    return f"{base}.{ext.lstrip('.')}" if ext else base


def guess_ext(url: str, content_type: str = "", fallback: str = "mp3") -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in _EXT_BY_TYPE:
        return _EXT_BY_TYPE[ct]
    m = re.search(r"\.(flac|mp3|m4a|ogg|wav)(?:\?|$)", url or "", re.I)
    if m:
        return m.group(1).lower()
    return fallback


def download(url: str, dest_dir: str | Path, *, filename: str | None = None,
             ext_fallback: str = "mp3", timeout: float = 120.0,
             overwrite: bool = False, referer: str = "",
             on_progress: Callable[[int, int], None] | None = None
             ) -> DownloadResult:
    """下载 ``url`` 到 ``dest_dir``。

    :param filename: 指定文件名（不含路径）；省略则从 URL 推断
    :param overwrite: 已存在同名文件时是否覆盖
    """
    d = Path(dest_dir)
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return DownloadResult(False, error=f"无法创建目录 {d}: {exc}")

    headers = {"User-Agent": "lx-music-desktop/2.12.5"}
    if referer:
        headers["Referer"] = referer

    sess = get_session()
    try:
        with sess.get(url, headers=headers, stream=True,
                      timeout=timeout, allow_redirects=True) as resp:
            if resp.status_code != 200:
                return DownloadResult(
                    False, error=f"HTTP {resp.status_code}")
            ext = guess_ext(url, resp.headers.get("Content-Type", ""),
                            ext_fallback)
            name = filename or _name_from_url(url, ext)
            out = d / name
            if out.exists() and not overwrite:
                return DownloadResult(
                    False, path=str(out),
                    error=f"文件已存在（用 --overwrite 覆盖）：{out.name}")

            total = int(resp.headers.get("Content-Length") or 0)
            written = 0
            tmp = out.with_suffix(out.suffix + ".part")
            try:
                with tmp.open("wb") as f:
                    for chunk in resp.iter_content(chunk_size=64 * 1024):
                        if not chunk:
                            continue
                        f.write(chunk)
                        written += len(chunk)
                        if on_progress:
                            on_progress(written, total)
                # 原子替换：避免半截文件被当成完成
                if out.exists():
                    out.unlink()
                tmp.replace(out)
            except Exception:
                tmp.unlink(missing_ok=True)
                raise
            return DownloadResult(True, path=str(out), bytes=written)
    except Exception as exc:                        # noqa: BLE001
        return DownloadResult(False, error=f"{type(exc).__name__}: {exc}")


def _name_from_url(url: str, ext: str) -> str:
    tail = (url or "").split("?")[0].rsplit("/", 1)[-1]
    stem = Path(tail).stem if tail else "download"
    if not stem:
        stem = "download"
    return safe_filename(stem, ext)


def detect_audio_kind(path: str | Path) -> str:
    """读文件头判断真实格式（用于识别"假 flac"之类）。

    返回 ``flac`` / ``mp3`` / ``m4a`` / ``unknown``。
    """
    try:
        head = Path(path).open("rb").read(12)
    except OSError:
        return "unknown"
    if head[:4] == b"fLaC":
        return "flac"
    if head[:3] == b"ID3":
        return "mp3"                               # 需要再确认是否 mp3 帧
    if head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2", b"\xff\xfa"):
        return "mp3"
    if head[4:8] == b"ftyp":
        return "m4a"
    if head[:4] == b"OggS":
        return "ogg"
    return "unknown"
