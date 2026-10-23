# -*- coding: utf-8 -*-
"""
market_calendar.py ─ 台股今天(或指定日)有沒有開市

給盤前排程開頭用:休市就整班跳過(不抓資料、不畫圖卡、不發 LINE)。依序檢查:
  1. 週六 / 週日
  2. 手動清單 chips/closed_days.json(臨時休市、程式判斷不到時,使用者在 GitHub 網頁加一行就生效)
  3. 證交所休市日表(OpenAPI holidaySchedule:國定假日、補假、春節封關)
  4. 臺北市停止上班(行政院人事行政總處停班停課公告;證交所規則:臺北市全天停止上班 → 股市休市)

網路抓不到時一律「當作有開市」(寧可多發一次,不要漏發),並把原因記在 data/market_calendar.json,
事後可以看那個檔確認判斷依據。用法:
  python chips/scripts/market_calendar.py              # 檢查今天(台北時間)
  python chips/scripts/market_calendar.py 2026/10/26   # 檢查指定日
"""
import os, re, sys, json, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import tw_now, read_json, write_json

HERE = os.path.dirname(os.path.abspath(__file__))
CHIPS = os.path.join(HERE, "..")
DATA = os.path.join(CHIPS, "data")
MANUAL_PATH = os.path.join(CHIPS, "closed_days.json")
STATE_PATH = os.path.join(DATA, "market_calendar.json")
TWSE_URL = "https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule"
DGPA_URL = "https://www.dgpa.gov.tw/typh/daily/nds.html"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}


# ─────────────── 日期 ───────────────
def parse_date(s):
    """各種日期寫法 → datetime.date;認不得回 None。
    民國 7 碼 1151026、民國 115/10/26、西元 20261026 / 2026/10/26 / 2026-10-26"""
    if s is None: return None
    s = str(s).strip()
    m = re.fullmatch(r"(\d{2,3})[/.-](\d{1,2})[/.-](\d{1,2})", s)            # 民國含分隔
    if m and int(m.group(1)) < 1000:
        y, mo, d = int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3))
    else:
        m = re.fullmatch(r"(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})", s)
        if m: y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        elif re.fullmatch(r"\d{8}", s): y, mo, d = int(s[:4]), int(s[4:6]), int(s[6:])
        elif re.fullmatch(r"\d{7}", s): y, mo, d = int(s[:3]) + 1911, int(s[3:5]), int(s[5:])
        else: return None
    try: return dt.date(y, mo, d)
    except ValueError: return None

def fmt(d): return d.strftime("%Y/%m/%d")


# ─────────────── 2. 手動清單 ───────────────
def manual_closed(path=MANUAL_PATH):
    """chips/closed_days.json → {date: 原因}。格式 {"closed": {"2026/10/23": "薔琵颱風休市", ...}}"""
    j = read_json(path, {}) or {}
    out = {}
    for k, v in (j.get("closed") or {}).items():
        d = parse_date(k)
        if d: out[d] = v or "手動標記休市"
    return out


# ─────────────── 3. 證交所休市日表 ───────────────
def twse_closed_from_rows(rows):
    """證交所 holidaySchedule 回傳的列 → {date: 名稱}。
    表裡也列了「開始交易日 / 最後交易日」(那天其實有開市),要排除;其餘(放假、市場無交易)算休市。"""
    out = {}
    for r in rows or []:
        if not isinstance(r, dict): continue
        name = str(r.get("Name") or r.get("名稱") or "").strip()
        desc = str(r.get("Description") or r.get("說明") or "").strip()
        d = parse_date(r.get("Date") or r.get("日期"))
        if not d: continue
        text = name + desc
        if "開始交易" in text or "最後交易" in text: continue
        out[d] = name or desc or "證交所休市日"
    return out

def fetch_twse(get=None, timeout=15):
    import requests
    get = get or requests.get
    r = get(TWSE_URL, headers=UA, timeout=timeout); r.raise_for_status()
    return r.json()


# ─────────────── 4. 臺北市停止上班 ───────────────
def _html_text(html):
    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", html or "")
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = t.replace("&nbsp;", " ").replace("臺", "台")
    return re.sub(r"\s+", " ", t)

def taipei_suspension(html):
    """人事行政總處停班停課頁 → {日期: 說明}(只收「台北市全市停止上班」;部分區里、只停下午的不算休市)。
    「今天 / 明天」以頁面的「更新時間」為基準換算日期;頁面寫了 10月23日 這類日期就直接用。
    回傳 (結果 dict, 台北市那一段原文),原文存檔方便事後核對頁面格式有沒有變。"""
    text = _html_text(html)
    m = re.search(r"更新時間\s*[:：]?\s*(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})", text)
    base = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None
    k = text.find("台北市")
    if k < 0: return {}, ""
    seg = text[k + 3:k + 3 + 160]
    nxt = re.search(r"\S{2,3}[縣市](?=\s)", seg)                               # 截到下一個縣市名之前
    if nxt and nxt.start() > 0: seg = seg[:nxt.start()]
    seg = seg.strip(" |｜:：")
    out = {}
    for clause in re.split(r"[。；;]", seg):
        if "停止上班" not in clause: continue
        if re.search(r"[區里鄉鎮]|部分|山區", clause): continue                 # 只有部分地區停班,股市照開
        if "下午停止上班" in clause and "上午停止上班" not in clause: continue   # 只停下午班:早上照常交易
        md = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", clause)
        if md and base: day = dt.date(base.year, int(md.group(1)), int(md.group(2)))
        elif "明天" in clause or "明日" in clause: day = base + dt.timedelta(days=1) if base else None
        elif "今天" in clause or "今日" in clause: day = base
        else: day = base
        if day: out[day] = "台北市停止上班：" + clause.strip()
    return out, seg

def fetch_dgpa(get=None, timeout=15):
    import requests
    get = get or requests.get
    r = get(DGPA_URL, headers=UA, timeout=timeout); r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text


# ─────────────── 合在一起 ───────────────
def check(day=None, now=None, twse=None, dgpa=None, manual_path=MANUAL_PATH, state_path=STATE_PATH, save=True):
    """day 開市嗎?回 (closed: bool, reason: str)。twse / dgpa 可傳入假的抓取函式(測試用),
    傳 False 代表不查那一層。網路錯誤 → 那一層當作沒休市,錯誤記進 state。"""
    now = now or tw_now()
    day = day or now.date()
    if isinstance(day, dt.datetime): day = day.date()
    state = read_json(state_path, {}) or {} if state_path else {}
    note = {"day": fmt(day), "checked_at": now.strftime("%Y/%m/%d %H:%M"), "sources": {}}
    closed, reason = False, ""

    if day.weekday() >= 5: closed, reason = True, "週末"
    if not closed:
        m = manual_closed(manual_path)
        if day in m: closed, reason = True, f"手動清單:{m[day]}"
        note["sources"]["manual"] = "ok"

    if not closed and twse is not False:
        try:
            rows = (twse or fetch_twse)()
            hol = twse_closed_from_rows(rows)
            state["twse_holidays"] = {fmt(k): v for k, v in sorted(hol.items())}
            state["twse_fetched_at"] = note["checked_at"]
            note["sources"]["twse"] = f"ok({len(hol)} 天)"
        except Exception as e:
            note["sources"]["twse"] = f"失敗,改用快取:{type(e).__name__}: {str(e)[:80]}"
            hol = {parse_date(k): v for k, v in (state.get("twse_holidays") or {}).items()}
        if day in hol: closed, reason = True, f"證交所休市日:{hol[day]}"

    if not closed and dgpa is not False and abs((day - now.date()).days) <= 1:   # 停班公告只看今明兩天
        try:
            res, seg = taipei_suspension((dgpa or fetch_dgpa)())
            note["sources"]["dgpa"] = "ok"; note["dgpa_taipei"] = seg[:120]
            if day in res: closed, reason = True, res[day]
        except Exception as e:
            note["sources"]["dgpa"] = f"失敗:{type(e).__name__}: {str(e)[:80]}"

    note["closed"], note["reason"] = closed, reason
    state["last_check"] = note
    if save and state_path:
        try: write_json(state_path, state, indent=1)
        except OSError: pass
    return closed, reason


if __name__ == "__main__":
    d = parse_date(sys.argv[1]) if len(sys.argv) > 1 else None
    c, why = check(d)
    print(json.dumps({"day": fmt(d or tw_now().date()), "closed": c, "reason": why}, ensure_ascii=False))
