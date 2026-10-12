#!/bin/sh
# lx.sh —— lx-cli 便捷包装器
#
# 作用：自动解析 CLI 根目录并调用 run.py，使调用方无需知道安装位置。
#       支持"免安装 + 改名/搬家"。
#
# 用法：
#   sh lx.sh search "yorushika" --json
#   sh lx.sh status --json
#
# 环境变量：
#   LX_CLI_ROOT   显式指定 CLI 根目录（含 run.py 的那个目录）
#   LX_CLI_PY     指定 python 解释器（默认 python3 → python）

set -u

# ---- 1. 定位 CLI 根 ----
find_root() {
    # 1) 环境变量优先
    if [ -n "${LX_CLI_ROOT:-}" ] && [ -f "$LX_CLI_ROOT/run.py" ]; then
        printf '%s\n' "$LX_CLI_ROOT"; return 0
    fi

    # 2) 从本脚本位置推导：本脚本在 <cli-root>/skills/lx-cli/scripts/
    here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
    candidate=$(CDPATH= cd -- "$here/../../.." 2>/dev/null && pwd) || candidate=""
    if [ -n "$candidate" ] && [ -f "$candidate/run.py" ]; then
        printf '%s\n' "$candidate"; return 0
    fi

    # 3) 常见位置兜底
    for d in \
        "$HOME/lx-cli-v2" \
        "$HOME/.local/share/lx-cli-v2" \
        "/opt/lx-cli-v2" \
        "$(pwd)"
    do
        [ -f "$d/run.py" ] && { printf '%s\n' "$d"; return 0; }
    done
    return 1
}

ROOT=$(find_root) || {
    echo "lx.sh: 找不到 CLI 根目录（需含有 run.py 的目录）。" >&2
    echo "       请设置 LX_CLI_ROOT=<cli-root> 后重试。" >&2
    exit 2
}

# ---- 2. 选解释器 ----
# 注意：Windows 上 `python` 可能是 Microsoft Store 的占位 stub（会打印提示并非零退出），
# 所以必须**实际执行**验证，而不是仅用 command -v 检查存在性。
PY=""
for cand in "${LX_CLI_PY:-}" py python3 python; do
    [ -n "$cand" ] || continue
    command -v "$cand" >/dev/null 2>&1 || continue
    if "$cand" -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >/dev/null 2>&1; then
        PY="$cand"; break
    fi
done

if [ -z "$PY" ]; then
    echo "lx.sh: 找不到可用的 Python 3.10+（可设 LX_CLI_PY 指定完整路径）。" >&2
    exit 2
fi

# ---- 3. 执行 ----
exec "$PY" "$ROOT/run.py" "$@"
