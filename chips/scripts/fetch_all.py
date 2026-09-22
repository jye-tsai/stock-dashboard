# -*- coding: utf-8 -*-
"""
fetch_all.py ─ 台股盤後籌碼一鍵抓取（期交所＋證交所＋永豐PDF）
產出：
  data/YYYYMMDD.json        當日完整數據（含前一交易日對照）
  data/latest.json          同上（最新一份）
  data/index.json           歷史日期清單
  data/YYYYMMDD_claude.txt  貼給 Claude 的純文字數據表
  data/YYYYMMDD_spf_*.png   永豐 籌碼快訊／盤後快訊 轉圖
用法：python scripts/fetch_all.py [YYYY/MM/DD]
"""
import sys, os, io, re, json, datetime as dt
import requests, pandas as pd

TAIFEX = "https://www.taifex.com.tw/cht/3/"
TWSE   = "https://www.twse.com.tw/rwd/zh/"
SPF_LIST = "https://www.spf.com.tw/sinopacSPF/research/list.do?id=1709f20d3ff00000d8e2039e8984ed51"
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
     "Referer": "https://www.taifex.com.tw/cht/3/futContractsDate"}
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
os.makedirs(DATA, exist_ok=True)
ROLES = ["自營商", "投信", "外資"]
LOG = []
def log(s): LOG.append(s); print(s)

# ─────────────── 工具 ───────────────
def decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp950", "big5"):
        try: return raw.decode(enc)
        except UnicodeDecodeError: pass
    return raw.decode("utf-8", "ignore")

def num(x, default=0):
    if x is None: return default
    s = str(x).replace(",", "").replace("+", "").strip()
    if s in ("", "-", "--", "nan", "None"): return default
    try:
        f = float(s); return int(f) if f == int(f) and "." not in s else f
    except ValueError: return default

def ymd(d): return d.replace("/", "")

# ─────────────── 期交所：三大法人期貨 OI ───────────────
def taifex_fut(date):
    r = requests.post(TAIFEX + "futContractsDateDown",
                      data={"queryStartDate": date, "queryEndDate": date, "commodityId": ""}, headers=H, timeout=30)
    txt = decode(r.content)
    if "商品名稱" not in txt: return None
    df = pd.read_csv(io.StringIO(txt)); df.columns = [c.strip() for c in df.columns]
    return df if not df.empty else None

def fut_oi(df, name):
    sub = df[df["商品名稱"].astype(str).str.strip().str.replace("台", "臺") == name]
    out = {}
    for _, r in sub.iterrows():
        role = str(r["身份別"]).strip()
        if role in ROLES:
            out[role] = {"long": num(r["多方未平倉口數"]), "short": num(r["空方未平倉口數"]),
                         "net": num(r["多空未平倉口數淨額"]), "day_net": num(r["多空交易口數淨額"])}
    return out

# ─────────────── 期交所：全市場 OI（小台／微台 → 散戶多空比） ───────────────
def taifex_market_oi(date, code):
    r = requests.post(TAIFEX + "futDataDown",
                      data={"down_type": "1", "commodity_id": code, "queryStartDate": date, "queryEndDate": date},
                      headers=H, timeout=30)
    txt = decode(r.content)
    if "未沖銷" not in txt: return None
    df = pd.read_csv(io.StringIO(txt)); df.columns = [c.strip() for c in df.columns]
    col_oi = [c for c in df.columns if "未沖銷" in c][0]
    col_sess = [c for c in df.columns if "交易時段" in c]
    if col_sess: df = df[df[col_sess[0]].astype(str).str.contains("一般")]
    return int(pd.to_numeric(df[col_oi].astype(str).str.replace(",", ""), errors="coerce").fillna(0).sum())

def retail_ratio(market_oi, inst):
    """永豐口徑：散戶多單＝全市場OI−三大法人多單；散戶空單＝全市場OI−三大法人空單；比＝(多−空)/全市場OI"""
    if not market_oi or not inst: return None
    il = sum(v["long"] for v in inst.values()); is_ = sum(v["short"] for v in inst.values())
    rl, rs = market_oi - il, market_oi - is_
    return {"market_oi": market_oi, "retail_long": rl, "retail_short": rs,
            "retail_net": rl - rs, "ratio_pct": round((rl - rs) / market_oi * 100, 2)}

# ─────────────── 期交所：選擇權 買賣權分計（外資買/賣權淨OI） ───────────────
def taifex_opt(date):
    r = requests.post(TAIFEX + "callsAndPutsDateDown",
                      data={"queryStartDate": date, "queryEndDate": date, "commodityId": "TXO"}, headers=H, timeout=30)
    txt = decode(r.content)
    if "身份別" not in txt: return None
    df = pd.read_csv(io.StringIO(txt)); df.columns = [c.strip() for c in df.columns]
    c_role = [c for c in df.columns if "身份" in c][0]
    c_cp   = [c for c in df.columns if "權別" in c or "買賣權" in c][0]
    c_net  = [c for c in df.columns if "未平倉" in c and "淨額" in c and "口數" in c][0]
    out = {}
    for _, r in df.iterrows():
        role = str(r[c_role]).strip()
        if role not in ROLES: continue
        cp = "call" if "買" in str(r[c_cp]) else "put"
        out.setdefault(role, {})[cp] = num(r[c_net])
    return out

# ─────────────── 期交所：P/C ratio ───────────────
def taifex_pc(date):
    r = requests.post(TAIFEX + "pcRatioDown", data={"queryStartDate": date, "queryEndDate": date}, headers=H, timeout=30)
    txt = decode(r.content)
    if "買賣權" not in txt: return None
    df = pd.read_csv(io.StringIO(txt)); df.columns = [c.strip() for c in df.columns]
    row = df.iloc[-1]
    c_vol = [c for c in df.columns if "成交量比率" in c][0]; c_oi = [c for c in df.columns if "未平倉量比率" in c][0]
    return {"volume_ratio_pct": num(row[c_vol]), "oi_ratio_pct": num(row[c_oi])}

# ─────────────── 期交所：台指VIX（盡力而為，失敗以永豐為準） ───────────────
def taifex_vix(date):
    try:
        r = requests.post("https://www.taifex.com.tw/cht/7/vixMinNewDown",
                          data={"queryStartDate": date, "queryEndDate": date}, headers=H, timeout=30)
        txt = decode(r.content)
        df = pd.read_csv(io.StringIO(txt)); df.columns = [c.strip() for c in df.columns]
        c = [c for c in df.columns if "VIX" in c.upper() or "波動" in c][-1]
        return float(pd.to_numeric(df[c], errors="coerce").dropna().iloc[-1])
    except Exception as e:
        log(f"  VIX 抓取失敗（{e.__class__.__name__}），請以永豐快訊為準"); return None

# ─────────────── 證交所：加權指數／成交金額 ───────────────
def twse_index(date):
    r = requests.get(TWSE + "afterTrading/FMTQIK", params={"date": ymd(date), "response": "json"}, headers=H, timeout=30)
    j = r.json()
    if j.get("stat") != "OK": return None
    y, m, d = date.split("/"); roc = f"{int(y)-1911}/{m}/{d}"
    for row in j["data"]:   # 日期, 成交股數, 成交金額, 成交筆數, 加權指數, 漲跌點數
        if row[0].strip() == roc:
            return {"close": num(row[4]), "chg": num(row[5]), "amount_yi": round(num(row[2]) / 1e8)}
    return None

# ─────────────── 證交所：三大法人買賣超（億） ───────────────
def twse_inst(date):
    r = requests.get(TWSE + "fund/BFI82U", params={"dayDate": ymd(date), "type": "day", "response": "json"}, headers=H, timeout=30)
    j = r.json()
    if j.get("stat") != "OK": return None
    out = {}
    for row in j["data"]:
        name, net = row[0], num(row[3]) / 1e8
        if name.startswith("自營商"): out["自營"] = round(out.get("自營", 0) + net, 2)
        elif name.startswith("投信"): out["投信"] = round(net, 2)
        elif name.startswith("外資"): out["外資"] = round(out.get("外資", 0) + net, 2)
        elif name.startswith("合計"): out["合計"] = round(net, 2)
    return out

# ─────────────── 證交所：融資餘額（億） ───────────────
def twse_margin(date):
    r = requests.get(TWSE + "marginTrading/MI_MARGN", params={"date": ymd(date), "selectType": "MS", "response": "json"}, headers=H, timeout=30)
    j = r.json()
    if j.get("stat") != "OK": return None
    rows = j.get("creditList") or (j.get("tables", [{}])[0].get("data", []))
    for row in rows:
        if "融資金額" in str(row[0]):
            return round(num(row[5]) / 1e5, 1)   # 仟元 → 億
    return None

# ─────────────── 永豐 PDF → PNG ───────────────
def spf_fetch(date):
    try:
        from bs4 import BeautifulSoup; import fitz
    except ImportError:
        log("  永豐：缺 bs4/pymupdf，略過"); return {}
    html = requests.get(SPF_LIST, headers={"User-Agent": H["User-Agent"]}, timeout=30).text
    soup = BeautifulSoup(html, "html.parser"); out = {}
    for a in soup.select("a[href$='.pdf']"):
        title = a.get_text(strip=True)
        if title not in ("台指期籌碼快訊", "台指期盤後快訊"): continue
        m = re.search(r"\d{4}/\d{2}/\d{2}", a.parent.get_text(" "))
        if not m or m.group(0) != date: continue
        pdf = requests.get(a["href"], headers={"User-Agent": H["User-Agent"]}, timeout=60).content
        doc = fitz.open(stream=pdf, filetype="pdf")
        tag = "chips" if "籌碼" in title else "post"
        pngs = []
        for i, page in enumerate(doc):
            fn = f"{ymd(date)}_spf_{tag}_p{i+1}.png"
            page.get_pixmap(dpi=170).save(os.path.join(DATA, fn)); pngs.append(fn)
        out[title] = pngs
    if not out: log(f"  永豐：{date} 尚未上傳")
    return out

# ─────────────── 交易日搜尋 ───────────────
def prev_trading_day(date):
    d = dt.datetime.strptime(date, "%Y/%m/%d")
    for _ in range(12):
        d -= dt.timedelta(days=1)
        if d.weekday() >= 5: continue
        s = d.strftime("%Y/%m/%d"); df = taifex_fut(s)
        if df is not None: return s, df
    return None, None

def latest_trading_day():
    d = dt.datetime.utcnow() + dt.timedelta(hours=8)
    for _ in range(12):
        s = d.strftime("%Y/%m/%d")
        if d.weekday() < 5:
            df = taifex_fut(s)
            if df is not None: return s, df
        d -= dt.timedelta(days=1)
    return None, None

# ─────────────── 主流程 ───────────────
def collect(date, df):
    out = {"date": date}
    out["txf"] = fut_oi(df, "臺股期貨"); out["mtx"] = fut_oi(df, "小型臺指期貨"); out["tmf"] = fut_oi(df, "微型臺指期貨")
    for key, code in (("mtx", "MTX"), ("tmf", "TMF")):
        try: out[key + "_retail"] = retail_ratio(taifex_market_oi(date, code), out[key])
        except Exception as e: log(f"  {code} 全市場OI 失敗：{e}"); out[key + "_retail"] = None
    for k, f in (("opt", taifex_opt), ("pc", taifex_pc), ("index", twse_index), ("inst", twse_inst), ("margin", twse_margin)):
        try: out[k] = f(date)
        except Exception as e: log(f"  {k} 失敗：{e}"); out[k] = None
    out["vix"] = taifex_vix(date)
    return out

def s(n): return f"{n:+,}" if isinstance(n, int) else ("—" if n is None else str(n))

def claude_text(t, p):
    L = []; ix = t.get("index") or {}; pix = p.get("index") or {}
    L.append(f"【台股盤後數據】{t['date']}（前一交易日 {p['date']}）")
    if ix:
        chg_pct = (ix["chg"] / pix["close"] * 100) if pix.get("close") else None
        pc = f"{chg_pct:+.2f}%" if chg_pct is not None else "—"
        L.append(f"加權指數 {ix['close']:,}  {ix['chg']:+,}（自算 {pc}，分母前收 {pix.get('close','?')}）  成交 {ix['amount_yi']:,} 億")
    if t.get("inst"):
        i = t["inst"]; L.append(f"三大法人 {i.get('合計',0):+.2f} 億｜外資 {i.get('外資',0):+.2f}｜投信 {i.get('投信',0):+.2f}｜自營 {i.get('自營',0):+.2f}")
    if t.get("margin") is not None: L.append(f"融資餘額 {t['margin']:,} 億（前值 {p.get('margin','—')}）")
    L.append("── 臺股期貨 未平倉（前→今）──")
    for role in ROLES:
        a, b = t["txf"].get(role), p["txf"].get(role)
        if a and b:
            L.append(f"{role}：多 {b['long']:,}→{a['long']:,}（{s(a['long']-b['long'])}）  空 {b['short']:,}→{a['short']:,}（{s(a['short']-b['short'])}）  淨 {b['net']:,}→{a['net']:,}（{s(a['net']-b['net'])}）")
    if t.get("opt") and p.get("opt") and "外資" in t["opt"]:
        a, b = t["opt"]["外資"], p["opt"].get("外資", {})
        L.append(f"外資買權淨OI {b.get('call','—')}→{a.get('call')}（{s(a.get('call',0)-b.get('call',0))}）  賣權淨OI {b.get('put','—')}→{a.get('put')}（{s(a.get('put',0)-b.get('put',0))}）")
    for key, name in (("mtx_retail", "小台"), ("tmf_retail", "微台")):
        a, b = t.get(key), p.get(key)
        if a and b:
            L.append(f"{name}散戶多空比 {b['ratio_pct']:+.2f}% → {a['ratio_pct']:+.2f}%（散戶淨 {b['retail_net']:+,}→{a['retail_net']:+,}；全市場OI {a['market_oi']:,}）")
    if t.get("pc") and p.get("pc"):
        L.append(f"全市場 Put/Call（OI）{p['pc']['oi_ratio_pct']}% → {t['pc']['oi_ratio_pct']}%")
    if t.get("vix") is not None: L.append(f"台指VIX {p.get('vix','—')} → {t['vix']}")
    if t.get("spf"): L.append("永豐 PDF 已轉圖：" + "、".join(fn for v in t["spf"].values() for fn in v))
    L.append("資料：期交所（OI/選擇權/PC）＋證交所（指數/法人/融資）＋永豐（對照）；多空比為自算（永豐口徑）")
    return "\n".join(L)

def main():
    arg = [a for a in sys.argv[1:] if not a.startswith("--")]
    if arg:
        today = arg[0]; df_t = taifex_fut(today)
        if df_t is None: sys.exit(f"{today} 期交所尚無資料")
    else:
        today, df_t = latest_trading_day()
        if df_t is None: sys.exit("找不到近期資料")
    prev, df_p = prev_trading_day(today)
    log(f"今日 {today}｜前一交易日 {prev}")
    t = collect(today, df_t); p = collect(prev, df_p)
    t["spf"] = spf_fetch(today)
    t["prev"] = p; t["log"] = LOG
    t["generated_at"] = (dt.datetime.utcnow() + dt.timedelta(hours=8)).isoformat(timespec="seconds")
    t["claude_text"] = claude_text(t, p)

    tag = ymd(today)
    json.dump(t, open(os.path.join(DATA, f"{tag}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(t, open(os.path.join(DATA, "latest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(os.path.join(DATA, f"{tag}_claude.txt"), "w", encoding="utf-8").write(t["claude_text"])
    idx_path = os.path.join(DATA, "index.json")
    idx = json.load(open(idx_path)) if os.path.exists(idx_path) else []
    if tag not in idx: idx.append(tag); idx.sort(reverse=True)
    json.dump(idx[:250], open(idx_path, "w"), indent=0)
    print("\n" + t["claude_text"])

if __name__ == "__main__":
    main()
