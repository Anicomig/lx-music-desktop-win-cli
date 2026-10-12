# 内部文档索引（排障入口）

> **给 AI/维护者**：CLI 出问题时，从**现象**出发，按本页找到对应文档与代码位置。
> 目标：不读完整源码也能快速定位。

---

## 0. 30 秒定位表

| 现象 | 先看 | 代码位置 |
|---|---|---|
| 命令报错但看不出原因 | [调试](#3-调试手段) | `cli/__init__.py:main()` |
| `--json` 输出解析失败 / 有杂字符 | [契约](contracts.md#json-契约) | `cli/_common.py:emit()` |
| 退出码不对 | [契约](contracts.md#退出码) | `errors.py:exit_code_for()` |
| 找不到 LX / 数据目录 | [可移植性](#4-可移植性) | `paths.py:find_exe()` |
| 读写数据库出错 | [数据库](database.md) | `core/db_reader.py` / `core/db_writer.py` |
| 歌曲 id 不对 / 插入后播不了 | [契约](contracts.md#歌曲-id) | `core/musicinfo.py:make_song_id()` |
| 搜索某平台没结果 | [平台源](sources.md) | `sources/<平台>.py` |
| 播放控制无效 | [契约](contracts.md#播放状态) | `core/openapi_client.py` |
| `play-song` 不生效 | [契约](contracts.md#scheme-url) | `core/scheme_url.py` |
| 音源脚本装不上 / 更新失败 | [音源脚本](scripts.md) | `scripts/service.py` / `scripts/repo.py` |
| 歌单插入结果不对 | [数据库](database.md#写入规则) | `cli/playlist.py:compare()` |
| 文档与实现不符 | 本页 §5 | `scripts/gen_commands_doc.py` |

---

## 1. 模块地图

```
src/lx_cli/
├── cli/                    表现层（Click）
│   ├── __init__.py         入口 main()、命令注册、退出码处理
│   ├── _common.py          Ctx / emit / wrap_errors / 参数解析
│   ├── music.py            search/song/album/leaderboard/hot/lyric/source-list
│   ├── player.py           play/pause/…/status + Scheme(play-song/search-play)
│   ├── playlist.py         歌单读写 + ★ add --from-search + compare()
│   ├── script.py           音源脚本管理命令
│   ├── proc.py             start/stop/config/where/backup
│   └── db_cmd.py           db tables/info/schema/query/stats
├── core/                   领域层（无 CLI 依赖，可单测）
│   ├── musicinfo.py        ★ id 构造/解析 + meta 编解码 + 来源显示名
│   ├── matcher.py          换源/去重匹配（±5s + 版本词）
│   ├── openapi_client.py   Open API 客户端（播放/状态/歌词/SSE）
│   ├── scheme_url.py       lxmusic:// 派发（播放指定歌曲等）
│   ├── db_reader.py        只读数据库
│   ├── db_writer.py        写数据库（事务 + 幂等）
│   ├── launcher.py         进程控制 + exe 查找
│   ├── config_store.py     config_v2.json 读写
│   └── http.py             统一 requests.Session
├── sources/                ① 平台元数据接口（搜索用）
│   ├── base.py             PlatformSource 协议 + SongRecord
│   ├── search.py           单/多/聚合搜索
│   ├── http.py             平台请求（含 kw 单引号 JSON 修复）
│   └── {kg,kw,tx,mg,wy}.py 各平台官方接口
├── scripts/                ② JS 音源脚本管理（不执行）
│   ├── store.py            user_api.json 读写（gz_/zlib + 原子写）
│   ├── metadata.py         脚本头解析
│   ├── repo.py             源仓库声明式适配 + 镜像回退
│   └── service.py          install/update/list/remove
├── paths.py                ★ 路径解析（可移植性 P1–P4）
├── errors.py               异常树 + 退出码
└── _logging.py             日志（强制 stderr）
```

---

## 2. 数据流（三条通道）

```
                     ┌──────────────────────────────┐
搜索歌曲 →  sources/ │ ① 平台元数据接口（官方域名）    │ 有返回值，快
                     └──────────────────────────────┘
                              ↓ SongRecord（含可落库 id）
                     ┌──────────────────────────────┐
                     │  core/db_writer.py  写歌单     │ 需 LX 关闭
                     └──────────────────────────────┘

播放控制 →  core/openapi_client.py   ② Open API     有返回值，快（仅当前曲）
播放指定 →  core/scheme_url.py       ③ Scheme URL   无返回值，慢（秒级）

音源脚本 →  scripts/*                只管装/更新，不执行
```

> **分工不可混**：`sources/` 不碰脚本，`scripts/` 不查歌。

---

## 3. 调试手段

```bash
python run.py -v  <命令>          # INFO 日志（stderr）
python run.py -vv <命令>          # DEBUG（含 HTTP/路径探测）
python run.py --debug-trace <命令> # 未预期异常时打印堆栈
```

代码里用 `get_logger()`；**不要用 `print`**（会污染 `--json`）。

---

## 4. 可移植性

见 [`research/05-kg-id-定论与文档更正.md`](research/05-kg-id-定论与文档更正.md) 与
[`research/06-官方文档核对-openapi与scheme.md`](research/06-官方文档核对-openapi与scheme.md)。要点：

* `run.py` / `lx.bat` 按**自身位置**定位 `src/`，改名搬家均可用
* `paths.py:user_data_dir()` 只读 `%APPDATA%`，**不硬编码用户名**
* `paths.py:find_exe()` 顺序：`LX_EXE` → 候选路径（含各盘符）→ PATH → **注册表** → 目录扫描
* 兜底环境变量：`LX_EXE`（exe）、`LX_DATA_DIR`（数据目录）

---

## 5. 文档与实现的一致性

| 文档 | 是否自动生成 | 校验方式 |
|---|---|---|
| `docs/reference/commands.md` | ✅ 从 `--help` 生成 | `python scripts/gen_commands_doc.py --check` |
| 其它文档 | ❌ 手写 | 靠代码评审 |

> 改了 CLI 参数后**必须**重新生成 commands.md，否则 `--check` 会失败。

---

## 6. 测试

```bash
cd lx-cli-v2
PYTHONPATH=src python -m pytest tests/ -q      # 273+ 用例
```

| 测试文件 | 覆盖 |
|---|---|
| `test_musicinfo.py` | id/meta 契约（**kg 无前缀**、歌手分隔符、类型不稳定） |
| `test_db.py` | 读写、幂等、稀疏 order、虚拟歌单 |
| `test_sources.py` | 单/多/聚合、失败隔离、kw 单引号 JSON |
| `test_matcher.py` | 去重口径、±5s、版本词 |
| `test_scripts.py` | gz_/zlib 编解码、更新保留 id、手改保护 |
| `test_openapi_client.py` | **status 字符串**（旧版布尔 bug 回归） |
| `test_scheme_url.py` | URL 构造、平台必传参数 |
| `test_cli_contract.py` | `--json` 契约、退出码、`--db` 生效 |
| `test_portability.py` | P1–P4（改名/搬家、数据目录、exe 查找） |

**提交前钩子**：`.githooks/pre-commit` 会跑测试，失败则阻止提交
（启用：`git config core.hooksPath .githooks`）。

---

## 7. 已知契约陷阱（改代码前必读）

| 陷阱 | 说明 | 位置 |
|---|---|---|
| **kg 的 id 无前缀** | 是 `<songId>_<hash>`，写成 `kg_…` 会生成 LX 不认的 id | `core/musicinfo.py` |
| **`local` 的 id 是路径** | 含 `_`，禁止切分 | 同上 |
| **`gz_` 不是 gzip** | 是 **zlib**；用 gzip 解压会失败 | `scripts/store.py` |
| **`status` 是字符串** | `playing`/`paused`/`error`/`stoped`；当布尔会错 | `core/openapi_client.py` |
| **状态变更非同步** | 发命令后约 1 秒才生效 | 同上 |
| **`singer` 三种分隔符** | DB `、`；匹配 `、&;；/,，\|`；Open API `;` | `musicinfo` / `matcher` |
| **`order` 可能稀疏** | 不能当下标；缺 order 的行要排最后 | `core/db_reader.py` |
| **`user_api.json` 需 Tab + 原子写** | 否则 LX 会改名 `.bak` 并弹错 | `scripts/store.py` |
| **CJK 不能用 `LOWER()`** | SQLite 的 LOWER 只处理 ASCII | `core/db_reader.py` |
| **`config_v2.json` 键是扁平点号** | `openAPI.enable` 而非嵌套对象 | `core/config_store.py` |
| **Click 会吞 `Exit`** | `standalone_mode=False` 时退出码在**返回值**里 | `cli/__init__.py:main()` |
| **Click 的 `--apply` dest** | 默认 dest 是 `apply`，参数名若是 `apply_` 会 TypeError | 各命令 |

---

## 8. 深入阅读

* [契约](contracts.md) —— id/meta/状态/退出码/JSON 的精确定义
* [架构](architecture.md) —— 分层、依赖、数据流
* [平台源](sources.md) —— 5 个平台的能力与 endpoint
* [音源脚本](scripts.md) —— 脚本机制与仓库适配
* [数据库](database.md) —— schema、读写规则、边界数据
* [命名约定](conventions.md) —— 三类"源"的区分
* [调研归档](research/) —— 桌面端源码、真实数据、官方文档核对
* [命名约定](conventions.md)
