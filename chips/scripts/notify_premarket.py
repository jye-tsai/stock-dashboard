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
gen = (t.get("generated_at") or "")[:10].replace("-", "/")              # 週日中午先發週一盤前 → 標明哪天抓的
lines = [f"🐶 {t['date']} 盤前" + (f"（{gen[5:]} 先發,週一早上不再重發）" if gen and gen != t["date"] else "")]
if t["missing"]: lines.append("⚠ 需手動補：" + "、".join(t["missing"]))
D = t.get("describe") or {}
if D.get("headline"):
    lines.append(D["headline"])
    lines += [f"{a['name']}:{a['short']}" for a in D.get("aspects") or [] if a["k"] not in ("night",)]   # 夜盤已在一句話裡
    lines.append("── 數據 ──")
lines.append("｜".join(s(k) for k in ("dji", "sox", "tsm")))
if n: lines.append(f"夜盤 {n['night_close']:,.0f}（{n['night_chg']:+,.0f}）")
lines.append(os.getenv("SITE_URL", ""))
msgs = [{"type": "text", "text": "\n".join(lines)}]
card, site = os.path.join(d, f"card_pre_{t['date'].replace('/', '')}.png"), os.getenv("SITE_URL", "")
if site and os.path.exists(card):                                 # 先圖後文字;等 Pages 部署完才傳圖,逾時只發文字
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from render_card import card_url_when_live, image_message
    url = card_url_when_live(card, site, int(os.getenv("CARD_WAIT", "240")))
    if url: msgs.insert(0, image_message(url)); print("notify: 圖卡", url)
    else: print("notify: 圖卡還沒部署好,只發文字")
r = requests.post("https://api.line.me/v2/bot/message/push", headers={"Authorization": f"Bearer {tok}"},
                  json={"to": uid, "messages": msgs}, timeout=20)
print("notify:", r.status_code, r.text[:100])
if r.status_code == 200:
    import datetime as dt
    json.dump({"last": t["date"], "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}, open(MARK, "w", encoding="utf-8"))
