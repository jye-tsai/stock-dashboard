/* app.js — 主程式(原 index.html 內嵌 script)。§ 目錄見下方;圖表在 charts.js、純計算在 scripts/calc.js。 */
/* ============================================================
   胖虎的小財庫 — 主程式索引(用 § 搜尋可快速跳到各段)
   §1  全域狀態、常數、小工具      §10 市價更新(觸發 Action)
   §2  數字跳動動畫                §11 持股/年度編輯操作
   §3  計算(市值/損益)            §12 儲存 / 載入 / 快取
   §4  畫面 render                 §13 GitHub 同步
   §5  圖表繪製與風格              §14 檔案存取(存檔/選檔)
   §6  分頁切換                    §15 主題 / 圖表風格切換
   §7  編輯模式                    §16 下拉重新整理(PWA)
   §8  密碼(PBKDF2)              §17 啟動(splash + init)
   §9  解鎖 / 權限 UI
   ============================================================ */

/* ==================== §1. 全域狀態、常數、小工具 ==================== */
let DATA = null;
let editMode = false;
let holdSort = { key: null, dir: -1 };           // 持股表排序狀態
let navRangeDays = 90;                            // 資產走勢顯示筆數(交易日;0=全部;'ytd'=今年)
let HERO = null;                                  // render 算出的今日損益狀態(分享戰報用)
function sortHoldings(key) {
  if (holdSort.key === key) holdSort.dir *= -1;
  else { holdSort.key = key; holdSort.dir = -1; }
  if (DATA) render({ charts: false });
}
function setNavRange(d) {
  navRangeDays = d;
  document.querySelectorAll('.nav-range .btn').forEach(b => b.classList.toggle('primary', String(b.dataset.r) === String(d)));
  if (DATA) render();
}
// 點持股列展開/收合明細(點到輸入框/連結/按鈕時不觸發)
function toggleHoldDetail(tr, ev) {
  if (ev && ev.target.closest('input, select, button, a')) return;
  const d = tr.nextElementSibling;
  if (d && d.classList.contains('hold-detail')) d.style.display = d.style.display === 'none' ? '' : 'none';
}
let fsHandle = null;
const DEFAULT_TITLE = '股票庫存儀表板';
const EDIT_UNLOCK_MINUTES = 30;

// 數字格式:formatter 建一次重複用(toLocaleString 每次呼叫都重新解析 locale,數字跳動動畫每 frame 都在叫)
const NF0 = new Intl.NumberFormat('zh-TW');
const NF2 = new Intl.NumberFormat('zh-TW', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmt = n => NF0.format(Math.round(n));
const fmt2 = n => NF2.format(n);
const pct = n => (n * 100).toFixed(2) + '%';
const cls = n => n > 0 ? 'up' : n < 0 ? 'down' : '';
const sign = n => n > 0 ? '+' : '';
const esc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;');
// UTF-8 字串 → base64(GitHub Contents API 用);不靠已棄用的 unescape,也不 spread 大陣列免爆 call stack
const b64utf8 = s => btoa(Array.from(new TextEncoder().encode(s), b => String.fromCharCode(b)).join(''));
// localStorage 包一層:Safari 隱私模式 / 儲存空間滿會 throw,統一在這裡吞掉並留 debug 訊息
const store = {
  get(k) { try { return window.localStorage.getItem(k); } catch (e) { console.debug('[pf] storage get', k, e); return null; } },
  set(k, v) { try { window.localStorage.setItem(k, v); } catch (e) { console.debug('[pf] storage set', k, e); } },
  del(k) { try { window.localStorage.removeItem(k); } catch (e) { console.debug('[pf] storage del', k, e); } }
};
// 系統「減少動態效果」:數字不跳動、圖表不動畫、CSS 過場關掉(見 style 內 prefers-reduced-motion)
const REDUCED_MOTION = !!(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches);
if (REDUCED_MOTION && window.Chart) Chart.defaults.animation = false;   // 圖表動畫一併關(Chart.js 已先載入)

// 台北時間狀態(週末 / 開盤前 / 交易時段):render 的資料新鮮度標記與自動觸發更新市價共用
function tpeNow() {
  const t = new Date(Date.now() + 8 * 3600 * 1000);
  const z = n => String(n).padStart(2, '0');
  return { date: `${t.getUTCFullYear()}-${z(t.getUTCMonth() + 1)}-${z(t.getUTCDate())}`, dow: t.getUTCDay(), hh: t.getUTCHours(), mm: t.getUTCMinutes() };
}
const isWeekend = n => n.dow === 0 || n.dow === 6;
const isPreOpen = n => n.hh < 9 || (n.hh === 9 && n.mm < 10);                 // 排程 09:05 首跑,09:10 前不算「未更新」
const isTradingWindow = n => !isWeekend(n) && !isPreOpen(n) && (n.hh < 14 || (n.hh === 14 && n.mm <= 10));   // 到 14:00 收盤結算那輪為止

/* ==================== §2. 數字跳動動畫 ==================== */
const countCache = {};
function animateCounts() {
  document.querySelectorAll('#cards .value[data-count]').forEach(el => {
    const to = parseFloat(el.dataset.count) || 0;
    const signed = el.dataset.signed === '1';
    const key = el.dataset.key;
    const from = (key in countCache) ? countCache[key] : 0;
    countCache[key] = to;
    const finalText = (signed ? sign(to) : '') + fmt(to);
    if (from === to || REDUCED_MOTION) { el.textContent = finalText; return; }   // 值沒變(如換主題)或減少動態 → 直接落定
    const dur = 650, t0 = performance.now();
    const ease = x => 1 - Math.pow(1 - x, 3);
    const tick = now => {
      const p = Math.min(1, (now - t0) / dur);
      const v = from + (to - from) * ease(p);
      el.textContent = (signed ? sign(v) : '') + fmt(v);
      if (p < 1) requestAnimationFrame(tick);
      else el.textContent = finalText;
    };
    requestAnimationFrame(tick);
  });
}

/* ==================== §3. 計算(市值 / 損益 / 比例) ==================== */
// 計算邏輯在 scripts/calc.js(UMD),與 GitHub Action 的 update-prices.mjs 共用同一份;
// 改手續費 / 稅率 / 四捨五入只改那裡,history 的 un / ret 才會跟畫面一致
const compute = d => PfCalc.compute(d);

/* ==================== §4. 畫面 render(卡片 / 持股表 / 標題) ==================== */
// 下一幀執行;背景分頁 / 視窗被遮住時 requestAnimationFrame 會暫停,所以 300ms 內沒輪到就用 setTimeout 補跑,兩者只跑一次
function deferFrame(fn) {
  let done = false;
  const run = () => { if (done) return; done = true; fn(); };
  requestAnimationFrame(run);
  setTimeout(run, 300);
}
// Hero 右側小走勢:近 30 個交易日總市值(全史,不受區間鈕影響);不足 2 點回空字串
function heroSparkSvg() {
  const full = PfCalc.histSlices(DATA && DATA.history, 0, tpeNow().date).full.slice(-30);
  if (full.length < 2) return '';
  const vals = full.map(p => Number(p.mv) || 0), lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
  const w = 240, h = 56, n = vals.length;
  const pt = (v, i) => `${(i / (n - 1) * w).toFixed(1)},${(h - 3 - (v - lo) / span * (h - 8)).toFixed(1)}`;
  const line = vals.map(pt).join(' ');
  const area = `M0,${h} L${line.replace(/ /g, ' L')} L${w},${h} Z`;
  const chg = vals[0] ? (vals[n - 1] / vals[0] - 1) * 100 : 0, dir = chg >= 0 ? 'up' : 'down';
  const from = String(full[0].date).slice(5), to = String(full[n - 1].date).slice(5);
  return `<div class="hero-spark ${dir}" title="近 ${n} 個交易日總市值 ${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%">
      <div class="k"><span>總市值 近 ${n} 日</span><span class="${dir}">${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%</span></div>
      <svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="近 ${n} 個交易日總市值走勢 ${from} 到 ${to}">
        <defs><linearGradient id="hsg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="currentColor" stop-opacity=".35"/><stop offset="1" stop-color="currentColor" stop-opacity="0"/></linearGradient></defs>
        <path d="${area}" fill="url(#hsg)"/><polyline points="${line}" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>
      </svg></div>`;
}
function render(opts) {
  const d = DATA;
  const withCharts = !(opts && opts.charts === false);   // 只動表格(排序 / 隱藏零股)時不重畫圖表
  const { rows, t } = compute(d);
  const realized = d['已實現損益'] || 0;
  const dividend = d['股息收入'] || 0;
  const totalPL = realized + t.unrealized + dividend;
  const E = editMode;
  const title = d.title || DEFAULT_TITLE;
  d.title = title;
  document.title = title;
  // 胖虎表情:拿「今天的未實現損益」跟「昨天(上一個交易日)的未實現損益」比 —— 變好→笑、變差→哭、持平→淡定
  // 還沒有昨天的歷史資料時,先看當前未實現損益的正負
  const histArr = Array.isArray(d.history) ? d.history : [];
  const today = String(d.priceUpdated || d.updated || '').slice(0, 10);
  let prevDay = null;
  for (let i = histArr.length - 1; i >= 0; i--) {
    if (histArr[i] && histArr[i].date && histArr[i].date !== today) { prevDay = histArr[i]; break; }
  }
  let moodVal;
  if (prevDay && typeof prevDay.un === 'number') moodVal = t.unrealized - prevDay.un;        // 跟昨日未實現損益比
  else if (prevDay && typeof prevDay.mv === 'number') moodVal = t.mv - prevDay.mv;            // 舊資料沒存 un,退而比市值
  else moodVal = t.unrealized;                                                                // 沒有昨天資料 → 看當前未實現
  const moodSrc = moodVal > 0 ? 'panghu.webp' : moodVal < 0 ? 'panghu-sad.webp' : 'panghu-flat.webp';
  const moodTip = moodVal > 0 ? '今天比昨天賺😆' : moodVal < 0 ? '今天比昨天賠😢' : '跟昨天持平😐';
  const mascotImg = `<img class="brand-icon mascot" src="${moodSrc}" alt="胖虎" title="${moodTip}" onerror="if(this.src.indexOf('panghu.webp')<0){this.src='panghu.webp'}else{this.replaceWith(Object.assign(document.createElement('span'),{className:'brand-icon',textContent:'📊'}))}">`;
  document.getElementById('dashboard-title').innerHTML = E
    ? `${mascotImg}<input class="title-input" data-path="title" value="${esc(title)}" maxlength="40" title="會儲存到 data.json 的 title 欄位">`
    : `${mascotImg}<span class="brand-title-text">${esc(title)}</span>`;
  // 賺錢時胖虎跳一下,每次開頁最多一次:動畫真的播完(animationend)才記「跳過了」,
  // 不然快取先畫、網路再畫的第二次 render 會把還沒跳的 img 換掉,等於沒跳
  if (moodVal > 0 && !render._hopped) {
    const m = document.querySelector('img.mascot');
    if (m) { m.classList.add('happy'); m.addEventListener('animationend', () => { render._hopped = true; }, { once: true }); }
  }

  // 更新時間 + 資料新鮮度提示(以台北時間判斷;週末/開盤前不算過期)
  const upEl = document.getElementById('updated');
  const pu = d.priceUpdated || d.updated || '';
  if (pu) {
    const n = tpeNow();
    const puDate = String(pu).slice(0, 10);
    let tag = '';
    if (puDate === n.date) tag = ' <span title="今日已更新" class="fresh-ok">●</span>';
    else if (isWeekend(n)) tag = ' <span class="fresh-muted">・週末休市</span>';
    else if (isPreOpen(n)) tag = ' <span class="fresh-muted">・開盤前</span>';
    else tag = ' <span title="今日尚未收到更新,排程可能漏跑" class="fresh-warn">⚠ 資料可能未更新</span>';
    upEl.innerHTML = '更新時間:' + esc(pu) + tag;
  } else {
    upEl.textContent = '更新時間:-';
  }
  const puEl = document.getElementById('price-updated');
  if (puEl) puEl.textContent = d.priceUpdated
    ? `📈 市價更新時間:${d.priceUpdated}(台北時間，由 GitHub Action 更新）`
    : '📈 市價更新時間：尚未更新（按「更新市價」或等開盤時段自動更新後，此處會顯示時間）';
  document.body.classList.toggle('editing', E);
  document.querySelectorAll('.edit-only').forEach(el => el.classList.toggle('hidden', !E));

  // Hero:今日損益(各檔 prevClose 加總;缺 prevClose 退回 history 前一交易日市值差,都沒有就整塊隱藏)
  const TC = PfCalc.todayChange(rows, prevDay, t.mv, tpeNow().date);              // 各檔昨收加總;缺昨收退回 history 前一交易日市值差
  const heroChg = TC ? TC.chg : null, heroBase = TC ? TC.base : 0, heroMissing = TC ? TC.missing : 0;
  const heroPanel = document.getElementById('hero-panel');
  if (heroPanel) {
    if (heroChg == null) { heroPanel.style.display = 'none'; HERO = null; }
    else {
      heroPanel.style.display = '';
      const heroPct = heroBase ? heroChg / heroBase : 0;
      const heroRate = t.costAmt ? totalPL / t.costAmt : 0;
      HERO = { heroChg, heroPct, heroMissing, totalPL, heroRate, mv: t.mv };
      document.getElementById('hero').innerHTML = `
      <div class="hero-main">
        <div class="label">今日損益${TC && TC.exDivCount ? `<span class="fresh-muted" title="除息日的價差不算虧損,昨收已扣掉股息">(${TC.exDivCount} 檔除息已調整)</span>` : ''}</div>
        <div class="hero-num ${cls(heroChg)}">${sign(heroChg)}${fmt(heroChg)} <span class="hero-pct">(${sign(heroPct)}${pct(heroPct)}${heroMissing ? `,${heroMissing} 檔缺昨收未計` : ''})</span></div>
      </div>
      </div>${heroSparkSvg()}`;                  // 右側:近 30 日總市值小走勢;總市值 / 總報酬看正下方的摘要卡片列
    }
  }

  // 摘要卡片(編輯模式下 已實現損益/股息收入 可改)
  const numIn = (path, val) => `<input class="ed" type="number" step="any" data-path="${path}" value="${val}">`;
  // [label, 顯示值, 著色值, 副標, 原始數值, 是否帶正負號]
  const cards = [
    ['總市值', fmt(t.mv), null, null, t.mv, false],
    ['總成本', fmt(t.costAmt), null, null, t.costAmt, false],
    ['未實現損益', sign(t.unrealized) + fmt(t.unrealized), t.unrealized, sign(t.unrealized) + pct(t.costAmt ? t.unrealized / t.costAmt : 0), t.unrealized, true],
    ['已實現損益', E ? numIn('已實現損益', realized) : sign(realized) + fmt(realized), realized, null, realized, true],
    ['股息收入', E ? numIn('股息收入', dividend) : fmt(dividend), dividend, null, dividend, false],
    ['總損益', sign(totalPL) + fmt(totalPL), totalPL, null, totalPL, true]
  ];
  // 帳戶資訊小卡(解鎖後顯示;編輯模式沿用 data-path 寫回 account.*)
  const acc = d.account || (d.account = {});
  const accCardsHtml = (() => {
    const item = (label, key) => {
      const val = acc[key] || 0;
      const shown = E ? `<input class="ed" type="number" step="any" data-path="account.${key}" value="${val}">` : (val > 0 ? '+' : '') + fmt(val);
      return `<div class="card acct sec-protected"><div class="label">${label}</div><div class="value ${cls(val)}">${shown}</div></div>`;
    };
    const avail = (acc['餘額'] || 0) + (acc['交割款T1'] || 0) + (acc['交割款T2'] || 0);
    return item('帳戶餘額', '餘額') + item('交割款項 T+1', '交割款T1') + item('交割款項 T+2', '交割款T2')
      + `<div class="card acct sec-protected"><div class="label">可用餘額</div><div class="value ${cls(avail)}">${(avail > 0 ? '+' : '') + fmt(avail)}</div></div>`;
  })();
  document.getElementById('cards').innerHTML = cards.map(([label, val, colorVal, sub, raw, signed]) => {
    const cnt = String(val).includes('<input') ? '' : ` data-count="${raw}" data-signed="${signed ? 1 : 0}" data-key="${label}"`;
    return `
    <div class="card">
      <div class="label">${label}</div>
      <div class="value ${colorVal === null ? '' : cls(colorVal)}"${cnt}>${val}</div>
      ${sub ? `<div class="sub ${cls(colorVal)}">${sub}</div>` : ''}
    </div>`;
  }).join('') + accCardsHtml;
  animateCounts();

  // 持股表
  const hideZero = document.getElementById('hide-zero').checked && !E;
  const types = Object.keys(d.fees.taxRates);
  const OPT_COLS = new Set(['sellCost', 'costPctOfTotal', 'mvPctOfTotal']);   // 平常用不到的欄,預設收起(CSS .col-opt)
  const cols = [['類型','type'],['代號','code'],['名稱','name'],['成本','cost'],['市價','price'],['走勢','spark'],['張數','lots'],['成本金額','costAmt'],['市值','mv'],['賣出(稅+費)','sellCost'],['未實現損益','unrealized'],['損益比例','plRatio'],['成本比例','costPctOfTotal'],['市值比例','mvPctOfTotal'],['更新時間','priceTime']];
  const headHtml = cols.map(([label, key]) => {
    if (key === 'spark') return `<th title="近 30 個交易日收盤走勢(由 Action 寫入 history[].prices)">${label}</th>`;
    const arrow = holdSort.key === key ? (holdSort.dir < 0 ? ' ▼' : ' ▲') : '';
    return `<th class="th-sort${OPT_COLS.has(key) ? ' col-opt' : ''}" data-action="sortHoldings" data-args='["${key}"]' title="點擊排序">${label}${arrow}</th>`;
  }).join('') + (E ? '<th></th>' : '');
  const ptimeCell = r => `<td title="${r.priceTime ? esc(r.priceTime) : '尚未由 Action 更新'}" class="ptime">${r.priceTime ? esc(r.priceTime.slice(5)) : '—'}</td>`;
  // 今日漲跌%(相對昨收 prevClose;缺昨收就不顯示)
  const todayChg = r => (r.prevClose > 0 && r.price > 0) ? (r.price - r.prevClose) / r.prevClose : null;
  const todayHtml = r => { const c = todayChg(r); return c == null ? '' : `<div class="today-chg ${c > 0 ? 'up' : c < 0 ? 'down' : ''}" title="相對昨收 ${fmt2(r.prevClose)}">今日 ${c > 0 ? '+' : ''}${(c * 100).toFixed(2)}%</div>`; };
  // 近 30 個交易日小走勢:history[].prices[code](Action 每日寫入 + 回補);不足 2 點就空白。回傳 svg 字串
  const sparkSvg = r => {
    // 近 30 個交易日:個股(漲紅跌綠)+ 同期加權指數(灰虛線,同起點正規化);沒 prices 資料就空白
    const S = PfCalc.sparkSeries(histArr, r.code, 30); if (!S) return '';
    const w = 72, hgt = 22, n = S.pts.length;
    const norm = (arr, base) => arr.map(v => v > 0 ? v / base - 1 : null);
    const me = norm(S.pts, S.pts[0]);
    const tBase = S.taiex.find(v => v > 0);
    const tw = tBase ? norm(S.taiex, tBase) : null;
    const all = me.concat(tw ? tw.filter(v => v != null) : []);
    const lo = Math.min(...all), hi = Math.max(...all), span = hi - lo || 1e-9;
    const path = arr => arr.map((v, i) => v == null ? null : `${(i / (n - 1) * w).toFixed(1)},${(hgt - 2 - (v - lo) / span * (hgt - 4)).toFixed(1)}`).filter(Boolean).join(' ');
    const meP = me[n - 1] * 100, twP = tw && tw[n - 1] != null ? tw[n - 1] * 100 : null;
    const pctTxt = v => (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
    const title = `近 ${n} 個交易日 ${pctTxt(meP)}${twP != null ? `(大盤 ${pctTxt(twP)})` : ''}`;
    return `<svg class="spark-svg ${meP >= 0 ? 'up' : 'down'}" viewBox="0 0 ${w} ${hgt}" width="${w}" height="${hgt}" role="img" aria-label="${title}"><title>${title}</title>`
      + (tw ? `<polyline class="spark-tw" points="${path(tw)}" fill="none" stroke-width="1" stroke-dasharray="2 2"/>` : '')
      + `<polyline points="${path(me)}" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
  };
  // 排序(僅檢視模式;編輯模式維持原順序,避免欄位索引錯位)
  if (holdSort.key && !E) {
    const k = holdSort.key, dir = holdSort.dir;
    rows.sort((a, b) => {
      const va = a[k], vb = b[k];
      if (typeof va === 'string' || typeof vb === 'string') return dir * String(va == null ? '' : va).localeCompare(String(vb == null ? '' : vb), 'zh-Hant', { numeric: true });
      return dir * ((va || 0) - (vb || 0));
    });
  }
  document.getElementById('holdings').innerHTML =
    '<tr>' + headHtml + '</tr>' +
    rows.map((r, i) => {
      if (hideZero && r.lots <= 0) return '';
      const hitTarget = r.target > 0 && r.price >= r.target;
      const hitStop = r.stop > 0 && r.price <= r.stop;
      const hitClass = hitTarget ? 'hit-target' : hitStop ? 'hit-stop' : '';
      const flag = hitTarget ? ' 🎯' : hitStop ? ' ⚠️' : '';
      const cells = E ? `
        <td><select class="ed narrow" data-path="holdings.${i}.type">${types.map(tp => `<option ${tp===r.type?'selected':''}>${tp}</option>`).join('')}</select></td>
        <td><input class="ed narrow" data-path="holdings.${i}.code" value="${esc(r.code)}"></td>
        <td><input class="ed wide" data-path="holdings.${i}.name" value="${esc(r.name)}"></td>
        <td><input class="ed" type="number" step="any" data-path="holdings.${i}.cost" value="${r.cost}"></td>
        <td><input class="ed" type="number" step="any" data-path="holdings.${i}.price" value="${r.price}"></td>
        <td></td>
        <td><input class="ed" type="number" step="any" data-path="holdings.${i}.lots" value="${r.lots}"></td>` : `
        <td><span class="tag">${esc(r.type)}</span></td><td><a class="code-link" href="https://tw.stock.yahoo.com/quote/${encodeURIComponent(r.code)}" target="_blank" rel="noopener" title="在 Yahoo 股市開啟 ${esc(r.code)}">${esc(r.code)}</a></td><td>${esc(r.name)}${flag}</td>
        <td>${fmt2(r.cost)}</td><td>${fmt2(r.price)}${todayHtml(r)}</td><td class="spark">${sparkSvg(r)}</td><td>${r.lots.toLocaleString('zh-TW',{minimumFractionDigits:3})}</td>`;
      const sellNet = r.mv - r.sellCost;
      const colspan = cols.length + (E ? 1 : 0);
      const dstat = (k, v) => `<span class="d-stat"><span class="d-k">${k}</span><span class="d-v">${v}</span></span>`;
      let detailInner;
      if (E) {
        detailInner = `<span class="d-stat"><span class="d-k">🎯 目標價</span><input class="ed narrow" type="number" step="any" data-path="holdings.${i}.target" value="${r.target || ''}"></span>`
          + `<span class="d-stat"><span class="d-k">⚠️ 停損價</span><input class="ed narrow" type="number" step="any" data-path="holdings.${i}.stop" value="${r.stop || ''}"></span>`
          + dstat('賣出可拿回', fmt(sellNet));
      } else {
        const toT = r.target > 0 ? (r.price >= r.target ? '已達標 🎯' : '距目標 ' + pct((r.target - r.price) / r.price)) : '';
        const toS = r.stop > 0 ? (r.price <= r.stop ? '已觸停損 ⚠️' : '距停損 ' + pct((r.price - r.stop) / r.price)) : '';
        detailInner = dstat('賣出可拿回', fmt(sellNet))
          + dstat('🎯 目標價', r.target > 0 ? `${fmt2(r.target)}　${toT}` : '—')
          + dstat('⚠️ 停損價', r.stop > 0 ? `${fmt2(r.stop)}　${toS}` : '—');
      }
      return `<tr class="hold-row ${hitClass}" data-action="toggleHoldDetail">${cells}
        <td>${fmt(r.costAmt)}</td><td>${fmt(r.mv)}</td><td class="col-opt">${fmt(r.sellCost)}</td>
        <td class="${cls(r.unrealized)}">${sign(r.unrealized)}${fmt(r.unrealized)}</td>
        <td class="${cls(r.unrealized)}">${pct(r.plRatio)}</td>
        <td class="col-opt">${pct(r.costPctOfTotal)}</td><td class="col-opt">${pct(r.mvPctOfTotal)}</td>
        ${ptimeCell(r)}
        ${E ? `<td><button class="btn sm danger" data-action="delHolding" data-args='[${i}]'>🗑</button></td>` : ''}
      </tr>
      <tr class="hold-detail" style="display:${E ? '' : 'none'}"><td colspan="${colspan}">${detailInner}</td></tr>`;
    }).join('') +
    `<tr class="total"><td colspan="7">合計</td>
      <td>${fmt(t.costAmt)}</td><td>${fmt(t.mv)}</td><td class="col-opt">${fmt(t.sellCost)}</td>
      <td class="${cls(t.unrealized)}">${sign(t.unrealized)}${fmt(t.unrealized)}</td>
      <td class="${cls(t.unrealized)}">${pct(t.costAmt ? t.unrealized / t.costAmt : 0)}</td>
      <td class="col-opt">100.00%</td><td class="col-opt">100.00%</td><td></td>${E ? '<td></td>' : ''}</tr>`;

  // 持股卡片(手機檢視模式)
  const stat = (k, v, c2) => `<div class="h-stat"><span class="k">${k}</span><span class="v ${c2 || ''}">${v}</span></div>`;
  document.getElementById('holdings-cards').innerHTML =
    rows.filter(r => !(hideZero && r.lots <= 0)).map(r => `
    <div class="h-card">
      <div class="h-top">
        <span class="tag">${esc(r.type)}</span>
        <a class="code-link" href="https://tw.stock.yahoo.com/quote/${encodeURIComponent(r.code)}" target="_blank" rel="noopener">${esc(r.code)}</a>
        <span class="h-name">${esc(r.name)}${r.target > 0 && r.price >= r.target ? ' 🎯' : r.stop > 0 && r.price <= r.stop ? ' ⚠️' : ''}</span>
        <span class="h-ratio ${cls(r.unrealized)}">${sign(r.unrealized)}${pct(r.plRatio)}</span>
        ${sparkSvg(r)}
      </div>
      <div class="h-stats">
        ${stat('市價', fmt2(r.price))}
        ${todayChg(r) != null ? stat('今日', `<span class="${todayChg(r) > 0 ? 'up' : todayChg(r) < 0 ? 'down' : ''}">${todayChg(r) > 0 ? '+' : ''}${(todayChg(r) * 100).toFixed(2)}%</span>`) : ''}
        ${stat('成本', fmt2(r.cost))}
        ${stat('張數', r.lots.toLocaleString('zh-TW', { minimumFractionDigits: 3 }))}
        ${stat('市值', fmt(r.mv))}
        ${stat('未實現損益', sign(r.unrealized) + fmt(r.unrealized), cls(r.unrealized))}
        ${stat('市值比例', pct(r.mvPctOfTotal))}
        ${stat('更新時間', r.priceTime ? r.priceTime.slice(5) : '—')}
        ${r.target > 0 ? stat('🎯 目標', fmt2(r.target) + (r.price >= r.target ? ' 已達' : '')) : ''}
        ${r.stop > 0 ? stat('⚠️ 停損', fmt2(r.stop) + (r.price <= r.stop ? ' 觸及' : '')) : ''}
      </div>
    </div>`).join('') + `
    <div class="h-card h-total">
      <div class="h-top">
        <span class="h-name">合計</span>
        <span class="h-ratio ${cls(t.unrealized)}">${sign(t.unrealized)}${pct(t.costAmt ? t.unrealized / t.costAmt : 0)}</span>
      </div>
      <div class="h-stats">
        ${stat('總市值', fmt(t.mv))}
        ${stat('總成本', fmt(t.costAmt))}
        ${stat('未實現損益', sign(t.unrealized) + fmt(t.unrealized), cls(t.unrealized))}
        ${stat('賣出稅費', fmt(t.sellCost))}
      </div>
    </div>`;

  // 年度表
  const ys = d.yearly || [];
  document.getElementById('yearly').innerHTML =
    `<tr><th>年度</th><th>資本利得</th><th>股息收入</th><th>備註</th>${E ? '<th></th>' : ''}</tr>` +
    ys.map((y, i) => E ? `<tr>
        <td><input class="ed narrow" data-path="yearly.${i}.year" value="${esc(y.year)}"></td>
        <td><input class="ed" type="number" step="any" data-path="yearly.${i}.capitalGain" value="${y.capitalGain}"></td>
        <td><input class="ed" type="number" step="any" data-path="yearly.${i}.dividend" value="${y.dividend || 0}"></td>
        <td><input class="ed narrow" data-path="yearly.${i}.note" value="${esc(y.note || '')}"></td>
        <td><button class="btn sm danger" data-action="delYear" data-args='[${i}]'>🗑</button></td>
      </tr>` : `<tr><td>${esc(y.year)}</td>
        <td class="${cls(y.capitalGain)}">${fmt(y.capitalGain)}</td>
        <td>${y.dividend ? fmt(y.dividend) : '-'}</td><td>${esc(y.note || '')}</td></tr>`).join('') +
    `<tr class="total"><td>總計</td>
      <td class="${cls(ys.reduce((s,y)=>s+y.capitalGain,0))}">${fmt(ys.reduce((s,y)=>s+y.capitalGain,0))}</td>
      <td>${fmt(ys.reduce((s,y)=>s+(y.dividend||0),0))}</td><td></td>${E ? '<td></td>' : ''}</tr>`;

  // 圖表延到下一幀:Hero / 卡片 / 表格先上畫面;#app 顯示後 canvas 才有真實尺寸,不會先畫 0×0 再 resize
  if (withCharts) deferFrame(() => { if (DATA) drawCharts(rows.filter(r => r.mv > 0), ys); });
  updateFavicon(title);
  updateMiniHero();
  document.getElementById('loader').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');
  restoreActiveTab();
  if (typeof hideSplash === 'function') hideSplash();
}

/* ==================== §6. 分頁切換 ==================== */
function switchTab(tab) {
  document.querySelectorAll('.tab-page').forEach(el => el.classList.toggle('active', el.id === 'tab-' + tab));
  document.querySelectorAll('.tab-btn, .bnav-btn').forEach(btn => btn.classList.toggle('active', btn.dataset.tab === tab));
  store.set('pf-active-tab', tab);
  if (tab === 'overview') {
    setTimeout(resizeAllCharts, 60);
  }
}

function restoreActiveTab() {
  let tab = 'overview';
  tab = store.get('pf-active-tab') || 'overview';
  if (!document.getElementById('tab-' + tab)) tab = 'overview';
  if (tab === 'yearly' && !isUnlocked()) tab = 'overview';  // 年度紀錄需解鎖
  switchTab(tab);
}

/* ==================== §7. 編輯模式 ==================== */
async function sha256Text(text) {
  const data = new TextEncoder().encode(text);
  const hash = await crypto.subtle.digest('SHA-256', data);
  return Array.from(new Uint8Array(hash)).map(b => b.toString(16).padStart(2, '0')).join('');
}

/* ==================== §8. 密碼:PBKDF2-SHA256 + 隨機鹽(相容舊版 SHA-256) ==================== */
const PBKDF2_ITER = 210000;
const b64enc = arr => btoa(String.fromCharCode(...new Uint8Array(arr)));
const b64dec = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));

// data.json 混淆：固定金鑰 AES-256-GCM（與 scripts/update-prices.mjs 相同）。
// 目的：網站對所有人正常顯示，但 repo 上的 data.json 不是明文。金鑰在公開程式內＝防君子不防小人。
const OBF_KEY_B64 = '3Nr6TNQZewwC/3wye+lwc60BCeWcaPRmQddHyAbS+uc=';
let _obfKey = null;
async function obfKey() { return _obfKey || (_obfKey = await crypto.subtle.importKey('raw', b64dec(OBF_KEY_B64), { name: 'AES-GCM' }, false, ['encrypt', 'decrypt'])); }
async function encData(obj) {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ct = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, await obfKey(), new TextEncoder().encode(JSON.stringify(obj)));
  return { enc: 1, iv: b64enc(iv), ct: b64enc(ct) };
}
async function decData(o) {
  const pt = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: b64dec(o.iv) }, await obfKey(), b64dec(o.ct));
  return JSON.parse(new TextDecoder().decode(pt));
}
async function decodeMaybe(x) { return (x && x.enc === 1) ? await decData(x) : x; }
async function pbkdf2Hash(pwd, saltBytes, iter) {
  const km = await crypto.subtle.importKey('raw', new TextEncoder().encode(pwd), 'PBKDF2', false, ['deriveBits']);
  const bits = await crypto.subtle.deriveBits({ name: 'PBKDF2', salt: saltBytes, iterations: iter, hash: 'SHA-256' }, km, 256);
  return b64enc(bits);
}
async function verifyPassword(pwd) {
  const a = DATA && DATA.auth;
  if (a && a.salt && a.hash) {
    try { return (await pbkdf2Hash(pwd, b64dec(a.salt), a.iter || PBKDF2_ITER)) === a.hash; }
    catch (e) { return false; }
  }
  // 舊版相容:無加鹽 SHA-256(data.json 的 passwordHash)
  if (DATA && DATA.passwordHash) {
    try { return (await sha256Text(pwd)) === DATA.passwordHash; } catch (e) { return false; }
  }
  // 完全沒設密碼(全新 data.json):放行並提醒去設定。
  // 舊版的內建預設雜湊已移除:寫在公開 repo 裡的固定密碼等於沒鎖,還多一個可離線暴力破解的目標
  toast('⚠ 這份資料尚未設定密碼,請到 ⚙️ 設定 → 🔑 設定密碼');
  return true;
}
// 設定新密碼:升級為 PBKDF2 並移除舊的弱雜湊
// 通用確認視窗(取代 confirm),回傳 Promise<boolean>
let _confirmResolve = null;
function uiConfirm(msg) {
  return new Promise(resolve => {
    _confirmResolve = resolve;
    document.getElementById('confirm-msg').textContent = msg;
    document.getElementById('confirm-modal').classList.remove('hidden');
  });
}
function closeConfirm(ok) {
  document.getElementById('confirm-modal').classList.add('hidden');
  const r = _confirmResolve; _confirmResolve = null;
  if (r) r(!!ok);
}

// 觸控裝置(手機/平板)用數字鍵盤;桌機(滑鼠)用一般鍵盤打字
const IS_TOUCH = !!(window.matchMedia && window.matchMedia('(pointer: coarse)').matches);
function applyKeypadMode(scopeId, inputId) {
  const kp = document.querySelector('#' + scopeId + ' .keypad');
  if (kp) kp.style.display = IS_TOUCH ? 'grid' : 'none';
  const inp = document.getElementById(inputId);
  if (inp) {
    inp.readOnly = IS_TOUCH;                            // 手機:唯讀,只用鍵盤盤
    if (!IS_TOUCH) setTimeout(() => inp.focus(), 60);   // 桌機:自動聚焦,直接打字
  }
}

// 設定新密碼(數字鍵盤,兩步驟:輸入 → 確認)
let _setpwdStep = 1, _setpwdFirst = '';
function setpwdReset() {
  _setpwdStep = 1; _setpwdFirst = '';
  document.getElementById('setpwd-input').value = '';
  document.getElementById('setpwd-input').placeholder = '輸入新密碼';
  document.getElementById('setpwd-title').textContent = '🔑 設定新密碼(至少 6 碼)';
  document.getElementById('setpwd-next').textContent = '下一步';
  document.getElementById('setpwd-err').textContent = '';
}
async function setPassword() {
  if (!isUnlocked() && !(await verifyEditPassword())) return;
  setpwdReset();
  document.getElementById('setpwd-modal').classList.remove('hidden');
  applyKeypadMode('setpwd-modal', 'setpwd-input');
}
function closeSetPwd() { document.getElementById('setpwd-modal').classList.add('hidden'); }
async function setpwdNext() {
  const inp = document.getElementById('setpwd-input');
  const err = document.getElementById('setpwd-err');
  const v = inp.value;
  if (_setpwdStep === 1) {
    if (v.length < 6) { err.textContent = '密碼至少 6 碼'; return; }
    _setpwdFirst = v; _setpwdStep = 2;
    inp.value = ''; inp.placeholder = '再輸入一次';
    document.getElementById('setpwd-title').textContent = '🔑 再輸入一次確認';
    document.getElementById('setpwd-next').textContent = '儲存密碼';
    err.textContent = '';
    return;
  }
  if (v !== _setpwdFirst) { err.textContent = '兩次不一致,請重新設定'; setpwdReset(); return; }
  try {
    const salt = crypto.getRandomValues(new Uint8Array(16));
    DATA.auth = { alg: 'PBKDF2-SHA256', salt: b64enc(salt), iter: PBKDF2_ITER, hash: await pbkdf2Hash(v, salt, PBKDF2_ITER) };
    delete DATA.passwordHash;
    cache();
    closeSetPwd();
    toast('✅ 密碼已更新,記得按「💾 儲存 JSON」寫回');
  } catch (e) { err.textContent = '此瀏覽器不支援加密 API'; }
}

// 用頁面內視窗輸入密碼(手機/PWA 比原生 prompt 穩);回傳 Promise<boolean>
let _pwdResolve = null;
async function verifyEditPassword() {
  try {
    const unlockedUntil = Number(sessionStorage.getItem('pf-edit-unlocked-until') || 0);
    if (Date.now() < unlockedUntil) return true;
  } catch (e) { console.debug('[pf]', e); }
  return new Promise(resolve => {
    _pwdResolve = resolve;
    const inp = document.getElementById('pwd-input');
    const err = document.getElementById('pwd-err');
    if (inp) inp.value = '';
    if (err) err.textContent = '';
    document.getElementById('pwd-modal').classList.remove('hidden');
    applyKeypadMode('pwd-modal', 'pwd-input');
  });
}
// 數字鍵盤輸入(點按,不叫出系統鍵盤);id 預設解鎖欄位,可傳 setpwd-input
function pinKey(k, id) {
  const inp = document.getElementById(id || 'pwd-input');
  if (!inp) return;
  if (k === 'back') inp.value = inp.value.slice(0, -1);
  else if (k === 'clear') inp.value = '';
  else if (inp.value.length < 20) inp.value += k;
  const err = document.getElementById(id === 'setpwd-input' ? 'setpwd-err' : 'pwd-err');
  if (err) err.textContent = '';
}
async function submitPwd() {
  const pwd = document.getElementById('pwd-input').value;
  if (await verifyPassword(pwd)) {
    try { sessionStorage.setItem('pf-edit-unlocked-until', String(Date.now() + EDIT_UNLOCK_MINUTES * 60 * 1000)); } catch (e) { console.debug('[pf]', e); }
    closePwdModal(true);
  } else {
    const err = document.getElementById('pwd-err');
    if (err) err.textContent = '密碼錯誤,請再試一次';
    const inp = document.getElementById('pwd-input');
    if (inp) inp.value = '';
  }
}
function closePwdModal(ok) {
  document.getElementById('pwd-modal').classList.add('hidden');
  const r = _pwdResolve; _pwdResolve = null;
  if (ok) updateAuthUI();
  if (r) r(!!ok);
}

/* ==================== §9. 解鎖 / 權限 UI(解鎖後才顯示 編輯/載入/GitHub) ==================== */
function isUnlocked() {
  try { return Date.now() < Number(sessionStorage.getItem('pf-edit-unlocked-until') || 0); }
  catch (e) { return false; }
}
function updateAuthUI() {
  const ok = isUnlocked();
  document.querySelectorAll('.auth-only').forEach(el => el.classList.toggle('hidden', !ok));
  document.getElementById('unlock-btn').classList.toggle('hidden', ok);
  const wasLocked = document.body.classList.contains('locked');
  document.body.classList.toggle('locked', !ok);
  // 解鎖瞬間,隱藏的圖表(年度損益)需要重畫一次才能正確顯示尺寸
  if (wasLocked && ok && DATA) render();
}
async function unlockUI() {
  if (await verifyEditPassword()) toast('🔓 已解鎖');
}
function lockUI() {
  try { sessionStorage.removeItem('pf-edit-unlocked-until'); } catch (e) { console.debug('[pf]', e); }
  if (editMode) {
    editMode = false;
    document.getElementById('edit-btn').textContent = '✏️ 編輯';
    document.getElementById('save-btn').classList.add('hidden');
  }
  updateAuthUI();
  if (DATA) render();
  toast('🔒 已登出');
}

/* ==================== §10. 市價更新:一律由 GitHub Action 伺服器端處理 ==================== */
// 按下「更新市價」→ 觸發 GitHub Action 在伺服器端抓價並寫回 data.json。
// 瀏覽器受 CORS 限制無法自己抓(證交所/櫃買/Yahoo 都不允許跨站讀取),所以改由 Action 代勞;
// 約 1 分鐘後 Action 會 commit 新價,重新整理頁面即可看到。
async function updatePrices() {
  const c = ghCfg();
  if (!ghReady(c)) {
    toast('市價改由 GitHub Action 自動更新;請先設定 GitHub 同步(⚙️),或到 repo 的 Actions 分頁手動執行');
    return;
  }
  if (!await uiConfirm('將觸發 GitHub Action 於伺服器端更新市價並寫回 data.json。\n約 1 分鐘後重新整理頁面即可看到最新價。\n\n要現在執行嗎?')) return;
  try {
    toast('正在觸發 GitHub Action…');
    const url = `https://api.github.com/repos/${c.owner}/${c.repo}/actions/workflows/update-prices.yml/dispatches`;
    const r = await fetch(url, {
      method: 'POST',
      headers: ghHeaders(c),
      body: JSON.stringify({ ref: c.branch || 'main' })
    });
    if (r.status === 204) {
      toast('✅ 已觸發更新,約 1 分鐘後重新整理即可看到新價');
      return;
    }
    const msg = (await r.json().catch(() => ({}))).message || ('HTTP ' + r.status);
    if (r.status === 401) throw new Error('Token 無效或已過期');
    if (r.status === 403) throw new Error('Token 需要 Actions 寫入權限(fine-grained 勾「Actions 讀寫」,或 classic 勾 workflow)');
    if (r.status === 404) throw new Error('找不到 update-prices.yml,請先把 .github/workflows/update-prices.yml 上傳到 repo 並推到預設分支');
    throw new Error(msg);
  } catch (e) {
    toast('❌ 觸發失敗:' + e.message);
  }
}

// 刷新時自動觸發更新市價（靜默、不跳確認；60 秒內不重複觸發）
async function autoTriggerPrices(c) {
  try {
    if (!ghReady(c)) return;
    if (!isTradingWindow(tpeNow())) return;      // 盤後 / 週末 / 09:10 前不浪費 Action(腳本本身也會擋,這裡省掉 dispatch)
    const last = +(store.get('pf-autoprice-ts') || 0);
    if (Date.now() - last < 60000) return;
    store.set('pf-autoprice-ts', String(Date.now()));
    const url = `https://api.github.com/repos/${c.owner}/${c.repo}/actions/workflows/update-prices.yml/dispatches`;
    const r = await fetch(url, { method: 'POST', headers: ghHeaders(c), body: JSON.stringify({ ref: c.branch || 'main' }) });
    if (r.status === 204) toast('📈 已自動觸發更新市價（約 1 分鐘後再整理看最新）');
    else if (r.status === 403) toast('自動更新需 Token 有 Actions 寫入權限');
  } catch (e) { console.debug('[pf]', e); }
}

/* ==================== §11. 持股 / 年度 編輯操作 ==================== */
async function toggleEdit() {
  if (!editMode) {
    const ok = await verifyEditPassword();
    if (!ok) return;
  }
  editMode = !editMode;
  document.getElementById('edit-btn').textContent = editMode ? '👁 檢視' : '✏️ 編輯';
  document.getElementById('save-btn').classList.toggle('hidden', !editMode);
  render();
}
function addHolding() {
  DATA.holdings.push({ type: 'ETF', code: '', name: '', cost: 0, price: 0, lots: 0 });
  render();
}
async function delHolding(i) {
  const h = DATA.holdings[i];
  if (await uiConfirm(`確定刪除 ${h.code} ${h.name}?`)) { DATA.holdings.splice(i, 1); cache(); render(); }
}
function addYear() {
  DATA.yearly.push({ year: String(new Date().getFullYear()), capitalGain: 0, dividend: 0, note: '' });
  render();
}
async function delYear(i) {
  if (await uiConfirm('確定刪除這筆年度紀錄?')) { DATA.yearly.splice(i, 1); cache(); render(); }
}
// 欄位變更 → 寫回 DATA → 重算
document.addEventListener('change', e => {
  const path = e.target.dataset && e.target.dataset.path;
  if (!path) return;
  const parts = path.split('.');
  let obj = DATA;
  for (let i = 0; i < parts.length - 1; i++) obj = obj[isNaN(parts[i]) ? parts[i] : +parts[i]];
  const key = parts[parts.length - 1];
  obj[key] = e.target.type === 'number' ? (parseFloat(e.target.value) || 0) : e.target.value;
  cache(); render();
});

/* ==================== §12. 儲存 / 載入 / 快取 ==================== */
function cache() { store.set('portfolio-data', JSON.stringify(DATA)); }
function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2200);
}

// IndexedDB:記住 data.json 的檔案 handle,下次免重選
const idb = {
  open: () => new Promise((res, rej) => {
    const r = indexedDB.open('pf-db', 1);
    r.onupgradeneeded = () => r.result.createObjectStore('kv');
    r.onsuccess = () => res(r.result); r.onerror = rej;
  }),
  get: async k => { const db = await idb.open(); return new Promise(res => {
    const r = db.transaction('kv').objectStore('kv').get(k);
    r.onsuccess = () => res(r.result); r.onerror = () => res(null); }); },
  set: async (k, v) => { const db = await idb.open(); return new Promise(res => {
    const tx = db.transaction('kv', 'readwrite');
    tx.objectStore('kv').put(v, k); tx.oncomplete = res; }); }
};

/* ==================== §13. GitHub 同步(讀取 / commit) ==================== */
function ghCfg() { try { return JSON.parse(store.get('pf-gh')) || null; } catch (e) { return null; } }
function ghReady(c) { return c && c.owner && c.repo && c.token; }
function ghUrl(c) {
  return `https://api.github.com/repos/${c.owner}/${c.repo}/contents/${encodeURIComponent(c.path || 'data.json')}`;
}
function ghHeaders(c) {
  return { 'Authorization': 'Bearer ' + c.token, 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28' };
}
async function ghLoad(c) {
  const r = await fetch(`${ghUrl(c)}?ref=${c.branch || 'main'}&_=${Date.now()}`,
    { headers: { ...ghHeaders(c), 'Accept': 'application/vnd.github.raw+json' }, cache: 'no-store' });
  if (!r.ok) throw new Error('讀取失敗 ' + r.status);
  return r.json();
}
// 把 GitHub API 的狀態碼轉成白話訊息,方便判斷存檔失敗原因
function ghErr(status, j) {
  const detail = j && j.message ? `（${j.message}）` : '';
  const map = {
    401: 'Token 無效或已過期，請到 GitHub 重新產生 token 並更新設定',
    403: '權限不足：Token 需要這個 repo 的 Contents 讀寫權限（速率限制也可能造成）',
    404: '找不到 repo／分支／檔案路徑，請檢查帳號、Repo 名稱、分支、檔案路徑是否正確，且 Token 有權限存取',
    409: '版本衝突：repo 上的檔案比你手上的新',
    422: '送出的內容有誤，通常是分支或檔案路徑設定問題'
  };
  return new Error((map[status] || ('GitHub 錯誤 ' + status)) + detail);
}
async function ghSave(c, json) {
  const commit = async () => {
    let sha;
    const g = await fetch(`${ghUrl(c)}?ref=${c.branch || 'main'}&_=${Date.now()}`, { headers: ghHeaders(c), cache: 'no-store' });
    if (g.ok) sha = (await g.json()).sha;
    else if (g.status !== 404) throw ghErr(g.status, await g.json().catch(() => ({})));
    const body = {
      message: '更新庫存資料 ' + new Date().toISOString().slice(0, 10),
      content: b64utf8(json),
      branch: c.branch || 'main'
    };
    if (sha) body.sha = sha;
    return fetch(ghUrl(c), { method: 'PUT', headers: ghHeaders(c), body: JSON.stringify(body) });
  };
  let r = await commit();
  if (r.status === 409 || r.status === 422) r = await commit();   // sha 衝突 → 重抓最新 sha 再存一次
  if (!r.ok) throw ghErr(r.status, await r.json().catch(() => ({})));
}

async function openGhModal() {
  if (!await verifyEditPassword()) return;
  const c = ghCfg() || {};
  // 在 GitHub Pages 上自動帶入 owner/repo
  let owner = c.owner || '', repo = c.repo || '';
  if (!owner && location.hostname.endsWith('.github.io')) {
    owner = location.hostname.split('.')[0];
    repo = location.pathname.split('/')[1] || '';
  }
  document.getElementById('gh-owner').value = owner;
  document.getElementById('gh-repo').value = repo;
  document.getElementById('gh-branch').value = c.branch || 'main';
  document.getElementById('gh-path').value = c.path || 'data.json';
  document.getElementById('gh-token').value = c.token || '';
  document.getElementById('gh-modal').classList.remove('hidden');
}
function closeGhModal() { document.getElementById('gh-modal').classList.add('hidden'); }
function saveGh() {
  const c = {
    owner: document.getElementById('gh-owner').value.trim(),
    repo: document.getElementById('gh-repo').value.trim(),
    branch: document.getElementById('gh-branch').value.trim() || 'main',
    path: document.getElementById('gh-path').value.trim() || 'data.json',
    token: document.getElementById('gh-token').value.trim()
  };
  if (!ghReady(c)) { toast('帳號、Repo、Token 為必填'); return; }
  store.set('pf-gh', JSON.stringify(c));
  updateGhBtn();
  closeGhModal();
  toast('✅ GitHub 設定已儲存');
}
async function clearGh() {
  if (await uiConfirm('確定清除 GitHub 設定(含 Token)?')) {
    store.del('pf-gh');
    updateGhBtn();
    closeGhModal();
  }
}
function updateGhBtn() {
  document.getElementById('gh-btn').textContent = ghReady(ghCfg()) ? '🔗 GitHub 同步' : '⚙️ GitHub 同步';
}

async function saveFile() {
  DATA.updated = new Date().toISOString().slice(0, 10);
  cache();
  const json = JSON.stringify(await encData(DATA));

  // 已設定 GitHub → 直接 commit 回 repo
  const c = ghCfg();
  if (ghReady(c)) {
    try {
      toast('上傳到 GitHub 中…');
      await ghSave(c, json);
      render();
      toast(`✅ 已 commit 到 ${c.owner}/${c.repo}`);
      return;
    } catch (err) {
      if (!await uiConfirm('GitHub 儲存失敗:' + err.message + '\n\n改存到本機檔案?(注意:存到本機不會更新網站上的資料)')) return;
    }
  } else if (location.hostname.endsWith('.github.io')) {
    // 透過 GitHub Pages 開啟卻沒設定同步 → 存本機檔案不會更新網站,主動提醒先設定
    if (await uiConfirm('你正透過 GitHub Pages 開啟,但尚未設定 GitHub 同步。\n\n存到本機檔案「不會」更新網站上的資料。要現在設定 GitHub 同步嗎?')) {
      openGhModal();
      return;
    }
  }
  try {
    let h = fsHandle || await idb.get('handle');
    if (!h && window.showSaveFilePicker) {
      h = await showSaveFilePicker({ suggestedName: 'data.json',
        types: [{ description: 'JSON', accept: { 'application/json': ['.json'] } }] });
      await idb.set('handle', h);
    }
    if (h) {
      if (await h.queryPermission({ mode: 'readwrite' }) !== 'granted' &&
          await h.requestPermission({ mode: 'readwrite' }) !== 'granted') throw new Error('未授權');
      const w = await h.createWritable();
      await w.write(json); await w.close();
      fsHandle = h;
      render();
      toast('✅ 已儲存到 ' + h.name);
      return;
    }
    throw new Error('不支援');
  } catch (err) {
    if (err.name === 'AbortError') return;
    // fallback:下載檔案
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([json], { type: 'application/json' }));
    a.download = 'data.json';
    a.click();
    render();
    toast('已下載 data.json,請覆蓋原檔');
  }
}

async function pickFile() {
  if (!await verifyEditPassword()) return;
  try {
    if (window.showOpenFilePicker) {
      const [h] = await showOpenFilePicker({ types: [{ description: 'JSON', accept: { 'application/json': ['.json'] } }] });
      fsHandle = h;
      await idb.set('handle', h);
      const file = await h.getFile();
      load(await decodeMaybe(JSON.parse(await file.text())));
      return;
    }
  } catch (err) { if (err.name === 'AbortError') return; }
  document.getElementById('file-input').click();
}

/* ==================== §14. 檔案存取(存檔 / 選檔 / 拖放) ==================== */
function normalizeData(json) {
  if (!json.title && json.dashboardTitle) json.title = json.dashboardTitle;
  if (!json.title) json.title = DEFAULT_TITLE;
  return json;
}
function load(json) { DATA = normalizeData(json); cache(); render(); }

document.getElementById('file-input').addEventListener('change', e => {
  const file = e.target.files[0];
  if (file) file.text().then(async t => load(await decodeMaybe(JSON.parse(t))));
});
document.addEventListener('dragover', e => e.preventDefault());
document.addEventListener('drop', async e => {
  e.preventDefault();
  const file = e.dataTransfer.files[0];
  if (file && file.name.endsWith('.json')) {
    if (!await verifyEditPassword()) return;
    load(await decodeMaybe(JSON.parse(await file.text())));
  }
});
document.getElementById('hide-zero').addEventListener('change', () => DATA && render({ charts: false }));
// 跨 600px 斷點(轉向 / 分割畫面)時重畫:熱圖週數、子圖排法都跟寬度走
if (window.matchMedia) matchMedia('(max-width: 600px)').addEventListener('change', () => { if (DATA) render(); });
// 顯示全部欄位:純 CSS 切換(body.all-cols),不重畫;記住偏好
{
  const allCols = document.getElementById('all-cols');
  if (allCols) {
    const on = store.get('pf-all-cols') === '1';
    allCols.checked = on; document.body.classList.toggle('all-cols', on);
    allCols.addEventListener('change', e => { document.body.classList.toggle('all-cols', e.target.checked); store.set('pf-all-cols', e.target.checked ? '1' : '0'); });
  }
}

/* ==================== §14b. 分享戰報:Hero + 走勢合成一張圖 → Web Share / 下載 ==================== */
// 1080×1350(IG 4:5)。模式:今日(Hero 的今日損益 + 近 30 個交易日總市值線)/ 本週 / 本月(期間總報酬變化 + 期間總市值線)。
// 走勢線自己用 canvas 畫,不貼畫面上的 Chart canvas(圖例、隱藏線、動畫中間幀都不會混進來);配色取當前主題 CSS 變數。
// 「只顯示 %」:金額改成 % 或「—」。previewOnly=true 只回傳 canvas(測試 / 預覽)。
const SHARE_MODES = { day: { title: '今日戰報', label: '今日損益' }, week: { title: '本週戰報', label: '本週損益' }, month: { title: '本月戰報', label: '本月損益' } };
// 文字塞不進 maxW 就逐步縮字級(最小 minPx),回傳實際字級並已設好 ctx.font
function fitText(c, text, maxW, px, weight, family, minPx = 20) {
  for (let s = px; s >= minPx; s -= 2) { c.font = `${weight} ${s}px ${family}`; if (c.measureText(text).width <= maxW) return s; }
  c.font = `${weight} ${minPx}px ${family}`; return minPx;
}
// 小走勢線:series = [{date, mv}] 畫進 box{x,y,w,h};面積漸層、最高 / 最低點標記、首尾日期
function drawMiniLine(c, series, box, col) {
  const { x, y, w, h } = box, vals = series.map(p => Number(p.mv) || 0);
  const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
  const px = i => x + (vals.length > 1 ? i / (vals.length - 1) : .5) * w;
  const py = v => y + h - 34 - (v - lo) / span * (h - 84);
  const base = y + h - 34;
  c.save();
  const grad = c.createLinearGradient(0, y, 0, base);
  grad.addColorStop(0, withAlpha(col.line, .38)); grad.addColorStop(1, withAlpha(col.line, .02));
  c.beginPath(); vals.forEach((v, i) => i ? c.lineTo(px(i), py(v)) : c.moveTo(px(i), py(v)));
  c.lineTo(px(vals.length - 1), base); c.lineTo(px(0), base); c.closePath(); c.fillStyle = grad; c.fill();
  c.beginPath(); vals.forEach((v, i) => i ? c.lineTo(px(i), py(v)) : c.moveTo(px(i), py(v)));
  c.strokeStyle = col.line; c.lineWidth = 4; c.lineJoin = 'round'; c.lineCap = 'round'; c.stroke();
  const ex = PfCalc.extremes(vals);
  if (ex.hi !== ex.lo) {
    c.font = `700 22px ${col.font}`; c.textBaseline = 'middle';
    [[ex.hi, col.hi, '▲ ' + (col.money ? fmt(vals[ex.hi]) : '最高'), -22], [ex.lo, col.lo, '▼ ' + (col.money ? fmt(vals[ex.lo]) : '最低'), 24]].forEach(([i, cc, txt, dy]) => {
      c.fillStyle = cc; c.beginPath(); c.arc(px(i), py(vals[i]), 7, 0, Math.PI * 2); c.fill();
      c.textAlign = i === 0 ? 'left' : i === vals.length - 1 ? 'right' : 'center';
      c.fillText(txt, px(i), py(vals[i]) + dy);
    });
  }
  c.fillStyle = col.muted; c.font = `600 22px ${col.font}`; c.textBaseline = 'bottom';
  c.textAlign = 'left'; c.fillText(String(series[0].date).slice(5), x, y + h);
  c.textAlign = 'right'; c.fillText(String(series[series.length - 1].date).slice(5), x + w, y + h);
  c.restore();
}
async function shareCard(previewOnly) {
  if (!DATA) { toast('資料還沒載入'); return null; }
  const mode = (document.getElementById('share-mode') || {}).value || 'day';
  const M = SHARE_MODES[mode] || SHARE_MODES.day;
  const pctOnly = !!(document.getElementById('share-pct-only') || {}).checked;
  const now = tpeNow(), full = PfCalc.histSlices(DATA.history, 0, now.date).full;
  // 期間損益:今日走 Hero(各檔昨收);本週 / 本月走 history 的總報酬變化
  let chg, pctV, missing = 0, series;
  if (mode === 'day') {
    if (!HERO) { toast('今日損益還沒算出來,無法產生戰報'); return null; }
    chg = HERO.heroChg; pctV = HERO.heroPct; missing = HERO.heroMissing; series = full.slice(-30);
  } else {
    let start;
    if (mode === 'week') { const d = new Date(Date.now() + 8 * 3600 * 1000); d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7)); start = d.toISOString().slice(0, 10); }
    else start = now.date.slice(0, 8) + '01';
    const PC = PfCalc.periodChange(full, start);
    if (!PC) { toast(`${M.title}:期間內還沒有足夠資料`); return null; }
    chg = PC.chg; pctV = PC.pct; series = PC.series;
  }
  const TT = PfCalc.totals(DATA), rate = TT.cost ? TT.totalReturn / TT.cost : 0;
  const css = getComputedStyle(document.documentElement), v = n => css.getPropertyValue(n).trim();
  const P = CHART_PALETTES[getChartStyleKey()];
  const W = 1080, H = 1350, PAD = 60, INNER = W - PAD * 2;
  const cv = document.createElement('canvas'); cv.width = W; cv.height = H;
  const c = cv.getContext('2d');
  const FAM = v('--font-ui') || '"Segoe UI", "Microsoft JhengHei", "PingFang TC", "Noto Sans TC", sans-serif';
  const font = (w, px) => `${w} ${px}px ${FAM}`;
  const upC = v('--up'), downC = v('--down'), textC = v('--text'), labelC = v('--label') || v('--muted'), mutedC = v('--muted');
  const colorOf = n => n > 0 ? upC : n < 0 ? downC : textC;
  const card = (x, y, w, h) => { c.fillStyle = v('--card'); c.strokeStyle = v('--border'); c.lineWidth = 2; roundedRectPath(c, x, y, w, h, 28); c.fill(); c.stroke(); };
  c.fillStyle = v('--bg'); c.fillRect(0, 0, W, H);
  c.textBaseline = 'middle'; c.textAlign = 'left';

  // 標題列:吉祥物 + 標題 + 期間
  const mascot = document.querySelector('img.mascot');
  let tx = PAD;
  if (mascot && mascot.complete && mascot.naturalWidth) {
    c.save(); c.beginPath(); c.arc(PAD + 60, 120, 60, 0, Math.PI * 2); c.closePath(); c.clip();
    c.drawImage(mascot, PAD, 60, 120, 120); c.restore();
    c.strokeStyle = v('--title-accent'); c.lineWidth = 5; c.beginPath(); c.arc(PAD + 60, 120, 60, 0, Math.PI * 2); c.stroke();
    tx = PAD + 150;
  }
  const day = String(DATA.priceUpdated || DATA.updated || now.date).slice(0, 10);
  const title = DATA.title || DEFAULT_TITLE;
  c.fillStyle = v('--title'); fitText(c, title, W - tx - PAD, 54, 850, FAM, 30); c.fillText(title, tx, 100);
  c.fillStyle = mutedC; c.font = font(600, 28);
  const period = mode === 'day' ? (DATA.priceUpdated || day) : `${String(series[0].date).slice(5)} ~ ${String(series[series.length - 1].date).slice(5)}`;
  c.fillText(`${M.title} · ${period}`, tx, 152);

  // 損益大字
  const pctTxt = `${sign(pctV)}${pct(pctV)}`;
  card(PAD, 220, INNER, 400);
  c.fillStyle = labelC; c.font = font(700, 32);
  c.fillText(M.label + (missing ? `(${missing} 檔缺昨收未計)` : ''), PAD + 48, 285);
  c.fillStyle = colorOf(chg);
  if (pctOnly) { fitText(c, pctTxt, INNER - 96, 150, 880, FAM); c.fillText(pctTxt, PAD + 44, 400); }
  else {
    const big = sign(chg) + fmt(chg);
    fitText(c, big, INNER - 96, 118, 880, FAM); c.fillText(big, PAD + 44, 392);
    c.font = font(750, 52); c.fillText(`(${pctTxt})`, PAD + 48, 478);
  }
  const col2 = W / 2 + 20, rowY = 560, colW = W - PAD - 48 - col2;
  c.fillStyle = labelC; c.font = font(700, 28); c.fillText('總市值', PAD + 48, rowY - 24); c.fillText('總報酬', col2, rowY - 24);
  c.fillStyle = textC; c.font = font(800, 44); c.fillText(pctOnly ? '—' : fmt(TT.mv), PAD + 48, rowY + 28);
  const rateTxt = `${sign(rate)}${pct(rate)}`, retTxt = pctOnly ? rateTxt : `${sign(TT.totalReturn)}${fmt(TT.totalReturn)} · ${rateTxt}`;
  c.fillStyle = colorOf(TT.totalReturn); fitText(c, retTxt, colW, 44, 800, FAM, 26); c.fillText(retTxt, col2, rowY + 28);

  // 走勢:自己畫總市值線
  card(PAD, 670, INNER, 520);
  c.fillStyle = labelC; c.font = font(700, 30); c.textAlign = 'left'; c.textBaseline = 'middle';
  c.fillText(mode === 'day' ? '總市值走勢(近 30 個交易日)' : '總市值走勢(本期間)', PAD + 48, 720);
  if (series && series.length >= 2) {
    drawMiniLine(c, series, { x: PAD + 48, y: 760, w: INNER - 96, h: 400 }, { line: v('--title-accent') || v('--accent'), hi: P.hi, lo: P.lo, muted: mutedC, font: FAM, money: !pctOnly });
  } else { c.fillStyle = mutedC; c.font = font(600, 28); c.fillText('(走勢資料不足)', PAD + 48, 900); }

  // 頁尾:站台網址(在 GitHub Pages 上才有)
  const site = location.hostname.endsWith('.github.io') ? location.host + location.pathname.replace(/index\.html$/, '') : '';
  c.fillStyle = mutedC; c.font = font(600, 26); c.textAlign = 'center';
  c.fillText(title + (site ? ' · ' + site : ''), W / 2, H - 70);
  if (previewOnly) return cv;

  // 輸出:能 Web Share 檔案就分享(手機丟 LINE / IG),不能就下載 PNG
  const blob = await new Promise(res => cv.toBlob(res, 'image/png'));
  if (!blob) { toast('產生圖片失敗'); return null; }
  const file = new File([blob], `panghu-${mode}-${day}.png`, { type: 'image/png' });
  const text = `${title} ${day} ${M.label} ${pctTxt}`;
  if (navigator.canShare && navigator.canShare({ files: [file] })) {
    try { await navigator.share({ files: [file], title: text, text }); return null; }
    catch (e) { if (e && e.name === 'AbortError') return null; console.debug('[pf] share', e); }   // 使用者取消就靜靜結束;其他錯誤退回下載
  }
  const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = file.name; link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 4000);
  toast('已下載戰報圖片(此瀏覽器不支援直接分享)');
  return null;
}

/* ==================== §15. 主題 / 圖表風格切換 ==================== */
// ⚙️ 設定視窗(主題 / 圖表 / GitHub / 載入 / 密碼 的收納處)
function openSettingsModal() { document.getElementById('settings-modal').classList.remove('hidden'); }
function closeSettingsModal() { document.getElementById('settings-modal').classList.add('hidden'); }
function applyTheme(t) {
  if (!THEME_KEYS.includes(t)) t = 'ocean';
  document.documentElement.dataset.theme = t;
  document.getElementById('theme-sel').value = t;
  store.set('pf-theme', t);
  // 狀態列/瀏覽器列底色跟著主題走(Android 狀態列、iOS 安全區底色)
  const bg = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim();
  const m = document.querySelector('meta[name="theme-color"]');
  if (m && bg) m.setAttribute('content', bg);
  if (DATA) render();
}
function applyChartStyle(t) {
  if (t !== 'match' && !CHART_PALETTES[t]) t = 'match';
  document.getElementById('chart-style-sel').value = t;
  store.set('pf-chart-style', t);
  if (DATA) render();
}
// 色弱友善 / 緊湊密度:html class + 記偏好;色弱會改 --up / --down,圖表要重畫
function applyFlag(cls, on, key, redraw) {
  document.documentElement.classList.toggle(cls, on);
  store.set(key, on ? '1' : '0');
  const el = document.getElementById(cls + '-toggle'); if (el) el.checked = on;
  if (redraw && DATA) render();
}
document.getElementById('cvd-toggle').addEventListener('change', e => applyFlag('cvd', e.target.checked, 'pf-cvd', true));
document.getElementById('compact-toggle').addEventListener('change', e => applyFlag('compact', e.target.checked, 'pf-compact', true));
applyFlag('cvd', store.get('pf-cvd') === '1', 'pf-cvd', false);
applyFlag('compact', store.get('pf-compact') === '1', 'pf-compact', false);
document.getElementById('theme-sel').addEventListener('change', e => applyTheme(e.target.value));
document.getElementById('chart-style-sel').addEventListener('change', e => applyChartStyle(e.target.value));
applyTheme(store.get('pf-theme') || (window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches ? 'midnight' : 'ocean'));   // 沒選過主題就跟系統深淺
applyChartStyle(store.get('pf-chart-style') || 'match');

/* ==================== §16. 下拉重新整理(手機 / PWA) ==================== */
(function () {
  if (!document.body) return;
  const ind = document.createElement('div');
  ind.id = 'ptr';
  ind.innerHTML = '<span class="ptr-ico">↓</span><span class="ptr-txt">下拉重新整理</span>';
  document.body.appendChild(ind);
  const txt = ind.querySelector('.ptr-txt'), ico = ind.querySelector('.ptr-ico');
  let startY = 0, dy = 0, active = false;
  const TH = 70;
  addEventListener('touchstart', e => {
    if (window.scrollY <= 0 && e.touches.length === 1) { startY = e.touches[0].clientY; active = true; dy = 0; }
  }, { passive: true });
  addEventListener('touchmove', e => {
    if (!active) return;
    dy = e.touches[0].clientY - startY;
    if (dy > 0 && window.scrollY <= 0) {
      ind.style.transition = 'none';
      ind.style.transform = `translateX(-50%) translateY(${Math.min(dy, 90) - 60}px)`;
      ind.style.opacity = String(Math.min(1, dy / TH));
      txt.textContent = dy >= TH ? '放開重新整理' : '下拉重新整理';
      ico.style.transform = dy >= TH ? 'rotate(180deg)' : 'rotate(0)';
    }
  }, { passive: true });
  addEventListener('touchend', () => {
    if (!active) return;
    active = false;
    ind.style.transition = 'transform .25s ease, opacity .25s ease';
    if (dy >= TH) {
      txt.textContent = '更新中…'; ico.textContent = '⟳'; ind.classList.add('spin');
      ind.style.transform = 'translateX(-50%) translateY(0)'; ind.style.opacity = '1';
      setTimeout(() => location.reload(), 300);
    } else {
      ind.style.transform = 'translateX(-50%) translateY(-60px)'; ind.style.opacity = '0';
    }
    dy = 0;
  }, { passive: true });
})();

/* ==================== §16a. 分頁 icon / 標題 / 迷你 Hero ==================== */
// 分頁 icon 畫今日漲跌三角(顏色跟 --up / --down,色弱模式一起變)、標題前綴今日 %;沒有今日損益就還原原本 favicon
function updateFavicon(title) {
  const link = document.getElementById('favicon'); if (!link) return;
  if (!HERO || HERO.heroChg == null) { if (link.dataset.dyn) { link.href = 'favicon.png'; delete link.dataset.dyn; } document.title = title; return; }
  const pctTxt = `${sign(HERO.heroPct)}${pct(HERO.heroPct)}`;
  document.title = `${pctTxt} · ${title}`;
  const css = getComputedStyle(document.documentElement), v = n => css.getPropertyValue(n).trim();
  const cv = document.createElement('canvas'); cv.width = cv.height = 64; const c = cv.getContext('2d');
  c.fillStyle = v('--card') || '#fff'; roundedRectPath(c, 0, 0, 64, 64, 14); c.fill();
  c.fillStyle = HERO.heroChg > 0 ? v('--up') : HERO.heroChg < 0 ? v('--down') : v('--muted');
  c.beginPath();
  if (HERO.heroChg >= 0) { c.moveTo(32, 12); c.lineTo(56, 52); c.lineTo(8, 52); } else { c.moveTo(8, 12); c.lineTo(56, 12); c.lineTo(32, 52); }
  c.closePath(); c.fill();
  link.href = cv.toDataURL('image/png'); link.dataset.dyn = '1';
}
// 手機:Hero 面板捲出畫面後,頂部貼一條「今日 ±X(±%)· 總市值」;桌機 CSS 直接不顯示
function updateMiniHero() {
  const mini = document.getElementById('mini-hero'); if (!mini) return;
  if (!HERO || HERO.heroChg == null) { mini.classList.remove('show'); mini.innerHTML = ''; return; }
  syncMiniHero();
  mini.innerHTML = `<span class="k">今日</span><span class="${cls(HERO.heroChg)}">${sign(HERO.heroChg)}${fmt(HERO.heroChg)}(${sign(HERO.heroPct)}${pct(HERO.heroPct)})</span><span class="k">總市值</span><span>${fmt(HERO.mv)}</span>`;
}
// 用 scroll 事件而不是 IntersectionObserver:IO 在背景分頁 / 某些 WebView 不觸發,scroll + getBoundingClientRect 每個環境都準且夠便宜
// iOS 的 scroll 事件在慣性捲動 / 下拉回彈 / reload 還原捲動位置時常少最後一發,單靠 scroll 會卡在「亮著」:
// (1) 頁面在頂端(scrollY ≤ 40)一律不顯示;(2) 每次 scroll 後 150ms 再對一次落定位置;(3) touchend / scrollend 也對一次
function syncMiniHero() {
  const mini = document.getElementById('mini-hero'), heroPanel = document.getElementById('hero-panel');
  if (!mini || !heroPanel) return;
  const atTop = (window.scrollY || document.documentElement.scrollTop || 0) <= 40;
  const gone = !atTop && heroPanel.style.display !== 'none' && heroPanel.getBoundingClientRect().bottom < 0;
  const show = gone && !!HERO;
  mini.classList.toggle('show', show);
  // 保底:亮著的期間每 500ms 對一次(只在亮著時跑,一次 getBoundingClientRect),事件全漏也會在半秒內關掉
  if (show && !_miniWatch) _miniWatch = setInterval(syncMiniHero, 500);
  else if (!show && _miniWatch) { clearInterval(_miniWatch); _miniWatch = 0; }
}
let _miniWatch = 0;
let _miniTimer = 0;
const syncMiniHeroSettled = () => { syncMiniHero(); clearTimeout(_miniTimer); _miniTimer = setTimeout(syncMiniHero, 150); };
window.addEventListener('scroll', syncMiniHeroSettled, { passive: true });
window.addEventListener('scrollend', syncMiniHero, { passive: true });
window.addEventListener('touchend', syncMiniHeroSettled, { passive: true });

/* ==================== §16a2. Modal 無障礙 + 自救 ==================== */
// 設定裡的「清快取重新載入」:走 index.html head 的 __pfHeal(unregister SW + 清 caches + reload),那段獨立於 app.js 所以 app.js 壞了也能按
function healApp() { if (window.__pfHeal) window.__pfHeal(); else location.reload(); }
// Modal 開啟時 focus 第一個可聚焦元素、Tab 在視窗內循環、Esc 等同點遮罩關閉(走 backdrop action)
(function () {
  const FOCUSABLE = 'button, [href], input:not([type="hidden"]), select, textarea, [tabindex]:not([tabindex="-1"])';
  const openModal = () => [...document.querySelectorAll('.modal-bg')].find(m => !m.classList.contains('hidden'));
  new MutationObserver(muts => {
    muts.forEach(m => {
      const el = m.target;
      if (el.classList && el.classList.contains('modal-bg') && !el.classList.contains('hidden') && !el.contains(document.activeElement)) {
        const f = el.querySelector(FOCUSABLE); if (f) setTimeout(() => f.focus(), 0);
      }
    });
  }).observe(document.body, { attributes: true, attributeFilter: ['class'], subtree: true });
  document.addEventListener('keydown', e => {
    const m = openModal(); if (!m) return;
    if (e.key === 'Escape') { e.preventDefault(); m.dispatchEvent(new MouseEvent('click', { bubbles: true })); return; }
    if (e.key !== 'Tab') return;
    const items = [...m.querySelectorAll(FOCUSABLE)].filter(x => !x.disabled && x.offsetParent !== null); if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });
})();

/* ==================== §16b. 事件委派 ==================== */
// HTML 不寫 onclick,改 data-action="fn" data-args='[...]'(JSON 陣列;省略 = 無參數)。
// 特殊 action:backdrop(點遮罩空白處才呼叫 args[0])、seq(依序呼叫多個無參數函式)、toggleHoldDetail(要拿列元素與事件)。
// Enter 送出:data-enter="fn"。ACTIONS 是允許清單,markup 打錯字或注入的名字不會亂呼叫全域函式。
const ACTIONS = new Set(['pickFile', 'unlockUI', 'toggleEdit', 'saveFile', 'updatePrices', 'openSettingsModal', 'lockUI', 'switchTab', 'shareCard',
  'togglePieMode', 'setNavRange', 'addHolding', 'addYear', 'closeSettingsModal', 'openGhModal', 'setPassword', 'clearGh', 'closeGhModal', 'saveGh',
  'closePwdModal', 'pinKey', 'submitPwd', 'closeSetPwd', 'setpwdNext', 'closeConfirm', 'sortHoldings', 'delHolding', 'delYear', 'healApp']);
const callAction = (name, args) => {
  if (!ACTIONS.has(name) || typeof window[name] !== 'function') { console.debug('[pf] 未知 data-action', name); return; }
  return window[name](...(args || []));
};
document.addEventListener('click', ev => {
  const el = ev.target.closest('[data-action]'); if (!el) return;
  const name = el.dataset.action;
  let args = [];
  if (el.dataset.args) { try { args = JSON.parse(el.dataset.args); } catch (e) { console.debug('[pf] data-args 不是合法 JSON', el.dataset.args); } }
  if (name === 'backdrop') { if (ev.target === el) callAction(args[0], args.slice(1)); return; }
  if (name === 'seq') { args.forEach(n => callAction(n, [])); return; }
  if (name === 'toggleHoldDetail') { toggleHoldDetail(el, ev); return; }
  callAction(name, args);
});
document.addEventListener('keydown', ev => {
  if (ev.key !== 'Enter') return;
  const el = ev.target.closest('[data-enter]'); if (!el) return;
  ev.preventDefault(); callAction(el.dataset.enter, []);
});

/* ==================== §17. 啟動(splash + init 載入資料) ==================== */
/* 啟動畫面(splash):至少停留 SPLASH_MIN,載入完成後再收起 */
const SPLASH_MIN = 1200;             // 最少停留毫秒(想更久就調大)
const splashStart = Date.now();
function hideSplash() {
  const s = document.getElementById('splash');
  if (!s || s.classList.contains('hide')) return;
  const wait = Math.max(0, SPLASH_MIN - (Date.now() - splashStart));
  setTimeout(() => {
    s.classList.add('hide');
    setTimeout(() => { if (s.parentNode) s.remove(); }, 600);
  }, wait);
}
setTimeout(hideSplash, 4000);        // 備援上限(資料載不出來時)

/* ---------- 啟動 ----------
   0. localStorage 快取先畫(有的話),下面任一來源成功就無縫換成最新
   1. GitHub 同步已設定 → 讀 repo 最新 data.json
   2. fetch data.json(GitHub Pages / http 伺服器),最多等 8 秒
   3. 記住的檔案 handle(若權限仍有效)
   4. 都不通 → 停在快取並提示;沒快取請使用者選檔 */
(async function init() {
  updateAuthUI();
  updateGhBtn();
  const showPickHint = () => {
    const hint = document.getElementById('loader-hint');
    const p = document.querySelector('#loader p');
    if (hint) hint.classList.remove('hidden');
    if (p) p.textContent = '請選擇 data.json 或拖曳檔案到此頁面';
  };
  setTimeout(() => { if (!DATA) showPickHint(); }, 800);
  // 0. 有上次快取先畫出來(零等待);之後網路來源到了再無縫換成最新,網路慢也不會白畫面、也看得出是不是舊資料
  const cachedRaw = store.get('portfolio-data');
  let shownCache = false;
  if (cachedRaw) { try { DATA = JSON.parse(cachedRaw); render(); shownCache = true; } catch (e) { console.debug('[pf]', e); } }
  const afterFresh = () => { if (shownCache && cachedRaw !== JSON.stringify(DATA)) toast('已更新為最新資料'); };
  // 1. 已設定 GitHub → 優先讀 repo 最新版(不受 Pages 部署延遲影響)
  const ghc = ghCfg();
  if (ghReady(ghc)) {
    autoTriggerPrices(ghc);            // 交易時段內自動送出更新市價(不等待,不影響載入)
    try { load(await decodeMaybe(await ghLoad(ghc))); afterFresh(); return; }
    catch (e) { toast('GitHub 讀取失敗,改用其他來源'); }
  }
  // 2. 同站 data.json(GitHub Pages);最多等 8 秒,弱網也給它機會
  try {
    const r = await fetch('data.json', { cache: 'no-store', signal: AbortSignal.timeout(8000) });
    if (!r.ok) throw 0;
    load(await decodeMaybe(await r.json()));
    afterFresh();
    return;
  } catch (e) { console.debug('[pf]', e); }
  // 3. 記住的檔案 handle
  try {
    const h = await idb.get('handle');
    if (h && await h.queryPermission({ mode: 'read' }) === 'granted') {
      fsHandle = h;
      const file = await h.getFile();
      load(await decodeMaybe(JSON.parse(await file.text())));
      afterFresh();
      return;
    }
  } catch (e) { console.debug('[pf]', e); }
  // 4. 都不通:有快取就停在快取並明講;沒有才請使用者選檔
  if (shownCache) toast('⚠ 無法取得最新資料,目前顯示上次快取');
  else {
    document.getElementById('loader-hint').classList.remove('hidden');
    document.querySelector('#loader p').textContent = '無法自動讀取 data.json';
  }
})();
