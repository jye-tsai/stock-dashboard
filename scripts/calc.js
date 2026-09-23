/* 胖虎的小財庫 — 純計算共用模組(UMD)
   前端 index.html:<script src="scripts/calc.js"> → window.PfCalc
   GitHub Action scripts/update-prices.mjs:createRequire(import.meta.url)('./calc.js')
   兩塊:
   (1) 損益:成本 / 市值 / 賣出成本 / 未實現 / 總報酬 —— 前端畫面與 Action 寫 history 共用,改費率只改這裡
   (2) 時序:history 切片、日變動、極值、回撤、對比線、每日統計、今日損益、sparkline —— 前端圖表用,純函式方便在 Node 測
   語法刻意停在 ES5(var / function),前後端都零轉譯直接吃。 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.PfCalc = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  var DEFAULT_TAX = 0.003;   // 沒在 fees.taxRates 列的類別視為個股稅率

  /* ================= (1) 損益 ================= */

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

  /* ================= (2) 時序 ================= */

  function isWeekendYmd(ymd) {
    var m = String(ymd).split('-');
    var dow = new Date(+m[0], +m[1] - 1, +m[2]).getDay();
    return dow === 0 || dow === 6;
  }

  // history → { full:全史(去週末;有大盤資料後,沒 taiex 的日子視為休市也去掉), hist:區間, off:區間在全史的起點 }
  // range:0 = 全部、N = 最後 N 筆(交易日)、'ytd' = 今年(以 todayYmd 的年份)
  function histSlices(history, range, todayYmd) {
    var all = (Array.isArray(history) ? history : []).filter(function (p) { return p && p.date; });
    var hasTaiex = all.some(function (p) { return Number(p.taiex) > 0; });
    var full = all.filter(function (p) { return !isWeekendYmd(p.date) && (!hasTaiex || Number(p.taiex) > 0); });
    var hist = full;
    if (range === 'ytd') { var y0 = String(todayYmd || '').slice(0, 4) + '-01-01'; hist = full.filter(function (p) { return String(p.date) >= y0; }); }
    else if (range > 0) hist = full.slice(-range);
    return { full: full, hist: hist, off: full.length - hist.length };
  }

  // 每日變動(第一筆沒有前值 → 0)
  function dailyChanges(arr) { return arr.map(function (v, i) { return i === 0 ? 0 : v - arr[i - 1]; }); }

  // 極值 index;全相等時 hi === lo
  function extremes(arr) {
    var hi = 0, lo = 0;
    arr.forEach(function (v, i) { if (v > arr[hi]) hi = i; if (v < arr[lo]) lo = i; });
    return { hi: hi, lo: lo };
  }

  // 回撤:ret 距「截至當日歷史最高」的差(金額)與佔當日成本 %;每筆 { amt, pct, peakIdx }
  function drawdown(retArr, costArr) {
    var peak = -Infinity, peakIdx = 0;
    return retArr.map(function (r, i) {
      if (r > peak) { peak = r; peakIdx = i; }
      var amt = r - peak;
      return { amt: amt, pct: costArr[i] ? amt / costArr[i] * 100 : 0, peakIdx: peakIdx };
    });
  }

  // 區間(從 off 起)內最深回撤:{ idx, amt, pct, peakIdx, days(高點→谷底交易日數), dd(區間切片) };空區間 null
  function worstDrawdown(ddAll, off) {
    var dd = ddAll.slice(off);
    if (!dd.length) return null;
    var worst = 0;
    dd.forEach(function (x, i) { if (x.pct < dd[worst].pct) worst = i; });
    var w = dd[worst];
    return { idx: worst, amt: w.amt, pct: w.pct, peakIdx: w.peakIdx, days: worst + off - w.peakIdx, dd: dd };
  }

  // 時間加權報酬指數(TWR,起點 100):日報酬 = (Δ市值 − Δ成本) / 昨日市值,逐日連乘。
  // 加碼 / 減碼當天 Δ市值 ≈ Δ成本,指數不動 —— 對比大盤才不會被「錢進來」誤判成「贏了」
  // 時間加權報酬指數(起點 100)。每日報酬 =(市值變化 − 資金流入 + 股息入袋)÷ 前日市值
  //   資金流入 = Δ成本 − Δ已實現:買進日 = 買進成本;賣出日 = −(移除成本 + 已實現損益)= −賣出所得(只用 Δ成本會把該筆已實現當成當日漲跌)
  //   股息入袋 = Δ股息收入:除息日股價掉、市值少,但現金進口袋,加回才不會把除息當成賠(realArr / divArr 可不給 = 舊行為)
  //   某日缺 real / div 欄(舊資料)→ 該日 Δ 視為 0,不會因 null→數字跳一大筆
  function twrIndex(mvArr, costArr, realArr, divArr) {
    var out = [100];
    var delta = function (arr, i) { return arr && arr[i] != null && arr[i - 1] != null ? (Number(arr[i]) || 0) - (Number(arr[i - 1]) || 0) : 0; };
    for (var i = 1; i < mvArr.length; i++) {
      var prev = mvArr[i - 1] || 0;
      var flow = ((costArr && costArr[i]) || 0) - ((costArr && costArr[i - 1]) || 0) - delta(realArr, i);
      var r = prev > 0 ? (mvArr[i] - prev - flow + delta(divArr, i)) / prev : 0;
      out.push(out[i - 1] * (1 + r));
    }
    return out;
  }

  // 對比線:以「第一個有大盤資料的點」為 0% 正規化;{ firstT, me, tw, tsmc|null };大盤資料不足 2 點 → null
  // 有給 costArr 就用 TWR 指數當「我的組合」(加碼不失真;再給 realArr / divArr 則賣出日、除息日也不失真);沒給退回市值正規化(舊行為)
  function benchLines(mvArr, taiexArr, tsmcArr, costArr, realArr, divArr) {
    var firstT = -1, count = 0;
    for (var i = 0; i < taiexArr.length; i++) if (taiexArr[i] > 0) { if (firstT < 0) firstT = i; count++; }
    if (firstT < 0 || count < 2) return null;
    var meArr = costArr ? twrIndex(mvArr, costArr, realArr, divArr) : mvArr;
    var baseM = meArr[firstT] || 1, baseT = taiexArr[firstT] || 1, baseS = (tsmcArr && tsmcArr[firstT]) || 0;
    var norm = function (arr, base) { return arr.slice(firstT).map(function (v) { return v > 0 ? (v / base - 1) * 100 : null; }); };
    return { firstT: firstT, me: norm(meArr, baseM), tw: norm(taiexArr, baseT), tsmc: baseS > 0 ? norm(tsmcArr, baseS) : null };
  }

  // 每日損益統計(熱圖旁的統計卡):days = [{ date, chg }]
  function dailyStats(days) {
    var wins = days.filter(function (d) { return d.chg > 0; }), losses = days.filter(function (d) { return d.chg < 0; });
    var sum = function (a) { return a.reduce(function (s, d) { return s + d.chg; }, 0); };
    var best = null, worst = null;
    days.forEach(function (d) { if (!best || d.chg > best.chg) best = d; if (!worst || d.chg < worst.chg) worst = d; });
    var streak = function (positive) {
      var max = 0, cur = 0;
      days.forEach(function (d) { if (positive ? d.chg > 0 : d.chg < 0) { cur++; if (cur > max) max = cur; } else cur = 0; });
      return max;
    };
    var curStreak = 0, curSign = 0;                                 // 從最後一天往回數同號連續天數;正 = 連賺、負 = 連賠
    for (var i = days.length - 1; i >= 0; i--) {
      var s = days[i].chg > 0 ? 1 : days[i].chg < 0 ? -1 : 0;
      if (!s) break;
      if (!curSign) curSign = s;
      if (s !== curSign) break;
      curStreak++;
    }
    return {
      n: days.length, wins: wins.length, losses: losses.length, flat: days.length - wins.length - losses.length,
      winRate: days.length ? wins.length / days.length : 0,
      avgWin: wins.length ? sum(wins) / wins.length : 0, avgLoss: losses.length ? sum(losses) / losses.length : 0,
      best: best, worst: worst, maxWinStreak: streak(true), maxLossStreak: streak(false), curStreak: curStreak * curSign
    };
  }

  // 今日損益(Hero):各檔 prevClose 加總;沒有任何昨收就退回「總市值 − history 前一交易日市值」;都沒有 → null
  // 除息:holdings[].exDiv = { date, amount }(Action 寫入),date 是今天就把昨收扣掉股息 —— 除息造成的價差不是虧損
  function todayChange(rows, prevDay, totalMv, todayYmd) {
    var exOf = function (r) { return r.exDiv && String(r.exDiv.date) === String(todayYmd) && r.exDiv.amount > 0 ? r.exDiv.amount : 0; };
    var pc = rows.filter(function (r) { return r.prevClose > 0 && r.price > 0 && r.lots > 0; });
    if (pc.length) {
      var chg = 0, base = 0, exCount = 0;
      pc.forEach(function (r) {
        var ex = exOf(r), ref = r.prevClose - ex;
        if (ex) exCount++;
        chg += Math.round((r.price - ref) * 1000 * r.lots); base += Math.round(ref * 1000 * r.lots);
      });
      var held = rows.filter(function (r) { return r.price > 0 && r.lots > 0; }).length;
      return { chg: chg, base: base, pct: base ? chg / base : 0, missing: held - pc.length, exDivCount: exCount };
    }
    if (prevDay && typeof prevDay.mv === 'number' && prevDay.mv > 0) {
      return { chg: totalMv - prevDay.mv, base: prevDay.mv, pct: (totalMv - prevDay.mv) / prevDay.mv, missing: 0, exDivCount: 0 };
    }
    return null;
  }

  // 股票池搜尋(持股表單代號欄):代號「前綴」優先(2 → 所有 2 開頭;23 → 23 開頭),其次名稱「包含」(台積 → 2330)
  // list = [[code, name, market], ...];回傳 { items: 最多 limit 筆, total: 全部符合數 },大小寫不分
  function stockSearch(list, q, limit) {
    q = String(q == null ? '' : q).trim().toUpperCase(); limit = limit || 8;
    if (!q) return { items: [], total: 0 };
    var byCode = [], byName = [];
    (list || []).forEach(function (s) {
      if (!s) return;
      if (String(s[0]).toUpperCase().indexOf(q) === 0) byCode.push(s);
      else if (String(s[1] || '').toUpperCase().indexOf(q) >= 0) byName.push(s);
    });
    var all = byCode.concat(byName);
    return { items: all.slice(0, limit), total: all.length };
  }

  // sparkline:近 n 筆有該檔價的 history → { pts:[價], taiex:[同日大盤|null] };不足 2 點 → null
  function sparkSeries(history, code, n) {
    var out = [];
    (history || []).forEach(function (h) {
      if (h && h.prices && h.prices[code] > 0) out.push({ p: h.prices[code], t: Number(h.taiex) > 0 ? Number(h.taiex) : null });
    });
    out = out.slice(-(n || 30));
    if (out.length < 2) return null;
    return { pts: out.map(function (o) { return o.p; }), taiex: out.map(function (o) { return o.t; }) };
  }

  // 一段期間的總報酬變化(分享卡「本週 / 本月」):base = 期間開始前最後一筆(沒有就用期間第一筆),end = 全史最後一筆;
  // pct 以 end 當日成本為分母;series 從 base 到 end(畫走勢線用);期間內沒資料或只有一筆 → null
  function periodChange(full, startYmd) {
    if (!full || full.length < 2) return null;
    var startIdx = -1;
    for (var i = 0; i < full.length; i++) if (String(full[i].date) >= String(startYmd)) { startIdx = i; break; }
    if (startIdx < 0) return null;
    var baseIdx = startIdx > 0 ? startIdx - 1 : 0;
    if (baseIdx >= full.length - 1) return null;
    var base = full[baseIdx], end = full[full.length - 1];
    var chg = (Number(end.ret) || 0) - (Number(base.ret) || 0), cost = Number(end.cost) || 0;
    return { chg: chg, pct: cost ? chg / cost : 0, from: String(base.date), to: String(end.date), series: full.slice(baseIdx) };
  }

  return {
    DEFAULT_TAX: DEFAULT_TAX,
    holdingAmounts: holdingAmounts, compute: compute, totals: totals,
    isWeekendYmd: isWeekendYmd, histSlices: histSlices, dailyChanges: dailyChanges, extremes: extremes,
    drawdown: drawdown, worstDrawdown: worstDrawdown, twrIndex: twrIndex, benchLines: benchLines, dailyStats: dailyStats,
    todayChange: todayChange, sparkSeries: sparkSeries, periodChange: periodChange, stockSearch: stockSearch
  };
});
