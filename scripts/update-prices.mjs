// 在 GitHub Action 的伺服器端執行:抓台股「即時價」→ 寫回 data.json。
// 即時來源:Yahoo(regularMarketPrice)優先 → 證交所 MIS(z/pz)補。
// 時間戳:只要這次有抓到即時價,就更新 priceUpdated 與該檔 priceTime(就算價格沒變),
//         所以「時間有沒有前進」可用來判斷即時更新是否真的在運作。
// 防還原:只有即時價能覆蓋現有價格;收盤價(OpenAPI)只用來初始化「完全沒有價格」的新標的。
import fs from 'node:fs';

const FILE = process.env.DATA_FILE || 'data.json';

function readData() {
  return JSON.parse(fs.readFileSync(FILE, 'utf8'));
}

// 計算總成本 / 總市值 / 總報酬(與前端 compute 邏輯一致)
function computeTotals(data) {
  const f = data.fees || {};
  const feeRate = f.feeRate || 0, feeDiscount = f.feeDiscount || 0, taxRates = f.taxRates || {};
  let cost = 0, mv = 0, unreal = 0;
  for (const h of (data.holdings || [])) {
    const c = Math.round((h.cost || 0) * 1000 * (h.lots || 0));
    const m = Math.round((h.price || 0) * 1000 * (h.lots || 0));
    const taxRate = taxRates[h.type] ?? 0.003;
    const sellCost = Math.round(m * (taxRate + feeRate * feeDiscount));
    cost += c; mv += m; unreal += m - c - sellCost;
  }
  const realized = data['已實現損益'] || 0, dividend = data['股息收入'] || 0;
  return { cost, mv, unreal, realized, dividend, totalReturn: unreal + realized + dividend };
}

// 台北時間戳(直接 UTC+8 手算,不依賴 runner 時區資料庫;台灣無日光節約,固定 +8),例:2026-06-15 12:16
function taipeiStamp() {
  const d = new Date(Date.now() + 8 * 3600 * 1000);
  const z = n => String(n).padStart(2, '0');
  return `${d.getUTCFullYear()}-${z(d.getUTCMonth() + 1)}-${z(d.getUTCDate())} ${z(d.getUTCHours())}:${z(d.getUTCMinutes())}`;
}

async function fetchJson(url, ms = 12000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), ms);
  try {
    const r = await fetch(url, {
      signal: ctrl.signal,
      headers: { 'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json' }
    });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return await r.json();
  } finally { clearTimeout(timer); }
}

// 即時來源 1:Yahoo 財經(regularMarketPrice = 即時/最後成交價),先試上市 .TW 再試上櫃 .TWO
async function fromYahoo(codes) {
  const live = {};
  for (const c of codes) {
    for (const suf of ['.TW', '.TWO']) {
      try {
        const j = await fetchJson(`https://query1.finance.yahoo.com/v8/finance/chart/${c}${suf}?interval=1d&range=1d`);
        const m = j && j.chart && j.chart.result && j.chart.result[0] && j.chart.result[0].meta;
        const p = m && m.regularMarketPrice;
        if (p > 0) { live[c] = p; break; }
      } catch (e) {}
    }
  }
  return live;
}

// 即時來源 2:證交所 MIS(z=成交 → pz=最後揭示;不取昨收 y,以免用舊價倒退)
async function fromMis(codes) {
  const live = {};
  if (!codes.length) return live;
  const q = codes.flatMap(c => [`tse_${c}.tw`, `otc_${c}.tw`]).join('|');
  const url = `https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=${q}&json=1&delay=0&_=${Date.now()}`;
  const j = await fetchJson(url, 15000);
  (j.msgArray || []).forEach(s => {
    const p = parseFloat(s.z) || parseFloat(s.pz);
    if (p > 0) live[s.c] = p;
  });
  return live;
}

// 收盤價(只用來初始化「完全沒有價格」的新標的)
async function fromTwse() {
  const list = await fetchJson('https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL', 20000);
  const map = {};
  (list || []).forEach(s => { const p = parseFloat(s.ClosingPrice); if (p > 0) map[s.Code] = p; });
  return map;
}
async function fromTpex() {
  const list = await fetchJson('https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes', 20000);
  const map = {};
  (list || []).forEach(s => {
    const code = s.SecuritiesCompanyCode || s.Code || s.code;
    const p = parseFloat(s.Close || s.ClosingPrice || s.close);
    if (code && p > 0) map[code] = p;
  });
  return map;
}

async function main() {
  // 週末不動作(台北星期六/日);排程設成每天跑,由這裡擋掉非交易日,避免漏掉週五又不在假日亂寫
  const tpeDow = new Date(Date.now() + 8 * 3600 * 1000).getUTCDay(); // 0=日 .. 6=六(台北)
  if (tpeDow === 0 || tpeDow === 6) { console.log('週末(台北),不更新'); return; }

  const data = readData();
  const holdings = data.holdings || [];
  const codes = [...new Set(holdings.map(h => h.code).filter(Boolean))];
  if (!codes.length) { console.log('沒有可查詢的代號,結束。'); return; }

  const stamp = taipeiStamp();
  console.log(`時間 ${stamp}`);

  // 即時價:Yahoo 優先,MIS 補 Yahoo 沒抓到的
  const live = {};
  try {
    const y = await fromYahoo(codes);
    Object.assign(live, y);
    console.log(`Yahoo 即時: 取得 ${Object.keys(y).length}/${codes.length}`);
  } catch (e) { console.log(`Yahoo 失敗(${e.message})`); }

  const misCodes = codes.filter(c => !(live[c] > 0));
  if (misCodes.length) {
    try {
      const m = await fromMis(misCodes);
      Object.assign(live, m);
      console.log(`MIS 即時: 補抓 ${Object.keys(m).length}/${misCodes.length}`);
    } catch (e) { console.log(`MIS 失敗(${e.message})`); }
  }

  // 只有「完全沒有價格、即時也沒抓到」的新標的,才用收盤價初始化
  let eod = {};
  const needInit = holdings.filter(h => h.code && !(h.price > 0) && !(live[h.code] > 0)).map(h => h.code);
  if (needInit.length) {
    try { eod = await fromTwse(); } catch (e) { console.log(`證交所收盤 失敗(${e.message})`); }
    if (needInit.some(c => !(eod[c] > 0))) {
      try { const t = await fromTpex(); for (const k in t) if (!(eod[k] > 0)) eod[k] = t[k]; } catch (e) {}
    }
  }

  let changed = 0, liveHit = 0;
  for (const h of holdings) {
    if (!h.code) continue;
    if (live[h.code] > 0) {
      liveHit++;
      h.priceTime = stamp;                                   // 最後抓到即時價的時間(有抓到就更新)
      if (h.price !== live[h.code]) { h.price = live[h.code]; changed++; }
    } else if (!(h.price > 0) && eod[h.code] > 0) {
      h.price = eod[h.code]; h.priceTime = stamp; changed++; // 初始化新標的
    }
  }
  const noLive = codes.filter(c => !(live[c] > 0) && !(eod[c] > 0));
  if (noLive.length) console.log('即時抓不到:', noLive.join('、'));

  if (liveHit > 0 || changed > 0) {
    data.updated = stamp.slice(0, 10);
    data.priceUpdated = stamp;     // 最後成功抓到即時價的時間 → 判斷是否真的在即時更新

    // 記錄每日資產走勢(同一天只留最新一筆,供前端畫淨值曲線)
    const tot = computeTotals(data);
    const day = stamp.slice(0, 10);
    data.history = Array.isArray(data.history) ? data.history : [];
    const entry = { date: day, mv: tot.mv, cost: tot.cost, un: tot.unreal, real: tot.realized, div: tot.dividend, ret: tot.totalReturn };
    const last = data.history[data.history.length - 1];
    if (last && last.date === day) data.history[data.history.length - 1] = entry;
    else data.history.push(entry);
    if (data.history.length > 400) data.history = data.history.slice(-400);

    fs.writeFileSync(FILE, JSON.stringify(data, null, 2));
    console.log(`寫回:即時 ${liveHit} 檔、價格變動 ${changed} 檔;總市值 ${tot.mv}、總報酬 ${tot.totalReturn}(${stamp})`);
  } else {
    console.log('完全沒抓到即時價,維持原狀不寫檔(時間戳不前進=即時來源不通)');
  }
}

main().catch(e => { console.error('執行失敗:', e); process.exit(1); });
