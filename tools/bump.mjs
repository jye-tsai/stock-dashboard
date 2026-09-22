// 上傳前一鍵:跑測試 → 綠燈才把靜態檔版本 query 換新(index.html 的 ?v= × 4、sw.js 的 ASSET_VER 與 CACHE)。
//   node tools/bump.mjs            跑測試 + bump
//   node tools/bump.mjs --no-test  只 bump(不建議)
//   node tools/bump.mjs --show     只印目前版本
// 版本字串 = 台北日期 YYYYMMDD + 序號字母(同一天第二次是 b、第三次 c…);CACHE 的數字 +1。
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const rd = f => fs.readFileSync(path.join(root, f), 'utf8');
const wr = (f, s) => fs.writeFileSync(path.join(root, f), s);
const args = new Set(process.argv.slice(2));

const idx = rd('index.html'), sw = rd('sw.js');
const curVer = (sw.match(/const ASSET_VER = '([^']+)'/) || [])[1];
const curCache = (sw.match(/const CACHE = 'panghu-v(\d+)'/) || [])[1];
const idxVers = [...new Set((idx.match(/\?v=([0-9a-z]+)/g) || []).map(s => s.slice(3)))];
if (!curVer || !curCache) { console.error('sw.js 裡找不到 ASSET_VER / CACHE'); process.exit(1); }
console.log(`目前:index.html ?v=${idxVers.join(',')}(×${(idx.match(/\?v=[0-9a-z]+/g) || []).length})  sw.js ASSET_VER=${curVer}  CACHE=panghu-v${curCache}`);
if (idxVers.length !== 1 || idxVers[0] !== curVer) console.warn('⚠ index.html 與 sw.js 的版本不一致,bump 會統一成新值');
if (args.has('--show')) process.exit(0);

if (!args.has('--no-test')) {
  const r = spawnSync(process.execPath, ['tests/run.mjs'], { cwd: root, stdio: 'inherit' });
  if (r.status !== 0) { console.error('\n測試沒過,不 bump。修好再來。'); process.exit(1); }
}

// 新版本:台北今天 + 序號
const d = new Date(Date.now() + 8 * 3600 * 1000);
const today = `${d.getUTCFullYear()}${String(d.getUTCMonth() + 1).padStart(2, '0')}${String(d.getUTCDate()).padStart(2, '0')}`;
let letter = 'a';
if (curVer.startsWith(today)) { const l = curVer.slice(8) || 'a'; letter = String.fromCharCode(l.charCodeAt(0) + 1); if (letter > 'z') { console.error('同一天 bump 超過 26 次?去休息。'); process.exit(1); } }
const newVer = today + letter, newCache = Number(curCache) + 1;

let idx2 = idx.replace(/\?v=[0-9a-z]+/g, `?v=${newVer}`);
let sw2 = sw.replace(/const ASSET_VER = '[^']+'/, `const ASSET_VER = '${newVer}'`).replace(/const CACHE = 'panghu-v\d+'/, `const CACHE = 'panghu-v${newCache}'`);
wr('index.html', idx2); wr('sw.js', sw2);
console.log(`\n已 bump → ?v=${newVer}  CACHE=panghu-v${newCache}`);
console.log('上傳:index.html、sw.js,加上你這次改到的 .js / .css / scripts/ / tests/ 檔(子資料夾要進到對應資料夾上傳,或用 GitHub Desktop 一次 push)。');
