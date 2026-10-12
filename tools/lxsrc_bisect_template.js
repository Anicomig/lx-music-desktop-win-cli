/**
 * 反向二分：从 lxsrc_probe.js 里「能跑通」的沙箱出发，逐个删/改，找到
 * 到底哪个细节让 v6 载荷从「注册 6 个源」变成「什么都不注册」。
 *
 * 直接复用 lxsrc_probe.js 的 buildSandbox，保证基线是真·能跑通的那套。
 */
'use strict';
const fs = require('fs');
const vm = require('vm');
const { buildSandbox } = require('./lxsrc_probe.js');

const SRC = 'C:\\Users\\EDY\\Documents\\workspace\\本地音源\\lx-music-source-v6.js';
const raw = fs.readFileSync(SRC, 'utf8');

const FILE_META = {
  name: '独家音源',
  description: '后续更新，请关注微信公众号: 洛雪科技',
  version: '6',
  author: 'w',
  homepage: '',
};

function run(label, mutate, stubOverrides) {
  const { sandbox, rec } = buildSandbox({
    src: raw,
    scriptInfo: Object.assign({}, FILE_META),
    stub: stubOverrides || {},
  });
  try { mutate && mutate(sandbox, rec); } catch (e) {
    process.stdout.write(`${label.padEnd(42)} MUTATE-ERR ${e.message}\n`); return;
  }
  let err = null;
  try { vm.runInContext(raw, vm.createContext(sandbox), { filename: 'v6.js', timeout: 20000 }); }
  catch (e) { err = `${e.name}: ${e.message}`; }
  const flag = rec.inited.length ? '' : '   <== 变成了 0';
  process.stdout.write(
    `${label.padEnd(42)} send=${rec.inited.length} on=${rec.onRequest.length} req=${rec.requests.length}${err ? ' err=' + err : ''}${flag}\n`
  );
}

process.stdout.write('--- 基线（应当 send=1）---\n');
run('BASELINE (lxsrc_probe 原样)', null, {});
run('BASELINE 再跑一次（确认稳定）', null, {});

// ── 决定性验证：同步读 vs 让出一轮事件循环后读 ──
process.stdout.write('\n=== 决定性验证：send(inited) 是不是异步的 ===\n');
(async () => {
  for (const label of ['同步读取', 'await setTimeout(0) 后读取', 'await 300ms 后读取']) {
    const { sandbox, rec } = buildSandbox({ src: raw, scriptInfo: Object.assign({}, FILE_META), stub: {} });
    vm.runInContext(raw, vm.createContext(sandbox), { filename: 'v6.js', timeout: 20000 });
    if (label === '同步读取') {
      // 不动
    } else if (label === 'await setTimeout(0) 后读取') {
      await new Promise(r => setTimeout(r, 0));
    } else {
      await new Promise(r => setTimeout(r, 300));
    }
    process.stdout.write(`${label.padEnd(30)} send=${rec.inited.length} req=${rec.requests.length}\n`);
  }
  process.stdout.write('\n（结论：send 在 /rconfig 的响应回调里才发出 —— 同步读必然为 0）\n');
})();

process.stdout.write('\n--- 逐项删减 ---\n');
run('删 process 别名 global', (sb) => { delete sb.global; });
run('删 window', (sb) => { delete sb.window; });
run('删 self', (sb) => { delete sb.self; });
run('删 __lx_init_error_handler__', (sb) => { delete sb.__lx_init_error_handler__; });
run('删 lx.currentScriptInfo.rawScript', (sb) => { delete sb.lx.currentScriptInfo.rawScript; });
run('currentScriptInfo.description 置空', (sb) => { sb.lx.currentScriptInfo.description = ''; });
run('currentScriptInfo.name 置空', (sb) => { sb.lx.currentScriptInfo.name = ''; });
run('currentScriptInfo.version 置空', (sb) => { sb.lx.currentScriptInfo.version = ''; });
run('currentScriptInfo 整体置空', (sb) => { sb.lx.currentScriptInfo = {}; });
run('删 lx.env', (sb) => { delete sb.lx.env; });
run('删 lx.version', (sb) => { delete sb.lx.version; });
run('lx.on 改成返回 undefined', (sb, rec) => {
  sb.lx.on = (n, h) => { if (n === 'request') rec.onRequest.push(h); };
});
run('lx.send 改成返回 undefined', (sb, rec) => {
  sb.lx.send = (n, d) => { if (n === 'inited') rec.inited.push(d); };
});
run('lx.request 改成不同步回调(cb 用 Promise)', (sb, rec) => {
  sb.lx.request = (url, o, cb) => {
    rec.requests.push({ url: String(url), options: o || {} });
    Promise.resolve().then(() => { try { cb(null, { statusCode: 200, body: {} }, {}); } catch (e) { void e; } });
    return () => {};
  };
});

process.stdout.write('\n--- 改 crypto 桩 ---\n');
run('md5 恒定', null, { md5Const: true });
run('randomBytes 全 0', null, { zeroRandomBytes: true });
run('md5 恒定 + randomBytes 全 0', null, { md5Const: true, zeroRandomBytes: true });

process.stdout.write('\n--- 删 utils 各子项 ---\n');
run('删 lx.utils.zlib', (sb) => { delete sb.lx.utils.zlib; });
run('删 lx.utils.buffer', (sb) => { delete sb.lx.utils.buffer; });
run('删 lx.utils.crypto.randomBytes', (sb) => { delete sb.lx.utils.crypto.randomBytes; });
run('删 lx.utils.crypto.rsaEncrypt', (sb) => { delete sb.lx.utils.crypto.rsaEncrypt; });
run('删 lx.utils.crypto.aesEncrypt', (sb) => { delete sb.lx.utils.crypto.aesEncrypt; });
run('删 lx.utils.crypto.md5', (sb) => { delete sb.lx.utils.crypto.md5; });
run('删 lx.utils 整体', (sb) => { delete sb.lx.utils; });
