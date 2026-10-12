# 命名约定与架构术语

> **本文档解决一个真实存在的混淆**：中文"源"被用于指代两个完全不同的东西。
> 所有代码、文档、CLI 输出都必须遵守本约定。
> 日期：2026-10-12

---

## 1. 三层概念（务必区分）

| 层 | 代码位置 | 是什么 | 权威来源 |
|---|---|---|---|
| **① 平台元数据接口** | `sources/` | 直连各平台**官方域名**的查询客户端 | `musicSdk/{kg,kw,tx,mg,wy}/*.js` |
| **② JS 音源脚本** | `scripts/` | 第三方作者的 JS 插件，**只用于换播放地址** | `pdone/lx-music-source` |
| **③ 平台标识** | 贯穿全局 | `kg`/`kw`/`tx`/`wy`/`mg` 字符串 | `musicSdk/index.js:12-38` |

### 1.1 ① 平台元数据接口（"查"）

`musicSdk/` 下每个平台目录里有**该平台官方接口**的实现，例如：

```js
// musicSdk/kg/musicSearch.js:12
//   → 酷狗官方域名
http://songsearch.kugou.com/song_search_v2?platform=AndroidFilter&...

// musicSdk/kg/util.js:12-24  → 酷狗官方签名算法
const signatureParams = (params, platform='android', body='') => {
  let keyparam = 'OIlwieks28dk2k092lksi2UIkp'   // 酷狗公开的 app key
  ...
  return toMD5(sign_params)
}
```

能力范围：`musicSearch` / `album` / `songList` / `leaderboard` / `comment` /
`lyric` / `pic` / `singer` / `hotSearch` / `tipSearch` / `musicInfo`。

**不包含**：取播放 URL（见 §2）。

### 1.2 ② JS 音源脚本（"播"）

**唯一职责**：给一首歌的标识 + 音质 → **返回一个可播放的 URL 字符串**。

```js
// preload.js:37-45 —— LX 硬编码的动作白名单
const supportActions = {
  kw: ['musicUrl'], kg: ['musicUrl'], tx: ['musicUrl'],
  wy: ['musicUrl'], mg: ['musicUrl'], xm: ['musicUrl'],
  local: ['musicUrl', 'lyric', 'pic'],
}
```

脚本声明的 `search` / `musicSearch` 等动作会被**静默丢弃**（不是脚本作者不写，是 LX 不给）。

### 1.3 ③ 平台标识

`kg` `kw` `tx` `wy` `mg`（另有效能受限的 `local`）。
显示名走 i18n（`zh-cn.json:629-635`）：**酷狗音乐 / 酷我音乐 / 企鹅音乐 / 网易音乐 / 咪咕音乐**。

---

## 2. 播放能力的唯一来源（重要）

```js
// musicSdk/api-source.js:33-38 —— "取播放 URL"的分派器
const apis = source => {
  if (/^user_api/.test(apiSource.value)) return userApi.apis[source]  // ← JS 音源脚本
  let api = getAPI(source)
  if (api) return api
  throw new Error('Api is not found')                                  // ← 否则直接抛错
}
```

而 `apiList` 的填充来源是**空的**：

```js
// api-source.js:11-29
const allApi = { /* 全部被注释掉 */ }
const apiList = {}
for (const api of apiSourceInfo) { ... }   // apiSourceInfo 也是空数组
```

**结论**：v2.12.5 中
* 内置播放 API 已**全部停用**
* **不装 JS 音源脚本 → 所有在线歌都搜得到，但一首也播不了**

验证：`store/utils.ts:14-16`
```js
export const assertApiSupport = (source) =>
  source == 'local' || qualityList.value[source] != null
```

---

## 3. 命名硬规则

### 3.1 禁止事项

| ❌ 禁止 | ✅ 正确 | 原因 |
|---|---|---|
| 在 `sources/` 里出现脚本名（`flower`/`sixyin`） | 只出现 `kg`/`kw`/… | ① 不认识 ② |
| 让 `scripts/` 去查歌 | 查询交给 `sources/` | ② 没有查询能力 |
| 用 "源" 单指某一层 | 明说"**平台源**"或"**音源脚本**" | 消除歧义 |
| 输出 `source: "Flower"` | `source: "kg"` + `sourceLabel: "酷狗音乐"` | 用户明确要求 |
| 把 `musicSdk` 叫成"内置源" | 叫"**平台元数据接口**"或 `sources/` | 与②区分 |

### 3.2 CLI 输出字段约定

```json
{
  "source": "kg",              // 平台标识（③）
  "sourceLabel": "酷狗音乐",    // 显示名（读 common.sourceNameType）
  "origin": "musicSdk"         // 数据来自 ①（便于调试/溯源）
}
```

音源脚本相关的命令单独命名，**不出现在歌曲查询结果里**：

```
lx script list        # 列出已装 JS 音源脚本（②）
lx script update ...
```

### 3.3 代码内命名

```python
# sources/    ①  平台元数据源
class KgSource(SourceBase)          # 一个平台一个类
PLATFORMS = ("kg", "kw", "tx", "mg", "wy")

# scripts/    ②  JS 音源脚本管理
class ScriptStore                   # user_api.json 读写
class ScriptService                 # install/update/list/remove

# 词表
platform  = ③ 的平台标识
source    = ① 的查询实现（对外暴露给 agent 时等于 platform）
script    = ② 的 JS 插件 —— 不要叫它 "source"
```

---

## 4. 各层能力对照（给 CLI 设计用）

| 能力 | ① 平台元数据接口 | ② JS 音源脚本 | Open API | Scheme URL | 直接写 DB |
|---|---|---|---|---|---|
| 搜索歌曲 | ✅ | ❌ | ❌ | ⚠️ 仅 GUI 内 | ❌ |
| 专辑/歌单/歌词/评论/排行榜 | ✅ | ❌ | ❌ | ⚠️ 打开歌单 | ❌ |
| 取播放 URL | ❌ | ✅ **唯一** | ❌ | ❌ | ❌ |
| 播放指定歌曲 | ❌ | ❌ | ❌ | ✅ `music/play` | ❌ |
| 搜索并播放 | ❌ | ❌ | ❌ | ✅ `music/searchPlay` | ❌ |
| 播放/暂停/音量/收藏当前曲 | ❌ | ❌ | ✅ | ✅ | ❌ |
| 读当前状态/歌词 | ❌ | ❌ | ✅ | ❌ | ❌ |
| 歌单增删改 | ❌ | ❌ | ❌ | ❌ | ✅ |
| 收藏**任意**曲 | ❌ | ❌ | ❌ | ❌ | ✅（写 `love`） |

> 参考：`LX-CLI-project/research/06-官方文档核对-openapi与scheme.md` §5.7

---

## 5. 本项目采用的方案（已与用户确认）

**方案 A**：搜索 CLI 自己做，播放交给 LX。

```
lx search "yorushika"            → ① sources/（平台元数据接口）→ 返回带 id 的歌曲列表
lx playlist add --from-search …  → 直接写 DB
lx player play-song <id>         → Scheme URL（lxmusic://music/play）
                                    → LX 自己去调 ② JS 音源脚本取 URL 并播放
```

**CLI 不自己执行 ② 的 JS 脚本**（因此 `scripts/` 只做安装/更新/列表/删除）。

理由：② 硬依赖 Electron（`contextBridge` / `webFrame` / `needle`），脱离 Electron 原生跑不了；
且没必要 —— 播放交给 LX 自己更稳。
