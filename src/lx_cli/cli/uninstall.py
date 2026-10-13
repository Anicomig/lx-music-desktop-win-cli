"""``lx uninstall`` —— 卸载 CLI 自身的痕迹。

**不删 LX Music / 不删 LX 数据**。只清：
  * pip 装的 ``lx-cli`` 包（如有）
  * ``lx.exe``（如存在）
  * CLI 自己写的元数据（``lx_cli_scripts_meta.json`` 等）

默认 dry-run。``--apply`` 才执行。
``--restore-config`` 会把 ``config_v2.json.openAPI.enable`` 设回 false
（**需要先关 LX**；否则会被 LX 覆盖）。
"""
from __future__ import annotations

import json as _json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import click

from ..core.launcher import is_running
from ..paths import lx_datas_dir
from ._common import Ctx, pass_ctx, wrap_errors


@dataclass
class PlanItem:
    action: str                          # "edit" | "skip" | "fail" | "keep"
    target: str                          # 人类描述
    cmd: str = ""                        # 实际执行的命令（dry-run 时不跑）
    detail: dict[str, Any] = field(default_factory=dict)
    note: str = ""


def _detect_pip_installed() -> PlanItem:
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "show", "lx-cli"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=15)
    except Exception as exc:
        return PlanItem("skip", "pip 包 lx-cli", note=f"pip 调用失败：{exc}")
    if r.returncode != 0:
        return PlanItem("skip", "pip 包 lx-cli",
                        note="未通过 pip 安装（可能用 run.py / pipx / uv）")
    info = {}
    for line in r.stdout.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            info[k.strip()] = v.strip()
    return PlanItem(
        "edit",
        f"pip 包 lx-cli {info.get('Version', '?')}",
        cmd=f"{sys.executable} -m pip uninstall -y lx-cli",
        detail={"name": info.get("Name"), "version": info.get("Version"),
                "location": info.get("Location")},
    )


def _detect_lx_exe() -> PlanItem:
    """找当前 PATH 上的 lx.exe（仅删 Scripts/ 下的，避免误删其他同名 exe）。"""
    lx = shutil.which("lx")
    if not lx:
        return PlanItem("skip", "lx.exe", note="PATH 中无 lx（可能用 run.py）")
    lx_path = Path(lx)
    if "Scripts" not in lx_path.parts and "bin" not in lx_path.parts:
        return PlanItem(
            "skip", "lx.exe", detail={"path": lx},
            note="不在 Scripts/bin 目录；可能不是 pip 装的，**不删**（安全）")
    return PlanItem("edit", "lx.exe", cmd=f'rm "{lx}"',
                    detail={"path": lx})


def _detect_cli_metadata(_ctx: Ctx) -> list[PlanItem]:
    items: list[PlanItem] = []
    datas = lx_datas_dir()
    if not datas.is_dir():
        return items
    for p in datas.glob("lx_cli_scripts_meta.json"):
        items.append(PlanItem("edit", f"LxDatas/{p.name}",
                              cmd=f'rm "{p}"', detail={"path": str(p)}))
    cache = datas / "lx_cli_cache"
    if cache.is_dir():
        items.append(PlanItem("edit", "LxDatas/lx_cli_cache/",
                              cmd=f'rm -rf "{cache}"', detail={"path": str(cache)}))
    return items


def _plan_restore_config(ctx: Ctx) -> PlanItem:
    from ..core import config_store
    from ..paths import config_v2_path
    try:
        cfg_path = config_v2_path(ctx.exe)
    except Exception as exc:
        return PlanItem("skip", "还原 openAPI.enable",
                        note=f"无法定位 config_v2.json：{exc}")
    if not cfg_path.is_file():
        return PlanItem("skip", "还原 openAPI.enable", note="config_v2.json 不存在")
    return PlanItem(
        "edit", "关闭开放 API (config_v2.json openAPI.enable=false)",
        cmd="_internal_save_config_openapi_disable",
        detail={"path": str(cfg_path)},
        note="**需先关 LX**，否则会被 LX 覆盖。程序会再检查一次。",
    )


def _build_plan(ctx: Ctx, restore_config: bool) -> list[PlanItem]:
    items: list[PlanItem] = []
    items.append(_detect_pip_installed())
    items.append(_detect_lx_exe())
    items.extend(_detect_cli_metadata(ctx))
    items.append(PlanItem(
        "keep", "LX Music Desktop 桌面端",
        note="**不删**（避免误伤你的 LX；如要彻底卸载，请到系统应用管理）"))
    items.append(PlanItem(
        "keep", "LX 数据 (LxDatas/)",
        detail={"path": str(lx_datas_dir())},
        note="**不删**（含歌单、配置、音源脚本、备份等，删了就没了）"))
    items.append(PlanItem(
        "keep", "你的 release zip 文件",
        note="**不删**（下载包）"))
    if restore_config:
        items.append(_plan_restore_config(ctx))
    else:
        items.append(PlanItem(
            "skip", "还原开放 API 设置",
            note="要还原 openAPI.enable=false，请加 --restore-config（**需先关 LX**）"))
    return items


def _format_human(plan: list[PlanItem], will_apply: bool) -> str:
    lines = ["", f"卸载计划（{'将执行' if will_apply else 'dry-run'}）：", ""]
    for it in plan:
        sym = {"edit": "  [待删]  ", "skip": "  [跳过]  ", "fail": "  [失败]  ",
               "keep": "  [保留]  ", "edit-done": "  [已删]  "
               }.get(it.action, "  [?]     ")
        lines.append(f"{sym}{it.target}")
        for k, v in it.detail.items():
            v = str(v)
            if len(v) > 80:
                v = v[:77] + "…"
            lines.append(f"          {k}: {v}")
        if it.note:
            lines.append(f"          注：{it.note}")
    lines.append("")
    if not will_apply:
        lines.append("这是预览；要真正执行请加 --apply（首次确认会再问一次）。")
    return "\n".join(lines)


def _do_uninstall(plan: list[PlanItem], restore_config: bool, ctx: Ctx,
                 assume_yes: bool) -> list[PlanItem]:
    """执行 plan 里所有 'edit' 动作，附带二次确认。"""
    if restore_config and is_running():
        raise SystemExit(
            "要 --restore-config 必须先关 LX。\n"
            "运行：lx stop\n"
            "再试：lx uninstall --apply --restore-config")

    edits = [p for p in plan if p.action == "edit"]
    if not edits:
        return plan

    if not assume_yes:
        click.echo("\n即将执行以下操作：")
        for it in edits:
            click.echo(f"  • {it.target}")
        click.confirm("确认执行？", default=False, abort=True)

    for it in edits:
        if it.cmd == "_internal_save_config_openapi_disable":
            from ..core import config_store
            try:
                cfg = config_store.load_config(ctx.exe)
                cfg["openAPI.enable"] = False
                config_store.save_config(cfg, ctx.exe)
                it.action = "edit-done"
            except Exception as exc:
                it.action = "fail"
                it.detail["error"] = str(exc)
        else:
            try:
                subprocess.run(it.cmd, shell=True, check=True,
                               capture_output=True, timeout=30)
                it.action = "edit-done"
            except subprocess.CalledProcessError as exc:
                it.action = "fail"
                it.detail["error"] = (exc.stderr or str(exc))[:200]
    return plan


# ------- Click 命令 -------

@click.command("uninstall")
@click.option("--apply", "do_apply", is_flag=True,
              help="真正执行（默认 dry-run）")
@click.option("--yes", "assume_yes", is_flag=True,
              help="跳过二次确认（用于脚本/AI 自主决策）")
@click.option("--restore-config", is_flag=True,
              help="把 config_v2.json.openAPI.enable 改回 false（**需先关 LX**）")
@click.option("--json", "as_json", is_flag=True, help="输出结构化 JSON")
@pass_ctx
@wrap_errors
def uninstall_cmd(ctx: Ctx, do_apply: bool, assume_yes: bool,
                  restore_config: bool, as_json: bool) -> None:
    """卸载 lx-cli。**不删 LX Music 桌面端 / LX 数据**。"""
    plan = _build_plan(ctx, restore_config)
    if do_apply:
        plan = _do_uninstall(plan, restore_config, ctx, assume_yes)
    if as_json:
        click.echo(_json.dumps({"plan": [asdict(p) for p in plan]},
                               ensure_ascii=False, indent=2))
    else:
        click.echo(_format_human(plan, do_apply))
    n_fail = sum(1 for p in plan if p.action == "fail")
    if n_fail:
        raise SystemExit(1)
