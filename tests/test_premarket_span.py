# 盤前:連假時美股改成「台股前收以來累計」、期貨 / 外匯去掉盤中即時價(chips/scripts/premarket.py us_span / trim_live / summarize)
# 情境:10/22(四)台股收盤後颱風假 + 光復節補假,10/27(二)才開;美股中間開了 10/22、10/23、10/26 三天。
import os, sys, unittest, datetime as dt
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "chips", "scripts"))
import premarket as pm

D = dt.date
def ts(y, m, d, h=13, mi=30): return dt.datetime(y, m, d, h, mi, tzinfo=dt.timezone.utc).timestamp()

def eq_bars(closes):                       # 股票:Yahoo 日線時間戳 = 美東開盤 13:30 UTC
    days = [D(2026, 10, x) for x in (19, 20, 21, 22, 23, 26)]
    return [{"ts": ts(d.year, d.month, d.day), "d": d, "c": c} for d, c in zip(days, closes)]

def raw(key, bars, kind="idx", nd=2, name=None):
    return {"key": key, "name": name or key, "nd": nd, "kind": kind, "src": "yahoo", "bars": bars}

SOX = [11316.34, 11283.81, 11505.56, 11400.0, 11200.0, 11000.0]   # 10/21 收 11505.56,之後三天

class Span(unittest.TestCase):
    def test_holiday_three_sessions(self):
        span, ref = pm.us_span({"spx": raw("spx", eq_bars(SOX))}, D(2026, 10, 22))
        self.assertEqual(span, 3); self.assertEqual(ref["date"], D(2026, 10, 26))
    def test_normal_day_one_session(self):           # 平常:台股前收 10/26 → 美股只有 10/26 一天
        self.assertEqual(pm.us_span({"spx": raw("spx", eq_bars(SOX))}, D(2026, 10, 26))[0], 1)
    def test_monday_premarket_from_friday(self):     # 週日中午先發週一:台股前收週五 10/23,美股最後也是 10/23
        b = eq_bars(SOX)[:-1]
        self.assertEqual(pm.us_span({"spx": raw("spx", b)}, D(2026, 10, 23))[0], 1)
    def test_no_since(self):
        self.assertEqual(pm.us_span({"spx": raw("spx", eq_bars(SOX))}, None)[0], 1)

class Summarize(unittest.TestCase):
    def test_cumulative_and_sessions(self):
        r = pm.summarize(raw("sox", eq_bars(SOX), name="費城半導體"), span=3)
        self.assertEqual((r["value"], r["prev"], r["from"], r["date"], r["span"]), (11000.0, 11505.56, "10/21", "10/26", 3))
        self.assertAlmostEqual(r["pct"], round((11000 / 11505.56 - 1) * 100, 2))
        self.assertEqual([x["date"] for x in r["sessions"]], ["10/22", "10/23", "10/26"])
        self.assertAlmostEqual(r["sessions"][0]["pct"], round((11400 / 11505.56 - 1) * 100, 2))
    def test_single_day_unchanged(self):              # 平常日:跟改版前一樣,最後兩根比
        r = pm.summarize(raw("sox", eq_bars(SOX)), span=1)
        self.assertEqual((r["prev"], r["pct"]), (11200.0, round((11000 / 11200 - 1) * 100, 2)))
        self.assertNotIn("span", r); self.assertNotIn("sessions", r)
    def test_missing(self):
        self.assertFalse(pm.summarize(raw("x", None), span=3)["ok"])

class TrimLive(unittest.TestCase):
    REF = {"date": D(2026, 10, 26), "close_ts": ts(2026, 10, 26, 21, 30)}
    def fut(self):                                    # 期貨:最後一根是台北 07:20(美東前一晚 19:20)抓到的盤中即時價
        b = [{"ts": ts(2026, 10, d, 4, 0), "d": D(2026, 10, d), "c": c} for d, c in ((22, 100.0), (23, 101.0), (26, 102.0))]
        return b + [{"ts": ts(2026, 10, 26, 23, 20), "d": D(2026, 10, 26), "c": 104.5}]
    def test_drop_live_bar(self):
        r = pm.summarize(raw("brent", self.fut(), kind="fut", name="布蘭特"), span=1, ref=self.REF)
        self.assertEqual((r["value"], r["prev"]), (102.0, 101.0))
        self.assertEqual(r["live"]["value"], 104.5)
    def test_equity_never_trimmed(self):
        b = eq_bars(SOX)
        self.assertEqual(pm.trim_live(raw("sox", b), self.REF)[0], b)
    def test_twd_trimmed(self):
        b = self.fut()
        self.assertEqual(len(pm.trim_live(raw("twd", b, kind="px"), self.REF)[0]), 3)
    def test_stooq_by_date(self):                     # Stooq 沒有時間戳:日期晚於美股最後交易日的那根拿掉
        b = [{"ts": None, "d": D(2026, 10, d), "c": c} for d, c in ((22, 1.0), (23, 2.0), (26, 3.0), (27, 9.0))]
        kept, dropped = pm.trim_live(raw("gold", b, kind="fut"), self.REF)
        self.assertEqual((kept[-1]["c"], dropped["c"]), (3.0, 9.0))
    def test_no_ref_no_trim(self):
        b = self.fut()
        self.assertEqual(len(pm.trim_live(raw("brent", b, kind="fut"), None)[0]), 4)

if __name__ == "__main__":
    unittest.main()
