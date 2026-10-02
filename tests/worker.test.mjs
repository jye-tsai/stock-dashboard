// cloudflare/worker.mjs 路由測試:cron 字串 → 哪個 workflow(Cron Triggers 與 ROUTES 對不上是 2026-09-30 / 10-02 兩次漏跑的原因)
import assert from 'node:assert/strict';
const log = console.log; console.log = () => {};          // 未知 cron 的警告不印
const { route, cronWindow } = await import('../cloudflare/worker.mjs');
const R = c => { const r = route(c); return r.workflow + ' ' + JSON.stringify(r.inputs); };
assert.equal(R('*/10 1-5 * * *'), 'update-prices.yml null');
assert.equal(R('30 23 * * 1-5'), 'chips.yml {"premarket":"true","source":"cron"}');
assert.equal(R('40 7 * * 2-6'), 'chips.yml {"source":"cron"}');
assert.equal(R('40 8 * * 2-6'), 'chips.yml {"source":"cron"}');
assert.equal(R('*/30 * * * *'), 'update-prices.yml null');   // 對不到 → 保住股價
const W = (p, s) => cronWindow(p, new Date(s));           // 台北時間 = UTC + 8
assert.equal(W('/chips-cron', '2026-10-02T07:40:00Z'), true);        // 週五 15:40
assert.equal(W('/chips-cron', '2026-10-02T08:40:00Z'), true);        // 週五 16:40
assert.equal(W('/chips-cron', '2026-10-02T07:29:00Z'), false);       // 15:29
assert.equal(W('/chips-cron', '2026-10-02T10:00:00Z'), false);       // 18:00
assert.equal(W('/chips-cron', '2026-10-03T07:40:00Z'), false);       // 週六
assert.equal(W('/premarket-cron', '2026-10-01T23:30:00Z'), true);    // 台北週五 07:30(UTC 還是週四)
assert.equal(W('/premarket-cron', '2026-10-02T01:00:00Z'), false);   // 09:00 開盤後
assert.equal(W('/premarket-cron', '2026-10-01T22:59:00Z'), false);   // 06:59
assert.equal(W('/premarket-cron', '2026-10-04T23:30:00Z'), true);    // 台北週一 07:30(UTC 週日)
assert.equal(W('/premarket-cron', '2026-10-03T23:30:00Z'), false);   // 台北週日 07:30
assert.equal(W('/nope', '2026-10-02T07:40:00Z'), false);
console.log = log;
console.log('worker.test: 5 條路由 + 11 個時段通過');
