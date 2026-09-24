# -*- coding: utf-8 -*-
"""notify.py ─ 抓完資料後推 LINE（Messaging API push）。
訊息 = 盤後數據摘要（chips/data/latest.json）＋ 庫存段（repo 根目錄 data.json：每檔收盤 / 今日% / 未實現，加總計）。

需 GitHub Secrets：LINE_CHANNEL_TOKEN（Channel access token）、LINE_USER_ID（你的 userId）；任一缺少就靜默跳過。
LINE Notify 已於 2025 年停止服務，故改用 Messaging API。免費方案每月 200 則，所以 chips.yml 只在 15:40 排程那班呼叫。

同一交易日只通知一次：送出後把日期寫進 chips/data/notified.json（workflow 會一起 commit）。
用法：python chips/scripts/notify.py [--dry-run]     --dry-run 只印訊息不送、不寫標記。

data.json 是前端同一把 AES-256-GCM 金鑰混淆的（防君子不防小人，金鑰本來就在公開的 app.js 裡），這裡用 cryptography 解開。
損益公式與 scripts/calc.js 對齊：成本 / 市值四捨五入到元、賣出成本 = 市值 ×（證交稅率 + 手續費率 × 折數）、未實現 = 市值 − 成本 − 賣出成本。"""
import os, sys, json, math, base64, datetime as dt
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Windows 主控台 cp950 印不出 emoji，本機 --dry-run 預覽用
except Exception: pass

DRY = "--dry-run" in sys.argv
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
DATA_DIR = os.path.join(ROOT, "chips", "data")
MARK = os.path.join(DATA_DIR, "notified.json")
OBF_KEY = base64.b64decode("3Nr6TNQZewwC/3wye+lwc60BCeWcaPRmQddHyAbS+uc=")
DEFAULT_TAX = 0.003

def js_round(x):            # JS Math.round：.5 往正無限大
    return math.floor(x + 0.5)

def fmt(n):                 # 千分位整數，帶正負
    return f"{int(js_round(n)):+,}"

def fmt2(n):
    return f"{n:,.2f}"

def today_tpe():
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=8)).strftime("%Y-%m-%d")

# ── 盤後數據段 ──
def chips_lines():
    p = os.path.join(DATA_DIR, "latest.json")
    if not os.path.exists(p): return ["🐶 盤後數據尚未產生"], None
    t = json.load(open(p, encoding="utf-8"))
    ix, i, f = t.get("index") or {}, t.get("inst") or {}, (t.get("txf") or {}).get("外資") or {}
    mr, tr = t.get("mtx_retail") or {}, t.get("tmf_retail") or {}
    L = [f"🐶 {t['date']} 盤後"]
    if ix: L.append(f"加權 {ix['close']:,} {ix['chg']:+,}　量 {ix['amount_yi']:,} 億")
    if i: L.append(f"外資現貨 {i.get('外資', 0):+.0f} 億｜法人 {i.get('合計', 0):+.0f}")
    if f: L.append(f"外資期貨淨 {f['net']:+,}" + (f"（{f.get('day_net', 0):+,}）" if f.get("day_net") is not None else ""))
    if mr and tr: L.append(f"小台 {mr['ratio_pct']:+.2f}%　微台 {tr['ratio_pct']:+.2f}%")
    if t.get("pc"): L.append(f"P/C(OI) {t['pc'].get('oi_ratio_pct')}%")
    MISS = {"inst": "外資現貨", "margin": "融資餘額", "opt": "選擇權", "pc": "P/C", "index": "加權指數",
            "mtx_retail": "小台散戶", "tmf_retail": "微台散戶", "txf.外資": "外資台指期"}
    miss = t.get("missing") or []; core = [MISS.get(k, k) for k in miss if k != "margin"]
    if core: L.append("⚠ 盤後尚未完整公布:" + "、".join(core) + ",後續班次自動更新")
    if "margin" in miss: L.append("融資餘額待 21:30 更新(沿用前一交易日)")
    ins = (t.get("insight") or {}).get("lines") or []
    if ins: L += ["── 解讀 ──"] + ins            # 價量 / 籌碼衍生解讀(fetch_all 算好存在 json,這裡只轉貼;全部帶,訊息上限 4900 字綽綽有餘)
    pg = t.get("panghu") or {}
    if pg.get("version") == 4 and pg.get("aspects"):     # 胖虎指標 v4:四面向現況描述;有極端事件才附歷史紀錄
        L += ["── 胖虎指標(現況描述) ──"] + [f"{a['name']}:{a['short']}" for a in pg["aspects"]]
        SH = {"gap60": "乖離", "vol_ratio": "量能", "foreign20_pct": "外資", "fut_chg20": "期貨20日", "retail": "散戶", "pc": "P/C", "twd20": "台幣"}
        if pg.get("position"): L.append("歷史位置:" + "・".join(f"{SH.get(x['k'], x['name'])} P{x['p']}" for x in pg["position"]))
        for e in pg.get("events") or []:
            L.append(f"⚠ {e['name']}:{e['text']}" + (f"(近 10 日第 {e['day']} 次)" if e.get("day", 1) > 1 else ""))
            if e.get("history_text"): L.append("　" + e["history_text"])
    return L, t.get("date")

# ── 庫存段 ──
def load_data_json():
    p = os.path.join(ROOT, "data.json")
    if not os.path.exists(p): return None
    raw = json.load(open(p, encoding="utf-8"))
    if not (isinstance(raw, dict) and raw.get("enc")): return raw
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    iv, ct = base64.b64decode(raw["iv"]), base64.b64decode(raw["ct"])   # ct 尾 16 bytes 是 tag，AESGCM.decrypt 吃的正是這格式
    return json.loads(AESGCM(OBF_KEY).decrypt(iv, ct, None).decode("utf-8"))

def holding_amounts(h, fees):
    f = fees or {}
    fee_rate, fee_disc, tax = f.get("feeRate", 0), f.get("feeDiscount", 0), (f.get("taxRates") or {})
    lots = h.get("lots") or 0
    cost = js_round((h.get("cost") or 0) * 1000 * lots)
    mv = js_round((h.get("price") or 0) * 1000 * lots)
    tax_rate = tax[h.get("type")] if tax.get(h.get("type")) is not None else DEFAULT_TAX
    sell = js_round(mv * (tax_rate + fee_rate * fee_disc))
    return cost, mv, mv - cost - sell

def holdings_lines(d):
    today = today_tpe()
    hs = [h for h in (d.get("holdings") or []) if (h.get("lots") or 0) > 0 and (h.get("price") or 0) > 0]
    if not hs: return []
    L = ["── 庫存 ──"]
    t_cost = t_mv = t_un = 0; day_chg = day_base = 0; ex_cnt = 0
    for h in hs:
        cost, mv, un = holding_amounts(h, d.get("fees"))
        t_cost += cost; t_mv += mv; t_un += un
        pc = h.get("prevClose") or 0
        ex = h.get("exDiv") or {}
        if ex and str(ex.get("date")) == today and (ex.get("amount") or 0) > 0: pc -= ex["amount"]; ex_cnt += 1
        day = ""
        if pc > 0:
            day_chg += js_round((h["price"] - pc) * 1000 * h["lots"]); day_base += js_round(pc * 1000 * h["lots"])
            day = f" {((h['price'] / pc) - 1) * 100:+.2f}%"
        name = (h.get("name") or "")[:6]
        st, tg = h.get("stop") or 0, h.get("target") or 0                  # 自己設的停損 / 目標價:觸到就標出來(盤中另有即時提醒)
        mk = f"　⚠ 低於停損 {fmt2(st)}" if st > 0 and h["price"] <= st else f"　🎯 達目標 {fmt2(tg)}" if tg > 0 and h["price"] >= tg else ""
        L.append(f"{h.get('code','')} {name}　{fmt2(h['price'])}{day}　{fmt(un)}（{(un / cost * 100) if cost else 0:+.1f}%）{mk}")
    realized, dividend = d.get("已實現損益") or 0, d.get("股息收入") or 0
    total_ret = t_un + realized + dividend
    L.append("──")
    if day_base: L.append(f"今日損益 {fmt(day_chg)}（{day_chg / day_base * 100:+.2f}%）" + (f"　※{ex_cnt} 檔除息已調整" if ex_cnt else ""))
    L.append(f"總市值 {t_mv:,}｜未實現 {fmt(t_un)}")
    L.append(f"總報酬 {fmt(total_ret)}（{(total_ret / t_cost * 100) if t_cost else 0:+.2f}%）")
    pu = d.get("priceUpdated")
    if pu: L.append(f"市價時間 {pu}")
    return L

def main():
    tok, uid = os.getenv("LINE_CHANNEL_TOKEN"), os.getenv("LINE_USER_ID")
    if not DRY and (not tok or not uid):
        print("notify: 無 LINE secrets，略過"); return
    lines, chip_date = chips_lines()
    mark = json.load(open(MARK, encoding="utf-8")) if os.path.exists(MARK) else {}
    if not DRY and chip_date and mark.get("last") == chip_date:
        print(f"notify: {chip_date} 已通知過，略過"); return
    try:
        d = load_data_json()
        if d: lines += holdings_lines(d)
    except Exception as e:
        lines.append(f"（庫存段讀取失敗：{e.__class__.__name__}）"); print("notify: holdings error", repr(e))
    site = os.getenv("SITE_URL", "")
    if site: lines.append(site)
    text = "\n".join(lines)
    print(text)
    if DRY: return
    import requests
    r = requests.post("https://api.line.me/v2/bot/message/push",
                      headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
                      json={"to": uid, "messages": [{"type": "text", "text": text[:4900]}]}, timeout=20)
    print("notify:", r.status_code, r.text[:120])
    if r.status_code == 200 and chip_date:
        json.dump({"last": chip_date, "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}, open(MARK, "w", encoding="utf-8"))

if __name__ == "__main__":
    main()
