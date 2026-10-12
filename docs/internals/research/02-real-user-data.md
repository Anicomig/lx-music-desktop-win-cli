# 洛雪音乐助手（LX Music Desktop）真实用户数据分析报告

> **分析对象**：`C:\Users\EDY\AppData\Roaming\lx-music-desktop\LxDatas\`
> **分析方式**：全程**只读**。SQLite 通过 `sqlite3.connect("file:...?mode=ro", uri=True)` 打开，未执行任何写入、`VACUUM` 或 WAL checkpoint。
> **分析时间**：2026-10-12
> **数据快照**：`lx.data.db` 14,774,272 字节（2026-09-16 10:35:48）；`-shm` 32768 字节。
>
> **关于 `-wal`**：分析开始时 `-wal` 为 **32 字节（空）**；分析过程中应用进程 `lx-music-desktop.exe`（PID 20688，启动于 2026-10-12 13:19:54）处于运行状态并自行向 `-wal` 写入，结束时增长至 107,152 字节。**这些写入来自应用本身，不是本次分析产生的**——本次分析的所有 SQLite 连接均以 `mode=ro` 打开，未执行任何写语句、`VACUUM` 或 checkpoint。所有数据目录内文件的修改时间在分析前后**完全未变**（`config_v2.json` 13:19:55、`data.json` 13:52:47、`user_api.json` 2026-09-10 13:44:08、`hot_key.json` 2026-07-22 10:35:27、`lx.data.db` 2026-09-16 10:35:48）。

> **标注约定**：所有结论均来自实际查询。凡属推断而非直接观测的内容，均以 **〔推断〕** 明确标注。

---

## 0. 数据目录总览

| 文件 | 大小 (bytes) | 最后修改时间 | 说明 |
|---|---:|---|---|
| `lx.data.db` | 14,774,272 | 2026-09-16 10:35:48 | 主数据库 |
| `lx.data.db-wal` | 32 | 2026-10-12 13:25:41 | 空 WAL（无未提交事务） |
| `lx.data.db-shm` | 32,768 | 2026-10-12 13:19:54 | 共享内存索引 |
| `config_v2.json` | 5,127 | 2026-10-12 13:19:55 | 应用设置 |
| `data.json` | 1,395 | 2026-10-12 13:52:47 | UI 状态 / 搜索历史 |
| `user_api.json` | 116,772 | 2026-09-10 13:44:08 | 导入的音源脚本 |
| `hot_key.json` | 1,782 | 2026-07-22 10:35:27 | 快捷键绑定 |
| `sync/` | 目录 | 2026-07-27 11:27:43 | 同步客户端/服务端凭证 |

数据库 PRAGMA 事实：`page_size=4096`、`page_count=3612`、`journal_mode=wal`、`encoding=UTF-8`、`user_version=0`、`application_id=0`、`auto_vacuum=0`、`freelist_count=0`。

`db_info` 表只有 1 行：`{id: 1, field_name: "version", field_value: "2"}` —— 即 **数据库 schema 版本号为 2**。

---

## 1. 数据库 Schema（完整 `sqlite_master` SQL）

数据库共 **9 张表**（含 2 张内部统计表）+ **5 个显式索引** + **5 个自动索引**。

### 1.1 核心业务表

#### `my_list` —— 歌单元数据

```sql
CREATE TABLE "my_list" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "source" TEXT,
    "sourceListId" TEXT,
    "position" INTEGER NOT NULL,
    "locationUpdateTime" INTEGER,
    PRIMARY KEY("id")
  )
```

- 主键：`id`（自动索引 `sqlite_autoindex_my_list_1`）
- 可空列：`source`、`sourceListId`、`locationUpdateTime`

#### `my_list_music_info` —— 歌单内歌曲（**核心表**）

```sql
CREATE TABLE "my_list_music_info" (
    "id" TEXT NOT NULL,
    "listId" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "singer" TEXT NOT NULL,
    "source" TEXT NOT NULL,
    "interval" TEXT,
    "meta" TEXT NOT NULL,
    UNIQUE("id","listId")
  )
```

- 唯一约束：`UNIQUE("id","listId")` → 自动索引 `sqlite_autoindex_my_list_music_info_1`
- 复合索引：`index_my_list_music_info ON my_list_music_info (id, listId)`
- 只有 `interval` 可空

#### `my_list_music_info_order` —— 歌单排序

```sql
CREATE TABLE "my_list_music_info_order" (
    "listId" TEXT NOT NULL,
    "musicInfoId" TEXT NOT NULL,
    "order" INTEGER NOT NULL
  )
```

```sql
CREATE INDEX "index_my_list_music_info_order" ON "my_list_music_info_order" (
    "listId",
    "musicInfoId"
  )
```

> **注意**：该表**没有主键、没有唯一约束**。`order` 是 SQL 保留字，查询时必须写成 `"order"`。

#### `download_list` —— 下载记录

```sql
CREATE TABLE "download_list" (
    "id" TEXT NOT NULL,
    "isComplate" INTEGER NOT NULL,
    "status" TEXT NOT NULL,
    "statusText" TEXT NOT NULL,
    "progress_downloaded" INTEGER NOT NULL,
    "progress_total" INTEGER NOT NULL,
    "url" TEXT,
    "quality" TEXT NOT NULL,
    "ext" TEXT NOT NULL,
    "fileName" TEXT NOT NULL,
    "filePath" TEXT NOT NULL,
    "musicInfo" TEXT NOT NULL,
    "position" INTEGER NOT NULL,
    PRIMARY KEY("id")
  )
```

> 列名 `isComplate` 是上游的**拼写错误**（应为 `isComplete`），CLI 必须原样沿用。

#### `dislike_list` —— 不喜欢列表

```sql
CREATE TABLE "dislike_list" (
    "type" TEXT NOT NULL,
    "content" TEXT NOT NULL,
    "meta" TEXT
  )
```

> 无主键、无索引。`meta` 可空。

#### `lyric` —— 歌词缓存

```sql
CREATE TABLE "lyric" (
    "id" TEXT NOT NULL,
    "source" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "text" TEXT NOT NULL
  )
```

> 无主键、无索引。

#### `music_url` —— 播放 URL 缓存

```sql
CREATE TABLE "music_url" (
    "id" TEXT NOT NULL,
    "url" TEXT NOT NULL
  )
```

> 无主键、无索引。

#### `music_info_other_source` —— 换源信息（**本数据集为空**）

```sql
CREATE TABLE "music_info_other_source" (
    "source_id" TEXT NOT NULL,
    "id" TEXT NOT NULL,
    "source" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "singer" TEXT NOT NULL,
    "meta" TEXT NOT NULL,
    "order" INTEGER NOT NULL,
    UNIQUE("source_id","id")
  )
```

```sql
CREATE INDEX "index_music_info_other_source" ON "music_info_other_source" (
    "source_id",
    "id"
  )
```

#### `db_info` —— 元数据

```sql
CREATE TABLE "db_info" (
    "id" INTEGER NOT NULL UNIQUE,
    "field_name" TEXT,
    "field_value" TEXT,
    PRIMARY KEY("id" AUTOINCREMENT)
  )
```

### 1.2 内部表与索引清单

```sql
CREATE TABLE sqlite_sequence(name,seq)
CREATE TABLE sqlite_stat1(tbl,idx,stat)
CREATE TABLE sqlite_stat4(tbl,idx,neq,nlt,ndlt,sample)
```

自动索引（`sql` 为 `NULL`）：`sqlite_autoindex_db_info_1`、`sqlite_autoindex_download_list_1`、`sqlite_autoindex_music_info_other_source_1`、`sqlite_autoindex_my_list_1`、`sqlite_autoindex_my_list_music_info_1`。

`sqlite_stat1` 有 6 行统计信息，例如 `my_list_music_info_order | index_my_list_music_info_order | 993 100 1`、`my_list_music_info | index_my_list_music_info | 993 2 1`。

### 1.3 实际行数

| 表 | 行数 |
|---|---:|
| `db_info` | 1 |
| `dislike_list` | 2 |
| `download_list` | 473 |
| `lyric` | 4,265 |
| `music_info_other_source` | **0** |
| `music_url` | 899 |
| `my_list` | 15 |
| `my_list_music_info` | 1,892 |
| `my_list_music_info_order` | 1,892 |

---

## 2. 歌单清单（`my_list` 全部 15 行）

按 `position` 升序：

| position | id | name | source | sourceListId | locationUpdateTime |
|---:|---|---|---|---|---|
| 0 | `kg_7b8006eaa1afd301b59c111e083a5863` | 电音 | `kg` | `1742411` | `NULL` |
| 1 | `kg_e3e0dceee5b87575f2a8f8fd7ab49595` | 【日系治愈】做你的守护神，做你的避风港 | `kg` | `4541959` | `NULL` |
| 2 | `kg_f44418f4d08f408ddb8e6ee2d640653f` | Anicomig喜欢的音乐 | `kg` | `1887337` | `NULL` |
| 3 | `userlist_1776872436891` | 本地ASMR | `NULL` | `NULL` | `1776872436891` |
| 4 | `kg_8cdcb0276d97a0b6eab11273afa236e1` | 孤独摇滚！~纽带乐队官方歌单 | `kg` | `id_6409482` | `NULL` |
| 5 | `kg_a1f0f6f30b5d27496e9c38858547c6d2` | 花譜-kaf O(∩_∩)O | `kg` | `id_3503017` | `NULL` |
| 6 | `wy_9c18cb75990e8fe4b46041c6932702b3` | 2025上半年Billboard术力口年榜 | `wy` | `13912472171` | `NULL` |
| 7 | `kg_58b9d6ef430ab4a71569ed736614396a` | 写作业时适合听的纯音乐(*^ω^*) | `kg` | `id_8011850` | `NULL` |
| 8 | `kg_831907691ba3a3b2d8986ed8d2b61c24` | ヨルシカ（yorushika） | `kg` | `id_9377748` | `NULL` |
| 9 | `wy_dd90c06f221d7bb7976c85c193004298` | 原神各国主题曲 | `wy` | `7700420165` | `NULL` |
| 10 | `userlist_1784778004746` | yorushika本地 | `NULL` | `NULL` | `NULL` |
| 11 | `userlist_1784782928613` | 本地-写作业时适合听的纯音乐 | `NULL` | `NULL` | `NULL` |
| 12 | `userlist_1785515376162` | 塞壬唱片-local | `NULL` | `NULL` | `NULL` |
| 13 | `tx_01f8d8ef9ba89ef43cb1c28c289d2a9f` | 塞壬唱片 | `tx` | `9413313362` | `1786517368997` |
| 14 | `kg_dd55b49370e11e913853796b37c3bfcb` | HOYO-MiX热单精选 | `kg` | `id_8247632` | `NULL` |

### 2.1 人工歌单 vs 机器生成歌单（**关键区分**）

**用户手工创建的歌单（4 个）** —— id 形如 `userlist_<epoch毫秒>`，`source` 与 `sourceListId` 均为 `NULL`：

- `userlist_1776872436891` — 本地ASMR
- `userlist_1784778004746` — yorushika本地
- `userlist_1784782928613` — 本地-写作业时适合听的纯音乐
- `userlist_1785515376162` — 塞壬唱片-local

> `userlist_` 后缀的整数是 **Unix epoch 毫秒时间戳**。例如 `1776872436891` → 2026-04-22T23:40:36.891（+08:00）。这说明 id 由创建时刻生成，**天然唯一且不会重复**，但可读性差。

**从在线平台导入的歌单（11 个）** —— id 形如 `<source>_<32位小写十六进制>`，均由平台歌单派生：

- `kg_` 前缀 8 个、`wy_` 前缀 2 个、`tx_` 前缀 1 个。

### 2.2 `sourceListId` 的两种格式（易被忽略的坑）

| kind | 样例 | 出现的歌单 |
|---|---|---|
| 纯数字 | `1742411`、`4541959`、`1887337`、`13912472171`、`7700420165`、`9413313362` | kg(3) / wy(2) / tx(1) |
| `id_` + 数字 | `id_6409482`、`id_3503017`、`id_8011850`、`id_9377748`、`id_8247632` | 仅 kg(5) |

**同一 `source`（kg）内部并存两种前缀形式** —— 5 个带 `id_`、3 个不带。CLI 在解析/回写 `sourceListId` 时不能假设统一格式，也不应在剥离 `id_` 前缀时做归一化写回（会破坏与上游的对应关系）。

---

## 3. 内置虚拟歌单 `default` 与 `love`

| listId | `my_list_music_info` 行数 | `my_list` 中存在行? | `my_list_music_info_order` 行数 |
|---|---:|---|---:|
| `default` | 164 | **否（0 行）** | 164 |
| `love` | 188 | **否（0 行）** | 188 |

**确认结论**：`default`（默认列表 / 试听列表）与 `love`（我喜欢）**在 `my_list` 中没有任何行**，它们是**虚拟列表**，仅存在于 `my_list_music_info` + `my_list_music_info_order` 中，由应用硬编码。

按 `listId` 分组的全部歌曲数（含虚拟列表）：

| listId | 行数 | distinct id | 在 `my_list`? |
|---|---:|---:|---|
| `tx_01f8d8ef9ba89ef43cb1c28c289d2a9f` | 246 | 246 | YES |
| `userlist_1785515376162` | 219 | 219 | YES |
| `kg_f44418f4d08f408ddb8e6ee2d640653f` | 219 | 219 | YES |
| `love` | 188 | 188 | **NO（虚拟）** |
| `default` | 164 | 164 | **NO（虚拟）** |
| `kg_58b9d6ef430ab4a71569ed736614396a` | 159 | 159 | YES |
| `userlist_1784782928613` | 158 | 158 | YES |
| `userlist_1776872436891` | 98 | 98 | YES |
| `kg_7b8006eaa1afd301b59c111e083a5863` | 97 | 97 | YES |
| `userlist_1784778004746` | 89 | 89 | YES |
| `kg_831907691ba3a3b2d8986ed8d2b61c24` | 89 | 89 | YES |
| `kg_dd55b49370e11e913853796b37c3bfcb` | 61 | 61 | YES |
| `kg_a1f0f6f30b5d27496e9c38858547c6d2` | 35 | 35 | YES |
| `wy_9c18cb75990e8fe4b46041c6932702b3` | 27 | 27 | YES |
| `kg_e3e0dceee5b87575f2a8f8fd7ab49595` | 21 | 21 | YES |
| `kg_8cdcb0276d97a0b6eab11273afa236e1` | 14 | 14 | YES |
| `wy_dd90c06f221d7bb7976c85c193004298` | 8 | 8 | YES |

**合计 17 个 listId** = `my_list` 的 15 个 + 2 个虚拟列表。**没有空歌单**（`my_list` 中每个歌单都至少有 1 首歌）。

---

## 4. 歌曲行结构（**最关键部分**）

### 4.1 `source` 取值枚举与计数（全表 1,892 行）

| source | 行数 | 占比 | 说明 |
|---|---:|---:|---|
| `kg` | 958 | 50.6% | 酷狗 |
| `local` | 565 | 29.9% | 本地文件 |
| `kw` | 301 | 15.9% | 酷我 |
| `wy` | 53 | 2.8% | 网易云 |
| `tx` | 10 | 0.5% | QQ 音乐 |
| `mg` | 5 | 0.3% | 咪咕 |
| **合计** | **1,892** | 100% | |

**共 6 个不同的 `source` 值**，无 `NULL`、无空字符串。

各歌单的 source 分布（体现"歌单来源"与"歌曲来源"可分离）：

- 从 `kg` 导入的歌单中混有 `wy`/`kw` 歌曲，例如 `kg_f44418f4d08f408ddb8e6ee2d640653f`（Anicomig喜欢的音乐）：`kg` 217 + `wy` 1 + `kw` 1。
- `wy_9c18cb75990e8fe4b46041c6932702b3`：`wy` 21 + `kg` 6。
- `tx_01f8d8ef9ba89ef43cb1c28c289d2a9f`（塞壬唱片）：`kw` 195 + `kg` 35 + `tx` 6 + `wy` 5 + `mg` 5。
- 4 个 `userlist_` 歌单为纯 `local`。

> **CLI 影响**：歌单的 `source` 字段**不代表**其内部歌曲的 `source`。必须逐行读取歌曲的 `source`。

### 4.2 `id` 格式规则（**CLI 必须精确解析**）

先给出经过全量 1,892 行正则归类的**格式模板**：

| source | id 模板 | 行数 | 样例 |
|---|---|---:|---|
| `kg` | `<数字>` + `_` + `<32位大写HEX>` | 934 | `631537655_5A86012526BD981CD3AF1125E3FE234A` |
| `kg` | `kg_` + `<数字>` + `_` + `<32位大写HEX>` | 24 | `kg_500951349_EF93F2291FE39466A16E4B795C235933` |
| `kw` | `kw_` + `<数字>` | 301 | `kw_26275820` |
| `wy` | `wy_` + `<数字>` | 53 | `wy_2635292773` |
| `tx` | `tx_` + `<12位字母数字MID>` | 10 | `tx_001SxL503C84XM` |
| `mg` | `mg_` + `<数字>` | 5 | `mg_1140207815` |
| `local` | `<绝对文件路径>`（无 `_` 分隔语义） | 565 | `C:\Users\EDY\Music\...\xxx.flac` |

#### ⚠️ **重大发现：并非所有 id 都遵循 `<source>_` 前缀约定**

全量统计：**1,892 行中只有 393 行（20%）的 `id` 以 `<source>_` 开头；1,499 行（79%）不是。**

| source | 不以 `<source>_` 开头的行数 | 原因 |
|---|---:|---|
| `kg` | **934** | 使用**裸** `<songId>_<hash>` 形式，无 `kg_` 前缀 |
| `local` | **565** | id 就是文件系统绝对路径 |

非 `local` 的非前缀情况**全部集中在 `kg`**（`kw`/`wy`/`tx`/`mg` 100% 带前缀）。

**裸 kg id 的合法性已验证**：对这 934 行，将 id 按第一个 `_` 切分为 `(a, b)`，与 `json.loads(meta)` 的 `(songId, hash)` 比对——

```
bare-form rows matching meta.songId_hash: 934; mismatching: 0; meta-unparsable: 0
```

即 **934/934 完全一致**。所以裸形式 `<songId>_<hash>` 是**语义完整且自洽**的，只是缺少 `kg_` 前缀。

**示例（`kg` 裸形式）**：

```
'631537655_5A86012526BD981CD3AF1125E3FE234A'  | Amnesia (DJ阿虎) | DJ亚哲、DJ阿虎 | 03:11
'162081113_EF92CAA2334E9369BBE644E8EFE448CD'  | Amnesia          | 阿吉野马      | 04:26
'623367999_73857B3B13E7FAB1BEB63D2D68BF0668'  | Amnesia          | Electronic Mortal、Electronic Ponos | 02:16
'77126248_48BB2A9A22A4CE3FC86C249848B99BC1'   | Everything's Alright | 塞壬唱片-MSR、澤田かおり | 04:09
```

**示例（`kg_` 带前缀形式，全部 24 行都在 `tx_01f8...` 歌单内）**：

```
'kg_500951349_EF93F2291FE39466A16E4B795C235933' | Paper Boat | 塞壬唱片-MSR、chengcheng、Maria Landi
'kg_431907502_457AD81BE90B84FE5044EA5102951ACB' | 烛影暖      | 塞壬唱片-MSR、KH
'kg_436580072_150276888B0FA7237438B6C6888F71DC' | Epilogue   | 塞壬唱片-MSR、SHIKI
```

**关键分布事实**：这 24 行 `kg_` 前缀 id **100% 位于 `tx_01f8d8ef9ba89ef43cb1c28c289d2a9f` 歌单内**，而所有其它 12 个含 `kg` 歌曲的歌单**全部**使用裸形式。

```
'kg_f44418f4d08f408ddb8e6ee2d640653f' kg_prefixed=0    bare_numeric_hex=217  total_kg=217
'love'                                kg_prefixed=0    bare_numeric_hex=184  total_kg=184
'tx_01f8d8ef9ba89ef43cb1c28c289d2a9f' kg_prefixed=24   bare_numeric_hex=11   total_kg=35
（其余 11 个歌单均为 kg_prefixed=0）
```

并且 `tx_01f8...` 是**唯一一个同时存在两种形式的歌单**：

```
=== mixed within the same list? ===
    tx_01f8d8ef9ba89ef43cb1c28c289d2a9f
```

> **〔推断〕** 前缀形式很可能由"换源"操作产生（在 tx 歌单内把歌曲换成 kg 音源），或由较新版本的代码路径写入。此处仅为推断，数据库中没有直接证据。
> **CLI 影响**：解析 `id` **绝不能**依赖"前 3 个字符是 source"。正确做法是：用 `<source>_` 前缀尝试剥离，**失败时按 source 分派**——`kg` 回退为 `<songId>_<hash>`，`local` 直接当路径处理。

#### `local` 的 id

`local` 的 id 是**绝对文件路径**，且**同时混有 Windows 与 Android 路径**（说明数据经同步从手机端合并而来）：

```
'C:\Users\EDY\Music\ヨルシカ（yorushika）\あの夏に咲け (在那个夏天绽放) - ヨルシカ.flac'
'/storage/emulated/0/Music/ASMR/SnapTube Audio/[ASMR] あったかぁい♡ゼロ距離囁きで脳ゾクゾク♡睡眠導入_耳かき_綿棒_吐息 EarCleaning_ Tingle_ Triggers for Sleep【KU100(M4A_1.m4a'
```

`local` 路径中含 `\`、`/`、`、`、空格、emoji、全角括号等；且**含 `_`**，因此**任何按 `_` 切分 id 的通用逻辑都会破坏 local id**。

### 4.3 `singer` 中多个歌手的**分隔符**（实测）

对全表 1,892 行统计分隔符出现次数：

| 字符 | Unicode | 行数 | 是否分隔符 |
|---|---|---:|---|
| `、` | U+3001 IDEOGRAPHIC COMMA | **497** | ✅ **是（唯一规范分隔符）** |
| `;` | U+003B SEMICOLON | 217 | ❌ 否（属于歌手名本身） |
| `&` | U+0026 AMPERSAND | 6 | ❌ 否（属于歌手名本身） |
| `，` | U+FF0C FULLWIDTH COMMA | **0** | — |
| `,` | U+002C ASCII COMMA | **0** | — |
| `/` | U+002F SLASH | **0** | — |

**结论：多歌手由 `、`（U+3001 顿号）分隔。**

关键证据 —— **ASCII 逗号在 `singer` 中从未出现（0 行）**：

```
=== singer exact values containing ASCII comma (potential multi-singer) ===
    TOTAL rows with ASCII comma in singer: 0
```

同时也**没有任何一行同时含 `、` 和 `,`**（`count=0`）。这说明 `、` 是**可靠且无歧义**的分隔符。

**真实多歌手样例**：

```
sep='、' source=kg  singer='DJ亚哲、DJ阿虎'                         name='Amnesia (DJ阿虎)'
sep='、' source=kg  singer='Electronic Mortal、Electronic Ponos'   name='Amnesia'
sep='、' source=kg  singer='塞壬唱片-MSR、澤田かおり'                 name="Everything's Alright"
sep='、' source=kg  singer='塞壬唱片-MSR、Dazbee、*Luna'            name='酸橙色信笺'
sep='、' source=kg  singer='塞壬唱片-MSR、Adam Gubman、Chris Mann、Sage X Price'  （4 人）
sep='、' source=wy  singer='陈致逸、HOYO-MiX'                       name='璃月 Liyue'
```

**警告 —— 不要按 `;` 或 `&` 切分**，它们是歌手名的一部分：

```
'&' →  'Yunomi&nicamoq'              name='インドア系ならトラックメイカー'   ← 单一组合名
'&' →  'Tanir & Tyomcha'             name='Da Da Da'                    ← 单一组合名
'&' →  'Hillsong Young & Free'       name='Wake (Studio)'               ← 单一组合名
'&' →  'MYTH & ROID'                 name='STYX HELIX'                  ← 单一组合名
'&' →  'Raven & Kreyn、RudeLies、Nino Lucarelli'  ← 混合！& 在第一个歌手名内，、才是分隔符
```

第 5 例是最危险的案例：`Raven & Kreyn、RudeLies、Nino Lucarelli` 正确切分是 **3 个歌手**（`Raven & Kreyn` / `RudeLies` / `Nino Lucarelli`），若按 `&` 切分则会错误得到 4 段。**必须只按 `、` 切分。**

`singer` 中无控制字符（0 行）。

### 4.4 `meta` JSON 列结构

**全部 1,892 行的 `meta` 均可被 `json.loads` 成功解析，失败数 = 0。**

#### 4.4.1 按 source 的键集合

| source | 行数 | keys |
|---|---:|---|
| `kg` | 921 | `_qualitys, albumId, albumName, hash, picUrl, qualitys, songId` |
| `kg` | 37 | `_qualitys, albumName, hash, picUrl, qualitys, songId`（**无 `albumId`**） |
| `kw` | 187 | `_qualitys, albumId, albumName, hash, picUrl, qualitys, songId` |
| `kw` | 114 | `_qualitys, albumId, albumName, picUrl, qualitys, songId`（**无 `hash`**） |
| `wy` | 53 | `_qualitys, albumId, albumName, picUrl, qualitys, songId` |
| `tx` | 6 | `_qualitys, albumId, albumMid, albumName, id, picUrl, qualitys, songId, strMediaMid` |
| `tx` | 4 | `_qualitys, albumId, albumName, picUrl, qualitys, songId` |
| `mg` | 5 | `_qualitys, albumId, albumName, picUrl, qualitys, songId` |
| `local` | 565 | `albumName, ext, filePath, picUrl, songId`（**完全不同的结构**） |

> `_qualitys` 是 `qualitys` 数组按键展开的冗余副本（`_` 前缀 = 去重/查找用）。CLI 读取时以 `qualitys` 数组为准。

#### 4.4.2 完整美化示例

**`kg`**（id `631537655_5A86012526BD981CD3AF1125E3FE234A`，listId `default`）：

```json
{
  "songId": 631537655,
  "albumName": "Amnesia(DJ阿虎版)",
  "picUrl": "http://imge.kugou.com/stdmusic/480/20260730/20260730112323282773.jpg",
  "qualitys": [
    { "type": "128k",      "size": "2.93 MB",  "hash": "5A86012526BD981CD3AF1125E3FE234A" },
    { "type": "320k",      "size": "7.31 MB",  "hash": "407852F20B636B9ED6EC79EB00795796" },
    { "type": "flac",      "size": "22.25 MB", "hash": "0BCFAC694F6DE0A438826AC6174C7540" },
    { "type": "flac24bit", "size": "40.91 MB", "hash": "2E3E1F58A8A001E4D8DE189536B6293E" }
  ],
  "_qualitys": {
    "128k":      { "size": "2.93 MB",  "hash": "5A86012526BD981CD3AF1125E3FE234A" },
    "320k":      { "size": "7.31 MB",  "hash": "407852F20B636B9ED6EC79EB00795796" },
    "flac":      { "size": "22.25 MB", "hash": "0BCFAC694F6DE0A438826AC6174C7540" },
    "flac24bit": { "size": "40.91 MB", "hash": "2E3E1F58A8A001E4D8DE189536B6293E" }
  },
  "albumId": "201445175",
  "hash": "5A86012526BD981CD3AF1125E3FE234A"
}
```

**`kw`**（id `kw_26275820`）：

```json
{
  "songId": "26275820",
  "albumName": "ミカヅキの航海",
  "picUrl": "http://img1.kwcdn.kuwo.cn/star/albumcover/500/s4s49/87/1017012233.jpg",
  "qualitys": [
    { "type": "128k", "size": "4.0Mb" },
    { "type": "320k", "size": "9.99Mb" },
    { "type": "flac", "size": "30.79Mb" }
  ],
  "_qualitys": {
    "flac": { "size": "30.79MB" },
    "320k": { "size": "9.99MB" },
    "128k": { "size": "4.0MB" }
  },
  "albumId": "3655002"
}
```

> ⚠️ **注意大小写不一致**：`qualitys[].size` 为 `"4.0Mb"`（小写 b），而 `_qualitys` 里为 `"4.0MB"`（大写 B）。且 `hash` 键在此行**不存在**。

**`wy`**（id `wy_2635292773`）：

```json
{
  "songId": 2635292773,
  "albumName": "原神-炽炎交逐之原 Land of Tleyaoyotl",
  "picUrl": "https://p2.music.126.net/DTUwP3lY4oiwd8AM1um_kQ==/109951170031752778.jpg",
  "qualitys": [
    { "type": "128k",      "size": "4.35 MB" },
    { "type": "320k",      "size": "10.87 MB" },
    { "type": "flac",      "size": "30.17 MB" },
    { "type": "flac24bit", "size": "56.18 MB" }
  ],
  "_qualitys": {
    "flac24bit": { "size": "56.18 MB" },
    "flac":      { "size": "30.17 MB" },
    "320k":      { "size": "10.87 MB" },
    "128k":      { "size": "4.35 MB" }
  },
  "albumId": 250336341
}
```

**`tx`**（id `tx_001SxL503C84XM`）—— 键最多：

```json
{
  "songId": "001SxL503C84XM",
  "albumName": "インドア系ならトラックメイカー (UR7UV Remix)",
  "picUrl": "https://y.gtimg.cn/music/photo_new/T002R500x500M000003HiZu720TF7x.jpg",
  "qualitys": [
    { "type": "128k", "size": "2.98 MB" },
    { "type": "320k", "size": "7.44 MB" }
  ],
  "_qualitys": {
    "128k": { "size": "2.98 MB" },
    "320k": { "size": "7.44 MB" }
  },
  "albumId": "003HiZu720TF7x",
  "strMediaMid": "001SxL503C84XM",
  "albumMid": "003HiZu720TF7x",
  "id": 246330673
}
```

> tx 的 `songId` 是**字符串 MID**，这正是 `tx_001SxL503C84XM` 中 id 的来源。`meta.id` 是数字的内部 id，**不要与 `songId` 混淆**。

**`mg`**（id `mg_1140207815`）—— 注意 `qualitys[].size` 和 `hash` 全为空串，且 `picUrl` 是相对路径：

```json
{
  "songId": "1140207815",
  "albumName": "《风雪过境》游戏原声",
  "albumId": "1140207757",
  "picUrl": "/data/oss/resource/00/2c/np/hl.webp",
  "qualitys": [
    { "type": "flac", "size": "", "hash": "" },
    { "type": "320k", "size": "", "hash": "" },
    { "type": "128k", "size": "", "hash": "" }
  ],
  "_qualitys": {
    "flac": { "size": "", "hash": "" },
    "320k": { "size": "", "hash": "" },
    "128k": { "size": "", "hash": "" }
  }
}
```

**`local`**（id 为文件路径）—— 结构完全不同：

```json
{
  "albumName": "夏草が邪魔をする",
  "filePath": "C:\\Users\\EDY\\Music\\ヨルシカ（yorushika）\\あの夏に咲け (在那个夏天绽放) - ヨルシカ.flac",
  "songId": "C:\\Users\\EDY\\Music\\ヨルシカ（yorushika）\\あの夏に咲け (在那个夏天绽放) - ヨルシカ.flac",
  "picUrl": "",
  "ext": "flac"
}
```

> `local` 的 `songId` **等于** `filePath` **等于**行的 `id`。此处的 `\\` 是 JSON 转义，实际存储为单个 `\`。

#### 4.4.3 类型不稳定（CLI 必须容忍）

| source | 键 | 类型分布 |
|---|---|---|
| `kg` | `songId` | `int` 89 / `str` 869 |
| `kg` | `albumId` | `str` 921（37 行缺失） |
| `kg` | `picUrl` | `str` 579 / **`null` 379** |
| `kw` | `songId` | `int` 287 / `str` 14 |
| `kw` | `albumId` | `int` 100 / `str` 201 |
| `wy` | `songId` | `int` 49 / `str` 4 |
| `wy` | `albumId` | `int` 49 / `str` 4 |
| `tx` | `songId` | `str` 10 |
| `mg` | `songId` | `str` 5 |
| `local` | `songId` | `str` 565 |

**同一个键在同一个 source 内就可能是 int 或 str**，且 `picUrl` 可以是 JSON `null`。CLI 读取时必须按字符串归一化。

#### 4.4.4 `qualitys[]` 元素结构

| source | 元素键 | 出现次数 |
|---|---|---:|
| `kg` | `["hash","size","type"]` | 3,173 |
| `kw` | `["hash","size","type"]` | 577 |
| `kw` | `["size","type"]`（**无 hash**） | 301 |
| `mg` | `["hash","size","type"]` | 19 |
| `tx` | `["hash","size","type"]` | 12 |
| `tx` | `["size","type"]` | 14 |
| `wy` | `["hash","size","type"]` | 16 |
| `wy` | `["size","type"]` | 170 |

`type` 的全部取值：

```
{'128k': 1327, '320k': 1296, 'flac': 1147, 'flac24bit': 493,
 'atmos': 5, 'atmos_plus': 1, 'master': 5, 'hires': 4, '192k': 4}
```

> **`hash` 键并非总是存在**（kw 301 行、wy 170 行、tx 14 行缺失）。CLI 不能假定 `item["hash"]` 一定可读。

### 4.5 `interval` 时长格式

| 格式 | 行数 |
|---|---:|
| `MM:SS`（分钟 2 位） | 1,825 |
| **其它**（实为 `MMM:SS`，分钟 3 位） | 47 |
| `M:SS`（分钟 1 位） | 20 |

`interval` **无 NULL、无空串**。

⚠️ **分钟位可能是 1~3 位**，因为存在超长 ASMR 音频。共 **81 行时长 ≥ 60 分钟**，最长样例：

```
'133:18'  [ASMR] あったかぁい♡ゼロ距離囁きで…
'179:02'  ASMR 至上1番音が良い3時間このゾクゾク耐えられる？…
'184:23'  [ASMR/3時間] 竹耳かきたっぷり。…
```

> CLI 解析 `interval` 时若假设 `^\d{2}:\d{2}$` 会漏掉 67 行。**不要**把它转换为秒后假定 < 3600。

---

## 5. `my_list_music_info_order` 排序机制

### 5.1 总体

- 行数 **1,892**，与 `my_list_music_info` 行数**完全相等**。
- 每个 `listId` 的 `order` 均从 **0** 开始。
- **没有孤儿行**（`musicInfoId` 在 `my_list_music_info` 中找不到对应 `(listId, id)` 的行）：全部 17 个歌单 `orphanOrder=0`。
- **没有缺行**（每首歌都有对应 order 行）：全部 17 个歌单 `missingOrder=0`。

### 5.2 稠密性 —— **发现 1 处稀疏**

16 个歌单的 `order` 均为**稠密 `0..n-1`**。**唯一例外**：

```
listId='tx_01f8d8ef9ba89ef43cb1c28c289d2a9f'  music=246  order=246  min=0  max=247  distinct=246
```

全局检查结果：

```
=== global check: any list whose max(order) != count-1 ? ===
  lists violating dense 0..n-1: 1
    {'listId': 'tx_01f8d8ef9ba89ef43cb1c28c289d2a9f', 'n': 246, 'mn': 0, 'mx': 247, 'd': 246}
=== sparse order gap in tx_ list ===
  orders present=246 min=0 max=247 MISSING order values=[226, 227]
```

即 `tx_01f8...` 歌单中 **`order` 值 226 和 227 缺失**，实际只有 246 行，但最大值到 247。

> **〔推断〕** 典型成因是**曾删除过 2 首歌而未重排后续 `order`**。
> **CLI 影响（重要）**：**不能**假设 `order` 是 `0..n-1` 的连续下标，也**不能**用 `order` 直接作为数组索引。必须按 `order` 升序读取再自行建立位置映射；若 CLI 要写入排序，应先对目标歌单做一次 `order` 重排归零。

### 5.3 排序语义

`order` 是歌单内的展示顺序，与插入时间无关。示例（`love` 歌单）：

```
order=0  id='C:\Users\EDY\Music\ヨルシカ（yorushika）\あの夏に咲け (在那个夏天绽放) - ヨルシカ.flac'
order=1  id='27316142_E4215CF77C0A1DED5C4DF1032392FAB2'
order=2  id='2930796_7E46F307574FB25BABC1F68841DD05E3'
order=3  id='32826349_44659DBF5B30216E9337E2505BB2FEC0'
order=4  id='434687541_1F6BB8CA35C41BAC6EFB2D9B91A94C7C'
```

以 `userlist_1776872436891`（本地ASMR）为例，`order=0..4` 为不同的 ASMR 音轨，顺序稳定。

`tx_01f8...` 歌单中 `order` 跨越 0..247 而缺 226/227 —— **该歌单内 `order` 值本身是唯一的**（`d=246`），所以按 `order` 排序仍是确定性全序。

---

## 6. 重复与数据质量

### 6.1 单歌单内重复 —— **零**

```sql
SELECT id, listId, COUNT(*) n FROM my_list_music_info GROUP BY id, listId HAVING n>1
```

结果：**`(id,listId)` 重复组 = 0**。与 `UNIQUE("id","listId")` 约束一致。

### 6.2 跨歌单重复（同 id 出现在多个歌单）

- **有 192 个不同 id 出现在 >1 个歌单中**。
- 最高出现在 **4 个歌单**：

```
id='83252353_AFB15305C3E3FAE258200F9A3525892B' lists=4  恋のうた / Yunomi、鬼頭明里
    in: default | kg_e3e0dceee5b87575f2a8f8fd7ab49595 | kg_f44418f4d08f408ddb8e6ee2d640653f | love
```

出现在 3 个歌单的样例：

```
'1051821583_38A6C13F5A1A4AC97EBAE2185507715C'  Cry For Me (feat. Ami) / Michita
'116989871_8B4D0B91A150C3BE70058F5D8A668876'   老人と海 (老人与海) / ヨルシカ
'191858996_DBAFE33B7E4AE8BF8629D79515D67856'   青春コンプレックス / 結束バンド
'29029652_5B9834202642933A7E4F226B806BDDFF'    彼女は旅に出る (她踏上了旅程) / 鎖那
'2930796_7E46F307574FB25BABC1F68841DD05E3'     3rd Coast (Jealousy) / 韩国群星
'32826349_44659DBF5B30216E9337E2505BB2FEC0'    インドア系ならトラックメイカー / Yunomi
'506755631_04281DFEFC6BF44214E0A271A2D73AE9'   LEMON MELON COOKIE / ヰ世界情緒
'58365692_848E7C5B1F28BE228C167A4EF4D4FE61'    Teeth / 5 Seconds of Summer
'wy_2700788167'                                臙脂 ft. 重音テト / bk、重音テト
（共 16 个出现在 3 个歌单，其余出现在 2 个）
```

> **这是正常现象**（同一首歌被加入多个歌单），**不是数据错误**。CLI 的"删除歌单内歌曲"必须带 `listId` 条件，否则会误删其它歌单的同一首歌。

### 6.3 **跨 source 的同一首歌** —— 256 组

```sql
SELECT name, singer, COUNT(DISTINCT source) ns FROM my_list_music_info
GROUP BY name, singer HAVING ns>1
```

**结果：256 组 `(name, singer)` 对应多个 `source`。**

典型样例：

| name | singer | sources | 行数 |
|---|---|---|---:|
| End of Days | ReoNa | `kw,kg,local` | 3 |
| 老人と海 (老人与海) | ヨルシカ | `kg,local` | 4 |
| インドア系ならトラックメイカー | Yunomi | `wy,kg` | 4 |
| あの夏に咲け (在那个夏天绽放) | ヨルシカ | `local,kg` | 4 |
| 花に亡霊 (花上的亡灵) | ヨルシカ | `kg,local` | 3 |
| 纳塔 Natlan | HOYO-MiX | `wy,kg` | 3 |
| Everything's Alright | 塞壬唱片-MSR、澤田かおり | `kg,kw` | 3 |
| 嘘月 | ヨルシカ | `kg,local` | 3 |
| 又三郎 | ヨルシカ | `kg,local` | 3 |
| 青涩 | Powerful_K | `kg,local` | 2 |
| 雪国 | ヨルシカ | `kg,local` | 2 |
| 雨中舞 | Soulloom苏洛牧 | `kg,local` | 2 |

> **主因**：用户把本地文件（`local`）与在线音源（`kg`/`wy`）的同名歌曲都加入了歌单。**`(name, singer)` 不是全局唯一键。**

**仅按 `name` 匹配会更糟** —— 同一标题对应 3 个不同 source 的例子：

```
'愚人曲'、'大骑士领'、'夏日潜行'、'乱序'、'Running In The Dark'、'Radiant'、
'G大调弦乐小夜曲'、'FIVE超新星☆全能live时刻！'、"Everything's Alright"、'End of Days'
```

### 6.4 同 source 内 `(name, singer)` 对应多个 id —— 11 组

```sql
SELECT name, singer, source, COUNT(DISTINCT id) ni FROM my_list_music_info
GROUP BY name, singer, source HAVING ni>1
```

**共 11 组**。分两类：

**A. 同 `songId` 不同 `hash`**（同一首歌的不同版本/文件）：

```
'Bunny Jump (bronya电音曲)' / hanser / kg
    '41919669_356DA5B1D6C1A9C27889E1B7AD2CCE35'
    '41919669_A10ECDBFDA178DC3454BB25AEAACEC81'      ← 同 songId，不同 hash

'UPGRADE (D)(feat.Laco)' / 澤野弘之 / kg
    '464854341_07B9B828D0DFAA52C7C077BDDCFC652A'
    '464854341_BCB0542BA472BF92085C62F7FDAAF8FF'

'トゥットゥルー (嘟嘟噜)' / 花澤香菜 / kg
    '2874475_35D2053959C039C0E618E883BF4231BF'
    '2874475_43DA10E718EB49ADB58F62D9AD86BB1A'

'少年' / 梦然 / kg
    '62878164_5D93A1ABC5BA5838D1128547A7FB4EF1'
    '62878164_D94F0758423EDFBD8DAB6288D4792BB9'

'未来轮廓' / 陈乐一 / kg
    '55367455_40E4CC17A0AAFFA31F2633D5CB083206'
    '55367455_B960D43E85AB92B429A0CD6063EC1E89'
```

**B. 完全不同 `songId`**（上游重复收录）：

```
'G大调弦乐小夜曲' / 深广轻音乐团 / kg   —— 3 个不同 id
    '2745913_553EA4BB4ED8C0EFD7B20E4CFFE8AA27'
    '384155055_94B447F55C6784221E012DEE4784EBD5'
    '384166602_666F517BC9987B5AD9BDAAE68B15A9F6'

'MILABO' / ずっと真夜中でいいのに。 / kg   —— 2 个 id，共 4 行
    '305485356_A6DACC88F8B8C0916C5C6AAEC253BF1D'
    '77518949_104C3E8D4095DD1868D317C48813D160'

'Scarborough Fair' / Sarah Brightman / kg
    '302501889_002F5095E3C15D9EE0BC624D8B987B07'
    '510521_7AB49B3B2D1CAAD0CB2A49357A5F98B0'

'又三郎' / ヨルシカ / kg
    '110259707_A273A77A9D37D6F8376D2D0EA6275BC7'
    '236085730_9AE9D46BCEB6371C906B68BEC6DB6D78'

'ハレハレヤ (朗朗晴天)' / 猫瑾 / kg
    '54983400_758369B06168527C6CE5016B68F74549'
    '54983400_D65D559861A58799CF30F3D697B61953'   ← A 类

'ASMR Triggers for Your Sleep 【Whispering/KU100/睡眠導入】' / Macoto ASMR まこと。 / local
    两个不同路径的 m4a 文件
```

> **CLI 影响**：去重时若用 `(name, singer)` 做键会**误删**；若用完整 `id` 则会保留同 songId 的不同 hash 版本（这是**正确的**，因为它们是不同的音频文件）。

### 6.5 NULL / 空值统计

`my_list_music_info` 全表：

| 列 | NULL | 空字符串 |
|---|---:|---:|
| `id` | 0 | 0 |
| `listId` | 0 | 0 |
| `name` | 0 | 0 |
| `singer` | 0 | 0 |
| `source` | 0 | 0 |
| `interval` | **0** | **0** |
| `meta` | 0 | 0 |

**该表数据非常干净：无任何 NULL 或空串。** 唯一的"空"出现在 `meta` 内部的嵌套字段（`picUrl: null` × 379、`qualitys[].size: ""`、`qualitys[].hash: ""`）。

`my_list` 中：`source`/`sourceListId`/`locationUpdateTime` 可为 `NULL`（4 个 `userlist_` 歌单即为 `NULL`）。

### 6.6 全局 id 唯一性

```
rows=1892  distinct id=1683
distinct (id,source) pairs=1683
```

**1,683 个不同的歌曲 id**，1,892 行。209 行是跨歌单重复。

---

## 7. `config_v2.json`

文件 5,127 字节，顶层 **2 个键**：`version`、`setting`。

- `version` = `"2.1.0"`
- `setting` = 一个**扁平化的 135 键字典**（键名用 `.` 分层，但 JSON 结构本身是平的）

> **未发现任何密钥/token/密码**。已对 `pass|pwd|secret|token|key|auth|cookie|credential|session|sign` 等模式全量扫描，**命中数为 0**。因此本文件**无需脱敏**。

### 7.1 Open API 相关

| 键 | 值 | 含义 |
|---|---|---|
| `openAPI.enable` | `true` | **Open API 已启用** |
| `openAPI.port` | `"23330"` | 监听端口（字符串） |
| `openAPI.bindLan` | `false` | 仅绑定本机，未开放局域网 |

### 7.2 音源 / API 源相关

| 键 | 值 | 含义 |
|---|---|---|
| `common.apiSource` | `"user_api_969_1789019033898"` | **当前启用的音源 id** |
| `common.sourceNameType` | `"real"` | 显示真实平台名 |
| `list.isShowSource` | `true` | 列表显示来源 |
| `download.isUseOtherSource` | `false` | 下载时不使用其它源 |

**`customSource` 与 `apiSource` 这两个键名在本文件中不存在。** 实际的音源选择键是 `common.apiSource`，其值指向 `user_api.json` 中的某个条目 id。

**验证**：`user_api_969_1789019033898` 确实存在于 `user_api.json` 的 8 个条目中 → 对应条目为 **「独家音源」 version 6, author "w"**。

### 7.3 与"哪些源被启用"相关的设置

本配置中**没有**逐平台（kg/kw/wy/tx/mg）的启用开关。启用的平台集合由**所选音源脚本自身**（`user_api.json` 内对应条目的 `script`）决定。

其它相关设置：

| 键 | 值 |
|---|---|
| `player.playQuality` | `"320k"` |
| `download.enable` | `true` |
| `download.savePath` | `C:\Users\EDY\Music` |
| `download.fileName` | `歌名 - 歌手` |
| `download.maxDownloadNum` | `3` |
| `download.isSavePathGroupByListName` | `true` |
| `network.proxy.enable` | `false` |
| `sync.enable` | `true` |
| `sync.mode` | `"client"` |
| `sync.client.host` | `https://oh10867346ne.vicp.fun` |
| `sync.server.port` | `"23332"` |

> `sync.client.host` 是用户自建的同步服务器地址（vicp.fun 内网穿透域名）。它本身**不是密钥**（真正的凭证在 `sync/client/syncAuthKey.json`），但属于敏感基础设施信息。

播放器其它关键设置：`player.togglePlayMethod="listLoop"`、`player.volume=0.24`、`player.isSavePlayTime=true`、`desktopLyric.enable=true`、`theme.id="black"`、`common.langId="zh-cn"`。

---

## 8. `user_api.json`（导入的音源脚本）

文件 116,597 字节（磁盘 116,772）。

### 8.1 顶层结构

```json
{
  "userApis": [ /* 8 个条目 */ ]
}
```

**顶层只有 1 个键 `userApis`，是长度为 8 的数组。**

### 8.2 条目字段（8 个条目字段完全一致）

每个条目恰好含 **8 个键**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | str | 形如 `user_api_<数字>_<13位时间戳>` |
| `name` | str | 音源名称 |
| `description` | str | 描述（可为空串） |
| `version` | str | 版本（格式不统一） |
| `author` | str | 作者（可为空串） |
| `homepage` | str | 主页（**全部 8 个均为空串 `""`**） |
| `allowShowUpdateAlert` | bool | **全部 8 个均为 `true`** |
| `script` | str | **压缩后的脚本正文** |

`id` 格式：`user_api_` + 3~4 位数字 + `_` + **13 位 Unix epoch 毫秒**。例如 `user_api_969_1789019033898` → 时间戳 ≈ 2026-09-08。

### 8.3 脚本正文编码方式 —— **已确证**

**编码为 `"gz_" + base64(zlib.compress(源码UTF-8))`。**

严格验证（测试全部 8 个条目，均通过）：`script[3:]` → `base64.b64decode` → `zlib.decompress` → UTF-8 解码，**8/8 全部成功**。压缩率约 0.44~0.92。

```python
raw = json.load(open("user_api.json", encoding="utf-8"))["userApis"]
src = zlib.decompress(base64.b64decode(entry["script"][3:])).decode("utf-8")
```

> **`gz_` 前缀本身具有误导性**——它**不是 gzip**（gzip 有 `\x1f\x8b` 魔数），而是裸 **zlib** 流。若误用 `gzip.decompress` 会失败。正确做法是 `zlib.decompress`。

### 8.4 各条目元数据与体积（**不转储正文**）

| # | id | name | version | author | description | script(raw) | zlib | 明文 |
|---:|---|---|---|---|---|---:|---:|---:|
| 0 | `user_api_927_1784270441030` | `[独家音源]` | `4` | 洛雪科技 | 音源更新，关注微信公众号：洛雪科技 | 50,775 | 38,078 | 105,158 |
| 1 | `user_api_470_1784270459209` | `聚合API接口 (by lerd)` | `v2.0.0` | lerd | 理论可听全平台无损 | 8,479 | 6,357 | 18,388 |
| 2 | `user_api_702_1784270472634` | `野花🌷` | `1.0.0` | *(空)* | *(空)* | 3,699 | 2,771 | 7,445 |
| 3 | `user_api_941_1784270475853` | `Free listen` | `v1.1.2` | *(空)* | A lx-music source | 8,827 | 6,618 | 18,410 |
| 4 | `user_api_942_1784771052702` | `聚合API接口 (CF)` | `3` | lerd | v3 | 895 | 667 | 972 |
| 5 | `user_api_759_1784771163172` | `ikun音源` | `v22` | ikunshare | *(空)* | 2,147 | 1,608 | 4,897 |
| 6 | `user_api_259_1784771206121` | `Huibq_lxmusic源` | `v1.2.0` | Huibq | Github搜索"洛雪音乐音源"，禁止批量下载！ | 1,559 | 1,165 | 2,689 |
| 7 | `user_api_969_1789019033898` | `独家音源` | `6` | w | 后续更新，请关注微信公众号: 洛雪科技 | 38,475 | 28,852 | 57,608 |

> **#7 是当前启用项**（`config_v2.json` 的 `common.apiSource`）。

### 8.5 各脚本的散文头部（`@name` 等注释）

每个脚本文本以 JSDoc 风格注释开头，与实际元数据一致：

```
/*! @name [独家音源] @description 音源更新… @version 4 @author 洛雪科技
    @repository https://github.com/lxmusics/lx-music-api-server */

/*! @name 聚合API接口 (by lerd) @description 理论可听全平台无损 @version v2.0.0 @author lerd */
/*! @name 野花🌷 @version 1.0.0 */
/*! @name Free listen @description A lx-music source @version v1.1.2 @wy_token null … */
/*! @name 聚合API接口 (CF) @description v3 @version 3 @author lerd */
/*! @name ikun音源 @version v22 @author ikunshare */
/*! @name Huibq_lxmusic源 @version v1.2.0 @author Huibq */
/*! @name 独家音源 @version 6 @author w */
```

**代码混淆情况**：`聚合API接口 (by lerd)` 使用 **jsjiami.com.v7** 混淆（`var _0xod2 = 'jsjiami.com.v7'`）；`野花🌷` 使用十六进制转义字符串数组；`独家音源` 使用 Unicode 标识符混淆。`Free listen` 是 webpack 打包产物。

### 8.6 各脚本引用的外部主机

| 主机 | 出现于 |
|---|---|
| `api.music.lerd.dpdns.org` | 聚合API接口 (CF) |
| `api.ikunshare.com` | ikun音源 |
| `lxmusicapi.onrender.com` | Huibq_lxmusic源 |
| `www.hhlqilongzhu.cn` | 聚合API接口 (by lerd) |
| `interface3.music.163.com` / `www.kuwo.cn` / `m.kuwo.cn` / `wwwapi.kugou.com` / `u.y.qq.com` / `music.migu.cn` / `app.c.nf.migu.cn` | Free listen（各平台直连） |
| `github.com` / `raw.githubusercontent.com` / `cdn.jsdelivr.net` / `fastly.jsdelivr.net` / `gcore.jsdelivr.net` | Free listen、[独家音源]（更新检查） |

### ⚠️ 8.7 安全隐患：明文凭证

对**解压后**的脚本文本扫描（`Key|Token|Secret|Salt|Pwd|Password|Sign|Fingerprint|Auth` 赋值模式），发现：

| 条目 | 命中（**值已脱敏**） |
|---|---|
| **独家音源**（#7，**当前启用**） | `SERVER_SCRIPT_CONFIG` = `{"apiUrl":"<redacted>","apiKey":"<redacted, len=7>","signSalt":"<redacted, len=14>","fingerprint":"<redacted, len=32>"}` |
| **Free listen**（#3） | `defaultKey` (len=40)、`eapiKey` (len=16) |
| ikun音源（#5） | `API_KEY = ""`（空串，无泄露） |
| Huibq_lxmusic源（#6） | `API_KEY = 'share-v3'`（公共共享值，非私密） |

`独家音源` 的凭证以**明文**嵌在解压后的脚本里：

```javascript
// ===== 服务端下发配置(自动生成, 请勿修改) =====
globalThis['SERVER_SCRIPT_CONFIG'] = {"apiUrl":"https://88.lxmusic.xn--fiqs8s",
  "apiKey":"<redacted>","signSalt":"<redacted>","fingerprint":"<redacted>"};
```

> **该 apiUrl 使用了 Punycode 域名 `xn--fiqs8s`**（解码为 `.中国`）。
> **`Free listen` 的 `eapiKey` / `defaultKey` 是网易云与 QQ 音乐客户端的公共 API 常量**，属于公开已知值，非用户私密凭证。

**结论**：`user_api.json` 内含**真实可用的第三方音源签名密钥**（`apiKey` + `signSalt`）。CLI 若输出/导出这些条目，**必须默认脱敏 `script` 字段**。

---

## 9. `data.json`

文件 1,395 字节，顶层 **10 个键**。

### 9.1 完整内容

```json
{
  "viewPrevState": {
    "url": "/list",
    "query": { "id": "userlist_1785515376162" }
  },
  "lastStartInfo": "2.12.6",
  "listPrevSelectId": "userlist_1785515376162",
  "listScrollPosition": {
    "love": 0,
    "kg_f44418f4d08f408ddb8e6ee2d640653f": 0,
    "kg_58b9d6ef430ab4a71569ed736614396a": 0,
    "kg_831907691ba3a3b2d8986ed8d2b61c24": 1852,
    "userlist_1784778004746": 2750,
    "userlist_1784782928613": 0,
    "tx_01f8d8ef9ba89ef43cb1c28c289d2a9f": 3400,
    "userlist_1785515376162": 0,
    "wy_dd90c06f221d7bb7976c85c193004298": 0,
    "kg_dd55b49370e11e913853796b37c3bfcb": 1714,
    "default": 0
  },
  "listUpdateInfo": {
    "kg_831907691ba3a3b2d8986ed8d2b61c24": {
      "updateTime": 1785290522559,
      "isAutoUpdate": false
    }
  },
  "playInfo": {
    "time": 4.101333,
    "maxTime": 207.672521,
    "listId": "userlist_1785515376162",
    "index": 118
  },
  "songListSetting": { "source": "wy", "sortId": "hot", "tagId": "" },
  "searchSetting": { "temp_source": "kw", "source": "kg", "type": "music" },
  "searchHistoryList": [
    "Whistle Stop", "Vows of the Sea", "相变临界OST",
    "破缺对称 塞壬唱片-MSR;DAVID MURILLO;Bleeding Fingers",
    "audio 包子音乐社", "Amnesia", "HOYO-", "HOYO-MiX",
    "轻涟", "清涟", "纳塔", "明日方舟 酸橙色信笺", "明日方舟", "塞壬唱片"
  ],
  "leaderboardSetting": { "source": "kw", "boardId": "kw__16" }
}
```

### 9.2 逐键说明

| 键 | 类型 | 内容与 CLI 相关性 |
|---|---|---|
| `viewPrevState` | dict | 上次路由 `{url:"/list", query:{id:...}}` —— 用于恢复 UI 位置 |
| `lastStartInfo` | str | `"2.12.6"` —— **应用版本号**（注意与 DB schema 版本 `2`、config 版本 `2.1.0` 均不同） |
| `listPrevSelectId` | str | 上次选中的歌单 id = `userlist_1785515376162` |
| `listScrollPosition` | dict | **每个歌单的滚动位置**（像素）。含虚拟列表 `love`、`default` |
| `listUpdateInfo` | dict | 自动更新元数据：`{updateTime: <epoch ms>, isAutoUpdate: bool}`，仅 1 个歌单有记录 |
| `playInfo` | dict | 上次播放进度：`time`/`maxTime`（秒，float）、`listId`、`index`（歌单内下标） |
| `songListSetting` | dict | 歌单页筛选：`source`/`sortId`/`tagId` |
| `searchSetting` | dict | 搜索源选择：`source="kg"`、`temp_source="kw"`、`type="music"` |
| `searchHistoryList` | list[str] | **14 条搜索历史**（最新在前） |
| `leaderboardSetting` | dict | 排行榜选择：`source="kw"`、`boardId="kw__16"` |

### 9.3 与歌单 UI 状态相关的要点

- **`listScrollPosition` 包含虚拟列表 `love` 和 `default`**（与 §3 结论一致：它们参与 UI 但没有 `my_list` 行）。
- **`listUpdateInfo` 的 `updateTime` 是 epoch 毫秒**（`1785290522559` ≈ 2026-08-29），与 `my_list.locationUpdateTime`（唯一非空值为 `1786517368997` ≈ 2026-08-12）**单位一致，但存储在两个不同文件中**。CLI 若需"歌单最后更新时间"，需同时考虑这两处。
- **`playInfo.index = 118`** 是 `userlist_1785515376162`（219 首）内的**下标**，与 `my_list_music_info_order.order` 语义对应。
- `searchSetting.source`（`kg`）与 `songListSetting.source`（`wy`）、`leaderboardSetting.source`（`kw`）是**三个互相独立的源选择**。

### 9.4 附带：`hot_key.json`（非任务要求，但同目录）

顶层 `{"global": {...}, "local": {...}}`，各含 `enable` 与 `keys`。

- `local.enable = true`，绑定 6 个快捷键：`f1`（聚焦搜索）、`space`（播放/暂停）、`arrowup`（上一首）、`arrowdown`（下一首）、`arrowleft`（后退）、`arrowright`（快进）。
- `global.enable = **false**`，但仍存有 8 个 `mod+alt+*` 绑定（上一首/音量/桌面歌词等）。

每个绑定为 `{type: "win_main"|"win_lyric", name: <i18n key>, action: <action id>}`。

### 9.5 附带：`sync/` 目录（**含凭证，需注意**）

```
sync/client/syncAuthKey.json   3,416 bytes
sync/server/serverInfo.json       51 bytes
```

**`sync/server/serverInfo.json`**：`{"serverId":"MQKy2BHiqMBDPyKttjH2/g==","version":2}`

**`sync/client/syncAuthKey.json`**：顶层是一个 **以 base64 `serverId` 为键**的字典，共 **21 个键**（11 个 `serverId` + 10 个带 `_b` 后缀的"备份/备用"条目）。每个值结构固定：

```json
{
  "<serverId(base64)>": {
    "clientId": "<base64 16字节>",
    "key":      "<base64 16字节，长度24字符>",   ← 【敏感，已脱敏】
    "serverName": "<字符串>"                      ← 【敏感，已脱敏】
  }
}
```

> **`key` 字段是同步服务的认证密钥**（base64，24 字符）。CLI 读取该文件时**必须脱敏**。
> `_b` 后缀条目暗示应用为每个服务端保存了一份备用凭证。
> 本报告**未输出任何 `key` 或 `serverName` 的实际值**。

---

## 10. 其它表

### 10.1 `lyric`（4,265 行）

- **`source` 列只有一个取值**：`'raw'`（4,265 行全部）。
- `type` 分布：`tlyric` 1,139、`lyric` 1,139、`lxlyric` 1,139、`rlyric` 848。
- **`text` 是 base64 编码的歌词文本**（非明文）。已验证：`base64.b64decode` 后得到标准 LRC：

```
[ti:Jealousy]
[ar:韩国群星 (Korea Various Artists)]
[al:DJMax Portable Black Square O.S.T (DJ MAX黑色广场)]
[by:]
[offset:0]
[00:00.0]Jealousy - 韩国群星 (Korea Various Artists)
[00:07.813]'Cause of my jealousy
```

- `lxlyric` 类型同样是 base64，但解出的是 LX 增强格式（`[00:00.0]<0,488>J…`），**不是合法 JSON**。
- **1,139 个 distinct 歌词 id**（`lyric` 表 892 个 distinct id —— 注：此处 `SELECT COUNT(DISTINCT id)` 得 892）。
- **`lyric` 与歌单的关联是"弱"的**：4,265 行中只有 **3,629 行**的 `id` 能在 `my_list_music_info` 中找到对应歌曲；**636 行对应不上**（歌曲已被移出所有歌单，但歌词缓存仍在）。

  失配样例：

```
1050825368_BD73A95A1AD3EF0D1680E28043A74DC5
234695276_69A2F50A9E8FDD5701D9044BE1050A93
tx_001mg3qI05CEqK
tx_001qhJnb1n5p0r
tx_003ZCVHK0CnQrF
```

  > 这些 id 同时出现在 `music_url` 的失配清单中 —— **说明它们曾经在歌单里，后被删除**，但缓存表未清理。

### 10.2 `music_url`（899 行）

`id` 格式 = **`<歌曲id>` + `_` + `<音质>`**：

| 后缀 | 行数 |
|---|---:|
| `_320k` | 423 |
| `_flac` | 389 |
| `_flac24bit` | 64 |
| `_128k` | 23 |

**验证**：899 行中 **768 行**去掉最后一个 `_后缀` 后能匹配到 `my_list_music_info.id`；**131 行匹配不上**（对应已删除的歌曲）。

其中 4 个"匹配不上"的样例揭示了**决定性证据**：

```
kw_451849892_320k
tx_001mg3qI05CEqK_320k
1050825368_BD73A95A1AD3EF0D1680E28043A74DC5_320k
234695276_69A2F50A9E8FDD5701D9044BE1050A93_flac24bit
```

**这些 id 的 `<歌曲id>` 部分（`kw_451849892`、`tx_001mg3qI05CEqK` 等）在 `my_list_music_info` 中确实不存在** → 属于**已被删除歌曲的残留 URL 缓存**，而非格式问题。

`music_url` 中的 id **同样使用 §4.2 所述的裸 kg 形式**（`159190436_D5E7C33B…_flac`），且 `kg_` 前缀 id 仅 29 个，而 `kw_` 297、`tx_` 115、`wy_` 10。

URL 主机分布（**第三方 CDN 直链**）：

| 主机 | 行数 |
|---|---:|
| `fsdg360.hw.kugou.com` | 289 |
| `fsdg360.tx.kugou.com` | 169 |
| `kw-er.kuwo.cn` | 144 |
| `ws.stream.qqmusic.qq.com` | 108 |
| `kw-lv.kuwo.cn` | 72 |
| `car-er.kuwo.cn` | 36 |
| `kw-lw.kuwo.cn` | 31 |
| `car-lv.kuwo.cn` | 17 |
| `fsandroid.kugou.com` | 16 |

> URL 含**时效性签名**（如 `/202607171441/<hash>/v3/<hash>/…`），会过期。CLI 不应把 `music_url` 当作长期有效数据。

### 10.3 `download_list`（473 行）

| isComplate | status | 行数 |
|---:|---|---:|
| 1 | `completed` | 472 |
| 0 | `error` | **1** |

`quality` / `ext` 组合：`flac/flac` 367、`flac24bit/flac` 64、`320k/mp3` 29、`128k/mp3` 13。

**`id` 格式 = `<歌曲id>` + `_` + `<音质>` + `_` + `<扩展名>`**（比 `music_url` 多一层）：

| 尾部两段 | 行数 |
|---|---:|
| `flac_flac` | 367 |
| `flac24bit_flac` | 64 |
| `320k_mp3` | 29 |
| `128k_mp3` | 13 |

去掉最后 2 段后，**469/473 行**能匹配到歌单歌曲 id；**4 行不能**：

```
1050825368_BD73A95A1AD3EF0D1680E28043A74DC5_320k_mp3
234695276_69A2F50A9E8FDD5701D9044BE1050A93_flac24bit_flac
kw_385376527_128k_mp3
wy_2151215639_flac_flac
```

**`musicInfo` 列是嵌套 JSON 对象**（注意：与 `my_list_music_info.meta` 不同，这里是**对象**而非字符串），且 `id` 字段**不含音质/扩展名后缀**：

```json
{
  "id": "271243244_DB3C28F05805A3800DA5E4931A0E549E",
  "name": "夏の肖像",
  "singer": "ヨルシカ",
  "source": "kg",
  "interval": "05:25",
  "meta": { "songId": "271243244", "albumName": "幻燈", "qualitys": [...] }
}
```

其余列（同上行）：`statusText: "下载完成"`、`progress_downloaded: 120842738`、`progress_total: 120842738`、`quality: "flac24bit"`、`ext: "flac"`、`fileName: "夏の肖像 - ヨルシカ.flac"`、`filePath: "C:\\Users\\EDY\\Music\\ヨルシカ（yorushika）\\夏の肖像 - ヨルシカ.flac"`、`position: 14`。

> `fileName` 的命名符合 `config_v2.json` 的 `download.fileName = "歌名 - 歌手"`。

### 10.4 `dislike_list`（仅 2 行）

| rowid | type | content | meta |
|---:|---|---|---|
| 1 | `music` | `シンデレラ (giga first night remix) (cinderella)@deco*27、ギガp` | `NULL` |
| 2 | `music` | `scarborough fair@山田タマル` | `NULL` |

**`content` 格式 = `歌名@歌手`，用 ASCII `@` 分隔。** 注意第 1 行的歌手部分本身含 `、`（`deco*27、ギガp`）—— 与 §4.3 一致。

> 这是**与 `id` 无关的模糊匹配**式黑名单（只有名字+歌手，无 source/id），CLI 处理时需按 `@` 分割并保留多歌手结构。

### 10.5 `music_info_other_source`（**0 行**）

表结构与 2 个索引均存在，但**本数据集中没有任何数据**。

> 该表用于"歌曲换源"（为某首歌缓存其它平台的匹配结果）。为空说明用户从未使用过换源功能，或该缓存被清空过。**CLI 不能依赖此表存在数据。**

---

## 11. CLI 实现要点汇总

### 11.1 必须处理的 `id` 格式规则

1. **`id` 前缀不可作为 `source` 的可靠判据**（仅 20% 的行符合 `<source>_` 形式）。
2. 按 source 分派解析：
   - `kw`/`wy`/`mg` → `^(kw|wy|mg)_(\d+)$`
   - `tx` → `^tx_([0-9A-Za-z]{12})$`（MID）
   - `kg` → **两种形式**：`^kg_(\d+)_([0-9A-F]{32})$`（24 行）或 `^(\d+)_([0-9A-F]{32})$`（934 行）
   - `local` → **就是文件路径**，不要做任何切分；**且路径中可能含 `_`**
3. `music_url.id` = `<歌曲id>_<音质>`；`download_list.id` = `<歌曲id>_<音质>_<扩展名>`。**剥离后缀的段数是固定的（1 段 / 2 段），但 `local` 歌曲出现在这些表中时同样会带后缀**，需先用 `rsplit` 再校验。
4. 判断"这首歌属于哪个平台"**永远用 `source` 列**，不要从 `id` 推断。

### 11.2 必须处理的 `meta` 结构

- 全部可 JSON 解析，但**键集合与值类型因 source 而异**（6 种键集）。
- `local` 的 meta **没有** `qualitys`/`_qualitys`/`songId`(数字)，只有 `albumName/filePath/songId/picUrl/ext`。
- `songId` 与 `albumId` 可能是 **int 或 str**；`picUrl` 可能是 **`null`**。
- `qualitys[].hash` **可能整个键都不存在**（kw/wy/tx 部分行）。
- `qualitys[].size` 可能是**空串**（mg/tx 部分行）。
- `_qualitys` 的大小写与 `qualitys` 不一致（`Mb` vs `MB`），**以 `qualitys` 数组为准**。

### 11.3 数据质量问题清单

| # | 问题 | 量化 | CLI 应对 |
|---|---|---:|---|
| 1 | `kg` id 缺前缀 | **934 行** | 前缀失败时回退裸形式 |
| 2 | `local` id 是文件路径（含 `_`、Win/Android 混用） | **565 行** | 特判，禁止切分 |
| 3 | `order` 稀疏（缺 226/227） | 1 个歌单（`tx_01f8…`） | 按序读取，勿当下标 |
| 4 | 跨歌单同 id 重复 | 192 个 id | 删除必须带 `listId` |
| 5 | 跨 source 同曲（同名同歌手） | **256 组** | 勿用 `(name,singer)` 去重 |
| 6 | 同 source 同名歌手多 id | 11 组 | 用完整 `id` 去重才安全 |
| 7 | `interval` 分钟位 1~3 位 | 67 行非 `MM:SS` | 宽松正则 `^\d+:\d{2}$` |
| 8 | `lyric`/`music_url` 残留已删歌曲 | 636 / 131 行 | 关联时允许失配 |
| 9 | 虚拟歌单无 `my_list` 行 | `default` 164、`love` 188 | 特判硬编码 |
| 10 | `sourceListId` 双格式（`id_` 前缀可选） | kg 内 5 vs 3 | 勿归一化写回 |
| 11 | `download_list` 列名拼写错误 `isComplate` | 表级 | 原样沿用 |
| 12 | `music_info_other_source` 空表 | 0 行 | 勿假设有数据 |
| 13 | 音源脚本内含明文签名密钥 | 2/8 条目 | 导出时默认脱敏 |
| 14 | `sync/client/syncAuthKey.json` 含同步密钥 | 21 键 | 读取时脱敏 |

### 11.4 安全与只读建议

- **数据库仍需以 `mode=ro` 打开**；写操作应通过应用自身或严格事务进行。
- 输出层必须对以下内容脱敏：`user_api.json` 的 `script`（尤其 #3、#7）、`syncAuthKey.json` 的 `key`/`serverName`、`config_v2.json` 的 `sync.client.host`。
- 本报告**未输出任何实际密钥值**，全部以 `<redacted>` 或长度替代。

---

## 12. 不确定项声明

以下内容为**推断**，非直接观测，已在正文中以 **〔推断〕** 标注：

1. `kg` id 存在两种形式（裸 / 带前缀）的**原因**。观测到的事实是：24 个带前缀 id 100% 落在 `tx` 歌单内、且该歌单是唯一混合两种形式的歌单。**真实成因（换源 / 版本差异 / 导入路径不同）无法从数据库中判定。**
2. `tx` 歌单 `order` 缺 226/227 的**成因**（推定为删除歌曲未重排）。
3. `music_url` 与 `lyric` 中 131 / 636 行失配，**推定为歌曲被移出歌单后的残留缓存**（依据：这些 id 在 `music_url`、`lyric`、`download_list` 中一致地缺失于歌单表，符合"曾经存在后被删除"的特征）。
4. `_b` 后缀同步凭证条目为"备用凭证"（从命名与结构推断）。
5. 各音源脚本支持的平台集合：因正文被混淆/压缩，**未能从脚本中静态提取完整的平台声明**；仅 `Free listen`（酷我/酷狗/企鹅/咪咕）和 `ikun音源`（含 `kw`/`wy`/`git` 字样）有可辨识的声明。其余音源的实际可用平台需运行时验证。

---

*报告结束。所有查询脚本位于 `C:\Users\EDY\Documents\workspace\LX-CLI-project\_scratch\`（`s01`~`s18`），可复现本报告中的每一项数据。*
