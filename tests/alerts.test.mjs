// 停損 / 目標價提醒(scripts/alerts.mjs):跨過去只發一次、回到安全區才重新起算、改價位重算、資料異常不發、賣光清狀態
import assert from 'node:assert/strict';
import { scanAlerts, alertText } from '../scripts/alerts.mjs';

const H = (price, o = {}) => ({ code: '2330', name: '台積電', lots: 2, cost: 1850, prevClose: 2475, stop: 2400, target: 3000, price, ...o });
const data = { holdings: [H(2475)] };
const step = (price, o, want, wantState) => {
  data.holdings[0] = H(price, o);
  const fire = scanAlerts(data, '2026-09-25 13:35');
  assert.deepEqual(fire.map(f => f.kind), want, `price ${price} ${JSON.stringify(o)}`);
  assert.deepEqual(Object.keys(data.alerts), wantState, `state after ${price}`);
  return fire;
};

step(2475, {}, [], []);                                          // 正常
const fired = step(2395, {}, ['stop'], ['2330:stop']);           // 跌破停損 → 發
step(2380, {}, [], ['2330:stop']);                               // 還在下面 → 不重發
step(2410, {}, [], ['2330:stop']);                               // 回到停損 ~ +1% 之間 → 不重算
step(2380, {}, [], ['2330:stop']);                               // 又跌下去 → 不重發
step(2430, {}, [], []);                                          // 回到 +1% 以上 → 重算
step(2390, {}, ['stop'], ['2330:stop']);                         // 再跌破 → 重發
step(2390, { stop: 2395 }, ['stop'], ['2330:stop']);             // 改了停損價 → 重算後重發
step(3010, { prevClose: 2900, stop: 2395 }, ['target'], ['2330:target']);   // 達目標
step(3500, { prevClose: 2900, stop: 2395 }, [], ['2330:target']);           // 漲超過 10.5%(超出漲跌停)→ 資料異常不發
step(3010, { prevClose: 2900, lots: 0, stop: 2395 }, [], []);              // 賣光 → 清狀態
step(3010, { prevClose: 2900, stop: 0, target: 0 }, [], []);               // 沒設價位 → 不檢查

// 兩檔同時觸發,訊息分段
const two = { holdings: [H(2395), H(3010, { code: '0050', name: '元大台灣50', prevClose: 2900 })] };
const f2 = scanAlerts(two, '2026-09-25 13:35');
assert.deepEqual(f2.map(f => f.kind + ':' + f.h.code), ['stop:2330', 'target:0050']);
const txt = alertText(f2, '2026-09-25 13:35');
assert.match(txt, /^⚠ 停損提醒 13:35\n2330 台積電 現價 2,395 ≤ 停損 2,400\n今日 -3\.2%｜成本 1,850\(\+29\.5%\)\n停損是你自己設的/);
assert.match(txt, /🎯 目標價提醒 13:35\n0050 元大台灣50 現價 3,010 ≥ 目標 3,000\n今日 \+3\.8%｜成本 1,850\(\+62\.7%\)\n目標價是你自己設的/);

// 單檔的文字(跟 update-prices 實際送 LINE 的一樣)
assert.equal(alertText(fired, '2026-09-25 13:35').split('\n').length, 4);
console.log('alerts.test: 15 個情境通過');
