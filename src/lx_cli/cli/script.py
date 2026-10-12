"""``lx script`` —— ② JS 音源脚本管理（安装/更新/列表/删除；**不执行脚本**）。

⚠️ 术语：此处的"脚本"是 ``pdone/lx-music-source`` 里的 JS 音源插件，
**不是** ``lx source-list`` 里的平台元数据接口。
"""
from __future__ import annotations

import click

from ..errors import LxCliError, ScriptError
from ..scripts import repo as repo_mod
from ..scripts import service
from ._common import Ctx, emit, json_option, pass_ctx, wrap_errors


@click.group("script")
def script_group() -> None:
    """音源脚本管理（安装/更新/列表/删除）。"""


def _version_label(version: str) -> str:
    """版本号展示：已有 ``v`` 前缀就不重复加。

    实测版本串形态混杂：``4`` / ``v2.0.0`` / ``1.0.0`` / ``v22``。
    """
    v = (version or "").strip()
    if not v:
        return "v?"
    return v if v.lower().startswith("v") else f"v{v}"


# --------------------------------------------------------------- 列表


@script_group.command("list")
@json_option
@pass_ctx
@wrap_errors
def list_cmd(ctx: Ctx) -> None:
    """列出已安装的音源脚本。"""
    rows = service.list_scripts(exe_path=ctx.exe)
    active = service.get_active_source(exe_path=ctx.exe)

    lines = [f"# 已安装 {len(rows)} 个音源脚本", ""]
    for r in rows:
        mark = "*" if r["id"] == active else " "
        warn = "  [已手改]" if r["modified"] else ""
        lines.append(f" {mark} {r['name']}  {_version_label(r['version'])}"
                     f"  by {r['author'] or '-'}{warn}")
        lines.append(f"     id={r['id']}")
        lines.append(f"     sha256={r['sha256'][:16]}…  字符数={r['scriptChars']:,}")
    if active:
        lines.append("")
        lines.append(f"当前启用：{active}")
    else:
        lines.append("")
        lines.append("当前未启用任何用户音源（LX 将无法播放在线歌曲）")

    emit(ctx, "\n".join(lines), {"count": len(rows), "active": active,
                                 "scripts": rows})


@script_group.command("repo")
@click.option("--check", is_flag=True, help="同时查询远端版本信息（联网）。")
@json_option
@pass_ctx
@wrap_errors
def repo_cmd(ctx: Ctx, check: bool) -> None:
    """列出源仓库（pdone/lx-music-source）可用的音源脚本。"""
    rows = []
    for s in repo_mod.REPO_SOURCES:
        item = repo_mod.describe(s)
        if check:
            try:
                text, url, _ = repo_mod.fetch_script(s.key)
                item["remote"] = {
                    **repo_mod.parse_script_meta(text).to_dict(),
                    "sha256": repo_mod.sha256_of(text),
                    "chars": len(text),
                }
                item["fetchedFrom"] = url
            except LxCliError as exc:
                item["remoteError"] = str(exc)
        rows.append(item)

    lines = [f"# 仓库 pdone/lx-music-source 共 {len(rows)} 个音源", ""]
    for r in rows:
        line = f"  {r['key']:10s} {r['label']}"
        if "remote" in r:
            line += f"   v{r['remote'].get('version') or '?'}"
        if r.get("remoteError"):
            line += "   (查询失败)"
        lines.append(line)
    emit(ctx, "\n".join(lines), {"repo": {"owner": repo_mod.OWNER,
                                           "repo": repo_mod.REPO,
                                           "branch": repo_mod.BRANCH},
                                 "sources": rows})


# --------------------------------------------------------------- 安装 / 更新


@script_group.command("install")
@click.argument("target", required=False)
@click.option("--file", "file_path", default=None,
              help="从本地 .js 文件安装。")
@click.option("--url", "url_", default=None, help="从 URL 下载安装。")
@click.option("--apply", "apply_", is_flag=True, help="实际写入（默认预演）。")
@click.option("--force", is_flag=True, help="覆盖被手改过的脚本 / LX 运行时也写。")
@json_option
@pass_ctx
@wrap_errors
def install_cmd(ctx: Ctx, target: str | None, file_path: str | None,
                url_: str | None, apply_: bool, force: bool) -> None:
    """安装音源脚本。

    \b
    TARGET 可以是仓库里的目录名或中文名（如 flower / 野花🌷）。
    也支持：
      --file <本地.js>
      --url  <https://...>

    \b
    示例：
      lx script install flower                 # 从仓库下载（预演）
      lx script install flower --apply
      lx script install --file .\\my.js --apply
      lx script install --url https://.../latest.js --apply
    """
    given = [bool(target), bool(file_path), bool(url_)]
    if sum(given) != 1:
        raise ScriptError("必须（且只能）提供 TARGET / --file / --url 之一")

    dry = not apply_
    if file_path:
        plan = service.install_from_file(
            file_path, exe_path=ctx.exe, force=force, dry_run=dry)
    elif url_:
        text = repo_mod.fetch_text(url_)
        plan = service.install_from_text(
            text, exe_path=ctx.exe, force=force, dry_run=dry, url=url_)
    else:
        plan = service.install_from_repo(
            target, exe_path=ctx.exe, force=force, dry_run=dry)  # type: ignore[arg-type]

    verb = {"install": "安装", "update": "更新", "skip": "跳过",
            "remove": "删除"}.get(plan.action, plan.action)
    head = f"[预演] 将{verb}" if dry else f"已{verb}"
    human = (f"{head}：{plan.name}\n"
             f"  id      {plan.entry_id or '(新建)'}\n"
             f"  版本    {plan.old_version or '-'} → {plan.new_version or '-'}\n"
             f"  来源    {plan.source_key or plan.url}\n"
             f"  说明    {plan.reason}")
    if dry:
        human += "\n\n这是预演，未写入。确认后加 --apply。"
    emit(ctx, human, {"dryRun": dry, "plan": plan.to_json()})


@script_group.command("update")
@click.argument("name", required=False)
@click.option("--all", "update_all_flag", is_flag=True, help="更新全部（有来源记录的）。")
@click.option("--apply", "apply_", is_flag=True, help="实际写入（默认预演）。")
@click.option("--force", is_flag=True, help="覆盖被手改过的脚本。")
@json_option
@pass_ctx
@wrap_errors
def update_cmd(ctx: Ctx, name: str | None, update_all_flag: bool,
               apply_: bool, force: bool) -> None:
    """检查并更新音源脚本（**按内容哈希**判断，不用 @version）。"""
    dry = not apply_

    if name:
        # 单个：先看它是否已安装且带来源记录
        rows = service.list_scripts(exe_path=ctx.exe)
        target = next((r for r in rows if r["name"] == name or r["id"] == name), None)
        if target is None:
            raise ScriptError(f"未安装该脚本：{name}（用 lx script install 安装）")
        src = target.get("installedFrom") or ""
        if not src:
            raise ScriptError(
                f"脚本 {name!r} 没有来源记录（不是 CLI 安装的），无法自动更新。\n"
                "可指定来源：lx script install <repo名> --apply")
        text, url, key = repo_mod.fetch_script(src)
        plan = service.install_from_text(
            text, name=target["name"], exe_path=ctx.exe,
            force=force, dry_run=dry, source_key=key, url=url)
        plans = [plan]
    else:
        plans = service.update_all(exe_path=ctx.exe, force=force, dry_run=dry)

    upd = [p for p in plans if p.action == "update"]
    skip = [p for p in plans if p.action == "skip"]

    lines = [f"# {'[预演] ' if dry else ''}更新检查：{len(plans)} 个脚本",
             f"  需更新 {len(upd)}  跳过 {len(skip)}", ""]
    for p in plans:
        tag = {"update": "→ 更新", "skip": "  跳过", "install": "  安装"}.get(
            p.action, p.action)
        detail = f"  {p.old_version or '?'} → {p.new_version or '?'}" if p.action == "update" else ""
        lines.append(f"  {tag}  {p.name}{detail}")
        lines.append(f"        {p.reason}")
    if dry and upd:
        lines += ["", "这是预演，未写入。确认后加 --apply。"]
    else:
        lines += ["", f"已更新 {len(upd)} 个。" if not dry else ""]

    emit(ctx, "\n".join(lines),
         {"dryRun": dry, "updated": len(upd), "skipped": len(skip),
          "plans": [p.to_json() for p in plans]})


# --------------------------------------------------------------- 删除 / 启用


@script_group.command("remove")
@click.argument("name")
@click.option("--apply", "apply_", is_flag=True, help="实际删除（默认预演）。")
@click.option("--force", is_flag=True)
@json_option
@pass_ctx
@wrap_errors
def remove_cmd(ctx: Ctx, name: str, apply_: bool, force: bool) -> None:
    """删除音源脚本。"""
    plan = service.remove(name, exe_path=ctx.exe, force=force, dry_run=not apply_)
    head = "[预演] 将删除" if not apply_ else "已删除"
    emit(ctx, f"{head}：{plan.name}  (id={plan.entry_id})",
         {"dryRun": not apply_, "plan": plan.to_json()})


@script_group.command("enable")
@click.argument("name")
@click.option("--force", is_flag=True)
@json_option
@pass_ctx
@wrap_errors
def enable_cmd(ctx: Ctx, name: str, force: bool) -> None:
    """切换当前启用的音源脚本（写 common.apiSource）。"""
    rows = service.list_scripts(exe_path=ctx.exe)
    target = next((r for r in rows if r["name"] == name or r["id"] == name), None)
    if target is None:
        raise ScriptError(f"未安装该脚本：{name}")
    service.set_active_source(target["id"], exe_path=ctx.exe, force=force)
    emit(ctx, f"已启用音源：{target['name']}",
         {"active": target["id"], "name": target["name"]})


@script_group.command("active")
@json_option
@pass_ctx
@wrap_errors
def active_cmd(ctx: Ctx) -> None:
    """查看当前启用的音源。"""
    active = service.get_active_source(exe_path=ctx.exe)
    name = ""
    if active:
        rows = service.list_scripts(exe_path=ctx.exe)
        m = next((r for r in rows if r["id"] == active), None)
        name = m["name"] if m else "(未知/已删除)"
    emit(ctx, f"{active or '(未设置)'}  {name}",
         {"active": active, "name": name})


@script_group.command("verify")
@json_option
@pass_ctx
@wrap_errors
def verify_cmd(ctx: Ctx) -> None:
    """校验 user_api.json 与脚本头是否合法。"""
    from ..scripts import store
    from ..scripts.metadata import is_valid_script, parse_script_meta

    issues: list[str] = []
    try:
        entries = store.load_entries(exe_path=ctx.exe)
    except LxCliError as exc:
        emit(ctx, f"读取失败：{exc}", {"ok": False, "issues": [str(exc)]})
        return

    for e in entries:
        if not e.script:
            issues.append(f"{e.name}: 脚本无法解码（gz_/zlib 格式异常）")
            continue
        if not is_valid_script(e.script):
            issues.append(f"{e.name}: 缺少合法头部注释块（LX 会拒绝加载）")
        if e.script != store.decode_script(e.script_encoded):
            issues.append(f"{e.name}: 编解码不一致")

    ok = not issues
    lines = [f"# 校验 {len(entries)} 个脚本：{'通过' if ok else '发现问题'}"]
    lines += [f"  - {i}" for i in issues]
    emit(ctx, "\n".join(lines),
         {"ok": ok, "count": len(entries), "issues": issues,
          "scripts": [e.to_json() for e in entries]})
