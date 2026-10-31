"""backtest.py 的 series 拆年檔:拆 → 合要等於原本;只有該年的元素;write_series_files 會清掉不在清單裡的舊年檔。"""
import json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "chips", "scripts"))
import backtest as B


def sample():
    dates = ["2024/12/30", "2024/12/31", "2025/01/02", "2025/01/03", "2026/01/05"]
    n = len(dates)
    return {"dates": dates, "close": [1.0 * i for i in range(n)], "temp": list(range(n)), "pos": [50] * n,
            "v3": {"temp": [None] * n, "pos": list(range(n)), "regime": ["多頭", None, "空頭", "空頭", None]},
            "eq": {"a": [1, 1.1, 1.2, 1.3, 1.4], "b": [1, 0.9, 0.8, 0.7, 0.6]}}


class SeriesSplit(unittest.TestCase):
    def test_split_then_merge_equals_original(self):
        s = sample()
        parts = B.split_series_by_year(s)
        self.assertEqual(list(parts), ["2024", "2025", "2026"])
        self.assertEqual(parts["2024"]["dates"], ["2024/12/30", "2024/12/31"])
        self.assertEqual(parts["2025"]["eq"]["a"], [1.2, 1.3])
        self.assertEqual(parts["2026"]["v3"]["regime"], [None])
        self.assertEqual(B.merge_series_parts([parts[y] for y in sorted(parts)]), s)

    def test_v3_none_kept(self):
        s = sample(); s["v3"] = None
        parts = B.split_series_by_year(s)
        self.assertIsNone(parts["2025"]["v3"])
        self.assertEqual(B.merge_series_parts([parts[y] for y in sorted(parts)]), s)

    def test_write_prunes_old_years(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "series")); open(os.path.join(d, "series", "2019.json"), "w").write("{}")
            files = B.write_series_files(d, sample())
            self.assertEqual(files, ["series/2024.json", "series/2025.json", "series/2026.json"])
            self.assertEqual(sorted(os.listdir(os.path.join(d, "series"))), ["2024.json", "2025.json", "2026.json"])
            self.assertEqual(json.load(open(os.path.join(d, "series", "2026.json")))["dates"], ["2026/01/05"])


if __name__ == "__main__":
    unittest.main()
