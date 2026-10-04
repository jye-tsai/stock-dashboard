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
from common import tw_now, read_json, write_json, write_text, decode, parse_tx                   # 共用小工具(見 common.py)
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
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                     params={"range": "3y", "interval": "1d"}, headers=UA, timeout=20)    # 3 年:算「今天的漲跌在近 3 年排第幾」
    j = r.json()["chart"]["result"][0]
    ts = j["timestamp"]; cl = j["indicators"]["quote"][0]["close"]
    rows = [(t, c) for t, c in zip(ts, cl) if c is not None]
    if len(rows) < 2: raise ValueError("rows<2")
    (t1, c1), (t0, c0) = rows[-1], rows[-2]
    d = dt.datetime.fromtimestamp(t1, dt.timezone.utc) - dt.timedelta(hours=4)      # 美東(粗略,只拿來標日期)
    hist = [(rows[i][1] / rows[i - 1][1] - 1) * 100 for i in range(1, len(rows) - 1) if rows[i - 1][1]]   # 歷史單日漲跌(不含今天)
    return {"close": c1, "prev": c0, "date": d.strftime("%m/%d"), "hist": hist}

def stooq(sym):
    r = requests.get("https://stooq.com/q/d/l/", params={"s": sym, "i": "d"}, headers=UA, timeout=20)
    df = pd.read_csv(io.StringIO(r.text))
    if "Close" not in df.columns or len(df) < 2: raise ValueError("no data")
    df = df.dropna(subset=["Close"]).tail(760)                                       # 約 3 年
    cl = df["Close"].astype(float).tolist()
    return {"close": cl[-1], "prev": cl[-2], "date": str(df["Date"].iloc[-1])[5:].replace("-", "/"),
            "hist": [(cl[i] / cl[i - 1] - 1) * 100 for i in range(1, len(cl) - 1) if cl[i - 1]]}

def fetch_item(key, name, ysym, ssym, nd, kind):
    for src, fn, sym in (("yahoo", yahoo, ysym), ("stooq", stooq, ssym)):
        try:
            v = fn(sym)
            chg = v["close"] - v["prev"]; pct = chg / v["prev"] * 100
            out = {"name": name, "value": round(v["close"], nd), "prev": round(v["prev"], nd),
                   "chg": round(chg, 4), "pct": round(pct, 2), "date": v["date"], "src": src, "ok": True}
            if kind == "fut" and abs(pct) >= 3: out["roll_warn"] = True      # 期貨連續合約換月日會出現假跳動(例:布蘭特一天 -5.9%、WTI 卻 +1.2%)
            qq = quantiles(v.get("hist") or [])                                # 今天的漲跌在近 3 年排第幾(0 最跌、100 最漲)
            if qq: out["p"] = int(round(pctile(pct, qq))); out["years"] = round(len(v["hist"]) / 250, 1)
            return out
        except Exception as e:
            log(f"  {name} {src} 失敗：{e.__class__.__name__}")
    return {"name": name, "value": MISSING, "prev": MISSING, "chg": None, "pct": None, "date": "", "src": "", "ok": False}

# ── 期交所：台指期近月 一般時段 vs 盤後（夜盤） ──
def taifex_night(date):
    """期交所台指期近月:一般時段收盤 vs 盤後(夜盤);解析共用 common.parse_tx(盤後 fetch_all 也用同一支)"""
    H = {**UA, "Referer": "https://www.taifex.com.tw/cht/3/futDataDown"}
    r = requests.post("https://www.taifex.com.tw/cht/3/futDataDown",
                      data={"down_type": "1", "commodity_id": "TX", "queryStartDate": date, "queryEndDate": date}, headers=H, timeout=30)
    txt = decode(r.content)
    if not txt or "收盤價" not in txt: raise ValueError("無資料")
    x = parse_tx(txt)
    if not x or x["day_close"] is None: raise ValueError("無一般時段")
    if x["night_close"] is None: raise ValueError("盤後時段尚未公布")
    out = {"contract": x["contract"], "day_close": x["day_close"], "night_close": x["night_close"],
           "night_high": x["night_high"], "night_low": x["night_low"], "night_open": x["night_open"]}
    out["night_chg"] = round(out["night_close"] - out["day_close"], 0); out["night_pct"] = round(out["night_chg"] / out["day_close"] * 100, 2)
    return out

def prev_trading_day(d):
    for _ in range(10):
        d -= dt.timedelta(days=1)
        if d.weekday() < 5: return d
    return d

def main():
    now = tw_now(); target = premarket_target_day(now)                 # 週末跑 = 下週一的盤前(週日中午先發)
    today = target.strftime("%Y/%m/%d"); tag = target.strftime("%Y%m%d")
    log(f"盤前抓取 {today}(實際 {now.strftime('%m/%d %H:%M')})")
    with ThreadPoolExecutor(max_workers=8) as ex:                      # 15 檔各抓 3 年日線,同時抓(原本一檔一檔來)
        got = list(ex.map(lambda it: fetch_item(*it), ITEMS))
    us = {it[0]: v for it, v in zip(ITEMS, got)}
    missing.extend(v["name"] for v in got if not v["ok"])                # 照 ITEMS 順序記缺漏(不在執行緒裡改共用清單)

    # 夜盤：前一交易日的盤後時段（凌晨 05:00 收盤）
    night, last_td = None, prev_trading_day(now)
    for _ in range(4):
        try:
            night = taifex_night(last_td.strftime("%Y/%m/%d")); night["date"] = last_td.strftime("%m/%d"); break
        except Exception as e:
            log(f"  夜盤 {last_td.strftime('%m/%d')} 失敗：{e}"); last_td = prev_trading_day(last_td)
    if night is None: missing.append("台指期夜盤")

    # 台股前收：站上 latest.json
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

    # ── 文字表 ──
    def fmt(it, pct_only=False):
        if not it["ok"]: return f"{it['name']} {MISSING}"
        v = it["value"]; s = f"{v:,.2f}" if isinstance(v, float) and v % 1 else f"{v:,.0f}" if isinstance(v, (int, float)) else v
        if it["name"] == "美債10Y": return f"美債10Y {it['value']:.2f}%（{it['chg']*100:+.0f}bps）"
        return f"{it['name']} {s}（{it['pct']:+.2f}%{'，可能是換月' if it.get('roll_warn') else ''}）"
    L = [f"【盤前數據】{today}（抓取 {now.strftime('%H:%M') if target.date() == now.date() else now.strftime('%m/%d %H:%M')}）"]
    L.append(claude_news_instruction("pre", today))                  # 提醒 Claude 先上網查時事(數據裡沒有新聞)
    if missing: L.append(f"⚠⚠ 需手動補資料：{'、'.join(missing)} ⚠⚠（請 Claude 提醒使用者上傳截圖補齊，不要自行猜測）")
    us_date = next((us[k]["date"] for k in ("dji", "spx", "sox") if us[k]["ok"]), "?")
    L.append(f"美股 {us_date}：" + "｜".join(fmt(us[k]) for k in ("dji", "spx", "ixic", "sox")))
    L.append("ADR/個股：" + "｜".join(fmt(us[k]) for k in ("tsm", "nvda", "tsla", "aapl")))
    L.append("債匯金油：" + "｜".join(fmt(us[k]) for k in ("us10y", "dxy", "gold", "brent", "wti", "twd", "vix")))
    if night:
        L.append(f"台指期夜盤（{night['date']}）：收 {night['night_close']:,.0f}（{night['night_chg']:+,.0f}，{night['night_pct']:+.2f}%）"
                 f" 高 {night['night_high']:,.0f} 低 {night['night_low']:,.0f}｜日盤收 {night['day_close']:,.0f}（{night['contract']}）")
    else: L.append(f"台指期夜盤：{MISSING}（期交所盤後時段未取得）")
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
