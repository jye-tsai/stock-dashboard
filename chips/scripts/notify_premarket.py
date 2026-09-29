# -*- coding: utf-8 -*-
"""早上推 LINE：盤前數據摘要＋缺漏提醒"""
import os, json, sys, requests
tok, uid = os.getenv("LINE_CHANNEL_TOKEN"), os.getenv("LINE_USER_ID")
if not tok or not uid: print("notify: 無 LINE secrets"); sys.exit(0)
d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
t = json.load(open(os.path.join(d, "premarket_latest.json"), encoding="utf-8"))
MARK = os.path.join(d, "premarket_notified.json")            # 同一天只發一次(手動重跑不會再吵一次);跟盤後的 notified.json 分開記
try: mark = json.load(open(MARK, encoding="utf-8"))
except Exception: mark = {}
if mark.get("last") == t["date"]: print(f"notify: {t['date']} 盤前已通知過，略過"); sys.exit(0)
us, n = t["us"], t.get("night")
def s(k): it = us[k]; return f"{it['name']} {it['pct']:+.2f}%" if it["ok"] else f"{it['name']} 缺"
lines = [f"🐶 {t['date']} 盤前"]
if t["missing"]: lines.append("⚠ 需手動補：" + "、".join(t["missing"]))
D = t.get("describe") or {}
if D.get("headline"):
    lines.append(D["headline"])
    lines += [f"{a['name']}:{a['short']}" for a in D.get("aspects") or [] if a["k"] not in ("night",)]   # 夜盤已在一句話裡
    lines.append("── 數據 ──")
lines.append("｜".join(s(k) for k in ("dji", "sox", "tsm")))
if n: lines.append(f"夜盤 {n['night_close']:,.0f}（{n['night_chg']:+,.0f}）")
lines.append(os.getenv("SITE_URL", ""))
r = requests.post("https://api.line.me/v2/bot/message/push", headers={"Authorization": f"Bearer {tok}"},
                  json={"to": uid, "messages": [{"type": "text", "text": "\n".join(lines)}]}, timeout=20)
print("notify:", r.status_code, r.text[:100])
if r.status_code == 200:
    import datetime as dt
    json.dump({"last": t["date"], "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}, open(MARK, "w", encoding="utf-8"))
