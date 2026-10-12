"""``user_api.json`` 读写（音源脚本存储）。

**编码格式**【已核实 — 用本机真实文件 8/8 验证】：

    script = "gz_" + base64(zlib.compress(utf8_bytes))

⚠️ 前缀叫 ``gz_`` 但**不是 gzip** —— 是 **zlib** 格式（``0x78 0x9C`` 开头）。
用 ``gzip.decompress`` 会失败。

**文件结构**：

    {"userApis": [
       {"id": "user_api_927_1784270441030", "name": "...", "description": "...",
        "version": "...", "author": "...", "homepage": "...",
        "allowShowUpdateAlert": true, "script": "gz_..."}
    ]}

**写入纪律**：
* **Tab 缩进**（LX 自己写出来的是 Tab；用空格虽能读，但为一致性保持 Tab）
* **原子写**（temp + rename）：解析失败会让 LX 改名 ``.bak`` 并弹错
* **LX 运行时不得写入**
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from .._logging import get_logger
from ..errors import LxRunningError, ScriptError, ScriptParseError
from ..paths import scripts_meta_path, user_api_path

log = get_logger()

GZ_PREFIX = "gz_"


# --------------------------------------------------------------- 编解码


def encode_script(script: str) -> str:
    """脚本明文 → ``gz_`` + base64(zlib)。

    >>> s = "/*\\n * @name t\\n */"
    >>> encode_script(s).startswith("gz_")
    True
    """
    raw = script.encode("utf-8")
    return GZ_PREFIX + base64.b64encode(zlib.compress(raw)).decode("ascii")


def decode_script(encoded: str) -> str:
    """``gz_`` 编码 → 脚本明文。

    **不是 gzip** —— 用 ``zlib.decompress``。
    """
    if not encoded:
        return ""
    if not encoded.startswith(GZ_PREFIX):
        # 少数情况下可能是明文（旧格式/手工编辑）
        return encoded
    try:
        return zlib.decompress(base64.b64decode(encoded[len(GZ_PREFIX):])).decode("utf-8")
    except Exception as exc:                      # noqa: BLE001
        raise ScriptParseError(
            f"脚本解码失败（应为 gz_ + base64(zlib)，注意不是 gzip）：{exc}"
        ) from exc


# --------------------------------------------------------------- 数据模型


@dataclass
class ScriptEntry:
    """一条已安装的音源脚本。"""

    id: str
    name: str = ""
    description: str = ""
    version: str = ""
    author: str = ""
    homepage: str = ""
    allow_show_update_alert: bool = True
    script_encoded: str = ""
    script: str = field(default="", repr=False)

    @property
    def sha256(self) -> str:
        import hashlib
        return hashlib.sha256(self.script.encode("utf-8")).hexdigest()

    def to_storage(self) -> dict:
        """转成写回 ``user_api.json`` 的 dict（8 键，顺序与 LX 一致）。"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "homepage": self.homepage,
            "allowShowUpdateAlert": self.allow_show_update_alert,
            "script": self.script_encoded or encode_script(self.script),
        }

    def to_json(self, *, show_secrets: bool = False) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "homepage": self.homepage,
            "scriptChars": len(self.script),
            "sha256": self.sha256,
            "allowShowUpdateAlert": self.allow_show_update_alert,
        }


def _entry_from_storage(d: dict) -> ScriptEntry:
    encoded = d.get("script") or ""
    try:
        script = decode_script(encoded)
    except ScriptParseError:
        script = ""
    return ScriptEntry(
        id=d.get("id") or "",
        name=d.get("name") or "",
        description=d.get("description") or "",
        version=d.get("version") or "",
        author=d.get("author") or "",
        homepage=d.get("homepage") or "",
        allow_show_update_alert=bool(d.get("allowShowUpdateAlert", True)),
        script_encoded=encoded,
        script=script,
    )


# --------------------------------------------------------------- 读写


def load_entries(exe_path: Path | None = None,
                 path: Path | None = None) -> list[ScriptEntry]:
    """读取全部已安装脚本。文件不存在返回空列表。"""
    p = Path(path) if path else user_api_path(exe_path)
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ScriptError(f"user_api.json 读取失败：{p}: {exc}",
                          detail={"path": str(p)}, cause=exc) from exc

    apis = raw.get("userApis") if isinstance(raw, dict) else raw
    if not isinstance(apis, list):
        raise ScriptError(f"user_api.json 结构异常（期望 {{'userApis': [...]}}）：{p}")
    return [_entry_from_storage(d) for d in apis if isinstance(d, dict)]


def save_entries(entries: list[ScriptEntry], *, exe_path: Path | None = None,
                 path: Path | None = None, check_running: bool = True,
                 force: bool = False) -> Path:
    """**原子写**回 ``user_api.json``。

    * Tab 缩进（与 LX 一致）
    * temp + ``os.replace`` 原子替换
    * 写前可选检查 LX 未运行
    """
    if check_running and not force:
        from ..core.launcher import is_running
        if is_running():
            raise LxRunningError(
                "LX Music 正在运行，写 user_api.json 会被它覆盖。"
                "请先关闭 LX，或加 --force。")

    p = Path(path) if path else user_api_path(exe_path)
    p.parent.mkdir(parents=True, exist_ok=True)

    payload = {"userApis": [e.to_storage() for e in entries]}
    text = json.dumps(payload, ensure_ascii=False, indent="\t")

    tmp = p.with_name(p.name + f".tmp{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    try:
        os.replace(tmp, p)            # 原子替换
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    log.debug("wrote %d scripts to %s", len(entries), p)
    return p


# --------------------------------------------------------------- 哈希清单


def load_meta(exe_path: Path | None = None,
              path: Path | None = None) -> dict:
    """读 CLI 自管的哈希清单（用于检测"被手改过"）。"""
    p = Path(path) if path else scripts_meta_path(exe_path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_meta(meta: dict, *, exe_path: Path | None = None,
              path: Path | None = None) -> None:
    p = Path(path) if path else scripts_meta_path(exe_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def record_install(entry: ScriptEntry, *, source: str = "", url: str = "",
                   exe_path: Path | None = None,
                   path: Path | None = None) -> None:
    """记录某脚本"由 CLI 安装时的内容哈希"。"""
    meta = load_meta(exe_path, path)
    meta[entry.id] = {
        "installedSha256": entry.sha256,
        "name": entry.name,
        "version": entry.version,
        "source": source,
        "url": url,
        "installedAt": int(time.time() * 1000),
    }
    save_meta(meta, exe_path=exe_path, path=path)


def is_modified(entry: ScriptEntry, meta: dict) -> bool:
    """脚本是否被手改过（与 CLI 记录的哈希不一致，或无记录）。

    无记录 = 用户自己导入的 → 同样视为"被改动"，更新时需 ``--force``。
    """
    rec = meta.get(entry.id)
    if not rec:
        return True
    return rec.get("installedSha256") != entry.sha256


def backup_file(exe_path: Path | None = None,
                path: Path | None = None) -> Path | None:
    """写前备份 ``user_api.json`` → ``.bak-<时间戳>``。"""
    p = Path(path) if path else user_api_path(exe_path)
    if not p.exists():
        return None
    dst = p.with_name(p.name + f".bak-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(p, dst)
    return dst
