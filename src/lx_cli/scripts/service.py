"""音源脚本管理业务逻辑：install / update / list / remove。

**关键规则**：

1. **更新时保留原 id** —— 否则用户的 ``common.apiSource`` 选择会跳变回内置源
2. **按内容哈希判断是否需要更新**（不能用 ``@version``，有决定性反例）
3. **被手改过的脚本需 ``--force``** 才覆盖（比对 CLI 记录的哈希）
4. 安装前检查数量上限（LX 限 20）
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from .._logging import get_logger
from ..errors import (
    ScriptError, ScriptModifiedError, ScriptParseError, TooManyScriptsError,
)
from . import metadata as md
from . import repo as repo_mod
from . import store

log = get_logger()

#: LX 上限
MAX_SCRIPTS = md.MAX_SCRIPTS


@dataclass
class ChangePlan:
    """一次安装/更新的计划（供 dry-run 展示）。"""

    action: str                 # install | update | skip | remove
    entry_id: str
    name: str
    old_version: str = ""
    new_version: str = ""
    old_sha: str = ""
    new_sha: str = ""
    url: str = ""
    source_key: str = ""
    reason: str = ""

    def to_json(self) -> dict:
        return {
            "action": self.action,
            "id": self.entry_id,
            "name": self.name,
            "oldVersion": self.old_version,
            "newVersion": self.new_version,
            "changed": bool(self.old_sha and self.old_sha != self.new_sha),
            "url": self.url,
            "source": self.source_key,
            "reason": self.reason,
        }


def _new_entry_id(existing: list[store.ScriptEntry]) -> str:
    """生成新条目 id。

    格式 ``user_api_<随机>_<毫秒>``；``user_api`` 前缀是 LX 的硬要求
    （``apiSource.ts`` 用 ``/^user_api/`` 判断是否为用户脚本）。
    """
    import random
    used = {e.id for e in existing}
    for _ in range(100):
        cand = f"user_api_{random.randint(100, 999)}_{int(time.time() * 1000)}"
        if cand not in used:
            return cand
    raise ScriptError("无法生成唯一 id")


def list_scripts(*, exe_path: Path | None = None, path: Path | None = None,
                 meta_path: Path | None = None) -> list[dict]:
    """列出已安装脚本（含"是否被手改过"）。"""
    entries = store.load_entries(exe_path, path)
    meta = store.load_meta(exe_path, meta_path)
    out = []
    for e in entries:
        rec = meta.get(e.id) or {}
        d = e.to_json()
        d["modified"] = store.is_modified(e, meta)
        d["installedFrom"] = rec.get("source") or ""
        d["installedUrl"] = rec.get("url") or ""
        d["meta"] = md.parse_script_meta(e.script).to_dict() if e.script else {}
        out.append(d)
    return out


# --------------------------------------------------------------- 安装


def install_from_text(text: str, *, name: str | None = None,
                      exe_path: Path | None = None, path: Path | None = None,
                      meta_path: Path | None = None,
                      source_key: str = "", url: str = "",
                      force: bool = False,
                      dry_run: bool = False) -> ChangePlan:
    """从脚本明文安装。"""
    md.validate_script_size(text)
    parsed = md.parse_script_meta(text, strict=True)

    entries = store.load_entries(exe_path, path)
    if len(entries) >= MAX_SCRIPTS:
        raise TooManyScriptsError(
            f"已达上限 {MAX_SCRIPTS} 个音源（LX 限制）。请先删除一些。")

    new_sha = repo_mod.sha256_of(text)
    display = name or parsed.name or "未命名音源"

    # 已存在同名脚本？→ 视为更新（保留原 id）
    for e in entries:
        if e.name == display:
            return _apply_update(
                e, text, entries, parsed, dry_run=dry_run, force=force,
                exe_path=exe_path, path=path, meta_path=meta_path,
                source_key=source_key, url=url)

    plan = ChangePlan(
        action="install", entry_id="", name=display,
        new_version=parsed.version, new_sha=new_sha,
        url=url, source_key=source_key, reason="新安装",
    )
    if dry_run:
        return plan

    entry = store.ScriptEntry(
        id=_new_entry_id(entries),
        name=display,
        description=parsed.description,
        version=parsed.version,
        author=parsed.author,
        homepage=parsed.homepage,
        allow_show_update_alert=True,
        script_encoded=store.encode_script(text),
        script=text,
    )
    plan.entry_id = entry.id
    entries.append(entry)
    store.backup_file(exe_path, path)
    store.save_entries(entries, exe_path=exe_path, path=path, force=force)
    store.record_install(entry, source=source_key, url=url,
                         exe_path=exe_path, path=meta_path)
    return plan


def _apply_update(entry: store.ScriptEntry, text: str,
                  entries: list[store.ScriptEntry], parsed: md.ScriptMeta, *,
                  dry_run: bool, force: bool,
                  exe_path: Path | None, path: Path | None,
                  meta_path: Path | None, source_key: str,
                  url: str) -> ChangePlan:
    """更新已有脚本 —— **保留原 id**。"""
    new_sha = repo_mod.sha256_of(text)
    meta = store.load_meta(exe_path, meta_path)

    plan = ChangePlan(
        action="update", entry_id=entry.id, name=entry.name,
        old_version=entry.version, new_version=parsed.version,
        old_sha=entry.sha256, new_sha=new_sha,
        url=url, source_key=source_key,
    )

    if entry.sha256 == new_sha:
        plan.action = "skip"
        plan.reason = "内容相同，无需更新"
        return plan

    # 被手改过 → 需要 --force
    if store.is_modified(entry, meta) and not force:
        raise ScriptModifiedError(
            f"脚本 {entry.name!r} 与 CLI 记录的哈希不一致（可能被手动修改过）。\n"
            "覆盖会丢失你的修改。确认要覆盖请加 --force。",
            detail={"id": entry.id, "name": entry.name},
        )

    plan.reason = "内容有变化" if plan.old_sha else "新记录"
    if dry_run:
        return plan

    entry.version = parsed.version
    entry.description = parsed.description
    entry.author = parsed.author
    entry.homepage = parsed.homepage
    entry.script = text
    entry.script_encoded = store.encode_script(text)

    store.backup_file(exe_path, path)
    store.save_entries(entries, exe_path=exe_path, path=path, force=force)
    store.record_install(entry, source=source_key, url=url,
                         exe_path=exe_path, path=meta_path)
    return plan


def install_from_file(file_path: str | Path, *, exe_path: Path | None = None,
                      path: Path | None = None, meta_path: Path | None = None,
                      force: bool = False, dry_run: bool = False) -> ChangePlan:
    """从本地文件安装。"""
    p = Path(file_path)
    if not p.exists():
        raise ScriptError(f"文件不存在：{p}")
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ScriptParseError(
            f"文件不是 UTF-8（音源脚本必须 UTF-8）：{p}") from exc
    return install_from_text(text, exe_path=exe_path, path=path,
                             meta_path=meta_path, force=force,
                             dry_run=dry_run, url=str(p))


def install_from_repo(name: str, *, exe_path: Path | None = None,
                      path: Path | None = None, meta_path: Path | None = None,
                      force: bool = False, dry_run: bool = False,
                      timeout: float = 30.0) -> ChangePlan:
    """从 ``pdone/lx-music-source`` 下载并安装（自动回退镜像）。"""
    text, url, key = repo_mod.fetch_script(name, timeout=timeout)
    return install_from_text(text, exe_path=exe_path, path=path,
                             meta_path=meta_path, force=force,
                             dry_run=dry_run, source_key=key, url=url)


# --------------------------------------------------------------- 更新


def update_all(*, exe_path: Path | None = None, path: Path | None = None,
               meta_path: Path | None = None, force: bool = False,
               dry_run: bool = True, timeout: float = 30.0) -> list[ChangePlan]:
    """检查并更新**所有**已安装脚本。

    靠"CLI 记录的来源"决定从哪下载；无来源记录的（用户自己导入的）跳过。
    """
    entries = store.load_entries(exe_path, path)
    meta = store.load_meta(exe_path, meta_path)
    plans: list[ChangePlan] = []

    for e in entries:
        rec = meta.get(e.id) or {}
        source_key = rec.get("source") or ""
        if not source_key:
            plans.append(ChangePlan(
                action="skip", entry_id=e.id, name=e.name,
                old_version=e.version, old_sha=e.sha256,
                reason="无来源记录（非 CLI 安装），跳过"))
            continue

        try:
            text, url, key = repo_mod.fetch_script(source_key, timeout=timeout)
        except ScriptError as exc:
            plans.append(ChangePlan(
                action="skip", entry_id=e.id, name=e.name,
                old_version=e.version, reason=f"下载失败：{exc}"))
            continue

        parsed = md.parse_script_meta(text)
        new_sha = repo_mod.sha256_of(text)
        if e.sha256 == new_sha:
            plans.append(ChangePlan(
                action="skip", entry_id=e.id, name=e.name,
                old_version=e.version, new_version=parsed.version,
                old_sha=e.sha256, new_sha=new_sha, url=url, source_key=key,
                reason="内容相同，无需更新"))
            continue

        if store.is_modified(e, meta) and not force:
            plans.append(ChangePlan(
                action="skip", entry_id=e.id, name=e.name,
                old_version=e.version, new_version=parsed.version,
                old_sha=e.sha256, new_sha=new_sha, url=url, source_key=key,
                reason="脚本被手动修改过，需 --force 才覆盖"))
            continue

        plan = ChangePlan(
            action="update", entry_id=e.id, name=e.name,
            old_version=e.version, new_version=parsed.version,
            old_sha=e.sha256, new_sha=new_sha, url=url, source_key=key,
            reason="内容有变化")
        if not dry_run:
            e.version = parsed.version
            e.description = parsed.description
            e.author = parsed.author
            e.homepage = parsed.homepage
            e.script = text
            e.script_encoded = store.encode_script(text)
            store.record_install(e, source=key, url=url,
                                 exe_path=exe_path, path=meta_path)
        plans.append(plan)

    if not dry_run and any(p.action == "update" for p in plans):
        store.backup_file(exe_path, path)
        store.save_entries(entries, exe_path=exe_path, path=path, force=force)

    return plans


# --------------------------------------------------------------- 删除


def remove(name_or_id: str, *, exe_path: Path | None = None,
           path: Path | None = None, meta_path: Path | None = None,
           force: bool = False, dry_run: bool = False) -> ChangePlan:
    """按 id 或名称删除脚本。"""
    entries = store.load_entries(exe_path, path)
    target = None
    for e in entries:
        if e.id == name_or_id or e.name == name_or_id:
            target = e
            break
    if target is None:
        raise ScriptError(f"未找到脚本：{name_or_id}")

    plan = ChangePlan(action="remove", entry_id=target.id, name=target.name,
                      old_version=target.version, old_sha=target.sha256,
                      reason="删除")
    if dry_run:
        return plan

    entries = [e for e in entries if e.id != target.id]
    store.backup_file(exe_path, path)
    store.save_entries(entries, exe_path=exe_path, path=path, force=force)

    meta = store.load_meta(exe_path, meta_path)
    meta.pop(target.id, None)
    store.save_meta(meta, exe_path=exe_path, path=meta_path)
    return plan


# --------------------------------------------------------------- 当前音源


def get_active_source(*, exe_path: Path | None = None) -> str | None:
    """当前启用的音源 id（``common.apiSource``）。"""
    from ..core.config_store import current_api_source
    return current_api_source(exe_path)


def set_active_source(entry_id: str, *, exe_path: Path | None = None,
                      force: bool = False) -> None:
    """切换当前启用的音源（写 ``config_v2.json``）。"""
    from ..core import config_store
    from ..errors import LxRunningError
    if not force:
        from ..core.launcher import is_running
        if is_running():
            raise LxRunningError("LX 正在运行，改配置会被覆盖。请先关闭 LX，或加 --force。")
    s = config_store.load_config(exe_path)
    s["common.apiSource"] = entry_id
    config_store.save_config(s, exe_path)
