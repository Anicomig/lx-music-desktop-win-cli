# 01b — 桌面数据模型：独立复核报告

> 本文件是 `./01-desktop-data-model.md` 的**独立交叉复核**（由并行第二路调研产出，未覆盖原文件）。
> 目的：对关键结论做二次独立验证，并记录**两处对原报告/我方观测的更正**。
> 日期：2026-10-12 · 来源源码：`lx-music-desktop-2.12.5`

---

## 1. 交叉复核结论表

| # | 主题 | 结论 | 依据 |
|---|---|---|---|
| 1 | id 唯一工厂 `toNewMusicInfo` | **AGREE** | `src/common/utils/tools.ts:3-56`；默认 `${source}_${songmid}`（`:10`），**仅 kg 覆写**（`:39`） |
| 2 | kg `/collect`「无参数」 | **更正补充**（见 §3） | `openApi/index.ts:167-172` |
| 3 | Open API 端点集合 | **AGREE** | 仅 13 个端点；default → `401 'Forbidden'`（`:205-208`） |
| 4 | 源显示名前缀选择 | **AGREE + 补充**（见 §4） | `store/index.ts:86-88`、`defaultSetting.ts:15`、`zh-cn.json:620-635` |
| 5 | `.lxmc` = gzip JSON | **AGREE** | `src/common/utils/nodejs.ts:143-177`（非 `.json` 后缀一律 gunzip） |
| 6 | `meta` 为唯一逃逸口、DB 单列 JSON | **AGREE** | `common/types/music.d.ts:40-47`、`dbService/modules/list/index.ts:28-37` |
| 7 | `default`/`love` 虚拟列表 | **AGREE** | 无 `my_list` 行；名称存 i18n key |
| 8 | 音质判定用 `_qualitys` 字典 | **AGREE** | `qualitys` 数组仅供 UI 角标 |
| 9 | 聚合搜索跨源混排、单源不排序 | **AGREE** | `store/search/music/action.ts:87-126` |

---

## 2. 逐源 id 推导（已核到 SDK 行号）

| source | `songmid` 来源 | 最终 `id` 形态 | 我方实测对照 |
|---|---|---|---|
| `kg` | `rawData.Audioid`（`musicSdk/kg/musicSearch.js:55`） | **`<Audioid>_<FileHash>`（无前缀）** | ✅ 与真实 DB 934 行一致 |
| `kw` | `MUSICRID.replace('MUSIC_','')`（`kw/musicSearch.js:33,87`） | `kw_<数字>` | ✅ 301 行 |
| `tx` | `item.mid`（`tx/musicSearch.js:118`）**不是数字 songId** | `tx_<字母数字MID>` | ✅ 10 行（12 位） |
| `wy` | `item.id`（`wy/musicSearch.js:85`） | `wy_<数字>` | ✅ 53 行 |
| `mg` | `data.songId`（`mg/musicSearch.js:181`）**不是 copyrightId** | `mg_<songId>` | ✅ 5 行 |
| `bd` | `item.song_id`（`bd/musicSearch.js:55`） | `bd_<id>`，但 **bd 未注册**（`musicSdk/index.js:38-41` 注释掉） | — CLI 亦无 |
| `local` | `path`（`renderer/utils/music.ts:83` `id: path`） | **绝对路径，无前缀** | ✅ 565 行 |

> 与真实 DB 1892 行统计完全吻合，说明推导链正确。

---

## 3. 更正 1：`kg_<songId>_<hash>` 变体的来源【推断】

**我方在真实 DB 观测到 24 行** `kg_<songId>_<hash>` 形态（100% 位于 `tx_01f8d8ef9ba89ef43cb1c28c289d2a9f` 歌单内）。

**但 v2.12.5 的正常代码路径不产生该形态**：`tools.ts:39` 对 `case 'kg'` **无条件覆写** `newInfo.id = songmid + '_' + hash`，**不存在产生 `kg_` 前缀的分支**。

**最可能成因【推断】**：旧版"扁平 id"遗留数据 + **`playListPart_v2` 导入不重算 id**
（`useShare.ts:52-55`；对比 v1 的 `playListPart` 分支会调用 `toNewMusicInfo` 重算）。

**对 CLI 的确定含义**（不依赖成因）：
- **两种形态都必须能读**（容错解析），但**新写入一律用规范形态**（kg 为裸 `<songId>_<hash>`）
- 该歌单是**唯一混合两种形态**的歌单 → 读取层必须逐行看 `id`，不能按歌单推断格式

> ⚠️ 成因未验证；`playListPart_v2` 的 id 处理路径建议在实施阶段 2 时用源码再确认一次。

---

## 4. 更正 2：Open API 的 `/collect` / `/uncollect` 不接受歌曲参数

`src/main/modules/openApi/index.ts:167-172`：

```ts
case '/collect':
  sendTaskbarButtonClick('collect')
  break
case '/uncollect':
  sendTaskbarButtonClick('unCollect')
  break
```

**没有 `musicInfo`/`id` 参数** —— 只能作用于**当前正在播放的歌曲**。

**对 AI 驱动 CLI 的后果（重要）**：
- 无法"查询到某首歌 → 通过 Open API 收藏它"
- 想收藏任意歌曲只有两条路：
  1. 先让它成为当前播放曲（CLI 无"播放指定歌曲"能力 → 需 GUI 或 DB 侧操作）
  2. **直接写 DB** 的 `love` 列表（`my_list_music_info` + order 表）
- ⇒ **"收藏任意歌曲"必须走 DB 写入路径**，不能用 Open API。这一点必须写进 CLI 的能力边界文档。

同理，其它 Open API 写端点（`/play` `/pause` `/seek` `/volume` `/mute` `/skip-*`）都是**作用于当前播放器状态**，不接受"目标歌曲"参数。

---

## 5. 更正 3：`source_tx` 显示名是「企鹅音乐」而非「QQ音乐」

- i18n：`zh-cn.json:633` → `"source_tx": "企鹅音乐"`
- 但 `renderer/utils/musicSdk/index.js:23` 有硬编码 `'QQ音乐'`
- **两者不同**；UI 走 i18n（`store/index.ts:86-88` 决定前缀），**硬编码名未被 UI 使用**

**CLI 含义**：显示名应**照 i18n**（`企鹅音乐`），不要照 SDK 里的硬编码字符串。

另：`source_local` **不存在于 `zh-cn.json`** → UI 对 local 的显示推测为裸 `"local"`【未验证】。
CLI 建议对 local 自行显示为「本地音乐」并在文档中固定，避免随 LX 版本变动。

---

## 6. 本次复核新增的可用结论

1. **默认 `sourceNameType` 是 `'alias'`**（`defaultSetting.ts:15`），而**本机实际是 `'real'`**
   → CLI 若输出显示名，应**读 `common.sourceNameType` 决定用 `source_*` 还是 `source_alias_*`**，
   不要硬编码一套；或同时输出 `source`（id）+ 显示名两个字段。
2. **bd 确实未注册**（`musicSdk/index.js:38-41` 注释掉）→ 与 CLI 现状（无 bd）一致，
   补 bd 的价值低于其它项（印证 `02-改进计划.md` 决策点 5 的"建议暂缓"）。

---

## 7. 未验证项（本报告）

| # | 项 | 状态 |
|---|---|---|
| 1 | `kg_<songId>_<hash>` 24 行的确切成因 | 【推断】旧数据 + `playListPart_v2` 不重算 |
| 2 | `playListPart_v2` 导入是否**一律**不重算 id | 未逐分支确认 |
| 3 | local 在 UI 的实际显示文案 | 【未验证】推测裸 `"local"` |
| 4 | 各音源脚本实际支持的平台 | 正文混淆，无法静态提取（需运行时验证） |
