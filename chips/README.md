# 台股日報・盤後籌碼站

收盤後自動抓 期交所（三大法人 OI／選擇權／P/C）＋證交所（指數／法人買賣超／融資）＋永豐盤後快訊 PDF，
整理成今昨對照表，一鍵「複製給 Claude」出圖。

## 三步上線
1. 把 `chips/` 資料夾與 `.github/workflows/chips.yml` 放進 stock-dashboard repo 後 push。
2. **Settings → Pages**：Source 選 `Deploy from a branch`，Branch 選 `main` / `(root)`，存檔。
3. **Actions** 分頁 → 左側「台股盤後籌碼抓取」→ `Run workflow` 跑第一次。
   之後每個交易日 15:40、16:40 自動跑；網址 `https://jye-tsai.github.io/stock-dashboard/chips/`。

## 頁面上「▶ 立即抓取」按鈕
需要一個 Fine-grained PAT（只勾這個 repo 的 **Actions: Read and write**）。
儀表板若已在 ⚙️ 設定 GitHub 同步，這頁**自動借用同一把 token**，不用再填；要用另一把才到這頁 ⚙️ 填。手動觸發帶 `source=manual`，不會 LINE 通知。
不設也沒差，去 Actions 分頁按 Run workflow 一樣。

## 每天流程
收盤 → 開網頁 → 確認日期是今天 → 「📋 複製給 Claude」→ 貼到對話（永豐 PNG 可一併拖給 Claude 對照）。

## 排程
跟收盤價一樣：**Cloudflare Worker 準時打 `workflow_dispatch`**（台北 15:40、16:40，帶 `inputs.source=cron`），GitHub 自己的 `schedule` 當備援（會漂移）。Worker 程式在本機 `cloudflare-worker.js`（不進 repo），Cron Triggers 加 `40 7 * * 1-5` 與 `40 8 * * 1-5`（UTC）。
舊圖：每次抓完會刪「當日不在清單裡的 png」與「30 天前的 png」，repo 不會被 PDF 轉圖越撐越肥。

## LINE 通知
只在 **15:40 排程或 Cloudflare cron 那班**推一則（免費方案每月 200 則；手動 Run workflow 與頁面「立即抓取」不通知），同一交易日不重發（`data/notified.json`）。
內容 = 盤後數據摘要 ＋ **庫存段**（每檔 代號 名稱 收盤 今日% 未實現，加 今日損益 / 總市值 / 總報酬；讀 repo 根目錄 `data.json`，同前端金鑰解密）。
Secrets：`LINE_CHANNEL_TOKEN`、`LINE_USER_ID`（Messaging API，LINE Notify 已停）。本機預覽：`python chips/scripts/notify.py --dry-run`。

## 出錯時
Actions 失敗會寄 email。把紅字貼給 Claude 修 `scripts/fetch_all.py` 即可；
每個資料源各自 try/except，一個掛掉不影響其他欄位（會標 —）。
