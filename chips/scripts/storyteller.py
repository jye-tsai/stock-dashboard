# -*- coding: utf-8 -*-
"""storyteller.py ─ 籌碼站 / LINE 的說書人(靈感:ta-kb同步-說書人.ps1;網頁版在 scripts/story.js)
把盤後籌碼的真實數字講成奇幻 / 修仙劇情:外資 = 王城騎士團 / 仙門大長老、散戶 = 村民 / 散修、台指期 = 巨龍 / 護山神獸……
- 只包裝真實數字,不編數字;句子由題庫片段組合,亂數種子 = 日期 + 世界 → 同一天同一則(網頁與 LINE 一致)
- 開關與世界觀:chips/story.json 的 "world":「奇幻」「修仙」「隨機」(每天輪)「關閉」
用到的地方:fetch_all.py 寫進當日 JSON 的 story(籌碼站網頁顯示)、notify.py 盤後 LINE、notify_failure.py 失敗通知。"""
import os, json, random, hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "..", "story.json")
WORLDS = ("奇幻", "修仙")

def world_for(date_str, cfg_path=CONFIG):
    """設定檔的世界觀;「隨機」依日期固定輪一個;「關閉」或讀不到設定 → None(不講故事)"""
    try:
        with open(cfg_path, encoding="utf-8") as f: w = (json.load(f) or {}).get("world", "隨機")
    except (OSError, ValueError):
        w = "隨機"
    if w in WORLDS: return w
    if w == "隨機": return WORLDS[int(hashlib.md5(str(date_str).encode()).hexdigest(), 16) % 2]
    return None

G = {
    "奇幻": {
        "開場": ["黃昏的王城廣場,傳令兵敲響了鐘。", "夕陽把城牆染成金色,說書人清了清喉嚨。", "旅店裡的吟遊詩人放下酒杯:「來聽今天的戰報。」", "收市的號角吹響,{npc}跑來報告戰況。"],
        "npc": ["獨眼老兵", "旅店老闆娘", "城門守衛", "見習法師", "會算帳的哥布林", "一隻會說話的黑貓"],
        "外資買": ["王城騎士團帶回 {v} 億金幣{run}。", "騎士團凱旋,搬回 {v} 億金幣{run}。"],
        "外資賣": ["王城騎士團撤出了 {v} 億金幣{run}。", "騎士團把 {v} 億金幣運出城外{run}。"],
        "散戶多": ["村民們扛著草叉喊多(小台散戶多空比 {r})。", "廣場上的村民一面倒看多({r})。"],
        "散戶空": ["村民們躲進地窖看空(小台散戶多空比 {r})。", "村民紛紛收拾行李,看空情緒升高({r})。"],
        "散戶平": ["村民們議論紛紛,多空沒有定論({r})。"],
        "龍加多": ["巨龍(外資台指期)收起了 {n} 口空單的爪子,淨部位 {net} 口。", "巨龍翻了個身,淨空單少了 {n} 口(淨 {net} 口)。"],
        "龍加空": ["巨龍又伸出 {n} 口空單的爪子,淨部位 {net} 口。", "巨龍低吼一聲,淨空單多了 {n} 口(淨 {net} 口)。"],
        "正價差": ["期貨比現貨高 {b} 點,巨龍嘴角微笑。"],
        "逆價差": ["期貨比現貨低 {b} 點,巨龍皺起了眉頭。"],
        "PC低": ["避險護盾很薄(P/C {pc}%),大家都很勇敢。"],
        "PC高": ["城裡家家戶戶在買護盾(P/C {pc}%)。"],
        "收尾": ["說書人:以上都是真實戰報,明天再見。", "吟遊詩人收起魯特琴:「明日的故事,明日再唱。」"],
        "倒下": ["☠ 胖虎倒下了!", "☠ 一陣黑霧襲來,胖虎昏了過去。"],
        "復活": ["(修好後重跑一次就能復活)"],
    },
    "修仙": {
        "開場": ["酉時,仙門鐘鳴九響,執事展開今日卷宗。", "暮色中,藏經閣長老翻開了今日的玉簡。", "{npc}踏雲而來:「今日仙門戰況如下。」"],
        "npc": ["外門管事", "藏經閣長老", "掃地的老雜役", "戒律堂執事", "守山靈獸"],
        "外資買": ["仙門大長老收入 {v} 億靈石{run}。", "大長老神識一掃,納入 {v} 億靈石{run}。"],
        "外資賣": ["仙門大長老取走 {v} 億靈石{run}。", "大長老拂袖而去,帶走 {v} 億靈石{run}。"],
        "散戶多": ["散修們群情激昂,紛紛看多(小台散戶多空比 {r})。"],
        "散戶空": ["散修們閉關避禍,看空者眾({r})。"],
        "散戶平": ["散修們各說各話,多空未定({r})。"],
        "龍加多": ["護山神獸(外資台指期)收回 {n} 口空單,淨部位 {net} 口。"],
        "龍加空": ["護山神獸又亮出 {n} 口空單的獠牙,淨部位 {net} 口。"],
        "正價差": ["期貨高出現貨 {b} 點,神獸氣息平和。"],
        "逆價差": ["期貨低於現貨 {b} 點,神獸躁動不安。"],
        "PC低": ["護體罡氣稀薄(P/C {pc}%),眾修士膽氣頗壯。"],
        "PC高": ["人人祭起護體法寶(P/C {pc}%)。"],
        "收尾": ["執事合上卷宗:「今日之事,皆有據可查。」", "長老撫鬚:「明日再議。」"],
        "倒下": ["☠ 胖虎道消身隕!", "☠ 心魔反噬,胖虎走火入魔。"],
        "復活": ["(修好後重跑一次即可轉世重修)"],
    },
}

def _rng(date_str, world, salt=""):
    return random.Random(int(hashlib.md5(f"{date_str}|{world}|{salt}".encode()).hexdigest(), 16))

def _fill(rng, world, key, **kw):
    B = G[world]
    s = rng.choice(B[key])
    if "{npc}" in s: s = s.replace("{npc}", rng.choice(B["npc"]))
    return s.format(**kw)

def chips_story(t, world):
    """盤後當日資料(fetch_all 的 t)→ 說書幾行;欄位缺就跳過那句"""
    if world not in G: return []
    r = _rng(t.get("date", ""), world, "chips")
    L = [_fill(r, world, "開場")]
    inst = t.get("inst") or {}
    fx = inst.get("外資")
    if isinstance(fx, (int, float)):
        run = ((t.get("insight") or {}).get("foreign") or {})
        run_txt = f"(連 {run.get('run')} 日{'買' if fx > 0 else '賣'})" if run.get("run", 0) >= 2 and run.get("side") in ("連買", "連賣") else ""
        L.append(_fill(r, world, "外資買" if fx > 0 else "外資賣", v=f"{abs(fx):,.0f}", run=run_txt))
    mr = (t.get("mtx_retail") or {}).get("ratio_pct")
    if isinstance(mr, (int, float)):
        L.append(_fill(r, world, "散戶多" if mr >= 10 else "散戶空" if mr <= -10 else "散戶平", r=f"{mr:+.1f}%"))
    f_now = ((t.get("txf") or {}).get("外資") or {}).get("net")
    f_prev = (((t.get("prev") or {}).get("txf") or {}).get("外資") or {}).get("net")
    if isinstance(f_now, (int, float)) and isinstance(f_prev, (int, float)) and f_now != f_prev:
        d = f_now - f_prev
        L.append(_fill(r, world, "龍加多" if d > 0 else "龍加空", n=f"{abs(d):,.0f}", net=f"{f_now:+,.0f}"))
    b = t.get("basis")
    if isinstance(b, (int, float)) and abs(b) >= 20:
        L.append(_fill(r, world, "正價差" if b > 0 else "逆價差", b=f"{abs(b):,.0f}"))
    pc = (t.get("pc") or {}).get("oi_ratio_pct")
    if isinstance(pc, (int, float)) and (pc < 80 or pc > 130):
        L.append(_fill(r, world, "PC低" if pc < 80 else "PC高", pc=f"{pc:.1f}"))
    L.append(_fill(r, world, "收尾"))
    return L

def fail_lines(world, date_str=""):
    """失敗通知的開頭兩句(世界觀關閉 → [])"""
    if world not in G: return []
    r = _rng(date_str, world, "fail")
    return [r.choice(G[world]["倒下"]), r.choice(G[world]["復活"])]
