# -*- coding: utf-8 -*-
"""kd.py ─ 大盤日 KD(9,3,3)與「反彈滿足區」提醒(純計算,不連網;資料由 fetch_all.kd_live 抓)。
使用者要的提醒(2026-11-23 設定,門檻在 chips/kd_alert.json,可以直接改數字):
  第一段 hot  :收盤接近滿足區(離下緣 near_pct% 以內或更高)而且 K ≥ k_hot(超買)
  第二段 cross:近 recent_days 日收盤到過「接近」的位置,而且今天 KD 高檔死亡交叉(昨天 K≥D、今天 K<D,昨天 K 或 D ≥ cross_min)
兩段都只描述指標狀態,不是買賣建議。"""
import os, json

DEFAULT = {"enabled": True, "zone_lo": 39546, "zone_hi": 40991, "near_pct": 2.0,
           "k_hot": 80, "cross_min": 70, "recent_days": 5, "n": 9, "min_days": 30}

def load_cfg(path):
    cfg = dict(DEFAULT)
    try:
        with open(path, encoding="utf-8") as f: cfg.update({k: v for k, v in json.load(f).items() if k in DEFAULT})
    except (OSError, ValueError): pass
    return cfg

def kd_series(highs, lows, closes, n=9):
    """台灣慣用的 KD:RSV = (收盤 − n 日最低) / (n 日最高 − n 日最低) × 100;K = 2/3 前 K + 1/3 RSV;D = 2/3 前 D + 1/3 K;起始 50。
    回傳從第 n 天起每天的 (K, D)。資料不足回空 list。"""
    out = []; k = d = 50.0
    for i in range(n - 1, len(closes)):
        hh, ll = max(highs[i - n + 1:i + 1]), min(lows[i - n + 1:i + 1])
        rsv = 50.0 if hh == ll else (closes[i] - ll) / (hh - ll) * 100
        k = k * 2 / 3 + rsv / 3; d = d * 2 / 3 + k / 3
        out.append((k, d))
    return out

def evaluate(highs, lows, closes, cfg=None):
    """回 {k, d, prev_k, prev_d, close, near, stage, text, alert};天數不夠(KD 還沒收斂)回 None。"""
    cfg = cfg or DEFAULT
    if not cfg.get("enabled", True): return None
    if not (len(highs) == len(lows) == len(closes)) or len(closes) < max(cfg["min_days"], cfg["n"] + 1): return None
    kd = kd_series(highs, lows, closes, cfg["n"])
    (pk, pd_), (k, d) = kd[-2], kd[-1]
    c = closes[-1]; lo, hi = cfg["zone_lo"], cfg["zone_hi"]
    line = lo * (1 - cfg["near_pct"] / 100)                       # 「接近」門檻
    near = c >= line
    near_recent = max(closes[-cfg["recent_days"]:]) >= line
    hot = k >= cfg["k_hot"]
    cross = pk >= pd_ and k < d and max(pk, pd_) >= cfg["cross_min"]
    stage = "cross" if (cross and near_recent) else ("hot" if (near and hot) else None)
    where = (f"已進滿足區 {lo:,.0f}～{hi:,.0f}" if lo <= c <= hi else f"已超過滿足區上緣 {hi:,.0f}" if c > hi
             else f"離滿足區下緣 {lo:,.0f} 還差 {(lo - c) / c * 100:.1f}%")
    text = f"大盤日 KD(9,3,3) K {k:.1f} / D {d:.1f}(昨 {pk:.1f} / {pd_:.1f});收盤 {c:,.0f},{where}"
    alert = None
    if stage == "hot":
        alert = f"🔔 反彈提醒①:收盤 {c:,.0f} {where},KD 進超買(K {k:.1f} ≥ {cfg['k_hot']})"
    elif stage == "cross":
        alert = f"🔔🔔 反彈提醒②:KD 高檔死亡交叉(K {pk:.1f}→{k:.1f} 跌破 D {d:.1f}),收盤 {c:,.0f} {where}"
    return {"k": round(k, 1), "d": round(d, 1), "prev_k": round(pk, 1), "prev_d": round(pd_, 1), "close": c,
            "near": near, "stage": stage, "text": text, "alert": alert,
            "zone": [lo, hi], "near_line": round(line)}
