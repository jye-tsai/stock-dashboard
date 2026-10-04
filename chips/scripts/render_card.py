# -*- coding: utf-8 -*-
"""
render_card.py ─ 把盤前 / 盤後的胖虎指標畫成一張 1080 寬的圖卡(PNG),給 LINE 傳圖與網頁「🖼 圖卡」連結用。
  python chips/scripts/render_card.py post   讀 data/latest.json            → data/card_post_YYYYMMDD.png
  python chips/scripts/render_card.py pre    讀 data/premarket_latest.json  → data/card_pre_YYYYMMDD.png
每天一張(同一天重跑會覆蓋);超過 30 天的圖卡自動刪。只描述現況,不預測、不給倉位。
字型:CARD_FONT / CARD_FONT_BOLD 環境變數 → Noto Sans CJK(GitHub 機器 apt 裝)→ 微軟正黑(本機)→ Pillow 內建(沒中文,只保證不當掉)。
另提供 card_url_when_live():等 GitHub Pages 部署到這張圖的新內容才回傳網址,給 notify*.py 傳圖用。
"""
import os, sys, json, hashlib, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.normpath(os.path.join(HERE, "..", "data"))
KEEP_DAYS = 30
W, H_MIN, M = 1080, 1350, 56                      # 寬、最小高(IG 4:5)、左右邊界

# 配色(跟籌碼站深藍卡一致)
BG, PANEL, LINE_C = "#172A52", "#1f3563", "#ffffff22"
WHITE, SUB, MUTED, GOLD = "#ffffff", "#c8cfe0", "#9fb0d6", "#FFD682"
TONE = {"bull": "#ff9b9b", "buy": "#ff9b9b", "inflow": "#ff9b9b", "bear": "#7be0a5", "sell": "#7be0a5", "outflow": "#7be0a5",
        "bull_lean": "#ffc4c4", "bear_lean": "#b5efcc", "hot": GOLD, "cold": "#9fc3ff", "neutral": WHITE}

FONT_CANDIDATES = [   # (regular, bold, ttc index)
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 3),   # 3 = 繁中 TC
    ("/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc", "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc", 3),
    ("C:/Windows/Fonts/msjh.ttc", "C:/Windows/Fonts/msjhbd.ttc", 0),
]
_FC = {}
def font(size, bold=False):
    from PIL import ImageFont
    key = (size, bold)
    if key in _FC: return _FC[key]
    cands = []
    if os.getenv("CARD_FONT"): cands.append((os.getenv("CARD_FONT"), os.getenv("CARD_FONT_BOLD") or os.getenv("CARD_FONT"), int(os.getenv("CARD_FONT_INDEX", "0"))))
    cands += FONT_CANDIDATES
    f = None
    for reg, bd, idx in cands:
        path = bd if bold else reg
        if path and os.path.exists(path):
            try: f = ImageFont.truetype(path, size, index=idx); break
            except Exception: continue
    if f is None: f = ImageFont.load_default(size)
    _FC[key] = f
    return f

def wrap(draw, text, fnt, width, max_lines=None):
    """逐字換行(中文沒有空白可斷);超過 max_lines 最後一行加「…」"""
    lines, cur = [], ""
    for ch in str(text or ""):
        if ch == "\n": lines.append(cur); cur = ""; continue
        if draw.textlength(cur + ch, font=fnt) <= width: cur += ch
        else: lines.append(cur); cur = ch
    if cur: lines.append(cur)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]; last = lines[-1]
        while last and draw.textlength(last + "…", font=fnt) > width: last = last[:-1]
        lines[-1] = last + "…"
    return lines

class Canvas:
    """先在很高的畫布上由上往下畫,最後裁到內容高度(至少 H_MIN)"""
    def __init__(self):
        from PIL import Image, ImageDraw
        self.im = Image.new("RGB", (W, 3200), BG); self.d = ImageDraw.Draw(self.im); self.y = M
    def text(self, x, s, size, color=WHITE, bold=False, width=None, max_lines=None, gap=1.35):
        f = font(size, bold); width = width or (W - M - x)
        ls = wrap(self.d, s, f, width, max_lines)
        for ln in ls:
            self.d.text((x, self.y), ln, font=f, fill=color); self.y += int(size * gap)
        return len(ls)
    def hr(self, pad=18):
        self.y += pad; self.d.line([(M, self.y), (W - M, self.y)], fill="#ffffff33", width=2); self.y += pad
    def save(self, path, footer):
        self.hr(12); self.text(M, footer, 22, MUTED, gap=1.45); self.y += M - 20
        h = max(H_MIN, self.y)
        from PIL import ImageDraw
        im = self.im.crop((0, 0, W, h)); ImageDraw.Draw(im).rectangle([(8, 8), (W - 9, h - 9)], outline=GOLD, width=4)
        im.save(path, optimize=True)
        return path

def header(cv, kind, date, right_lines):
    cv.text(M, "胖虎盤前" if kind == "pre" else "胖虎盤後籌碼站", 26, GOLD, bold=True)
    y0 = cv.y
    cv.text(M, f"{date} {'盤前' if kind == 'pre' else '盤後'}", 50, WHITE, bold=True)
    y1 = cv.y; cv.y = y0 + 4
    for i, (s, c) in enumerate(right_lines):
        f = font(34 if i == 0 else 24, i == 0); w = cv.d.textlength(s, font=f)
        cv.d.text((W - M - w, cv.y), s, font=f, fill=c); cv.y += 46 if i == 0 else 32
    cv.y = max(cv.y, y1) + 6

def aspect_rows(cv, aspects, detail_lines=1, name_w=128, wrap_lines=2):
    for a in aspects:
        cv.hr(12)
        top = cv.y
        cv.d.text((M, top + 4), a.get("name", ""), font=font(28, True), fill=GOLD)
        cv.y = top
        cv.text(M + name_w, a.get("label", ""), 32, TONE.get(a.get("tone"), WHITE), bold=True, max_lines=2)
        for ln in (a.get("lines") or [])[:detail_lines]:
            cv.text(M + name_w, ln, 23, SUB, max_lines=wrap_lines, gap=1.4)

def ruler(cv, pos):
    """同一把尺:淡色帶 = 正常區間(P20~P80),圓點 = 今天,偏離的變金色"""
    cv.hr(12)
    cv.text(M, "歷史位置(今天在歷史中排第幾;0 最低、100 最高)", 24, MUTED)
    cv.y += 6
    tx0, tx1 = M + 330, W - M - 150
    for x in pos:
        hl = x["p"] <= 20 or x["p"] >= 80; col = GOLD if hl else SUB
        yc = cv.y + 18
        cv.d.text((M, cv.y), x["name"], font=font(23, True), fill=WHITE if not hl else GOLD)
        cv.d.text((M, cv.y + 28), f"{x['text']}" + (f"(近 {x['years']} 年)" if x.get("years") is not None and x["years"] < 9 else ""), font=font(20), fill=col)
        cv.d.line([(tx0, yc + 8), (tx1, yc + 8)], fill="#ffffff33", width=3)
        b0 = tx0 + (tx1 - tx0) * 0.2; b1 = tx0 + (tx1 - tx0) * 0.8
        cv.d.rounded_rectangle([(b0, yc + 2), (b1, yc + 14)], radius=6, fill="#9fb0d644")
        px = tx0 + (tx1 - tx0) * min(98, max(2, x["p"])) / 100
        cv.d.ellipse([(px - 11, yc - 3), (px + 11, yc + 19)], fill=col)
        f = font(22); s = f"P{x['p']}"; cv.d.text((W - M - cv.d.textlength(s, font=f), cv.y + 6), s, font=f, fill=col)
        rng = x.get("range") or ""
        if rng:
            fr = font(18); cv.d.text((tx0, cv.y + 32), "正常 " + rng, font=fr, fill=MUTED)
        cv.y += 64

def render_post(t, out_dir=DATA):
    pg = t.get("panghu") or {}; ix = t.get("index") or {}; pix = (t.get("prev") or {}).get("index") or {}
    close, chg = ix.get("close"), ix.get("chg")
    pct = (chg / pix["close"] * 100) if (chg is not None and pix.get("close")) else None
    right = []
    if close is not None:
        right.append((f"加權 {close:,.2f}", WHITE))
        if chg is not None: right.append((f"{'▲' if chg > 0 else '▼' if chg < 0 else ''}{abs(chg):,.2f}" + (f"({pct:+.2f}%)" if pct is not None else ""), TONE["bull"] if chg > 0 else TONE["bear"] if chg < 0 else SUB))
        if ix.get("amount_yi"): right.append((f"量 {ix['amount_yi']:,} 億", MUTED))
    cv = Canvas(); header(cv, "post", t.get("date", ""), right)
    if pg.get("headline"): cv.y += 6; cv.text(M, pg["headline"], 34, WHITE, bold=True, gap=1.45)
    elif pg.get("summary"): cv.text(M, pg["summary"], 30, WHITE, bold=True)
    aspect_rows(cv, pg.get("aspects") or [], detail_lines=1)
    if pg.get("position"): ruler(cv, pg["position"])
    for e in pg.get("events") or []:
        cv.hr(10); cv.text(M, f"極端事件 {e.get('name', '')}:{e.get('text', '')}", 26, GOLD, bold=True)
        if e.get("history_text"): cv.text(M, e["history_text"], 21, SUB, max_lines=2)
    miss = [m for m in (t.get("missing") or []) if m != "margin"]
    foot = (f"盤後資料尚未完整公布:{'、'.join(miss)}。" if miss else "") + "胖虎指標只描述現況,不預測漲跌、不給倉位;不是投資建議。產生 " + (t.get("generated_at") or "").replace("T", " ")
    tag = t["date"].replace("/", "")
    return cv.save(os.path.join(out_dir, f"card_post_{tag}.png"), foot)

def render_pre(t, out_dir=DATA):
    D = t.get("describe") or {}; n = t.get("night")
    right = []
    if n and n.get("night_close"): right += [(f"夜盤 {n['night_close']:,.0f}", WHITE), (f"{n.get('night_chg', 0):+,.0f}({n.get('night_pct', 0):+.2f}%)", TONE["bull"] if (n.get("night_chg") or 0) > 0 else TONE["bear"] if (n.get("night_chg") or 0) < 0 else SUB)]
    cv = Canvas(); header(cv, "pre", t.get("date", ""), right)
    if t.get("missing"):
        cv.y += 4; cv.text(M, "需手動補資料:" + "、".join(t["missing"]), 26, "#ffb3b3", bold=True)
    if D.get("headline"): cv.y += 6; cv.text(M, D["headline"], 34, WHITE, bold=True, gap=1.45)
    aspect_rows(cv, D.get("aspects") or [], detail_lines=3, name_w=150, wrap_lines=3)
    foot = (D.get("note") or "只描述盤前現況,不預測開盤方向、不給倉位。") + "黃金 / 油 / 美元指數是期貨連續合約,換月當天漲跌不準。不是投資建議。產生 " + (t.get("generated_at") or "").replace("T", " ")
    tag = t["date"].replace("/", "")
    return cv.save(os.path.join(out_dir, f"card_pre_{tag}.png"), foot)

def cleanup(out_dir=DATA, keep_days=KEEP_DAYS, today=None):
    """刪掉 keep_days 天以前的 card_*_YYYYMMDD.png"""
    today = today or (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=8)).date()
    cutoff = (today - dt.timedelta(days=keep_days)).strftime("%Y%m%d"); gone = []
    for fn in os.listdir(out_dir):
        if fn.startswith("card_") and fn.endswith(".png"):
            tag = fn[:-4].rsplit("_", 1)[-1]
            if tag.isdigit() and len(tag) == 8 and tag < cutoff:
                os.remove(os.path.join(out_dir, fn)); gone.append(fn)
    return gone

def card_url_when_live(local_path, site_url, timeout=240, every=10):
    """等 GitHub Pages 上這張圖的內容跟本機剛畫的一樣(= 部署完成)才回傳網址(帶內容雜湊,LINE 不會拿到舊快取);逾時回 None"""
    import time, requests
    if not (local_path and site_url and os.path.exists(local_path)): return None
    body = open(local_path, "rb").read(); h = hashlib.sha1(body).hexdigest()[:10]
    url = site_url.rstrip("/") + "/data/" + os.path.basename(local_path)
    end = time.time() + timeout
    while True:
        try:
            r = requests.get(url, params={"t": int(time.time())}, timeout=20)
            if r.status_code == 200 and r.content == body: return f"{url}?v={h}"
        except Exception: pass
        if time.time() >= end: return None
        time.sleep(every)

def image_message(url):
    return {"type": "image", "originalContentUrl": url, "previewImageUrl": url}

def main():
    kind = (sys.argv[1:] or ["post"])[0]
    src = "latest.json" if kind == "post" else "premarket_latest.json"
    with open(os.path.join(DATA, src), encoding="utf-8") as f: t = json.load(f)
    path = render_post(t) if kind == "post" else render_pre(t)
    print("圖卡:", path, os.path.getsize(path), "bytes")
    gone = cleanup()
    if gone: print(f"清掉 {len(gone)} 張舊圖卡:{', '.join(gone[:5])}")

if __name__ == "__main__":
    main()
