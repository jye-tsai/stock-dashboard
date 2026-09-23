# 胖虎的小財庫 🐶📈

純前端的台股庫存儀表板,部署在 GitHub Pages,資料存在 `data.json`,市價由 GitHub Action 在伺服器端自動更新。

> 線上網址:`https://jye-tsai.github.io/stock-dashboard/`
> Repo:`jye-tsai/stock-dashboard`(分支 `main`)
> 本機工作目錄:`Desktop/mygithub/股票庫存儀表版`

---

## 快速定位（給接手的人 / 新的 Claude session)

先讀這段就能接手。細節在後面各節。

- **前端四個檔**:`index.html`(純結構,約 290 行)、`styles.css`(主題 + 版面)、`app.js`(主程式,§ 分段,Ctrl+F 搜 `§` 跳段)、`charts.js`(八張圖 + 熱圖,每圖一支 `drawXxx(T)`);純計算在 `scripts/calc.js`(前端與 Action 共用)。載入順序:calc.js → Chart.js → charts.js → app.js。
- **HTML 不寫 `onclick`**:按鈕用 `data-action="fn" data-args='[...]'`,由 `app.js` §16b 的委派 listener 查允許清單(`ACTIONS`)呼叫;Enter 送出用 `data-enter="fn"`。新增按鈕記得把函式名加進 `ACTIONS`。
- **市價不是前端抓的**——瀏覽器受 CORS 限制抓不到證交所/Yahoo。市價由 **GitHub Action 跑 `scripts/update-prices.mjs`** 在伺服器端抓,寫回 `data.json` 並 commit;由 **Cloudflare Worker 的 cron** 準時觸發(GitHub 自己的 schedule 當備援)。
- **`data.json` 的正本在 repo**,不是本機。排程會直接 commit 到 repo。**本機資料夾刻意不放 `data.json`**(舊明文版已搬到 `../股票庫存儀表版_原圖備份/`),要本機測試就從 repo 下載一份,測完刪掉,**不要拿本機蓋 repo**。
- **改完用 GitHub Desktop push**(本機資料夾已是 git repo,接著 `origin/main`):開 GitHub Desktop → 看 Changes 清單 → 寫一行摘要 → Commit → Push。子資料夾、隱藏資料夾、刪檔全部一次同步,不會再漏。`cloudflare-worker.js` 已在 `.git/info/exclude`,不會被推上去;`data.json` 不要勾(排程會自己 commit,你本機那份永遠比較舊)。
- **上傳前一鍵**:`node tools/bump.mjs` → 先跑測試,綠燈才把 `index.html` 四處 `?v=` 與 `sw.js` 的 `ASSET_VER` / `CACHE` 換成新值(台北日期 + 序號字母),並印出要上傳哪些檔。**不要再手改版號**。
- **一鍵檢查**:`node tests/run.mjs`(語法 + `tests/calc.test.mjs` + `tests/sw.test.mjs`);push 到 repo 會由 `.github/workflows/check.yml` 自動跑,紅燈 = 上錯 / 漏檔。改 `calc.js` 順手補測。
- **畫面卡住 / 看不到新版**:⚙️ 設定 →「🧹 清快取重新載入」(unregister SW + 清 caches + reload)。render 炸掉或 12 秒載不完時頂部也會自動出這條紅色橫幅(`index.html` head 內嵌,不依賴 app.js)。
- **已知環境雷**:某些沙箱 / 掛載會顯示 `index.html` / `.mjs` 的**殘檔或舊版**(行數不對、node 檢查報怪錯)。這不是檔案壞掉——以編輯器/檔案工具讀到的內容為準,別被殘檔誤導。

---

## 功能

- **總覽**:今日損益 Hero 置頂(左:今日賺賠大字;右:近 30 個交易日總市值 sparkline;總市值 / 總報酬看正下方的摘要卡片列;各檔 `prevClose` 加總,缺昨收退回比 history 前一交易日市值)、**總報酬瀑布圖**(0 → 未實現 → 已實現 → 股息 → 總報酬,浮動長條、負分項往下走、端點標金額)、市值比例甜甜圈、年度損益、資產走勢、每日市值變動、報酬對比大盤、摘要卡片列(帳戶餘額 / 交割款併入,解鎖後顯示)、持股損益。
- **持股明細**:可點欄位排序、點列展開明細(賣出可拿回、目標 / 停損距離);賣出稅費 / 成本比例 / 市值比例三欄預設收起,勾「顯示全部欄位」才出現(記在 localStorage);市價下方顯示**今日漲跌 %**;「走勢」欄是**近 30 個交易日 sparkline**(inline SVG,漲紅跌綠,滑過看區間 %;資料來自 `history[].prices`,由 Action 寫入 + 回補),**點它(或展開列的「📈 近 90 日走勢」、手機卡片的 sparkline)開單檔小視窗**:近 90 日收盤線 + 成本 / 目標 / 停損虛線 + 統計格(現價、成本、未實現、區間漲跌 vs 大盤、區間高低、距目標 / 停損);手機自動轉卡片(卡片列右側也有 sparkline)。
- **目標價 / 停損價**:每檔可設,到價時整列標記 🎯 / ⚠️。
- **資料過期警示**:頁首更新時間旁,今日已更新亮綠點 ●;交易日過了還沒更新顯示紅底「⚠ 資料可能未更新」(週末 / 開盤前不誤報)。
- **數字跳動動畫**、**載入骨架屏**、**下拉重新整理**(手機;軟更新:重抓資料 → render,不整頁 reload、不閃白;編輯中不更新;抓不到才 reload)、**底部分頁列**(手機寬度時取代頂部頁籤:總覽 / 持股 / 年度 / 分享 / 設定固定在螢幕下緣)。**手機版面**:摘要卡 3 欄 × 2 列、三張子圖改橫向滑動卡片(scroll-snap)、熱圖只畫近 13 週、區間鈕滿寬五等分、更新時間併進按鈕列。
- **⚙️ 設定的兩個開關**:「色弱友善」(漲橘 / 跌藍,全站含圖表一起換)、「緊湊密度」(間距 / 字級 / 面板內距 / 圖高整體縮,靠 token 一次生效);都記在 localStorage。
- **列印 / 存 PDF**:`@media print` 白底、藏工具列與分頁鈕、三個分頁全印、面板不跨頁切斷;月底 Ctrl+P 就是一份報表。
- **分頁 icon 與標題帶今日漲跌**:favicon 動態畫 ▲ / ▼(顏色跟 --up / --down),`document.title` 前綴今日 %;手機捲過 Hero 後頂部貼一條迷你今日損益列。
- **7 種主題**:🌊 海洋藍、🌅 珊瑚暖陽、🌿 抹茶清新、🌌 午夜金、🍡 馬卡龍、🌙 美少女、🧬 Agent Neon;標題會發光。圖表配色隨主題(含極值高亮色 `hi`/`lo`)。
- **工具列收納**:頁面主題、圖表風格、GitHub 同步、載入 JSON、設定密碼都收在「⚙️ 設定」視窗;header 只留 解鎖(→ 編輯)/ 儲存 / 更新市價 / ⚙️ 設定 / 登出。
- **胖虎吉祥物**:依「今日未實現損益 vs 昨日」換表情(賺 → 笑、賠 → 哭、持平 → 淡定)。
- **分享戰報**:Hero 右下選「今日 / 本週 / 本月」→「📤 分享戰報」→ canvas 合成 1080×1350 圖(吉祥物 + 標題 + 期間 → 損益大字 → 總市值 / 總報酬 → **總市值走勢線**(自己畫,今日 = 近 30 個交易日、週月 = 該期間;標最高 / 最低與首尾日期)→ 頁尾網址),配色跟當前主題;文字自動縮字級不溢出。手機走 Web Share 直接丟 LINE / IG,桌機下載 PNG。勾「只顯示 %」金額全部隱藏只留百分比。本週 / 本月損益 = 期間起點前最後一筆到最新一筆的**總報酬**變化(`PfCalc.periodChange`)。
- **PWA**:可安裝到手機主畫面、全螢幕、離線看上次資料。
- **編輯模式**:解鎖後可改標題、持股、年度、帳戶、目標 / 停損,存回 GitHub。

### 走勢圖群(總覽下方)

1. **資產走勢**:堆疊面積 = 成本 + 未實現損益,合計 ≈ 總市值(白色加粗虛線標總市值天花板),並標該區間**最高 / 最低**點。Y 軸自 0 起。
2. **每日市值變動**:柱狀,較前一日增減,紅漲綠跌;區間內**漲最多 / 跌最多**用高亮色(`palette.hi`/`lo`)+ 文字標示。
3. **報酬對比**:以區間起點為 0% 正規化的折線 —— **我的組合 vs 加權指數 vs 台積電**。我的組合用**時間加權報酬(TWR)**:日報酬 = (Δ市值 − Δ成本) / 昨日市值 逐日連乘,加碼 / 減碼當天指數不動,不會把「錢進來」畫成「贏大盤」(`PfCalc.twrIndex`)。
4. **回撤**:總報酬(`ret`)距「截至當日的歷史前高」掉了多少,佔當日成本的 %;副標寫**最大回撤**(高點 → 谷底日期、幾個交易日、金額)與**目前回撤 + 離新高還差多少**(在新高就顯示 ●)。前高看全史、畫面只看區間,所以切區間不會讓回撤「變小」。
5. **每日損益月曆**(獨立 panel):GitHub 貢獻牆式熱圖,欄 = 週、列 = 週一~週五,一格一天;紅賺綠賠、深淺 = √(金額 / 區間最大)(小額也看得見),0 用底色、休市虛框;近 26 週,不受區間鈕影響;滑過看金額,**點格子 → 四張走勢圖定位到那天**(不在目前區間就自動切「全部」)。右側 **統計卡**:勝率、賺 / 賠天數、平均賺 / 賠一天、最佳 / 最差日、最長連賺 / 連賠、目前連續。純 CSS grid,不吃 Chart.js。

前四圖共用同一組時間範圍(近 1 週 / 近 1 月 / 近 3 月 / 今年 / 全部;筆數 = 交易日)與 **hover 同步**(滑到某天,其他三張同一天亮點 + 垂直十字線,tooltip 只留在滑鼠那張,不會四個框疊在一起;`navSyncPlugin`,靠 MM-DD label 對齊)與同一份 `hist`;桌機寬度(> 800px)時每日變動與報酬對比左右並排;**週末**一律不畫,**有 taiex 之後**沒 taiex 的日期(國定假日休市)也不畫。

---

## 檔案結構

| 檔案 | 用途 |
|---|---|
| `index.html` | 整個儀表板(HTML / CSS / JS 單檔);Chart.js 走 cdnjs 並鎖 `integrity`(SRI),升版要同步換 hash(`https://api.cdnjs.com/libraries/Chart.js/<ver>?fields=sri`) |
| `data.json` | 資料來源(持股、年度、帳戶、歷史、密碼等);**正本在 repo,本機不放**(repo 上是 AES 混淆版,由 Action 寫回) |
| `styles.css` / `app.js` / `charts.js` | 前端三件套:設計 token(`--fs-* / --fw-* / --r-* / --sp-* / --font-ui / --font-num / --ring`)+ 主題顏色 + 版面。字體:系統堆疊(iPhone / Mac PingFang、Windows Segoe + 微軟正黑),金額用 Google Fonts **Inter**(載不到退回系統字) / 主程式(載入、render、編輯、密碼、GitHub、分享卡、事件委派)/ 八張圖 + 熱圖。**尺寸一律用 token**,主題只改顏色;字重最重 800,880 只給 Hero 大字 |
| `scripts/calc.js` | **純計算共用模組**(UMD):(1) 損益:成本 / 市值 / 賣出成本 / 未實現 / 總報酬;(2) 時序:history 切片、日變動、回撤、對比線、每日統計、今日損益、sparkline、期間損益。前端 `<script>` 載、Action 用 `createRequire` 載;改費率 / 稅率只改這裡 |
| `scripts/update-prices.mjs` | GitHub Action 用:抓市價 + 昨收 + 加權指數、寫回 data.json、記錄 / 回補歷史 |
| `.github/workflows/update-prices.yml` | GitHub Action 設定(備援排程 + 手動 / 外部觸發) |
| `.github/workflows/check.yml` / `tests/` | push 自動跑語法 + 單元測試(Node 三檔 + Python 三支);本機 `node tests/run.mjs` |
| `chips/` + `.github/workflows/chips.yml` | 子專案「盤後籌碼站」:期交所 / 證交所 / 永豐盤後資料,15:40 排程後推 LINE(含庫存段,讀本 repo 的 `data.json`);見 `chips/README.md` |
| `tools/bump.mjs` | 上傳前一鍵:測試 + 換版號(不在 SW 快取清單,純本機工具) |
| `manifest.json` / `sw.js` | PWA 設定 / Service Worker(離線快取) |
| `panghu-icon.png`(192px,iOS apple-touch-icon)/ `panghu-icon.webp`(512px,manifest + splash + intro)/ `favicon.png`(64px) | PWA App 圖示 / 網頁小圖示 |
| `panghu.webp` / `panghu-sad.webp` / `panghu-flat.webp` | 吉祥物表情(笑 / 哭 / 淡定),512px WebP。**`panghu-flat.webp` 目前是笑臉去飽和的佔位圖**,有真的淡定圖直接同名覆蓋即可 |
| (repo 外)`../股票庫存儀表版_原圖備份/` | 原始 1254px PNG 大圖 + 改圖前的 sw.js / manifest.json 備份,不上傳 |
| `cloudflare-worker.js` | **不在 repo**,是貼到 Cloudflare 的外部排程器 |

---

## `data.json` 結構

```jsonc
{
  "title": "胖虎的小財庫",
  "updated": "2026-07-01",            // 最後更新日期
  "priceUpdated": "2026-07-01 11:10", // 最後抓到即時價的台北時間戳
  "fees": { "feeRate": 0.001425, "feeDiscount": 0.4,
            "taxRates": { "個股": 0.003, "ETF": 0.001, "債券ETF-高收益": 0 } },
  "holdings": [
    { "type": "個股", "code": "2330", "name": "台積電",
      "cost": 1707.96, "price": 2490, "lots": 2.33,
      "priceTime": "2026-07-01 11:10",  // 該檔最後即時價時間
      "prevClose": 2475,                // 昨收(算今日漲跌%;由 Action 寫入)
      "yahooSym": ".TW",                // Yahoo 後綴(上市 .TW / 上櫃 .TWO;由 Action 寫入,下次查價直接用)
      "target": 5000, "stop": 1600 }
  ],
  "account": { "餘額": 0, "交割款T1": 0, "交割款T2": 0 },
  "已實現損益": 465709,
  "股息收入": 231270,
  "yearly": [ { "year": "2026", "capitalGain": 4356433, "dividend": 231270, "note": "" } ],
  "history": [
    { "date": "2026-07-01", "mv": 10944100, "cost": 6568347, "un": 4346967,
      "real": 465709, "div": 231270, "ret": 5043946,
      "taiex": 23456.7,   // 加權指數收盤(對比大盤用;由 Action 抓 / 回補)
      "tsmc": 2490,       // 台積電當日價(對比用;由 Action 抓 / 回補)
      "prices": { "2330": 2490, "00981A": 32 },   // 各檔當日價(持股表 sparkline;由 Action 寫入,近 90 筆用 Yahoo 日線回補)
      "pricesMiss": { "00981A": 1 } }             // 回補不到的檔(標了就不再重抓;今日那筆不標)
  ],
  "auth": { "alg": "PBKDF2-SHA256", "salt": "…(base64)", "iter": 210000, "hash": "…(base64)" }
}
```

- **除息日**:Action 從 Yahoo `events.dividends` 抓到今日除息就寫 `holdings[].exDiv = { date, amount }`,前端算今日損益時昨收扣掉股息(除息價差不算虧損),Hero 標「N 檔除息已調整」;過期自動清掉。
- `holdings[].prevClose` / `yahooSym` / `exDiv`、`history[].taiex` / `tsmc` / `taiexMiss` / `tsmcMiss` / `prices` / `pricesMiss` 都是**後端寫入的欄位**;前端缺這些欄位時會**優雅略過**(不顯示今日 %、不畫對比線),不會壞掉。
- `auth` 沒設定時相容舊版 `passwordHash`(無鹽 SHA-256);兩者都沒有(全新 data.json)→ 解鎖直接放行並提示去「⚙️ 設定 → 🔑 設定密碼」。**內建預設密碼已移除**(公開 repo 裡的固定雜湊等於沒鎖)。

---

## 自動更新市價:運作架構

```
Cloudflare Worker(cron,準時) ──呼叫──▶ GitHub workflow_dispatch
        │                                        │
        │                                  GitHub Action 執行
        │                              scripts/update-prices.mjs
        │                      (Yahoo 即時 → MIS → 證交所/櫃買收盤補新標的)
        ▼                                        │
  台北 09:00–13:45 每 15 分            寫回 data.json + commit
                                                 │
                                         GitHub Pages 重新部署
                                                 │
                                          儀表板讀到最新價
```

`update-prices.mjs` 行為重點:

- **價格來源順序**:Yahoo `regularMarketPrice`(即時)→ 證交所 MIS `z`/`pz`(即時)→ 證交所 / 櫃買 OpenAPI 收盤(**僅用來補「完全沒有價格」的新標的**)。**只有即時價能覆蓋現有價格**,避免被舊收盤價蓋回去。
- **只認「今日」的即時價**:Yahoo 看 `regularMarketTime`、MIS 看 `d`(資料日),最後成交日不是台北今天(平日國定假日休市)就不算即時價 → 不寫檔、不會多一根假日 history、時間戳不前進。
- **Yahoo 各檔並行查**,查到的後綴記在 `holdings[].yahooSym`(`.TW` 上市 / `.TWO` 上櫃),下次直接用;`fetchJson` 對逾時 / 429 / 5xx 自動重試一次。
- **昨收**:Yahoo `previousClose` / MIS `y` 存進各檔 `prevClose`(前端算今日漲跌 %)。
- **加權指數 / 台積電**:每次抓 `^TWII` 現值與 2330 現值寫進當天 history;並用 `fetchYahooDailyClose()` 抓歷史日收盤,**自動回補** history 裡還沒有 `taiex` / `tsmc` 的舊日期(自我修復,一次補齊 6/15 以來)。補不到的(Yahoo 該日無資料或超過 6 個月)標 `taiexMiss` / `tsmcMiss`,之後不再為它重抓;今日那筆不標。
- **歷史**:每次把 `{date, mv, cost, un, real, div, ret, taiex, tsmc}` 存進 `history`(同一天只留最新一筆)。
- **週末防呆**:腳本在台北週六 / 日直接跳過;平日休市由上面「只認今日」的檢查擋。
- **時間戳**:`priceUpdated` 與各檔 `priceTime` 用台北時間(`taipeiStamp()`,`Date.now()+8h` 手算,不依賴 runner 時區)。
- **寫檔條件**:`liveHit>0 || changed>0` 才寫(抓不到即時價就不動,時間戳不前進 = 即時來源不通)。

### 為什麼用 Cloudflare Worker?

GitHub 內建 `schedule` 排程**不可靠**(常延遲數小時、漏跑、在奇怪時間跑)。所以改用 **Cloudflare Worker cron** 準時觸發 GitHub Action;GitHub Action 自己的 `schedule` 保留當備援(`.yml` 內 `5,20,35,50 1-6 * * *`)。

### 排程時間(都用 UTC,台北 = UTC + 8)

| cron(UTC) | 台北時間 | 用途 |
|---|---|---|
| `*/15 1-5 * * *` | 09:00–13:45 每 15 分 | 交易時段更新(Cloudflare) |
| `0 6 * * *` | 14:00 | 收盤結算(Cloudflare) |

> Cloudflare「星期幾」編號易混淆,所以排成「每天」(`*`),由腳本擋掉週末。

---

## 前端載入資料的順序(`index.html` §17 `init()`)

0. 有 localStorage 快取(上次成功載入的資料)**先畫出來,零等待**;下面任一來源成功就無縫換成最新(內容有變才 toast「已更新為最新資料」)。
1. 若這個瀏覽器有設定 GitHub 同步 → 讀 **repo 上的 data.json**(不受 Pages 部署延遲影響),並在**交易時段內**(平日 09:10–14:10 台北)順手觸發一次更新市價;盤後 / 週末不觸發,省 Action。
2. 否則 `fetch('data.json')`(需要 http 伺服器 / GitHub Pages;`file://` 會被瀏覽器擋),最多等 8 秒。
3. 否則用記住的檔案 handle(File System Access)。
4. 都不行 → 有快取就停在快取並提示「⚠ 無法取得最新資料」;沒快取才請使用者選檔 / 拖檔。

---

## 程式碼分段(`index.html` 的 `<script>`,用 `§` 搜尋跳段)

| § | 內容 | § | 內容 |
|---|---|---|---|
| §1 | 全域狀態、常數、小工具 | §10 | 市價更新(觸發 Action) |
| §2 | 數字跳動動畫 | §11 | 持股 / 年度編輯操作 |
| §3 | 計算(委派 `scripts/calc.js`) | §12 | 儲存 / 載入 / 快取 |
| §5 | 圖表:見 `charts.js`(1 色盤 → 2 helper → 3 plugin → 4 drawXxx → 5 drawCharts) | §16b | 事件委派(`data-action`) |
| §4 | 畫面 render | §13 | GitHub 同步 |
| §5 | (已搬到 `charts.js`) | §14 | 檔案存取(存檔 / 選檔);§14b 分享戰報 |
| §6 | 分頁切換 | §15 | 主題 / 圖表風格切換 |
| §7 | 編輯模式 | §16 | 下拉重新整理(PWA) |
| §8 | 密碼(PBKDF2) | §17 | 啟動(splash + init) |
| §9 | 解鎖 / 權限 UI | | |

主題色盤在 `charts.js` 的 `CHART_PALETTES`;每個主題有 `slices / dividend / grid`。**漲跌色不在 palette**,圖表一律讀 CSS 變數 `--up / --down`(主題定義;「色弱友善」開關 `html.cvd` 覆寫成橘 / 藍)。slices 前五色與各主題的漲跌對都跑過 dataviz `validate_palette.js`:相鄰 CVD ΔE ≥ 8、正常視力 ≥ 15(cute 漲跌對 7.1,靠 +/- 符號當第二編碼);深色 / 粉嫩主題的「亮度帶」檢查刻意不過,那是風格本質。極值 / 賺賠最多 / 回撤谷底一律用 `--accent`,不另開 hue。`charts.js` 慣例:每張圖一支 `drawXxx(T)`,`T = chartTheme()` 帶當前主題的顏色 / 字型;tooltip / 座標軸 / 圖例用 `tooltipOpts / axisX / axisY / legendBottom` factory,不再各自複製;alpha 用 `withAlpha(color, a)` 不拼 hex 字尾;不改 `Chart.defaults`(只設一次 dpr / 字型)。八張圖都經 `upsertChart()`:同 canvas 同 type 就 `update()`(換主題 / 切區間有過場、不重建),inline plugin 參數一律走 `options.plugins.<id>`,不可用 closure 抓外部變數(update 不會換 plugin)。排序持股表 / 隱藏零股走 `render({ charts: false })` 不重畫圖。`styles.css` 的 `--total-bg / --row-hover` 由 `--accent` 經 `color-mix` 自動算(深色主題 `--tint` 調高),不必每套主題各寫。tooltip 文字色**跟著 tooltip 底色**走(深底亮字、白底深字),不受頁面主題影響。

---

## 部署 / 設定備忘

1. **GitHub Pages**:repo → Settings → Pages,來源設 `main` 分支根目錄。
2. **GitHub Token**(fine-grained PAT,只給此 repo):`Contents: Read and write`(存檔)+ `Actions: Read and write`(觸發 workflow_dispatch)。用於儀表板「⚙️ 設定 → GitHub 同步」與 Cloudflare 的 `GH_TOKEN`。
3. **GitHub Action 權限**:repo → Settings → Actions → Workflow permissions → **Read and write**。
4. **Cloudflare Worker**:貼上 `cloudflare-worker.js`(一支管收盤價與籌碼站兩個 workflow,依 cron 字串分流);Secret `GH_TOKEN` = 上面的 token;Cron Triggers `*/15 1-5 * * *`、`0 6 * * *`(收盤價)+ `40 7 * * 1-5`、`40 8 * * 1-5`(籌碼站)。
5. **PWA 安裝**:手機開 Pages 網址 → 加入主畫面(需 https)。

---

## 安全性說明

- `data.json` 在**公開 repo**,任何人都讀得到(持股、金額等)。前端密碼只是 UI 遮罩,擋不住直接讀檔。
- 防止他人**竄改**資料靠的是 GitHub 的寫入權限 / token —— 沒有 token 誰都存不回 repo。
- 密碼雜湊用 **PBKDF2-SHA256 + 隨機鹽**(解鎖後可到「⚙️ 設定 → 🔑 設定密碼」);相容舊版 SHA-256。
- token 只存在你裝置的瀏覽器(localStorage)與 Cloudflare Secret,不在 repo 內。

---

## 常見維護 / 踩過的坑

- **本機雙擊 `index.html`(file://)看不到最新資料**:`file://` 下瀏覽器擋掉 `fetch('data.json')`,會退回讀舊快取。要在本機看最新,開小伺服器:資料夾內 `python -m http.server 8000` → 瀏覽器開 `http://localhost:8000/`;或直接看線上 Pages。
- **上傳用「Upload files」拖檔,別用網頁編輯器貼**:貼上曾造成檔案截斷 / 前後不一致(YAML、index.html 都發生過)。
- **`data.json` 以 repo 為正本**:排程會 commit 到 repo,本機那份會落後。**別拿本機蓋 repo**(會蓋掉新價與新歷史)。要同步就從 repo 下載覆蓋本機。
- **看不到更新(圖示 / 靜態檔)**:`sw.js` 對圖片走 stale-while-revalidate:第一次 F5 回舊快取、背景抓新版,**再按一次 F5 就是新的**;PWA 關 App 重開兩次同理。.js / .css 有 `?v=` 版本 query,`index.html` 換了 v 就一定抓新檔,不受這條影響。
  改了圖或 `sw.js` 本身,順手把 `sw.js` 的 `CACHE = 'panghu-vN'` 版號 +1,activate 會整包清掉舊快取,一次到位。
  (`Ctrl + F5` 是繞過 Service Worker 直接打網路,所以看得到新圖,但不會寫回 SW 快取,下次 F5 又舊——這是舊版 cache-first 的症狀,v2 起已改。)
- **Action push 被 reject**:儀表板手動「儲存」直接 PUT 到 repo,若剛好落在 Action checkout 與 push 之間,push 會被拒。workflow 已加 `git pull --rebase` + 重試 3 次;若三次都失敗(同檔衝突)才會紅,下一輪排程會重抓。
- **`raw.githubusercontent.com` 有 CDN 快取**(數分鐘),剛 push 完可能抓到舊版,別誤判成「沒上傳成功」。
- **GitHub Actions 清單時間是 UTC**,+8 才是台北;最準看自動更新 commit 訊息(台北時間)。
- **盤後 / 假日**:抓到的是收盤價,`價格變動 0` 屬正常;假日無 taiex → 走勢圖該日不畫。
- **新功能要等排程**:今日漲跌 %、對比大盤(taiex/tsmc)需要 `update-prices.mjs` 跑過寫入新欄位,**下次排程後**才會出現;在那之前前端自動略過。

---

## 改動後要上傳哪些檔

- 改**版面 / 互動** → 上傳 `index.html` / `styles.css` / `app.js`;改**圖表** → `charts.js`。**同時把版本 query 換掉**:`index.html` 四處 `?v=YYYYMMDDx` 與 `sw.js` 的 `ASSET_VER` 改成同一個新值,`CACHE` 版號 +1。不換 v 的後果是「新 app.js 配舊 calc.js」:Service Worker 把舊 calc.js 從快取吐出來,頁面第一次開會卡在載入畫面(2026-09-22 實際發生過一次)。
- 改**損益計算 / 費率規則 / 時序計算** → 上傳 `scripts/calc.js` + `sw.js`(CACHE 版號 +1)。
- 改**抓價 / 歷史 / 回補邏輯** → 上傳 `scripts/update-prices.mjs`。
- 改**排程** → 上傳 `.github/workflows/update-prices.yml`(Cloudflare 那份在 Cloudflare 後台改)。
- 改**圖示 / 吉祥物圖** → 上傳新圖 + `sw.js`(CACHE 版號 +1);換檔名的話 `index.html` / `manifest.json` / `intro.html` 引用也要一起。
- `data.json` 一般**不用手動上傳**(交給排程);除非要改持股 / 年度等,建議用儀表板編輯模式存回 repo。
