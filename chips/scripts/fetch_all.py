# -*- coding: utf-8 -*-
"""
fetch_all.py ─ 台股盤後籌碼一鍵抓取（期交所＋證交所＋永豐PDF）
產出：
  data/YYYYMMDD.json        當日完整數據（含前一交易日對照）
  data/latest.json          同上（最新一份）
  data/index.json           歷史日期清單
  data/series.json          近 20 日精簡資料(20 日走勢圖用,省得頁面抓 20 個完整日檔)
  data/YYYYMMDD_claude.txt  貼給 Claude 的純文字數據表
  data/YYYYMMDD_spf_*.png   永豐 籌碼快訊／盤後快訊 轉圖
用法：python scripts/fetch_all.py [YYYY/MM/DD]
"""
import sys, os, io, re, json, time, math, bisect, datetime as dt
import requests, pandas as pd
from urllib.parse import urljoin
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from panghu import *                                             # 胖虎指標純計算:v2 對照 / v4 描述 / 位置百分位 / 一句話總結(backtest 走 fa.xxx 也照樣拿得到)
from panghu import _close, _amt, _pct, _mean, _lvl, _fmt, _run   # import * 不帶底線名稱,補上

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
def twse_index(date, tries=3):
    # 證交所短時間連打(今日 + 前一交易日各一次)會回空白 / HTML → 先看是不是 JSON,不是就等 4 秒重試,最多 tries 次
    for a in range(tries):
        r = requests.get(TWSE + "afterTrading/FMTQIK", params={"date": ymd(date), "response": "json"}, headers=H, timeout=30)
        if r.text.strip().startswith("{"): break
        log(f"  加權指數 {date}:非 JSON 回應 {r.text[:60]!r},第 {a + 1} 次")
        if a < tries - 1: time.sleep(4)
    else: return None
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

def fill_index_from_saved(t):
    """加權指數抓不到時,退回讀已存檔的 data/{tag}.json(前一交易日通常前一天就存好了;16:40 重跑時當日也有 15:40 的檔),
    免得前收是空的、漲跌 % 變問號。檔裡也沒有就維持 None。"""
    if t.get("index"): return
    try: old = json.load(open(os.path.join(DATA, f"{ymd(t['date'])}.json"), encoding="utf-8")).get("index")
    except Exception: return
    if old and old.get("close"):
        t["index"] = old
        if "index" in t.get("missing", []): t["missing"].remove("index")
        if (t.get("tx") or {}).get("close"): t["basis"] = round(t["tx"]["close"] - old["close"], 2)   # collect 當時沒指數算不出基差,補算
        log(f"  {t['date']} 加權指數改用已存檔的值(收盤 {old['close']:,})")

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

# ─────────────── 胖虎指標 v4:盤後要抓的歷史(加權月表、匯率日線、外資期貨 60 日) ───────────────
# 指標本身的計算(build_describe / 位置百分位 / 一句話總結)在 panghu.py,這裡只負責把資料抓齊再呼叫。
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

def recent_fut_nets(date, n):
    """date 之前最近 n 個交易日的外資台指期淨未平倉 {日期: 口}:回測原始資料(每週六更新)+ 每日存檔(較新,蓋過)"""
    got = {}
    y, m = int(date[:4]), int(date[5:7])
    for _ in range(4):                                             # 往回 4 個月的回測原始資料
        try:
            for d, x in json.load(open(os.path.join(DATA, "..", "backtest", "raw", f"{y}{m:02d}.json"), encoding="utf-8")).items():
                fu = (x.get("txf") or {}).get("外資") or {}
                if d < date and (fu.get("long") or 0) + (fu.get("short") or 0) > 0: got[d] = fu["net"]
        except Exception: pass
        m -= 1
        if m == 0: y, m = y - 1, 12
    for x in recent_days(n, ymd(date)):
        fu = (x.get("txf") or {}).get("外資") or {}
        if (fu.get("long") or 0) + (fu.get("short") or 0) > 0: got[x["date"]] = fu["net"]
    return dict(sorted(got.items())[-n:])

def describe_live(t, p, hist, cfg):
    """每天盤後用:加權收盤從證交所月表往回抓 130 天、匯率用 Yahoo 日線;極端事件附 events.json 的歷史"""
    closes, amts, ds = index_history(t["date"], 130)
    ix = t.get("index") or {}
    if closes and ix.get("close") and ds[-1] != t["date"]:           # 月表還沒更新到當天 → 補上當日(月表抓不齊時不補,整段留空)
        closes.append(ix["close"]); amts.append(ix.get("amount_yi") or 0)
    dist = load_dist()
    pg = build_describe(t, p, hist, cfg, closes, amts, fx_history(t["date"]), load_events_history(), dist)
    try:
        h60 = sorted(recent_fut_nets(t["date"], 60).values())
        ca = next((a for a in pg.get("aspects") or [] if a["k"] == "chips"), None)
        if ca and len(h60) >= 40 and (pg.get("data") or {}).get("fut_net") is not None:
            m = h60[len(h60) // 2]; pg["data"]["fut_net_med60"] = m
            ca["lines"].append(f"水位對照:近 {len(h60)} 日淨部位中位數 淨{'空' if m < 0 else '多'} {abs(m):,} 口(外資 3 年來多單大砍、空單大增,只看水位會失真)")
    except Exception as e: log(f"  外資期貨 60 日對照失敗:{e.__class__.__name__}: {e}")
    try: attach_position(pg, t, dist)
    except Exception as e: log(f"  位置百分位計算失敗:{e.__class__.__name__}: {e}")
    return pg

# ─────────────── 收尾 / 寫檔(單日與回補共用) ───────────────
def finish_day(t, p):
    """補上依賴前一日的欄位:融資沿用、prev、claude_text、昨日摘要。"""
    if t.get("margin") is None and p.get("margin") is not None:
        t["margin"] = p["margin"]; t["margin_note"] = f"證交所尚未公布，沿用 {p['date']} 值"; log("  融資：" + t["margin_note"])
    # 前一日只留 collect() 抓到的原始欄位:回補時 p 是已經寫過的前一天,若整份塞進去會連它的 prev 一起帶著,一天疊一天(曾疊到 18 層、檔案 400 KB)
    t["prev"] = {k: v for k, v in p.items() if k not in ("prev", "log", "claude_text", "insight", "panghu", "prev_summary", "generated_at")}
    t["log"] = LOG
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
        t["claude_text"] += "\n【胖虎指標・現況描述】" + (("\n" + pg["headline"]) if pg.get("headline") else "") + "".join(f"\n・{a['name']} {a['label']}:" + ";".join(a["lines"]) for a in pg["aspects"])
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
    write_series(idx)

SERIES_N = 20
def slim_day(t):
    """20 日走勢圖用的精簡欄位(頁面 SPARKS / renderCharts 讀哪些就留哪些;新增圖表要一起加)"""
    def g(*k):
        o = t
        for x in k: o = o.get(x) if isinstance(o, dict) else None
        return o
    return {"tag": ymd(t["date"]), "date": t["date"],
            "index": {k: (t.get("index") or {}).get(k) for k in ("close", "chg", "amount_yi")},
            "inst": t.get("inst"), "margin": t.get("margin"), "vix": t.get("vix"), "basis": t.get("basis"),
            "mtx_retail": {"ratio_pct": g("mtx_retail", "ratio_pct")}, "tmf_retail": {"ratio_pct": g("tmf_retail", "ratio_pct")},
            "pc": {"oi_ratio_pct": g("pc", "oi_ratio_pct")}, "txf": {"外資": {"net": g("txf", "外資", "net")}},
            "panghu": {"data": {"gap60": g("panghu", "data", "gap60"), "ma60": g("panghu", "data", "ma60")}}}

def write_series(idx):
    """data/series.json:近 SERIES_N 個交易日的精簡資料(由舊到新),籌碼站開頁只抓這一支,不用抓 20 個完整日檔"""
    out = []
    for tag in sorted(idx)[-SERIES_N:]:
        try: out.append(slim_day(json.load(open(os.path.join(DATA, f"{tag}.json"), encoding="utf-8"))))
        except Exception: continue
    json.dump(out, open(os.path.join(DATA, "series.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))

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
        fill_index_from_saved(t); fill_index_from_saved(p)
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
    fill_index_from_saved(t); fill_index_from_saved(p)
    t["spf"] = spf_fetch(today)
    cleanup_pngs(ymd(today), {fn for v in t["spf"].values() for fn in v})
    finish_day(t, p)
    idx = load_index(); write_day(t, idx, latest=True); save_index(idx)
    print("\n" + t["claude_text"])

if __name__ == "__main__":
    main()
