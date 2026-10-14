# 更新日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## v0.3.0 — 2026-10-13

> 本版新增**下载能力**：CLI 不再只能"看"下载，而是能自己在本地下载音乐。
> ⚠️ 发布包体积因内置便携 Node 从 ~1.4 MB 增至 ~38 MB。

### 新增
- **批量下载（P3 增强）**：
  * `download list-all <歌单>` —— **整个歌单批量下载**（支持 id 或名称；
    名称歧义时报错让你用 id）
  * `download failed-all` —— 批量重下失败曲，涵盖 `status=error`
    **以及"记录在但文件已丢失"**两类
  * `download repair` —— `failed-all` 的短别名（保留兼容）
  * 共同特性：默认**预演**、`--limit` 限量、`--report` 导出 JSON 清单、
    `--source` 过滤、**跳过已存在**、**失败不中断**、每首间隔 0.35s 防限流
- **`lx download url/get/repair`（P3）—— CLI 自己执行 JS 音源下载**：
  * `download url <songmid> --source kw` 取播放直链（排查"能不能取到"）
  * `download get <songmid> --source kw --out <dir>` 下载单曲
  实现方式：**Node sidecar** 加载 LX 的 JS 音源脚本，复刻 desktop 的
  `musicUrl` 协议取直链，再由 CLI HTTP 下载。
- **内嵌便携 Node**（`tools/node/`，89 MB）：开箱即用，无需用户装 Node。
  用 `scripts/prepare_node.py` 准备；发布包随带。
- **`lx download` 命令族（只读）** —— 查看下载状况：
  * `download stats` —— 总数/完成/失败、按状态/质量/来源统计、总字节
  * `download list` —— 逐条列出（可按 status/source/quality 过滤）
  * `download failed` —— 只列失败项，**每条给出可操作建议**
  * `download verify` —— 校验文件是否真实存在（找出"记录在但文件没了"）
  全部只读，LX 运行时也安全。
- **`lx script doctor`** —— 音源脚本体检：
  * 字符数过小 → 标记"疑似空壳"（实测根因：972 字符脚本导致 26 首下载失败）
  * 识别**转发型脚本**及其依赖的第三方后端（后端挂了脚本就废）
  * 提取支持的平台/音质；检查头部注释块
  * 自动推荐可替代的健康脚本与启用命令

### 修复
- ★ **`songmid` 带 source 前缀导致取链必然失败**：
  `download_list` 里的 id 形如 `kw_223088839`，但 JS 音源脚本需要**裸 id**。
  实测：传 `kw_223088839` → 失败；传 `223088839` → 成功。
  现统一用 `parse_song_id` 解析出裸 id（kg 同时剥掉 hash）。
  这个 bug 会让批量重下 **全部 32 首失败**。
- `verify_downloads` 大小比对阈值从 1% 放宽到 **10%** ——
  实测 LX 下载后会补写 ID3 标签，正常文件也差 1~2%，1% 会误报 70 条。

### 测试
- 448 passed, 2 skipped（新增 88 用例）

### ⚠️ 安全说明
CLI 现在会**执行第三方 JS 音源脚本**。Node 的 `vm` **不是安全沙箱**
（脚本理论上可经原型链逃逸）。已做的限制：独立子进程、不注入
`fs`/`child_process`/`net`、只暴露受控 `lx.*` 接口、30s 超时强杀、
`--max-old-space-size=256`。**请只运行你信任的音源脚本。**

### 资源管理
Node 为**一次性子进程**：按需启动、取到结果立即退出、绝不常驻。
已用 12 个用例覆盖（成功/失败/超时/坏脚本/Ctrl+C 后均无残留进程）。

---

## v0.2.1 — 2026-10-13

### 新增
- **`lx status-install`**：显示完整安装状态 —— 版本号、安装方式
  （editable / site-packages / 免安装）、包位置、Python 版本与架构、
  依赖是否齐全、`lx.exe` 解析结果、数据目录是否存在、`lx` 是否全局可用、
  内置 wheels 离线能力。支持 `--json`。
  （区别于 `--version`，后者保持只显示版本号）
- **`install.bat` 支持就地更新旧版**：检测到已装 `lx-cli` 时自动覆盖更新，
  无需先卸载；首次安装与升级用同一脚本。

### 修复
- **Open API 502（真机验证）**：根因是 `bindLan=true` 时把连接目标写成
  `0.0.0.0`（监听通配符，不可连接且会被发给系统代理）。现固定为 `127.0.0.1`。
  另为本机端点引入独立会话 `_local_session()`（`trust_env=False`）作为加固。
  详见 `docs/guide/迁移到新电脑.md` §9.1。
- **`--exe` 选项此前未生效**：`find_exe()` 现在接受显式覆盖参数。
- **`lx where` 的潜在崩溃**：改用 `find_exe(ctx.exe)`。
- **`status-install` 的全局 lx 误判**：正确区分"PATH 上的 lx.exe"与
  "当前目录的 ./lx.bat"，避免假阳性/假阴性。

### 变更
- `lyric` 增加 `lyric-all` 别名（与 Open API 端点同名，减少混淆）。
- 发布包内置全部依赖 wheel（离线安装，见 v0.2.0）。

### 测试
- 344 passed, 2 skipped。

---

## v0.2.0 — 2026-10-12

首个公开发布版本。Windows 命令行工具，围绕 LX Music Desktop 构建：

- 搜索（5 平台官方接口聚合/单源/多源）
- 歌单读写 + 内容比对后批量插入（默认预演）
- 播放控制（开放 API）+ 指定歌曲播放（Scheme URL）
- 音源脚本管理（对接 pdone/lx-music-source）
- 全命令 `--json` + 稳定退出码
- 可移植：改目录名/换电脑可用；自动定位数据目录与安装位置
- 内置 wheels 离线安装（`install.bat`）
- `lx doctor` 自检、`lx uninstall` 卸载
- 291 → 336 测试
