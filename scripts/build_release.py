"""构建发布 zip。

用法::

    python scripts/build_release.py           # 自动确定版本（git tag 或 pyproject）
    python scripts/build_release.py v0.2.0    # 指定版本
    python scripts/build_release.py v0.2.0 --no-upload   # 只构建，不发布

产出：``dist/lx-music-desktop-win-cli-vX.Y.Z.zip``
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
PYPROJECT = ROOT / "pyproject.toml"

# 排除规则：跟 .gitignore 一致（公开仓库口径）
# 注：.gitignore 本身要打进 zip（用户应该能看到/审阅排除规则）
# ⚠️ 路径段（**单层目录名**，不要写"a/b"，要写"a"和"b"两个）
EXCLUDE_PATH_FRAGMENTS = {
    "planning",            # docs/planning
    "_backup",             # _backup
    "__pycache__",
    ".pytest_cache",
    ".git",
    "dist",
    "build",
}
EXCLUDE_GLOBS = {
    "*.pyc", "*.pyo", "*.pyd",
    "*.egg-info", ".vscode", ".idea", "*.tmp", "*.bak",
    ".DS_Store", "Thumbs.db", "desktop.ini",
    "_msg.txt", "COMMIT_MSG*.txt",
    # 真实数据/配置（按文件名）
    "user_api.json", "config_v2.json", "data.json",
    "*.db-wal", "*.db-shm", "*.db-journal",
    # 同步密钥
    "*syncAuthKey*.json",
    "lx_cli_scripts_meta.json",
}


def should_exclude(p: Path) -> bool:
    """是否应排除该路径。

    两类规则：
    * 路径前缀：``docs/planning``、``_backup`` 等整段目录
    * 文件名/后缀模式：``*.pyc``、``user_api.json`` 等
    """
    parts = set(p.parts)
    # 路径前缀规则
    for frag in EXCLUDE_PATH_FRAGMENTS:
        if frag in parts:
            return True
    # 文件名/后缀规则
    rel = p.name
    if rel in EXCLUDE_GLOBS:
        return True
    return any(p.match(g) for g in EXCLUDE_GLOBS)


def read_version_from_pyproject() -> str:
    """从 pyproject 读版本号。"""
    import tomllib
    with PYPROJECT.open("rb") as f:
        d = tomllib.load(f)
    return d["project"]["version"]


def write_version_to_pyproject(new: str) -> None:
    """改 pyproject 里的 version 字段。"""
    text = PYPROJECT.read_text(encoding="utf-8")
    new_text = re.sub(
        r'^(version\s*=\s*")[^"]*(")',
        rf'\g<1>{new}\g<2>',
        text, count=1, flags=re.M,
    )
    if new_text == text:
        raise SystemExit("未找到 pyproject 中的 version 字段")
    PYPROJECT.write_text(new_text, encoding="utf-8")


def get_git_info() -> tuple[str, bool, str]:
    """返回 (short_sha, dirty, head_subject)。

    ⚠️ Windows 下 git 的 stdout 在 GBK 控制台里会丢字节；强制 UTF-8 + 容错解码。
    """
    common = dict(capture_output=True, text=True, cwd=ROOT, env=os.environ,
                  encoding="utf-8", errors="replace")
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], **common).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], **common).stdout.strip())
    subject = subprocess.run(["git", "log", "-1", "--pretty=%s"], **common).stdout.strip()
    return sha, dirty, subject


def build_zip(version: str, src_dir: Path) -> Path:
    """打 zip：根目录直接是仓库文件（不含顶层 lx-cli-v2/）。"""
    zip_name = f"lx-music-desktop-win-cli-v{version}.zip"
    zip_path = DIST / zip_name
    DIST.mkdir(exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()

    files = [p for p in src_dir.rglob("*") if p.is_file() and not should_exclude(p)]
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as zf:
        for p in files:
            rel = p.relative_to(src_dir)
            zf.write(p, rel.as_posix())

    return zip_path


def verify_zip(zip_path: Path) -> None:
    """解压到临时目录，跑：版本 + 测试 + 必要文件存在性。"""
    print(f"  验证：解压 {zip_path.name} → 跑测试")
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp)
        run_env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        run_env["PYTHONIOENCODING"] = "utf-8"

        # 1. version
        r = subprocess.run([sys.executable, "run.py", "--version"],
                           cwd=tmp, capture_output=True, text=True,
                           encoding="utf-8", env=run_env, timeout=30)
        if r.returncode != 0:
            raise SystemExit(f"run.py --version 失败: {r.stdout}{r.stderr}")
        print(f"    version OK: {r.stdout.strip()}")

        # 2. 关键文件
        for must in ("README.md", "pyproject.toml", "run.py", "lx.bat",
                     ".gitignore", "src/lx_cli/__init__.py",
                     "skills/lx-cli/SKILL.md", "tests/fixtures/lx.data.db"):
            if not (Path(tmp) / must).is_file():
                raise SystemExit(f"缺少关键文件: {must}")
        print("    关键文件齐全")

        # 3. 测试
        r = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q"],
                           cwd=tmp, capture_output=True, text=True,
                           encoding="utf-8", env=run_env, timeout=300)
        if r.returncode != 0:
            tail = "\n".join((r.stdout or "").splitlines()[-15:])
            raise SystemExit(f"测试失败：\n{tail}")
        last = (r.stdout or "").strip().splitlines()[-1]
        print(f"    测试 OK: {last}")

        # 4. 排除项确实没被打进 zip
        #    注意：检查的是"zip 根目录下面**作为路径片段**出现"的禁止项，
        #    不能用 rglob 走子串，否则 tests 用的 fixture/tmp 路径会误报。
        for entry in os.listdir(tmp):
            if entry in {"docs", "tests", "src", "skills", "scripts", "tools"}:
                full = Path(tmp) / entry
                for forbidden in ("docs/planning", "_backup"):
                    if any(part == "planning" or part == "_backup"
                           for part in (full).parts):
                        raise SystemExit(f"zip 含排除目录: {forbidden}")
                # 文件级别的禁止项
                bad_files = ("user_api.json", "config_v2.json", "data.json")
                for f in full.rglob("*"):
                    if not f.is_file():
                        continue
                    if f.name in bad_files or f.suffix in (".db-wal", ".db-shm"):
                        raise SystemExit(f"zip 包含排除文件: {f.relative_to(tmp)}")
                    if "syncAuthKey" in f.name or f.name == "lx_cli_scripts_meta.json":
                        raise SystemExit(f"zip 含密钥: {f.relative_to(tmp)}")
        print("    排除项校验通过")


def create_github_release(version: str, zip_path: Path, notes: str) -> None:
    """用 gh 创建 release + 上传 zip。"""
    gh = Path(r"D:\Program Files\GitHub CLI\gh.exe")
    if not gh.exists():
        raise SystemExit(f"找不到 gh: {gh}")
    tag = f"v{version}"

    # tag 已存在则跳过创建，仅上传 asset
    tag_check = subprocess.run(
        [str(gh), "release", "view", tag, "--repo", "Anicomig/lx-music-desktop-win-cli"],
        capture_output=True, text=True, encoding="utf-8")
    if tag_check.returncode != 0:
        print(f"  创建 release {tag} ...")
        r = subprocess.run(
            [str(gh), "release", "create", tag,
             "--repo", "Anicomig/lx-music-desktop-win-cli",
             "--title", f"lx-music-desktop-win-cli v{version}",
             "--notes", notes],
            capture_output=True, text=True, encoding="utf-8")
        if r.returncode != 0:
            raise SystemExit(f"创建 release 失败：\n{r.stderr}")
    else:
        print(f"  release {tag} 已存在，直接上传")

    print(f"  上传 {zip_path.name} ...")
    r = subprocess.run(
        [str(gh), "release", "upload", tag, str(zip_path),
         "--repo", "Anicomig/lx-music-desktop-win-cli", "--clobber"],
        capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise SystemExit(f"上传失败：\n{r.stderr}")
    print(f"  ✓ https://github.com/Anicomig/lx-music-desktop-win-cli/releases/tag/{tag}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("version", nargs="?",
                    help="版本号 (例 v0.2.0)。省略则用 pyproject 中的版本")
    ap.add_argument("--no-upload", action="store_true",
                    help="只构建 zip，不创建 GitHub release")
    ap.add_argument("--no-bump", action="store_true",
                    help="不修改 pyproject 版本（默认会同步）")
    ap.add_argument("--allow-dirty", action="store_true",
                    help="允许工作树有未提交修改")
    args = ap.parse_args()

    # 版本
    if args.version:
        version = args.version.lstrip("v")
    else:
        version = read_version_from_pyproject()
    print(f"目标版本: v{version}")

    # 工作树检查
    sha, dirty, subject = get_git_info()
    if dirty and not args.allow_dirty:
        print("  ⚠️ 工作树有未提交修改（可用 --allow-dirty 强制）")
        return 1

    # 同步 pyproject（除非显式禁用）
    if not args.no_bump and read_version_from_pyproject() != version:
        print(f"  同步 pyproject: {read_version_from_pyproject()} → {version}")
        write_version_to_pyproject(version)

    # 构建
    print("构建 zip ...")
    zip_path = build_zip(version, ROOT)
    size_mb = zip_path.stat().st_size / 1024 / 1024
    print(f"  ✓ {zip_path.name}  ({size_mb:.2f} MB)")

    # 验证
    print("验证 ...")
    verify_zip(zip_path)

    # 发布
    if not args.no_upload:
        notes = (
            f"## lx-music-desktop-win-cli v{version}\n\n"
            f"**Commit:** `{sha}` — {subject}\n"
            f"**Build:** {datetime.now():%Y-%m-%d %H:%M:%S}\n\n"
            f"### 简介\n"
            f"洛雪音乐助手（LX Music Desktop）的 Windows 命令行工具。"
            f"下载后解压即用，免安装、免修改路径。\n\n"
            f"### 快速开始\n"
            f"```\n"
            f"unzip lx-music-desktop-win-cli-v{version}.zip\n"
            f"cd lx-music-desktop-win-cli\n"
            f"python -m pip install click requests\n"
            f"python run.py --help\n"
            f"```\n\n"
            f"详见仓库 README。\n"
        )
        create_github_release(version, zip_path, notes)
    else:
        print(f"\n仅构建模式，zip 在: {zip_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
