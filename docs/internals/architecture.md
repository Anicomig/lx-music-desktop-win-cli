# 架构

> 分层、依赖方向、数据流。改代码前确认改动落在正确的层。

---

## 1. 分层

```
cli/           表现层（Click）—— 参数解析、输出、错误→退出码
  ↓ 只调用
core/          领域层 —— 无 CLI 依赖，可独立单测
sources/       ① 平台元数据接口（搜索）
scripts/       ② JS 音源脚本管理（安装/更新，不执行）
  ↓ 依赖
paths/ errors/ _logging/    基础设施
```

**依赖方向单向**：`cli → core/sources/scripts → 基础设施`。
`core/` **不得** import `cli/`（否则无法单测）。

---

## 2. 三个通道（为什么这样分）

| 通道 | 能力 | 有返回值 | 速度 | 代码 |
|---|---|---|---|---|
| **Open API** | 当前播放状态、控制、歌词、收藏当前曲 | ✅ | 快 | `core/openapi_client.py` |
| **Scheme URL** | 播放**指定**曲、搜索并播放、歌单、不喜欢 | ❌ | 慢（秒级） | `core/scheme_url.py` |
| **平台元数据接口** | 搜索/专辑/歌单/歌词/评论/排行 | ✅ | 中 | `sources/` |
| **直接写 DB** | 歌单增删改、收藏任意曲 | ✅ | 快（需关 LX） | `core/db_writer.py` |

> **为什么必须这样分**：LX 的 Open API **只有 13 个端点**，没有搜索/歌单/取 URL
> （`openApi/index.ts:88-207`）。所以查询只能自己实现，写歌单只能直连 DB。

---

## 3. 数据流

### 3.1 搜索

```
lx search "x"
  → cli/music.py:search_cmd
  → sources/search.py:search(platforms=None)   # None = 聚合全部
      → 并发各 sources/<平台>.py:search()
          → sources/http.py:request_json()      # 重试 Session
          → 各平台官方域名
      → 失败隔离：单平台抛错 → 该源返回空结果，不影响其它
      → merge_results() 按 id 去重
  → SongRecord.to_json()  # 含 id/source/sourceLabel
  → cli/_common.py:emit()  # --json 时只输出 JSON
```

### 3.2 搜索 → 歌单（需求 D）

```
lx playlist add <list> --from-search "x"
  → cli/playlist.py:add_cmd
  → do_search() 取候选（SongRecord 带可落库 id）
  → db_reader.songs_in_list() 取现有
  → compare(candidates, existing, by=...)      # ★ 核心比对
      → id 模式：复合 id 完全匹配
      → name+singer：跨平台同曲
      → fuzzy：core/matcher.is_same_song（±5s + 版本词）
  → 默认 dry_run：只报告；--apply 才
  → db_writer.add_songs()  # 幂等 + 单事务 + BEGIN IMMEDIATE
```

### 3.3 播放

```
lx play / pause / toggle
  → core/openapi_client.py → http://127.0.0.1:23330/<endpoint>

lx play-song --name … --source kg …
  → core/scheme_url.py:play_song()
  → 构造 lxmusic://music/play?data=…
  → cmd /c start "" "<url>"    # 走 shell 关联
  → LX 自己调用 JS 音源脚本拿 URL 并播放
```

### 3.4 音源脚本

```
lx script install flower --apply
  → cli/script.py → scripts/service.py:install_from_repo()
  → scripts/repo.py:fetch_script()   # 直链失败→镜像回退
  → scripts/metadata.py:parse_script_meta()  # 校验头部
  → scripts/store.py:save_entries()  # gz_/zlib + Tab + 原子写
  → 记录内容哈希到 lx_cli_scripts_meta.json（供"手改检测"）
```

---

## 4. 关键设计决策

| 决策 | 理由 |
|---|---|
| `sources/` 与 `scripts/` 彻底分开 | 前者查元数据，后者换 URL；混用会导致术语与职责错乱（见 [conventions](conventions.md)） |
| `SongRecord` 带 `id` 字段 | 旧版只有 `songmid`，导致"搜索→歌单"结构上不可能（DB id 是复合的） |
| 写操作默认 dry-run | `playlist add` / `script update` 先给报告，避免误写 |
| 全命令支持 `--json` | AI 消费方的硬需求；且有测试固化形状 |
| 日志强制 stderr | 否则污染 `--json` 的 stdout |
| 不用 Click standalone 模式 | 自己接管退出码（旧版 except 分支是死代码） |
| 异常树统一继承 `LxCliError` | 否则未预期异常会打印裸 repr 且退出码错 |

---

## 5. 扩展点

| 想加什么 | 改哪里 |
|---|---|
| **新的平台元数据源** | 新建 `sources/<id>.py` 实现 `PlatformSource`，在 `sources/__init__.py` 末尾 `_register(...)` |
| 新的歌曲查询能力 | 在 `PlatformSource` 加方法 + 各平台实现（可选，未实现的会抛 `SourceError`） |
| 新的音源仓库 | 改 `scripts/repo.py` 的 `REPO_SOURCES` / `RAW_TEMPLATE` / `MIRRORS`（**声明式**） |
| 新的 CLI 命令组 | 新建 `cli/<组>.py`，在 `cli/__init__.py` 里 `add_command` |
| 新的退出码语义 | `errors.py` 加异常类（带 `exit_code`/`code`） |

---

## 6. 测试组织

```
tests/
├── test_musicinfo.py       契约（id/meta/歌手）
├── test_matcher.py         去重匹配
├── test_db.py              DB 读写（用脱敏夹具）
├── test_sources.py         搜索（mock 平台）
├── test_openapi_client.py  Open API（mock HTTP）
├── test_scheme_url.py      Scheme URL 构造
├── test_scripts.py         脚本管理（临时目录）
├── test_cli_contract.py    退出码 + --json 契约
├── test_portability.py     P1–P4
└── fixtures/lx.data.db     脱敏夹具（合成数据，真实结构）
```

**夹具**由 `scripts/make_fixture.py` 从真实库派生：保留结构边界
（kg 裸 id 934 / 二次前缀 24、稀疏 order、虚拟歌单），隐私全部替换。

**端到端脚本**（需联网，不进 pytest）：
* `scripts/e2e_playlist.py` —— 搜索→对比→插入
* `scripts/e2e_scripts.py` —— 脚本安装/更新/删除（含"真实文件未被改"断言）
