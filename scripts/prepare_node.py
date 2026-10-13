"""准备便携版 Node（供 CLI 执行 JS 音源脚本用）。

用途：用户机器没装 Node 时，也能用 `lx download url/get`。

用法::

    python scripts/prepare_node.py            # 下载并解压到 tools/node/
    python scripts/prepare_node.py --check    # 只校验现有安装

产物：``tools/node/node.exe`` + ``tools/node/MANIFEST.json``（含 sha256）

> ⚠️ 便携 Node 不影响仓库：``tools/node/`` 会被 .gitignore 忽略
> （二进制太大），只随**发布 zip** 分发。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NODE_DIR = ROOT / "tools" / "node"
MANIFEST = NODE_DIR / "MANIFEST.json"

#: 优先用这个 LTS（实测 zip 35.9MB）
NODE_VERSION = "v24.21.0"

#: 需要的文件（便携版解压后只保留必需项，省空间）
KEEP = (
    "node.exe",
    "LICENSE",
    "README.md",
)


def _repo_root() -> Path:
    return ROOT


def find_system_node() -> tuple[str, str]:
    exe = shutil.which("node")
    if not exe:
        return "", ""
    try:
        v = subprocess.run([exe, "--version"], capture_output=True,
                           text=True, timeout=15).stdout.strip()
    except Exception:
        v = ""
    return exe, v


def download_node(version: str = NODE_VERSION) -> Path:
    """下载便携 Node zip 并解压 ``node.exe`` 到 tools/node/。"""
    arch = "x64" if platform.machine().endswith("64") else "x86"
    name = f"node-{version}-win-{arch}"
    url = f"https://nodejs.org/dist/{version}/{name}.zip"

    print(f"下载 {url}")
    tmpd = Path(tempfile.mkdtemp(prefix="nodezh_"))
    zpath = tmpd / f"{name}.zip"
    try:
        with urllib.request.urlopen(url, timeout=300) as r:
            data = r.read()
        zpath.write_bytes(data)
        size_mb = len(data) / 1024 / 1024
        print(f"  已下载 {size_mb:.1f} MB")

        NODE_DIR.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zpath) as zf:
            for member in zf.namelist():
                base = os.path.basename(member)
                if base in KEEP and not member.endswith("/"):
                    with zf.open(member) as src, \
                            (NODE_DIR / base).open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    print(f"  提取 {base}")

        if not (NODE_DIR / "node.exe").is_file():
            raise SystemExit("解压后未找到 node.exe")

        # 记录清单
        exe = NODE_DIR / "node.exe"
        try:
            ver = subprocess.run([str(exe), "--version"], capture_output=True,
                                 text=True, timeout=20).stdout.strip()
        except Exception:
            ver = version
        manifest = {
            "version": ver or version,
            "source": url,
            "arch": arch,
            "files": [
                {"name": p.name, "size": p.stat().st_size,
                 "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                for p in sorted(NODE_DIR.iterdir()) if p.is_file()
            ],
        }
        MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        total = sum(f["size"] for f in manifest["files"])
        print(f"\n就绪：{exe}")
        print(f"  版本: {manifest['version']}")
        print(f"  体积: {total/1024/1024:.1f} MB")
        return exe
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)


def verify() -> int:
    if not MANIFEST.is_file():
        print("[FAIL] 缺少 tools/node/MANIFEST.json，请先跑 prepare_node.py")
        return 1
    mf = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bad = []
    for f in mf["files"]:
        p = NODE_DIR / f["name"]
        if not p.is_file():
            bad.append(f"缺失 {f['name']}")
            continue
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        if h != f["sha256"]:
            bad.append(f"哈希不符 {f['name']}")
    if bad:
        print("[FAIL] " + "; ".join(bad))
        return 1
    exe = NODE_DIR / "node.exe"
    try:
        v = subprocess.run([str(exe), "--version"], capture_output=True,
                           text=True, timeout=20).stdout.strip()
    except Exception as exc:
        print(f"[FAIL] 无法执行 node.exe: {exc}")
        return 1
    print(f"[OK] 便携 Node {v} 可用（{len(mf['files'])} 个文件）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验")
    ap.add_argument("--version", default=NODE_VERSION, help="Node 版本")
    ap.add_argument("--force", action="store_true", help="已存在也重新下载")
    args = ap.parse_args()

    if args.check:
        return verify()

    if (NODE_DIR / "node.exe").is_file() and not args.force:
        print("已存在 tools/node/node.exe（用 --force 重新下载）")
        return verify()

    sys_node, sys_ver = find_system_node()
    if sys_node:
        print(f"（检测到系统 Node：{sys_node} {sys_ver} —— 仍会准备便携版以便分发）")

    download_node(args.version)
    return verify()


if __name__ == "__main__":
    sys.exit(main())
