"""chips/scripts/notify.py 的 decode_data_json 要解得開 scripts/codec.js 寫的 v2(跨語言對拍):
用 node 跑 codec.js 把一份假資料編成 v2,再用 Python 解回來比對。沒有 node 或 cryptography 就跳過。"""
import json, os, shutil, subprocess, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "chips", "scripts"))

SAMPLE = {
    "title": "測試", "updated": "2026-10-31", "priceUpdated": "2026-10-31 13:25",
    "fees": {"feeRate": 0.001425, "feeDiscount": 0.4, "taxRates": {"個股": 0.003}},
    "holdings": [
        {"type": "個股", "code": "2330", "name": "台積電", "cost": 100, "price": 110, "lots": 1, "priceTime": "2026-10-31 13:25", "prevClose": 108, "yahooSym": ".TW"},
        {"type": "ETF", "code": "0050", "name": "元大台灣50", "cost": 50, "price": 0, "lots": 2},
    ],
    "已實現損益": 1, "股息收入": 2, "alerts": {},
    "history": [{"date": "2026-10-30", "mv": 1000, "cost": 900, "un": 100, "real": 1, "div": 2, "ret": 103, "prices": {"2330": 100}, "lots": {"2330": 1}, "costs": {"2330": 100}},
                {"date": "2026-10-31", "mv": 1010, "cost": 900, "un": 110, "real": 1, "div": 2, "ret": 113, "prices": {"2330": 110}, "lots": {"2330": 1}, "costs": {"2330": 100}}],
}


class CodecCrossLang(unittest.TestCase):
    def test_python_decodes_node_v2(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("沒有 node")
        try:
            import cryptography  # noqa: F401
        except ImportError:
            self.skipTest("沒有 cryptography")
        import notify
        js = ("import { createRequire } from 'node:module';"
              "const C = createRequire(import.meta.url)('./scripts/codec.js');"
              "let s=''; process.stdin.on('data', d => s += d); process.stdin.on('end', async () => process.stdout.write(C.stringify(await C.encode(JSON.parse(s)))));")
        r = subprocess.run([node, "--input-type=module", "-e", js], cwd=ROOT, input=json.dumps(SAMPLE, ensure_ascii=False), capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        raw = json.loads(r.stdout)
        self.assertEqual(raw["enc"], 2)
        self.assertNotIn("lots", json.dumps(raw["quotes"]))
        d = notify.decode_data_json(raw)
        self.assertEqual(d, SAMPLE)

    def test_v1_still_decodes(self):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError:
            self.skipTest("沒有 cryptography")
        import base64, os as _os
        import notify
        iv = _os.urandom(12)
        ct = AESGCM(notify.OBF_KEY).encrypt(iv, json.dumps(SAMPLE, ensure_ascii=False).encode("utf-8"), None)
        d = notify.decode_data_json({"enc": 1, "iv": base64.b64encode(iv).decode(), "ct": base64.b64encode(ct).decode()})
        self.assertEqual(d, SAMPLE)


if __name__ == "__main__":
    unittest.main()
