"""批量下载：整个歌单 / 失败曲集合。

与 ``download get``（单曲）共用同一套 JS 音源宿主，
但增加：并发控制、进度报告、失败汇总、断点跳过、清单导出。

★ 资源管理：一次批量任务**只启动一个** Node 宿主进程不行 ——
  宿主是一次性的（取完一个 URL 就退出）。所以批量时是"多次一次性调用"，
  每次调用之间**没有常驻进程**。这是刻意的：宁可慢一点，也不要泄漏。

设计要点：
  * 默认 **预演**（``dry_run=True``），加 ``--apply`` 才真下
  * 已存在且大小正常的文件**跳过**（``skip_existing``）
  * 单曲失败**不中断**整批，最后汇总
  * 完成后输出清单（可 ``--report <path>`` 存 JSON）
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from .._logging import get_logger
from ..core import db_reader
from ..core.musicinfo import parse_song_id
from ..errors import UsageError
from . import fetcher, jshost

log = get_logger()

#: 两次取链之间的间隔（秒）——避免触发平台限流
RATE_DELAY = 0.35


@dataclass
class BatchItem:
    """批量任务里的单曲。"""
    name: str
    singer: str
    source: str
    songmid: str
    quality: str = "320k"
    list_id: str = ""
    list_name: str = ""
    reason: str = ""                     # 若来自失败清单，记录原失败原因

    # 结果
    ok: bool = False
    skipped: bool = False
    path: str = ""
    bytes: int = 0
    detected: str = ""
    error: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name, "singer": self.singer, "source": self.source,
            "songmid": self.songmid, "quality": self.quality,
            "listId": self.list_id, "listName": self.list_name,
            "reason": self.reason, "ok": self.ok, "skipped": self.skipped,
            "path": self.path, "bytes": self.bytes, "detected": self.detected,
            "error": self.error,
        }


@dataclass
class BatchReport:
    items: list[BatchItem] = field(default_factory=list)
    dry_run: bool = True
    script: str = ""
    out_dir: str = ""
    elapsed_s: float = 0.0

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def ok_count(self) -> int:
        return sum(1 for i in self.items if i.ok)

    @property
    def skip_count(self) -> int:
        return sum(1 for i in self.items if i.skipped)

    @property
    def fail_items(self) -> list[BatchItem]:
        return [i for i in self.items if not i.ok and not i.skipped]

    def to_json(self) -> dict[str, Any]:
        return {
            "dryRun": self.dry_run,
            "script": self.script,
            "outDir": self.out_dir,
            "total": self.total,
            "ok": self.ok_count,
            "skipped": self.skip_count,
            "failed": len(self.fail_items),
            "elapsedS": round(self.elapsed_s, 1),
            "items": [i.to_json() for i in self.items],
        }


# ------------------------------------------------------------ 构造任务

def items_from_playlist(list_id: str, *, quality: str = "320k",
                        db_override=None, exe_path=None) -> list[BatchItem]:
    """从歌单构造批量任务。"""
    info = db_reader.get_list(list_id, db_override, exe_path)
    if not info:
        raise UsageError(f"找不到歌单：{list_id}")
    songs = db_reader.songs_in_list(list_id, db_override=db_override,
                                    exe_path=exe_path)
    out: list[BatchItem] = []
    for s in songs:
        sid = s.get("id") or ""
        src = s.get("source") or ""
        if not sid or not src:
            continue
        try:
            p = parse_song_id(sid, src)
            mid = p.songmid
        except Exception:                          # noqa: BLE001
            mid = sid
        out.append(BatchItem(
            name=s.get("name") or "", singer=s.get("singer") or "",
            source=src, songmid=mid, quality=quality,
            list_id=list_id, list_name=info.get("name") or "",
        ))
    return out


def items_from_failed(*, source: str | None = None, quality: str | None = None,
                      limit: int | None = None,
                      db_override=None, exe_path=None) -> list[BatchItem]:
    """从"下载失败"的记录构造批量任务。

    覆盖两类：
      1. ``status = error``（真失败）
      2. 记录存在但**磁盘文件已丢失**（``verify`` 发现的）
    """
    rows = db_reader.downloads(status="incomplete",
                               db_override=db_override, exe_path=exe_path)
    errs = [r for r in rows if r["status"] == db_reader.DL_ERROR]

    # 再补上"文件丢失"的（这些 status 可能是 completed）
    try:
        v = db_reader.verify_downloads(check_size=False,
                                       db_override=db_override,
                                       exe_path=exe_path)
        seen = {(r["source"], r["songmid"]) for r in errs}
        for m in v["missingItems"]:
            key = (m["source"], m["songmid"])
            if key not in seen and m["source"]:
                errs.append({**m, "statusText": "文件已丢失"})
                seen.add(key)
    except Exception:                              # noqa: BLE001
        pass

    if source:
        errs = [r for r in errs if r["source"] == source]
    if limit:
        errs = errs[:limit]

    return [BatchItem(
        name=r["name"], singer=r["singer"], source=r["source"],
        songmid=r["songmid"], quality=quality or r["quality"] or "320k",
        reason=r.get("statusText") or "",
    ) for r in errs if r["source"] and r["songmid"]]


def items_from_search(songs: Iterable[dict], *, quality: str = "320k"
                      ) -> list[BatchItem]:
    """从搜索结果（或其他 song dict）构造任务。"""
    out = []
    for s in songs:
        src = s.get("source") or ""
        sid = s.get("id") or ""
        mid = s.get("songmid") or ""
        if not mid and sid and src:
            try:
                mid = parse_song_id(sid, src).songmid
            except Exception:                      # noqa: BLE001
                mid = sid
        if not (src and mid):
            continue
        out.append(BatchItem(
            name=s.get("name") or "", singer=s.get("singer") or "",
            source=src, songmid=mid, quality=quality))
    return out


# ------------------------------------------------------------ 执行

def run_batch(items: list[BatchItem], out_dir: str | Path, *,
              script_code: str, script_name: str = "",
              quality: str = "", apply_: bool = False,
              overwrite: bool = False, skip_existing: bool = True,
              limit: int | None = None,
              on_item: Callable[[int, int, BatchItem], None] | None = None,
              ) -> BatchReport:
    """执行（或预演）批量下载。

    :param script_code: JS 音源脚本源码
    :param apply_: False 时只列计划，不启动 Node、不下载
    """
    rep = BatchReport(dry_run=not apply_, script=script_name,
                      out_dir=str(out_dir))
    work = items[:limit] if limit else items
    rep.items = work

    if not apply_:
        return rep

    dest = Path(out_dir)
    t0 = time.time()
    total = len(work)
    for idx, it in enumerate(work, 1):
        if on_item:
            on_item(idx, total, it)

        # 跳过已存在且大小合理的文件
        if skip_existing and not overwrite:
            guess = fetcher.safe_filename(
                f"{it.name} - {it.singer}" if it.singer else it.name,
                "flac" if it.quality.startswith("flac") else "mp3")
            cand = dest / guess
            if cand.is_file() and cand.stat().st_size > 1024:
                it.skipped = True
                it.path = str(cand)
                it.bytes = cand.stat().st_size
                continue

        r = jshost.fetch_url(script_code, source=it.source,
                             songmid=it.songmid, quality=quality or it.quality,
                             script_name=script_name)
        if not r.ok:
            it.error = f"取链接失败({r.stage}): {r.error}"
            time.sleep(RATE_DELAY)
            continue

        fname = fetcher.safe_filename(
            f"{it.name} - {it.singer}" if it.singer else it.name,
            fetcher.guess_ext(r.url))
        d = fetcher.download(r.url, dest, filename=fname, overwrite=overwrite)
        it.ok = d.ok
        it.path = d.path
        it.bytes = d.bytes
        it.error = d.error
        if d.ok:
            it.detected = fetcher.detect_audio_kind(d.path)
        time.sleep(RATE_DELAY)

    rep.elapsed_s = time.time() - t0
    return rep


def save_report(rep: BatchReport, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rep.to_json(), ensure_ascii=False, indent=2),
                 encoding="utf-8")
    return p
