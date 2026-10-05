// 即時價來源取捨(純函式,tests/quote.test.mjs 直接測;update-prices.mjs 呼叫)
// 證交所 MIS 是真即時(約 5 秒);Yahoo 台股報價延遲約 20 分鐘(2026-10-05 實測:09:20 才拿到當天價)。
// 所以 MIS 優先、Yahoo 補 MIS 沒拿到的;Yahoo 仍照跑,因為昨收 / 除息 / 上市櫃後綴都靠它。

// hhmm:台北時間 HHMM 整數(例 905)。回 { code, price, prev } 或 null。
// - 資料日 d 不是今天(休市日 MIS 仍回上一交易日)→ null
// - 09:00 前一律不收:08:30–09:00 是開盤前試撮,pz 是試撮價不是成交價(2026-10-05 08:57 曾被寫進當日紀錄)
// - z = 最近成交價;沒有(顯示 "-")才用 pz(最後揭示價),再沒有用 b 最佳一檔買價(即時、與成交價差一檔內)
// - 2026-10-05 實測:盤中 MIS 對程式查詢常常 z、pz 全是 "-"(連 2330 在 11:50 也是),只剩五檔買賣 b / a 有值
// - 13:25–13:30 收盤集合競價時 pz、b 都是試撮 → 只收 z
export function misQuote(s, today, hhmm) {
  const d = String((s && s.d) || '');
  const day = d.length === 8 ? `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}` : '';
  if (!s || !s.c || day !== today || hhmm < 900) return null;
  const z = parseFloat(s.z), pz = parseFloat(s.pz), y = parseFloat(s.y), bid = parseFloat(String(s.b || '').split('_')[0]);
  const open = hhmm < 1325;
  const [price, via] = z > 0 ? [z, 'z'] : open && pz > 0 ? [pz, 'pz'] : open && bid > 0 ? [bid, 'bid'] : [0, ''];
  return { code: String(s.c), price, via, prev: y > 0 ? y : 0 };
}

// MIS 查詢字串:已知上市(.TW)/ 上櫃(.TWO)只查那一邊;不知道才兩邊都查(多一個空白回應)
export function misQuery(codes, symHint = {}) {
  return codes.flatMap(c => symHint[c] === '.TW' ? [`tse_${c}.tw`] : symHint[c] === '.TWO' ? [`otc_${c}.tw`] : [`tse_${c}.tw`, `otc_${c}.tw`]).join('|');
}

// 合併:MIS 有價就用 MIS,否則用 Yahoo;回 { live, src } src[code] = 'MIS' | 'Yahoo'
export function mergeLive(mis, yahoo) {
  const live = {}, src = {};
  for (const c of new Set([...Object.keys(yahoo || {}), ...Object.keys(mis || {})])) {
    if (mis && mis[c] > 0) { live[c] = mis[c]; src[c] = 'MIS'; }
    else if (yahoo && yahoo[c] > 0) { live[c] = yahoo[c]; src[c] = 'Yahoo'; }
  }
  return { live, src };
}
