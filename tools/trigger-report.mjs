// 排程可靠度報表:抓 GitHub Actions 的 update-prices / chips 執行紀錄 → scripts/trigger-stats.mjs 統計 → reports/triggers.md
// 用法(GitHub Action trigger-report.yml 每週六跑,也可手動):GITHUB_TOKEN=… GITHUB_REPOSITORY=owner/repo node tools/trigger-report.mjs [天數,預設 14]
import fs from 'node:fs';
import { triggerStats, statsMarkdown } from '../scripts/trigger-stats.mjs';

const repo = process.env.GITHUB_REPOSITORY || 'jye-tsai/stock-dashboard';
const token = process.env.GITHUB_TOKEN;
const days = +(process.argv[2] || 14);
const tpe = new Date(Date.now() + 8 * 3600 * 1000);
const to = tpe.toISOString().slice(0, 10);
const from = new Date(tpe.getTime() - (days - 1) * 86400000).toISOString().slice(0, 10);
// GitHub 的 created 篩選是 UTC 日期;台北清晨 07:20 = 前一天 UTC 23:20 → 往前多抓一天,統計範圍仍由 triggerStats 依台北日期切
const fromUtc = new Date(tpe.getTime() - days * 86400000).toISOString().slice(0, 10);

async function runs(workflow) {
  const out = [];
  for (let page = 1; page <= 20; page++) {
    const r = await fetch(`https://api.github.com/repos/${repo}/actions/workflows/${workflow}/runs?per_page=100&page=${page}&created=%3E%3D${fromUtc}`, {
      headers: { Accept: 'application/vnd.github+json', ...(token ? { Authorization: 'Bearer ' + token } : {}) },
    });
    if (!r.ok) throw new Error(`${workflow} HTTP ${r.status}`);
    const j = await r.json();
    out.push(...j.workflow_runs.map(x => ({ display_title: x.display_title, created_at: x.created_at })));
    if (j.workflow_runs.length < 100) break;
  }
  return out;
}

const all = [...await runs('update-prices.yml'), ...await runs('chips.yml')];
const md = statsMarkdown(triggerStats(all, from, to, tpe.toISOString().slice(0, 16).replace('T', ' ')), tpe.toISOString().slice(0, 16).replace('T', ' '));
fs.mkdirSync('reports', { recursive: true });
fs.writeFileSync('reports/triggers.md', md);
if (process.env.GITHUB_STEP_SUMMARY) fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, md);
console.log(md);
