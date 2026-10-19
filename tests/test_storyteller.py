# -*- coding: utf-8 -*-
"""籌碼站說書人(chips/scripts/storyteller.py):只用當日資料的數字、同一天同一則、兩個世界、設定檔開關、缺欄位不當掉"""
import os, sys, json, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "chips", "scripts"))
import storyteller as S

T = {"date": "2026/10/16", "inst": {"外資": -461.47}, "insight": {"foreign": {"run": 8, "side": "連賣"}},
     "mtx_retail": {"ratio_pct": 25.71}, "txf": {"外資": {"net": -93675}}, "prev": {"txf": {"外資": {"net": -97582}}},
     "basis": 130.74, "pc": {"oi_ratio_pct": 67.6}}

class TestStoryteller(unittest.TestCase):
    def test_numbers_and_determinism(self):
        a, b = S.chips_story(T, "奇幻"), S.chips_story(T, "奇幻")
        self.assertEqual(a, b)
        txt = "\n".join(a)
        for s in ("461 億", "連 8 日賣", "+25.7%", "3,907", "-93,675", "131", "67.6"):
            self.assertIn(s, txt)
        self.assertIn("靈石", "\n".join(S.chips_story(T, "修仙")))

    def test_missing_fields(self):
        self.assertGreaterEqual(len(S.chips_story({"date": "2026/10/16"}, "奇幻")), 2)   # 只剩開場 + 收尾
        self.assertEqual(S.chips_story(T, "關閉"), [])

    def test_world_config(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "story.json")
            for w, want in (("修仙", "修仙"), ("關閉", None)):
                with open(p, "w", encoding="utf-8") as f: json.dump({"world": w}, f, ensure_ascii=False)
                self.assertEqual(S.world_for("2026/10/16", p), want)
            with open(p, "w", encoding="utf-8") as f: json.dump({"world": "隨機"}, f, ensure_ascii=False)
            self.assertIn(S.world_for("2026/10/16", p), S.WORLDS)
            self.assertIn(S.world_for("x", os.path.join(d, "nope.json")), S.WORLDS)   # 沒設定檔 = 隨機

    def test_fail_lines(self):
        self.assertTrue(S.fail_lines("奇幻", "d")[0].startswith("☠"))
        self.assertEqual(S.fail_lines(None), [])

if __name__ == "__main__":
    unittest.main()
