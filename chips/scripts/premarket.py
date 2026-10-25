# -*- coding: utf-8 -*-
"""
premarket.py ─ 盤前資料自動抓取（美股收盤＋債匯金油＋台指期夜盤＋台股前收）
產出 data/premarket_YYYYMMDD.json、data/premarket_latest.json、data/premarket_YYYYMMDD_claude.txt
防呆：任何取不到的欄位一律寫成 "【缺】"，並在 missing 清單與文字表最上方用 ⚠ 標示，讓 Claude 知道要請使用者手動補。
來源：Yahoo Finance（主）→ Stooq（備援）；期交所 futDataDown 盤後交易時段；站上 latest.json（台股前收）。
"""
import os, io, re, sys, json, datetime as dt
import requests, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from panghu import describe_premarket, quantiles, pctile, load_panghu_cfg, premarket_target_day, claude_news_instruction   # 盤前描述卡 / 標哪一天(純計算,tests/test_panghu.py 有測)
from common import tw_now, read_json, write_json, write_text, decode, parse_tx_night                   # 共用小工具(見 common.py)
from concurrent.futures import ThreadPoolExecutor

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data"); os.makedirs(DATA, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
MISSING = "【缺】"
LOG, missing = [], []
def log(s): LOG.append(s); print(s)

# ── 想抓的標的：key, 中文名, Yahoo 代碼, Stooq 代碼, 小數位, 顯示方式 ──
ITEMS = [
    ("dji",  "道瓊",       "^DJI",     "^dji",   0, "idx"),
    ("spx",  "S&P 500",    "^GSPC",    "^spx",   0, "idx"),
    ("ixic", "那斯達克",   "^IXIC",    "^ndq",   0, "idx"),
    ("sox",  "費城半導體", "^SOX",     "^sox",   0, "idx"),
    ("tsm",  "台積電ADR",  "TSM",      "tsm.us", 2, "px"),
    ("nvda", "輝達",       "NVDA",     "nvda.us",2, "px"),
    ("tsla", "特斯拉",     "TSLA",     "tsla.us",2, "px"),
    ("aapl", "蘋果",       "AAPL",     "aapl.us",2, "px"),
    ("us10y","美債10Y",    "^TNX",     "10yusy.b",2, "yld"),
    ("dxy",  "美元指數",   "DX-Y.NYB", "dx.f",   2, "fut"),
    ("gold", "黃金期貨",   "GC=F",     "gc.f",   0, "fut"),
    ("brent","布蘭特",     "BZ=F",     "cb.f",   2, "fut"),
    ("wti",  "WTI",        "CL=F",     "cl.f",   2, "fut"),
    ("twd",  "美元/台幣",  "TWD=X",    "usdtwd", 2, "px"),
    ("vix",  "VIX",        "^VIX",     "^vix",   2, "px"),
]

def yahoo(sym):
    """3 年日線 → [{ts, d, c}](ts = UTC 秒,d = 美東日期)。3 年:算「這次漲跌在近 3 年排第幾」"""
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                     params={"range": "3y", "interval": "1d"}, headers=UA, timeout=20)
    j = r.json()["chart"]["result"][0]
    ts = j["timestamp"]; cl = j["indicators"]["quote"][0]["close"]
    bars = [{"ts": t, "d": (dt.datetime.fromtimestamp(t, dt.timezone.utc) - dt.timedelta(hours=4)).date(), "c": c}   # 美東(粗略,標日期用)
            for t, c in zip(ts, cl) if c is not None]
    if len(bars) < 2: raise ValueError("rows<2")
    return bars

def stooq(sym):
    r = requests.get("https://stooq.com/q/d/l/", params={"s": sym, "i": "d"}, headers=UA, timeout=20)
    df = pd.read_csv(io.StringIO(r.text))
    if "Close" not in df.columns or len(df) < 2: raise ValueError("no data")
    df = df.dropna(subset=["Close"]).tail(760)                                       # 約 3 年
    return [{"ts": None, "d": dt.date.fromisoformat(str(d)[:10]), "c": float(c)} for d, c in zip(df["Date"], df["Close"])]

def fetch_raw(key, name, ysym, ssym, nd, kind):
    """只抓日線,還不算漲跌(要先知道美股收在哪天、台股前收以來過了幾個美股交易日,見 summarize)"""
    for src, fn, sym in (("yahoo", yahoo, ysym), ("stooq", stooq, ssym)):
        try: return {"key": key, "name": name, "nd": nd, "kind": kind, "src": src, "bars": fn(sym)}
        except Exception as e: log(f"  {name} {src} 失敗：{e.__class__.__name__}")
    return {"key": key, "name": name, "nd": nd, "kind": kind, "src": "", "bars": None}

LIVE_KINDS = ("fut",)          # 期貨 / 外匯近乎 24 小時交易:07:20 抓時下一個交易時段已開盤,最後一根是「盤中即時價」
LIVE_KEYS = ("twd",)

def trim_live(raw, ref):
    """把美股收盤之後才開的那根(期貨 / 外匯的盤中即時價)拿掉,只留跟美股同一天收的價。
    ref = {"date": 美股最後交易日, "close_ts": 那天 21:30 UTC};回傳 (bars, 被拿掉的即時價 or None)。
    2026-10-25 前沒做:布蘭特、美元指數的「漲跌」其實是結算後到台北早上 7 點的變化,隔天前收也對不上前一天的現值。"""
    bars = list(raw["bars"] or [])
    if not ref or not (raw["kind"] in LIVE_KINDS or raw["key"] in LIVE_KEYS): return bars, None
    dropped = None
    while len(bars) > 2:
        b = bars[-1]
        late = (b["ts"] is not None and b["ts"] > ref["close_ts"]) or (b["ts"] is None and b["d"] > ref["date"])
        if not late: break
        dropped = dropped or b; bars.pop()
    return bars, dropped

def summarize(raw, span=1, ref=None):
    """日線 → 顯示用的一筆。span = 台股前收以來的美股交易日數(連假時 > 1:漲跌改成累計,並列出每天)。"""
    name, nd, kind = raw["name"], raw["nd"], raw["kind"]
    if not raw.get("bars"):
        return {"name": name, "value": MISSING, "prev": MISSING, "chg": None, "pct": None, "date": "", "src": "", "ok": False}
    bars, dropped = trim_live(raw, ref)
    span = max(1, min(span, len(bars) - 1))
    last, base = len(bars) - 1, len(bars) - 1 - span
    c1, c0 = bars[last]["c"], bars[base]["c"]
    chg = c1 - c0; pct = chg / c0 * 100
    out = {"name": name, "value": round(c1, nd), "prev": round(c0, nd), "chg": round(chg, 4), "pct": round(pct, 2),
           "date": bars[last]["d"].strftime("%m/%d"), "src": raw["src"], "ok": True}
    if span > 1:
        out["span"] = span; out["from"] = bars[base]["d"].strftime("%m/%d")
        out["sessions"] = [{"date": bars[i]["d"].strftime("%m/%d"), "pct": round((bars[i]["c"] / bars[i - 1]["c"] - 1) * 100, 2)}
                           for i in range(base + 1, last + 1)]
    if dropped: out["live"] = {"value": round(dropped["c"], nd), "note": "抓取時盤中即時價(未採用)"}
    if kind == "fut" and abs(pct) >= 3 * span ** .5: out["roll_warn"] = True    # 期貨連續合約換月日會出現假跳動
    cl = [b["c"] for b in bars[:base + 1]]                                     # 歷史:同樣天數的漲跌(不含這次)
    hist = [(cl[i] / cl[i - span] - 1) * 100 for i in range(span, len(cl)) if cl[i - span]]
    qq = quantiles(hist)
    if qq: out["p"] = int(round(pctile(pct, qq))); out["years"] = round(len(hist) / 250, 1)
    return out

def us_span(raws, since):
    """台股前收(since,date)之後美股開了幾天:以道瓊 / 標普 / 那指的日線為準;回 (span, ref)。
    平常 = 1;10/22(四)收盤後連休到 10/27 → 美股 10/22、10/23、10/26 三天 = 3。"""
    for k in ("spx", "dji", "ixic"):
        b = raws.get(k, {}).get("bars")
        if not b: continue
        last = b[-1]["d"]
        ref = {"date": last, "close_ts": dt.datetime(last.year, last.month, last.day, 21, 30, tzinfo=dt.timezone.utc).timestamp()}
        if since is None: return 1, ref
        n = sum(1 for x in b if x["d"] >= since)
        return max(1, n), ref
    return 1, None

# ── 期交所：台指期近月 一般時段 vs 盤後（夜盤） ──
def taifex_night(day_date, until):
    """台指期近月:day_date 日盤收盤 vs 它之後那一段夜盤(解析在 common.parse_tx_night)。
    ⚠ 期交所把夜盤算在下一個交易日(週五晚那段的交易日期是下週一),所以要查 day_date ~ until(要標的盤前日)這個區間。"""
    H = {**UA, "Referer": "https://www.taifex.com.tw/cht/3/futDataDown"}
    r = requests.post("https://www.taifex.com.tw/cht/3/futDataDown",
                      data={"down_type": "1", "commodity_id": "TX", "queryStartDate": day_date, "queryEndDate": until}, headers=H, timeout=30)
    txt = decode(r.content)
    if not txt or "收盤價" not in txt: raise ValueError("無資料")
    x = parse_tx_night(txt, day_date)
    if not x or x["day_close"] is None: raise ValueError("無一般時段")
    if x["night_close"] is None: raise ValueError("盤後時段尚未公布")
    out = {"contract": x["contract"], "day_close": x["day_close"], "night_close": x["night_close"],
           "night_high": x["night_high"], "night_low": x["night_low"], "night_open": x["night_open"]}
    out["night_chg"] = round(out["night_close"] - out["day_close"], 0); out["night_pct"] = round(out["night_chg"] / out["day_close"] * 100, 2)
    return out

def main():
    now = tw_now(); target = premarket_target_day(now)                 # 週末跑 = 下週一的盤前(週日中午先發)
    today = target.strftime("%Y/%m/%d"); tag = target.strftime("%Y%m%d")
    # 休市(國定假日 / 補假 / 颱風假 / chips/closed_days.json)→ 整班跳過:不抓、不寫檔,notify_premarket 也因日期對不上而不發
    from market_calendar import check as market_check
    closed, why = market_check(target.date(), now=now)
    if closed: print(f"盤前 {today} 休市({why}),略過"); return
    log(f"盤前抓取 {today}(實際 {now.strftime('%m/%d %H:%M')})")

    # 台股前收:站上 latest.json(先讀:美股要算「台股收盤之後」的漲跌,夜盤也要接在這天之後)
    prev = None
    try:
        lj = read_json(os.path.join(DATA, "latest.json"))
        if lj is None: raise ValueError("latest.json 讀不到")
        ix, inst, f = lj.get("index") or {}, lj.get("inst") or {}, (lj.get("txf") or {}).get("外資") or {}
        prev = {"date": lj["date"], "close": ix.get("close"), "chg": ix.get("chg"), "amount_yi": ix.get("amount_yi"),
                "foreign": inst.get("外資"), "inst_total": inst.get("合計"), "foreign_net_oi": f.get("net"),
                "basis": lj.get("basis"), "mtx": (lj.get("mtx_retail") or {}).get("ratio_pct"), "tmf": (lj.get("tmf_retail") or {}).get("ratio_pct")}
        pc = (lj.get("prev") or {}).get("index") or {}
        prev["pct"] = round(ix["chg"] / pc["close"] * 100, 2) if ix.get("chg") is not None and pc.get("close") else None
        pp = lj.get("prev") or {}                                                    # 前前一日:給描述卡算期貨增減、散戶跳動
        prev["foreign_net_oi_prev"] = ((pp.get("txf") or {}).get("外資") or {}).get("net")
        prev["mtx_prev"] = (pp.get("mtx_retail") or {}).get("ratio_pct"); prev["tmf_prev"] = (pp.get("tmf_retail") or {}).get("ratio_pct")
        if any(v is None for v in (prev["close"], prev["foreign"])): missing.append("台股前收（latest.json 不完整）")
    except Exception as e:
        log(f"  台股前收失敗：{e}"); missing.append("台股前收")
    since = dt.datetime.strptime(prev["date"], "%Y/%m/%d").date() if prev and prev.get("date") else None

    with ThreadPoolExecutor(max_workers=8) as ex:                      # 15 檔各抓 3 年日線,同時抓(原本一檔一檔來)
        raws = list(ex.map(lambda it: fetch_raw(*it), ITEMS))
    span, ref = us_span({r["key"]: r for r in raws}, since)          # 連假:台股收盤後美股開了幾天(平常 1)
    if span > 1: log(f"  連假:台股前收 {prev['date']} 之後美股開了 {span} 天,漲跌改成累計")
    us = {r["key"]: summarize(r, span, ref) for r in raws}
    missing.extend(v["name"] for v in us.values() if not v["ok"])

    # 夜盤:只取緊接在台股前收那天日盤之後的那一段(凌晨 05:00 收);抓不到就標缺,不退回更早的日子充數
    night = None
    if since:
        for attempt in range(2):
            try:
                night = taifex_night(prev["date"], today); night["date"] = since.strftime("%m/%d"); break   # date = 這段夜盤接在哪天日盤之後
            except Exception as e:
                log(f"  夜盤 {since.strftime('%m/%d')} 失敗({attempt + 1}):{e}")
    if night is not None and span > 1:                                 # 連假:夜盤只到第一個美股交易日的凌晨,之後幾天期貨沒交易
        night["lag"] = span - 1
        first_us = next((us[k]["sessions"][0]["date"] for k in ("spx", "dji", "sox") if us[k].get("sessions")), "")
        night["note"] = f"只反映 {first_us} 美股;之後 {span - 1} 個美股交易日台指期休市沒有報價"
    if night is None: missing.append("台指期夜盤")

    # ── 文字表 ──
    def fmt(it, pct_only=False):
        if not it["ok"]: return f"{it['name']} {MISSING}"
        v = it["value"]; s = f"{v:,.2f}" if isinstance(v, float) and v % 1 else f"{v:,.0f}" if isinstance(v, (int, float)) else v
        if it["name"] == "美債10Y": return f"美債10Y {it['value']:.2f}%（{it['chg']*100:+.0f}bps{'，' + str(it['span']) + '日累計' if it.get('span') else ''}）"
        return f"{it['name']} {s}（{it['pct']:+.2f}%{'，' + str(it['span']) + '日累計' if it.get('span') else ''}{'，可能是換月' if it.get('roll_warn') else ''}）"
    L = [f"【盤前數據】{today}（抓取 {now.strftime('%H:%M') if target.date() == now.date() else now.strftime('%m/%d %H:%M')}）"]
    L.append(claude_news_instruction("pre", today))                  # 提醒 Claude 先上網查時事(數據裡沒有新聞)
    if missing: L.append(f"⚠⚠ 需手動補資料：{'、'.join(missing)} ⚠⚠（請 Claude 提醒使用者上傳截圖補齊，不要自行猜測）")
    us_date = next((us[k]["date"] for k in ("dji", "spx", "sox") if us[k]["ok"]), "?")
    if span > 1:                                                        # 連假:先講清楚是累計,再列每天
        frm = next((us[k]["from"] for k in ("dji", "spx", "sox") if us[k].get("from")), "?")
        L.append(f"⚠ 連假:台股前收 {prev['date']} 之後美股開了 {span} 天,以下美股 / ADR / 債匯漲跌都是 {frm} 收盤 → {us_date} 收盤的累計")
        for k in ("sox", "tsm", "ixic"):
            if us[k].get("sessions"): L.append(f"  {us[k]['name']} 逐日：" + "、".join(f"{x['date']} {x['pct']:+.2f}%" for x in us[k]["sessions"]))
        us_date = f"{frm}→{us_date}（{span}日累計）"
    L.append(f"美股 {us_date}：" + "｜".join(fmt(us[k]) for k in ("dji", "spx", "ixic", "sox")))
    L.append("ADR/個股：" + "｜".join(fmt(us[k]) for k in ("tsm", "nvda", "tsla", "aapl")))
    L.append("債匯金油：" + "｜".join(fmt(us[k]) for k in ("us10y", "dxy", "gold", "brent", "wti", "twd", "vix")))
    if night:
        L.append(f"台指期夜盤（{night['date']}）：收 {night['night_close']:,.0f}（{night['night_chg']:+,.0f}，{night['night_pct']:+.2f}%）"
                 f" 高 {night['night_high']:,.0f} 低 {night['night_low']:,.0f}｜日盤收 {night['day_close']:,.0f}（{night['contract']}）"
                 + (f"｜⚠ {night['note']}" if night.get("note") else ""))
    else: L.append(f"台指期夜盤：{MISSING}（{prev['date'] if prev else '前一交易日'} 日盤之後的盤後時段未取得;不拿更早的夜盤充數）")
    if prev and prev.get("close") is not None:
        L.append(f"台股前收（{prev['date']}）：加權 {prev['close']:,}（{prev['chg']:+,}，{('%+.2f%%' % prev['pct']) if prev['pct'] is not None else MISSING}）"
                 f" 量 {prev['amount_yi']:,} 億｜外資 {prev['foreign']:+.0f} 億｜法人 {prev['inst_total']:+.0f}｜外資淨空 {prev['foreign_net_oi']:,}"
                 f"｜正價差 {prev['basis'] if prev['basis'] is not None else MISSING}｜小台 {prev['mtx']}% 微台 {prev['tmf']}%")
    else: L.append(f"台股前收：{MISSING}")
    L.append("來源：Yahoo/Stooq 收盤價（美元指數為 ICE DXY、油為 ICE 布蘭特／NYMEX WTI 期貨、10Y 為 CBOE ^TNX，單位 %）；夜盤為期交所盤後交易時段；"
             "夜盤高低含整段盤後（含美股盤中）。黃金 / 油 / 美元指數是期貨連續合約，換月當天的漲跌幅不準。")
    if missing: L.append(f"⚠ 缺：{'、'.join(missing)}")

    # ── 描述卡(純規則,只描述):一句話 + 5 個面向;放在文字表最前面
    try: desc = describe_premarket(us, night, prev, load_panghu_cfg())
    except Exception as e: log(f"  描述卡失敗:{e.__class__.__name__}: {e}"); desc = None
    if desc:
        L.insert(1, desc["headline"] + "".join(f"\n・{a['name']} {a['label']}:" + ";".join(a["lines"]) for a in desc["aspects"]))
    out = {"date": today, "generated_at": now.isoformat(timespec="seconds"), "us": us, "night": night, "prev": prev, "describe": desc,
           "missing": missing, "log": LOG, "claude_text": "\n".join(L)}
    write_json(os.path.join(DATA, f"premarket_{tag}.json"), out, indent=1)            # 原子寫入
    write_json(os.path.join(DATA, "premarket_latest.json"), out, indent=1)
    write_text(os.path.join(DATA, f"premarket_{tag}_claude.txt"), out["claude_text"])
    for m in missing: print(f"::warning title=盤前資料缺漏 {today}::{m}")
    print("\n" + out["claude_text"])

if __name__ == "__main__":
    main()
