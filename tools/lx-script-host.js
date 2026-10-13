#!/usr/bin/env node
/**
 * lx-script-host.js —— LX 音源脚本宿主（Node sidecar）
 *
 * 作用：在不启动 LX 的前提下，加载并执行 LX 的 JS 音源脚本，
 *       走 `musicUrl` 协议取出音频直链。
 *
 * 用法（由 Python 以子进程方式调用）：
 *
 *   node lx-script-host.js --script <file.js> --source kw \
 *        --id 223088839 --quality 320k [--json]
 *
 * 成功时 stdout 输出 **单行 JSON**：
 *   { "ok": true, "url": "...", "source": "kw", "quality": "320k",
 *     "script": "...", "elapsedMs": 123 }
 * 失败时：
 *   { "ok": false, "error": "...", "stage": "load|init|request" }
 *
 * 设计约束（★ 用户要求"用完要释放"）：
 *   - **一次性进程**：取到 URL 后立即退出，绝不常驻
 *   - 不写任何文件
 *   - 超时由父进程强杀（脚本内部也有兜底）
 *   - 内存上限由父进程用 --max-old-space-size 控制
 *
 * 安全说明（诚实告知）：
 *   Node 的 vm **不是安全沙箱**，脚本理论上可经原型链逃逸。
 *   本宿主只做到"限制能力"：不注入 fs / child_process / net，
 *   只给受控的 lx.* 接口。请仅运行你信任的音源脚本。
 */
'use strict'

const fs = require('fs')
const http = require('http')
const https = require('https')
const crypto = require('crypto')
const vm = require('vm')

/* ------------------------------------------------------------ 参数解析 */

function parseArgs(argv) {
  const out = { quality: '', json: false, timeout: 25000 }
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i]
    if (a === '--json') { out.json = true; continue }
    if (a.startsWith('--')) {
      const key = a.slice(2)
      const val = argv[i + 1]
      out[key] = val
      i++
    }
  }
  return out
}

const args = parseArgs(process.argv)
const scriptPath = args.script
const wantSource = args.source
const wantId = args.id
const wantQuality = args.quality
const timeoutMs = Number(args.timeout || 25000)

function fail(msg, stage) {
  process.stdout.write(JSON.stringify({
    ok: false, error: String(msg || 'unknown'), stage: stage || 'request',
  }) + '\n')
  process.exit(1)
}

if (!scriptPath || !wantSource || !wantId) {
  fail('缺少参数：--script / --source / --id', 'args')
}

let code
try {
  code = fs.readFileSync(scriptPath, 'utf8')
} catch (e) {
  fail(`无法读取脚本: ${e.message}`, 'load')
}

/* ------------------------------------------------------------ LX 桩实现 */

const state = {
  handlers: {},
  inited: null,
  requests: [],
  cookies: {},
}

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:82.0) Gecko/20100101 Firefox/82.0'

/**
 * 复刻 LX 的 lx.request(url, options, callback)
 * ★ 必须跟随 3xx，否则拿不到 kuwo 的 cookie（脚本取 token 的前提）
 */
function doRequest(url, options, callback, depth) {
  depth = depth || 0
  const u = String(url)
  state.requests.push(u)
  const lib = u.startsWith('https') ? https : http
  const headers = Object.assign({
    'User-Agent': UA,
    Accept: '*/*',
  }, (options && options.headers) || {})

  const cookieStr = Object.keys(state.cookies)
    .map((k) => `${k}=${state.cookies[k]}`).join('; ')
  if (cookieStr) headers.Cookie = cookieStr

  const req = lib.request(u, {
    method: (options && options.method) || 'GET',
    headers,
    timeout: timeoutMs,
  }, (res) => {
    const sc = res.headers['set-cookie']
    if (Array.isArray(sc)) {
      for (const c of sc) {
        const m = /^([^=]+)=([^;]*)/.exec(c)
        if (m) state.cookies[m[1]] = m[2]
      }
    }
    if (res.statusCode >= 300 && res.statusCode < 400 &&
        res.headers.location && depth < 5) {
      res.resume()
      let next
      try {
        next = new URL(res.headers.location, u).toString()
      } catch (e) {
        next = res.headers.location
      }
      return doRequest(next, options, callback, depth + 1)
    }
    const chunks = []
    res.on('data', (c) => chunks.push(c))
    res.on('end', () => {
      const raw = Buffer.concat(chunks)
      const text = raw.toString('utf8')
      let parsed = text
      try { parsed = JSON.parse(text) } catch (e) { /* 保留文本 */ }
      callback(null, {
        statusCode: res.statusCode,
        statusMessage: res.statusMessage,
        headers: res.headers,
        body: parsed,
        raw,
      }, raw)
    })
  })
  req.on('error', (e) => callback(e, null, null))
  req.on('timeout', () => req.destroy(new Error('request timeout')))
  if (options && options.body) req.write(options.body)
  req.end()
}

const bufUtils = {
  from: (...a) => Buffer.from(...a),
  bufToString: (b, enc) => Buffer.from(b).toString(enc || 'utf8'),
  concat: (arr) => Buffer.concat(arr),
}

const cryptUtils = {
  md5: (s) => crypto.createHash('md5').update(String(s)).digest('hex'),
  sha1: (s) => crypto.createHash('sha1').update(String(s)).digest('hex'),
  sha256: (s) => crypto.createHash('sha256').update(String(s)).digest('hex'),
  randomBytes: (n) => crypto.randomBytes(n),
  aesEncrypt: (buf, mode, key, iv) => {
    const k = Buffer.from(String(key || ''), 'utf8')
    const i = Buffer.from(String(iv || ''), 'utf8')
    const alg = k.length === 32 ? 'aes-256-cbc' : 'aes-128-cbc'
    const c = crypto.createCipheriv(
      alg, k.slice(0, k.length === 32 ? 32 : 16),
      i.length >= 16 ? i.slice(0, 16) : Buffer.alloc(16))
    return Buffer.concat([c.update(Buffer.from(buf)), c.final()])
  },
  aesDecrypt: (buf, mode, key, iv) => {
    const k = Buffer.from(String(key || ''), 'utf8')
    const i = Buffer.from(String(iv || ''), 'utf8')
    const alg = k.length === 32 ? 'aes-256-cbc' : 'aes-128-cbc'
    const d = crypto.createDecipheriv(
      alg, k.slice(0, k.length === 32 ? 32 : 16),
      i.length >= 16 ? i.slice(0, 16) : Buffer.alloc(16))
    return Buffer.concat([d.update(Buffer.from(buf)), d.final()])
  },
  rsaEncrypt: () => { throw new Error('rsaEncrypt 未实现') },
  rsaDecrypt: () => { throw new Error('rsaDecrypt 未实现') },
}

const lx = {
  EVENT_NAMES: {
    request: 'request',
    inited: 'inited',
    updateAlert: 'updateAlert',
  },
  env: 'desktop',
  version: '2.12.5',
  currentScriptInfo: {
    name: 'lx-cli-host', description: '', version: '', author: '', homepage: '',
  },
  request: doRequest,
  utils: { buffer: bufUtils, crypto: cryptUtils },
  crypto: cryptUtils,
  md5: cryptUtils.md5,
  on: (name, handler) => { state.handlers[name] = handler },
  send: (name, data) => { if (name === 'inited') state.inited = data },
}

/* ------------------------------------------------------------ 执行脚本 */

const sandbox = {
  lx,
  console,
  Buffer,
  URL,
  setTimeout, clearTimeout, setInterval, clearInterval,
  process: { env: {}, version: process.version, platform: process.platform },
  require: (m) => (m === 'lx' ? lx : {}),
}
sandbox.global = sandbox
sandbox.globalThis = sandbox

const t0 = Date.now()
try {
  vm.createContext(sandbox)
  vm.runInContext(code, sandbox, { timeout: timeoutMs, filename: scriptPath })
} catch (e) {
  fail(`脚本执行失败: ${e.message}`, 'load')
}

const info = state.inited || {}
const handler = state.handlers.request
if (!handler) {
  fail('脚本没有注册 request handler', 'load')
}
if (info.status === false) {
  fail(`脚本自报初始化失败: ${info.message || ''}`, 'init')
}

/* ------------------------------------------------------------ 发起请求 */

const payload = {
  source: wantSource,
  action: 'musicUrl',
  info: {
    type: wantQuality || undefined,
    musicInfo: {
      id: wantId,
      songmid: wantId,
      source: wantSource,
      name: 'lx-cli',
      singer: 'lx-cli',
      interval: '00:00',
      meta: {
        songId: wantId, albumName: '', picUrl: '',
        qualitys: [], _qualitys: {},
      },
      types: [],
    },
  },
}

let settled = false
function finish(result) {
  if (settled) return
  settled = true
  process.stdout.write(JSON.stringify(result) + '\n')
  // ★ 一次性进程：输出后立刻退出（用完即释放）
  process.exit(result.ok ? 0 : 1)
}

// 兜底超时
const hardTimer = setTimeout(() => {
  finish({ ok: false, error: 'handler 超时', stage: 'request' })
}, timeoutMs)

try {
  const ret = handler(payload, (resp) => {
    clearTimeout(hardTimer)
    const url = extractUrl(resp)
    if (url) {
      finish({
        ok: true, url, source: wantSource,
        quality: wantQuality || '', script: args.name || '',
        elapsedMs: Date.now() - t0,
        initedSources: Object.keys(info.sources || {}),
      })
    } else {
      finish({
        ok: false, stage: 'request',
        error: typeof resp === 'string' ? resp : JSON.stringify(resp).slice(0, 300),
      })
    }
  })
  if (ret && typeof ret.then === 'function') {
    ret.then((r) => {
      clearTimeout(hardTimer)
      const url = extractUrl(r)
      if (url) {
        finish({
          ok: true, url, source: wantSource,
          quality: wantQuality || '', script: args.name || '',
          elapsedMs: Date.now() - t0,
          initedSources: Object.keys(info.sources || {}),
        })
      } else {
        finish({
          ok: false, stage: 'request',
          error: typeof r === 'string' ? r : JSON.stringify(r).slice(0, 300),
        })
      }
    }).catch((e) => {
      clearTimeout(hardTimer)
      finish({ ok: false, stage: 'request', error: (e && e.message) || String(e) })
    })
  }
} catch (e) {
  clearTimeout(hardTimer)
  fail(`调用 handler 失败: ${e.message}`, 'request')
}

/** 兼容多种返回形状：字符串 URL / {url} / {data:{url}} */
function extractUrl(r) {
  if (!r) return ''
  if (typeof r === 'string') return r.startsWith('http') ? r : ''
  if (typeof r.url === 'string' && r.url.startsWith('http')) return r.url
  const d = r.data
  if (typeof d === 'string' && d.startsWith('http')) return d
  if (d && typeof d === 'object') {
    if (typeof d.url === 'string' && d.url.startsWith('http')) return d.url
    if (d.data && typeof d.data.url === 'string' && d.data.url.startsWith('http')) {
      return d.data.url
    }
  }
  return ''
}
