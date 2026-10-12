"""搜索：单平台 / 指定多平台 / **聚合全部平台**。

聚合语义**照抄桌面端** ``store/search/music/action.ts:87-126``：

* ``sourceId == 'all'`` → 并发所有平台
* **单个平台失败不中断整体**，该平台返回空结果（``action.ts:99-105``）
* 结果按 ``id`` 去重（先到先得）
* 单平台模式**不排序**；聚合模式跨平台混排

各平台**分页口径不同**（已核源码）：

* ``kw``：上游 0-based（``pn = page - 1``），CLI 对外统一 1-based
* ``wy``：``allPage`` 用模块默认 limit（源码 bug，``wy/musicSearch.js:107``）
* 其余：1-based / offset
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable

from .._logging import get_logger
from ..errors import UsageError
from . import get_source, list_platforms
from .base import PLATFORMS, SearchResult, SongRecord, SourceError

log = get_logger()

#: 聚合时每平台取多少条（与桌面端 listInfos.all.limit 一致）
AGGREGATE_LIMIT = 30


def search_one(platform: str, keyword: str, *, page: int = 1,
               limit: int = 30) -> SearchResult:
    """单平台搜索（不做跨平台合并/排序，与桌面端单平台模式一致）。"""
    src = get_source(platform)
    return src.search(keyword, page=page, limit=limit)


def search_many(platforms: Iterable[str], keyword: str, *, page: int = 1,
                limit: int = AGGREGATE_LIMIT,
                max_workers: int = 5) -> list[SearchResult]:
    """并发搜多个平台。

    **失败隔离**：某个平台抛错时记录 warning 并返回空结果，
    不影响其它平台（照抄 ``action.ts:99-105`` 的 catch）。
    """
    plats = [p for p in platforms]
    results: list[SearchResult] = []
    if not plats:
        return results

    with ThreadPoolExecutor(max_workers=min(max_workers, len(plats))) as pool:
        futures = {
            pool.submit(search_one, p, keyword, page=page, limit=limit): p
            for p in plats
        }
        for fut in as_completed(futures):
            p = futures[fut]
            try:
                results.append(fut.result())
            except SourceError as exc:
                log.warning("平台 %s 搜索失败：%s", p, exc.message)
                results.append(SearchResult(platform=p, list=[], total=0,
                                            page=page, all_page=1, limit=limit))
            except Exception as exc:                       # 兜底：绝不因单平台炸掉整体
                log.warning("平台 %s 搜索异常：%s", p, exc)
                results.append(SearchResult(platform=p, list=[], total=0,
                                            page=page, all_page=1, limit=limit))

    # 保持**调用方传入的平台顺序**（而不是全局声明顺序）——
    # 否则 search(platforms=['wy']) 的 results[0] 会变成 kg，
    # 导致单平台模式取错结果。
    order = {p: i for i, p in enumerate(plats)}
    results.sort(key=lambda r: order.get(r.platform, 999))
    return results


def merge_results(results: Iterable[SearchResult], *, dedupe: bool = True
                  ) -> list[SongRecord]:
    """跨平台合并（按 ``id`` 去重，先到先得）。"""
    out: list[SongRecord] = []
    seen: set[str] = set()
    for res in results:
        for song in res.list:
            if dedupe:
                sid = song.to_song_id()
                if sid in seen:
                    continue
                seen.add(sid)
            out.append(song)
    return out


def search(keyword: str, *, platforms: Iterable[str] | None = None,
           page: int = 1, limit: int = AGGREGATE_LIMIT,
           dedupe: bool = True) -> dict:
    """统一入口。

    :param platforms: ``None`` → **聚合全部平台**（默认行为）；
                      单项列表 → 单平台；多项 → 指定多平台。
    :returns: ``{"mode": "single|multi|aggregate", "results": [...],
                 "songs": [...], "failed": [...]}``

    * ``mode == "single"``  → ``results`` 只有一项，``songs`` 即该项内容
    * 其它                  → ``songs`` 是合并去重后的跨平台列表
    """
    plats = list(platforms) if platforms else list(list_platforms())
    unknown = [p for p in plats if p not in PLATFORMS]
    if unknown:
        # 参数问题 → 用 UsageError（退出码 2），而不是平台接口错误
        raise UsageError(
            f"未知平台 {unknown[0]!r}（可用：{', '.join(PLATFORMS)}）",
            detail={"unknown": unknown, "available": list(PLATFORMS)},
        )

    results = search_many(plats, keyword, page=page, limit=limit)

    if len(plats) == 1:
        mode = "single"
        songs = list(results[0].list) if results else []
    elif len(plats) == len(list_platforms()):
        mode = "aggregate"
        songs = merge_results(results, dedupe=dedupe)
    else:
        mode = "multi"
        songs = merge_results(results, dedupe=dedupe)

    failed = [r.platform for r in results if not r.list and r.total == 0]

    return {
        "mode": mode,
        "keyword": keyword,
        "page": page,
        "platforms": plats,
        "results": results,
        "songs": songs,
        "failed": failed,
    }
