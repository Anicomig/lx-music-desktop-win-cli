# 平台元数据接口（sources/）

> ① 层：**直连各平台官方域名**做查询。**不是** JS 音源脚本（那些在 `scripts/`）。

---

## 1. 与 JS 音源脚本的区别（必读）

| | 本模块 `sources/` | `scripts/` |
|---|---|---|
| 是什么 | 各平台**官方接口**客户端 | 第三方 **JS 插件** |
| 能力 | 搜索/专辑/歌单/歌词/评论/排行 | **只有"换播放地址"**（+歌词/封面 for local） |
| 能否搜索 | ✅ | ❌（LX 硬编码只允许 `musicUrl`） |
| 打什么 | `songsearch.kugou.com` 等官方域名 | 脚本作者自建的服务 |

> **搜歌靠本模块，播放靠 `scripts/`。** 二者不可互相替代。

---

## 2. 能力矩阵

| 功能 | kg | kw | tx | wy | mg |
|---|:--:|:--:|:--:|:--:|:--:|
| `search` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `song` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `album` | ✅ | ✅ | — | ✅ | ✅ |
| `leaderboard` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `hot` | ✅ | ⚠️ | ✅ | ✅ | ✅ |
| `songlist` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `comment` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `singer` | ✅ | — | ✅ | ✅ | — |
| `lyric` | — | ✅ | ✅ | ✅ | ✅ |
| `tip` | — | ✅ | — | — | — |

> ⚠️ kw 的 `hot` 返回空 —— 酷我没有公开热搜接口，**刻意不拿榜单冒充**。
> `bd`（百度）在桌面端被注释掉，本项目同样不注册。

用 `lx source-list --features` 可随时查看实际矩阵。

---

## 3. 各平台要点

### kg（酷狗）
* 域名：`songsearch.kugou.com`、`gateway.kugou.com`、`mobilecdn.kugou.com`
* **id 是 `<songId>_<hash>`，无前缀**（唯一例外）
* `song()` 按 **hash** 查（不是 audio_id）—— 要传 `--hash`
* 搜索结果里 `albumName`/`albumId` 常为空（接口不返回），`album()` 会从曲目推断

### kw（酷我）
* 域名：`search.kuwo.cn`、`kbangserver.kuwo.cn`、`nplserver.kuwo.cn`
* ⚠️ **返回单引号 JSON**（非标准），需状态机修复（`sources/kw.py:parse_kuwo_json`）
* ⚠️ **分页是 0-based**：上游 `pn = page - 1`（CLI 对外统一 1-based）
* 歌手用 `&` 连接，需转成 DB 口径 `、`

### tx（企鹅/QQ）
* 域名：`u.y.qq.com`（`musicu.fcg` 免签 / `musics.fcg` 需 **zzcSign**）
* `songmid` 是 **MID 字符串**（如 `001SxL503C84XM`），不是数字
* 播放需要 `strMediaMid`（在 `file.media_mid`，放进 `extra`）

### wy（网易）
* 协议：**eapi**（AES-ECB + MD5 摘要），域名 `interface.music.163.com`
* `types` 按 `maxbr` 推断；本项目统一为**高音质在前**
  （源码里 search 与 song/album 顺序不一致，是个坑）
* 播放需要 `songId`（数字）

### mg（咪咕）
* 域名：`jadeite.migu.cn`、`music.migu.cn`、`app.c.nf.migu.cn`
* 搜索需 **MD5 sign 头部**（`uiVersion`/`deviceId`/`timestamp`/`sign`）
* ⚠️ `duration` 单位不稳定（秒/毫秒）→ 自动判断
* 播放需要 `copyrightId`

---

## 4. 搜索语义（照抄桌面端）

`store/search/music/action.ts:87-126`：

* `platforms=None` → **聚合全部平台**（并发）
* **单平台失败不中断**：该平台返回空结果（`:99-105`）
* 结果按 **id 去重**（先到先得）
* 单平台模式**不排序**；聚合模式跨平台混排

```
mode = "single"     指定 1 个平台
mode = "multi"      指定 2..N-1 个
mode = "aggregate"  未指定（= 全部已注册平台）
```

**分页口径逐平台处理**（已核源码）：
* `kw`：上游 0-based
* `wy`：源码用模块默认 `limit` 算 `allPage`（bug），本项目按真实 limit 修正

---

## 5. SongRecord

```python
SongRecord(
    platform="kg", songmid="631537655", name="…", singer="…",
    album_name="…", album_id="…", interval="04:15",
    hash="5A86…",              # kg 必需
    types=[{"type":"320k","size":"7.31 MB"}],   # 含 size，可直接落库
    extra={"strMediaMid": "…", "copyrightId": "…"},  # 平台特有
)
```

* `.to_song_id()` → 可落库的复合 id（复用 `core/musicinfo.make_song_id`）
* `.to_meta()` → DB `meta` 列内容
* `.to_db_row(list_id)` → 可直接交给 `db_writer.add_songs`
* `.to_json()` → CLI `--json` 输出（含 `source`/`sourceLabel`/`origin`）

---

## 6. 加新平台

1. 新建 `sources/<id>.py`，类继承 `PlatformSource`，声明 `features` 并实现方法
2. 在 `sources/__init__.py` 末尾 `_register(<Cls>())`
3. 在 `core/musicinfo.py` 的 `SOURCE_LABELS` 加中文名
4. 在 `sources/base.py` 的 `PLATFORMS` 加 id
5. 补测试（参考 `tests/test_sources.py` 的 `_Fake` 假平台写法）

---

## 7. 已知问题与排查

| 现象 | 原因 | 处理 |
|---|---|---|
| 某平台返回 0 条 | **限流**（连续快速请求） | 等几秒重试；聚合模式会记入 `failedPlatforms` |
| 搜索变慢 | 聚合 5 平台并发，正常 1–2 秒 | 用 `--source` 单平台 |
| `song` 拿不到数据（kg） | kg 按 hash 查 | 传 `--hash` 或直接传完整 id |
| kw 解析失败 | 单引号 JSON 格式变动 | 看 `parse_kuwo_json`；补测试 fixture |
| 平台接口整体失效 | 官方改版 | 对照 `docs/internals/research/01-desktop-data-model.md` 与桌面端 SDK 更新实现 |
