#!/usr/bin/env node
/**
 * lxsrc_probe.js — LX 音源脚本通用探针（一个文件，任意版本可用）
 *
 * 用途：拿到一个没见过的 LX 音源 .js，一次性问出：
 *   1. LX 会看到什么元数据（复刻 userApi/utils.ts 的解析规则 + 长度上限）
 *   2. 它属于哪一类混淆（纯文本 / jsjiami / obfuscator.io / JSVMP / jsfuck / 服务端下发）
 *   3. 它声明了哪些 sources / actions / qualitys（含 LX 白名单过滤后的【实际生效】集合）
 *   4. 每个 source × quality 真正请求的 URL / 方法 / 头 / body
 *   5. 响应的字段契约（Proxy 追踪属性访问路径，不靠猜）
 *   6. 是否依赖服务端下发（握手器型）
 *
 * 用法：
 *   node lxsrc_probe.js <file.js>                     # 人读摘要 + JSON 落盘
 *   node lxsrc_probe.js <file.js> --json out.json     # 指定 JSON 路径
 *   node lxsrc_probe.js <file.js> --md  out.md        # 额外导出 Markdown 报告
 *   node lxsrc_probe.js <file.js> --strings           # 额外做静态字符串表还原
 *   node lxsrc_probe.js <file.js> --variants          # 额外扫描 6 种 lx 桩变体（定位自校验分支）
 *   node lxsrc_probe.js <dir>                         # 批量跑目录下所有 .js
 *
 * 直接探针本机已安装的音源（读 LxDatas/user_api.json，无需手工导出）：
 *   node lxsrc_probe.js --from-store --list           # 列出已安装的音源
 *   node lxsrc_probe.js --from-store --name 独家       # 按 name 子串筛选并探针
 *   node lxsrc_probe.js --from-store --store <path>   # 指定 user_api.json 路径
 *
 * 设计原则：**不执行任何真实网络请求**。lx.request 被替换，响应由本脚本伪造。
 * 所以对未知/可疑脚本也是安全的。
 *
 * 不依赖任何 npm 包，只要 Node >= 16。
 */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');
const zlib = require('zlib');

// ────────────────────────────────────────────────────────────────
// 兜底：被探的脚本经常在异步分支里 throw（例如版本校验失败）。
// Node 默认会让 unhandledRejection 终止进程 —— 那会让整批探针中断。
// 这里全部接住并记录，绝不退出。
// ────────────────────────────────────────────────────────────────
const HOST_ASYNC_ERRORS = [];
process.on('unhandledRejection', (reason) => {
  HOST_ASYNC_ERRORS.push(`unhandledRejection: ${reason && reason.stack ? String(reason.stack).split('\n')[0] : String(reason)}`);
});
process.on('uncaughtException', (err) => {
  HOST_ASYNC_ERRORS.push(`uncaughtException: ${err && err.stack ? String(err.stack).split('\n')[0] : String(err)}`);
});

// ────────────────────────────────────────────────────────────────
// 0. 常量：复刻 LX 源码里的白名单
//    lx-music-desktop-master/src/main/modules/userApi/renderer/preload.js:28-45
// ────────────────────────────────────────────────────────────────

const ALL_SOURCES = ['kw', 'kg', 'tx', 'wy', 'mg', 'local'];
const SUPPORT_QUALITYS = {
  kw: ['128k', '320k', 'flac', 'flac24bit'],
  kg: ['128k', '320k', 'flac', 'flac24bit'],
  tx: ['128k', '320k', 'flac', 'flac24bit'],
  wy: ['128k', '320k', 'flac', 'flac24bit'],
  mg: ['128k', '320k', 'flac', 'flac24bit'],
  local: [],
};
const SUPPORT_ACTIONS = {
  kw: ['musicUrl'], kg: ['musicUrl'], tx: ['musicUrl'],
  wy: ['musicUrl'], mg: ['musicUrl'], xm: ['musicUrl'],
  local: ['musicUrl', 'lyric', 'pic'],
};

// 复刻 userApi/utils.ts:53-59 的 INFO_NAMES 长度上限
const INFO_LIMITS = { name: 24, description: 36, author: 56, homepage: 1024, version: 36 };

// 探针用的假 musicInfo：把各平台已知私有字段全塞进去
// （字段来源见 docs/db.md 的 LX.Music.MusicInfo.meta）
const TEST_MUSIC_INFO = {
  id: 'TEST_ID',
  songmid: 'TEST_SONGMID',
  hash: 'TEST_HASH',                 // kg
  strMediaMid: 'TEST_STRMEDIAMID',   // tx
  msg: 'TEST_MSG',                   // mg
  copyrightId: 'TEST_CRID',          // mg
  albumId: 'TEST_ALBUMID',
  albumName: 'TEST_ALBUM',
  name: 'test-name',
  singer: 'test-singer',
  source: 'kw',
  interval: '03:45',
  img: 'https://example.invalid/cover.jpg',
  type: '320k',
  types: [{ type: '320k', size: null }],
  meta: {},
};

// ────────────────────────────────────────────────────────────────
// 1. 元数据解析（复刻 utils.ts:61-89）
// ────────────────────────────────────────────────────────────────

function parseScriptInfo(src) {
  const head = /^\/\*[\S|\s]+?\*\//.exec(src);
  if (!head) return { error: '无效的自定义源文件（找不到头部 /*! ... */ 注释）' };
  const rxp = /^\s?\*\s?@(\w+)\s(.+)$/;
  const raw = {};
  for (const line of head[0].split(/\r?\n/)) {
    const r = rxp.exec(line);
    if (!r) continue;
    if (INFO_LIMITS[r[1]] == null) continue;
    raw[r[1]] = r[2].trim();
  }
  const info = {};
  for (const [k, len] of Object.entries(INFO_LIMITS)) {
    let v = raw[k] ?? '';
    if (v.length > len) v = v.substring(0, len) + '...';
    info[k] = v;
  }
  info._nameFallback = raw.name ? null : `user_api_${new Date().toLocaleString()}`;
  return info;
}

// ────────────────────────────────────────────────────────────────
// 2. 混淆族识别
// ────────────────────────────────────────────────────────────────

function detectFamily(src) {
  const hits = [];
  const nonAscii = (src.match(/[^\x00-\x7F]/g) || []).length;
  const nonAsciiRatio = nonAscii / src.length;
  const zeroWidth = (src.match(/[\u200B-\u200D\uFEFF]/g) || []).length;
  const hexIdent = new Set((src.match(/_0x[0-9a-fA-F]{3,8}/g) || []));
  const longB64 = (src.match(/['"][A-Za-z0-9+/=]{2000,}['"]/g) || []).length;

  // obfuscator.io 常用 \uXXXX 转义把标识符/关键字藏起来 —— 此时源码是纯 ASCII，
  // 上面的 nonAsciiRatio 判据完全失效。必须另设判据。
  const uEscapes = (src.match(/\\u00[0-9a-fA-F]{2}/g) || []).length;
  const unescaped = src.replace(/\\u([0-9a-fA-F]{4})/g, (_m, h) =>
    String.fromCharCode(parseInt(h, 16)));
  // 数字字符串表：[[65219,65235,...],[...]]
  const numericStringTable = /\[\s*\[\s*\d{2,6}\s*,\s*\d{2,6}\s*,\s*\d{2,6}\s*,/.test(src);

  if (/jsjiami\.com\.v\d/i.test(src)) hits.push('jsjiami');
  if (/^\[?\]?[\[\]\(\)!\+]+$/m.test(src) && src.replace(/[\[\]\(\)!\+]/g, '').length < src.length * 0.05) hits.push('jsfuck');
  if (/ﾟωﾟ|｟|Σ\(|AAEncode/i.test(src)) hits.push('aaencode/jjencode');
  if (/javascript-obfuscator|obfuscator\.io/i.test(src)) hits.push('obfuscator.io');
  if (hexIdent.size > 200) hits.push('obfuscator.io-like(_0x 标识符)');
  if (uEscapes > 200) hits.push(`obfuscator.io-like(\\uXXXX 转义 ×${uEscapes})`);
  if (/Object\.call\.bind\(Array\.bind\)/.test(unescaped)) hits.push('obfuscator.io 自防护前导');
  if (numericStringTable) hits.push('数字字符串表');
  if (nonAsciiRatio > 0.05) hits.push('JSVMP-like(非 ASCII 标识符)');
  if (zeroWidth > 0) hits.push('零宽字符标识符');
  if (longB64 > 0) hits.push(`内嵌超长 base64 ×${longB64}`);
  if (/SERVER_SCRIPT_CONFIG/.test(src)) hits.push('服务端下发配置(SERVER_SCRIPT_CONFIG)');
  if (!hits.length) hits.push('纯文本 / 轻度混淆');

  // 是否像「字符串表 + 双参解码器」
  const twoArgCalls = (src.match(/_0x[0-9a-fA-F]+\(\s*0x[0-9a-fA-F]+\s*,\s*['"]/g) || []).length;
  const aliasPattern = /const\s+(_0x[0-9a-fA-F]+)\s*=\s*(_0x[0-9a-fA-F]+)\s*;/.test(src);
  const hasStringTable = /String\['fromCharCode'\]|String\.fromCharCode/.test(src)
    && /charCodeAt/.test(src);

  return {
    hits,
    stats: {
      bytes: src.length,
      lines: src.split(/\r?\n/).length,
      nonAsciiChars: nonAscii,
      nonAsciiRatio: Number(nonAsciiRatio.toFixed(4)),
      zeroWidthChars: zeroWidth,
      hexIdentifiers: hexIdent.size,
      uEscapes,
      numericStringTable,
      embeddedLongBase64: longB64,
      twoArgDecoderCalls: twoArgCalls,
      hasAliasedStringDecoder: aliasPattern && hasStringTable,
    },
    decodeHint: aliasPattern && hasStringTable
      ? '检测到「字符串表 + 别名解码器」，可加 --strings 做静态还原'
      : '未检测到可静态还原的字符串表；以运行时探针结果为准',
  };
}

// ────────────────────────────────────────────────────────────────
// 3. 静态字符串表还原（对 jsjiami / obfuscator.io 系通用）
//    思路：找到 `const A = B;`（B 是双参解码函数），把 A 换成记录型包装器。
// ────────────────────────────────────────────────────────────────

function extractStrings(src) {
  // jsjiami/obfuscator.io 的调用点往往通过**多个别名**抵达解码器：
  //   function _0x332b(a,b){...}          ← 真正的解码器
  //   const _0x2375d4 = _0x332b;          ← 顶层别名
  //   const _0x1a9c83 = _0x2375d4;        ← 函数内别名
  //   const _0x25a897 = _0x332b;          ← 又直接指回解码器
  // 只包第一个别名会漏掉大部分调用（实测只得 13 条，实际约 295 条）。
  // 所以这里做**不动点迭代**：把所有能（直接或传递）指到解码器的别名统统包起来。
  const DECL_RE = /(?:const|let|var)\s+(_0x[0-9a-fA-F]+)\s*=\s*(_0x[0-9a-fA-F]+)\s*[;,]/g;

  const decls = [];
  let m;
  while ((m = DECL_RE.exec(src)) !== null) decls.push({ alias: m[1], from: m[2], raw: m[0] });
  if (!decls.length) return { ok: false, reason: '未找到「别名 = 解码器」结构', strings: [] };

  // 哪个标识符是真正的解码器？取「被别名指向、但自己不指向别人」的那个。
  const targets = new Set(decls.map(d => d.from));
  const aliases = new Set(decls.map(d => d.alias));
  const roots = [...targets].filter(t => !aliases.has(t));
  if (!roots.length) return { ok: false, reason: '别名链里找不到根解码器', strings: [] };
  const decoder = roots[0];

  // 不动点：known = 已知指向解码器的标识符集合
  const known = new Set([decoder]);
  let changed = true;
  while (changed) {
    changed = false;
    for (const d of decls) {
      if (!known.has(d.alias) && known.has(d.from)) { known.add(d.alias); changed = true; }
    }
  }
  const wrapTargets = [...known].filter(k => k !== decoder);

  // 只有当别名确实被当作函数调用（双参、第二参是字符串）时才值得包
  const wrapped = [];
  for (const a of wrapTargets) {
    const callRe = new RegExp(a + "\\(\\s*(?:0x[0-9a-fA-F]+|\\d+)\\s*,\\s*['\"]");
    if (callRe.test(src)) wrapped.push(a);
  }
  if (!wrapped.length) {
    return { ok: false, reason: `找到解码器 ${decoder}，但没有任何别名带双参字符串调用点`, strings: [] };
  }

  // 生成包装代码：注意 __REC 必须在任何解码调用之前定义
  const wrapper = `const __REC = (a,b,r)=>{ (globalThis.__STR = globalThis.__STR || []).push({off:a,key:b,val:r}); };\n`;

  let out = src;
  for (const a of wrapped) {
    // 只替换「别名声明」那一行，指向到解码器的：const A = <chained>;
    const re = new RegExp(`((?:const|let|var)\\s+${a}\\s*=\\s*)${decoder}\\s*([;,])`, 'g');
    out = out.replace(re, `$1((x,y)=>{ const r = ${decoder}(x,y); __REC(x,y,r); return r; })$2`);
  }

  return { ok: true,
           instrumented: { decoder, wrappedAliases: wrapped, aliasCount: decls.length },
           code: wrapper + out,
           finish: (sandbox) => {
             const all = (sandbox.__STR || []).map(s => s.val).filter(v => typeof v === 'string');
             const unique = Array.from(new Set(all));
             const printable = unique.filter(v =>
               /^[\x20-\x7E\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]+$/.test(v));
             return { allCount: all.length, uniqueCount: unique.length, strings: printable };
           } };
}

// ────────────────────────────────────────────────────────────────
// 4. lx 运行时桩 + 沙箱
// ────────────────────────────────────────────────────────────────

function buildSandbox(opts) {
  const stub = opts.stub || {};
  const rec = {
    inited: [], onRequest: [], requests: [], sendOther: [], errors: [], logs: [],
    currentBody: { code: 200, data: {}, url: 'https://example.invalid/a.mp3', src: 'https://example.invalid/a.mp3', music_url: 'https://example.invalid/a.mp3' },
    currentRequestUrls: [],
  };

  const lx = {
    EVENT_NAMES: { request: 'request', inited: 'inited', updateAlert: 'updateAlert' },
    env: stub.env || 'desktop',
    version: stub.version || '2.0.0',
    currentScriptInfo: Object.assign({}, opts.scriptInfo, { rawScript: opts.src }),

    request(url, o, cb) {
      const optsObj = o || {};
      rec.requests.push({ url: String(url), options: optsObj });
      rec.currentRequestUrls.push(String(url));
      const body = rec.currentBody;
      setTimeout(() => {
        try {
          cb(null, {
            statusCode: 200, statusMessage: 'OK', headers: {}, bytes: 0,
            raw: Buffer.from(typeof body === 'string' ? body : JSON.stringify(body)),
            body,
          }, body);
        } catch (e) { rec.errors.push(`in request callback: ${e.name}: ${e.message}`); }
      }, 0);
      return () => {};
    },

    on(name, handler) {
      if (name === 'request' || name === lx.EVENT_NAMES.request) rec.onRequest.push(handler);
      return Promise.resolve();
    },

    send(name, data) {
      if (name === 'inited' || name === lx.EVENT_NAMES.inited) rec.inited.push(data);
      else rec.sendOther.push({ name, data });
      return Promise.resolve();
    },

    utils: {
      crypto: {
        aesEncrypt: (buf, mode, key, iv) => {
          const crypto = require('crypto');
          const c = crypto.createCipheriv(mode, key, iv || Buffer.alloc(0));
          return Buffer.concat([c.update(buf), c.final()]);
        },
        rsaEncrypt: (buf, key) => {
          const crypto = require('crypto');
          const b = Buffer.concat([Buffer.alloc(Math.max(0, 128 - buf.length)), buf]);
          return crypto.publicEncrypt({ key, padding: crypto.constants.RSA_NO_PADDING }, b);
        },
        randomBytes: (n) => stub.zeroRandomBytes
          ? Buffer.alloc(n)
          : require('crypto').randomBytes(n),
        md5: (s) => stub.md5Const
          ? '0123456789abcdef0123456789abcdef'
          : require('crypto').createHash('md5').update(s).digest('hex'),
      },
      buffer: {
        from: (...a) => Buffer.from(...a),
        bufToString: (b, f) => Buffer.from(b, 'binary').toString(f),
      },
      zlib: {
        inflate: (b) => new Promise((res, rej) => require('zlib').inflate(b, (e, d) => e ? rej(e) : res(d))),
        deflate: (d) => new Promise((res, rej) => require('zlib').deflate(d, (e, dd) => e ? rej(e) : res(dd))),
      },
    },
  };

  const sandbox = {
    lx,
    __lx_init_error_handler__: { sendError: (m) => rec.errors.push(`__lx_init_error_handler__: ${m}`) },
    console: {
      log: (...a) => rec.logs.push(a.map(String).join(' ')),
      error: (...a) => rec.logs.push('ERROR ' + a.map(String).join(' ')),
      warn: (...a) => rec.logs.push('WARN ' + a.map(String).join(' ')),
      info: (...a) => rec.logs.push(a.map(String).join(' ')),
      debug: () => {},
    },
    Buffer, setTimeout, clearTimeout, setInterval, clearInterval, setImmediate, queueMicrotask,
    Promise, TextDecoder, TextEncoder, URL, URLSearchParams,
    Object, Array, String, Number, Boolean, Math, JSON, Date, RegExp, Error, TypeError,
    Map, Set, WeakMap, WeakSet, Symbol, Proxy, Reflect,
    Uint8Array, Uint16Array, Uint32Array, Int8Array, Int16Array, Int32Array,
    Float32Array, Float64Array, ArrayBuffer, DataView, BigInt,
    atob: (s) => Buffer.from(s, 'base64').toString('binary'),
    btoa: (s) => Buffer.from(s, 'binary').toString('base64'),
    encodeURIComponent, decodeURIComponent, encodeURI, decodeURI,
    escape, unescape, parseInt, parseFloat, isNaN, isFinite,
  };
  sandbox.globalThis = sandbox;
  sandbox.window = sandbox;
  sandbox.self = sandbox;
  sandbox.global = sandbox;
  // 反分析陷阱复现：显式挂一个 process 键。
  //   'process' in globalThis === true  —— 真 LX 沙箱里这是 false（preload 不暴露 process）。
  //   有些脚本用这个判断「我不在真 LX 里」，然后走诱饵分支。
  if (stub.exposeProcessKey) sandbox.process = undefined;
  return { sandbox, rec, lx };
}

// ────────────────────────────────────────────────────────────────
// 5. Proxy 响应体：追踪属性访问路径
// ────────────────────────────────────────────────────────────────

function makePathTracingBody(codeVal, sink) {
  const mk = (prefix) => new Proxy({}, {
    get(_t, prop) {
      if (typeof prop === 'symbol') return undefined;
      const p = prefix ? `${prefix}.${String(prop)}` : String(prop);
      if (p === 'code') return codeVal;
      sink.push(p);
      return mk(p);
    },
    has() { return true; },
  });
  return mk('');
}

// ────────────────────────────────────────────────────────────────
// 5.5 超时包装
//     坑：有的脚本 request handler 返回永不 settle 的 Promise。
//     此时事件循环会空掉，Node 直接静默 exit 0 —— 探针看起来"没输出"。
//     所以每次调用 handler 都必须带超时（也顺便让事件循环保持存活）。
// ────────────────────────────────────────────────────────────────

function withTimeout(promise, ms, label) {
  let timer;
  const timeout = new Promise((_res, rej) => {
    timer = setTimeout(() => rej(new Error(`__TIMEOUT__ handler 未在 ${ms}ms 内 settle (${label})`)), ms);
  });
  return Promise.race([Promise.resolve(promise), timeout])
    .finally(() => clearTimeout(timer));
}

// ────────────────────────────────────────────────────────────────
// 6. 单文件探针
// ────────────────────────────────────────────────────────────────

async function probeFile(file, opts = {}) {
  const out = { file, fileName: opts.displayName || path.basename(file) };
  let src;
  if (typeof opts.sourceText === 'string') {
    src = opts.sourceText;
  } else {
    try { src = fs.readFileSync(file, 'utf8'); }
    catch (e) { out.fatal = `读取失败: ${e.message}`; return out; }
  }

  out.metadata = parseScriptInfo(src);
  out.obfuscation = detectFamily(src);

  // ---- 静态字符串还原（可选）----
  let runCode = src;
  let stringFinisher = null;
  if (opts.strings) {
    try {
      const ex = extractStrings(src);
      out.staticStrings = { ok: ex.ok, reason: ex.reason || null, instrumented: ex.instrumented || null };
      if (ex.ok) { runCode = ex.code; stringFinisher = ex.finish; }
    } catch (e) {
      out.staticStrings = { ok: false, reason: `${e.name}: ${e.message}` };
    }
  }

  // ---- 第 1 趟：跑起来，抓 inited / on('request') / 请求 ----
  const metaFromFile = {
    name: out.metadata.name || '', description: out.metadata.description || '',
    version: out.metadata.version || '', author: out.metadata.author || '',
    homepage: out.metadata.homepage || '',
  };
  const { sandbox, rec } = buildSandbox({
    src,
    scriptInfo: Object.assign({}, metaFromFile, opts.metaOverride || {}),
    stub: opts.stub || {},
  });
  const ctx = vm.createContext(sandbox);
  out.run = {};
  try {
    vm.runInContext(runCode, ctx, { filename: out.fileName, timeout: opts.timeout || 20000 });
    out.run.loadOk = true;
  } catch (e) {
    out.run.loadOk = false;
    out.run.error = `${e.name}: ${e.message}`;
    out.run.stack = String(e.stack || '').split('\n').slice(0, 5);
  }
  // 给异步留出时间（有的脚本 await 网络）
  await new Promise(r => setTimeout(r, opts.settleMs ?? 300));

  // 收走这一轮里逃逸到宿主进程的异步错误（属当前文件）
  out.run.asyncErrors = HOST_ASYNC_ERRORS.splice(0, HOST_ASYNC_ERRORS.length);
  out.run.consoleLogs = rec.logs.slice(0, 30);
  out.run.runtimeErrors = rec.errors.slice(0, 20);
  out.run.sendCalls = rec.inited.length + rec.sendOther.length;
  // 加载阶段（还没调 handler）就发出的请求 —— 通常是握手/授权/版本校验
  out.run.initialRequests = rec.requests.slice(0).map(r => ({
    url: r.url,
    method: (r.options && r.options.method || 'GET').toUpperCase(),
    headers: (r.options && r.options.headers) || null,
    body: (r.options && (r.options.body || r.options.form || r.options.formData)) || null,
  }));
  out.run.requestCount = rec.requests.length;
  out.run.otherSendEvents = rec.sendOther.map(s => s.name);

  if (stringFinisher) {
    // 注意：这里**不能**立即快照！很多字符串是在 handler 被调用时才惰性解码的
    // （所有 URL 模板都属于这一类）。真正的快照放在所有探针轮次之后。
    out.staticStrings.pending = true;
  }

  // ---- 声明 vs 生效 ----
  const raw = rec.inited.length ? rec.inited[rec.inited.length - 1] : null;
  out.declared = raw && raw.sources ? raw.sources : null;
  out.declaredStatus = raw ? raw.status : null;
  out.declaredOpenDevTools = raw ? raw.openDevTools : null;
  out.effective = null;
  if (out.declared) {
    out.effective = {};
    for (const s of ALL_SOURCES) {
      const u = out.declared[s];
      if (!u || u.type !== 'music') continue;
      out.effective[s] = {
        type: 'music',
        actions: (SUPPORT_ACTIONS[s] || []).filter(a => (u.actions || []).includes(a)),
        qualitys: (SUPPORT_QUALITYS[s] || []).filter(q => (u.qualitys || []).includes(q)),
      };
    }
    // 被白名单丢掉的部分
    out.dropped = {};
    for (const s of Object.keys(out.declared)) {
      if (!ALL_SOURCES.includes(s)) { out.dropped[s] = '平台不在 LX 白名单'; continue; }
      const u = out.declared[s] || {};
      const lostA = (u.actions || []).filter(a => !(SUPPORT_ACTIONS[s] || []).includes(a));
      const lostQ = (u.qualitys || []).filter(q => !(SUPPORT_QUALITYS[s] || []).includes(q));
      if (lostA.length || lostQ.length) out.dropped[s] = { actions: lostA, qualitys: lostQ };
    }
  }

  // ---- 判定形态 ----
  if (!out.run.loadOk) out.form = 'F-加载失败';
  else if (!rec.onRequest.length) out.form = 'B-服务端下发/加载器（未注册 request，等于不提供任何源）';
  else out.form = 'A-纯客户端（已注册 request）';

  // ---- 第 2 趟：逐个 source×quality 探 URL ----
  out.endpoints = [];
  const handler = rec.onRequest[rec.onRequest.length - 1];
  if (handler && out.effective) {
    for (const source of Object.keys(out.effective)) {
      const quals = out.effective[source].qualitys.length
        ? out.effective[source].qualitys : [null];
      for (const quality of quals) {
        const before = rec.requests.length;
        let err = null, returned = undefined;
        try {
          returned = await withTimeout(handler({
            source, action: 'musicUrl',
            info: { type: quality, musicInfo: Object.assign({}, TEST_MUSIC_INFO, { source }) },
          }), opts.handlerTimeout || 5000, `${source}/${quality}`);
        } catch (e) { err = `${e.name}: ${e.message}`; }
        const news = rec.requests.slice(before).map(r => ({
          url: r.url,
          method: (r.options && (r.options.method || (r.options.method || '')).toUpperCase()) || 'GET',
          headers: (r.options && r.options.headers) || null,
          body: (r.options && (r.options.body || r.options.form || r.options.formData)) || null,
        }));
        out.endpoints.push({
          source, quality,
          requests: news,
          returned: typeof returned === 'string' ? returned : (returned === undefined ? null : '<非字符串>'),
          error: err,
        });
      }
    }
  }

  // ---- 第 3 趟：Proxy 追踪响应字段路径 ----
  out.responsePaths = [];
  if (handler && out.effective && out.declared) {
    // 猜每个源的响应 code 值：先试 200，再试 0
    for (const source of Object.keys(out.effective)) {
      for (const codeVal of [200, 0]) {
        const sink = [];
        rec.currentBody = makePathTracingBody(codeVal, sink);
        let err = null;
        try {
          await withTimeout(handler({
            source, action: 'musicUrl',
            info: { type: (out.effective[source].qualitys[0] || null),
                    musicInfo: Object.assign({}, TEST_MUSIC_INFO, { source }) },
          }), opts.handlerTimeout || 5000, `${source}/paths`);
        } catch (e) { err = `${e.name}: ${e.message}`; }
        if (sink.length) {
          // 去掉 await 造成的伪影：`await proxy` 会让引擎去读 `.then`
          const paths = Array.from(new Set(sink.map(p => p.replace(/\.then$/, ''))))
            .filter(p => p !== 'then');
          const leaves = paths.filter(p => !paths.some(o => o !== p && o.startsWith(p + '.')));
          out.responsePaths.push({ source, codeCheck: codeVal, accessed: paths, leaves, error: err });
          break; // 这一档成立，不用再试另一个 code
        }
        if (codeVal === 0) {
          out.responsePaths.push({ source, codeCheck: '200 与 0 都不成立', accessed: [], leaves: [], error: err });
        }
      }
    }
  }

  // ---- 第 4 趟：参数溯源 —— 哪个 musicInfo 字段进了 URL ----
  //  做法：把每个候选字段填上唯一标记，发一次请求，看哪些标记出现在 URL 里。
  //  这是「照着复刻一个 source」时最省时间的一步。
  out.attribution = [];
  if (handler && out.effective) {
    const FIELDS = ['songmid', 'hash', 'strMediaMid', 'msg', 'copyrightId',
                    'albumId', 'albumName', 'name', 'singer', 'id', 'interval'];
    for (const source of Object.keys(out.effective)) {
      const quality = out.effective[source].qualitys[0] || null;
      const info = Object.assign({}, TEST_MUSIC_INFO);
      for (const f of FIELDS) info[f] = `MK${f.toUpperCase()}MK`;
      rec.currentBody = { code: 200, data: { url: 'https://example.invalid/a.mp3' },
                          url: 'https://example.invalid/a.mp3',
                          src: 'https://example.invalid/a.mp3',
                          music_url: 'https://example.invalid/a.mp3' };
      const before = rec.requests.length;
      let err = null;
      try {
        await withTimeout(handler({ source, action: 'musicUrl',
          info: { type: quality, musicInfo: info } }), opts.handlerTimeout || 5000, `${source}/attr`);
      } catch (e) { err = `${e.name}: ${e.message}`; }
      const urls = rec.requests.slice(before).map(r => r.url);
      const blob = urls.join(' | ');
      const consumed = FIELDS.filter(f => blob.includes(`MK${f.toUpperCase()}MK`));
      const unused = FIELDS.filter(f => !consumed.includes(f));
      out.attribution.push({ source, quality, consumed, unused,
                             requests: urls.map(u => u.slice(0, 200)), error: err });
    }
  }

  // ---- 静态字符串快照（必须放在所有 handler 探针之后，见上面的说明）----
  if (stringFinisher && out.staticStrings) {
    try {
      const res = stringFinisher(sandbox);
      out.staticStrings.strings = res.strings;
      out.staticStrings.count = res.strings.length;
      out.staticStrings.rawCount = res.allCount;
      out.staticStrings.uniqueRawCount = res.uniqueCount;
      delete out.staticStrings.pending;
    } catch (e) { out.staticStrings.finishError = `${e.name}: ${e.message}`; }
  }

  // ---- 自动诊断：给出可执行的下一步 ----
  out.diagnosis = diagnose(out);

  return out;
}

// ────────────────────────────────────────────────────────────────
// 6.2 自动诊断
//     把「跑出来不对劲」翻译成「下一步该做什么」。
// ────────────────────────────────────────────────────────────────

function diagnose(r) {
  const d = [];
  const run = r.run || {};
  const eff = r.effective ? Object.keys(r.effective) : [];
  const initial = run.initialRequests || [];

  if (r.fatal) { d.push(`无法读取文件：${r.fatal}`); return d; }

  if (run.loadOk && !run.sendCalls && initial.length) {
    d.push('⚠️ 加载期发了请求，但没有 send(\'inited\')。**先确认你是否等了异步**：' +
           '有些脚本把 inited 放在握手响应回调里，同步读取必然是 0（本工具已内置等待）。' +
           '若已等待仍为 0，则大概率是元数据自校验不通过 —— 跑 --variants 交叉验证。');
  }
  if (!run.loadOk) {
    d.push('加载即抛错。最常见原因是**元数据自校验**：脚本把 currentScriptInfo 与硬编码值比对，' +
           '不一致就 throw（例：`初始化失败！将音源 名字、描述、版本号、作者和主页回正`）。' +
           '本工具已按文件原文注入，若仍失败请检查 --strings 插桩是否破坏了结构，或跑 --variants。');
  }
  if (run.sendCalls && !initial.length && !(r.endpoints || []).length) {
    d.push('声明了源但没有任何请求 —— 检查 actions 是否被 LX 白名单过滤成空（见「被白名单丢弃」）。');
  }
  if (r.declared && !Object.keys(r.declared).length) {
    d.push('send(\'inited\') 里 sources 为空对象。');
  }
  if (r.dropped && Object.keys(r.dropped).length) {
    d.push(`有声明被 LX 白名单丢弃（${Object.keys(r.dropped).join(', ')}）—— 这些能力在真 LX 里不生效。`);
  }
  if (initial.length && (initial.some(q => /rconfig|\/config|version|license|auth/i.test(q.url)))) {
    d.push('加载期存在疑似**授权/配置/版本校验**请求。注意：它的失败**不一定**会阻止脚本工作，' +
           '要看 send(\'inited\') 是否仍然发出。');
  }
  if (r.attribution && r.attribution.length) {
    const never = r.attribution.filter(a => !a.consumed.length);
    if (never.length) {
      d.push(`${never.map(a => a.source).join('/')} 的 URL 里没有任何 musicInfo 字段 —— ` +
             '可能是该平台走独立分支，或它在 handler 内部先抛错了。');
    }
  }
  if (!d.length) d.push('未发现异常。');
  return d;
}

// ────────────────────────────────────────────────────────────────
// 6.5 桩变体扫描
//     有些脚本会自校验元数据 / 依赖真实 md5 / 依赖随机数，
//     校验不过就静默走另一条（或干脆什么都不做）分支。
//     探针若只试一种桩，就会得出「它什么都不提供」的错误结论。
//     这里把几种常见桩组合各跑一遍，用「生效源数 + 请求数」排序。
// ────────────────────────────────────────────────────────────────

const VARIANTS = [
  { id: 'V1-exact',        label: '元数据取自文件 + 真实 crypto（基线）', stub: {}, metaOverride: {} },
  { id: 'V2-md5const',     label: '元数据取自文件 + md5 恒定',            stub: { md5Const: true }, metaOverride: {} },
  { id: 'V3-zerorand',     label: '元数据取自文件 + randomBytes 全 0',    stub: { zeroRandomBytes: true }, metaOverride: {} },
  { id: 'V4-blankmeta',    label: '元数据清空（模拟注释头被改）',          stub: {}, metaOverride: { name: '', description: '', version: '', author: '', homepage: '' } },
  { id: 'V5-oldversion',   label: '元数据取自文件 + lx.version=1.0.0',    stub: { version: '1.0.0' }, metaOverride: {} },
  { id: 'V6-processkey',   label: '多挂一个 process 键（反分析陷阱）',      stub: { exposeProcessKey: true }, metaOverride: {} },
];

async function sweepVariants(file, baseOpts) {
  const rows = [];
  for (const v of VARIANTS) {
    const r = await probeFile(file, Object.assign({}, baseOpts, {
      stub: v.stub, metaOverride: v.metaOverride,
    }));
    const eff = r.effective ? Object.keys(r.effective) : [];
    const urls = (r.endpoints || []).flatMap(e => (e.requests || []).map(q => q.url));
    rows.push({
      variant: v.id, label: v.label,
      loadOk: !!(r.run && r.run.loadOk),
      loadError: (r.run && r.run.error) || null,
      effectiveSources: eff,
      registeredHandler: !!(r.endpoints && r.endpoints.length),
      requestCount: (r.run && r.run.requestCount) || 0,
      distinctHosts: Array.from(new Set(urls.map(u => {
        try { return new URL(u).host; } catch { return '(relative)'; }
      }))),
      sampleUrl: urls[0] || null,
      score: eff.length * 100 + urls.length,
    });
  }
  rows.sort((a, b) => b.score - a.score);
  return rows;
}

// ────────────────────────────────────────────────────────────────
// 7. 报告渲染
// ────────────────────────────────────────────────────────────────

function renderMd(results) {
  const L = [];
  L.push('# 音源脚本探针报告', '');
  L.push(`> 由 \`lx-cli/scripts/lxsrc_probe.js\` 生成，共 ${results.length} 个文件。`);
  L.push('> **未执行任何真实网络请求**，所有响应均为本地伪造。', '');

  for (const r of results) {
    L.push('---', '', `## \`${r.fileName}\``, '');
    if (r.fatal) { L.push(`**致命错误**: ${r.fatal}`, ''); continue; }

    const md = r.metadata || {};
    if (md.error) L.push(`**元数据**: ${md.error}`, '');
    else {
      L.push('| 元数据 | 值 |', '|---|---|');
      for (const k of ['name', 'description', 'version', 'author', 'homepage']) {
        L.push(`| \`@${k}\` | ${md[k] || '(空)'} |`);
      }
      L.push('');
    }

    const o = r.obfuscation || {};
    L.push(`**混淆族**: ${(o.hits || []).join(' + ')}`, '');
    if (o.stats) {
      const s = o.stats;
      L.push(`**规模**: ${s.bytes} 字节 / ${s.lines} 行 · 非 ASCII ${s.nonAsciiChars} (${(s.nonAsciiRatio * 100).toFixed(1)}%) · ` +
             `\`_0x\` 标识符 ${s.hexIdentifiers} 个 · 双参解码调用 ${s.twoArgDecoderCalls} 次 · 零宽字符 ${s.zeroWidthChars}`, '');
    }
    L.push(`**形态判定**: \`${r.form}\``, '');

    if (r.diagnosis && r.diagnosis.length) {
      L.push('**诊断**:', '');
      for (const x of r.diagnosis) L.push(`- ${x}`);
      L.push('');
    }

    const rr = r.run || {};
    if (rr.initialRequests && rr.initialRequests.length) {
      L.push('### 加载期请求（握手/授权/版本校验）', '');
      for (const q of rr.initialRequests) {
        L.push(`- \`${q.method}\` \`${q.url}\``);
        if (q.headers) L.push(`  - headers: \`${JSON.stringify(q.headers)}\``);
      }
      L.push('');
    }

    L.push(`**加载**: ${rr.loadOk ? '成功' : '失败'} · send 调用 ${rr.sendCalls ?? 0} 次 · ` +
           `on('request') ${(r.endpoints || []).length ? '已注册' : '未注册'} · 请求 ${rr.requestCount ?? 0} 次`, '');
    if (rr.error) L.push('```', rr.error, ...(rr.stack || []), '```', '');
    if (rr.runtimeErrors && rr.runtimeErrors.length) {
      L.push('**运行时错误**:', '');
      for (const e of rr.runtimeErrors) L.push(`- ${e}`);
      L.push('');
    }

    if (r.effective && Object.keys(r.effective).length) {
      L.push('### 生效的源（LX 白名单过滤后）', '');
      L.push('| source | actions | qualitys |', '|---|---|---|');
      for (const [s, v] of Object.entries(r.effective)) {
        L.push(`| \`${s}\` | ${(v.actions || []).join(' ') || '—'} | ${(v.qualitys || []).join(' ') || '—'} |`);
      }
      L.push('');
    } else {
      L.push('**未上报任何生效源** —— 该脚本不会给 LX 提供任何能力。', '');
    }
    if (r.dropped && Object.keys(r.dropped).length) {
      L.push('**被白名单丢弃**:', '');
      for (const [s, v] of Object.entries(r.dropped)) L.push(`- \`${s}\`: ${JSON.stringify(v)}`);
      L.push('');
    }

    if (r.endpoints && r.endpoints.length) {
      L.push('### 实际请求', '');
      for (const ep of r.endpoints) {
        L.push(`**\`${ep.source}\` / \`${ep.quality}\`**`, '');
        if (ep.requests && ep.requests.length) {
          for (const q of ep.requests) {
            L.push(`- \`${q.method}\` \`${q.url}\``);
            if (q.headers) L.push(`  - headers: \`${JSON.stringify(q.headers)}\``);
            if (q.body) L.push(`  - body: \`${typeof q.body === 'string' ? q.body : JSON.stringify(q.body)}\``);
          }
        } else L.push('- (未发出请求)');
        if (ep.error) L.push(`- ⚠️ ${ep.error}`);
        if (ep.returned) L.push(`- 返回: \`${String(ep.returned).slice(0, 120)}\``);
        L.push('');
      }
    }

    if (r.responsePaths && r.responsePaths.length) {
      L.push('### 响应字段契约（Proxy 追踪）', '');
      L.push('| source | 校验 | 读取路径 |', '|---|---|---|');
      for (const p of r.responsePaths) {
        L.push(`| \`${p.source}\` | \`code == ${p.codeCheck}\` | \`${(p.leaves || []).join('`, `') || '—'}\` |`);
      }
      L.push('');
    }

    if (r.attribution && r.attribution.length) {
      L.push('### 参数溯源（哪个 musicInfo 字段进了 URL）', '');
      L.push('| source | 被使用的字段 | 未使用的字段 |', '|---|---|---|');
      for (const a of r.attribution) {
        L.push(`| \`${a.source}\` | ${a.consumed.map(f => '`' + f + '`').join(' ') || '—'} | ${a.unused.map(f => '`' + f + '`').join(' ')} |`);
      }
      L.push('');
      L.push('<details><summary>各 source 的实际 URL</summary>', '');
      for (const a of r.attribution) {
        L.push(`- \`${a.source}/${a.quality}\``);
        for (const u of a.requests) L.push(`  - \`${u}\``);
        if (a.error) L.push(`  - ⚠️ ${a.error}`);
      }
      L.push('', '</details>', '');
    }

    if (r.variants && r.variants.length) {
      L.push('### 桩变体扫描（哪个桩能让它暴露自己）', '');
      L.push('| 变体 | 加载 | 生效源 | 请求数 | 命中的 host |', '|---|---|---|---|---|');
      for (const v of r.variants) {
        L.push(`| \`${v.variant}\` | ${v.loadOk ? '✅' : '❌'} | ${v.effectiveSources.join(', ') || '—'} | ${v.requestCount} | ${v.distinctHosts.join(', ') || '—'} |`);
      }
      L.push('');
      const best = r.variants[0];
      if (best) L.push(`**结论**: 最佳桩为 \`${best.variant}\`（${best.label}），样本 URL: \`${best.sampleUrl || '—'}\``, '');
    }

    if (r.staticStrings && r.staticStrings.ok && r.staticStrings.strings) {
      L.push(`### 静态字符串还原（${r.staticStrings.count} 条唯一）`, '');
      const urls = r.staticStrings.strings.filter(s => /^https?:\/\//.test(s));
      if (urls.length) { L.push('**URL 类**:', ''); for (const u of urls) L.push(`- \`${u}\``); L.push(''); }
    }
  }
  return L.join('\n');
}

// ────────────────────────────────────────────────────────────────
// 8.5 读 LX 已安装的音源（LxDatas/user_api.json）
//     LX 把导入的脚本存成 "gz_" + base64(zlib.deflate(raw))，见
//     lx-music-desktop-master/src/main/modules/userApi/utils.ts:90-98
//     （不以 gz_ 开头的值原样返回，兼容早期未压缩格式）
// ────────────────────────────────────────────────────────────────

function resolveLxDatas(exeDir) {
  if (exeDir) {
    const portable = path.join(exeDir, 'portable');
    if (fs.existsSync(portable)) {
      // LX app.ts:133 —— setPath('userData', <portable>/userData)
      return path.join(portable, 'userData', 'LxDatas');
    }
  }
  const plat = process.platform;
  if (plat === 'win32') {
    const roaming = process.env.APPDATA;
    if (!roaming) throw new Error('APPDATA 未设置');
    return path.join(roaming, 'lx-music-desktop', 'LxDatas');
  }
  if (plat === 'darwin') {
    return path.join(process.env.HOME || '', 'Library/Application Support/lx-music-desktop', 'LxDatas');
  }
  const base = process.env.XDG_CONFIG_HOME || path.join(process.env.HOME || '', '.config');
  return path.join(base, 'lx-music-desktop', 'LxDatas');
}

function inflateScript(script) {
  if (typeof script !== 'string') return '';
  if (!script.startsWith('gz_')) return script;   // 兼容早期未压缩存储
  return zlib.inflateSync(Buffer.from(script.slice(3), 'base64')).toString('utf8');
}

function readStore(storePath, exeDir) {
  const p = storePath || path.join(resolveLxDatas(exeDir), 'user_api.json');
  if (!fs.existsSync(p)) throw new Error(`找不到音源存储文件: ${p}`);
  const data = JSON.parse(fs.readFileSync(p, 'utf8'));
  const list = Array.isArray(data) ? data : (data.userApis || []);
  return { path: p, entries: list };
}

// ────────────────────────────────────────────────────────────────
// 9. CLI
// ────────────────────────────────────────────────────────────────

function parseArgs(argv) {
  const a = { files: [], json: null, md: null, strings: false, timeout: 20000, quiet: false };
  for (let i = 0; i < argv.length; i++) {
    const t = argv[i];
    if (t === '--json') a.json = argv[++i];
    else if (t === '--md') a.md = argv[++i];
    else if (t === '--strings') a.strings = true;
    else if (t === '--variants') a.variants = true;
    else if (t === '--from-store') a.fromStore = true;
    else if (t === '--store') a.store = argv[++i];
    else if (t === '--exe-dir') a.exeDir = argv[++i];
    else if (t === '--name') a.name = argv[++i];
    else if (t === '--list') a.list = true;
    else if (t === '--export') a.export = argv[++i];
    else if (t === '--settle') a.settleMs = Number(argv[++i]);
    else if (t === '--timeout') a.timeout = Number(argv[++i]) || 20000;
    else if (t === '--handler-timeout') a.handlerTimeout = Number(argv[++i]) || 5000;
    else if (t === '--quiet') a.quiet = true;
    else if (t === '--help' || t === '-h') a.help = true;
    else a.files.push(t);
  }
  return a;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help || (!args.files.length && !args.fromStore && !args.list)) {
    process.stdout.write(fs.readFileSync(__filename, 'utf8').split('*/')[0].replace(/^\/\*\*?/, '') + '\n');
    process.exit(args.help ? 0 : 1);
  }

  // ---- 模式：从 LX 已安装音源存储读取 ----
  if (args.fromStore || args.list) {
    let store;
    try { store = readStore(args.store, args.exeDir); }
    catch (e) { process.stderr.write(`FATAL: ${e.message}\n`); process.exit(1); }

    process.stderr.write(`store: ${store.path}  (${store.entries.length} 个音源)\n`);

    if (args.list) {
      process.stdout.write('\n=== 已安装的音源 ===\n');
      process.stdout.write(
        `${'name'.padEnd(26)} ${'version'.padEnd(10)} ${'author'.padEnd(14)} ${'raw'.padStart(8)}  id\n`);
      process.stdout.write('-'.repeat(110) + '\n');
      for (const e of store.entries) {
        let rawLen = '?';
        try { rawLen = String(inflateScript(e.script).length); } catch { rawLen = 'ERR'; }
        process.stdout.write(
          `${String(e.name || '').slice(0, 25).padEnd(26)} ` +
          `${String(e.version || '').slice(0, 9).padEnd(10)} ` +
          `${String(e.author || '').slice(0, 13).padEnd(14)} ` +
          `${rawLen.padStart(8)}  ${e.id}\n`);
      }
      process.stdout.write('\n');
      // --list 一律「只列出」，不与探针混在一起。
      // 想「列出并全部探针」就用 --from-store（不带 --list）。
      return;
    }

    // 把已安装脚本导出成 .js 文件（便于 diff 版本 / 用文件模式再探针）
    if (args.export) {
      fs.mkdirSync(args.export, { recursive: true });
      const safe = (s) => String(s || '').replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_').trim() || 'unnamed';
      const written = [];
      for (const e of store.entries) {
        let raw;
        try { raw = inflateScript(e.script); }
        catch (err) { written.push({ name: e.name, error: err.message }); continue; }
        const fn = `${safe(e.name)}__v${safe(e.version)}__${e.id}.js`;
        const fp = path.join(args.export, fn);
        fs.writeFileSync(fp, raw, 'utf8');
        written.push({ name: e.name, version: e.version, file: fp, bytes: raw.length });
      }
      process.stdout.write(`\n=== 导出到 ${args.export} ===\n`);
      for (const w of written) {
        process.stdout.write(w.error
          ? `  ${w.name}: 失败 ${w.error}\n`
          : `  ${w.bytes.toString().padStart(8)} B  ${path.basename(w.file)}\n`);
      }
      process.stdout.write('\n');
    }

    const picked = store.entries.filter(e =>
      !args.name || String(e.name || '').includes(args.name));
    if (!picked.length) {
      process.stderr.write(`没有匹配 --name ${JSON.stringify(args.name)} 的音源\n`);
      process.exit(1);
    }

    const results = [];
    for (const e of picked) {
      let raw;
      try { raw = inflateScript(e.script); }
      catch (err) {
        results.push({ file: `<store:${e.id}>`, fileName: e.name || e.id,
                       fatal: `脚本解压失败: ${err.message}` });
        continue;
      }
      process.stderr.write(`probe: ${e.name} (v${e.version}) ... `);
      const r = await probeFile(`<store:${e.id}>`, {
        sourceText: raw,
        displayName: `${e.name} (v${e.version})`,
        strings: args.strings, timeout: args.timeout,
        handlerTimeout: args.handlerTimeout, settleMs: args.settleMs,
      });
      r.storeEntry = {
        id: e.id, name: e.name, version: e.version, author: e.author,
        description: e.description, homepage: e.homepage,
        allowShowUpdateAlert: e.allowShowUpdateAlert,
        storedBytes: String(e.script || '').length,
        rawBytes: raw.length,
        storePath: store.path,
      };
      if (args.variants) {
        r.variants = await sweepVariants(`<store:${e.id}>`, {
          sourceText: raw, displayName: e.name,
          strings: false, timeout: args.timeout, handlerTimeout: args.handlerTimeout,
        });
      }
      results.push(r);
      process.stderr.write(`${r.form || r.fatal}\n`);
    }

    if (!args.quiet) {
      process.stdout.write('\n=== 摘要 ===\n');
      for (const r of results) {
        const eff = r.effective ? Object.keys(r.effective) : [];
        process.stdout.write(
          `\n${r.fileName}  [${r.storeEntry ? r.storeEntry.id : ''}]\n` +
          `  混淆: ${(r.obfuscation && r.obfuscation.hits || []).join(' + ') || '?'}\n` +
          `  形态: ${r.form || r.fatal}\n` +
          `  生效源: ${eff.length ? eff.join(', ') : '(无)'}\n` +
          `  请求数: ${(r.run && r.run.requestCount) || 0}\n`);
        for (const ep of (r.endpoints || [])) {
          for (const q of (ep.requests || [])) {
            process.stdout.write(`    ${ep.source}/${ep.quality} ${q.method} ${q.url.slice(0, 150)}\n`);
          }
        }
      }
      process.stdout.write('\n');
    }

    if (args.json) {
      fs.writeFileSync(args.json, JSON.stringify(results, null, 2), 'utf8');
      process.stderr.write(`JSON -> ${args.json}\n`);
    }
    if (args.md) {
      fs.writeFileSync(args.md, renderMd(results), 'utf8');
      process.stderr.write(`MD   -> ${args.md}\n`);
    }
    return;
  }

  // 目录展开
  const targets = [];
  for (const f of args.files) {
    const st = fs.existsSync(f) ? fs.statSync(f) : null;
    if (st && st.isDirectory()) {
      for (const n of fs.readdirSync(f)) if (n.toLowerCase().endsWith('.js')) targets.push(path.join(f, n));
    } else targets.push(f);
  }

  const results = [];
  for (const t of targets) {
    process.stderr.write(`probe: ${path.basename(t)} ... `);
    const r = await probeFile(t, { strings: args.strings, timeout: args.timeout,
                                   handlerTimeout: args.handlerTimeout,
                                   settleMs: args.settleMs });
    if (args.variants) {
      r.variants = await sweepVariants(t, { strings: false, timeout: args.timeout,
                                            handlerTimeout: args.handlerTimeout });
    }
    results.push(r);
    process.stderr.write(`${r.form || r.fatal}\n`);
  }

  // 控制台摘要
  if (!args.quiet) {
    process.stdout.write('\n=== 摘要 ===\n');
    for (const r of results) {
      const eff = r.effective ? Object.keys(r.effective) : [];
      process.stdout.write(
        `\n${r.fileName}\n` +
        `  混淆: ${(r.obfuscation && r.obfuscation.hits || []).join(' + ') || '?'}\n` +
        `  形态: ${r.form || r.fatal}\n` +
        `  生效源: ${eff.length ? eff.join(', ') : '(无)'}\n` +
        `  请求数: ${(r.run && r.run.requestCount) || 0}\n`
      );
      if (r.endpoints) {
        for (const e of r.endpoints) {
          for (const q of (e.requests || [])) {
            process.stdout.write(`    ${e.source}/${e.quality} ${q.method} ${q.url.slice(0, 150)}\n`);
          }
        }
      }
    }
    process.stdout.write('\n');
  }

  const jsonPath = args.json || null;
  if (jsonPath) {
    fs.writeFileSync(jsonPath, JSON.stringify(results, null, 2), 'utf8');
    process.stderr.write(`JSON -> ${jsonPath}\n`);
  }
  if (args.md) {
    fs.writeFileSync(args.md, renderMd(results), 'utf8');
    process.stderr.write(`MD   -> ${args.md}\n`);
  }
}

// 作为模块被 require 时不自动执行，方便其他脚本复用这些内部件
if (require.main === module) {
  main().catch(e => { process.stderr.write(`FATAL: ${e.stack}\n`); process.exit(1); });
}

module.exports = { probeFile, buildSandbox, detectFamily, parseScriptInfo, extractStrings,
                   sweepVariants, VARIANTS, readStore, inflateScript, resolveLxDatas };
