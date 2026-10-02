# Cloudflare Worker(排程觸發器)

`worker.mjs` 是貼在 Cloudflare 的 Worker 正本。它只做一件事:依 cron 準時呼叫 GitHub `workflow_dispatch`。
GitHub 內建 schedule 常延遲數小時或漏跑,所以盤中股價與籌碼站都靠這支準時觸發。

## Cron Triggers(Worker → Settings → Triggers,必須剛好這 4 條)

| Cron(UTC) | 台北時間 | 觸發 |
|---|---|---|
| `*/10 1-5 * * *` | 每天 09:00–13:50 每 10 分(週末由腳本擋) | `update-prices.yml` 盤中股價 |
| `30 23 * * 1-5` | 週一~五 07:30 | `chips.yml` 盤前 |
| `40 7 * * 2-6` | 週一~五 15:40 | `chips.yml` 盤後 |
| `40 8 * * 2-6` | 週一~五 16:40 | `chips.yml` 補永豐 |

Cloudflare 星期欄 **1=日 … 7=六**(跟 GitHub 不同)。

**新增 / 修改 cron 時,三個地方要一起改**:Cloudflare 後台的 Cron Triggers、`worker.mjs` 的 `ROUTES`、這張表。
對不上時 Worker log 會出現「⚠ 未知 cron」。

## cron-job.org(第二條觸發路,2026-10-02 加)

Cloudflare cron 會整段不觸發(log 完全沒紀錄),所以另外用 cron-job.org 每 10 分打 Worker 根網址 `/`,跟 Cloudflare cron 並行:

- URL:Worker 根網址(結尾 `/`)
- Schedule:Custom,Minutes `5,15,25,35,45,55`、Hours `9-13`、週一~五,Time zone `Asia/Taipei`
  (故意跟 Cloudflare 的 `*/10` 錯開 5 分:兩邊都正常 = 股價每 5 分更新;任一邊掛 = 每 10 分;不會同一分鐘重複觸發)
- 預期回應:`✅ 已觸發 股價 update-prices`(cron-job.org 的 History 看得到每次的回應與狀態碼)

**15:40 盤後推播也有第二條路**:cron-job.org 另建一個 job 打 `Worker網址/chips-cron`
- Schedule:Minutes `40`、Hours `15`、週一~五,Time zone `Asia/Taipei`(想 16:40 補永豐也一起,Hours 填 `15,16`)
- 只在台北週一~五 15:30–17:59 有效,其他時間回「⏸ 不在時段」不觸發;同一交易日 LINE 只發一次,兩邊都打也只收一則
- 預期回應:`✅ 已觸發 籌碼站 chips 盤後(cron,會發 LINE)`

**07:30 盤前推播也一樣**:cron-job.org 再建一個 job 打 `Worker網址/premarket-cron`
- Schedule:Minutes `30`、Hours `7`、週一~五,Time zone `Asia/Taipei`
- 只在台北週一~五 07:00–08:59 有效;盤前 LINE 同一天只發一次
- 預期回應:`✅ 已觸發 籌碼站 chips 盤前(cron,會發 LINE)`
- 注意:`/premarket`(手動)也會發 LINE —— chips.yml 盤前那步不看 source,同日沒發過就發

**兩邊同時打不會重複推播**:chips.yml / update-prices.yml 的 checkout 指定 `ref: main`,排在後面的 run 拿到的是最新版
(含前一個 run 的資料與 `chips/data/notified.json`),notify 看到「今天已通知」就略過。2026-10-02 15:40 第一次兩邊都打時,
第二個 run 拿到舊版 → push 衝突失敗(剛好沒重發),之後才加 `ref: main`。

注意:Worker 網址是公開的,打 `/` 就會觸發一次 Action(無害,只是多跑);瀏覽器網址列預先載入也會算一次,所以手動測試時常見「同一秒兩次」。

## 改程式

1. 改 `worker.mjs` → commit
2. Cloudflare → Workers → 這支 Worker → Edit code → 整段貼上 → Deploy
3. Secret `GH_TOKEN`(fine-grained PAT,`jye-tsai/stock-dashboard` 的 Actions: Read and write)放在 Worker → Settings → Variables and Secrets,**不要寫進程式**

## 出事怎麼查

- **股價沒自動更新**:Worker → Logs 看有沒有 `cron */10 1-5 * * * → update-prices.yml`
  - 完全沒有紀錄 → Cron Triggers 那條不見 / 被改(2026-10-02 就是被換成 `*/30 * * * *`)
  - 有紀錄但 `dispatch failed 401` → `GH_TOKEN` 過期,重產 PAT 更新 Secret
  - Cloudflare 那邊沒紀錄,但 cron-job.org History 有 200 → 正常,cron-job.org 頂著;有空再修 Cloudflare
  - cron-job.org History 是 5xx / 逾時 → Worker 掛了或 `GH_TOKEN` 過期(回應內容會寫 GitHub 的錯誤)
- **手動補一次**:瀏覽器開 Worker 根網址 `/`(股價)、`/chips`(不發 LINE)、`/chips-cron`(15:30–17:59 才有效,會發 LINE)、`/premarket`(會發 LINE)、`/premarket-cron`(07:00–08:59 才有效)
- 盤中斷線超過 30 分鐘,`update-prices.mjs` 下一次有跑到時會推 LINE「⚠ 股價排程可能停了」;15:40 籌碼站推播也會標出「今日股價沒更新到收盤」。
