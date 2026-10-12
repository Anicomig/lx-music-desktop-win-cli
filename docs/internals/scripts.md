# 音源脚本（scripts/）

> ② 层：管理 `pdone/lx-music-source` 那类 **JS 音源插件**。
> 只做**安装/更新/列表/删除**，**不执行脚本**。

---

## 1. 它是什么

| | 说明 |
|---|---|
| **输入** | 一首歌的标识 + 音质（`{source, action:'musicUrl', info:{musicInfo, type}}`） |
| **输出** | **一个播放 URL 字符串** |
| **不做** | 搜索、专辑、歌单、排行榜 |

由 LX 硬编码限制（`preload.js:37-45`）：

```js
const supportActions = {
  kw: ['musicUrl'], kg: ['musicUrl'], tx: ['musicUrl'],
  wy: ['musicUrl'], mg: ['musicUrl'], xm: ['musicUrl'],
  local: ['musicUrl', 'lyric', 'pic'],
}
```

脚本里写的 `search` / `musicSearch` 会被**静默丢弃**（不是作者不写，是 LX 不给）。

> **为什么必须装**：LX v2.12.5 已把内置播放 API 全部停用
> （`api-source.js:11-29` 的 `allApi` 与 `apiSourceInfo` 皆空），
> 音频地址**只能**来自用户脚本。即 **不装 = 搜得到但播不了**。

---

## 2. 存储格式

路径：`%APPDATA%\lx-music-desktop\LxDatas\user_api.json`

```json
{"userApis": [{
  "id": "user_api_927_1784270441030",
  "name": "[独家音源]",
  "description": "…",
  "version": "4",
  "author": "…",
  "homepage": "",
  "allowShowUpdateAlert": true,
  "script": "gz_<base64(zlib.compress(utf8))>"
}]}
```

### 2.1 编码

```python
encode = "gz_" + base64.b64encode(zlib.compress(text.encode("utf-8"))).decode()
decode = zlib.decompress(base64.b64decode(s[3:])).decode("utf-8")
```

> ⚠️ **`gz_` 前缀有误导性 —— 是 zlib 不是 gzip**。
> `gzip.decompress` 会失败。实测本机 8/8 脚本用 zlib 全部解压成功。

> ⚠️ 压缩**不必**与 Node 逐字节一致（Python 压缩比略有差异），
> 但会影响 LX `importApi` 的去重比对（它比的是压缩后字符串）。

### 2.2 写入纪律

| 要求 | 原因 |
|---|---|
| **Tab 缩进** | 与 LX 写出的格式一致 |
| **temp + rename 原子写** | 写坏 JSON 会让 LX 把文件改名 `.bak` 并弹错误框 |
| **LX 关闭时写** | LX 是内存缓存 + 全量回写，运行时会覆盖 |
| 写前备份 `.bak-<时间戳>` | 可回滚 |

---

## 3. 脚本头格式

必须**位于文件索引 0**（前面有 BOM/空行/任意字符即非法）：

```js
/*!
 * @name 六音音源
 * @description v1.2.1
 * @version v1.2.1
 * @author 六音
 * @homepage www.sixyin.com
 */
```

* 白名单**只有 5 个键**：`name` `description` `author` `homepage` `version`
* 超长截断 `substring(0,len)+'...'`：**24 / 36 / 56 / 1024 / 36**
* 注释块可以是 `/*!` 或 `/**`（LX 不校验 `!`）

---

## 4. 更新判定（关键）

**不能用 `@version`** —— 版本串形态混杂（`4` / `v2.0.0` / `1.0.0` / `v22`），
且 App 从不比较版本。

**决定性反例**：仓库 `lx/latest.js` 与本机已装 v6 **内容不同但 `@version` 都是 6**
（该源会就地重新混淆）。

⇒ 必须用**内容哈希**（sha256）：

```
本地 sha256 == 远端 sha256  →  skip
不同                        →  update
```

**更新时保留原 `id`** —— 否则用户的 `common.apiSource` 选择会跳变回内置源。

---

## 5. 仓库适配（声明式）

`scripts/repo.py` 的 `REPO_SOURCES` 描述 `pdone/lx-music-source` 的 10 个源：

| key | 显示名 |
|---|---|
| `sixyin` | 六音音源 |
| `huibq` | Huibq 源 |
| `flower` | 野花🌷 |
| `lx` | 洛雪官方源 |
| `changqing` | 长青 SVIP 音源 |
| `huanyin` | 幻音音源 |
| `ikun` | ikun 音源 |
| `grass` | 野草🌾 |
| `juhe` | 聚合 API 源 |
| `qdy` | qdy 源 |

**仓库事实**：
* `latest.js` = 最高版本文件的**物理副本**（`CreateLatest.py` 用 `shutil.copy2`），非 symlink
* 权威版本指针在 `CreateLatest.py` 的 `VERSIONS` 字典（人工维护，可能滞后）
* 直链：`https://raw.githubusercontent.com/pdone/lx-music-source/main/<key>/latest.js`
* 镜像：5 个 ghproxy 系，自动回退

### 5.1 仓库变化时怎么改

**只改 `scripts/repo.py` 顶部**：

```python
REPO_SOURCES = (RepoSource("新目录名", "中文名", "备注"), …)
RAW_TEMPLATE = "https://…/{owner}/{repo}/{branch}/{path}"
MIRRORS = ("https://…/{url}", …)
OWNER = "pdone";  REPO = "lx-music-source";  BRANCH = "main"
```

若是**换了仓库**（不是同一个仓库改结构），改 `OWNER`/`REPO`/`BRANCH` 即可。

---

## 6. 安全防护（照 LX 的限制）

| 限制 | 值 |
|---|---|
| 单脚本大小 | ≤ **9,000,000** 字符 |
| 音源数量 | ≤ **20** 个 |
| URL 协议 | 必须 `^https?://` |
| 重定向 | ≤ 3 跳 |
| 编码 | 必须 **UTF-8**（否则报"可能是错误页"） |
| HTML 检测 | 拒绝（镜像失效常返回 404 页面） |

**不要改动脚本一个字节** —— 有脚本带自毁/自校验：
* `lx/2.js` 有基于 `@name+@description` MD5 的内存炸弹
* 多脚本有 `SCRIPT_MD5` 自校验

本项目的做法是**整体替换**，从不做文本编辑。

---

## 7. 手改保护

CLI 在 `LxDatas/lx_cli_scripts_meta.json`（**LX 不读**）记录安装时的哈希：

```json
{"user_api_969_…": {"installedSha256": "642de2d…", "source": "lx",
                    "url": "https://…/lx/latest.js", "installedAt": 1789019033898}}
```

更新前比对：哈希不符（或**无记录** = 用户自己导入的）→ 视为"被手改"，
**拒绝覆盖并要求 `--force`**。

---

## 8. 不执行脚本

CLI **不自己跑 JS**。原因：

* 脚本硬依赖 Electron（`contextBridge` / `webFrame` / `needle`），脱离 Electron 原生跑不了
* 强行 shim `globalThis.lx` 有三个坑：
  ① 必须提供 `currentScriptInfo.rawScript`（`lx/2.js` 用它自毁校验）
  ② `lx.version` 必须精确 `'2.0.0'`（`juhe/3.js` 拿它做比较）
  ③ `lx.utils.crypto.rsaEncrypt` 语义是"左补零至 128 字节 + RSA_NO_PADDING"
* **没必要**：播放交给 LX 自己做（`lx play-song` 走 Scheme URL，LX 会调脚本）

---

## 9. 排查

| 现象 | 原因 | 处理 |
|---|---|---|
| 装完 LX 里看不到 | LX 未重启 | 重启 LX |
| 所有在线歌播不了 | 没启用脚本 | `lx script enable <名字>` |
| 更新报"无来源记录" | 该脚本是你手动导入的 | 用 `lx script install <仓库名> --apply` |
| 更新报"被手动修改过" | 你改过脚本 | 确认要覆盖再加 `--force` |
| 下载失败 | 直链+镜像都不通 | 手动下载后 `--file` |
| 下载到 HTML | 镜像失效 | 已自动检测并报错 |
| 脚本装完不生效 | 脚本本身服务挂了 | `lx script repo --check` 看远端；换一个源 |
