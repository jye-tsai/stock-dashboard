# -*- coding: utf-8 -*-
"""weekly_report.py ─ 每週日產生「交接文件更新草稿」：本週序列表＋胖虎指標(現況描述)。
輸出 data/weekly_YYYYMMDD.md 與 data/weekly_index.json"""
import os, json, glob, datetime as dt
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DATA = os.path.join(ROOT, "data")
idx = json.load(open(os.path.join(DATA, "index.json")))
days = sorted(idx)[-5:]                     # 最近 5 個交易日
rows = [json.load(open(os.path.join(DATA, f"{d}.json"), encoding="utf-8")) for d in days if os.path.exists(os.path.join(DATA, f"{d}.json"))]
if not rows: raise SystemExit("no data")
def g(o, *ks, d="—"):
    for k in ks:
        if o is None: return d
        o = o.get(k) if isinstance(o, dict) else None
    return d if o is None else o
def n(v, f="{:,}"): return f.format(v) if isinstance(v, (int, float)) else ("—" if v is None else str(v))
today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).strftime("%Y%m%d")
L = [f"# 台股日報・交接文件更新草稿（{rows[0]['date']} ～ {rows[-1]['date']}）", "",
     "> 由籌碼站自動產生，數字可直接貼進交接文件「4.2 最新數據序列」；判讀與劇情主線請 Claude 補。", "",
     "## 一、本週數據序列", "",
     "| 日期 | 加權 | 漲跌 | 量(億) | 外資現貨(億) | 法人合計 | 外資淨空 | 淨空增減 | 小台多空比 | 微台多空比 | P/C(OI) | 期指近月收 | 價差 |",
     "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
prev_net = None
for t in rows:
    f = g(t, "txf", "外資", d={}) or {}
    net = f.get("net"); dnet = (net - prev_net) if (net is not None and prev_net is not None) else None; prev_net = net
    L.append("| " + " | ".join([
        t["date"][5:], n(g(t,"index","close")), n(g(t,"index","chg"), "{:+,}"), n(g(t,"index","amount_yi")),
        n(g(t,"inst","外資"), "{:+.0f}"), n(g(t,"inst","合計"), "{:+.0f}"), n(net), n(dnet, "{:+,}"),
        n(g(t,"mtx_retail","ratio_pct"), "{:+.2f}%"), n(g(t,"tmf_retail","ratio_pct"), "{:+.2f}%"),
        n(g(t,"pc","oi_ratio_pct"), "{}%"), n(g(t,"tx","close"), "{:,.0f}"), n(g(t,"basis"), "{:+,.0f}")]) + " |")
last = rows[-1]; f = g(last, "txf", "外資", d={}) or {}
L += ["", "## 二、週末狀態（校驗用前值）", "",
      f"- 加權 {n(g(last,'index','close'))}；量 {n(g(last,'index','amount_yi'))} 億；融資 {n(g(last,'margin'))} 億（證交所口徑）",
      f"- 外資期貨 OI：多 {n(f.get('long'))}／空 {n(f.get('short'))}／淨 {n(f.get('net'))}；投信淨多 {n(g(last,'txf','投信','net'))}；自營 {n(g(last,'txf','自營商','net'))}",
      f"- 外資選擇權：買權淨 {n(g(last,'opt','外資','call'))}、賣權淨 {n(g(last,'opt','外資','put'))}",
      f"- 散戶：小台 {n(g(last,'mtx_retail','ratio_pct'),'{:+.2f}%')}、微台 {n(g(last,'tmf_retail','ratio_pct'),'{:+.2f}%')}；P/C {n(g(last,'pc','oi_ratio_pct'))}%",
      "", "## 三、胖虎指標（每日盤後現況描述，不預測、不給倉位）", ""]
pgs = [(t["date"][5:], t.get("panghu") or {}) for t in rows]
if any(pg.get("version") == 4 for _, pg in pgs):
    L += ["| 日期 | 趨勢 | 籌碼 | 情緒 | 匯率 | 極端事件 |", "|---|---|---|---|---|---|"]
    for dte, pg in pgs:
        a = {x["k"]: x["label"] for x in pg.get("aspects") or []}
        ev = "、".join(e["name"] for e in pg.get("events") or []) or "—"
        L.append(f"| {dte} | {a.get('trend', '—')} | {a.get('chips', '—')} | {a.get('sentiment', '—')} | {a.get('fx', '—')} | {ev} |")
    last_pg = pgs[-1][1]
    for x in last_pg.get("aspects") or []: L.append(f"- 週末{x['name']}:{';'.join(x['lines'])}")
else:
    L.append("- 本週資料尚無胖虎指標 v4")
L += ["", "## 四、待 Claude 補寫", "", "- 劇情主線（本週四～五個交易日的因果）", "- 外資期貨方法論新增觀察", "- 散戶溫度計案例入庫", "- 紀律成本照實記（出入點位與差額）", "- 下週事件時程與補齊／防守條件"]
fn = f"weekly_{today}.md"
open(os.path.join(DATA, fn), "w", encoding="utf-8").write("\n".join(L))
wi_path = os.path.join(DATA, "weekly_index.json")
wi = json.load(open(wi_path)) if os.path.exists(wi_path) else []
if fn not in wi: wi.insert(0, fn)
json.dump(wi[:60], open(wi_path, "w"), indent=0)
print("weekly:", fn)
