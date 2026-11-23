# 大盤日 KD 與反彈滿足區提醒(chips/scripts/kd.py)＋證交所高低月表解析;不連外。
import os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "chips", "scripts")); sys.path.insert(0, HERE)
import kd as KD
try:
    import pandas, requests  # noqa: F401
    HAVE = True
except ImportError:
    HAVE = False

CFG = dict(KD.DEFAULT)

def flat(n, c): return [c + 100] * n, [c - 100] * n, [c] * n

class KdCalc(unittest.TestCase):
    def test_formula(self):
        # 9 天:最高 110、最低 90、最後收 100 → RSV 50 → K = D = 50;再一天收在最高 110 → RSV 100
        h, l, c = [110] * 9, [90] * 9, [100] * 9
        self.assertEqual(KD.kd_series(h, l, c), [(50.0, 50.0)])
        k, d = KD.kd_series(h + [110], l + [90], c + [110])[-1]
        self.assertAlmostEqual(k, 50 * 2 / 3 + 100 / 3); self.assertAlmostEqual(d, 50 * 2 / 3 + k / 3)
        self.assertEqual(KD.kd_series([1] * 5, [1] * 5, [1] * 5), [])

    def test_too_short_or_disabled(self):
        self.assertIsNone(KD.evaluate(*flat(20, 36000), CFG))
        self.assertIsNone(KD.evaluate(*flat(40, 36000), dict(CFG, enabled=False)))

    def test_far_from_zone_no_alert(self):
        h, l, c = flat(30, 34000)
        for i in range(10):                                   # 連漲到 36,800:K 很高但離滿足區還遠 → 不提醒
            v = 34000 + (i + 1) * 280; h.append(v + 50); l.append(v - 200); c.append(v)
        r = KD.evaluate(h, l, c, CFG)
        self.assertGreaterEqual(r["k"], 80); self.assertFalse(r["near"]); self.assertIsNone(r["stage"]); self.assertIsNone(r["alert"])
        self.assertIn("還差", r["text"])

    def rally(self, top):
        h, l, c = flat(30, 35000)
        step = (top - 35000) / 12
        for i in range(12):
            v = 35000 + (i + 1) * step; h.append(v + 50); l.append(v - 200); c.append(v)
        return h, l, c

    def test_hot_near_zone(self):
        r = KD.evaluate(*self.rally(39000), CFG)             # 39,000 ≥ 39,546×0.98 = 38,755 → 接近;K ≥ 80
        self.assertTrue(r["near"]); self.assertEqual(r["stage"], "hot"); self.assertIn("反彈提醒①", r["alert"])
        r = KD.evaluate(*self.rally(40000), CFG)
        self.assertIn("已進滿足區", r["text"])

    def test_death_cross_after_reaching_zone(self):
        h, l, c = self.rally(40000)
        for v in (39300, 38600):                              # 高檔回落兩天 → K 跌破 D;收盤已掉回門檻下,但 5 日內到過
            h.append(v + 300); l.append(v - 100); c.append(v)
            r = KD.evaluate(h, l, c, CFG)
            if r["stage"] == "cross": break
        self.assertEqual(r["stage"], "cross"); self.assertIn("反彈提醒②", r["alert"]); self.assertLess(r["k"], r["d"])

    def test_cfg_file(self):
        cfg = KD.load_cfg(os.path.join(HERE, "..", "chips", "kd_alert.json"))
        self.assertEqual((cfg["zone_lo"], cfg["zone_hi"], cfg["k_hot"]), (39546, 40991, 80))
        self.assertEqual(KD.load_cfg("/no/such/file")["zone_lo"], 39546)

@unittest.skipUnless(HAVE, "需要 pandas / requests")
class KdFetch(unittest.TestCase):
    def setUp(self):
        import fetch_all as fa, common as C
        from chips_fake_net import FakeNet
        self.fa = fa; self._orig = (fa.requests.get, C.time.sleep, fa.time.sleep)
        fa.requests.get = FakeNet().get; C.time.sleep = fa.time.sleep = lambda s: None; fa._OH.clear()
    def tearDown(self):
        import common as C
        self.fa.requests.get, C.time.sleep, self.fa.time.sleep = self._orig; self.fa._OH.clear()
    def test_month_ohlc(self):
        m = self.fa._month_ohlc(2026, 10)
        self.assertEqual(m["2026/10/02"], (48520.3, 48300.4, 48475.74))
    def test_missing_month_gives_none(self):
        self.assertIsNone(self.fa.kd_live({"date": "2026/10/02"}))    # 9 月抓不到 → 不算,不拿殘缺資料算

if __name__ == "__main__":
    unittest.main()
