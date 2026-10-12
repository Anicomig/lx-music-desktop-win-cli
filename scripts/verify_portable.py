"""移植性验收：验证"把 lx-cli-v2 文件夹拷到新电脑就能用"。

在**副本目录**里调用 ``run.py``，且**不设置 PYTHONPATH**，
模拟一台只有 Python、没有 pip 安装、没有本机配置的新电脑。

用法::

    python scripts/verify_portable.py [<cli-dir>]
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent


def run(args: list[str], cwd: Path, env: dict | None = None,
        timeout: float = 90) -> subprocess.CompletedProcess:
    e = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    e["PYTHONIOENCODING"] = "utf-8"
    if env:
        e.update(env)
    return subprocess.run(args, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          cwd=str(cwd), env=e, timeout=timeout)


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else None

    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))
        print(f"  [{'OK ' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))

    tmp_created = False
    if target is None:
        target = Path(tempfile.mkdtemp(prefix="lxport_")) / "lx-cli-v2"
        shutil.copytree(SRC, target, ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", ".pytest_cache", ".git"))
        tmp_created = True
        print(f"已复制到：{target}\n")
    else:
        print(f"使用既有目录：{target}\n")

    try:
        # 1. 最小启动
        p = run([sys.executable, "run.py", "--version"], target)
        check("python run.py --version", p.returncode == 0 and "0.2" in p.stdout,
              p.stdout.strip() or p.stderr.strip()[:80])

        # 2. 加载的是副本本身（不是别处的包）
        p = run([sys.executable, "-c",
                 "import sys; sys.path.insert(0,'src'); import lx_cli,os;"
                 "print(os.path.dirname(lx_cli.__file__))"], target)
        check("加载自副本目录", str(target) in p.stdout, p.stdout.strip()[-40:])

        # 3. 帮助可用
        p = run([sys.executable, "run.py", "--help"], target)
        ok = p.returncode == 0 and all(c in p.stdout for c in
                                       ("search", "playlist", "script", "db"))
        check("所有命令组可见", ok)

        # 4. 路径解析（P3/P4）
        p = run([sys.executable, "run.py", "where", "--json"], target)
        ok = p.returncode == 0
        detail = ""
        if ok:
            import json
            d = json.loads(p.stdout)
            ok = bool(d.get("LxDatas"))
            detail = Path(d["LxDatas"]).name
        check("where 解析数据目录", ok, detail)

        # 5. 从任意工作目录调用（绝对路径）
        p = run([sys.executable, str(target / "run.py"), "--version"], Path.home())
        check("从其它 cwd 调用", p.returncode == 0 and "0.2" in p.stdout)

        # 6. 测试可在副本里跑
        p = run([sys.executable, "-m", "pytest", "tests/", "-q", "--no-header"],
                target, timeout=300)
        tail = (p.stdout or "").strip().splitlines()[-1:] or [""]
        check("副本内测试可运行", p.returncode == 0, tail[0][:60])

        # 7. 检查依赖是否声明齐全（新电脑只需装这些）
        #    注：不能用 `python -S` 测 —— 那会禁用 site-packages，
        #    连第三方依赖 click/requests 都找不到，属预期行为而非移植性问题。
        p = run([sys.executable, "-c",
                 "import tomllib,pathlib;"
                 "d=tomllib.loads(pathlib.Path('pyproject.toml').read_text('utf-8'));"
                 "print('\\n'.join(d['project']['dependencies']))"], target)
        deps = [ln.strip() for ln in (p.stdout or "").splitlines() if ln.strip()]
        check("pyproject 声明了依赖", bool(deps), ", ".join(deps) or "无")
        missing = []
        for dep in deps:
            mod = dep.split(">=")[0].split("==")[0].split("[")[0].strip()
            mod = {"pyjwt": "jwt"}.get(mod, mod)
            r = run([sys.executable, "-c", f"import {mod}"], target)
            if r.returncode != 0:
                missing.append(mod)
        check("必需依赖均已安装", not missing, ", ".join(missing) or "全部就绪")

        # 8. 真实调用（只读，需网络）
        p = run([sys.executable, "run.py", "search", "yorushika",
                 "--limit", "2", "--json"], target)
        if p.returncode == 0:
            import json
            d = json.loads(p.stdout)
            check("真机搜索可用", d.get("count", 0) > 0, f"{d.get('count')} 首")
        else:
            check("真机搜索可用（网络相关，可忽略）", False, p.stderr[:60])
    finally:
        if tmp_created and "--keep" not in sys.argv:
            shutil.rmtree(target.parent, ignore_errors=True)

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n=== {passed}/{total} 通过 ===")
    if passed != total:
        print("失败项：")
        for n, ok, d in results:
            if not ok:
                print(f"  - {n}  {d}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
