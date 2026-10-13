"""``lx script doctor`` —— 音源脚本体检。

回答："我装的这些脚本，哪个**当前可用**？"

本轮真实问题的根因就是"启用了 972 字符的空壳脚本"，
而 `lx script list` 只显示字符数，用户看不出"太小 = 有问题"。

体检维度（全部只读）：
  * 体积异常（过小 = 疑似空壳 / 转发壳）
  * 是否被手改过（``modified``）
  * 头部注释块是否规范（LX 靠它读元信息）
  * 声明的支持平台/音质（从脚本源码里提取）
  * 是否依赖外部后端（转发型脚本，后端挂了就废）
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

import click

from ..scripts import service as script_service
from ..scripts import store as script_store
from ._common import Ctx, emit, json_option, pass_ctx, wrap_errors

#: 小于此字符数视为"疑似空壳"（实测：正常脚本 2.6k~105k，空壳 972）
SHELL_THRESHOLD = 2000

_EXTERNAL_HOST_RE = re.compile(
    r"https?://([a-zA-Z0-9][a-zA-Z0-9.\-]*\.[a-zA-Z]{2,})", re.I)

#: 平台官方域名（出现这些说明是"纯客户端"脚本）
_OFFICIAL_HOSTS = (
    "kugou.com", "kuwo.cn", "kuwo.com", "music.163.com", "163.com",
    "y.qq.com", "qq.com", "migu.cn", "126.net", "gtimg.cn",
)
#: 常见分发/镜像域名（不算"后端依赖"）
_IGNORE_HOSTS = ("github.com", "githubusercontent.com", "jsdelivr.net",
                 "unpkg.com", "npmjs.com", "npmjs.org")

_QUALITY_ORDER = ["flac24bit", "flac", "hires", "320k", "192k", "128k"]


@dataclass
class ScriptCheck:
    id: str
    name: str
    version: str = ""
    author: str = ""
    scriptChars: int = 0
    modified: bool = False
    active: bool = False
    status: str = "ok"                 # ok | warn | fail
    issues: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    qualities: list[str] = field(default_factory=list)
    kind: str = ""                     # self-contained | proxy | unknown
    externalHosts: list[str] = field(default_factory=list)
    hasMetaBlock: bool = False
    hint: str = ""


def _extract_from_source(code: str) -> dict[str, Any]:
    """从脚本源码里提取线索。"""
    out: dict[str, Any] = {
        "sources": [], "qualities": [], "hasMetaBlock": False,
        "externalHosts": [], "kind": "unknown",
    }
    if not code:
        return out

    head = code[:2000]
    out["hasMetaBlock"] = any(k in head for k in ("@name", "@version", "@author"))

    order = ["kg", "kw", "tx", "wy", "mg"]
    found = {m.group(1) for m in re.finditer(r"""['"](kg|kw|tx|wy|mg)['"]""", code)}
    # 混淆脚本可能用转义形式 \u006b\u0067 等；再试一次解转义后的文本
    if not found:
        try:
            unescaped = code.encode("utf-8").decode("unicode_escape", "ignore")
            found = {m.group(1)
                     for m in re.finditer(r"""['"](kg|kw|tx|wy|mg)['"]""", unescaped)}
        except Exception:                          # noqa: BLE001
            pass
    # 再兜底：从 "sources" 结构里找
    if not found:
        for m in re.finditer(r"""sources["']?\s*[:=]\s*\{([^}]{0,300})""", code):
            for k in order:
                if k in m.group(1):
                    found.add(k)
    out["sources"] = [s for s in order if s in found]

    quals = {q for q in _QUALITY_ORDER
             if f"'{q}'" in code or f'"{q}"' in code}
    out["qualities"] = [q for q in _QUALITY_ORDER if q in quals]

    hosts: set[str] = set()
    for m in _EXTERNAL_HOST_RE.finditer(code):
        h = m.group(1).lower()
        if h.endswith(_IGNORE_HOSTS):
            continue
        hosts.add(h)
    out["externalHosts"] = sorted(hosts)

    official = [h for h in hosts if any(o in h for o in _OFFICIAL_HOSTS)]
    non_official = [h for h in hosts
                    if not any(o in h for o in _OFFICIAL_HOSTS)]
    if non_official:
        out["kind"] = "proxy"
    elif official:
        out["kind"] = "self-contained"
    return out


def _check_one(item: dict[str, Any], active_id: str | None,
               exe_path=None) -> ScriptCheck:
    chk = ScriptCheck(
        id=item.get("id", ""),
        name=item.get("name", ""),
        version=str(item.get("version") or ""),
        author=str(item.get("author") or ""),
        scriptChars=int(item.get("scriptChars") or 0),
        modified=bool(item.get("modified")),
        active=(item.get("id") == active_id),
    )

    # 取源码（用于分析）—— ScriptEntry.script 就是明文源码
    code = ""
    try:
        entries = script_store.load_entries(exe_path=exe_path)
        for e in entries:
            if getattr(e, "id", None) == chk.id:
                code = getattr(e, "script", "") or ""
                break
    except Exception as exc:                       # noqa: BLE001
        chk.status = "fail"
        chk.issues.append(f"无法读取脚本：{type(exc).__name__}: {exc}")
        chk.hint = "脚本文件损坏；建议从仓库重装"
        return chk

    # 字符数以实际源码为准（service 返回的 scriptChars 可能不同）
    if code:
        chk.scriptChars = len(code)

    info = _extract_from_source(code)
    chk.sources = info["sources"]
    chk.qualities = info["qualities"]
    chk.hasMetaBlock = info["hasMetaBlock"]
    chk.externalHosts = info["externalHosts"]
    chk.kind = info["kind"]

    # --- 规则 ---
    if chk.scriptChars < SHELL_THRESHOLD:
        chk.status = "fail" if chk.active else "warn"
        chk.issues.append(
            f"仅 {chk.scriptChars} 字符（正常应 ≥{SHELL_THRESHOLD}）"
            "—— 疑似空壳，很可能拿不到播放地址")
        chk.hint = "换用其它脚本：lx script enable <名字>"
    elif not chk.hasMetaBlock:
        if chk.status == "ok":
            chk.status = "warn"
        chk.issues.append("头部缺 @name/@version/@author 注释块（LX 靠它读元信息）")

    if chk.modified:
        # ⚠️ 只有"CLI 装的"脚本才有哈希记录可比。用户从 LX GUI 导入的脚本
        #    installedFrom 为空，此时 modified=True 是**误报**，不应告警。
        if item.get("installedFrom") or item.get("installedUrl"):
            chk.issues.append("内容与 CLI 记录哈希不符（疑似被手动修改）")
            if chk.status == "ok":
                chk.status = "warn"

    if chk.kind == "proxy" and chk.externalHosts:
        chk.issues.append(
            "转发型脚本，依赖第三方后端："
            + ", ".join(chk.externalHosts[:3])
            + "（后端挂了则脚本失效）")

    if not chk.sources:
        chk.issues.append("未能识别支持的平台（可能被强混淆）")

    if not chk.hint and chk.active and chk.status != "ok":
        chk.hint = "这是**当前启用**的脚本，建议先换一个"
    return chk


def _format_human(checks: list[ScriptCheck]) -> str:
    lines = ["", "音源脚本体检报告", "=" * 52, ""]
    mark = {"ok": "✓ OK  ", "warn": "! WARN", "fail": "✗ FAIL"}
    order = {"fail": 0, "warn": 1, "ok": 2}
    for c in sorted(checks, key=lambda x: (order.get(x.status, 3),
                                           -x.scriptChars)):
        tag = "   ← 当前启用" if c.active else ""
        lines.append(f"  {mark[c.status]}  {c.name}  v{c.version}{tag}")
        lines.append(f"          {c.scriptChars:,} 字符  "
                     f"类型={c.kind or '?'}  "
                     f"平台={','.join(c.sources) or '?'}"
                     + (f"  音质={','.join(c.qualities)}" if c.qualities else ""))
        for i in c.issues:
            lines.append(f"          • {i}")
        if c.hint:
            lines.append(f"          → {c.hint}")
        lines.append("")

    oks = [c for c in checks if c.status == "ok"]
    warns = [c for c in checks if c.status == "warn"]
    fails = [c for c in checks if c.status == "fail"]
    lines.append(f"汇总: {len(oks)} 正常  {len(warns)} 警告  {len(fails)} 有问题")

    active = next((c for c in checks if c.active), None)
    if active:
        lines.append(f"当前启用: {active.name}  [{active.status}]")
        if active.status != "ok":
            good = [c for c in checks
                    if c.status == "ok" and c.scriptChars >= SHELL_THRESHOLD]
            if good:
                lines.append(f"  建议换成: {good[0].name}")
                lines.append(f'  命令:     lx script enable "{good[0].name}"'
                             "   (需先关闭 LX)")
    return "\n".join(lines)


@click.command("doctor")
@json_option
@pass_ctx
@wrap_errors
def script_doctor_cmd(ctx: Ctx) -> None:
    """体检已装音源脚本（找空壳/失效/被改过的）。

    排查"搜得到但播不了 / 下载失败"时优先用它。
    """
    items = script_service.list_scripts(exe_path=ctx.exe)
    active_id = script_service.get_active_source(exe_path=ctx.exe)

    checks = [_check_one(it, active_id, ctx.exe) for it in items]

    if ctx.json:
        emit(ctx, "", {
            "active": active_id,
            "count": len(checks),
            "shellThreshold": SHELL_THRESHOLD,
            "scripts": [asdict(c) for c in checks],
        })
    else:
        emit(ctx, _format_human(checks), {"count": len(checks)})
