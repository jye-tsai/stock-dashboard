// Cloudflare Worker:準時觸發 GitHub Action(GitHub 自己的 schedule 常漂移,這裡當主力、GitHub schedule 當備援)。
// 這份是正本:改了先改這裡、commit,再整段貼到 Cloudflare(Worker → Edit code → Deploy)。Cron 清單見 cloudflare/README.md。
// token 不要寫在這裡,用 Cloudflare 的 Secret(名稱:GH_TOKEN;fine-grained PAT,Actions: Read and write)。
//
// 一支 Worker 管兩個 workflow,依觸發的 cron 字串分流(Cloudflare Triggers 全用 UTC):
//   */10 1-5 * * *   台北 09:00–13:50 每 10 分       → update-prices.yml(盤中股價)
//   30 23 * * 1-5    台北 07:30 盤前(週一~五)        → chips.yml(premarket=true,source=cron → 盤前 LINE)
//   40 7 * * 2-6     台北 15:40 盤後(週一~五)        → chips.yml(source=cron → 盤後 LINE)
//   40 8 * * 2-6     台北 16:40 補永豐 PDF            → chips.yml(source=cron;同日已通知過 notify.py 會略過)
//   ※ Cloudflare 星期欄 1=日 … 7=六(GitHub 是 0=日)。盤後同一天,週一~五寫 2-6;
//     盤前 23:30 UTC 是台北隔天,台北週一~五 = UTC 週日~四 = 1-5。
//   ※ 新增 Cron Trigger 一定要在下面 ROUTES 補一條。對不到的仍會打 update-prices(保住股價),但 log 會標「未知 cron」
//     (2026-09-30 盤前漏跑、2026-10-02 股價那條被換成 */30 * * * * 整早沒觸發,都是 Cron Triggers 與這裡對不上)。
// 瀏覽器手動:開 Worker 根網址 / 觸發股價;/chips 觸發籌碼站盤後;/premarket 觸發盤前(都是 source=manual,不通知)。
// 其他路徑(favicon.ico)忽略。

const REPO = 'jye-tsai/stock-dashboard';

// 依「分 時」比對(不比星期欄,星期編號兩邊不同、容易寫錯),由上往下第一個符合的生效
const ROUTES = [
  { re: /^\*\/10 1-5 /, workflow: 'update-prices.yml', inputs: null },                           // 09:00–13:50 盤中股價
  { re: /^30 23 /,      workflow: 'chips.yml', inputs: { premarket: 'true', source: 'cron' } },   // 07:30 盤前
  { re: /^40 (7|8) /,   workflow: 'chips.yml', inputs: { source: 'cron' } },                      // 15:40 / 16:40 盤後
];
const DEFAULT_ROUTE = { workflow: 'update-prices.yml', inputs: null };                            // 對不到 → 至少保住股價

export function route(cron) {
  const r = ROUTES.find(x => x.re.test(cron));
  if (!r) console.log('⚠ 未知 cron:', cron, '(Cron Triggers 與 worker ROUTES 對不上,見 cloudflare/README.md)');
  return r || DEFAULT_ROUTE;
}

export default {
  async scheduled(event, env, ctx) {
    const r = route(event.cron);
    console.log('cron', event.cron, '→', r.workflow, JSON.stringify(r.inputs));
    ctx.waitUntil(dispatch(env, r.workflow, r.inputs));
  },
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === '/') { const r = await dispatch(env, 'update-prices.yml', null); return reply(r, '股價 update-prices'); }
    if (url.pathname === '/chips') { const r = await dispatch(env, 'chips.yml', { source: 'manual' }); return reply(r, '籌碼站 chips 盤後(手動,不通知)'); }
    if (url.pathname === '/premarket') { const r = await dispatch(env, 'chips.yml', { premarket: 'true', source: 'manual' }); return reply(r, '籌碼站 chips 盤前(手動)'); }
    return new Response('ok');
  }
};

function reply(r, label) {
  return new Response(r.ok ? `✅ 已觸發 ${label}` : `❌ 失敗 ${r.status} ${r.body}`, { status: r.ok ? 200 : 500 });
}

// inputs 為 null 時不帶(update-prices.yml 沒宣告 inputs,帶了會 422)
async function dispatch(env, workflow, inputs) {
  const body = { ref: 'main' };
  if (inputs) body.inputs = inputs;
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
