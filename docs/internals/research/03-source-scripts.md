# 03 — 洛雪音乐助手 JS 音源脚本：导入 / 更新 / 执行 机制调研

> 调研对象（均只读）：
> - LX Music Desktop 源码：`C:\Users\EDY\Documents\workspace\lx-music-desktop-2.12.5`（v2.12.5）
> - 音源仓库（`pdone/lx-music-source` 的 GitHub 镜像）：`C:\Users\EDY\Documents\workspace\lx-music-source-main`
> - **额外实证样本**（本次调研发现的真实运行时数据）：`C:\Users\EDY\AppData\Roaming\lx-music-desktop\LxDatas\user_api.json`（只读读取，未修改）
>
> 阅读约定：
> - ✅ **【已核实】** = 本报告中直接引用了源码/文件/哈希/解码结果。
> - ⚠️ **【推断】** = 未直接验证，仅由上下文推理得出。
> - 所有 `file:line` 均相对于上述目录根。

---

## 0. 执行摘要（TL;DR）

| 问题 | 结论 |
|---|---|
| 脚本存放在哪 | `%APPDATA%\lx-music-desktop\LxDatas\user_api.json`，顶层对象 `{"userApis":[...]}` |
| 脚本编码 | ✅ **已核实**：`"gz_" + base64( zlib.deflate( script_utf8 ) )`，逐字节可复现 |
| 元数据来源 | ✅ **已核实**：正则从脚本首部 `/* ... */` 块中抠 `@name/@description/@version/@author/@homepage` |
| 脚本能否搜索 | ❌ **不能**。桌面端只实现 `musicUrl` / `lyric` / `pic`。✅ 由 `supportActions` 硬编码 + 类型定义共同证实 |
| 执行环境 | ✅ **已核实**：隐藏 `BrowserWindow`（`show:false`）+ preload 通过 `contextBridge` 暴露 `window.lx`，再 `webFrame.executeJavaScript(script)` |
| 非 Electron 能否运行 | ❌ 原生不能。依赖 `webFrame`、`needle`、Node `zlib/crypto`、`tunnel`，且 `lx` 全部由 preload 注入 |
| 更新机制 | ✅ **已核实**：**LX 本体不做更新检查**。脚本自己发 `updateAlert` 事件，App 只负责弹窗 + 打开 URL |
| 更新地址来源 | 两种：脚本硬编码 `SCRIPT_MD5` + 自建接口轮询；或 `@update_url` 元数据（仅个别脚本）|
| CLI 要做的最小动作 | 下载 `latest.js` → 校验首部注释块 → 解析元数据 → zlib deflate → base64 → 写入 `user_api.json` |

---

# Part A — 音源仓库 `lx-music-source-main`

## A.1 仓库根布局 【已核实】

```
lx-music-source-main/
├── .github/
├── AGENTS.md           # 仓库自身的 AI/贡献者规范（UTF-8）
├── README.md           # 各源 raw 直链 + 镜像加速站说明（UTF-8）
├── CreateLatest.py     # latest.js 生成脚本（UTF-8）
├── changqing/  flower/  grass/  huanyin/  huibq/
├── ikun/  juhe/  lx/  qdy/  sixyin/
```

> 编码说明：`AGENTS.md` / `README.md` / `CreateLatest.py` 三个文件**实际是 UTF-8**（Python 解码验证通过）。
> 在 Windows PowerShell 里 `Get-Content` 看到乱码，是因为控制台输出编码为 GBK，而非文件本身是 GBK。
> ✅ 已核实：三个文件 `raw.decode('utf-8')` 成功，`decode('gb18030')` 会先失败或被跳过。**无需** GB18030 解码。
> 但要注意：**仓库里的 `.js` 脚本内容包含大量非 ASCII**（中文注释、CJK、Unicode 私有区 PUA、组合变音符），必须始终按 **UTF-8** 读写，任何按 GBK 处理都会损坏脚本。

## A.2 各目录文件清单与哈希 【已核实】

用 Python `hashlib` 逐文件计算（`md5` 全量，`sha256` 取前 16 位）：

| 目录 | 文件 | 大小 (bytes) | md5 | 备注 |
|---|---|---|---|---|
| `changqing` | `1.3.0.js` | 27645 | `a1371aa279a13de8182bee16a6a32f68` | |
| | `latest.js` | 27645 | `a1371aa279a13de8182bee16a6a32f68` | **同哈希** |
| `flower` | `1.js` | 10057 | `28a6d8f0d49206a73b6b2f7d3bc10c57` | |
| | `latest.js` | 10057 | `28a6d8f0d49206a73b6b2f7d3bc10c57` | **同哈希** |
| `grass` | `1.js` | 9176 | `d0ad31bc256f49e2dc9d70b36b1e6eae` | |
| | `latest.js` | 9176 | `d0ad31bc256f49e2dc9d70b36b1e6eae` | **同哈希** |
| `huanyin` | `3.js` | 7316 | `b282089b5da6bea418c44b4a3f5fa317` | |
| | `latest.js` | 7316 | `b282089b5da6bea418c44b4a3f5fa317` | **同哈希** |
| `huibq` | `1.2.0.js` | 2727 | `f2e262e192f1e526bc9333a16ebcdf2b` | |
| | `latest.js` | 2727 | `f2e262e192f1e526bc9333a16ebcdf2b` | **同哈希** |
| `ikun` | `6.js` | 4494 | `6c352d53568e471f29f89b77172db833` | 旧版本，**无对应** latest |
| | `22.js` | 4991 | `e837cf818441096f5870e24c631343ee` | 最高版本 |
| | `latest.js` | 4991 | `e837cf818441096f5870e24c631343ee` | **= `22.js`** |
| `juhe` | `3.js` | 994 | `e8620ef707cd4bb62d1055f0e1ea848b` | |
| | `latest.js` | 994 | `e8620ef707cd4bb62d1055f0e1ea848b` | **同哈希** |
| `lx` | `2.js` | 10593 | `d68a5ad5bb9ec6019ab8c4cada3c417c` | |
| | `3.js` | 10595 | `e557cbe686b85779b4cae95a15e12dba` | |
| | `4.js` | 114852 | `1888f9865338afe6d5534b35171c61a4` | |
| | `5.js` | 62829 | `60cdb8135b8fb6eb2d701a6e679a4d04` | |
| | `6.js` | 64094 | `bad0bcfaa97f19041486ef113c705dda` | 最高版本 |
| | `latest.js` | 64094 | `bad0bcfaa97f19041486ef113c705dda` | **= `6.js`** |
| `qdy` | `9.3.js` | 31090 | `4f9d4c4409d84cf3b7309f906454ab39` | |
| | `latest.js` | 31090 | `4f9d4c4409d84cf3b7309f906454ab39` | **同哈希** |
| `sixyin` | `1.2.0.js` | 372394 | `80c1c133fad59478768115df30e55a5c` | 旧版本 |
| | `1.2.1.js` | 333015 | `430020e5017137615c970e0e62881742` | 最高版本 |
| | `latest.js` | 333015 | `430020e5017137615c970e0e62881742` | **= `1.2.1.js`** |

## A.3 `latest.js` 是什么？ 【已核实】

**结论：`latest.js` 是一个物理副本（byte-for-byte copy），不是符号链接、不是生成物、不是重定向。**

证据：

1. 10 个目录中，`latest.js` 与「该目录最高版本文件」**md5 完全一致**（上表加粗行）。
2. `CreateLatest.py` 直接调用 `shutil.copy2(src, dst)`（见 A.4）——`copy2` 会复制内容与时间戳，产生独立文件。
3. 目录中不存在 `.gitattributes`/LFS 指针/软链接特征；`flower/latest.js` 与 `flower/1.js` 同为 10057 bytes 且同为普通文件。
4. **反证**：`ikun/` 与 `lx/` 与 `sixyin/` 保留了旧版本文件，但 `latest.js` **只**指向最高版本，说明它不是「任一文件的别名」而是「被显式选中的那一个」。

⚠️ **【推断】**「最高版本文件」不等于「latest.js 的来源」——真正的来源是 `CreateLatest.py` 里手写的 `VERSIONS` 字典。如果维护者忘记改字典，`latest.js` 会停留在旧版本。也就是说 **`latest.js` 是唯一权威的「当前版本」指针，文件名里的版本号不是**。

## A.4 `CreateLatest.py` 解析 【已核实】

全文（37 行，UTF-8）：

```python
#!/usr/bin/env python3
"""跨平台脚本：更新各音乐源的 latest.js 文件"""

import os
import shutil
from pathlib import Path

# Latest Version Numbers
VERSIONS = {
    'changqing': '1.3.0',
    'flower': '1',
    'grass': '1',
    'huanyin': '3',
    'huibq': '1.2.0',
    'ikun': '22',
    'lx': '6',
    'sixyin': '1.2.1',
    'juhe': '3',
    'qdy': '9.3'
}

def main():
    script_dir = Path(__file__).parent.resolve()

    for source, version in VERSIONS.items():
        src = script_dir / source / f'{version}.js'
        dst = script_dir / source / 'latest.js'

        if src.exists():
            shutil.copy2(src, dst)
            print(f'✅ {source}: {version}.js → latest.js')
        else:
            print(f'❌ {source}: {version}.js 不存在')

if __name__ == '__main__':
    main()
```

`CreateLatest.py:31` —— 核心就是一行 `shutil.copy2(src, dst)`。

**它生成什么**：把 `<源>/<版本>.js` 全量复制为 `<源>/latest.js`。不生成索引、不生成校验和、不写版本清单 JSON。**没有产物文件**。

**新增版本的更新工作流**（`AGENTS.md:27-31` 权威描述）：

```
### 添加新版本
1. 将新版本 JS 文件放入对应源目录（如 sixyin/1.2.2.js）
2. 编辑 CreateLatest.py，更新 VERSIONS 字典中的版本号
3. 运行 python CreateLatest.py
```

`AGENTS.md:19-25` 补充：

```
### 更新 latest.js
python CreateLatest.py
将各源的版本文件复制为 latest.js。
```

其它相关约定（`AGENTS.md:69-79`）：

- 版本命名：语义化版本（`1.2.0`、`4`），**版本号即文件名**（`1.2.0.js`），`latest.js` 始终指向当前最新版本。
- Git 提交信息格式：`[源名] 更新到 v版本号`，例如 `[sixyin] 更新到 v1.2.1`。
- `AGENTS.md:83`：「JS 文件通常是混淆或压缩后的代码，无需手动编辑」。

> ✅ 目录中没有 `.github/workflows` 自动执行 `CreateLatest.py` 的证据（`.github/` 存在内容但未发现与本脚本相关的 workflow；⚠️ 未逐一读取 `.github/` 全部内容，此项为**推断**：`latest.js` 由维护者手动生成并提交，因此 `latest.js` 与其版本文件**同一次 commit 内**进仓库）。

## A.5 脚本元数据头部格式 【已核实】

`AGENTS.md:35-60` 是权威定义：

```
### JS 文件规范
- 文件头部必须包含注释块，包含：
  - `@name` - 音源名称
  - `@description` - 描述和版本信息
  - `@version` - 版本号
  - `@author` - 作者
  - `@homepage` - 主页（可选）
  - `@repository` - 仓库地址（可选）
  - `@netease` / `@tencent` - 平台标识（可选）

示例：
/*!
 * @name 六音音源
 * @description v1.2.1
 * @version v1.2.1
 * @author 六音
 * @homepage www.sixyin.com
 * @netease MUSIC_U=;
 * @tencent ts_last=y.qq.com/n/ryqq/album;
 * @preserve
 */
```

- `@preserve` 表示保留注释，防止被压缩工具移除（`AGENTS.md:60`）。

### 真实脚本头部样本

**`sixyin/1.2.1.js:1-9`**（含 `@preserve`，与 AGENTS.md 示例完全对齐）：

```javascript
/*!
 * @name 六音音源
 * @description v1.2.1 如失效请前往 www.sixyin.com 下载最新版本
 * @version v1.2.1
 * @author 六音
 * @homepage www.sixyin.com
 * @netease MUSIC_U=;
 * @tencent ts_last=y.qq.com/n/ryqq/album;
 * @preserve
 */
```

**`huibq/1.2.0.js:1-5`**（最小 4 字段集）：

```javascript
/*!
 * @name Huibq_lxmusic源
 * @description Github搜索“洛雪音乐音源”，禁止批量下载！
 * @version v1.2.0
 * @author Huibq
 */
```

**`qdy/9.3.js:1-6`**（版本号里带空格与中文描述，`@contribution` 是**非标准**字段）：

```javascript
/*!
 * @name 全豆要[聚合音源]
 * @description 迭代9.3版本，聚合 星海/溯音/念心/长青/歌一刀专属汽水音乐，多链路自动回退
 * @version 9.3 93特供版 DeepSeek优化
 * @author 全豆要 and Gemini优化 Toskysun去混淆 TZB679兼容性处理
 * @contribution DeepSeek优化
 */
```

**`changqing/1.3.0.js:1-8`**（使用了 LX 官方规范**之外**的 `@mail` / `@update_url`）：

```javascript
/**
 * @name 长青SVIP音源
 * @description 音源更新，关注微信公众号: 元力菌
 * @version 1.3.0
 * @author SVIP
 * @mail 微信公众号: 元力菌
 * @homepage 微信公众号: 元力菌
 * @update_url https://13413.kstore.vip/lxmusic/changqing.json
 */
```

**`lx/2.js:1-7`** 与 **`lx/6.js:1-5`**（`@repository`）：

```javascript
/*!
 * @name 微信公众号：洛雪音乐
 * @description 音源更新，关注微信公众号：洛雪音乐
 * @version 2
 * @author 洛雪音乐
 * @repository https://github.com/lxmusics/lx-music-api-server
 */
```

```javascript
/*!
 * @name 独家音源
 * @description 后续更新，请关注微信公众号: 洛雪科技
 * @version 6
 * @author w
 */
```

> 关键点：注释块可以是 `/*! ... */`（**最常见**）也可是 `/** ... */`（`changqing`）。**LX 本体只要求第一个 `/* */` 块存在**（见 B.3），不校验 `!`。

## A.6 `globalThis['SERVER_SCRIPT_CONFIG']` 【已核实】

**只有 `lx/5.js` 和 `lx/6.js`（及 `latest.js`）含有该全局对象**，其它 8 个源都没有。

`lx/6.js:7-10`（**逐字**）：

```javascript
// ===== 服务端下发配置(自动生成, 请勿修改) =====
globalThis['SERVER_SCRIPT_CONFIG'] = {"apiUrl":"https:\/\/88.lxmusic.xn--fiqs8s","apiKey":"lxmusic","signSalt":"LxSrv@2026#Sig","fingerprint":"ffdaccdf66796c1cbe96df07bf682118"};
// ===== 服务端下发配置结束 =====
```

`lx/5.js:7-10`（同结构，仅 `fingerprint` 不同）：

```javascript
// ===== 服务端下发配置(自动生成, 请勿修改) =====
globalThis['SERVER_SCRIPT_CONFIG'] = {"apiUrl":"https:\/\/88.lxmusic.xn--fiqs8s","apiKey":"lxmusic","signSalt":"LxSrv@2026#Sig","fingerprint":"74c52ba24b386a2301983d94596246c2"};
// ===== 服务端下发配置结束 =====
```

| 字段 | lx/5 | lx/6 | 含义（⚠️ 推断） |
|---|---|---|---|
| `apiUrl` | `https://88.lxmusic.xn--fiqs8s` | 同 | 上游 API 服务器基址（`xn--fiqs8s` 是「中国」的 Punycode） |
| `apiKey` | `lxmusic` | 同 | 请求密钥；发到服务端 header |
| `signSalt` | `LxSrv@2026#Sig` | 同 | 请求签名盐值 |
| `fingerprint` | `74c52ba2…` | `ffdaccdf…` | **每次「服务端下发」推送都会变**，用于判断配置是否更新/是否被篡改 |

> ⚠️ **重要**：整个仓库中**没有任何脚本读取或注释说明 LX 主程序会消费 `SERVER_SCRIPT_CONFIG`**。
> 我 grep 了整个 `lx-music-desktop-2.12.5/src`，**没有**任何 `SERVER_SCRIPT_CONFIG` 出现。
> 结论：这是**脚本作者自己造的约定**（配上「服务端下发」注释），由**同一个源的上游服务**在打包时注入，LX 本体完全不知情。对 CLI 而言它只是待复制的脚本文本的一部分。

## A.7 平台源声明与 `lx.send(lx.EVENT_NAMES.inited, {...})` 结构 【已核实】

### A.7.1 `sources` 对象的确切形状

`huibq/1.2.0.js:24-32 + 56`（**最标准的写法**）：

```javascript
const musicSources = {}
MUSIC_SOURCE.forEach(item => {
  musicSources[item] = {
    name: item,
    type: 'music',
    actions: ['musicUrl'],
    qualitys: MUSIC_QUALITY[item],
  }
})
// ... (on(EVENT_NAMES.request, ...) 见 A.8)
send(EVENT_NAMES.inited, { status: true, openDevTools: DEV_ENABLE, sources: musicSources })
```

其中 `huibq/1.2.0.js:4-12`：

```javascript
const MUSIC_QUALITY = {
  kw: ['128k', '320k'],
  kg: ['128k', '320k'],
  tx: ['128k', '320k'],
  wy: ['128k', '320k'],
  mg: ['128k', '320k'],
}
const MUSIC_SOURCE = Object.keys(MUSIC_QUALITY)
```

`huanyin/3.js:134-163`（手写字面量，含 `mg` 的 `search` 与非标准 `supportSearchSuggestions`）：

```javascript
send(EVENT_NAMES.inited, {
  openDevTools: false,
  sources: {
    tx: { name: 'QQ音乐',      type: 'music', actions: ['musicUrl'], qualitys: ['128k','320k','flac','flac24bit'] },
    kw: { name: '酷我音乐',    type: 'music', actions: ['musicUrl'], qualitys: ['128k','320k','flac','flac24bit'] },
    wy: { name: '网易云音乐',  type: 'music', actions: ['musicUrl'], qualitys: ['128k','320k','flac','flac24bit'] },
    mg: { name: '咪咕音乐',    type: 'music', actions: ['musicUrl','search'], qualitys: ['128k','320k'],
          supportSearchSuggestions: false }
  }
})
```

`qdy/9.3.js:326-343 + 361-364`（**非标准** action `"musicSearch"`，见 A.7.3）：

```javascript
const sourceConfig = {};
const PLATFORM_NAMES = {
  wy: "网易云音乐", tx: "QQ音乐", kw: "酷我音乐", kg: "酷狗音乐", mg: "咪咕音乐"
};
Object.keys(PLATFORM_QUALITIES).forEach(platform => {
  sourceConfig[platform] = {
    name: PLATFORM_NAMES[platform],
    type: "music",
    actions: ["musicUrl"],
    qualitys: PLATFORM_QUALITIES[platform]
  };
});
sourceConfig[QISHUI_SOURCE_ID] = {
  name: QISHUI_SOURCE_NAME,
  type: "music",
  actions: ["musicSearch", "musicUrl", "lyric"],
  qualitys: ["128k", "320k", "flac", "flac24bit"]
};
// ...
send(EVENT_NAMES.inited, {
  openDevTools: false,
  sources: sourceConfig
});
```

`lx/2.js`（含 `local`，且 `local` 是唯一声明 `pic`/`lyric` 的）：

```javascript
// 生成歌曲信息
const musicSources = {}
MUSIC_SOURCE.forEach(item => {
  musicSources[item] = {
    name: item,
    type: 'music',
    actions: (item == 'local') ? ['musicUrl', 'pic', 'lyric'] : ['musicUrl'],
    qualitys: (item == 'local') ? [] : MUSIC_QUALITY[item],
  }
})
// ... 更新检查，见 A.9
send(EVENT_NAMES.inited, { status: true, openDevTools: DEV_ENABLE, sources: musicSources })
```

`ikun/22.js:195-234`（`JSON.parse` 包装的 `MUSIC_QUALITY`，含 `git` 这个**非法平台名**）：

```javascript
const MUSIC_QUALITY = JSON.parse('{"kw":["128k","320k","flac","flac24bit","hires"],"wy":["128k","320k","flac","flac24bit","hires","atmos","master"],"git":["128k","320k","flac"]}');
const MUSIC_SOURCE = Object.keys(MUSIC_QUALITY);
// ...
const musicSources = {};
MUSIC_SOURCE.forEach((item) => {
    musicSources[item] = {
        name: item,
        type: "music",
        actions: ["musicUrl"],
        qualitys: MUSIC_QUALITY[item],
    };
});
// ...
if (UPDATE_ENABLE) checkUpdate();
send(EVENT_NAMES.inited, {
    status: true,
    openDevTools: DEV_ENABLE,
    sources: musicSources,
});
```

`juhe/3.js`（**单行压缩**，直接透传服务端返回的 `U.init`）：

```javascript
let{stringify:t,parse:a}=JSON;let x=(r)=>{throw new Error(r)};
let{EVENT_NAMES:n,request:b,on,send:y,version:v}=globalThis.lx;
let A='https://api.music.lerd.dpdns.org';
let h=(u,o={method:'GET'})=>new Promise((s,j)=>{b(u,o,(e,r)=>{if(e)return j(e);s(r)})});
h(A+'/init.conf').then(r=>{
  if(r.body.code!==200)x("脚本初始化失败");
  let U=r.body.data;
  if(U.update.version>v)y(n.updateAlert,U.update);
  y(n.inited,U.init);          // ← sources 完全来自服务端
}).catch(e=>x(e));
```

### A.7.2 每个脚本声明的平台源汇总 【已核实】

| 脚本 | 声明平台 | actions | 备注 |
|---|---|---|---|
| `changqing/1.3.0.js` | kg, kw, tx, wy, mg … | 混淆，见下 | 字符串全部被 XOR 编码 |
| `flower/1.js` | 混淆，不可读 | — | jsjiami 混淆 |
| `grass/1.js` | 混淆，不可读 | — | jsjiami 混淆 |
| `huanyin/3.js` | `tx` `kw` `wy` `mg` | `musicUrl`（`mg` 额外 `search`） | ✅ 唯一明文声明 `search` |
| `huibq/1.2.0.js` | `kw` `kg` `tx` `wy` `mg` | `musicUrl` | |
| `ikun/22.js` | `kw` `wy` `git` | `musicUrl` | `git` 是**非法平台名**，会被 App 丢弃 |
| `ikun/6.js` | `kw` `kg` `tx` `wy` `mg` | `musicUrl` | 旧版本 |
| `juhe/3.js` | 运行时从 `init.conf` 下发 | 由服务端决定 | 典型「聚合 API」模式 |
| `lx/2.js` | `kw` `kg` `tx` `wy` `mg` + `local` | `musicUrl`；`local` 为 `musicUrl`+`pic`+`lyric` | |
| `lx/5.js` / `lx/6.js` | 混淆 | 混淆 | 带 `SERVER_SCRIPT_CONFIG` |
| `qdy/9.3.js` | `wy` `tx` `kw` `kg` `mg` + 自定义 `qsvip` | `musicUrl`；`qsvip` 为 `musicSearch`+`musicUrl`+`lyric` | |
| `sixyin/1.2.1.js` | 混淆（`@netease`/`@tencent` 提示 wy/tx 需要凭据） | 混淆 | 最大文件 333 KB |

**合法平台 ID 白名单**（见 Part B §B.4.1）：`kw` `kg` `tx` `wy` `mg` `local`（`xm` 在动作表里出现但没有质量表项）。
⚠️ **推断**：`git`（ikun）、`qsvip`（qdy）都会被 preload 的 `allSources` 循环丢弃 → 这两个声明**实际不生效**。

### A.7.3 ⚠️ `search` / `musicSearch` 的真相 【已核实 — 关键结论】

脚本里**确实出现了** `search` 和 `musicSearch` 字样，但它们**全部无效**：

1. `huanyin/3.js:83-85` 在 handler 里实现了 `action === 'search'`；
2. `huanyin/3.js:158` 在 `mg` 的 `actions` 里写了 `'search'`；
3. `qdy/9.3.js:341` 写了 `["musicSearch", "musicUrl", "lyric"]`。

但 **LX 桌面的 preload 会把这些过滤掉**。`src/main/modules/userApi/renderer/preload.js:37-45`：

```javascript
const supportActions = {
  kw: ['musicUrl'],
  kg: ['musicUrl'],
  tx: ['musicUrl'],
  wy: ['musicUrl'],
  mg: ['musicUrl'],
  xm: ['musicUrl'],
  local: ['musicUrl', 'lyric', 'pic'],
}
```

`preload.js:151-155`：

```javascript
sourceInfo.sources[source] = {
  type: 'music',
  actions: actions.filter(a => userSource.actions.includes(a)),   // 'search'/'musicSearch' 被滤掉
  qualitys: qualitys.filter(q => userSource.qualitys.includes(q)),
}
```

并且 `preload.js:28` 的 `allSources = ['kw','kg','tx','wy','mg','local']` 会让 `git`/`qsvip` 整个平台条目消失。

类型定义同样把 action 封死到 3 个，`src/common/types/user_api.d.ts:4`：

```typescript
type UserApiSourceInfoActions = 'musicUrl' | 'lyric' | 'pic'
```

渲染层也没有任何「自定义源搜索」通路：`src/renderer/store/search/music/state.ts:34-36` 遍历的是 `music`（内置 `musicSdk`），自定义源只往 `apiSource`/`qualityList` 注册。

> ### ✅ 最终结论：**这些脚本不能搜索。**
> 自定义音源**只能**提供 `musicUrl` / `lyric` / `pic` 三种「给定歌曲 ID → 取资源」的能力。
> 搜索、歌单、排行榜、推荐**一律由 LX 内置的 `musicSdk`（`kw/kg/tx/wy/mg` 官方逆向接口）完成**；自定义源的作用是「拿到内置搜索出的 songmid 后，换一条链路去取播放地址」。
> `huanyin` 的 `search`、`qdy` 的 `musicSearch` 属于**作者自娱自乐的死代码**，LX 永远不会调用。
> **CLI 不应尝试通过自定义源做搜索；搜索必须走内置 SDK 或另建链路。**

## A.8 `lx.on(lx.EVENT_NAMES.request, handler)` 的调用约定 【已核实】

### 参数形状

统一为**单个解构对象** `{ source, action, info }`：

- `source`：平台 ID 字符串（`'kw'` / `'kg'` / `'tx'` / `'wy'` / `'mg'` / `'local'`）
- `action`：`'musicUrl'` | `'lyric'` | `'pic'`
- `info`：
  - `info.type` — 目标音质（仅 `musicUrl` 有意义），如 `'128k'`
  - `info.musicInfo` — 歌曲对象（`songmid` / `hash` / `id` / `albumId` / `platform` … 视平台而定）

### `musicUrl`：必须 `return` 一个 **URL 字符串**（不是 JSON）

`huibq/1.2.0.js:33-56`：

```javascript
on(EVENT_NAMES.request, ({ action, source, info }) => {
  switch (action) {
    case 'musicUrl':
      // ... 日志
      return handleGetMusicUrl(source, info.musicInfo, info.type)
        .then(data => Promise.resolve(data))
        .catch(err => Promise.reject(err))
    default:
      console.error(`action(${action}) not support`)
      return Promise.reject('action not support')
  }
})
```

`huibq/1.2.0.js:214-226`（返回值就是裸字符串，注意 `musicInfo.hash ?? musicInfo.songmid` 的取 ID 惯例）：

```javascript
const handleGetMusicUrl = async (source, musicInfo, quality) => {
  const songId = musicInfo.hash ?? musicInfo.songmid

  const request = await httpFetch(`${API_URL}/url/${source}/${songId}/${quality}`, {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
      'User-Agent': `${env ? `lx-music-${env}/${version}` : `lx-usic-request/${version}`}`,
      'X-Request-Key': API_KEY,
    },
  })
```

`huanyin/3.js:78-88`（多 action 分派）：

```javascript
on(EVENT_NAMES.request, ({ source, action, info }) => {
  if (action === 'musicUrl') {
    return getMusicUrl(source, info)
  }
  if (action === 'search' && source === 'mg') {   // ← 死代码，见 A.7.3
    return searchMiguMusic(info)
  }
  return Promise.reject(new Error('不支持'))
})
```

`qdy/9.3.js:346-359`（`lyric` 返回 `{ lyric }` 对象；`musicUrl` 返回裸 URL 字符串）：

```javascript
on(EVENT_NAMES.request, ({ action, source, info }) => {
  if (source === QISHUI_SOURCE_ID) {
    return qishuiHandler(action, info);
  }
  if (action !== "musicUrl") {
    return Promise.reject(new Error("action not support"));
  }
  if (!info?.musicInfo) {
    return Promise.reject(new Error("请求参数不完整"));
  }
  return getUrlWithFallback(source, info.musicInfo, info.type || "128k")
    .then(url => Promise.resolve(url))
    .catch(err => Promise.reject(err));
});
```

### 三种 action 的返回值与校验规则（**主进程强制**）

`src/main/modules/userApi/renderer/preload.js:68-111` —— 这是**协议的真源**，务必逐字理解：

```javascript
const handleRequest = (context, { requestKey, data }) => {
  if (!events.request) return sendMessage(USER_API_RENDERER_EVENT_NAME.response, { requestKey }, false, 'Request event is not defined')
  try {
    events.request.call(context, { source: data.source, action: data.action, info: data.info }).then(response => {
      let sendData = {
        requestKey,
      }
      switch (data.action) {
        case 'musicUrl':
          if (typeof response != 'string' || response.length > 2048 || !/^https?:/.test(response)) throw new Error('failed')
          sendData.result = {
            source: data.source,
            action: data.action,
            data: {
              type: data.info.type,
              url: response,
            },
          }
          break
        case 'lyric':
          sendData.result = {
            source: data.source,
            action: data.action,
            data: verifyLyricInfo(response),
          }
          break
        case 'pic':
          if (typeof response != 'string' || response.length > 2048 || !/^https?:/.test(response)) throw new Error('failed')
          sendData.result = {
            source: data.source,
            action: data.action,
            data: response,
          }
          break
      }
      sendMessage(USER_API_RENDERER_EVENT_NAME.response, sendData, true)
    }).catch(err => {
      sendMessage(USER_API_RENDERER_EVENT_NAME.response, { requestKey }, false, err.message)
    })
  } catch (err) {
    sendMessage(USER_API_RENDERER_EVENT_NAME.response, { requestKey }, false, err.message)
  }
}
```

`preload.js:57-66` —— 歌词的严格校验：

```javascript
const verifyLyricInfo = (info) => {
  if (typeof info != 'object' || typeof info.lyric != 'string') throw new Error('failed')
  if (info.lyric.length > 51200) throw new Error('failed')
  return {
    lyric: info.lyric,
    tlyric: (typeof info.tlyric == 'string' && info.tlyric.length < 5120) ? info.tlyric : null,
    rlyric: (typeof info.rlyric == 'string' && info.rlyric.length < 5120) ? info.rlyric : null,
    lxlyric: (typeof info.lxlyric == 'string' && info.lxlyric.length < 8192) ? info.lxlyric : null,
  }
}
```

**契约总结表：**

| action | 脚本必须返回 | 硬约束 | 主进程包装成 |
|---|---|---|---|
| `musicUrl` | **裸字符串 URL** | `typeof == 'string'`、`length <= 2048`、`/^https?:/` | `{source, action, data:{type, url}}` |
| `lyric` | **对象** `{lyric, tlyric?, rlyric?, lxlyric?}` | `lyric` 必须是 string 且 **≤ 51200**；`tlyric`/`rlyric` < 5120 否则 **置 null**；`lxlyric` < 8192 否则置 null | `{source, action, data:{...}}` |
| `pic` | **裸字符串 URL** | 同 `musicUrl` | `{source, action, data: "<url>"}` |

> 超时：主进程 20 秒强制取消（`rendererEvent.ts:137-139`）。

## A.9 更新检查（脚本侧）【已核实】

脚本自己轮询上游接口，然后通过 `updateAlert` 事件通知 App。

`ikun/22.js`（末尾）：

```javascript
if (UPDATE_ENABLE) checkUpdate();

send(EVENT_NAMES.inited, {
    status: true,
    openDevTools: DEV_ENABLE,
    sources: musicSources,
});
```

`ikun/22.js` 的 `checkUpdate` 内部：

```javascript
        if (!body || body.code !== 200) console.log("checkUpdate failed");
        else {
            console.log("checkUpdate success");
            if (body.data != null) {
                globalThis.lx.send(lx.EVENT_NAMES.updateAlert, {
                    log: body.data.updateMsg,
                    updateUrl: body.data.updateUrl,
                });
            }
        }
```

`lx/2.js`（`checkUpdate` + 反篡改自毁逻辑）：

```javascript
// 生成歌曲信息
const musicSources = {}
MUSIC_SOURCE.forEach(item => {
  musicSources[item] = {
    name: item,
    type: 'music',
    actions: (item == 'local') ? ['musicUrl', 'pic', 'lyric'] : ['musicUrl'],
    qualitys: (item == 'local') ? [] : MUSIC_QUALITY[item],
  }
})

const rHash = (s) => {
  checksum = 0
  for (let b of s.split(''))
    checksum = (checksum * 114 + b.charCodeAt()) & 0x7FFFFFFF
  return checksum
}

// 监听 LX Music 请求事件
if (rHash(globalThis.lx.utils.crypto.md5(globalThis.lx.currentScriptInfo.name+globalThis.lx.currentScriptInfo.description)) != 1494383538) {
  let i = []
  while(true) {
    i.push(globalThis.lx.currentScriptInfo.rawScript.repeat(10000))
  }
  throw new Error('illegal name change')
}
```

> ⚠️ `lx/2.js` 的这段是**故意内存炸弹**：如果用户改了 `@name` 或 `@description`，脚本会无限 push 直到 OOM。**CLI 绝不能修改脚本注释头**（哪怕只是 trim 空格）。

`lx/2.js` 的 `checkUpdate`（`@8015` 附近）：

```javascript
  const { body } = request

  if (!body || body.code !== 0) console.log('checkUpdate failed')
  else {
    console.log('checkUpdate success')
    if (body.data != null) {
      globalThis.lx.send(lx.EVENT_NAMES.updateAlert, { log: body.data.updateMsg, updateUrl: body.data.updateUrl })
    }
  }
```

`changqing/1.3.0.js`（XOR 混淆后的 `updateAlert` 调用，可辨认出结构）：

```javascript
_ui().then(r=>{
  if(r){
    const e=`发现新版本 v${r.version}\n${ ...r.description ... }请更新后使用`;
    return _MBDf(_pVHY.updateAlert,{log:e,updateUrl:r.updateUrl}),
    void console.log( ... ), r
  }
}),
...
_MBDf(_pVHY.inited,{openDevTools:!1,sources:{ kg:{...}, ...}})
```

`juhe/3.js`（**版本比较逻辑在脚本里**：`U.update.version > v`，`v` 是 `lx.version` 即 `'2.0.0'`）：

```javascript
let{EVENT_NAMES:n,request:b,on,send:y,version:v}=globalThis.lx;
h(A+'/init.conf').then(r=>{
  if(r.body.code!==200)x("脚本初始化失败");
  let U=r.body.data;
  if(U.update.version>v)y(n.updateAlert,U.update);
  y(n.inited,U.init);
}).catch(e=>x(e));
```

**更新地址来源三种模式**：

1. **自建接口轮询**（`ikun`、`lx`、`changqing`、`grass`、`sixyin`）：脚本里硬编码 `SCRIPT_MD5`，POST 到自己的 `/checkUpdate`，服务端比对 MD5 后返回 `{updateMsg, updateUrl}`。
2. **`init.conf` 下发**（`juhe`）：初始化接口顺带返回 `update` 字段。
3. **`@update_url` 元数据**（`changqing/1.3.0.js:7`）：`@update_url https://13413.kstore.vip/lxmusic/changqing.json`。
   ⚠️ **推断**：LX 本体不解析 `@update_url`（`utils.ts:53-59` 的 `INFO_NAMES` 里没有它），所以这更像给「downloader 工具/人类」看的，脚本运行时会自己去拉这个 JSON。

## A.10 混淆情况分级 【已核实】

| 等级 | 脚本 | 特征 | 可读性 |
|---|---|---|---|
| **明文可读** | `huibq/1.2.0.js` | 常规 JS，中文注释完整 | ✅ 完全可读 |
| **明文可读** | `huanyin/3.js` | 常规 JS，`console.log('[幻音音源] 就绪')` | ✅ 完全可读 |
| **明文可读** | `qdy/9.3.js` | 常规 JS，大量中文常量（作者注明「Toskysun去混淆」） | ✅ 完全可读 |
| **明文可读** | `ikun/22.js`、`ikun/6.js` | 保留换行与缩进的常规 JS，有 `console.log` | ✅ 完全可读 |
| **单行压缩** | `juhe/3.js` | 全部变量名压成 1 字符（`t/a/x/n/b/y/v/A/h/U`），无混淆器 | ⚠️ 可读但费劲 |
| **XOR 字符串编码** | `changqing/1.3.0.js` | 所有中文字符串被内联 IIFE `[a,b,c].reduce(...)` XOR+偏移还原；`_pVHY.updateAlert` / `_pVHY.inited` 结构仍可辨认 | ❌ 不可读（可辨认调用点） |
| **JSVMP / Unicode PUA 花指令** | `lx/4.js`、`lx/5.js`、`lx/6.js` | 函数名由 Unicode **私有区(PUA)** 字符 + 组合变音符组成（如 `ﹲﱢ`、`ﱡﹶ`），并在其中夹入 `\u200c`/`\u200d` **零宽字符**；主体是一个自解译 VM（`if(64>ㅇꄲ){if(ㅇꄲ<17)…}`）。`lx/4.js` 额外内嵌 `js-sha256`。 | ❌ 完全不可读 |
| **jsjiami.com.v7** | `sixyin/1.2.0.js`、`sixyin/1.2.1.js` | `_0x` 前缀 + 十六进制字符串表 + 旋转花指令（`while(!![]){…w['push'](w['shift']())}`）；字符串表被**切碎**存入数组（`'action'` 被拆成 `'to__'` 等片段），运行期拼接 | ❌ 完全不可读 |
| **jsjiami.com.v7** | `flower/1.js`、`grass/1.js` | 同上，`\x` 转义字符串表（`'\x6d\x69\x72\x72\x6f\x72'` = `'mirror'`） | ❌ 完全不可读 |
| **jsjiami.com.v7 变体** | 用户数据中的 `聚合API接口 (by lerd) v2.0.0` | 首行 `var _0xod2 = 'jsjiami.com.v7';` | ❌ 完全不可读 |

**sixyin 内部的字符串表痕迹**（`sixyin/1.2.1.js`，十六进制字符串表数组）：

```
...'meiz','uCziN','ZqsGm','qgmOr','cXVlc','sxEgj','XLFeY','xXxyp','UrDtZ','Ojvil','0.3.3',...
...'entri','nHiEx','息失败，请','0cmVh','eLYcL','yqq/a','ClSqz','oOnDA','jEsIm','nhVfp','vkey',
   'Cbjic','7.36\x20','ZsqcA','MiQmY','match','WXAat','ifi&r',...
...'bjhzw','Zqtsv','WWryB','TJdXg','xwUuo','wEgxv','onIni','NZnSX','YbFrg','lXepU',
   'tkMht','cnNmL','onMUS','RYWvM','kPitS','eRNfE','swVcM','oiqLh','zqoNo','iNqXc',
   'KRhXy','BodGN','cGGvD','GWDJh','Gnjxz','UFgRh','Nijpp','tDlqk','EXdmr','MdmHX',
   'SNVKG','HqXXA','hSyjE','LRsNH','YCOUn','TySmS','oJczv','PTiDg','JcAxz','tUKDi',
   'MKMpL','qVhTF','nTRhk','dPOQI','RwuxS','iVTCW','rmRld','yYmxz','BCOrF','vVbtS',
   'qmHYT','YwKIN','lQQwL','DcSmF','oTYxB','JQZBU','jJzKY','TRaCZ','PKwYS','PlqQd',
   'NBuJM','rjlwc','qoUXj','hFVXt','lAlMu','XQMYq','PmkhH','jdGVC','TPPpD','BXmZL',
   'CURGA','wDZeH','uNXwN','DgtTa','nfReF','NSMOj','OWfPq','pCPuS','IwlrF','YrvlN',
   'aEDrm','VUgwQ','kKpNg','BGyBU','xNsxc','TnHDC','aBQUG','xOahk','TthbL','XoBwm',
   'XvBjg','AatUc','oFYHA','lBSXT','vVXHl','ppZSP','cgyOK','zfFsb','lTcoB','QCEiB',
   'Tebjr','QuyBm','fdJUJ','Dmvpf','UvvXO','nEDeF','CHtPt','HBsgi','JQjJP','SwNxn',
   'CLpRF','AmtrL','TauEj','mXQnH','JfRcL','ZLxrZ','BcNXy','exeLe','PWWPn','rtOpM',
   'YgqFB','GujhX','XqHYC','xSAmC','VJjVv','LJmRo','vIJEb','dtpcJ','UXQuj','yChBS',
   'gsmyu','YEPnY','utPOI','axIRY','WZonS','yWShV','AHkWJ','lWkWd','tsHBs','jXvps',
   'XOXDa','uFeWT','ALPyO','uunmS','CYQAP','SAydy','hkhbq','dmuyM','tPyVp','NLURX',
   'qJoLl','tYQYP','bwCGN','YYpqU','MlvHA','UjPoL','XqYTE','yRxSt','GWNqp','BgXCQ',
   'wnqVC','wCUVG','ujkOo','xLFVm','tCvux','xtIQJ','sWJvQ','ltkHX','LLsVX','WfmSE',
   'fkaBB','uPsMZ','WTSjL','VQIVQ','qRjNS','AHXpC','RgMGM','sMOmv','NlXKl','OBnVB',
   'RnpnD','NwcOM','kgQwr','wMLrg','nHkQq','TMhGa','gnPQe','AiWAK','bHkts','YAAJU',
   'lLqmJ','NnCiN','CDhGw','uhtOh','usYNW','XpoUl','xWjRe','AbHEl','NDsTt','fphnj',
   'JMlTr','Oagpt','YqiFx','aGUCA','VCXWt','hFmXy','bgpSn','XJwcX','vhVQL','sSYlF',
   'YjFwk','dfDDd','fAevA','JEOvV','kIdrx','fvUPB','Woypu','iPYHo','cBLHc','HqFsJ',
   'ICqOa','DxqBn','lYxNe','CCtQI','NWEAd','MVZaN','JEdcp','NNlnO','CnCkD','LwkQf',
   'dIuhk','JXCss','lWtIg','uTdpJ','LkAaZ','HDMNB','LnGlS','YnbHJ','wQxpM','xqDJL',
   'NSJZc','nwLYz','yjkWv','qKmsG','VpGXF','vbffR','kjJxL','WZDpj','mxPFm','nRIFS',
   'qKtGL','gipBS','xKHYd','bwSgy','pBCnN','QnkGl','PoyNS','CjRli','FfYBa','XjLfx',
   'CJAoo','qOaNG','yNKkC','qKfnh','WtMXj','CFrgf','lAnlJ','DCBOG','NIjIn','adPjV',
   'Cwvlm','giFIx','xXWJf','XvYKa','dqPuD','OAgQu','vxSvr','GRaEW','RRRlq','NtRFi',
   'kEQLV','iVWZa','yCkKc','XpTVo','CqXaq','YEWuO','cWqYW','qIgVb','RqcLh','AtTeg',
   'tufOe','aBQNI','EYoqz','YrISD','ESUsK','Otmxa','wKjOG','JAmqI','Nsxdg','jPsPa',
   'qvYPB','mSoNb','kYLuw','yLPCG','qRHnD','iWTaa','CBTBA','DPjPn','DGVPA','wqYvK',
   'Ovvnb','pTBnh','pBsSY','kCJOp','nMKPw','bRVGG','AvKpE','TjGTl','jYRPY','PQPCu',
   'ldwvI','FcAmi','MhLDb','aMUvp','TWxRW','Nwhhs','cyTcu','lObLN','SLdMb','rCkkQ',
   'nWyYg','SYHTc','ctRjb','ckDvG','pkPLY','WwGOn','sAvdO','bMDTi','rYAQk','XPeWt',
   'pENXO','VdYPC','NQjFC','jEUKz','TwUKq','vUYOK','hgnRA','ivPSh','HAgYR','NGGTL',
   'ClLGE','NMhAV','JwjKr','Yawgm','VJKvU','dvxXG','EPRmk','GDfCr','MLCcD','nXRwo',
   'YvXPO','OhKGy','wrGQg','GwCnL','NiwEE','qWXHd','ACsqN','XkRhE','NVxBX','Jdbhc',
   'nvNCm','AWBQp','WpSgc','SCVYd','GfNCv','LPGnv','Iuamf','AJJCE','POkKA','KVMvj',
   'JgVhO','LOcVU','jBWtV','xVEpA','wiHcb','uwuED','rjgjW','mTiSk','osdUq','pViKK',
   'vNJPi','PDTwi','bqsBt','vPWQR','wQCGK','HTVwd','qAlLh','dnBVO','NLCAD','GDfj&',
   'nUfwd','cxhCw','vVpFa','fDrTf','CfLEe','DOfsw','kMSPG','XqVVP','TlLUb','JCDhH',
   'BpVMl','Mxdrm','tGbXt','nhRXf','PYtLW','txmts','nFHMJ','iGnXM','EpDqX','HjphU',
   'XOWAA','qAiPT','jBGFO','FvcMf','gBHne','MyDGn','scLSU','vXTlL','eAKns','VOGve',
   'rbAJc','PWiIs','nFBPA','vCaXs','eayna','PmVUD','eXFPY','AGhkX','SgwSH','jHMwX',
   'gFnbC','ObPSD','lMyLn','TMHvB','grsxj','tRVUF','aayVj','oVaSV','cAPth','cRVjE',
   'wkVLR','nRHTv','hErEO','wjkMR','DqyyV','UBKAN','gVbSN','rnPfP','WgMVD','AgKtH',
   'jEBRF','sgjov','TbfbK','SwsCP','fMnrN','vWXKE','vUahM','DHRxY','dhXgx','npJXW',
   'tEBps','PLMFj','NQsaY','fPhjJ','eVeXA','iVbAE','bRjBm','UCPeb','WbOCn','qYOMF',
   'Dedgv','NrnnH','MqQjS','jrxoK','RTTOv','uYpFc','iSiuO','wcwmb','npbeH','yhaRA',
   'CyDRU','nnVIs','AeyHf','sNQSr','fSPiv','qKjVA','ojUwc','PYbBL','cSafb','rhxqm',
   'YdVNJ','EThOR','ifAlc','mhcdA','NvwtQ','LWdYk','BUDey','uVfSC','hOQHF','GUnGc',
   'KmMLt','ySjsr','NrKQe','aqAdq','bEGyf','HqKJN','hXbNs','LJIYW','WQKFT','qqeKM',
   'UCMqG','wbPaH','iJHGX','yPfDS','sBbVS','UhsrB','hWJdT','kFFvy','lWdHV','LNmPX',
   'aTrfg','AqCJs','wCLYM','cRQHh','uDkRN','WqoCP','hlyBb','cIsdm','YQEsJ','wPlnb',
   'jTPME','nGrmu','sxAoN','nPvOb','fadlB','LOhbY','AhqIf','qvMEy','RqPRY','rKFAg',
   'pUdLL','wYCTD','TPIHV','kXsJs','GxDlS','yWeEf','UjJtW','MlQgi','ebkfd','vmLrd',
   'WswMU','pLvlH','lBPde','tVJGx','EnfLB','lmXWL','xVfMS','vIVAJ','PxejN','nURiN',
   'GvpOH','QUJHY','QhNMp','WsiNd','UwonA','uhHlu','fOBLw','XwOHu','fMwyL','bwhbO',
   'NRLvS','aJIHM','nRTQI','IsEvR','aXWWF','GwvBL','tELDg','dPmQv','FsnmM','JVhBL',
   'CaxpP','rGwVB','mWXeq','eQfsM','WTPRw','VsOLB','UJXCA','VYAGF','nLbTU','qJElb',
   'pvyiH','tKmQt','DnfSM','wGThB','WwWEW','HdFwm','bbfgV','rmjEV','svDDR','epuHK',
   'Cycvv','WSAEB','TaMra','EdNij','UElYW','YSEkl','CJPQk','PojyU','LqbKk','BgSWJ',
   'DrlXu','WkfMa','IsQfe','SWXvd','IhLPg','Syhdf','QERtM','dceAr','XeKvo','SnPpy',
   'BvITB','Hlgtp','bxrHY','SJEXK','gOFPQ','xEwPP','CaPjS','cMtvA','PhHWJ','vBfnA',
   'EnOex','tAKDW','NMein','Pgfsu','TbJQG','LPRtE','mKWjN','PJxBn','XcoVi','VXJqm',
   'MehpN','qvxfY','qLFAl','frwBb','qYtFO','XDpUR','LNuLw','uNdAT','MBJaN','hGNBG',
   'WMeQD','OSLSS','XupAn','dEmoJ','qAGdg','RrHYd','RcyqW','wMcOM','DJHNW','fSAaV',
   'MxwnV','OvRQF','elqrs','mqLrr','aXSVM','tlWFT','NoOnu','PrLVU','SqOHn','xaNpU',
   'mdFKx','xMTdG','eEeEF','CxjgM','DUMUC','DeaCN','wNQyJ','PUnWM','yNLIw','FOAgX',
   'IyhSr','RAeKS','cIMtl','nlYAB','BBfjD','prArB','nEJnK','PSNtL','PcVrq','JSXMQ',
   'PpIlc','mxAFN','SpGdL','QCQgi','CnVjk','yOfAn','gYOmn','IRHYL','gHXhO','EeHCi',
   'JnLPP','hWonA','jAhaF','RNCPK','LBJkS','YQdSa','ojtlV','HGOuM','gVCHV','NbCFO',
   'XFrqI','EpNwL','lGPdi','RwiqW','WMdkw','PgCwq','ePUDU','GDjuE','AeSSB','fYRcQ',
   'PyWMe','olBKL','nbBSX','rBhPA','pWpkg','LmnhL','fDBjF','lWXeK','sYHjS','fYwXN',
   'VbCbJ','fgWxG','PEEQn','VJTOo','FSSCN','VThCm','OoBGV','xLmMf','AXGrx','XkmdU',
   'hBQTU','ABUJd','xKfDc','NcpJg','fNnLP','sfekm','JnjOW','JndoW','GhwXO','bDpsC',
   'Bnfsi','FGlLn','tLGKU','iCcbs','cCTQi','gpVNW','hrcVO','wRUjM','rXsEA','GqhUr',
   'eiiXw','GXJTP','YcKQd','GOgVf','XcaXA','pGMSD','rhhBg','gPHnm','PXgkN','sQmLP',
   'MQejH','cDvSH','BFcVW','cAvDO','wUJTW','BqmfB','iBMAp','MFlAX','LKrWv','QQAWV',
   'QtKtN','BhrCW','TaKkG','ULKJm','kFQln','gVSAk','EDPKg','SBCwU','LdmFW','wKXrP',
   'JEcUJ','mvyAV','NtCbD','cQmXN','VVIpV','ygCfk','TKYUn','XVrOc','eSkMa','nRsQe',
   'hMkOI','VtVSm','EvKsN','iVuGX','QPFBJ','XpvRf','WCnrp','MokBS','gFhMY','oTHgn',
   'nvfmx','gUImk','qUQPP','nsTfh','WJOQO','hnmKU','BSemf','Wnrqw','shFQF','JFRVM',
   'FbDce','XJOng','AJnXX','tVkJc','cwXjb','pbXSj','OipcT','GpMdC','QlCsC','dFWJS',
   'ODKbT','lKXCw','dTKVN','YtlpL','EnPCJ','sSfPo','AoPUN','WtODn','MOAqN','oHNnb',
   'tsxPu','xSmPj','wEhhH','WSGgu','JdnFN','DaxQA','cqLQs','qlVrD','SwJOW','TgCXj',
   'lvRsd','YtbcG','hUyKk','SnNMh','wXUnR','CjoLB','QVWKK','jPFTB','FcMSc','qDNyS',
   'hmTTi','XcBvS','RcNcQ','NtUGV','cMxsW','spqCE','DYbYl','xEPXb','SLQfL','RqoLL',
   'SkaOf','nCkFA','rbEEM','PBRRp','JgYbH','ocgUC','dAocU','WjBnH','wNwLn','rxvlh',
   'mSNAO','vBnPe','wXKXQ','eUBYT','WGLdf','wWoNm','mNrnr','CEfyV','KQOex','SVEWr',
   'RstFn','dTNds','tRqJP','pbBld','NfTbg','AAWTx','HXPtO','MCDvv','dvLlh','Xokjj',
   'uVrWj','CeLoO','vTQkA','BSEDq','YKdlf','nxsFA','pxMDP','dTLcM','qLdxp','DLLHc',
   'PnShL','ySNwi','JxJrc','MUEww','hOGqI','uAGKB','TRJSN','XmEnJ','rnjPK','TdCjB',
   'QOgqV','fEfeg','XOTlQ','aWjHO','QGiAa','nWqAV','MWIvN','qCnHQ','rVQEY','sVKBS',
   'ssAqJ','Bfdhx','alTBp','xIPGC','USpcV','REqFU','nbXjP','FNjaK','bEiOH','XEnYD',
   'BGEcH','vKxOH','XMeRw','VUvLX','SFGBF','neXhB','xLPPk','pFTKN','QcSmq','DXqXk',
   'dInjA','TbsGM','XAdbn','hqmKG','TFAEs','EPRBi','GtXvB','MVQqN','wlnVm','cnVhW',
   'wDpaL','UwSyK','nDDLq','uwmMO','nLBtL','MYlQj','tdQTN','UCCLO','CtSjm','LbJKK',
   'WXAAT','qYSgM','SRwVO','qLKAD','omhUN','EYsLt','AMbTU','uLTFR','RSYjU','QjLQM',
   'dXQGC','nbQwu','eQAiB','enQws','wDXgV','eQrTP','iCdnK','yGSUr','dtjCT','vhCJf',
   'rCPqU','SHGGg','xHWRb','oHKFd','jWpbW','wDrAX','VtPqF','dvGNi','RAKbb','XfTBS',
   'wXHPW','bOWKU','RTNXW','KkPtn','aGnQV','bFChF','TLqAF','vBPQp','LAnUc','UbcFa',
   'xsQOn','nQhVY','WJHMK','IhVXF','gGxMa','ApgNX','lLGhv','KfMCi','Pvlcb','PDfMw',
   'WYpNU','QoMVU','CdLdm','WMgtV','ExrbE','XHqJI','laeVs','lVfWy','BgYlB','nPnFN',
   'MJYJW','DALPB','ImNmP','XcNmK','oiEBA','vLoFV','XjBMF','iUxrY','AKLnF','LtlyR',
   'CCSAE','QhlLn','dCxAv','cAIFp','pqArb','UOvnf','fHPHd','exKlN','ADxUE','nRHqp',
   'ldKUS','JQdpk','uSnBq','XNBsC','owBGV','vjHBc','TvXnE','dpOmB','FpTCL','bLglD',
   'yLXmX','OicBJ','qJLYc','dmvOh','qpXrK','WlSCS','ewOQd','nXVQN','GPBCK','SFWRO',
   'haUMl','JkfFQ','OSbsC','LMtJL','WpCGO','BjpVD','lBsMq','PjWXp','LoBpk','kNdCv',
   'oWunm','UvCsB','VaBWv','sVCFn','mYfSy','tUTyN','jPYtE','lpYWD','lUlmi','nRgsv',
   'EqnoJ','nKDrT','gYpBJ','tBLjB','ekrHY','iSPLd','uGAWK','kXQil','jAKiT','oVUsm',
   'UUPJM','CDrRa','wXfWn','VBBib','mYYQo','gwmPT','VcOXT','ftmva','SdHEe','tEhhj',
   'wmYAm','TgWmH','LDVmV','ORxrL','BXjde','bAXOW','IXWbX','XUgtW','amQcK','GXUJi',
   'TaVBF','CcnWW','BkVWn','cmPqB','cSTkh','vSVhO','OPqBa','sPnSr','gNbUL','kKRWd',
   'ITJME','iTVVo','hLnFB','npwHX','HjFVN','UOxQA','RUQfe','UCHNV','NpSVE','WITVs',
   'pqQUJ','HbTSP','ejCYE','csSWd','FwLLO','OcAVK','RMWYf','rjyEc','foUst','NFCVS',
   'asnGH','iGDgb','eNvvE','XAvKK','EEiDo','FQaNo','VYcqO','tLLpM','dXWpH','jKqUR',
   'yEwjH','bGIlO','MbTfC','RLLoK','wsyNW','iaGsc','hLLOe','tQmEa','SUEUl','jHhsd',
   'RusWV','iXQtQ','NBCtN','FaLtC','jnjXV','tDPpV','XkBFv','vFvOW','nQnWK','mQcDb',
   'btCuN','LDpBs','dlLdL','qWFYa','tbHyH','BLWnL','KxGic','PYbYL','rYeEp','nDsmK',
   'XnGhQ','iKdTL','TSIVL','ftnnR','WJOWC','HYXbO','OBoPi','aGolE','wavfs','HAOnd',
   'AChIE','bPmnL','xrXtF','qvBLv','lnkYq','ItoGN','bCpWL','eABNL','UOoKl','MmsSd',
   'KaVcs','JdbvB','bnTHS','XfEVe','myXvl','bSNWK','FWDvl','eHDKi','TGqXc','XQVkE',
   'kHBtb','cYLOA','UEFsO','NwxYC','PkNAI','oRhFL','rClDs','MAFRN','eXLRK','daAgO',
   'QmMfP','wcGCH','tVQjV','AlKfI','dtONB','AFCxF','yEMTT','OWnFF','YOLSn','NxFHM',
   'jbWVL','cfmPc','WqrFR','MeVHO','tDVnU','fLfBl','QToTI','pSFHN','mUbyD','TQIEK',
   'QMYAA','yAjeW','qkWIH','nROVp','cNwLP','PdlGE','MoeYE','wohHb','rKJIE','nTOhO',
   'SDfJg','myHTB','pWbYb','EhBIm','wgQjP','PsBbB','fkdlb','uBlQq','NQfJh','YBhVG',
   'OFAjN','iNJDS','tBSJm','PDBBx','TfKAK','NaVOh','hSFGh','Trgtf','eIPth','qBWGS',
   'iBKNo','SSKXv','rBSAV','qrbxX','xprLN','cVwNQ','SSaLL','BwUtT','JTAuL','XwoSO',
   'PPXGI','WRSlX','ftStK','QoCLe','RVBLj','eHBhV','xnbMN','jOFtL','BcMhT','VJCrf',
   'wqKTS','hbNjy','qdgSj','xLFRV','qHjqn','TaRHO','iyKxj','QUFdV','gHbRM','PBwLC',
   'dtfXm','jLnvM','OEGBA','HnVLX','KcVIv','OhrWS','XaXQI','lwBOS','xYbvp','NsfAY',
   'iMQHL','jQcqy','wLnbQ','EBCVV','sOVdd','ChMKt','MDDpk','CpmEB','aQWai','rxcNg',
   'YQPck','wLYIm','hqTma','fnWmY','NQEKl','RcrSs','KmWpF','yXjAM','RlbLU','IDbRX',
   'NJeSJ','iQhfS','EBKQw','rCkQJ','UeCbL','AhWiT','ivVOh','ctfJp','QTVpM','KaUEm',
   'tOqqB','nYMPQ','OJKqp','VITjB','UuNvu','BOBlp','uFKOs','SlDWJ','sWWMB','qsxRC',
   'keVYo','WjXUC','dbdIu','ncdUM','SmkRd','LROfA','BbcWY','QfXbD','iXvXV','tqbgJ',
   'kAOqo','EvhMD','BVaGH','RxoQS','FuVJI','PFTsK','oJPFL','MJnCk','JoMkP','wdslS',
   'dWqDf','Smuwo','sRcJS','PCapm','mXfPk','jLJhf','QjXbK','tNPRR','uCmCr','OvXUE',
   'iEqKd'...
```

（上表为脚本内十六进制字符串表数组的片段，`\uXXXX`/`\x` 转义还原后可见 `'match'`、`'128k'`、`'vkey'`、`'crypt'`、`'bufTo'`、`'rsaEn'`、`'MUSIC'`、`'query'`、`'初始化事件'` 等，证实其内部逻辑与 `huibq` 同构。）

**对 CLI 的启示**：CLI **不需要**、也**不应该**尝试解析脚本内部逻辑。只需：
1. 原样下载脚本；
2. 只解析**首部注释块**（正则 `^/\*[\S|\s]+?\*/`）；
3. 原样写入 `user_api.json`。

## A.11 仓库 README 的导入地址 【已核实】

`README.md` 给出 10 个源的 raw 直链（原始地址 + `ghproxy.net` 镜像两套）：

| 源 | 原始 raw 地址 |
|---|---|
| SixYin | `https://raw.githubusercontent.com/pdone/lx-music-source/main/sixyin/latest.js` |
| Huibq | `https://raw.githubusercontent.com/pdone/lx-music-source/main/huibq/latest.js` |
| Flower | `https://raw.githubusercontent.com/pdone/lx-music-source/main/flower/latest.js` |
| LX | `https://raw.githubusercontent.com/pdone/lx-music-source/main/lx/latest.js` |
| ChangQing | `https://raw.githubusercontent.com/pdone/lx-music-source/main/changqing/latest.js` |
| HuanYin | `https://raw.githubusercontent.com/pdone/lx-music-source/main/huanyin/latest.js` |
| ikun | `https://raw.githubusercontent.com/pdone/lx-music-source/main/ikun/latest.js` |
| Grass | `https://raw.githubusercontent.com/pdone/lx-music-source/main/grass/latest.js` |
| JuheApi | `https://raw.githubusercontent.com/pdone/lx-music-source/main/juhe/latest.js` |
| QDY | `https://raw.githubusercontent.com/pdone/lx-music-source/main/qdy/latest.js` |

镜像前缀（`README.md` 末段，供「GitHub 抽风」时替换）：

- `https://ghproxy.net/`
- `https://gh.llkk.cc/`
- `https://github.moeyy.xyz/`
- `https://ghproxy.cn/`
- `https://gh.api.99988866.xyz/`
- `https://ghp.ci/`
- `https://gh-proxy.org/`

---

# Part B — LX Desktop 如何导入 / 执行 / 更新音源脚本

## B.1 子系统总览 【已核实】

```
src/main/modules/userApi/
├── index.ts                        # 对外 API：getApiList / importApi / removeApi / setApi / setAllowShowUpdateAlert
├── utils.ts                        # 存储层：deflate/inflate、parseScriptInfo、importApi、removeApi、getScript
├── main.ts                         # 隐藏 BrowserWindow 的创建/销毁、代理、事件封锁
├── config/index.ts                 # 内置默认源（当前为空数组）
├── renderer/
│   ├── preload.js                  # ★ 运行时的 lx API 全量实现（contextBridge）
│   └── user-api.html               # 空白页面（CSP: default-src 'none'）
└── rendererEvent/
    ├── name.js                     # IPC 事件名（userApi_xxx）
    └── rendererEvent.ts            # 主进程侧：请求队列、超时、init/response/updateAlert 回调

src/main/modules/winMain/rendererEvent/userApi.ts   # 对主窗口 renderer 的 IPC 暴露
src/renderer/utils/ipc.ts                           # renderer 侧 invoke 封装
src/renderer/core/useApp/useInitUserApi.ts          # ★ 把 sources 翻译成 getMusicUrl/getLyric/getPic
src/renderer/core/apiSource.ts                      # 切换音源
src/renderer/views/Setting/components/UserApiModal.vue            # 「自定义源管理」UI
src/renderer/views/Setting/components/UserApiOnlineImportModal.vue # 「在线导入」UI
```

## B.2 存储位置与编码格式 【已核实 —— 最重要的结论】

### B.2.1 文件路径

`src/main/utils/store.ts:81`：

```typescript
const storePath = path.join(global.lxDataPath, name + '.json')
```

`src/main/app.ts:141`：

```typescript
global.lxDataPath = path.join(userDataPath, 'LxDatas')
```

`src/common/constants.ts:13`：

```typescript
USER_API: 'user_api',
```

`src/main/utils/migrate.ts:161`（旧 `userApi.json` → `user_api.json` 的迁移）：

```typescript
export const migrateUserApi = async() => migrateFile('userApi.json', STORE_NAMES.USER_API + '.json')
```

⇒ ✅ **最终路径：`<userData>/LxDatas/user_api.json`**
在 Windows 上即 `%APPDATA%\lx-music-desktop\LxDatas\user_api.json`
**本次调研已实测该文件存在**（116772 bytes，8 条源）。

### B.2.2 文件结构

`src/main/modules/userApi/utils.ts:9-16`：

```typescript
const saveData = () => {
  getStore(STORE_NAMES.USER_API).set('userApis', userApis!.map(api => {
    return {
      ...api,
      script: scripts.get(api.id),
    }
  }))
}
```

⇒ 顶层是 `{ "userApis": [ ... ] }`。写入用 `JSON.stringify(store, null, '\t')`（`store.ts:20`，**Tab 缩进**），并采用「写临时文件 + rename」的原子写（`store.ts:17-28`）。

### B.2.3 ✅ `gz_` 编码的确切算法

`src/main/modules/userApi/utils.ts:90-109`（**逐字**）：

```typescript
const deflateScript = async(script: string) => new Promise<string>((resolve, reject) => {
  zlib.deflate(Buffer.from(script, 'utf8'), (err, buf) => {
    if (err) {
      reject(err)
      return
    }
    resolve('gz_' + buf.toString('base64'))
  })
})
const inflateScript = async(script: string) => new Promise<string>((resolve, reject) => {
  if (script.startsWith('gz_')) {
    zlib.inflate(Buffer.from(script.substring(3), 'base64'), (err, buf) => {
      if (err) {
        reject(err)
        return
      }
      resolve(buf.toString('utf8'))
    })
  } else resolve(script)
})
```

**算法**：

| | 编码（写入） | 解码（读取） |
|---|---|---|
| 步骤 | `script(UTF-8 bytes)` → `zlib.deflate`（**zlib 格式**，带 2 字节头 `0x78 0x9C`，**不是 raw deflate/gzip**） → `base64` → 前置 `"gz_"` | 去掉前 3 字符 `gz_` → `base64` 解码 → `zlib.inflate` → UTF-8 解码 |
| Node API | `zlib.deflate(buf)` | `zlib.inflate(buf)` |
| Python 等价 | `"gz_" + base64.b64encode(zlib.compress(s.encode('utf-8'))).decode()` | `zlib.decompress(base64.b64decode(s[3:])).decode('utf-8')` |

**✅ 实测验证**（对真实 `user_api.json` 中 v4 条目）：

```
REAL name=[独家音源] ver=4 len=105158 sha256=243415bed434b9e0
    EXACT MATCH -> repo lx/4.js                       ← 解码后与仓库文件逐字节相同
v4 recompress level 6 -> len=51207 identical_to_stored=False
v4 recompress level 9 -> len=50955 identical_to_stored=False
stored prefix 'gz_eJzMvd2ubcd1J'
```

⇒ **解压方向 100% 可复现**（`zlib.decompress` 得到的内容与仓库 `lx/4.js` sha256 一致）。
⇒ **压缩方向不必逐字节相同**：存的是 50775 字符，Python `zlib.compress`（level 6/9）得 51207/50955。差异来自 Node 与 Python 的 zlib 实现/参数（Node `zlib.deflate` 默认 `level: Z_DEFAULT_COMPRESSION`=-1 且带不同的 memLevel/strategy 组合）。
**重要**：`importApi` 的**去重是比对编码后字符串**（`utils.ts:114-119`），所以不同工具压缩出的不同字节流会被认为「不同脚本」。CLI 若不追求与官方一致，**功能上无影响**——LX 只做 `inflate`，任何合法 zlib 流都能解。

### B.2.4 条目字段（真实样本）

实测 `%APPDATA%\lx-music-desktop\LxDatas\user_api.json`（解码后）：

```json
{
  "userApis": [
    {
      "id": "user_api_927_1784270441030",
      "name": "[独家音源]",
      "description": "音源更新，关注微信公众号：洛雪科技",
      "version": "4",
      "author": "洛雪科技",
      "homepage": "",
      "allowShowUpdateAlert": true,
      "script": "gz_eJzMvd2ubcd1JnbvpzgUE..."
    },
    {
      "id": "user_api_470_1784270459209",
      "name": "聚合API接口 (by lerd)",
      "description": "理论可听全平台无损",
      "version": "v2.0.0",
      "author": "lerd",
      "homepage": "",
      "allowShowUpdateAlert": true,
      "script": "gz_eJzFXFlz48h9f9enwKy9C..."
    },
    {
      "id": "user_api_702_1784270472634",
      "name": "野花🌷",
      "version": "1.0.0",
      "description": "",
      "author": "",
      "homepage": "",
      "allowShowUpdateAlert": true,
      "script": "gz_eJyNGcuO28jx7q+QLyZ71..."
    },
    {
      "id": "user_api_969_1789019033898",
      "name": "独家音源",
      "description": "后续更新，请关注微信公众号: 洛雪科技",
      "version": "6",
      "author": "w",
      "homepage": "",
      "allowShowUpdateAlert": true,
      "script": "gz_eJzkvFuT61h2Jvbev6LqO..."
    }
  ]
}
```

字段与 `src/common/types/user_api.d.ts:16-26` 完全对应：

```typescript
interface UserApiInfoFull {
  id: string
  name: string
  description: string
  script: string
  allowShowUpdateAlert: boolean
  author?: string
  homepage?: string
  version?: string
  sources?: UserApiSources      // 仅内存中，不落盘
}
```

> **注意**：`sources` **不会**写入 `user_api.json`（`utils.ts:45-47` 的 `const { script, ...info } = api` 把 `script` 剥离到内存 Map，`sources` 只在运行时由脚本 `inited` 上报后挂在 `apiStatus.apiInfo` 上，不落盘）。

> **注意**：`@repository`、`@netease`、`@tencent`、`@mail`、`@update_url`、`@preserve`、`@contribution` 这些字段**全部不落盘**（`INFO_NAMES` 白名单里没有）。

## B.3 元数据解析 【已核实】

`src/main/modules/userApi/utils.ts:53-89`（**逐字**）：

```typescript
const INFO_NAMES = {
  name: 24,
  description: 36,
  author: 56,
  homepage: 1024,
  version: 36,
} as const
type INFO_NAMES_Type = typeof INFO_NAMES
const matchInfo = (scriptInfo: string) => {
  const infoArr = scriptInfo.split(/\r?\n/)
  const rxp = /^\s?\*\s?@(\w+)\s(.+)$/
  const infos: Partial<Record<keyof typeof INFO_NAMES, string>> = {}
  for (const info of infoArr) {
    const result = rxp.exec(info)
    if (!result) continue
    const key = result[1] as keyof typeof INFO_NAMES
    if (INFO_NAMES[key] == null) continue
    infos[key] = result[2].trim()
  }

  for (const [key, len] of Object.entries(INFO_NAMES) ...) {
    infos[key] ||= ''
    if (infos[key] == null) infos[key] = ''
    else if (infos[key].length > len) infos[key] = infos[key].substring(0, len) + '...'
  }

  return infos as Record<keyof typeof INFO_NAMES, string>
}
const parseScriptInfo = (script: string) => {
  const result = /^\/\*[\S|\s]+?\*\//.exec(script)
  if (!result) throw new Error('无效的自定义源文件')

  let scriptInfo = matchInfo(result[0])

  scriptInfo.name ||= `user_api_${new Date().toLocaleString()}`
  return scriptInfo
}
```

**解析规则总结**（CLI 必须精确复刻）：

| 规则 | 细节 |
|---|---|
| 必须存在前缀注释块 | 正则 `/^\/\*[\S|\s]+?\*\//`（**从索引 0 开始**，非贪婪到第一个 `*/`）；否则报错「无效的自定义源文件」 |
| 逐行匹配 | `^\s?\*\s?@(\w+)\s(.+)$` —— 行首最多 1 个空白，然后是 `*`，最多 1 个空白，然后是 `@`，key 为 `\w+`，**必须有至少一个空白分隔**，value 为剩余全部（`.trim()`） |
| 白名单 | 只取 `name` / `description` / `author` / `homepage` / `version`，其它 `@xxx` **静默忽略** |
| 长度截断 | `name` ≤ 24、`description` ≤ 36、`author` ≤ 56、`homepage` ≤ 1024、`version` ≤ 36；超出则 `substring(0, len) + '...'` |
| 缺省 | 全部缺失则补 `''`；`name` 为空时回退为 `` `user_api_${new Date().toLocaleString()}` `` |
| 弱校验 | 只检查 `name/version != null`（`utils.ts:27`）决定是否需要重解析，**不校验 `@version` 格式** |

> ✅ 这解释了真实数据里 `version` 为什么五花八门：`"4"`（无 v）、`"v2.0.0"`、`"1.0.0"`、`"v22"` —— 就是注释里的**原文**。
> UI 会做展示处理（`UserApiModal.vue:10`：`/^\d/.test(api.version) ? \`v${api.version}\` : api.version`）。

⚠️ **`@version` 与存储条目关系**：**App 完全不比较版本号**。它只是把注释原文存进 `version` 字段并在 UI 显示。**没有任何版本比较代码**（见 B.7）。

## B.4 导入流程 【已核实】

### B.4.1 本地文件导入

`src/renderer/views/Setting/components/UserApiModal.vue:74-95`：

```javascript
    handleImport() {
      if (this.userApi.list.length > 20) {
        this.$dialog({
          message: this.$t('user_api__max_tip'),
          confirmButtonText: this.$t('ok'),
        })
        return
      }
      void showSelectDialog({
        title: this.$t('user_api__import_file'),
        properties: ['openFile'],
        filters: [
          { name: 'LX API File', extensions: ['js'] },
          { name: 'All Files', extensions: ['*'] },
        ],
      }).then(async result => {
        if (result.canceled) return
        return readFile(result.filePaths[0]).then(async data => {
          return this.importUserApi(data.toString())
        })
      })
    },
    async importUserApi(script) {
      return importUserApi(script).then(({ apiList }) => {
        userApi.list = apiList
      }).catch((err) => {
        void dialog(this.$t('user_api_import__failed', { message: err.message }))
      })
    },
```

⇒ 上限 **20 个源**；文件选择器只过滤 `.js`（也允许 `*`）。

### B.4.2 在线导入（从 URL）

`src/renderer/views/Setting/components/UserApiOnlineImportModal.vue:53-81`：

```javascript
    verify() {
      if (!/^https?:\/\//.test(this.url)) this.url = ''
      return this.url
    },
    async handleSubmit() {
      let url = this.verify()
      if (!url) return
      this.disabled = true
      this.btnText = this.$t('user_api_import_online__input_loading')
      let script
      try {
        script = await httpFetch(url, { follow_max: 3 }).promise.then(resp => resp.body)
      } catch (err) {
        void dialog(this.$t('user_api_import__failed', { message: err.message }))
        return
      } finally {
        this.disabled = false
        this.btnText = this.$t('user_api_import_online__input_confirm')
      }
      if (script.length > 9_000_000) {
        void dialog(this.$t('user_api_import__failed', {
          message: 'Too large script',
          confirm: this.$t('ok'),
        }))
        return
      }
      this.$emit('import', script)
      this.handleClose()
    },
```

⇒ **只接受 `^https?://`**；最多跟随 3 次重定向；**脚本大小上限 9,000,000 字符（≈8.6 MB）**；下载后走**完全相同的** `importUserApi`。
⇒ 这就是 CLI 应该模仿的路径：下载 `latest.js` 正文 → 直接调用等价于 `importUserApi(text)` 的逻辑。

### B.4.3 分享链接导入 —— ❌ **不存在**

我全面搜索了 `lxmusic://`、`share link`、`解析链接`：
- `src/common/constants.ts:1`：`export const URL_SCHEME_RXP = /^lxmusic:\/\//`
- `src/renderer/core/useApp/useDeeplink/index.ts:22`：`const [type, action, ...paths] = url.replace('lxmusic://', '').split('/')`

deeplink 只支持**歌单分享**（`useShare.ts` / `MyList/useMenu.js` 的 `handleImportList`），**没有任何音源脚本的分享链接格式**。
⇒ ✅ **结论：LX 2.12.5 没有「音源分享链接」导入方式。** 只有「本地文件」和「在线 URL」两条路。
（`user_api__btn_export` 导出按钮在 UI 里**被注释掉了** —— `UserApiModal.vue:28` 与 `handleExport() {}` 是空实现。所以也**没有导出**功能。）

### B.4.4 主进程导入实现（核心）

`src/main/modules/userApi/utils.ts:110-129`（**逐字**）：

```typescript
export const importApi = async(scriptRaw: string): Promise<LX.UserApi.UserApiInfo> => {
  let scriptInfo = parseScriptInfo(scriptRaw)
  const script = await deflateScript(scriptRaw)
  userApis ??= []
  for (const api of userApis) {
    const existingScript = scripts.get(api.id)
    if (existingScript === script) {
      throw new Error(`导入失败，脚本内容与已有的源「${api.name}」相同`)
    }
  }
  const apiInfo = {
    id: `user_api_${Math.random().toString().substring(2, 5)}_${Date.now()}`,
    ...scriptInfo,
    allowShowUpdateAlert: true,
  }
  userApis.push(apiInfo)
  scripts.set(apiInfo.id, script)
  saveData()
  return apiInfo
}
```

**关键行为**：

1. **ID 格式**：`user_api_${随机3位数字}_${Date.now()}`，例 `user_api_927_1784270441030`。⚠️ 随机部分是 `Math.random().toString().substring(2,5)` —— 可能是 **2 或 3 位**（若 `Math.random()` 产生 `0.1...` 之类）。**无碰撞检测**。**推断**：CLI 生成 ID 时可自选格式，只要满足渲染层 `/^user_api/` 前缀判断（`apiSource.ts:21`、`api-source.js:34`）。
2. **去重 = 比对压缩后字符串**。同一脚本重复导入会**报错**，而不是覆盖。
3. **导入即新增，不合并**。没有「同 name 覆盖」逻辑 —— **这正是 CLI 更新时必须先 `removeApi` 再 `importApi` 的原因。**
4. `allowShowUpdateAlert` 默认 `true`。
5. **`importApi` 不做任何合法性/安全性检查**，只要求有注释块。

### B.4.5 IPC 通路

`src/common/ipcNames.ts:105-114`：

```typescript
    import_user_api: 'import_user_api',
    remove_user_api: 'remove_user_api',
    set_user_api: 'set_user_api',
    get_user_api_list: 'get_user_api_list',
    request_user_api: 'request_user_api',
    request_user_api_cancel: 'request_user_api_cancel',
    get_user_api_status: 'get_user_api_status',
    user_api_status: 'user_api_status',
    user_api_show_update_alert: 'user_api_show_update_alert',
    user_api_set_allow_update_alert: 'user_api_set_allow_update_alert',
```

`src/main/modules/winMain/rendererEvent/userApi.ts:16-46`：

```typescript
  mainHandle<string, LX.UserApi.ImportUserApi>(WIN_MAIN_RENDERER_EVENT_NAME.import_user_api, async({ params: script }) => {
    return importApi(script)
  })

  mainHandle<string[], LX.UserApi.UserApiInfo[]>(WIN_MAIN_RENDERER_EVENT_NAME.remove_user_api, async({ params: apiIds }) => {
    return removeApi(apiIds)
  })

  mainHandle<LX.UserApi.UserApiSetApiParams>(WIN_MAIN_RENDERER_EVENT_NAME.set_user_api, async({ params: apiId }) => {
    await setApi(apiId)
  })
  // ...
```

`src/renderer/utils/ipc.ts:124-132` 是渲染侧薄封装。

## B.5 执行运行时 【已核实】

### B.5.1 隐藏 BrowserWindow

`src/main/modules/userApi/main.ts:58-132`（关键片段）：

```typescript
export const createWindow = async(userApi: LX.UserApi.UserApiInfo) => {
  await closeWindow()
  dir ??= process.env.NODE_ENV !== 'production' ? webpackUserApiPath : path.join(__dirname, 'userApi')

  if (!html) {
    html = await fs.promises.readFile(path.join(dir, 'renderer/user-api.html'), 'utf8')
  }
  const preloadUrl = process.env.NODE_ENV !== 'production'
    ? `${path.join(__dirname, '../dist/user-api-preload.js')}`
    : `${path.join(__dirname, 'user-api-preload.js')}`

  browserWindow = new BrowserWindow({
    resizable: false,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    roundedCorners: false,
    hasShadow: false,
    show: false,                                   // ← 隐藏窗口
    webPreferences: {
      contextIsolation: true,                      // ← 上下文隔离
      nodeIntegration: false,                      // ← 渲染进程无 Node
      nodeIntegrationInWorker: false,
      sandbox: false,
      spellcheck: false,
      autoplayPolicy: 'document-user-activation-required',
      enableWebSQL: false,
      disableDialogs: true,
      webgl: false,
      images: false,
      preload: preloadUrl,                         // ← 预加载脚本
    },
  })

  for (const eventName of denyEvents) {
    browserWindow.webContents.on(eventName, (event: Electron.Event) => {
      event.preventDefault()
    })
  }
  browserWindow.webContents.session.setPermissionRequestHandler((webContents, permission, resolve) => {
    if (webContents === browserWindow?.webContents) {
      resolve(false)                               // ← 拒绝一切权限请求
      return
    }
    resolve(true)
  })
  browserWindow.webContents.setWindowOpenHandler(() => {
    return { action: 'deny' }                      // ← 拒绝一切弹窗
  })

  await browserWindow.loadURL('data:text/html;charset=UTF-8,' + encodeURIComponent(html))

  browserWindow.on('ready-to-show', async() => {
    global.lx.event_app.on('updated_config', handleUpdateProxy)
    sendEvent(USER_API_RENDERER_EVENT_NAME.initEnv, { ...userApi, script: await getScript(userApi.id), proxy: getProxy() })
  })
}
```

- `denyEvents`（`main.ts:14-20`）：`will-navigate`、`will-redirect`、`will-attach-webview`、`will-prevent-unload`、`media-started-playing` 全部 `preventDefault`。
- 页面来自 `data:text/html`，`user-api.html` 内容为空 `<body>`（`user-api.html:9-11`），并且 CSP 是 `default-src 'none'`（`user-api.html:5`）。
- **一次只加载一个源**：`createWindow` 开头 `await closeWindow()`。
- `closeWindow`（`main.ts:134-144`）销毁窗口并 `clearAuthCache()` / `clearStorageData()` / `clearCache()`。

### B.5.2 preload 暴露的 `window.lx` **全量 API**

`src/main/modules/userApi/renderer/preload.js:192-347`。以下是完整 API 面（**逐字摘录关键部分**）：

```javascript
  contextBridge.exposeInMainWorld('lx', {
    EVENT_NAMES,
    request(url, { method = 'get', timeout, headers, body, form, formData }, callback) { ... },
    send(eventName, data) { ... },
    on(eventName, handler) { ... },
    utils: {
      crypto: {
        aesEncrypt(buffer, mode, key, iv) { ... },
        rsaEncrypt(buffer, key) { ... },
        randomBytes(size) { ... },
        md5(str) { ... },
      },
      buffer: {
        from(...args) { ... },
        bufToString(buf, format) { ... },
      },
      zlib: {
        inflate(buf) { ... },
        deflate(data) { ... },
      },
    },
    currentScriptInfo: {
      name: userApi.name,
      description: userApi.description,
      version: userApi.version,
      author: userApi.author,
      homepage: userApi.homepage,
      rawScript: userApi.script,
    },
    version: '2.0.0',
    env: 'desktop',
  })
```

**逐项**：

| 成员 | 签名 | 说明 |
|---|---|---|
| `lx.EVENT_NAMES` | `{ request: 'request', inited: 'inited', updateAlert: 'updateAlert' }`（`preload.js:19-23`） | 只有 3 个事件名 |
| `lx.request(url, options, callback)` | `options: {method='get', timeout, headers, body, form, formData}`；返回 **abort 函数** | 由 **Node `needle`** 发请求（绕过 CSP/同源）。`timeout` 被钳制 `Math.min(timeout, 60000)`，默认 60000。回调 `(err, resp, body)`，`resp = {statusCode, statusMessage, headers, bytes, raw, body}`，`body` 若可 JSON.parse 则已解析 |
| `lx.send(eventName, data)` | 返回 Promise | 只接受 `'inited'` 与 `'updateAlert'`；其它 reject `The event is not supported: ...` |
| `lx.on(eventName, handler)` | 返回 Promise | 只接受 `'request'`；其它 reject |
| `lx.utils.crypto.aesEncrypt(buffer, mode, key, iv)` | `=> Buffer` | `createCipheriv` |
| `lx.utils.crypto.rsaEncrypt(buffer, key)` | `=> Buffer` | **左补零到 128 字节**，`RSA_NO_PADDING` |
| `lx.utils.crypto.randomBytes(size)` | `=> Buffer` | |
| `lx.utils.crypto.md5(str)` | `=> hex string` | |
| `lx.utils.buffer.from(...)` | `=> Buffer` | |
| `lx.utils.buffer.bufToString(buf, format)` | `=> string` | `Buffer.from(buf, 'binary').toString(format)` |
| `lx.utils.zlib.inflate/deflate` | Promise | |
| `lx.currentScriptInfo` | `{name, description, version, author, homepage, rawScript}` | **`rawScript` 是明文全文**（见 `lx/2.js` 的自毁校验用到它） |
| `lx.version` | `'2.0.0'` | **API 版本**，不是 App 版本 |
| `lx.env` | `'desktop'` | 移动端为 `'mobile'`（脚本里用 `env != 'mobile'` 分支） |

**注意**：`EVENT_NAMES` 全是小写 `request`/`inited`/`updateAlert`。

### B.5.3 脚本如何被加载执行

`preload.js:355-366`（**逐字**）：

```javascript
  webFrame.executeJavaScript(`(() => {
window.addEventListener('error', (event) => {
  if (event.isTrusted) globalThis.__lx_init_error_handler__.sendError(event.message.replace(/^Uncaught\\sError:\\s/, ''))
})
window.addEventListener('unhandledrejection', (event) => {
  if (!event.isTrusted) return
  const message = typeof event.reason === 'string' ? event.reason : event.reason?.message ?? String(event.reason)
  globalThis.__lx_init_error_handler__.sendError(message.replace(/^Error:\\s/, ''))
})
})()`)

  webFrame.executeJavaScript(userApi.script).catch(_ => _)
```

- ✅ **确认了假设**：`webFrame.executeJavaScript(script)` 在 preload 里执行脚本全文。
- 同时注册了 `error` / `unhandledrejection` 监听，把**首个**错误通过 `__lx_init_error_handler__.sendError` 上报（`onError` 用 `isInitedApi` 门闩保证只报一次，`preload.js:181-186`）。
- 触发链路：preload 顶部 `ipcRenderer.on(USER_API_RENDERER_EVENT_NAME.initEnv, (event, data) => initEnv(data))`（`preload.js:370-372`）→ 主进程在 `ready-to-show` 时 `sendEvent(initEnv, {...userApi, script: await getScript(userApi.id), proxy})`（`main.ts:127`）。

### B.5.4 `inited` 的规范化（重要！）

`preload.js:128-167`：

```javascript
const handleInit = (context, info) => {
  if (!info) {
    sendMessage(USER_API_RENDERER_EVENT_NAME.init, null, false, 'Missing required parameter init info')
    return
  }
  if (info.openDevTools === true) {
    sendMessage(USER_API_RENDERER_EVENT_NAME.openDevTools)
  }
  const sourceInfo = {
    sources: {},
  }
  try {
    for (const source of allSources) {
      const userSource = info.sources[source]
      if (!userSource || userSource.type !== 'music') continue
      const qualitys = supportQualitys[source]
      const actions = supportActions[source]
      sourceInfo.sources[source] = {
        type: 'music',
        actions: actions.filter(a => userSource.actions.includes(a)),
        qualitys: qualitys.filter(q => userSource.qualitys.includes(q)),
      }
    }
  } catch (error) {
    console.log(error)
    sendMessage(USER_API_RENDERER_EVENT_NAME.init, null, false, error.message)
    return
  }
  sendMessage(USER_API_RENDERER_EVENT_NAME.init, sourceInfo, true)

  ipcRenderer.on(USER_API_RENDERER_EVENT_NAME.request, (event, data) => {
    handleRequest(context, data)
  })
}
```

`preload.js:28-45`：

```javascript
const allSources = ['kw', 'kg', 'tx', 'wy', 'mg', 'local']
const supportQualitys = {
  kw: ['128k', '320k', 'flac', 'flac24bit'],
  kg: ['128k', '320k', 'flac', 'flac24bit'],
  tx: ['128k', '320k', 'flac', 'flac24bit'],
  wy: ['128k', '320k', 'flac', 'flac24bit'],
  mg: ['128k', '320k', 'flac', 'flac24bit'],
  local: [],
}
const supportActions = {
  kw: ['musicUrl'], kg: ['musicUrl'], tx: ['musicUrl'], wy: ['musicUrl'],
  mg: ['musicUrl'], xm: ['musicUrl'], local: ['musicUrl', 'lyric', 'pic'],
}
```

**规范化三步**：① 只保留 `allSources` 里的平台；② `type` 必须严格等于 `'music'`；③ `actions` 和 `qualitys` 与内置白名单取交集。
⇒ 脚本声明的 `hires` / `atmos` / `master` / `24bit` / `192k` 等**全部被裁掉**，只剩 `128k/320k/flac/flac24bit`。

### B.5.5 请求/响应协议（完整时序）

```
Renderer(主窗口)                    Main Process                    隐藏窗口(脚本)
     │                                   │                               │
     │ invoke request_user_api           │                               │
     │  {requestKey, data:{source,       │                               │
     │   action:'musicUrl',              │                               │
     │   info:{type, musicInfo}}}        │                               │
     ├──────────────────────────────────►│                               │
     │                                   │ rendererEvent.request()       │
     │                                   │  ├ 清旧 timeout               │
     │                                   │  ├ 设 20s 超时                │
     │                                   │  ├ requestQueue.set(key,      │
     │                                   │  │   [resolve,reject,data])   │
     │                                   │  └ sendEvent('userApi_request')│
     │                                   ├──────────────────────────────►│
     │                                   │                               │ ipcRenderer.on → handleRequest
     │                                   │                               │ events.request.call(ctx,{source,action,info})
     │                                   │                               │  → 脚本 return URL字符串 / Promise
     │                                   │                               │ 校验格式 → sendMessage('userApi_response', {requestKey,result}, true)
     │                                   │◄──────────────────────────────┤
     │                                   │ mainOn('userApi_response', handleResponse)
     │                                   │  ├ requestQueue.get(key)
     │                                   │  ├ delete + clearTimeout
     │                                   │  └ status ? resolve(result) : reject(Error(message))
     │◄──────────────────────────────────┤
     │ {source, action, data:{type,url}} │
```

主进程侧代码 `src/main/modules/userApi/rendererEvent/rendererEvent.ts:124-143`：

```typescript
export const request = async({ requestKey, data }: LX.UserApi.UserApiRequestParams): Promise<any> => await new Promise((resolve, reject) => {
  if (!userApi) {
    reject(new Error('user api is not load'))
  }

  const timeout = timeouts.get(requestKey)
  if (timeout) {
    clearTimeout(timeout)
    timeouts.delete(requestKey)
    cancelRequest(requestKey)
  }

  timeouts.set(requestKey, setTimeout(() => {
    cancelRequest(requestKey)
  }, 20000))

  requestQueue.set(requestKey, [resolve, reject, data])
  sendRequest({ requestKey, data })
})
```

响应处理 `rendererEvent.ts:51-61`：

```typescript
  const handleResponse = ({ params: { status, data: { requestKey, result }, message } }: ResponseParams) => {
    const request = requestQueue.get(requestKey)
    if (!request) return
    requestQueue.delete(requestKey)
    clearRequestTimeout(requestKey)
    if (status) {
      request[0](result)
    } else {
      request[1](new Error(message))
    }
  }
```

**IPC 事件名**（`rendererEvent/name.js:1-15`）：全部前缀 `userApi_` → `userApi_initEnv`、`userApi_init`、`userApi_request`、`userApi_response`、`userApi_openDevTools`、`userApi_showUpdateAlert`、`userApi_getProxy`、`userApi_proxyUpdate`。

### B.5.6 渲染层如何把 `sources` 变成可调用的 API

`src/renderer/core/useApp/useInitUserApi.ts:25-132` —— **这是 `sources` 的消费端**（关键片段，完整保留语义）：

```typescript
  const rUserApiStatus = onUserApiStatus(({ params: { status, message, apiInfo } }) => {
    userApi.status = status
    userApi.message = message

    if (!apiInfo || apiInfo.id !== appSetting['common.apiSource']) return
    if (status) {
      if (apiInfo.sources) {
        let apis: any = {}
        let qualitys: LX.QualityList = {}
        for (const [source, { actions, type, qualitys: sourceQualitys }] of Object.entries(apiInfo.sources)) {
          if (type != 'music') continue
          apis[source as LX.Source] = {}
          for (const action of actions) {
            switch (action) {
              case 'musicUrl':
                apis[source].getMusicUrl = (songInfo: LX.Music.MusicInfo, type: LX.Quality) => {
                  const requestKey = `request__${Math.random().toString().substring(2)}`
                  return {
                    canceleFn() {
                      userApiRequestCancel(requestKey)
                    },
                    promise: sendUserApiRequest({
                      requestKey,
                      data: {
                        source,
                        action: 'musicUrl',
                        info: {
                          type,
                          musicInfo: songInfo,
                        },
                      },
                    }).then(res => {
                      return { type, url: res.data.url }
                    }).catch(async err => {
                      console.log(err.message)
                      return Promise.reject(err)
                    }),
                  }
                }
                break
              case 'lyric':
                apis[source].getLyric = (songInfo: LX.Music.MusicInfo) => { /* action:'lyric' → res.data */ }
                break
              case 'pic':
                apis[source].getPic = (songInfo: LX.Music.MusicInfo) => { /* action:'pic' → res.data */ }
                break
              default:
                break
            }
          }
          qualitys[source as LX.Source] = sourceQualitys
        }
        qualityList.value = qualitys
        userApi.apis = apis
      }
    } else {
      if (message) {
        void dialog({
          message: `${t('user_api__init_failed_alert', { name: apiInfo.name })}\n${message}`,
          selection: true,
          confirmButtonText: t('ok'),
        })
      }
    }
    if (!window.lx.apiInitPromise[1]) window.lx.apiInitPromise[2](status)
  })
```

消费点 `src/renderer/utils/musicSdk/api-source.js:33-38`：

```javascript
const apis = source => {
  if (/^user_api/.test(apiSource.value)) return userApi.apis[source]
  let api = getAPI(source)
  if (api) return api
  throw new Error('Api is not found')
}
```

⇒ ✅ **自定义源与内置源是同一个 `apis(source)` 接口**。LX 的播放逻辑拿到 `getMusicUrl(songInfo, quality)` 后完全无感。

## B.6 安全隔离与权限 【已核实】

| 机制 | 位置 | 效果 |
|---|---|---|
| `contextIsolation: true` + `nodeIntegration: false` | `main.ts:84-88` | 脚本跑在独立 world，拿不到 `require`/`ipcRenderer` |
| 空白页 + `CSP: default-src 'none'` | `user-api.html:5` | 脚本无法用 `fetch`/`XHR`/`<img>` 直连网络（**但** `lx.request` 走 Node 侧 `needle`，**刻意绕过 CSP**） |
| `show: false` | `main.ts:82` | 不可见，用户无法交互 |
| `setPermissionRequestHandler → resolve(false)` | `main.ts:108-114` | 拒绝摄像头/麦克风/通知等所有权限 |
| `setWindowOpenHandler → deny` | `main.ts:115-117` | 禁止开新窗口 |
| `denyEvents` 全 `preventDefault` | `main.ts:14-20, 102-107` | 禁止导航、重定向、webview 附加、卸载阻止、媒体播放 |
| `webgl: false`, `images: false`, `enableWebSQL: false`, `disableDialogs: true` | `main.ts:91-94` | 削面 |
| 销毁时清 session | `main.ts:137-141` | `clearAuthCache` + `clearStorageData` + `clearCache` |
| `lx.request` 超时上限 | `preload.js:211` | ≤ 60s |
| 歌词/URL 长度与格式校验 | `preload.js:57-66, 77-102` | 防超大返回 |
| 单次请求 20s 强制超时 | `rendererEvent.ts:137-139` | |

### ❌ 域名白名单：**不存在**

- `lx.request(url, ...)`（`preload.js:194-242`）**不检查 URL**，任意 `http/https` 主机都放行。
- 唯一的「校验」是 `musicUrl`/`pic` **返回值**必须以 `http`/`https` 开头且 ≤ 2048 字符（`preload.js:78, 96`）。
- `lx.utils.crypto.rsaEncrypt` **允许脚本传入任意公钥**做无填充 RSA —— 是给「聚合 API」做响应解密用的（`juhe/3.js` 的 `code===303` 分支）。
- UI 层明说了这一点，`src/lang/zh-cn.json:738`：

```
"user_api__note": "提示：虽然我们尽可能地隔离了脚本的运行环境，但导入包含恶意行为的脚本仍可能会影响你的系统，请谨慎导入。"
```

- 脚本能拿到 `lx.currentScriptInfo.rawScript`（明文全文），也能用 `lx.utils.crypto.randomBytes`。**沙箱是「尽力而为」级别，不是安全边界。**

⚠️ **【推断】** 由于 `sandbox: false` 且 preload 里 `import needle from 'needle'`、`import zlib from 'zlib'`、`import { ... } from 'crypto'`、`import { httpOverHttp } from 'tunnel'`，这些 Node 模块是在 **preload 的内部 scope**里，`contextBridge` 只桥接了受控函数。常规脚本无法越狱，但历史上 Electron preload 逃逸漏洞不少。

## B.7 版本处理与更新流 【已核实 —— 关键结论】

### B.7.1 `@version` 的角色

- 解析 → 存进条目的 `version` 字符串字段（截断 36 字符）（`utils.ts:53-89`）
- UI 显示（`UserApiModal.vue:10`：`{{ /^\d/.test(api.version) ? \`v${api.version}\` : api.version }}`）
- **然后就没有了。**

✅ **App 里没有任何代码对 `version` 做解析、比较、排序或判断。** 我 grep 了 `semver`、`compareVersion`、`gt(` 等，`userApi` 相关路径下零命中。
`utils.ts:27` 里的 `api.version != null` 只是为了判断「这条记录是否被旧版本 App 写入过、需要重新解析注释头」，**不是版本比较**：

```typescript
      if (api.version != null) continue
      requiredUpdate ||= true
      try {
        infoFull.splice(i, 1, {
          ...parseScriptInfo(api.script),
          ...api,
        })
      } catch (e) {
        infoFull.splice(i, 1)
        i--
      }
```

⇒ **`@version` 对 App 纯粹是展示字段。** CLI 更新判断**不能依赖 App**，必须自己比对。

### B.7.2 `updateAlert` 更新流

**App 完全被动，不做任何网络请求。**

`preload.js:243-262`（`send` 的 `updateAlert` 分支）：

```javascript
    send(eventName, data) {
      return new Promise((resolve, reject) => {
        if (!eventNames.includes(eventName)) return reject(new Error('The event is not supported: ' + eventName))
        switch (eventName) {
          case EVENT_NAMES.inited:
            if (isInitedApi) return reject(new Error('Script is inited'))
            isInitedApi = true
            handleInit(this, data)
            resolve()
            break
          case EVENT_NAMES.updateAlert:
            if (isShowedUpdateAlert) return reject(new Error('The update alert can only be called once.'))
            isShowedUpdateAlert = true
            handleShowUpdateAlert(data, resolve, reject)
            break
          default:
            reject(new Error('Unknown event name: ' + eventName))
        }
      })
    },
```

`preload.js:169-179`：

```javascript
const handleShowUpdateAlert = (data, resolve, reject) => {
  if (!data || typeof data != 'object') return reject(new Error('parameter format error.'))
  if (!data.log || typeof data.log != 'string') return reject(new Error('log is required.'))
  if (data.updateUrl && !/^https?:\/\/[^\s$.?#].[^\s]*$/.test(data.updateUrl) && data.updateUrl.length > 1024) delete data.updateUrl
  if (data.log.length > 1024) data.log = data.log.substring(0, 1024) + '...'
  sendMessage(USER_API_RENDERER_EVENT_NAME.showUpdateAlert, {
    log: data.log,
    updateUrl: data.updateUrl,
  })
  resolve()
}
```

**约束**：`updateAlert` 每个脚本生命周期**只能发一次**；`log` 必填且截断到 1024；`updateUrl` 必须匹配 `^https?://`。

`rendererEvent.ts:65-73`：

```typescript
  const handleShowUpdateAlert = ({ params: { data } }: UpdateInfoParams) => {
    if (!userApi.allowShowUpdateAlert) return
    sendShowUpdateAlert({
      name: userApi.name,
      description: userApi.description,
      log: data.log,
      updateUrl: data.updateUrl,
    })
  }
```

⇒ 若用户勾掉了该源的「允许显示更新弹窗」，通知被丢弃。

`useInitUserApi.ts:145-166`（最终 UI 行为）：

```typescript
  const rUserApiShowUpdateAlert = onShowUserApiUpdateAlert(({ params: { name, log, updateUrl } }) => {
    if (updateUrl) {
      void dialog({
        message: `${t('user_api__update_alert', { name })}\n${log}`,
        selection: true,
        showCancel: true,
        confirmButtonText: t('user_api__update_alert_open_url'),
        cancelButtonText: t('close'),
      }).then(confirm => {
        if (!confirm) return
        window.setTimeout(() => {
          void openUrl(updateUrl)
        }, 300)
      })
    } else {
      void dialog({ message: `${t('user_api__update_alert', { name })}\n${log}`, selection: true, confirmButtonText: t('ok') })
    }
  })
```

⇒ ✅ **App 只弹一个对话框，用户点「打开更新地址」后用系统浏览器打开 `updateUrl`。App 从不下载新脚本、从不替换已存脚本、没有任何 `checkUpdate` 网络调用。**

`src/lang/zh-cn.json:741-742` 佐证文案：

```
"user_api__update_alert": "自定义源「{name}」发现新版本：",
"user_api__update_alert_open_url": "打开更新地址",
```

### B.7.3 存储里的旧记录迁移

`utils.ts:24-49`：若某条记录 `version == null`（说明是老版本 App 写的），会重新跑 `parseScriptInfo(api.script)` 补全元数据并回写；解析失败则**直接删除该条**。

## B.8 是否能在非 Electron 环境运行？ 【已核实 —— 结论：不能】

✅ **确认：不可能脱离 Electron 运行。**

硬依赖清单（逐条有据）：

| 依赖 | 出处 | 为什么无法替代 |
|---|---|---|
| `window.lx` 全局 | `preload.js:192` `contextBridge.exposeInMainWorld('lx', {...})` | `contextBridge` 是 **Electron 独有 API**。所有脚本首行都是 `const {...} = globalThis.lx`，没有 `lx` 直接 `TypeError: Cannot destructure property ... of undefined` |
| `webFrame.executeJavaScript(script)` | `preload.js:366` | `webFrame` 是 **Electron renderer 独有**。Node 里没有等价物（`vm.runInThisContext` 语义不同：不同 global、无 DOM） |
| `needle`（Node HTTP） | `preload.js:2` | 脚本发请求**只**通过 `lx.request`。要在 Node 里跑就得自己实现 `lx.request` |
| `node:zlib` | `preload.js:3` | 供 `lx.utils.zlib` |
| `node:crypto` | `preload.js:4` | 供 `lx.utils.crypto`（`aesEncrypt` / `rsaEncrypt` / `randomBytes` / `md5`） |
| `tunnel` | `preload.js:6` | 代理支持（`httpOverHttp` / `httpsOverHttp`） |
| `ipcRenderer` | `preload.js:1` | 请求分发到主进程 |
| DOM 事件 | `preload.js:356-363` | `window.addEventListener('error' / 'unhandledrejection')` |
| `Buffer` | `preload.js:277, 291-296` | `crypto`/`buffer` 工具返回 Node `Buffer` |

⚠️ **【推断 - 但是高置信】** 理论上可以写一个 **Node shim**：

```
vm.createContext({...})  →  注入 globalThis.lx = {
  EVENT_NAMES, request: needleAdapter, send, on, utils:{...}, currentScriptInfo, version:'2.0.0', env:'desktop'
}
```

然后 `vm.runInContext(script, ctx)`。**这会是个能跑通大部分源的实现**——因为脚本只碰 `globalThis.lx`、`Promise`、`JSON`、`console`、`setTimeout`、`Buffer` 等标准/已注入对象，**不碰 DOM**（我通读了 7 个可读脚本，没有 `document`/`window.` 用法；`huanyin`/`qdy` 只用 `setTimeout`）。

**但要注意三个坑**：

1. `lx.currentScriptInfo.rawScript` 必须提供（`lx/2.js` 用它做自毁校验）；
2. `lx.version === '2.0.0'` 必须精确（`juhe/3.js` 拿它和 `U.update.version` 直接 `>` 比较）；
3. `lx.utils.crypto.rsaEncrypt` 的语义是「**左补零到 128 字节 + RSA_NO_PADDING**」，用现成库时容易做错。

**所以**：对**这个 CLI 项目**而言，能跑（shim）和该跑（直接用 LX 本体）是两件事 —— 见 Part C。

## B.9 端到端时序图

```
① 导入
  UI(本地文件 / HTTP URL) → import_user_api → main/userApi/index.ts:importApi
     → utils.ts:parseScriptInfo(scriptRaw)   // 解析首部注释块
     → utils.ts:deflateScript(scriptRaw)     // gz_ + base64(zlib.deflate)
     → 去重比对 → push userApis[] → saveData()
     → 写 <userData>/LxDatas/user_api.json

② 启用（用户切到该源）
  apiSource.ts:setUserApi(id) → set_user_api → main:setApi(id)
     → closeWindow()（若有旧源）→ loadApi(id) → createWindow(userApi)
     → new BrowserWindow({show:false, preload: user-api-preload.js})
     → loadURL('data:text/html,...')
     → ready-to-show → sendEvent(initEnv, {...userApi, script: getScript(id), proxy})
     → preload: initEnv() → contextBridge.exposeInMainWorld('lx', {...})
                          → webFrame.executeJavaScript(script)
     → 脚本: send(EVENT_NAMES.inited, {status:true, openDevTools, sources})
     → preload: handleInit() 规范化 → ipc 'userApi_init' → rendererEvent.handleInit
     → apiStatus = {status:true, apiInfo:{...userApi, sources}}
     → sendStatusChange → ipc 'user_api_status' → 主窗口 renderer
     → useInitUserApi: 把 sources 编译成 userApi.apis[src].getMusicUrl/getLyric/getPic
     → qualityList.value = {...}

③ 播放（拿 URL）
  播放器 → apis(source).getMusicUrl(songInfo, quality)
     → sendUserApiRequest({requestKey, data:{source, action:'musicUrl', info:{type, musicInfo}}})
     → request_user_api → rendererEvent.request()
     → requestQueue.set(key,[resolve,reject]); 20s timeout
     → sendEvent('userApi_request') → preload: handleRequest()
     → events.request.call(ctx, {source, action, info}) → 脚本返回 URL 字符串
     → 校验 string / ≤2048 / ^https?: → 'userApi_response' {requestKey, result, status:true}
     → handleResponse → resolve() → .then(res => ({type, url: res.data.url}))

④ 更新提醒（脚本主动）
  脚本: checkUpdate() → lx.request(自建接口) → 得到 {updateMsg, updateUrl}
     → lx.send(EVENT_NAMES.updateAlert, {log, updateUrl})     // 每生命周期仅一次
     → preload: handleShowUpdateAlert → 'userApi_showUpdateAlert'
     → rendererEvent: 若 allowShowUpdateAlert → sendShowUpdateAlert
     → 主窗口: dialog 弹窗 → 用户点「打开更新地址」→ shell.openExternal(updateUrl)
     ★ App 到此为止 —— 不下载、不替换
```

---

# Part C — 对 CLI 的结论与建议

## C.1 关键结论汇总

| # | 结论 | 依据 |
|---|---|---|
| (a) | `user_api.json` 格式：`{"userApis":[{id,name,description,version,author,homepage,allowShowUpdateAlert,script:"gz_"+base64(zlib.deflate(utf8))}]}` | `utils.ts:9-16, 90-109`；真实文件实测 ✅ |
| (b) | 脚本元数据：**必须是文件最开头的** `/* ... */` 块，行格式 `^\s?\*\s?@(\w+)\s(.+)$`，仅 `name/description/author/homepage/version` 有效，长度截断 24/36/56/1024/36 | `utils.ts:53-89` ✅ |
| (c) | **脚本不能搜索**，只有 `musicUrl` / `lyric` / `pic`；`search`/`musicSearch` 会被 `actions.filter()` 滤掉，非法平台名会被 `allSources` 丢弃 | `preload.js:28-45, 151-155`；`user_api.d.ts:4` ✅ |
| (d) | 更新：**App 不做更新检查**。脚本自己发 `updateAlert`，App 仅弹窗+开浏览器 | `rendererEvent.ts:65-73`；`useInitUserApi.ts:145-166` ✅ |
| (e) | **App 不会覆盖同名源**。导入 = 新增；重复内容会报错。CLI 更新必须 **remove → import** | `utils.ts:110-129` ✅ |
| (f) | `latest.js` = 最高版本文件的**物理副本**，由 `CreateLatest.py` 的 `shutil.copy2` 生成，权威版本指针是 `VERSIONS` 字典 | `CreateLatest.py:31` + 10/10 md5 一致 ✅ |
| (g) | 最大源数 **20**；单脚本上限 **9,000,000 字符**；URL 必须 `^https?://` | `UserApiModal.vue:75`；`UserApiOnlineImportModal.vue:72, 54` ✅ |
| (h) | 更新检查所需的 `id` 形如 `user_api_XXX_<epoch_ms>`，**前缀 `user_api` 是硬要求** | `apiSource.ts:21`、`api-source.js:34` ✅ |

## C.2 CLI 安装 / 更新的可靠流程

### C.2.1 前置：定位数据目录

```
Windows : %APPDATA%\lx-music-desktop\LxDatas\user_api.json
macOS   : ~/Library/Application Support/lx-music-desktop/LxDatas/user_api.json
Linux   : ~/.config/lx-music-desktop/LxDatas/user_api.json   (userData 由 Electron app.getPath('userData') 决定)
```

⚠️ 依据 `app.ts:141` + `store.ts:81`，`LxDatas` 是 `userData` 的子目录。**Electron 的 `userData` 默认是 `appData/<appName>`**，`appName` 取 `package.json` 的 `name`。**推断**：若用户改了 `--user-data-dir` 或用了便携版，路径会变；CLI 应支持 `--data-dir` 覆盖。

### C.2.2 必须遵守的写入纪律

1. **LX 必须在退出状态**（或至少该源未被激活）。LX 是「内存缓存 + 全量回写」模式（`utils.ts:6-16`，`userApis` 与 `scripts` 都是模块级变量），**运行中的 App 会在下次 `saveData()` 时把你写的文件整个覆盖掉**。
2. **保持 JSON 结构**：顶层 `{"userApis": [...]}`，`JSON.stringify(store, null, '\t')`（Tab 缩进）。
3. **原子写**：写 `<path>.<rand>.temp` 再 `rename`（照抄 `store.ts:17-28`），避免 LX 启动时读到半个文件（`store.ts:82-104`：解析失败会把文件重命名成 `.bak` 并弹错误框！）。
4. **脚本原文必须是 UTF-8 字节**再 `zlib.deflate`。
5. **不要修改脚本内容**（哪怕 trim）。原因：
   - `lx/2.js` 有基于 `@name + @description` 的 MD5 自毁校验（改了会 OOM）。
   - 若干脚本有 `SCRIPT_MD5` 自校验，改动会导致它自己报「脚本被修改」。
   - 直接原样透传最安全。

### C.2.3 安装算法

```
install(source_url):
  1. GET source_url  (follow redirects, ≤3；超时 ≤60s；拒绝 body > 9_000_000 字符)
  2. text = decode_utf8(body)          # ★ 绝不能用 GBK
  3. meta = parse_header(text)          # 复刻 utils.ts:53-89
       - 若 ^/\*[\S|\s]+?\*/ 不匹配 → 报错「无效的自定义源文件」
       - 逐行 ^\s?\*\s?@(\w+)\s(.+)$
       - 只取 name/description/author/homepage/version
       - 截断 24/36/56/1024/36，超长加 '...'
       - name 空 → 用回退名（建议用 source 目录名，比 App 的 locale 时间串更好）
  4. script_field = "gz_" + base64(zlib.compress(text.encode('utf-8')))
  5. 读 user_api.json（不存在则视作 {"userApis": []}）
  6. 去重：若某条目的 script 字符串 == script_field → 已存在，跳过/提示
            若某条目的 (name 或 上游源标识) 相同但 script 不同 → 这是「更新」场景
  7. entry = { id: "user_api_<rand>_<epoch_ms>",
               name, description, version, author, homepage,
               allowShowUpdateAlert: true,
               script: script_field }
     ★ field 顺序无关紧要；缺失的可选字段建议补 ''（与 App 一致）
  8. 若 ≥ 20 条 → 拒绝（或提示先删）
  9. 原子写回
```

### C.2.4 更新算法（**幂等**）

由于 App 没有「覆盖」概念，CLI 必须自己做 **remove + add**：

```
update(entry_id, source_url):
  1. new_text = GET source_url
  2. new_meta = parse_header(new_text)
  3. old_entry = lookup(entry_id)
  4. 若 old_entry 存在：
       old_text = zlib.decompress(base64.b64decode(old_entry.script[3:])).decode('utf-8')
       if old_text == new_text:  → 无变化，直接返回（不要重写文件！）
  5. new_entry = build(new_meta, new_text)
       ★ 保留原 entry 的 id 与 allowShowUpdateAlert，只换 script 与元数据
         （保留 id 可以让用户的「当前选中源」不跳变 —— settings 里的 common.apiSource 存的就是这个 id）
  6. 用 new_entry 替换 old_entry（同位置），原子写回
```

> ✅ **强烈建议更新时保留原 `id`**。理由：`appSetting['common.apiSource']` 存的是 id（`apiSource.ts:47` `setApiSource(apiId)`）。换 id 会让用户下次启动时落到内置源上。
> ⚠️ 但这与 `importApi` 的语义（永远新 id）不同，属于 CLI 的增强 —— **需要确认 LX 不会因 id 复用而出问题**。从代码看 id 只用于 `find(api => api.id == id)` 与 Map key，**复用同 id、换 script 是安全的**（`getUserApis` 每次启动都从文件重建 `scripts` Map）。

### C.2.5 版本比对（CLI 自己实现）

App 不做，所以 CLI 必须做。建议**双重判断**：

| 方法 | 说明 | 可靠性 |
|---|---|---|
| **内容哈希**（**首选**） | 下载后与本地解码文本逐字节比对；相同即最新 | ✅ 最可靠、零误判 |
| `@version` 字符串 | 语义化比较（注意仓库里存在 `"1.3.0"`、`"4"`、`"v3"`、`"9.3 93特供版 DeepSeek优化"` 这种**非标准**值） | ⚠️ 会误判，只能作展示 |
| `ETag` / `Last-Modified` | 对 raw.githubusercontent.com 有效 | ⚠️ ghproxy 镜像可能不透传 |

> ⚠️ **注意 `lx/6.js` 的教训**：仓库 `latest.js`（sha `bad0bcf…`）与用户机器上实际装的 v6（sha `642de2d…`）**内容不同但 `@version` 都是 `6`**。
> 这说明该源会**就地重新混淆**同一版本号。⇒ **`@version` 完全不可信，必须用内容哈希判断。**

### C.3 关于"能否脱离 Electron 运行脚本"

| 用途 | 可行性 | 说明 |
|---|---|---|
| **CLI 安装/更新/管理源** | ✅ 完全可行 | 只需 JSON + zlib + base64 + 正则。**不需要执行脚本**。 |
| **CLI 校验脚本可用性（能初始化）** | ⚠️ 需 Electron | 要 `lx` 全局 + `webFrame.executeJavaScript` |
| **CLI 实际取播放 URL** | ⚠️ 需 shim 或 Electron | 见 B.8 的 Node shim 方案可行性分析 |

**建议**：
- **v1 CLI 只做「安装/更新/列表/删除/导出」**，不执行脚本 —— 零依赖，最稳。
- 若确实要「测试源是否可用」，起一个最小 Electron 进程（`BrowserWindow` + 复刻 preload），而**不是**用 `vm` 硬 shim（后者要精确复刻 `rsaEncrypt` 的补零语义、`version:'2.0.0'`、`currentScriptInfo.rawScript`，且无法覆盖所有混淆脚本的隐蔽依赖）。

### C.4 已知陷阱清单

1. ⚠️ **LX 运行时会覆盖你的写入** —— 必须先退出 LX。
2. ⚠️ **`user_api.json` 解析失败会被 LX 重命名为 `.bak` 并弹错误框**（`store.ts:91-100`）—— 写入必须原子且 JSON 合法。
3. ⚠️ **不要改脚本一个字节** —— `lx/2.js` 会内存炸弹；多个脚本有 `SCRIPT_MD5` 自校验。
4. ⚠️ **必须 UTF-8** —— 脚本含 PUA 字符、零宽字符、组合变音符，GBK 往返必损坏。
5. ⚠️ **`latest.js` 不可全信** —— 它由人工 `CreateLatest.py` 生成，可能滞后。理想做法：同时读目录列表，或直接信任 `latest.js`（因为 README 只公布 latest.js 链接，**对 CLI 而言 latest.js 就是唯一入口**）。
6. ⚠️ **同一版本号可能是不同内容**（`lx/6.js` 实测）→ 用哈希，不用 `@version`。
7. ⚠️ **20 个源上限** —— CLI 批量安装时要检查。
8. ⚠️ **`git`/`qsvip` 这类平台名会被 LX 丢弃** —— CLI 若做「能力展示」，应复刻 `allSources`/`supportActions`/`supportQualitys` 白名单，避免展示假能力。
9. ⚠️ **`hires`/`atmos`/`master`/`24bit`/`192k` 等音质会被裁掉**，只剩 `128k/320k/flac/flac24bit`。
10. ⚠️ **`@description` 在真实数据里常含换行/引号**，JSON 转义要正确。

### C.5 建议 CLI 数据结构

```jsonc
// lxcli 自己的 state 文件（不要混进 user_api.json）
{
  "sources": [
    {
      "key": "sixyin",                                       // 上游标识
      "installId": "user_api_123_1784270441030",             // = user_api.json 里的 id
      "url": "https://raw.githubusercontent.com/.../sixyin/latest.js",
      "mirror": "https://ghproxy.net/...",
      "installedSha256": "430020e5017137615c970e0e62881742", // 对比仓库表的 md5/sha
      "installedVersion": "v1.2.1",
      "installedAt": "2026-10-12T13:57:32+08:00"
    }
  ]
}
```

`update` 时：读 `state` → 下载 → 算 hash → 若 hash 相同则跳过（**这是唯一可靠的「已是最新」判据**）→ 否则替换 `user_api.json` 中 `installId` 对应条目的 `script` 与元数据字段。

---

## 附录 A：本报告用到的原始命令与证据

**编码验证**
```python
for enc in ("utf-8","gb18030"):
    try: t = raw.decode(enc); print(enc); break
    except: pass
```
⇒ `AGENTS.md` / `README.md` / `CreateLatest.py` 均 utf-8。

**哈希与 latest 一致性**：对 10 个目录的每个 `.js` 计算 `md5` / `sha256[:16]`，结果见 A.2 表（10/10 `latest.js` 与最高版本文件 md5 相同）。

**`gz_` 解码验证**
```python
raw = zlib.decompress(base64.b64decode(s[3:])).decode("utf-8")
# [独家音源] v4 解码后 sha256[:16] = 243415bed434b9e0
# repo lx/4.js            sha256[:16] = 243415bed434b9e0   ← 一致
```

**仓库 vs 用户实机差异**
```
REAL name=独家音源 ver=6  len=57608  sha256=642de2d017585820
repo lx/6.js              len=64094  sha256=ef5289ddc2e8fd98
→ 首个差异在 char 338（SERVER_SCRIPT_CONFIG 行之后，VM 主体开始处）
→ 两者 SERVER_SCRIPT_CONFIG 的 fingerprint 均为 ffdaccdf66796c1cbe96df07bf682118
→ 结论：同一 @version 6，但脚本被就地重新混淆过（非 PUA 差异；PUA 去除后仍不等）
```

**真实 `user_api.json` 统计**：8 条源，116772 bytes，顶层 `['userApis']`。

## 附录 B：`lx` API 完整参考（给写源/写 CLI 的人）

```javascript
// === 从 globalThis.lx 解构出的标准写法 ===
const { EVENT_NAMES, request, on, send, utils, env, version, currentScriptInfo } = globalThis.lx

// EVENT_NAMES = { request: 'request', inited: 'inited', updateAlert: 'updateAlert' }

// --- 必须 ---
on(EVENT_NAMES.request, ({ source, action, info }) => { /* 返回 Promise */ })
send(EVENT_NAMES.inited, {
  status: true,                 // 可选，preload 现在不读它
  openDevTools: false,          // true 则自动打开 DevTools
  sources: {
    kw: { name: '酷我', type: 'music', actions: ['musicUrl'], qualitys: ['128k','320k','flac','flac24bit'] },
    // 仅 local 支持 lyric/pic；其余平台的 lyric/pic 会被 filter 掉
  }
})

// --- 可选 ---
send(EVENT_NAMES.updateAlert, { log: '有新版本', updateUrl: 'https://...' })  // 仅一次！

// --- 发起 HTTP ---
const abort = request(url, { method: 'GET', timeout: 5000, headers: {}, body, form, formData },
                      (err, resp, body) => { /* resp.body 尽力 JSON.parse */ })

// --- 工具 ---
utils.crypto.md5(str)                       // → hex
utils.crypto.aesEncrypt(buf, mode, key, iv) // → Buffer
utils.crypto.rsaEncrypt(buf, pemPubKey)     // → Buffer（左补零至 128 + RSA_NO_PADDING）
utils.crypto.randomBytes(n)                 // → Buffer
utils.buffer.from(...) / utils.buffer.bufToString(buf, 'utf8')
await utils.zlib.inflate(buf) / deflate(data)

// --- 只读信息 ---
currentScriptInfo = { name, description, version, author, homepage, rawScript }
version // '2.0.0'  ← API 版本
env     // 'desktop' | 'mobile'
```
