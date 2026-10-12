# skills 使用（用户向）

> 让 AI 助手（如 DeepSeek Harness / Claude 等）能**正确使用**本 CLI。
> 技术细节见 [`../../skills/README.md`](../../skills/README.md)。

---

## 1. 为什么需要

本 CLI 有几个**反直觉的规则**，AI 不知道就会出错：

| 规则 | 不知道的后果 |
|---|---|
| 写歌单前必须关闭 LX | 写了会被 LX 覆盖，白干 |
| 酷狗的歌曲 id **没有** `kg_` 前缀 | 写出的 id LX 不认，歌播不了 |
| `source` 是平台（`kg`）不是音源脚本名（`Flower`） | 概念混乱，用错命令 |
| 写操作默认是**预演** | 以为写进去了，其实没写 |
| 退出码 `3` = 需要关 LX | 只看到"失败"，反复重试 |

skill 就是把这些**提前告诉 AI** 的说明书。

---

## 2. 安装

### 2.1 DSH（推荐）

```powershell
# Windows：把 skill 目录链接进 DSH 的 skills 目录
mklink /D "$env:USERPROFILE\.dsh\skills\lx-cli" "<cli-root>\skills\lx-cli"
```

```bash
# Linux / macOS
ln -s "<cli-root>/skills/lx-cli" ~/.dsh/skills/lx-cli
```

`<cli-root>` = 含 `run.py` 与 `src/` 的目录（本项目 `lx-cli-v2/`）。

完成后，AI 在你说"搜歌/加进歌单/播放某首歌"时会自动用上它。

### 2.2 其它 AI 工具

把 `skills/lx-cli/SKILL.md` 的内容贴进对话即可（它自包含）。

建议同时告诉 AI CLI 的路径，例如：
> "用 `python D:\tools\lx-cli-v2\run.py` 来调用 lx-cli，先读 skills/lx-cli/SKILL.md。"

---

## 3. 装好后怎么用

直接用自然语言提需求即可，例如：

| 你说 | AI 会做的 |
|---|---|
| "搜一下 yorushika 的歌" | `search --json`，整理结果给你 |
| "把这些加进我的「塞壬唱片」歌单" | 先 `playlist add --dry-run` 报告重复情况，确认后 `--apply` |
| "现在放的是什么" | `status --json` |
| "音源是不是该更新了" | `script update --all --json`（哈希比对，不实际写入） |

> AI 在写操作前**应当**先预演并征得你同意（skill 里写了这条铁律）。

---

## 4. 验证 skill 生效

让 AI 执行：

> "列一下 lx-cli 能干什么，以及写操作需要注意什么。"

如果它能说出"写之前要关 LX"和"默认预演"，说明 skill 生效了。

---

## 5. 相关文档

* [`../../skills/lx-cli/SKILL.md`](../../skills/lx-cli/SKILL.md) —— 技能本体
* [`ai-usage.md`](ai-usage.md) —— AI 使用指南（JSON 契约等细节）
* [`功能与操作.md`](功能与操作.md) —— 人类用户手册
