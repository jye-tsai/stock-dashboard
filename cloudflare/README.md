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

## 改程式

1. 改 `worker.mjs` → commit
2. Cloudflare → Workers → 這支 Worker → Edit code → 整段貼上 → Deploy
3. Secret `GH_TOKEN`(fine-grained PAT,`jye-tsai/stock-dashboard` 的 Actions: Read and write)放在 Worker → Settings → Variables and Secrets,**不要寫進程式**

## 出事怎麼查

- **股價沒自動更新**:Worker → Logs 看有沒有 `cron */10 1-5 * * * → update-prices.yml`
  - 完全沒有紀錄 → Cron Triggers 那條不見 / 被改(2026-10-02 就是被換成 `*/30 * * * *`)
  - 有紀錄但 `dispatch failed 401` → `GH_TOKEN` 過期,重產 PAT 更新 Secret
- **手動補一次**:瀏覽器開 Worker 根網址 `/`(股價)、`/chips`、`/premarket`
- 盤中斷線超過 30 分鐘,`update-prices.mjs` 下一次有跑到時會推 LINE「⚠ 股價排程可能停了」;15:40 籌碼站推播也會標出「今日股價沒更新到收盤」。
