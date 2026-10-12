# 数据库

> `lx.data.db` 的 schema、读写规则、以及必须容忍的边界数据。

---

## 1. Schema（真实库实测）

```sql
CREATE TABLE my_list (
  id TEXT NOT NULL, name TEXT NOT NULL,
  source TEXT, sourceListId TEXT,
  position INTEGER NOT NULL, locationUpdateTime INTEGER,
  PRIMARY KEY(id));

CREATE TABLE my_list_music_info (
  id TEXT NOT NULL, listId TEXT NOT NULL, name TEXT NOT NULL,
  singer TEXT NOT NULL, source TEXT NOT NULL,
  interval TEXT, meta TEXT NOT NULL,
  UNIQUE(id, listId));                     -- ★ 复合唯一

CREATE TABLE my_list_music_info_order (
  listId TEXT NOT NULL, musicInfoId TEXT NOT NULL,
  "order" INTEGER NOT NULL);               -- ★ 无主键、无唯一约束；order 是保留字
```

其它表：`download_list`（注意列名拼写 **`isComplate`**）、`dislike_list`、
`lyric`（`text` 是 **base64 的 LRC**，`source` 恒为 `'raw'`）、
`music_url`（URL 含时效签名）、`music_info_other_source`（**本机为空表**）、`db_info`。

---

## 2. 读取规则

### 2.1 排序（有坑）

```sql
-- ❌ 旧版：缺 order 的行被 COALESCE 拉到 0，排到最前（静默错序）
ORDER BY COALESCE(o."order", 0)

-- ✅ 本项目：缺 order 的行排最后
ORDER BY (o."order" IS NULL), o."order"
```

**`order` 可能稀疏**：实测某歌单 246 行但 `max(order)=247`（缺 226/227）。
**不能把 `order` 当数组下标。**

### 2.2 搜索（有坑）

```sql
-- ❌ 旧版：LOWER() 只处理 ASCII，对中文完全无效；且不转义通配符
WHERE LOWER(name) LIKE ?

-- ✅ 本项目：直接用 LIKE（SQLite 对 ASCII 本身大小写不敏感）+ ESCAPE 转义
WHERE name LIKE ? ESCAPE '\'
```

用户输入里的 `%` / `_` 必须转义，否则变成通配符。

### 2.3 只读连接

```python
sqlite3.connect(f"file:{path}?mode=ro", uri=True)
```

> ⚠️ 必须用 **URI** 形式；`connect(path, read_only=True)` **不生效**。

---

## 3. 写入规则

| 规则 | 说明 |
|---|---|
| **LX 必须关闭** | LX 内存缓存 + 全量回写，运行时写会被覆盖 |
| 单事务 | 每次调用一个事务，失败整体回滚 |
| **`BEGIN IMMEDIATE`** | 读-改-写之前立即取写锁，防丢更新 |
| 幂等 | 同 id 重复 add 不产生重复行（返回 `skipped`） |
| `order` 压实 | 重建为 `0..n-1`；写入前先 `DELETE` 该歌单所有 order 行 |
| 虚拟歌单 | `default`/`love` **无 `my_list` 行**；可写歌，**不可改名/删除**；不更新 `locationUpdateTime` |
| 用户歌单 id | `userlist_<毫秒><序号>`，**必须保证唯一**（旧版纯毫秒会同毫秒撞主键） |

### 3.1 写入流程（`add_songs`）

```
BEGIN IMMEDIATE
  ├─ 检查歌单存在（虚拟歌单视为存在）
  ├─ 读现有 id 顺序（缺 order 排最后，并去重）
  ├─ 逐条 INSERT OR IGNORE 新歌（已存在则 skipped）
  ├─ DELETE 该歌单全部 order 行
  ├─ 按 position（top/bottom）拼接后重新插入 order
  └─ 更新 locationUpdateTime（虚拟歌单跳过）
COMMIT
```

---

## 4. 边界数据（必须容忍）

来自真实库 1892 行的实测：

| 数据 | 情况 |
|---|---|
| **kg 的 id** | 934 行无前缀 + 24 行带 `kg_`（同一歌单内混用） |
| **local 的 id** | 是文件路径，含 `_`，Windows 与 Android 路径混存 |
| **歌手分隔** | `、` 497 行；`;` 217 行、`&` 6 行**是名字的一部分** |
| **`interval`** | 67 行非 `MM:SS`（分钟位 1–3 位，最长 `184:23`） |
| **`meta.songId`** | kg int 89/str 869；kw int 287/str 14（类型不稳定） |
| **`picUrl`** | 可能是 JSON `null` |
| **`qualitys[].hash`** | 键可能不存在 |
| **跨歌单同 id** | 192 个 id 出现在多个歌单（正常） |
| **跨平台同曲** | 256 组（同名+同歌手，不同 id） |
| **虚拟歌单** | `default` 164 首、`love` 188 首，`my_list` 中无行 |
| **孤儿缓存** | `lyric` 636 行、`music_url` 131 行关联不上现存歌单 |

> **数据本身很干净**：`id/listId/name/singer/source/interval/meta` 的
> NULL 与空串**全部为 0**；`(id,listId)` 重复组 = 0。

---

## 5. 夹具（测试用）

真实库**不能**直接用于测试（隐私 + 会被写坏）。用
`scripts/make_fixture.py` 从备份派生**脱敏夹具**：

```bash
python scripts/make_fixture.py <备份DB> tests/fixtures/lx.data.db
```

* **保留结构**：kg 裸 id 934 / 二次前缀 24、稀疏 order、虚拟歌单、多歌手符号
* **替换隐私**：歌名/歌手 → 占位、local 路径 → 假路径、URL → `example.invalid`
* 校验过：真实内容命中 **0**（ヨルシカ/塞壬/Amnesia/… 全为 0）

夹具已入库（`.gitignore` 里对它有例外），保证新克隆也能跑测试。

---

## 6. 排查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| `attempt to write a readonly database` | 用了只读连接（`db query` 写 SQL 时正常） | 用写命令而不是 `db query` |
| `歌单不存在` | id 拼错，或读的是别的库 | `lx playlist list` 确认；注意 `--db` 要放**子命令前** |
| 写入后 LX 里看不到 | LX 正在运行被覆盖 / 未刷新 | 关 LX 再写；写完启动 LX |
| 顺序不对 | 该歌单 order 稀疏 | 已处理（缺 order 排最后）；必要时 `reorder` |
| 报 `database is locked` | LX 正在写 | 等几秒，或关 LX |
