// Cloudflare Worker:準時觸發 GitHub Action(GitHub 自己的 schedule 常漂移,這裡當主力、GitHub schedule 當備援)。
// 注意:這支是貼到 Cloudflare 用的,不要上傳到 GitHub repo(本機 .git/info/exclude 已排除)。
// token 不要寫在這裡,用 Cloudflare 的 Secret(名稱:GH_TOKEN;fine-grained PAT,Actions: Read and write)。
//
// 一支 Worker 管兩個 workflow,依觸發的 cron 字串分流(Cloudflare Triggers 全用 UTC):
//   */15 1-5 * * *   台北 09:00–13:45 每 15 分     → update-prices.yml(收盤價)
//   0 6 * * *        台北 14:00 收盤結算           → update-prices.yml
//   40 7 * * 1-5     台北 15:40 盤後               → chips.yml(籌碼站,inputs.source=cron → 會 LINE 通知)
//   40 8 * * 1-5     台北 16:40 補永豐 PDF          → chips.yml(source=cron;同日已通知過 notify.py 會略過)
// 瀏覽器手動:開 Worker 根網址 / 觸發收盤價;開 /chips 觸發籌碼站(source=manual,不通知)。其他路徑(favicon.ico)忽略。

const REPO = 'jye-tsai/stock-dashboard';
const CHIPS_CRONS = new Set(['40 7 * * 1-5', '40 8 * * 1-5']);

export default {
  async scheduled(event, env, ctx) {
    const chips = CHIPS_CRONS.has(event.cron);
    ctx.waitUntil(dispatch(env, chips ? 'chips.yml' : 'update-prices.yml', chips ? { source: 'cron' } : null));
  },
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === '/') { const r = await dispatch(env, 'update-prices.yml', null); return reply(r, '收盤價 update-prices'); }
    if (url.pathname === '/chips') { const r = await dispatch(env, 'chips.yml', { source: 'manual' }); return reply(r, '籌碼站 chips(手動,不通知)'); }
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
