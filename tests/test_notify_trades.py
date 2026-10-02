# 15:40 推播「今日進出」:比對前一交易日 history 張數快照(chips/scripts/notify.py trades_lines)
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "chips", "scripts"))
import notify

TODAY = "2026-10-02"
def data(prev_lots, holdings, real_prev=472542, real_now=480777, costs=None):
    prev = {"date": "2026-10-01", "real": real_prev, "lots": prev_lots}
    if costs: prev["costs"] = costs
    return {"已實現損益": real_now, "holdings": holdings, "history": [prev, {"date": TODAY, "real": real_now}]}

class Trades(unittest.TestCase):
    def setUp(self): notify.today_tpe = lambda: TODAY
    def test_today_real_case(self):          # 2026-10-02 實況:00891 10→5、新買 00904 5 張 @44
        L = notify.trades_lines(data({"00891": 10, "0050": 1}, [
            {"code": "00891", "name": "中信關鍵半導體", "lots": 5, "cost": 34.29},
            {"code": "0050", "name": "元大台灣50", "lots": 1, "cost": 102.91},
            {"code": "00904", "name": "台新臺灣半導體30", "lots": 5, "cost": 44}]))
        self.assertEqual(L, ["── 今日進出 ──", "賣 00891 中信關鍵半導體 5 張（剩 5 張）",
                             "買 00904 台新臺灣半導體30 5 張 @44（220,000）", "今日已實現 +8,235"])
    def test_buy_only_no_realized_line(self):
        L = notify.trades_lines(data({}, [{"code": "00904", "name": "X", "lots": 5, "cost": 44}], real_now=472542))
        self.assertNotIn("今日已實現", "\n".join(L))
    def test_add_to_position_price_from_avg(self):   # 1 張 @100 加碼 1 張 → 均價 110 → 買進價 120
        L = notify.trades_lines(data({"A": 1}, [{"code": "A", "name": "A", "lots": 2, "cost": 110}], costs={"A": 100}))
        self.assertEqual(L[1], "買 A A 1 張 @120（120,000）（共 2 張）")
    def test_sell_all_and_odd_lots(self):
        L = notify.trades_lines(data({"A": 2.33}, [{"code": "A", "name": "A", "lots": 0, "cost": 1}]))
        self.assertEqual(L[1], "賣 A A 2.33 張（全部）")
    def test_no_snapshot_or_no_change(self):
        self.assertEqual(notify.trades_lines({"holdings": [], "history": [{"date": "2026-10-01"}]}), [])
        self.assertEqual(notify.trades_lines(data({"A": 1}, [{"code": "A", "lots": 1}])), [])

if __name__ == "__main__": unittest.main()
