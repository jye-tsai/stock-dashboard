// sw.js 行為測試:在 Node 模擬 Service Worker 全域,驗 install / activate / fetch 三種策略。版號從 sw.js 原始碼讀,不用跟著改。
import fs from 'node:fs'; import vm from 'node:vm';
import { fileURLToPath } from 'node:url'; import path from 'node:path';
const src = fs.readFileSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'sw.js'), 'utf8');
const CACHE = src.match(/const CACHE = '([^']+)'/)[1];
const shellLocal = (src.match(/^\s*'\.\/[^']*'/gm) || []).length;              // SHELL 裡本站檔案數
const listeners = {}; const store = new Map();
const cacheObj = { match: async req => store.get(req.url), put: async (req, res) => { store.set(req.url, res); }, add: async u => { store.set(u, { body: 'shell:' + u }); }, keys: async () => [...store.keys()].map(u => ({ url: u })) };
let netBody = 'v1', netFail = false;
const ctx = {
  self: { addEventListener: (t, fn) => { listeners[t] = fn; }, skipWaiting: async () => {}, clients: { claim: async () => {} } },
  caches: { open: async () => cacheObj, keys: async () => ['panghu-v1', CACHE], delete: async k => { ctx._deleted.push(k); return true; }, match: async req => store.get(req.url) },
  _deleted: [], fetch: async () => { if (netFail) throw new Error('offline'); return { ok: true, body: netBody, clone() { return { ok: true, body: netBody }; } }; },
  URL, Promise, Response: { error: () => ({ body: 'ERR' }) }, console
};
vm.createContext(ctx); vm.runInContext(src, ctx);
async function dispatch(url, mode = 'no-cors') {
  let responded, waited = [];
  listeners.fetch({ request: { method: 'GET', url, mode }, respondWith: p => { responded = p; }, waitUntil: p => waited.push(p) });
  const res = await responded; await Promise.allSettled(waited); return res;
}
const R = []; const ok = (n, c) => R.push([n, !!c]);
const IMG = 'https://x.test/panghu.webp';
let r = await dispatch(IMG); ok('miss → network + 補快取', r.body === 'v1' && store.get(IMG).body === 'v1');
netBody = 'v2'; r = await dispatch(IMG); const firstOld = r.body === 'v1', refreshed = store.get(IMG).body === 'v2'; r = await dispatch(IMG);
ok('stale-while-revalidate:第一次舊、背景更新', firstOld && refreshed); ok('第二次拿到新', r.body === 'v2');
netFail = true; r = await dispatch(IMG); ok('離線有快取 → 快取', r.body === 'v2');
r = await dispatch('https://x.test/nothing.webp'); ok('離線無快取 → error response 不 throw', r.body === 'ERR');
netFail = false; netBody = 'data-new'; r = await dispatch('https://x.test/data.json'); ok('data.json 網路優先', r.body === 'data-new');
await listeners.activate({ waitUntil: p => (ctx._act = p) }); await ctx._act; ok(`activate 只刪舊快取(留 ${CACHE})`, JSON.stringify(ctx._deleted) === '["panghu-v1"]');
await listeners.install({ waitUntil: p => (ctx._inst = p) }); await ctx._inst;
ok(`install 預快取 SHELL(${shellLocal} 個本站檔)`, [...store.keys()].filter(k => k.startsWith('./')).length === shellLocal && shellLocal >= 10);
let fail = 0; for (const [n, c] of R) { console.log((c ? 'PASS' : 'FAIL') + '  ' + n); if (!c) fail++; }
process.exit(fail ? 1 : 0);
