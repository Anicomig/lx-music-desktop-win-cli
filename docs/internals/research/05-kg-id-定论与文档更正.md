# 05 — `kg` 歌曲 id 形态：定论与两处文档更正

> 本文件终结三份调研报告中一致标注为【推断】的遗留问题，并**更正既有文档 `docs/db.md` 的错误说法**。
> 全部结论基于真实 DB 实测 + 源码定位。只读操作。
> 日期：2026-10-12

---

## 1. 定论：`kg` 歌曲 id 的规范形态是**无前缀**的

**唯一权威**：`src/common/utils/tools.ts:3-56`（`toNewMusicInfo`）

```ts
// :10  默认公式
const newInfo = { id: `${oldMusicInfo.source}_${oldMusicInfo.songmid}`, ... }
// :35-40  仅 kg 覆写 —— 顺序相反，且不带 source 前缀
switch (oldMusicInfo.source) {
  case 'kg':
    meta.hash = oldMusicInfo.hash
    meta.albumAudioId = oldMusicInfo.albumAudioId
    newInfo.id = oldMusicInfo.songmid + '_' + oldMusicInfo.hash
    break
```

grep 全源码：**不存在任何为 kg 添加 `kg_` 前缀的分支**。

**真实 DB 实测**（1892 行）：

| 形态 | 行数 |
|---|---:|
| `<songId>_<32位HEX>`（**规范，无前缀**） | **934** |
| `kg_<songId>_<32位HEX>`（异常变体） | 24 |

---

## 2. 更正既有文档：`docs/db.md` §4 的 kg 行是**错的**

`docs/db.md:417-430` 原文：

```
## 4. 歌曲 ID 格式
<source>_<songid> 加上可选的 <hash> 后缀
| kg | `kg_<audioid>[_<filehash>]` | `kg_244874231_E0AD93DC04412BE31404173A4B3120E4` |

**kg 的 hash 后缀**: LX 桌面有时会自动附加 <filehash> 后缀，这是 LX 自动换源后的产物。
我方写入时只用 `kg_<audioid>`(不带 hash)即可，后续 LX 启动会自动补全。
```

### 错在哪里

| # | 文档说法 | 实际 | 证据 |
|---|---|---|---|
| 1 | kg 格式为 `kg_<audioid>[_<hash>]` | **是 `<songId>_<hash>`，无 `kg_` 前缀** | `tools.ts:39`；934 vs 24 行 |
| 2 | "写入时只用 `kg_<audioid>`（不带 hash）即可" | 🔴 **照此写入会生成 LX 从不产生的 id**，且**不会"自动补全"**（无任何补全代码） | `toNewMusicInfo` 是唯一工厂 |
| 3 | "hash 后缀是 LX 自动换源后的产物" | 方向**说反了**：`<hash>` 是**规范形态的一部分**；带 `kg_` 前缀的才是异常变体 | 同上 |

> ⚠️ **实施阶段 2 必须以 `tools.ts:39` 为准，不能照抄 `docs/db.md` §4。**
> 建议同步修正 `docs/db.md`（属该文档的维护范围）。

---

## 3. `kg_` 异常变体（24 行）的成因：**运行时 `${source}_${id}` 二次拼接**

### 3.1 排除了"旧版遗留数据"假说（三份报告此前的【推断】）

| 检验 | 结果 | 结论 |
|---|---|---|
| 24 行是否有 `meta.hash`？ | **24/24 都有**，且与 id 中 hash **完全一致** | ❌ 不是缺 hash 的旧数据 |
| `meta` 键集是否与规范行不同？ | **完全相同**（7 个键全有） | ❌ 不是旧 schema |
| 这些 songId 是否也以规范形态存在？ | **0/24** | 它们是不同的歌，不是重复 |
| 所在歌单的 `locationUpdateTime` | **2026-08-12**（很近） | ❌ 不是历史遗留 |

### 3.2 真正成因：`${musicInfo.source}_${musicInfo.id}` 拼接【已核实源码】

`src/renderer/core/music/utils.ts:44`：

```js
key = `${musicInfo.source}_${musicInfo.id}`
```

当 `musicInfo` 是**已经归一化过的 kg 曲目**（其 `id` 已是 `<songId>_<hash>`）时，
该表达式产出 **`kg_<songId>_<hash>`** —— 即**二次加前缀**。

这与 `core/music/utils.ts:35` 的 `local_${musicInfo.id}` 是同一类拼接。

**佐证**：`core/music/utils.ts:62` 用 `otherSource.map(toNewMusicInfo)` 把换源结果转为
`MusicInfoOnline[]` 并缓存；`:320/:404/:503` 的 `getOtherSource(...)` → `updateListMusics([...otherSource])`
把换源结果**写回歌单**。该路径正是"换源后写入"的通道。

**对元数据指纹的印证**：24 行的 `picUrl` 为**空串 `""`**（规范行为正常 URL），
`qualitys` 恒为 4 档（23/24 是 `128k+320k+flac+flac24bit`），而规范行形态分散
（434× 4档 / 353× 3档 / 116× 2档 / 27× 1档）—— 说明是**另一条产出路径**，
与"换源写回"高度吻合。

> 【推断】剩余部分：具体是 `utils.ts:44` 的 key 被当作 id 写回，还是 `updateListMusics`
> 链路里另有 `${source}_${id}` 拼接点。已定位到可能位置，实施阶段可用一次真实"换源+写回"操作复核。

### 3.3 对 CLI 的确定含义（不依赖成因）

1. **读取必须容忍两种形态**：解析 kg id 时，先剥可选 `kg_` 前缀，再按 `<songId>_<hash>` 取
2. **写入一律用规范形态**（无 `kg_` 前缀）—— 与 934/958 = **97.5%** 的现存数据一致
3. **绝不能按 `id` 前缀反推 source**：kg 有 934 行无前缀；`local` 的 id 是文件路径（含 `_`，禁止按 `_` 切分）
4. 该 24 行全部位于 `tx_01f8d8ef...`（塞壬唱片）歌单，是**唯一混合两种形态**的歌单

---

## 4. 附带更正：歌手分隔符的"双重口径"

- **DB 存储口径**：多歌手用 **`、`（U+3001）** 分隔（497 行）；`;`（217 行）与 `&`（6 行）**是歌手名的一部分**
  - 反例：`Raven & Kreyn、RudeLies、Nino Lucarelli` = **3** 个歌手
- **LX 匹配口径**：`musicSdk/index.js:80` 的换源匹配用
  `/、|&|;|；|\/|,|，|\|/` **全部**作为分隔符来比较

**含义**：CLI 做**展示/拆分**时应只按 `、`；做**模糊匹配/去重**时应照 LX 用全部分隔符。
两种口径**都要实现**，且不可混用。这一点此前未被任何报告指出。

---

## 5. 未验证项

| # | 项 | 状态 |
|---|---|---|
| 1 | `utils.ts:44` 的 key 是否就是被写回 DB 的那个 id | 【推断】高度可能，待真机复核 |
| 2 | `kg_` 变体是否只在"换源写回"时产生 | 【推断】 |
| 3 | `docs/db.md` 其余章节是否还有类似错误 | 未全面复核（已发现 §4；§3.8 引用的 `siren_repair.py` 存在） |
