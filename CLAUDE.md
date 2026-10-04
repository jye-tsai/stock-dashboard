# 給 Claude 的固定指示(每次對話自動讀到)

你沒有跨對話記憶。這份檔就是記憶:使用者的習慣、固定流程、別踩的雷都寫在這裡。專案全貌看 `README.md`(先讀「快速定位」那段)。

## 使用者說「看盤前 / 看盤後 / 今天怎樣」時的固定流程

數據是程式自動抓的,**但裡面沒有任何新聞**(資料來源只有 Yahoo / Stooq / 期交所 / 證交所 / 永豐 PDF,沒有富途、沒有新聞源)。時事要你自己上網查。

1. **先拿最新數據**(雲端 session 是新 clone,先 `git fetch origin main` 再讀 `origin/main` 的版本)
   - 盤前:`chips/data/premarket_YYYYMMDD_claude.txt`(或 `premarket_latest.json`)。週日中午那班會標成「下週一」。
   - 盤後:`chips/data/YYYYMMDD_claude.txt`(或 `latest.json`)。融資約 21:30 後才補。
   - 庫存:`node tools/show-data.mjs`(data.json 是加密的,這支會解開印重點;不寫檔)。
   - **先檢查日期**:檔案日期不是今天(盤前:今天或下週一)就直說「資料還沒更新到今天」,不要拿舊資料當今天講。
2. **照檔案第二行「【給 Claude】」的指示上網查時事**:盤前查前一交易日收盤後到現在(美股、費半、輝達 / 台積電 ADR、利率、美元台幣、油金、地緣政治、今日將公布的數據);盤後查今天台股、外資、半導體、匯率、盤後公告。整理 3–5 則,每則附來源與時間。
3. **合併說明**:時事 + 數據對照(哪些數字可能跟哪則消息有關),再帶到使用者的持股(今日損益、今日進出)。
4. **規矩**:查不到 / 不能上網就直說,不要猜;檔案寫「⚠ 需手動補 / 【缺】」的欄位,請使用者上傳截圖補,不要自己補數字;最後提醒不是投資建議。

## 排程與觸發(出事先看這裡)

- 盤中股價:Cloudflare cron `:00/:10…` + cron-job.org `:05/:15…`(兩路並行),網頁超過 15 分沒更新會補觸發。
- 盤前 07:25(cron-job.org)/ 07:30(Cloudflare);週日 12:00 先發週一盤前。盤後 15:35 / 15:40 / 15:45。LINE 同一天只發一次。
- 每個觸發都帶來源(GitHub 執行紀錄標題如「股價 cloudflare」「籌碼 盤後 cronjob」);可靠度報表 `reports/triggers.md`(每週六)。
- 細節、Cron 清單、出事怎麼查:`cloudflare/README.md`。Worker 正本是 `cloudflare/worker.mjs`,改完要使用者自己貼到 Cloudflare。

## 改程式的規矩

- 測試:`node tests/run.mjs`、`python3 -m unittest discover -s tests -p "test_*.py"`,都要綠燈才 push。
- 改了前端(`app.js` / `charts.js` / `styles.css` / `scripts/calc.js` / `index.html`)→ `node tools/bump.mjs` 換版號,不要手改。
- `data.json` 以 repo 為正本(排程每 5 分鐘在寫),不要拿本機舊檔蓋;真要改資料,先 pull 最新、只動要改的欄位。
- 使用者在手機 / 網頁操作,說明用繁體中文、白話,給可以直接貼上的東西(程式碼整段、設定值逐欄)。
