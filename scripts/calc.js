/* 胖虎的小財庫 — 損益計算共用模組(UMD)
   前端 index.html:<script src="scripts/calc.js"> → window.PfCalc
   GitHub Action scripts/update-prices.mjs:createRequire(import.meta.url)('./calc.js')
   改手續費 / 證交稅 / 四捨五入規則只改這一份,兩邊一定一致(history 的 un / ret 才對得上畫面)。
   語法刻意停在 ES5(var / function),前後端都零轉譯直接吃。 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.PfCalc = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  var DEFAULT_TAX = 0.003;   // 沒在 fees.taxRates 列的類別視為個股稅率

  // 單檔:成本、市值、賣出成本(證交稅 + 手續費 × 折數)、未實現損益(已扣賣出成本)
  // 金額都以「元」四捨五入到整數;lots 為張(1 張 = 1000 股,可小數 = 零股)
  function holdingAmounts(h, fees) {
    var f = fees || {};
    var feeRate = f.feeRate || 0, feeDiscount = f.feeDiscount || 0, taxRates = f.taxRates || {};
    var lots = h.lots || 0;
    var costAmt = Math.round((h.cost || 0) * 1000 * lots);
    var mv = Math.round((h.price || 0) * 1000 * lots);
    var taxRate = taxRates[h.type] != null ? taxRates[h.type] : DEFAULT_TAX;
    var sellCost = Math.round(mv * (taxRate + feeRate * feeDiscount));
    return { costAmt: costAmt, mv: mv, sellCost: sellCost, unrealized: mv - costAmt - sellCost };
  }

  // 全部持股:每檔 rows(原欄位 + 金額 + 報酬率 + 占比)與合計 t
  function compute(d) {
    var holdings = (d && d.holdings) || [];
    var t = { costAmt: 0, mv: 0, sellCost: 0, unrealized: 0 };
    var rows = holdings.map(function (h) {
      var a = holdingAmounts(h, d && d.fees);
      t.costAmt += a.costAmt; t.mv += a.mv; t.sellCost += a.sellCost; t.unrealized += a.unrealized;
      return Object.assign({}, h, a, { plRatio: a.costAmt ? a.unrealized / a.costAmt : 0 });
    });
    rows.forEach(function (r) {
      r.costPctOfTotal = t.costAmt ? r.costAmt / t.costAmt : 0;
      r.mvPctOfTotal = t.mv ? r.mv / t.mv : 0;
    });
    return { rows: rows, t: t };
  }

  // 總報酬 = 未實現 + 已實現 + 股息;欄位名對齊 history 一筆(cost / mv / unreal / realized / dividend / totalReturn)
  function totals(d) {
    var t = compute(d).t;
    var realized = (d && d['已實現損益']) || 0, dividend = (d && d['股息收入']) || 0;
    return { cost: t.costAmt, mv: t.mv, unreal: t.unrealized, realized: realized, dividend: dividend, totalReturn: t.unrealized + realized + dividend };
  }

  return { holdingAmounts: holdingAmounts, compute: compute, totals: totals, DEFAULT_TAX: DEFAULT_TAX };
});
