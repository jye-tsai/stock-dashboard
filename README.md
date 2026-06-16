# 胖虎的小財庫 🐶📈

純前端的台股庫存儀表板,部署在 GitHub Pages,資料存在 `data.json`,市價由 GitHub Action 自動更新。

> 線上網址:`https://jye-tsai.github.io/stock-dashboard/`

---

## 功能

- **總覽**:總報酬甜甜圈(未實現/已實現/股息)、市值比例、年度損益、資產走勢折線、持股損益。
- **持股明細**:可點欄位排序、點列展開明細(賣出可拿回、目標/停損距離);手機自動轉卡片。
- **目標價 / 停損價**:每檔可設,到價時整列標記 🎯 / ⚠️。
- **數字跳動動畫**、**載入骨架屏**、**下拉重新整理**(手機)。
- **7 種主題**:🌊 海洋藍、🌅 珊瑚暖陽、🌿 抹茶清新、🌌 午夜金、🍡 馬卡龍、🌙 美少女、🧬 Agent Neon;標題會發光。
- **胖虎吉祥物**:依「今日未實現損益 vs 昨日」換表情(賺→笑、賠→哭)。
- **PWA**:可安裝到手機主畫面、全螢幕、離線看上次資料。
- **編輯模式**:解鎖後可改標題、持股、年度、帳戶、目標/停損,存回 GitHub。

---

## 檔案結構

| 檔案 | 用途 |
|---|---|
| `index.html` | 整個儀表板(HTML/CSS/JS 單檔) |
| `data.json` | 資料來源(持股、年度、帳戶、歷史、密碼等) |
| `scripts/update-prices.mjs` | GitHub Action 用:抓市價、寫回 data.json、記錄歷史 |
| `.github/workflows/update-prices.yml` | GitHub Action 設定(備援排程 + 手動/外部觸發) |
| `manifest.json` / `sw.js` | PWA 設定 / Service Worker(離線快取) |
| `panghu-icon.png` | PWA App 圖示 |
| `panghu.png` / `panghu-sad.png` | 吉祥物表情(笑 / 哭);可選 `panghu-flat.png`(淡定) |
| `cloudflare-worker.js` | **不在 repo**,是貼到 Cloudflare 的外部排程器 |

---

## 自動更新市價:運作架構

```
Cloudflare Worker(cron,準時) ──呼叫──▶ GitHub workflow_dispatch
        │                                        │
        │                                   GitHub Action 執行
        │                                update-prices.mjs
        │                          (Yahoo 即時 → MIS → 證交所/櫃買收盤)
        ▼                                        │
   台北 09:00–13:45 每 15 分            寫回 data.json + commit
                                                 │
                                         GitHub Pages 重新部署
                                                 │
                                          儀表板讀到最新價
```

- **價格來源順序**:Yahoo `regularMarketPrice`(即時)→ 證交所 MIS(即時)→ 證交所/櫃買 OpenAPI(收盤,僅用來補沒有價格的新標的)。**只有即時價能覆蓋現有價格**,避免被舊收盤價蓋回去。
- **歷史**:每次更新把 `{date, mv, cost, un, real, div, ret}` 存進 `data.json.history`(供資產走勢圖)。
- **週末防呆**:腳本在台北週六/日自動跳過,不更新。
- **時間戳**:`priceUpdated` 與各檔 `priceTime` 用台北時間(UTC+8 手算)。

### 為什麼用 Cloudflare Worker?

GitHub 內建的 `schedule` 排程**不可靠**(常延遲數小時、漏跑、在奇怪時間跑)。所以改用 **Cloudflare Worker 的 cron** 準時去觸發 GitHub Action。GitHub Action 自己的 `schedule` 保留當備援。

### 排程時間(都用 UTC,台北 = UTC + 8)

| cron(UTC) | 台北時間 | 用途 |
|---|---|---|
| `*/15 1-5 * * *` | 09:00–13:45 每 15 分 | 交易時段更新(Cloudflare) |
| `0 6 * * *` | 14:00 | 收盤結算(Cloudflare) |

> Cloudflare 的「星期幾」編號易混淆,所以排成「每天」(`*`),由腳本擋掉週末。

---

## 部署 / 設定備忘

1. **GitHub Pages**:repo 設定 → Pages,來源設 `main` 分支根目錄。
2. **GitHub Token**(fine-grained PAT,只給此 repo):
   - `Contents: Read and write`(儀表板存檔)
   - `Actions: Read and write`(觸發 workflow_dispatch)
   - 用於:儀表板「⚙️ GitHub」同步、Cloudflare Worker 的 `GH_TOKEN`。
3. **GitHub Action 權限**:repo → Settings → Actions → Workflow permissions → **Read and write**。
4. **Cloudflare Worker**:
   - 貼上 `cloudflare-worker.js`。
   - Secret:`GH_TOKEN` = 上面的 token。
   - Cron Triggers:`*/15 1-5 * * *`、`0 6 * * *`。
5. **PWA 安裝**:用手機開 Pages 網址 → 加入主畫面(需 https,本機 file:// 無安裝功能)。

---

## 安全性說明

- `data.json` 在**公開 repo**,任何人都讀得到(持股、金額等)。前端密碼只是 UI 遮罩,擋不住直接讀檔。
- **防止他人「竄改」資料**靠的是 GitHub 的寫入權限 / token —— 沒有 token 任何人都存不回 repo。
- 密碼雜湊用 **PBKDF2-SHA256 + 隨機鹽**(解鎖後可按「🔑 設定密碼」設定);相容舊版 SHA-256。
- token 只存在你裝置的瀏覽器(localStorage)與 Cloudflare Secret,不在 repo 內。

---

## 常見維護

- **改完檔案要重新上傳到 repo**,Pages 才會更新;手機 App 開啟時(有網路)會自動抓最新版。
- **看不到更新**:多半是瀏覽器快取 → `Ctrl + F5` 強制重整。
- **GitHub Actions 清單時間是 UTC**,+8 才是台北;最準的對時看自動更新 commit 訊息(台北時間)。
- **想手動更新市價**:儀表板按「📈 更新市價」,或直接打開 Cloudflare Worker 網址。
- **盤後 / 假日**:抓到的是收盤價,`價格變動 0` 屬正常。
