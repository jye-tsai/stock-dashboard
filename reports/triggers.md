# 排程可靠度(2026-10-18 ~ 2026-10-31,平日 10 天)

產生時間 2026-10-31 16:06(台北)。「到」= 預定時刻後 5 分鐘內 GitHub 有收到該來源的觸發。

| 來源 | 應到 | 實到 | 到達率 | 平均延遲 | 最大延遲 |
|---|---:|---:|---:|---:|---:|
| 盤中股價・Cloudflare | 300 | 300 | 100.0% | 27 秒 | 39 秒 |
| 盤中股價・cron-job.org | 300 | 300 | 100.0% | 15 秒 | 20 秒 |
| 盤前推播・Cloudflare | 10 | 10 | 100.0% | 27 秒 | 36 秒 |
| 盤前推播・cron-job.org | 10 | 10 | 100.0% | 20 秒 | 22 秒 |
| 週日先發週一盤前・Cloudflare | 2 | 2 | 100.0% | 42 秒 | 56 秒 |
| 週日先發週一盤前・cron-job.org | 2 | 2 | 100.0% | 37 秒 | 37 秒 |
| 盤後・Cloudflare | 20 | 20 | 100.0% | 25 秒 | 36 秒 |
| 盤後・cron-job.org | 20 | 20 | 100.0% | 25 秒 | 33 秒 |

## 其他觸發(不列入可靠度)
- 股價 schedule:25 次
- 股價 web:1 次
- 股價 url:1 次
- 籌碼 盤後 schedule:12 次

來源標記:cloudflare = Cloudflare Worker cron;cronjob = cron-job.org(URL 帶 `?src=cronjob`);web = 網頁補觸發;button = 「📈 更新市價」;url = 瀏覽器開 Worker 網址;schedule = GitHub 內建排程;manual = GitHub 網頁手動 Run。
