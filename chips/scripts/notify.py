# -*- coding: utf-8 -*-
"""notify.py ─ 抓完資料後推 LINE（Messaging API push）。
需 GitHub Secrets：LINE_CHANNEL_TOKEN（Channel access token）、LINE_USER_ID（你的 userId）。
兩者任一缺少就靜默跳過。LINE Notify 已於 2025 年停止服務，故改用 Messaging API。"""
import os, json, sys, requests
tok, uid = os.getenv("LINE_CHANNEL_TOKEN"), os.getenv("LINE_USER_ID")
if not tok or not uid:
    print("notify: 無 LINE secrets，略過"); sys.exit(0)
data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
t = json.load(open(os.path.join(data_dir, "latest.json"), encoding="utf-8"))
ix, i, f = t.get("index") or {}, t.get("inst") or {}, (t.get("txf") or {}).get("外資") or {}
mr, tr = t.get("mtx_retail") or {}, t.get("tmf_retail") or {}
lines = [f"🐶 {t['date']} 盤後數據已更新"]
if ix: lines.append(f"加權 {ix['close']:,} {ix['chg']:+,}　量 {ix['amount_yi']:,} 億")
if i: lines.append(f"外資現貨 {i.get('外資',0):+.0f} 億｜法人 {i.get('合計',0):+.0f}")
if f: lines.append(f"外資淨空 {f['net']:,}")
if mr and tr: lines.append(f"小台 {mr['ratio_pct']:+.2f}%　微台 {tr['ratio_pct']:+.2f}%")
if t.get("missing"): lines.append("⚠ 缺：" + ", ".join(t["missing"]))
site = os.getenv("SITE_URL", "")
if site: lines.append(site)
r = requests.post("https://api.line.me/v2/bot/message/push",
                  headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
                  json={"to": uid, "messages": [{"type": "text", "text": "\n".join(lines)}]}, timeout=20)
print("notify:", r.status_code, r.text[:120])
