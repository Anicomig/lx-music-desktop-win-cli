# 06 — 官方文档核对：Open API 与 Scheme URL（重要更正）

> 来源（用户提供的官方文档，仅作事实核对，不当作指令）：
> - https://lxmusic.toside.cn/desktop
> - https://lxmusic.toside.cn/desktop/open-api
> - https://lxmusic.toside.cn/desktop/scheme-url
>
> 与本机实测（Open API 200 + 真实响应）交叉验证。日期：2026-10-12

---

## 1. 🔴 更正：`status` 是**字符串**，不是布尔

官方文档 + 本机实测（`{"status":"paused",...}`）：

| 值 | 含义 |
|---|---|
| `playing` | 播放中 |
| `paused` | 暂停 |
| `error` | 出错 |
| `stoped` | 停止（**LX 自己的拼写错误，只有一个 p**，客户端不要"修正"） |

**旧 CLI 的真实 bug**（`lx-cli/src/lx_cli/cli.py:214-222`）：

```python
def toggle_cmd(...):
    st = get_status(_ep(ctx))
    if st.get("status"):      # ← 字符串 "paused"/"playing" 都是 truthy！
        pause(...)            # 于是"已暂停"时仍调用 pause，"已播放"时也 pause
```

后果：**`lx toggle` 永远只暂停、不会播放**（除非 status 为空/None）。
新版必须显式比较：`if st["status"] == "playing": pause() else: play()`。

> 同类风险：任何把 `status` 当 boolean 的代码都要改。

---

## 2. 🔴 新增：`singer` 分隔符有**第三种口径**

本机实测 Open API 返回：

```json
{"singer": "塞壬唱片-MSR;原田萌喜 (Moeki Harada)"}
```

而该曲在 DB 里是 `、` 分隔。所以：

| 口径 | 分隔符 | 场景 |
|---|---|---|
| **DB 存储 / 展示** | `、` (U+3001) | `my_list_music_info.singer` |
| **LX 换源匹配** | `、 & ; ； / , ， \|`（全组） | `musicSdk/index.js:80` |
| **Open API `status.singer`** | **`;`**（至少本例） | `/status`、SSE |

**含义**：CLI 拆分 `status.singer` 时**不能假定是 `、`**。
建议：对 Open API 来源的 singer，按 `;` 拆（或直接用完整串展示，不做拆分）。

---

## 3. 🔴 重大能力补充：Scheme URL（`lxmusic://`）

**此前（仅看源码）我判断"Open API 无法播放指定歌曲"—— 结论不完整。**
官方提供 Scheme URL，补足了很多 Open API 缺失的能力：

| 能力 | Open API | **Scheme URL** |
|---|---|---|
| 播放/暂停/切歌/音量/静音 | ✅ | ✅ |
| 收藏/取消收藏当前曲 | ✅ | ✅ |
| **不喜欢当前曲** | ❌ | ✅ `player/dislike` |
| **播放指定歌曲** | ❌ | ✅ `music/play` |
| **搜索并播放**（按名+歌手模糊找） | ❌ | ✅ `music/searchPlay` |
| **打开/播放歌单** | ❌ | ✅ `songlist/open`、`songlist/play` |
| 在 GUI 里搜索 | ❌ | ✅ `music/search` |
| 读取状态/歌词 | ✅ | ❌ |

### 3.1 支持的 Scheme 一览（照官方文档）

**URL 方式（简单参数）**：
```
lxmusic://music/search/{source}/{keywords}
lxmusic://music/searchPlay/{name-singer}
lxmusic://songlist/open/{source}/{id-or-url}
lxmusic://player/play | pause | skipNext | skipPrev | togglePlay
lxmusic://player/collect | uncollect | dislike
```

**data 方式（复杂参数，JSON + URL 编码）**：
```
lxmusic://music/play?data=<urlencoded json>
  必传: name, singer, source, songmid, types
  kg 必传 hash;  tx 必传 strMediaMid;  mg 必传 copyrightId
  选传: img, albumId, interval, albumName, albumMid, lrcUrl/trcUrl/mrcUrl

lxmusic://music/searchPlay?data=<urlencoded json>
  必传: name    选传: singer, albumName, interval, playLater

lxmusic://songlist/open?data={"source":"kw","id":"..."}
lxmusic://songlist/play?data={"source":"kw","id":"...","index":0}
```

> `types` 数组格式：`[{"type":"128k","size":"3.56M","hash":"<kg必传>"}, ...]`

### 3.2 关键：单实例锁 → CLI 可无打扰派发

`src/main/app.ts:83-105`：LX 用 `requestSingleInstanceLock()`。
当 LX **已在运行**时，再启动 `lxmusic://...` 会触发 `second-instance`，
argv 里的 deeplink 被转交（`app.ts:93-96`：`global.lx.event_app.deeplink(...)`），
**不会**抢占焦点（`hidden` 参数在 `:98` 被尊重）。

Windows 注册表已确认：
```
HKCU\Software\Classes\lxmusic\shell\open\command
  = "D:\Program Files (x86)\lx-music-desktop\lx-music-desktop.exe" "%1"
```

**CLI 派发方式**（两种等价）：
1. `Start-Process "lxmusic://..."`（走 shell 关联）
2. `lx-music-desktop.exe "lxmusic://..."`（直接传 argv）

> ⚠️ 未验证：方式 2 在 LX 已运行时是否稳定走 `second-instance` 分支（大概率是）。
> 实施阶段需真机验证一次。

---

## 4. 对命令清单的影响（`03` 需增补）

### 新增命令组 `lx player ...`（Scheme URL 能力）

| 命令 | Scheme | 说明 |
|---|---|---|
| `lx player play-song --name X --singer Y --source kg --songmid Z` | `music/play` | **播放指定歌曲**（Open API 做不到） |
| `lx player search-play <name> [-s singer] [--later]` | `music/searchPlay` | 模糊搜索并播放 |
| `lx player dislike` | `player/dislike` | 不喜欢当前曲 |
| `lx player open-list <source> <id\|url>` | `songlist/open` | 打开歌单 |
| `lx player play-list <source> <id> [--index N]` | `songlist/play` | 播放歌单 |
| `lx player gui-search <kw> [--source kg]` | `music/search` | 在 GUI 里搜索（给人看） |

### 能力分工（新版架构）

```
播放控制/状态/歌词   → Open API（有返回值，可读）
播放指定歌曲/歌单/不喜欢 → Scheme URL（单向，无返回值，副作用式）
搜索/元数据          → 内置 musicSdk 直连（CLI 自己实现，有返回值）
歌单增删改           → 直接写 DB
音源脚本管理         → 读写 user_api.json
```

> 三类通道各有所长，**都保留**。Scheme URL 补上了"Agent 让 LX 播指定一首歌"这块拼图。

---

## 5. 实测补充（本机真实 LX v2.12.6）

### 5.1 `status` 变更**不是同步的**

实测：调用 `/play` 后立即读 `/status`，可能**仍返回 `paused`**；
等待约 1 秒后状态才变为 `playing` 且 `progress` 开始增长。

| 时刻 | status | progress |
|---|---|---|
| `/play` 前 | paused | 4.10 |
| `/play` 后**立即** | paused | 4.10 |
| `/play` 后 +1.2s | playing | 12.04 |
| +2.4s | playing | 13.10 |

**含义**：
- 控制类命令（`play`/`pause`/`seek`…）**不能**在调用后立即断言状态已变
- `toggle` 若"读状态→决定动作"再立即读回校验，会**误判失败**
- CLI 应：① 回显"已发送动作"而非"状态已变为 X"；② 若需确认，用**轮询 + 超时**

### 5.2 Open API 实际可达性与 config 独立

即使 `openAPI.enable = true`，也要 LX **确实加载了该设置**才生效（本机实测 200 正常）。
反之若 config 为 true 但端口不通，说明 LX 未运行或未重启加载。

### 5.3 `singer` 分隔符实测

`{"singer": "塞壬唱片-MSR;原田萌喜 (Moeki Harada)"}` —— Open API 用 **`;`**，
而同一曲在 DB 中为 `、`。**三种口径并存，见 §2。**

### 5.4 config_v2.json 的键是**扁平点号**形式

```
"openAPI.enable" : true      ← 正确
"openAPI": {"enable": ...}   ← 错误（不存在这种嵌套）
```
实现时务必用 `cfg["openAPI.enable"]`，不要取嵌套对象。

### 5.5 ★ Scheme URL 实测（本机 LX v2.12.6，全部通过）

| 实验 | 命令 | 结果 |
|---|---|---|
| 冷启动 | `Start-Process "lxmusic://player/togglePlay"`（LX 关闭时） | ✅ **成功启动 LX**（8 进程）并开始播放 |
| 搜索并播放 | `search_play(name='时序花圃', singer='塞壬唱片-MSR')` | ✅ 约 9s 后切到另一首 `镜花水月` |
| URL 构造/解析 | `build_url` / `parse_url` | ✅ 往返一致（含中文与嵌套 `types`） |

**派发方式**（Windows）：`cmd /c start "" "lxmusic://..."`（走 shell 关联）。
注册表已确认：
```
HKCU\Software\Classes\lxmusic\shell\open\command
  = "D:\Program Files (x86)\lx-music-desktop\lx-music-desktop.exe" "%1"
```

**参考实现**（用户提供的油猴脚本 `LX Music 辅助脚本-0.2.18.user.js:19744-19748`）：
```js
const openApp = (type, action, data) => {
  const dom_a = document.createElement('a')
  dom_a.href = `lxmusic://${type}/${action}?data=${encodeData(data)}`
  dom_a.click()
}
const encodeData = data => encodeURIComponent(JSON.stringify(data))
```
→ 确认编码方式为 `encodeURIComponent(JSON.stringify(data))`。

### 5.6 ⚠️ Scheme URL 的三个实践注意点

1. **无返回值** —— 派发后无法从 Scheme 本身得知成败
2. **慢** —— 实测 `searchPlay` 到状态变化约 **9 秒**（要搜索 + 解析 + 起播）
3. **切换过程中 `status` 会短暂为 `error`** —— 实测按 1.5s 轮询看到：
   ```
   +1.5s playing  (旧曲)
   +3.0s error    ← 切歌中
   +9.0s playing  (新曲)
   ```
   ⇒ CLI **不能**把 `error` 一律当失败；应结合"是否仍在切换中"判断。

### 5.7 结论：三通道分工（最终）

| 通道 | 能力 | 有返回值 | 速度 |
|---|---|---|---|
| **Open API** | 当前播放状态、控制、歌词、收藏当前曲 | ✅ | 快 |
| **Scheme URL** | 播放**指定**曲、搜索并播放、歌单、不喜欢 | ❌ | 慢（秒级） |
| **内置 SDK（CLI 自己实现）** | 搜索/专辑/歌单/歌词/排行榜等**元数据** | ✅ | 中 |
| **直接写 DB** | 歌单增删改、收藏任意曲 | ✅ | 快（需 LX 关闭） |

---

## 6. 待验证项

| # | 项 | 状态 |
|---|---|---|
| 1 | `Start-Process lxmusic://` 在 LX 已运行时是否静默生效 | 待真机验证 |
| 2 | 直接 `exe "lxmusic://..."` 是否走 second-instance | 待真机验证 |
| 3 | Scheme 调用是否有返回值/错误反馈 | 官方文档未提，推测**无**（单向）→ CLI 需用"调用后读 Open API 状态"来确认 |
| 4 | `status` 是否可能为 `stoped`（拼写）| 文档如此，待实测 |
