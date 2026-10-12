# tools —— 独立辅助工具

> 这些工具**不属于** `lx` 命令，是独立的脚本，按需运行。
> 从旧版 `lx-cli/scripts/` 迁移而来（去掉了硬编码本机路径）。

---

## `lxsrc_probe.js` —— 音源脚本通用探针 ★

**用途**：解析一个音源 `.js` 文件，弄清楚它到底请求哪些接口、用什么参数、
返回什么字段。当某个音源**失效**或你想**评估**它时用。

```bash
# 列出本机已安装的音源（读 LxDatas/user_api.json）
node tools/lxsrc_probe.js --from-store --list

# 探针某个已安装音源
node tools/lxsrc_probe.js --from-store --name 独家音源 --strings

# 探针单个文件
node tools/lxsrc_probe.js path/to/source.js --json out.json

# 批量 + 生成 Markdown 报告
node tools/lxsrc_probe.js <目录> --json out.json --md out.md

# 混淆脚本：还原字符串表
node tools/lxsrc_probe.js source.js --strings

# 跑不出来时：扫 6 种 lx 桩变体
node tools/lxsrc_probe.js source.js --variants
```

**输出**：元数据 / 混淆族 / 生效源 / 真实 endpoint / 响应字段契约 /
参数溯源 / 自动诊断。

零依赖，不联网，需 Node.js 16+。

---

## `lxsrc_bisect_template.js` —— 反向二分模板

**用途**：当探针结论可疑时，从"能跑通的桩"出发逐个删/改，
定位**是哪个细节**改变了脚本行为。

改顶部 `SRC` 与 `run(...)` 列表即可用于新脚本。

---

## `lx_to_anylisten.py` —— LX 歌单 → any-listen 转换器

**用途**：把 LX 的 `.lxmc` 歌单文件转成 any-listen 的 `.alcfg` 格式。

```bash
python tools/lx_to_anylisten.py <input.lxmc> [-o output.alcfg] [--no-gzip]
```

支持的 LX 顶层 `type`：`playList_v2` / `allData_v2` / `playListPart_v2` /
`playListPart` / `defautlList` / `playList`。自动识别 gzip。

---

## 注意

| 事项 | 说明 |
|---|---|
| 这些工具**不是** `lx` 命令的一部分 | 需单独 `node` / `python` 调用 |
| `lxsrc_*.js` 需 Node.js ≥16 | 纯 JS，无 npm 依赖 |
| 与 `lx script` 的分工 | `lx script` 管**安装/更新**；这些工具管**分析/转换** |

## 相关文档

* 音源脚本机制：[`../docs/internals/scripts.md`](../docs/internals/scripts.md)
* 反混淆实战：[`../docs/internals/research/03-source-scripts.md`](../docs/internals/research/03-source-scripts.md)
* `.lxmc` 格式：[`../docs/internals/research/01-desktop-data-model.md`](../docs/internals/research/01-desktop-data-model.md)
