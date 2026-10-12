"""真机冒烟测试：用已安装的 `lx` 命令做只读验证。

**只做只读操作**（搜索/状态/看库/看脚本），不写任何真实数据。
写操作需要关闭 LX，另行手动验证。

用法::

    python scripts/smoke_real.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def lx(*args: str, timeout: float = 90) -> tuple[int, str, str]:
    """调用**全局 lx 命令**（不带 PYTHONPATH，验证安装态可用）。"""
    import os
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run(["lx", *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env,
                       timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def jget(out: str):
    return json.loads(out)


def main() -> int:
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))
        print(f"  [{'OK ' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))

    print("=== 真机冒烟测试（只读）===\n")

    # 1. 版本
    code, out, err = lx("--version")
    check("lx --version", code == 0 and "0.2" in out, out.strip())

    # 2. where
    code, out, err = lx("where", "--json")
    ok = code == 0
    detail = ""
    if ok:
        try:
            d = jget(out)
            ok = bool(d.get("exe")) and bool(d.get("LxDatas"))
            detail = f"exe={Path(d['exe']).name}"
            exists = Path(d["LxDatas"]).is_dir()
            check("数据目录存在", exists, d["LxDatas"])
        except Exception as exc:
            ok, detail = False, f"JSON 解析失败：{exc}"
    check("lx where --json", ok, detail)

    # 3. 搜索（聚合）
    code, out, err = lx("search", "yorushika", "--limit", "3", "--json")
    if code == 0:
        d = jget(out)
        n = d.get("count", 0)
        plats = [p for p in d.get("platforms", [])]
        check("lx search 聚合", n > 0, f"{n} 首，平台={len(plats)}")
        if d.get("songs"):
            s = d["songs"][0]
            has = all(k in s for k in ("id", "name", "singer", "albumName",
                                       "source", "sourceLabel"))
            check("搜索结果字段齐全", has, f"source={s.get('source')} label={s.get('sourceLabel')}")
            # 来源必须是平台 id（不是脚本名）
            bad = [x for x in d["songs"]
                   if x.get("source") not in ("kg", "kw", "tx", "wy", "mg")]
            check("来源均为平台 id", not bad)
    else:
        check("lx search 聚合", False, f"exit={code} {err[:80]}")

    # 4. 单平台
    time.sleep(2)
    code, out, err = lx("search", "yorushika", "--source", "wy", "--limit", "2", "--json")
    ok = code == 0 and jget(out)["mode"] == "single" if code == 0 else False
    check("lx search 单平台", ok, f"mode={jget(out)['mode'] if code == 0 else '?'}")

    # 5. 数据库
    code, out, err = lx("db", "stats", "--json")
    if code == 0:
        d = jget(out)
        check("lx db stats", d.get("songs", 0) > 0,
              f"{d.get('lists')} 歌单 / {d.get('songs')} 首")
    else:
        check("lx db stats", False, err[:80])

    # 6. 歌单列表
    code, out, err = lx("playlist", "list", "--json")
    if code == 0:
        d = jget(out)
        names = [x["id"] for x in d["lists"]]
        check("lx playlist list", "default" in names and "love" in names,
              f"{len(d['lists'])} 个（含虚拟歌单）")
    else:
        check("lx playlist list", False, err[:80])

    # 7. 音源脚本
    code, out, err = lx("script", "list", "--json")
    if code == 0:
        d = jget(out)
        check("lx script list", d.get("count", 0) > 0,
              f"{d['count']} 个，启用={d.get('active', '')[:24]}")
        bad = [s for s in d.get("scripts", []) if not s.get("sha256")]
        check("脚本均可解码（有 sha256）", not bad)
    else:
        check("lx script list", False, err[:80])

    # 8. 状态
    code, out, err = lx("status", "--json")
    if code == 0:
        d = jget(out)
        check("lx status", "status" in d,
              f"status={d.get('status')!r} playing={d.get('playing')}")
        check("status 是字符串", isinstance(d.get("status"), str))
    else:
        check("lx status", False, err[:80])

    # 9. 错误契约
    code, out, err = lx("search", "x", "--source", "nope", "--json")
    ok = code == 2
    if ok:
        try:
            d = jget(out)
            ok = "error" in d and "code" in d["error"]
        except Exception:
            ok = False
    check("未知平台 → exit 2 + 结构化错误", ok, f"exit={code}")

    # 10. 只读保护
    code, out, err = lx("db", "query", "DELETE FROM my_list", "--json")
    check("写 SQL 被拒", code == 1, err.strip()[:60])

    # ---- 汇总 ----
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n=== {passed}/{total} 通过 ===")
    if passed != total:
        print("失败项：")
        for name, ok, detail in results:
            if not ok:
                print(f"  - {name}  {detail}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
