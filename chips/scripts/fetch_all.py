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
import sys, os, io, re, json, time, datetime as dt
import requests, pandas as pd
from urllib.parse import urljoin

TAIFEX = "https://www.taifex.com.tw/cht/3/"
TWSE   = "https://www.twse.com.tw/rwd/zh/"
SPF_LIST = "https://www.spf.com.tw/sinopacSPF/research/list.do?id=1709f20d3ff00000d8e2039e8984ed51"
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
     "Referer": "https://www.taifex.com.tw/cht/3/futContractsDate"}
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
os.makedirs(DATA, exist_ok=True)
ROLES = ["自營商", "投信", "外資"]
def role_of(x):
    x = str(x).strip()
    if x.startswith("自營"): return "自營商"
    if x.startswith("投信"): return "投信"
    if x.startswith("外資"): return "外資"
    return None
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
    df = pd.read_csv(io.StringIO(txt), index_col=False); df.columns = [c.strip() for c in df.columns]; df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
    return df if not df.empty else None

def fut_oi(df, name):
    sub = df[df["商品名稱"].astype(str).str.strip().str.replace("台", "臺") == name]
    out = {}
    for _, r in sub.iterrows():
        role = role_of(r["身份別"])
        if role:
            out[role] = {"long": num(r["多方未平倉口數"]), "short": num(r["空方未平倉口數"]),
                         "net": num(r["多空未平倉口數淨額"]), "day_net": num(r["多空交易口數淨額"])}
    return out

# ─────────────── 期交所：全市場 OI（小台／微台 → 散戶多空比） ───────────────
def taifex_market_oi(date, code):
    r = requests.post(TAIFEX + "futDataDown",
                      data={"down_type": "1", "commodity_id": code, "queryStartDate": date, "queryEndDate": date},
                      headers=H, timeout=30)
    txt = decode(r.content)
    if "未沖銷" not in txt: log(f"  {code} 全市場OI：回應非預期（前 80 字）{txt[:80]!r}"); return None
    df = pd.read_csv(io.StringIO(txt), dtype=str, index_col=False); df.columns = [c.strip() for c in df.columns]; df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
    col_oi = [c for c in df.columns if "未沖銷" in c][0]
    col_sess = [c for c in df.columns if "交易時段" in c]
    sub = df
    if col_sess:
        sub = df[df[col_sess[0]].astype(str).str.contains("一般")]
        if sub.empty: sub = df[~df[col_sess[0]].astype(str).str.contains("盤後")]
        if sub.empty: sub = df
    vals = pd.to_numeric(sub[col_oi].astype(str).str.replace(",", "").str.strip(), errors="coerce").fillna(0)
    total = int(vals.sum())
    if total == 0:
        log(f"  {code} 全市場OI=0；欄位 {df.columns.tolist()}；列數 {len(df)}；時段值 {df[col_sess[0]].unique()[:4].tolist() if col_sess else '-'}；OI樣本 {df[col_oi].head(3).tolist()}")
        return None
    log(f"  {code} 全市場OI {total:,}（{len(sub)} 列；欄 {col_oi}）")
    return total

def taifex_tx_close(date):
    """臺股期貨近月：一般時段收盤、盤後（夜盤）收盤"""
    r = requests.post(TAIFEX + "futDataDown",
                      data={"down_type": "1", "commodity_id": "TX", "queryStartDate": date, "queryEndDate": date},
                      headers=H, timeout=30)
    txt = decode(r.content)
    if "收盤價" not in txt: log("  TX 收盤：CSV 無收盤價欄"); return None
    df = pd.read_csv(io.StringIO(txt), dtype=str, index_col=False); df.columns = [c.strip() for c in df.columns]
    c_m = [c for c in df.columns if "到期月份" in c][0]; c_close = [c for c in df.columns if c.startswith("收盤價")][0]
    c_sess = [c for c in df.columns if "交易時段" in c]
    df = df[df[c_m].astype(str).str.strip().str.fullmatch(r"\d{6}")]          # 排除價差/週選
    if df.empty: return None
    near = sorted(df[c_m].astype(str).str.strip().unique())[0]
    sub = df[df[c_m].astype(str).str.strip() == near]
    def close_of(mask):
        v = pd.to_numeric(sub[mask][c_close].astype(str).str.replace(",", ""), errors="coerce").dropna()
        return float(v.iloc[0]) if len(v) else None
    if c_sess:
        day = close_of(sub[c_sess[0]].astype(str).str.contains("一般")); night = close_of(sub[c_sess[0]].astype(str).str.contains("盤後"))
    else:
        day, night = close_of(pd.Series(True, index=sub.index)), None
    return {"contract": near, "close": day, "night_close": night}

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
    if "身份別" not in txt: log("  選擇權：CSV 無身份別欄"); return None
    df = pd.read_csv(io.StringIO(txt), index_col=False); df.columns = [c.strip() for c in df.columns]; df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
    c_role = [c for c in df.columns if "身份" in c][0]
    c_cp   = [c for c in df.columns if "權別" in c or "買賣權" in c][0]
    c_net  = [c for c in df.columns if "未平倉" in c and "淨額" in c and "口數" in c][0]
    df[c_role] = df[c_role].ffill(); df[c_cp] = df[c_cp].ffill()      # CSV 合併儲存格會留空 → 往下補
    out = {}
    for _, r in df.iterrows():
        role = role_of(r[c_role])
        if not role: continue
        cp_raw = str(r[c_cp]).strip().upper()
        cp = "call" if ("買" in cp_raw or "CALL" in cp_raw) else "put" if ("賣" in cp_raw or "PUT" in cp_raw) else None
        if cp: out.setdefault(role, {})[cp] = num(r[c_net])
    if "外資" in out and ("call" not in out["外資"] or "put" not in out["外資"]):
        log(f"  選擇權：外資僅抓到 {list(out['外資'])}；權別欄值範例 {df[c_cp].dropna().unique()[:4].tolist()}")
    return out

# ─────────────── 期交所：P/C ratio ───────────────
def taifex_pc(date):
    r = requests.post(TAIFEX + "pcRatioDown", data={"queryStartDate": date, "queryEndDate": date}, headers=H, timeout=30)
    txt = decode(r.content)
    if "買賣權" not in txt: log(f"  P/C：回應非預期（前 80 字）{txt[:80]!r}"); return None
    df = pd.read_csv(io.StringIO(txt), dtype=str, index_col=False); df.columns = [c.strip() for c in df.columns]; df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
    c_date = [c for c in df.columns if "日期" in c][0]
    c_vol = [c for c in df.columns if "成交量比率" in c][0]; c_oi = [c for c in df.columns if "未平倉量比率" in c][0]
    def f(v):
        m = re.search(r"-?\d+(?:\.\d+)?", str(v).replace(",", "")); return float(m.group()) if m else None
    rows = df[df[c_date].astype(str).str.strip() == date]
    if rows.empty: rows = df.dropna(subset=[c_oi])
    if rows.empty: log(f"  P/C：無資料列，原始前 2 列 {df.head(2).values.tolist()}"); return None
    row = rows.iloc[0]
    return {"volume_ratio_pct": f(row[c_vol]), "oi_ratio_pct": f(row[c_oi])}

# ─────────────── 期交所：台指VIX（盡力而為，失敗以永豐為準） ───────────────
def taifex_vix(date):
    return None   # 期交所無 CSV 端點，VIX 以永豐快訊為準

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
    try: j = r.json()
    except Exception: log(f"  融資：非 JSON 回應 {r.text[:80]!r}"); return None
    log(f"  融資 keys：{list(j.keys())[:8]}")
    if j.get("stat") != "OK": log(f"  融資：證交所回 {j.get('stat')}"); return None
    rows = j.get("creditList") or []
    for tb in j.get("tables", []):
        rows += tb.get("data", []) or []
    for row in rows:
        if "融資金額" in str(row[0]):
            return round(num(row[-1]) / 1e5, 1)   # 最後一欄＝今日餘額（仟元→億）
    log("  融資：找不到「融資金額」列"); return None

# ─────────────── 永豐 PDF → PNG ───────────────
def spf_fetch(date):
    out = {}
    try:
        from bs4 import BeautifulSoup
        try: import pymupdf as fitz
        except ImportError: import fitz
        ua = {"User-Agent": H["User-Agent"]}
        html = requests.get(SPF_LIST, headers=ua, timeout=30).text
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("a[href$='.pdf']"):
            title = a.get_text(strip=True)
            if title not in ("台指期籌碼快訊", "台指期盤後快訊"): continue
            m = re.search(r"\d{4}/\d{2}/\d{2}", a.parent.get_text(" "))
            if not m or m.group(0) != date: continue
            url = urljoin("https://www.spf.com.tw/", a["href"])       # 相對路徑補成完整網址
            pdf = requests.get(url, headers=ua, timeout=60).content
            doc = fitz.open(stream=pdf, filetype="pdf")
            tag = "chips" if "籌碼" in title else "post"
            pngs = []
            max_pages = 1 if tag == "chips" else 2       # 籌碼快訊 1 頁；盤後快訊只留前 2 頁
            for i, page in enumerate(doc):
                if i >= max_pages: break
                fn = f"{ymd(date)}_spf_{tag}_p{i+1}.png"
                page.get_pixmap(dpi=170).save(os.path.join(DATA, fn)); pngs.append(fn)
            out[title] = pngs
        if not out: log(f"  永豐：{date} 尚未上傳")
    except Exception as e:
        log(f"  永豐抓取失敗（{e.__class__.__name__}: {e}），略過")
    return out

# ─────────────── 清舊圖 ───────────────
def cleanup_pngs(tag, keep):
    """刪掉：(1) 當日不在 spf 清單裡的 png（舊版曾把盤後快訊轉出 30 頁）；(2) 30 天前的 png（json 留著）。
    當日 spf 一張都沒抓到（永豐尚未上傳／抓失敗）就不碰當日的圖，避免把上一班抓好的刪掉。"""
    cutoff = (dt.datetime.utcnow() + dt.timedelta(hours=8) - dt.timedelta(days=30)).strftime("%Y%m%d")
    removed = []
    for fn in os.listdir(DATA):
        if not fn.endswith(".png"): continue
        day = fn[:8]
        stale_today = day == tag and keep and fn not in keep
        too_old = day.isdigit() and day < cutoff
        if stale_today or too_old:
            os.remove(os.path.join(DATA, fn)); removed.append(fn)
    if removed: log(f"  清掉 {len(removed)} 張舊圖：{', '.join(removed[:5])}{'…' if len(removed) > 5 else ''}")

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
        try:
            moi = taifex_market_oi(date, code)
            if not out[key]: log(f"  {code} 三大法人列為空（商品名稱比對失敗？CSV 商品名：{df['商品名稱'].astype(str).str.strip().unique()[:6].tolist()}）")
            out[key + "_retail"] = retail_ratio(moi, out[key])
        except Exception as e: log(f"  {code} 全市場OI 失敗：{e}"); out[key + "_retail"] = None
    for k, f in (("opt", taifex_opt), ("pc", taifex_pc), ("index", twse_index), ("inst", twse_inst), ("margin", twse_margin)):
        try: out[k] = f(date)
        except Exception as e: log(f"  {k} 失敗：{e}"); out[k] = None
    out["vix"] = taifex_vix(date)
    try:
        out["tx"] = taifex_tx_close(date)
        if out["tx"] and out.get("index") and out["tx"].get("close"):
            out["basis"] = round(out["tx"]["close"] - out["index"]["close"], 2)
    except Exception as e: log(f"  TX 收盤失敗：{e}"); out["tx"] = None
    missing = [k for k in ("opt", "pc", "index", "inst", "margin", "mtx_retail", "tmf_retail") if out.get(k) is None]
    if "外資" not in out["txf"]: missing.append("txf.外資")
    if missing:
        log(f"  {date} 缺：{', '.join(missing)}")
        print(f"::warning title=欄位缺漏 {date}::{', '.join(missing)}")
    out["missing"] = missing
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
    if t.get("margin") is not None:
        L.append(f"融資餘額 {t['margin']:,} 億（證交所口徑，含 ETF；" + (t['margin_note'] if t.get("margin_note") else f"前值 {p.get('margin','—')}") + "）")
    if t.get("tx") and t["tx"].get("close"):
        b = t.get("basis"); L.append(f"台指期近月收 {t['tx']['close']:,.0f}（{'正' if b and b>=0 else '逆'}價差 {b:+,.0f}）" + (f"　夜盤收 {t['tx']['night_close']:,.0f}" if t['tx'].get('night_close') else ""))
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
    if LOG: L.append("── 抓取日誌 ──"); L += LOG
    return "\n".join(L)

# ─────────────── 收尾 / 寫檔(單日與回補共用) ───────────────
def finish_day(t, p):
    """補上依賴前一日的欄位:融資沿用、prev、claude_text、昨日摘要。"""
    if t.get("margin") is None and p.get("margin") is not None:
        t["margin"] = p["margin"]; t["margin_note"] = f"證交所尚未公布，沿用 {p['date']} 值"; log("  融資：" + t["margin_note"])
    t["prev"] = p; t["log"] = LOG
    t["generated_at"] = (dt.datetime.utcnow() + dt.timedelta(hours=8)).isoformat(timespec="seconds")
    t["claude_text"] = claude_text(t, p)
    prev_file = os.path.join(DATA, f"{ymd(p['date'])}.json")     # 給「複製給 Claude」用的昨日摘要（前 4 行）
    if os.path.exists(prev_file):
        try:
            pj = json.load(open(prev_file, encoding="utf-8"))
            t["prev_summary"] = "\n".join((pj.get("claude_text") or "").splitlines()[:4])
        except Exception: pass

def load_index():
    p = os.path.join(DATA, "index.json")
    return json.load(open(p)) if os.path.exists(p) else []

def save_index(idx):
    idx = sorted(set(idx), reverse=True)[:250]
    json.dump(idx, open(os.path.join(DATA, "index.json"), "w"), indent=0)

def write_day(t, idx, latest):
    tag = ymd(t["date"])
    json.dump(t, open(os.path.join(DATA, f"{tag}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(os.path.join(DATA, f"{tag}_claude.txt"), "w", encoding="utf-8").write(t["claude_text"])
    if latest: json.dump(t, open(os.path.join(DATA, "latest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if tag not in idx: idx.append(tag)

# ─────────────── 回補 ───────────────
def backfill(n, start=None):
    """往回補 n 個交易日（20 日走勢圖用）。從 start（YYYY/MM/DD）或最近交易日往前找 n+1 個有期交所資料的日子，
    每日 collect 一次；已有 {tag}.json 的日子略過（不覆蓋當日含永豐圖的正式檔）。永豐 PDF 只有當日，回補不抓；不動 latest.json。"""
    if start:
        today, df = start, taifex_fut(start)
    else:
        today, df = latest_trading_day()
    if df is None: sys.exit("回補：找不到起始交易日")
    days = [(today, df)]
    while len(days) < n + 1:
        d, f = prev_trading_day(days[-1][0])
        if d is None: break
        days.append((d, f)); time.sleep(0.5)
    log(f"回補 {len(days) - 1} 個交易日：{days[-1][0]}（僅當前一日）… {today}")
    cols = []
    for d, f in days:
        log(f"— {d}"); cols.append(collect(d, f)); time.sleep(1)
    idx = load_index(); written = []
    for i in range(len(cols) - 2, -1, -1):                     # 由舊到新，昨日摘要才接得上
        t, p = cols[i], cols[i + 1]; tag = ymd(t["date"])
        if os.path.exists(os.path.join(DATA, f"{tag}.json")): log(f"  {tag} 已存在，略過"); continue
        finish_day(t, p); write_day(t, idx, latest=False); written.append(tag)
    save_index(idx)
    print(f"\n回補完成：寫入 {len(written)} 天 {written[:1]}…{written[-1:] if written else ''}；略過 {len(cols) - 1 - len(written)} 天")

# ─────────────── 主流程 ───────────────
def main():
    argv = sys.argv[1:]
    n_back = 0                                                     # python fetch_all.py [YYYY/MM/DD] --backfill 20
    if "--backfill" in argv:
        k = argv.index("--backfill"); n_back = 20
        if k + 1 < len(argv) and argv[k + 1].isdigit(): n_back = int(argv[k + 1]); del argv[k + 1]   # 數字是 --backfill 的值，不是日期
        del argv[k]
    arg = [a for a in argv if not a.startswith("--")]
    if n_back: return backfill(n_back, arg[0] if arg else None)
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
    cleanup_pngs(ymd(today), {fn for v in t["spf"].values() for fn in v})
    finish_day(t, p)
    idx = load_index(); write_day(t, idx, latest=True); save_index(idx)
    print("\n" + t["claude_text"])

if __name__ == "__main__":
    main()
