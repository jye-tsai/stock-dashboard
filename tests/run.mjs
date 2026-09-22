// 一鍵檢查:語法 + 單元測試。本機:node tests/run.mjs;GitHub Action check.yml 也是跑這支。
// 沒有任何外部套件,Node 20+ 即可。
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const run = (args, label) => {
  const r = spawnSync(process.execPath, args, { cwd: root, encoding: 'utf8' });
  const ok = r.status === 0;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}`);
  if (!ok) console.log((r.stdout + r.stderr).trim().split('\n').map(l => '      ' + l).join('\n'));
  else if (r.stdout.trim()) console.log(r.stdout.trim().split('\n').map(l => '      ' + l).join('\n'));
  return ok;
};

let ok = true;
for (const f of ['app.js', 'charts.js', 'sw.js', 'scripts/calc.js', 'scripts/update-prices.mjs']) ok = run(['--check', f], `syntax ${f}`) && ok;
for (const t of ['tests/calc.test.mjs', 'tests/sw.test.mjs']) ok = run([t], t) && ok;
console.log(ok ? '\n全部通過' : '\n有東西壞了,看上面 FAIL');
process.exit(ok ? 0 : 1);
