# `--json` 契约与退出码

> SKILL.md 的补充细节。只在需要精确解析输出时加载。

## 1. 保证

| 保证 | 说明 |
|---|---|
| stdout 只有 JSON | 日志/警告一律 stderr，不污染解析 |
| 成功必有输出 | 不会 `exit 0` + 空 stdout |
| 失败也是 JSON | `{"error": {"code","message","detail"}}` |
| 形状稳定 | 字段名不随调用改变 |
| 敏感字段脱敏 | `--show-secrets` 才显示 |

## 2. 退出码

| 码 | 含义 | 异常类 |
|---|---|---|
| 0 | 成功 | — |
| 1 | 运行时错误 | `LxCliError` |
| 2 | 用法错误 | `UsageError` |
| 3 | 需先关闭 LX | `LxRunningError` |
| 4 | 上游失败 | `SourceError` / `OpenApiError` |
| 130 | 被中断 | — |

### `error.code` 取值

`usage` · `path` · `lx_running` · `lx_not_running` ·
`openapi` / `openapi_disabled` / `openapi_timeout` / `openapi_server_error` / `openapi_bad_request` ·
`db` / `db_locked` / `no_such_list` / `no_such_song` ·
`source` / `unknown_source` ·
`script` / `script_parse` / `script_too_large` / `script_modified` / `script_download` / `too_many_scripts` ·
`scheme`

## 3. 形状

### 3.1 `search`

```json
{
  "keyword": "yorushika",
  "mode": "single | multi | aggregate",
  "page": 1,
  "count": 140,
  "platforms": ["kg","kw","mg","tx","wy"],
  "failedPlatforms": [],
  "songs": [{
    "id": "116989871_8B4D0B91A150C3BE70058F5D8A668876",
    "songmid": "116989871",
    "name": "老人と海",
    "singer": "ヨルシカ",
    "singerList": ["ヨルシカ"],
    "albumName": "老人と海",
    "albumId": "…",
    "interval": "04:15",
    "source": "kg",
    "sourceLabel": "酷狗音乐",
    "origin": "musicSdk",
    "types": [{"type": "320k", "size": "7.31 MB"}],
    "img": "http://…"
  }]
}
```

> `mode`：指定 1 个平台 = `single`；指定 2..N-1 = `multi`；不指定 = `aggregate`。
> `failedPlatforms` 只表示"该平台这次没返回结果"（多为限流），**不是**整体失败。

### 3.2 `playlist add`（预演/执行）

```json
{
  "listId": "userlist_…",
  "listName": "我的收藏",
  "origin": {"kind": "search", "query": "yorushika", "platforms": ["kg"], "mode": "single"},
  "dedupeBy": "id",
  "dryRun": true,
  "existingCount": 12,
  "wouldAdd": 8,
  "alreadyIn": 22,
  "suspectDuplicates": 1,
  "items": {
    "toAdd": [ /* 同 search 的 song 形状 */ ],
    "skipped": ["kw_1", "…"],
    "suspect": [{"name": "…", "singer": "…", "id": "…"}]
  },
  "added": 8            // 仅在 --apply 时出现
}
```

### 3.3 `playlist list` / `show`

```json
// list
{"lists": [{"id":"…","name":"…","source":null,"songCount":219,"isVirtual":false}]}
// show
{"list": {...}, "count": 10, "songs": [ /* DB 行：id/name/singer/source/interval/meta */ ]}
```

> `isVirtual: true` = 内置的 `default`（默认列表）/ `love`（我喜欢）——
> 没有元数据行，**不能改名/删除**，但可以加歌。

### 3.4 `status`

```json
{"playing": false, "status": "paused", "name": "…", "singer": "…",
 "albumName": "…", "duration": 207.67, "progress": 4.10, "playbackRate": 1}
```

> `status` 是**字符串**：`playing`/`paused`/`error`/`stoped`。
> 附带的 `playing` 布尔是本 CLI 计算的便捷字段，**不要**自己用 `bool(status)` 判断。

### 3.5 `script list`

```json
{
  "count": 8,
  "active": "user_api_969_1789019033898",
  "scripts": [{
    "id": "user_api_969_…", "name": "独家音源", "version": "6",
    "author": "w", "homepage": "",
    "scriptChars": 57608,
    "sha256": "642de2d0…",
    "modified": false,          // true = 与 CLI 记录的哈希不符（可能被手改）
    "installedFrom": "lx",      // 来自仓库哪个目录（CLI 安装才有）
    "installedUrl": "https://…",
    "meta": {"name":"…","version":"…","author":"…","homepage":"…","description":"…"}
  }]
}
```

### 3.6 `script update`

```json
{"dryRun": true, "updated": 1, "skipped": 7,
 "plans": [{"action":"update","name":"…","oldVersion":"6","newVersion":"7",
            "changed":true,"reason":"内容有变化"}]}
```

> `action` ∈ `install` · `update` · `skip` · `remove`。
> **判据是内容哈希**，不是版本号（仓库存在"同版本号但内容不同"的实例）。

### 3.7 `where`

```json
{"exe": "D:\\…\\lx-music-desktop.exe",
 "userData": "C:\\Users\\…\\AppData\\Roaming\\lx-music-desktop",
 "LxDatas": "…\\LxDatas",
 "config_v2.json": "…", "data.json": "…",
 "user_api.json": "…", "lx.data.db": "…", "scripts_meta.json": "…"}
```

### 3.8 错误

```json
{"error": {"code": "lx_running",
           "message": "LX Music 正在运行，写库可能被它覆盖。请先关闭 LX，或加 --force。"}}
```

## 4. 安全边界速查

| 类别 | 命令 | 需关 LX |
|---|---|---|
| 只读 | `search` `song` `album` `leaderboard` `hot` `status` `lyric` `where` `backup` `db *` `playlist list/show/find` `script list/repo/active/verify` | 否 |
| 写 | `playlist create/rename/delete/add/remove`、`config-enable/disable`、`script install/update/remove/enable` | **是** |
| 播放控制 | `play` `pause` `toggle` `next` `prev` `seek` `volume` `mute` `collect` `uncollect` | 否（改的是运行状态） |
| Scheme | `play-song` `search-play` `dislike` `open-list` `play-list` | 否 |
