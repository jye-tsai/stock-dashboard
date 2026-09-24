# -*- coding: utf-8 -*-
"""panghu_v3.py ─ 胖虎指標 v3(實驗組):環境層 × 溫度層 → 市場狀態判讀 + 建議倉位。
目前只給 backtest.py 用,不影響每天 15:40 的正式判斷(正式版仍是 fetch_all.build_panghu 的 v2)。

  環境層(慢):60 日均線斜率、收盤對 120 日均線、外資 20 日累計佔成交金額、台幣 20 日變化,各 -1/0/+1,
              加總判多頭 / 盤整 / 空頭;新狀態連續 confirm_days 天才確認,避免來回跳。
  溫度層(快):沿用 v2 的情境評分(fa.build_panghu),權重換成 panghu_v3.json 的 temp_weights(拿掉沒預測力的項目),取 3 日平均。
  恐慌:特定情境(超跌、爆量長黑、P/C 極低、散戶接刀、VIX 驟升)或溫度極低。多頭與盤整判為洗盤;空頭只標記不加碼。
  倉位:依環境給區間,溫度在區間內調整;換級後至少持有 min_hold 天(環境改變不受限)。

用法:build(t, p, hist, cfg3, base_cfg, fa) → dict;hist 要含之前至少 140 天(120 日均線 + 斜率回看)。
"""
import json, math

def _mean(xs): return sum(xs) / len(xs) if xs else None
def _close(d): return ((d or {}).get("index") or {}).get("close")
def _amt(d): return ((d or {}).get("index") or {}).get("amount_yi")

def regime_raw(seq, R):
    """seq = hist + [t](由舊到新)。回傳 (分數, 明細, 原始環境) ;資料不足回 (None, {}, None)"""
    cl = [_close(d) for d in seq]
    if len(cl) < R["long_ma_days"] or any(c is None for c in cl[-R["long_ma_days"]:]): return None, {}, None
    n, lag = R["ma_days"], R["slope_lag"]
    ma_now = _mean(cl[-n:]); ma_then = _mean(cl[-n - lag:-lag]) if len(cl) >= n + lag else None
    slope = (ma_now / ma_then - 1) * 100 if ma_then else None
    vs_long = (cl[-1] / _mean(cl[-R["long_ma_days"]:]) - 1) * 100
    fd = R["foreign_days"]; fs = [((d.get("inst") or {}).get("外資")) for d in seq[-fd:]]; am = [_amt(d) for d in seq[-fd:]]
    foreign = (sum(x or 0 for x in fs) / sum(a or 0 for a in am) * 100) if all(a for a in am) else None
    xd = R["fx_days"]; tw = [((d.get("fx") or {}).get("usdtwd")) for d in seq]
    fx = (tw[-1] / tw[-1 - xd] - 1) * 100 if (len(tw) > xd and tw[-1] and tw[-1 - xd]) else None
    def sgn(x, th, inv=False):
        if x is None: return 0
        s = 1 if x >= th else -1 if x <= -th else 0
        return -s if inv else s
    parts = {"slope": (slope, sgn(slope, R["slope_pct"])), "vs_long": (vs_long, sgn(vs_long, R["vs_long_pct"])),
             "foreign": (foreign, sgn(foreign, R["foreign_pct"])), "fx": (fx, sgn(fx, R["fx_pct"], inv=True))}   # 台幣貶(美元兌台幣上升)= 偏空
    score = sum(v[1] for v in parts.values())
    raw = "多頭" if score >= R["bull_at"] else "空頭" if score <= R["bear_at"] else "盤整"
    return score, {k: {"value": None if v[0] is None else round(v[0], 2), "score": v[1]} for k, v in parts.items()}, raw

def build(t, p, hist, cfg3, base_cfg, fa):
    # ── 溫度層:沿用 v2 情境評分,權重換成 v3 的
    c = json.loads(json.dumps(base_cfg)); c["weights"] = {k: cfg3["temp_weights"].get(k, 0) for k in base_cfg["weights"]}
    inner = fa.build_panghu(t, p, hist[-20:], c)
    prev3 = (hist[-1].get("panghu3") or {}) if hist else {}
    temps = [x for x in ([(h.get("panghu3") or {}).get("temp_raw") for h in hist[-(cfg3["temp_smooth_days"] - 1):]] + [inner.get("temp")]) if x is not None]
    temp_s = round(_mean(temps)) if temps else None

    # ── 環境層(新狀態連續 confirm_days 天才確認)
    R = cfg3["regime"]; score, parts, raw = regime_raw(hist + [t], R)
    prev_reg = prev3.get("regime"); streak = (prev3.get("raw_streak", 0) + 1) if (raw and raw == prev3.get("raw")) else 1
    if prev_reg is None: regime = raw
    elif raw and raw != prev_reg and streak >= R["confirm_days"]: regime = raw
    else: regime = prev_reg
    turned = regime if (prev_reg and regime and regime != prev_reg) else None

    # ── 恐慌
    C = cfg3["capitulation"]; hits = [f"{it['name']}・{it['scenario']}" for it in inner.get("items", [])
                                    if it["scenario"] in C["scenarios"].get(it["k"], [])]
    panic = bool(hits) or (inner.get("temp") is not None and inner["temp"] <= C["temp_max"])

    # ── 狀態
    S = cfg3["states"]; state = None
    if regime and temp_s is not None:
        g = S[regime]
        if panic: state = g["panic"]
        elif temp_s >= S["high_temp"] and "high" in g: state = g["high"]
        elif temp_s < S["low_temp"] and "low" in g: state = g["low"]
        else: state = g["mid"]
        if turned: state = (S["turn_bull"] if turned == "多頭" else S["turn_bear"] if turned == "空頭" else "轉入盤整") + "・" + state

    # ── 倉位(區間內依溫度;恐慌在多頭拉到上緣、盤整加碼;最短持有)
    P = cfg3["position"]; pos = None
    if regime and temp_s is not None:
        lo, hi = P["ranges"][regime]
        x = max(0.0, min(1.0, (temp_s - P["temp_lo"]) / (P["temp_hi"] - P["temp_lo"])))
        pos = lo + (hi - lo) * x
        if panic and regime == "多頭": pos = hi
        elif panic and regime == "盤整": pos = min(hi, pos + P["panic_boost"])
        pos = int(math.floor(pos / P["step"] + 0.5) * P["step"])
        prev_pos, held = prev3.get("pos"), prev3.get("held", 0)
        if prev_pos is not None and pos != prev_pos and held < P["min_hold"] and not turned: pos = prev_pos
    held = (prev3.get("held", 0) + 1) if (pos is not None and pos == prev3.get("pos")) else 1
    return {"version": 3, "temp_raw": inner.get("temp"), "temp": temp_s, "regime": regime, "raw": raw, "raw_streak": streak,
            "regime_score": score, "regime_parts": parts, "turned": turned, "panic": panic, "panic_hits": hits,
            "state": state, "pos": pos, "held": held, "items": inner.get("items", [])}
