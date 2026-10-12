# lx-music-desktop-win-cli

**洛雪音乐助手（LX Music Desktop）的命令行工具 —— Windows 端，为 AI 使用而设计。**

用命令行控制 LX 播放、搜索全网音乐、读写歌单、管理音源脚本。
所有命令都有稳定的 `--json` 输出与明确的退出码，便于脚本与 AI 消费。

```bash
lx search "yorushika"                      # 聚合搜索 5 大平台
lx playlist add mylist --from-search "…"   # 搜索→对比→插入歌单（默认预演）
lx script list                             # 管理音源脚本
lx play-song --name X --singer Y --source kg --songmid Z --hash H   # 播放指定歌曲
```

---

## 🙏 本项目依赖的两个上游项目

本工具是**围绕**下面两个项目构建的客户端，自身不提供音乐内容：

### [lyswhut/lx-music-desktop](https://github.com/lyswhut/lx-music-desktop) — 洛雪音乐助手（必需）

桌面端本体。本 CLI 的全部能力都建立在它之上：

| CLI 能力 | 依赖 LX 的什么 |
|---|---|
| 播放控制 / 状态 / 歌词 | [开放 API 服务](https://lxmusic.toside.cn/desktop/open-api)（v2.7.0+） |
| 播放指定歌曲 / 歌单 | [Scheme URL](https://lxmusic.toside.cn/desktop/scheme-url)（`lxmusic://`） |
| 搜索 / 专辑 / 排行榜 | 其内置 `musicSdk` 的官方接口实现（本 CLI 按其契约重新实现） |
| 歌单读写 | 其本地 SQLite 库 `lx.data.db` |

* 仓库：https://github.com/lyswhut/lx-music-desktop
* 文档：https://lxmusic.toside.cn/desktop
* 许可：Apache-2.0（**本项目与它无隶属关系，仅为第三方工具**）

> 本项目针对 **v2.12.5** 的数据结构与接口契约实现，并参考 v2.12.6 实测行为。

### [pdone/lx-music-source](https://github.com/pdone/lx-music-source) — 洛雪音源集合（播放必需）

第三方 JS 音源脚本集合（`flower` / `sixyin` / `lx` / `huibq` …）。

**为什么必需**：LX v2.12.5 起**内置播放接口已全部停用**，音频地址只能由 JS 音源脚本提供
（`musicSdk/api-source.js:33-38`）。所以**不装音源脚本 = 搜得到但播不了**。

`lx script` 命令族即用于管理这些脚本：安装 / 更新 / 列表 / 删除 / 切换。

* 仓库：https://github.com/pdone/lx-music-source
* 本 CLI **不执行**这些脚本，只负责安装与更新；执行由 LX 自己完成
* 脚本版权归各作者所有，本项目仅提供管理工具

---

## 环境要求（Windows）

### 必需

| 项 | 要求 | 说明 |
|---|---|---|
| **操作系统** | **Windows 10 / 11**（x64 或 x86） | 本项目专注 Windows；路径探测含注册表逻辑 |
| **Python** | **≥ 3.10**（实测 3.13，32/64 位均可） | `python --version` 可验证 |
| **LX Music Desktop** | v2.7.0+（建议 v2.12.5+） | 需**至少打开过一次**以生成配置 |
| **开放 API** | 需启用 | 设置 → 开放 API 服务 → 启用；或 `lx config-enable` |

### Python 依赖

```bash
python -m pip install click requests
```

| 包 | 版本 | 用途 |
|---|---|---|
| [`click`](https://pypi.org/project/click/) | ≥ 8.1 | 命令行框架 |
| [`requests`](https://pypi.org/project/requests/) | ≥ 2.32 | HTTP（含自动重试） |

**可选**（仅 `sync` 相关功能需要，当前版本未接线，可暂不装）：

```bash
python -m pip install websockets cryptography pyjwt
```

> 国内加速：追加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`

**无需**安装 Node.js（音源脚本由 LX 自己运行，不由本 CLI 执行）。

---

## 快速开始（3 步）

### 1. 运行方式（任选其一）

**方式 A：免安装（推荐先试）**

```cmd
cd lx-music-desktop-win-cli
python run.py --help
lx.bat --help
```

> 免安装方式**支持随意改目录名/搬家**：启动器按自身位置定位代码，不依赖 `pip install`。

**方式 B：安装为 `lx` 命令**

```cmd
python -m pip install -e .        :: 开发模式（改代码即时生效）
python -m pip install .           :: 正式安装
lx --help
```

### 2. 让 LX 开启开放 API

```cmd
lx config-enable          :: 写 config_v2.json（需先关闭 LX）
lx start --hidden         :: 启动 LX（托盘）
lx status                 :: 验证能读到状态
```

> 也可在 LX 界面手动开启：**设置 → 开放 API 服务 → 启用**。

### 3. 确认环境

```cmd
lx where                  :: 显示 LX 安装路径与数据目录（含诊断信息）
```

---

## 命令总览

| 组 | 命令 | 用途 |
|---|---|---|
| **查询** | `search` `song` `album` `leaderboard` `hot` `lyric` `source-list` | 走各平台**官方接口**查元数据 |
| **播放** | `play` `pause` `toggle` `next` `prev` `seek` `volume` `mute` `status` | 走开放 API |
| **指定播放** | `play-song` `search-play` `dislike` `open-list` `play-list` | 走 Scheme URL（`lxmusic://`） |
| **收藏** | `collect` `uncollect` | 仅对当前播放曲 |
| **歌单** | `playlist list/show/find/create/rename/delete/add/remove` | 直接读写本地库 |
| **音源脚本** | `script list/repo/install/update/remove/enable/active/verify` | 管理 `pdone/lx-music-source` 的脚本 |
| **进程** | `start` `stop` `is-running` | 启停 LX |
| **配置** | `config-show` `config-enable` `config-disable` `where` `backup` | 配置与备份 |
| **数据库** | `db tables/info/schema/query/stats` | 只读查询 |

完整参数见 [`docs/reference/commands.md`](docs/reference/commands.md)。

---

## 设计要点（重要）

### 三类"源"，不要混

| 叫法 | 位置 | 干什么 |
|---|---|---|
| **平台元数据接口** | `src/lx_cli/sources/` | 直连酷狗/酷我/QQ/咪咕/网易**官方域名**，负责**搜索** |
| **JS 音源脚本** | `src/lx_cli/scripts/` | 第三方 JS 插件（来自 [pdone/lx-music-source](https://github.com/pdone/lx-music-source)），负责**换播放地址** |
| **平台标识** | `kg` `kw` `tx` `wy` `mg` | 表示"这首歌属于哪个平台" |

CLI 输出里 `source: "kg"` + `sourceLabel: "酷狗音乐"`，**永远不出现脚本名**。

详见 [`docs/internals/conventions.md`](docs/internals/conventions.md)。

### 安全边界

| 操作 | 约束 |
|---|---|
| 读数据库/状态 | 随时可做（只读，LX 运行时也安全） |
| **写歌单 / 写配置 / 写音源脚本** | **必须先关闭 LX**，否则会被 LX 覆盖（返回退出码 `3`） |
| 批量插入歌单 | **默认 `--dry-run`**，确认后加 `--apply` |
| 更新音源脚本 | 按**内容哈希**判断；被手改过需 `--force` |

> 绝不要用 `--force` 绕过硬性前置检查 —— 那可能导致数据被 LX 覆盖。

---

## 文档

| 文档 | 内容 |
|---|---|
| [`docs/guide/功能与操作.md`](docs/guide/功能与操作.md) | 每个功能怎么用、注意事项 |
| [`docs/guide/迁移到新电脑.md`](docs/guide/迁移到新电脑.md) | **换电脑：拷过去就能用**（含依赖、自检清单） |
| [`docs/guide/ai-usage.md`](docs/guide/ai-usage.md) | AI 使用指南（JSON 契约、退出码、安全） |
| [`docs/guide/skills-usage.md`](docs/guide/skills-usage.md) | skills 安装与使用 |
| [`docs/reference/commands.md`](docs/reference/commands.md) | **全部命令与参数**（自动生成） |
| [`docs/internals/`](docs/internals/README.md) | 架构、契约、代码地图（**排障用**） |
| [`skills/lx-cli/SKILL.md`](skills/lx-cli/SKILL.md) | 供 AI 加载的 skill |
| [`tools/README.md`](tools/README.md) | 独立工具（音源探针、歌单转换） |

---

## 可移植性

* **改目录名或换路径后仍可用**（启动器按自身位置定位）
* **换电脑 / 换 Windows 账号自动适配**：数据目录由 `%APPDATA%` 推导，不硬编码
* **找不到 LX 时会主动搜索**：候选路径 → PATH → **注册表**（`lxmusic://` 协议关联、卸载信息）→ 目录扫描
* 可用 `--exe` 或环境变量 `LX_EXE` 显式指定 LX
* 极端部署可用环境变量 `LX_DATA_DIR` 直接指定数据目录

详见 [`docs/guide/迁移到新电脑.md`](docs/guide/迁移到新电脑.md)。

---

## 开发

```bash
python -m pytest tests/ -q            # 290+ 用例，无需 PYTHONPATH
python scripts/gen_commands_doc.py    # 重新生成命令文档
python scripts/check_skills.py        # 校验 skills 规范
```

提交前钩子（可选）：

```cmd
git config core.hooksPath .githooks
```

---

## 致谢与授权

* 核心依赖 [lyswhut/lx-music-desktop](https://github.com/lyswhut/lx-music-desktop)（Apache-2.0）
* 音源脚本来自 [pdone/lx-music-source](https://github.com/pdone/lx-music-source) 及各脚本作者
* 本项目为**第三方工具**，与上述项目**无隶属或背书关系**

### 免责声明

* 本工具**不提供、不托管、不分发**任何音乐内容或音频文件
* 所有元数据查询直连各音乐平台的公开接口；播放地址由 LX 与用户安装的音源脚本提供
* 请遵守各音乐平台的服务条款与当地法律法规，仅将本工具用于个人合法用途

## License

MIT
