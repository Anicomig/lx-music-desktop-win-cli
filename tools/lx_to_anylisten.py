# -*- coding: utf-8 -*-
"""
LX Music (.lxmc) → any-listen (.alcfg) 歌单转换器

参考文档:
  C:/Users/EDY/Documents/workspace/docs/lx-to-anylisten.md

用法:
  python lx_to_anylisten.py <input.lxmc> [-o output.alcfg] [--no-gzip]
"""
import argparse
import gzip
import json
import os
import sys
import time
from typing import Any


# ----------------------------- 读取 LX -----------------------------

def load_lx(path: str) -> dict:
    """读取 .lxmc 或 .json, 自动判断是否 gzip"""
    with open(path, "rb") as f:
        data = f.read()
    is_gzip = len(data) >= 2 and data[:2] == b"\x1f\x8b"
    if is_gzip or not path.endswith(".json"):
        try:
            text = gzip.decompress(data).decode("utf-8")
        except OSError:
            text = data.decode("utf-8")
    else:
        text = data.decode("utf-8")
    return json.loads(text)


def unwrap_lx_lists(lx: dict) -> list:
    """从 LX 顶层结构取出 UserListInfoFull[] 数组"""
    t = lx.get("type")
    if t in ("playList_v2", "allData_v2"):
        return lx.get("data") if t == "playList_v2" else lx.get("playList", [])
    if t in ("playListPart_v2", "playListPart", "defautlList", "playList"):
        d = lx.get("data")
        return d if isinstance(d, list) else [d]
    if t in ("setting_v2", "setting"):
        print(f"[warn] LX 文件 type={t!r} 不含歌单, 跳过", file=sys.stderr)
        return []
    print(f"[warn] 未知 LX type={t!r}, 尝试把 data 当成数组", file=sys.stderr)
    return lx.get("data", []) if isinstance(lx.get("data"), list) else []


# ----------------------------- 转换歌曲 meta -----------------------------

def _to_size_str(size: Any) -> str | None:
    """LX size: '3.4 MB' / '8.5 Mb' / None -> 保留原文(AL 只要求 string|None)"""
    if size is None:
        return None
    return str(size)


def convert_meta(lx_meta: dict, source: str) -> dict:
    """LX meta -> any-listen meta"""
    new: dict = {}

    # 公共字段
    new["musicId"] = str(lx_meta.get("songId", ""))
    new["albumName"] = lx_meta.get("albumName", "") or ""

    pic = lx_meta.get("picUrl")
    new["picUrl"] = pic if pic else None

    # source: 顶层字段 -> meta.source (any-listen 强制放 meta 里)
    new["source"] = source

    # qualitys: LX 数组 + _qualitys 字典 -> AL 字典
    qdict: dict = {}
    for q in lx_meta.get("qualitys") or []:
        if not isinstance(q, dict):
            continue
        qtype = q.get("type")
        if not qtype:
            continue
        entry: dict = {"sizeStr": _to_size_str(q.get("size"))}
        if "hash" in q:
            entry["hash"] = q["hash"]
        qdict[qtype] = entry
    for qtype, qv in (lx_meta.get("_qualitys") or {}).items():
        if qtype in qdict:
            # 优先保留 AL 里已有的 hash, 没有就从 _qualitys 补
            if "hash" in qv and "hash" not in qdict[qtype]:
                qdict[qtype]["hash"] = qv["hash"]
        else:
            entry = {"sizeStr": _to_size_str(qv.get("size"))}
            if "hash" in qv:
                entry["hash"] = qv["hash"]
            qdict[qtype] = entry
    if qdict:
        new["qualitys"] = qdict

    # LX MusicInfoMetaBase 字段
    if lx_meta.get("albumId") is not None:
        new["albumId"] = lx_meta["albumId"]
    if lx_meta.get("year") is not None:
        new["year"] = lx_meta["year"]
    if lx_meta.get("trackNo") is not None:
        new["trackNo"] = lx_meta["trackNo"]
    if lx_meta.get("discNo") is not None:
        new["discNo"] = lx_meta["discNo"]

    # tx 专属: strMediaMid / albumMid / id(数字 songId)
    if lx_meta.get("strMediaMid"):
        new["strMediaMid"] = lx_meta["strMediaMid"]
    if lx_meta.get("albumMid"):
        new["albumMid"] = lx_meta["albumMid"]
    if lx_meta.get("id") is not None and source == "tx":
        new["id"] = lx_meta["id"]

    # kg 专属: hash
    if lx_meta.get("hash"):
        new["hash"] = lx_meta["hash"]

    # mg 专属: copyrightId / lrcUrl / mrcUrl / trcUrl
    for k in ("copyrightId", "lrcUrl", "mrcUrl", "trcUrl"):
        if lx_meta.get(k) is not None:
            new[k] = lx_meta[k]

    # any-listen 必填: createTime/updateTime/posTime
    now_ms = int(time.time() * 1000)
    new["createTime"] = int(lx_meta.get("createTime", now_ms))
    new["updateTime"] = int(lx_meta.get("updateTime", now_ms))
    new["posTime"] = int(lx_meta.get("posTime", now_ms))

    return new


def convert_music(lx_music: dict) -> dict:
    """LX MusicInfo -> any-listen MusicInfoOnline"""
    is_local = lx_music.get("source") == "local"
    source = lx_music.get("source", "")
    lx_meta = lx_music.get("meta", {}) or {}

    out: dict = {
        "id": lx_music["id"],
        "name": lx_music.get("name", ""),
        "singer": lx_music.get("singer", ""),
        "interval": lx_music.get("interval"),
        "isLocal": is_local,
    }

    if is_local:
        # 本地歌曲: meta 走 MusicInfoMeta_local 格式
        out["meta"] = {
            "musicId": str(lx_meta.get("songId", lx_music["id"])),
            "albumName": lx_meta.get("albumName", "") or "",
            "picUrl": lx_meta.get("picUrl"),
            "filePath": lx_meta.get("filePath", ""),
            "ext": lx_meta.get("ext", ""),
            "bitrateLabel": lx_meta.get("bitrateLabel"),
            "sizeStr": str(lx_meta.get("size", "") or ""),
            "deviceId": lx_meta.get("deviceId", ""),
            "createTime": int(time.time() * 1000),
            "updateTime": int(time.time() * 1000),
            "posTime": int(time.time() * 1000),
        }
    else:
        out["meta"] = convert_meta(lx_meta, source)

    return out


# ----------------------------- 转换歌单 -----------------------------

def _default_userlist_meta(lx_list: dict, lx_meta: dict | None = None) -> dict:
    """构造 any-listen UserListInfoBaseMeta"""
    lx_meta = lx_meta or {}
    now_ms = int(time.time() * 1000)
    song_count = len(lx_list.get("list") or [])
    return {
        "songCount": song_count,
        "pic": lx_meta.get("pic", ""),
        "playCount": int(lx_meta.get("playCount", 0)),
        "createTime": int(lx_meta.get("createTime", now_ms)),
        "updateTime": int(lx_meta.get("updateTime", now_ms)),
        "posTime": int(lx_meta.get("posTime", now_ms)),
        "desc": lx_meta.get("desc", ""),
    }


def convert_userlist(lx_list: dict) -> dict:
    """LX UserListInfoFull -> any-listen UserListInfoGeneralFull"""
    return {
        "id": lx_list["id"],
        "parentId": None,
        "name": lx_list.get("name", ""),
        "type": "general",
        "meta": _default_userlist_meta(lx_list),
        "list": [convert_music(m) for m in (lx_list.get("list") or [])],
    }


def build_anylisten(lx_lists: list) -> dict:
    """LX UserListInfoFull[] -> any-listen ListDataFull"""
    default_list = None
    love_list = None
    user_lists: list = []

    for pl in lx_lists:
        pid = pl.get("id")
        if pid == "default" and default_list is None:
            converted = convert_userlist({**pl, "name": pl.get("name") or "默认列表"})
            converted["id"] = "default"
            converted["name"] = pl.get("name") or "默认列表"
            converted["type"] = "default"
            default_list = converted
        elif pid == "love" and love_list is None:
            converted = convert_userlist({**pl, "name": pl.get("name") or "我的收藏"})
            converted["id"] = "love"
            converted["name"] = pl.get("name") or "我的收藏"
            converted["type"] = "default"
            love_list = converted
        else:
            user_lists.append(convert_userlist(pl))

    # 如果 LX 没有 default/love, 用空壳
    if default_list is None:
        default_list = {
            "id": "default",
            "parentId": None,
            "name": "默认列表",
            "type": "default",
            "meta": _default_userlist_meta({"list": []}),
            "list": [],
        }
    if love_list is None:
        love_list = {
            "id": "love",
            "parentId": None,
            "name": "我的收藏",
            "type": "default",
            "meta": _default_userlist_meta({"list": []}),
            "list": [],
        }

    return {
        "defaultList": default_list,
        "loveList": love_list,
        "userList": user_lists,
    }


def wrap_backup(list_data: dict, version: int = 1) -> dict:
    """包成 AnyListen.SongListBackupData"""
    return {"songlist": {"version": version, "data": list_data}}


# ----------------------------- 写入 -----------------------------

def save_anylisten(path: str, data: dict, gzip_output: bool = True) -> None:
    text = json.dumps(data, ensure_ascii=False)
    if gzip_output and not path.endswith(".json"):
        with open(path, "wb") as f:
            f.write(gzip.compress(text.encode("utf-8")))
    else:
        if not path.endswith(".json"):
            path += ".json"
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)


# ----------------------------- CLI -----------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="LX .lxmc → any-listen .alcfg 转换器")
    ap.add_argument("input", help="输入 LX 文件 (.lxmc 或 .json)")
    ap.add_argument("-o", "--output", help="输出文件路径 (默认: <input>.alcfg)")
    ap.add_argument("--no-gzip", action="store_true", help="不 gzip 压缩, 输出明文 JSON")
    ap.add_argument("--version", type=int, default=1, help="SongListBackupData version 字段")
    ap.add_argument("--pretty", action="store_true", help="明文 JSON 时用缩进格式")
    args = ap.parse_args()

    if not os.path.isfile(args.input):
        print(f"[error] 输入文件不存在: {args.input}", file=sys.stderr)
        return 1

    out_path = args.output or (os.path.splitext(args.input)[0] + ".alcfg")

    lx = load_lx(args.input)
    print(f"[info] 读取 LX 文件: {args.input}", file=sys.stderr)
    print(f"[info] LX type: {lx.get('type', '<none>')}", file=sys.stderr)

    lx_lists = unwrap_lx_lists(lx)
    print(f"[info] LX 歌单数: {len(lx_lists)}", file=sys.stderr)
    total_songs = sum(len(pl.get("list") or []) for pl in lx_lists)
    print(f"[info] LX 总歌曲数: {total_songs}", file=sys.stderr)

    al_data = build_anylisten(lx_lists)
    al_backup = wrap_backup(al_data, version=args.version)

    if args.no_gzip:
        if not out_path.endswith(".json"):
            out_path += ".json"
        text = json.dumps(al_backup, ensure_ascii=False, indent=2 if args.pretty else None)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        if not out_path.endswith(".alcfg"):
            out_path += ".alcfg"
        text = json.dumps(al_backup, ensure_ascii=False)
        with open(out_path, "wb") as f:
            f.write(gzip.compress(text.encode("utf-8")))

    out_size = os.path.getsize(out_path)
    print(f"[ok] 已写入: {out_path}  ({out_size:,} bytes)", file=sys.stderr)
    print(f"[info] AL defaultList: {len(al_data['defaultList']['list'])} 首", file=sys.stderr)
    print(f"[info] AL loveList:    {len(al_data['loveList']['list'])} 首", file=sys.stderr)
    print(f"[info] AL userList:    {len(al_data['userList'])} 个歌单", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
