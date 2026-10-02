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

// ─── 排程斷線偵測:盤中排程(Cloudflare cron 每 10 分)漏跑時,下一次任何來源跑到這裡就發現「中間空了很久」
// 2026-10-02 Cloudflare 的 */10 cron 被換掉,整個早上沒觸發,只有開網頁時才補到價 → 加這個讓它自己喊。
// prev = 上次的 priceUpdated、stamp = 現在(都是台北 'YYYY-MM-DD HH:MM')。只看平日 09:00–14:00。
// 同一天 → 距上次超過 limit 分;前一天以前 → 今天 09:00 起算超過 limit 分還沒第一筆。回傳 { gap, last } 或 null。
export function scheduleGap(prev, stamp, limit = 30) {
  const day = stamp.slice(0, 10), mins = s => +s.slice(11, 13) * 60 + +s.slice(14, 16);
  const dow = new Date(day + 'T00:00:00Z').getUTCDay();
  const now = mins(stamp);
  if (dow === 0 || dow === 6 || now < 9 * 60 || now > 14 * 60) return null;
  const p = String(prev || '');
  const gap = p.slice(0, 10) === day ? now - mins(p) : now - 9 * 60;
  return gap > limit ? { gap, last: p ? (p.slice(0, 10) === day ? p.slice(11, 16) : p) : '從未' } : null;
}
// 一天只喊一次:狀態記在 data.alerts['sched:YYYY-MM-DD'],舊日期的順手清掉。回傳要發的文字或 ''
export function scheduleGapAlert(data, prev, stamp, trigger) {
  const g = scheduleGap(prev, stamp);
  const st = data.alerts && typeof data.alerts === 'object' ? data.alerts : (data.alerts = {});
  const key = 'sched:' + stamp.slice(0, 10);
  for (const k of Object.keys(st)) if (k.startsWith('sched:') && k !== key) delete st[k];
  if (!g || st[key]) return '';
  st[key] = { at: stamp, gap: g.gap };
  const by = { schedule: 'GitHub 備援排程', workflow_dispatch: '手動 / 網頁 / Cloudflare 觸發' }[trigger] || trigger || '未知來源';
  return [
    `⚠ 股價排程可能停了 ${stamp.slice(11, 16)}`,
    `上次更新 ${g.last},中間 ${g.gap} 分鐘沒有自動更新`,
    `這次由「${by}」補上`,
    '請檢查 Cloudflare Worker 的 Cron Triggers 是否還有 */10 1-5 * * *(cloudflare/README.md)',
  ].join('\n');
}
