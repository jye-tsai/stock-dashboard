# -*- coding: utf-8 -*-
"""backtest.py ─ 胖虎指標回測(驗證 chips/panghu.json 的情境、分數、權重)。

  python chips/scripts/backtest.py fetch [--years 2] [--minutes 100] [--days N]
      抓歷史逐日原始資料(沿用 fetch_all.collect,跟每天盤後抓的是同一份欄位)。
      可中斷續跑:已抓好的日子不重抓;時間用完就存檔結束,再跑一次會接著抓。
  python chips/scripts/backtest.py eval
      依目前的 chips/panghu.json 重算每一天的胖虎指標,算前瞻報酬、策略模擬、情境統計,輸出 result.json。
      改了 panghu.json 只要重跑 eval(不用重抓)。

資料:chips/backtest/raw/YYYYMM.json(一個月一檔,{日期: 當日原始資料})
結果:chips/backtest/result.json;報告頁 chips/backtest/index.html 讀它。

注意:
  - 台指 VIX 官方只留近 3 個月,回測期間大多沒有 → 該項自動不計分(溫度用有資料的項目標準化)。
  - 期交所的期貨 / 選擇權三大法人只開放近 3 年;更早的日子走「精簡抓取」(lite):照抓指數、外資現貨、融資、P/C、台指期收盤、匯率,
    外資期貨多空與散戶多空比留空不計分。評估時「近 3 年完整版」與「更早精簡版」分兩段看,口徑不同不混在一起。
  - 「15:40 版」模擬盤後實際發 LINE 的時點:當日融資還沒公布,融資那項不計分;「含融資版」是 21:30 補齊後的結果。
  - 決策在當日盤後,最快隔日收盤才能執行 → 策略從「決策日 +1 的收盤」開始持有,不偷看當天收盤。
  - 加權指數是價格指數,不含股息;成本以換倉幅度 × COST_PER_TURN 計。
  - 這是機械式指標回測,用來抓明顯錯誤的情境與分數,不是保證未來績效。
"""
import os, sys, json, time, math, argparse, datetime as dt, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
BT = os.environ.get("BT_DIR") or os.path.join(ROOT, "backtest")
RAW = os.path.join(BT, "raw")
PACE = 0.6                  # 每天之間的間隔秒數(證交所對頻繁請求會擋)
COST_PER_TURN = 0.0015      # 換倉成本:每 100% 部位變動約 0.15%(ETF 證交稅 0.1% + 手續費折扣後雙邊)

spec = importlib.util.spec_from_file_location("fa", os.path.join(HERE, "fetch_all.py"))
fa = importlib.util.module_from_spec(spec)
_argv = sys.argv; sys.argv = ["fetch_all"]; spec.loader.exec_module(fa); sys.argv = _argv

_spec3 = importlib.util.spec_from_file_location("panghu_v3", os.path.join(HERE, "panghu_v3.py"))
v3 = importlib.util.module_from_spec(_spec3); _spec3.loader.exec_module(v3)
V3_CFG_PATH = os.path.join(ROOT, "panghu_v3.json")
V2_CFG_PATH = os.path.join(ROOT, "panghu_v2.json")          # 封存的 v2 評分版設定(對照組);正式版 panghu.json 已是 v4 描述型
DEDUPE = 10                                                  # 獨立事件:同一種情境 / 事件相隔 10 個交易日以內算同一波

def load_v2_cfg():
    c = jload(V2_CFG_PATH)
    if c: return c
    c = fa.load_panghu_cfg()
    return c if c.get("version", 2) == 2 else None

def tpe_now(): return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=8)).replace(tzinfo=None)   # 台北時間(不帶時區字尾,免得誤讀成 UTC)
def jload(p, d=None):
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return d
def jsave(p, o):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"; json.dump(o, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":")); os.replace(tmp, p)

# ─────────────── 證交所月表:交易日清單 + 加權收盤 / 漲跌 / 成交金額(一個月一支請求) ───────────────
_MT = {}
def month_table(y, m):
    key = (y, m)
    if key in _MT: return _MT[key]
    out = {}
    for attempt in range(3):
        try:
            r = fa.requests.get(fa.TWSE + "afterTrading/FMTQIK", params={"date": f"{y}{m:02d}01", "response": "json"}, headers=fa.H, timeout=30)
            j = r.json()
            if j.get("stat") == "OK":
                for row in j.get("data") or []:
                    yy, mm, dd = row[0].strip().split("/")
                    out[f"{int(yy) + 1911}/{mm}/{dd}"] = {"close": fa.num(row[4]), "chg": fa.num(row[5]), "amount_yi": round(fa.num(row[2]) / 1e8)}
                break
        except Exception as e: print(f"  月表 {y}/{m:02d} 失敗({e.__class__.__name__}),重試")
        time.sleep(5 * (attempt + 1))
    time.sleep(PACE); _MT[key] = out
    return out

def cached_index(date):                             # 取代 fetch_all.twse_index:同一個月不重複打
    y, m, _ = date.split("/")
    return month_table(int(y), int(m)).get(date)

def safe(fn, *a):
    try: return fn(*a)
    except Exception as e: print(f"  {fn.__name__} 失敗:{e.__class__.__name__}"); return None

# ─────────────── 精簡抓取(3 年以前) ───────────────
FULL_YEARS = 3              # 期交所三大法人開放的年數;早於「今天 - 3 年 + 15 天」的日子才允許走精簡版(近期的失敗照常重試,不降級)
TWSE_GAP = 0.8              # 連打兩支證交所之間的間隔,避免被擋
def collect_lite(d):
    out = {"date": d, "lite": True, "txf": {}, "mtx": {}, "tmf": {}, "mtx_retail": None, "tmf_retail": None, "opt": None, "vix": None}
    out["index"] = cached_index(d)
    out["inst"] = safe(fa.twse_inst, d); time.sleep(TWSE_GAP)
    out["margin"] = safe(fa.twse_margin, d)
    out["pc"] = safe(fa.taifex_pc, d)
    out["tx"] = safe(fa.taifex_tx_close, d)
    if out["tx"] and out.get("index") and out["tx"].get("close"): out["basis"] = round(out["tx"]["close"] - out["index"]["close"], 2)
    out["fx"] = fa.fx_for(d)
    out["missing"] = [k for k in ("index", "inst", "margin", "pc", "tx") if out.get(k) is None] + ["期貨三大法人(官方只開放近 3 年)"]
    return out

# ─────────────── fetch ───────────────
def cmd_fetch(years, minutes, limit_days):
    fa.twse_index = cached_index
    fa.FX_RANGE = f"{max(1, math.ceil(years + 0.5))}y" if years <= 4 else "10y"
    t_end = time.time() + minutes * 60
    now = tpe_now(); start = (now - dt.timedelta(days=int(years * 365.25))).strftime("%Y/%m/%d")
    months = []; y, m = int(start[:4]), int(start[5:7])
    while (y, m) <= (now.year, now.month):
        months.append((y, m)); m += 1
        if m > 12: y, m = y + 1, 1
    todo = []
    for (y, m) in months:
        for d in sorted(month_table(y, m)):
            if d >= start: todo.append(d)
    if limit_days: todo = todo[-limit_days:]
    print(f"回測期間 {todo[0] if todo else '—'} ~ {todo[-1] if todo else '—'},共 {len(todo)} 個交易日")
    lite_before = (now - dt.timedelta(days=int(FULL_YEARS * 365.25) - 15)).strftime("%Y/%m/%d")
    print(f"{lite_before} 以前走精簡抓取(期貨三大法人官方只開放近 {FULL_YEARS} 年)")
    stores = {}; done = skip = fail = 0; stopped = False
    for d in todo:
        ym = d[:4] + d[5:7]; path = os.path.join(RAW, ym + ".json")
        if ym not in stores: stores[ym] = jload(path, {}) or {}
        st = stores[ym]
        if (st.get(d) or {}).get("_ok"): skip += 1; continue
        if time.time() > t_end: stopped = True; break
        df = None if d < lite_before else safe(fa.taifex_fut, d)        # 太舊的日子不用試,期交所一定回 DateTime error
        if df is not None and not fa.fut_ready(df): df = None                 # 當天三大法人還沒算好(未平倉全 0)→ 當作沒有,下次重試
        if df is None:
            if d >= lite_before: fail += 1; print(f"  {d} 期交所無資料,略過(近期日子不降級,下次重試)"); time.sleep(PACE); continue
            c = collect_lite(d)
        else:
            c = fa.collect(d, df)
        if c.get("inst") is None: time.sleep(8); c["inst"] = safe(fa.twse_inst, d)          # 證交所偶爾擋 → 等一下重抓一次
        if c.get("margin") is None: time.sleep(8); c["margin"] = safe(fa.twse_margin, d)
        c["_ok"] = bool(c.get("index") and c.get("inst") and (c.get("lite") or (c.get("txf") or {}).get("外資")))
        st[d] = c; jsave(path, st); fa.LOG.clear()
        if c["_ok"]: done += 1
        else: fail += 1
        if (done + fail) % 20 == 0: print(f"  進度:新抓 {done}、失敗 {fail}、已有 {skip}(最後 {d})")
        time.sleep(PACE)
    total_ok = sum(1 for s in stores.values() for v in s.values() if v.get("_ok"))
    for f in sorted(os.listdir(RAW)) if os.path.isdir(RAW) else []:
        ym = f[:6]
        if ym not in stores: total_ok += sum(1 for v in (jload(os.path.join(RAW, f), {}) or {}).values() if v.get("_ok"))
    status = {"updated": now.isoformat(timespec="seconds"), "range": [todo[0], todo[-1]] if todo else None,
              "trading_days": len(todo), "ok": total_ok, "new": done, "fail": fail, "lite_before": lite_before,
              "complete": (not stopped) and total_ok >= len(todo) - fail}
    jsave(os.path.join(BT, "fetch_status.json"), status)
    print(f"\n抓取結束:新抓 {done}、失敗 {fail}、原本已有 {skip};累計可用 {total_ok}/{len(todo)}" + ("(時間用完,再跑一次會接著抓)" if stopped else ""))

# ─────────────── eval 工具 ───────────────
def rank(xs):
    o = sorted(range(len(xs)), key=lambda i: xs[i]); r = [0.0] * len(xs); i = 0
    while i < len(o):
        j = i
        while j + 1 < len(o) and xs[o[j + 1]] == xs[o[i]]: j += 1
        for k in range(i, j + 1): r[o[k]] = (i + j) / 2
        i = j + 1
    return r
def corr(a, b):
    n = len(a)
    if n < 5: return None
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a); vb = sum((y - mb) ** 2 for y in b)
    if va == 0 or vb == 0: return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)
def spearman(a, b): return corr(rank(a), rank(b)) if len(a) >= 5 else None
def mean(xs): return sum(xs) / len(xs) if xs else None
def r4(x): return None if x is None else round(x, 4)

def metrics(rets, expo, idx_rets):
    eq = 1.0; peak = 1.0; mdd = 0.0; curve = []
    for r in rets:
        eq *= (1 + r); peak = max(peak, eq); mdd = min(mdd, eq / peak - 1); curve.append(eq)
    n = len(rets)
    mu = mean(rets) or 0; sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / n) if n else 0
    changes = sum(1 for i in range(1, len(expo)) if abs(expo[i] - expo[i - 1]) > 1e-9)
    cagr = (eq ** (250 / n) - 1) if n else None
    up = [(s, x) for s, x in zip(rets, idx_rets) if x > 0]; dn = [(s, x) for s, x in zip(rets, idx_rets) if x < 0]
    upc = sum(s for s, _ in up) / sum(x for _, x in up) if up else None          # 上漲參與度:大盤漲的日子吃到幾成
    dnc = sum(s for s, _ in dn) / sum(x for _, x in dn) if dn else None          # 下跌承受度:大盤跌的日子挨了幾成
    return {"total": r4(eq - 1), "cagr": r4(cagr), "mdd": r4(mdd), "calmar": round(cagr / abs(mdd), 2) if (cagr is not None and mdd < 0) else None,
            "vol": r4(sd * math.sqrt(250)), "sharpe": round(mu / sd * math.sqrt(250), 2) if sd else None,
            "up_cap": r4(upc), "down_cap": r4(dnc), "changes": changes, "avg_expo": r4(mean(expo)), "days": n}, curve

def simulate(close, pos, lag=1, cost=COST_PER_TURN):
    """pos[i] = 第 i 天盤後決策(0~1);lag=1 → 第 i+1 天收盤才換到該部位,持有第 i+2 天的漲跌。
    回傳 (策略每日報酬, 每日實際部位, 指數每日報酬),長度皆 N-1,第 j 筆對應日期 j+1。"""
    n = len(close); rets, expo, idx = [], [], []
    prev_e = 0.0
    for j in range(1, n):
        k = j - 1 - lag
        e = pos[k] if k >= 0 else 0.0
        ret = close[j] / close[j - 1] - 1
        rets.append(e * ret - abs(e - prev_e) * cost); expo.append(e); idx.append(ret); prev_e = e
    return rets, expo, idx

def run_seq(days, cfg, mode):
    """依 cfg 由舊到新逐日重算胖虎指標(hist 只含之前的日子);mode=live 模擬 15:40 融資未公布"""
    seq = []
    for t0 in days:
        t = json.loads(json.dumps(t0))
        if mode == "live": t["margin_note"] = "回測模擬 15:40:當日融資未公布"
        t["panghu"] = fa.build_panghu(t, seq[-1] if seq else {}, seq[-20:], cfg)
        seq.append(t)
    return seq

def run_seq_v3(days, cfg3, base_cfg):
    """v3 實驗組:hist 給之前 150 天(120 日均線 + 斜率回看);一律模擬 15:40(當日融資未公布)"""
    seq = []
    for t0 in days:
        t = json.loads(json.dumps(t0)); t["margin_note"] = "回測模擬 15:40:當日融資未公布"
        t["panghu3"] = v3.build(t, seq[-1] if seq else {}, seq[-150:], cfg3, base_cfg, fa)
        t["panghu"] = {"temp": t["panghu3"]["temp_raw"], "items": t["panghu3"]["items"]}      # 給 build_panghu 的前一日參考用
        seq.append(t)
    return seq

def call_of(pct):                 # 倉位 → 方向判讀:≥70 偏多、≤30 偏空、其餘中性(v2 / v3 同一把尺)
    if pct is None: return None
    return "偏多" if pct >= 70 else "偏空" if pct <= 30 else "中性"

def truth_of(r, th):              # 事後真相:之後報酬 > th 漲、< -th 跌、其餘平
    if r is None: return None
    return "up" if r > th else "down" if r < -th else "flat"

def judge(calls, truth):
    """calls: 偏多/中性/偏空;truth: up/flat/down。回傳命中率、覆蓋率、提升倍數、平衡準確率"""
    pairs = [(c, t) for c, t in zip(calls, truth) if c and t]
    n = len(pairs)
    if not n: return None
    base = {k: sum(1 for _, t in pairs if t == k) / n for k in ("up", "flat", "down")}
    def prec(c, t):
        xs = [tt for cc, tt in pairs if cc == c]; return (sum(1 for x in xs if x == t) / len(xs)) if xs else None
    mp = {"偏多": "up", "中性": "flat", "偏空": "down"}
    rec = []
    for t in ("up", "flat", "down"):
        xs = [cc for cc, tt in pairs if tt == t]
        if xs: rec.append(sum(1 for c in xs if mp[c] == t) / len(xs))
    pu, pd = prec("偏多", "up"), prec("偏空", "down")
    return {"n": n, "base_up": r4(base["up"]), "base_down": r4(base["down"]),
            "cov_bull": r4(sum(1 for c, _ in pairs if c == "偏多") / n), "cov_bear": r4(sum(1 for c, _ in pairs if c == "偏空") / n),
            "prec_bull": r4(pu), "prec_bear": r4(pd),
            "lift_bull": r4(pu / base["up"]) if (pu is not None and base["up"]) else None,
            "lift_bear": r4(pd / base["down"]) if (pd is not None and base["down"]) else None,
            "balanced": r4(mean(rec))}

def pos_of(seq): return [((s.get("panghu") or {}).get("suggest_pct") or 0) / 100 for s in seq]

def find_episodes(close, dd_min=0.08, bear=0.15):
    """回檔事件:從前高跌超過 dd_min 算一次,直到收盤站回前高為止。深度 ≥ bear 算「真下跌」,其餘算「洗盤」。
    回傳 [(peak_i, trough_i, recover_i 或 None)]"""
    eps = []; peak = 0; trough = None; on = False
    for i in range(1, len(close)):
        if not on:
            if close[i] >= close[peak]: peak = i
            elif close[i] / close[peak] - 1 <= -dd_min: on = True; trough = i
        else:
            if close[i] < close[trough]: trough = i
            if close[i] >= close[peak]: eps.append((peak, trough, i)); on = False; peak = i
    if on: eps.append((peak, trough, None))
    return [(p, t, e, "真下跌" if close[t] / close[p] - 1 <= -bear else "洗盤") for p, t, e in eps]

def grade_episode(ep, close, eq, expo_full, N, re_lvl=0.7, cut_ratio=0.5, rally_days=60):
    p, t, e, kind = ep
    idx_dd = close[t] / close[p] - 1; s_dd = eq[t] / eq[p] - 1
    e0 = expo_full[p]
    cut = next((i for i in range(p + 1, t + 1) if e0 > 0 and expo_full[i] <= e0 * cut_ratio), None)
    re = next((i for i in range(t, N) if expo_full[i] >= re_lvl), None)
    w = min(t + rally_days, N - 1); ridx = close[w] / close[t] - 1; rs = eq[w] / eq[t] - 1
    return {"expo_peak": r4(e0), "expo_trough": r4(expo_full[t]), "strat_dd": r4(s_dd),
            "avoided": r4(1 - s_dd / idx_dd) if idx_dd < 0 else None,
            "cut_days": (cut - p) if cut is not None else None, "cut_at_dd": r4(close[cut] / close[p] - 1) if cut is not None else None,
            "re_days": (re - t) if re is not None else None, "re_missed": r4(close[re] / close[t] - 1) if re is not None else None,
            "rally_days": w - t, "rally_idx": r4(ridx), "rally_cap": r4(rs / ridx) if ridx > 0 else None}

def goals_of(ep_rows, key):
    """三個目標:真下跌少跌幾成、洗盤谷底還留幾成與幾天回到七成、大底後 60 天吃到幾成"""
    bear = [r[key] for r in ep_rows if r["kind"] == "真下跌"]; wash = [r[key] for r in ep_rows if r["kind"] == "洗盤"]
    return {"bear_n": len(bear), "bear_avoided": r4(mean([g["avoided"] for g in bear if g["avoided"] is not None])),
            "bear_cut_at": r4(mean([g["cut_at_dd"] for g in bear if g["cut_at_dd"] is not None])),
            "wash_n": len(wash), "wash_expo_trough": r4(mean([g["expo_trough"] for g in wash])),
            "wash_re_days": r4(mean([g["re_days"] for g in wash if g["re_days"] is not None])),
            "wash_never_back": sum(1 for g in wash if g["re_days"] is None),
            "rally_cap": r4(mean([g["rally_cap"] for g in bear if g["rally_cap"] is not None]))}

# 多組設定並排:把不屬於該組的權重歸零(溫度只用剩下的項目標準化)
GROUPS = {
    "all":   {"name": "全部 13 項", "keep": None},
    "chips": {"name": "只看籌碼", "keep": ["foreign_spot", "fut_long", "fut_short", "retail", "pc", "margin"]},
    "price": {"name": "只看價格趨勢", "keep": ["trend", "volume", "pv"]},
}
# 參數敏感度:主要門檻與權重各 ×0.8 / ×1.2
SENS = [
    (("thresholds", "trend", "strong_pct"), "趨勢強勢乖離 %"), (("thresholds", "trend", "weak_pct"), "趨勢站穩乖離 %"),
    (("thresholds", "volume", "hi"), "放量倍數"), (("thresholds", "foreign_spot", "big_yi"), "外資大買金額(億)"),
    (("thresholds", "fut", "deadzone"), "期貨增減門檻(口)"), (("thresholds", "retail", "mild"), "散戶偏多空門檻 %"),
    (("thresholds", "pc", "lo"), "P/C 偏空線"), (("position", "buffer"), "換級緩衝(分)"),
    (("stops", "line1_cut_pct"), "跌破防線降幅 %"), (("stops", "line1_lookback"), "防線回看天數"),
    (("weights", "trend"), "趨勢權重"), (("weights", "foreign_spot"), "外資現貨權重"),
]
def cfg_with(cfg, path, factor):
    c = json.loads(json.dumps(cfg)); o = c
    for k in path[:-1]: o = o[k]
    v = o[path[-1]]; nv = v * factor
    if path[-1].endswith(("lookback", "_days", "days")): nv = max(1, int(round(nv)))   # 只有「天數」類取整;權重、門檻保留小數(權重 2 × 0.8 = 1.6,取整會變回 2 等於沒測)
    o[path[-1]] = nv
    return c, v, nv

def run_describe(days, cfg4):
    """v4 描述型逐日重算(模擬 15:40,融資未公布);收盤 / 成交金額 / 匯率用回測資料本身"""
    cl = [d["index"]["close"] for d in days]; am = [d["index"]["amount_yi"] for d in days]
    fxs = {k: [(d.get("fx") or {}).get(k) for d in days] for k in fa.FX_SYMS}
    seq = []
    for i, t0 in enumerate(days):
        t = json.loads(json.dumps(t0)); t["margin_note"] = "回測模擬 15:40:當日融資未公布"
        fxh = {k: [x for x in v[max(0, i - 40):i + 1] if x] for k, v in fxs.items()}
        t["panghu"] = fa.build_describe(t, seq[-1] if seq else {}, seq[-20:], cfg4, cl[max(0, i - 129):i + 1], am[max(0, i - 129):i + 1], fxh, None)
        seq.append(t)
    return seq

def events_summary(dseq, close, dates, cfg4):
    N = len(close)
    def fw(i, k): return (close[i + k] / close[i] - 1) if i + k < N else None
    trend = [((s.get("panghu") or {}).get("data") or {}).get("trend") for s in dseq]
    evs = {}
    for key, spec in cfg4["events"].items():
        if not isinstance(spec, dict): continue
        hit = [i for i, s in enumerate(dseq) if any(e["k"] == key for e in (s.get("panghu") or {}).get("events", []))]
        first = [i for j, i in enumerate(hit) if j == 0 or i - hit[j - 1] > DEDUPE]
        lst = []
        for i in first:
            txt = next((e["text"] for e in dseq[i]["panghu"]["events"] if e["k"] == key), "")
            lst.append({"date": dates[i], "close": close[i], "text": txt, "trend": cfg4["trend"]["labels"].get(trend[i], trend[i]),
                        "fwd5": r4(fw(i, 5)), "fwd20": r4(fw(i, 20)), "fwd60": r4(fw(i, 60)),
                        "dd20": r4(min(close[i:min(N, i + 21)]) / close[i] - 1)})
        done = [x for x in lst if x["fwd20"] is not None]; f20 = sorted(x["fwd20"] for x in done)
        bear = [x for x in done if x["trend"] == cfg4["trend"]["labels"]["bear_stack"]]
        evs[key] = {"name": spec["name"], "n": len(done), "n_days": len(hit), "pending": len(lst) - len(done),
                    "up20": sum(1 for x in done if x["fwd20"] > 0), "down20": sum(1 for x in done if x["fwd20"] <= 0),
                    "median20": r4(f20[len(f20) // 2]) if f20 else None, "mean20": r4(mean(f20)),
                    "worst_dd20": r4(min((x["dd20"] for x in done), default=None)) if done else None,
                    "in_bear": {"n": len(bear), "up20": sum(1 for x in bear if x["fwd20"] > 0), "down20": sum(1 for x in bear if x["fwd20"] <= 0)},
                    "list": lst}
    ts = {}
    for key, label in cfg4["trend"]["labels"].items():
        ii = [i for i, x in enumerate(trend) if x == key]
        runs = sum(1 for j, i in enumerate(ii) if j == 0 or i - ii[j - 1] > 1)
        f = sorted(x for x in (fw(i, 20) for i in ii) if x is not None)
        ts[label] = {"key": key, "days": len(ii), "runs": runs, "share": r4(len(ii) / N),
                     "median20": r4(f[len(f) // 2]) if f else None, "mean20": r4(mean(f)),
                     "up20": r4(mean([1 if x > 0 else 0 for x in f])) if f else None}
    return {"generated_at": tpe_now().isoformat(timespec="seconds"), "range": [dates[0], dates[-1]], "n_days": N, "dedupe_days": DEDUPE,
            "events": evs, "trend_states": ts,
            "note": "獨立事件:同一種事件相隔 10 個交易日以內算同一波,只取第一天。dd20 = 事件後 20 日內最低收盤相對事件日的跌幅。回測期間 3 年以前為精簡資料,不影響這幾種事件的判斷(只用指數、成交金額、基差、P/C)。"}

# ─────────────── eval ───────────────
def cmd_eval():
    cfg = load_v2_cfg()
    if not cfg: print("找不到 v2 設定(chips/panghu_v2.json),無法評估對照組"); return
    days = []
    for f in sorted(os.listdir(RAW)) if os.path.isdir(RAW) else []:
        if f.endswith(".json"): days += [v for v in (jload(os.path.join(RAW, f), {}) or {}).values() if v.get("_ok")]
    days.sort(key=lambda x: x["date"])
    need = int(os.environ.get("BT_MIN_DAYS", "30"))
    if len(days) < need: print(f"可用交易日只有 {len(days)} 天,至少要 {need} 天才評估;先不產生結果"); return
    fa.FX_RANGE = "10y"
    for d in days:                                    # 匯率:缺的用長區間日線補
        if not d.get("fx"): d["fx"] = fa.fx_for(d["date"])
    dates = [d["date"] for d in days]; close = [d["index"]["close"] for d in days]; N = len(days); mid = N // 2
    def fwd(k): return [(close[i + k] / close[i] - 1) if i + k < N else None for i in range(N)]
    F = {5: fwd(5), 20: fwd(20)}
    t0 = time.time()

    live = run_seq(days, cfg, "live"); full = run_seq(days, cfg, "full")
    strat_pos = {"panghu_live": pos_of(live), "panghu_full": pos_of(full), "buy_hold": [1.0] * N, "fixed_half": [0.5] * N}
    names = {"panghu_live": "胖虎指標(15:40 版)", "panghu_full": "胖虎指標(含融資)", "buy_hold": "全程滿倉", "fixed_half": "固定五成"}
    cfg3 = jload(V3_CFG_PATH)
    seq3 = run_seq_v3(days, cfg3, cfg) if cfg3 else None
    if seq3:
        strat_pos["panghu_v3"] = [((s_.get("panghu3") or {}).get("pos") if (s_.get("panghu3") or {}).get("pos") is not None else 50) / 100 for s_ in seq3]
        names["panghu_v3"] = "胖虎指標 v3(實驗)"
    grp_seq = {"all": live}
    for g, spec in GROUPS.items():
        if spec["keep"] is None: continue
        c = json.loads(json.dumps(cfg)); c["weights"] = {k: (w if k in spec["keep"] else 0) for k, w in cfg["weights"].items()}
        grp_seq[g] = run_seq(days, c, "live")
        strat_pos["grp_" + g] = pos_of(grp_seq[g]); names["grp_" + g] = spec["name"]

    # ── 策略績效(全期間 / 前半 / 後半)
    strategy = {"all": {}, "h1": {}, "h2": {}}; curves = {}; expos = {}; idx_rets = None
    for k, pos in strat_pos.items():
        rets, expo, idx_rets = simulate(close, pos)
        strategy["all"][k], curves[k] = metrics(rets, expo, idx_rets)
        strategy["h1"][k], _ = metrics(rets[:mid], expo[:mid], idx_rets[:mid])
        strategy["h2"][k], _ = metrics(rets[mid:], expo[mid:], idx_rets[mid:])
        curves[k] = [1.0] + curves[k]; expos[k] = [0.0] + expo      # 對齊日期(第 i 筆 = dates[i])

    # ── 回檔事件 + 三個目標
    eps = find_episodes(close)
    ep_rows = []
    for ep in eps:
        p, t, e, kind = ep
        row = {"kind": kind, "peak": dates[p], "trough": dates[t], "recover": dates[e] if e is not None else None,
               "depth": r4(close[t] / close[p] - 1), "days_down": t - p, "days_back": (e - t) if e is not None else None}
        for k in strat_pos:
            if k in ("buy_hold", "fixed_half", "panghu_full"): continue
            row[k] = grade_episode(ep, close, curves[k], expos[k], N)
        ep_rows.append(row)
    goals = {k: goals_of(ep_rows, k) for k in strat_pos if k not in ("buy_hold", "fixed_half", "panghu_full")}

    # ── 分段:近 3 年完整版 vs 更早精簡版(缺期貨三大法人)
    lite_idx = [i for i, d in enumerate(days) if d.get("lite")]
    segments = {}
    if lite_idx and len(lite_idx) < N:
        cut = max(lite_idx) + 1                                            # 精簡版一定在最前面連續一段
        for seg, (a, b) in (("lite", (0, cut)), ("full", (cut, N))):
            if b - a < 30: continue
            sm = {}
            for k, pos in strat_pos.items():
                rets, expo, ir = simulate(close[a:b], pos[a:b])
                sm[k], _ = metrics(rets, expo, ir)
            sub_eps = [r for r in ep_rows if a <= dates.index(r["peak"]) < b]
            segments[seg] = {"range": [dates[a], dates[b - 1]], "n": b - a, "strategy": sm,
                             "goals": {k: goals_of(sub_eps, k) for k in goals}, "n_episodes": len(sub_eps)}

    # ── 溫度分組 / 等級相關(15:40 版)
    temps = [(s.get("panghu") or {}).get("temp") for s in live]
    buckets = []
    for lo in (0, 20, 40, 60, 80):
        hi = 101 if lo == 80 else lo + 20
        ii = [i for i, tp in enumerate(temps) if tp is not None and lo <= tp < hi]
        row = {"lo": lo, "hi": min(hi, 100), "n": len(ii)}
        for k in (5, 20):
            xs = [F[k][i] for i in ii if F[k][i] is not None]
            row[f"fwd{k}"] = r4(mean(xs)); row[f"hit{k}"] = r4(mean([1 if x > 0 else 0 for x in xs])) if xs else None
        buckets.append(row)
    uncond = {k: r4(mean([x for x in F[k] if x is not None])) for k in (5, 20)}
    def ic_of(seq, rng=None, k=20):
        tp = [(s.get("panghu") or {}).get("temp") for s in seq]; rng = rng or range(N)
        pr = [(tp[i], F[k][i]) for i in rng if tp[i] is not None and F[k][i] is not None]
        return r4(spearman([a for a, _ in pr], [b for _, b in pr])) if len(pr) >= 5 else None
    ic = {"fwd5": ic_of(live, k=5), "fwd20": ic_of(live), "fwd20_h1": ic_of(live, range(0, mid)), "fwd20_h2": ic_of(live, range(mid, N))}
    for g, sq in grp_seq.items(): ic["grp_" + g] = ic_of(sq)
    for seg, sv in segments.items():
        a = dates.index(sv["range"][0]); b = dates.index(sv["range"][1]) + 1
        sv["ic20"] = ic_of(live, range(a, b)); sv["ic20_chips"] = ic_of(grp_seq["chips"], range(a, b)) if "chips" in grp_seq else None

    # ── 各指標(含融資版):分數與之後報酬的等級相關
    items = []
    for k, nm in cfg["names"].items():
        sc, f5, f20 = [], [], []
        for i, s in enumerate(full):
            it = next((x for x in (s.get("panghu") or {}).get("items", []) if x["k"] == k), None)
            if it is None or F[20][i] is None: continue
            sc.append(it["score"]); f20.append(F[20][i]); f5.append(F[5][i])
        by = {}
        for s_, r_ in zip(sc, f20): by.setdefault(s_, []).append(r_)
        items.append({"k": k, "name": nm, "w": cfg["weights"].get(k, 0), "n": len(sc),
                      "ic5": r4(spearman(sc, f5)) if sc else None, "ic20": r4(spearman(sc, f20)) if sc else None,
                      "by_score": {str(s_): {"n": len(v), "fwd20": r4(mean(v))} for s_, v in sorted(by.items())}})

    # ── 各情境(含融資版)
    sc_rows = {}
    for i, s in enumerate(full):
        for it in (s.get("panghu") or {}).get("items", []):
            row = sc_rows.setdefault((it["k"], it["scenario"]), {"k": it["k"], "name": it["name"], "scenario": it["scenario"],
                                                                 "score": it["score"], "n": 0, "_f5": [], "_f20": [], "_idx": [], "example": None})
            row["n"] += 1; row["_idx"].append(i)
            if F[5][i] is not None: row["_f5"].append(F[5][i])
            if F[20][i] is not None: row["_f20"].append(F[20][i])
            row["example"] = f"{s['date']}:{it['note']}"
    scenarios = []
    for row in sc_rows.values():
        f5, f20, ix_ = row.pop("_f5"), row.pop("_f20"), row.pop("_idx")
        row["fwd5"] = r4(mean(f5)); row["fwd20"] = r4(mean(f20)); row["hit20"] = r4(mean([1 if x > 0 else 0 for x in f20])) if f20 else None
        first = [i for j, i in enumerate(ix_) if j == 0 or i - ix_[j - 1] > DEDUPE]          # 同一波只算第一天,避免連續天數灌水
        ev20 = [F[20][i] for i in first if F[20][i] is not None]
        row["n_events"] = len(first); row["ev_fwd20"] = r4(mean(ev20)); row["ev_hit20"] = r4(mean([1 if x > 0 else 0 for x in ev20])) if ev20 else None
        ex = (row["ev_fwd20"] - uncond[20]) if (row["ev_fwd20"] is not None and uncond[20] is not None) else None
        row["excess20"] = r4(ex)
        row["flag"] = ("樣本少" if row["n_events"] < 5 else
                       "方向不符" if (ex is not None and row["score"] != 0 and (ex > 0) != (row["score"] > 0) and abs(ex) >= 0.005) else
                       "中性卻有方向" if (ex is not None and row["score"] == 0 and abs(ex) >= 0.02) else "")
        scenarios.append(row)
    order = list(cfg["names"])
    scenarios.sort(key=lambda r: (order.index(r["k"]) if r["k"] in order else 99, -r["score"], r["scenario"]))
    seen = {(r["k"], r["scenario"]) for r in scenarios}
    untriggered = [{"k": k, "name": cfg["names"].get(k, k), "scenario": sk, "score": v["score"]}
                   for k, grp in cfg["scenarios"].items() if k in cfg["names"] for sk, v in grp.items() if (k, sk) not in seen]

    # ── 參數敏感度(15:40 版):各 ×0.8 / ×1.2
    base = strategy["all"]["panghu_live"]; bg = goals["panghu_live"]
    sens = []
    for path, label in SENS:
        row = {"label": label, "path": ".".join(path)}
        for tag, fct in (("lo", 0.8), ("hi", 1.2)):
            try:
                c, v, nv = cfg_with(cfg, path, fct)
                sq = run_seq(days, c, "live"); rets, expo, ir = simulate(close, pos_of(sq))
                m, cv = metrics(rets, expo, ir); cv = [1.0] + cv; ex = [0.0] + expo
                g = goals_of([{"kind": r["kind"], "x": grade_episode((dates.index(r["peak"]), dates.index(r["trough"]),
                              dates.index(r["recover"]) if r["recover"] else None, r["kind"]), close, cv, ex, N)} for r in ep_rows], "x")
                row["base"] = v; row[tag] = {"value": nv, "total": m["total"], "mdd": m["mdd"], "calmar": m["calmar"], "ic20": ic_of(sq),
                                             "bear_avoided": g["bear_avoided"], "wash_re_days": g["wash_re_days"]}
            except Exception as e: row[tag] = {"error": f"{e.__class__.__name__}"}
        dt_ = [abs((row[t].get("total") or 0) - (base["total"] or 0)) for t in ("lo", "hi") if "total" in row[t]]
        dm_ = [abs((row[t].get("mdd") or 0) - (base["mdd"] or 0)) for t in ("lo", "hi") if "mdd" in row[t]]
        row["fragile"] = bool((dt_ and max(dt_) > 0.08) or (dm_ and max(dm_) > 0.04))
        sens.append(row)

    # ── 判斷準確度(方向 20 日 ±2%、環境 60 日 ±5%;都跟笨方法比)
    F60 = [(close[i + 60] / close[i] - 1) if i + 60 < N else None for i in range(N)]
    T20 = [truth_of(x, 0.02) for x in F[20]]; T60 = [truth_of(x, 0.05) for x in F60]
    ma60 = [(_ma := (sum(close[i - 59:i + 1]) / 60)) if i >= 59 else None for i in range(N)]
    base_trend = [None if ma60[i] is None else ("偏多" if close[i] >= ma60[i] * 1.02 else "偏空" if close[i] <= ma60[i] * 0.98 else "中性") for i in range(N)]
    methods = {"v2": [call_of(round(x * 100)) for x in strat_pos["panghu_live"]], "always_bull": ["偏多"] * N, "ma60": base_trend}
    mnames = {"v2": "胖虎 v2", "always_bull": "永遠偏多(笨方法)", "ma60": "60 日均線 ±2%(笨方法)"}
    if seq3:
        methods["v3"] = [call_of((x.get("panghu3") or {}).get("pos")) for x in seq3]; mnames["v3"] = "胖虎 v3(實驗)"
        reg_call = {"多頭": "偏多", "盤整": "中性", "空頭": "偏空"}
        methods_reg = {"v3": [reg_call.get((x.get("panghu3") or {}).get("regime")) for x in seq3]}
    else: methods_reg = {}
    v2temp = [(x.get("panghu") or {}).get("temp") for x in live]
    methods_reg.update({"v2": [None if t is None else ("偏多" if t >= 60 else "偏空" if t <= 40 else "中性") for t in v2temp],
                        "always_bull": ["偏多"] * N, "ma60": base_trend})
    direction = {k: judge(v, T20) for k, v in methods.items()}
    regime_acc = {k: judge(v, T60) for k, v in methods_reg.items()}
    # 各狀態之後的表現(v3)
    states = []
    if seq3:
        by = {}
        for i, x in enumerate(seq3):
            st_ = (x.get("panghu3") or {}).get("state")
            if not st_ or F[20][i] is None: continue
            key = st_.split("・", 1)[-1] if st_.startswith(("轉多確認", "轉空確認", "轉入盤整")) else st_
            by.setdefault(key, []).append(F[20][i])
        for k, xs in sorted(by.items(), key=lambda kv: -len(kv[1])):
            states.append({"state": k, "n": len(xs), "fwd20": r4(mean(xs)), "up20": r4(mean([1 if x > 0.02 else 0 for x in xs])),
                           "down20": r4(mean([1 if x < -0.02 else 0 for x in xs]))})
    # 轉折:每次真下跌,多久判空、谷底後多久判多
    def first(rng, cond): return next((i for i in rng if cond(i)), None)
    turns = []
    for r in ep_rows:
        if r["kind"] != "真下跌": continue
        pk, tr = dates.index(r["peak"]), dates.index(r["trough"])
        row = {"peak": r["peak"], "trough": r["trough"], "depth": r["depth"]}
        detect = {"v2": (lambda i: methods["v2"][i] == "偏空", lambda i: methods["v2"][i] == "偏多"),
                  "ma60": (lambda i: base_trend[i] == "偏空", lambda i: base_trend[i] == "偏多")}
        if seq3: detect["v3"] = (lambda i: (seq3[i].get("panghu3") or {}).get("regime") == "空頭", lambda i: (seq3[i].get("panghu3") or {}).get("regime") == "多頭")
        for k, (isbear, isbull) in detect.items():
            b = first(range(pk + 1, tr + 1), isbear); u = first(range(tr, N), isbull)
            row[k] = {"bear_days": (b - pk) if b is not None else None, "bear_dd": r4(close[b] / close[pk] - 1) if b is not None else None,
                      "bull_days": (u - tr) if u is not None else None, "bull_gain": r4(close[u] / close[tr] - 1) if u is not None else None}
        turns.append(row)
    # 誤報與穩定度
    years_n = N / 250
    def flips(seq_calls, want):
        idx = [i for i in range(1, N) if seq_calls[i] == want and seq_calls[i - 1] != want and seq_calls[i - 1] is not None]
        bad = [i for i in idx if i + 40 < N and ((close[i + 40] > close[i]) if want in ("空頭", "偏空") else (close[i + 40] < close[i]))]
        return {"n": len(idx), "false": len(bad), "false_rate": r4(len(bad) / len(idx)) if idx else None}
    stability = {}
    def changes(xs): return sum(1 for i in range(1, N) if xs[i] is not None and xs[i - 1] is not None and xs[i] != xs[i - 1])
    stability["v2"] = {"call_changes_per_year": round(changes(methods["v2"]) / years_n, 1), "to_bear": flips(methods["v2"], "偏空"), "to_bull": flips(methods["v2"], "偏多")}
    stability["ma60"] = {"call_changes_per_year": round(changes(base_trend) / years_n, 1), "to_bear": flips(base_trend, "偏空"), "to_bull": flips(base_trend, "偏多")}
    if seq3:
        regs = [(x.get("panghu3") or {}).get("regime") for x in seq3]
        stability["v3"] = {"call_changes_per_year": round(changes(methods["v3"]) / years_n, 1), "regime_changes_per_year": round(changes(regs) / years_n, 1),
                           "to_bear": flips(regs, "空頭"), "to_bull": flips(regs, "多頭")}
    judgment = {"names": mnames, "direction": direction, "regime": regime_acc, "states": states, "turns": turns, "stability": stability,
                "notes": "方向:之後 20 日漲超過 2% 算漲、跌超過 2% 算跌;環境:之後 60 日 ±5%。平衡準確率 = 漲 / 平 / 跌三類各自命中率的平均,「永遠偏多」固定約 0.33。誤報 = 翻空後 40 天反而更高、翻多後 40 天反而更低。"}

    acts = {}
    for s in live:
        a = ((s.get("panghu") or {}).get("discipline") or {}).get("act")
        if a: acts[a] = acts.get(a, 0) + 1

    res = {
        "generated_at": tpe_now().isoformat(timespec="seconds"), "config_version": cfg.get("version"),
        "range": [dates[0], dates[-1]], "n_days": N, "split_date": dates[mid], "cost_per_turn": COST_PER_TURN,
        "lite_days": len(lite_idx), "segments": segments,
        "vix_days": sum(1 for d in days if d.get("vix")), "uncond": uncond,
        "names": names, "groups": {("grp_" + g): s["name"] for g, s in GROUPS.items() if s["keep"] is not None},
        "strategy": strategy, "goals": goals, "episodes": ep_rows,
        "buckets": buckets, "ic": ic, "items": items, "scenarios": scenarios, "untriggered": untriggered,
        "sensitivity": {"base": {"total": base["total"], "mdd": base["mdd"], "calmar": base["calmar"], "ic20": ic["fwd20"],
                                 "bear_avoided": bg["bear_avoided"], "wash_re_days": bg["wash_re_days"]}, "rows": sens},
        "actions": acts, "judgment": judgment,
        "series": {"dates": dates, "close": close, "temp": temps, "pos": [round(p * 100) for p in strat_pos["panghu_live"]],
                   "v3": {"temp": [(x.get("panghu3") or {}).get("temp") for x in seq3], "pos": [(x.get("panghu3") or {}).get("pos") for x in seq3],
                          "regime": [(x.get("panghu3") or {}).get("regime") for x in seq3]} if seq3 else None,
                   "eq": {k: [round(x, 4) for x in v] for k, v in curves.items()}},
        "notes": [
            "15:40 版模擬盤後發 LINE 的時點:當日融資未公布,融資不計分;含融資版是 21:30 補齊後的結果。",
            f"台指 VIX 官方只留近 3 個月,回測 {N} 天中只有 {sum(1 for d in days if d.get('vix'))} 天有 VIX,其餘不計分。",
            "決策在當日盤後,策略從隔日收盤才換倉(不偷看)。加權指數為價格指數,不含股息。",
            f"期交所期貨 / 選擇權三大法人只開放近 3 年;更早的 {len(lite_idx)} 天為精簡版,外資期貨多空與散戶多空比不計分(分段表分開看)。",
            f"換倉成本以每 100% 部位變動 {COST_PER_TURN * 100:.2f}% 計。",
            "回檔事件:從前高跌超過 8% 算一次,站回前高結束;跌幅 ≥ 15% 算「真下跌」,其餘算「洗盤」。這是事後分類,用來打分數;指標本身只能用當下資料判斷。",
            "情境表改用「獨立事件」:同一情境相隔 10 個交易日以內算同一波,只取第一天;「方向不符」= 分數給正、獨立事件之後 20 日卻跑輸平均(或反之)超過 0.5%;獨立事件少於 5 次不判斷。",
            "參數敏感度:單一門檻 ×0.8 / ×1.2 後總報酬變動超過 8 個百分點或最大回檔變動超過 4 個百分點,標為「敏感」,代表那個數字可能是剛好擬合出來的。"]
    }
    # ── v4 描述型:極端事件歷史(獨立事件)與趨勢狀態基準 → events.json(籌碼站與 LINE 讀)
    cfg4 = fa.load_panghu_cfg()
    if cfg4.get("version") == 4:
        dseq = run_describe(days, cfg4)
        evj = events_summary(dseq, close, dates, cfg4)
        jsave(os.path.join(BT, "events.json"), evj)
        res["events_summary"] = {k: {x: v.get(x) for x in ("name", "n", "n_days", "up20", "down20", "median20", "worst_dd20", "in_bear")} for k, v in evj["events"].items()}
        res["trend_states"] = evj["trend_states"]
        print("  極端事件(獨立):" + "、".join(f"{v['name']} {v['n']} 次({v['up20']} 漲 {v['down20']} 跌)" for v in evj["events"].values()))
    jsave(os.path.join(BT, "result.json"), res)
    L = strategy["all"]
    print(f"回測 {dates[0]} ~ {dates[-1]},{N} 天(計算 {time.time() - t0:.0f} 秒);溫度與 20 日報酬等級相關 {ic.get('fwd20')}")
    for k in strat_pos: print(f"  {names[k]:<14} 總報酬 {L[k]['total']:+.2%}  最大回檔 {L[k]['mdd']:.2%}  換倉 {L[k]['changes']} 次  平均部位 {L[k]['avg_expo']:.0%}")
    g = goals["panghu_live"]
    print(f"  回檔事件 {len(ep_rows)} 次(真下跌 {g['bear_n']}、洗盤 {g['wash_n']});真下跌少跌 {g['bear_avoided']};洗盤谷底部位 {g['wash_expo_trough']}、回到七成 {g['wash_re_days']} 天;大底後 60 天參與 {g['rally_cap']}")
    print(f"  情境 {len(scenarios)} 種出現過,{len(untriggered)} 種沒出現;方向不符 {sum(1 for r in scenarios if r['flag'] == '方向不符')} 種;敏感參數 {sum(1 for r in sens if r['fragile'])} 個")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "eval"])
    ap.add_argument("--years", type=float, default=2)
    ap.add_argument("--minutes", type=float, default=100)
    ap.add_argument("--days", type=int, default=0, help="只抓最近 N 個交易日(測試用)")
    a = ap.parse_args()
    if a.cmd == "fetch": cmd_fetch(a.years, a.minutes, a.days)
    else: cmd_eval()
