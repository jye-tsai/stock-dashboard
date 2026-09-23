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
跟收盤價一樣：**Cloudflare Worker 準時打 `workflow_dispatch`**（台北 15:40、16:40，帶 `inputs.source=cron`），GitHub 自己的 `schedule` 當備援（會漂移）。Worker 程式在本機 `cloudflare-worker.js`（不進 repo），Cron Triggers 加 `40 7 * * 2-6` 與 `40 8 * * 2-6`（UTC；**Cloudflare 星期欄 1=日 … 7=六**，跟 GitHub 的 0=日不同，寫 `1-5` 會變週日～週四）。
舊圖：每次抓完會刪「當日不在清單裡的 png」與「30 天前的 png」，repo 不會被 PDF 轉圖越撐越肥。

## 回補歷史（20 日走勢）
Actions → chips → Run workflow，`backfill` 填 20 跑一次即可，往回補 20 個交易日（期交所 / 證交所歷史都能按日查；永豐 PDF 只有當日，回補不抓）。已存在的日子不覆蓋，不動 `latest.json`，不會 LINE 通知。本機：`python chips/scripts/fetch_all.py --backfill 20`。

## 胖虎指標與自動紀律
每天盤後依 13 項指標判斷**情境**：趨勢、外資現貨、外資期貨多單、外資期貨空單、美元兌台幣、美元指數、量能、價量配合、散戶多空比、P/C(OI)、VIX、融資、基差。每項有多個情境（例如趨勢有強勢多頭、剛站上、站上回測、盤整、剛跌破、超跌等 11 種），情境決定分數（−2～+2）與說法，乘權重加總映射成 0～100 溫度。
**建議倉位**：溫度 20 以下空手、80 以上滿倉，中間線性對應、每 10% 一級（一成～九成）；要越過目前級距邊界 3 分才換級，加碼另需外資現貨買超，避免天天跳動。
**紀律**：防線 = 20 日均線與近 10 日最低收盤取高者、第二道 = 近 20 日最低收盤；跌破防線降兩級（首日跌破但溫度仍 ≥ 60 先觀察一天）、跌破第二道空手。動作句有十種：跌破第二道、跌破防線、假跌破觀察、外資未買超暫不加碼、升級、降級、滿倉、空手、連 N 日維持、維持。
情境、分數、門檻、權重、級距、動作句全部在 `chips/panghu.json`，改那裡就好，不用動程式。網頁、LINE、週報都只看胖虎指標，沒有手寫部位檔。
這是機械式指標加總，不是投資建議；實際下不下單是人的事。匯率來源 Yahoo（`TWD=X`、`DX-Y.NYB`），一次抓三個月日線快取。

## 回測（驗證胖虎指標）
GitHub → Actions → **backtest** → Run workflow。預設抓兩年逐日資料（約 40～80 分鐘，抓不完會存進度，再跑一次接著抓），依目前的 `chips/panghu.json` 重算每一天的胖虎指標，報告頁在 `chips/backtest/`（籌碼站胖虎指標卡的「📊 回測」）。
報告內容：策略績效（照建議倉位操作 vs 全程滿倉 vs 固定五成，含第一年樣本內 / 第二年樣本外）、淨值曲線、溫度分組之後的報酬、各指標分數與之後報酬的相關、每個情境出現次數與之後表現（標出「方向不符」）。
改了 `panghu.json` 之後，Run workflow 時 `eval_only` 填 `true`，幾秒就重算完，不用重抓。
限制：台指 VIX 官方只留近 3 個月，回測期間大多沒有，該項不計分；「15:40 版」模擬發 LINE 當下，融資尚未公布不計分；決策後隔日收盤才換倉；加權為價格指數不含股息。

## 台指 VIX
來源是期交所官方月檔 `Dailydownload/vix/log2data/YYYYMMnew.txt`（big5、tab 分隔，欄位為交易日期 / 時間 / 波動率指數 / 收盤前 1 分鐘平均），值與永豐快訊的「VIX 指標」一致。官方只留近 3 個月，更早的日子抓不到就留空。
歷史日子要補 VIX，跑 Run workflow 時 `backfill` 填天數並把 `force` 設 `true`（會重寫已存在的當日 json）。

## 今日解讀（價量 / 籌碼）
`fetch_all.py` 每天用已收的欄位算五項並存進當日 json 的 `insight`：量能水位（今日量 vs 近 20 日均量）、價量配合四象限、融資 vs 指數 5 日、外資現貨連買 / 連賣與指數背離、基差 vs 近 5 日均。頁面「今日解讀」卡與 LINE 訊息共用這份，不各算各的。回補的歷史日子沒有這欄，卡片會自動隱藏。
主頁的法人 / 融資 / 散戶多空比 / P/C 等數值可以點，原地展開該指標近 10 日走勢；「20 日走勢」六張圖預設收起。

## LINE 通知
只在 **15:40 排程或 Cloudflare cron 那班**推一則（免費方案每月 200 則；手動 Run workflow 與頁面「立即抓取」不通知），同一交易日不重發（`data/notified.json`）。
內容 = 盤後數據摘要 ＋ **庫存段**（每檔 代號 名稱 收盤 今日% 未實現，加 今日損益 / 總市值 / 總報酬；讀 repo 根目錄 `data.json`，同前端金鑰解密）。
Secrets：`LINE_CHANNEL_TOKEN`、`LINE_USER_ID`（Messaging API，LINE Notify 已停）。本機預覽：`python chips/scripts/notify.py --dry-run`。

## 出錯時
Actions 失敗會寄 email。把紅字貼給 Claude 修 `scripts/fetch_all.py` 即可；
每個資料源各自 try/except，一個掛掉不影響其他欄位（會標 —）。
