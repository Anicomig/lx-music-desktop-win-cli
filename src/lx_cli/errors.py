"""统一异常树与退出码映射。

设计目标（修复旧版缺陷）:

1. 旧版只有一个 ``LXError``，401/404/5xx/超时全混在一起，无法分类处理。
2. 旧版 ``main()`` 的 except 分支是**死代码**（Click standalone 模式会先 ``sys.exit``），
   导致未捕获异常时出现"exit 1 且 stdout/stderr 全空"的最坏情况。

这里定义分层异常，并由 :func:`exit_code_for` 集中映射；CLI 层用统一的 try/except
包裹，保证**任何失败都有明确输出与退出码**。
"""
from __future__ import annotations

# ---- 退出码约定（写入 docs/JSON-CONTRACT.md）----
EXIT_OK = 0
EXIT_RUNTIME = 1      # 一般运行时错误
EXIT_USAGE = 2        # 用法/参数错误
EXIT_LX_RUNNING = 3   # 需要先关闭 LX
EXIT_UPSTREAM = 4     # 网络/上游平台失败


class LxCliError(Exception):
    """所有 lx-cli 异常的基类。

    子类可覆盖 :attr:`exit_code`；:attr:`detail` 用于在 ``--json`` 下输出结构化信息。
    """

    exit_code: int = EXIT_RUNTIME
    code: str = "error"

    def __init__(self, message: str, *, detail: dict | None = None,
                 cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}
        self.cause = cause

    def to_json(self) -> dict:
        payload: dict = {"code": self.code, "message": self.message}
        if self.detail:
            payload["detail"] = self.detail
        return {"error": payload}


# ---------- 用法 ----------

class UsageError(LxCliError):
    exit_code = EXIT_USAGE
    code = "usage"


# ---------- 环境 / 前置条件 ----------

class LxNotRunningError(LxCliError):
    """需要 LX 运行（如 Open API 命令）但它没在跑。"""
    code = "lx_not_running"


class LxRunningError(LxCliError):
    """需要 LX 关闭（写 DB / 写 user_api.json）但它还在跑。"""
    exit_code = EXIT_LX_RUNNING
    code = "lx_running"


class PathError(LxCliError):
    """找不到 exe / 数据目录 / DB。"""
    code = "path"


# ---------- Open API（播放控制） ----------

class OpenApiError(LxCliError):
    exit_code = EXIT_UPSTREAM
    code = "openapi"


class OpenApiDisabled(OpenApiError):
    """端口不通或 401 —— 通常是开放 API 未启用。"""
    code = "openapi_disabled"


class OpenApiTimeout(OpenApiError):
    code = "openapi_timeout"


class OpenApiServerError(OpenApiError):
    code = "openapi_server_error"


class OpenApiBadRequest(OpenApiError):
    code = "openapi_bad_request"


# ---------- 数据库 ----------

class DbError(LxCliError):
    code = "db"


class DbLockedError(DbError):
    code = "db_locked"


class NoSuchListError(DbError):
    code = "no_such_list"


class NoSuchSongError(DbError):
    code = "no_such_song"


# ---------- 音乐源 ----------

class SourceError(LxCliError):
    exit_code = EXIT_UPSTREAM
    code = "source"

    def __init__(self, source: str, message: str, **kw) -> None:
        super().__init__(f"{source}: {message}", **kw)
        self.source = source


class UnknownSourceError(SourceError):
    code = "unknown_source"


# ---------- 音源脚本管理 ----------

class ScriptError(LxCliError):
    code = "script"


class ScriptParseError(ScriptError):
    """脚本头非法 / 不是合法 js / 非 UTF-8。"""
    code = "script_parse"


class ScriptTooLargeError(ScriptError):
    code = "script_too_large"


class ScriptModifiedError(ScriptError):
    """本地脚本被手改过 —— 需 --force 才覆盖。"""
    code = "script_modified"


class ScriptDownloadError(ScriptError):
    exit_code = EXIT_UPSTREAM
    code = "script_download"


class TooManyScriptsError(ScriptError):
    """超过 LX 上限（20 个）。"""
    code = "too_many_scripts"


def exit_code_for(exc: BaseException) -> int:
    """把异常映射为进程退出码。"""
    if isinstance(exc, LxCliError):
        return exc.exit_code
    return EXIT_RUNTIME
