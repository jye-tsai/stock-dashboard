// scripts/calc.js 單元測試(純 Node):損益 / 時序 / TWR / 除息。任何一項 FAIL 就 exit 1。
import { createRequire } from 'node:module';
const PfCalc = createRequire(import.meta.url)('../scripts/calc.js');
const R = []; const ok = (n, c, info) => R.push([n, !!c, info]);
const near = (a, b, eps = 1e-9) => Math.abs(a - b) < eps;

/* ---------- 損益:與舊版前端 / 後端公式逐字對照 ---------- */
const sample = {
  fees: { feeRate: 0.001425, feeDiscount: 0.4, taxRates: { '個股': 0.003, 'ETF': 0.001, '債券ETF-高收益': 0 } },
  holdings: [
    { type: '個股', code: '2330', name: '台積電', cost: 1707.96, price: 2490, lots: 2.33 },
    { type: 'ETF', code: '00981A', name: '主動統一台股增長', cost: 16.18, price: 32, lots: 160 },
    { type: '債券ETF-高收益', code: '00679B', name: '元大美債20年', cost: 30.5, price: 29.1, lots: 12.345 },
    { type: '未知類別', code: '6488', name: '環球晶', cost: 500, price: 0, lots: 1 }
  ],
  '已實現損益': 465709, '股息收入': 231270
};
function oldCompute(d) {
  const f = d.fees;
  const rows = d.holdings.map(h => {
    const costAmt = Math.round(h.cost * 1000 * h.lots), mv = Math.round(h.price * 1000 * h.lots);
    const taxRate = f.taxRates[h.type] ?? 0.003, sellCost = Math.round(mv * (taxRate + f.feeRate * f.feeDiscount));
    const unrealized = mv - costAmt - sellCost;
    return { ...h, costAmt, mv, sellCost, unrealized, plRatio: costAmt ? unrealized / costAmt : 0 };
  });
  const t = rows.reduce((a, r) => ({ costAmt: a.costAmt + r.costAmt, mv: a.mv + r.mv, sellCost: a.sellCost + r.sellCost, unrealized: a.unrealized + r.unrealized }), { costAmt: 0, mv: 0, sellCost: 0, unrealized: 0 });
  rows.forEach(r => { r.costPctOfTotal = t.costAmt ? r.costAmt / t.costAmt : 0; r.mvPctOfTotal = t.mv ? r.mv / t.mv : 0; });
  return { rows, t };
}
ok('compute == 舊前端公式', JSON.stringify(PfCalc.compute(sample)) === JSON.stringify(oldCompute(sample)));
ok('totals 欄位', (() => { const t = PfCalc.totals(sample); return t.totalReturn === t.unreal + 465709 + 231270 && t.cost === oldCompute(sample).t.costAmt; })());
ok('compute 空資料', PfCalc.compute({}).rows.length === 0 && PfCalc.totals(null).mv === 0);

/* ---------- 時序 ---------- */
const hist = [
  { date: '2026-06-12', un: 100, taiex: 0 }, { date: '2026-06-13', un: 100, taiex: 0 },
  { date: '2026-06-15', un: 120, taiex: 20000, cost: 1000, ret: 120 }, { date: '2026-06-16', un: 90, taiex: 20100, cost: 1000, ret: 90 },
  { date: '2026-06-19', un: 90, taiex: 0, cost: 1000, ret: 90 }, { date: '2026-06-22', un: 150, taiex: 20300, cost: 1000, ret: 150 },
  { date: '2026-06-23', un: 130, taiex: 20200, cost: 1000, ret: 130 }, { date: '2027-01-05', un: 200, taiex: 21000, cost: 1000, ret: 200 },
];
const S0 = PfCalc.histSlices(hist, 0, '2027-01-06');
ok('histSlices 去週末 / 無大盤日', S0.full.map(h => h.date).join() === '2026-06-15,2026-06-16,2026-06-22,2026-06-23,2027-01-05');
ok('histSlices 最後 N 筆 + off', (() => { const s = PfCalc.histSlices(hist, 2, '2027-01-06'); return s.hist.length === 2 && s.off === 3; })());
ok('histSlices ytd', (() => { const s = PfCalc.histSlices(hist, 'ytd', '2027-01-06'); return s.hist.length === 1 && s.off === 4; })());
ok('dailyChanges', JSON.stringify(PfCalc.dailyChanges([10, 15, 12])) === '[0,5,-3]');
ok('extremes', JSON.stringify(PfCalc.extremes([3, 9, 1, 9])) === '{"hi":1,"lo":2}');
const dd = PfCalc.drawdown([100, 120, 90, 95, 130, 110], [1000, 1000, 1000, 1000, 1000, 1000]);
ok('drawdown', dd.map(x => x.amt).join() === '0,0,-30,-25,0,-20' && near(dd[2].pct, -3) && dd[2].peakIdx === 1);
ok('worstDrawdown', (() => { const w = PfCalc.worstDrawdown(dd, 0); return w.idx === 2 && w.days === 1; })());
ok('worstDrawdown off(高點在區間前)', (() => { const w = PfCalc.worstDrawdown(dd, 4); return w.idx === 1 && w.days === 1 && w.amt === -20; })());
ok('worstDrawdown 空', PfCalc.worstDrawdown(dd, 6) === null);
const st = PfCalc.dailyStats([{ date: 'd1', chg: 10 }, { date: 'd2', chg: 20 }, { date: 'd3', chg: -5 }, { date: 'd4', chg: 0 }, { date: 'd5', chg: 7 }, { date: 'd6', chg: 8 }]);
ok('dailyStats', st.wins === 4 && st.losses === 1 && st.flat === 1 && st.best.date === 'd2' && st.worst.date === 'd3' && st.maxWinStreak === 2 && st.curStreak === 2);
ok('dailyStats 連賠', PfCalc.dailyStats([{ chg: 5 }, { chg: -1 }, { chg: -2 }]).curStreak === -2);
ok('sparkSeries', JSON.stringify(PfCalc.sparkSeries([{ prices: { x: 1 }, taiex: 100 }, { prices: { y: 2 } }, { prices: { x: 3 }, taiex: 0 }, { prices: { x: 2 }, taiex: 110 }], 'x', 2)) === '{"pts":[3,2],"taiex":[null,110]}');
const pc = PfCalc.periodChange([{ date: '2026-09-11', ret: 100, cost: 1000 }, { date: '2026-09-14', ret: 120, cost: 1000 }, { date: '2026-09-21', ret: 150, cost: 2000 }], '2026-09-14');
ok('periodChange', pc.from === '2026-09-11' && pc.chg === 50 && pc.pct === 0.025 && pc.series.length === 3);

/* ---------- TWR:加碼 / 減碼不影響報酬指數 ---------- */
const mv = [1000, 1100, 2200, 2310, 2000], cost = [800, 800, 1900, 1900, 1900];   // 第 3 天加碼 1100(mv 與 cost 同增)、第 5 天跌
const twr = PfCalc.twrIndex(mv, cost);
ok('twrIndex 起點 100', twr[0] === 100);
ok('twrIndex 漲 10%', near(twr[1], 110));
ok('twrIndex 加碼日不動', near(twr[2], 110));
ok('twrIndex 加碼後再漲 5%', near(twr[3], 115.5));
ok('twrIndex 跌', near(twr[4], 115.5 * (2000 / 2310)));
ok('twrIndex mv=0 不爆', near(PfCalc.twrIndex([0, 100, 110], [0, 100, 100])[2], 110));
// 賣出日:成本 1000 的部位以 1200 賣出(已實現 +200),市值少 1200 → 當日 0%(舊算法只扣成本會顯示 −20%)
ok('twrIndex 賣出日流出 = 賣出所得', near(PfCalc.twrIndex([2000, 800], [2000, 1000], [0, 200])[1], 100));
// 除息日:股價掉 50、股息收入 +50 → 當日 0%;沒給 divArr 則照舊顯示 −5%
ok('twrIndex 除息加回', near(PfCalc.twrIndex([1000, 950], [800, 800], [0, 0], [100, 150])[1], 100));
ok('twrIndex 不給 div 照舊', near(PfCalc.twrIndex([1000, 950], [800, 800])[1], 95));
// 舊資料某日缺 real / div(null)→ 該日 Δ 當 0,不會爆一大筆
ok('twrIndex real/div 缺欄不跳', near(PfCalc.twrIndex([1000, 1100, 1100], [800, 800, 800], [null, 300, 300], [null, 100, 100])[2], 110));
const B = PfCalc.benchLines(mv, [0, 200, 220, 220, 210], [50, 55, 66, 66, 60], cost);
ok('benchLines firstT 跳過無大盤', B.firstT === 1);
ok('benchLines 我的組合走 TWR(加碼日 0%)', near(B.me[0], 0) && near(B.me[1], 0) && near(B.me[2], 5));
ok('benchLines 大盤 / 台積電正規化', near(B.tw[1], 10) && near(B.tsmc[1], 20));
ok('benchLines 沒 cost 退回市值正規化', near(PfCalc.benchLines(mv, [0, 200, 220, 220, 210], null).me[1], 100));
ok('benchLines 大盤不足 2 點 → null', PfCalc.benchLines([1, 2], [0, 5], null) === null);

// stockSearch:代號前綴優先、名稱包含其次、limit / total、空字串
const POOL = [['0050', '元大台灣50', 'TW'], ['2330', '台積電', 'TW'], ['2303', '聯電', 'TW'], ['00981A', '統一台股增長主動式', 'TW'], ['6488', '環球晶', 'OTC'], ['2317', '鴻海', 'TW']];
const S1 = PfCalc.stockSearch(POOL, '23');
ok('stockSearch 前綴 23 → 3 檔', S1.total === 3 && S1.items.every(s => s[0].startsWith('23')));
ok('stockSearch 名稱包含', PfCalc.stockSearch(POOL, '台積').items[0][0] === '2330');
ok('stockSearch 代號優先於名稱', PfCalc.stockSearch(POOL, '0')[0] === undefined && PfCalc.stockSearch(POOL, '0').items[0][0] === '0050');
ok('stockSearch 小寫 a 也對到 00981A', PfCalc.stockSearch(POOL, '00981a').total === 1);
ok('stockSearch limit / total', PfCalc.stockSearch(POOL, '2', 2).items.length === 2 && PfCalc.stockSearch(POOL, '2', 2).total === 3);
ok('stockSearch 空字串 → 空', PfCalc.stockSearch(POOL, '  ').total === 0 && PfCalc.stockSearch(null, 'x').total === 0);

/* ---------- 今日損益 + 除息調整 ---------- */
const rows = [{ code: 'a', price: 110, prevClose: 100, lots: 1 }, { code: 'b', price: 50, prevClose: 0, lots: 2 }];
const tc = PfCalc.todayChange(rows, { mv: 999 }, 210000, '2026-09-22');
ok('todayChange 昨收路徑', tc.chg === 10000 && tc.base === 100000 && tc.missing === 1 && tc.exDivCount === 0);
ok('todayChange history 退路', PfCalc.todayChange([{ code: 'b', price: 50, lots: 2 }], { mv: 90000 }, 100000, '2026-09-22').chg === 10000);
ok('todayChange null', PfCalc.todayChange([{ code: 'b', price: 50, lots: 2 }], null, 100000, '2026-09-22') === null);
const ex = PfCalc.todayChange([{ code: 'a', price: 96, prevClose: 100, lots: 1, exDiv: { date: '2026-09-22', amount: 5 } }], null, 0, '2026-09-22');
ok('除息日:昨收扣股息,96 vs 95 = +1000', ex.chg === 1000 && ex.exDivCount === 1);
const exOld = PfCalc.todayChange([{ code: 'a', price: 96, prevClose: 100, lots: 1, exDiv: { date: '2026-09-21', amount: 5 } }], null, 0, '2026-09-22');
ok('非今日的 exDiv 不調整', exOld.chg === -4000 && exOld.exDivCount === 0);

/* ---------- 存檔前合併 Action 寫的市價(防止前端用舊資料蓋掉) ---------- */
{
  const local = { priceUpdated: '2026-10-01 15:08', title: '新標題', history: [{ date: '2026-10-01' }],
    holdings: [{ code: '2330', price: 2510, lots: 3, priceTime: '2026-10-01 15:08' }, { code: '0050', price: 0, lots: 1 }] };
  const remote = { priceUpdated: '2026-10-02 10:02', title: '舊標題', history: [{ date: '2026-10-01' }, { date: '2026-10-02' }], alerts: { x: 1 },
    holdings: [{ code: '2330', price: 2500, lots: 2, priceTime: '2026-10-02 10:02', prevClose: 2510, exDiv: { date: '2026-10-02', amount: 5 } }, { code: '00878', price: 20 }] };
  const n = PfCalc.mergeServerFields(local, remote);
  const h = local.holdings[0];
  ok('合併:較新的市價 / 時間 / 昨收 / 除息帶進來', n === 1 && h.price === 2500 && h.priceTime === '2026-10-02 10:02' && h.prevClose === 2510 && h.exDiv.amount === 5);
  ok('合併:使用者編輯(張數 / 標題)保留', h.lots === 3 && local.title === '新標題');
  ok('合併:priceUpdated / history / alerts 用 remote', local.priceUpdated === '2026-10-02 10:02' && local.history.length === 2 && local.alerts.x === 1);
  ok('合併:代號對不上的持股不動', local.holdings[1].price === 0 && local.holdings.length === 2);
  const l2 = { priceUpdated: '2026-10-02 10:05', holdings: [{ code: '2330', price: 2520 }] };
  ok('合併:remote 沒比較新 → 不動', PfCalc.mergeServerFields(l2, remote) === 0 && l2.holdings[0].price === 2520);
}

/* ---------- 網頁自動補觸發:超過 15 分才送、同一 10 分區段只送一次 ---------- */
{
  const S = PfCalc.autoTriggerSlot;
  ok('補觸發:股價 8 分鐘前 → 不送', S('2026-10-02 11:30', '2026-10-02 11:38', null) === null);
  ok('補觸發:剛好 15 分 → 不送', S('2026-10-02 11:20', '2026-10-02 11:35', null) === null);
  ok('補觸發:16 分 → 送,記區段', S('2026-10-02 11:20', '2026-10-02 11:36', null) === '2026-10-02 11:3');
  ok('補觸發:同區段下拉第二次 → 不送', S('2026-10-02 11:20', '2026-10-02 11:39', '2026-10-02 11:3') === null);
  ok('補觸發:下一區段還是舊 → 再送一次', S('2026-10-02 11:20', '2026-10-02 11:40', '2026-10-02 11:3') === '2026-10-02 11:4');
  ok('補觸發:昨天的價(跨日) → 送', S('2026-10-01 13:50', '2026-10-02 09:12', null) === '2026-10-02 09:1');
  ok('補觸發:從沒更新過 → 送', S('', '2026-10-02 09:12', null) === '2026-10-02 09:1');
}

/* ---------- 今日損益:當天新買的用買進成本 ---------- */
{
  const T = '2026-10-02';
  // 2026-10-02 實況:00904 今天新買 5 張 @44,現價 44.04、昨收 43.43;前一天快照沒 lots、prices 沒 00904
  const rows = [{ code: '00904', price: 44.04, prevClose: 43.43, lots: 5, cost: 44 }, { code: '0050', price: 112.85, prevClose: 112.9, lots: 1, cost: 102.91 }];
  const old = { date: '2026-10-01', mv: 1, prices: { '0050': 112.9 } };
  const r1 = PfCalc.todayChange(rows, old, 0, T);
  ok('新買整檔:用買進價 44 不用昨收 → +200 −50', r1.chg === 200 - 50 && r1.newCount === 1 && r1.base === 220000 + 112900);
  // 有 lots 快照:0050 1 張 @100 加碼 1 張 → 均價 105 → 買進價 110;現價 112
  const add = PfCalc.todayChange([{ code: '0050', price: 112, prevClose: 111, lots: 2, cost: 105 }], { date: '2026-10-01', lots: { '0050': 1 }, costs: { '0050': 100 } }, 0, T);
  ok('加碼:舊 1 張用昨收(+1000)、新 1 張用推回買進價 110(+2000)', add.chg === 3000 && add.base === 111000 + 110000);
  // 減碼不影響:快照 10 張、今天 5 張 → 5 張全用昨收
  const sell = PfCalc.todayChange([{ code: '00891', price: 37.95, prevClose: 37.82, lots: 5, cost: 34.29 }], { lots: { '00891': 10 } }, 0, T);
  ok('減碼:剩下的張數照昨收', sell.chg === 650 && sell.newCount === 0);
  // 沒快照、prices 也沒有(很舊的 history)→ 照舊全用昨收
  ok('沒任何快照 → 照舊', PfCalc.todayChange(rows, { mv: 1 }, 0, T).chg === Math.round(0.61 * 5000) - 50);
  // 新買但 Yahoo 還沒給昨收 → 仍可用買進價算
  const noPc = PfCalc.todayChange([{ code: 'X', price: 10.5, lots: 1, cost: 10 }], { lots: {} }, 0, T);
  ok('新買沒昨收也算得出', noPc && noPc.chg === 500 && noPc.missing === 0);
}

let fail = 0;
for (const [n, c, info] of R) { console.log((c ? 'PASS' : 'FAIL') + '  ' + n + (c || !info ? '' : '  → ' + info)); if (!c) fail++; }
process.exit(fail ? 1 : 0);
