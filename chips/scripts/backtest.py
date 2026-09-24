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
    stores = {}; done = skip = fail = 0; stopped = False
    for d in todo:
        ym = d[:4] + d[5:7]; path = os.path.join(RAW, ym + ".json")
        if ym not in stores: stores[ym] = jload(path, {}) or {}
        st = stores[ym]
        if (st.get(d) or {}).get("_ok"): skip += 1; continue
        if time.time() > t_end: stopped = True; break
        df = safe(fa.taifex_fut, d)
        if df is None: fail += 1; print(f"  {d} 期交所無資料,略過"); time.sleep(PACE); continue
        c = fa.collect(d, df)
        if c.get("inst") is None: time.sleep(8); c["inst"] = safe(fa.twse_inst, d)          # 證交所偶爾擋 → 等一下重抓一次
        if c.get("margin") is None: time.sleep(8); c["margin"] = safe(fa.twse_margin, d)
        c["_ok"] = bool(c.get("index") and c.get("inst") and (c.get("txf") or {}).get("外資"))
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
              "trading_days": len(todo), "ok": total_ok, "new": done, "fail": fail, "complete": (not stopped) and total_ok >= len(todo) - fail}
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

# ─────────────── eval ───────────────
def cmd_eval():
    cfg = fa.load_panghu_cfg()
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
                                                                 "score": it["score"], "n": 0, "_f5": [], "_f20": [], "example": None})
            row["n"] += 1
            if F[5][i] is not None: row["_f5"].append(F[5][i])
            if F[20][i] is not None: row["_f20"].append(F[20][i])
            row["example"] = f"{s['date']}:{it['note']}"
    scenarios = []
    for row in sc_rows.values():
        f5, f20 = row.pop("_f5"), row.pop("_f20")
        row["fwd5"] = r4(mean(f5)); row["fwd20"] = r4(mean(f20)); row["hit20"] = r4(mean([1 if x > 0 else 0 for x in f20])) if f20 else None
        ex = (row["fwd20"] - uncond[20]) if (row["fwd20"] is not None and uncond[20] is not None) else None
        row["excess20"] = r4(ex)
        row["flag"] = ("樣本少" if row["n"] < 5 else
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

    acts = {}
    for s in live:
        a = ((s.get("panghu") or {}).get("discipline") or {}).get("act")
        if a: acts[a] = acts.get(a, 0) + 1

    res = {
        "generated_at": tpe_now().isoformat(timespec="seconds"), "config_version": cfg.get("version"),
        "range": [dates[0], dates[-1]], "n_days": N, "split_date": dates[mid], "cost_per_turn": COST_PER_TURN,
        "vix_days": sum(1 for d in days if d.get("vix")), "uncond": uncond,
        "names": names, "groups": {("grp_" + g): s["name"] for g, s in GROUPS.items() if s["keep"] is not None},
        "strategy": strategy, "goals": goals, "episodes": ep_rows,
        "buckets": buckets, "ic": ic, "items": items, "scenarios": scenarios, "untriggered": untriggered,
        "sensitivity": {"base": {"total": base["total"], "mdd": base["mdd"], "calmar": base["calmar"], "ic20": ic["fwd20"],
                                 "bear_avoided": bg["bear_avoided"], "wash_re_days": bg["wash_re_days"]}, "rows": sens},
        "actions": acts,
        "series": {"dates": dates, "close": close, "temp": temps, "pos": [round(p * 100) for p in strat_pos["panghu_live"]],
                   "eq": {k: [round(x, 4) for x in v] for k, v in curves.items()}},
        "notes": [
            "15:40 版模擬盤後發 LINE 的時點:當日融資未公布,融資不計分;含融資版是 21:30 補齊後的結果。",
            f"台指 VIX 官方只留近 3 個月,回測 {N} 天中只有 {sum(1 for d in days if d.get('vix'))} 天有 VIX,其餘不計分。",
            "決策在當日盤後,策略從隔日收盤才換倉(不偷看)。加權指數為價格指數,不含股息。",
            f"換倉成本以每 100% 部位變動 {COST_PER_TURN * 100:.2f}% 計。",
            "回檔事件:從前高跌超過 8% 算一次,站回前高結束;跌幅 ≥ 15% 算「真下跌」,其餘算「洗盤」。這是事後分類,用來打分數;指標本身只能用當下資料判斷。",
            "情境表的「方向不符」= 分數給正、之後 20 日卻跑輸平均(或反之)超過 0.5%;樣本少於 5 次不判斷。",
            "參數敏感度:單一門檻 ×0.8 / ×1.2 後總報酬變動超過 8 個百分點或最大回檔變動超過 4 個百分點,標為「敏感」,代表那個數字可能是剛好擬合出來的。"]
    }
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
