"""从备份的真实库派生一个**脱敏测试夹具**（只读来源，写出到 tests/fixtures）。

脱敏原则：
* 保留**结构性边界样本**：kg 裸 id、kg 二次前缀变体、local 路径、稀疏 order、
  多歌手 `、`、`&`/`;` 出现在歌手名、虚拟歌单 default/love、跨歌单重复 id
* 替换**隐私内容**：歌名/歌手/专辑 → 合成占位；local 路径 → 假路径；
  meta 里的 URL → 假域名（保留字段结构）
* 不含任何密钥（本就不在 DB 中）

用法：python scripts/make_fixture.py <备份DB> <输出DB>
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

SRC_DEFAULT = (
    Path(__file__).resolve().parent.parent.parent   # lx-cli-v2/scripts -> project root
    / "_backup" / "lxdata-20261012-142624" / "lx.data.db"
)


def _fake_url_rewrite(meta_str: str) -> str:
    """把 meta 里的真实 URL 换成假域名，保留结构与字段名。"""
    try:
        meta = json.loads(meta_str)
    except Exception:
        return meta_str
    if isinstance(meta.get("picUrl"), str) and meta["picUrl"].startswith("http"):
        meta["picUrl"] = "http://example.invalid/cover.jpg"
    for key in ("lrcUrl", "trcUrl", "mrcUrl"):
        if isinstance(meta.get(key), str) and meta[key].startswith("http"):
            meta[key] = "http://example.invalid/lyric"
    return json.dumps(meta, ensure_ascii=False)


def _fake_path(path: str, counter: int) -> str:
    """把 local 的真实文件路径替换为**唯一**的合成路径（保留扩展名）。

    必须唯一：``my_list_music_info`` 有 ``UNIQUE(id, listId)``，
    若多条真实路径映射到同一个假路径会撞唯一约束。
    """
    ext = Path(path).suffix or ".flac"
    return f"D:\\Fixture\\Music\\sample_{counter:05d}{ext}"


def build(src: Path, out: Path) -> dict:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    s = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)
    s.row_factory = sqlite3.Row
    d = sqlite3.connect(str(out))
    d.executescript("""
        CREATE TABLE my_list (
            id TEXT NOT NULL, name TEXT NOT NULL, source TEXT,
            sourceListId TEXT, position INTEGER NOT NULL,
            locationUpdateTime INTEGER, PRIMARY KEY(id));
        CREATE TABLE my_list_music_info (
            id TEXT NOT NULL, listId TEXT NOT NULL, name TEXT NOT NULL,
            singer TEXT NOT NULL, source TEXT NOT NULL, interval TEXT,
            meta TEXT NOT NULL, UNIQUE(id, listId));
        CREATE TABLE my_list_music_info_order (
            listId TEXT NOT NULL, musicInfoId TEXT NOT NULL, "order" INTEGER NOT NULL);
        CREATE TABLE download_list (
            id TEXT NOT NULL PRIMARY KEY, status TEXT NOT NULL,
            progress_downloaded INTEGER, progress_total INTEGER,
            fileName TEXT, filePath TEXT, position INTEGER);
        CREATE TABLE dislike_list (type TEXT NOT NULL, content TEXT NOT NULL, meta TEXT);
        CREATE TABLE music_url (id TEXT NOT NULL, url TEXT NOT NULL);
        CREATE TABLE lyric (id TEXT NOT NULL, source TEXT NOT NULL,
                            type TEXT NOT NULL, text TEXT NOT NULL);
    """)

    # --- my_list：保留 id（结构相关），名称脱敏 ---
    for r in s.execute("SELECT * FROM my_list ORDER BY position"):
        d.execute(
            "INSERT INTO my_list (id,name,source,sourceListId,position,locationUpdateTime)"
            " VALUES (?,?,?,?,?,?)",
            (r["id"], f"夹具歌单 {r['position']:02d}", r["source"],
             r["sourceListId"], r["position"], r["locationUpdateTime"]))

    # --- 歌曲：按 list 复制，保持 id/meta 结构；文本脱敏 ---
    # local 的 id 是路径且需唯一，用映射表保证一致（order 表要能对上）
    path_map: dict[str, str] = {}
    idx = 0
    for r in s.execute("SELECT * FROM my_list_music_info"):
        idx += 1
        song_id = r["id"]
        if r["source"] == "local":
            if song_id not in path_map:
                path_map[song_id] = _fake_path(song_id, len(path_map) + 1)
            song_id = path_map[song_id]
        singer = r["singer"]
        # 保留分隔符特征：只替换名字本体，保留 、 & ; 等符号结构与数量
        singer_fake = re.sub(r"[^\s、&;／/,，|]+",
                             lambda m: f"S{abs(hash(m.group(0))) % 100:02d}", singer)
        name_fake = f"曲目 {idx:04d}"
        meta = _fake_url_rewrite(r["meta"] or "{}")
        if r["source"] == "local":
            try:
                m = json.loads(meta)
                if isinstance(m.get("filePath"), str):
                    m["filePath"] = song_id
                    meta = json.dumps(m, ensure_ascii=False)
            except Exception:
                pass
        d.execute(
            "INSERT INTO my_list_music_info (id,listId,name,singer,source,interval,meta)"
            " VALUES (?,?,?,?,?,?,?)",
            (song_id, r["listId"], name_fake, singer_fake, r["source"],
             r["interval"], meta))

    # --- order：**原样保留**（含稀疏缺口，这是重要边界样本）---
    for r in s.execute("SELECT * FROM my_list_music_info_order"):
        mid = r["musicInfoId"]
        if mid in path_map:                      # 与歌曲表用同一映射
            mid = path_map[mid]
        d.execute('INSERT INTO my_list_music_info_order (listId,musicInfoId,"order")'
                  " VALUES (?,?,?)", (r["listId"], mid, r["order"]))

    for r in s.execute("SELECT * FROM dislike_list"):
        d.execute("INSERT INTO dislike_list VALUES (?,?,?)",
                  (r["type"], f"曲目@S01", r["meta"]))
    d.execute("INSERT INTO music_url VALUES ('fixture_1','http://example.invalid/audio')")
    d.execute("INSERT INTO lyric VALUES ('fixture_1','raw','lyric','W3Rlc3Rd')")
    d.execute("INSERT INTO download_list VALUES "
              "('fixture_1','completed',100,100,'f.flac','D:\\\\Fixture\\\\f.flac',0)")

    d.commit()

    counts = {t: d.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("my_list", "my_list_music_info",
                        "my_list_music_info_order")}
    d.close(); s.close()
    return counts


if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else SRC_DEFAULT
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else (
        Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "lx.data.db")
    if not src.exists():
        print(f"source not found: {src}", file=sys.stderr)
        raise SystemExit(2)
    counts = build(src, out)
    print(f"fixture written: {out}")
    for k, v in counts.items():
        print(f"  {k}: {v}")
