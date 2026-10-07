# 排程可靠度(2026-10-05 ~ 2026-10-07,平日 3 天)

產生時間 2026-10-07 08:02(台北)。「到」= 預定時刻後 5 分鐘內 GitHub 有收到該來源的觸發。

| 來源 | 應到 | 實到 | 到達率 | 平均延遲 | 最大延遲 |
|---|---:|---:|---:|---:|---:|
| 盤中股價・Cloudflare | 60 | 60 | 100.0% | 17 秒 | 23 秒 |
| 盤中股價・cron-job.org | 60 | 60 | 100.0% | 15 秒 | 21 秒 |
| 盤前推播・Cloudflare | 3 | 3 | 100.0% | 15 秒 | 15 秒 |
| 盤前推播・cron-job.org | 3 | 3 | 100.0% | 15 秒 | 19 秒 |
| 週日先發週一盤前・Cloudflare | 0 | 0 | 0.0% | — | — |
| 週日先發週一盤前・cron-job.org | 0 | 0 | 0.0% | — | — |
| 盤後・Cloudflare | 4 | 4 | 100.0% | 17 秒 | 18 秒 |
| 盤後・cron-job.org | 4 | 2 | 50.0% | 19 秒 | 19 秒 |

## 漏掉的時段
- **盤後・cron-job.org**(2):10-05 15:35、10-06 15:35

## 其他觸發(不列入可靠度)
- 股價 schedule:2 次
- 股價 url:16 次
- 股價 claude:3 次
- 籌碼 盤後 schedule:2 次
- 籌碼 盤後 claude:1 次

來源標記:cloudflare = Cloudflare Worker cron;cronjob = cron-job.org(URL 帶 `?src=cronjob`);web = 網頁補觸發;button = 「📈 更新市價」;url = 瀏覽器開 Worker 網址;schedule = GitHub 內建排程;manual = GitHub 網頁手動 Run。
