# skills —— 供 AI 使用 lx-cli

> 本目录存放符合 **skill-creator 规范** 的 AI 技能，让 AI 能正确使用 lx-cli。
> 人类用户文档见 [`../docs/guide/`](../docs/guide/) 。

---

## 1. 目录结构

```
skills/
├── README.md                  ← 本文件
└── lx-cli/                    ← 技能名（与 frontmatter 的 name 一致）
    ├── SKILL.md               ← 必需；正文 <500 行，只放核心规则与常用命令
    ├── references/            ← 渐进披露：细节按需加载
    │   ├── commands.md        ← 全部命令与参数（从 --help 自动生成）
    │   ├── json-contract.md   ← --json 形状、退出码、错误码
    │   └── troubleshooting.md ← 按现象排障
    └── scripts/
        └── lx.sh              ← 便捷包装器（自动解析 CLI 根目录）
```

### 为什么这样拆

| 层 | 进上下文时机 | 内容 |
|---|---|---|
| `description`（~100 词） | **总是** | 决定 AI 何时加载本技能 |
| `SKILL.md` 正文 | 技能被触发时 | 铁律、常用命令、退出码、避坑 |
| `references/*` | 只有需要时 | 完整参数表、精确 schema、排障 |

> 正文刻意控制在 500 行内 —— 把"细节"外置，避免每次触发都灌满上下文。

---

## 2. 安装

### DSH

```powershell
mklink /D "$env:USERPROFILE\.dsh\skills\lx-cli" "<cli-root>\skills\lx-cli"
```

```bash
# Linux / macOS
ln -s "<cli-root>/skills/lx-cli" ~/.dsh/skills/lx-cli
```

`<cli-root>` = 含 `run.py` 与 `src/` 的目录。

### 其它 AI 工具

把 `skills/lx-cli/SKILL.md` 贴进对话即可（它自包含核心规则，
并指向同目录的 `references/`；若无法读取文件，可一并粘贴）。

---

## 3. 使用

装好后直接用自然语言，例如：

| 你说 | AI 会做 |
|---|---|
| "搜一下 yorushika" | `search --json` 并整理 |
| "加进我的「塞壬唱片」歌单" | 先 dry-run 报告重复情况，确认后 `--apply` |
| "现在放的是什么" | `status --json` |
| "音源该更新了吗" | `script update --all --json`（只预演） |

AI 在写操作前**应当**先预演并征得同意（SKILL.md 里是铁律）。

### 便捷包装器

```bash
sh skills/lx-cli/scripts/lx.sh --version
sh skills/lx-cli/scripts/lx.sh search "yorushika" --json
```

它自动解析 CLI 根目录（支持改名/搬家），必要时可显式指定：

```bash
LX_CLI_ROOT=<cli-root> sh skills/lx-cli/scripts/lx.sh status --json
```

---

## 4. 规范校验

本目录的 skill 必须符合 skill-creator 规范，已纳入测试与提交钩子：

```bash
python scripts/check_skills.py      # 校验（退出码 0/1）
python -m pytest tests/test_skills.py -q
```

校验项：

* `SKILL.md` 文件名**全大写**
* frontmatter 含 `name` / `description`
* `name` 匹配 `^[a-z0-9]+(-[a-z0-9]+)*$`，1–64 字符，**且与目录名一致**
* `description` 1–1024 字符，且包含触发词
* 正文建议 **< 500 行**
* `@path` 引用的文件**必须存在**
* 子目录只允许 `scripts/` `assets/` `references/`
* **不得写死本机路径**（换电脑后仍可用）

---

## 5. 维护

| 改动 | 要做什么 |
|---|---|
| CLI 命令/参数变了 | 重新生成 `docs/reference/commands.md`，并同步复制到 `references/commands.md` |
| 退出码/JSON 形状变了 | 更新 `references/json-contract.md` |
| 新增常见故障 | 更新 `references/troubleshooting.md` |
| 改了触发场景 | 更新 `SKILL.md` 的 `description`（决定何时加载） |

> `references/commands.md` 与 `docs/reference/commands.md` 内容相同：
> 由 `scripts/gen_commands_doc.py` 生成，是**单一事实来源**。

---

## 6. 相关文档

| 文档 | 内容 |
|---|---|
| [`../docs/guide/skills-usage.md`](../docs/guide/skills-usage.md) | 面向用户的 skills 说明 |
| [`../docs/guide/ai-usage.md`](../docs/guide/ai-usage.md) | AI 使用指南（更详细） |
| [`../docs/internals/README.md`](../docs/internals/README.md) | CLI 内部排障索引 |
