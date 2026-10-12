"""``config_v2.json`` 读写。

结构：``{"version": "2.1.0", "setting": {<135 个扁平键>}}``

用到的键：
* ``openAPI.enable`` / ``openAPI.port`` / ``openAPI.bindLan`` —— 开放 API 服务
* ``common.apiSource`` —— **当前启用的音源脚本 id**（注意：不是 ``customSource``/``apiSource``）
* ``common.sourceNameType`` —— ``real`` | ``alias``，决定源显示名用 ``source_*`` 还是 ``source_alias_*``
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .._logging import get_logger
from ..errors import PathError
from ..paths import config_v2_path

log = get_logger()

DEFAULT_PORT = "23330"


def load_config(exe_path: Path | None = None) -> dict[str, Any]:
    """读 ``config_v2.json``，返回其中的 ``setting`` 段（不存在则返回 {}）。"""
    p = config_v2_path(exe_path)
    if not p.exists():
        raise PathError(
            f"找不到 config_v2.json：{p}\n"
            "请先启动一次 LX Music 以生成该文件。",
            detail={"path": str(p)},
        )
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PathError(f"config_v2.json 读取失败：{p}: {exc}",
                        detail={"path": str(p)}, cause=exc) from exc
    setting = data.get("setting")
    return setting if isinstance(setting, dict) else {}


def save_config(setting: dict[str, Any], exe_path: Path | None = None) -> None:
    """把 ``setting`` 段写回 ``config_v2.json``（保留其它顶层键）。

    ⚠️ 须在 LX 关闭时调用，否则可能被 LX 的内存副本覆盖。
    采用**原子写**（temp + replace）。
    """
    p = config_v2_path(exe_path)
    if not p.exists():
        raise PathError(f"找不到 config_v2.json：{p}", detail={"path": str(p)})

    raw = json.loads(p.read_text(encoding="utf-8"))
    raw["setting"] = setting

    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)
    log.debug("config written: %s", p)


def get_setting(key: str, default: Any = None,
                exe_path: Path | None = None) -> Any:
    return load_config(exe_path).get(key, default)


# --------------------------------------------------------------- 音源显示名


def source_name_type(exe_path: Path | None = None) -> str:
    """``real`` | ``alias``（默认 ``alias``，见 ``defaultSetting.ts:15``）。"""
    try:
        val = load_config(exe_path).get("common.sourceNameType")
    except PathError:
        return "real"
    return val if val in ("real", "alias") else "real"


def current_api_source(exe_path: Path | None = None) -> str | None:
    """当前启用的音源脚本 id（``common.apiSource``）。"""
    try:
        return load_config(exe_path).get("common.apiSource")
    except PathError:
        return None
