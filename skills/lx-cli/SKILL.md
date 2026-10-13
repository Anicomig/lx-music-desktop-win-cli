---
name: lx-cli
description: Control LX Music desktop (洛雪音乐助手) from the command line — search music across 5 platforms (kg/kw/tx/wy/mg), read/write playlists, control playback, manage JS source scripts, and run doctor/install-status/uninstall. Use when user asks to "搜歌", "search songs", "加进歌单/add to playlist", "看我的歌单/list my playlists", "播放某首歌/play this song", "更新音源/update music sources", "更新/安装/卸载 cli", "查看安装状态", or when a task requires driving LX Music / lx-cli programmatically.
license: MIT
compatibility: opencode
metadata:
  audience: ai-agents
  workflow: music-control
  language: python
  requires: lx-music-desktop
---

# LX CLI (lx-cli)

Drive **LX Music desktop (洛雪音乐助手)** from the command line. Every command
supports `--json` with a stable shape for automated consumption.

## ⚠ CRITICAL RULES (read first)

1. **Writes require LX to be CLOSED.** Editing playlists, config, or source scripts
   while LX runs gets **overwritten** by LX's in-memory cache (exit code **3**).
   **Never use `--force` to bypass it** — it can lose data.
2. **Write commands default to dry-run.** `playlist add` and `script install/update`
   report first and write nothing. Review, then add `--apply`.
3. **Always pass `--json`.** stdout is then pure JSON; logs go to stderr.
4. **Branch on exit codes**, not on output text.
5. **Never infer the platform from the id prefix** — Kugou (`kg`) ids have **no**
   `kg_` prefix (they look like `631537655_5A86…`).

---

## 安装 / 更新 / 卸载（简短 —— 细节强制读包内文档）

> ⚠️ **安装、更新、卸载、换电脑迁移的完整步骤以 CLI 安装包内的文档为准。**
> 本 skill 不复述细节（会与包内文档脱节）。**动手前先读**：

| 场景 | 必读（CLI 包内） |
|---|---|
| 首次安装 | `<cli-root>/README.md` |
| 升级到新版 | `<cli-root>/docs/guide/如何更新.md` |
| 换电脑 / 拷贝迁移 | `<cli-root>/docs/guide/迁移到新电脑.md` |
| 卸载 | README.md 的「卸载」小节 + `lx uninstall --help` |

* `<cli-root>` = 含 `run.py` 与 `src/` 的文件夹（本 skill 位于 `<cli-root>/skills/lx-cli/`）。
* **入口优先用 `run.py`**（免安装、改目录名/搬家仍可用）：
  `python <cli-root>/run.py --version`
* 若 `lx` 已装到 PATH，直接用 `lx …` 更方便。
* ⚠️ **不要用裸 `python -m lx_cli`** —— 可能静默加载旧版（症状：命令缺失）。

最小验证（读文档后执行）：

```bash
python <cli-root>/run.py --version          # 版本号
python <cli-root>/run.py status-install     # 安装方式/位置/全局可用性
python <cli-root>/run.py doctor             # 8 项自检，失败项给下一步命令
```

> Windows 一键安装/更新：双击 `<cli-root>/install.bat`（自动检测旧版并覆盖更新）。
> 卸载：`<cli-root>/uninstall.bat`（只清 CLI 自身，不删 LX 与歌单数据）。

---

## When to Use This Skill

- search songs, or see a song's album/artist/platform
- add songs to a playlist; create/rename/delete playlists
- see what's playing, or control playback
- play a *specific* song (not just next/prev)
- check/install/update JS source scripts (音源)
- install / update / uninstall the CLI, or check install status
- diagnose problems (`doctor`) or locate LX paths (`where`)

---

## 正常 Desktop 操作功能（命令地图）

| 功能 | 命令 |
|---|---|
| **搜索/元数据** | `search` `song` `album` `leaderboard` `hot` `lyric` `source-list` |
| **播放控制** | `play` `pause` `toggle` `next` `prev` `seek` `volume` `mute` `status` |
| **指定播放** | `play-song` `search-play` `dislike` `open-list` `play-list` |
| **收藏** | `collect` `uncollect`（仅作用于当前播放曲） |
| **歌词** | `lyric`（当前曲）· `lyric-all`（全部类型，`lyric --all` 同义） |
| **歌单** | `playlist list/show/find/create/rename/delete/add/remove` |
| **音源脚本** | `script list/repo/install/update/remove/enable/active/verify` `script doctor` |
| **下载记录（只读）** | `download stats/list/failed/verify` |
| **进程** | `start` `stop` `is-running` |
| **配置/路径** | `config-show` `config-enable` `config-disable` `where` `backup` |
| **数据库（只读）** | `db tables/info/schema/query/stats` |
| **自检/安装态/卸载** | `doctor` `status-install` `uninstall` |

完整参数见 `@references/commands.md`（由 `--help` 自动生成）。

---

## 核心工作流

### 1. 搜索

```bash
python <cli-root>/run.py search "yorushika" --json               # 聚合 5 平台
python <cli-root>/run.py search "yorushika" --source kg --json   # 单平台
python <cli-root>/run.py search "yorushika" --sources kg,wy --json
```

每项含 `id` `name` `singer` `singerList` `albumName` `interval`
`source`（如 `kg`）`sourceLabel`（如 `酷狗音乐`）。
**`source` 是平台 id，绝不是脚本名。**

### 2. 加歌到歌单

```bash
# 1) 先预演 —— 看 wouldAdd / alreadyIn / suspectDuplicates
python <cli-root>/run.py playlist add <list_id> --from-search "yorushika" --source kg --json
# 2) 确认后写入（LX 必须关闭）
python <cli-root>/run.py playlist add <list_id> --from-search "yorushika" --source kg --apply --json
```

或用已筛选结果：`search … --json > songs.json` → `playlist add <id> --from songs.json --apply --json`
`--dedupe-by id`（默认，保守）| `name+singer` | `fuzzy`。

### 3. 播放

```bash
python <cli-root>/run.py toggle --json
python <cli-root>/run.py status --json     # name/singer/status/progress
python <cli-root>/run.py volume 50 --json
```

播放**指定**歌（Scheme URL，慢、无返回值）：

```bash
python <cli-root>/run.py search-play "又三郎" --singer ヨルシカ --json
# 约 9s 生效，之后用 status --json 确认
```

### 4. 音源脚本 + 下载排查

```bash
python <cli-root>/run.py script list --json          # 已装 + 当前启用
python <cli-root>/run.py script doctor --json        # ★ 体检：找空壳/失效脚本
python <cli-root>/run.py script update --all --json  # 预演（按内容哈希）
python <cli-root>/run.py script install flower --apply --json  # 需关 LX
```

**下载情况只读查询**（不发起下载）：

```bash
python <cli-root>/run.py download stats  --json   # 总数/完成/失败/质量/来源
python <cli-root>/run.py download failed --json   # 失败明细 + 可操作建议
python <cli-root>/run.py download verify --json   # 文件是否真实存在
```

> ⚠️ **下载失败先查音源脚本**：`script doctor` 会标出"字符数过小=疑似空壳"。
> CLI **无法发起下载**（Open API / Scheme URL 均无下载端点），只能在 GUI 里下。

---

## 当 CLI 没有该功能 / 本文未覆盖 → 优先读包内文档

若所需能力**不在上面的命令地图里**，或**本文没写清楚**，
**不要猜测命令** —— 先读 CLI 安装包内的文档（它们是最权威、随版本更新的）：

```
<cli-root>/
├── README.md                     快速开始、安装、卸载、命令总览
├── CHANGELOG.md                  版本变更
├── docs/
│   ├── guide/
│   │   ├── 功能与操作.md          每个功能怎么用、注意事项
│   │   ├── ai-usage.md           AI 使用指南（JSON 契约、退出码、安全边界）
│   │   ├── skills-usage.md       skills 安装与使用
│   │   ├── 如何更新.md            升级流程
│   │   └── 迁移到新电脑.md         换电脑部署
│   ├── reference/
│   │   └── commands.md           ★ 全部命令与参数（自动生成）
│   └── internals/
│       ├── README.md             ★ 排障索引（现象 → 查哪份文档/代码）
│       ├── architecture.md        架构分层
│       ├── contracts.md           关键契约（id 规则、meta 字段…）
│       ├── conventions.md         命名与来源约定（区分平台/脚本）
│       ├── database.md            SQLite schema 与写入约束
│       ├── sources.md             平台元数据接口
│       ├── scripts.md             JS 音源脚本机制
│       └── research/              桌面端源码调研、真实数据统计、官方文档核对
└── skills/lx-cli/                 ← 本 skill
```

**查找优先级**：

1. `docs/reference/commands.md` —— 命令/参数是否真的存在
2. `docs/guide/功能与操作.md` —— 该功能怎么用、有什么坑
3. `docs/internals/README.md` —— 排障索引，指向更深的文档
4. `docs/internals/contracts.md` —— 数据字段/id 规则等硬契约
5. `docs/internals/research/` —— 桌面端源码与真实数据的调研报告

> 想快速自查命令是否存在：`python <cli-root>/run.py --help` 或
> `python <cli-root>/run.py <group> --help`。

---

## Exit Codes（据此分支）

| Code | 含义 | 处理 |
|---|---|---|
| `0` | OK | 解析 stdout |
| `1` | 运行时错误 | 读 `error.message` |
| `2` | **用法错误**（参数错/平台未知） | 改参数，**不要重试** |
| `3` | **LX 必须关闭** | 请用户关闭 LX；**绝不用 `--force`** |
| `4` | 上游失败（网络/平台） | 可退避重试 |

失败也输出 JSON：`{"error": {"code","message","detail"}}`。

## Tips & Known Behaviors

| 现象 | 真相 |
|---|---|
| 某平台返回 0 条 | **限流**；等几秒。聚合模式记在 `failedPlatforms` |
| `play` 后 `status` 没变 | 状态更新**异步**（约 1s），别立即断言 |
| `status` = `error` | 切歌中间态，**不是**崩溃 |
| `search-play` 像没反应 | Scheme URL 单向且慢（秒级） |
| `status` 像布尔 | 它是**字符串**：`playing`/`paused`/`error`/`stoped` |
| 控制台中文乱码 | 加 `--json`（CLI 会切 UTF-8） |
| `lx` 命令不可用 | 用 `run.py`；装回见包内 README |

## Never Do This

- ❌ 用 `--force` 绕过「LX 正在运行」检查
- ❌ 手工编辑 `%APPDATA%\lx-music-desktop\LxDatas\*` —— 用 CLI 命令
- ❌ 把 `source` 当脚本名
- ❌ 以为 `kg` 的 id 以 `kg_` 开头
- ❌ 没看预演报告就加 `--apply`
- ❌ 猜命令 —— 先读包内文档或 `--help`

## Reference Files

按需加载（本 skill 目录内）：

- @references/commands.md — 完整命令/参数（由 `--help` 生成）
- @references/json-contract.md — `--json` 精确形状 + 退出码/错误码
- @references/troubleshooting.md — 排障（限流、播放、DB、脚本）
- @scripts/lx.sh — 自动定位 `<cli-root>` 的便捷包装器

**包内文档（不在本 skill 目录，见上文目录地图）** 是安装/更新/卸载与
深度行为的权威来源。
