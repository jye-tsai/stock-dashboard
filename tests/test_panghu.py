# -*- coding: utf-8 -*-
"""胖虎指標純函式測試(chips/scripts/panghu.py):全部用假資料,不碰網路、不讀 data/。
本機:python -m unittest discover -s tests -p "test_*.py" -v ;GitHub check.yml 也是這樣跑。"""
import os, sys, json, math, copy, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "chips", "scripts"))
import panghu as P

CFG = json.load(open(os.path.join(HERE, "..", "chips", "panghu.json"), encoding="utf-8"))


def q_linear(lo, hi):
    """第 0~100 百分位等距的分位表"""
    return [round(lo + (hi - lo) * i / 100, 4) for i in range(101)]

def make_dist(**metrics):
    """metrics: key -> (lo, hi) 或 (lo, hi, years)"""
    out = {}
    for k, v in metrics.items():
        lo, hi = v[0], v[1]; q = q_linear(lo, hi)
        out[k] = {"n": 2000, "years": v[2] if len(v) > 2 else 9.9, "from": "2016/10/01", "to": "2026/09/23", "mean": (lo + hi) / 2, "q": q}
    return {"range": ["2016/09/26", "2026/09/23"], "metrics": out}

def closes_geometric(n, daily, start=100.0):
    return [start * (1 + daily) ** i for i in range(n)]

def day(date, close, chg, amt=5000, **extra):
    t = {"date": date, "index": {"close": close, "chg": chg, "amount_yi": amt}}
    t.update(extra); return t


class TestRealizedVol(unittest.TestCase):
    def test_constant_growth_is_zero(self):
        self.assertAlmostEqual(P.realized_vol(closes_geometric(30, 0.01), 20), 0.0, places=9)

    def test_alternating_known_value(self):
        xs = [100, 101] * 11                       # 21 筆 → 20 個報酬,+ln1.01 / -ln1.01 交替,平均 0
        want = math.log(1.01) * math.sqrt(245) * 100
        self.assertAlmostEqual(P.realized_vol(xs, 20), want, places=6)

    def test_too_short_returns_none(self):
        self.assertIsNone(P.realized_vol([100] * 20, 20))
        self.assertIsNone(P.realized_vol([], 20))


class TestPercentile(unittest.TestCase):
    Q = list(range(101))

    def test_bounds(self):
        self.assertEqual(P.pctile(-5, self.Q), 0.0)
        self.assertEqual(P.pctile(500, self.Q), 100.0)

    def test_exact_and_interpolated(self):
        self.assertEqual(P.pctile(50, self.Q), 50)
        self.assertAlmostEqual(P.pctile(50.5, self.Q), 50.5)

    def test_ties_take_middle(self):
        q = [i * 0.2 for i in range(20)] + [5] * 21 + [6 + i for i in range(60)]      # 第 20~40 百分位都是 5(整體仍由小到大)
        self.assertEqual(P.pctile(5, q), 30)

    def test_band_labels(self):
        self.assertEqual([P.pct_band(p) for p in (0, 5, 6, 20, 21, 50, 79, 80, 94, 95, 100)],
                         ["極低", "極低", "偏低", "偏低", "正常區間", "正常區間", "正常區間", "偏高", "偏高", "極高", "極高"])

    def test_hist_band(self):
        d = make_dist(pc=(80, 180))
        self.assertEqual(P.hist_band("pc", 170, d), 1)
        self.assertEqual(P.hist_band("pc", 90, d), -1)
        self.assertEqual(P.hist_band("pc", 130, d), 0)
        self.assertIsNone(P.hist_band("pc", 130, None))
        self.assertIsNone(P.hist_band("nope", 1, d))
        self.assertIsNone(P.hist_band("pc", None, d))


class TestPosition(unittest.TestCase):
    def base_pg(self):
        return {"version": 4, "aspects": [{"k": "trend", "label": "多頭排列"}, {"k": "risk", "label": "波動中等"}],
                "events": [], "data": {"gap60": 6.0, "vol_ratio": 84.0}}

    def test_fields_and_headline(self):
        pg = self.base_pg(); t = {"pc": {"oi_ratio_pct": 85.0}, "mtx_retail": {"ratio_pct": 20.0}, "tmf_retail": {"ratio_pct": 12.2}}
        dist = make_dist(gap60=(-10, 10), vol_ratio=(60, 140), pc=(80, 180), retail=(-30, 30, 3.0))
        P.attach_position(pg, t, dist)
        pos = {x["k"]: x for x in pg["position"]}
        self.assertEqual(set(pos), {"gap60", "vol_ratio", "pc", "retail"})
        g = pos["gap60"]
        self.assertEqual(g["p"], 80); self.assertEqual(g["band"], "偏高"); self.assertEqual(g["word"], "漲離均線")
        self.assertEqual(g["text"], "+6.0%"); self.assertEqual(g["range"], "-6.0 ~ +6.0%")
        self.assertEqual(g["range_text"], "正常 -6.0 ~ +6.0%・中位數 +0.0%")
        self.assertEqual(pos["vol_ratio"]["p"], 30); self.assertEqual(pos["vol_ratio"]["band"], "正常區間")
        self.assertEqual(pos["pc"]["p"], 5); self.assertEqual(pos["pc"]["band"], "極低"); self.assertEqual(pos["pc"]["word"], "避險少")
        self.assertEqual(pos["retail"]["value"], 16.1); self.assertEqual(pos["retail"]["years"], 3.0)
        self.assertEqual(pg["headline"], "今天:多頭排列・波動中等;4 項中 2 項偏離平常(漲離均線、避險少)")
        self.assertIn("分布資料到 2026/09/23", pg["position_note"])

    def test_headline_all_normal_and_events(self):
        pg = self.base_pg(); pg["data"] = {"gap60": 0.0}; dist = make_dist(gap60=(-10, 10))
        P.attach_position(pg, {}, dist)
        self.assertEqual(pg["headline"], "今天:多頭排列・波動中等;1 項都在正常區間")
        pg2 = self.base_pg(); pg2["data"] = {"gap60": 0.0}; pg2["events"] = [{"name": "趨勢超跌"}, {"name": "爆量長黑"}]
        P.attach_position(pg2, {}, dist)
        self.assertTrue(pg2["headline"].endswith("・⚠ 趨勢超跌、爆量長黑"))

    def test_headline_without_trend_or_risk(self):
        pg = self.base_pg(); pg["aspects"] = []; pg["data"] = {"gap60": 9.0}
        P.attach_position(pg, {}, make_dist(gap60=(-10, 10)))
        self.assertEqual(pg["headline"], "今天:1 項中 1 項偏離平常(漲離均線)")

    def test_no_dist_or_no_values(self):
        pg = self.base_pg(); P.attach_position(pg, {}, None); self.assertNotIn("position", pg)
        pg = self.base_pg(); pg["data"] = {}; P.attach_position(pg, {}, make_dist(gap60=(-10, 10))); self.assertNotIn("headline", pg)


class TestDescribe(unittest.TestCase):
    def describe(self, closes, amts=None, t_extra=None, dist=None, hist=None):
        amts = amts or [5000] * len(closes)
        chg = closes[-1] - closes[-2]
        t = day("2026/09/24", closes[-1], chg, amts[-1], **(t_extra or {})); p = day("2026/09/23", closes[-2], 0, amts[-2])
        return P.build_describe(t, p, hist or [], CFG, closes, amts, {}, None, dist)

    def test_bull_stack(self):
        cl = closes_geometric(130, 0.002)
        pg = self.describe(cl)
        tr = next(a for a in pg["aspects"] if a["k"] == "trend")
        self.assertEqual(tr["label"], "多頭排列"); self.assertEqual(tr["tone"], "bull")
        self.assertEqual(pg["data"]["ma20"], round(sum(cl[-20:]) / 20)); self.assertEqual(pg["data"]["ma120"], round(sum(cl[-120:]) / 120))
        self.assertGreater(pg["data"]["gap60"], 0); self.assertEqual(pg["events"], [])
        self.assertEqual([a["k"] for a in pg["aspects"]], ["trend"])       # 沒給籌碼 / 情緒 / 匯率 / 分布 → 只有趨勢

    def test_bear_stack_and_oversold_event(self):
        cl = closes_geometric(130, -0.008)
        pg = self.describe(cl)
        self.assertEqual(next(a for a in pg["aspects"] if a["k"] == "trend")["label"], "空頭排列")
        self.assertLessEqual(pg["data"]["gap20"], -6.0)
        self.assertEqual([e["k"] for e in pg["events"]], ["oversold"])      # 天天跌 0.8%,收盤離 20 日均線約 7.5%,超過 6% 門檻
        ev = pg["events"][0]; self.assertEqual(ev["day"], 1); self.assertTrue(ev["new"]); self.assertNotIn("history", ev)

    def test_event_counts_previous_days(self):
        cl = closes_geometric(130, -0.008)
        hist = [{"panghu": {"events": [{"k": "oversold"}]}}] * 3
        pg = self.describe(cl, hist=hist)
        self.assertEqual(pg["events"][0]["day"], 4); self.assertFalse(pg["events"][0]["new"])

    def test_surge_down_event(self):
        cl = [100.0] * 129 + [99.0]                                          # 跌 1%
        amts = [5000] * 129 + [8000]                                         # 均量的 160%
        pg = self.describe(cl, amts)
        self.assertIn("surge_down", [e["k"] for e in pg["events"]])
        self.assertEqual(pg["data"]["vol_ratio"], 160.0)

    def test_risk_aspect_needs_dist_groups(self):
        cl = [100 + (i % 2) for i in range(130)]                             # 100 / 101 交替 → 波動固定
        dist = make_dist(rv20=(5, 15, 3.0))                                    # 15.6% 的波動落在第 100 百分位 → 波動高
        dist["risk"] = {"k68": 1.27, "groups": [
            {"label": "波動低", "lo": 0, "hi": 80, "dd_med": -1.5, "dd_w10": -3.7, "p8": 1, "n_ep": 10, "ep8": 1},
            {"label": "波動高", "lo": 80, "hi": 101, "dd_med": -1.8, "dd_w10": -10.3, "p8": 14, "n_ep": 15, "ep8": 3}]}
        pg = self.describe(cl, dist=dist)
        rk = next(a for a in pg["aspects"] if a["k"] == "risk")
        self.assertEqual(rk["label"], "波動高"); self.assertEqual(rk["tone"], "hot")
        self.assertAlmostEqual(pg["data"]["rv20"], round(math.log(1.01) * math.sqrt(245) * 100, 2), places=2)
        self.assertIn("接下來 20 日常見漲跌約 ±", rk["lines"][1]); self.assertIn("獨立 15 段中 3 段", rk["lines"][2])
        self.assertIsNone(self.describe(cl).get("data", {}).get("risk_range"))   # 沒分布 → 不寫風險面向

    def test_sentiment_uses_hist_band_when_dist_given(self):
        cl = closes_geometric(130, 0.002)
        extra = {"pc": {"oi_ratio_pct": 85.0}, "mtx_retail": {"ratio_pct": 16.0}, "tmf_retail": {"ratio_pct": 16.0}}
        fixed = self.describe(cl, t_extra=extra)                             # 固定門檻:85 在 80~100 算中性,16 ≥ 5 算偏多
        self.assertEqual(next(a for a in fixed["aspects"] if a["k"] == "sentiment")["label"], "散戶偏多・P/C 中性")
        hist = self.describe(cl, t_extra=extra, dist=make_dist(pc=(80, 180), retail=(-30, 30)))   # 跟歷史比:85 極低、16 正常
        self.assertEqual(next(a for a in hist["aspects"] if a["k"] == "sentiment")["label"], "散戶中性・P/C 偏低")


def us_item(name, pct, value=100.0, ok=True, p=None, **kw):
    d = {"name": name, "value": value, "prev": value / (1 + pct / 100) if pct is not None else None, "chg": (value - value / (1 + pct / 100)) if pct is not None else None,
         "pct": pct, "date": "09/28", "src": "yahoo", "ok": ok}
    if p is not None: d["p"] = p
    d.update(kw); return d

class TestPremarket(unittest.TestCase):
    def us_weak(self):
        return {"dji": us_item("道瓊", -0.67), "spx": us_item("S&P 500", -0.77), "ixic": us_item("那斯達克", -0.92), "sox": us_item("費城半導體", -1.61, p=12),
                "tsm": us_item("台積電ADR", 0.50, 452.88), "nvda": us_item("輝達", 1.68), "aapl": us_item("蘋果", -0.78), "tsla": us_item("特斯拉", -3.94),
                "us10y": us_item("美債10Y", None, 5.24, chg=0.06), "dxy": us_item("美元指數", 0.34, 101.3), "twd": us_item("美元/台幣", 0.29, 31.87),
                "vix": us_item("VIX", -0.31, 16.02), "gold": us_item("黃金期貨", -3.38, 4175, roll_warn=True)}
    NIGHT = {"contract": "202610", "day_close": 48123.0, "night_close": 47909.0, "night_high": 48404.0, "night_low": 47783.0, "night_chg": -214.0, "night_pct": -0.44, "date": "09/24"}
    PREV = {"date": "2026/09/29", "close": 47631.96, "chg": -392.64, "pct": -0.82, "amount_yi": 8247, "foreign": -632.0, "inst_total": -782.0,
            "foreign_net_oi": -79029, "foreign_net_oi_prev": -77031, "basis": 135.04, "mtx": 16.83, "tmf": 24.16, "mtx_prev": 10.0, "tmf_prev": 9.54}   # 散戶平均 +10.7 點

    def test_full_day(self):
        d = P.describe_premarket(self.us_weak(), self.NIGHT, self.PREV, CFG)
        A = {a["k"]: a for a in d["aspects"]}
        self.assertEqual(list(A), ["us", "semi", "rates", "night", "prev"])
        self.assertEqual(A["us"]["label"], "美股偏弱・費半領跌"); self.assertEqual(A["us"]["tone"], "bear")
        self.assertIn("費城半導體 -1.61%(近 3 年 P12,偏弱的一天)", A["us"]["lines"][0])
        self.assertEqual(A["semi"]["label"], "台積 ADR 逆勢強"); self.assertEqual(A["semi"]["tone"], "bull")
        self.assertEqual(A["rates"]["label"], "利率升・美元強・台幣貶(外資偏出的環境)"); self.assertEqual(A["rates"]["tone"], "cold")
        self.assertEqual(A["night"]["label"], "夜盤小跌"); self.assertEqual(A["night"]["short"], "夜盤小跌 -0.44%")
        self.assertEqual(A["prev"]["label"], "外資現貨大賣・散戶接刀・正價差大")     # 期貨只加 1,998 口,不到 3,000 門檻
        self.assertEqual(d["headline"], "今早:美股偏弱・費半領跌・台積 ADR 逆勢強・利率升・美元強・台幣貶;夜盤小跌 -0.44%;昨收 外資現貨大賣・散戶接刀・正價差大")

    def test_night_missing_and_partial_us(self):
        us = self.us_weak(); us["sox"]["ok"] = False; us["tsm"]["ok"] = False
        d = P.describe_premarket(us, None, None, CFG); A = {a["k"]: a for a in d["aspects"]}
        self.assertNotIn("semi", A); self.assertNotIn("prev", A)
        self.assertEqual(A["us"]["label"], "美股偏弱")                               # 費半缺 → 不判領跌
        self.assertEqual(A["night"]["label"], "夜盤【缺】")
        self.assertTrue(d["headline"].endswith(";夜盤【缺】"))

    def test_roll_warn_dxy_is_ignored_and_thresholds(self):
        us = self.us_weak(); us["dxy"]["roll_warn"] = True; us["us10y"]["chg"] = 0.01
        d = P.describe_premarket(us, self.NIGHT, self.PREV, CFG); A = {a["k"]: a for a in d["aspects"]}
        self.assertEqual(A["rates"]["label"], "利率平・台幣貶")                        # 換月的美元指數不寫、1bps 算持平
        big = dict(self.NIGHT, night_pct=1.2, night_chg=580.0, night_close=48703.0)
        self.assertEqual(P.describe_premarket(us, big, None, CFG)["aspects"][-1]["label"], "夜盤大漲")   # prev=None → 夜盤是最後一個面向
        pv = dict(self.PREV, foreign=20.0, foreign_net_oi=-82031, pct=0.3, mtx=10.0, tmf=10.0, mtx_prev=22.0, tmf_prev=20.0, basis=10.0)
        self.assertEqual(P.describe_premarket(us, self.NIGHT, pv, CFG)["aspects"][-1]["label"], "外資中性・期貨加空・散戶翻空")

    def test_quantiles(self):
        self.assertIsNone(P.quantiles(list(range(100))))
        q = P.quantiles(list(range(1000)))
        self.assertEqual(len(q), 101); self.assertEqual((q[0], q[50], q[100]), (0, 500, 999))


class TestPremarketTargetDay(unittest.TestCase):       # 週末跑的盤前 = 下週一(週日中午先發)
    def test_days(self):
        import datetime as dt
        D = lambda s: dt.datetime.strptime(s, "%Y-%m-%d %H:%M")
        self.assertEqual(P.premarket_target_day(D("2026-10-04 12:00")).strftime("%Y/%m/%d"), "2026/10/05")   # 週日 → 週一
        self.assertEqual(P.premarket_target_day(D("2026-10-03 09:00")).strftime("%Y/%m/%d"), "2026/10/05")   # 週六 → 週一
        self.assertEqual(P.premarket_target_day(D("2026-10-05 07:30")).strftime("%Y/%m/%d"), "2026/10/05")   # 週一 → 當天(同日已發就略過)
        self.assertEqual(P.premarket_target_day(D("2026-10-02 07:30")).strftime("%Y/%m/%d"), "2026/10/02")   # 平日 → 當天

class TestClaudeNewsInstruction(unittest.TestCase):    # *_claude.txt 第二行:提醒 Claude 先上網查時事
    def test_text(self):
        pre, post = P.claude_news_instruction("pre", "2026/10/05"), P.claude_news_instruction("post", "2026/10/05")
        for x in (pre, post):
            self.assertTrue(x.startswith("【給 Claude】"))
            self.assertIn("上網查", x); self.assertIn("不要猜", x); self.assertIn("來源與時間", x)
        self.assertIn("美股", pre); self.assertIn("2026/10/05 台股盤中到收盤後", post)

class TestEventHistoryText(unittest.TestCase):
    def test_text(self):
        self.assertEqual(P.event_history_text({}), "歷史上沒有同類事件紀錄")
        s = P.event_history_text({"n": 9, "up20": 5, "down20": 4, "median20": 0.014, "worst_dd20": -0.167, "in_bear": {"n": 3, "up20": 0, "down20": 3}})
        self.assertEqual(s, "歷史 9 次:之後 20 日 5 漲 4 跌、中位數 +1.4%,20 日內最深再跌 -16.7%;其中發生在空頭排列時 3 次:0 漲 3 跌")


if __name__ == "__main__":
    unittest.main()
