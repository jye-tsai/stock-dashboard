// 在 GitHub Action 的伺服器端執行:抓台股市價 → 寫回 data.json。
// 原則(避免價格來回跳/被還原):
//   - 即時成交價(MIS 的 z/pz)優先,而且「只有即時價能覆蓋現有價格」。
//   - 收盤價/昨收只用來「補目前沒有價格的新標的」或「收盤後結算」。
//   - 盤中若某檔抓不到即時價,就維持原價不動,絕不用較舊的收盤/昨收蓋掉。
import fs from 'node:fs';

const FILE = process.env.DATA_FILE || 'data.json';

function readData() {
  return JSON.parse(fs.readFileSync(FILE, 'utf8'));
}

// 台北時間:時間戳 + 是否盤中(週一~週五 09:00–13:30)
function taipei() {
  const p = Object.fromEntries(
    new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Taipei', hour12: false,
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', weekday: 'short'
    }).formatToParts(new Date()).map(x => [x.type, x.value])
  );
  const stamp = `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}`;
  const mins = (+p.hour) * 60 + (+p.minute);
  const weekday = !['Sat', 'Sun'].includes(p.weekday);
  const marketOpen = weekday && mins >= 9 * 60 && mins <= 13 * 60 + 30;
  return { stamp, marketOpen };
}

async function fetchJson(url, ms = 20000) {
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

// MIS 即時報價:live = 即時成交(z 或 pz);prevClose = 昨收(y)
async function fromMis(codes) {
  const out = { live: {}, prevClose: {} };
  if (!codes.length) return out;
  const q = codes.flatMap(c => [`tse_${c}.tw`, `otc_${c}.tw`]).join('|');
  const url = `https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=${q}&json=1&delay=0&_=${Date.now()}`;
  const j = await fetchJson(url);
  (j.msgArray || []).forEach(s => {
    const live = parseFloat(s.z) || parseFloat(s.pz);   // 即時成交 / 最後揭示
    const y = parseFloat(s.y);                          // 昨收
    if (live > 0) out.live[s.c] = live;
    if (y > 0) out.prevClose[s.c] = y;
  });
  return out;
}

// 證交所 OpenAPI 上市每日收盤
async function fromTwse() {
  const list = await fetchJson('https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL');
  const map = {};
  (list || []).forEach(s => { const p = parseFloat(s.ClosingPrice); if (p > 0) map[s.Code] = p; });
  return map;
}

// 櫃買中心 OpenAPI 上櫃每日收盤
async function fromTpex() {
  const list = await fetchJson('https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes');
  const map = {};
  (list || []).forEach(s => {
    const code = s.SecuritiesCompanyCode || s.Code || s.code;
    const p = parseFloat(s.Close || s.ClosingPrice || s.close);
    if (code && p > 0) map[code] = p;
  });
  return map;
}

async function main() {
  const data = readData();
  const holdings = data.holdings || [];
  const codes = [...new Set(holdings.map(h => h.code).filter(Boolean))];
  if (!codes.length) { console.log('沒有可查詢的代號,結束。'); return; }

  const { stamp, marketOpen } = taipei();
  console.log(`時間 ${stamp}(${marketOpen ? '盤中' : '非盤中'})`);

  // 1) 即時成交價(只有它能覆蓋現有價格)
  let live = {}, prevClose = {};
  try {
    const r = await fromMis(codes);
    live = r.live; prevClose = r.prevClose;
    console.log(`MIS 即時: 取得 ${Object.keys(live).length}/${codes.length}`);
  } catch (e) { console.log(`MIS 失敗(${e.message})`); }

  // 2) 收盤價:只在「沒有即時價、且(非盤中要結算 或 目前完全沒有價格要初始化)」時才抓
  const eodNeeded = h => h.code && !(live[h.code] > 0) && (!marketOpen || !(h.price > 0));
  let eod = {};
  if (holdings.some(eodNeeded)) {
    try { eod = await fromTwse(); console.log(`證交所收盤: ${Object.keys(eod).length} 檔`); }
    catch (e) { console.log(`證交所收盤 失敗(${e.message})`); }
    if (holdings.some(h => eodNeeded(h) && !(eod[h.code] > 0))) {
      try { const t = await fromTpex(); for (const k in t) if (!(eod[k] > 0)) eod[k] = t[k]; console.log('已併入櫃買收盤'); }
      catch (e) { console.log(`櫃買收盤 失敗(${e.message})`); }
    }
  }

  // 3) 套用:即時價優先;無即時價時,僅「非盤中」或「該檔尚無價格」才用收盤/昨收
  let changed = 0;
  const miss = [];
  for (const h of holdings) {
    if (!h.code) continue;
    let p = 0, kind = '';
    if (live[h.code] > 0) { p = live[h.code]; kind = '即時'; }
    else if (!marketOpen || !(h.price > 0)) {
      const fb = eod[h.code] > 0 ? eod[h.code] : (prevClose[h.code] > 0 ? prevClose[h.code] : 0);
      if (fb > 0) { p = fb; kind = marketOpen ? '初始' : '收盤'; }
    }
    if (!(p > 0)) { if (!(h.price > 0)) miss.push(h.code); continue; }
    if (h.price !== p) { h.price = p; h.priceTime = stamp; changed++; console.log(`${h.code} → ${p}(${kind})`); }
  }
  if (miss.length) console.log('查不到:', miss.join('、'));

  if (changed > 0) {
    data.updated = stamp.slice(0, 10);
    data.priceUpdated = stamp;
    fs.writeFileSync(FILE, JSON.stringify(data, null, 2));
    console.log(`已更新 ${changed} 檔市價(${stamp}),寫回 ${FILE}。`);
  } else {
    console.log('市價無變動,不寫檔。');
  }
}

main().catch(e => { console.error('執行失敗:', e); process.exit(1); });
