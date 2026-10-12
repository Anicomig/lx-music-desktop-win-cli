"""歌曲匹配 / 去重判定（移植桌面端 ``musicSdk/index.js:75-175`` 的逻辑）。

桌面端换源时的匹配步骤：

1. **时长 ±5 秒硬门槛** —— 时长差超过 5s 直接不匹配
2. 三轮匹配：歌名全等+歌手包含 / 歌手全等+歌名包含 / 专辑全等+…
3. **版本标记词**（``versionChars``）：若两者在"伴奏 / live / remix / 翻唱"等词上
   不一致，则**不算同一首**（避免把 Live 版当成原版）

本模块提供精简可用的 :func:`is_same_song` 与 :func:`find_duplicates`，
供"对比现有歌单"使用。
"""
from __future__ import annotations

import re
from typing import Iterable

#: 版本标记词（移植自桌面端 ``versionChars.ts``，覆盖中英日韩常见标记）
VERSION_CHARS: tuple[str, ...] = (
    # 中文
    "伴奏", "纯音乐", "无损", "试听", "片段", "副歌", "铃声", "清唱",
    "翻唱", "原唱", "重制", "重置", "重录", "现场", "演唱会", "翻录",
    "变速", "加速", "慢速", "降调", "升调", "女声", "男声", "童声",
    "合唱", "对唱", "独唱", "吉他", "钢琴", "小提琴", "古筝", "二胡",
    "dj", "remix", "混音", "混响", "电音",
    # 英文
    "live", "acoustic", "instrumental", "remix", "remaster",
    "remastered", "cover", "demo", "edit", "version", "ver",
    "radio", "extended", "short", "instrumental", "karaoke",
    "orchestra", "orchestral", "piano", "guitar", "unplugged",
    "studio", "mono", "stereo", "deluxe", "bonus", "track",
    "feat", "ft", "with", "op", "ed", "ost", "bgm",
    # 日文
    "インスト", "カラオケ", "ライブ", "カバー", "アコースティック",
    "リミックス", "オルゴール", "ピアノ", "ギター",
    # 韩文
    "반주", "라이브", "커버", "리믹스", "피아노", "기타",
)

#: 分隔符（用于歌名归一化；这里故意只做"弱"归一，保留版本词供后续判定）
_STRIP_CHARS = re.compile(r"[\s'\"\.\,，、&\"\(\)（）`~\-<>|\/\]\[!！?？:：;；]+")


def normalize_text(text: str | None) -> str:
    """归一化歌名/歌手：去空白与常见标点，转小写。"""
    if not text:
        return ""
    return _STRIP_CHARS.sub("", str(text)).lower()


def parse_interval(interval: str | None) -> int:
    """``03:11`` / ``1:02:03`` / ``184:23`` → 秒。无法解析返回 0。"""
    if not interval:
        return 0
    parts = str(interval).strip().split(":")
    total = 0
    unit = 1
    try:
        for p in reversed(parts):
            total += int(float(p)) * unit
            unit *= 60
    except (TypeError, ValueError):
        return 0
    return total


def version_flags(text: str | None) -> set[str]:
    """提取文本中出现的版本标记词。"""
    norm = normalize_text(text)
    return {c for c in VERSION_CHARS if normalize_text(c) in norm}


def is_same_song(name_a: str, singer_a: str, interval_a: str | int | None,
                 name_b: str, singer_b: str, interval_b: str | int | None,
                 *, duration_tolerance: int = 5) -> bool:
    """判断两首歌是否"同一首"。

    规则（对齐桌面端 ``findMusic``）：

    1. **时长差 > tolerance 秒 → 不是同一首**（硬门槛）
    2. 歌名归一化后不相等（且互不包含）→ 不是
    3. **版本标记不一致 → 不是**（防把 Live / 伴奏当原版）
    4. 歌手：一方为空则放行；否则要求包含关系
    """
    fa, fb = normalize_text(name_a), normalize_text(name_b)
    if not fa or not fb:
        return False
    if not (fa == fb or fa in fb or fb in fa):
        return False

    # 时长硬门槛（任一为 0 视为未知，跳过该检查）
    sa = interval_a if isinstance(interval_a, int) else parse_interval(interval_a)
    sb = interval_b if isinstance(interval_b, int) else parse_interval(interval_b)
    if sa and sb and abs(sa - sb) > duration_tolerance:
        return False

    # 版本标记必须一致
    if version_flags(name_a) != version_flags(name_b):
        return False

    na, nb = normalize_text(singer_a), normalize_text(singer_b)
    if not na or not nb:
        return True
    return na in nb or nb in na


def find_duplicates(candidate: dict, existing: Iterable[dict]) -> list[dict]:
    """在现有歌曲里找出与 ``candidate`` 同曲的条目（供对比报告用）。

    ``candidate`` / ``existing`` 项需含 ``name`` ``singer`` ``interval``。
    """
    out: list[dict] = []
    for r in existing:
        if is_same_song(
            candidate.get("name") or "", candidate.get("singer") or "",
            candidate.get("interval") or "",
            r.get("name") or "", r.get("singer") or "", r.get("interval") or "",
        ):
            out.append(r)
    return out
