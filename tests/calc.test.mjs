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

let fail = 0;
for (const [n, c, info] of R) { console.log((c ? 'PASS' : 'FAIL') + '  ' + n + (c || !info ? '' : '  → ' + info)); if (!c) fail++; }
process.exit(fail ? 1 : 0);
