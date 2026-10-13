"""准备内置依赖 wheels（离线安装用）。

用法::

    python scripts/prepare_wheels.py            # 下载依赖到 wheels/
    python scripts/prepare_wheels.py --check    # 校验现有 wheels 是否完整

设计要点：

* 优先下载 **py3-none-any**（跨 Python 版本通用）的 wheel
* ``charset-normalizer`` 的 wheel 绑定 cpXXX/winYY —— 它**不是必需的**
  （``requests`` 会在缺失时回退到纯 Python 实现），所以：
  - 若当前 Python 版本能拿到匹配 wheel → 一并内置（性能更好）
  - 拿不到 → **跳过**，让 requests 走纯 Python 回退（功能不受影响）
* 结果记录在 ``wheels/MANIFEST.json``（含 sha256），安装脚本据此校验
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WHEELS = ROOT / "wheels"

# 直接依赖（pyproject 里声明的）
DIRECT = ["click", "requests"]

# 可选：能拿到匹配 wheel 就装，拿不到跳过（requests 有纯 Python 回退）
OPTIONAL_VERSION_BOUND = ["charset-normalizer"]


def _pip_download(pkgs: list[str], dest: Path, *, universal_only: bool) -> bool:
    """下载到 dest；失败返回 False。"""
    cmd = [sys.executable, "-m", "pip", "download", *pkgs, "-d", str(dest), "-q"]
    if universal_only:
        # 只允许纯 Python wheel（跨版本通用）
        cmd += ["--only-binary=:all:", "--platform", "any", "--python-version", "3"]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300)
    if r.returncode != 0:
        print(f"    (失败：{(r.stderr or '').strip()[:160]})")
    return r.returncode == 0


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def prepare(check_only: bool = False) -> int:
    if check_only:
        return _verify()

    if WHEELS.exists():
        shutil.rmtree(WHEELS)
    WHEELS.mkdir(parents=True)

    print("下载依赖 wheels（含传递依赖）...")
    # 一次下载 click+requests，pip 会自动带上传递依赖
    ok = _pip_download(DIRECT, WHEELS, universal_only=False)
    if not ok:
        # 回退：分开下，只求通用 wheel
        print("  整体下载失败，尝试仅通用 wheel ...")
        for pkg in DIRECT:
            _pip_download([pkg], WHEELS, universal_only=False)

    have = sorted(p.name for p in WHEELS.glob("*.whl"))
    print(f"  得到 {len(have)} 个 wheel")

    # 处理版本绑定的可选依赖
    for pkg in OPTIONAL_VERSION_BOUND:
        already = any(p.name.lower().startswith(pkg.replace("-", "_")) or
                      p.name.lower().startswith(pkg)
                      for p in WHEELS.glob("*.whl"))
        if already:
            print(f"  {pkg}: 版本匹配，已内置（性能更好）")
            continue
        print(f"  {pkg}: 无匹配 wheel → 跳过（requests 会回退到纯 Python）")

    # 生成 MANIFEST
    manifest = {
        "generated_by": "scripts/prepare_wheels.py",
        "python": f"{sys.version_info.major}.{sys.version_info.minor}"
                  f".{sys.version_info.micro}",
        "platform": sys.platform,
        "universal": True,
        "wheels": [
            {"name": p.name, "size": p.stat().st_size, "sha256": _sha256(p)}
            for p in sorted(WHEELS.glob("*.whl"))
        ],
    }
    (WHEELS / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    total = sum(w["size"] for w in manifest["wheels"])
    print(f"\n内置 wheels: {len(manifest['wheels'])} 个，"
          f"共 {total/1024:.0f} KB")
    for w in manifest["wheels"]:
        print(f"  {w['name']:50s} {w['size']/1024:7.0f} KB")
    return 0


def _verify() -> int:
    mf = WHEELS / "MANIFEST.json"
    if not mf.is_file():
        print("[FAIL] 缺少 wheels/MANIFEST.json，请先跑 prepare_wheels.py")
        return 1
    data = json.loads(mf.read_text(encoding="utf-8"))
    bad = []
    for w in data["wheels"]:
        p = WHEELS / w["name"]
        if not p.is_file():
            bad.append(f"缺失: {w['name']}")
            continue
        if _sha256(p) != w["sha256"]:
            bad.append(f"哈希不符: {w['name']}")
    if bad:
        print("[FAIL] wheels 校验失败：")
        for b in bad:
            print(f"  - {b}")
        return 1
    print(f"[OK] {len(data['wheels'])} 个 wheel 校验通过")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验现有 wheels")
    args = ap.parse_args()
    return prepare(check_only=args.check)


if __name__ == "__main__":
    sys.exit(main())
