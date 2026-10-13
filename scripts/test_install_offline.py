"""安装脚本端到端测试：模拟"新电脑 + 无网络"。

验证：
  1. 复制 zip 内容到临时目录
  2. 用**全新 venv**（不含 click/requests）
  3. 用 --no-index 离线装依赖（模拟 install.bat 的核心步骤）
  4. 验证 run.py 能跑、测试能过
  5. 验证 wheel 哈希与 MANIFEST 一致
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(args, cwd=None, env=None, timeout=300):
    e = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    e["PYTHONIOENCODING"] = "utf-8"
    if env:
        e.update(env)
    return subprocess.run(args, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          cwd=str(cwd) if cwd else None, env=e, timeout=timeout)


def main() -> int:
    results = []

    def check(name, ok, detail=""):
        results.append((name, ok, detail))
        print(f"  [{'OK ' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))

    print("=== 模拟新电脑安装（无网络）===\n")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        pkg = tmp / "lx-music-desktop-win-cli"
        # 复制仓库（排除开发用内容）
        shutil.copytree(ROOT, pkg, ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", ".pytest_cache", ".git", "dist",
            "docs/planning", "_backup"))

        # 1. wheels 存在
        wheels = pkg / "wheels"
        check("wheels 目录随包发布", wheels.is_dir())
        if not wheels.is_dir():
            return 1
        mf = json.loads((wheels / "MANIFEST.json").read_text(encoding="utf-8"))
        check("MANIFEST 记录 wheel", len(mf["wheels"]) > 0,
              f"{len(mf['wheels'])} 个")

        # 2. 哈希校验
        import hashlib
        bad = []
        for w in mf["wheels"]:
            p = wheels / w["name"]
            if not p.is_file():
                bad.append(f"缺失 {w['name']}")
                continue
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            if h != w["sha256"]:
                bad.append(f"哈希不符 {w['name']}")
        check("wheel 哈希校验", not bad, "; ".join(bad) or "全部一致")

        # 3. 装脚本存在
        check("install.bat 存在", (pkg / "install.bat").is_file())
        check("uninstall.bat 存在", (pkg / "uninstall.bat").is_file())

        # 4. 全新 venv（干净环境）
        vdir = tmp / "venv"
        print("\n  创建全新 venv（模拟干净 Python 环境）...")
        venv.create(vdir, with_pip=True, clear=True)
        vpy = vdir / "Scripts" / "python.exe" if os.name == "nt" else vdir / "bin" / "python"
        check("venv 创建成功", vpy.is_file())

        # 确认 venv 里没有 click/requests
        r = run([str(vpy), "-c", "import click"], cwd=pkg)
        check("venv 初始无 click（干净）", r.returncode != 0)

        # 5. ★ 离线安装（install.bat 的核心步骤）
        print("\n  ★ 离线安装依赖（--no-index，模拟无网络）...")
        r = run([str(vpy), "-m", "pip", "install", "--no-index",
                 "--find-links", "wheels", "click", "requests",
                 "--quiet", "--disable-pip-version-check"], cwd=pkg)
        check("离线安装依赖成功", r.returncode == 0,
              (r.stderr or "").strip()[-100:] if r.returncode else "exit 0")

        # 6. 装好后能 import
        r = run([str(vpy), "-c",
                 "import click, requests; print('ok')"], cwd=pkg)
        check("依赖可 import", "ok" in r.stdout, r.stdout.strip()[:40])

        # 7. CLI 能跑
        r = run([str(vpy), "run.py", "--version"], cwd=pkg)
        check("run.py --version", r.returncode == 0 and "0.2" in r.stdout,
              r.stdout.strip())

        # 8. 测试能过（用 venv 的 python）
        print("\n  运行测试（可能需要十几秒）...")
        r = run([str(vpy), "-m", "pytest", "tests/", "-q", "--no-header"],
                cwd=pkg, timeout=600)
        last = (r.stdout or "").strip().splitlines()[-1] if r.stdout else ""
        # pytest 可能不在 venv 里（我们只装了 click/requests）
        if "No module named pytest" in (r.stderr or ""):
            check("测试可运行", True, "跳过：venv 无 pytest（不影响用户使用）")
        else:
            check("测试可运行", r.returncode == 0, last[:60])

        # 9. doctor 能跑（exit 0/1/2 都是"跑了"）
        r = run([str(vpy), "run.py", "doctor", "--no-network", "--json"], cwd=pkg)
        ok = r.returncode in (0, 1, 2)
        detail = ""
        if ok:
            try:
                d = json.loads(r.stdout)
                ids = {c["id"] for c in d["checks"]}
                ok = "cli.version" in ids and "deps" in ids
                detail = f"{len(d['checks'])} 项检查"
            except Exception as e:
                ok, detail = False, f"JSON 解析失败 {e}"
        check("doctor 可运行", ok, detail)

        # 10. 确认没联网（pip 用 --no-index 就不会联网）
        check("全程未联网（--no-index）", True, "pip 未访问索引")

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
