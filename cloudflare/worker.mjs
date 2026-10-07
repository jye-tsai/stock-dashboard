// Cloudflare Worker:準時觸發 GitHub Action(GitHub 自己的 schedule 常漂移,這裡當主力、GitHub schedule 當備援)。
// 這份是正本:改了先改這裡、commit,再整段貼到 Cloudflare(Worker → Edit code → Deploy)。Cron 清單見 cloudflare/README.md。
// token 不要寫在這裡,用 Cloudflare 的 Secret(名稱:GH_TOKEN;fine-grained PAT,Actions: Read and write)。
//
// 一支 Worker 管兩個 workflow,依觸發的 cron 字串分流(Cloudflare Triggers 全用 UTC):
//   */10 1-5 * * *   台北 09:00–13:50 每 10 分       → update-prices.yml(盤中股價)
//   20 23 * * 1-5    台北 07:20 盤前(週一~五)        → chips.yml(premarket=true,source=cron → 盤前 LINE)
//   0 4 * * 1        台北週日 12:00 先發週一盤前      → chips.yml(同上;premarket.py 週末跑會標成下週一,週一 07:20 同日已發 → 略過)
//   40 7 * * 2-6     台北 15:40 盤後(週一~五)        → chips.yml(source=cron → 盤後 LINE)
//   40 8 * * 2-6     台北 16:40 補永豐 PDF            → chips.yml(source=cron;同日已通知過 notify.py 會略過)
//   ※ Cloudflare 星期欄 1=日 … 7=六(GitHub 是 0=日)。盤後同一天,週一~五寫 2-6;
//     盤前 23:30 UTC 是台北隔天,台北週一~五 = UTC 週日~四 = 1-5。
//   ※ 新增 Cron Trigger 一定要在下面 ROUTES 補一條。對不到的仍會打 update-prices(保住股價),但 log 會標「未知 cron」
//     (2026-09-30 盤前漏跑、2026-10-02 股價那條被換成 */30 * * * * 整早沒觸發,都是 Cron Triggers 與這裡對不上)。
// 瀏覽器手動:開 Worker 根網址 / 觸發股價;/chips 觸發籌碼站盤後(source=manual,不發 LINE);
//   /premarket 觸發盤前(chips.yml 盤前不看 source,一律發 LINE,同日只發一次)。
// cron-job.org 用(有時段限制,網址公開也不怕被亂打;同一天 LINE 只發一次,跟 Cloudflare cron 兩邊都打也只收一則):
//   /chips-cron      籌碼站盤後 source=cron,台北週一~五 15:30–17:59 有效
//   /premarket-cron  籌碼站盤前,台北週一~五 07:00–08:59、週日 11:30–13:59(週一盤前提早發)有效
// 來源標記 via:Cloudflare cron = cloudflare;網址觸發看 ?src=(cron-job.org 的 URL 都加 ?src=cronjob),沒帶 = url。
//   GitHub 執行紀錄標題會顯示它,tools/trigger-report.mjs 據此統計各來源準不準。
// 其他路徑(favicon.ico)忽略。

const REPO = 'jye-tsai/stock-dashboard';

// 依「分 時」比對(不比星期欄,星期編號兩邊不同、容易寫錯),由上往下第一個符合的生效
const ROUTES = [
  { re: /^\*\/10 1-5 /, workflow: 'update-prices.yml', inputs: {} },                             // 09:00–13:50 盤中股價
  { re: /^[23]0 23 /,    workflow: 'chips.yml', inputs: { premarket: 'true', source: 'cron' } },   // 07:20 盤前(2026-10-07 起;舊的 30 23 = 07:30 也認,改 Cloudflare 前後都不會打錯)
  { re: /^0 4 /,        workflow: 'chips.yml', inputs: { premarket: 'true', source: 'cron' } },   // 週日 12:00 先發週一盤前
  { re: /^40 (7|8) /,   workflow: 'chips.yml', inputs: { source: 'cron' } },                      // 15:40 / 16:40 盤後
];
const DEFAULT_ROUTE = { workflow: 'update-prices.yml', inputs: {} };                              // 對不到 → 至少保住股價

export function route(cron) {
  const r = ROUTES.find(x => x.re.test(cron));
  if (!r) console.log('⚠ 未知 cron:', cron, '(Cron Triggers 與 worker ROUTES 對不上,見 cloudflare/README.md)');
  return r || DEFAULT_ROUTE;
}

// cron-job.org 路徑的有效時段(台北;days 0=日 … 6=六,分鐘數 [from, to)):網址是公開的,擋掉其他時間被亂打
// (盤中打盤後會拿到前一天的籌碼;半夜打盤前會用舊資料發掉當天那一則)
const WEEKDAYS = [1, 2, 3, 4, 5];
export const WINDOWS = {
  '/chips-cron':     [{ days: WEEKDAYS, from: 15 * 60 + 30, to: 18 * 60 }],   // 週一~五 15:30–17:59
  '/premarket-cron': [{ days: WEEKDAYS, from: 7 * 60, to: 9 * 60 },          // 週一~五 07:00–08:59
                      { days: [0], from: 11 * 60 + 30, to: 14 * 60 }],       // 週日 11:30–13:59(週一盤前提早發)
};
export function cronWindow(path, now = new Date()) {
  const ws = WINDOWS[path]; if (!ws) return false;
  const t = new Date(now.getTime() + 8 * 3600 * 1000);
  const dow = t.getUTCDay(), m = t.getUTCHours() * 60 + t.getUTCMinutes();
  return ws.some(w => w.days.includes(dow) && m >= w.from && m < w.to);
}
const hhmm = m => String(Math.floor(m / 60)).padStart(2, '0') + ':' + String(m % 60).padStart(2, '0');
const DAYNAME = d => d.length === 5 && d[0] === 1 && d[4] === 5 ? '週一~五' : d.map(x => '週' + '日一二三四五六'[x]).join('、');
const notInWindow = path => new Response(`⏸ 不在時段(${path}:台北 ${WINDOWS[path].map(w => `${DAYNAME(w.days)} ${hhmm(w.from)}–${hhmm(w.to - 1)}`).join(' / ')}),沒有觸發`, { status: 200 });

export default {
  async scheduled(event, env, ctx) {
    const r = route(event.cron), inputs = { ...r.inputs, via: 'cloudflare' };
    console.log('cron', event.cron, '→', r.workflow, JSON.stringify(inputs));
    ctx.waitUntil(dispatch(env, r.workflow, inputs));
  },
  async fetch(request, env) {
    const url = new URL(request.url), via = viaOf(url);
    if (url.pathname === '/') { const r = await dispatch(env, 'update-prices.yml', { via }); return reply(r, '股價 update-prices'); }
    if (url.pathname === '/chips') { const r = await dispatch(env, 'chips.yml', { source: 'manual', via }); return reply(r, '籌碼站 chips 盤後(手動,不通知)'); }
    if (url.pathname === '/chips-cron') {
      if (!cronWindow(url.pathname)) return notInWindow(url.pathname);
      const r = await dispatch(env, 'chips.yml', { source: 'cron', via }); return reply(r, '籌碼站 chips 盤後(cron,會發 LINE)');
    }
    if (url.pathname === '/premarket-cron') {
      if (!cronWindow(url.pathname)) return notInWindow(url.pathname);
      const r = await dispatch(env, 'chips.yml', { premarket: 'true', source: 'cron', via }); return reply(r, '籌碼站 chips 盤前(cron,會發 LINE)');
    }
    if (url.pathname === '/premarket') { const r = await dispatch(env, 'chips.yml', { premarket: 'true', source: 'manual', via }); return reply(r, '籌碼站 chips 盤前(手動,同日沒發過會發 LINE)'); }
    return new Response('ok');
  }
};

// ?src=cronjob → 'cronjob';沒帶或怪字元 → 'url'(瀏覽器手動開)
export function viaOf(url) {
  const s = url.searchParams.get('src') || '';
  return /^[A-Za-z0-9_-]{1,20}$/.test(s) ? s : 'url';
}

function reply(r, label) {
  return new Response(r.ok ? `✅ 已觸發 ${label}` : `❌ 失敗 ${r.status} ${r.body}`, { status: r.ok ? 200 : 500 });
}

// 帶的 inputs 必須是 workflow 有宣告的,否則 GitHub 回 422(update-prices.yml / chips.yml 都有宣告 via)
async function dispatch(env, workflow, inputs) {
  const body = { ref: 'main' };
  if (inputs && Object.keys(inputs).length) body.inputs = inputs;
  const res = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${workflow}/dispatches`, {
    method: 'POST',
    headers: {
      'Authorization': 'Bearer ' + env.GH_TOKEN,
      'Accept': 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent': 'panghu-cron-worker'
    },
    body: JSON.stringify(body)
  });
  const text = res.ok ? '' : await res.text();
  if (!res.ok) console.log('dispatch failed:', workflow, res.status, text);
  return { ok: res.status === 204, status: res.status, body: text };
}
