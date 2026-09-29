# -*- coding: utf-8 -*-
"""圖卡(chips/scripts/render_card.py):用假資料畫盤前 / 盤後兩張,驗尺寸、檔名、30 天清理。沒中文字型也能跑(只驗版面不當掉)。"""
import os, sys, tempfile, datetime as dt, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "chips", "scripts"))
try:
    import PIL  # noqa: F401
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False
import render_card as R

POST = {"date": "2026/09/29", "generated_at": "2026-09-29T15:41:40", "missing": ["margin"],
        "index": {"close": 47631.96, "chg": -392.64, "amount_yi": 8247}, "prev": {"index": {"close": 48024.6}},
        "panghu": {"headline": "今天:多頭排列・波動中等;8 項中 1 項偏離平常(避險少)",
                   "aspects": [{"k": "trend", "name": "趨勢", "label": "多頭排列", "tone": "bull", "lines": ["收盤 47,632:20 日均 46,821(+1.7%)"]},
                               {"k": "risk", "name": "風險", "label": "波動中等", "tone": "neutral", "lines": ["近 20 日實際波動 16.8%"]}],
                   "position": [{"k": "pc", "name": "P/C(OI)", "text": "75.3%", "p": 3, "years": 9.9, "range": "98.0 ~ 141.7%"},
                                {"k": "retail", "name": "散戶多空比", "text": "+20.5%", "p": 71, "years": 3.0, "range": "-9.4 ~ +25.0%"}],
                   "events": [{"name": "趨勢超跌", "text": "收盤低於 20 日均 6.5%", "history_text": "歷史 9 次:之後 20 日 5 漲 4 跌"}]}}
PRE = {"date": "2026/09/30", "generated_at": "2026-09-30T07:31:02", "missing": [],
       "night": {"night_close": 47909.0, "night_chg": -214.0, "night_pct": -0.44},
       "describe": {"headline": "今早:美股偏弱・費半領跌;夜盤小跌 -0.44%", "note": "只描述盤前現況",
                    "aspects": [{"k": "us", "name": "美股", "label": "美股偏弱・費半領跌", "tone": "bear", "lines": ["道瓊 -0.67%、S&P 500 -0.77%" * 6, "VIX 16"]}]}}


@unittest.skipUnless(HAVE_PIL, "需要 Pillow")
class TestRender(unittest.TestCase):
    def test_post_and_pre(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            p = R.render_post(POST, d); q = R.render_pre(PRE, d)
            self.assertEqual(os.path.basename(p), "card_post_20260929.png")
            self.assertEqual(os.path.basename(q), "card_pre_20260930.png")
            for f in (p, q):
                w, h = Image.open(f).size
                self.assertEqual(w, 1080); self.assertGreaterEqual(h, 1350); self.assertLess(h, 3200)

    def test_missing_fields_do_not_crash(self):
        with tempfile.TemporaryDirectory() as d:
            R.render_post({"date": "2026/09/29"}, d); R.render_pre({"date": "2026/09/30", "missing": ["台指期夜盤"]}, d)
            self.assertEqual(sorted(os.listdir(d)), ["card_post_20260929.png", "card_pre_20260930.png"])


class TestCleanup(unittest.TestCase):
    def test_only_old_cards_removed(self):
        with tempfile.TemporaryDirectory() as d:
            for fn in ("card_post_20260801.png", "card_pre_20260830.png", "card_post_20260929.png", "20260801_spf_a_p1.png", "card_post_latest.png"):
                open(os.path.join(d, fn), "wb").close()
            gone = R.cleanup(d, 30, today=dt.date(2026, 9, 29))
            self.assertEqual(sorted(gone), ["card_post_20260801.png"])        # 08/30 剛好 30 天內留著;永豐圖、非日期檔不碰
            self.assertEqual(len(os.listdir(d)), 4)


if __name__ == "__main__":
    unittest.main()
