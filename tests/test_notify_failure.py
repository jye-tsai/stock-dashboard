# -*- coding: utf-8 -*-
"""失敗通知(chips/scripts/notify_failure.py)+ 圖片壓縮(common.shrink_png)"""
import os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "chips", "scripts"))
import notify_failure as F
from common import shrink_png

class FakeResp:
    def __init__(self, j): self._j = j
    def json(self): return self._j

class TestNotifyFailure(unittest.TestCase):
    def test_failed_steps(self):
        jobs = {"jobs": [{"steps": [{"name": "抓資料（盤後）", "conclusion": "success"},
                                    {"name": "Commit", "conclusion": "failure"},
                                    {"name": "LINE 通知", "conclusion": "skipped"}]}]}
        self.assertEqual(F.failed_steps(lambda *a, **k: FakeResp(jobs), "o/r", "1", "t"), ["Commit"])

    def test_failed_steps_api_error(self):
        def boom(*a, **k): raise OSError("down")
        self.assertEqual(F.failed_steps(boom, "o/r", "1", "t"), [])

    def test_message(self):
        t = F.message("籌碼 盤後 cronjob", ["Commit"], "https://github.com/o/r/actions/runs/1")
        self.assertIn("籌碼 盤後 cronjob", t); self.assertIn("失敗步驟:Commit", t); self.assertTrue(t.endswith("/runs/1"))
        self.assertIn("查不到", F.message("x", [], ""))

class TestShrinkPng(unittest.TestCase):
    def test_shrink_keeps_size_and_palette(self):
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            self.skipTest("沒有 Pillow")
        im = Image.new("RGB", (400, 300), "#1b2a4e"); d = ImageDraw.Draw(im)
        for i in range(0, 400, 7): d.line([(i, 0), (400 - i, 300)], fill=(i % 255, 200, 90), width=2)
        with tempfile.TemporaryDirectory() as tmp:
            raw, small = os.path.join(tmp, "raw.png"), os.path.join(tmp, "small.png")
            im.save(raw); shrink_png(im, small)
            out = Image.open(small)
            self.assertEqual(out.size, (400, 300)); self.assertEqual(out.mode, "P")
            self.assertLessEqual(os.path.getsize(small), os.path.getsize(raw))
            shrink_png(raw)                                   # 路徑版:覆蓋原檔
            self.assertEqual(Image.open(raw).mode, "P")

if __name__ == "__main__":
    unittest.main()
