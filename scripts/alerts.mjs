// 停損 / 目標價提醒的判斷(純函式,不碰網路、不讀環境變數);update-prices.mjs 每次更新股價後呼叫,tests/alerts.test.mjs 直接測
// ─── 停損 / 目標價盤中提醒(LINE):價位是自己設的,這裡只負責「碰到了告訴你」
// 同一檔同一種提醒跨過去只發一次;價格回到停損 +1% 以上(目標 −1% 以下)或改了價位才重新起算。
// 狀態存在 data.alerts(跟著 data.json 一起加密);漲跌超過 ±10.5%(超出漲跌停)視為資料異常不發;LINE secrets 沒設就只寫 log。
export function scanAlerts(data, stamp) {
  const st = data.alerts && typeof data.alerts === 'object' ? data.alerts : {};
  const fire = [];
  for (const h of data.holdings || []) {
    if (!h.code) continue;
    const held = h.lots > 0 && h.price > 0;
    const sane = !(h.prevClose > 0) || Math.abs(h.price / h.prevClose - 1) <= 0.105;
    const rules = [
      ['stop', h.stop, p => p <= h.stop, p => p >= h.stop * 1.01],
      ['target', h.target, p => p >= h.target, p => p <= h.target * 0.99],
    ];
    for (const [kind, lv, hit, back] of rules) {
      const key = h.code + ':' + kind;
      if (!held || !(lv > 0)) { delete st[key]; continue; }          // 賣光 / 沒設價位 → 清掉
      if (!sane) continue;
      if (st[key] && st[key].level !== lv) delete st[key];            // 改了價位 → 重新起算
      if (st[key] && back(h.price)) delete st[key];                   // 回到安全區 → 重新起算
      if (!st[key] && hit(h.price)) { st[key] = { level: lv, price: h.price, at: stamp }; fire.push({ kind, h, key }); }
    }
  }
  data.alerts = st;
  return fire;
}
export function alertText(fire, stamp) {
  const n2 = x => (+x).toLocaleString('en-US', { maximumFractionDigits: 2 });
  const pct = x => (x >= 0 ? '+' : '') + (x * 100).toFixed(1) + '%';
  const L = [];
  for (const kind of ['stop', 'target']) {
    const xs = fire.filter(f => f.kind === kind);
    if (!xs.length) continue;
    L.push(kind === 'stop' ? `⚠ 停損提醒 ${stamp.slice(11, 16)}` : `🎯 目標價提醒 ${stamp.slice(11, 16)}`);
    for (const { h } of xs) {
      L.push(`${h.code} ${(h.name || '').slice(0, 8)} 現價 ${n2(h.price)} ${kind === 'stop' ? '≤ 停損' : '≥ 目標'} ${n2(kind === 'stop' ? h.stop : h.target)}`);
      const day = h.prevClose > 0 ? `今日 ${pct(h.price / h.prevClose - 1)}` : '';
      const vs = h.cost > 0 ? `成本 ${n2(h.cost)}(${pct(h.price / h.cost - 1)})` : '';
      if (day || vs) L.push([day, vs].filter(Boolean).join('｜'));
    }
    L.push(kind === 'stop' ? '停損是你自己設的,執不執行由你決定。' : '目標價是你自己設的,要不要賣由你決定。');
  }
  return L.join('\n');
}
