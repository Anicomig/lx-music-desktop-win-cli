# 排障速查

> SKILL.md 的补充。只在遇到具体失败时加载。

## 1. 先做这三步

```bash
python <cli-root>/run.py --version                       # 是 0.2.x 吗？
python <cli-root>/run.py -vv where --json                # 包位置 / exe / 数据目录
python <cli-root>/run.py --debug-trace <失败的命令>       # 未预期异常时打堆栈
```

## 2. 按现象定位

| 现象 | 最可能原因 | 处理 |
|---|---|---|
| `No such command 'script'`，命令莫名变少 | **加载到了旧版 lx_cli** | 改用 `run.py`，或设 `PYTHONPATH=<cli-root>/src` |
| `ModuleNotFoundError: lx_cli` | 未安装且未用 `run.py` | 用 `run.py`，或在 `<cli-root>` 下 `pip install -e .` |
| `无法连接开放 API` / `openapi_disabled` | LX 未运行，或"开放 API 服务"未启用 | `config-enable` 后重启 LX |
| `openapi_timeout` | LX 正在启动 | 等几秒；`start --wait` 会自动等 |
| 退出码 3 `lx_running` | 写操作但 LX 开着 | **让用户关闭 LX**；不要 `--force` |
| `attempt to write a readonly database` | 用 `db query` 跑了写语句 | 改用 `playlist` / `script` 等写命令 |
| `PathError: 找不到 lx-music-desktop.exe` | 装在非常规位置 | `--exe <路径>` 或 `setx LX_EXE <路径>` |
| 数据目录不对（多账号/便携版） | `%APPDATA%` 或 portable 布局 | `where --json` 核对；必要时 `set LX_DATA_DIR=<LxDatas>` |
| 中文乱码 | 控制台编码 | 加 `--json`（CLI 已尽量切 UTF-8） |
| `UnicodeEncodeError` | 旧版脚本在 GBK 控制台 | 升级；或 `chcp 65001` |

## 3. 搜索类问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 某平台 0 条，其它正常 | **限流**（连续快速请求） | 等 3–5 秒重试；或 `--source` 指定别的平台 |
| 聚合慢 | 并发 5 平台（正常 1–2 秒） | 用 `--source` 单平台 |
| `kg` 的 `song` 拿不到数据 | kg 按 **hash** 查 | 传 `--hash`，或把完整 id 当 `--songmid` |
| 专辑名为空（kg） | 搜索接口不返回专辑字段 | 正常；`album` 会从曲目推断 |
| 全平台都失败（exit 4） | 网络/PAC/代理 | 检查网络；`-vv` 看具体 URL |

> **聚合模式的语义**：单平台失败**不**导致整体失败，只体现在 `failedPlatforms`。

## 4. 播放类问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 搜得到但点了没声音 | **没装/没启用 JS 音源脚本** | `script list` → `script enable <名字>` |
| `play` 后 `status` 没变 | 状态更新**异步**（约 1 秒） | 等 1 秒再查，别立刻断言 |
| `status` = `error` | 切歌过程中的正常中间态 | 稍等再看；不是崩溃 |
| `search-play` 没反应 | Scheme URL **单向且慢**（约 9 秒） | 等 10 秒再 `status` 确认 |
| `lxmusic://` 完全无反应 | 协议未注册 / LX 未装 | 重装 LX（它会注册协议） |
| 收藏了"错误的歌" | Open API 的 `collect` **只作用于当前播放曲** | 想收藏任意曲：写 `love` 歌单 |

## 5. 歌单/数据库问题

| 现象 | 原因 | 处理 |
|---|---|---|
| `no_such_list` | list_id 拼错，或读的不是那个库 | `playlist list --json` 确认；`--db` 要放**子命令前** |
| 写入后 LX 里看不到 | LX 正在运行被覆盖，或未刷新 | 关 LX 再写；写完启动 LX |
| 顺序不对 | `order` 稀疏（真实库存在） | 已处理（缺 order 排最后）；必要时重排 |
| `database is locked` | LX 正在写 | 等几秒，或关 LX |
| `--db` 似乎没生效 | 全局选项放在了子命令后 | 写成 `lx --db x.db playlist list` |
| 内置歌单改不了名 | `default`/`love` 是虚拟歌单 | 设计如此（LX 也不允许） |

## 6. 音源脚本问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 装完 LX 里看不到 | LX 未重启 | 重启 LX |
| 更新报"无来源记录" | 脚本是你手动导入的（CLI 没记录） | `script install <仓库名> --apply` |
| 更新报"被手动修改过" | 你改过脚本内容 | 确认要覆盖再加 `--force` |
| 下载失败（exit 4） | 直链 + 镜像都不通 | 手动下载后 `--file <路径>` |
| 下载到 HTML | 镜像失效 | 已被识别并报错；换镜像或手动下载 |
| `script verify` 报"缺少头部注释块" | 脚本不是合法音源格式 | 换一个源 |
| 脚本装好但某些歌播不了 | 该脚本的服务端挂了 | `script enable <另一个>` |

## 7. 安全提醒

* 任何写操作前，先 `backup <目录>`（含 WAL 三件套 + SHA256 清单）
* 不要手工编辑 `%APPDATA%\lx-music-desktop\LxDatas\user_api.json` ——
  它是 `gz_`+**zlib** 编码（**不是 gzip**）、Tab 缩进、且 LX 期望原子写
* 不要绕过硬性前置检查（`--force`）除非你清楚后果

## 8. 什么时候该看更深的文档

| 需求 | 文档 |
|---|---|
| 精确 JSON 字段 | [`json-contract.md`](json-contract.md) |
| 全部命令与参数 | [`commands.md`](commands.md) |
| CLI 内部原理/契约 | `<cli-root>/docs/internals/README.md`（排障索引） |
| 桌面端数据结构 | `<cli-root>/docs/internals/research/01-desktop-data-model.md` |
| 真实用户数据统计 | `<cli-root>/docs/internals/research/02-real-user-data.md` |
| 音源脚本机制 | `<cli-root>/docs/internals/research/03-source-scripts.md` |
