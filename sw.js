// 胖虎的小財庫 — Service Worker(離線快取)
// 改了任何靜態檔(styles.css / app.js / charts.js / scripts/calc.js / 圖示)記得把 CACHE 版號 +1,activate 會把舊快取整包清掉。
// index.html 走網路優先;.js / .css 用 ?v= 版本 query 當快取鍵,index.html 換了 v 就一定抓新檔,不會出現「新 app.js 配舊 calc.js」。
// 靜態資源走 stale-while-revalidate:先回快取、背景抓新版寫回;就算忘了改版號,F5 兩次也一定看到新圖。
const ASSET_VER = '20260922h';                 // 與 index.html 的 ?v= 一致;改 .js / .css 時兩邊一起換
const CACHE = 'panghu-v12';
const SHELL = [
  './',
  './index.html',
  './styles.css?v=' + ASSET_VER,
  './charts.js?v=' + ASSET_VER,
  './app.js?v=' + ASSET_VER,
  './scripts/calc.js?v=' + ASSET_VER,
  './manifest.json',
  './favicon.png',
  './panghu-icon.png',
  './panghu-icon.webp',
  './panghu.webp',
  './panghu-sad.webp',
  './panghu-flat.webp',
  'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js'
];

// 安裝:快取 app shell(個別加入,單一失敗不影響整體)
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE)
      .then(c => Promise.allSettled(SHELL.map(u => c.add(u))))
      .then(() => self.skipWaiting())
  );
});

// 啟用:清掉舊版快取
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// 取用策略
self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  const isData = url.pathname.endsWith('data.json') || url.hostname.includes('api.github.com');
  const isDoc = req.mode === 'navigate' || url.pathname.endsWith('.html') || url.pathname.endsWith('/');

  // 網頁與資料:網路優先(確保看到最新),離線時退回最後一次快取
  if (isData || isDoc) {
    e.respondWith(
      fetch(req).then(res => {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(req, copy)).catch(() => {});
        return res;
      }).catch(() => caches.match(req).then(hit => hit || caches.match('./index.html')))
    );
    return;
  }

  // 靜態資源(圖示、Chart.js):stale-while-revalidate
  // 有快取 → 立刻回快取,同時背景抓網路新版寫回(下次 F5 就是新的);沒快取 → 等網路,抓到補快取。
  e.respondWith(
    caches.open(CACHE).then(c =>
      c.match(req).then(hit => {
        const refresh = fetch(req).then(res => {
          if (res && res.ok) c.put(req, res.clone()).catch(() => {});
          return res;
        }).catch(() => null);
        if (hit) {
          e.waitUntil(refresh);
          return hit;
        }
        return refresh.then(res => res || Response.error());
      })
    )
  );
});
