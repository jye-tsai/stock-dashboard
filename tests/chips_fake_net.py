# 測試用假網路:把 fetch_all / premarket 的 requests.get / post 換成讀 tests/fixtures/chips 的檔案(不連期交所 / 證交所)。
# mode 可模擬證交所被擋:前 n 次回 HTML、之後才回 JSON。
import os, json
FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "chips")

class Resp:
    def __init__(self, body, status=200):
        self.content = body if isinstance(body, bytes) else body.encode("utf-8")
        self.text = self.content.decode("utf-8", "replace"); self.status_code = status; self.ok = status < 400
    def json(self): return json.loads(self.text)
    def raise_for_status(self):
        if not self.ok: raise RuntimeError(f"HTTP {self.status_code}")

def _file(name):
    with open(os.path.join(FX, name), "rb") as f: return f.read()

class FakeNet:
    def __init__(self, blocked=0, not_ready=False):
        self.blocked = blocked; self.not_ready = not_ready; self.calls = []
    def post(self, url, data=None, **kw):
        self.calls.append(("POST", url.rsplit("/", 1)[-1], (data or {}).get("commodity_id") or (data or {}).get("commodityId")))
        if url.endswith("futContractsDateDown"): return Resp(_file("futContracts_notready.csv" if self.not_ready else "futContracts.csv"))
        if url.endswith("futDataDown"): return Resp(_file(f"futData_{data['commodity_id']}.csv"))
        if url.endswith("callsAndPutsDateDown"): return Resp(_file("callsAndPuts.csv"))
        if url.endswith("pcRatioDown"): return Resp(_file("pcRatio.csv"))
        raise AssertionError("未預期的 POST " + url)
    def get(self, url, params=None, **kw):
        name = url.rstrip("/").rsplit("/", 1)[-1]
        self.calls.append(("GET", name, None))
        if name in ("FMTQIK", "BFI82U", "MI_MARGN"):
            if self.blocked > 0:
                self.blocked -= 1
                return Resp("<html>請稍後再試</html>")
            return Resp(_file(f"twse_{name}.json"))
        raise AssertionError("未預期的 GET " + url)
