# 盤前 06:40 早班保險(chips/scripts/panghu.py premarket_early_hold):07:00 前缺夜盤 / 美股主指 → 不發 LINE,留給 07:20 備援
import os, sys, unittest, datetime as dt
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "chips", "scripts"))
from panghu import premarket_early_hold as hold

def T(h, m): return dt.datetime(2026, 11, 2, h, m)
US_OK = {k: {"name": n, "ok": True} for k, n in (("dji", "道瓊"), ("spx", "S&P 500"), ("sox", "費城半導體"), ("tsm", "台積電ADR"))}
NIGHT = {"night_close": 45926.0}

class Early(unittest.TestCase):
    def test_all_ready_sends(self):
        self.assertIsNone(hold(T(6, 41), NIGHT, US_OK))
    def test_night_missing_holds(self):
        self.assertEqual(hold(T(6, 41), None, US_OK), "台指期夜盤")
    def test_us_missing_holds(self):
        us = dict(US_OK); us["sox"] = {"name": "費城半導體", "ok": False}
        self.assertEqual(hold(T(6, 41), NIGHT, us), "費城半導體")
    def test_after_seven_sends_anyway(self):           # 07:20 備援:缺也發(附需手動補),不然整天沒 LINE
        self.assertIsNone(hold(T(7, 21), None, US_OK))
        self.assertIsNone(hold(T(7, 0), None, US_OK))
    def test_sunday_noon_unaffected(self):
        self.assertIsNone(hold(T(12, 5), None, US_OK))
    def test_minor_missing_does_not_hold(self):        # 蘋果 / 油金缺不算,只看夜盤與主指
        us = dict(US_OK); us["aapl"] = {"name": "蘋果", "ok": False}; us["brent"] = {"name": "布蘭特", "ok": False}
        self.assertIsNone(hold(T(6, 41), NIGHT, us))
    def test_custom_end(self):
        self.assertIsNone(hold(T(6, 41), None, US_OK, end=630))

if __name__ == "__main__":
    unittest.main()
