# -*- coding: utf-8 -*-
"""common.py ─ 籌碼站各支程式共用的小工具(fetch_all / premarket / notify / notify_premarket / render_card)。
- 台北時間 tw_now():取代已不建議使用的 datetime.utcnow()
- 讀寫檔 read_json / write_json / write_text:用 with 開檔;寫入一律「先寫暫存檔再整個換過去」,
  Action 寫到一半被中斷也不會留下半截的 latest.json(籌碼站網頁會打不開)
- shrink_png:圖片存成 256 色(永豐 PDF 頁 / 圖卡;repo 長大速度少約 6 成)
- get_json:證交所被連續請求時會回 HTML / 空白而不是 JSON → 等一下重試(原本只有加權指數有,法人 / 融資 / 月表沒有)
- 期交所 CSV:decode / read_csv_text / col(找不到欄位時錯誤訊息直接列出實際欄位)/ parse_tx(台指期近月日盤 + 夜盤)
pandas 只在 CSV 相關函式裡才 import,notify 這類不需要 pandas 的程式也能用。"""
import os, json, time, tempfile, datetime as dt

TPE = dt.timezone(dt.timedelta(hours=8))

def tw_now():
    """台北現在時間(naive datetime,跟既有程式的比較 / 格式化方式一致)"""
    return dt.datetime.now(TPE).replace(tzinfo=None)

# ─────────────── 讀寫檔 ───────────────
def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError):
        return default

def write_text(path, text):
    """原子寫入:同資料夾先寫暫存檔,寫完 os.replace 一次換過去(同一個檔案系統上是原子操作)"""
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=os.path.basename(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f: f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try: os.remove(tmp)
        except OSError: pass
        raise

def write_json(path, obj, **kw):
    kw.setdefault("ensure_ascii", False)
    write_text(path, json.dumps(obj, **kw))

# ─────────────── 圖片 ───────────────
def shrink_png(src, path=None, colors=256):
    """PNG 轉 256 色調色盤再存(PIL Image 或檔案路徑;path 省略 = 覆蓋原檔)。
    永豐 PDF 頁、圖卡都是文字 + 少數色塊,256 色肉眼看不出差別,檔案小約 6 成(2026-10-09 實測 980→372 KB)。
    這些圖每天 commit 進 repo,省下的就是 repo 長大的速度。不抖色(dither)以免文字邊緣出雜點。"""
    from PIL import Image
    im = Image.open(src) if isinstance(src, str) else src
    path = path or src
    if im.mode not in ("RGB", "P"): im = im.convert("RGB")
    if im.mode == "RGB": im = im.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    im.save(path, optimize=True)
    return path

# ─────────────── 網路 ───────────────
def get_json(get, url, params=None, headers=None, tries=3, wait=4, log=print, label=""):
    """GET 後確認回的是 JSON 物件;不是(證交所被擋時回 HTML / 空白)、連線錯誤或 5xx / 429 → 等 wait×次數 秒重試。
    get = requests.get(傳進來,測試才能換成假網路)。全部失敗回 None,不丟例外。"""
    for a in range(tries):
        why = ""
        try:
            r = get(url, params=params, headers=headers, timeout=30)
            status = getattr(r, "status_code", 200)
            if status == 429 or status >= 500: why = f"HTTP {status}"
            elif r.text.strip().startswith("{"): return r.json()
            else: why = f"非 JSON 回應 {r.text[:60]!r}"
        except Exception as e:
            why = f"{e.__class__.__name__}: {e}"
        log(f"  {label or url}:{why},第 {a + 1}/{tries} 次")
        if a < tries - 1: time.sleep(wait * (a + 1))
    return None

# ─────────────── 期交所 CSV ───────────────
def decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp950", "big5"):
        try: return raw.decode(enc)
        except UnicodeDecodeError: pass
    return raw.decode("utf-8", "ignore")

def read_csv_text(txt, dtype=None):
    """期交所下載的 CSV → DataFrame:欄名去空白、拿掉行尾逗號產生的 Unnamed 欄"""
    import io, pandas as pd
    df = pd.read_csv(io.StringIO(txt), dtype=dtype, index_col=False)
    df.columns = [str(c).strip() for c in df.columns]
    return df.loc[:, ~df.columns.str.startswith("Unnamed")]

def col(df, *keys, start=False):
    """第一個「包含全部 keys」(start=True:以 keys[0] 開頭)的欄名;找不到丟 ValueError 並列出實際欄位,期交所改欄名時一看就懂"""
    for c in df.columns:
        if (c.startswith(keys[0]) if start else all(k in c for k in keys)): return c
    raise ValueError(f"找不到「{'+'.join(keys)}」欄,實際欄位:{list(df.columns)}")

def parse_tx(txt):
    """futDataDown 的台指期 CSV → 近月契約 {contract, day_close, night_close, night_high, night_low, night_open};
    排除價差 / 週選(到期月份不是 6 位數字)。沒有一般時段 → None;夜盤欄位缺就是 None。"""
    import pandas as pd
    df = read_csv_text(txt, dtype=str)
    c_m, c_close = col(df, "到期月份"), col(df, "收盤價", start=True)
    c_sess = next((c for c in df.columns if "交易時段" in c), None)
    df = df[df[c_m].astype(str).str.strip().str.fullmatch(r"\d{6}")]
    if df.empty: return None
    near = sorted(df[c_m].astype(str).str.strip().unique())[0]
    sub = df[df[c_m].astype(str).str.strip() == near]
    def first(rows, name):
        v = pd.to_numeric(rows[col(df, name, start=True)].astype(str).str.replace(",", ""), errors="coerce").dropna()
        return float(v.iloc[0]) if len(v) else None
    if c_sess:
        day = sub[sub[c_sess].astype(str).str.contains("一般")]; night = sub[sub[c_sess].astype(str).str.contains("盤後")]
    else:
        day, night = sub, sub.iloc[0:0]
    if day.empty: return None
    out = {"contract": near, "day_close": first(day, "收盤價"), "night_close": None, "night_high": None, "night_low": None, "night_open": None}
    if not night.empty:
        out.update({"night_close": first(night, "收盤價"), "night_high": first(night, "最高價"),
                    "night_low": first(night, "最低價"), "night_open": first(night, "開盤價")})
    return out

def parse_tx_night(txt, day_date):
    """futDataDown 日期區間的台指期 CSV → day_date 日盤「之後」那一段夜盤。
    ⚠ 期交所把夜盤算在「下一個交易日」:週五 15:00–週六 05:00 那段,交易日期是下週一。
    所以 day_date 那天的「盤後」列其實是前一晚的夜盤(2026-10-04 前程式誤用它,夜盤一直晚一段、漲跌也對錯日盤)。
    做法:取交易日期晚於 day_date 的最後一批「盤後」列當夜盤,近月契約以夜盤為準(結算日換月時日盤用同一契約比);
    回 {contract, day_date, night_date, day_close, night_close, night_high, night_low, night_open};
    day_date 之後還沒有夜盤 → night_* 為 None;day_date 沒有日盤 → None。"""
    import pandas as pd
    df = read_csv_text(txt, dtype=str)
    c_d, c_m, c_s = col(df, "交易日期"), col(df, "到期月份"), col(df, "交易時段")
    df = df.assign(_d=df[c_d].astype(str).str.strip(), _m=df[c_m].astype(str).str.strip(), _s=df[c_s].astype(str))
    df = df[df["_m"].str.fullmatch(r"\d{6}")]                          # 排除價差 / 週選
    day, night = df[(df["_d"] == day_date) & df["_s"].str.contains("一般")], df[(df["_d"] > day_date) & df["_s"].str.contains("盤後")]
    if day.empty: return None
    def num(rows, name):
        v = pd.to_numeric(rows[col(df, name, start=True)].astype(str).str.replace(",", ""), errors="coerce").dropna()
        return float(v.iloc[0]) if len(v) else None
    out = {"contract": sorted(day["_m"].unique())[0], "day_date": day_date, "night_date": None, "day_close": None,
           "night_close": None, "night_high": None, "night_low": None, "night_open": None}
    if not night.empty:
        nd = sorted(night["_d"].unique())[-1]; night = night[night["_d"] == nd]
        out["contract"] = sorted(night["_m"].unique())[0]; out["night_date"] = nd
        n = night[night["_m"] == out["contract"]]
        out.update({"night_close": num(n, "收盤價"), "night_high": num(n, "最高價"), "night_low": num(n, "最低價"), "night_open": num(n, "開盤價")})
    d = day[day["_m"] == out["contract"]]
    out["day_close"] = num(d if not d.empty else day[day["_m"] == sorted(day["_m"].unique())[0]], "收盤價")
    return out

