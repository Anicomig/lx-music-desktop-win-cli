# 01 · 洛雪音乐助手 桌面端（v2.12.5）歌曲/歌单数据结构 与 音源选择、搜索逻辑

> 调研对象：`C:\Users\EDY\Documents\workspace\lx-music-desktop-2.12.5`（Vue 3 + Electron，洛雪音乐助手 v2.12.5）
> 目的：为编写「控制本 App 的 CLI」提供**必须复刻或必须互操作**的数据契约与算法契约。
> 所有结论均基于实际源码，标注 `文件:行号`。凡无法从源码证实的，明确标注 **未验证/推测**。

---

## 目录

1. [核心结论速览（CLI 必读）](#0-核心结论速览cli-必读)
2. [MusicInfo / 歌曲对象结构](#1-musicinfo--歌曲对象结构)
3. [歌单 / 列表结构](#2-歌单--列表结构)
4. [source 标识符与音源注册表](#3-source-标识符与音源注册表)
5. [搜索逻辑](#4-搜索逻辑)
6. [搜索结果展示所需字段](#5-搜索结果展示所需字段)
7. [附录：数据库 Schema 与 JSON 导入导出格式](#6-附录)

---

## 0. 核心结论速览（CLI 必读）

| 主题 | 结论 |
|---|---|
| **歌曲 id 规范** | `id = source + '_' + songmid`，但 **kg 例外**：`id = songmid + '_' + hash`（顺序相反，无 source 前缀） |
| **在线 source 全集** | `'kw' \| 'kg' \| 'tx' \| 'wy' \| 'mg'`（类型定义）+ `'local'`。**`bd` 和 `xm` 存在但被排除在注册表外** |
| **列表中实际可用的 source** | 仅 5 个在线源 + local；`bd`/`xm` 的 `musicSearch` 不会被聚合搜索调用 |
| **`meta` 是唯一逃逸口** | 所有源特有字段（hash / strMediaMid / copyrightId / qualitys）**全部塞进 `meta`**，DB 里以 **JSON 字符串** 单列存储 |
| **`singer` 分隔符** | 中文顿号 `、`（U+3001），由 `formatSingerName(singers, nameKey, join='、')` 统一产出 |
| **`interval`** | **格式化字符串** `"mm:ss"`（如 `"03:55"`），不是秒数；零时长为 `"--/--"` |
| **内置虚拟列表** | `default`（试听列表）、`love`（我喜欢）**不是** `userList` 成员，DB 里 **不存在** `my_list` 行，仅存歌曲行 |
| **`.lxmc` 文件** | **gzip 压缩的 JSON**（非明文）；`.json` 后缀则直接读明文 |
| **搜索分页** | 全源聚合时用**同一个 page 号并发请求所有源**，最后按相似度重排并全局去重 |
| **播放取 URL** | 逐源降级：`getPlayQuality()` → 从 `TRY_QUALITYS_LIST` 里挑第一个「歌曲有 + 音源支持」的音质；失败则 `getOtherSource()` 跨源匹配后重试 |

---

## 1. MusicInfo / 歌曲对象结构

### 1.1 权威类型定义

`src/common/types/music.d.ts:1-124`（完整关键部分逐字引用）：

```ts
// src/common/types/music.d.ts:3-18
interface MusicQualityType { // {"type": "128k", size: "3.56M"}
  type: LX.Quality
  size: string | null
}
interface MusicQualityTypeKg { // {"type": "128k", size: "3.56M"}
  type: LX.Quality
  size: string | null
  hash: string
}
type _MusicQualityType = Partial<Record<Quality, {
  size: string | null
}>>
type _MusicQualityTypeKg = Partial<Record<Quality, {
  size: string | null
  hash: string
}>>
```

```ts
// src/common/types/music.d.ts:21-87  —— 核心对象定义（逐字）
interface MusicInfoMetaBase {
  songId: string | number // 歌曲ID，mg源为copyrightId，local为文件路径
  albumName: string // 歌曲专辑名称
  picUrl?: string | null // 歌曲图片链接
  toggleMusicInfo?: MusicInfoOnline | null
}

interface MusicInfoMeta_online extends MusicInfoMetaBase {
  qualitys: MusicQualityType[]
  _qualitys: _MusicQualityType
  albumId?: string | number // 歌曲专辑ID
}

interface MusicInfoMeta_local extends MusicInfoMetaBase {
  filePath: string
  ext: string
}

interface MusicInfoBase<S = LX.Source> {
  id: string
  name: string // 歌曲名
  singer: string // 艺术家名
  source: S // 源
  interval: string | null // 格式化后的歌曲时长，例：03:55
  meta: MusicInfoMetaBase
}

interface MusicInfoLocal extends MusicInfoBase<'local'> {
  meta: MusicInfoMeta_local
}

interface MusicInfo_online_common extends MusicInfoBase<'kw' | 'wy'> {
  meta: MusicInfoMeta_online
}

interface MusicInfoMeta_kg extends MusicInfoMeta_online {
  qualitys: MusicQualityTypeKg[]
  _qualitys: _MusicQualityTypeKg
  hash: string // 歌曲hash
  albumAudioId?: string // 专辑内歌曲ID(MixSongID)，用于歌词精确搜索
}
interface MusicInfo_kg extends MusicInfoBase<'kg'> {
  meta: MusicInfoMeta_kg
}

interface MusicInfoMeta_tx extends MusicInfoMeta_online {
  strMediaMid: string // 歌曲strMediaMid
  id?: number // 歌曲songId
  albumMid?: string // 歌曲albumMid
}
interface MusicInfo_tx extends MusicInfoBase<'tx'> {
  meta: MusicInfoMeta_tx
}

interface MusicInfoMeta_mg extends MusicInfoMeta_online {
  copyrightId: string // 歌曲copyrightId
  lrcUrl?: string // 歌曲lrcUrl
  mrcUrl?: string // 歌曲mrcUrl
  trcUrl?: string // 歌曲trcUrl
}
interface MusicInfo_mg extends MusicInfoBase<'mg'> {
  meta: MusicInfoMeta_mg
}

type MusicInfoOnline = MusicInfo_online_common | MusicInfo_kg | MusicInfo_tx | MusicInfo_mg
type MusicInfo = MusicInfoOnline | MusicInfoLocal
```

### 1.2 顶层字段一览（新格式 / 内存格式）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `string` | **主键**，构成见 §1.3。列表内去重、DB 唯一键、`music_url`/`lyric` 缓存键均用它 |
| `name` | `string` | 歌曲名 |
| `singer` | `string` | 艺术家名，多歌手用 `、` 连接 |
| `source` | `LX.Source` | `'kw' \| 'kg' \| 'tx' \| 'wy' \| 'mg' \| 'local'` |
| `interval` | `string \| null` | 格式化时长 `"mm:ss"` |
| `meta` | `object` | 源特有字段容器（见下） |

**注意：顶层没有 `songmid`、`albumName`、`img`、`types`、`typeUrl` 等字段。** 那是 **旧格式**（见 §1.6），在新格式中它们或进入 `meta`，或已被彻底删除。

### 1.3 `id` 的构成 —— 精确规则（最重要的一节）

唯一的构造函数是 `toNewMusicInfo`，位于 `src/common/utils/tools.ts:3-56`（逐字）：

```ts
// src/common/utils/tools.ts:3-56
export const toNewMusicInfo = (oldMusicInfo: any): LX.Music.MusicInfo => {
  const meta: Record<string, any> = {
    songId: oldMusicInfo.songmid, // 歌曲ID，local为文件路径
    albumName: oldMusicInfo.albumName, // 歌曲专辑名称
    picUrl: oldMusicInfo.img, // 歌曲图片链接
  }
  const newInfo = {
    id: `${oldMusicInfo.source}_${oldMusicInfo.songmid}`,
    name: oldMusicInfo.name,
    singer: oldMusicInfo.singer,
    source: oldMusicInfo.source,
    interval: oldMusicInfo.interval,
    meta: meta as LX.Music.MusicInfoOnline['meta'],
  }

  if (oldMusicInfo.source == 'local') {
    meta.filePath = oldMusicInfo.filePath ?? oldMusicInfo.songmid ?? ''
    meta.ext = oldMusicInfo.ext ?? /\.(\w+)$/.exec(meta.filePath)?.[1] ?? ''
  } else {
    meta.qualitys = oldMusicInfo.types
    meta._qualitys = oldMusicInfo._types
    meta.albumId = oldMusicInfo.albumId
    if (meta._qualitys.flac32bit && !meta._qualitys.flac24bit) {
      meta._qualitys.flac24bit = meta._qualitys.flac32bit
      delete meta._qualitys.flac32bit

      meta.qualitys = (meta.qualitys as any[]).map(quality => {
        if (quality.type == 'flac32bit') quality.type = 'flac24bit'
        return quality
      })
    }

    switch (oldMusicInfo.source) {
      case 'kg':
        meta.hash = oldMusicInfo.hash
        meta.albumAudioId = oldMusicInfo.albumAudioId
        newInfo.id = oldMusicInfo.songmid + '_' + oldMusicInfo.hash
        break
      case 'tx':
        meta.strMediaMid = oldMusicInfo.strMediaMid
        meta.id = oldMusicInfo.songId
        meta.albumMid = oldMusicInfo.albumMid
        break
      case 'mg':
        meta.copyrightId = oldMusicInfo.copyrightId
        meta.lrcUrl = oldMusicInfo.lrcUrl
        meta.mrcUrl = oldMusicInfo.mrcUrl
        meta.trcUrl = oldMusicInfo.trcUrl
        break
    }
  }

  return newInfo
}
```

**结论（`id` 规则表）：**

| source | `id` 形态 | 示例 |
|---|---|---|
| `kw` | `kw_{songmid}` | `kw_62355680` |
| `tx` | `tx_{songmid}` | `tx_0039MnYb0qxYhV`（`songmid` 即 `item.mid`） |
| `wy` | `wy_{songmid}` | `wy_1901371647` |
| `mg` | `mg_{songmid}` | `mg_6009140...`（`songmid` 即 `data.songId`） |
| **`kg`** | **`{songmid}_{hash}`** ⚠️ | `A1B2C3D4_9F8E7D6C5B4A...` |
| `local` | **文件绝对路径** | `C:\Music\a.flac` |

> ⚠️ **CLI 关键陷阱 1**：`kg` 的 id **不是** `kg_xxx`，而是 `songmid + '_' + hash`，且 `source` 字段仍是 `'kg'`。任何「用 `id.split('_')[0]` 反推 source」的写法都会 kg 上出错。**source 必须读 `musicInfo.source` 字段**。

> ⚠️ **CLI 关键陷阱 2**：`kg` 的 `hash` 来自搜索结果顶层的 `rawData.FileHash`（`src/renderer/utils/musicSdk/kg/musicSearch.js:63`），即**128k 版本的 hash**；而每个具体音质的 hash 存在 `types[].hash` / `_qualitys[q].hash` 里（`kg/musicSearch.js:20-48`）。改动 `types` 顺序不会影响 id，但**改 hash 会改 id**。

`local` 的 `id` 在 `src/renderer/utils/music.ts:82-95` 被直接赋为文件路径：

```ts
// src/renderer/utils/music.ts:82-95
  return {
    id: path,
    name,
    singer,
    source: 'local',
    interval,
    meta: {
      albumName,
      filePath: path,
      songId: path,
      picUrl: '',
      ext: ext.replace(/^\./, ''),
    },
  }
```

另有 deeplink 场景下构造的伪 id：`id: \`sp_${name}_s${singer}_a${albumName}_i${interval ?? ''}\``，`source: 'local'`（`src/renderer/core/useApp/useDeeplink/useMusicAction.js:184`）。这是「按名字搜索播放」的临时对象，**未验证**其是否会落库。

### 1.4 `meta` 的精确内容

**`meta` 字段是逐源的、动态拼装的**（`tools.ts:3-53`），不是固定 schema。汇总：

#### 所有源共有
```ts
songId: string | number   // kw/kg/tx/wy -> songmid ; mg -> copyrightId ; local -> 文件路径
albumName: string         // 专辑名（可能是 ''）
picUrl?: string | null    // 封面 URL；来自旧格式的 img；可能为 null
toggleMusicInfo?: MusicInfoOnline | null  // 「换源」后指向另一个源的等价歌曲
```

#### 仅在线源（`MusicInfoMeta_online`）
```ts
qualitys: MusicQualityType[]          // 数组形式，有顺序，用于 UI 展示「无损/24bit」角标
_qualitys: _MusicQualityType          // 字典形式 { '320k': { size }, flac: { size, hash? } }
albumId?: string | number             // 专辑 ID
```

#### 各源追加字段
| source | `meta` 追加字段 |
|---|---|
| `kg` | `hash: string`（**必填**）、`albumAudioId?: string`、`_qualitys[q].hash`（**每个音质各自的 hash**） |
| `tx` | `strMediaMid: string`、`id?: number`（歌曲 songId，与 `songId` 重名但语义不同）、`albumMid?: string` |
| `mg` | `copyrightId: string`、`lrcUrl?`、`mrcUrl?`、`trcUrl?` |
| `local` | `filePath: string`、`ext: string`（无 `qualitys`/`_qualitys`/`albumId`） |
| `kw`/`wy` | 无追加 |

> ⚠️ **CLI 关键陷阱 3**：`meta` 中同时存在 `songId` 与（tx 的）`id`。`toOldMusicInfo`（`tools.ts:88`）把 `meta.id` 还原成旧格式的 `songId` 字段。

### 1.5 `qualitys` / `_qualitys` 与 `LX.Quality`

音质枚举 `src/common/types/common.d.ts:50`：

```ts
type Quality = '128k' | '320k' | 'flac' | 'flac24bit' | '192k' | 'ape' | 'wav'
```

优先级顺序常量 `src/common/constants.ts:82`：

```ts
export const QUALITYS = ['flac24bit', 'flac', 'wav', 'ape', '320k', '192k', '128k'] as const
```

**`_qualitys` 是判定「这首歌能不能放某音质」的唯一依据**（见 §4.3）。各源搜索结果生成 `types`/`_types` 的代码位置：

| source | 文件:行 | 音质来源字段 |
|---|---|---|
| `kw` | `kw/musicSearch.js:41-97` | `N_MINFO` 正则解析：`4000→flac24bit`、`2000→flac`、`320→320k`、`128→128k` |
| `kg` | `kg/musicSearch.js:15-68` | `FileSize/HQFileSize/SQFileSize/ResFileSize` + 对应 `*FileHash` |
| `tx` | `tx/musicSearch.js:69-99` | `file.size_128mp3 / size_320mp3 / size_flac / size_hires` |
| `wy` | `wy/musicSearch.js:43-91` | `privilege.maxBrLevel=='hires'` + `privilege.maxbr` 分级 |
| `mg` | `mg/musicSearch.js:137-171` | `audioFormats[].formatType`: `PQ/HQ/SQ/ZQ24` |
| `bd` | `bd/musicSearch.js:24-46` | `all_rate` 逗号分隔（`128/320/flac`），**size 恒为 null** |

`kg` 的 `_types` 形态（`kg/musicSearch.js:20-25`）：
```js
types.push({ type: '128k', size, hash: rawData.FileHash })
_types['128k'] = { size, hash: rawData.FileHash }
```

**旧版 `flac32bit` → 新版 `flac24bit` 的迁移**在 `toNewMusicInfo`（`tools.ts:25-33`）与 `fixNewMusicInfoQuality`（`tools.ts:106-124`）两处。

### 1.6 旧格式（OldMusicInfo）—— CLI 若解析 `.lxmc` 旧文件需要

`toOldMusicInfo`（`src/common/utils/tools.ts:58-100`）给出旧格式全貌：

```ts
// src/common/utils/tools.ts:58-100
export const toOldMusicInfo = (minfo: LX.Music.MusicInfo) => {
  const oInfo: Record<string, any> = {
    name: minfo.name,
    singer: minfo.singer,
    source: minfo.source,
    songmid: minfo.meta.songId,
    interval: minfo.interval,
    albumName: minfo.meta.albumName,
    img: minfo.meta.picUrl ?? '',
    typeUrl: {},
  }
  if (minfo.source == 'local') {
    oInfo.filePath = minfo.meta.filePath
    oInfo.ext = minfo.meta.ext
    oInfo.albumId = ''
    oInfo.types = []
    oInfo._types = {}
  } else {
    oInfo.albumId = minfo.meta.albumId
    oInfo.types = minfo.meta.qualitys
    oInfo._types = minfo.meta._qualitys

    switch (minfo.source) {
      case 'kg':
        oInfo.hash = minfo.meta.hash
        oInfo.albumAudioId = minfo.meta.albumAudioId
        break
      case 'tx':
        oInfo.strMediaMid = minfo.meta.strMediaMid
        oInfo.albumMid = minfo.meta.albumMid
        oInfo.songId = minfo.meta.id
        break
      case 'mg':
        oInfo.copyrightId = minfo.meta.copyrightId
        oInfo.lrcUrl = minfo.meta.lrcUrl
        oInfo.mrcUrl = minfo.meta.mrcUrl
        oInfo.trcUrl = minfo.meta.trcUrl
        break
    }
  }

  return oInfo
}
```

**旧格式顶层字段全集**：`name, singer, source, songmid, interval, albumName, img, typeUrl, albumId, types, _types`，加上 `/kg→hash, albumAudioId`、`/tx→strMediaMid, albumMid, songId`、`/mg→copyrightId, lrcUrl, mrcUrl, trcUrl`、`/local→filePath, ext`，以及搜索结果里的 `lrc`、`otherSource`（在 `kw/musicSearch.js:91-93` 等仍在产出，但新格式已丢弃）。

**旧格式没有 `id` 字段** —— 这也是 `toNewMusicInfo` 必须存在的原因：旧数据导入时用 `source + songmid` 现场算出 id。

### 1.7 `singer` 表示

统一由 `formatSingerName` 产出，`src/renderer/utils/musicSdk/utils.js:33-50`：

```js
// src/renderer/utils/musicSdk/utils.js:39-49
export const formatSingerName = (singers, nameKey = 'name', join = '、') => {
  if (Array.isArray(singers)) {
    const singer = []
    singers.forEach(item => {
      let name = item[nameKey]
      if (!name) return
      singer.push(name)
    })
    return decodeName(singer.join(join))
  }
  return decodeName(String(singers ?? ''))
}
```

- 分隔符：**`、`（U+3001 中文顿号）**
- `kw` 用自定义 `formatSinger`（`kw/musicSearch.js:82`）
- `wy` 手工 `join('、')`（`wy/musicSearch.js:31-37`）
- `bd` 用 `item.author.replace(',', '、')`（`bd/musicSearch.js:49`）
- `decodeName`（`src/renderer/utils/index.ts:79-82`）做 HTML 实体反转义

`findMusic` 的歌手匹配正则（`musicSdk/index.js:80`）确认了所有可能出现的分隔符：
```js
const singersRxp = /、|&|;|；|\/|,|，|\|/
```
排序时统一 `split` 后 `localeCompare` 排序再用 `、` 连接（`musicSdk/index.js:81-83`）——**这意味着 `singer` 字段在跨源匹配时会被规范化，但存储值不会被改写**。

### 1.8 `interval` 表示

`src/common/utils/common.ts:62-72`：

```ts
export const formatPlayTime = (time: number) => {
  let m = Math.trunc(time / 60)
  let s = Math.trunc(time % 60)
  return m == 0 && s == 0 ? '--/--' : numFix(m) + ':' + numFix(s)
}

export const formatPlayTime2 = (time: number) => {
  let m = Math.trunc(time / 60)
  let s = Math.trunc(time % 60)
  return numFix(m) + ':' + numFix(s)
}
```

- 输入是**秒数**，输出 `"mm:ss"`（`numFix` 补零，`common.ts:42`）
- 时长为 0 或缺省 → 字面量 `"--/--"`（**不是 null**）
- **超过 60 分钟不会进位到小时**：`m` 会大于 59，如 `"75:30"`
- UI 用 `item.interval || '--/--'` 兜底（`OnlineList/index.vue:44`），所以 `null` 和 `'--/--'` 视觉一致
- 类型声明上 `interval: string | null`（`music.d.ts:45`）

**反向解析**（`musicSdk/index.js:100-111`）—— CLI 若要比对时长需复刻：
```js
const getIntv = (interval) => {
  if (!interval) return 0
  let intvArr = interval.split(':')
  let intv = 0
  let unit = 1
  while (intvArr.length) {
    intv += parseInt(intvArr.pop()) * unit
    unit *= 60
  }
  return intv
}
```

---

## 2. 歌单 / 列表结构

### 2.1 权威类型定义

`src/common/types/list.d.ts:1-142`（逐字引用关键部分）：

```ts
// src/common/types/list.d.ts:3-52
interface UserListInfo {
  id: string
  name: string
  // list: LX.Music.MusicInfo[]
  source?: LX.OnlineSource
  sourceListId?: string
  // position?: number
  locationUpdateTime: number | null
}

interface MyDefaultListInfo {
  id: 'default'
  name: 'list__name_default'
  // name: '试听列表'
  // list: LX.Music.MusicInfo[]
}

interface MyLoveListInfo {
  id: 'love'
  name: 'list__name_love'
  // name: '我的收藏'
  // list: LX.Music.MusicInfo[]
}

interface MyTempListInfo {
  id: 'temp'
  name: '临时列表'
  // list: LX.Music.MusicInfo[]
  // TODO: save default lists info
  meta: {
    id?: string
  }
}

type MyListInfo = MyDefaultListInfo | MyLoveListInfo | UserListInfo

interface MyAllList {
  defaultList: MyDefaultListInfo
  loveList: MyLoveListInfo
  userList: UserListInfo[]
  tempList: MyTempListInfo
}
```

```ts
// src/common/types/list.d.ts:123-141
interface MyDefaultListInfoFull extends MyDefaultListInfo {
  list: LX.Music.MusicInfo[]
}
interface MyLoveListInfoFull extends MyLoveListInfo {
  list: LX.Music.MusicInfo[]
}
interface UserListInfoFull extends UserListInfo {
  list: LX.Music.MusicInfo[]
}
interface MyTempListInfoFull extends MyTempListInfo {
  list: LX.Music.MusicInfo[]
}

interface ListDataFull {
  defaultList: LX.Music.MusicInfo[]
  loveList: LX.Music.MusicInfo[]
  userList: UserListInfoFull[]
  tempList: LX.Music.MusicInfo[]
}
```

DB 层类型（含 `position`），`src/main/types/db_service.d.ts:35-42`：

```ts
interface UserListInfo {
  id: string
  name: string
  source?: LX.OnlineSource
  sourceListId?: string
  position: number
  locationUpdateTime: number | null
}
```

> 📌 `position` **只存在于 DB 层与主进程内存**，IPC 传出时被剥离（`src/main/worker/dbService/modules/list/index.ts:43-52` 的 `getAllUserList` 显式 `const { position, ...newList } = list`）。渲染进程的 `userList` **只有数组顺序，没有 position 字段**。

### 2.2 列表元数据 ↔ 歌曲行 ↔ 排序 的关系

**存储层是 3 张表**（`src/main/worker/dbService/tables.ts:128-169`）：

```sql
-- tables.ts:128-138
CREATE TABLE "my_list" (
  "id" TEXT NOT NULL,
  "name" TEXT NOT NULL,
  "source" TEXT,
  "sourceListId" TEXT,
  "position" INTEGER NOT NULL,
  "locationUpdateTime" INTEGER,
  PRIMARY KEY("id")
);

-- tables.ts:139-150
CREATE TABLE "my_list_music_info" (
  "id" TEXT NOT NULL,
  "listId" TEXT NOT NULL,
  "name" TEXT NOT NULL,
  "singer" TEXT NOT NULL,
  "source" TEXT NOT NULL,
  "interval" TEXT,
  "meta" TEXT NOT NULL,
  UNIQUE("id","listId")
);

-- tables.ts:157-163
CREATE TABLE "my_list_music_info_order" (
  "listId" TEXT NOT NULL,
  "musicInfoId" TEXT NOT NULL,
  "order" INTEGER NOT NULL
);
```

**关系要点：**

1. **元数据与歌曲分离**：`my_list` 只存表头，歌曲在 `my_list_music_info`，用 `listId` 外键关联。
2. **排序独立成表**：`order` 不在歌曲表里，而在 `my_list_music_info_order`。查询靠 LEFT JOIN + `ORDER BY O."order" ASC`（`list/statements.ts:63-70`）：
   ```sql
   SELECT mInfo."id", mInfo."name", mInfo."singer", mInfo."source", mInfo."interval", mInfo."meta"
   FROM my_list_music_info mInfo
   LEFT JOIN my_list_music_info_order O
   ON mInfo.id=O.musicInfoId AND O.listId=@listId
   WHERE mInfo.listId=@listId
   ORDER BY O."order" ASC
   ```
3. **`meta` 以 JSON 字符串落库**，读时 `JSON.parse`（`dbService/modules/list/index.ts:28-37` 写入、`:171-188` 读取）：
   ```ts
   // dbService/modules/list/index.ts:28-37
   const toDBMusicInfo = (musicInfos: LX.Music.MusicInfo[], listId: string, offset: number = 0): LX.DBService.MusicInfo[] => {
     return musicInfos.map((info, index) => {
       return {
         ...info,
         listId,
         meta: JSON.stringify(info.meta),
         order: offset + index,
       }
     })
   }
   ```
4. **同一首歌可存在于多个列表**（唯一键是 `("id","listId")` 组合），`getMusicExistListIds`（`dbService/modules/list/index.ts:413-416`）就是查这个。
5. **列表级去重**：同一列表内同一 `id` 只能有一行 —— 渲染层 `listMusicAdd`（`store/list/listManage/action.ts:224-247`）与主进程 `musicsAdd`（`dbService/modules/list/index.ts:210-236`）**各自**做了一次 Set 去重。
6. **`order` 是稀疏递增的整数**，不是数组下标：追加到底部时取「最后一首的 order + 1」（`dbService/modules/list/index.ts:230`），避免全表重排。只有 `musicsPositionUpdate`（`:337-361`）会整体重写为 `0..n-1`。

### 2.3 内置/虚拟列表 `default` (试听列表) 与 `love` (我喜欢)

常量定义 `src/common/constants.ts:26-32`：

```ts
export const LIST_IDS = {
  DEFAULT: 'default',
  LOVE: 'love',
  TEMP: 'temp',
  DOWNLOAD: 'download',
  PLAY_LATER: null,
} as const
```

对象定义 `src/renderer/store/list/listManage/state.ts:6-23`：

```ts
export const defaultList = markRaw<LX.List.MyDefaultListInfo>({
  id: LIST_IDS.DEFAULT,
  name: 'list__name_default',
})
export const loveList = markRaw<LX.List.MyLoveListInfo>({
  id: LIST_IDS.LOVE,
  name: 'list__name_love',
})
export const tempList = markRaw<LX.List.MyTempListInfo>({
  id: LIST_IDS.TEMP,
  name: '临时列表',
  meta: {},
})
```

**特殊情况 1：它们不是 `userList` 成员，DB 中没有 `my_list` 行。**
证据：`listDataOverwrite`（`store/list/listManage/action.ts:109-144`）把 `userList` 与 default/love/temp 分开处理：
```ts
// store/list/listManage/action.ts:112-140（节选）
  const newUserListInfos = userList.map(({ list, ...listInfo }) => {
    newUserIds.push(listInfo.id)
    ...
  })
  ...
  if (allMusicList.has(LIST_IDS.DEFAULT)) {
    overwriteMusicList(LIST_IDS.DEFAULT, defaultList)
    ...
  }
  overwriteMusicList(LIST_IDS.LOVE, loveList)
  ...
  const newIds = [LIST_IDS.DEFAULT, LIST_IDS.LOVE, ...userList.map(l => l.id)]
```
主进程 `listDataOverwrite`（`dbService/modules/list/index.ts:367-395`）同样只把 `listData.userList` 写进 `dbLists`，而 default/love/temp 的歌曲直接写进 `musicLists` Map。**因此 CLI 从 DB 读不到 default/love 的元数据，必须硬编码这两个 id 与 i18n key。**

**特殊情况 2：`name` 存的是 i18n key，不是显示名。**
`'list__name_default'` / `'list__name_love'`。渲染时翻译。CLI 若要与 UI 对齐，需查 `src/lang/zh-cn.json` 的 `list__name_default`、`list__name_love`。

**特殊情况 3：`love` 列表在「列表不存在时」的特殊返回约定。**
多处代码用「若目标列表不存在，则仅当它是 love 才返回 `[id]`」这一模式：
```ts
// store/list/listManage/action.ts:226
if (!targetList) return id == loveList.id ? [id] : []
// store/list/listManage/action.ts:258
if (!targetList) return listId == loveList.id ? [listId] : []
// store/list/listManage/action.ts:291
if (!targetList) return listId == loveList.id ? [listId] : []
// store/list/listManage/action.ts:210
return isExist || listId == loveList.id ? [listId] : []
```
含义：**love 列表即使尚未加载过歌曲（不在 `allMusicList` Map 中），也允许「先写入后加载」**。

**特殊情况 4：`updateList` 对三个虚拟列表的写操作被丢弃。**
```ts
// store/list/listManage/action.ts:74-89
  switch (id) {
    case defaultList.id:
    case loveList.id:
      break                                  // ← 静默丢弃
    case tempList.id:
      tempList.meta = meta ?? {}
      break
    default:
      targetList = userLists.find(l => l.id == id)
      ...
  }
```
**无法重命名 default/love**。

**特殊情况 5：`temp` 列表（临时列表）** 用于「播放歌单/排行榜时临时装载」，带 `meta.id` 记录来源列表 id（如 `kw__123456`）。见 `views/songList/Detail/action.ts:44-56` 与 `store/list/action.ts:79-85`：
```ts
// store/list/action.ts:79-85
export const setTempList = async(id: string, list: LX.Music.MusicInfoOnline[]) => {
  tempListMeta.id = id
  await overwriteListMusics({
    listId: LIST_IDS.TEMP,
    musicInfos: list,
  })
}
```
`temp` 在同步功能中被**明确排除**（`src/main/modules/sync/listEvent.ts:58,70,74,83`：`if (isRemote || listId == LIST_IDS.TEMP) return`）。

**特殊情况 6：`PLAY_LATER = null`** —— 不是真实列表，只是一个「稍后播放」的临时队列标记（`components/material/OnlineList/usePlay.ts:38-41`）。

**特殊情况 7：`download`** 是下载列表 id，数据在 `download_list` 表，属于 `LX.Download.ListItem[]`，**不是 MusicInfo**（`types/list.d.ts:54-61` 的 `ListSaveInfo` 区分 `'myList' | 'downloadList'`）。

### 2.4 `sourceListId` 的语义与格式（CLI 要能生成/解析）

`UserListInfo.source` + `sourceListId` 表达「此列表是从某在线源导入的，可刷新」。

**`sourceListId` 的两种格式：**

| 形态 | 含义 | 出处 |
|---|---|---|
| 纯 id，如 `'1234567'` | 普通歌单 id | `views/songList/Detail/action.ts:12-35` |
| `board__{id}`，如 `'board__kw__16'` | 排行榜 id | `store/list/syncSourceList.ts:11-13` |

```ts
// store/list/syncSourceList.ts:7-20
const fetchList = async(id: string, source: LX.OnlineSource, sourceListId: string) => {
  setFetchingListStatus(id, true)

  let promise
  if (/^board__/.test(sourceListId)) {
    const id = sourceListId.replace(/^board__/, '')
    promise = id ? getBoardListAll(id, true) : Promise.reject(new Error('id not defined: ' + sourceListId))
  } else {
    promise = getListDetailAll(sourceListId, source, true)
  }
  ...
}
```

**注意 `sourceListId` 的两种「带 source 前缀」的书写不一致：**

- 去重判定用 `source__id` 与 `id` 混用（`views/songList/Detail/action.ts:10-16`）：
  ```ts
  const getListId = (id: string, source: LX.OnlineSource) => `${source}__${id}`
  const listId = getListId(id, source)
  const targetList = userLists.find(l => l.sourceListId == listId)   // ← 找的是 `${source}__${id}`
  ...
  await createUserList({
    id: `${source}_${toMD5(listId)}`,       // ← 列表 id 是 `${source}_${md5(source__id)}`
    source,
    sourceListId: id,                        // ← 但存进 sourceListId 的是裸 id！
  })
  ```
  也就是说：**判定时拿 `source__id` 去比，写入时却写裸 `id`**。对 `board__` 前缀来说，`getListId` 会产出 `kw__board__kw__16`，而存的是 `board__kw__16`。**CLI 若要复刻「该歌单是否已导入」的判定，必须用 `source__${sourceListId}` 去比对，而不是直接比 `sourceListId`。**

- 排行榜路径（`views/Leaderboard/action.ts:31`）同样：`id: \`${source}_${toMD5(listId)}\``。

**自动刷新的数据流**：`syncSourceList.ts:22-31` → `overwriteListMusics` 覆写全部歌曲 + 写 `setListUpdateTime`。触发点见 `store/list/listManage/action.ts:197`（用户列表重排时更新 `locationUpdateTime = Date.now()`）。

**`locationUpdateTime`**：毫秒时间戳或 `null`。`createUserList` 中 `position < 0 ? null : Date.now()`（`store/list/action.ts:71`）。**注意与 `ListUpdateInfo` 区分**：后者是 data 存储的 `Record<listId, { updateTime, isAutoUpdate }>`（`types/list.d.ts:49-52`）。

### 2.5 歌曲行的位置更新常量

```ts
// src/common/types/app_setting.d.ts:6
type AddMusicLocationType = 'top' | 'bottom'
```
默认值 `'top'`（`src/common/defaultSetting.ts:109`：`'list.addMusicLocationType': 'top'`）。

---

## 3. source 标识符与音源注册表

### 3.1 类型层面的 source 全集

`src/common/types/common.d.ts:48-52`：

```ts
type OnlineSource = 'kw' | 'kg' | 'tx' | 'wy' | 'mg'
type Source = OnlineSource | 'local'

type Quality = '128k' | '320k' | 'flac' | 'flac24bit' | '192k' | 'ape' | 'wav'

type QualityList = Partial<Record<LX.Source, LX.Quality[]>>
```

> 📌 **`bd` 与 `xm` 不在类型系统里** —— 即使 `musicSdk/index.js` 导入了它们。

### 3.2 运行时注册表（权威）

`src/renderer/utils/musicSdk/index.js:1-62`：

```js
import kw from './kw/index'
import kg from './kg/index'
import tx from './tx/index'
import wy from './wy/index'
import mg from './mg/index'
import bd from './bd/index'
import xm from './xm'
import { supportQuality } from './api-source'
import { versionChars } from './versionChars'

const sources = {
  sources: [
    {
      name: '酷我音乐',
      id: 'kw',
    },
    {
      name: '酷狗音乐',
      id: 'kg',
    },
    {
      name: 'QQ音乐',
      id: 'tx',
    },
    {
      name: '网易音乐',
      id: 'wy',
    },
    {
      name: '咪咕音乐',
      id: 'mg',
    },
    {
      name: '虾米音乐',
      id: 'xm',
    },
    // {
    //   name: '百度音乐',
    //   id: 'bd',
    // },
  ],
  kw,
  kg,
  tx,
  wy,
  mg,
  bd,
  xm,
}
export default {
  ...sources,
  init() {
    const tasks = []
    for (let source of sources.sources) {
      let sm = sources[source.id]
      sm && sm.init && tasks.push(sm.init())
    }
    return Promise.all(tasks)
  },
  supportQuality,

  async searchMusic({ name, singer, source: s, limit = 25 }) {
    const trimStr = str => typeof str == 'string' ? str.trim() : str
    const musicName = trimStr(name)
    const tasks = []
    const excludeSource = ['xm']
    for (const source of sources.sources) {
      if (!sources[source.id].musicSearch || source.id == s || excludeSource.includes(source.id)) continue
      tasks.push(sources[source.id].musicSearch.search(`${musicName} ${singer || ''}`.trim(), 1, limit).catch(_ => null))
    }
    return (await Promise.all(tasks)).filter(s => s)
  },
  ...
}
```

**注册表实际生效的 source（有 `musicSearch`）**：`kw`、`kg`、`tx`、`wy`、`mg`。`xm` 被 `excludeSource` 排除（其 `musicSearch` 已被注释掉，`xm.js:14`），`bd` 被注释出 `sources.sources` 数组（仍然被 `...sources` 展开导出，因此 `musicSdk.bd` 是**可访问的**，只是不会被自动遍历到）。

**这就是为什么 `sourceNames` 只硬编码 5 个键**（见 §3.3）。

### 3.3 显示名（两种模式）

`src/renderer/store/index.ts:86-105`：

```ts
export const getSourceI18nPrefix = () => {
  return appSetting['common.sourceNameType'] == 'real' ? 'source_' : 'source_alias_'
}

export const sourceNames = computed(() => {
  const prefix = getSourceI18nPrefix()
  const sourceNames: Record<LX.OnlineSource | 'all', string> = {
    kw: 'kw',
    tx: 'tx',
    kg: 'kg',
    mg: 'mg',
    wy: 'wy',
    all: window.i18n.t(prefix + 'all' as any),
  }
  for (const { id } of music.sources) {
    sourceNames[id as LX.OnlineSource] = window.i18n.t(prefix + id as any)
  }

  return sourceNames
})
```

`appSetting['common.sourceNameType']` 取值 `'alias' | 'real'`（`types/app_setting.d.ts:39`），默认 `'alias'`（`defaultSetting.ts:15`）。

**完整显示名映射表**（`src/lang/zh-cn.json:620-635`，逐字）：

| key | zh-cn 值（alias 模式） | key | zh-cn 值（real 模式） |
|---|---|---|---|
| `source_alias_all` | 聚合大会 | `source_all` | 聚合搜索 |
| `source_alias_kw` | 小蜗音乐 | `source_kw` | 酷我音乐 |
| `source_alias_kg` | 小枸音乐 | `source_kg` | 酷狗音乐 |
| `source_alias_tx` | 小秋音乐 | `source_tx` | 企鹅音乐 |
| `source_alias_wy` | 小芸音乐 | `source_wy` | 网易音乐 |
| `source_alias_mg` | 小蜜音乐 | `source_mg` | 咪咕音乐 |
| `source_alias_bd` | 小杜音乐 | `source_bd` | 百度音乐 |
| `source_alias_xm` | 小霞音乐 | `source_xm` | 虾米音乐 |

> ⚠️ 注意：**`sourceNames` 里 `kw/tx/kg/mg/wy` 的初值是裸 id 字符串**（`kw: 'kw'`），只有 `all` 与循环里的 `music.sources` 走了 i18n。由于循环一定覆盖这 5 个键，初值实际不会生效 —— 但**如果某个源被从 `music.sources` 移除，UI 会显示裸 id**。这是 CLI 展示时的潜在不一致点。
> `source_local` 在 zh-cn.json 中 **不存在**（grep 无匹配）—— **未验证** local 在 UI 上的显示名，推测为裸字符串 `"local"`。

### 3.4 「启用/可用」的判定 —— `assertApiSupport`

**这是 CLI 最需要复刻的判断**。`src/renderer/store/utils.ts:14-16`：

```ts
export const assertApiSupport = (source: LX.Source): boolean => {
  return source == 'local' || qualityList.value[source] != null
}
```

`qualityList` 是一个 `shallowRef<LX.QualityList>({})`（`src/renderer/store/index.ts:157`），即 `Partial<Record<Source, Quality[]>>`。

**`qualityList` 的两种来源：**

1. **内置 API 源**（`src/renderer/core/apiSource.ts:38-44`）：
   ```ts
   } else {
     // @ts-expect-error
     qualityList.value = musicSdk.supportQuality[apiId] ?? {}
     apiSource.value = apiId
     void setUserApiAction(apiId)
     ...
   }
   ```
   `musicSdk.supportQuality` 来自 `api-source.js:24-29`，遍历 `api-source-info.ts` 数组 —— **该数组在整个 v2.12.5 中是空的**（全部被注释，`api-source-info.ts:9-30`）。

2. **用户音源脚本**（`src/renderer/core/useApp/useInitUserApi.ts:32-132`）：
   ```ts
   if (apiInfo.sources) {
     let apis: any = {}
     let qualitys: LX.QualityList = {}
     for (const [source, { actions, type, qualitys: sourceQualitys }] of Object.entries(apiInfo.sources)) {
       if (type != 'music') continue
       apis[source as LX.Source] = {}
       for (const action of actions) {
         switch (action) {
           case 'musicUrl': ...
           case 'lyric': ...
           case 'pic': ...
         }
       }
       qualitys[source as LX.Source] = sourceQualitys
     }
     qualityList.value = qualitys
     userApi.apis = apis
   }
   ```

> 📌 **结论：v2.12.5 中 `qualityList` 完全由「当前选中的用户音源脚本」决定。** 没有脚本 → `qualityList = {}` → **所有在线源都不可播放**（`assertApiSupport` 全 false）。这解释了为什么默认配置 `'common.apiSource': 'temp'`（`defaultSetting.ts:14`）而 `api-source-info.ts` 为空 —— 用户必须导入音源脚本。**CLI 必须先确认音源脚本已加载，否则只能做元数据操作，不能取播放 URL。**

**UI 中的体现**：
- 搜索结果「下载/播放」按钮禁用：`OnlineList/index.vue:46`
  ```html
  <material-list-buttons :index="index" :remove-btn="false" :download-btn="assertApiSupport(item.source)" :play-btn="checkApiSource ? assertApiSupport(item.source) : true" ... />
  ```
- 我的列表整行置灰 + 不可下载：`views/List/MusicList/index.vue:31,52`
  ```html
  :class="[{ ... }, { disabled: !assertApiSupport(item.source) }]"
  ...
  <material-list-buttons :index="index" :download-btn="assertApiSupport(item.source) && item.source != 'local'" ... />
  ```
- 歌单/排行榜也用它过滤（`views/Search/MusicList/useList.ts:41`、`views/songList/Detail/action.ts` 等）。

**⚠️ `assertApiSupport` 是「按 source 粒度」的，不是「按歌曲粒度」的。** 一首歌是否真的能播还要看 `meta._qualitys`（见 §4.3）。

### 3.5 音源脚本（用户 API）如何注册进 source

**协议类型**（`src/common/types/user_api.d.ts:1-34`）：

```ts
declare namespace LX {
  namespace UserApi {
    type UserApiSourceInfoType = 'music'
    type UserApiSourceInfoActions = 'musicUrl' | 'lyric' | 'pic'

    interface UserApiSourceInfo {
      name: string
      type: UserApiSourceInfoType
      actions: UserApiSourceInfoActions[]
      qualitys: LX.Quality[]
    }

    type UserApiSources = Record<LX.Source, UserApiSourceInfo>

    interface UserApiInfoFull {
      id: string
      name: string
      description: string
      script: string
      allowShowUpdateAlert: boolean
      author?: string
      homepage?: string
      version?: string
      sources?: UserApiSources
    }
    ...
  }
}
```

**脚本侧能力上限**（`src/main/modules/userApi/renderer/preload.js:28-45`）：

```js
const allSources = ['kw', 'kg', 'tx', 'wy', 'mg', 'local']
const supportQualitys = {
  kw: ['128k', '320k', 'flac', 'flac24bit'],
  kg: ['128k', '320k', 'flac', 'flac24bit'],
  tx: ['128k', '320k', 'flac', 'flac24bit'],
  wy: ['128k', '320k', 'flac', 'flac24bit'],
  mg: ['128k', '320k', 'flac', 'flac24bit'],
  local: [],
}
const supportActions = {
  kw: ['musicUrl'],
  kg: ['musicUrl'],
  tx: ['musicUrl'],
  wy: ['musicUrl'],
  mg: ['musicUrl'],
  xm: ['musicUrl'],
  local: ['musicUrl', 'lyric', 'pic'],
}
```

**注册流程**（`preload.js:128-167`）：
```js
const handleInit = (context, info) => {
  ...
  const sourceInfo = { sources: {} }
  try {
    for (const source of allSources) {
      const userSource = info.sources[source]
      if (!userSource || userSource.type !== 'music') continue
      const qualitys = supportQualitys[source]
      const actions = supportActions[source]
      sourceInfo.sources[source] = {
        type: 'music',
        actions: actions.filter(a => userSource.actions.includes(a)),
        qualitys: qualitys.filter(q => userSource.qualitys.includes(q)),
      }
    }
  } catch (error) { ... }
  sendMessage(USER_API_RENDERER_EVENT_NAME.init, sourceInfo, true)
  ...
}
```
**脚本声明会被宿主取交集过滤** —— 脚本声称支持 `'192k'` 也会被丢掉（`supportQualitys` 里没有）。

**脚本调用桥接**（`useInitUserApi.ts:40-66`，`musicUrl` 分支）：
```ts
case 'musicUrl':
  apis[source].getMusicUrl = (songInfo: LX.Music.MusicInfo, type: LX.Quality) => {
    const requestKey = `request__${Math.random().toString().substring(2)}`
    return {
      canceleFn() { userApiRequestCancel(requestKey) },
      promise: sendUserApiRequest({
        requestKey,
        data: {
          source,
          action: 'musicUrl',
          info: { type, musicInfo: songInfo },
        },
      }).then(res => {
        return { type, url: res.data.url }
      })...
    }
  }
```
**注意：传给脚本的 `musicInfo` 是 `toOldMusicInfo(musicInfo)` 的结果**（在 `core/music/utils.ts:272,309` 调用处 `musicSdk[source].getMusicUrl(toOldMusicInfo(musicInfo), itemQuality)`）——**即脚本看到的是旧格式**（`songmid`/`hash`/`strMediaMid`/`copyrightId` 在顶层）。这是 CLI 与音源脚本互操作时必须遵守的契约。

**脚本返回校验**（`preload.js:78`）：
```js
case 'musicUrl':
  if (typeof response != 'string' || response.length > 2048 || !/^https?:/.test(response)) throw new Error('failed')
```

**音源选择逻辑**（`src/renderer/utils/musicSdk/api-source.js:31-38`）：
```js
const getAPI = source => apiList[`${apiSource.value}_api_${source}`]

const apis = source => {
  if (/^user_api/.test(apiSource.value)) return userApi.apis[source]
  let api = getAPI(source)
  if (api) return api
  throw new Error('Api is not found')
}
```
**`apiSource` 以 `user_api` 开头 → 用脚本**；否则查内置表（当前恒为空 → 抛 `'Api is not found'`）。

**切换音源的入口** `src/renderer/core/apiSource.ts:8-48`：
```ts
let prevId = ''
export const setUserApi = async(apiId: string) => {
  if (prevId == apiId) return
  prevId = apiId
  if (window.lx.apiInitPromise[1]) { ... }

  if (/^user_api/.test(apiId)) {
    qualityList.value = {}
    userApi.status = false
    userApi.message = 'initing'

    await setUserApiAction(apiId).then(() => {
      if (prevId != apiId) return
      apiSource.value = apiId
    }).catch(err => {
      ...
      let api = apiSourceInfo.find(api => !api.disabled)
      if (!api) return
      apiSource.value = api.id
      if (api.id != appSetting['common.apiSource']) setApiSource(api.id)
    })
  } else {
    qualityList.value = musicSdk.supportQuality[apiId] ?? {}
    apiSource.value = apiId
    ...
  }
  ...
}
```
**异步竞态保护**：`prevId` 比较；`window.lx.apiInitPromise[0]` 是一个 Promise，形如 `await window.lx.apiInitPromise[0]` 在取播放 URL 前被 await（`core/music/utils.ts:164,249,303`）—— 抛 `new Error('source init failed')`。

---

## 4. 搜索逻辑

### 4.1 入口与状态

搜索框文本存在 `src/renderer/store/search/state.ts` 的 `searchText`（ref）。搜索设置：
```ts
// src/common/constants.ts:62-66
  search: {
    temp_source: 'kw',
    source: 'all',
    type: 'music',
  },
```
`type` 取值 `'music' | 'songlist'`（`views/Search/index.vue:89-94`）。

音乐搜索的每个 source 各有一份分页状态，`src/renderer/store/search/music/state.ts:1-48`（逐字）：

```ts
export declare interface ListInfo {
  list: LX.Music.MusicInfo[]
  total: number
  page: number
  maxPage: number
  limit: number
  key: string | null
  noItemLabel: string
}

interface ListInfos extends Partial<Record<LX.OnlineSource, ListInfo>> {
  'all': ListInfo
}

export const sources: Array<LX.OnlineSource | 'all'> = markRaw([])

export const listInfos: ListInfos = markRaw({
  all: reactive<ListInfo>({
    page: 1,
    maxPage: 0,
    limit: 30,
    total: 0,
    list: [],
    key: null,
    noItemLabel: '',
  }),
})
export const maxPages: Partial<Record<LX.OnlineSource, number>> = {}
for (const source of music.sources) {
  if (!music[source.id as LX.OnlineSource]?.musicSearch) continue
  sources.push(source.id as LX.OnlineSource)
  listInfos[source.id as LX.OnlineSource] = reactive<ListInfo>({
    page: 1,
    maxPage: 0,
    limit: 30,
    total: 0,
    list: [],
    key: '',
    noItemLabel: '',
  })
  maxPages[source.id as LX.OnlineSource] = 0
}
sources.push('all')
```

**关键点：**
- `sources` 数组由 `music.sources` **动态构建**，只收有 `musicSearch` 的源 → 实际是 `['kw','kg','tx','wy','mg','all']`（顺序即 UI Tab 顺序）
- `'all'` 永远 **追加在最后**
- 默认 `limit = 30`，每个源每页独立分页
- `key = \`${page}__${text}\`` 用作**竞态令牌**：响应回来时 `if (key != listInfo!.key) return []` 丢弃过期结果

### 4.2 核心搜索函数

`src/renderer/store/search/music/action.ts:87-126`（逐字）：

```ts
export const search = async(text: string, page: number, sourceId: LX.OnlineSource | 'all'): Promise<LX.Music.MusicInfo[]> => {
  const listInfo = listInfos[sourceId]
  if (!text) return resetListInfo(sourceId)
  const key = `${page}__${text}`
  if (sourceId == 'all') {
    listInfo!.noItemLabel = window.i18n.t('list__loading')
    listInfo!.key = key
    let task = []
    for (const source of sources) {
      if (source == 'all') continue
      task.push((music[source]?.musicSearch.search(text, page, listInfos.all.limit) ?? Promise.reject(new Error('source not found: ' + source))).catch((error: any) => {
        console.log(error)
        return {
          allPage: 1,
          limit: 30,
          list: [],
          source,
          total: 0,
        }
      }))
    }
    return Promise.all(task).then((results: SearchResult[]) => {
      if (key != listInfo!.key) return []
      return setLists(results, page, text)
    })
  } else {
    if (listInfo?.key == key && listInfo?.list.length) return listInfo?.list
    listInfo!.noItemLabel = window.i18n.t('list__loading')
    listInfo!.key = key
    return music[sourceId].musicSearch.search(text, page, listInfo!.limit).then((data: SearchResult) => {
      if (key != listInfo!.key) return []
      return setList(data, page, text)
    }).catch((error: any) => {
      resetListInfo(sourceId)
      listInfo!.noItemLabel = window.i18n.t('list__load_failed')
      console.log(error)
      throw error
    })
  }
}
```

**⚠️ 关键发现：`'all'` 与单源的数值口径不一致。**
- `'all'` 分支：`music[source]?.musicSearch.search(text, page, listInfos.all.limit)` —— **用的是 `listInfos.all.limit`（=30）**，不是目标源自己的默认 limit。所以 `tx`（其内置 `limit: 50`）在聚合模式下也被限制为 30。
- 单源分支：`music[sourceId].musicSearch.search(text, page, listInfo!.limit)` —— 用该源自己的 `listInfo.limit`（同样初始 30）。
- **UI 从不修改 `limit`**（`views/Search/MusicList/useList.ts:16-24` 只有 `page`），所以 limit 实际恒为 30。

**❌ `'all'` 模式下没有错误上抛**：每个源的失败被 `.catch()` 吞成 `{ list: [], total: 0, allPage: 1 }`。单源模式则会 `throw error` 并清空列表、把 `noItemLabel` 设为 `list__load_failed`。

**缓存短路**：单源且 `key` 相同且 `list.length` 非空 → 直接返回，**不再请求**（`:113`）。

### 4.3 结果合并、排序、去重（`setLists`）

`src/renderer/store/search/music/action.ts:23-60`（逐字）：

```ts
/**
 * 按搜索关键词重新排序列表
 * @param list 歌曲列表
 * @param keyword 搜索关键词
 * @returns 排序后的列表
 */
const handleSortList = (list: LX.Music.MusicInfo[], keyword: string) => {
  let arr: any[] = []
  for (const item of list) {
    sortInsert(arr, {
      num: similar(keyword, `${item.name} ${item.singer}`),
      data: item,
    })
  }
  return arr.map(item => item.data).reverse()
}

const setLists = (results: SearchResult[], page: number, text: string): LX.Music.MusicInfo[] => {
  let pages = []
  let totals = []
  let limit = 0
  let list = []
  for (const source of results) {
    maxPages[source.source] = source.allPage
    limit = Math.max(source.limit, limit)
    if (source.allPage < page) continue
    list.push(...source.list)
    pages.push(source.allPage)
    totals.push(source.total)
  }
  list = deduplicationList(list.map(s => markRaw(toNewMusicInfo(s))))
  let listInfo = listInfos.all
  listInfo.maxPage = Math.max(0, ...pages)
  const total = Math.max(0, ...totals)
  if (page == 1 || (total && list.length)) listInfo.total = total
  else listInfo.total = limit * page
  // listInfo.limit = limit
  listInfo.page = page
  listInfo.list = handleSortList(list, text)
  if (text && !list.length && page == 1) listInfo.noItemLabel = window.i18n.t('no_item')
  else listInfo.noItemLabel = ''
  return listInfo.list
}
```

**聚合算法（CLI 必须复刻的部分）：**

1. **并发请求所有源，同一个 `page` 号**
2. **`maxPages[source]` 被更新**，但 `listInfo.all.maxPage = max(所有源的 allPage)` —— 分页控件用「最大页数」
3. **`if (source.allPage < page) continue`** —— 页码超出某源上限时**静默跳过该源**（不报错、不补齐）
4. **`list.push(...source.list)`** —— 按 `sources` 数组顺序（kw, kg, tx, wy, mg）拼接
5. **`deduplicationList`** 按 `id` 去重 —— **先到先得，后面的同 id 被丢弃**（`src/renderer/utils/index.ts:66-73`）：
   ```ts
   export const deduplicationList = <T extends LX.Music.MusicInfo>(list: T[]): T[] => {
     const ids = new Set<string>()
     return list.filter(s => {
       if (ids.has(s.id)) return false
       ids.add(s.id)
       return true
     })
   }
   ```
6. **`toNewMusicInfo` 转新格式**
7. **`handleSortList` 按相似度重排**：`similar(keyword, \`${item.name} ${item.singer}\`)`，`sortInsert` 二分插入升序，最后 `.reverse()` → **降序（最相似在最前）**
8. **`total = max(所有源的 total)`** —— 这是「估计值」，不是真实结果总数

**相似度算法**（`src/common/utils/common.ts:137-160`）：标准 Levenshtein 距离，返回 `1 - (距离 / 较长串长度)`，范围 `[0, 1]`，越大越相似：

```ts
export const similar = (a: string, b: string) => {
  if (!a || !b) return 0
  if (a.length > b.length) { // 保证 a <= b
    let t = b
    b = a
    a = t
  }
  let al = a.length
  let bl = b.length
  let mp = [] // 一个表
  let i, j, ai, lt, tmp // ai：字符串a的第i个字符。 lt：左上角的值。 tmp：暂存新的值。
  for (i = 0; i <= bl; i++) mp[i] = i
  for (i = 1; i <= al; i++) {
    ai = a.charAt(i - 1)
    lt = mp[0]
    mp[0] = mp[0] + 1
    for (j = 1; j <= bl; j++) {
      tmp = Math.min(mp[j] + 1, mp[j - 1] + 1, lt + (ai == b.charAt(j - 1) ? 0 : 1))
      lt = mp[j]
      mp[j] = tmp
    }
  }
  return 1 - (mp[bl] / bl)
}
```

> ⚠️ **CLI 注意**：这个排序是**全局的**，跨源混排。所以 UI 上「第一条」不一定是某指定源的。若 CLI 要「指定源搜索」，必须走单源分支（`sourceId != 'all'`），那时**不排序**（`setList` 直接 `deduplicationList(datas.list.map(...))`，保持服务端返回顺序）。

**单源 `setList`**（`search/music/action.ts:62-74`）：
```ts
const setList = (datas: SearchResult, page: number, text: string): LX.Music.MusicInfo[] => {
  let listInfo = listInfos[datas.source]!
  listInfo.list = deduplicationList(datas.list.map(s => markRaw(toNewMusicInfo(s))))
  if (page == 1 || (datas.total && datas.list.length)) listInfo.total = datas.total
  else listInfo.total = datas.limit * page
  listInfo.maxPage = datas.allPage
  listInfo.page = page
  listInfo.limit = datas.limit
  if (text && !datas.list.length && page == 1) listInfo.noItemLabel = window.i18n.t('no_item')
  else listInfo.noItemLabel = ''
  return listInfo.list
}
```
注意这里会 **`listInfo.limit = datas.limit`** 回写（各源 `limit` 默认值不同：kw=30, kg=30, tx=50, wy=30, mg=30, bd=30；见各 `musicSearch.js` 的 `limit` 字段）。所以**切到 tx Tab 后再切回 all，all 的 limit 仍是 30**（`setLists` 里 `listInfo.limit` 那行被注释掉了）。

### 4.4 各源 `search()` 的返回契约

所有源的 `search(str, page, limit)` 返回**同一 shape**（这是 CLI 最该对齐的接口）：

```ts
{
  list: OldMusicInfo[],   // 旧格式！由调用方 toNewMusicInfo
  allPage: number,
  limit: number,
  total: number,
  source: LX.OnlineSource,
}
```

各源实现与分页参数（逐字）：

| source | 文件:行 | 页码/尺寸参数 | total 来源 | 重试 |
|---|---|---|---|---|
| `kw` | `kw/musicSearch.js:102-125` | `pn=${page - 1}`（**0-based**）、`rn=${limit}` | `parseInt(result.TOTAL)` | `retryNum > 2` |
| `kg` | `kg/musicSearch.js:86-108` | `page=${page}`（**1-based**）、`pagesize=${limit}` | `result.data.total` | `++retryNum > 3` |
| `tx` | `tx/musicSearch.js:130-147` | `page_num: page`、`num_per_page: limit` | `meta.sum` | `retryNum > 5` |
| `wy` | `wy/musicSearch.js:94-118` | `offset: limit * (page - 1)`（**offset 式**）、`limit` | `result.data.totalCount` | `++retryNum > 3` |
| `mg` | `mg/musicSearch.js:198-222` | `pageNo=${page}`、`pageSize=${limit}` | `parseInt(songResultData.totalCount)` | `++retryNum > 3` |
| `bd` | `bd/musicSearch.js:65-87` | `page_no=${page}`、`page_size=${limit}` | `result.result.song_info.total` | `++retryNum > 3` |

**统一 `allPage = Math.ceil(total / limit)`。**

**⚠️ `kw` 的分页是 0-based**（`pn=${page - 1}`），其余是 1-based / offset。CLI 若直接调用上游 API 必须逐源处理。

**⚠️ `wy` 的 `allPage` 用 `this.limit` 而非传入的 `limit`**（`wy/musicSearch.js:107`）：
```js
this.allPage = Math.ceil(this.total / this.limit)
```
其余源用 `limit`。在 limit 恒为 30 时无差异，但若 CLI 传入不同 limit 会算错。

### 4.5 `findMusic` —— 跨源「找同一首歌」（换源 / deeplink 核心）

`src/renderer/utils/musicSdk/index.js:75-175`，这是**最复杂、CLI 最需要复刻的算法**。关键片段（逐字）：

```js
async findMusic({ name, singer, albumName, interval, source: s }) {
    const lists = await this.searchMusic({ name, singer, source: s, limit: 25 })
    ...
    const singersRxp = /、|&|;|；|\/|,|，|\|/
    const sortSingle = singer => singersRxp.test(singer)
      ? singer.split(singersRxp).sort((a, b) => a.localeCompare(b)).join('、')
      : (singer || '')
    ...
    const getIntv = (interval) => {
      if (!interval) return 0
      let intvArr = interval.split(':')
      let intv = 0
      let unit = 1
      while (intvArr.length) {
        intv += parseInt(intvArr.pop()) * unit
        unit *= 60
      }
      return intv
    }
    const trimStr = str => typeof str == 'string' ? str.trim() : (str || '')
    const filterStr = str => typeof str == 'string' ? str.replace(/\s|'|\.|,|，|&|"|、|\(|\)|（|）|`|~|-|<|>|\||\/|\]|\[|!|！/g, '') : String(str || '')
    const fMusicName = filterStr(name).toLowerCase()
    const fSinger = filterStr(sortSingle(singer)).toLowerCase()
    const fAlbumName = filterStr(albumName).toLowerCase()
    const fInterval = getIntv(interval)
    const isEqualsInterval = (intv) => Math.abs((fInterval || intv) - (intv || fInterval)) <= 5
    const isEqualsVersionMusicNameChar = (name) => {
      for (const char of versionChars) {
        if (name.includes(char) != fMusicName.includes(char)) return false
      }
      return true
    }
    const isIncludesName = (name) => (fMusicName.includes(name) || name.includes(fMusicName)) && isEqualsVersionMusicNameChar(name)
    const isIncludesSinger = (singer) => fSinger ? (fSinger.includes(singer) || singer.includes(fSinger)) : true
    const isEqualsAlbum = (album) => fAlbumName ? fAlbumName == album : true

    const result = lists.map(source => {
      for (const item of source.list) {
        item.name = trimStr(item.name)
        item.singer = trimStr(item.singer)
        item.fSinger = filterStr(sortSingle(item.singer).toLowerCase())
        item.fMusicName = filterStr(String(item.name ?? '').toLowerCase())
        item.fAlbumName = filterStr(String(item.albumName ?? '').toLowerCase())
        item.fInterval = getIntv(item.interval)
        if (!isEqualsInterval(item.fInterval)) {
          item.name = null
          continue
        }
        if (item.fMusicName == fMusicName && isIncludesSinger(item.fSinger)) return item
      }
      for (const item of source.list) {
        if (item.name == null) continue
        if (item.fSinger == fSinger && isIncludesName(item.fMusicName)) return item
      }
      for (const item of source.list) {
        if (item.name == null) continue
        if (isEqualsAlbum(item.fAlbumName) && isIncludesSinger(item.fSinger) && isIncludesName(item.fMusicName)) return item
      }
      return null
    }).filter(s => s)
    const newResult = []
    if (result.length) {
      newResult.push(...sortMusic(result, item => item.fSinger == fSinger && item.fMusicName == fMusicName && item.interval == interval))
      newResult.push(...sortMusic(result, item => item.fMusicName == fMusicName && item.fSinger == fSinger && item.fAlbumName == fAlbumName))
      newResult.push(...sortMusic(result, item => item.fSinger == fSinger && item.fMusicName == fMusicName))
      newResult.push(...sortMusic(result, item => item.fMusicName == fMusicName && item.interval == interval))
      newResult.push(...sortMusic(result, item => item.fSinger == fSinger && item.interval == interval))
      newResult.push(...sortMusic(result, item => item.interval == interval))
      newResult.push(...sortMusic(result, item => item.fMusicName == fMusicName))
      newResult.push(...sortMusic(result, item => item.fSinger == fSinger))
      newResult.push(...sortMusic(result, item => item.fAlbumName == fAlbumName))
      for (const item of result) {
        delete item.fSinger
        delete item.fMusicName
        delete item.fAlbumName
        delete item.fInterval
      }
      newResult.push(...result)
    }
    return newResult
  },
```

**算法要点：**

1. **搜索词**：`\`${musicName} ${singer || ''}\`.trim()`，`limit = 25`，**永远 page = 1**
2. **排除自己**：`if (... || source.id == s ...) continue` —— 不搜原源（避免换源换回同一首）
3. **排除 `xm`**：`const excludeSource = ['xm']`
4. **每个源最多挑 1 首**（`lists.map(...)` 返回单值）
5. **时长过滤是无条件的硬门槛**：`if (!isEqualsInterval(item.fInterval)) { item.name = null; continue }` —— 误差 **≤ 5 秒**
6. **三轮匹配优先级**（同一源内）：① 歌名完全相等 + 歌手包含；② 歌手完全相等 + 歌名包含；③ 专辑相等 + 歌手包含 + 歌名包含
7. **歌名匹配要过版本标记检查**（`versionChars`）—— 防止把「Live」「伴奏」「remix」当作同一首：

`src/renderer/utils/musicSdk/versionChars.ts:1-9`（开头）：
```ts
export const versionChars = [
  // 伴奏 / 无人声
  // instrumental: [
  'instrumental',
  'inst',
  'karaoke',
  'backing track',
  'minus one',
  'minus vocal',
  'no vocal',
  'off vocal',
  'vocal removed',
  '伴奏',
  ...
```

**完整清单**（124 行，按类别分组，逐字汇总）：

| 类别 | 标记词 |
|---|---|
| **伴奏/无人声** | `instrumental`, `inst`, `karaoke`, `backing track`, `minus one`, `minus vocal`, `no vocal`, `off vocal`, `vocal removed`, `伴奏`, `伴唱`, `卡拉ok`, `纯音乐`, `无人声`, `去人声`, `消音`, `オフボーカル`, `インスト`, `반주`, `노래방` |
| **现场** | `live`, `concert`, `tour`, `festival`, `stage`, `session`, `现场`, `演唱会`, `巡演`, `音乐会`, `ライブ`, `공연`, `라이브` |
| **翻唱** | `cover`, `tribute`, `rendition`, `remake`, `翻唱`, `致敬`, `改编`, `カバー`, `커버` |
| **混音** | `remix`, `mix`, `club`, `dance`, `extended`, `house`, `edm`, `dj`, `dub`, `trap`, `混音`, `重混`, `电音`, `リミックス`, `리믹스` |
| **原声/不插电** | `acoustic`, `unplugged`, `stripped`, `原声`, `不插电`, `アコースティック`, `어쿠스틱` |
| **Demo** | `demo`, `小样`, `试听`, `デモ`, `데모` |
| **速度变化** | `slowed`, `slowed reverb`, `sped up`, `speed up`, `nightcore`, `慢速`, `加速`, `变速`, `ナイトコア` |
| **特殊乐器版** | `piano`, `guitar`, `orchestra`, `symphony`, `violin`, `钢琴`, `吉他`, `管弦乐`, `小提琴`, `ピアノ`, `ギター`, `피아노`, `기타` |

**判定语义**（`musicSdk/index.js:119-124`）：
```js
const isEqualsVersionMusicNameChar = (name) => {
  for (const char of versionChars) {
    if (name.includes(char) != fMusicName.includes(char)) return false
  }
  return true
}
```
**逐词双向 XOR**：候选歌名与原歌名在**每一个**标记词上的「包含与否」必须一致。任一标记词只在一侧出现即判定为不同版本。注意这是**子串匹配且大小写敏感**（`fMusicName` 已 `toLowerCase()`，但 `versionChars` 里都是小写，匹配的是已小写的候选名 —— 逻辑一致）。

> ⚠️ **注意「试听」在 demo 类里** —— 而 `LIST_IDS.DEFAULT` 的中文名曾叫「试听列表」（`types/list.d.ts:16` 注释）。两者无关联，仅是同词巧合。
8. **最终 9 级排序**（`sortMusic` 是稳定的「筛选删除」实现，保持原相对顺序）；**未匹配任何条件的被追加到最后**
9. **`sortMusic` 会 `delete` 掉 `fSinger/fMusicName/fAlbumName/fInterval` 四个临时字段**（`:89-92`），最后兜底也删一遍（`:165-170`）

**调用方**：`src/renderer/core/music/utils.ts:20-76` 的 `getOtherSource`：
```ts
// core/music/utils.ts:20-76（节选）
export const getOtherSource = async(musicInfo, isRefresh = false): Promise<LX.Music.MusicInfoOnline[]> => {
  if (otherSourceCache.has(musicInfo)) return otherSourceCache.get(musicInfo)!
  let key: string
  let searchMusicInfo: { name, singer, source, albumName, interval }
  if ('progress' in musicInfo) {
    key = `local_${musicInfo.id}`
    searchMusicInfo = { name: ..., singer: ..., source: ..., albumName: ..., interval: ... }
  } else {
    key = `${musicInfo.source}_${musicInfo.id}`
    searchMusicInfo = {
      name: musicInfo.name,
      singer: musicInfo.singer,
      source: musicInfo.source,
      albumName: musicInfo.meta.albumName,
      interval: musicInfo.interval ?? '',
    }
  }
  if (getOtherSourcePromises.has(key)) return getOtherSourcePromises.get(key)

  const promise = new Promise<LX.Music.MusicInfoOnline[]>((resolve, reject) => {
    let timeout = setTimeout(() => { reject(new Error('find music timeout')) }, 15_000)
    musicSdk.findMusic(searchMusicInfo).then((otherSource) => {
      if (otherSourceCache.size > 10) otherSourceCache.clear()
      const source = otherSource.map(toNewMusicInfo) as LX.Music.MusicInfoOnline[]
      otherSourceCache.set(musicInfo, source)
      resolve(source)
    }).catch(reject).finally(() => { if (timeout) clearTimeout(timeout) })
  })...
}
```

- **超时 15 秒**
- **缓存：`otherSourceCache` 是 `Map<musicInfo, MusicInfoOnline[]>`**（以**对象引用**为键，不是 id！），超过 10 项整体 `clear()`
- **并发去重**：`getOtherSourcePromises` 按 key 复用同一 Promise

**⚠️ 注意 `key = \`${musicInfo.source}_${musicInfo.id}\``** —— 对 kg 来说会变成 `kg_A1B2_9F8E`，这纯粹是内部 key，不影响功能，但说明**作者自己也把 id 当成「不含 source 前缀」来用**，是个隐患。

### 4.6 播放音质选择 —— `getPlayQuality`

`src/renderer/core/music/utils.ts:221-235`（逐字）：

```ts
export const TRY_QUALITYS_LIST = ['flac24bit', 'flac', '320k'] as const
type TryQualityType = typeof TRY_QUALITYS_LIST[number]
export const getPlayQuality = (highQuality: LX.Quality, musicInfo: LX.Music.MusicInfoOnline): LX.Quality => {
  let type: LX.Quality = '128k'
  if (TRY_QUALITYS_LIST.includes(highQuality as TryQualityType)) {
    let list = qualityList.value[musicInfo.source]

    let t = TRY_QUALITYS_LIST
      .slice(TRY_QUALITYS_LIST.indexOf(highQuality as TryQualityType))
      .find(q => musicInfo.meta._qualitys[q] && list?.includes(q))

    if (t) type = t
  }
  return type
}
```

**语义：**
- 用户设置 `appSetting['player.playQuality']`（默认 `'128k'`，`defaultSetting.ts:28`）
- 若设置值不在 `TRY_QUALITYS_LIST`（即用户设了 `128k` / `192k` / `ape` / `wav`）→ **恒返回 `'128k'`**
- 否则从设置值开始**向下**（降级方向）在 `['flac24bit','flac','320k']` 里找第一个「歌曲有（`meta._qualitys[q]`）**且**音源支持（`qualityList.value[source].includes(q)`）」的音质
- **兜底 `'128k'` 不做存在性校验** —— 即使歌曲和音源都没有 128k 也会返回它

**下载用的音质选择** 稍有不同，`src/renderer/worker/download/utils.ts:57-66`（用 `QUALITYS` 全序）：

```ts
export const getMusicType = (musicInfo: LX.Music.MusicInfoOnline, type: LX.Quality, qualityList: LX.QualityList): LX.Quality => {
  let list = qualityList[musicInfo.source]
  if (!list) return '128k'
  if (!list.includes(type)) type = list[list.length - 1]
  const rangeType = QUALITYS.slice(QUALITYS.indexOf(type))
  for (const type of rangeType) {
    if (musicInfo.meta._qualitys[type]) return type
  }
  return '128k'
}
```
差异：**若用户设置值不在音源支持列表里，先降级到该音源支持列表的最后一项**（`list[list.length - 1]`，即最低音质），然后仍用 `QUALITYS` 全序向下找。

### 4.7 取播放 URL 的完整链路

```
core/music/index.ts: getMusicUrl()                       ← 按类型分发
  ├─ 'progress' in musicInfo → ./download
  ├─ source == 'local'       → ./local
  └─ else                    → ./online: getMusicUrl()
       ├─ getStoreMusicUrl(musicInfo, targetQuality)      ← 先查 DB 缓存
       └─ handleGetOnlineMusicUrl()                       ← core/music/utils.ts:291-334
            ├─ musicSdk[source].getMusicUrl(toOldMusicInfo(musicInfo), targetQuality)
            │    └─ apis(source).getMusicUrl(...)         ← 内置 or 用户脚本
            └─ 失败 → onToggleSource() + getOtherSource() + getOnlineOtherSourceMusicUrl()
```

**带缓存的入口**（`src/renderer/core/music/online.ts:41-63`）：
```ts
export const getMusicUrl = async({ musicInfo, quality, isRefresh, allowToggleSource = true, onToggleSource = () => {} }) => {
  const targetQuality = quality ?? getPlayQuality(appSetting['player.playQuality'], musicInfo)
  const cachedUrl = await getStoreMusicUrl(musicInfo, targetQuality)
  if (cachedUrl && !isRefresh) return cachedUrl

  return handleGetOnlineMusicUrl({ musicInfo, quality, onToggleSource, isRefresh, allowToggleSource }).then(({ url, quality: targetQuality, musicInfo: targetMusicInfo, isFromCache }) => {
    if (targetMusicInfo.id != musicInfo.id && !isFromCache) void saveMusicUrl(targetMusicInfo, targetQuality, url)
    void saveMusicUrl(musicInfo, targetQuality, url)
    return url
  })
}
```
**缓存 key 已验证**：`music_url` 表的主键 `id` **是 `MusicInfo.id` 与音质拼接**，不是裸 id。`src/renderer/utils/ipc.ts:636-657`（逐字）：

```ts
/**
 * 从缓存获取歌曲URL
 * @param musicInfo 歌曲信息
 * @param type URL音质
 * @returns
 */
export const getMusicUrl = async(musicInfo: LX.Music.MusicInfo, type: LX.Quality): Promise<string> => {
  return rendererInvoke<string, string>(WIN_MAIN_RENDERER_EVENT_NAME.get_music_url, `${musicInfo.id}_${type}`)
}

/**
 * 缓存歌曲URL
 * @param musicInfo 歌曲信息
 * @param type URL音质
 * @param url 歌曲URL
 */
export const saveMusicUrl = async(musicInfo: LX.Music.MusicInfo, type: LX.Quality, url: string) => {
  await rendererInvoke<LX.Music.MusicUrlInfo>(WIN_MAIN_RENDERER_EVENT_NAME.save_music_url, {
    id: `${musicInfo.id}_${type}`,
    url,
  })
}
```

> ✅ **`music_url.id` 的真实形态：`${musicInfo.id}_${quality}`**，例如 `kw_62355680_320k`、`A1B2C3D4_9F8E..._flac`。
> 表结构本身只有 `("id", "url")` 两列（`tables.ts:197-202`），音质信息**编码在 id 字符串里**。
> CLI 若要命中/写入该缓存，必须完全复刻这个拼接规则。

**存的时候两首歌都存** —— 原曲和换源后的曲（`online.ts:59-60`）。

**歌词缓存的 key 则是裸 id**（`src/renderer/utils/ipc.ts:557-563, 578-608`）：
```ts
export const getPlayerLyric = async(musicInfo: LX.Music.MusicInfo) => {
  return rendererInvoke<string, LX.Player.LyricInfo>(WIN_MAIN_RENDERER_EVENT_NAME.get_palyer_lyric, musicInfo.id)
}
```
对应 `lyric` 表的 `("id", "source", "type", "text")`（`tables.ts:188-196`），其中 `source` 列取值 `'raw' | 'edited'`，`type` 取 `'lyric' | 'tlyric' | 'rlyric' | 'lxlyric'`（`types/db_service.d.ts:44-54`）。**歌词缓存不区分音质、不区分源。**

**其他缓存 key 规律汇总：**

| 缓存 | Key 形态 | 出处 |
|---|---|---|
| 播放 URL | `${musicInfo.id}_${quality}` | `utils/ipc.ts:643,654` |
| 原始歌词 / 已编辑歌词 | `musicInfo.id` + `source` 列 | `utils/ipc.ts:558,584,590` |
| 其他音源（换源结果） | `source_id` = ? （调用已注释，**未验证**） | `tables.ts:170-181` |
| 搜索列表缓存 | `slist__${source}__${sortId}__${tabId}__${page}` | `store/songList/action.ts:99` |
| 歌单详情缓存 | `sdetail__${source}__${id}__${page}` | `store/songList/action.ts:132` |
| 排行榜缓存 | `${source}__${id}__${page}` | `store/leaderboard/action.ts:75` |
| `getOtherSource` 内存缓存 | **`musicInfo` 对象引用**（不是 id！） | `core/music/utils.ts:17,25` |

**`handleGetOnlineMusicUrl`**（`core/music/utils.ts:291-334`，逐字）：
```ts
export const handleGetOnlineMusicUrl = async({ musicInfo, quality, onToggleSource, isRefresh, allowToggleSource }): Promise<{ url, musicInfo, quality, isFromCache }> => {
  if (!await window.lx.apiInitPromise[0]) throw new Error('source init failed')
  const targetQuality = quality ?? getPlayQuality(appSetting['player.playQuality'], musicInfo)

  let reqPromise
  try {
    reqPromise = musicSdk[musicInfo.source].getMusicUrl(toOldMusicInfo(musicInfo), targetQuality).promise
  } catch (err: any) {
    reqPromise = Promise.reject(err)
  }
  return reqPromise.then(({ url, type }: { url: string, type: LX.Quality }) => {
    return { musicInfo, url, quality: type, isFromCache: false }
  }).catch(async(err: any) => {
    console.log(err)
    if (!allowToggleSource || err.message == requestMsg.tooManyRequests) throw err
    onToggleSource()
    return getOtherSource(musicInfo).then(otherSource => {
      if (otherSource.length) {
        return getOnlineOtherSourceMusicUrl({
          musicInfos: [...otherSource],
          onToggleSource,
          quality,
          isRefresh,
          retryedSource: [musicInfo.source],
        })
      }
      throw err
    })
  })
}
```

**所有源 `getMusicUrl` 都返回 `{ type, url }` 形状的 `{ promise, canceleFn }` 对象**（见 `kw/api-temp.js:15-21` 的典型实现）。

### 4.8 换源（切换音源）

**两条不同的「换源」路径，CLI 要分清：**

#### A. 播放时自动换源（`getOnlineOtherSourceMusicUrl`）

`src/renderer/core/music/utils.ts:237-286`（逐字）：

```ts
export const getOnlineOtherSourceMusicUrl = async({ musicInfos, quality, onToggleSource, isRefresh, retryedSource = [] }): Promise<{ url, musicInfo, quality, isFromCache }> => {
  if (!await window.lx.apiInitPromise[0]) throw new Error('source init failed')

  let musicInfo: LX.Music.MusicInfoOnline | null = null
  let itemQuality: LX.Quality | null = null
  // eslint-disable-next-line no-cond-assign
  while (musicInfo = (musicInfos.shift()!)) {
    if (retryedSource.includes(musicInfo.source)) continue
    retryedSource.push(musicInfo.source)
    if (!assertApiSupport(musicInfo.source)) continue
    itemQuality = quality ?? getPlayQuality(appSetting['player.playQuality'], musicInfo)
    if (!musicInfo.meta._qualitys[itemQuality]) continue

    console.log('try toggle to: ', musicInfo.source, musicInfo.name, musicInfo.singer, musicInfo.interval)
    onToggleSource(musicInfo)
    break
  }
  if (!musicInfo || !itemQuality) throw new Error(window.i18n.t('toggle_source_failed'))

  const cachedUrl = await getStoreMusicUrl(musicInfo, itemQuality)
  if (cachedUrl && !isRefresh) return { url: cachedUrl, musicInfo, quality: itemQuality, isFromCache: true }

  let reqPromise
  try {
    reqPromise = musicSdk[musicInfo.source].getMusicUrl(toOldMusicInfo(musicInfo), itemQuality).promise
  } catch (err: any) {
    reqPromise = Promise.reject(err)
  }
  return reqPromise.then(({ url, type }: { url: string, type: LX.Quality }) => {
    return { musicInfo, url, quality: type, isFromCache: false }
  }).catch((err: any) => {
    if (err.message == requestMsg.tooManyRequests) throw err
    console.log(err)
    return getOnlineOtherSourceMusicUrl({ musicInfos, quality, onToggleSource, isRefresh, retryedSource })
  })
}
```

**核心算法：**
1. **`musicInfos` 是被 `shift()` 消费的队列**（原地修改调用方的数组 —— 传的是 `[...otherSource]` 副本，安全）
2. **`retryedSource` 保证每个 source 只试一次**
3. 三重过滤：`assertApiSupport(source)` → `getPlayQuality()` → `musicInfo.meta._qualitys[itemQuality]` 存在
4. 找到候选后 `onToggleSource(musicInfo)` 通知 UI 更新显示
5. 命中后**先查缓存**，未命中再请求
6. **请求失败递归重试下一首**；唯一例外：`err.message == requestMsg.tooManyRequests` 直接抛出（429 不重试）
7. 全部试完抛 `window.i18n.t('toggle_source_failed')`

**`onToggleSource` 的消费者在播放器里**（`src/renderer/core/player/action.ts:96-108`）：
```ts
  return (toggleMusicInfo ? getMusicUrl({
    musicInfo: toggleMusicInfo,
    isRefresh,
    allowToggleSource: false,
  }) : Promise.reject(new Error('not found'))).catch(async() => {
    return getMusicUrl({
      musicInfo,
      isRefresh,
      onToggleSource(mInfo) {
        if (diffCurrentMusicInfo(musicInfo)) return
        setAllStatus(window.i18n.t('toggle_source_try'))
      },
    })
  }).then(url => {
```
即：**先试 `meta.toggleMusicInfo`（用户手动换过的源，`allowToggleSource: false` 不再级联）→ 失败再走完整换源链路**。

**`meta.toggleMusicInfo` 是「换源结果」的持久化标记**，会被写进列表存储。

#### B. 用户手动换源（UI 弹窗改列表）

`src/renderer/views/List/MusicList/useMusicToggle.js:22-49`：

```js
  const toggleSource = async(toggleMusicInfo) => {
    const oldId = musicInfo.value.id
    let oldIdx = list.value.findIndex(m => m.id == oldId)
    if (oldIdx < 0) {
      isShowMusicToggleModal.value = false
      await addListMusics(props.listId, [toggleMusicInfo])
      return
    }
    const id = toggleMusicInfo.id
    const index = list.value.findIndex(m => m.id == id)
    const removeIds = [oldId]
    if (index > -1) {
      if (!await dialog.confirm({
        message: t('music_toggle_duplicate_tip'),
        ...
      })) return
      removeIds.push(id)
    }
    isShowMusicToggleModal.value = false
    await removeListMusics({ listId: props.listId, ids: removeIds })
    await addListMusics(props.listId, [toggleMusicInfo], 'bottom')
    if (index != -1 && index < oldIdx) oldIdx--
    await updateListMusicsPosition({ listId: props.listId, ids: [id], position: oldIdx })
    if (playMusicInfo.listId == props.listId && playMusicInfo.musicInfo?.id == oldId) {
      playListById(props.listId, toggleMusicInfo.id)
    }
  }
```

**语义：** 从列表删除旧 id → 在**末尾**添加新 id → 再把新 id 移动到旧 id 的位置。若新 id 已在列表中则弹窗确认并一并删除（先删再插）。若正在播放这首歌则重新触发播放。

换源弹窗的候选列表来自各源搜索结果，见 `views/List/MusicList/components/MusicToggleModal.vue`（`:4` 有 `base-tab` 切源，`:7-27` 每项显示 `item.name` / `item.singer` / `item.meta.albumName` / `item.interval`）。

---

## 5. 搜索结果展示所需字段

### 5.1 列表组件（权威）

搜索结果使用 `src/renderer/components/material/OnlineList/index.vue`（被 `views/Search/MusicList/index.vue:3-14` 引用）。

**表头**（`OnlineList/index.vue:5-25`）：
```html
<th class="num" style="width: 5%;">#</th>
<th class="nobreak">{{ $t('music_name') }}</th>
<th class="nobreak" style="width: 22%;">{{ $t('music_singer') }}</th>
<th class="nobreak" style="width: 22%;">{{ $t('music_album') }}</th>
<th class="nobreak" style="width: 9%;">{{ $t('music_time') }}</th>
<th class="nobreak" style="width: 16%;">{{ $t('action') }}</th>
```

**行渲染**（`OnlineList/index.vue:34-47`，逐字）：
```html
<div class="list-item-cell no-select num" style="flex: 0 0 5%;" @click.stop>{{ index + 1 }}</div>
<div class="list-item-cell auto name">
  <span class="select name" :aria-label="item.name">{{ item.name }}</span>
  <span v-if="item.meta._qualitys.flac24bit" class="no-select badge badge-theme-primary">{{ $t('tag__lossless_24bit') }}</span>
  <span v-else-if="item.meta._qualitys.ape || item.meta._qualitys.flac || item.meta._qualitys.wav" class="no-select badge badge-theme-primary">{{ $t('tag__lossless') }}</span>
  <span v-else-if="item.meta._qualitys['320k']" class="no-select badge badge-theme-secondary">{{ $t('tag__high_quality') }}</span>
  <span v-if="sourceTag" class="no-select badge badge-theme-tertiary">{{ item.source }}</span>
</div>
<div class="list-item-cell" style="flex: 0 0 22%;"><span class="select" :aria-label="item.singer">{{ item.singer }}</span></div>
<div class="list-item-cell" style="flex: 0 0 22%;"><span class="select" :aria-label="item.meta.albumName">{{ item.meta.albumName }}</span></div>
<div class="list-item-cell" style="flex: 0 0 9%;"><span class="no-select">{{ item.interval || '--/--' }}</span></div>
```

### 5.2 展示字段结论表

| UI 列 | 数据来源字段 | 备注 |
|---|---|---|
| `#` 序号 | `index + 1` | 计算值 |
| **歌曲名** | `item.name` | i18n key `music_name` |
| 音质角标 | `item.meta._qualitys.{flac24bit / ape / flac / wav / '320k'}` | **互斥三选一**，优先级：24bit 无损 > 无损 > 320k。`'320k'` 必须用**方括号**访问（非合法标识符） |
| **来源角标** | `item.source` | **仅在 `sourceTag` 为 true 时显示**，显示的是**裸 source id**（`"kw"`），不是显示名。`sourceTag` 由父组件传：`views/Search/MusicList/index.vue:10` → `:source-tag="sourceId == 'all'"`。**只有聚合搜索才显示来源** |
| **歌手/作者** | `item.singer` | i18n key `music_singer` |
| **专辑名** | `item.meta.albumName` | i18n key `music_album`。**注意不是 `item.albumName`** |
| **时长** | `item.interval \|\| '--/--'` | i18n key `music_time` |
| 操作 | — | i18n key `action`；按钮禁用取决于 `assertApiSupport(item.source)` |

**未展示但存在**：`meta.albumId`、`meta.picUrl`、`meta.songId`、`meta.qualitys`（数组）、`meta.hash`、`meta.strMediaMid`、`meta.copyrightId`、`item.id`。

> ⚠️ **`albumId` 在搜索结果中确实被解析并存储，但从不显示。** 它在取封面（`tx/index.js:26` 用 `songInfo.albumId`）、打开详情页（`kg/index.js:31`）、换源匹配（`isEqualsAlbum` 用 `albumName` 而非 id）中起作用。

### 5.3 我的列表的展示（对比）

`src/renderer/views/List/MusicList/index.vue:44-52`：

```html
<div class="list-item-cell auto name" :aria-label="item.name">
  <span class="select name">{{ item.name }}</span>
  <span v-if="isShowSource" class="no-select label-source">{{ item.source }}</span>
</div>
<div class="list-item-cell" style="flex: 0 0 22%;"><span class="select" :aria-label="item.singer">{{ item.singer }}</span></div>
<div class="list-item-cell" style="flex: 0 0 22%;"><span class="select" :aria-label="item.meta.albumName">{{ item.meta.albumName }}</span></div>
<div class="list-item-cell" style="flex: 0 0 9%;"><span class="no-select">{{ item.interval || '--/--' }}</span></div>
```

差异：
- **来源用 `<span class="label-source">` 而非 badge**，可见性由 `appSetting['list.isShowSource']` 控制（`useListInfo.js:36`），默认 `true`（`defaultSetting.ts:107`）
- **不显示音质角标**
- **`isShowSource` 的文案是「是否显示歌曲来源（仅对我的列表有效）」**（`types/app_setting.d.ts:478-481`）

### 5.4 换源弹窗的展示

`views/List/MusicList/components/MusicToggleModal.vue:10-16`：
```html
<h3 :class="$style.text" :aria-label="`${item.name} - ${item.singer}`">{{ item.name }}</h3>
<h3 v-if="item.meta.albumName" :class="[$style.text, $style.albumName]" :aria-label="item.meta.albumName">
  {{ item.singer }}
  <span v-if="item.meta.albumName"> / {{ item.meta.albumName }}</span>
</h3>
...
<div :class="$style.label">{{ item.interval }}</div>
```
展示 `name` + `singer` + `meta.albumName` + `interval`，格式为 `歌手 / 专辑名`。

---

## 6. 附录

### 6.1 `.lxmc` 文件格式 —— CLI 导入导出的关键

**`.lxmc` 是 gzip 压缩的 JSON；`.json` 是明文 JSON。** `src/common/utils/nodejs.ts:143-177`（逐字）：

```ts
/**
 * 保存lx配置文件
 * @param path 保存路径
 * @param data 数据
 */
export const saveLxConfigFile = async(path: string, data: any) => {
  if (!path.endsWith('.lxmc')) path += '.lxmc'
  fs.writeFile(path, await gzipData(JSON.stringify(data)), 'binary', err => {
    console.log(err)
  })
}

/**
 * 读取lx配置文件
 * @param path 文件路径
 * @returns 数据
 */
export const readLxConfigFile = async(path: string): Promise<any> => {
  let isJSON = path.endsWith('.json')
  let data: string | Buffer = await fs.promises.readFile(path, isJSON ? 'utf8' : 'binary')
  if (!data) return data
  if (!isJSON) data = await gunzipData(Buffer.from(data, 'binary'))
  data = JSON.parse(data)

  // 修复v1.14.0出现的导出数据被序列化两次的问题
  if (typeof data != 'object') {
    try {
      data = JSON.parse(data)
    } catch (err) {
      return data
    }
  }

  return data
}
```

**判定逻辑：仅看后缀名。** 非 `.json` 一律按 gzip 处理。

### 6.2 全部 JSON `type` 枚举与 schema

| `type` | 结构 | 导出位置 | 导入位置 |
|---|---|---|---|
| `allData` | `{ type, defaultList?: {list}, playList: [...], setting: {...} }` | 旧版 | `SettingBackup.vue:141-146` |
| **`allData_v2`** | `{ type, setting: AppSetting, playList: GetListFullResult[] }` | `SettingBackup.vue:176-180` | `SettingBackup.vue:147-150` |
| `setting` | `{ type, data: AppSetting }` | 旧版 | `SettingBackup.vue:219-221` |
| `setting_v2` | `{ type: 'setting_v2', data: AppSetting }` | `SettingBackup.vue:194-197` | `SettingBackup.vue:222-224` |
| `defautlList` | `{ type, data: {list} }`（**注意源码里的拼写错误 `defautl`**） | 旧版 | `SettingBackup.vue:269-271` |
| `playList` | `{ type, data: [...] }` | 旧版 | `SettingBackup.vue:272-274` |
| **`playList_v2`** | `{ type: 'playList_v2', data: GetListFullResult[] }` | `SettingBackup.vue:242-248` | `SettingBackup.vue:275-277` |
| `playListPart` | `{ type, data: {id, name, list} }` | 旧版 | `useShare.ts:48-51` |
| **`playListPart_v2`** | `{ type: 'playListPart_v2', data: MyListInfoPart['data'] }` | `useShare.ts:22-25` | `useShare.ts:52-55` |

**类型声明**（`src/common/types/config_files.d.ts:1-9`，逐字）：
```ts
declare namespace LX {
  namespace ConfigFile {
    interface MyListInfoPart {
      type: 'playListPart_v2'
      data: LX.List.MyDefaultListInfoFull | LX.List.MyLoveListInfoFull | LX.List.UserListInfoFull
    }
  }
}
```

### 6.3 导出列表的精确生成代码

`src/renderer/views/Setting/components/SettingBackup.vue:58-68`（逐字）——**这就是导出 schema 的定义**：

```js
    const getAllLists = async() => {
      const lists = []
      lists.push(await getListMusics(defaultList.id).then(musics => ({ ...defaultList, list: toRaw(musics) })))
      lists.push(await getListMusics(loveList.id).then(musics => ({ ...loveList, list: toRaw(musics) })))

      for await (const list of userLists) {
        lists.push(await getListMusics(list.id).then(musics => ({ ...toRaw(list), list: toRaw(musics) })))
      }

      return lists
    }
```

**⚠️ 导出数组的第 0 项永远是 `default`，第 1 项永远是 `love`，其余是用户列表（按 UI 顺序）。** 导入端依赖这个约定（`SettingBackup.vue:91-93,116-118`）：
```js
      const defaultList = allLists.shift().list
      const loveList = allLists.shift().list
      await overwriteListFull({ defaultList, loveList, userList: allLists })
```

**`playList_v2` 完整 schema 示例：**
```json
{
  "type": "playList_v2",
  "data": [
    {
      "id": "default",
      "name": "list__name_default",
      "list": [
        {
          "id": "kw_62355680",
          "name": "突然的自我",
          "singer": "伍佰",
          "source": "kw",
          "interval": "03:55",
          "meta": {
            "songId": "62355680",
            "albumName": "突然的自我",
            "picUrl": null,
            "qualitys": [{ "type": "320k", "size": "9.12M" }],
            "_qualitys": { "320k": { "size": "9.12M" } },
            "albumId": "123456"
          }
        }
      ]
    },
    {
      "id": "love",
      "name": "list__name_love",
      "list": []
    },
    {
      "id": "userlist_1712345678901",
      "name": "我的歌单",
      "source": "kg",
      "sourceListId": "3ac9f1e0...",
      "locationUpdateTime": 1712345678901,
      "list": [ /* MusicInfo[] */ ]
    }
  ]
}
```

### 6.4 `playListPart_v2` 的导入行为（CLI 需要知道）

`src/renderer/views/List/MyList/useShare.ts:47-102` 关键逻辑（逐字节选）：

```js
      switch (configData.type) {
        case 'playListPart':
          listData = configData.data
          listData.list = filterMusicList(listData.list.map(m => toNewMusicInfo(m)))
          break
        case 'playListPart_v2':
          listData = configData.data
          listData.list = filterMusicList(listData.list).map(m => fixNewMusicInfoQuality(m))
          break
        default:
          showImportTip(configData.type)
          return
      }

      const targetList = [defaultList, loveList, ...userLists].find(l => l.id == listData.id)
      if (targetList) {
        const confirm = await dialog.confirm({ ... })
        if (confirm) {
          listData.name = targetList.name
          switch (listData.id) {
            case defaultList.id:
            case loveList.id:
              break
            default:
              void updateUserList([{ name: listData.name, id: listData.id, source: ..., sourceListId: ..., locationUpdateTime: ... }])
              break
          }
          void overwriteListMusics({ listId: listData.id, musicInfos: listData.list.map(m => fixNewMusicInfoQuality(m)) })
          return
        }
        listData.id += `__${Date.now()}`
      }
      void createUserList({
        position: index,
        name: listData.name,
        id: listData.id,
        source: listData.source,
        sourceListId: listData.sourceListId,
      })
      void addListMusics(listData.id, listData.list.map(m => fixNewMusicInfoQuality(m)))
```

**规则：**
- **id 冲突** → 弹窗确认；确认则**覆盖**（保留本地 name，对 default/love 不改元数据）；**取消则 id 追加 `__${Date.now()}` 后作为新列表创建**
- **id 不冲突** → 直接 `createUserList` + `addListMusics`（**追加合并**，不是覆盖）
- 导入时对 v2 数据做 `fixNewMusicInfoQuality`（`flac32bit`→`flac24bit` 迁移）
- 歌单内**重复 id 会被过滤**：`filterMusicList`（`tools.ts:126-134`）：
  ```ts
  export const filterMusicList = <T extends LX.Music.MusicInfo>(list: T[]): T[] => {
    const ids = new Set<string>()
    return list.filter(s => {
      if (!s.id || ids.has(s.id) || !s.name) return false
      if (s.singer == null) s.singer = ''
      ids.add(s.id)
      return true
    })
  }
  ```
  **⚠️ 无 `id` 或无名 `name` 的条目会被静默丢弃；`singer` 为 null 会被改写为 `''`。**

### 6.5 导出 TXT / CSV 格式

`src/renderer/worker/main/list.ts:326-367`：

**TXT**（`isMerge=false` 时每列表一个 `lx_list_{name}.txt`；`true` 时合并为一个文件、列表间空行分隔）：
```js
list.list.map(m => `${m.name}  ${m.singer}  ${m.meta.albumName ?? ''}`).join('\n')
```
**两个空格**分隔，编码 UTF-8 with BOM。

**CSV**：同字段顺序，表头由调用方传入：
```js
// SettingBackup.vue:336
`${t('music_name')},${t('music_singer')},${t('music_album')}\n`
```
CSV 转义（`list.ts:353-358`）：`"` → `""`；含 `,` 的字段用 `"` 包裹。UTF-8 with BOM。

### 6.6 数据库完整 Schema（本次相关表）

`src/main/worker/dbService/tables.ts`，`DB_VERSION = '2'`（`:231`）：

```sql
-- :120-127
CREATE TABLE "db_info" (
  "id" INTEGER NOT NULL UNIQUE,
  "field_name" TEXT,
  "field_value" TEXT,
  PRIMARY KEY("id" AUTOINCREMENT)
);

-- :128-138  —— 用户列表元数据（不含 default/love/temp）
CREATE TABLE "my_list" (
  "id" TEXT NOT NULL, "name" TEXT NOT NULL, "source" TEXT,
  "sourceListId" TEXT, "position" INTEGER NOT NULL, "locationUpdateTime" INTEGER,
  PRIMARY KEY("id")
);

-- :139-150  —— 歌曲行（meta 是 JSON 字符串）
CREATE TABLE "my_list_music_info" (
  "id" TEXT NOT NULL, "listId" TEXT NOT NULL, "name" TEXT NOT NULL,
  "singer" TEXT NOT NULL, "source" TEXT NOT NULL, "interval" TEXT, "meta" TEXT NOT NULL,
  UNIQUE("id","listId")
);

-- :157-163  —— 排序独立表
CREATE TABLE "my_list_music_info_order" (
  "listId" TEXT NOT NULL, "musicInfoId" TEXT NOT NULL, "order" INTEGER NOT NULL
);

-- :170-181  —— 「其他音源」（换源结果缓存，当前代码中读写均被注释掉）
CREATE TABLE "music_info_other_source" (
  "source_id" TEXT NOT NULL, "id" TEXT NOT NULL, "source" TEXT NOT NULL,
  "name" TEXT NOT NULL, "singer" TEXT NOT NULL, "meta" TEXT NOT NULL, "order" INTEGER NOT NULL,
  UNIQUE("source_id","id")
);

-- :188-196  —— 歌词缓存（按 id + source + type）
CREATE TABLE "lyric" (
  "id" TEXT NOT NULL, "source" TEXT NOT NULL, "type" TEXT NOT NULL, "text" TEXT NOT NULL
);

-- :197-202  —— 播放 URL 缓存
CREATE TABLE "music_url" (
  "id" TEXT NOT NULL, "url" TEXT NOT NULL
);

-- :203-220  —— 下载列表
CREATE TABLE "download_list" (
  "id" TEXT NOT NULL, "isComplate" INTEGER NOT NULL, "status" TEXT NOT NULL,
  "statusText" TEXT NOT NULL, "progress_downloaded" INTEGER NOT NULL,
  "progress_total" INTEGER NOT NULL, "url" TEXT, "quality" TEXT NOT NULL,
  "ext" TEXT NOT NULL, "fileName" TEXT NOT NULL, "filePath" TEXT NOT NULL,
  "musicInfo" TEXT NOT NULL, "position" INTEGER NOT NULL,
  PRIMARY KEY("id")
);

-- :221-227
CREATE TABLE "dislike_list" ("type" TEXT NOT NULL, "content" TEXT NOT NULL, "meta" TEXT);
```

**索引**：`my_list_music_info(id, listId)` 与 `my_list_music_info_order(listId, musicInfoId)`（`tables.ts:151-156,164-169`）。

**兼容性修复**（`dbHelper.ts:23-37`）：旧版把数字 id 当 TEXT 存导致追加 `.0`：
```ts
const idFixRxp = /\.0$/
export const queryAllUserList = () => {
  const list = createListQueryStatement().all() as LX.DBService.UserListInfo[]
  for (const info of list) {
    // 兼容v2.3.0之前版本插入数字类型的ID导致其意外在末尾追加 .0 的问题
    if (info.sourceListId?.endsWith?.('.0')) {
      info.sourceListId = info.sourceListId.replace(idFixRxp, '')
    }
  }
  return list
}
```

### 6.7 列表操作 IPC 名称（若 CLI 走 IPC 而非直接改 DB）

`src/common/ipcNames.ts:22-37`：
```ts
    list_data_overwire: 'list_data_overwire',
    list_get: 'list_get',
    list_add: 'list_add',
    list_remove: 'list_remove',
    list_update: 'list_update',
    list_update_position: 'list_update_position',
    list_music_get: 'list_music_get',
    list_music_add: 'list_music_add',
    list_music_move: 'list_music_move',
    list_music_remove: 'list_music_remove',
    list_music_update: 'list_music_update',
    list_music_update_position: 'list_music_update_position',
    list_music_overwrite: 'list_music_overwrite',
    list_music_clear: 'list_music_clear',
    list_music_check_exist: 'list_music_check_exist',
    list_music_get_list_ids: 'list_music_get_list_ids',
```
以及 `ipcNames.ts:128-131`：
```ts
    get_music_url: 'get_music_url',
    save_music_url: 'save_music_url',
    clear_music_url: 'clear_music_url',
    get_music_url_count: 'get_music_url_count',
```

**对应 payload 类型**（`src/common/types/list.d.ts:64-121`）已在本报告 §2 引用。

### 6.8 开放 API 服务（CLI 可直接利用的现成 HTTP 接口）

`src/main/modules/openApi/index.ts:87-211`。**这是 CLI 唯一无需逆向即可使用的官方 HTTP 通道。**

| 端点 | 方法 | 说明 |
|---|---|---|
| `/status?filter=a,b,c` | GET | 返回播放器状态 JSON 子集（`index.ts:49-54`） |
| `/lyric` | GET | 纯文本当前歌词 |
| `/lyric-all` | GET | `{lyric, tlyric, rlyric, lxlyric}` |
| `/play` `/pause` `/skip-next` `/skip-prev` | GET | 播放控制（`index.ts:145-156`） |
| `/seek?offset=秒` | GET | 校验 `0 <= offset <= duration`，否则 400 |
| `/collect` `/uncollect` | GET | 收藏/取消收藏 |
| `/volume?volume=0-100` | GET | 校验范围 |
| `/mute?mute=true\|false` | GET | 校验字面量 |
| `/subscribe-player-status?filter=` | GET | **SSE 流**，逐字段推送 |

默认过滤字段（`index.ts:32-41`）：
```ts
const defaultFilter = [
  'status', 'name', 'singer', 'albumName', 'lyricLineText',
  'duration', 'progress', 'playbackRate',
] satisfies SubscribeKeys[]
```
监听地址：`bindLan ? '0.0.0.0' : '127.0.0.1'`（`index.ts:281`），默认端口 `23330`（`defaultSetting.ts:149`）。
**⚠️ 该服务没有「搜索」「添加歌曲到列表」「取歌曲 URL」端点** —— 只能做播放控制与状态读取。

### 6.9 未验证 / 推测清单

| # | 条目 | 状态 |
|---|---|---|
| 1 | ~~`music_url` 表的 `id` 是否拼接了音质~~ | ✅ **已验证**：`id = ${musicInfo.id}_${quality}`（`utils/ipc.ts:643,654`）。见 §6.7 |
| 2 | `source_local` 的 i18n 显示名 | **未验证**：`src/lang/*.json` 中不存在该 key，推测 UI 显示裸字符串 `"local"` |
| 3 | deeplink 构造的 `sp_...` 伪 id 是否会持久化进列表 | **未验证**：`useMusicAction.js:184` 构造后立即走 `getOtherSource`，推测该临时对象被丢弃、只保留搜索结果 |
| 4 | `music_info_other_source` 表当前是否还有写入 | **推测无**：`core/music/utils.ts:69` 的 `saveOtherSourceFromStore` 调用被注释掉，但表仍存在。其 `source_id` 列语义**未验证** |
| 5 | `api-source-info.ts` 为空是否意味着**所有内置音源在 v2.12.5 中均不可用** | **强推测是**（`musicSdk.supportQuality` 为空对象 → `apiSource` 非 `user_api` 时 `getAPI` 抛 `Api is not found`）。但 `defaultSetting['common.apiSource'] = 'temp'` 且该 id 不在数组中，逻辑上必然走 `getAPI` 分支失败。需实际运行验证 |
| 6 | `musicSdk/index.js` 中 `sources.sources` 的 `name` 字段（'酷我音乐' 等）是否在任何 UI 中出现 | **推测否**：UI 一律走 `sourceNames`（i18n），该 `name` 字段疑似遗留 |
| 7 | ~~`versionChars` 的具体内容~~ | ✅ **已验证**：124 行、8 大类别，见 §4.5 第 7 点 |
| 8 | `lyric` 表的 `source`/`type` 列的实际取值组合，以及 `saveLyric` 的写入路径（`save_lyric_raw` / `save_lyric_edited` 是两个独立 IPC） | **部分验证**：类型声明为 `source: 'raw' \| 'edited'`、`type: 'lyric' \| keyof Omit<LyricInfo,'lyric'>`。**主进程写入实现未读** |
| 9 | 各源 `getMusicDetailPageUrl` 是否全部可用 | **未验证**：`kw`(`kw/index.js:93`)、`kg`(`kg/index.js:30`)、`tx`(`tx/index.js:28`)、`wy`(`wy/index.js:28`)、`mg`(`mg/index.js:27`)、`bd`(`bd/index.js:35`) 均已定义；`xm` 的已被注释（`xm.js:42-49`） |

---

## 7. CLI 实现检查清单（速查）

```
□ 歌曲 id 生成：source=='kg' ? `${songmid}_${hash}` : `${source}_${songmid}`
                  source=='local' ? 文件绝对路径
□ 永远从 musicInfo.source 读源，绝不从 id 拆分
□ singer 用 '、' 连接；interval 用 'mm:ss'（可 >59 分钟），空为 '--/--'
□ 所有源特有字段放 meta；meta 落库时 JSON.stringify
□ 音质判定用 meta._qualitys[q]（不是 meta.qualitys）
□ 源可用性判定：source=='local' || qualityList[source] != null
□ default / love 不查 my_list 表；名称是 i18n key
□ 导出数组顺序：[default, love, ...userList]
□ .lxmc = gzip(JSON)；.json = 明文
□ 聚合搜索：同 page 并发所有源 → 按 id 去重（先到先得）→ 按 similar() 降序
□ 单源搜索：不排序
□ 换源匹配：时长 ±5 秒硬门槛 → 三轮匹配 → 9 级排序
□ 取 URL 前 await window.lx.apiInitPromise[0]
□ 传给用户音源脚本的 musicInfo 是旧格式（toOldMusicInfo）
```

---

*报告生成时间：2026-10-12 · 基于 lx-music-desktop v2.12.5 源码静态分析*
