# 籌碼站抓取 / 共用工具測試:用 tests/chips_fake_net.py 的假網路餵期交所 / 證交所格式的檔案(tests/fixtures/chips),不連外。
# 期望值 = 2026-10-04 重構前舊程式對同一組檔案的輸出(重構後必須一模一樣)。
import os, sys, json, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "chips", "scripts")); sys.path.insert(0, HERE)
try:
    import pandas, requests  # noqa: F401
    HAVE = True
except ImportError:
    HAVE = False
import common as C
from chips_fake_net import FakeNet

D = "2026/10/02"

@unittest.skipUnless(HAVE, "需要 pandas / requests")
class FetchParsing(unittest.TestCase):
    def setUp(self):
        import fetch_all as fa, premarket as pm
        self.fa, self.pm = fa, pm
        self.net = FakeNet()
        self._orig = (fa.requests.post, fa.requests.get, pm.requests.post, C.time.sleep, fa.time.sleep)
        fa.requests.post = self.net.post; fa.requests.get = self.net.get; pm.requests.post = self.net.post
        C.time.sleep = fa.time.sleep = lambda s: None
    def tearDown(self):
        fa, pm = self.fa, self.pm
        fa.requests.post, fa.requests.get, pm.requests.post, C.time.sleep, fa.time.sleep = self._orig

    def test_futures_oi(self):
        fa = self.fa; df = fa.taifex_fut(D)
        self.assertTrue(fa.fut_ready(df))
        self.assertEqual(fa.fut_oi(df, "臺股期貨")["外資"], {"long": 20000, "short": 45678, "net": -25678, "day_net": -1500})
        self.assertEqual(fa.fut_oi(df, "微型臺指期貨")["自營商"], {"long": 1000, "short": 900, "net": 100, "day_net": 100})
        self.assertEqual(fa.taifex_market_oi(D, "MTX"), 59000)

    def test_not_ready(self):
        self.fa.requests.post = FakeNet(not_ready=True).post
        self.assertFalse(self.fa.fut_ready(self.fa.taifex_fut(D)))

    def test_tx_and_night_share_parser(self):
        self.assertEqual(self.fa.taifex_tx_close(D), {"contract": "202610", "close": 48671.0, "night_close": 48475.0})
        n = self.pm.taifex_night(D)
        self.assertEqual((n["day_close"], n["night_close"], n["night_high"], n["night_low"], n["night_open"], n["night_chg"], n["night_pct"]),
                         (48671.0, 48475.0, 48650.0, 48300.0, 48600.0, -196.0, -0.4))

    def test_options_pc(self):
        self.assertEqual(self.fa.taifex_opt(D)["外資"], {"call": 11500, "put": -2300})
        self.assertEqual(self.fa.taifex_pc(D), {"volume_ratio_pct": 96.15, "oi_ratio_pct": 88.24})

    def test_twse(self):
        fa = self.fa
        self.assertEqual(fa.twse_index(D), {"close": 48475.74, "chg": 122.25, "amount_yi": 9382})
        self.assertEqual(fa.twse_inst(D), {"自營": 20.26, "投信": 57.69, "外資": 26.22, "合計": 104.17})
        self.assertEqual(fa.twse_margin(D), 6351.0)

    def test_twse_blocked_then_ok(self):   # 證交所先回 2 次 HTML(被擋)→ 第 3 次才給 JSON:法人 / 融資以前會直接變「缺」
        fa = self.fa
        for f, want in ((fa.twse_inst, 104.17), (fa.twse_margin, 6351.0)):
            net = FakeNet(blocked=2); fa.requests.get = net.get
            got = f(D)
            self.assertEqual(got["合計"] if isinstance(got, dict) else got, want)
            self.assertEqual(sum(1 for c in net.calls if c[0] == "GET"), 3)

    def test_twse_blocked_too_long(self):
        self.fa.requests.get = FakeNet(blocked=5).get
        self.assertIsNone(self.fa.twse_inst(D))

    def test_load_saved_day(self):         # 前一交易日存檔完整才沿用,缺欄位 / 融資沿用 / 日期不符 → 重抓
        fa = self.fa
        with tempfile.TemporaryDirectory() as d:
            old, fa.DATA = fa.DATA, d
            try:
                base = {"date": D, "index": {"close": 1}, "missing": [], "claude_text": "x", "prev": {"date": "y"}, "spf": {"a": ["b"]}}
                C.write_json(os.path.join(d, "20261002.json"), base)
                got = fa.load_saved_day(D)
                self.assertEqual(got, {"date": D, "index": {"close": 1}, "missing": []})   # 衍生欄位都拿掉
                for bad in ({"missing": ["inst"]}, {"margin_note": "沿用"}, {"date": "2026/10/01"}):
                    C.write_json(os.path.join(d, "20261002.json"), {**base, **bad})
                    self.assertIsNone(fa.load_saved_day(D), bad)
                self.assertIsNone(fa.load_saved_day("2026/09/30"))                         # 沒檔
            finally:
                fa.DATA = old

class Common(unittest.TestCase):
    def test_atomic_write(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "latest.json")
            C.write_json(p, {"a": 1}, indent=1)
            self.assertEqual(C.read_json(p), {"a": 1})
            class Boom:                                            # 序列化到一半失敗 → 舊檔不動、不留暫存檔
                def __str__(self): raise RuntimeError("boom")
            with self.assertRaises(Exception): C.write_text(p, Boom())
            self.assertEqual(C.read_json(p), {"a": 1})
            self.assertEqual(os.listdir(d), ["latest.json"])
            self.assertIsNone(C.read_json(os.path.join(d, "none.json")))
            self.assertEqual(C.read_json(os.path.join(d, "none.json"), []), [])

    def test_get_json_retry(self):
        calls = []
        class R:
            def __init__(self, t, s=200): self.text, self.status_code = t, s
            def json(self): return json.loads(self.text)
        seq = [R("", 200), R("{}", 503), R('{"stat":"OK"}')]
        def get(url, **kw): calls.append(1); return seq.pop(0)
        old = C.time.sleep; C.time.sleep = lambda s: None
        try:
            self.assertEqual(C.get_json(get, "u", log=lambda s: None), {"stat": "OK"})
            self.assertEqual(len(calls), 3)
            def boom(url, **kw): raise ConnectionError("x")
            self.assertIsNone(C.get_json(boom, "u", tries=2, log=lambda s: None))
        finally:
            C.time.sleep = old

    @unittest.skipUnless(HAVE, "需要 pandas")
    def test_col_error_lists_columns(self):
        df = C.read_csv_text("日期,收盤價,\n2026/10/02,1,\n")
        self.assertEqual(list(df.columns), ["日期", "收盤價"])          # 行尾逗號的 Unnamed 欄拿掉
        self.assertEqual(C.col(df, "收盤", start=True), "收盤價")
        with self.assertRaises(ValueError) as e: C.col(df, "未沖銷")
        self.assertIn("實際欄位", str(e.exception)); self.assertIn("收盤價", str(e.exception))

    def test_tw_now(self):
        import datetime as dt
        n = C.tw_now(); u = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        self.assertAlmostEqual((n - u).total_seconds(), 8 * 3600, delta=5)

if __name__ == "__main__": unittest.main()
