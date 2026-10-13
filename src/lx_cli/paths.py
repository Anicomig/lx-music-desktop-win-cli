"""路径解析：可移植性核心（P1–P4）。

设计目标（见 ``docs/planning/05-交付要求.md``）：

* **P1 换 CLI 目录/改名后仍可用** —— 不硬编码 CLI 自身路径；
  入口脚本按**自身文件位置**推导 ``src/``
* **P2 多种安装方式** —— 支持免安装直接跑（``run.bat`` / ``lx.py``）、
  ``pip install``、以及运行期不依赖安装
* **P3 跨机器/跨账号自动定位 LX 数据** —— 只依赖 ``APPDATA`` 环境变量
  （Windows）与平台默认位置，绝不硬编码用户名
* **P4 查找 LX 安装目录** —— 除固定候选外，主动搜索注册表与常见安装根目录

LX 数据位置（``lx-music-desktop/src/main/app.ts:127-143``）::

    userData/            <- Electron app.getPath('userData')
    └── LxDatas/         <- global.lxDataPath（应用所有数据）

``userData``：

* Windows 默认：``%APPDATA%\\lx-music-desktop``
* Windows portable：``<exe dir>\\portable\\userData``（仅当 ``<exe dir>\\portable`` 存在）
* macOS：``~/Library/Application Support/lx-music-desktop``
* Linux：``$XDG_CONFIG_HOME/lx-music-desktop`` 或 ``~/.config/lx-music-desktop``
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

# 数据库相关表
LIST_TABLES = ("my_list", "my_list_music_info", "my_list_music_info_order")

# LX 可执行文件名
EXE_NAME = "lx-music-desktop.exe" if sys.platform == "win32" else "lx-music-desktop"


# ================================================================ P1：自身位置


def package_root() -> Path:
    """lx_cli 包所在目录（不依赖调用方的工作目录）。"""
    return Path(__file__).resolve().parent


def project_root() -> Path:
    """CLI 项目根（含 ``pyproject.toml`` 与 ``src/`` 的那一层）。

    用于"免安装运行"时把 ``src`` 加进 ``sys.path``。
    包位于 ``<root>/src/lx_cli/``，故上溯两级。
    """
    return package_root().parent.parent


def src_dir() -> Path:
    """源码目录 ``<root>/src``（包所在的那一层）。"""
    return package_root().parent


def ensure_importable() -> bool:
    """确保 ``lx_cli`` 可被导入 —— 支持"换目录/改名后直接跑"。

    把 :func:`src_dir` 加入 ``sys.path``（若尚未存在）。

    :returns: 是否新加入了路径（已存在或非源码布局时返回 False）

    注意：若已 ``pip install``，``package_root()`` 位于 site-packages
    （``<site-packages>/lx_cli``，其 parent 不以 ``src`` 命名），
    此时不需要也不应该改 ``sys.path`` —— 返回 False。
    """
    src = src_dir()
    if src.name != "src" or not (src / "lx_cli").is_dir():
        return False                     # 已安装到 site-packages，无需处理
    s = str(src)
    if s in sys.path:
        return False
    sys.path.insert(0, s)
    return True


# ================================================================ P3：LX 数据


def _config_home_dir() -> Path:
    """非 Windows 的 ``userData``。"""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "lx-music-desktop"
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else (Path.home() / ".config")
    return root / "lx-music-desktop"


def _windows_appdata() -> Path | None:
    """Windows ``%APPDATA%``（**不硬编码用户名** —— 读环境变量）。"""
    roaming = os.environ.get("APPDATA")
    if roaming:
        return Path(roaming)
    # 兜底：USERPROFILE\AppData\Roaming
    profile = os.environ.get("USERPROFILE")
    if profile:
        return Path(profile) / "AppData" / "Roaming"
    return None


def user_data_dir(exe_path: Path | None = None) -> Path:
    """Electron ``userData`` 目录（支持 portable 覆盖 + 跨机器）。

    :param exe_path: 已知 exe 路径时，会检查其同级 ``portable/`` 目录
    """
    if exe_path is not None:
        exe = Path(exe_path)
        portable_root = exe.parent / "portable"
        if portable_root.is_dir():
            # app.ts:130 -> app.setPath('userData', <portable>/userData)
            return portable_root / "userData"

    if sys.platform == "win32":
        base = _windows_appdata()
        if base is None:
            raise RuntimeError(
                "无法确定用户数据目录：APPDATA 与 USERPROFILE 环境变量都未设置。\n"
                "请用 --exe 指定 LX 安装位置，或设置 LX_DATA_DIR。")
        return base / "lx-music-desktop"

    # 非 Windows：也允许 APPDATA（Wine / 交叉环境）
    if os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "lx-music-desktop"
    return _config_home_dir()


def _env_data_dir() -> Path | None:
    """``LX_DATA_DIR`` 环境变量覆盖（最后兜底，用于极端情况）。"""
    v = os.environ.get("LX_DATA_DIR")
    return Path(v) if v else None


def lx_datas_dir(exe_path: Path | None = None) -> Path:
    """``LxDatas`` 目录。

    ``LX_DATA_DIR`` 环境变量可整体覆盖（用于非标准部署）：

    * 指向 ``.../LxDatas`` → 原样使用
    * 指向其它目录        → 视为 ``userData``，自动补 ``LxDatas``
    """
    override = _env_data_dir()
    if override is not None:
        if override.name.lower() == "lxdatas":
            return override
        return override / "LxDatas"
    return user_data_dir(exe_path) / "LxDatas"


def user_api_path(exe_path: Path | None = None) -> Path:
    """``user_api.json`` —— 已导入的音源脚本。

    ``script`` = ``"gz_" + base64(zlib.compress(raw))``（**zlib 不是 gzip**）。
    """
    return lx_datas_dir(exe_path) / "user_api.json"


def config_v2_path(exe_path: Path | None = None) -> Path:
    return lx_datas_dir(exe_path) / "config_v2.json"


def data_json_path(exe_path: Path | None = None) -> Path:
    return lx_datas_dir(exe_path) / "data.json"


def db_path(exe_path: Path | None = None, override: Path | str | None = None) -> Path:
    if override is not None:
        return Path(override)
    return lx_datas_dir(exe_path) / "lx.data.db"


def scripts_meta_path(exe_path: Path | None = None) -> Path:
    """CLI 自管的音源脚本哈希清单（LX 不读）。"""
    return lx_datas_dir(exe_path) / "lx_cli_scripts_meta.json"


def data_dir_report(exe_path: Path | None = None) -> dict:
    """诊断用：数据目录定位过程与结果（``lx where`` 展示）。"""
    base = None
    if sys.platform == "win32":
        base = _windows_appdata()
    return {
        "platform": sys.platform,
        "APPDATA": os.environ.get("APPDATA") or "",
        "USERPROFILE": os.environ.get("USERPROFILE") or "",
        "XDG_CONFIG_HOME": os.environ.get("XDG_CONFIG_HOME") or "",
        "LX_DATA_DIR": os.environ.get("LX_DATA_DIR") or "",
        "resolved_userData": str(user_data_dir(exe_path)),
        "resolved_LxDatas": str(lx_datas_dir(exe_path)),
        "exists": lx_datas_dir(exe_path).is_dir(),
    }


# ================================================================ P4：查找 exe


def _candidate_paths() -> list[Path]:
    """常见安装位置（跨机器通用，含可选的盘符扫描）。"""
    if sys.platform == "win32":
        roots = [
            Path(r"C:\Program Files"),
            Path(r"C:\Program Files (x86)"),
        ]
        # 其它盘符（D:/E:/…）也试一遍 —— 换电脑后盘符常变
        for letter in "DEFGH":
            drive = Path(f"{letter}:\\")
            if drive.exists():
                roots.append(drive / "Program Files")
                roots.append(drive / "Program Files (x86)")
        out: list[Path] = []
        for r in roots:
            out.append(r / "lx-music-desktop" / EXE_NAME)
        # 便携版常见位置
        out += [
            Path.home() / "lx-music-desktop" / EXE_NAME,
            Path.home() / "Desktop" / "lx-music-desktop" / EXE_NAME,
            Path(os.environ.get("LOCALAPPDATA") or "") / "Programs"
            / "lx-music-desktop" / EXE_NAME,
        ]
        return [p for p in out if str(p)]
    if sys.platform == "darwin":
        return [Path("/Applications/lx-music-desktop.app/Contents/MacOS/lx-music-desktop")]
    return [
        Path("/opt/lx-music-desktop/lx-music-desktop"),
        Path("/usr/local/bin/lx-music-desktop"),
        Path("/usr/bin/lx-music-desktop"),
        Path.home() / ".local" / "bin" / "lx-music-desktop",
    ]


def _find_on_path() -> Path | None:
    """PATH 上是否有 lx-music-desktop（有些安装方式会加进去）。"""
    found = shutil.which("lx-music-desktop") or shutil.which(EXE_NAME)
    return Path(found) if found else None


def _find_in_windows_registry() -> Path | None:
    """P4：从 Windows 注册表查 LX 安装/卸载信息与 ``lxmusic://`` 协议处理程序。

    查三处：
    1. ``HKCU\\Software\\Classes\\lxmusic\\shell\\open\\command``
       （协议关联，实测指向 exe，**最可靠**）
    2. ``...\\Uninstall\\*`` 的 ``DisplayIcon`` / ``InstallLocation``
    3. ``HKLM`` 下的 ``App Paths``
    """
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None

    def _exe_from_command(cmd: str) -> Path | None:
        # 形如: "D:\path\lx-music-desktop.exe" "%1"
        cmd = cmd.strip()
        if cmd.startswith('"'):
            end = cmd.find('"', 1)
            if end > 0:
                p = Path(cmd[1:end])
                return p if p.exists() else None
        token = cmd.split(" ")[0]
        p = Path(token)
        return p if p.exists() else None

    # 1) lxmusic:// 协议关联
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Classes\lxmusic\shell\open\command",
        ) as k:
            cmd, _ = winreg.QueryValueEx(k, "")
            p = _exe_from_command(str(cmd))
            if p:
                return p
    except OSError:
        pass

    # 2) 卸载信息（HKCU + HKLM，32/64 位视图）
    uninstall_roots = [
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for hive, sub in uninstall_roots:
        try:
            with winreg.OpenKey(hive, sub) as root:
                for i in range(winreg.QueryInfoKey(root)[0]):
                    try:
                        name = winreg.EnumKey(root, i)
                        if "lx" not in name.lower() and "music" not in name.lower():
                            continue
                        with winreg.OpenKey(root, name) as item:
                            for value_name in ("DisplayIcon", "InstallLocation",
                                               "UninstallString"):
                                try:
                                    val, _ = winreg.QueryValueEx(item, value_name)
                                except OSError:
                                    continue
                                p = _exe_from_command(str(val).strip('"'))
                                if p and p.name.lower() == EXE_NAME.lower():
                                    return p
                                # InstallLocation 是目录
                                cand = Path(str(val).strip('"')) / EXE_NAME
                                if cand.exists():
                                    return cand
                    except OSError:
                        continue
        except OSError:
            continue

    # 3) App Paths
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, rf"Software\Microsoft\Windows\CurrentVersion"
                                      rf"\App Paths\{EXE_NAME}") as k:
                val, _ = winreg.QueryValueEx(k, "")
                p = Path(str(val).strip('"'))
                if p.exists():
                    return p
        except OSError:
            continue
    return None


def find_exe(exe_override: Path | None = None, *,
            search: bool = True) -> tuple[Path | None, str]:
    """P4：查找 LX 可执行文件，返回 ``(路径, 来源说明)``。

    查找顺序：

    1. 显式参数 ``exe_override``（来自 CLI 的 ``--exe`` 选项）
    2. 环境变量 ``LX_EXE``（显式覆盖）
    3. 固定候选路径（含各盘符 ``Program Files``）
    4. ``PATH``
    5. Windows 注册表（协议关联 / 卸载信息 / App Paths）
    6. 有界目录扫描（常见安装根下的 ``lx-music-desktop`` 目录）

    :param exe_override: CLI ``--exe`` 选项传入的路径
    :param search: 是否执行第 5/6 步（可能稍慢）
    """
    if exe_override:
        p = Path(exe_override)
        if p.exists():
            return p, "cli:--exe"
        return None, f"cli:--exe 指向的路径不存在：{p}"

    explicit = os.environ.get("LX_EXE")
    if explicit:
        p = Path(explicit)
        if p.exists():
            return p, "env:LX_EXE"
        return None, f"env:LX_EXE 指向的路径不存在：{p}"

    for p in _candidate_paths():
        try:
            if p.exists():
                return p, "candidate"
        except OSError:
            continue

    on_path = _find_on_path()
    if on_path:
        return on_path, "PATH"

    if search:
        reg = _find_in_windows_registry()
        if reg:
            return reg, "registry"

        scanned = _scan_common_roots()
        if scanned:
            return scanned, "scan"

    return None, "not-found"


def _scan_common_roots(max_entries: int = 400) -> Path | None:
    """有界扫描：常见安装根目录下找 ``lx-music-desktop`` 文件夹。

    为避免卡顿：限制扫描的根目录与条目数，只找一层子目录。
    """
    roots: list[Path] = []
    if sys.platform == "win32":
        for env_key in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            v = os.environ.get(env_key)
            if v:
                roots.append(Path(v))
        for letter in "DEFGH":
            d = Path(f"{letter}:\\")
            try:
                if d.exists():
                    roots.append(d)
            except OSError:
                continue
    else:
        roots += [Path("/opt"), Path("/usr/local"), Path.home()]

    seen = 0
    for root in roots:
        try:
            if not root.is_dir():
                continue
            for child in root.iterdir():
                seen += 1
                if seen > max_entries:
                    return None
                if not child.is_dir():
                    continue
                if "lx" not in child.name.lower():
                    continue
                cand = child / EXE_NAME
                if cand.exists():
                    return cand
        except (OSError, PermissionError):
            continue
    return None


def default_exe_path() -> Path:
    """兼容旧接口：返回最佳猜测（找不到时返回最通用兜底，由调用方报错）。"""
    found, _ = find_exe(search=False)
    if found:
        return found
    return _candidate_paths()[0]
