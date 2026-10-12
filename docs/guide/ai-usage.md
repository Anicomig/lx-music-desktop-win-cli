# AI 使用指南

> 面向**用 CLI 的 AI/自动化程序**：契约、退出码、安全边界、典型工作流。
> 人类用户请看 [`功能与操作.md`](功能与操作.md)。

---

## 1. 调用方式

三种等价（AI 建议用第一种，路径无关）：

```bash
python <cli-root>/run.py <命令> [参数]      # 免安装，路径无关
lx <命令> [参数]                            # 已 pip install
python -m lx_cli <命令> [参数]               # 已安装/已设 PYTHONPATH
```

> ⚠️ **不要依赖 `python -m lx_cli` 未安装时能用** —— 若系统里另有旧版
> `lx-cli`，会静默加载旧版（版本号不同）。用 `--version` 自检：
> 新版是 **0.2.x**。或用 `run.py` 保证加载的是本目录代码。

---

## 2. 机器可读输出：`--json`

**每一个输出命令都支持 `--json`**，且保证：

| 保证 | 说明 |
|---|---|
| **stdout 只有 JSON** | 日志/警告一律走 **stderr**，不污染解析 |
| **成功必有输出** | 不会出现 `exit 0` 但 stdout 为空 |
| **错误结构化** | 失败时也输出 JSON：`{"error": {"code","message","detail"}}` |
| **形状稳定** | 字段名不随调用变化（见下） |

### 2.1 典型形状

**搜索**
```json
{
  "keyword": "yorushika",
  "mode": "aggregate",            // single | multi | aggregate
  "page": 1,
  "count": 140,
  "platforms": ["kg","kw","mg","tx","wy"],
  "failedPlatforms": [],
  "songs": [
    {
      "id": "116989871_8B4D0B91A150C3BE70058F5D8A668876",
      "songmid": "116989871",
      "name": "老人と海",
      "singer": "ヨルシカ",
      "singerList": ["ヨルシカ"],
      "albumName": "老人と海",
      "albumId": "…",
      "interval": "04:15",
      "source": "kg",              // 平台标识
      "sourceLabel": "酷狗音乐",     // 显示名
      "origin": "musicSdk",        // 数据来源
      "types": [{"type":"320k","size":"7.31 MB"}],
      "img": "http://…"
    }
  ]
}
```

**歌单插入（预演/执行）**
```json
{
  "listId": "userlist_…",
  "listName": "我的收藏",
  "dryRun": true,
  "existingCount": 12,
  "wouldAdd": 8,
  "alreadyIn": 22,
  "suspectDuplicates": 1,
  "items": {"toAdd": […], "skipped": ["kw_1"], "suspect": […]},
  "added": 8                       // 仅 --apply 时出现
}
```

**错误**
```json
{"error": {"code": "lx_running", "message": "LX Music 正在运行…"}}
```

---

## 3. 退出码（必须区分处理）

| 码 | 含义 | AI 应对 |
|---|---|---|
| `0` | 成功 | 正常解析 stdout |
| `1` | 运行时错误 | 读 stderr / JSON error.message |
| `2` | **用法错误**（参数不对、未知平台/命令） | 修参数，别重试 |
| `3` | **需要先关闭 LX** | 提示用户关闭，或用 `--force`（有风险） |
| `4` | 上游失败（网络/平台接口） | 可退避重试；聚合模式单平台失败不报此码 |
| `130` | 被中断 | — |

`error.code` 取值：`usage` `path` `lx_running` `lx_not_running` `openapi*`
`db*` `source` `unknown_source` `script*` `scheme`。

---

## 4. 安全边界（务必遵守）

### 4.1 读 vs 写

| 类别 | 命令 | 是否需要 LX 关闭 |
|---|---|---|
| **只读** | `search` `song` `album` `db *` `playlist list/show/find` `script list` `where` `status` | 否 |
| **写** | `playlist create/rename/delete/add/remove`、`config-enable/disable`、`script install/update/remove/enable` | **是**（否则 exit 3） |

### 4.2 写入前先预演

`playlist add` 与 `script install/update` **默认预演**。
先跑一次读 `wouldAdd` / `plan.action`，确认后再加 `--apply`。

### 4.3 幂等性

* `playlist add`：同 id 重复添加**不会**产生重复行（返回 `alreadyIn`）。
* `script update`：内容哈希相同则 `skip`，不会重复写。

### 4.4 绝不要做的事

* ❌ 不要用 `--force` 绕过"LX 正在运行"检查 —— 会丢数据
* ❌ 不要直接改 `%APPDATA%` 下的文件（除本 CLI 提供的命令）
* ❌ 不要把 `script` 输出里的密钥字段当公开信息传播（默认已脱敏）
* ❌ 不要假设 `status` 是布尔值（它是字符串）

---

## 5. 典型工作流

### 5.1 「找歌 → 加进歌单」

```bash
# 1) 搜（JSON 便于筛选）
python run.py search "yorushika" --source kg --limit 20 --json

# 2) 先预演，看会不会重复
python run.py playlist add <list_id> --from-search "yorushika" --source kg --json
#    → 检查 wouldAdd / alreadyIn / suspectDuplicates

# 3) 确认后写入（LX 必须已关闭）
python run.py playlist add <list_id> --from-search "yorushika" --source kg --apply --json
```

> 更稳的做法：把搜索 JSON 存下来人工/AI 筛选，再 `--from file`。

### 5.2 「让 LX 播放某首歌」

```bash
# Open API 不能播放指定歌曲；用 Scheme URL
python run.py search-play "又三郎" --singer ヨルシカ
sleep 10                      # 它慢（约 9 秒生效）
python run.py status --json   # 确认
```

### 5.3 「更新音源脚本」

```bash
python run.py script list --json                    # 看现状
python run.py script update --all --json            # 预演（哈希比对）
python run.py script update --all --apply --json    # 执行（需关 LX）
```

### 5.4 「换电脑后的自检」

```bash
python run.py where --json        # exe 与数据目录是否解析正确
python run.py db stats --json     # 能否读到库
python run.py script list --json  # 音源是否在
```

---

## 6. 已知行为特性（避免误判）

| 特性 | 说明 |
|---|---|
| **平台限流** | 连续快速搜索时某平台可能返回 0 条。聚合模式会记为 `failedPlatforms`，**换几秒重试** |
| **状态延迟** | `play`/`pause` 后约 1 秒状态才变。别发完立刻断言 |
| **`error` 状态** | 切歌过程中会出现，**不是崩溃** |
| **Scheme URL 慢且单向** | 无返回值，只能事后用 `status` 确认 |
| **`singer` 分隔符有 3 种** | DB 用 `、`；平台匹配用 `、&;；/,，\|`；Open API 用 `;` |
| **`kg` 的 id 无前缀** | 是 `<数字>_<hash>`，不是 `kg_…`。按 `id.split('_')[0]` 反推平台**会错** |
| **`local` 的 id 是文件路径** | 含 `_`，禁止按 `_` 切分 |

---

## 7. 调试

```bash
python run.py -v search "x"      # INFO 日志（stderr）
python run.py -vv search "x"     # DEBUG
python run.py --debug-trace search "x"   # 未预期异常时打印堆栈
```

日志**永远走 stderr**，所以 `--json` 的 stdout 始终可解析。

---

## 8. 自检清单（AI 首次接入时）

```bash
python run.py --version              # 应是 0.2.x
python run.py where --json           # exe / 数据目录
python run.py is-running --json      # LX 是否在跑
python run.py search "test" --limit 1 --json   # 网络与平台是否可用
python run.py db stats --json        # 数据库可读
python run.py script list --json     # 音源脚本状态
```

全部通过再开始实际操作。
