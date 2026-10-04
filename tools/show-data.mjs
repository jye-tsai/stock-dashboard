// 印出 data.json(加密)的重點:市價時間、各檔持股、今日 history。給 Claude / 人工檢查用,不寫檔。
// 用法:node tools/show-data.mjs [檔案,預設 data.json]      看 repo 上最新:git fetch origin main && git show origin/main:data.json > /tmp/d.json && node tools/show-data.mjs /tmp/d.json
import fs from 'node:fs';
import crypto from 'node:crypto';
const KEY = Buffer.from('3Nr6TNQZewwC/3wye+lwc60BCeWcaPRmQddHyAbS+uc=', 'base64');   // 與 app.js / update-prices.mjs 相同的混淆金鑰
const raw = JSON.parse(fs.readFileSync(process.argv[2] || 'data.json', 'utf8'));
let d = raw;
if (raw.enc) {
  const iv = Buffer.from(raw.iv, 'base64'), all = Buffer.from(raw.ct, 'base64');
  const c = crypto.createDecipheriv('aes-256-gcm', KEY, iv); c.setAuthTag(all.subarray(all.length - 16));
  d = JSON.parse(Buffer.concat([c.update(all.subarray(0, all.length - 16)), c.final()]).toString('utf8'));
}
console.log(`市價時間 ${d.priceUpdated}|已實現 ${d['已實現損益']}|股息 ${d['股息收入']}`);
for (const h of d.holdings || []) if (h.lots > 0) console.log(`  ${h.code} ${h.name} ${h.lots} 張 @${h.cost}  現價 ${h.price}(昨收 ${h.prevClose ?? '—'},${h.priceTime ?? '—'})`);
const last = (d.history || []).at(-1);
if (last) { const { prices, pricesMiss, lots, costs, ...x } = last; console.log('history 最新', JSON.stringify(x)); }
