# 台股日報・盤後籌碼站

收盤後自動抓 期交所（三大法人 OI／選擇權／P/C）＋證交所（指數／法人買賣超／融資）＋永豐盤後快訊 PDF，
整理成今昨對照表，一鍵「複製給 Claude」出圖。

## 三步上線
1. 把 `chips/` 資料夾與 `.github/workflows/chips.yml` 放進 stock-dashboard repo 後 push。
2. **Settings → Pages**：Source 選 `Deploy from a branch`，Branch 選 `main` / `(root)`，存檔。
3. **Actions** 分頁 → 左側「台股盤後籌碼抓取」→ `Run workflow` 跑第一次。
   之後每個交易日 15:40、16:40 自動跑；網址 `https://jye-tsai.github.io/stock-dashboard/chips/`。

## 頁面上「▶ 立即抓取」按鈕
需要一個 Fine-grained PAT（只勾這個 repo 的 **Actions: Read and write**），
在頁面 ⚙️ 填入帳號／repo／token，只存在你的瀏覽器 localStorage。
不設也沒差，去 Actions 分頁按 Run workflow 一樣。

## 每天流程
收盤 → 開網頁 → 確認日期是今天 → 「📋 複製給 Claude」→ 貼到對話（永豐 PNG 可一併拖給 Claude 對照）。

## 出錯時
Actions 失敗會寄 email。把紅字貼給 Claude 修 `scripts/fetch_all.py` 即可；
每個資料源各自 try/except，一個掛掉不影響其他欄位（會標 —）。
