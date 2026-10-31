# -*- coding: utf-8 -*-
"""早上推 LINE：盤前數據摘要＋缺漏提醒"""
import os, json, sys, requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import read_json, write_json                              # 共用小工具(見 common.py)
tok, uid = os.getenv("LINE_CHANNEL_TOKEN"), os.getenv("LINE_USER_ID")
if not tok or not uid: print("notify: 無 LINE secrets"); sys.exit(0)
d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
t = read_json(os.path.join(d, "premarket_latest.json"))
if not t: print("notify: premarket_latest.json 讀不到"); sys.exit(0)
MARK = os.path.join(d, "premarket_notified.json")            # 同一天只發一次(手動重跑不會再吵一次);跟盤後的 notified.json 分開記
mark = read_json(MARK, {})
from common import tw_now
from panghu import premarket_target_day
want = premarket_target_day(tw_now()).strftime("%Y/%m/%d")           # 休市日 premarket.py 會整班跳過 → 檔案還是上一班的,不要拿舊資料再發
if t.get("date") != want: print(f"notify: 盤前資料是 {t.get('date')},今天要發的是 {want}(休市或還沒抓到),略過"); sys.exit(0)
if mark.get("last") == t["date"]: print(f"notify: {t['date']} 盤前已通知過，略過"); sys.exit(0)
us, n = t["us"], t.get("night")
from panghu import premarket_early_hold
hold = premarket_early_hold(tw_now(), n, us, end=int(os.getenv("PREMARKET_EARLY_END", "700")))
if hold: print(f"notify: 早班 {tw_now():%H:%M} 還缺 {hold},不發 LINE、不記已發,留給 07:20 那班"); sys.exit(0)
def s(k): it = us[k]; return f"{it['name']} {it['pct']:+.2f}%" if it["ok"] else f"{it['name']} 缺"
gen = (t.get("generated_at") or "")[:10].replace("-", "/")              # 週日中午先發週一盤前 → 標明哪天抓的
lines = [f"🐶 {t['date']} 盤前" + (f"（{gen[5:]} 先發,週一早上不再重發）" if gen and gen != t["date"] else "")]
span = next((v.get("span") for v in us.values() if v.get("span")), None)
if span:                                                              # 連假:美股漲跌是累計,夜盤只到第一晚
    frm = next((v.get("from") for v in us.values() if v.get("from")), "?")
    lines.append(f"⚠ 連假:美股以下為 {frm} 收盤起 {span} 個交易日累計" + ("；夜盤只到第一晚" if (n or {}).get("lag") else ""))
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
    from render_card import card_url_when_live, image_message
    url = card_url_when_live(card, site, int(os.getenv("CARD_WAIT", "240")))
    if url: msgs.insert(0, image_message(url)); print("notify: 圖卡", url)
    else: print("notify: 圖卡還沒部署好,只發文字")
r = requests.post("https://api.line.me/v2/bot/message/push", headers={"Authorization": f"Bearer {tok}"},
                  json={"to": uid, "messages": msgs}, timeout=20)
print("notify:", r.status_code, r.text[:100])
if r.status_code == 200:
    import datetime as dt
    write_json(MARK, {"last": t["date"], "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")})   # 原子寫入
