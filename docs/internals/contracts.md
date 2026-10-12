# 关键契约

> 这些是**不能改错**的定义。改代码前先读本页。
> 每条都有来源依据（源码或实测）。

---

## 歌曲 id

**唯一权威**：`lx-music-desktop/src/common/utils/tools.ts:3-56`（`toNewMusicInfo`）

| 平台 | id 形态 | 例 |
|---|---|---|
| `kw` `tx` `wy` `mg` | `<平台>_<songmid>` | `wy_2635292773` |
| **`kg`** | **`<songId>_<hash>`（无前缀！）** | `631537655_5A86012526BD981CD3AF1125E3FE234A` |
| `local` | **文件绝对路径** | `C:\Music\a.flac` |

```python
make_song_id("wy", "2635292773")                 # → wy_2635292773
make_song_id("kg", "631537655", "5A86…")         # → 631537655_5A86…（无 kg_）
make_song_id("kg", "631537655")                  # → 抛错（缺 hash）
```

**真实库统计**（1892 行）：kg 有 **934 行无前缀** vs 仅 24 行带 `kg_` 前缀。

### 硬规则

* ❌ **绝不能用** `id.split("_")[0]` 反推平台 —— 必须读 `source` 字段
* ❌ 不要给 kg 补 `kg_` 前缀（会生成 LX 不认、无法播放的 id）
* ✅ 读取时**容忍**两种形态（`parse_song_id`）
* ⚠️ 网上流传的某些文档（如 `workspace/docs/db.md`）曾错误声称
  kg 为 `kg_<audioid>` 且"LX 会自动补全" —— **已证伪**，见
  [`research/05-kg-id-定论与文档更正.md`](research/05-kg-id-定论与文档更正.md)

### 那 24 行 `kg_` 前缀怎么来的

运行时 `${musicInfo.source}_${musicInfo.id}` 二次拼接的产物
（`core/music/utils.ts:44`，换源写回路径）。已排除"旧版遗留数据"假说。

---

## meta

DB 中 `meta` 是 **JSON 字符串单列**。`my_list_music_info` 顶层只有 6 列：
`id / listId / name / singer / source / interval / meta`。

| 字段 | 说明 |
|---|---|
| `songId` | 来源是 songmid（local 为文件路径） |
| `albumName` / `albumId` / `picUrl` | 专辑与封面 |
| `qualitys` | **数组**，给 UI 角标用 |
| `_qualitys` | **字典**，判"能否播放"用这个 |
| `hash` | **kg 必需** |
| `strMediaMid` / `albumMid` / `id` | tx 特有 |
| `copyrightId` / `lrcUrl` / `trcUrl` / `mrcUrl` | mg 特有 |

**类型不稳定，必须容忍**：
* `songId`：kg int 89 / str 869；kw int 287 / str 14
* `picUrl` 可能是 JSON `null`（379 行）
* `qualitys[].hash` 键可能整个不存在

---

## 歌手分隔符（三种口径！）

| 场景 | 分隔符 | 位置 |
|---|---|---|
| **DB 存储/展示** | `、`（U+3001） | `my_list_music_info.singer` |
| **LX 换源匹配** | `、` `&` `;` `；` `/` `,` `，` `\|` | `musicSdk/index.js:80` |
| **Open API `status.singer`** | `;` | 实测 |

```python
split_singers("Raven & Kreyn、RudeLies、Nino Lucarelli")
# → ["Raven & Kreyn", "RudeLies", "Nino Lucarelli"]   （3 个，按 & 拆会错成 4）
```

> 展示只按 `、`；匹配照 LX 用全组。**两者不可混用**。

---

## 播放状态

Open API `/status` 的 `status` 是**字符串**：

| 值 | 含义 |
|---|---|
| `playing` | 播放中 |
| `paused` | 暂停 |
| `error` | 出错（**切歌过程中也会短暂出现，不是崩溃**） |
| `stoped` | 停止（LX 自己的拼写，只有一个 p） |

```python
is_playing(st)          # == (st["status"] == "playing")
bool(st["status"])      # ❌ 永远 True（"paused" 也是真值）
```

> 旧版 CLI 用布尔判断，导致 `lx toggle` **永远只暂停**。已修复并有回归测试。

### 状态变更非同步

实测：调用 `/play` 后**立即**读 `/status` 可能仍是 `paused`，约 1 秒后才变。
所以控制类命令只回显"已发送动作"，**不谎报状态已变**。

---

## Scheme URL

```
lxmusic://<path>?data=<encodeURIComponent(JSON.stringify(data))>
```

能力（Open API 没有的）：

| 用途 | path |
|---|---|
| 播放指定歌曲 | `music/play` （必传 name/singer/source/songmid/types；kg 加 hash、tx 加 strMediaMid、mg 加 copyrightId） |
| 搜索并播放 | `music/searchPlay` （必传 name） |
| 开关歌单 | `songlist/open` / `songlist/play` |
| 不喜欢 | `player/dislike` |

* **无返回值**（单向）
* **慢**：`searchPlay` 实测约 9 秒生效
* 派发方式：Windows 下 `cmd /c start "" "lxmusic://…"`（走 shell 关联；
  注册表 `HKCU\Software\Classes\lxmusic\shell\open\command` 指向 LX exe）
* LX 是**单实例**，已在运行时新调用会走 `second-instance` 分支，**不抢焦点**

---

## 退出码

| 码 | 含义 | 异常类 |
|---|---|---|
| `0` | 成功 | — |
| `1` | 运行时错误 | `LxCliError` 默认 |
| `2` | 用法错误 | `UsageError` |
| `3` | 需先关闭 LX | `LxRunningError` |
| `4` | 上游失败（网络/平台） | `SourceError`（`OpenApiError` 同） |
| `130` | 中断 | — |

`error.code` 细分类别：`usage` `path` `lx_running` `lx_not_running`
`openapi_disabled` `openapi_timeout` `db` `db_locked` `no_such_list`
`source` `unknown_source` `script_*` `scheme`。

---

## JSON 契约

1. `--json` 时 **stdout 只有 JSON**（日志走 stderr）
2. **成功必有输出**（不得 `exit 0` + 空 stdout）
3. 失败也输出 JSON：`{"error":{"code","message","detail"}}`
4. 形状稳定（字段名不随调用变化）
5. 敏感字段默认脱敏（`--show-secrets` 才显示）

---

## 平台源与显示名

| 平台 | 中文名 |
|---|---|
| `kg` | 酷狗音乐 |
| `kw` | 酷我音乐 |
| `tx` | **企鹅音乐**（不是"QQ音乐" —— 那是源码里的未使用硬编码串） |
| `wy` | 网易音乐（别名：小芸音乐） |
| `mg` | 咪咕音乐 |
| `local` | 本地音乐 |

显示名来自 i18n（`zh-cn.json:629-635`），前缀由
`common.sourceNameType`（`real`/`alias`）决定（`store/index.ts:87`）。

**输出永远用平台 id + 显示名，绝不用脚本名（Flower/SixYin）。**

---

## 数据库写规则

| 规则 | 说明 |
|---|---|
| **LX 运行时不得写** | LX 内存缓存 + 全量回写，会覆盖 |
| 单事务 | 每次调用一个事务，失败整体回滚 |
| `BEGIN IMMEDIATE` | 读-改-写前立即取写锁，防丢更新 |
| **幂等** | 同 id 重复添加不产生重复行 |
| `order` 可稀疏 | 重建时压实为 `0..n-1`；**读**时缺 order 的行排最后 |
| `order` 是保留字 | SQL 里必须加引号 `"order"` |
| 虚拟歌单 | `default`/`love` 无 `my_list` 行；可写歌，**不可改名/删除** |

---

## 音源脚本存储

```json
{"userApis": [{
  "id": "user_api_927_1784270441030",
  "name": "...", "description": "...", "version": "...",
  "author": "...", "homepage": "...",
  "allowShowUpdateAlert": true,
  "script": "gz_<base64(zlib.compress(utf8))>"
}]}
```

| 规则 | 说明 |
|---|---|
| **`gz_` 是 zlib，不是 gzip** | 用 `gzip.decompress` 会失败 |
| **Tab 缩进** | 与 LX 一致 |
| **原子写** | temp + rename；写坏会被 LX 改名 `.bak` 并弹错 |
| **更新保留原 id** | 否则用户 `common.apiSource` 选择会跳变 |
| **按内容哈希判更新** | `@version` 不可靠（有同版本号不同内容的实例） |
| **不得改动脚本字节** | 有些脚本有自毁/自校验（`lx/2.js`、`SCRIPT_MD5`） |
| 上限 | 单脚本 ≤9,000,000 字符；最多 20 个源 |
| 头部注释块 | 必须在**索引 0**；白名单 5 键；截断 24/36/56/1024/36 |
