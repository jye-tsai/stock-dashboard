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
import sys, os, io, re, json, time, math, bisect, datetime as dt
import requests, pandas as pd
from urllib.parse import urljoin

TAIFEX = "https://www.taifex.com.tw/cht/3/"
TWSE   = "https://www.twse.com.tw/rwd/zh/"
SPF_LIST = "https://www.spf.com.tw/sinopacSPF/research/list.do?id=1709f20d3ff00000d8e2039e8984ed51"
VIX_URL = "https://www.taifex.com.tw/file/taifex/Dailydownload/vix/log2data/"   # + YYYYMMnew.txt
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

def fut_ready(df):
    """期交所盤後三大法人未平倉約 15:00 才算好;在那之前查得到當天的列,但多空未平倉全是 0 → 視為尚未公布"""
    try:
        o = fut_oi(df, "臺股期貨")
        return any(((v.get("long") or 0) + (v.get("short") or 0)) > 0 for v in o.values())
    except Exception: return False

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
_VIX_CACHE = {}
def taifex_vix(date):
    """臺指選擇權波動率指數（台版 VIX）當日收盤值。
    來源：期交所「前 3 個月每日收盤之臺指選擇權波動率指數」的月檔（big5、tab 分隔），
          https://www.taifex.com.tw/file/taifex/Dailydownload/vix/log2data/YYYYMMnew.txt
          欄位：交易日期 / 時間 / 波動率指數 / 收盤前 1 分鐘平均；只留近 3 個月，更早的月份抓不到會回 None。
    同一個月的檔只抓一次（回補 20 天最多打 2 支）。值與永豐快訊「VIX 指標」一致。"""
    tag = ymd(date); ym = tag[:6]
    if ym not in _VIX_CACHE:
        m = {}
        try:
            r = requests.get(VIX_URL + ym + "new.txt", headers=H, timeout=30)
            for ln in r.content.decode("big5", "replace").splitlines():
                c = [x.strip() for x in ln.split("\t") if x.strip()]
                if len(c) >= 3 and c[0].isdigit() and len(c[0]) == 8:
                    try: m[c[0]] = float(c[2])
                    except ValueError: pass
            if not m: log(f"  VIX：{ym} 月檔沒有可解析的資料列")
        except Exception as e:
            log(f"  VIX 抓取失敗（{e.__class__.__name__}: {e}）")
        _VIX_CACHE[ym] = m
    return _VIX_CACHE[ym].get(tag)

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
        if df is not None and fut_ready(df): return s, df
    return None, None

def latest_trading_day():
    d = dt.datetime.utcnow() + dt.timedelta(hours=8)
    for _ in range(12):
        s = d.strftime("%Y/%m/%d")
        if d.weekday() < 5:
            df = taifex_fut(s)
            if df is not None and fut_ready(df): return s, df
            if df is not None: log(f"  {s} 期交所三大法人尚未算好(未平倉全為 0),改用前一交易日")
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
    out["fx"] = fx_for(date)                       # 美元兌台幣 / 美元指數(胖虎指標用)
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
        b = t.get("basis")   # 盤後早班跑時證交所指數可能還沒公布 → basis 是 None,不能直接格式化
        bs = f"（{'正' if b >= 0 else '逆'}價差 {b:+,.0f}）" if b is not None else "（價差 —,加權指數尚未公布）"
        L.append(f"台指期近月收 {t['tx']['close']:,.0f}" + bs + (f"　夜盤收 {t['tx']['night_close']:,.0f}" if t['tx'].get('night_close') else ""))
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

# ─────────────── 價量 / 籌碼衍生解讀 ───────────────
# 只用已經在收的欄位(加權收盤 / 漲跌 / 成交金額 / 融資餘額 / 外資現貨 / 基差)算,不加新來源。
# 結果存進當日 json 的 insight,前端「今日解讀」卡與 LINE 訊息共用一份,不各算各的。
def recent_days(n, skip_tag):
    """由舊到新讀「skip_tag 之前」最近 n 天已存檔的當日 json;讀不到就跳過。
    只取比當天早的日子:回補舊日子時 index 裡有之後的日期,不排除會偷看未來(每天盤後跑時當天就是最新一天,不受影響)"""
    out = []
    for tag in load_index():                       # index.json 是新到舊
        if tag >= skip_tag: continue
        try: out.append(json.load(open(os.path.join(DATA, f"{tag}.json"), encoding="utf-8")))
        except Exception: continue
        if len(out) >= n: break
    return list(reversed(out))

def _close(d): return ((d or {}).get("index") or {}).get("close")
def _amt(d): return ((d or {}).get("index") or {}).get("amount_yi")

def build_insight(t, p, hist):
    out = {}; L = []
    ix = t.get("index") or {}
    amt, chg, close = _amt(t), ix.get("chg"), ix.get("close")

    amts = [a for a in (_amt(h) for h in hist) if a]
    if amt and len(amts) >= 5:                                     # ① 量能水位:今日量 vs 近 N 日均量
        avg = sum(amts) / len(amts); r = amt / avg * 100
        lvl = "爆量" if r >= 150 else "放量" if r >= 120 else "縮量" if r <= 80 else "正常量"
        out["volume"] = {"amount": amt, "avg": round(avg), "ratio_pct": round(r, 1), "days": len(amts), "level": lvl}
        L.append(f"量能 {lvl}:{amt:,} 億,為近 {len(amts)} 日均量 {round(avg):,} 億的 {r:.0f}%")

    pamt = _amt(p)
    if amt and pamt and chg is not None:                           # ② 價量配合四象限
        up, more = chg > 0, amt > pamt
        label = "漲+放量" if up and more else "漲+縮量" if up else "跌+放量" if more else "跌+縮量"
        note = {"漲+放量": "量價配合,買盤跟上", "漲+縮量": "價量背離,追價意願低",
                "跌+放量": "賣壓宣洩,留意恐慌", "跌+縮量": "殺盤縮手,可能止穩"}[label]
        out["pv"] = {"label": label, "note": note, "amount_chg_pct": round((amt / pamt - 1) * 100, 1)}
        L.append(f"價量 {label}:{note}(量較前日 {(amt / pamt - 1) * 100:+.1f}%)")

    seq = hist + [t]
    # ③ 融資 vs 指數(近 5 個交易日)。證交所融資收盤後才出,15:40 / 16:40 兩班通常拿不到 → collect 會沿用前日值並留 margin_note;
    #    那種情況這行不算,免得拿昨天的數字掛「5 日」標籤產生假訊號(21:30 那班補到真值後自然會回來)。
    if len(seq) >= 6 and close and not t.get("margin_note"):
        base = seq[-6]; m0, m1, c0 = base.get("margin"), t.get("margin"), _close(base)
        if m0 and m1 and c0:
            dm, dc = (m1 - m0) / m0 * 100, (close / c0 - 1) * 100
            sig = ("籌碼乾淨:指數漲、融資降" if dc > 0 and dm < 0 else
                   "散戶追價:指數漲、融資也增" if dc > 0 else
                   "套牢加碼:指數跌、融資反增" if dm > 0 else "融資退場:指數跌、融資也降")
            out["margin"] = {"days": 5, "index_pct": round(dc, 2), "margin_pct": round(dm, 2), "signal": sig}
            L.append(f"融資 5 日:{sig}(指數 {dc:+.2f}%、融資 {dm:+.2f}%)")

    fs = [((h.get("inst") or {}).get("外資")) for h in seq]         # ④ 外資現貨連買 / 連賣 + 同期指數
    if fs and fs[-1] is not None:
        run, s = 0, 1 if fs[-1] > 0 else -1 if fs[-1] < 0 else 0
        if s:
            for v in reversed(fs):
                if v is None or (v > 0) != (s > 0) or v == 0: break
                run += 1
        if run >= 2:
            c0 = _close(seq[-run - 1]) if len(seq) > run else None
            dc = (close / c0 - 1) * 100 if c0 and close else None
            word = "連買" if s > 0 else "連賣"
            diverge = dc is not None and ((s > 0 and dc < 0) or (s < 0 and dc > 0))
            out["foreign"] = {"run": run, "side": word, "index_pct": None if dc is None else round(dc, 2), "diverge": diverge}
            L.append(f"外資現貨{word} {run} 日" + (f",同期指數 {dc:+.2f}%" if dc is not None else "") + (" ← 背離,留意對作" if diverge else ""))

    vx = t.get("vix"); vs = [h.get("vix") for h in hist if h.get("vix")]
    if vx and len(vs) >= 5:                                        # ⑥ VIX 水位(近 N 日均與區間)
        avg = sum(vs) / len(vs); hi, lo = max(vs), min(vs)
        lvl = "偏高・恐慌升溫" if vx >= avg * 1.2 else "偏低・波動鈍化" if vx <= avg * 0.8 else "中性"
        out["vix"] = {"now": vx, "avg": round(avg, 2), "hi": hi, "lo": lo, "level": lvl}
        L.append(f"VIX {vx}（{lvl}）：近 {len(vs)} 日均 {avg:.1f}、區間 {lo}～{hi}")

    bs = [h.get("basis") for h in hist[-5:] if h.get("basis") is not None]
    if t.get("basis") is not None and len(bs) >= 3:                # ⑤ 基差 vs 近 5 日均
        avg = sum(bs) / len(bs); now = t["basis"]
        sig = "正價差走闊,期貨偏多" if now > avg and now > 0 else "逆價差擴大,避險轉空" if now < avg and now < 0 else "價差收斂"
        out["basis"] = {"now": now, "avg5": round(avg, 2), "signal": sig}
        L.append(f"基差 {now:+.0f}(近 5 日均 {avg:+.0f}):{sig}")

    out["lines"] = L
    return out

# ─────────────── 匯率(Yahoo):美元兌台幣 TWD=X、美元指數 DX-Y.NYB ───────────────
# 一次抓 3 個月日線快取起來(回補 20 天也只打 2 支);Yahoo 日線用 UTC 日期,台北盤後看到的是最近一個已收盤的美國交易日,
# 拿來判斷方向足夠。某些日子 close 會是 null(Yahoo 常態),取「該日(含)以前最後一筆有值」。
FX_SYMS = {"usdtwd": "TWD=X", "dxy": "DX-Y.NYB"}
FX_RANGE = "3mo"                                   # 回測(backtest.py)會改成 2y
_FX_CACHE = {}
def _fx_series(sym):
    if sym in _FX_CACHE: return _FX_CACHE[sym]
    m = {}
    try:
        r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}", params={"interval": "1d", "range": FX_RANGE},
                         headers={"User-Agent": H["User-Agent"], "Accept": "application/json"}, timeout=30)
        res = r.json()["chart"]["result"][0]
        for ts, c in zip(res["timestamp"], res["indicators"]["quote"][0]["close"]):
            if c: m[dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y/%m/%d")] = round(float(c), 4)
        if not m: log(f"  匯率 {sym}:Yahoo 回傳沒有可用收盤")
    except Exception as e: log(f"  匯率 {sym} 抓取失敗({e.__class__.__name__}: {e})")
    _FX_CACHE[sym] = m
    return m

def fx_for(date):
    out = {}
    for k, sym in FX_SYMS.items():
        m = _fx_series(sym); ds = sorted(d for d in m if d <= date)
        if ds: out[k] = m[ds[-1]]; out[k + "_date"] = ds[-1]
    return out or None

# ─────────────── 胖虎指標(v2 情境版) ───────────────
# 13 項指標各自判斷「情境」,情境決定分數(-2~+2)與說法,全部寫在 chips/panghu.json;乘權重加總映射成 0~100 溫度,
# 再對應 0%~100% 建議倉位(每 10% 一級,越過邊界 buffer 分才換級,加碼另需外資現貨買超),最後依防線 / 第二道產生紀律動作。
# 這是機械式指標加總,規則與權重全在設定檔,不是投資建議。
PANGHU_CFG_PATH = os.path.join(DATA, "..", "panghu.json")
def load_panghu_cfg():
    return json.load(open(PANGHU_CFG_PATH, encoding="utf-8"))

def _mean(xs): return sum(xs) / len(xs) if xs else None
def _lvl(rows, v):
    cur = rows[0]
    for r in rows:
        if v >= r["min"]: cur = r
    return cur
def _fmt(tpl, **kw):
    try: return tpl.format(**kw)
    except Exception: return tpl
def _run(vals, sign):
    """由最後往前數,連續同號(sign>0 正、<0 負)的筆數;遇 None / 0 / 反號停"""
    n = 0
    for v in reversed(vals):
        if v is None or v == 0 or (v > 0) != (sign > 0): break
        n += 1
    return n

def build_panghu(t, p, hist, cfg):
    W, TH, NM, SC = cfg["weights"], cfg["thresholds"], cfg["names"], cfg["scenarios"]
    FLAT = TH.get("flat_pct", 0.3)
    ix = t.get("index") or {}; close, chg, amt = ix.get("close"), ix.get("chg"), ix.get("amount_yi")
    pclose = _close(p) or (close - chg if (close and chg is not None) else None)
    cp = (chg / pclose * 100) if (chg is not None and pclose) else None           # 今日指數漲跌 %
    seq = hist + [t]; items = []
    def add(k, key, **kw):
        s = (SC.get(k) or {}).get(key)
        if not s: return
        items.append({"k": k, "name": NM.get(k, k), "scenario": key, "score": max(-2, min(2, int(s["score"]))),
                      "w": W.get(k, 0), "note": _fmt(s["text"], **kw)})

    # ① 趨勢:收盤對均線乖離 + 今日是否剛穿越 + 今日方向
    th = TH["trend"]; n = th["ma_days"]
    closes = [c for c in (_close(h) for h in seq[-n:]) if c]
    if close and len(closes) >= 5:
        ma = _mean(closes); gap = (close / ma - 1) * 100
        pcl = [c for c in (_close(h) for h in hist[-n:]) if c]
        pgap = (pcl[-1] / _mean(pcl) - 1) * 100 if len(pcl) >= 5 else None
        up = (chg or 0) > 0
        key = ("overheat" if gap >= th["hot_pct"] else "strong_bull" if gap >= th["strong_pct"] else
               "oversold" if gap <= -th["hot_pct"] else "strong_bear" if gap <= -th["strong_pct"] else
               "cross_up" if (pgap is not None and pgap <= 0 < gap) else
               "cross_down" if (pgap is not None and pgap >= 0 > gap) else
               ("above" if up else "above_pullback") if gap > th["weak_pct"] else
               ("below_rebound" if up else "below") if gap < -th["weak_pct"] else "flat")
        add("trend", key, close=close, ma=ma, n=len(closes), gap=gap)

    # ② 量能:今日量對均量 × 漲跌方向
    th = TH["volume"]; amts = [a for a in (_amt(h) for h in hist[-th["avg_days"]:]) if a]
    if amt and len(amts) >= 5 and cp is not None:
        r = amt / _mean(amts); ratio = r * 100
        dirn = "up" if cp > FLAT else "down" if cp < -FLAT else "flat"
        key = ({"up": "surge_up", "down": "surge_down", "flat": "surge_flat"}[dirn] if r >= th["strong"] else
               {"up": "high_up", "down": "high_down", "flat": "high_flat"}[dirn] if r >= th["hi"] else
               "dry" if r <= th["dry"] else
               ({"up": "low_up", "down": "low_down"}.get(dirn, "normal")) if r <= th["low"] else "normal")
        add("volume", key, amt=amt, n=len(amts), ratio=ratio, cp=cp)

    # ③ 價量配合(日對日)
    pamt = _amt(p)
    if amt and pamt and cp is not None:
        dpct = (amt / pamt - 1) * 100; more = amt > pamt
        dirn = "up" if cp > FLAT else "down" if cp < -FLAT else "flat"
        add("pv", f"{dirn}_{'more' if more else 'less'}", cp=cp, dpct=dpct)

    # ④ 外資現貨:金額、連買連賣、翻多翻空、與指數背離
    th = TH["foreign_spot"]; fs = [((h.get("inst") or {}).get("外資")) for h in seq]
    fx = fs[-1]; fx_prev = fs[-2] if len(fs) >= 2 else None
    if fx is not None:
        if abs(fx) < th["small_yi"]: key = "flat"; run = 0
        else:
            s = 1 if fx > 0 else -1; run = _run(fs, s)
            big = abs(fx) >= th["big_yi"] or run >= th["run_days"]
            turn = fx_prev is not None and fx_prev * s < 0
            div = cp is not None and ((s > 0 and cp < -FLAT) or (s < 0 and cp > FLAT))
            key = (("big_buy" if big else "turn_buy" if turn else "buy_index_down" if div else "buy") if s > 0 else
                   ("big_sell" if big else "turn_sell" if turn else "sell_index_up" if div else "sell"))
        add("foreign_spot", key, fx=fx, run=run, cp=cp or 0, fx_prev=fx_prev or 0)

    # ⑤⑥ 外資期貨多單 / 空單(分開計分;合併動作與淨空水位寫在說明裡)
    th = TH["fut"]; fu, fp = (t.get("txf") or {}).get("外資"), (p.get("txf") or {}).get("外資")
    if fu and fp:
        dl, ds = fu["long"] - fp["long"], fu["short"] - fp["short"]
        def mv(d): return 0 if abs(d) < th["deadzone"] else (2 if abs(d) >= th["big"] else 1) * (1 if d > 0 else -1)
        ml, ms = mv(dl), mv(ds)
        ck = ((("add_long" if ml > 0 else "cut_long") + "_" + ("add_short" if ms > 0 else "cut_short")) if (ml and ms) else
              ("add_long" if ml > 0 else "cut_long") if ml else ("add_short" if ms > 0 else "cut_short") if ms else "none")
        combo = SC["fut_combo"].get(ck, "")
        base = th["baseline_net"]; net = fu["net"]
        net_note = f"淨空 {abs(net):,} 口,{'低於' if net > base else '高於'} {abs(base) // 10000} 萬口基態"
        kl = {2: "big_add", 1: "add", 0: "flat", -1: "cut", -2: "big_cut"}[ml]
        ks = {2: "big_add", 1: "add", 0: "flat", -1: "cut", -2: "big_cut"}[ms]
        add("fut_long", kl, d=dl, combo=combo); add("fut_short", ks, d=ds, net_note=net_note)

    # ⑦ 散戶多空比(反指標;大漲日翻空 = 軋空燃料、大跌日翻多 = 接刀)
    th = TH["retail"]
    def rmean(d): xs = [x["ratio_pct"] for x in ((d or {}).get("mtx_retail"), (d or {}).get("tmf_retail")) if x and x.get("ratio_pct") is not None]; return _mean(xs)
    r, rp = rmean(t), rmean(p)
    if r is not None:
        dr = (r - rp) if rp is not None else 0
        key = ("squeeze_fuel" if (cp is not None and cp >= th["big_move_pct"] and dr <= -th["flip"]) else
               "catch_knife" if (cp is not None and cp <= -th["big_move_pct"] and dr >= th["flip"]) else
               "zero" if abs(r) < th["zero"] else
               "extreme_long" if r >= th["strong"] else "long" if r >= th["mild"] else
               "extreme_short" if r <= -th["strong"] else "short" if r <= -th["mild"] else "neutral")
        add("retail", key, r=r, rp=rp if rp is not None else r)

    # ⑧ P/C(OI):水位 + 單日急升急降
    th = TH["pc"]; pcv = (t.get("pc") or {}).get("oi_ratio_pct"); pp = (p.get("pc") or {}).get("oi_ratio_pct")
    if pcv is not None:
        d = (pcv - pp) if pp is not None else 0
        key = ("very_high" if pcv >= th["strong_hi"] else "very_low" if pcv <= th["strong_lo"] else
               "jump_up" if d >= th["jump"] else "jump_down" if d <= -th["jump"] else
               "high" if pcv >= th["hi"] else "low" if pcv <= th["lo"] else "neutral")
        add("pc", key, pc=pcv, pp=pp if pp is not None else pcv)

    # ⑨ VIX:絕對高檔、單日驟升 / 退潮、過度安逸、對近期均值
    th = TH["vix"]; vx = t.get("vix"); vs = [h.get("vix") for h in hist if h.get("vix")]
    vp = hist[-1].get("vix") if hist else None
    if vx:
        dd = (vx / vp - 1) if vp else 0; avg = _mean(vs) if len(vs) >= 5 else None
        g = (vx / avg - 1) if avg else None
        key = ("panic_abs" if vx >= th["abs_hi"] else "spike" if (vp and dd >= th["spike"]) else
               "calm_down" if (vp and dd <= -th["spike"]) else "complacent" if vx <= th["abs_lo"] else
               None if g is None else
               "very_low" if g <= -th["strong"] else "low" if g <= -th["mild"] else
               "very_high" if g >= th["strong"] else "high" if g >= th["mild"] else "normal")
        if key: add("vix", key, vx=vx, vp=vp or vx, dd=dd * 100, n=len(vs), avg=avg or vx)

    # ⑩ 融資 vs 指數(融資沿用前日值時不算,避免假訊號)
    th = TH["margin"]; n = th["days"]
    if close and len(seq) > n and not t.get("margin_note"):
        base = seq[-n - 1]; m0, m1, c0 = base.get("margin"), t.get("margin"), _close(base)
        if m0 and m1 and c0:
            dm, dc = (m1 - m0) / m0 * 100, (close / c0 - 1) * 100
            key = (("clean_fast" if dm <= -th["strong_pct"] else "clean") if (dc > 0 and dm < 0) else
                   ("overheat" if dm > dc else "chase") if dc > 0 else "trapped" if dm > 0 else "exit")
            add("margin", key, n=n, dc=dc, dm=dm)

    # ⑪⑫ 美元兌台幣 / 美元指數(美元強 = 偏空):單日急變、連 N 日、對均值
    for k in ("usdtwd", "dxy"):
        th = TH[k]; rate = (t.get("fx") or {}).get(k)
        rates = [x for x in (((h.get("fx") or {}).get(k)) for h in seq) if x]
        hs = [x for x in (((h.get("fx") or {}).get(k)) for h in hist[-th["avg_days"]:]) if x]
        if rate and len(hs) >= 5:
            avg = _mean(hs); gap = (rate / avg - 1) * 100
            dd = (rates[-1] / rates[-2] - 1) * 100 if len(rates) >= 2 else 0
            diffs = [rates[i] - rates[i - 1] for i in range(1, len(rates))]
            run_up, run_dn = _run(diffs, 1), _run(diffs, -1)
            key = ("spike_up" if dd >= th["spike_pct"] else "spike_down" if dd <= -th["spike_pct"] else
                   "run_up" if run_up >= th["run_days"] else "run_down" if run_dn >= th["run_days"] else
                   "strong_up" if gap >= th["strong_pct"] else "up" if gap >= th["deadzone_pct"] else
                   "strong_down" if gap <= -th["strong_pct"] else "down" if gap <= -th["deadzone_pct"] else "flat")
            add(k, key, rate=rate, n=len(hs), gap=gap, dd=dd, run=max(run_up, run_dn))

    # ⑬ 基差:偏熱、深逆價差、正逆翻轉、對近 N 日均
    th = TH["basis"]; b = t.get("basis"); bp = p.get("basis")
    bs = [h.get("basis") for h in hist[-th["avg_days"]:] if h.get("basis") is not None]
    if b is not None and len(bs) >= 3:
        avg = _mean(bs)
        key = ("hot" if b >= th["hot"] else "deep_neg" if b <= th["deep_neg"] else
               "flip_neg" if (bp is not None and bp >= 0 > b) else "flip_pos" if (bp is not None and bp < 0 <= b) else
               "widen_pos" if (b > avg and b > 0) else "widen_neg" if (b < avg and b < 0) else "converge")
        add("basis", key, b=b, bp=bp if bp is not None else b, n=len(bs), avg=avg)

    # ── 溫度
    tot = sum(i["score"] * i["w"] for i in items); mx = sum(2 * i["w"] for i in items)
    temp = round((tot / mx + 1) / 2 * 100) if mx else None
    out = {"version": cfg.get("version", 2), "items": items, "raw": round(tot, 2), "max": round(mx, 2),
           "temp": temp, "n_items": len(items), "n_total": len(W)}
    if temp is None: return out
    label = _lvl(cfg["temp_labels"], temp)["label"]
    prev_pg = (hist[-1].get("panghu") or {}) if hist else {}
    prev_temp = prev_pg.get("temp"); prev_d = prev_pg.get("discipline") or {}
    prev_pct = prev_d.get("suggest_pct")

    # ── 倉位:線性對應 → 取整 step% → 緩衝(越過目前級距邊界 buffer 分才換)→ 加碼需外資買超
    P = cfg["position"]; z, f_, stp, buf = P["zero_at"], P["full_at"], P["step"], P["buffer"]
    span = (f_ - z) / (100 / stp)                                     # 每一級佔幾分溫度(預設 6)
    def pct_of(tp): x = max(0.0, min(1.0, (tp - z) / (f_ - z))) * 100; return int(math.floor(x / stp + 0.5) * stp)
    def band(pc): return (-1e9 if pc == 0 else z + (pc / stp - 0.5) * span, 1e9 if pc == 100 else z + (pc / stp + 0.5) * span)
    def pname(pc): return P["names"].get(str(pc), f"{pc}%")
    cand = pct_of(temp); base_pct = cand
    if prev_pct is not None:
        lo, hi = band(prev_pct)
        if lo - buf <= temp < hi + buf: base_pct = prev_pct              # 緩衝內 → 維持昨天級距
    fx_buy = (((t.get("inst") or {}).get("外資")) or 0) > 0
    gated = bool(P.get("gate_foreign") and prev_pct is not None and base_pct > prev_pct and not fx_buy)
    if gated: base_pct = prev_pct

    # ── 防線 / 第二道
    st = cfg["stops"]; cl_all = [c for c in (_close(h) for h in seq) if c]
    line1 = line2 = None
    if len(cl_all) >= 5 and close:
        ma = _mean(cl_all[-TH["trend"]["ma_days"]:])
        line1 = max(ma, min(cl_all[-st["line1_lookback"]:])); line2 = min(cl_all[-st["line2_lookback"]:])
        if line2 >= line1: line2 = line1 * 0.985
        line1, line2 = round(line1), round(line2)
    cut = st["line1_cut_pct"]; suggest_pct = base_pct; act = None
    prev_close = _close(hist[-1]) if hist else None; prev_l1 = prev_d.get("line1")
    first_break = not (prev_close and prev_l1 and prev_close < prev_l1)
    prev_act = prev_d.get("act")
    if line1 and close:
        if close < line2:                                              # 第二道:首日喊空手(🚨),之後幾天只說「仍在第二道下」
            suggest_pct = 0; act = "below_line2" if prev_act in ("out", "below_line2") else "out"
        elif close < line1:                                            # 防線:首日跌破才喊降級,之後幾天是「仍在防線下」
            if first_break and temp >= st["fake_break_temp"]: act = "fake_break"
            else: suggest_pct = max(0, base_pct - cut); act = "down" if first_break else "below_line"
    if act is None:
        act = ("gate" if gated else "up" if (prev_pct is not None and suggest_pct > prev_pct) else
               "weaken" if (prev_pct is not None and suggest_pct < prev_pct) else
               "top" if suggest_pct >= 100 else "bottom" if suggest_pct <= 0 else None)
    streak = (prev_d.get("streak", 0) + 1) if (prev_pct is not None and prev_pct == suggest_pct) else 1
    if act is None: act = "steady" if streak >= 3 else "hold"
    nxt = min(100, suggest_pct + stp); next_temp = math.ceil(band(suggest_pct)[1] + buf) if suggest_pct < 100 else None
    kw = dict(close=close or 0, line1=line1 or 0, line2=line2 or 0, temp=temp, suggest=pname(suggest_pct), base_name=pname(base_pct),
              prev_name=pname(prev_pct) if prev_pct is not None else "—", cand_name=pname(cand), cut_name=pname(max(0, base_pct - cut)),
              next_name=pname(nxt), next_temp=next_temp or 100, reenter=st["reenter_temp"], streak=streak)
    action = _fmt(cfg["actions"].get(act, ""), **kw)
    disc = {"suggest": pname(suggest_pct), "suggest_pct": suggest_pct, "cand_pct": cand, "prev_pct": prev_pct,
            "prev_name": pname(prev_pct) if prev_pct is not None else None,
            "line1": line1, "line2": line2,
            "line1_ok": (close >= line1) if (line1 and close) else None, "line2_ok": (close >= line2) if (line2 and close) else None,
            "next_name": pname(nxt) if suggest_pct < 100 else None, "next_temp": next_temp,
            "next_ok_temp": (temp >= next_temp) if next_temp else None, "next_ok_foreign": fx_buy,
            "act": act, "action": action, "streak": streak}
    delta = ("delta_none" if prev_temp is None else "delta_up" if temp > prev_temp else "delta_down" if temp < prev_temp else "delta_flat")
    dtxt = _fmt(cfg[delta], d=(temp - prev_temp) if prev_temp is not None else 0)
    out.update({"label": label, "suggest": pname(suggest_pct), "suggest_pct": suggest_pct, "prev_temp": prev_temp,
                "delta": dtxt, "discipline": disc})
    out["summary"] = _fmt(cfg["summary"], temp=temp, label=label, delta=dtxt, suggest=pname(suggest_pct))
    if len(items) < cfg.get("min_items_note", 10): out["partial"] = _fmt(cfg["partial_note"], n=len(items))
    return out

# ─────────────── 胖虎指標 v4(描述型) ───────────────
# 只描述盤後現況的四個面向:趨勢、籌碼、情緒、匯率;不合成分數、不預測漲跌、不給倉位。
# 10 年回測顯示用這些資料預測之後 20~60 日漲跌,沒有明顯贏過單看 60 日均線或永遠偏多,所以改成誠實描述。
# 極端事件(超跌、深逆價差、爆量長黑、P/C 極低)只標出,並附上歷史每一次「獨立事件」的後續(backtest 產生的 events.json)。
EVENTS_PATH = os.path.join(DATA, "..", "backtest", "events.json")
_IH = {}
def _month_index(y, m, tries=3):
    """證交所每日市場成交資訊月表 → {日期: (加權收盤, 成交金額億)};同一次執行快取(抓成功才快取)。
    證交所對連續請求會擋:失敗就等一下重試,最多 tries 次;每支之間間隔 1.2 秒。"""
    key = (y, m)
    if _IH.get(key): return _IH[key]
    out = {}
    for a in range(tries):
        try:
            r = requests.get(TWSE + "afterTrading/FMTQIK", params={"date": f"{y}{m:02d}01", "response": "json"}, headers=H, timeout=30)
            j = r.json()
            if j.get("stat") == "OK":
                for row in j.get("data") or []:
                    yy, mm, dd = row[0].strip().split("/")
                    out[f"{int(yy) + 1911}/{mm}/{dd}"] = (num(row[4]), round(num(row[2]) / 1e8))
                if out: break
            else: log(f"  加權月表 {y}/{m:02d}:證交所回 {j.get('stat')}")
        except Exception as e: log(f"  加權月表 {y}/{m:02d} 失敗({e.__class__.__name__}),第 {a + 1} 次")
        time.sleep(3 * (a + 1))
    if out: _IH[key] = out
    time.sleep(1.2)
    return out

def index_history(date, n=130):
    """date(含)之前最近 n 個交易日:(收盤 list, 成交金額 list, 日期 list),由舊到新。
    中間只要有一個月抓不到,就回傳空的(寧可不寫趨勢,也不要跳過缺的月份、算出錯位的均線)。
    當月例外:月初第一個交易日月表可能還沒更新,當月空的允許(describe_live 會補上當天)。"""
    y, m = int(date[:4]), int(date[5:7]); got = {}
    for k in range(12):
        mt = _month_index(y, m)
        if not mt and not (k == 0 and int(date[8:10]) <= 5):
            log(f"  加權月表 {y}/{m:02d} 抓不到,趨勢與超跌判斷今天不寫(避免均線錯位)")
            return [], [], []
        got.update(mt)
        if len([d for d in got if d <= date]) >= n: break
        m -= 1
        if m == 0: y, m = y - 1, 12
    ds = sorted(d for d in got if d <= date)[-n:]
    return [got[d][0] for d in ds], [got[d][1] for d in ds], ds

def fx_history(date, n=40):
    """date(含)之前最近 n 筆匯率日線(Yahoo),由舊到新"""
    out = {}
    for k, sym in FX_SYMS.items():
        mp = _fx_series(sym); ds = sorted(d for d in mp if d <= date)[-n:]
        out[k] = [mp[d] for d in ds]
    return out

_EV = None
def load_events_history():
    global _EV
    if _EV is None:
        try: _EV = json.load(open(EVENTS_PATH, encoding="utf-8")).get("events") or {}
        except Exception: _EV = {}
    return _EV

def _pct(a, b): return (a / b - 1) * 100 if (a is not None and b) else None

def event_history_text(h):
    """極端事件歷史摘要(獨立事件,同一波只算一次)"""
    if not h or not h.get("n"): return "歷史上沒有同類事件紀錄"
    s = f"歷史 {h['n']} 次:之後 20 日 {h['up20']} 漲 {h['down20']} 跌、中位數 {h['median20'] * 100:+.1f}%,20 日內最深再跌 {h['worst_dd20'] * 100:.1f}%"
    b = h.get("in_bear") or {}
    if b.get("n"): s += f";其中發生在空頭排列時 {b['n']} 次:{b['up20']} 漲 {b['down20']} 跌"
    return s

def build_describe(t, p, hist, cfg, closes, amts, fxh, ev_hist=None, dist=None):
    """t 當日、p 前一日、hist 之前的日子(由舊到新,至少 20 天);closes / amts 為 t(含)之前的加權收盤與成交金額(至少 120 天);
    fxh = {usdtwd: [...], dxy: [...]}(t 含之前)。ev_hist = 極端事件歷史(None 表示不附)。"""
    ix = t.get("index") or {}; close, chg, amt = ix.get("close"), ix.get("chg"), ix.get("amount_yi")
    pclose = _close(p) or (close - chg if (close and chg is not None) else None)
    cp = (chg / pclose * 100) if (chg is not None and pclose) else None
    aspects, data, events = [], {}, []
    def asp(k, name, label, tone, lines, short):
        aspects.append({"k": k, "name": name, "label": label, "tone": tone, "lines": [x for x in lines if x], "short": short})

    # ── 趨勢:收盤對 20 / 60 / 120 日均線,與 60 日均線方向
    T = cfg["trend"]; mas = {n: sum(closes[-n:]) / n for n in T["ma"] if len(closes) >= n}
    gap = {n: _pct(close, v) for n, v in mas.items()} if close else {}
    sm, lag = T["slope_ma"], T["slope_lag"]
    slope = _pct(sum(closes[-sm:]) / sm, sum(closes[-sm - lag:-lag]) / sm) if len(closes) >= sm + lag else None
    if close and 20 in mas and 60 in mas:
        m20, m60, m120 = mas[20], mas[60], mas.get(120)
        if m120 and m20 > m60 > m120 and close > m20: key, tone = "bull_stack", "bull"
        elif m120 and m20 < m60 < m120 and close < m20: key, tone = "bear_stack", "bear"
        elif close >= m60: key, tone = "above60", "bull_lean"
        else: key, tone = "below60", "bear_lean"
        label = T["labels"][key]
        ma_txt = "、".join(f"{n} 日均 {v:,.0f}({gap[n]:+.1f}%)" for n, v in sorted(mas.items()))
        sl_txt = None if slope is None else f"{sm} 日均線近 {lag} 日 {slope:+.1f}%,{'上彎' if slope >= T['slope_flat_pct'] else '下彎' if slope <= -T['slope_flat_pct'] else '走平'}"
        asp("trend", "趨勢", label, tone, [f"收盤 {close:,.0f}:{ma_txt}", sl_txt],
            f"{label}(20 日均 {gap[20]:+.1f}%、60 日均 {gap[60]:+.1f}%)")
        data.update({"trend": key, "ma20": round(m20), "ma60": round(m60), "ma120": round(m120) if m120 else None,
                     "gap20": round(gap[20], 2), "gap60": round(gap[60], 2), "gap120": round(gap[120], 2) if 120 in gap else None,
                     "slope60": round(slope, 2) if slope is not None else None})

    # ── 籌碼:外資現貨(今日、連買賣、20 日累計佔成交)、外資期貨多空、融資
    Cc = cfg["chips"]; seq = hist + [t]
    fs = [((d.get("inst") or {}).get("外資")) for d in seq[-Cc["foreign_days"]:]]
    am = [_amt(d) for d in seq[-Cc["foreign_days"]:]]
    fx0 = fs[-1]; lines = []; flabel = None; ftone = "neutral"; f20 = None
    if fx0 is not None:
        s = 1 if fx0 > 0 else -1 if fx0 < 0 else 0; run = 0
        for v in reversed(fs):
            if v is None or v == 0 or (v > 0) != (s > 0): break
            run += 1
        pairs = [(a, b) for a, b in zip(fs, am) if a is not None and b]
        if len(pairs) >= 10:
            f20 = sum(a for a, _ in pairs) / sum(b for _, b in pairs) * 100
            flabel = Cc["labels"]["buy"] if f20 >= Cc["foreign_pct"] else Cc["labels"]["sell"] if f20 <= -Cc["foreign_pct"] else Cc["labels"]["flat"]
            ftone = "buy" if f20 >= Cc["foreign_pct"] else "sell" if f20 <= -Cc["foreign_pct"] else "neutral"
            data["foreign20_pct"] = round(f20, 2)
        runs = "" if (s == 0 or abs(fx0) < Cc["foreign_flat_yi"]) else f"(連{'買' if s > 0 else '賣'} {run} 日)"
        lines.append(f"外資現貨 今日 {fx0:+,.0f} 億{runs}" + (f",近 {len(pairs)} 日累計 {sum(a for a, _ in pairs):+,.0f} 億、佔成交 {f20:+.1f}%" if f20 is not None else ""))
    fu, fp = (t.get("txf") or {}).get("外資"), (p.get("txf") or {}).get("外資")
    combo = None
    ok_oi = lambda x: bool(x) and ((x.get("long") or 0) + (x.get("short") or 0)) > 0     # 未平倉全 0 = 期交所還沒算好,不能拿來算增減
    if ok_oi(fu) and ok_oi(fp):
        dl, ds_ = fu["long"] - fp["long"], fu["short"] - fp["short"]; dz = Cc["fut_deadzone"]
        ml = 0 if abs(dl) < dz else (1 if dl > 0 else -1); ms = 0 if abs(ds_) < dz else (1 if ds_ > 0 else -1)
        ck = ((("add_long" if ml > 0 else "cut_long") + "_" + ("add_short" if ms > 0 else "cut_short")) if (ml and ms) else
              ("add_long" if ml > 0 else "cut_long") if ml else ("add_short" if ms > 0 else "cut_short") if ms else "none")
        combo = Cc["fut_combo"][ck]; base = Cc["baseline_net"]; net = fu["net"]
        lines.append(f"外資台指期 多單 {dl:+,} 口、空單 {ds_:+,} 口({combo});淨{'空' if net < 0 else '多'} {abs(net):,} 口,"
                     f"{'低於' if net > base else '高於'} {abs(base) // 10000} 萬口基態")
    n = Cc["margin_days"]
    if t.get("margin_note"): lines.append("今日融資尚未公布(21:30 那班補)")
    elif close and len(seq) > n:
        b0 = seq[-n - 1]; m0, m1, c0 = b0.get("margin"), t.get("margin"), _close(b0)
        if m0 and m1 and c0: lines.append(f"融資近 {n} 日 {_pct(m1, m0):+.2f}%(同期指數 {_pct(close, c0):+.2f}%),餘額 {m1:,.1f} 億")
    if flabel or combo:
        label = "・".join(x for x in (flabel, f"期貨{combo}" if combo else None) if x)
        asp("chips", "籌碼", label, ftone, lines, label + (f"(20 日累計佔成交 {f20:+.1f}%)" if f20 is not None else ""))

    # ── 情緒:散戶多空比、P/C、VIX
    S = cfg["sentiment"]; lines = []; parts = []; rlab = plab = None
    def rmean(d):
        xs = [x["ratio_pct"] for x in ((d or {}).get("mtx_retail"), (d or {}).get("tmf_retail")) if x and x.get("ratio_pct") is not None]
        return sum(xs) / len(xs) if xs else None
    r, rp = rmean(t), rmean(p)
    if r is not None:
        rb = hist_band("retail", r, dist)                                   # 有歷史分布就跟自己的歷史比(P80 以上偏多、P20 以下偏空)
        if rb is not None: rlab = "散戶偏多" if rb > 0 else "散戶偏空" if rb < 0 else "散戶中性"
        else: rlab = "散戶偏多" if r >= S["retail_mild"] else "散戶偏空" if r <= -S["retail_mild"] else "散戶中性"
        parts.append(rlab)
        det = "、".join(f"{nm} {x['ratio_pct']:+.1f}%" for nm, x in (("小台", t.get("mtx_retail")), ("微台", t.get("tmf_retail"))) if x and x.get("ratio_pct") is not None)
        lines.append(f"散戶多空比 {det}" + (f"(前日平均 {rp:+.1f}% → 今 {r:+.1f}%)" if rp is not None else ""))
    pc = (t.get("pc") or {}).get("oi_ratio_pct"); pp = (p.get("pc") or {}).get("oi_ratio_pct")
    if pc is not None:
        pb = hist_band("pc", pc, dist)
        if pb is not None: plab = "P/C 偏高" if pb > 0 else "P/C 偏低" if pb < 0 else "P/C 中性"
        else: plab = "P/C 偏高" if pc >= S["pc_hi"] else "P/C 偏低" if pc <= S["pc_lo"] else "P/C 中性"
        parts.append(plab)
        lines.append(f"全市場 P/C(OI) {pc:.1f}%" + (f"(前日 {pp:.1f}%)" if pp is not None else ""))
    vx = t.get("vix"); vs = [h.get("vix") for h in hist[-S["vix_days"]:] if h.get("vix")]
    if vx:
        avg = sum(vs) / len(vs) if len(vs) >= 5 else None
        lines.append(f"VIX {vx}" + (f"(近 {len(vs)} 日均 {avg:.1f},{'偏高' if vx >= avg * (1 + S['vix_mild']) else '偏低' if vx <= avg * (1 - S['vix_mild']) else '持平'})" if avg else ""))
    if parts:
        tone = "hot" if (rlab == "散戶偏多" and plab == "P/C 偏低") else "cold" if (rlab == "散戶偏空" and plab == "P/C 偏高") else "neutral"
        label = "・".join(parts); asp("sentiment", "情緒", label, tone, lines, label + (f"・VIX {vx}" if vx else ""))

    # ── 匯率:台幣、美元指數 20 日變化
    X = cfg["fx"]; lines = []; parts = []; tone = "neutral"
    def chg_n(xs): return _pct(xs[-1], xs[-1 - X["days"]]) if len(xs) > X["days"] else (_pct(xs[-1], xs[0]) if len(xs) >= 5 else None)
    tw = [x for x in (fxh.get("usdtwd") or []) if x]; dx = [x for x in (fxh.get("dxy") or []) if x]
    if tw:
        c = chg_n(tw)
        if c is not None:
            lab = "台幣升值" if c <= -X["flat_pct"] else "台幣貶值" if c >= X["flat_pct"] else "台幣持平"; parts.append(lab)
            tone = "inflow" if c <= -X["flat_pct"] else "outflow" if c >= X["flat_pct"] else "neutral"
            lines.append(f"美元兌台幣 {tw[-1]:.3f},近 {X['days']} 日 {c:+.2f}%({lab})"); data["twd20"] = round(c, 2)
    if dx:
        c = chg_n(dx)
        if c is not None:
            lab = "美元偏強" if c >= X["flat_pct"] else "美元偏弱" if c <= -X["flat_pct"] else "美元持平"; parts.append(lab)
            lines.append(f"美元指數 {dx[-1]:.2f},近 {X['days']} 日 {c:+.2f}%({lab})"); data["dxy20"] = round(c, 2)
    if parts:
        label = "・".join(parts); asp("fx", "匯率", label, tone, lines, label)

    if amt and len(amts) > 20:                                        # 成交金額對前 20 日均量(%),給位置百分位用
        _a = sum(amts[-21:-1]) / 20
        if _a: data["vol_ratio"] = round(amt / _a * 100, 1)

    # ── 極端事件(只標出,附歷史獨立事件後續;同一波連續出現標「第 N 天」)
    E = cfg["events"]; fired = []
    if 20 in gap and gap[20] <= E["oversold"]["pct"]: fired.append(("oversold", f"收盤低於 20 日均 {abs(gap[20]):.1f}%"))
    if t.get("basis") is not None and t["basis"] <= E["deep_neg"]["basis"]: fired.append(("deep_neg", f"基差 {t['basis']:+.0f} 點"))
    ad = E["surge_down"]["avg_days"]
    if amt and len(amts) > ad and cp is not None:
        avg = sum(amts[-ad - 1:-1]) / ad
        if avg and amt >= avg * E["surge_down"]["ratio"] and cp <= E["surge_down"]["chg_pct"]:
            fired.append(("surge_down", f"成交 {amt:,} 億(均量的 {amt / avg * 100:.0f}%),指數 {cp:+.2f}%"))
    if pc is not None and pc <= E["pc_low"]["pc"]: fired.append(("pc_low", f"P/C(OI) {pc:.1f}%"))
    for k, txt in fired:
        cnt = sum(1 for h in hist[-E["dedupe_days"]:] if k in [e["k"] for e in ((h.get("panghu") or {}).get("events") or [])])
        ev = {"k": k, "name": E[k]["name"], "text": txt, "day": cnt + 1, "new": cnt == 0}   # day = 近 dedupe_days 日內第幾次出現;new = 新一波
        if ev_hist is not None:
            hh = ev_hist.get(k) or {}
            ev["history"] = {x: hh.get(x) for x in ("n", "up20", "down20", "median20", "worst_dd20", "in_bear")}
            ev["history_text"] = event_history_text(hh)
        events.append(ev)

    summary = "|".join(f"{a['name']} {a['label']}" for a in aspects)
    return {"version": 4, "aspects": aspects, "events": events, "summary": summary, "data": data, "note": cfg.get("note", "")}

def describe_live(t, p, hist, cfg):
    """每天盤後用:加權收盤從證交所月表往回抓 130 天、匯率用 Yahoo 日線;極端事件附 events.json 的歷史"""
    closes, amts, ds = index_history(t["date"], 130)
    ix = t.get("index") or {}
    if closes and ix.get("close") and ds[-1] != t["date"]:           # 月表還沒更新到當天 → 補上當日(月表抓不齊時不補,整段留空)
        closes.append(ix["close"]); amts.append(ix.get("amount_yi") or 0)
    dist = load_dist()
    pg = build_describe(t, p, hist, cfg, closes, amts, fx_history(t["date"]), load_events_history(), dist)
    try: attach_position(pg, t, dist)
    except Exception as e: log(f"  位置百分位計算失敗:{e.__class__.__name__}: {e}")
    return pg

# ─────────────── 胖虎指標 v4:歷史位置百分位 ───────────────
# 只回答「今天這個值在過去歷史中排第幾(0 最低、100 最高)」;不加總、不給多空結論。
# 分布由 backtest.py 重算時產生(chips/backtest/dist.json,每週六更新),只含過去的日子,不偷看未來。
DIST_PATH = os.path.join(DATA, "..", "backtest", "dist.json")
POS_SPEC = [   # (key, 面向, 名稱, 顯示格式)
    ("gap60", "trend", "收盤對 60 日均", "{:+.1f}%"),
    ("vol_ratio", "trend", "成交對 20 日均量", "{:.0f}%"),
    ("foreign20_pct", "chips", "外資現貨 20 日佔成交", "{:+.1f}%"),
    ("fut_net", "chips", "外資台指期淨未平倉", "{:+,.0f} 口"),
    ("retail", "sentiment", "散戶多空比", "{:+.1f}%"),
    ("pc", "sentiment", "P/C(OI)", "{:.1f}%"),
    ("twd20", "fx", "美元兌台幣 20 日", "{:+.2f}%"),
]

def position_values(t, data):
    """位置百分位用的原始值;t 當日、data = build_describe 的 data"""
    f = (t.get("txf") or {}).get("外資") or {}
    ok_oi = ((f.get("long") or 0) + (f.get("short") or 0)) > 0          # 未平倉全 0 = 期交所還沒算好
    rs = [x["ratio_pct"] for x in (t.get("mtx_retail"), t.get("tmf_retail")) if x and x.get("ratio_pct") is not None]
    return {"gap60": data.get("gap60"), "vol_ratio": data.get("vol_ratio"), "foreign20_pct": data.get("foreign20_pct"),
            "fut_net": f.get("net") if ok_oi else None, "retail": round(sum(rs) / len(rs), 2) if rs else None,
            "pc": (t.get("pc") or {}).get("oi_ratio_pct"), "twd20": data.get("twd20")}

def pctile(v, q):
    """q = 101 個分位點(第 0~100 百分位,由小到大)→ v 的百分位;同值一大串時取中間"""
    if v <= q[0]: return 0.0
    if v >= q[-1]: return 100.0
    i, j = bisect.bisect_left(q, v), bisect.bisect_right(q, v)
    if j > i: return (i + j - 1) / 2
    return (i - 1) + (v - q[i - 1]) / (q[i] - q[i - 1])

def hist_band(k, v, dist):
    """跟歷史分布比:≥ P80 → 1、≤ P20 → -1、中間 → 0;沒有分布 → None(呼叫端退回固定門檻)"""
    d = ((dist or {}).get("metrics") or {}).get(k)
    if v is None or not d or len(d.get("q") or []) != 101: return None
    p = pctile(v, d["q"])
    return 1 if p >= 80 else -1 if p <= 20 else 0

def pct_band(p):
    return "極低" if p <= 5 else "偏低" if p <= 20 else "極高" if p >= 95 else "偏高" if p >= 80 else "正常區間"

def load_dist():
    try: return json.load(open(DIST_PATH, encoding="utf-8"))
    except Exception: return None

def attach_position(pg, t, dist):
    if not dist or not pg: return
    vals, M = position_values(t, pg.get("data") or {}), dist.get("metrics") or {}
    out = []
    for k, ak, name, fm in POS_SPEC:
        v, d = vals.get(k), M.get(k)
        if v is None or not d or len(d.get("q") or []) != 101: continue
        p = int(round(pctile(v, d["q"])))
        nf, unit = fm[:fm.index("}") + 1], fm[fm.index("}") + 1:]            # 數字格式 / 單位分開,區間只寫一次單位
        q20, q50, q80 = d["q"][20], d["q"][50], d["q"][80]
        out.append({"k": k, "aspect": ak, "name": name, "value": v, "text": fm.format(v), "p": p, "band": pct_band(p),
                    "years": d.get("years"), "n": d.get("n"), "q20": q20, "q50": q50, "q80": q80,
                    "range_text": f"正常 {nf.format(q20)} ~ {nf.format(q80)}{unit}・中位數 {nf.format(q50)}{unit}"})
    if out:
        pg["position"] = out
        pg["position_note"] = f"位置 = 今天的值在過去歷史中排第幾(0 最低、100 最高),分布資料到 {(dist.get('range') or ['', ''])[1]};只描述多極端,不是買賣訊號。"

# ─────────────── 收尾 / 寫檔(單日與回補共用) ───────────────
def finish_day(t, p):
    """補上依賴前一日的欄位:融資沿用、prev、claude_text、昨日摘要。"""
    if t.get("margin") is None and p.get("margin") is not None:
        t["margin"] = p["margin"]; t["margin_note"] = f"證交所尚未公布，沿用 {p['date']} 值"; log("  融資：" + t["margin_note"])
    t["prev"] = p; t["log"] = LOG
    hist = recent_days(20, ymd(t["date"]))
    try: t["insight"] = build_insight(t, p, hist)
    except Exception as e: log(f"  解讀計算失敗:{e.__class__.__name__}: {e}")
    try: t["panghu"] = describe_live(t, p, hist, load_panghu_cfg())      # v4 描述型(v2 評分版 build_panghu 只留給回測當對照)
    except Exception as e: log(f"  胖虎指標計算失敗:{e.__class__.__name__}: {e}")
    t["generated_at"] = (dt.datetime.utcnow() + dt.timedelta(hours=8)).isoformat(timespec="seconds")
    t["claude_text"] = claude_text(t, p)
    if (t.get("insight") or {}).get("lines"):
        t["claude_text"] += "\n【價量 / 籌碼解讀】\n" + "\n".join("・" + x for x in t["insight"]["lines"])
    pg = t.get("panghu") or {}
    if pg.get("version") == 4 and pg.get("aspects"):
        t["claude_text"] += "\n【胖虎指標・現況描述】" + "".join(f"\n・{a['name']} {a['label']}:" + ";".join(a["lines"]) for a in pg["aspects"])
        if pg.get("position"):
            t["claude_text"] += "\n・歷史位置:" + "、".join(f"{x['name']} {x['text']} 第 {x['p']} 百分位({x['band']})" for x in pg["position"])
        for e in pg.get("events") or []:
            t["claude_text"] += f"\n⚠ 極端事件 {e['name']}({e['text']},近 10 日第 {e['day']} 次):{e.get('history_text', '')}"
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
def backfill(n, start=None, force=False):
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
        old_path = os.path.join(DATA, f"{tag}.json")
        if os.path.exists(old_path):
            if not force: log(f"  {tag} 已存在，略過"); continue
            try:                                                   # --force 重寫時保留當日已抓到的永豐圖清單(回補不抓 PDF)
                old = json.load(open(old_path, encoding="utf-8"))
                if old.get("spf"): t["spf"] = old["spf"]
            except Exception: pass
        finish_day(t, p); write_day(t, idx, latest=False); save_index(idx); written.append(tag)   # 每天寫完就存 index,下一天的解讀才讀得到前面幾天
    save_index(idx)
    print(f"\n回補完成：寫入 {len(written)} 天 {written[:1]}…{written[-1:] if written else ''}；略過 {len(cols) - 1 - len(written)} 天")

# ─────────────── 主流程 ───────────────
def main():
    argv = sys.argv[1:]
    n_back = 0                                    # python fetch_all.py [YYYY/MM/DD] --backfill 20 [--force]
    if "--backfill" in argv:
        k = argv.index("--backfill"); n_back = 20
        if k + 1 < len(argv) and argv[k + 1].isdigit(): n_back = int(argv[k + 1]); del argv[k + 1]   # 數字是 --backfill 的值，不是日期
        del argv[k]
    arg = [a for a in argv if not a.startswith("--")]
    if n_back: return backfill(n_back, arg[0] if arg else None, "--force" in argv)   # --force：連已存在的日子也重寫(補 VIX / 解讀)
    if arg:
        today = arg[0]; df_t = taifex_fut(today)
        if df_t is None or not fut_ready(df_t): sys.exit(f"{today} 期交所尚無資料或三大法人尚未算好")
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
