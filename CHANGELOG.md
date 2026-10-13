# 更新日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

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
  详见 `docs/planning/08-代理502归因更正与真机验证.md`。
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
