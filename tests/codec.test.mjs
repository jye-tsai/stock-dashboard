// scripts/codec.js 測試:v1 / 明文 / v2 都解得開、v2 來回不失真、同內容輸出 byte 相同、改一天只動幾行、市價欄位拆到 quotes 明文。
import { createRequire } from 'node:module';
import crypto from 'node:crypto';
const PfCodec = createRequire(import.meta.url)('../scripts/codec.js');

const sample = {
  title: '測試', updated: '2026-10-31', priceUpdated: '2026-10-31 13:25',
  fees: { feeRate: 0.001425, feeDiscount: 0.4, taxRates: { '個股': 0.003 } },
  holdings: [
    { type: '個股', code: '2330', name: '台積電', cost: 100, price: 110, lots: 1, priceTime: '2026-10-31 13:25', prevClose: 108, yahooSym: '.TW', target: 150, stop: 90 },
    { type: 'ETF', code: '0050', name: '元大台灣50', cost: 50, price: 0, lots: 2 }
  ],
  account: { '餘額': 0 }, '已實現損益': 1, '股息收入': 2, yearly: [{ year: '2026', capitalGain: 1, dividend: 2, note: '' }],
  auth: { alg: 'PBKDF2-SHA256', salt: 'c2FsdA==', iter: 1, hash: 'aGFzaA==' }, alerts: {},
  history: Array.from({ length: 5 }, (_, i) => ({ date: `2026-10-2${i + 3}`, mv: 1000 + i, cost: 900, un: 100 + i, real: 1, div: 2, ret: 103 + i, prices: { '2330': 100 + i }, lots: { '2330': 1 }, costs: { '2330': 100 } }))
};
const norm = o => JSON.stringify(o, (k, v) => v && typeof v === 'object' && !Array.isArray(v) ? Object.fromEntries(Object.keys(v).sort().map(k => [k, v[k]])) : v);
const R = []; const ok = (n, c) => R.push([n, !!c]);

// v1(舊格式,用 node:crypto 照舊算法做一份)→ decode 得到原物件
const KEY = Buffer.from(PfCodec.KEY_B64, 'base64'), iv = crypto.randomBytes(12);
const c1 = crypto.createCipheriv('aes-256-gcm', KEY, iv);
const ct1 = Buffer.concat([c1.update(JSON.stringify(sample), 'utf8'), c1.final(), c1.getAuthTag()]);
ok('v1 解得開', norm(await PfCodec.decode({ enc: 1, iv: iv.toString('base64'), ct: ct1.toString('base64') })) === norm(sample));
ok('明文原樣回傳', await PfCodec.decode(sample) === sample);

const v2 = await PfCodec.encode(sample);
ok('v2 標記', v2.enc === 2 && typeof v2.head === 'string' && Array.isArray(v2.hist) && v2.hist.length === 5);
ok('時間戳明文', v2.updated === '2026-10-31' && v2.priceUpdated === '2026-10-31 13:25');
ok('quotes 只有市價欄位、沒有張數成本', JSON.stringify(v2.quotes['2330']) === JSON.stringify({ price: 110, prevClose: 108, priceTime: '2026-10-31 13:25', yahooSym: '.TW' }) && v2.quotes['0050'].price === 0 && !('lots' in v2.quotes['2330']));
const headTxt = JSON.stringify(v2);
ok('明文裡看不到張數 / 成本 / 已實現', !headTxt.includes('"lots"') && !headTxt.includes('"cost"') && !headTxt.includes('已實現'));
const back = await PfCodec.decode(JSON.parse(PfCodec.stringify(v2)));
ok('v2 來回不失真', norm(back) === norm(sample));
ok('holdings 市價合併回來', back.holdings[0].price === 110 && back.holdings[0].prevClose === 108 && back.holdings[1].price === 0);

const s1 = PfCodec.stringify(await PfCodec.encode(sample)), s2 = PfCodec.stringify(await PfCodec.encode(JSON.parse(JSON.stringify(sample))));
ok('同內容輸出 byte 相同(確定性 iv)', s1 === s2);
ok('hist 一行一筆、結尾換行', s1.split('\n').length === 5 + 4 && s1.endsWith(']}\n'));
const changed = JSON.parse(JSON.stringify(sample)); changed.holdings[0].price = 111; changed.history[4].mv = 9999; changed.priceUpdated = '2026-10-31 13:35';
const a = s1.split('\n'), b = PfCodec.stringify(await PfCodec.encode(changed)).split('\n');
ok('改今天的價 → 只動第 1 行(quotes / 時間戳)與最後一天那行', a.length === b.length && a.filter((l, i) => l !== b[i]).length === 2 && a[0] !== b[0] && a[a.length - 3] !== b[b.length - 3]);
ok('head 沒變(持股本體沒改)', JSON.parse(a[0] + '"hist":[]}').head === JSON.parse(b[0] + '"hist":[]}').head);
const tampered = JSON.parse(s1); tampered.hist[0] = tampered.hist[0].slice(0, -4) + 'AAAA';
ok('被改過的密文解不開(GCM tag)', await PfCodec.decode(tampered).then(() => false, () => true));

let fail = 0; for (const [n, c] of R) { console.log((c ? 'PASS' : 'FAIL') + '  ' + n); if (!c) fail++; }
process.exit(fail ? 1 : 0);
