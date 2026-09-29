# -*- coding: utf-8 -*-
"""
panghu.py ─ 胖虎指標的純計算(不抓網路、不寫檔),盤後 fetch_all.py 與回測 backtest.py 共用,tests/test_panghu.py 直接測這支。
  v2 情境版 build_panghu     :已停用的評分版,只留給回測當對照組(設定 chips/panghu_v2.json)
  v4 描述型 build_describe   :五個面向(趨勢 / 籌碼 / 情緒 / 匯率 / 風險)的現況描述 + 極端事件;不合成分數、不預測、不給倉位
  位置百分位 attach_position :今天的值在歷史分布(backtest 產生的 dist.json)中排第幾,加一句話總結 headline
輸入都是 dict / list,跟資料來源無關;所有門檻在 chips/panghu.json。
"""
import os, json, math, bisect

CHIPS = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
EVENTS_PATH = os.path.join(CHIPS, "backtest", "events.json")

def _close(d): return ((d or {}).get("index") or {}).get("close")
def _amt(d): return ((d or {}).get("index") or {}).get("amount_yi")

# ─────────────── 胖虎指標(v2 情境版) ───────────────
# 13 項指標各自判斷「情境」,情境決定分數(-2~+2)與說法,全部寫在 chips/panghu.json;乘權重加總映射成 0~100 溫度,
# 再對應 0%~100% 建議倉位(每 10% 一級,越過邊界 buffer 分才換級,加碼另需外資現貨買超),最後依防線 / 第二道產生紀律動作。
# 這是機械式指標加總,規則與權重全在設定檔,不是投資建議。
PANGHU_CFG_PATH = os.path.join(CHIPS, "panghu.json")
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

def realized_vol(closes, n=20):
    """近 n 日年化實際波動(%):對數日報酬的標準差 × √245;收盤不足 n+1 天回 None。盤後與回測共用"""
    xs = [c for c in closes[-(n + 1):] if c]
    if len(xs) < n + 1: return None
    r = [math.log(xs[i] / xs[i - 1]) for i in range(1, len(xs))]
    m = sum(r) / len(r)
    return math.sqrt(sum((x - m) ** 2 for x in r) / len(r)) * math.sqrt(245) * 100

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
        data["fut_net"] = net
        fo = ((hist[-20] if len(hist) >= 20 else {}).get("txf") or {}).get("外資")      # 20 個交易日前(hist 不含今天)
        if ok_oi(fo):
            c20 = net - fo["net"]; data["fut_chg20"] = c20
            nw = lambda x: f"淨{'空' if x < 0 else '多'} {abs(x):,}"
            lines.append(f"近 20 日 {nw(fo['net'])} → {abs(net):,} 口,{c20:+,} 口({'往多方:回補空單 / 加多' if c20 > 0 else '往空方:加空 / 砍多' if c20 < 0 else '持平'})")
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

    # ── 風險:近 20 日實際波動 → 震幅描述(不代表方向);要有回測產生的波動分組(dist.risk)才寫這個面向
    Kr = cfg.get("risk") or {}; nd = Kr.get("days", 20)
    rv = realized_vol(closes, nd) if closes else None
    if rv is not None:
        rv = round(rv, 2); data["rv20"] = rv                              # 跟位置百分位用同一個值,兩邊的百分位才會一致
        RK = (dist or {}).get("risk") or {}; dq = ((dist or {}).get("metrics") or {}).get("rv20") or {}
        if RK.get("groups") and len(dq.get("q") or []) == 101:
            pr = pctile(rv, dq["q"]); g = next((x for x in RK["groups"] if pr < x["hi"]), RK["groups"][-1])
            w = Kr.get("today_weight", 0.3); blend = w * rv + (1 - w) * (dq.get("mean") or rv)
            rng = blend * math.sqrt(nd / 245) * (RK.get("k68") or 1.0)          # 用歷史實際分布校準:約 2/3 的 20 日漲跌落在 ±rng 內
            data["risk_range"] = round(rng, 2)
            lines = [f"近 {nd} 日實際波動 {rv:.1f}%(年化),近 3 年第 {round(pr)} 百分位",
                     f"照目前估算,接下來 20 日常見漲跌約 ±{rng:.1f}%(歷史上約 2/3 的時間落在這個範圍內)",
                     f"歷史上這種波動環境:20 日內最深跌中位數 {g['dd_med']:+.1f}%、最差 1 成 {g['dd_w10']:+.1f}%,"
                     f"跌超過 8% 的機率 {g['p8']:.0f}%(獨立 {g['n_ep']} 段中 {g['ep8']} 段)",
                     "波動只描述震幅,不代表方向;高波動時大反彈也比較多"]
            asp("risk", "風險", g["label"], "hot" if g["lo"] >= 80 else "neutral", lines, f"{g['label']}(20 日常見 ±{rng:.1f}%)")

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

# ─────────────── 胖虎指標 v4:歷史位置百分位 ───────────────
# 只回答「今天這個值在過去歷史中排第幾(0 最低、100 最高)」;不加總、不給多空結論。
# 分布由 backtest.py 重算時產生(chips/backtest/dist.json,每週六更新),只含過去的日子,不偷看未來。
DIST_PATH = os.path.join(CHIPS, "backtest", "dist.json")
POS_SPEC = [   # (key, 面向, 名稱, 顯示格式)
    ("gap60", "trend", "收盤對 60 日均", "{:+.1f}%"),
    ("vol_ratio", "trend", "成交對 20 日均量", "{:.0f}%"),
    ("foreign20_pct", "chips", "外資現貨 20 日佔成交", "{:+.1f}%"),
    ("fut_chg20", "chips", "外資台指期 20 日增減", "{:+,.0f} 口"),   # 看增減不看水位:外資 3 年來多單大砍、空單大增,水位已經結構性漂移
    ("retail", "sentiment", "散戶多空比", "{:+.1f}%"),
    ("pc", "sentiment", "P/C(OI)", "{:.1f}%"),
    ("twd20", "fx", "美元兌台幣 20 日", "{:+.2f}%"),
    ("rv20", "risk", "近 20 日實際波動", "{:.1f}%"),                 # 只跟近 3 年比(波動水位會隨時代變)
]

POS_WORDS = {   # 偏低 / 偏高的白話(頁面標籤、一句話總結共用);百分位高不代表好、低不代表壞
    "gap60": ("跌離均線", "漲離均線"), "vol_ratio": ("量縮", "量增"), "foreign20_pct": ("外資賣得多", "外資買得多"),
    "fut_chg20": ("期貨往空方", "期貨往多方"), "retail": ("散戶偏空", "散戶偏多"), "pc": ("避險少", "避險多"),
    "twd20": ("台幣升", "台幣貶"), "rv20": ("震幅小", "震幅大"),
}

def position_values(t, data):
    """位置百分位用的原始值;t 當日、data = build_describe 的 data"""
    rs = [x["ratio_pct"] for x in (t.get("mtx_retail"), t.get("tmf_retail")) if x and x.get("ratio_pct") is not None]
    return {"gap60": data.get("gap60"), "vol_ratio": data.get("vol_ratio"), "foreign20_pct": data.get("foreign20_pct"),
            "fut_chg20": data.get("fut_chg20"), "retail": round(sum(rs) / len(rs), 2) if rs else None,
            "pc": (t.get("pc") or {}).get("oi_ratio_pct"), "twd20": data.get("twd20"), "rv20": data.get("rv20")}

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
                    "word": POS_WORDS.get(k, ("偏低", "偏高"))[1 if p >= 50 else 0],
                    "range": f"{nf.format(q20)} ~ {nf.format(q80)}{unit}",
                    "range_text": f"正常 {nf.format(q20)} ~ {nf.format(q80)}{unit}・中位數 {nf.format(q50)}{unit}"})
    if out:
        pg["position"] = out
        pg["position_note"] = f"位置 = 今天的值在過去歷史中排第幾(0 最低、100 最高),分布資料到 {(dist.get('range') or ['', ''])[1]};只描述多極端,不是買賣訊號。"
        # 一句話總結:趨勢・風險;幾項偏離平常(白話);有極端事件就附上 —— 純描述,不加總、不給結論
        lab = {a["k"]: a["label"] for a in pg.get("aspects") or []}
        head = "・".join(x for x in (lab.get("trend"), lab.get("risk")) if x)
        odd = [x for x in out if x["p"] <= 20 or x["p"] >= 80]
        tail = (f"{len(out)} 項中 {len(odd)} 項偏離平常(" + "、".join(x["word"] for x in odd) + ")") if odd else f"{len(out)} 項都在正常區間"
        ev = "、".join(e["name"] for e in pg.get("events") or [])
        pg["headline"] = "今天:" + (head + ";" if head else "") + tail + (f"・⚠ {ev}" if ev else "")

