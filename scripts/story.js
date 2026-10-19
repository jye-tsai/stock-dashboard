/* scripts/story.js — 說書人(UMD,瀏覽器掛在 window.PfStory;Node 用 require 測試)
   靈感:ta-kb同步-說書人.ps1。把「今天的真實數字」講成一段奇幻 / 修仙冒險:
   - 故事只包裝真實資料(漲跌、持股、除息、進出、停損 / 目標、成就),不編數字
   - 句子由題庫片段組成:{xxx} 展開成同名題庫裡隨機一句;{n}{pct} 等由程式帶入
   - 亂數用日期 + 世界 + 「換一則」次數當種子:同一天重畫是同一則,數字跟著盤中更新
   - 前幾天用過的句子(avoid)先避開,題庫用完才重複
   - 兩個世界的名詞表(TERMS)也給冒險主題的介面用:元寶 ↔ 靈石、裝備 ↔ 法寶、Lv ↔ 境界… */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.PfStory = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // ══ 名詞表:冒險主題介面 + 故事共用 ══
  var TERMS = {
    '奇幻': {
      hero: '勇者', vaultWord: '寶庫', coin: '元寶', item: '裝備', board: '裝備欄', bag: '背包', journal: '冒險日誌',
      today: '今日戰果', power: '戰力', invest: '投入資源', gear: '裝備加成', loot: '戰利品', salary: '俸祿', total: '總戰果',
      daily: '每日戰報', yearly: '年度戰績', lineup: '陣容配置', history: '歷年戰史', overview: '城堡', ach: '成就',
      attack: '攻擊力', damage: '受損', enhance: '強化', durability: '耐久',
      rarity: { legend: '傳說', epic: '史詩', rare: '稀有', common: '普通', broken: '破損', cursed: '詛咒' },
      slots: ['劍', '盾', '盔', '甲', '戒', '項鍊', '靴', '寶珠'],
      vaults: ['破洞錢袋', '錢袋', '銅寶箱', '鐵寶箱', '黃金寶箱', '傳說寶庫'],
      chapters: ['第一章・新手村', '第二章・王城', '第三章・龍之巢穴', '終章・傳說之境'],
      lv: function (lv) { return 'Lv.' + lv; }
    },
    '修仙': {
      hero: '道友', vaultWord: '洞府', coin: '靈石', item: '法寶', board: '法寶閣', bag: '儲物戒', journal: '修行日誌',
      today: '今日修為', power: '道行', invest: '投入靈石', gear: '法寶加持', loot: '機緣', salary: '宗門月俸', total: '總修為',
      daily: '每日功課', yearly: '年度修行', lineup: '本命法陣', history: '修行年譜', overview: '洞府', ach: '道果',
      attack: '威能', damage: '損耗', enhance: '祭煉', durability: '靈性',
      rarity: { legend: '仙品', epic: '天品', rare: '地品', common: '凡品', broken: '裂紋', cursed: '魔化' },
      slots: ['飛劍', '護心鏡', '道冠', '法袍', '儲物戒', '玉珮', '踏雲靴', '丹爐'],
      vaults: ['破碗', '儲物袋', '靈石匣', '乾坤袋', '洞天', '仙府'],
      chapters: ['第一卷・外門', '第二卷・內門', '第三卷・真傳', '終卷・飛升'],
      lv: function (lv) {
        var R = [[1, '煉氣'], [4, '築基'], [7, '金丹'], [11, '元嬰'], [16, '化神'], [21, '煉虛'], [26, '合體'], [31, '大乘'], [41, '渡劫']];
        var r = R[0]; for (var i = 0; i < R.length; i++) if (lv >= R[i][0]) r = R[i];
        var next = R[R.indexOf(r) + 1], span = next ? next[0] - r[0] : 9, layer = Math.min(9, lv - r[0] + 1);
        return r[1] + (span > 1 ? '・' + '一二三四五六七八九'[Math.min(8, Math.floor((layer - 1) * 9 / span))] + '層' : '');
      }
    }
  };

  // ══ 題庫 ══
  var G = {
    '奇幻': {
      時辰: { pre: '清晨', open: '正午', post: '黃昏', night: '深夜' },
      地點: ['旅店二樓', '壁爐邊', '村口的大樹下', '鐵匠鋪後院', '城牆上的哨塔'],
      NPC: ['旅店老闆娘', '獨眼老兵', '醉醺醺的吟遊詩人', '打瞌睡的守衛', '戴尖帽的見習法師', '賣蘋果的小女孩', '退休的屠龍者', '一隻會說話的黑貓', '鐵匠的學徒', '村口算命的老婆婆', '愛碎念的圖書館員', '會算帳的哥布林'],
      天氣: {
        2: ['陽光灑滿整座王城', '天空出現雙彩虹', '萬里無雲,連龍都出來曬太陽', '號角聲響徹山谷'],
        1: ['陽光灑在石板路上', '微風吹來烤麵包的香味', '晴朗的好天氣', '鳥兒在屋頂上唱歌'],
        0: ['起了薄薄的霧', '雲層灰灰的,看不出晴雨', '風停了,四周很安靜', '天色不明,像在思考什麼'],
        '-1': ['天空飄著細雨', '遠方雷聲隱隱', '雲層低得快壓到屋頂', '北風呼嘯而過'],
        '-2': ['雷雲壓城,暴雨傾盆', '暴風雪封住了山路', '天空裂開一道閃電', '狂風把旅店招牌吹走了']
      },
      開場: ['{時辰},{天氣}。{英雄}在{地點}醒來,聽見{NPC}在樓下吆喝。', '{時辰},{天氣}。{英雄}坐在{地點}擦拭長劍。', '{時辰}的{地點}人不多,{NPC}正在角落打盹。窗外{天氣}。', '{時辰},{英雄}推開窗,{天氣}。'],
      章名: ['{伙伴}的試煉', '{伙伴}與{boss}', '{天氣短}的日子', '王城風雲', '寶庫保衛戰', '{boss}來襲', '{伙伴}登場', '秘境之門'],
      天氣短: { 2: ['萬丈光芒'], 1: ['晴空'], 0: ['迷霧'], '-1': ['細雨'], '-2': ['雷雲壓城'] },
      伙伴好: ['{稀有}伙伴〈{伙伴}〉今天大顯身手,{pct}。', '〈{伙伴}〉一馬當先衝在最前面,{pct}。', '{NPC}說:「〈{伙伴}〉今天閃閃發光!」({pct})', '〈{伙伴}〉一劍劈開迷霧,{pct}。'],
      伙伴穩: ['〈{伙伴}〉穩穩守住陣線,{pct}。', '〈{伙伴}〉今天是隊上最可靠的一位,{pct}。'],
      Boss: ['野生的【{boss}】擋住去路,{pct}。', '【{boss}】被史萊姆偷襲了,{pct}。', '〈{boss}〉今天沾了一身泥,{pct}。', '地面裂開,〈{boss}〉被拖進了陷阱,{pct}。'],
      戰果好: ['⚔ {today} {chg}({pct}),{寶庫名}閃閃發亮,{等級}。', '⚔ {today} {chg}({pct}),吟遊詩人開始寫新歌。{等級}・{寶庫名}。'],
      戰果壞: ['⚔ {today} {chg}({pct}),{寶庫名}還在,{等級}。', '⚔ {today} {chg}({pct}),{英雄}擦掉臉上的泥,{等級}・{寶庫名}仍屹立不搖。'],
      戰果平: ['⚔ {today} {chg}({pct}),今天是休息日。{等級}・{寶庫名}。'],
      新高: ['🏔 {英雄}登上了從未到過的山頂(總市值創新高 {mv})。', '🏔 吟遊詩人宣布:{寶庫名}寫下新的傳說!(總市值新高 {mv})'],
      除息: ['💰 國王發下俸祿:{list}。', '💰 王城的信使送來俸祿袋:{list}。'],
      買進: ['🔨 鐵匠鋪打造了新裝備:{list}。', '🔨 {英雄}在市集添購了{list}。'],
      賣出: ['🪙 把戰利品換成金幣:{list}。', '🪙 {英雄}在商人那裡賣掉了{list}。'],
      停損: ['⚠ 陷阱警報!{list} 踩到了你設的停損線。'],
      目標: ['🎁 寶箱打開了!{list} 達到了目標價。'],
      成就: ['📜 說書人高聲宣布:{英雄}獲得稱號〈{list}〉!'],
      事件: ['一隻史萊姆擋路,{英雄}一腳把牠踢進草叢。', '路邊寶箱裡只有一張紙條:「記得分散風險」。', '流浪商人想賣你「永不下跌的護身符」,{英雄}婉拒了。', '{NPC}追上來塞給{英雄}一個麵包。', '一陣風吹來,捲走了{NPC}的帽子。', '一隻哥布林想打劫,看到你的裝備就跑了。', '{NPC}說:「聽說 K 線圖會說話。」', '地上有一枚金幣,撿起來發現是巧克力。', '一位旅人問路,{英雄}指錯了方向。', '{NPC}:「我覺得我們被跟蹤了。」回頭一看是隻雞。', '一隻烏鴉叼走了你的看盤筆記,又丟了回來。', '{NPC}唱起了一首走音的歌,歌名叫〈長期持有〉。'],
      提示好: ['村長提示:贏了也別忘記檢查裝備耐久。', '村長提示:好天氣也要記得帶傘。'],
      提示壞: ['村長提示:{total}還有 {ret},冒險繼續。', '村長提示:暴風雨總會過去,{total} {ret}。'],
      提示平: ['村長提示:平靜的日子最適合整理背包。']
    },
    '修仙': {
      時辰: { pre: '卯時', open: '午時', post: '酉時', night: '亥時' },
      地點: ['洞府', '丹房', '藏經閣外', '後山靈泉邊', '練劍坪'],
      NPC: ['掃地的老雜役', '外門管事', '煉丹房的童子', '藏經閣長老', '化形失敗的狐妖', '雲遊散修', '守山靈獸', '賣假丹藥的小販', '閉關三百年剛出來的師叔祖', '戒律堂執事', '山下茶棚的老闆'],
      天氣: {
        2: ['紫氣東來,祥雲滿天', '天降異象,七彩霞光籠罩山門', '靈氣如潮,滿山靈草一夜開花'],
        1: ['萬里無雲', '月華如水', '靈雨初歇,山色清新'],
        0: ['靈霧瀰漫山間', '天地寂靜,不見風雲', '雲深不知處'],
        '-1': ['靈雨霏霏', '罡風凜冽', '天邊雷雲聚集'],
        '-2': ['天劫降臨,雷雲壓頂', '心魔四起,陰風怒號', '九天玄雷一道接一道']
      },
      開場: ['{時辰},{天氣}。{英雄}在{地點}自入定中醒來。', '{時辰},{天氣}。{英雄}推開{地點}的石門。', '{時辰},{NPC}在{地點}外輕咳一聲,{天氣}。'],
      章名: ['{伙伴}出世', '{伙伴}與{boss}', '{天氣短}', '仙門風雲', '洞府初開', '心魔來襲', '{boss}渡劫'],
      天氣短: { 2: ['紫氣東來'], 1: ['月華如水'], 0: ['雲深'], '-1': ['靈雨'], '-2': ['天劫'] },
      伙伴好: ['{稀有}法寶〈{伙伴}〉靈光大盛,{pct}。', '〈{伙伴}〉劍鳴不止,{pct}。', '{NPC}驚呼:「〈{伙伴}〉竟然自行護主!」({pct})'],
      伙伴穩: ['〈{伙伴}〉穩如泰山,{pct}。', '〈{伙伴}〉今日靈性內斂,{pct}。'],
      Boss: ['〈{boss}〉被心魔所侵,{pct}。', '天雷劈中了〈{boss}〉,{pct}。', '〈{boss}〉靈光黯淡,{pct}。'],
      戰果好: ['☯ {today} {chg}({pct}),{寶庫名}靈氣充盈,{等級}。', '☯ {today} {chg}({pct}),修為精進!{等級}・{寶庫名}。'],
      戰果壞: ['☯ {today} {chg}({pct}),道心未失,{等級}・{寶庫名}仍在。', '☯ {today} {chg}({pct}),{英雄}吐出一口濁氣,{等級}。'],
      戰果平: ['☯ {today} {chg}({pct}),今日靜修。{等級}・{寶庫名}。'],
      新高: ['🏔 {英雄}突破瓶頸,境界前所未有(總市值新高 {mv})。'],
      除息: ['💰 宗門發下月俸:{list}。'],
      買進: ['🔥 {英雄}祭煉了新法寶:{list}。'],
      賣出: ['🪙 {英雄}把法寶換成靈石:{list}。'],
      停損: ['⚠ 護身禁制被觸動!{list} 碰到了停損線。'],
      目標: ['🎁 機緣到了!{list} 達到目標價。'],
      成就: ['📜 天道降下感應:{英雄}證得道果〈{list}〉!'],
      事件: ['一隻靈狐從林間探頭,又縮了回去。', '你偶得一縷頓悟:分散持有,方能長久。', '路邊老道士:「道友,追高需謹慎啊。」', '一朵祥雲飄過,修為 +1。', '{NPC}在路邊兜售「一鍵飛升符」,你沒理他。', '山澗裡的魚吐了個泡泡,泡泡上寫著「長期持有」。', '你踩到一株千年人參,它尖叫著跑了。', '天邊飛過一群仙鶴,排成了 K 線的形狀。', '一陣靈風吹過,{英雄}的頭髮全部豎起來。', '{NPC}偷吃了你的丹藥,臉都綠了。'],
      提示好: ['師尊提點:修為大進時,更要穩住道心。'],
      提示壞: ['師尊提點:{total}尚有 {ret},心魔終會散去。', '師尊提點:大道漫漫,一時起落不足掛齒({total} {ret})。'],
      提示平: ['師尊提點:無事之日,正好打坐。']
    }
  };

  // ══ 工具 ══
  function hash(s) { var h = 2166136261; for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }
  function rng(seed) { var a = seed >>> 0; return function () { a |= 0; a = (a + 0x6D2B79F5) | 0; var t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
  var sgn = function (v) { return v > 0 ? '+' : v < 0 ? '-' : ''; };
  var money = function (v) { var a = Math.abs(v); return sgn(v) + (a >= 10000 ? (a / 10000).toFixed(1) + '萬' : Math.round(a).toLocaleString('en-US')); };
  var pctTxt = function (p) { return sgn(p) + Math.abs(p * 100).toFixed(2) + '%'; };
  function mood(p) { return p >= 0.015 ? 2 : p >= 0.003 ? 1 : p > -0.003 ? 0 : p > -0.015 ? -1 : -2; }   // 大盤漲跌 → 天氣等級
  function slot(hhmm) { return hhmm < 900 ? 'pre' : hhmm < 1330 ? 'open' : hhmm < 1900 ? 'post' : 'night'; }

  // ══ 產生故事 ══
  // input: { date, hhmm, day(第幾回), taiexPct, todayChg, todayPct, totalReturn, mv, lv, vaultTier(0..5),
  //          best:{name, pct, rarity}, worst:{name, pct}, ath, exDiv:[文字], buys:[文字], sells:[文字], stops:[名], targets:[名], ach:[名] }
  // opts: { world, roll, avoid:[前幾天用過的模板] } → { world, title, lines:[{k, t}], used:[模板], opening }
  function tell(input, opts) {
    opts = opts || {};
    var world = TERMS[opts.world] ? opts.world : '奇幻', W = TERMS[world], B = G[world];
    var R = rng(hash(input.date + '|' + world + '|' + (opts.roll || 0)));
    var avoid = opts.avoid || [], used = [];
    var pick = function (arr) {
      var fresh = arr.filter(function (x) { return avoid.indexOf(x) < 0 && used.indexOf(x) < 0; });
      var pool = fresh.length ? fresh : arr, x = pool[Math.floor(R() * pool.length)];
      used.push(x); return x;
    };
    var m = mood(input.taiexPct || 0);
    var v = {
      英雄: '胖虎', 時辰: B.時辰[slot(input.hhmm || 1200)], 天氣: pick(B.天氣[m]), 天氣短: B.天氣短[m][0],
      伙伴: input.best ? input.best.name : '無名小卒', boss: input.worst ? input.worst.name : '影子',
      稀有: input.best && input.best.rarity ? W.rarity[input.best.rarity] || '' : '',
      today: W.today, total: W.total, ret: money(input.totalReturn || 0), chg: money(input.todayChg || 0), mv: money(input.mv || 0),
      寶庫名: W.vaults[Math.max(0, Math.min(5, input.vaultTier || 0))], 等級: W.lv(input.lv || 1)
    };
    var expand = function (s, extra) {
      for (var i = 0; i < 4 && /\{[^{}]+\}/.test(s); i++) {
        s = s.replace(/\{([^{}]+)\}/g, function (all, k) {
          if (extra && k in extra) return extra[k];
          if (k in v) return v[k];
          if (Array.isArray(B[k])) return B[k][Math.floor(R() * B[k].length)];
          return all;
        });
      }
      return s;
    };
    var lines = [];
    var add = function (k, key, extra) { lines.push({ k: k, t: expand(pick(B[key]), extra) }); };
    var title = '第 ' + (input.day || 1) + ' 回　' + expand(pick(B.章名));
    add('open', '開場');
    if (input.best && input.best.pct > 0) add('good', input.best.pct >= 0.02 ? '伙伴好' : '伙伴穩', { pct: pctTxt(input.best.pct) });
    if (input.worst && input.worst.pct < 0 && (!input.best || input.worst.name !== input.best.name)) add('bad', 'Boss', { pct: pctTxt(input.worst.pct) });
    var tp = input.todayPct || 0;
    add('result', tp > 0.001 ? '戰果好' : tp < -0.001 ? '戰果壞' : '戰果平', { pct: pctTxt(tp) });
    if (input.ath) add('event', '新高');
    [['exDiv', '除息'], ['buys', '買進'], ['sells', '賣出'], ['stops', '停損'], ['targets', '目標'], ['ach', '成就']].forEach(function (p) {
      var arr = input[p[0]]; if (arr && arr.length) add(p[0] === 'stops' ? 'warn' : 'event', p[1], { list: arr.join('、') });
    });
    if (R() < 0.6) lines.push({ k: 'misc', t: '※ ' + expand(pick(B.事件)) });
    add('hint', tp > 0.001 ? '提示好' : tp < -0.001 ? '提示壞' : '提示平');
    var opening = title.replace(/^第 \d+ 回　/, '') + '・' + v.天氣;
    return { world: world, title: title, lines: lines, used: used, opening: opening };
  }

  return { TERMS: TERMS, G: G, tell: tell, mood: mood, worlds: Object.keys(TERMS) };
});
