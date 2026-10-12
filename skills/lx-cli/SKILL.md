---
name: lx-cli
description: Control LX Music desktop (洛雪音乐助手) from the command line — search music across 5 platforms (kg/kw/tx/wy/mg), read/write playlists in the local database, control playback, and manage JS source scripts. Use when user asks to "搜歌", "search songs", "加进歌单/add to playlist", "看我的歌单/list my playlists", "播放某首歌/play this song", "更新音源/update music sources", or when a task requires driving LX Music / lx-cli programmatically.
license: MIT
compatibility: opencode
metadata:
  audience: ai-agents
  workflow: music-control
  language: python
  requires: lx-music-desktop
---

# LX CLI (lx-cli)

Drive **LX Music desktop (洛雪音乐助手)** from the command line: search, playlists,
playback control, and source-script management. Every command supports `--json`
with a stable shape for automated consumption.

## ⚠ CRITICAL RULES (read first)

1. **Writes require LX to be CLOSED.** Editing playlists, config, or source scripts
   while LX runs gets **overwritten** by LX's in-memory cache. The CLI returns
   exit code **3** in that case. **Never use `--force` to bypass it** — it can lose data.
2. **Write commands default to dry-run.** `playlist add` and `script install/update`
   report first and write nothing. Check the report, then add `--apply`.
3. **Always pass `--json`.** stdout is then pure JSON; logs go to stderr.
4. **Branch on exit codes**, not on output text.
5. **Never infer the platform from the id prefix** — Kugou (`kg`) ids have **no**
   `kg_` prefix (they look like `631537655_5A86…`).

## When to Use This Skill

Use when the user wants to:
- search for songs, or see what a song's album/artist/platform is
- add songs to a playlist, create/rename/delete playlists
- see what's playing, or control playback
- play a *specific* song (not just next/prev)
- check for or install/update JS source scripts (音源)

## Step 0 — Verify the CLI works

Prefer `run.py` (path-independent; survives renaming/moving the folder):

```bash
python <cli-root>/run.py --version       # must print 0.2.x
```

* `<cli-root>` = the folder containing `run.py` and `src/`.
* If `lx` is on PATH (installed), `lx …` also works.
* ⚠️ **Do not use bare `python -m lx_cli`** unless installed — an older `lx-cli`
  may be present and Python will silently load it (symptoms: commands missing).

Quick self-check before real work:

```bash
python <cli-root>/run.py where --json       # exe + data dir resolve correctly
python <cli-root>/run.py search "test" --limit 1 --json
python <cli-root>/run.py db stats --json
```

## Instructions

### 1. Search songs

```bash
python <cli-root>/run.py search "yorushika" --json               # aggregate all 5 platforms
python <cli-root>/run.py search "yorushika" --source kg --json   # one platform
python <cli-root>/run.py search "yorushika" --sources kg,wy --json
```

Each item has `id` `name` `singer` `singerList` `albumName` `interval`
`source` (`kg`) and `sourceLabel` (`酷狗音乐`).
`source` is a **platform id**, never a script name.

### 2. Add songs to a playlist

```bash
# 1) dry-run — read wouldAdd / alreadyIn / suspectDuplicates
python <cli-root>/run.py playlist add <list_id> --from-search "yorushika" --source kg --json
# 2) only then write (LX must be closed)
python <cli-root>/run.py playlist add <list_id> --from-search "yorushika" --source kg --apply --json
```

Pipe an already-filtered selection instead:

```bash
python <cli-root>/run.py search "yorushika" --json > songs.json
python <cli-root>/run.py playlist add <list_id> --from songs.json --apply --json
```

`--dedupe-by id` (default, conservative) | `name+singer` | `fuzzy`.

### 3. Playback

```bash
python <cli-root>/run.py play|pause|toggle|next|prev --json
python <cli-root>/run.py status --json        # name/singer/status/progress
python <cli-root>/run.py volume 50 --json
```

Play a **specific** song (Open API can't; uses Scheme URL — slow, no return value):

```bash
python <cli-root>/run.py search-play "又三郎" --singer ヨルシカ --json
# takes ~9s to take effect; verify afterwards with status --json
```

### 4. Source scripts (音源)

```bash
python <cli-root>/run.py script list --json          # installed + which is active
python <cli-root>/run.py script update --all --json  # dry-run, content-hash based
python <cli-root>/run.py script install flower --apply --json   # needs LX closed
```

## Exit Codes (branch on these)

| Code | Meaning | Action |
|---|---|---|
| `0` | OK | parse stdout |
| `1` | Runtime error | read `error.message` |
| `2` | **Usage error** (bad args / unknown platform) | fix args, **do not retry** |
| `3` | **LX must be closed** | ask the user to close it; **never `--force`** |
| `4` | Upstream failure (network/platform) | may retry with backoff |

Failures still print JSON: `{"error": {"code","message","detail"}}`.

## Tips & Known Behaviors

| Symptom | Reality |
|---|---|
| One platform returns 0 results | **rate-limited**; wait a few seconds. Aggregate mode records it in `failedPlatforms` |
| `play` then `status` unchanged | status updates are **async** (~1 s). Don't assert immediately |
| `status` is `error` | normal during track switching — **not** a crash |
| `search-play` seems ignored | Scheme URL is one-way and slow (seconds) |
| `status` looks boolean | it's a **string**: `playing`/`paused`/`error`/`stoped` |
| Chinese mojibake in console | use `--json`, or the CLI switches the console to UTF-8 |

## Never Do This

- ❌ Use `--force` to bypass the "LX is running" check
- ❌ Edit `%APPDATA%\lx-music-desktop\LxDatas\*` by hand — use this CLI's commands
- ❌ Treat `source` as a source-script name
- ❌ Assume `kg` ids start with `kg_`
- ❌ Run `--apply` without reviewing the dry-run report first

## Reference Files

Load only when needed:

- @references/commands.md — full command/flag reference (auto-generated from `--help`)
- @references/json-contract.md — exact `--json` shapes + exit-code/error taxonomy
- @references/troubleshooting.md — deeper failure diagnosis (rate limits, playback, DB, scripts)
- @scripts/lx.sh — convenience wrapper resolving `<cli-root>` automatically
