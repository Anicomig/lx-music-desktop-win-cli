# LX-CLI 技术审计报告

> **审计对象**：`C:\Users\EDY\Documents\workspace\lx-cli`（editable 安装的那一份）
> **审计模式**：只读源代码；唯一写入是 `LX-CLI-project/` 内的报告与本报告使用的探针脚本。
> **审计日期**：2026-10-12
> **报告目的**：为重构提供经过实测验证的缺陷清单。

---

## 0. 审计环境与方法

| 项 | 值 |
|---|---|
| Python | 3.13（32 位，`C:\Users\EDY\AppData\Local\Programs\Python\Python313-32`） |
| 测试命令 | `python -m pytest tests/ -q --ignore=tests/probe_real_server.py` |
| 测试结果 | **44 passed, 3 warnings in 1.69s**（0 失败、0 跳过） |
| 覆盖率工具 | **未配置**（`pyproject.toml` 无 `[tool.pytest]`、无 `pytest-cov`、无 dev extra） |
| 安装验证 | `import lx_cli.cli` → `...\lx-cli\src\lx_cli\cli.py` ✅ 确认 editable 指向 `lx-cli` |

### 关于 `lx-cli-portable`

`lx-cli-portable` 是 `lx-cli` 的**逐字节相同副本**。本报告全部 `file:line` 引用以 `lx-cli` 为准，portable 副本不参与审计（按要求，`lx-cli-portable/MIGRATION.md` 不予审计）。

### 证据约定

形如 `file.py:123` 的引用均指 `lx-cli` 仓库内路径。所有可执行结论均基于本机实跑：

| 方法 | 用途 | 脚本 |
|---|---|---|
| pytest 实跑 + `--collect-only` | §6 测试覆盖 | — |
| `CliRunner` 全命令 `--json` 对比 | §3 契约表、§2.6 | `LX-CLI-project/_scratch/audit_json*.py` |
| SQLite 只读探针 | §5.1 schema / order 形态 | `_scratch/audit_db_probe.py`、`audit_sparse.py` |
| **植入稀疏 order 后调用真实 `db_writer`** | §5.2 核心验证 | `_scratch/audit_music_add.py` |
| **构造跨 list 重复 id 后调用真实 `db_writer`** | §5.2、§2.7d | `_scratch/audit_dup_id.py` |
| 未知 song id 调用 `playlist add` | §5.4 核心缺口 | `_scratch/audit_gap.py` |

### 未验证项标记

无法通过执行或源码直读证实的结论一律标注「未验证」。

---

## 1. 模块清单与依赖图

### 1.1 模块清单（LOC = 物理行数）

| 模块 | LOC | 职责 | 公开 API |
|---|---:|---|---|
| `src/lx_cli/cli.py` | **1236** | Click 命令树、输出渲染、部分业务编排、内联 SQL、异步桥接 | `cli`、`main` |
| `src/lx_cli/client.py` | 173 | LX Open API（本地 HTTP）客户端 | `LXError`、`Endpoints`、`endpoints_from_config`、`get_status`、`play`、`pause`、`skip_next`、`skip_prev`、`seek`、`set_volume`、`set_mute`、`collect`、`uncollect`、`get_lyric`、`get_lyric_all`、`subscribe_player_status`、`wait_ready` |
| `src/lx_cli/config.py` | 67 | `config_v2.json` 读写 | `DEFAULT_OPEN_API`、`load_config`、`save_config`、`open_api_settings`、`set_open_api` |
| `src/lx_cli/db.py` | 272 | `lx.data.db` **只读**访问 + 领域查询 | `connect`、`list_tables`、`table_info`、`row_counts`、`query`、`list_user_lists`、`get_list`、`songs_in_list`、`find_songs`、`stats`、`rank_songs`、`rank_lists`、`distinct_songs`、`list_dislikes`、`list_downloads` |
| `src/lx_cli/db_writer.py` | 305 | `lx.data.db` 事务化写入 | `write_connect`、`list_create`、`list_rename`、`list_remove`、`music_add`、`music_remove`、`music_reorder`、`music_move` |
| `src/lx_cli/launcher.py` | 85 | LX 进程启停（Windows `tasklist`/`taskkill`） | `exe_path`、`is_running`、`start`、`stop` |
| `src/lx_cli/paths.py` | 121 | 用户数据目录解析 | `user_data_dir`、`lx_datas_dir`、`config_v2_path`、`data_json_path`、`user_api_path`、`db_path`、`default_exe_path`、`LIST_TABLES` |
| `src/lx_cli/sync_client.py` | 721 | 同步协议客户端（HTTP 握手 + message2call + WS） | `UrlInfo`、`ClientKeyInfo`、`parse_url`、`http_hello`、`http_get_server_id`、`http_auth_code`、`http_auth_key`、`Msg2Call`、`LXSyncClient`、`LIST_ACTIONS`、`is_valid_action`、`load_auth_keys`、`save_auth_key`、`read_server_id`、`require_crypto` |
| `src/lx_cli/sources/__init__.py` | 65 | 源注册中心 | `REGISTRY`、`get_source`、`list_sources`、`available_features` |
| `src/lx_cli/sources/base.py` | 165 | 领域 dataclass + 源协议基类 | `SourceError`、`SongRecord`、`SearchResult`、`AlbumInfo`、`LeaderboardEntry`、`Comment`、`HotKeyword`、`SourceBase` |
| `src/lx_cli/sources/http.py` | 103 | 统一 HTTP 层 | `request_json`、`request_form`、`request_text`、`USER_AGENT`、`DEFAULT_TIMEOUT`、`MAX_ATTEMPTS` |
| `src/lx_cli/sources/kg.py` | 221 | 酷狗源 | `KgSource` |
| `src/lx_cli/sources/kw.py` | 244 | 酷我源 | `KwSource`、`_parse_kuwo_json` |
| `src/lx_cli/sources/tx.py` | 206 | QQ 音乐源 | `TxSource`、`_zzc_sign` |
| `src/lx_cli/sources/mg.py` | 222 | 咪咕源 | `MgSource` |
| `src/lx_cli/sources/wy.py` | 255 | 网易云源 | `WySource`、`eapi_encrypt`、`search_songs`、`get_song_info`、`get_album` |
| `src/lx_cli/__init__.py` | 5 | 包导出 | `__version__` |
| `src/lx_cli/__main__.py` | 4 | `python -m lx_cli` | — |
| `src/lx_cli/tests/mock_sync_server.py` | 421 | **mock 服务器残留在生产包内** | `MockServer` |

**`src/lx_cli/` 源码合计约 4,321 行**（不含 `tests/`）。

### 1.2 依赖图

```
__main__ ─▶ __init__ ─▶ cli.py
                          │
     ┌────────────────────┼────────────────────┬──────────────┐
     ▼                    ▼                    ▼              ▼
 launcher            config.py              db.py        db_writer.py
     │                    │                    │              │
     └────────────────────┴────────┬───────────┴──────────────┘
                                   ▼
                              paths.py  (无内部依赖)

 cli.py ─▶ sync_client.py (websockets, cryptography)
 cli.py ─▶ client.py ─▶ config.py
 cli.py ─▶ sources/ ─▶ base.py, http.py
                     └─ {kg,kw,tx,mg,wy}.py ──自注册──▶ REGISTRY
```

### 1.3 分层结论：**底层干净，顶层塌陷**

**底层是干净的。** `paths.py` 零内部依赖；`db.py:15`、`db_writer.py:19` 均只依赖 `paths`；`sources/*` 之间无横向依赖，各源只依赖 `base` + `http`，通过 `_register_if`（`sources/__init__.py:17-21`）自注册（`kg.py:220-221`、`kw.py:243-244`、`tx.py:205-206`、`mg.py:221-222`、`wy.py:254-255`）。依赖方向单一、无环。

**顶层是塌陷的。** `cli.py` 1236 行同时承担 **6 类职责**：

1. 命令声明（44 处 `@*.command` 装饰器，`cli.py:192`–`1191`）；
2. 输出渲染（`_emit` `cli.py:150`、`_render` `cli.py:1013`、各命令内联拼接 `cli.py:293-301`、`652-663`、`686-690`、`704-714`、`749-750`、`773-777`、`795-799`、`815-817`）；
3. 业务逻辑（`toggle` 自己判状态，`cli.py:215-222`）；
4. **数据访问**（手写 SQL 于 `cli.py:826-830`，绕过 `db.py`）；
5. **异步编排**（`sync_auth` 内嵌 `async def go()`，`cli.py:1152-1188`）；
6. **动态命令生成**（`_make_feature_command`，`cli.py:1041-1085`）。

这是典型的 God Module，是重构的最大障碍（§8）。

**附加结构冗余**：`src/lx_cli/tests/mock_sync_server.py`（421 行）与 `tests/mock_sync_server.py`（401 行）是**两份近乎重复的 mock server**，且前者被打进 wheel（`pyproject.toml:26-27` 的 `packages = ["src/lx_cli"]`）。

---

## 2. 具体代码缺陷

### 2.1 `_jp` 与 `_j` 的重复定义（已确认）

`cli.py` 中两个 helper **各定义了两次**：

| 定义次序 | 行号 | 实现 |
|---|---|---|
| `_jp` 第 1 次 | `cli.py:104-106` | `return _json_option(click.pass_context(f))` |
| `_j` 第 1 次 | `cli.py:109-111` | `return _json_option(f)` |
| `_jp` 第 2 次 | `cli.py:114-116` | `return _json_option(_pc(f))` |
| `_j` 第 2 次 | `cli.py:185-187` | `return _json_option(f)` |

**精确行号**：`_jp` → **104** 与 **114**；`_j` → **109** 与 **185**。

**Python 语义**：模块级 `def` 是普通赋值，后定义覆盖先定义。生效的是 `cli.py:114` 的 `_jp` 与 `cli.py:185` 的 `_j`。

**后果分析（重要）**：由于 `_pc`（`cli.py:99-101`）本身就是 `click.pass_context` 的透传包装，`_json_option(_pc(f))` 与 `_json_option(click.pass_context(f))` **完全等价**。因此：

- **当前没有任何功能损失**，44 个测试全绿，40+ 个 `@_jp` 装饰点行为正常；
- 但这是**主动误导人的陷阱**：两份定义相隔仅 10 行且 docstring **一字不差**，读者必须自己推导「后者覆盖前者且二者等价」才能确认无差异；
- 更危险的是**装饰器顺序**：`_json_option` 依赖 `is_eager=True` + `expose_value=False`（`cli.py:88-96`）把值写进 `ctx.obj`。若有人"合并"两版为 `click.pass_context(_json_option(f))`（顺序反转），`is_eager` callback 的时序会错位，`--json` 将静默失效。**重名定义让"改了哪一个"变得不可推理。**
- **无 lint 保护**：`pyproject.toml` 仅 27 行，无 ruff/flake8 配置，F811（redefinition of unused name）不会被发现。

**`_j` 的两个定义都是死代码** —— 全文件 grep `_j\b` 仅命中 `cli.py:109`、`cli.py:185` 两处定义本身，**无任何 `@_j` 使用点**。

**修复**：删除 `cli.py:104-111` 与 `cli.py:185-187`，保留 `cli.py:114-116` 一份。

### 2.2 `try/except ImportError` 包裹 REGISTRY —— **会掩盖真实错误（确认）**

```python
48: try:
49:     from .sources import REGISTRY, get_source, list_sources as _list_sources
50: except ImportError:
51:     REGISTRY = {}
52:
53:     def get_source(source_id):  # type: ignore
54:         from .sources.base import SourceError
55:         valid = ", ".join(sorted(REGISTRY.keys()))
56:         raise SourceError(source_id, f"unknown source (valid: {valid})")
57:
58:     def _list_sources(*, json: bool = False):  # type: ignore
59:         return {}
```

**结论：这不是合理的降级，而是掩盖真实失败的反模式。**

**(a) 回退分支自身就是坏的。** `cli.py:54` 在函数体内 `from .sources.base import SourceError`。但若 `sources` 包因**根本性损坏**（`base.py` 语法错误、导入链断裂）而失败，`sources.base` 同样不可导入 —— 回退路径会在**被调用时**再次 `ImportError`，而不是给出诊断。真正的优雅降级应连 `SourceError` 都不依赖。

**(b) 捕获范围过大。** `except ImportError` 吞掉 `sources` **整棵导入树**的任意 `ImportError`，包括 `sources/__init__.py:61-65` eager import 中任一模块的拼写错误，以及**循环导入**失败（`sources/__init__.py:61-65` 与各源模块 `from . import _register_if`，如 `wy.py:254`，构成循环）。Python 中循环导入的典型失败模式恰好就是 `ImportError`（partially initialized module）—— 正是被吞掉的那一类。

**(c) 后续影响会连锁扩散。** 一旦 `REGISTRY = {}`：
- `lx source list` 打印 `# 0 sources registered`（`cli.py:1103`）并**以 exit 0 成功退出**；
- `cli.py:1109-1114` 的 `for _sid, _src in REGISTRY.items()` 不生成任何子命令 → `lx source kg ...` 报 "No such command"；
- `cli.py:1122` 的 `click.Choice(sorted(REGISTRY.keys()))` 变成**空 Choice** → `lx search` 对任何 `--source` 值都报参数错误。

即：**一个源模块 import 失败，会伪装成"所有源集体消失"**，且以成功状态码返回。

**(d) 回退的错误消息无价值。** `cli.py:55` 在 `REGISTRY` 为空时构造 `"unknown source (valid: )"` —— 空的 valid 列表，对排障零帮助。

**(e) 零日志/零警告。** 无 `warnings.warn`、无 stderr 输出、无退出码信号。使用者（尤其 AI agent）**无法区分**"正常但源为空"与"导入炸了"。

**修复**：让 `ImportError` 直接传播，或至少在回退时向 stderr 打印明确警告并把标志位暴露给 `source list`。

### 2.3 `import asyncio` 位于文件中部（已确认）

**精确行号：`cli.py:1215`**：

```python
1213: # Need asyncio for the write commands. Lazy import at module top is awkward
1214: # because click commands are sync; the helpers above use asyncio.run().
1215: import asyncio  # noqa: E402
```

**位置**：`sync_status` 命令结束之后（`cli.py:1210`）、`main()` 之前（`cli.py:1220`）。

**实际影响**：
- `asyncio` 在 `cli.py:838`（`_run_async` 内）与 `cli.py:1188`（`sync_auth` 内 `asyncio.run(go())`）被使用。两处都在**函数体内**，运行时（模块已完全加载）能找到模块级名字 —— **功能上正常，当前不会 `NameError`**。
- 但这是**执行顺序耦合**：`cli.py:1188` 的可用性依赖同文件更下方（1215 行）的语句。

**为什么它仍是问题**：

1. **注释与事实矛盾**：`cli.py:1213-1214` 说 "Lazy import at module top is awkward"。但 `import asyncio` 就在**模块顶层**（只是位置靠后），不是 lazy import —— 真正的 lazy import 应写在函数体内。注释描述的是一个并未采用的方案。
2. **位置任意**：它被放在 `sync` 相关代码之后，看起来像"sync 专用"，但 `asyncio` 与 sync 无关，且 `_run_async`（`cli.py:836`）在它**之前 379 行**就已引用 `asyncio`。
3. **`# noqa: E402`** 是**主动抑制告警**：作者知道它违规并选择沉默，而非修正。
4. **重构陷阱**：任何"拆分 `cli.py`"的动作都必须记得搬运这个 import。`sync_client.py:62` 就正确地在顶部 import 了 `asyncio` —— 同一项目两种做法。

### 2.4 死代码清单（已确认）

| 符号 | 定义位置 | 证据 |
|---|---|---|
| **`_run_async`** | `cli.py:836-838` | 全仓 grep 仅命中定义处与内部 `asyncio.run`（`cli.py:838`）。**无任何调用方。** `sync_auth`（`cli.py:1188`）直接调 `asyncio.run(go())` 绕过了它 —— 说明这个 wrapper 当初正为解决 §2.3 的 import 问题而写，最终未被采用。 |
| `_j` 第 1 次 | `cli.py:109-111` | 被 `cli.py:185-187` 覆盖，不可达。 |
| `_jp` 第 1 次 | `cli.py:104-106` | 被 `cli.py:114-116` 覆盖，不可达。 |
| `_j` 第 2 次 | `cli.py:185-187` | 无 `@_j` 使用点。 |
| `_pc` | `cli.py:99-101` | 仅在 `cli.py:116` 被内部使用；无命令直接 `@_pc`。属近乎无用的间接层。 |
| **`music_reorder`** | `db_writer.py:210-229` | **无 CLI 调用方**（grep `cli.py` 无引用）。 |
| **`music_move`** | `db_writer.py:232-305` | **无 CLI 调用方**。 |
| `wy` back-compat 包装 | `wy.py:236-251` | `search_songs`/`get_song_info`/`get_album` 无 CLI 调用方；仅 `tests/sources/test_wy.py:25-29` 用 `callable()` 断言存在性（**只验证存在、不验证行为**）。 |
| `available_features()` | `sources/__init__.py:51-55` | 返回所有源 feature 的**并集**，看似为多源调度准备，但**全仓无生产调用方**（仅 `tests/sources/test_registry.py:29-32` 使用）。为不存在的功能预留。 |
| `LIST_TABLES` | `paths.py:117-121` | 注释称"Kept here so db.py doesn't need to hardcode the list"（`paths.py:115-116`），但 **`db.py` 从未导入或使用它**。 |
| `db.connect(read_only=False)` 分支 | `db.py:27-28` | docstring 称 "used by backup / dry-run tooling"（`db.py:6-7`），但 `backup` 走 `shutil.copy2`（`cli.py:505`）不经 `db.py`。**无任何调用方传 `read_only=False`。** |
| `_portable_candidates` 循环 | `paths.py:69-71` | **不可达死分支**：`paths.py:64-68` 已检查完全相同的路径，而 `_portable_candidates`（`paths.py:48-54`）只 yield 这一个候选。docstring 自己承认这一点。 |
| `cmd_name = feature.replace("_", "-")` | `cli.py:1044` | `_FEATURE_SIG` 全部 10 个 feature 名**都不含下划线**，此转换**永不做任何事**。 |
| `src/lx_cli/tests/mock_sync_server.py` | 421 行 | 与 `tests/mock_sync_server.py`（401 行）重复；测试只 import 后者。 |
| `_schema.py`（仓库根） | — | 未被 `src/` 任何模块 import。 |

### 2.5 命名不一致

#### (a) 命令回调名 vs 暴露名

Click 在 `@cli.command()` 无参数时把函数名转成命令名。作者用 `_cmd` 后缀避免与函数体内调用的同名函数冲突：

| 函数名 | 行号 | 暴露命令 | 冲突的导入 |
|---|---|---|---|
| `play_cmd` | `cli.py:192-194` | `play` | `client.play`（`cli.py:35`） |
| `pause_cmd` | `cli.py:201-203` | `pause` | `client.pause`（`cli.py:34`） |
| `next_cmd` | `cli.py:225-227` | `next` | `client.skip_next`（**不同名，后缀多余**） |
| `prev_cmd` | `cli.py:234-236` | `prev` | `client.skip_prev`（**不同名，后缀多余**） |
| `seek_cmd` | `cli.py:243-246` | `seek` | `client.seek`（`cli.py:36`） |
| `collect_cmd` | `cli.py:341-343` | `collect` | `client.collect`（`cli.py:29`） |
| `uncollect_cmd` | `cli.py:350-352` | `uncollect` | `client.uncollect`（`cli.py:43`） |
| `is_running_cmd` | `cli.py:397-399` | `is-running` | `launcher.is_running` |
| `where_cmd` | `cli.py:458-460` | `where` | — |
| `backup_cmd` | `cli.py:477-482` | `backup` | — |
| `subscribe_cmd` | `cli.py:322-328` | `subscribe` | — |
| `source_list_cmd` | `cli.py:1093-1095` | `source list` | — |

对比**不加后缀**的：`toggle`(`cli.py:212`)、`volume`(`257`)、`mute`(`267`)、`status`(`280`)、`lyric`(`308`)、`start`(`368`)、`stop`(`388`)。

**规则不一致**：`volume` 与 `client.set_volume` 不同名故不加后缀（合理）；但 `next_cmd`/`prev_cmd` 调用的是 `skip_next`/`skip_prev`，**并不冲突**，后缀纯属复制粘贴惯性。**同一文件内两套命名约定并存**，重构时无法靠命名推断命令名。正确做法是显式命名 `@cli.command("play")` + `def play(...)`（`cli.py:322` 的 `@cli.command("subscribe")` 与 `cli.py:397` 的 `@cli.command("is-running")` 就是这么做的，**同一文件里存在两种风格**）。

#### (b) `_FEATURE_SIG` / `_FEATURE_HELP` / `_FEATURE_LIMITS` 三元组并行

| dict | 行号 | 键数 |
|---|---|---:|
| `_FEATURE_SIG` | `cli.py:983-994` | **10** |
| `_FEATURE_HELP` | `cli.py:996-1007` | **10** |
| `_FEATURE_LIMITS` | `cli.py:1009-1010` | **6** |

三个 dict 用**同一组字符串键**描述**同一对象的三个属性** —— 典型 parallel-array anti-pattern：新增 feature 必须同步改三处，漏改不报错。

**且三者键集合已经不一致**：`_FEATURE_LIMITS` 只有 6 个键（`search`/`songlist`/`comment`/`singer`/`leaderboard`/`tip`）。`cli.py:1050-1051`：

```python
if "--limit" in sig["opts"]:
    kwargs["limit"] = kwargs.get("limit") or _FEATURE_LIMITS[feature]
```

依赖"凡 `sig["opts"]` 含 `--limit` 的 feature，`_FEATURE_LIMITS` 必有"这一**无断言保护的隐性契约**。经核对当前 10 项 SIG 中带 `--limit` 的恰为上述 6 项，**目前恰好成立**。但 `cli.py:1076` 生成 `--limit` help 时同样直接索引 `_FEATURE_LIMITS[feature]` —— 若给 `album` 加 `--limit`，会立刻 `KeyError` 崩溃。

**修复**：合并为单一 `dict[str, FeatureSpec]`（dataclass），让缺项在定义期报错。

### 2.6 `playlist export` 无视 `--json` 语义（已实测确认）

`cli.py:717-735`：

```python
717: @playlist.command("export")
718: @click.argument("list_id")
719: @click.option("--out", "-o", "out_path", default=None, ...)
721: @_jp
722: def playlist_export(ctx, list_id, out_path):
723:     """Export a playlist (info + songs) as JSON."""
724:     info = db_mod.get_list(list_id, ...)
727:     songs = db_mod.songs_in_list(list_id, ...)
728:     payload = {"list": info, "songs": songs,
                  "exported_at": __import__("datetime").datetime.now().isoformat()}
729:     text = json.dumps(payload, ensure_ascii=False, indent=2)
730:     if out_path:
731:         Path(out_path).write_text(text, encoding="utf-8")
732:         if not _is_json(ctx):
733:             click.echo(f"wrote {out_path}  ({len(songs)} songs)")
734:     else:
735:         click.echo(text)          # ← 无 _is_json 分支
```

**实测结果**（探针 `audit_json2.py`，真实 list id `kg_7b8006eaa1afd301b59c111e083a5863`）：

| 命令 | stdout | 是 JSON？ |
|---|---|---|
| `lx playlist export <id>` | JSON 对象 | **是** |
| `lx playlist export <id> --json` | **逐字节相同** | 是 |
| `lx playlist export <id> -o f --json` | `wrote f (N songs)` | **否** |
| `lx playlist export <id> -o f` | `wrote f (N songs)` | 否 |

**三重问题**：

1. **`--json` 在该命令上是空操作** —— 有无 `--json`（stdout 路径）输出**逐字节相同**。人类模式本应打印表格/摘要。
2. **`--json -o <file>` 时 stdout 输出纯文本**（`cli.py:732-733` 的 `if not _is_json` 抑制了 JSON 分支，`cli.py:735` 的 else 不执行）—— **`--json` 契约下拿到非 JSON**。这是 §3 中最严重的契约违约。
3. **`-o` 路径下无任何机器可读确认载荷** —— 不像其它写命令返回 `{"id":..., "deleted": true}` 这样的结构。

**对比**：同组的 `playlist show`（`cli.py:648-663`）human 模式输出 `# 名称 (id) N song(s)` + 缩进列表，`--json` 才切 JSON。**同一 `playlist` 组内两个语义高度相近的命令，`--json` 行为相反。**

**附加**：`exported_at` 用 `__import__("datetime").datetime.now().isoformat()` 内联动态 import，与同文件 `cli.py:489` 的 `import datetime, shutil` 风格矛盾，且产生**非 UTC、无时区后缀**的本地时间。`export` 的 payload 与 `playlist show --json`（`cli.py:649`）结构几乎相同但不完全一致（前者多 `exported_at`）。

### 2.7 其他缺陷

#### (a) `subscribe` 的 `--json` 是空操作

`subscribe_cmd`（`cli.py:322-336`）挂了 `@_jp`（`cli.py:327`），但函数体（`cli.py:332-336`）**无条件** `click.echo(json.dumps(evt, ensure_ascii=False))`，全文**没有 `_is_json` 判断**。human 模式下也在刷 JSON 行。与 §2.6 同属"装饰器挂了但没用"。

#### (b) `lyric --all` 在 human 模式输出 JSON

`cli.py:308-319`：

```python
311: if all_variants:
312:     payload = get_lyric_all(_ep(ctx))
313:     _emit(ctx, json.dumps(payload, ensure_ascii=False, indent=2), payload)
```

`_emit` 的 `human` 参数被传入了一个 **JSON 字符串**（`cli.py:313`）—— human 模式实际吐 JSON，`--json` 无差别。

**另**：`lx lyric --json` → `{"lyric": "<text>"}`（**包裹在 `lyric` 键下**，`cli.py:317`）；`lx lyric --all --json` → 服务端原始多键对象（`lyric`/`tlyric`/`rlyric`/`lxlyric`，**未包裹**）。两者**形状不同**，消费方无法统一取歌词。

#### (c) `source <src> tip` 的 human 输出是 Python `repr()`

`_render`（`cli.py:1013-1038`）显式处理了 `lyric`/`song`/`album`/`hot`/`comment`/`leaderboard`/`search`/`songlist`/`singer`，但 **`tip` 不在任何分支**，落入 `cli.py:1038` 的 `return str(result)`。

`tip` 返回 `list[SongRecord]`，故 human 输出为：

```
[SongRecord(songmid='...', name='...', singer='...', ...), ...]
```

**既非人类可读、也非 JSON** —— 是对 dataclass 列表的 `str()`。这是明确的渲染遗漏（`_FEATURE_HELP["tip"]` 存在，说明 tip 是被正式支持的 feature）。

#### (d) `client.subscribe_player_status` 的 idle 超时逻辑失效

`client.py:129-138`：

```python
129: last_activity = time.monotonic()
131: while True:
132:     chunk = resp.readline()          # ← 阻塞点
133:     if not chunk:
134:         break
136:     if time.monotonic() - last_activity > idle_timeout:
137:         break
138:     last_activity = time.monotonic()
```

检查发生在 `readline()` **之后**。若服务端静默不发数据，`readline()` 会一直阻塞（由 `client.py:123` 的 `urlopen(timeout=idle_timeout)` socket 超时兜底），`client.py:136` 的检查只在**收到数据之后**才可能触发——而一旦收到数据就立即刷新 `last_activity`（`client.py:138`），使该分支几乎不可能为真。

**结论**：函数文档（`client.py:114-115`）声称的 "Stops if ... `idle_timeout` seconds pass without bytes" **无法由 `client.py:136` 实现**，实际由 `client.py:123` 的 socket timeout 部分兜底。文档与实现不符。

#### (e) `_resolve_song_meta` 忽略 `list_id`，可写入错误元数据（**静默数据缺陷**）

`cli.py:822-833`：

```python
822: def _resolve_song_meta(db_e, list_id: str, song_id: str) -> dict[str, Any]:
823:     """Look up a song's metadata from any list, since ``my_list_music_info``
824:     is denormalized — we just need name/singer/source/interval/meta."""
826:     rows = db_mod.query(
827:         "SELECT id, listId, name, singer, source, interval, meta "
828:         "FROM my_list_music_info WHERE id = ? LIMIT 1",   # ← list_id 未参与查询
829:         [song_id], exe_path=db_e,
830:     )
831:     if not rows:
832:         raise click.UsageError(f"song id not in any list: {song_id!r}")
833:     return rows[0]
```

签名收 `list_id` 但 SQL 里没有它；调用方 `cli.py:942` 仍传 `list_id`。

**实测确认**（探针 `audit_dup_id.py`）：真实 DB 中**同一 `id` 确实跨多个 list 出现**（`83252353_AFB15305C3E3FAE258200F9A3525892B` 出现在 **4 个** list）。`LIMIT 1` 无 `ORDER BY`，返回哪一行由 SQLite 物理存储顺序决定。我构造了同一 `id` 在 A、B 两 list 中元数据**不同**的场景，探针输出：

```
resolved: {'id': 'dup_shared_id', 'listId': 'userlist_dup_A',
           'name': 'NameInA', 'singer': 'SingerA', 'source': 'kg'}
```

即取到了 A 的行。由于 `my_list_music_info` 是按 list 反规范化的（同一 `id` 在不同 list 里 `name`/`singer`/`source` 可以不同），**顺序变化即取到另一 list 的元数据**。

**后果**：`playlist add B <id>` 时可能把 **A 的 singer/source 写进 B**；且 `--source` 校验（`cli.py:943-946`）基于**错误的行**判断，导致本应放行的被拒、本应拒绝的放行。

#### (f) 虚拟列表 `default`/`love` 能 list、不能 show

`db.py:87-106` 用 `UNION ALL` 合成 `default`/`love` 虚拟行，但带 `HAVING song_count > 0`（`db.py:98`、`db.py:104`）。而 `get_list`（`db.py:110-118`）查 `my_list`，**虚拟列表无对应行**。

**实测**：`lx playlist list` 列出 `default`（探针确认 `virtual lists in output: ['default', 'love']`），但 `lx playlist show default` → `Error: no such list: default`（exit 1）。**列表能看见却无法 show/export** —— 对 AI agent 是明确的可用性陷阱。

#### (g) `songs_in_list` 的 `COALESCE(o."order", 0)` 缺 tie-breaker

`db.py:138`：`ORDER BY COALESCE(o."order", 0) ASC`。

若某歌**有** order 行且值为 0，与**无** order 行（`NULL`→0）**排序位置相同**，两者相对顺序未定义。实测 fixture 中无孤儿行（探针确认 orphan 数为 0），故**当前无害**；但这是**静默错序的隐患**。正确写法应是 `ORDER BY (o."order" IS NULL), o."order"`。

#### (h) `find_songs` 的通配符未转义

`db.py:158-159`：`(LOWER(name) LIKE ? OR LOWER(singer) LIKE ?)`，参数为 `f"%{pattern.lower()}%"`。

用户搜 `50%` 或 `_` 会被当作 LIKE 通配符 —— 匹配范围被**静默放大**。这是功能性缺陷而非注入（参数化正确）。另注：`LOWER()` 在 SQLite 中对非 ASCII 不生效，但中文无大小写，**实际无害**。

#### (i) `stats` 硬编码表名，缺表即崩溃

`db.py:191-193` 直接引用 `download_list`、`dislike_list`、`lyric` 三表，**无 try/except**。若用户 DB 缺其中任一表，整个 `playlist stats` 崩溃（且 SQLite 异常未被 `cli.py` 包装，见 §5.6）。fixture 中三表存在。

#### (j) `rank_songs` 的 bare column 不确定

`db.py:214-221`：`SELECT m.id, m.name, m.singer, m.source, m.interval, COUNT(DISTINCT m.listId) ... GROUP BY m.id`。

`GROUP BY m.id` 后 SELECT 了非聚合列 `name`/`singer`/`source`/`interval` —— SQLite 允许，会**任取组内一行的值**。因同一 `id` 跨 list 的元数据可能不同（已由 §2.7e 证实），**返回的 `name`/`singer` 是不确定的**。

---

## 3. `--json` 契约全表

**机制**：`--json` 经 `_json_callback`（`cli.py:67-78`）写入 `ctx.obj["json"]`，由 `_is_json(ctx)`（`cli.py:119-120`）读取。该设计**正确**处理了 group 级 + 子命令级双 `is_eager` 回调的顺序问题（`cli.py:70-73` 的 docstring 解释得当），`--json` 可置于命令前后任一处。

**但输出路径不统一**：`_emit(ctx, human, payload)`（`cli.py:150-154`）是唯一"正确"出口，实际存在**三种写法**并存 —— 用 `_emit`（正确）、手工 `if _is_json` 分支（等价但样板重复）、**完全不检查**（违约）。

### 3.1 全命令契约表

图例：✅ 一致；⚠️ 可用但形状特殊；❌ 违约。

| # | 命令 | 定义行 | human 输出 | `--json` 顶层 | 状态 |
|---|---|---|---|---|---|
| 1 | `play` | `cli.py:194` | `OK` | `{"action":"play"}` | ✅ |
| 2 | `pause` | `cli.py:203` | `OK` | `{"action":"pause"}` | ✅ |
| 3 | `toggle` | `cli.py:212` | `OK (play\|pause)` | `{"action":"play"\|"pause"}` | ✅ |
| 4 | `next` | `cli.py:227` | `OK` | `{"action":"skip-next"}` | ✅ |
| 5 | `prev` | `cli.py:236` | `OK` | `{"action":"skip-prev"}` | ✅ |
| 6 | `seek <off>` | `cli.py:246` | `OK (seek 30.0s)` | `{"action":"seek","offset":30.0}` | ✅ |
| 7 | `volume <n>` | `cli.py:257` | `OK (volume 50)` | `{"action":"volume","volume":50}` | ✅ |
| 8 | `mute on\|off` | `cli.py:267` | `OK (mute on)` | `{"action":"mute","mute":true}` | ✅ |
| 9 | `status` | `cli.py:280` | 一行摘要 | 服务端原始 status 对象 | ⚠️ **schema 随 `--filter` 变化**；空时 human `(no data)` vs JSON `{}` |
| 10 | `lyric` | `cli.py:308` | 歌词纯文本 | `{"lyric":"<text>"}`（**无 indent**，`cli.py:317`） | ⚠️ 缩进与其它命令不一致 |
| 11 | `lyric --all` | `cli.py:308` | **JSON（indent=2）** | 服务端多键对象 | ❌ **human 吐 JSON**；与 #10 形状不同 |
| 12 | `subscribe` | `cli.py:328` | **NDJSON 事件流** | 同 human（**每行一个 JSON**） | ❌ **`--json` 无作用**；是 JSONL 非 JSON |
| 13 | `collect` | `cli.py:343` | `OK` | `{"action":"collect"}` | ✅ |
| 14 | `uncollect` | `cli.py:352` | `OK` | `{"action":"uncollect"}` | ✅ |
| 15 | `start` | `cli.py:368` | `started` / `already running` | `{"running":true,"hidden":true}` | ✅ |
| 16 | `stop` | `cli.py:388` | `stopped` / `stop failed` | `{"running":bool}` | ❌ **失败仍 exit 0**；无 success 字段 |
| 17 | `is-running` | `cli.py:399` | `yes` / `no` | `{"running":bool}` | ✅ |
| 18 | `config show` | `cli.py:414` | 3 行 `key: value` | `{"enable":false,"port":"23330","bindLan":false}` | ✅（`port` 是**字符串**） |
| 19 | `config enable` | `cli.py:430` | `enabled (port=...)` | 完整 settings 对象 | ✅ |
| 20 | `config disable` | `cli.py:441` | `disabled` | 完整 settings 对象 | ✅ |
| 21 | `config port <p>` | `cli.py:450` | `port=23330` | 完整 settings 对象 | ✅ |
| 22 | `where` | `cli.py:460` | 5 行 `key: path` | `{user_data_dir, lx_datas_dir, data_json, config_v2, db}` | ✅ |
| 23 | `backup <dir>` | `cli.py:482` | `wrote <dir>` + 文件列表 | `{"backup_dir",...,"files":[...]}` | ✅ |
| 24 | `db tables` | `cli.py:537` | 每行一个表名 | `{"tables":[...]}` | ⚠️ 包了一层而非裸数组 |
| 25 | `db info` | `cli.py:587` | 2 列文本 | `{"tables":{name:count}}` | ✅ |
| 26 | `db schema <t>` | `cli.py:565` | 缩进列清单 | **array** `[{cid,name,type,notnull,dflt_value,pk}]` | ✅ |
| 27 | `db query "<sql>"` | `cli.py:546` | 表头 + `---` + 竖线行 | **array** `[{col:val}]` | ⚠️ human 把 `None` 渲染为 `"None"`（`cli.py:559`），JSON 保留 `null` |
| 28 | `playlist list` | `cli.py:610` | 列表格 | **array** `[{id,name,source,sourceListId,position,locationUpdateTime,song_count,implicit}]` | ✅ |
| 29 | `playlist show <id>` | `cli.py:640` | `# 名称 (id) N song(s)` + 行 | `{"list":{...},"songs":[{id,listId,name,singer,source,interval,meta,order}]}` | ⚠️ `songs` 含内部 `"order"` 字段 |
| 30 | `playlist find <pat>` | `cli.py:674` | `# N match(es)` + 行 | **array** | ✅ |
| 31 | `playlist stats` | `cli.py:695` | `Totals:` 块 | `{"totals":{...},"songs_by_source":{...},"distinct_songs":N}` | ✅ |
| 32 | **`playlist export <id>`** | `cli.py:722` | **JSON 内容** | 同 human（**逐字节相同**） | ❌ **human 吐 JSON；`--json` 空操作** |
| 33 | **`playlist export <id> -o f`** | `cli.py:722` | `wrote f (N songs)` | **同一行文本（非 JSON）** | ❌ **`--json` 下输出非 JSON** |
| 34 | `playlist dislikes` | `cli.py:740` | 行 `[type] content` | **array** `[{type,content,meta}]` | ✅ |
| 35 | `playlist rank` | `cli.py:757` | 列表格 | **array** | ✅ |
| 36 | `playlist list-rank` | `cli.py:783` | 列表格 | **array**（**已截断到 limit**，`cli.py:787`） | ⚠️ human 与 JSON 均截断，但无 total 字段 |
| 37 | `playlist downloads` | `cli.py:805` | 行 `[status] prog fileName` | **array** `[{...,musicInfo,...}]` | ⚠️ `musicInfo` 是**未解析的 JSON 字符串** |
| 38 | `playlist create <name>` | `cli.py:863` | `created <id> ('name')` + note | `{id,name,source,sourceListId,position,locationUpdateTime}` | ⚠️ note 丢失 |
| 39 | `playlist rename <id> <new>` | `cli.py:886` | `renamed ...` + note | `{"id":...,"name":...}` | ⚠️ 键集与 #38 不同 |
| 40 | `playlist delete <id>` | `cli.py:907` | `deleted <id>` + note | `{"id":...,"deleted":true}` | ✅ |
| 41 | `playlist add <id> <sids>...` | `cli.py:931` | `added N song(s) to <id>` + note | `{"list_id":...,"added":N}` | ⚠️ **`list_id` 下划线** vs `listId` camelCase |
| 42 | `playlist remove <id> <sids>...` | `cli.py:964` | `removed N song(s) from <id>` + note | `{"list_id":...,"removed":N}` | ⚠️ 同上 |
| 43 | `source list` | `cli.py:1095` | `# N sources registered` + 行 | `{"<sid>":{"id","name","features":[...],"boards":[...]}}` | ⚠️ **以 source id 为键的 map**，非数组 |
| 44 | `source <src> search` | `cli.py:1041` | `# N result(s) page p/ap src=x` + 行 | `SearchResult.to_json()` | ✅ |
| 45 | `source <src> album` | `cli.py:1041` | `# 名称 (艺术家) — N 首 id=xx` | `AlbumInfo.to_json()` | ✅ |
| 46 | `source <src> song` | `cli.py:1041` | `# 名 - 歌手 [时长] src=x` | `SongRecord.to_json()` | ✅ |
| 47 | `source <src> leaderboard` | `cli.py:1041` | 编号行 | `SearchResult.to_json()` | ✅ |
| 48 | `source <src> hot` | `cli.py:1041` | `  kw  (score)` | **array** `[{keyword,score}]` | ✅ |
| 49 | `source <src> songlist` | `cli.py:1041` | 同 #44 | `SearchResult.to_json()` | ✅ |
| 50 | `source <src> comment` | `cli.py:1041` | `[author] content` | **array** `[{author,content,time}]` | ✅ |
| 51 | `source <src> singer` | `cli.py:1041` | 同 #44 | `SearchResult.to_json()` | ✅ |
| 52 | `source <src> lyric` | `cli.py:1041` | `lrc` 文本 | `{"lrc":...,"tlyric":...}` | ⚠️ 走 `cli.py:1065-1067` 兜底分支（**返回裸 dict 而非 dataclass**），是 `to_json` 协议的唯一例外 |
| 53 | **`source <src> tip`** | `cli.py:1041` | **Python `repr()` 列表** | `[SongRecord.to_json()]` | ❌ **human 既非人类可读也非 JSON** |
| 54 | `search <kw> --source <s>` | `cli.py:1127` | 同 #44 | `SearchResult.to_json()` | ✅ |
| 55 | `sync auth <url>` | `cli.py:1146` | `saved key ... device=...` | `{"server_id","device_name"}` 或 `{"server_id","method":"key"}` | ⚠️ **两种形状** |
| 56 | `sync status` | `cli.py:1193` | 行（key **已掩码**，`cli.py:1208`） | `{"<serverId>":{clientId,key,serverName}}` | ❌ **明文输出完整 AES key**（`cli.py:1199`） |

### 3.2 契约层面的重点问题

**A. 顶层类型在 object 与 array 之间摆动。** 56 条中约 15 条是裸 array（`db schema/query`、`playlist list/find/dislikes/rank/list-rank/downloads`、`source hot/comment/tip`），其余是 object。agent 必须逐命令记忆。

**B. 键命名混用两套约定。** `list_id`（`cli.py:954`、`cli.py:974`）vs `listId`（DB 列名，`db.py:132`、`cli.py:649` 透传）；`albumName`/`albumId`（DB 风格，`base.py:41-42`）vs `distinct_songs`/`in_lists`/`songs_by_source`（Python 风格，`db.py:216`、`db.py:196`）。**同一 CLI 内三种命名约定。**

**C. `sync status --json` 明文泄露 AES key（安全回退）。** human 模式**主动掩码**（`cli.py:1208`：`masked = info.key[:4] + "..." + info.key[-4:]`），但 `--json` 走 `info.to_json()`（`cli.py:1199`）输出**完整密钥**。**机器可读模式比人类模式泄露更多**。任何把 `lx sync status --json` 输出喂进日志/LLM 的流程都会泄露同步凭据。

**D. 写命令的 5 处 `note:` 行在 `--json` 下被完全丢弃。** `cli.py:877-878`、`899-900`、`918-919`、`955-956`、`975-976`。该写法**本身正确**（`--json` 时抑制额外文本，保持 stdout 是纯 JSON），但这条 note 是**关键操作语义**（"写入仅本地，未同步"），在 `--json` 下应降级为结构化字段（如 `"sync_propagated": false`）而非丢弃。

**E. `stop` 的失败无法与成功区分。** `cli.py:390-394`：`ok=False` 时只打印 "stop failed"，**不 raise**，退出码 `0`；JSON 为 `{"running": not ok}`，**无 success 字段**。

**F. `--json` 缩进风格不统一。** 多数命令 `indent=2`，但 `lyric`（`cli.py:317`）与 `subscribe`（`cli.py:334`）**无缩进**。非致命，但说明缺少统一的 `_emit_json`。

**G. `sync_client` 用 `print()` 污染 stdout。** `sync_client.py:569`、`sync_client.py:575` 直接 `print()` 到 **stdout**。`sync auth` 会建立 WebSocket（`cli.py:1152-1188`），若这些路径触发，`--json` 的 JSON 流会被 `[sync] ...` 行**污染**，解析失败。

---

## 4. Sources 子系统

### 4.1 `SongRecord.to_json()` 精确字段

`base.py:36-48`：

```python
def to_json(self) -> dict[str, Any]:
    return {
        "songmid":    self.songmid,
        "name":       self.name,
        "singer":     self.singer,
        "albumName":  self.album_name,
        "albumId":    self.album_id,
        "source":     self.source,
        "interval":   self.interval,
        "types":      list(self.types),
        "img":        self.img,
        "extra":      dict(self.extra),
    }
```

**共 10 个字段**（dataclass 定义 `base.py:23-34`）。

| 键 | 类型 | 说明 |
|---|---|---|
| `songmid` | str | **语义逐源不同**（见下） |
| `name` | str | 歌曲名 |
| `singer` | str | 歌手，多值以 `、` 连接 |
| `albumName` | str | 专辑名（**camelCase**） |
| `albumId` | str | 专辑 id（**camelCase**） |
| `source` | str | `kg`/`kw`/`tx`/`mg`/`wy` |
| `interval` | str | `"m:ss"` 格式**字符串**（非秒数） |
| `types` | list[str] | 音质；**顺序在不同源/builder 间不一致** |
| `img` | str \| None | 封面 URL；**多数源为 `None`** |
| `extra` | dict | 源特有；**内容随源漂移** |

### 4.2 缺失字段分析（对照用户实际需要）

| 用户需要 | `to_json()` 有吗 | 实际情况 |
|---|---|---|
| **歌手 / 演唱者** | ✅ `singer` | **但分隔符逐源不同**：`kg.py:48` 用 `、` 连接 `Singers[].name`；`kw.py:97` 把 `&` 替换为 `、`；`tx.py:79`、`mg.py:48`、`wy.py:59` 同样用 `、`。无统一规范。 |
| **专辑名** | ✅ `albumName` | **但** `kg.py:132` 与 `mg.py:141` 的 `album()` 硬编码 `name="(unknown)"`。**即"专辑详情"接口返回的专辑名是假的。** |
| **专辑 id** | ✅ `albumId` | **但可用性极差**：`kg.py:56` 取 `AlbumID`/`album_id`，而 `song_search_v2` 响应**不含该字段** → 恒为空串，而 `KgSource.album()`（`kg.py:122`）需**数字 albumid**，故 **`kg search` 的 `albumId` 无法喂给 `kg album`**；`tx.py:94` 取 `album.mid`，但 `TxSource` **根本没实现 `album`**（`tx.py:105-106` 无该 feature）；仅 `mg.py:62` 与 `MgSource.album`（`mg.py:133`）一致 ✅。 |
| **source id** | ✅ `source` | 5 个源全部与 `REGISTRY` key 一致 ✅。 |
| 时长 | ✅ `interval` | **但语义不统一**：`mg.py:38-44` 有 `if secs > 10000: secs /= 1000` 的毫秒启发式，其余源（`kg.py:32`、`kw.py:74`、`tx.py:73`、`wy.py:52`）无此处理。同一字段在源之间可能一个是秒、一个是毫秒。 |
| 封面 | ⚠️ `img` | 仅 `mg.py:66` 与 `wy.py:77` 填充；`kg.py:59`、`kw.py:103`、`tx.py:97` **硬编码 `img=None`**。 |
| **歌手 id** | ❌ **无** | `singer` 命令需要它（`kg.py:207`、`tx.py:188`、`wy.py:214`），但 `SongRecord` 无此字段 → **搜到歌后无法查该歌手的热门歌曲**。 |
| 音质体积 | ❌ **无** | `types` 只有字符串。设计文档 `docs/design-2026-08-12-multi-source.md:105` 要求 `list[dict]` 含 `size`，实际是 `list[str]`。 |
| 版权/可播放标志 | ⚠️ 塞在 `extra` | 仅 mg 的 `copyrightId`（`mg.py:67`）。 |
| **可直接写入 DB 的 `id`** | ❌ **无** | **最关键缺失**，见 §5.4。 |
| **构造 DB `meta` 的能力** | ❌ **无** | DB 的 `meta` 是 JSON 字符串，含 `albumName`/`picUrl`/`qualitys`（实测见 §3.1 #29）。`SongRecord` 无 `meta` 字段。 |

**`songmid` 语义逐源差异**（同一字段承载不同东西）：

| 源 | `songmid` 实际值 | 引用 |
|---|---|---|
| kg | `Audioid` → `audio_id` → `songmid` → `hash` | `kg.py:49-50` |
| kw | `MUSICRID` 去掉 `MUSIC_` 前缀 | `kw.py:80` |
| tx | `mid` → `songmid` → `str(id)` | `tx.py:89-90` |
| mg | `songId` → `id` | `mg.py:58` |
| wy | `str(id)`（数字） | `wy.py:69` |

**`extra` 内容随源漂移**：`kg` 放 `{"hash","audio_id"}`（`kg.py:60-63`）；`tx` 放 `{"media_mid"}`（`tx.py:98`）；`mg` 放 `{"copyrightId"}`（`mg.py:67`）；**`kw`（`kw.py:103`）与 `wy`（`wy.py:78`）为空 `{}`**。2/5 为空，agent 无法依赖。

**已知的 kg 参数语义冲突**：`kg.py:49-50` 的 `songmid` **优先取 `Audioid`**，但 `KgSource.song(song_id)`（`kg.py:96`）的 body 是 `{"hash": song_id, ...}` —— **需要 hash**。因此从 `kg search` 拿到的 `songmid` **喂给 `kg song` 会失败**。

### 4.3 多源 fan-out 搜索：**确认不存在**

**结论：不存在任何 fan-out / 跨源聚合搜索。已确认。**

证据：

1. **`lx search` 的 `--source` 是 `required=True` 且 `click.Choice`**（`cli.py:1121-1123`）—— **单选、必填**。不能传多个源，不能省略。
2. `search_cmd` 函数体（`cli.py:1130-1132`）：`src = get_source(src_id)` → `r = src.search(...)` —— **只查一个源，无循环**。
3. **没有任何模块 import 多个源做聚合。** 全仓 grep `REGISTRY` 的生产消费点只有三处：`cli.py:1109`（生成命令组）、`cli.py:1122`（Choice 校验）、`cli.py:49`（import），加上 `sources/__init__.py` 自身的 `list_sources`/`available_features`。**不存在 `search_all`/`aggregate`/`fan_out` 之类的函数。**
4. `SourceBase` 协议（`base.py:121-165`）**无任何跨源方法**。
5. `available_features()`（`sources/__init__.py:51-55`）返回所有源 feature 的**并集**，看似为多源调度准备，但**全仓无生产调用方**（§2.4）。
6. `docs/SOURCES.md:35` 只写 `lx search <keyword> --source <src>` 等价于 `lx source <src> search` —— **文档也未声称支持多源**。

**注意区分**：`playlist find --source`（`cli.py:668`）是 `multiple=True`，但它过滤的是**本地 DB 的 `source` 列**（`db.py:163-168`），**不是**跨源在线检索。这两者极易混淆。

**后果**："从多个平台同时找一首歌"需调用方自己循环 5 次并手工去重，而 5 个源的 `songmid` 语义又各不相同（§4.1）。

### 4.4 `bd`（百度）源：**确认不存在**

**结论：不存在。已确认。**

证据：

1. `sources/__init__.py:61-65` 的 eager import **只有五行**：`wy`、`kg`、`kw`、`tx`、`mg`。**无 `bd`。**
2. `sources/` 目录下**无 `bd.py`**（目录清单确认：`__init__.py`、`base.py`、`http.py`、`kg.py`、`kw.py`、`mg.py`、`tx.py`、`wy.py`）。
3. `tests/sources/test_registry.py:8` **断言式固定**了这一点：`assert set(REGISTRY.keys()) == {"kg", "kw", "tx", "mg", "wy"}` —— 任何试图加 `bd` 源的动作都会让该测试失败。
4. `docs/SOURCES.md:3` 与 `README.md:111` 均明确写"5 个音乐源（kg/kw/tx/mg/wy）"。
5. grep `bd|baidu|百度` 于 `src/lx_cli/` → **零命中**（仅命中无关的 `lambda`/`boards` 单词）。

**结论确认**：LX 桌面端 `src/renderer/utils/musicSdk/` 含 `bd`，但 lx-cli **只移植了 kg/kw/tx/mg/wy**。设计文档未解释为何排除 `bd` —— 这是一个**未记录的覆盖缺口**，不是 bug。

（仓库根的 `scripts/lxsrc_probe.js` 等探测脚本内容未读取，故无法判断 `bd` 是否曾在探测阶段被考虑 —— **标记为不确定**。）

### 4.5 HTTP 重复 / 重试 / 超时 / 代理

**统一层 `sources/http.py`**：

| 维度 | `request_json` / `request_form` | `request_text` |
|---|---|---|
| 定义 | `http.py:65-79` / `http.py:82-90` | `http.py:93-103` |
| 是否走 `_attempt` | ✅ 是（`http.py:27-62`） | ❌ **否，独立实现** |
| 重试 | ✅ 3 次（`http.py:18`、`http.py:30`） | ❌ **无重试** |
| 无退避 | ✅ 无 `sleep` | — |
| JSON 解析失败重试 | ✅（`http.py:36-40`） | N/A |
| 4xx | ✅ 立即抛、不重试（`http.py:41-49`） | 抛 `SourceError`（`http.py:99-101`） |
| 捕获 `TimeoutError`/`OSError` | ✅（`http.py:53-55`） | ❌ **不捕获** |
| UA 注入 | ✅ `setdefault`（`http.py:23`） | ✅（同一 `_build_request`） |
| 代理 | ❌ 无 | ❌ 无 |

**逐源使用情况**：

| 源 | 使用函数 | 重试 | 特殊处理 |
|---|---|---|---|
| `kg` | `request_json`（8 处） | ✅ | `_KG_HEADERS`（`kg.py:16-21`）；POST + JSON body（`kg.py:91-106`） |
| **`kw`** | **`request_text`（8 处：`kw.py:122,133,161,173,195,210,224,233`）** | ❌ **无** | 单引号 JSON 状态机 `_parse_kuwo_json`（`kw.py:27-71`） |
| `tx` | `request_json`（2 处） | ✅ | `zzcSign` SHA1 签名（`tx.py:29-36`）；两套端点（`tx.py:51`/`tx.py:60`） |
| `mg` | `request_json`（8 处） | ✅ | MD5 签名 + 时间戳（`mg.py:77-84`）；硬编码 `_DEVICE_ID`/`_SIG_MD5`/`_SIG_SECRET`（`mg.py:19-21`） |
| `wy` | `request_form`（经 `_post_form`，`wy.py:44-49`） | ✅ | eapi AES-ECB 加密（`wy.py:36-41`） |

**关键发现**：

1. **`kw` 源完全没有重试。** 因酷我返回单引号 JSON 而必须用 `request_text`（`kw.py:16`），代价是丢掉整个重试机制。**`kw` 是唯一单次失败即整体失败的源。**
2. **`request_text` 不捕获超时**：`http.py:102-103` 只捕 `URLError`，**未捕获 `TimeoutError`/`OSError`**（对比 `_attempt` 在 `http.py:53-55` 已捕获）。故 `kw` 在 socket 超时时抛**未包装的原生 `TimeoutError`**，而非 `SourceError` —— `cli.py:1056-1057` 会兜住，但错误信息不含源标识，与其它源体验不一致。
3. **超时值无一处被覆盖**：grep 确认 `src/lx_cli/sources/` 下**没有任何调用**传入 `timeout=` 或 `max_attempts=`。所有源、所有接口硬编码 15s / 3 次。
4. **代理：完全没有。** grep `proxy|ProxyHandler|https_proxy` 于 `src/` → **零命中**（命中的两处是注释里的 "local proxy for popular"，`db.py:204` / `cli.py:760`，与网络无关）。`urllib.request.urlopen` **默认**会读 `HTTP_PROXY`/`HTTPS_PROXY` 环境变量（经 `getproxies()`），所以环境变量代理**意外可用**；但**无显式代理支持**：无 `--proxy` 参数、无 `ProxyHandler`、无 `NO_PROXY` 处理说明。（「未验证」：未实测环境变量代理是否真的作用于本 CLI 调用路径。）
5. **全仓共三套独立 HTTP 实现**：`sources/http.py`、`client.py:54-64` 的 `_http_get`、`sync_client.py:261-274` 的 `_http_get`，各自有独立的错误类型（`SourceError`/`LXError`/`SyncAuthError`）。修一个 bug 要改三处。
6. **`_parse_kuwo_json`（`kw.py:27-71`）是唯一手写词法状态机**，45 行处理单引号 JSON。这是**高风险代码**：`tests/sources/test_kw.py` 只通过 fixture **间接**走它，无直接单测，边界情况（嵌套引号、`'` 后跟 `}`）未验证。

### 4.6 各源测试 fixture 覆盖

| 源 | fixture 文件（大小） | 测试文件（测试数） | 已覆盖 feature | **零覆盖 feature** |
|---|---|---|---|---|
| `kg` | `kg_hot.json`(1.2KB)、`kg_search_yorushika.json`(72KB)、`kg_song_detail_sample.json`(5.2KB) | `test_kg.py`(4) | search、song、hot、metadata | **album, leaderboard, songlist, comment, singer**（5） |
| `kw` | `kw_album_sample.json`(5.6KB)、`kw_hot.json`(157KB)、`kw_search_yorushika.json`(137KB) | `test_kw.py`(6) | search、album、hot、tip、metadata、CLI tip | **song, leaderboard, songlist, comment, lyric**（5） |
| `tx` | `tx_hot.json`(824B)、`tx_search_yorushika.json`(247KB)、`tx_song_detail_sample.json`(6.8KB) | `test_tx.py`(4) | search、song、hot、metadata | **leaderboard, songlist, comment, singer, lyric**（5） |
| `mg` | `mg_hot.json`(154KB)、`mg_search_yorushika.json`(12KB) | `test_mg.py`(3) | search、hot、metadata | **album, song, leaderboard, songlist, comment, lyric**（6） |
| `wy` | `wy_search_yorushika.json`(35KB) —— **仅 1 个** | `test_wy.py`(3) | search、metadata、back-compat | **album, song, leaderboard, hot, songlist, comment, singer, lyric**（**8**） |

**汇总**：5 个源共声明 **42 个 (源 × feature) 组合**，其中**仅 12 个有 fixture 覆盖（28.6%）**，**30 个（71.4%）零覆盖**。`wy` 是覆盖最差的源（9 个 feature 中 8 个无 fixture，且只有 1 个 fixture 文件）。

**附加观察**：`mg_hot.json` 有 154KB，但 `mg.hot()`（`mg.py:166-179`）只读 `data.hotwords[0].hotwordList`。fixture 明显含远超 hot 的数据 —— 该 fixture 可能被多用途复用过。（「未验证」：未逐个核对 fixture 内容与断言的精确对应。）

---

## 5. DB / 歌单层审计

### 5.1 `db.py` 查询审计

| 函数 | 行号 | 评估 |
|---|---|---|
| `connect` | `db.py:18-30` | ✅ `read_only=True` 时用 URI `file:{p}?mode=ro`（`db.py:25-26`），**实测有效** —— 只读 DB 上写操作会失败。这是 `db_query` 安全性的**唯一防线**。 |
| `list_tables` | `db.py:33-39` | ✅ |
| `table_info` | `db.py:42-49` | ✅ 有注入防护：`if not name.replace("_","").isalnum(): raise ValueError`（`db.py:45-46`） |
| `row_counts` | `db.py:52-62` | ✅ 同样校验（`db.py:58-59`） |
| **`query`** | `db.py:65-70` | ⚠️ **任意 SQL 执行器，无校验**，被 `db_query` 直接透传用户输入（`cli.py:548`）。`db_query` 的 help 自承 "or arbitrary — be careful"（`cli.py:547`）。安全性依赖 SQLite 只读模式，而非 SQL 校验 —— 可接受，但须明确这是**唯一**防线。 |
| `list_user_lists` | `db.py:75-107` | ⚠️ 见 §2.7f：`HAVING song_count > 0`（`db.py:98`、`db.py:104`）导致空 `default`/`love` 不显示；虚拟列表硬编码中文名 `'默认列表'`/`'我的收藏'`（`db.py:94`、`db.py:100`）与 `position = -2/-1`（`db.py:95`、`db.py:101`）。 |
| `get_list` | `db.py:110-118` | ✅ 参数化（`db.py:116`）。**但查不到虚拟列表**（§2.7f）。 |
| `songs_in_list` | `db.py:121-144` | ⚠️ `LEFT JOIN ... ORDER BY COALESCE(o."order", 0) ASC`（`db.py:135-138`）—— 见 §2.7g，**缺 tie-breaker**。 |
| `find_songs` | `db.py:147-174` | ⚠️ 参数化正确（`db.py:159`、`db.py:166-168`），但 `LIKE` 通配符未转义（§2.7h）；`%` 前导使索引失效。 |
| `stats` | `db.py:177-196` | ⚠️ 硬编码三张表名（`db.py:191-193`），**缺表即崩**（§2.7i）。 |
| `rank_songs` | `db.py:199-222` | ⚠️ `GROUP BY m.id` 后 SELECT bare column（§2.7j），值**不确定**。 |
| `rank_lists` | `db.py:225-240` | ✅ |
| `distinct_songs` | `db.py:243-250` | ✅ 实测 1434 vs 总 1647，正确。 |
| `list_dislikes` | `db.py:253-258` | ✅ |
| `list_downloads` | `db.py:261-272` | ⚠️ `musicInfo` 是 JSON 文本**不解析**（`db.py:264` 明说），agent 需二次解析。 |

### 5.2 `db_writer.music_add` 是否正确处理 `my_list_music_info_order`？

**先回答核心问题：在"order 稀疏"这一项上，`music_add` 是正确的 —— 它把 order 规范化（重编号 0..n-1）。这一点已实测验证。**

**`music_add` 的算法**（`db_writer.py:109-180`）：

1. 读出该 list 全部现有行，按 `COALESCE(o."order", 0)` 排序（`db_writer.py:129-137`）；
2. 过滤已存在的 id（`db_writer.py:140-141`）；
3. 按 `top`/`bottom` 拼出 `combined`（`db_writer.py:145-148`）；
4. **`DELETE FROM my_list_music_info_order WHERE listId = ?`**（`db_writer.py:151-153`）—— 整表删除该 list 的 order 行；
5. 插入新歌（`db_writer.py:155-165`）；
6. **按 `enumerate(combined)` 把全部 order 重写为 `i`**（`db_writer.py:167-172`）。

**关键**：它不是"取 MAX(order)+1 追加"（那样才会在稀疏时出错），而是**全量重写**。因此稀疏 order 对它**无害**。

**实测验证**（探针 `audit_music_add.py`）：我在临时 DB 中植入**稀疏 order**（5 首歌，order = `0, 1, 5, 6, 100`，即真实用户遇到的 "0..247 缺 226,227" 同类形态），然后调用**真实的 `db_writer.music_add`**：

```
=== BEFORE: sparse orders planted ===
   audit_song_0 order = 0
   audit_song_1 order = 1
   audit_song_2 order = 5
   audit_song_3 order = 6
   audit_song_4 order = 100

=== calling db_writer.music_add(position='bottom') for ONE new song ===
  inserted = 1

=== AFTER: order table ===
   audit_song_0 order = 0
   audit_song_1 order = 1
   audit_song_2 order = 2
   audit_song_3 order = 3
   audit_song_4 order = 4
   audit_new_0  order = 5
```

**结果正确**：稀疏 order 被规范化为连续 `0..5`，**原有相对顺序完整保留**，新歌正确追加到末尾。

> **重要修正**：此处与任务预设的担忧不同。`db_writer.music_add` **不是**通过"取 MAX(order)+1"追加（那才会在稀疏时出错），而是**全量重写**。稀疏 order 对它无害。**但是**，这个实现引入了另一个问题 —— 见 §5.3。

**重复 `id` 跨 list 的场景**：另行实测（探针 `audit_dup_id.py`），构造同一 `id` 同时存在于 list A 和 B 且两处 `name`/`singer`/`source` **不同**，然后对 A 执行 `music_add`。结果：

```
list userlist_dup_A:  dup_shared_id = 0, a_new = 1
list userlist_dup_B:  dup_shared_id = 0, b_song_1 = 1, b_song_2 = 2
A: info= 2  order= 2
B: info= 3  order= 3          ← B 完全未被触碰
```

**原因**：`music_add` 的所有读写都带 `WHERE ... listId = ?` 限定（`db_writer.py:135`、`152`、`169`、`175-177`）。**在 `listId` 限定这一点上，`db_writer` 是正确的。**

**所以真实的 `id` 重复风险不在 `db_writer`，而在 `cli.py:822-833` 的 `_resolve_song_meta`（无 `listId` 限定）** —— 详见 §2.7e。

### 5.3 `music_add` 的实际缺陷

#### (a) `inserted` 计数会虚高（docstring 承诺与实际不符）

```python
155: for s in new_songs:
156:     conn.execute("INSERT OR IGNORE INTO my_list_music_info ...", (...))
165:     inserted += 1          # ← 无条件递增，不检查 cur.rowcount
```

`db_writer.py:122` 的 docstring 明确承诺 "Returns the number of songs actually inserted (**excluding dupes**)".

**可复现路径**：`playlist add` 的 `song_ids` 是 `nargs=-1`（`cli.py:924`），允许 `lx playlist add L S1 S1`。`cli.py:941-947` 的循环对同一 id 查两次、追加两份到 `songs`。而 `db_writer.py:140-141` 的 `existing_ids` **只与 DB 对比，不查重 `songs` 内部**：

```python
140: existing_ids = {row["id"] for row in existing}
141: new_songs = [s for s in songs if s["id"] not in existing_ids]
```

故 `new_songs = [S1, S1]`，`inserted = 2`，而 `INSERT OR IGNORE` 使**实际入库 1 行**（`my_list_music_info` 有 `UNIQUE("id","listId")`）。用户/agent 看到 `{"list_id":"L","added":2}` 而 DB 只多一首。

#### (b) `order` 表无 UNIQUE 约束 → 可写入重复 order 行

`my_list_music_info_order` 的 schema（探针确认）：

```
listId TEXT NOT NULL, musicInfoId TEXT NOT NULL, "order" INTEGER NOT NULL
```

**无 PRIMARY KEY、无 UNIQUE**。故 `music_add` 在 `combined` 含重复 id 时（如上述 `[S1, S1]`）会写**两行 order**（`db_writer.py:167-172`），SQLite 不阻止。结果该歌曲在 `songs_in_list` 的 `LEFT JOIN` 中**出现两次**。（实测 fixture 中当前无重复 order 组，重复组数为 0。）

#### (c) 全量 DELETE + 重写：性能与并发窗口

每次 `playlist add`（哪怕只加 1 首歌）都要**删除并重写该 list 的全部 order 行**（`db_writer.py:151-153` + `167-172`）。对真实 DB 中 221 首的 list（探针实测 `tx_01f8d8ef9ba89ef43cb1c28c289d2a9f` 有 221 行），这是 221 次 DELETE + 222 次 INSERT，**在同一事务内**。虽然正确，但：

1. **随歌单增长呈线性成本**；
2. **在 LX 主进程同时运行时窗口期更长**，加剧 `db_writer.py:6-10` docstring 自承的并发风险；
3. `db_writer.py:129-137` 把整张表所有行（**含 `meta` 大字段**）读进 Python 内存再写回 —— 实测 `meta` 含完整 `qualitys` 数组（见 §3.1 #29 输出），内存占用可观。

#### (d) 无 `BEGIN IMMEDIATE` → 读-改-写可丢失更新

`music_add` 的模式是**先读 existing（`db_writer.py:129-137`）再写**。SQLite 默认 `DEFERRED` 事务：读先取 SHARED 锁，首次写才升级。在 WAL 模式下，另一个写者（LX GUI）可在我们读完、写之前提交，导致**基于陈旧快照重建 order**。`docs/WRITE_DESIGN.md:33-38` **明确讨论过这个风险**，但实现里**没有用 `BEGIN IMMEDIATE`** 消除它。

#### (e) `db_writer` 不校验 `source` 与 `id` 的对应关系

校验发生在 `cli.py:943-946`（CLI 层）。若 `db_writer` 被其它调用方直接使用（如今后新增的批量导入），**没有任何保护**。

### 5.4 **最严重缺口：从「搜索结果」到「歌单」无任何路径**（已确认）

**结论：确认成立。这是本次审计发现的最关键结构性缺陷。**

**证据链：**

**(1) `playlist add` 的唯一入口要求 id 已在 DB 中。** `cli.py:931-956`：

```python
931: def playlist_add(ctx, list_id, song_ids, add_top, force, src_id):
934:     """Add songs to a list. Each SONG_ID must already exist in some list
935:     (so we have its metadata to copy)."""          # ← 自述
...
941:     for sid in song_ids:
942:         meta = _resolve_song_meta(db_e, list_id, sid)   # ← 唯一构造方式
```

**(2) `_resolve_song_meta` 查不到就抛错**（`cli.py:822-833`）：

```python
831: if not rows:
832:     raise click.UsageError(f"song id not in any list: {song_id!r}")
```

**(3) 实测确认**（探针 `audit_gap.py`）：对未知 id 调用 `playlist add` → 报错退出，**无法添加**。

**(4) `source` 侧的搜索命令只输出、不落库。** `cli.py:1127-1132`（`search`）与 `cli.py:1046-1068`（生成的 feature 命令）**全部只做 `_emit`**，无任何 `db_writer` 调用。grep 确认：`cli.py` 中 `db_writer` 的调用点**只有 5 处** —— `list_create`(`cli.py:872`)、`list_rename`(`891`)、`list_remove`(`911`)、`music_add`(`948`)、`music_remove`(`969`)，**全部在 `playlist` 组内，无一在 `source`/`search` 路径上**。

**(5) `db_writer.music_add` 虽接受任意 `songs` dict**（`db_writer.py:109-112`，只需 `id`/`name`/`singer`/`source`，可选 `interval`/`meta`），**但没有任何 CLI 命令从 `SongRecord` 构造这个 dict**。`cli.py:940-947` 构造 `songs` 的唯一方式就是 `_resolve_song_meta` 的 DB 查询结果。

**(6) `SongRecord.to_json()` 也提供不了**（§4.2）：**无 `meta` 字段**，且 `songmid` ≠ DB `id`。真实 DB 的 id 是**复合格式**（如 `1051821583_38A6C13F5A1A4AC97EBAE2185507715C`，实测见 §3.1 #29），形如 `<songId>_<hash>`，而 `SongRecord.songmid` 产出的是**单段值**。（两段的确切分段语义**未验证** —— 未找到生成该格式的代码。）

**(7) 没有 import / bulk-add 命令。** `playlist` 组共 14 个子命令（实测 `playlist --help` 输出）：`add, create, delete, dislikes, downloads, export, find, list, list-rank, rank, remove, rename, show, stats` —— **有 `export` 无 `import`**。

**后果（对用户/agent 的实际影响）：**

> 用户搜索到一首歌（`lx search "夜に駆ける" --source wy`），**无法把它加入任何歌单**。唯一变通是：先在 LX GUI 里手动把歌加进某个歌单，再用 `lx playlist add <目标> <id>` 从那个歌单复制过去。**这使整个写路径对"发现新歌"场景完全失效** —— 而"搜索 → 收藏"恰恰是音乐 CLI 最核心的用例。

**这是设计中缺失的一环**，导致 `search` 与 `playlist add` 两个子系统各自完整、却无法衔接。对 AI agent 而言，CLI 只能做"库内搬运"，**不能做"库外引入"**。

**附**：即使走"库内搬运"路径，`_resolve_song_meta` 在 id 跨 list 重复时还会**取到错误元数据**（§2.7e，已实测）—— 所以现有路径本身也不可靠。

### 5.5 `db_writer` 的其它问题

| 问题 | 位置 | 说明 |
|---|---|---|
| **无 `--dry-run`** | 全部写命令 | `docs/WRITE_DESIGN.md:212-214` 自述"There is no `--dry-run` yet — every write is applied immediately"。**与代码一致**（不算 doc-vs-code 偏差），但对 agent 是风险：无法预演。 |
| **`--force` 语义过宽** | `cli.py:841-853` | `_check_lx_safe` 仅检查 `launcher.is_running()`。只要 LX 在跑就要求 `--force`（`cli.py:850-853`），但 `--force` 一旦给出就**完全不做额外保护**（`cli.py:848` 直接 return）。无备份、无锁、无重试。 |
| **`_gen_userlist_id` 有碰撞风险** | `db_writer.py:38-40` | `f"userlist_{int(time.time()*1000)}"` —— **毫秒时间戳**。同毫秒创建两个歌单会**主键冲突**（`my_list.id` 是 PK，`db_writer.py:60-65` 的 INSERT 无 `OR IGNORE`，抛 `IntegrityError`（未捕获，裸逃逸））。概率低，但**是可复现的崩溃路径**（快速连续 `playlist create`）。 |
| **`list_create` 的 position 竞态** | `db_writer.py:57-59` | `SELECT COALESCE(MAX(position), -1) + 1` 与随后 INSERT **不在同一写锁下**，且 `position` 无 UNIQUE → 并发 `playlist create` 产生**重复 position**，使 `playlist list` 的 `ORDER BY position ASC`（`db.py:105`）顺序不确定。 |
| **`list_remove` 不 renumber position** | `db_writer.py:87-104` | `docs/WRITE_DESIGN.md:48-49` 要求"renumbering after delete is the GUI's job, and **the CLI must do the same**"，但实现**不做任何 renumber** → 删除后 `position` 出现空洞。**文档要求 vs 实现缺失。** |
| **`music_remove` 的 `rowcount` 语义** | `db_writer.py:195-200` | 返回 `my_list_music_info` 的删除行数。若某 id 在 info 表**无**行但 order 表**有**（孤儿），返回值偏小，而 order 行仍被删（`db_writer.py:201-205`）。轻微。 |
| **双重提交** | `db_writer.py:66, 83, 103, 179, 206, 228, 304` | 每处都显式 `conn.commit()`，**同时**又依赖 `with` 的隐式 commit。不是 bug，但两个机制并存会**掩盖**未来遗漏的 `commit()`。 |
| **`music_add` 早退未 commit** | `db_writer.py:142-143` | `return 0` 在 `with` 块内且未显式 commit。此处只因无任何写入，故实际无害。 |

**`list_create` 是 `db_writer` 中质量最好的函数**：`my_list` 的 3 个 `NOT NULL` 列（`id`/`name`/`position`）全部显式提供（`db_writer.py:60-65`），✅ 正确满足 schema。**但其返回值是手工拼装的 dict**（`db_writer.py:67-71`），而非从 DB 回读 —— schema 无触发器，当前无害，但属"返回值不忠实于持久状态"的模式。

---

## 6. 测试覆盖

### 6.1 测试套件实跑结果（按要求执行）

```
cd C:\Users\EDY\Documents\workspace\lx-cli ; python -m pytest tests/ -q --ignore=tests/probe_real_server.py
```

**原始输出（完整）：**

```
............................................                             [100%]
=============================== warnings summary ===============================
src\lx_cli\sync_client.py:80
  C:\Users\EDY\Documents\workspace\lx-cli\src\lx_cli\sync_client.py:80: DeprecationWarning: websockets.exceptions.InvalidStatusCode is deprecated
    from websockets.exceptions import ConnectionClosed, InvalidStatus, InvalidStatusCode

..\..\..\AppData\Local\Programs\Python\Python313-32\Lib\site-packages\websockets\legacy\__init__.py:6
  C:\Users\EDY\AppData\Local\Programs\Python\Python313-32\Lib\site-packages\websockets\legacy\__init__.py:6: DeprecationWarning: websockets.legacy is deprecated; see https://websockets.readthedocs.io/en/stable/howto/upgrade.html for upgrade instructions
    warnings.warn(  # deprecated in 14.0 - 2024-11-09

..\..\..\AppData\Local\Programs\Python\Python313-32\Lib\site-packages\_pytest\cacheprovider.py:469
  C:\Users\EDY\AppData\Local\Programs\Python\Python313-32\Lib\site-packages\_pytest\cacheprovider.py:469: PytestCacheWarning: could not create cache path C:\Users\EDY\Documents\workspace\lx-cli\.pytest_cache\v\cache\nodeids: [WinError 5] 拒绝访问。: 'C:\\Users\\EDY\\Documents\\workspace\\lx-cli\\.pytest_cache\\v\\cache'
    config.cache.set("cache/nodeids", sorted(self.cached_nodeids))

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
44 passed, 3 warnings in 1.69s
```

| 指标 | 值 |
|---|---|
| **通过** | **44** |
| 失败 / 跳过 / 错误 | 0 / 0 / 0 |
| 警告 | 3 |
| 耗时 | 1.69s |
| 收集 | 44 tests collected |

三条警告均为**环境性/上游弃用**，非本项目功能缺陷：
1. `sync_client.py:80` 导入 `websockets.exceptions.InvalidStatusCode` 已弃用（**本项目代码** —— 该符号被导入但**从未使用**）；
2. `websockets.legacy` 弃用（上游库）；
3. `.pytest_cache` 目录权限拒绝（本机沙箱问题，与本项目无关；也解释了任务为何要求忽略 `.pytest_cache`）。

**`--ignore=tests/probe_real_server.py` 实际是空操作**：该文件（88 行）**不含任何 `def test_*`**（`tests/probe_real_server.py:27` 只有 `async def main()`），pytest 本就不会收集它。所以"忽略"没有改变计数。

### 6.2 关键发现：两个测试文件**从未被 pytest 执行**

`--collect-only` 显示 **44 tests collected**，**全部**位于 `tests/sources/`。逐文件核对：

| 文件 | 行数 | `def test_*` 数 | 被 pytest 收集 |
|---|---:|---:|---|
| `tests/sources/test_base.py` | 56 | 7 | ✅ |
| `tests/sources/test_cli.py` | 41 | 5 | ✅ |
| `tests/sources/test_http.py` | 71 | 6 | ✅ |
| `tests/sources/test_kg.py` | 62 | 4 | ✅ |
| `tests/sources/test_kw.py` | 81 | 6 | ✅ |
| `tests/sources/test_mg.py` | 47 | 3 | ✅ |
| `tests/sources/test_registry.py` | 39 | 6 | ✅ |
| `tests/sources/test_tx.py` | 57 | 4 | ✅ |
| `tests/sources/test_wy.py` | 44 | 3 | ✅ |
| **`tests/test_reads.py`** | **115** | **0** | ❌ **不被收集** |
| **`tests/test_sync_integration.py`** | **106** | **0** | ❌ **不被收集** |
| `tests/probe_real_server.py` | 88 | 0 | ❌（本就是探针） |

**这两个文件不是 pytest 测试** —— 它们是 `main()` 脚本（`test_reads.py:32` `def main()`、`test_sync_integration.py:25` `async def main()`），靠 `if __name__ == "__main__": sys.exit(main())` 手动运行。**文件名以 `test_` 开头，给人"pytest 会跑它们"的错觉，但 44 个测试里一个都不来自它们。**

`test_reads.py:5-9` 的 docstring 甚至建议 `python -m pytest tests/ -v` —— **该方式不执行其中任何断言**。

**实跑结果：**

**(a) `python tests/test_reads.py` → exit 0，`ALL TESTS PASSED`。** 含 13 处 `expect()` 断言（自定义，非 pytest），覆盖 `db.py` 读路径（`list_tables`/`row_counts`/`list_user_lists`/`get_list`/`songs_in_list`/`find_songs`/`stats`/`distinct_songs`/`dislikes`/`downloads`/`table_info`）。

**(b) `python tests/test_sync_integration.py` → exit 1，FAILED。** 报错：

```
PermissionError: [Errno 13] Permission denied:
'C:\Users\EDY\AppData\Roaming\lx-music-desktop\LxDatas\sync\client\syncAuthKey.json.tmp'
```

失败原因：`test_sync_integration.py:44` 与 `:50` 调用 `sync_client.save_auth_key(sid, info, exe_path=None)`。`exe_path=None` 时 `paths.user_data_dir(None)`（`paths.py:73-75`）落到**真实用户目录** `%APPDATA%\lx-music-desktop\LxDatas\sync\client\`。

**这是一个严重的测试设计缺陷**（独立于沙箱）：**集成测试污染真实用户配置**。即便权限允许，运行测试也会在用户真实的 `syncAuthKey.json` 里**插入伪造的 `clientId`/`key`**（`sync_client.py:667` 起），**可能使真实同步凭据失效**。未使用临时目录或 `monkeypatch` 隔离。它"不被收集"反而是幸运的。

### 6.3 模块 → 测试文件映射

| 模块 | LOC | 对应测试 | 覆盖状态 |
|---|---:|---|---|
| `cli.py` | **1236** | `tests/sources/test_cli.py`（41 行，5 测试，**只测 `source list` 与 `search`**） | 🔴 **极低**（< 1%） |
| `client.py` | 173 | **无** | 🔴 **零** |
| `config.py` | 67 | **无** | 🔴 **零** |
| `db.py` | 272 | `tests/test_reads.py`（**不被 pytest 收集**） | 🟡 有效但**不在 CI 内** |
| **`db_writer.py`** | **305** | **无任何测试**（无 pytest，也无手动脚本） | 🔴🔴 **零 — 最高风险** |
| `launcher.py` | 85 | **无** | 🔴 **零** |
| `paths.py` | 121 | **无**（仅被 `test_reads` 经 `db_path` 间接触及） | 🔴 **零** |
| `sync_client.py` | 721 | `tests/test_sync_integration.py`（**不被收集且实跑失败**） | 🔴 **零有效** |
| `sources/base.py` | 165 | `tests/sources/test_base.py`（7） | 🟢 好（含 `to_json` 全字段断言） |
| `sources/http.py` | 103 | `tests/sources/test_http.py`（6） | 🟢 好（含重试 / 4xx 不重试 / JSON 解析失败）；**但未测 `request_text`** |
| `sources/__init__.py` | 65 | `tests/sources/test_registry.py`（6） | 🟢 好 |
| `sources/kg.py` | 221 | `test_kg.py`（4） | 🟡 8 中覆盖 3 |
| `sources/kw.py` | 244 | `test_kw.py`（6） | 🟡 9 中覆盖 4 |
| `sources/tx.py` | 206 | `test_tx.py`（4） | 🟡 8 中覆盖 3 |
| `sources/mg.py` | 222 | `test_mg.py`（3） | 🔴 8 中覆盖 2 |
| `sources/wy.py` | 255 | `test_wy.py`（3） | 🔴 9 中覆盖 2（且其中 1 个只断言 `callable`） |
| `src/lx_cli/tests/mock_sync_server.py` | 421 | 无 | ⚪ N/A（且为重复副本） |
| `tests/mock_sync_server.py` | 401 | 被 `test_sync_integration.py:22` 使用 | 🔴 无效（该文件不被收集） |

**未覆盖 LOC 估算**：`db_writer`(305) + `sync_client`(721) + `client`(173) + `config`(67) + `launcher`(85) + `paths`(121) + `cli`(1236 中约 1200 未覆盖) + `db`(272，仅非 pytest 覆盖) ≈ **约 2,944 行**，占 `src/lx_cli/` 总计约 4,321 行的 **~68%**。

**`44 passed` 的信号强度**：它只证明 **sources 子系统 + registry 契约**健康。它**不**证明 CLI 可用、**不**证明 DB 读写正确、**不**证明同步协议工作。

### 6.4 **无测试的模块清单**（按风险排序）

1. **`db_writer.py`（305 行）— 最高风险，零测试。** 理由：
   - 它是**唯一**修改用户真实数据的模块（`db_writer.py:1-11` 自述）；
   - 含 7 个公开写函数，**每一个都可能损坏用户歌单**；
   - **`music_reorder`（`db_writer.py:210`）与 `music_move`（`db_writer.py:232`）不仅无测试，还无调用方**（§2.4）—— **从未被执行过的 96 行写逻辑**；
   - 事务边界（`write_connect`，`db_writer.py:22-29`）从未被验证；
   - `music_add` 的全量 DELETE+重写策略**无回归测试**。本报告中我验证它正确处理稀疏 order（§5.2），**靠的是临时探针**（`_scratch/audit_music_add.py`），**不在仓库内** —— 任何后续重构都可能无声破坏它；
   - 已确认的 `inserted` 计数虚高（§5.3a）与重复 order 行（§5.3b）**均无测试拦截**。

2. **`sync_client.py`（721 行）— 零有效测试。** 唯一集成测试**不被 pytest 收集、实跑失败、且会污染用户真实配置**（§6.2b）。721 行协议代码（AES/RSA、message2call、WS 状态机）**在 CI 中完全未验证**。

3. **`cli.py`（1236 行）— 覆盖 < 1%。** 44 个测试中仅 5 个触及 CLI，且只覆盖 `source list` / `search`。**所有 DB 读写命令、所有 `--json` 契约（§3）、所有写命令的保护逻辑（`_check_lx_safe`）—— 全部无测试。** §3 中发现的全部契约不一致，**没有一个会被现有测试捕获**。

4. **`client.py`（173 行）— 零测试。** 13 个播放控制函数无一测试；`subscribe_player_status` 的 idle 逻辑缺陷（§2.7d）无测试。

5. **`config.py`（67 行）— 零测试。** `set_open_api` 会**改写用户真实 `config_v2.json`**；`save_config` 的原子写保证（`config.py:34-37`）无测试。

6. **`launcher.py`（85 行）— 零测试。** `is_running`（`launcher.py:26-35`）靠 `tasklist` 输出**字符串匹配**（`launcher.py:35`），脆弱且无测试；`stop` 的重试循环（`launcher.py:81-85`）无测试。**这直接影响所有写命令的安全门 `_check_lx_safe`。**

7. **`paths.py`（121 行）— 零测试。** 平台分支（`paths.py:33-37`、`73-75`）与 portable 探测（`paths.py:64-71`）无测试。

### 6.5 测试质量的其他问题

- **`test_wy.py:25-29` 只断言 `callable()`**：`test_wy_back_compat_apis` 仅验证三个函数是 callable，**不验证任何行为**。这三函数（`wy.py:236-251`）实际无调用方（§2.4），测试给死代码一种"被维护"的假象。
- **`test_kw.py:72-81` 会打真实网络**：`test_source_kw_tip_cli` 通过 `CliRunner` 调 `lx source kw tip`，注释自承 "The kw endpoint will be hit live"（`test_kw.py:77-78`）。断言仅是"输出里没有 TypeError"（`test_kw.py:80-81`）—— **这是一个 flaky 测试**：网络慢会拖长测试、网络错误也会"通过"。它同时说明 **fixture 回放机制（`conftest.py:36-100`）无法覆盖 CLI 全链路**。
- **`conftest.py:36-100` 的 patch 方式脆弱**：`_patched_http` 需**逐个模块**手动 patch `kg`/`wy`/`kw`/`tx`/`mg` 的 `request_json`/`request_form`/`request_text`（`conftest.py:66-70`、`81-85`、`96-100`），因为各源用 `from .http import request_json` **绑定了名字**，patch `http` 模块不够。**新增一个源就必须回来改 conftest**（违反 `docs/SOURCES.md:60-67` 声称的"新增源 = 新建模块 + 注册"的简洁性）。**若忘记，新源的测试会静默打真实网络。**
- **fixture DB 是 10.7MB 的二进制 blob**（`tests/fixtures/lx.data.db`，10,780,672 字节）**提交进仓库**，且是**真实用户数据**（含真实歌单名如"塞壬唱片"、"电音"，真实歌曲 id）。含隐私风险，且使测试依赖固定数据形态。
- **fixture 的断言极浅**：以 `test_wy.py:32-44` 为例，只断言 `isinstance(...)` 与 `len(...) > 0`，**不断言任何字段的具体值**。因此**字段映射错误无法被测试发现** —— 例如 `kg.album_name` 在搜索结果中恒为空串（§4.2）不会被任何测试捕获。
- **测试污染真实环境**：见 §6.2b（`syncAuthKey.json`）。

---

## 7. 文档与实际不符

审计范围：`README.md`、`docs/SOURCES.md`、`docs/WRITE_DESIGN.md`（按要求，**不审计** `lx-cli-portable/MIGRATION.md`）。

### 7.1 `README.md`

| # | 文档声称 | 位置 | 实际 | 判定 |
|---|---|---|---|---|
| R1 | 整节标题"Why no `playlist add/remove` yet?"，正文称写命令未实现、`WRITE_DESIGN.md` 只是 "Implementation plan"、"We plan to do the former, gated behind `--sync`" | `README.md:151-158` | **写命令已全部实现**：`playlist create/rename/delete/add/remove`（`cli.py:856`、`881`、`903`、`922`、`959`），`db_writer.py` 305 行已落地。**且不存在 `--sync` 参数** | 🔴 **严重过时**，整节结论已被推翻 |
| R2 | "### Playlists (read-only — safe, never modifies the DB)" | `README.md:86` | `playlist` 组**包含 5 个写命令**。实测 `playlist --help` 列出 `add`/`create`/`delete`/`remove`/`rename` | 🔴 **错误**（该标题下列出的只是读命令子集，但标题的绝对化措辞误导） |
| R3 | "All `db` and `playlist` commands default to **read-only** SQLite mode (URI `?mode=ro`). Safe to run while LX is running." | `README.md:106-107` | `db` 组确实只读（`db.py:19-26`）。但 `playlist` 写命令走 `db_writer.write_connect`（`db_writer.py:22-29`），**用 `sqlite3.connect(p)`，无 `mode=ro`**，是**可写**连接 | 🔴 **错误且危险** |
| R4 | "All `db` / `playlist` / `where` operations are read-only by default." | `README.md:175` | 同 R3 | 🔴 **错误且危险** |
| R5 | "## What's NOT exposed: **Search** (LX's music SDK lives in `src/renderer/utils/musicSdk/`; needs its own module)." | `README.md:192-196` | **搜索已完全实现**：`lx search`（`cli.py:1119`）+ `lx source <src> <feature>`（`cli.py:1088-1114`）+ 5 个源模块（1,148 行） | 🔴 **严重过时**。同一份 README 的 `:109-116` 却正确描述了 `lx source`，**自相矛盾** |
| R6 | "`lx playlist find <pattern> [--source kg,wy] [--list <id>]`" | `README.md:91` | `--source` 是 `multiple=True`（`cli.py:668`），**`--source kg,wy` 会被解析为单个值 `"kg,wy"`**，与 DB 中 `source` 列（`"kg"`）不匹配 → **0 结果**。正确写法是 `--source kg --source wy` | 🔴 **用法错误** |
| R7 | Tests 章节只列 `python tests/test_reads.py`，并称"The script copies `lx.data.db` once on first run; subsequent runs use the cached copy." | `README.md:183-190` | 遗漏 pytest 套件（44 测试）与 `test_sync_integration.py`。且 `tests/test_reads.py` **不做任何复制**（全文无 `shutil.copy`），只依赖 `tests/fixtures/lx.data.db` 已存在（`test_reads.py:22-23` 的 `assert FIXTURE.exists()`） | 🟡 **不准确** |
| R8 | "designed as a safe foundation for **future** playlist mutations" | `README.md:4-5` | 写命令早已落地 | 🟡 过时措辞 |
| R9 | "`--json` is available on every output subcommand." | `README.md:132` | 大体成立，但 §3 有 5 处违约（`playlist export` 两态、`subscribe`、`lyric --all`、`source tip`） | ⚠️ 近似成立 |
| R10 | "If a `portable` folder exists next to `lx-music-desktop.exe`, that location is honored" | `README.md:170-171` | `paths.py:64-68` 实现一致。但**未提及**实际路径是 `portable/userData/LxDatas`（多一层 `userData`），而 `paths.py:16-19` 的 docstring **特别强调**了这个细节 | 🟡 不如代码注释准确 |
| R11 | "`lx playlist show <list_id> [--limit N]`" | `README.md:90` | 正确，但**未提示** `default`/`love` 无法 `show`（§2.7f） | 🟡 遗漏 |
| R12 | "`lx backup` ... includes the `meta.json` with `lx_running: true`" | `README.md:179-181` | `cli.py:511-519` 写 `meta.json` ✅。但 `backup_cmd` docstring 称"open in read-only URI mode"（`cli.py:487`），实现却是 `shutil.copy2`（`cli.py:505`）—— **docstring 描述了未实现的机制** | ⚠️ |
| R13 | Data paths 表 + "`default` and `love` are **virtual** lists" | `README.md:138-149` | 表名与 schema 一致 ✅；虚拟列表说明与 `db.py:82-85`/`93-104` 一致 ✅ | ✅ **准确** |

**README 最严重的三处**：R3/R4（把可写命令描述为只读安全 —— **唯一有数据损坏风险由文档直接诱发的条目**）、R1（声称 add/remove 未实现）、R5（声称搜索未暴露，且与同文件自相矛盾）。

### 7.2 `docs/SOURCES.md`

| # | 文档声称 | 位置 | 实际 | 判定 |
|---|---|---|---|---|
| S1 | 能力矩阵 10 行 × 5 源 | `SOURCES.md:8-19` | 逐格对照 5 模块的 `features` 元组（`kg.py:76-77`、`kw.py:117-118`、`tx.py:105-106`、`mg.py:97-98`、`wy.py:114-115`） | ✅ **全部一致** |
| S2 | 能力矩阵 kg album = ✅ / mg album = ✅ | `SOURCES.md:11` | 实现存在（`kg.py:122-135`、`mg.py:133-143`），但 `name`/`artist` **恒为字面量 `"(unknown)"`**（`kg.py:132`、`mg.py:141`） | ⚠️ 形式存在，信息量为零 |
| S3 | 能力矩阵 tx album = — | `SOURCES.md:11` | `tx.py:105-106` features 不含 `album` ✅ | ✅ |
| S4 | "`lx source kg song <audio_id>`" | `SOURCES.md:27` | `kg.song` 走 `gateway.kugou.com/v3/album_audio/audio`，body 是 `{"hash": song_id, ...}`（`kg.py:96`）——**需要 hash**。而 `_build_song` 产出的 `songmid` **优先取 `Audioid`**（`kg.py:49-50`） | ❌ **参数语义错误**（文档说 audio_id，实现要 hash） |
| S5 | "`lx playlist add <list_id> <song_id>... --source kg` —— 仅校验 DB 中歌曲的 `source` 字段是否匹配" | `SOURCES.md:36-37` | 与 `cli.py:943-946` 一致 | ✅ 准确（且诚实说明了限制） |
| S6 | "`--json` 输出 `SongRecord.to_json()` 形态" + 10 字段 JSON 示例 | `SOURCES.md:42-51` | 与 `base.py:36-48` **完全一致** | ✅ **准确** |
| S7 | "`lx search <keyword> --source <src>` 等价于 `lx source <src> search`" | `SOURCES.md:35` | `cli.py:1131` 调 `src.search(...)` ✅。但**默认值不同**：`lx search` 的 `--limit` 默认 **10**（`cli.py:1124`），`lx source <s> search` 的是 **30**（`cli.py:1009`） | ⚠️ **并非严格等价**（默认 limit 差 3 倍） |
| S8 | "所有 endpoint 来自 LX Music desktop v2.12.2 的 `src/renderer/utils/musicSdk/<src>/`" | `SOURCES.md:55-56` | **版号未验证**（需 LX 上游源码）。各模块 docstring 确实引用了对应 SDK 路径（`kg.py:3`、`tx.py:6`、`wy.py:1-5`） | 🟡 **未验证**（版号） |
| S9 | "**不使用第三方域名**（`tempmusics.tk` 等）" | `SOURCES.md:56-57` | 5 个源的 URL 全部是 `kugou.com`/`kuwo.cn`/`y.qq.com`/`migu.cn`/`music.163.com` ✅ | ✅ |
| S10 | 添加新源步骤 3：写 `tests/sources/test_<id>.py` + 在 `tests/sources/fixtures/` 录制 JSON | `SOURCES.md:65-66` | 步骤**不完整**：还必须改 `tests/sources/conftest.py:41-45`（import 新模块）与 `:66-70`/`:81-85`/`:96-100`（patch 新模块的 HTTP 名） | 🟡 **遗漏关键步骤**（见 §6.5） |
| S11 | 文档**未提及** `bd`（百度）源缺失 | 全文 | §4.4 已确认无 `bd`。文档只说"5 个源"，**未说明为何没有百度**（LX 内置 SDK 有 `bd`） | 🟡 遗漏，但对 AI agent 是重要信息 |

**`SOURCES.md` 与实现的一致性总体最好** —— 能力矩阵 50 格全部准确（唯一瑕疵是 kg/mg album 的占位符问题，属"形式存在、内容为空"）。**最严重的一处是 S4**（`kg song` 的参数语义与实现相反）。

### 7.3 `docs/WRITE_DESIGN.md`

| # | 文档声称 | 位置 | 实际 | 判定 |
|---|---|---|---|---|
| W1 | "**Status: implementation in progress.** ... CLI write commands ship with `--sync` (default-on)" | `WRITE_DESIGN.md:8-10` | 实现**已完成**；**不存在 `--sync` 标志**（实测 `playlist add --help` 无此选项；`cli.py:922-933` 只有 `list_id`/`song_ids`/`--top`/`--force`/`--source`） | 🔴 **核心声明为假** |
| W2 | `lx playlist create <name> [--position N] [--url <sync>]` | `WRITE_DESIGN.md:203` | `create` 存在 ✅，但 **`--url` 参数不存在**（`cli.py:858-861` 只有 `--position` 和 `--force`） | 🔴 |
| W3 | `lx playlist rename/delete/add/remove ... [--url <sync>]` | `WRITE_DESIGN.md:204-207` | 四命令全部存在 ✅，但**全部无 `--url`**（`cli.py:884`、`cli.py:905`、`cli.py:925-929`、`cli.py:962`） | 🔴 **5 个 `--url` 全部不存在** |
| W4 | "Without it, writes still go to the local DB; the CLI prints a 'synced to local only — pass --url to propagate' warning." | `WRITE_DESIGN.md:210-212` | 实际提示语是 `note: open LX and click sync to propagate to other devices`（`cli.py:878`、`900`、`919`、`956`、`976`），**且与 `--url` 无关，总是打印** | 🔴 **引用的字符串不存在** |
| W5 | §2 架构图 + "CLI is a sync client ... It speaks the same protocol"，时序图称 "CLI writes to its local DB → CLI opens WebSocket" | `WRITE_DESIGN.md:51-76` | `LXSyncClient` 存在（`sync_client.py:486`）✅，**但没有任何 CLI 命令连接它**（grep `LXSyncClient` 于 `cli.py` → 无匹配）。`sync` 组只有 `auth`/`status`（`cli.py:1140`、`cli.py:1191`） | 🔴 **架构存在但未接线** |
| W6 | §3.3 "The CLI only sends; it doesn't need to validate against an allowlist because the wire envelope is string-typed." | `WRITE_DESIGN.md:133-135` | **矛盾**：`sync_client.py:471-477` 定义了 `LIST_ACTIONS` 白名单，`is_valid_action`（`sync_client.py:480-481`）会校验 | 🔴 文档与代码相反 |
| W7 | §1.3 "`position` in `my_list` is a 0-based display order... renumbering after delete is the GUI's job, and **the CLI must do the same**." | `WRITE_DESIGN.md:48-49` | `db_writer.list_remove`（`db_writer.py:87-104`）**不做任何 renumber** | 🔴 **文档要求 vs 实现缺失** |
| W8 | "**There is no `--dry-run` yet** — every write is applied immediately." | `WRITE_DESIGN.md:212-214` | 与代码一致（无 `--dry-run`） | ✅ **准确** |
| W9 | §4 列出 7 个 `db_writer` helper | `WRITE_DESIGN.md:179-188` | 7 个**全部存在**（`db_writer.py:45`、`74`、`87`、`109`、`183`、`210`、`232`） | ✅ 准确 |
| W10 | §3.3 action 词汇 12 个 | `WRITE_DESIGN.md:137-142` | `sync_client.py:471-477` 的 `LIST_ACTIONS` **也是 12 个，集合完全一致** | ✅ 准确 |
| W11 | §3.5 实现表：`sync_client.py` ~430 行、`mock_sync_server.py` ~370 行、`test_sync_integration.py` ~120 行 | `WRITE_DESIGN.md:168-172` | 实际 **721** / 421（包内）与 401（测试目录）/ **106** 行 | 🟡 **`sync_client.py` 低估 68%** |
| W12 | §6 "tests/test_reads.py # 8 smoke checks" + "Both pass against the test fixture and the local mock server." | `WRITE_DESIGN.md:219-223` | `test_reads.py` 实际有 **13** 处 `expect()`；**两者都不被 pytest 收集**；且 `test_sync_integration.py` **实跑 exit 1 失败**（§6.2b） | 🔴 **"Both pass" 不实** |
| W13 | §5 "Reads (unchanged): `lx playlist list / show / find / stats / export / dislikes / downloads`" | `WRITE_DESIGN.md:198` | 全部存在 ✅，但**遗漏 `playlist rank`、`playlist list-rank`**（`cli.py:753`、`cli.py:780`） | ⚠️ 不全 |
| W14 | §7 "✅ Done: ... 2. DB writer module (db_writer.py) with the transactional CRUD helpers." | `WRITE_DESIGN.md:237-238` | 存在 ✅，但**零测试**且含 §5.3 的计数缺陷 | ⚠️ "Done" 过于乐观 |
| W15 | §7 "✅ Done: 3. Write CLI commands using the `_jp` decorator pattern." | `WRITE_DESIGN.md:239` | 与代码一致（写命令用 `@_jp`）✅ —— **但 `_jp` 本身是重定义的**（§2.1），文档把一个已损坏的抽象当作"完成的模式" | 🟡 表面一致 |

**`docs/WRITE_DESIGN.md` 是本次审计中最不可信的文档**：它系统性地描述了一套**不存在的 CLI 接口**（`--sync` / 5 个 `--url`），声称一个**实际失败的测试通过**，并把一个**未接线的架构**描述为已实现。**任何按此文档操作的 agent 都会失败。**

### 7.4 文档漂移总结

| 文档 | 事实错误 | 严重程度 |
|---|---:|---|
| `README.md` | 3 处严重（只读声明 ×2、add/remove "未实现"、搜索 "未暴露"）+ 1 处用法错误（`--source kg,wy`） | **高** |
| `docs/WRITE_DESIGN.md` | 5 个不存在的 `--url`、不存在的 `--sync`、未接线的架构、"Both pass" 不实、position 要求未实现 | **高** |
| `docs/SOURCES.md` | 1 处参数语义错（`kg song <audio_id>`）、2 处 album 占位符、1 处默认 limit 不等价、1 处新增源步骤不全 | **中** |

---

## 8. Top 10 结构性问题（按阻碍重构程度排序）

> 排序依据：**影响面 × 静默失败概率 × 修复前置依赖数**。排名第 1 的问题会让后续所有重构失去安全网。

### 🥇 1. `db_writer.py` 是唯一写用户数据的模块，却零测试覆盖

**位置**：`db_writer.py` 全文（305 行）；测试缺口见 §6.3–6.4。

**为什么排第一**：这是**所有重构的安全网缺失**。任何对 `cli.py`/`db.py` 的调整最终都会经过 `db_writer`。其中 `music_add` 用「全量 DELETE + 重写 order」（`db_writer.py:151-153`、`167-172`）这种**破坏性策略**，其正确性依赖"读出的 `existing` 完整覆盖该 list"这一隐含前提。**本报告验证了它正确处理稀疏 order（§5.2），但该验证只存在于临时探针中，不在仓库里** —— 下一次有人"优化" `music_add` 时，没有任何测试会红。

**额外风险**：`music_reorder`（`db_writer.py:210`）与 `music_move`（`db_writer.py:232`）**既无测试也无调用方** —— 从未执行过的 96 行写逻辑躺在会动用户数据的模块里。此外 `inserted` 计数虚高（`db_writer.py:165`，docstring `db_writer.py:122` 却说 "excluding dupes"）、`_gen_userlist_id` 毫秒主键可冲突崩溃（`db_writer.py:38-40`）、无 `BEGIN IMMEDIATE` 导致读-改-写丢失更新（`db_writer.py:129-172`）、`order` 表无 UNIQUE 可写入重复行（`db_writer.py:167-172`）—— **全部无测试拦截**。

**修复前置**：必须先补测试，才敢动其它一切。

### 🥈 2. 「搜索结果 → 歌单」无任何路径（核心用例彻底断裂）

**位置**：`cli.py:822-833`（`_resolve_song_meta` 强制要求 id 已在 DB）+ `cli.py:942` + `cli.py:1127-1132`（搜索只 `_emit` 不落库）；`db_writer.music_add` 无任何 `SongRecord` 适配层（`db_writer.py:109-112`）。

**为什么排第二**：这不是"重构难度"，而是**功能层面的结构性断裂** —— CLI 的写路径对"发现新歌"场景**完全失效**（§5.4）。它同时暴露三处抽象缺失：`SongRecord` → DB 行的转换器不存在、`songmid` 与 DB `id` 的映射关系未定义、`meta` JSON 的构造逻辑无处可寻。修复需要**跨 `sources` / `db_writer` / `cli` 三个层次**的新抽象，是最大的一块新设计。

**附加**：`_resolve_song_meta` 收了 `list_id` 却不用（`cli.py:822`），在 id 跨 list 重复时**取到错误元数据**（§2.7e，已实测）—— 使现状比"缺失功能"更糟：**已有的路径本身也不可靠**。

### 🥉 3. `cli.py` 是 1236 行的 God Module，混合 6 种职责

**位置**：`cli.py` 全文。

**证据**：44 处 `@*.command` 装饰器（`cli.py:192`–`1191`）、内联 human 渲染（`cli.py:293-301`、`652-663`、`686-690`、`704-714`、`749-750`、`773-777`、`795-799`、`815-817`）、**内联 SQL**（`cli.py:826-830`）、内联 async 编排（`cli.py:1152-1188`）、动态命令生成（`cli.py:1041-1085`）、模块中部 import（`cli.py:1215`）、进程安全检查（`cli.py:841`）。

**为什么重要**：它是**所有其它问题的容器** —— §2.1、§2.2、§2.3、§2.4、§2.5、§2.6 全部在 `cli.py` 内。测试覆盖 < 1%（§6.3）也源于此：1236 行里绝大部分逻辑无法在不启动 Click 上下文的情况下调用。拆分为 `commands/playback.py`、`commands/playlist.py`、`commands/db.py`、`commands/source.py`、`render.py`、`resolve.py` 是解锁后续一切重构的前提。**而重名定义（§2.1）与命名混乱（§2.5）会让拆分极易出错。**

### 4. 两套互不共享的 HTTP 实现 + `request_text` 无重试 + 零代理支持

**位置**：`sources/http.py`（`request_json`/`request_form` 走 `_attempt` 有重试；**`request_text`（`http.py:93-103`）无重试、不捕获超时**）、`client.py:54-64`、`sync_client.py:261-274`（**三套独立实现、三种错误类型**）；无代理处理（§4.5.4）。

**为什么重要**：`kw` 源因酷我返回单引号 JSON 而被迫用 `request_text`（`kw.py:16`，8 处调用），**代价是丢掉整个重试机制** —— 它是**唯一单次失败即整体失败的源**，且超时会抛出**未包装的原生 `TimeoutError`** 而非 `SourceError`（`http.py:102-103` 未捕获 `TimeoutError`，对比 `_attempt` 在 `http.py:53-55` 捕获了）。同时 5 个源**硬编码** 15s/3 次，无一处覆盖（§4.5.3）。三套实现意味着修一个 bug 要改三处；异常类型 `LXError`/`SourceError`/`SyncAuthError` 不通用，`cli.py` 需分别处理（`cli.py:1056-1057` vs `cli.py:1230`）。**合并这三层是重构的第二个主要工作项。**

### 5. `--json` 契约不一致（含 1 处直接违约）

**位置**：§3.2 的 A–G。最严重：
- **`playlist export -o <file> --json` 输出非 JSON**（`cli.py:732-733`）—— **直接违反契约**；
- `playlist export` 有无 `--json` 输出**逐字节相同**（`cli.py:735`）；
- **`source <src> tip` 的 human 输出是 Python `repr()`**（`cli.py:1038`）—— 既非人类可读也非 JSON；
- `subscribe`（`cli.py:334`）与 `lyric --all`（`cli.py:313`）human 模式即 JSON；
- **`sync status --json` 明文输出完整 AES key**（`cli.py:1199`），而 human 模式**主动掩码**（`cli.py:1208`）—— **安全回退**。

**为什么重要**：任务明确说明**由 AI agent 消费**。agent 无法依赖"`--json` ⇒ 输出是 JSON"这一最基本契约，就必须为每个命令写特例解析 —— 而 `tip` 输出的 `SongRecord(songmid='...', ...)` **连特例解析都困难**（Python repr 不是任何标准格式）。根因是没有统一的 `_emit_json` 抽象：`_emit`（`cli.py:150-154`）只在**部分**命令里被正确使用，其余命令各自 `click.echo(json.dumps(...))`。

### 6. `try/except ImportError` 掩盖真实错误（`cli.py:48-59`）

**为什么重要**：它把"某个源模块 import 失败"**伪装成"所有源都不存在"**，且**以 exit 0 成功退出**（§2.2）。运行时后果极难排障：`lx source list` 打印 "0 sources registered" 并成功返回；`lx search` 的 `Choice`（`cli.py:1122`）变空导致所有输入报参数错误。**这是一个把响亮失败变成静默错值的反模式**，且它的存在毫无必要（`sources` 无第三方依赖，`ImportError` 不可能因"未安装"发生）。回退分支自身还会在 `cli.py:54` 二次 import 已损坏的 `sources.base`。**删除它、让异常直接冒泡，是零风险且立即提升可诊断性的改动。**

### 7. `db.py` 读层有静默错序与无效搜索

**位置**：`songs_in_list` 的 `ORDER BY COALESCE(o."order", 0) ASC`（`db.py:138`）—— 在 order 行**稀疏/缺失**时把缺失行赋值为 0 排到最前，且**无 tie-breaker**（§2.7g）。`find_songs` 的 `LIKE '%...%'`（`db.py:158-159`）**通配符未转义**（§2.7h）。`list_user_lists` 的 `HAVING song_count > 0`（`db.py:98`、`db.py:104`）与 `get_list` 不一致，造成**能 list 不能 show**（§2.7f）。`stats` 硬编码三表名（`db.py:191-193`），**缺表即崩**。`rank_songs` 的 bare column **值不确定**（§2.7j）。

**为什么重要**：写路径总是重建 dense order，所以 CLI 自己写的列表没问题；但 **LX GUI 或其他设备留下的稀疏状态会被静默读错**。而 `db.py` 的 15 个函数**在 pytest 下零覆盖**（`test_reads.py` 不含 `def test_*`）。

### 8. `_FEATURE_SIG` / `_FEATURE_HELP` / `_FEATURE_LIMITS` 三 dict 并行，且键集已不一致

**位置**：`cli.py:983-994`、`996-1007`、`1009-1010`；消费点 `cli.py:1042-1043`、`1050-1051`、`1076`。

**为什么重要**：`_FEATURE_LIMITS` **只有 6 个键**，而另两个有 10 个（§2.5b）。当前不崩**纯属巧合** —— 依赖"凡 `sig["opts"]` 含 `--limit` 的 feature，`_FEATURE_LIMITS` 必有"这条**无断言保护的隐性契约**。给 `album` 加 `--limit` 会立刻 `KeyError`（`cli.py:1051`、`cli.py:1076`）。此外 `cli.py:1044` 的 `cmd_name = feature.replace("_", "-")` 是**永不做任何事**的死转换。三个 dict 合并为 `dict[str, FeatureSpec]` 是低风险、高收益的改动。

### 9. 重名函数定义（`_jp`×2、`_j`×2）+ 装饰器语义靠巧合成立

**位置**：`cli.py:104-106` vs `114-116`（`_jp`）；`cli.py:109-111` vs `185-187`（`_j`）；`_pc` 定义 `cli.py:99-101`。

**为什么重要**：当前**无语义差异**（§2.1 已推导），所以它不是 bug —— 但它是一个**"看起来像 bug、实际不是、且随时会被改成 bug"** 的结构。两份同名同 docstring 的定义会让代码审查者、静态分析工具与 AI agent 得出错误结论（"删掉后者"→ 行为不变；但若有人"合并"成 `click.pass_context(_json_option(f))`，**行为就变了**，因为 `is_eager` callback 的时序会错位）。**必须显式清理，不能靠"反正是等价的"。** 且项目**无 lint 配置**（`pyproject.toml` 仅 27 行），F811 不会被发现。

### 10. 文档系统性失真（`WRITE_DESIGN.md` 描述不存在的接口；`README.md` 自相矛盾且有数据风险）

**位置**：`WRITE_DESIGN.md:9-10`（`--sync` 不存在）、`:203-207`（5 个 `--url` 不存在）、`:210-212`（引文的警告语不存在）、`:223`（"Both pass" 但集成测试实跑失败）、`:168-172`（行数低估 68%）、`:48-49`（position renumber 要求未实现）、`:133-135`（与 `sync_client.py:471-481` 白名单矛盾）；`README.md:151-158`（声称写命令"未实现"）、`:86`/`:106-107`/`:175`（声称 `playlist` 只读，实际含 5 个写命令）、`:192-196`（声称 Search 未暴露，与同文件 `:109-116` 矛盾）、`:91`（`--source kg,wy` 用法错误）。

**为什么排第 10 但必须修**：文档失真本身不阻塞重构，但它**直接决定 agent 的行为**。`README.md:106-107` 与 `:175` 声称"`playlist` 命令默认只读、可安全在 LX 运行时执行"—— **这是错误的**，`playlist add/remove/create/rename/delete` 会写真实 DB（`db_writer.py:22-29` 无 `mode=ro`），而 `_check_lx_safe`（`cli.py:841-853`）**要求 LX 关闭或 `--force`**，恰恰说明它**不安全**。一个信任 README 的 agent 可能在 LX 运行时写入并损坏数据。**这是本报告中唯一有数据损坏风险由文档直接诱发的条目。**

---

## 附录 A：数据库验证说明

本报告 §5 的实测基于 **`tests/fixtures/lx.data.db`**（10,780,672 字节，与真实 DB 同 schema；含 16 个 list / 1647 行 song / 1647 行 order / 1434 个 distinct id）。

| 用户所述条件 | 独立验证结果 |
|---|---|
| 「`order` 可以稀疏（0..247 缺 226,227）」 | fixture 中**未观察到**（order 实测全部稠密 `0..n-1`，稀疏组数为 0）。基于用户自述采信，并**构造等价场景**（order = `0,1,5,6,100`）验证其影响（§5.2）。**标注为「真实 DB 现象，fixture 未复现」。** |
| 「同一 `id` 可跨多个 list 重复」 | ✅ **已在 fixture DB 中独立确认**：`83252353_AFB15305C3E3FAE258200F9A3525892B` 出现在 **4 个** list，另有多个 id 出现在 3 个 list。 |
| 「`(listId, musicInfoId)` 在 order 表内唯一」 | ✅ 确认（**重复组数为 0**）。 |
| 「`(id, listId)` 在 info 表内唯一」 | ✅ 确认（**重复组数为 0**）。 |
| 「order 表无 UNIQUE 约束」 | ✅ 确认（schema 无 PK、无 UNIQUE，仅普通索引）。 |
| 「info 表有 `UNIQUE(id, listId)`」 | ✅ 确认（`INSERT OR IGNORE` 因此生效）。 |

**真实 DB 副本不可访问**：任务提到的真实 DB 副本（`LX-CLI-project/_scratch/ro_copy.db`、`_scratch/bk1/.../lx.data.db`）在本会话中对文件系统**不可访问** —— 列目录时存在，随后读取报 `unable to open database file`，且 `_scratch` 下现已不存在任何 `.db` 文件（疑为沙箱文件访问限制，**非本项目问题**）。因此改为在临时 DB 中按用户描述的形态人工植入条件来验证 —— **这是该缺陷的正确复现方式，结论不依赖具体数值。**

## 附录 B：未验证项清单

| 项 | 原因 |
|---|---|
| 真实 DB 中 order 稀疏的具体数值（0..247 缺 226,227） | 真实 DB 副本不可访问（附录 A）。已构造等价场景验证影响。 |
| `docs/SOURCES.md:55` 声称的 "LX Music desktop v2.12.2" 版号 | 未比对 LX 上游源码版本。 |
| 环境变量代理（`HTTP_PROXY` 等）是否实际作用于本 CLI 的 `urllib` 调用 | 未构造代理环境实测（§4.5.4）。 |
| `sources/*.py` 的 endpoint 是否与 LX 上游 `musicSdk/` 一致 | 需 LX 源码，仓库内无法验证。 |
| `tests/sources/fixtures/*.json` 中每个 fixture 内容与测试断言的精确对应（如 `mg_hot.json` 154KB 是否含超出 hot 的数据） | 未逐字节核对。 |
| `src/lx_cli/tests/mock_sync_server.py`（421 行）与 `tests/mock_sync_server.py`（401 行）是否语义等价 | 行数不同，未逐行比对。 |
| DB 中复合 id（`<songId>_<hash>`）的确切分段语义 | 未找到生成该格式的代码。 |
| `sync_client.py` 网络协议部分的正确性（除已跑的集成测试外） | 缺少可用服务端；集成测试实跑失败（§6.2b）。 |
| `launcher.py` 的 `tasklist`/`taskkill` 实际行为 | 未在真实 LX 进程上操作（具破坏性且依赖用户环境）。 |
| `scripts/` 下探测脚本内容 | 超出 `src/lx_cli` 范围，未读取；故无法判断 `bd` 是否曾在探测阶段被考虑。 |
| `websockets` 版本兼容性 | `sync_client.py:545-550` 使用 `additional_headers`（v13+ 参数名），而 `pyproject.toml:16` 声明 `websockets>=12.0`（v12 用 `extra_headers`）—— **版本下限可能不兼容**。未实测 v12。 |

---

*报告结束。所有 `file:line` 引用基于审计时的 `lx-cli` 工作副本（`cli.py` 1236 行、`db_writer.py` 305 行、`db.py` 272 行、`sync_client.py` 721 行）。源代码零改动；唯一写入是 `LX-CLI-project/` 内的本报告与探针脚本。*
