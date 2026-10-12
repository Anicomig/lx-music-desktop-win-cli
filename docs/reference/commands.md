# 命令参数参考

> **本文件由 `scripts/gen_commands_doc.py` 从真实 `--help` 自动生成，请勿手改。**
> 改代码后重新生成：`python scripts/gen_commands_doc.py`
> 校验是否过期：`python scripts/gen_commands_doc.py --check`

## 全局约定

| 项 | 说明 |
|---|---|
| 全局选项 | 需放在子命令**之前**（如 `lx --db x.db playlist list`） |
| `--json` | 每个输出命令都支持；stdout 只有 JSON，日志走 stderr |
| `-v / -vv` | 日志级别（INFO / DEBUG），走 stderr |
| 退出码 | `0` 成功 · `1` 运行时 · `2` 用法 · `3` 需关 LX · `4` 上游 |

---

## 顶层命令

```
Usage: lx [OPTIONS] COMMAND [ARGS]...

  LX Music 桌面版命令行工具（AI 友好）。

Options:
  --exe PATH       lx-music-desktop.exe 路径（默认自动探测，或环境变量 LX_EXE）。
  --db PATH        覆盖 lx.data.db 路径（测试夹具用）。
  --data-dir PATH  覆盖 LxDatas 目录。
  -v, --verbose    日志级别：-v INFO，-vv DEBUG（日志走 stderr）。
  --show-secrets   显示密钥类字段（默认脱敏）。
  --version        Show the version and exit.
  -h, --help       Show this message and exit.

Commands:
  album
  backup
  collect
  config-disable
  config-enable
  config-show
  db              数据库只读查询（LX 运行时也安全）。
  dislike
  hot
  is-running
  leaderboard
  lyric
  mute
  next
  open-list
  pause
  play
  play-list
  play-song
  playlist        歌单查询与读写。
  prev
  script          音源脚本管理（安装/更新/列表/删除）。
  search
  search-play
  seek
  song
  source-list
  start
  status
  stop
  toggle
  uncollect
  volume
  where
```

---

## 各命令详解

### `lx album`

```text
Usage: lx album [OPTIONS] ALBUM_ID

Options:
  -s, --source [kg|kw|tx|mg|wy]  [required]
  --json                         输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help                     Show this message and exit.
```

### `lx backup`

```text
Usage: lx backup [OPTIONS] DEST_DIR

Options:
  --tag TEXT  自定义后缀（默认时间戳）。
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

### `lx collect`

```text
Usage: lx collect [OPTIONS]

Options:
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

### `lx config-disable`

```text
Usage: lx config-disable [OPTIONS]

Options:
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

### `lx config-enable`

```text
Usage: lx config-enable [OPTIONS]

Options:
  --port TEXT  端口（默认 23330）。
  --bind-lan   绑定 0.0.0.0（**无鉴权**，慎用）。
  --json       输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help   Show this message and exit.
```

### `lx config-show`

```text
Usage: lx config-show [OPTIONS]

Options:
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

### `lx db`

```text
Usage: lx db [OPTIONS] COMMAND [ARGS]...

  数据库只读查询（LX 运行时也安全）。

Options:
  -h, --help  Show this message and exit.

Commands:
  info
  query
  schema
  stats
  tables
```

### `lx dislike`

```text
Usage: lx dislike [OPTIONS]

Options:
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

### `lx hot`

```text
Usage: lx hot [OPTIONS]

Options:
  -s, --source [kg|kw|tx|mg|wy]  [default: kg]
  --json                         输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help                     Show this message and exit.
```

### `lx is-running`

```text
Usage: lx is-running [OPTIONS]

Options:
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

### `lx leaderboard`

```text
Usage: lx leaderboard [OPTIONS]

Options:
  -s, --source [kg|kw|tx|mg|wy]  [default: kw]
  -b, --board TEXT               榜单名或 id。
  -n, --limit INTEGER            [default: 30]
  --json                         输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help                     Show this message and exit.
```

### `lx lyric`

```text
Usage: lx lyric [OPTIONS]

Options:
  --all       输出全部歌词类型。
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

### `lx mute`

```text
Usage: lx mute [OPTIONS] {on|off}

Options:
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

### `lx next`

```text
Usage: lx next [OPTIONS]

Options:
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

### `lx open-list`

```text
Usage: lx open-list [OPTIONS] PLATFORM LIST_ID

Options:
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

### `lx pause`

```text
Usage: lx pause [OPTIONS]

Options:
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

### `lx play`

```text
Usage: lx play [OPTIONS]

Options:
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

### `lx play-list`

```text
Usage: lx play-list [OPTIONS] PLATFORM LIST_ID

Options:
  --index INTEGER  从第几首开始（0 起）。
  --json           输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help       Show this message and exit.
```

### `lx play-song`

```text
Usage: lx play-song [OPTIONS]

Options:
  --name TEXT          歌曲名。  [required]
  --singer TEXT        歌手名。  [required]
  -s, --source TEXT    平台（kg/kw/tx/mg/wy）。  [required]
  --songmid TEXT       歌曲 songmid（或完整 id）。  [required]
  --hash TEXT          kg 平台必传。
  --mediemid TEXT      tx 平台必传 strMediaMid。
  --copyright-id TEXT  mg 平台必传 copyrightId。
  --quality TEXT       期望音质。  [default: 320k]
  --no-types           不自动探测音质（默认会先查一次以取得 types）。
  --json               输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help           Show this message and exit.
```

### `lx playlist`

```text
Usage: lx playlist [OPTIONS] COMMAND [ARGS]...

  歌单查询与读写。

Options:
  -h, --help  Show this message and exit.

Commands:
  add
  create
  delete
  find
  list
  remove
  rename
  show
```

### `lx prev`

```text
Usage: lx prev [OPTIONS]

Options:
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

### `lx script`

```text
Usage: lx script [OPTIONS] COMMAND [ARGS]...

  音源脚本管理（安装/更新/列表/删除）。

Options:
  -h, --help  Show this message and exit.

Commands:
  active
  enable
  install
  list
  remove
  repo
  update
  verify
```

### `lx search`

```text
Usage: lx search [OPTIONS] KEYWORD

Options:
  -s, --source TEXT    只查一个平台（kg/kw/tx/mg/wy）。
  --sources TEXT       查多个平台，逗号分隔（如 kg,wy）。
  --all                聚合全部平台（默认行为）。
  -n, --limit INTEGER  每平台返回条数。  [default: 30]
  -p, --page INTEGER   [default: 1]
  --json               输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help           Show this message and exit.
```

### `lx search-play`

```text
Usage: lx search-play [OPTIONS] NAME

Options:
  --singer TEXT  歌手名（提高匹配准确率）。
  --album TEXT
  --later        稍后播放（加入队列而非立即播放）。
  --json         输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help     Show this message and exit.
```

### `lx seek`

```text
Usage: lx seek [OPTIONS] OFFSET

Options:
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

### `lx song`

```text
Usage: lx song [OPTIONS] SONGMID

Options:
  -s, --source [kg|kw|tx|mg|wy]  平台（kg/kw/tx/mg/wy）。  [required]
  --hash TEXT                    kg 平台取单曲详情需要 hash（形状 <songId>_<hash> 的前半段可用
                                 id）。
  --json                         输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help                     Show this message and exit.
```

### `lx source-list`

```text
Usage: lx source-list [OPTIONS]

Options:
  --features  同时列出每平台支持的能力。
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

### `lx start`

```text
Usage: lx start [OPTIONS]

Options:
  --hidden / --show     --hidden 走托盘（默认），--show 显示窗口。  [default: hidden]
  --wait / --no-wait    等待开放 API 就绪。  [default: wait]
  --wait-timeout FLOAT  [default: 30.0]
  --json                输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help            Show this message and exit.
```

### `lx status`

```text
Usage: lx status [OPTIONS]

Options:
  --filter TEXT  逗号分隔字段名，如 status,name,singer,progress
  --json         输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help     Show this message and exit.
```

### `lx stop`

```text
Usage: lx stop [OPTIONS]

Options:
  --timeout FLOAT  [default: 5.0]
  --force          强制结束进程树。
  --json           输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help       Show this message and exit.
```

### `lx toggle`

```text
Usage: lx toggle [OPTIONS]

Options:
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

### `lx uncollect`

```text
Usage: lx uncollect [OPTIONS]

Options:
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

### `lx volume`

```text
Usage: lx volume [OPTIONS] LEVEL

Options:
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

### `lx where`

```text
Usage: lx where [OPTIONS]

Options:
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

---

## 命令组

### `lx playlist`

```text
Usage: lx playlist [OPTIONS] COMMAND [ARGS]...

  歌单查询与读写。

Options:
  -h, --help  Show this message and exit.

Commands:
  add
  create
  delete
  find
  list
  remove
  rename
  show
```

#### `lx playlist add`

```text
Usage: lx playlist add [OPTIONS] LIST_ID

Options:
  --from-search TEXT              ★ 先搜索再加：给出关键字（默认聚合全部平台）。
  --from TEXT                     从 lx search --json 的输出文件导入（`-` 表示标准输入）。
  -s, --source TEXT               限定单个平台。
  --sources TEXT                  限定多个平台，逗号分隔。
  -n, --limit INTEGER             搜索时每平台取多少条。  [default: 30]
  --dedupe-by [id|name+singer|fuzzy]
                                  比对口径。  [default: id]
  --top                           插到歌单开头（默认末尾）。
  --apply                         实际写入（**默认只 dry-run 报告**）。
  --force                         LX 运行时也写（危险）。
  --json                          输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help                      Show this message and exit.
```

#### `lx playlist create`

```text
Usage: lx playlist create [OPTIONS] NAME

Options:
  --position INTEGER  侧栏位置（默认末尾）。
  --force             LX 运行时也写（危险）。
  --json              输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help          Show this message and exit.
```

#### `lx playlist delete`

```text
Usage: lx playlist delete [OPTIONS] LIST_ID

Options:
  --force
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

#### `lx playlist find`

```text
Usage: lx playlist find [OPTIONS] PATTERN

Options:
  -s, --source TEXT    限定平台（可重复）。
  --list TEXT          限定歌单。
  -n, --limit INTEGER  [default: 100]
  --json               输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help           Show this message and exit.
```

#### `lx playlist list`

```text
Usage: lx playlist list [OPTIONS]

Options:
  --user-only  隐藏内置 default/love。
  --json       输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help   Show this message and exit.
```

#### `lx playlist remove`

```text
Usage: lx playlist remove [OPTIONS] LIST_ID SONG_IDS...

Options:
  --force
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

#### `lx playlist rename`

```text
Usage: lx playlist rename [OPTIONS] LIST_ID NEW_NAME

Options:
  --force
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

#### `lx playlist show`

```text
Usage: lx playlist show [OPTIONS] LIST_ID

Options:
  -n, --limit INTEGER
  --offset INTEGER
  --json               输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help           Show this message and exit.
```

### `lx script`

```text
Usage: lx script [OPTIONS] COMMAND [ARGS]...

  音源脚本管理（安装/更新/列表/删除）。

Options:
  -h, --help  Show this message and exit.

Commands:
  active
  enable
  install
  list
  remove
  repo
  update
  verify
```

#### `lx script active`

```text
Usage: lx script active [OPTIONS]

Options:
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

#### `lx script enable`

```text
Usage: lx script enable [OPTIONS] NAME

Options:
  --force
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

#### `lx script install`

```text
Usage: lx script install [OPTIONS] [TARGET]

Options:
  --file TEXT  从本地 .js 文件安装。
  --url TEXT   从 URL 下载安装。
  --apply      实际写入（默认预演）。
  --force      覆盖被手改过的脚本 / LX 运行时也写。
  --json       输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help   Show this message and exit.
```

#### `lx script list`

```text
Usage: lx script list [OPTIONS]

Options:
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

#### `lx script remove`

```text
Usage: lx script remove [OPTIONS] NAME

Options:
  --apply     实际删除（默认预演）。
  --force
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

#### `lx script repo`

```text
Usage: lx script repo [OPTIONS]

Options:
  --check     同时查询远端版本信息（联网）。
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

#### `lx script update`

```text
Usage: lx script update [OPTIONS] [NAME]

Options:
  --all       更新全部（有来源记录的）。
  --apply     实际写入（默认预演）。
  --force     覆盖被手改过的脚本。
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

#### `lx script verify`

```text
Usage: lx script verify [OPTIONS]

Options:
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

### `lx db`

```text
Usage: lx db [OPTIONS] COMMAND [ARGS]...

  数据库只读查询（LX 运行时也安全）。

Options:
  -h, --help  Show this message and exit.

Commands:
  info
  query
  schema
  stats
  tables
```

#### `lx db info`

```text
Usage: lx db info [OPTIONS]

Options:
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

#### `lx db query`

```text
Usage: lx db query [OPTIONS] SQL

Options:
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

#### `lx db schema`

```text
Usage: lx db schema [OPTIONS] TABLE

Options:
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

#### `lx db stats`

```text
Usage: lx db stats [OPTIONS]

Options:
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

#### `lx db tables`

```text
Usage: lx db tables [OPTIONS]

Options:
  --json      输出机器可读 JSON（stdout 只有 JSON，日志走 stderr）。
  -h, --help  Show this message and exit.
```

---

## 备注

* 上表由真实 `--help` 生成，**参数以实际运行为准**。
* 需要"机器可读 + 稳定形状"时一律加 `--json`，其 schema 见
  [`../guide/ai-usage.md`](../guide/ai-usage.md)。
* 写操作（歌单/配置/音源脚本）默认或强制要求**关闭 LX**，否则返回退出码 `3`。
