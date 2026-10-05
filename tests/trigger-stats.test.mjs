// scripts/trigger-stats.mjs:排程可靠度統計
import assert from 'node:assert/strict';
import { triggerStats, statsMarkdown } from '../scripts/trigger-stats.mjs';

const run = (title, tpe) => ({ display_title: title, created_at: new Date(Date.parse(tpe + '+08:00')).toISOString() });
// 2026-10-05 週一:Cloudflare 股價只到 09:00(+20 秒)、09:10(+50 秒),其餘漏;cron-job.org 全到(+3 秒)
const runs = [run('股價 cloudflare', '2026-10-05T09:00:20'), run('股價 cloudflare', '2026-10-05T09:10:50')];
for (let h = 9; h <= 13; h++) for (let m = 5; m < 60; m += 10) runs.push(run('股價 cronjob', `2026-10-05T${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:03`));
runs.push(run('籌碼 盤前 cronjob', '2026-10-05T07:35:04'), run('籌碼 盤前 cloudflare', '2026-10-05T07:30:30'));
runs.push(run('籌碼 盤後 cloudflare', '2026-10-05T15:40:18'), run('籌碼 盤後 cronjob', '2026-10-05T15:35:02'));
runs.push(run('籌碼 盤後 cronjob', '2026-10-05T15:51:00'));              // 晚 6 分 → 不算 15:45 那格
runs.push(run('股價 web', '2026-10-05T10:33:00'), run('股價 button', '2026-10-05T11:00:00'), run('update-prices・股價更新', '2026-10-05T11:00:00'));
runs.push(run('股價 cloudflare', '2026-10-04T09:00:00'));                // 週日:不在平日內,不計
runs.push(run('籌碼 盤前 cronjob', '2026-10-04T12:00:05'));              // 週日 12:00 先發週一盤前

const st = triggerStats(runs, '2026-10-04', '2026-10-05');
const R = Object.fromEntries(st.rows.map(r => [r.label, r]));
assert.equal(st.days, 1);
assert.deepEqual([R['盤中股價・Cloudflare'].expected, R['盤中股價・Cloudflare'].hit, R['盤中股價・Cloudflare'].avgDelay, R['盤中股價・Cloudflare'].maxDelay], [30, 2, 35, 50]);
assert.equal(R['盤中股價・Cloudflare'].missed[0], '10-05 09:20');
assert.deepEqual([R['盤中股價・cron-job.org'].hit, R['盤中股價・cron-job.org'].rate, R['盤中股價・cron-job.org'].avgDelay], [30, 1, 3]);
assert.equal(R['盤前推播・cron-job.org'].hit, 1);
assert.equal(R['盤前推播・Cloudflare'].hit, 1);
assert.deepEqual([R['盤後・Cloudflare'].hit, R['盤後・Cloudflare'].missed], [1, ['10-05 16:40']]);
assert.deepEqual([R['盤後・cron-job.org'].hit, R['盤後・cron-job.org'].missed], [1, ['10-05 15:45']]);
assert.deepEqual(st.others, { '股價 web': 1, '股價 button': 1 });  // 舊標題(沒來源)不算
const md = statsMarkdown(st, '2026-10-05 17:00');
assert.match(md, /\| 盤中股價・Cloudflare \| 30 \| 2 \| 6\.7% \| 35 秒 \| 50 秒 \|/);
assert.match(md, /盤後・cron-job\.org\*\*\(1\):10-05 15:45/);
assert.deepEqual([R['週日先發週一盤前・cron-job.org'].expected, R['週日先發週一盤前・cron-job.org'].hit], [1, 1]);
assert.deepEqual([R['週日先發週一盤前・Cloudflare'].expected, R['週日先發週一盤前・Cloudflare'].missed], [1, ['10-04 12:00']]);
assert.equal(R['盤前推播・cron-job.org'].expected, 1);                     // 平日項目不算週日
console.log('trigger-stats.test: 14 項通過');
