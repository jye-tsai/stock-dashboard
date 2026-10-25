# 台股休市判斷(chips/scripts/market_calendar.py):週末 / 手動清單 / 證交所休市日表 / 臺北市停班
# 網路一律用假的抓取函式,不打外網;頁面格式是依公開說明推的,實際格式以排程存下的 data/market_calendar.json 核對。
import os, sys, json, tempfile, unittest, datetime as dt
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "chips", "scripts"))
import market_calendar as mc

D = dt.date
def now(y, m, d, h=7, mi=20): return dt.datetime(y, m, d, h, mi)

DGPA_TPL = """<html><body><h2>天然災害停止上班及上課情形</h2>
<p>更新時間：{upd}</p>
<table><tr><th>縣市名稱</th><th>停止上班上課情形</th></tr>
<tr><td>基隆市</td><td>{kl}</td></tr>
<tr><td>臺北市</td><td>{tp}</td></tr>
<tr><td>新北市</td><td>{ntp}</td></tr></table></body></html>"""
def page(tp, upd="2026/10/22 20:05:12", kl="明天停止上班、停止上課。", ntp="明天停止上班、停止上課。"):
    return DGPA_TPL.format(upd=upd, tp=tp, kl=kl, ntp=ntp)

class ParseDate(unittest.TestCase):
    def test_formats(self):
        for s in ("1151026", "115/10/26", "20261026", "2026/10/26", "2026-10-26"):
            self.assertEqual(mc.parse_date(s), D(2026, 10, 26), s)
    def test_bad(self):
        for s in (None, "", "abc", "2026/13/40", "115/02/30"): self.assertIsNone(mc.parse_date(s), s)

class TwseRows(unittest.TestCase):
    def test_skip_trading_days(self):
        rows = [{"Name": "光復節補假", "Date": "1151026", "Weekday": "一", "Description": "依規定放假1日"},
                {"Name": "國曆新年開始交易日", "Date": "1160104", "Description": "國曆新年開始交易"},
                {"Name": "農曆春節前最後交易日", "Date": "1160205", "Description": "農曆春節前最後交易"},
                {"Name": "市場無交易，僅辦理結算交割作業", "Date": "1160208", "Description": ""},
                {"Date": "bad"}, "not a dict"]
        out = mc.twse_closed_from_rows(rows)
        self.assertEqual(set(out), {D(2026, 10, 26), D(2027, 2, 8)})

class Taipei(unittest.TestCase):
    def test_tomorrow_relative_to_update_time(self):      # 前一晚 20:05 公告「明天」→ 隔天;07:20 檢查時頁面還是舊字樣也要對
        res, seg = mc.taipei_suspension(page("明天停止上班、停止上課。"))
        self.assertIn(D(2026, 10, 23), res); self.assertIn("停止上班", seg)
    def test_today(self):
        res, _ = mc.taipei_suspension(page("今天停止上班、停止上課。", upd="2026/10/23 05:30:00"))
        self.assertIn(D(2026, 10, 23), res)
    def test_explicit_date(self):
        res, _ = mc.taipei_suspension(page("10月23日停止上班、停止上課。"))
        self.assertIn(D(2026, 10, 23), res)
    def test_normal(self):
        res, _ = mc.taipei_suspension(page("今天照常上班、照常上課。", kl="今天照常上班、照常上課。", ntp="今天照常上班、照常上課。"))
        self.assertEqual(res, {})
    def test_partial_district_not_closed(self):           # 只有山區 / 部分里停班,股市照開
        res, _ = mc.taipei_suspension(page("北投區湖田里、士林區平等里明天停止上班、停止上課。"))
        self.assertEqual(res, {})
    def test_afternoon_only_not_closed(self):
        res, _ = mc.taipei_suspension(page("今天上午照常上班、照常上課，下午停止上班、停止上課。", upd="2026/10/23 10:00:00"))
        self.assertEqual(res, {})
    def test_other_city_does_not_leak(self):              # 新北停班、台北照常 → 不算
        res, _ = mc.taipei_suspension(page("明天照常上班、照常上課。"))
        self.assertEqual(res, {})
    def test_no_taipei_row(self):
        self.assertEqual(mc.taipei_suspension("<html>無資料</html>"), ({}, ""))

class Check(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.manual = os.path.join(self.tmp, "closed_days.json")
        self.state = os.path.join(self.tmp, "market_calendar.json")
        with open(self.manual, "w", encoding="utf-8") as f:
            json.dump({"closed": {"2026/10/26": "光復節補假"}}, f, ensure_ascii=False)
    def run_check(self, day, n, twse=False, dgpa=False):
        return mc.check(day, now=n, twse=twse, dgpa=dgpa, manual_path=self.manual, state_path=self.state)

    def test_weekend(self):
        self.assertEqual(self.run_check(D(2026, 10, 24), now(2026, 10, 24))[0], True)
    def test_manual(self):
        c, why = self.run_check(D(2026, 10, 26), now(2026, 10, 25, 12, 0))
        self.assertTrue(c); self.assertIn("光復節", why)
    def test_normal_day_open(self):
        self.assertEqual(self.run_check(D(2026, 10, 27), now(2026, 10, 27)), (False, ""))
    def test_twse(self):
        rows = [{"Name": "中秋節", "Date": "1151006", "Description": "放假"}]
        c, why = self.run_check(D(2026, 10, 6), now(2026, 10, 6), twse=lambda: rows)
        self.assertTrue(c); self.assertIn("中秋節", why)
    def test_twse_fail_uses_cache(self):              # 證交所抓不到 → 用上次存的快取
        rows = [{"Name": "中秋節", "Date": "1151006", "Description": "放假"}]
        self.run_check(D(2026, 10, 5), now(2026, 10, 5), twse=lambda: rows)
        def boom(): raise ConnectionError("down")
        c, _ = self.run_check(D(2026, 10, 6), now(2026, 10, 6), twse=boom)
        self.assertTrue(c)
    def test_typhoon(self):
        c, why = self.run_check(D(2026, 10, 23), now(2026, 10, 23), dgpa=lambda: page("明天停止上班、停止上課。"))
        self.assertTrue(c); self.assertIn("台北市停止上班", why)
    def test_dgpa_fail_means_open(self):              # 停班頁抓不到 → 當作有開市(寧可多發,不漏發)
        def boom(): raise TimeoutError("slow")
        c, _ = self.run_check(D(2026, 10, 23), now(2026, 10, 23), dgpa=boom)
        self.assertFalse(c)
        with open(self.state, encoding="utf-8") as f: st = json.load(f)
        self.assertIn("失敗", st["last_check"]["sources"]["dgpa"])
    def test_dgpa_only_for_today_tomorrow(self):      # 一週後的日子不看停班頁
        called = []
        self.run_check(D(2026, 10, 30), now(2026, 10, 23), dgpa=lambda: called.append(1) or page("明天停止上班。"))
        self.assertEqual(called, [])

class RepoManualFile(unittest.TestCase):
    def test_repo_closed_days_json_valid(self):          # 使用者在網頁手動編輯,格式壞掉要立刻紅燈
        p = os.path.join(os.path.dirname(__file__), "..", "chips", "closed_days.json")
        with open(p, encoding="utf-8") as f: j = json.load(f)
        for k in j["closed"]: self.assertIsNotNone(mc.parse_date(k), k)


class PremarketSkips(unittest.TestCase):
    def test_main_returns_before_fetch_when_closed(self):  # 休市:不抓美股、不寫 premarket_*.json
        import premarket
        orig_check, orig_fetch = mc.check, premarket.fetch_raw
        mc.check = lambda *a, **k: (True, "測試休市")
        premarket.fetch_raw = lambda *a, **k: self.fail("休市不該抓資料")
        try: self.assertIsNone(premarket.main())
        finally: mc.check, premarket.fetch_raw = orig_check, orig_fetch

if __name__ == "__main__":
    unittest.main()
