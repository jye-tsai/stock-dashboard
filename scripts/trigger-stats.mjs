// 排程可靠度統計(純函式,tests/trigger-stats.test.mjs 直接測):
// 輸入 GitHub Actions 的 run 清單(display_title 由 workflow 的 run-name 寫成「股價 cloudflare」「籌碼 盤後 cronjob」),
// 對照每個來源「應該」觸發的時段,算出應到 / 實到 / 平均與最大延遲,以及漏掉的時段。
// 時間一律台北(UTC+8);預設只算週一~五(休市日排程照樣會觸發,所以照算),days 指定的例外(週日先發週一盤前)。

// 每個來源預期的觸發時段(台北 HH:MM)。改了 Cloudflare Cron Triggers 或 cron-job.org 設定,要同步改這裡
const every10 = off => { const a = []; for (let h = 9; h <= 13; h++) for (let m = off; m < 60; m += 10) a.push(`${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`); return a; };
export const EXPECT = [
  { key: '股價', via: 'cloudflare', label: '盤中股價・Cloudflare', slots: every10(0) },   // */10 1-5 → 09:00–13:50
  { key: '股價', via: 'cronjob',    label: '盤中股價・cron-job.org', slots: every10(5) },  // 09:05–13:55
  { key: '籌碼 盤前', via: 'cloudflare', label: '盤前推播・Cloudflare', slots: ['07:30'] },
  { key: '籌碼 盤前', via: 'cronjob',    label: '盤前推播・cron-job.org', slots: ['07:25'] },
  { key: '籌碼 盤前', via: 'cloudflare', label: '週日先發週一盤前・Cloudflare', slots: ['12:00'], days: [0] },
  { key: '籌碼 盤前', via: 'cronjob',    label: '週日先發週一盤前・cron-job.org', slots: ['12:00'], days: [0] },
  { key: '籌碼 盤後', via: 'cloudflare', label: '盤後・Cloudflare', slots: ['15:40', '16:40'] },
  { key: '籌碼 盤後', via: 'cronjob',    label: '盤後・cron-job.org', slots: ['15:35', '15:45'] },
];
export const WINDOW_SEC = 300;     // 時段後 5 分鐘內出現才算這個時段有到(cron 正常延遲幾十秒)

const tpe = iso => new Date(new Date(iso).getTime() + 8 * 3600 * 1000);
const ymd = d => d.toISOString().slice(0, 10);
const parse = title => {                                    // '股價 cloudflare' → { key: '股價', via: 'cloudflare' }
  const m = String(title || '').match(/^(股價|籌碼 盤前|籌碼 盤後) (\S+)$/);
  return m ? { key: m[1], via: m[2] } : null;
};

// runs: [{ display_title, created_at }];from / to: 'YYYY-MM-DD'(台北,含頭含尾)
export function triggerStats(runs, from, to) {
  const all = [];                                           // [{ day, dow }]
  for (let d = new Date(from + 'T00:00:00Z'); ymd(d) <= to; d.setUTCDate(d.getUTCDate() + 1)) all.push({ day: ymd(d), dow: d.getUTCDay() });
  const daysOf = e => all.filter(x => (e.days || [1, 2, 3, 4, 5]).includes(x.dow)).map(x => x.day);
  const days = daysOf({});
  const tagged = [], others = {};
  for (const r of runs) {
    const p = parse(r.display_title); if (!p) continue;
    const t = tpe(r.created_at), day = ymd(t);
    if (day < from || day > to) continue;
    const known = EXPECT.some(e => e.key === p.key && e.via === p.via);
    if (known) tagged.push({ ...p, day, sec: t.getUTCHours() * 3600 + t.getUTCMinutes() * 60 + t.getUTCSeconds() });
    else { const k = `${p.key} ${p.via}`; others[k] = (others[k] || 0) + 1; }
  }
  const rows = EXPECT.map(e => {
    let hit = 0, sum = 0, max = 0; const missed = [];
    const eDays = daysOf(e);
    for (const day of eDays) for (const s of e.slots) {
      const at = +s.slice(0, 2) * 3600 + +s.slice(3, 5) * 60;
      const m = tagged.filter(x => x.key === e.key && x.via === e.via && x.day === day && x.sec >= at && x.sec < at + WINDOW_SEC)
                      .sort((a, b) => a.sec - b.sec)[0];
      if (m) { hit++; const d = m.sec - at; sum += d; if (d > max) max = d; }
      else missed.push(`${day.slice(5)} ${s}`);
    }
    const expected = eDays.length * e.slots.length;
    return { label: e.label, expected, hit, rate: expected ? hit / expected : 0, avgDelay: hit ? Math.round(sum / hit) : null, maxDelay: hit ? max : null, missed };
  });
  return { from, to, days: days.length, rows, others };
}

export function statsMarkdown(st, generatedAt) {
  const pct = x => (x * 100).toFixed(1) + '%';
  const L = [`# 排程可靠度(${st.from} ~ ${st.to},平日 ${st.days} 天)`, '',
    `產生時間 ${generatedAt}(台北)。「到」= 預定時刻後 ${WINDOW_SEC / 60} 分鐘內 GitHub 有收到該來源的觸發。`, '',
    '| 來源 | 應到 | 實到 | 到達率 | 平均延遲 | 最大延遲 |', '|---|---:|---:|---:|---:|---:|'];
  for (const r of st.rows) L.push(`| ${r.label} | ${r.expected} | ${r.hit} | ${pct(r.rate)} | ${r.avgDelay == null ? '—' : r.avgDelay + ' 秒'} | ${r.maxDelay == null ? '—' : r.maxDelay + ' 秒'} |`);
  const miss = st.rows.filter(r => r.missed.length);
  if (miss.length) {
    L.push('', '## 漏掉的時段');
    for (const r of miss) L.push(`- **${r.label}**(${r.missed.length}):${r.missed.slice(0, 40).join('、')}${r.missed.length > 40 ? ' …' : ''}`);
  }
  const o = Object.entries(st.others);
  if (o.length) L.push('', '## 其他觸發(不列入可靠度)', ...o.map(([k, n]) => `- ${k}:${n} 次`));
  L.push('', '來源標記:cloudflare = Cloudflare Worker cron;cronjob = cron-job.org(URL 帶 `?src=cronjob`);web = 網頁補觸發;button = 「📈 更新市價」;url = 瀏覽器開 Worker 網址;schedule = GitHub 內建排程;manual = GitHub 網頁手動 Run。');
  return L.join('\n') + '\n';
}
