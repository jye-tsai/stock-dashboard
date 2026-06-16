// Cloudflare Worker:定時觸發 GitHub Action「update-prices」
// 注意:這支是貼到 Cloudflare 用的,不要上傳到 GitHub repo。
// token 不要寫在這裡,改用 Cloudflare 的 Secret(名稱:GH_TOKEN)。

export default {
  // Cron 觸發(時間在 Cloudflare 的 Triggers 設定,UTC)
  async scheduled(event, env, ctx) {
    ctx.waitUntil(triggerUpdate(env));
  },
  // 用瀏覽器打開這個 Worker 的根網址(/)會手動觸發一次;其他路徑(如 favicon.ico)忽略,避免重複觸發
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname !== '/') return new Response('ok');
    const r = await triggerUpdate(env);
    return new Response(r.ok ? '✅ 已觸發 update-prices' : ('❌ 失敗 ' + r.status + ' ' + r.body), { status: r.ok ? 200 : 500 });
  }
};

async function triggerUpdate(env) {
  const res = await fetch(
    'https://api.github.com/repos/jye-tsai/stock-dashboard/actions/workflows/update-prices.yml/dispatches',
    {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + env.GH_TOKEN,
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'panghu-cron-worker'
      },
      body: JSON.stringify({ ref: 'main' })
    }
  );
  const body = res.ok ? '' : await res.text();
  if (!res.ok) console.log('dispatch failed:', res.status, body);
  return { ok: res.status === 204, status: res.status, body };
}
