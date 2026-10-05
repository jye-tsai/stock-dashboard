// 即時價取捨(scripts/quote.mjs):MIS 09:00 前不收、非今天不收、z 優先、收盤競價不用 pz、上市櫃查詢、MIS 優先合併
import assert from 'node:assert/strict';
import { misQuote, misQuery, mergeLive } from '../scripts/quote.mjs';

const T = '2026-10-05';
const S = (o = {}) => ({ c: '2330', d: '20261005', z: '1500.0000', pz: '1495.0000', y: '1480.0000', b: '1490.0000_1485.0000_', ...o });

assert.equal(misQuote(S(), T, 857), null, '09:00 前是試撮價,不收');
assert.equal(misQuote(S({ d: '20261002' }), T, 1000), null, '上一交易日資料不收');
assert.equal(misQuote(null, T, 1000), null);
assert.deepEqual(misQuote(S(), T, 905), { code: '2330', price: 1500, via: 'z', prev: 1480 }, 'z 優先');
assert.deepEqual(misQuote(S({ z: '-' }), T, 1100), { code: '2330', price: 1495, via: 'pz', prev: 1480 }, '沒成交用 pz');
assert.deepEqual(misQuote(S({ z: '-', pz: '-' }), T, 1150), { code: '2330', price: 1490, via: 'bid', prev: 1480 }, 'z / pz 都沒有用最佳買價');
assert.deepEqual(misQuote(S({ z: '-' }), T, 1326), { code: '2330', price: 0, via: '', prev: 1480 }, '收盤競價 pz / b 是試撮,不用');
assert.deepEqual(misQuote(S({ z: '-', pz: '-', y: '-', b: '-' }), T, 1000), { code: '2330', price: 0, via: '', prev: 0 });

assert.equal(misQuery(['2330', '6488', '00891'], { 2330: '.TW', 6488: '.TWO' }), 'tse_2330.tw|otc_6488.tw|tse_00891.tw|otc_00891.tw');

assert.deepEqual(mergeLive({ 2330: 1500, 2317: 0 }, { 2330: 1490, 2317: 200, 6488: 500 }),
  { live: { 2330: 1500, 2317: 200, 6488: 500 }, src: { 2330: 'MIS', 2317: 'Yahoo', 6488: 'Yahoo' } });
assert.deepEqual(mergeLive({}, {}), { live: {}, src: {} });
console.log('quote OK');
