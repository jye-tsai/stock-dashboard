# 胖虎的小財庫 🐶📈

純前端的台股庫存儀表板,部署在 GitHub Pages,資料存在 `data.json`,市價由 GitHub Action 在伺服器端自動更新。

> 線上網址:`https://jye-tsai.github.io/stock-dashboard/`
> Repo:`jye-tsai/stock-dashboard`(分支 `main`)
> 本機工作目錄:`Desktop/mygithub/股票庫存儀表版`

---

## 快速定位（給接手的人 / 新的 Claude session)

先讀這段就能接手。細節在後面各節。

- **整個 App 就是一個 `index.html`**(HTML + CSS + JS 全部內嵌,單檔約 2500+ 行)。JS 在檔案下半部的 `<script>` 裡,最上面有「§ 目錄」;用編輯器 **Ctrl+F 搜 `§`** 可跳段(§1~§17,見〈程式碼分段〉)。
- **市價不是前端抓的**——瀏覽器受 CORS 限制抓不到證交所/Yahoo。市價由 **GitHub Action 跑 `scripts/update-prices.mjs`** 在伺服器端抓,寫回 `data.json` 並 commit;由 **Cloudflare Worker 的 cron** 準時觸發(GitHub 自己的 schedule 當備援)。
- **`data.json` 的正本在 repo**,不是本機。排程會直接 commit 到 repo。本機那份常是舊的,**不要拿本機蓋 repo**。
- **改完要重新上傳到 repo**(用 GitHub「Upload files」拖檔,**別用網頁編輯器貼**,貼上容易截斷)。
- **驗證 JS 語法**的方法(因為 JS 內嵌在 html):擷取 `<script>let DATA … </script>` 段落丟 `node --check`。
- **已知環境雷**:某些沙箱 / 掛載會顯示 `index.html` / `.mjs` 的**殘檔或舊版**(行數不對、node 檢查報怪錯)。這不是檔案壞掉——以編輯器/檔案工具讀到的內容為準,別被殘檔誤導。

---

## 功能

- **總覽**:今日損益 Hero 置頂(今日賺賠大字 + 總市值 + 總報酬;各檔 `prevClose` 加總,缺昨收退回比 history 前一交易日市值)、總報酬橫向堆疊條(未實現 / 已實現 / 股息)、市值比例甜甜圈、年度損益、資產走勢、每日市值變動、報酬對比大盤、摘要卡片列(帳戶餘額 / 交割款併入,解鎖後顯示)、持股損益。
- **持股明細**:可點欄位排序、點列展開明細(賣出可拿回、目標 / 停損距離);市價下方顯示**今日漲跌 %**;手機自動轉卡片。
- **目標價 / 停損價**:每檔可設,到價時整列標記 🎯 / ⚠️。
- **資料過期警示**:頁首更新時間旁,今日已更新亮綠點 ●;交易日過了還沒更新顯示紅底「⚠ 資料可能未更新」(週末 / 開盤前不誤報)。
- **數字跳動動畫**、**載入骨架屏**、**下拉重新整理**(手機)、**底部分頁列**(手機寬度時取代頂部頁籤,總覽 / 持股 / 年度固定在螢幕下緣)。
- **7 種主題**:🌊 海洋藍、🌅 珊瑚暖陽、🌿 抹茶清新、🌌 午夜金、🍡 馬卡龍、🌙 美少女、🧬 Agent Neon;標題會發光。圖表配色隨主題(含極值高亮色 `hi`/`lo`)。
- **工具列收納**:頁面主題、圖表風格、GitHub 同步、載入 JSON、設定密碼都收在「⚙️ 設定」視窗;header 只留 解鎖(→ 編輯)/ 儲存 / 更新市價 / ⚙️ 設定 / 登出。
- **胖虎吉祥物**:依「今日未實現損益 vs 昨日」換表情(賺 → 笑、賠 → 哭、持平 → 淡定)。
- **PWA**:可安裝到手機主畫面、全螢幕、離線看上次資料。
- **編輯模式**:解鎖後可改標題、持股、年度、帳戶、目標 / 停損,存回 GitHub。

### 三張走勢圖(總覽下方)

1. **資產走勢**:堆疊面積 = 成本 + 未實現損益,合計 ≈ 總市值(白色加粗虛線標總市值天花板),並標該區間**最高 / 最低**點。Y 軸自 0 起。
2. **每日市值變動**:柱狀,較前一日增減,紅漲綠跌;區間內**漲最多 / 跌最多**用高亮色(`palette.hi`/`lo`)+ 文字標示。
3. **報酬對比**:以區間起點為 0% 正規化的折線 —— **我的組合 vs 加權指數 vs 台積電**,一眼看出有沒有贏大盤 / 贏單壓台積電。

三圖共用同一組時間範圍(近 1 月 / 近 3 月 / 全部)與同一份 `hist`;桌機寬度(> 800px)時每日變動與報酬對比左右並排;**週末**一律不畫,**有 taiex 之後**沒 taiex 的日期(國定假日休市)也不畫。

---

## 檔案結構

| 檔案 | 用途 |
|---|---|
| `index.html` | 整個儀表板(HTML / CSS / JS 單檔) |
| `data.json` | 資料來源(持股、年度、帳戶、歷史、密碼等);**正本在 repo** |
| `scripts/update-prices.mjs` | GitHub Action 用:抓市價 + 昨收 + 加權指數、寫回 data.json、記錄 / 回補歷史 |
| `.github/workflows/update-prices.yml` | GitHub Action 設定(備援排程 + 手動 / 外部觸發) |
| `manifest.json` / `sw.js` | PWA 設定 / Service Worker(離線快取) |
| `panghu-icon.png` / `favicon.png` | PWA App 圖示 / 網頁小圖示 |
| `panghu.png` / `panghu-sad.png` / `panghu-flat.png` | 吉祥物表情(笑 / 哭 / 淡定) |
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
      "tsmc": 2490 }      // 台積電當日價(對比用;由 Action 抓 / 回補)
  ],
  "auth": { "alg": "PBKDF2-SHA256", "salt": "…(base64)", "iter": 210000, "hash": "…(base64)" }
}
```

- `holdings[].prevClose`、`history[].taiex`、`history[].tsmc` 都是**後端寫入的欄位**;前端缺這些欄位時會**優雅略過**(不顯示今日 %、不畫對比線),不會壞掉。
- `auth` 沒設定時相容舊版 `passwordHash`(無鹽 SHA-256);再舊則用內建預設雜湊。

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
- **昨收**:Yahoo `previousClose` / MIS `y` 存進各檔 `prevClose`(前端算今日漲跌 %)。
- **加權指數 / 台積電**:每次抓 `^TWII` 現值與 2330 現值寫進當天 history;並用 `fetchYahooDailyClose()` 抓歷史日收盤,**自動回補** history 裡還沒有 `taiex` / `tsmc` 的舊日期(自我修復,一次補齊 6/15 以來)。
- **歷史**:每次把 `{date, mv, cost, un, real, div, ret, taiex, tsmc}` 存進 `history`(同一天只留最新一筆)。
- **週末防呆**:腳本在台北週六 / 日自動跳過。
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

1. 若這個瀏覽器有設定 GitHub 同步 → 讀 **repo 上的 data.json**(不受 Pages 部署延遲影響),並順手觸發一次更新市價。
2. 否則 `fetch('data.json')`(需要 http 伺服器 / GitHub Pages;`file://` 會被瀏覽器擋)。
3. 否則用記住的檔案 handle(File System Access)。
4. 否則用 localStorage 快取(上次成功載入的資料)。
5. 都不行 → 請使用者選檔 / 拖檔。

---

## 程式碼分段(`index.html` 的 `<script>`,用 `§` 搜尋跳段)

| § | 內容 | § | 內容 |
|---|---|---|---|
| §1 | 全域狀態、常數、小工具 | §10 | 市價更新(觸發 Action) |
| §2 | 數字跳動動畫 | §11 | 持股 / 年度編輯操作 |
| §3 | 計算(市值 / 損益 / 比例) | §12 | 儲存 / 載入 / 快取 |
| §4 | 畫面 render | §13 | GitHub 同步 |
| §5 | 圖表繪製與風格 | §14 | 檔案存取(存檔 / 選檔) |
| §6 | 分頁切換 | §15 | 主題 / 圖表風格切換 |
| §7 | 編輯模式 | §16 | 下拉重新整理(PWA) |
| §8 | 密碼(PBKDF2) | §17 | 啟動(splash + init) |
| §9 | 解鎖 / 權限 UI | | |

主題色盤在 `CHART_PALETTES`(§5 上方);每個主題有 `slices / gain / loss / dividend / grid / hi / lo`。tooltip 文字色**跟著 tooltip 底色**走(深底亮字、白底深字),不受頁面主題影響。

---

## 部署 / 設定備忘

1. **GitHub Pages**:repo → Settings → Pages,來源設 `main` 分支根目錄。
2. **GitHub Token**(fine-grained PAT,只給此 repo):`Contents: Read and write`(存檔)+ `Actions: Read and write`(觸發 workflow_dispatch)。用於儀表板「⚙️ 設定 → GitHub 同步」與 Cloudflare 的 `GH_TOKEN`。
3. **GitHub Action 權限**:repo → Settings → Actions → Workflow permissions → **Read and write**。
4. **Cloudflare Worker**:貼上 `cloudflare-worker.js`;Secret `GH_TOKEN` = 上面的 token;Cron Triggers `*/15 1-5 * * *`、`0 6 * * *`。
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
- **看不到更新**:多半是快取 → `Ctrl + F5`;PWA(加到主畫面)要**關掉 App 重開**才會抓新版。
- **`raw.githubusercontent.com` 有 CDN 快取**(數分鐘),剛 push 完可能抓到舊版,別誤判成「沒上傳成功」。
- **GitHub Actions 清單時間是 UTC**,+8 才是台北;最準看自動更新 commit 訊息(台北時間)。
- **盤後 / 假日**:抓到的是收盤價,`價格變動 0` 屬正常;假日無 taiex → 走勢圖該日不畫。
- **新功能要等排程**:今日漲跌 %、對比大盤(taiex/tsmc)需要 `update-prices.mjs` 跑過寫入新欄位,**下次排程後**才會出現;在那之前前端自動略過。

---

## 改動後要上傳哪些檔

- 改**畫面 / 圖表 / 互動** → 上傳 `index.html`。
- 改**抓價 / 歷史 / 回補邏輯** → 上傳 `scripts/update-prices.mjs`。
- 改**排程** → 上傳 `.github/workflows/update-prices.yml`(Cloudflare 那份在 Cloudflare 後台改)。
- `data.json` 一般**不用手動上傳**(交給排程);除非要改持股 / 年度等,建議用儀表板編輯模式存回 repo。
