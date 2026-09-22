/* charts.js — 圖表模組。載入順序:scripts/calc.js → Chart.js → charts.js → app.js。
   本檔只定義常數與函式;執行期才引用 app.js 的 fmt / sign / pct / tpeNow / DATA / navRangeDays / setNavRange / REDUCED_MOTION,
   純計算(history 切片、回撤、日統計…)走 PfCalc(scripts/calc.js)。
   結構:1. 主題色盤 → 2. 通用 helper(withAlpha / upsertChart / 設定 factory)→ 3. plugin 常數 → 4. 各圖 drawXxx(T) → 5. drawCharts 統籌。
   慣例:inline plugin 一律做成常數、參數走 options.plugins.<id>(update 不會換 plugin,closure 會殘留);
         alpha 一律用 withAlpha(),不拼 hex 字尾;每張圖的顏色 / 字型從 T(chartTheme())拿,不改 Chart.defaults。 */

/* ==================== 1. 主題色盤 ==================== */
const THEME_KEYS = ['ocean', 'coral', 'matcha', 'midnight', 'cute', 'sailor', 'agent'];
const CHART_PALETTES = {
  'ocean': {
    name: '海洋藍',
    slices: ['#0284c7', '#e11d48', '#0d9488', '#7c3aed', '#f59e0b', '#64748b'],
    gain: '#e11d48', loss: '#0d9488', dividend: '#0284c7', grid: 'rgba(2,132,199,.14)'   // 極值高亮改用 --accent,palette 不再帶 hi / lo
  },
  'coral': {
    name: '珊瑚暖陽',
    slices: ['#f97316', '#e0394e', '#0f9d76', '#d97706', '#fb7185', '#a8a29e'],
    gain: '#e0394e', loss: '#0f9d76', dividend: '#f97316', grid: 'rgba(249,115,22,.16)'
  },
  'matcha': {
    name: '抹茶清新',
    slices: ['#4d7c45', '#d6443b', '#15803d', '#7c9a3f', '#a16207', '#9ca99b'],
    gain: '#d6443b', loss: '#15803d', dividend: '#4d7c45', grid: 'rgba(77,124,69,.16)'
  },
  'midnight': {
    name: '午夜金',
    slices: ['#e0b34d', '#ff6b81', '#34d399', '#60a5fa', '#c084fc', '#94a3b8'],
    gain: '#ff6b81', loss: '#34d399', dividend: '#e0b34d', grid: 'rgba(224,179,77,.16)'
  },
  'cute': {
    name: '馬卡龍',
    slices: ['#ff9ec4', '#8fe0c8', '#ffd98c', '#b9a7ff', '#9fd0ff', '#ffc2a0'],
    gain: '#f0688f', loss: '#2bb39a', dividend: '#ffb84d', grid: 'rgba(244,143,177,.18)'
  },
  'sailor': {
    name: '美少女',
    slices: ['#2b3f9e', '#e11d48', '#eab308', '#ec4899', '#0ea5a4', '#a78bdb'],
    gain: '#e11d48', loss: '#0ea5a4', dividend: '#eab308', grid: 'rgba(43,63,158,.16)'
  },
  'agent': {
    name: 'Agent Neon',
    slices: ['#8b5cf6', '#35d5ff', '#ff4fb8', '#2ee6b8', '#facc15', '#94a3b8'],
    gain: '#ff4fb8', loss: '#2ee6b8', dividend: '#35d5ff', grid: 'rgba(139,92,246,.16)'
  }
};

function getChartStyleKey() {
  const selected = document.getElementById('chart-style-sel')?.value || 'match';
  const theme = document.documentElement.dataset.theme || 'ocean';
  const key = selected === 'match' ? theme : selected;
  return CHART_PALETTES[key] ? key : 'ocean';
}

function togglePieMode() {
  const m = store.get('pf-pie-mode') || 'costpl';
  store.set('pf-pie-mode', m === 'costpl' ? 'value' : 'costpl');
  if (DATA) render();
}

/* ==================== 2. 通用 helper ==================== */
// 全域一次性設定:高 DPI 上限 2(iPhone 3x 畫 2x 肉眼無差,像素量少一半);其餘顏色 / 字型都在各圖 options 明寫,不動 defaults
Chart.defaults.devicePixelRatio = Math.min(window.devicePixelRatio || 1, 2);
Chart.defaults.font.family = 'Segoe UI, Microsoft JhengHei, sans-serif';

// 顏色加 alpha:#rgb / #rrggbb / #rrggbbaa / rgb() / rgba() 都吃;認不得就原樣回傳
function withAlpha(color, a) {
  const c = String(color).trim();
  let m;
  if ((m = c.match(/^#([0-9a-f]{3})$/i))) { const h = m[1]; return `rgba(${parseInt(h[0] + h[0], 16)},${parseInt(h[1] + h[1], 16)},${parseInt(h[2] + h[2], 16)},${a})`; }
  if ((m = c.match(/^#([0-9a-f]{6})(?:[0-9a-f]{2})?$/i))) { const h = m[1]; return `rgba(${parseInt(h.slice(0, 2), 16)},${parseInt(h.slice(2, 4), 16)},${parseInt(h.slice(4, 6), 16)},${a})`; }
  if ((m = c.match(/^rgba?\(([^)]+)\)$/i))) { const p = m[1].split(',').slice(0, 3).map(s => s.trim()); return `rgba(${p.join(',')},${a})`; }
  return c;
}

// 同一個 canvas、同一種 type → 換 data / options 後 update()(有過場動畫、不重建 canvas context);
// canvas 被換掉(innerHTML 重畫)或 type 不同才 destroy 重建
function upsertChart(chart, canvas, config) {
  if (chart && chart.canvas === canvas && chart.config.type === config.type) {
    chart.data = config.data;
    chart.options = config.options;
    chart.update();
    return chart;
  }
  if (chart) chart.destroy();
  return new Chart(canvas, config);
}
// 容器 display:none(如鎖住時 body.locked 藏起來的年度長條)就不畫,等解鎖 render 再畫;已有實例先留著
function upsertChartIfVisible(chart, canvas, config) {
  if (!canvas || canvas.offsetParent === null) return chart;
  return upsertChart(chart, canvas, config);
}

// 目前主題的圖表用色 / 字型,drawCharts 每輪算一次傳給各圖
function chartTheme() {
  const css = getComputedStyle(document.documentElement);
  const v = name => css.getPropertyValue(name).trim();
  const styleKey = getChartStyleKey();
  const isAgent = styleKey === 'agent';
  const isDark = isAgent || styleKey === 'midnight';
  const border = v('--border');
  return {
    v, styleKey, isAgent, isDark,
    palette: CHART_PALETTES[styleKey],
    muted: v('--muted'), text: v('--text'), card: v('--card'), border,
    tooltipBg: isAgent ? 'rgba(7,10,22,.99)' : (styleKey === 'midnight' ? 'rgba(18,27,48,.98)' : '#ffffff'),
    tooltipBorder: isAgent ? 'rgba(53,213,255,.72)' : border,
    // tooltip 文字色跟著 tooltip 底色走(深底亮字、白底深字),不受頁面主題影響
    tipTitle: isAgent ? '#67e8f9' : (isDark ? '#f0f4ff' : '#1e293b'),
    tipBody: isAgent ? '#eef4ff' : (isDark ? '#e6ecff' : '#334155'),
    syncCol: isAgent ? 'rgba(103,232,249,.55)' : (isDark ? 'rgba(255,255,255,.32)' : 'rgba(15,23,42,.26)'),   // 走勢圖群十字線
    chartFont: isAgent ? 'Trebuchet MS, Segoe UI, Microsoft JhengHei, sans-serif' : 'Segoe UI, Microsoft JhengHei, sans-serif',
    tickColor: isAgent ? '#aebbf0' : v('--muted'),
    zeroLine: isAgent ? 'rgba(200,184,255,.52)' : 'rgba(102,112,133,.34)'
  };
}
const font = (T, size, weight) => ({ family: T.chartFont, size, weight: String(weight || 500) });
// tooltip 共用外觀;extra 覆蓋 / 補 callbacks 等
function tooltipOpts(T, extra) {
  return Object.assign({
    backgroundColor: T.tooltipBg, titleColor: T.tipTitle, bodyColor: T.tipBody, footerColor: T.tipBody,
    borderColor: T.tooltipBorder, borderWidth: 1.5, cornerRadius: 12, padding: 12, bodySpacing: 6,
    titleFont: font(T, 13, 700), bodyFont: font(T, 12, 600), footerFont: font(T, 12.5, 850)
  }, extra || {});
}
// 時間軸 x(無格線、最多 8 個刻度)
function axisX(T, extra) {
  return Object.assign({ grid: { display: false }, ticks: { color: T.muted, maxTicksLimit: 8, font: font(T, 11) } }, extra || {});
}
// 數值軸 y(淡格線、無邊框、自訂刻度文字);extra.ticks 會與預設 ticks 合併
function axisY(T, callback, extra) {
  const base = { border: { display: false }, grid: { color: T.palette.grid, drawTicks: false }, ticks: { color: T.muted, padding: 8, maxTicksLimit: 5, font: font(T, 11), callback } };
  if (extra && extra.ticks) { extra = Object.assign({}, extra); extra.ticks = Object.assign({}, base.ticks, extra.ticks); }
  return Object.assign(base, extra || {});
}
const tickWan = v => (v / 10000) + '萬';
const tickWanSigned = v => (v > 0 ? '+' : '') + (v / 10000) + '萬';
const tickPct = v => (v > 0 ? '+' : '') + v.toFixed(1) + '%';
// 底部圖例(pointStyle:circle / rectRounded / line)
function legendBottom(T, pointStyle, extra) {
  return Object.assign({ position: 'bottom', labels: { usePointStyle: true, pointStyle, color: T.muted, padding: 16, font: font(T, 12, 700) } }, extra || {});
}
const baseOpts = extra => Object.assign({ responsive: true, maintainAspectRatio: false }, extra || {});
// 面積填色上→下淡出(scriptable;chartArea 尚未就緒時退回單色)
const areaGrad = (color, aTop, aBottom) => c => {
  const area = c.chart.chartArea; if (!area) return withAlpha(color, aTop);
  const g = c.chart.ctx.createLinearGradient(0, area.top, 0, area.bottom);
  g.addColorStop(0, withAlpha(color, aTop)); g.addColorStop(1, withAlpha(color, aBottom)); return g;
};

function roundedRectPath(ctx, x, y, w, h, r) {
  const radius = Math.max(0, Math.min(r, Math.abs(w) / 2, Math.abs(h) / 2));
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.lineTo(x + w - radius, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + radius);
  ctx.lineTo(x + w, y + h - radius);
  ctx.quadraticCurveTo(x + w, y + h, x + w - radius, y + h);
  ctx.lineTo(x + radius, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - radius);
  ctx.lineTo(x, y + radius);
  ctx.quadraticCurveTo(x, y, x + radius, y);
  ctx.closePath();
}

/* ==================== 3. plugin 常數 ==================== */
// 甜甜圈中央大字(總市值)
const centerTextPlugin = {
  id: 'centerText',
  afterDatasetsDraw(chart, args, o) {
    if (!o || !o.text) return;
    const { ctx, chartArea } = chart;
    const x = (chartArea.left + chartArea.right) / 2, y = (chartArea.top + chartArea.bottom) / 2;
    ctx.save();
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillStyle = o.color || '#344054';
    ctx.font = `${o.weight || 800} ${o.fontSize || 18}px ${o.fontFamily}`;
    ctx.fillText(o.text, x, y - 8);
    ctx.fillStyle = o.subColor || o.color || '#667085';
    ctx.font = `${o.subWeight || 700} ${o.subFontSize || 12}px ${o.fontFamily}`;
    ctx.fillText(o.subText || '', x, y + 14);
    ctx.restore();
  }
};

// 年度長條:hover 該年時外圈發光
const barHoverGlowPlugin = {
  id: 'barHoverGlow',
  beforeDatasetsDraw(chart, args, o) {
    const active = chart.getActiveElements();
    if (!active.length) return;
    const index = active[0].index;
    const bars = chart.getSortedVisibleDatasetMetas().map(meta => meta.data[index]).filter(Boolean).map(el => el.getProps(['x', 'y', 'base', 'width'], true));
    if (!bars.length) return;
    const x = bars[0].x, width = Math.max(...bars.map(b => b.width || 0));
    const top = Math.min(...bars.map(b => Math.min(b.y, b.base))), bottom = Math.max(...bars.map(b => Math.max(b.y, b.base)));
    const { ctx } = chart;
    ctx.save();
    ctx.shadowColor = o.glowColor || 'rgba(139,92,246,.32)'; ctx.shadowBlur = o.glowBlur || 18;
    ctx.strokeStyle = o.borderColor || 'rgba(139,92,246,.52)'; ctx.lineWidth = o.lineWidth || 2;
    roundedRectPath(ctx, x - width / 2 - 6, top - 6, width + 12, Math.max(8, bottom - top) + 12, o.radius || 22);
    ctx.stroke();
    ctx.restore();
  }
};

// 年度長條:每年頂端標合計
const barTotalLabelPlugin = {
  id: 'barTotalLabel',
  afterDatasetsDraw(chart, args, o) {
    const totals = o.totals || [];
    if (!totals.length) return;
    const meta = chart.getSortedVisibleDatasetMetas().find(m => m.data && m.data.length);
    if (!meta) return;
    const yScale = chart.scales.y, { ctx, chartArea } = chart;
    ctx.save();
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.font = `${o.weight || 800} ${o.fontSize || 11}px ${o.fontFamily}`;
    totals.forEach((val, i) => {
      val = Number(val || 0);
      if (!Number.isFinite(val) || val === 0 || !meta.data[i]) return;
      const x = meta.data[i].getProps(['x'], true).x;
      let y = yScale.getPixelForValue(val) + (val >= 0 ? -15 : 16);
      y = Math.max(chartArea.top + 12, Math.min(chartArea.bottom - 12, y));
      ctx.fillStyle = val >= 0 ? o.gainColor : o.lossColor;
      ctx.shadowColor = o.shadowColor || 'transparent'; ctx.shadowBlur = o.shadowBlur || 0;
      ctx.fillText(`${sign(val)}${fmt(val)}`, x, y);
    });
    ctx.restore();
  }
};

// 持股損益水平條:背景軌道 + 條尾標籤(放不下時改放條內白字)
const plLabelPlugin = {
  id: 'plLabel',
  beforeDatasetsDraw(chart, args, o) {
    const meta = chart.getDatasetMeta(0), { ctx, chartArea } = chart;
    if (!meta.data.length) return;
    ctx.save();
    ctx.fillStyle = o.trackColor || 'rgba(127,127,127,.09)';
    meta.data.forEach(el => {
      if (!el) return;
      const p = el.getProps(['y', 'height'], true), h = Math.min(p.height || 24, 30);
      roundedRectPath(ctx, chartArea.left, p.y - h / 2, chartArea.right - chartArea.left, h, h / 2);
      ctx.fill();
    });
    ctx.restore();
  },
  afterDatasetsDraw(chart, args, o) {
    const rows = o.rows || [];
    if (!rows.length) return;
    const meta = chart.getDatasetMeta(0), xScale = chart.scales.x, { ctx } = chart;
    ctx.save();
    ctx.textBaseline = 'middle';
    ctx.font = `${o.weight || 800} ${o.fontSize || 11}px ${o.fontFamily}`;
    ctx.shadowColor = o.shadowColor || 'transparent'; ctx.shadowBlur = o.shadowBlur || 0;
    rows.forEach((r, i) => {
      const el = meta.data[i]; if (!el) return;
      const y = el.getProps(['y'], true).y, xEnd = xScale.getPixelForValue(r.unrealized);
      const label = `${sign(r.unrealized)}${fmt(r.unrealized)} (${pct(r.plRatio)})`, w = ctx.measureText(label).width;
      if (r.unrealized >= 0) {
        if (xEnd + 10 + w <= chart.width - 4) { ctx.textAlign = 'left'; ctx.fillStyle = o.gainColor; ctx.fillText(label, xEnd + 10, y); }
        else { ctx.textAlign = 'right'; ctx.fillStyle = 'rgba(255,255,255,.95)'; ctx.fillText(label, xEnd - 12, y); }
      } else {
        if (xEnd - 10 - w >= 4) { ctx.textAlign = 'right'; ctx.fillStyle = o.lossColor; ctx.fillText(label, xEnd - 10, y); }
        else { ctx.textAlign = 'left'; ctx.fillStyle = 'rgba(255,255,255,.95)'; ctx.fillText(label, xEnd + 12, y); }
      }
    });
    ctx.restore();
  }
};

// 資產走勢:在總市值線上標「▲ 最高 / ▼ 最低」
const navPeaksPlugin = {
  id: 'navPeaks',
  afterDatasetsDraw(chart, args, o) {
    if (!o || !o.showPeaks || !o.mvData) return;
    const meta = chart.getDatasetMeta(2);
    if (!meta || meta.hidden) return;
    const c = chart.ctx, n = o.mvData.length - 1;
    c.save();
    c.font = '700 11px ' + o.chartFont;
    [[o.hiIdx, o.hiCol, '▲ 最高 ' + fmt(o.mvData[o.hiIdx]), -12], [o.loIdx, o.loCol, '▼ 最低 ' + fmt(o.mvData[o.loIdx]), 18]].forEach(([idx, col, txt, dy]) => {
      const pt = meta.data[idx]; if (!pt) return;
      c.textAlign = idx === 0 ? 'left' : idx === n ? 'right' : 'center';
      c.fillStyle = col;
      c.fillText(txt, pt.x, pt.y + dy);
    });
    c.restore();
  }
};

// 每日變動:標「賺最多 / 賠最多」;標籤會壓到圖外(最極端那根碰到邊)就改畫在 bar 內側
const chgExtremesPlugin = {
  id: 'chgExtremes',
  afterDatasetsDraw(chart, args, o) {
    if (!o) return;
    const meta = chart.getDatasetMeta(0), x = chart.ctx, area = chart.chartArea;
    x.save();
    x.font = '700 10px ' + o.chartFont; x.textAlign = 'center';
    const put = (idx, txt, col, up) => {
      const b = meta.data[idx]; if (!b) return;
      x.fillStyle = col;
      if (up) {                                                      // 預設畫在 bar 頂端上方;頂到天就往 bar 內畫
        if (b.y - 14 >= area.top) { x.textBaseline = 'bottom'; x.fillText(txt, b.x, b.y - 4); }
        else { x.textBaseline = 'top'; x.fillText(txt, b.x, b.y + 4); }
      } else {                                                       // 預設畫在 bar 底端下方;碰到 x 軸就往 bar 內畫
        if (b.y + 14 <= area.bottom) { x.textBaseline = 'top'; x.fillText(txt, b.x, b.y + 4); }
        else { x.textBaseline = 'bottom'; x.fillText(txt, b.x, b.y - 4); }
      }
    };
    if (o.upIdx >= 0) put(o.upIdx, '賺最多', o.upHiC, true);
    if (o.dnIdx >= 0) put(o.dnIdx, '賠最多', o.dnHiC, false);
    x.restore();
  }
};

// 回撤圖:谷底點上方標「▼ 最大回撤 -X%」
const ddLabelPlugin = {
  id: 'ddLabel',
  afterDatasetsDraw(chart, args, o) {
    if (!o || !(o.idx >= 0) || !o.text) return;
    const meta = chart.getDatasetMeta(0), pt = meta.data[o.idx]; if (!pt) return;
    const c = chart.ctx, n = meta.data.length - 1;
    c.save();
    c.font = '700 10px ' + o.chartFont; c.fillStyle = o.color; c.textBaseline = 'bottom';
    c.textAlign = o.idx === 0 ? 'left' : o.idx === n ? 'right' : 'center';
    c.fillText(o.text, pt.x, pt.y - 6);
    c.restore();
  }
};

// 總報酬瀑布:每根長條端點標金額、相鄰分項間畫接續線(本條終點 → 下一條起點)
const wfLabelPlugin = {
  id: 'wfLabel',
  afterDatasetsDraw(chart, args, o) {
    if (!o || !o.bars) return;
    const meta = chart.getDatasetMeta(0), ctx = chart.ctx;
    ctx.save();
    ctx.font = '700 11px ' + o.chartFont; ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
    meta.data.forEach((el, i) => {
      const b = o.bars[i]; if (!el || !b) return;
      const p = el.getProps(['x', 'y', 'base', 'width'], true);
      ctx.fillStyle = o.color;
      ctx.fillText((b.total ? '' : sign(b.v)) + fmt(b.v), p.x, Math.min(p.y, p.base) - 5);
      const nx = meta.data[i + 1];
      if (nx && o.bars[i + 1] && !o.bars[i + 1].total) {
        const q = nx.getProps(['x', 'width'], true);
        ctx.strokeStyle = o.connector; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(p.x + p.width / 2, p.y); ctx.lineTo(q.x - q.width / 2, p.y); ctx.stroke();
      }
    });
    ctx.restore();
  }
};

// 走勢圖群(資產 / 每日變動 / 對比 / 回撤)hover 同步:滑到某一天,其他圖同一天亮點 + 垂直十字線,tooltip 只留在滑鼠那張。
// 各圖 labels 都是 MM-DD;對比圖從第一個有大盤的日子起算,index 對不上,所以用 label 比對。同一格不重複 update。
const NAV_SYNC_GROUP = () => [navChart, navChgChart, navBenchChart, navDdChart].filter(Boolean);
let _navSyncing = false;
function navSyncApply(other, label, withTooltip) {
  const idx = label == null ? -1 : other.data.labels.indexOf(label);
  if (other._syncIdx === idx && !withTooltip) return;
  other._syncIdx = idx;
  if (idx < 0) {
    other.setActiveElements([]);
    other.tooltip.setActiveElements([], { x: 0, y: 0 });
  } else {
    const els = other.data.datasets.map((ds, di) => ({ datasetIndex: di, index: idx }))
      .filter(e => other.isDatasetVisible(e.datasetIndex) && other.getDatasetMeta(e.datasetIndex).data[idx]);
    other.setActiveElements(els);
    if (withTooltip) {
      const first = els.length ? other.getDatasetMeta(els[0].datasetIndex).data[idx] : null;
      other.tooltip.setActiveElements(els, first ? { x: first.x, y: first.y } : { x: 0, y: 0 });
    } else other.tooltip.setActiveElements([], { x: 0, y: 0 });
  }
  other.update('none');
}
const navSyncPlugin = {
  id: 'navSync',
  afterEvent(chart, args) {
    if (_navSyncing) return;
    const ev = args.event;
    if (!ev || (ev.type !== 'mousemove' && ev.type !== 'mouseout')) return;
    const act = chart.getActiveElements();
    const label = ev.type === 'mousemove' && act.length ? chart.data.labels[act[0].index] : null;
    _navSyncing = true;
    try { NAV_SYNC_GROUP().forEach(other => { if (other !== chart) navSyncApply(other, label, false); }); }
    finally { _navSyncing = false; }
  },
  afterDraw(chart, args, o) {                                        // 垂直十字線
    const act = chart.getActiveElements(); if (!act.length || !act[0].element) return;
    const { ctx, chartArea } = chart;
    ctx.save();
    ctx.strokeStyle = (o && o.color) || 'rgba(127,127,127,.45)'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(act[0].element.x, chartArea.top); ctx.lineTo(act[0].element.x, chartArea.bottom); ctx.stroke();
    ctx.restore();
  }
};
// 從外部(月曆熱圖點格子)把走勢圖群定位到某一天:全群亮點,資產走勢那張開 tooltip,並捲到看得到的位置。
// 該日不在目前區間 → 先切「全部」重畫再定位
function navSyncTo(ymd) {
  const label = String(ymd).slice(5);
  const go = () => {
    if (!navChart) return;
    _navSyncing = true;
    try { NAV_SYNC_GROUP().forEach(c => navSyncApply(c, label, c === navChart)); }
    finally { _navSyncing = false; }
    const cv = document.getElementById('nav');
    if (cv) cv.scrollIntoView({ block: 'center', behavior: REDUCED_MOTION ? 'auto' : 'smooth' });
  };
  if (navChart && navChart.data.labels.includes(label)) go();
  else if (navRangeDays !== 0) { setNavRange(0); setTimeout(go, 450); }
}

// 圓餅圖 tooltip 專用定位:推到甜甜圈外側,避免遮住中間總市值
if (window.Chart && Chart.Tooltip && Chart.Tooltip.positioners && !Chart.Tooltip.positioners.pieOuter) {
  Chart.Tooltip.positioners.pieOuter = function (elements) {
    if (!elements.length) return false;
    const arc = elements[0].element, chartArea = this.chart.chartArea;
    const angle = ((arc.startAngle || 0) + (arc.endAngle || 0)) / 2, radius = (arc.outerRadius || 0) + 46;
    const side = Math.cos(angle) >= 0 ? 1 : -1;
    const rawX = arc.x + Math.cos(angle) * radius, rawY = arc.y + Math.sin(angle) * radius;
    return {
      x: Math.max(chartArea.left + 74, Math.min(chartArea.right - 74, rawX)),
      y: Math.max(chartArea.top + 34, Math.min(chartArea.bottom - 34, rawY)),
      xAlign: side > 0 ? 'left' : 'right', yAlign: 'center'
    };
  };
}

/* ==================== 4. 各圖 ==================== */
let pieChart, barChart, plChart, navChart, navChgChart, navBenchChart, navDdChart, wfChart;

function topHoldingsForPie(held, limit = 5) {
  const sorted = [...held].sort((a, b) => b.mv - a.mv);
  const main = sorted.slice(0, limit), rest = sorted.slice(limit);
  const otherMv = rest.reduce((s, r) => s + r.mv, 0);
  if (otherMv > 0) main.push({ name: '其他', code: `${rest.length} 檔`, mv: otherMv, costAmt: rest.reduce((s, r) => s + r.costAmt, 0) });
  return main;
}

// 4.1 市值比例甜甜圈:兩種模式(純市值占比 / 成本+損益兩段)
function drawPie(T, held) {
  const canvas = document.getElementById('pie'); if (!canvas) return;
  const P = T.palette, A = T.isAgent;
  const pieRows = topHoldingsForPie(held);
  const totalMv = pieRows.reduce((s, r) => s + r.mv, 0);
  const pieMode = store.get('pf-pie-mode') || 'costpl';
  const pmb = document.getElementById('pie-mode-btn'); if (pmb) pmb.textContent = pieMode === 'costpl' ? '切換：純市值比例' : '切換：成本+損益';
  const centerText = { text: fmt(totalMv), subText: '總市值', color: A ? '#dfe7ff' : T.text, subColor: A ? '#8ea0c7' : T.muted, fontSize: A ? 18 : 17, subFontSize: A ? 12.5 : 12, fontFamily: T.chartFont, weight: A ? 900 : 800, subWeight: 700 };
  const tip = extra => tooltipOpts(T, Object.assign({ position: 'pieOuter', caretSize: 7 }, extra));
  const legendLabels = { usePointStyle: true, pointStyle: 'circle', boxWidth: 8, boxHeight: 8, padding: 14, font: font(T, 12), color: T.muted };
  const common = { borderColor: T.card, borderWidth: A ? 4 : 5, spacing: A ? 3 : 2 };
  let config;
  if (pieMode === 'value') {
    config = {
      type: 'doughnut',
      data: { labels: pieRows.map(r => `${r.name} (${r.code})`), datasets: [Object.assign({
        data: pieRows.map(r => r.mv), backgroundColor: pieRows.map((_, i) => P.slices[i % P.slices.length]),
        borderRadius: 12, hoverOffset: A ? 16 : 10, hoverBorderWidth: A ? 5 : 6
      }, common)] },
      options: baseOpts({
        cutout: A ? '56%' : '58%', layout: { padding: { top: 10, right: 56, bottom: 8, left: 56 } },
        plugins: {
          legend: { position: 'bottom', labels: legendLabels }, centerText,
          tooltip: tip({ callbacks: { title: items => items[0]?.label || '', label: c => [`市值 ${fmt(c.parsed)}`, `占比 ${pct(totalMv ? c.parsed / totalMv : 0)}`] } })
        }
      }),
      plugins: [centerTextPlugin]
    };
  } else {
    // 每檔兩段:成本(同色淡)+ 獲利(同色實);整圈 = 總市值
    const segVals = [], segColors = [], segMeta = [];
    pieRows.forEach((r, i) => {
      const base = P.slices[i % P.slices.length], gain = Math.max(0, r.mv - r.costAmt);
      segVals.push(r.mv - gain); segColors.push(withAlpha(base, .35)); segMeta.push(r);
      segVals.push(gain); segColors.push(base); segMeta.push(r);
    });
    config = {
      type: 'doughnut',
      data: { labels: segMeta.map(r => r.name), datasets: [Object.assign({ data: segVals, backgroundColor: segColors, borderRadius: 8, hoverOffset: A ? 14 : 8 }, common)] },
      options: baseOpts({
        cutout: A ? '56%' : '58%', layout: { padding: { top: 10, right: 56, bottom: 8, left: 56 } },
        plugins: {
          legend: { position: 'bottom', onClick: () => {}, labels: Object.assign({}, legendLabels, {
            generateLabels: () => pieRows.map((r, i) => ({ text: r.name, fillStyle: P.slices[i % P.slices.length], strokeStyle: 'transparent', lineWidth: 0, fontColor: T.muted }))
          }) },
          centerText,
          tooltip: tip({
            filter: item => !!segMeta[item.dataIndex],
            callbacks: {
              title: items => segMeta[items[0].dataIndex]?.name || '',
              label: c => {
                const r = segMeta[c.dataIndex] || {}, pl = (r.mv || 0) - (r.costAmt || 0);
                return [`成本 ${fmt(r.costAmt || 0)}`, `${pl >= 0 ? '＋ 獲利' : '－ 虧損'} ${fmt(Math.abs(pl))}`, `＝ 市值 ${fmt(r.mv || 0)}`,
                  `報酬率 ${sign(pl)}${pct(r.costAmt ? pl / r.costAmt : 0)} · 占比 ${pct(totalMv ? (r.mv || 0) / totalMv : 0)}`];
              }
            }
          })
        }
      }),
      plugins: [centerTextPlugin]
    };
  }
  pieChart = upsertChart(pieChart, canvas, config);
}

// 4.2 總報酬:大字 + 圖例(HTML)+ 瀑布圖(0 → 未實現 → 已實現 → 股息 → 總報酬;負分項往下走)
function drawReturn(T, held) {
  const P = T.palette;
  const unrealized = held.reduce((s, r) => s + r.unrealized, 0);
  const realized = (DATA && DATA['已實現損益']) || 0, dividend = (DATA && DATA['股息收入']) || 0;
  const total = unrealized + realized + dividend;
  const invested = held.reduce((s, r) => s + r.costAmt, 0), rate = invested ? total / invested : 0;
  const comps = [
    { label: '未實現損益', value: unrealized, color: P.slices[0] },
    { label: '已實現損益', value: realized, color: P.slices[2] },
    { label: '股息收入', value: dividend, color: P.dividend }
  ];
  const retColor = total > 0 ? P.gain : total < 0 ? P.loss : (T.isAgent ? '#dfe7ff' : T.text);
  const retEl = document.getElementById('retbar');
  if (retEl) {
    retEl.innerHTML = `
    <div class="ret-head"><span class="ret-total" style="color:${retColor}">${sign(total)}${fmt(total)}</span><span class="ret-rate" style="color:${retColor}">報酬率 ${sign(rate)}${pct(rate)}</span></div>
    <div class="ret-legend">${comps.map(c => `<span class="ret-leg"><span class="ret-sw" style="background:${c.color}"></span>${c.label} ${sign(c.value)}${fmt(c.value)} · ${pct(total ? c.value / total : 0)}</span>`).join('')}</div>`;
  }
  const canvas = document.getElementById('wf'); if (!canvas) return;
  let run = 0;
  const bars = comps.map(c => { const from = run; run += c.value; return { label: c.label, from, to: run, v: c.value, total: false }; });
  bars.push({ label: '總報酬', from: 0, to: total, v: total, total: true });
  const colorOf = b => b.total ? (T.isAgent ? '#67e8f9' : P.slices[0]) : (b.v >= 0 ? P.gain : P.loss);
  wfChart = upsertChart(wfChart, canvas, {
    plugins: [wfLabelPlugin],
    type: 'bar',
    data: { labels: bars.map(b => b.label), datasets: [{
      data: bars.map(b => [b.from, b.to]),
      backgroundColor: bars.map(b => b.total ? colorOf(b) : withAlpha(colorOf(b), .8)),
      hoverBackgroundColor: bars.map(colorOf),
      borderWidth: 0, borderRadius: 6, borderSkipped: false, barPercentage: .62, categoryPercentage: .8
    }] },
    options: baseOpts({
      layout: { padding: { top: 22, right: 8, bottom: 0, left: 2 } },
      scales: { x: { grid: { display: false }, ticks: { color: T.text, font: font(T, 12, 700) } }, y: axisY(T, tickWan) },
      plugins: {
        wfLabel: { bars, color: T.text, chartFont: T.chartFont, connector: T.border },
        legend: { display: false },
        tooltip: tooltipOpts(T, { displayColors: false, callbacks: { label: c => { const b = bars[c.dataIndex]; return b.total ? ` 總報酬 ${sign(b.v)}${fmt(b.v)}` : [` ${b.label} ${sign(b.v)}${fmt(b.v)}`, ` 累計 ${sign(b.to)}${fmt(b.to)}`]; } } })
      }
    })
  });
}

// 4.3 持股損益水平條(依損益排序)
function drawPl(T, held) {
  const canvas = document.getElementById('pl'); if (!canvas) return;
  const P = T.palette, A = T.isAgent;
  const rows = [...held].sort((a, b) => b.unrealized - a.unrealized);
  plChart = upsertChart(plChart, canvas, {
    type: 'bar',
    data: { labels: rows.map(r => `${r.name} (${r.code})`), datasets: [{
      label: '未實現損益', data: rows.map(r => r.unrealized),
      backgroundColor: c => {
        const area = c.chart.chartArea, r = rows[c.dataIndex] || {}, base = r.unrealized >= 0 ? P.gain : P.loss;
        if (!area) return base;
        const g = c.chart.ctx.createLinearGradient(area.left, 0, area.right, 0);
        g.addColorStop(0, withAlpha(base, .53)); g.addColorStop(1, base); return g;
      },
      hoverBackgroundColor: rows.map(r => r.unrealized >= 0 ? P.gain : P.loss),
      borderWidth: 0, borderRadius: 14, borderSkipped: false, minBarLength: 8, maxBarThickness: 28
    }] },
    options: baseOpts({
      indexAxis: 'y',
      layout: { padding: { top: 4, right: 12, bottom: 2, left: 2 } },
      animation: { duration: 820, easing: 'easeOutBack' },
      scales: {
        x: { border: { display: false }, grid: { color: c => c.tick.value === 0 ? T.zeroLine : 'transparent', lineWidth: c => c.tick.value === 0 ? 1.7 : 1, drawTicks: false },
             ticks: { color: T.tickColor, padding: 8, font: font(T, A ? 12 : 11.5, 800), callback: tickWan } },
        y: { border: { display: false }, grid: { display: false }, ticks: { color: A ? '#b9c4ee' : T.muted, font: font(T, A ? 12.5 : 12, 800) } }
      },
      plugins: {
        legend: { display: false },
        plLabel: { rows, gainColor: P.gain, lossColor: P.loss, shadowColor: A ? 'rgba(255,79,184,.32)' : 'transparent', shadowBlur: A ? 8 : 0, fontFamily: T.chartFont, fontSize: A ? 11.5 : 11, weight: 850 },
        tooltip: tooltipOpts(T, { displayColors: false, callbacks: {
          title: items => items[0]?.label || '',
          label: c => { const r = rows[c.dataIndex] || {}; return [`未實現損益：${sign(r.unrealized)}${fmt(r.unrealized || 0)}`, `損益比例：${pct(r.plRatio || 0)}`, `成本：${fmt(r.costAmt || 0)}　市值：${fmt(r.mv || 0)}`]; }
        } })
      }
    }),
    plugins: [plLabelPlugin]
  });
}

// 4.4 年度損益(資本利得 + 股息堆疊;鎖住時容器隱藏就不畫)
function drawYearly(T, ys) {
  const canvas = document.getElementById('bar'); if (!canvas) return;
  const P = T.palette, A = T.isAgent;
  const years = [...ys].sort((a, b) => String(a.year).localeCompare(String(b.year), 'zh-Hant', { numeric: true }))
    .map(y => ({ ...y, capitalGain: y.capitalGain || 0, dividend: y.dividend || 0, total: (y.capitalGain || 0) + (y.dividend || 0) }));
  const capital = years.map(y => y.capitalGain), divs = years.map(y => y.dividend);
  const barStyle = {
    stack: 'yearly', borderColor: A ? 'rgba(255,255,255,.34)' : 'rgba(255,255,255,.72)', hoverBorderColor: A ? '#f8e7ff' : T.text,
    borderWidth: A ? 2 : 1.5, hoverBorderWidth: A ? 4 : 3, borderRadius: 18, borderSkipped: false, borderJoinStyle: 'round',
    minBarLength: A ? 10 : 7, barThickness: A ? 48 : 42, maxBarThickness: A ? 64 : 56, categoryPercentage: .74
  };
  barChart = upsertChartIfVisible(barChart, canvas, {
    type: 'bar',
    data: { labels: years.map(y => y.year + (y.note ? ` ${y.note}` : '')), datasets: [
      Object.assign({ label: '資本利得', data: capital, backgroundColor: capital.map(v => v >= 0 ? P.gain : P.loss), hoverBackgroundColor: capital.map(v => v >= 0 ? P.gain : P.loss) }, barStyle),
      Object.assign({ label: '股息收入', data: divs, backgroundColor: divs.map(v => v >= 0 ? P.dividend : P.loss), hoverBackgroundColor: divs.map(v => v >= 0 ? P.dividend : P.loss) }, barStyle)
    ] },
    options: baseOpts({
      layout: { padding: { top: 34, right: 8, bottom: 2, left: 2 } },
      animation: { duration: 820, easing: 'easeOutBack' }, hover: { animationDuration: 220 },
      interaction: { mode: 'index', intersect: false },
      scales: {
        x: { stacked: true, grid: { display: false }, ticks: { color: A ? '#b9c4ee' : T.muted, font: font(T, A ? 12 : 11.5, 800) } },
        y: axisY(T, tickWan, { stacked: true, grid: { color: c => c.tick.value === 0 ? T.zeroLine : P.grid, lineWidth: c => c.tick.value === 0 ? 1.7 : 1, drawTicks: false }, ticks: { color: T.tickColor, padding: 10, font: font(T, A ? 12 : 11.5, 800) } })
      },
      plugins: {
        legend: legendBottom(T, 'rectRounded', { labels: { usePointStyle: true, pointStyle: 'rectRounded', color: A ? '#d4dcff' : T.muted, boxWidth: A ? 14 : 12, boxHeight: A ? 14 : 12, padding: 18, font: font(T, A ? 13 : 12, 800) } }),
        barHoverGlow: { glowColor: A ? 'rgba(255,79,184,.30)' : 'rgba(180,35,24,.18)', borderColor: A ? 'rgba(53,213,255,.72)' : 'rgba(52,64,84,.34)', glowBlur: A ? 24 : 14, radius: 26, lineWidth: A ? 2.5 : 2 },
        barTotalLabel: { totals: years.map(y => y.total), gainColor: P.gain, lossColor: P.loss, shadowColor: A ? 'rgba(255,79,184,.32)' : 'transparent', shadowBlur: A ? 8 : 0, fontFamily: T.chartFont, fontSize: A ? 11.5 : 11, weight: 850 },
        tooltip: tooltipOpts(T, { cornerRadius: 14, padding: 13, bodySpacing: 7, footerSpacing: 9, displayColors: true, boxWidth: 10, boxHeight: 10, boxPadding: 6,
          titleFont: font(T, 13, 850), bodyFont: font(T, 12.5, 750),
          callbacks: {
            title: items => years[items[0]?.dataIndex]?.year || '',
            label: c => ` ${c.dataset.label}：${sign(c.parsed.y || 0)}${fmt(c.parsed.y || 0)}`,
            footer: items => { const y = years[items[0]?.dataIndex] || {}; return `年度合計：${sign(y.total || 0)}${fmt(y.total || 0)}`; }
          } })
      }
    }),
    plugins: [barHoverGlowPlugin, barTotalLabelPlugin]
  });
}

// 4.5 走勢圖群:資產走勢 / 每日變動 / 對比大盤 / 回撤(共用區間與 hover 同步)+ 月曆熱圖(全史)
function drawNavGroup(T) {
  const P = T.palette;
  const el = id => document.getElementById(id);
  const navCanvas = el('nav'), navBox = navCanvas ? navCanvas.closest('.chart-box') : null, navEmpty = el('nav-empty');
  const wraps = { chg: el('navchg-wrap'), bench: el('navbench-wrap'), dd: el('navdd-wrap') };
  const show = (w, on) => { if (w) w.style.display = on ? '' : 'none'; };
  const S = PfCalc.histSlices(DATA.history, navRangeDays, tpeNow().date);
  const { full: histFull, hist, off } = S;
  const drawn = { nav: false, chg: false, bench: false, dd: false };   // 這一輪有畫到的走 update,沒畫到的最後 destroy

  if (!hist.length) {
    if (navBox) navBox.style.display = 'none';
    if (navEmpty) navEmpty.style.display = 'block';
    Object.values(wraps).forEach(w => show(w, false));
  } else if (navCanvas) {
    if (navBox) navBox.style.display = '';
    if (navEmpty) navEmpty.style.display = 'none';
    const labels = hist.map(p => String(p.date).slice(5));
    const costData = hist.map(p => Number(p.cost) || 0), unData = hist.map(p => Number(p.un) || 0);
    const mvData = hist.map((p, i) => costData[i] + unData[i]);
    const many = hist.length > 60;
    const hiCol = T.v('--accent'), loCol = hiCol;                  // 極值 / 賺賠最多 / 回撤谷底一律主色:靠 ▲▼ 與形狀區分,不多開 hue
    const sync = { color: T.syncCol };

    // 資產走勢:堆疊面積(成本 + 未實現 ≈ 總市值),總市值虛線標最高 / 最低
    const ex = PfCalc.extremes(mvData);
    const showPeaks = mvData.length >= 2 && ex.hi !== ex.lo;
    const costColor = P.slices[5] || P.slices[P.slices.length - 1];
    drawn.nav = true;
    navChart = upsertChart(navChart, navCanvas, {
      plugins: [navPeaksPlugin, navSyncPlugin],
      type: 'line',
      data: { labels, datasets: [
        { label: '成本', data: costData, stack: 'comp', borderColor: costColor, backgroundColor: areaGrad(costColor, .48, .08), borderWidth: 1.5, fill: true, tension: .3, pointRadius: many ? 0 : 2, pointHoverRadius: 5, pointStyle: 'rectRounded' },
        { label: '未實現損益', data: unData, stack: 'comp', borderColor: P.gain, backgroundColor: areaGrad(P.gain, .6, .1), borderWidth: 1.5, fill: true, tension: .3, pointRadius: many ? 0 : 2, pointHoverRadius: 5, pointStyle: 'rectRounded' },
        { label: '總市值', data: mvData, stack: 'mv', borderColor: T.text, borderWidth: 2, borderDash: [6, 4], fill: false, tension: .3, pointStyle: 'line',
          pointRadius: mvData.map((_, i) => showPeaks && (i === ex.hi || i === ex.lo) ? 5 : 0),
          pointBackgroundColor: mvData.map((_, i) => i === ex.hi ? hiCol : i === ex.lo ? loCol : 'transparent'),
          pointBorderColor: mvData.map((_, i) => i === ex.hi ? hiCol : i === ex.lo ? loCol : 'transparent'), pointHoverRadius: 5 }
      ] },
      options: baseOpts({
        interaction: { mode: 'index', intersect: false },
        layout: { padding: { top: 20, right: 10, bottom: 2, left: 2 } },
        scales: { x: axisX(T, { stacked: true }), y: axisY(T, tickWan, { stacked: true, beginAtZero: true, ticks: { maxTicksLimit: 6 } }) },
        plugins: {
          navPeaks: { showPeaks, hiIdx: ex.hi, loIdx: ex.lo, hiCol, loCol, mvData, chartFont: T.chartFont },
          navSync: sync,
          legend: legendBottom(T, 'rectRounded'),
          tooltip: tooltipOpts(T, { displayColors: true, callbacks: { label: c => c.dataset.label === '總市值' ? ` 總市值：${fmt(c.parsed.y)}` : ` ${c.dataset.label}：${sign(c.parsed.y)}${fmt(c.parsed.y)}` } })
        }
      })
    });

    // 每日損益變動(較前一日未實現;紅賺綠賠,區間內賺最多 / 賠最多高亮)
    const chgCanvas = el('navchg');
    if (wraps.chg && chgCanvas && mvData.length >= 2) {
      show(wraps.chg, true);
      const chg = PfCalc.dailyChanges(unData);
      let upIdx = -1, dnIdx = -1, upMax = 0, dnMin = 0;
      chg.forEach((v, i) => { if (i === 0) return; if (v > upMax) { upMax = v; upIdx = i; } if (v < dnMin) { dnMin = v; dnIdx = i; } });
      drawn.chg = true;
      navChgChart = upsertChart(navChgChart, chgCanvas, {
        plugins: [chgExtremesPlugin, navSyncPlugin],
        type: 'bar',
        data: { labels, datasets: [{ label: '損益變動', data: chg, backgroundColor: chg.map((v, i) => i === upIdx ? hiCol : i === dnIdx ? loCol : (v >= 0 ? P.gain : P.loss)), borderRadius: 3, borderSkipped: false, barPercentage: .9, categoryPercentage: .8 }] },
        options: baseOpts({
          interaction: { mode: 'index', intersect: false },
          layout: { padding: { top: 18, right: 10, bottom: 14, left: 2 } },
          scales: { x: axisX(T), y: axisY(T, tickWanSigned) },
          plugins: {
            chgExtremes: { upIdx, dnIdx, upHiC: hiCol, dnHiC: loCol, chartFont: T.chartFont },
            navSync: sync, legend: { display: false },
            tooltip: tooltipOpts(T, { displayColors: false, callbacks: { label: c => ` 損益變動：${sign(c.parsed.y)}${fmt(c.parsed.y)}` } })
          }
        })
      });
    } else show(wraps.chg, false);

    // 報酬對比:我的組合 vs 加權指數 vs 台積電,以區間內第一個有大盤資料的點為 0%
    const benchCanvas = el('navbench');
    const B = PfCalc.benchLines(mvData, hist.map(p => Number(p.taiex) || 0), hist.map(p => Number(p.tsmc) || 0));
    if (wraps.bench && benchCanvas && B) {
      show(wraps.bench, true);
      const sets = [
        { label: '我的組合', data: B.me, borderColor: P.slices[0], backgroundColor: withAlpha(P.slices[0], .13), borderWidth: 2.5, fill: false, tension: .3, spanGaps: true, pointRadius: 0, pointHoverRadius: 5 },
        { label: '加權指數', data: B.tw, borderColor: T.muted, borderWidth: 2, borderDash: [6, 4], fill: false, tension: .3, spanGaps: true, pointRadius: 0, pointHoverRadius: 5 }
      ];
      if (B.tsmc) sets.push({ label: '台積電', data: B.tsmc, borderColor: P.slices[1] || P.gain, borderWidth: 2, borderDash: [2, 3], fill: false, tension: .3, spanGaps: true, pointRadius: 0, pointHoverRadius: 5 });
      drawn.bench = true;
      navBenchChart = upsertChart(navBenchChart, benchCanvas, {
        plugins: [navSyncPlugin],
        type: 'line',
        data: { labels: labels.slice(B.firstT), datasets: sets },
        options: baseOpts({
          interaction: { mode: 'index', intersect: false },
          layout: { padding: { top: 6, right: 10, bottom: 2, left: 2 } },
          scales: { x: axisX(T), y: axisY(T, tickPct) },
          plugins: {
            navSync: sync,
            legend: legendBottom(T, 'line', { labels: { usePointStyle: true, pointStyle: 'line', color: T.text, padding: 16, font: font(T, 12, 700) } }),
            tooltip: tooltipOpts(T, { displayColors: true, callbacks: { label: c => c.parsed.y == null ? null : ` ${c.dataset.label}：${c.parsed.y > 0 ? '+' : ''}${c.parsed.y.toFixed(2)}%` } })
          }
        })
      });
    } else show(wraps.bench, false);

    // 回撤:總報酬距「截至當日歷史最高」掉多少(佔成本 %);前高看全史、畫面只看區間
    const ddCanvas = el('navdd'), ddSub = el('navdd-sub');
    const W = PfCalc.worstDrawdown(PfCalc.drawdown(histFull.map(p => Number(p.ret) || 0), histFull.map(p => Number(p.cost) || 0)), off);
    if (wraps.dd && ddCanvas && W && hist.length >= 2) {
      show(wraps.dd, true);
      const dd = W.dd, cur = dd[dd.length - 1];
      const ddCol = P.loss, ddHi = loCol;
      if (ddSub) {
        const peakDate = histFull[W.peakIdx] ? String(histFull[W.peakIdx].date).slice(5) : '';
        const worstTxt = W.pct < 0 ? `最大回撤 ${W.pct.toFixed(1)}%(${peakDate} → ${labels[W.idx]},${W.days} 日,${fmt(W.amt)})` : '區間內沒有回撤';
        const curTxt = cur.pct < 0 ? `目前 ${cur.pct.toFixed(1)}%,離新高差 ${fmt(-cur.amt)}` : '目前在新高 ●';
        ddSub.textContent = `${worstTxt} · ${curTxt}`;
      }
      drawn.dd = true;
      navDdChart = upsertChart(navDdChart, ddCanvas, {
        plugins: [ddLabelPlugin, navSyncPlugin],
        type: 'line',
        data: { labels, datasets: [{
          label: '回撤', data: dd.map(x => Math.round(x.pct * 100) / 100), borderColor: ddCol, borderWidth: 1.5, fill: 'origin',
          backgroundColor: c => { const area = c.chart.chartArea; if (!area) return withAlpha(ddCol, .33); const g = c.chart.ctx.createLinearGradient(0, area.top, 0, area.bottom); g.addColorStop(0, withAlpha(ddCol, .06)); g.addColorStop(1, withAlpha(ddCol, .53)); return g; },
          tension: .3, pointRadius: dd.map((_, i) => i === W.idx && W.pct < 0 ? 4 : 0), pointBackgroundColor: ddHi, pointBorderColor: ddHi, pointHoverRadius: 5
        }] },
        options: baseOpts({
          interaction: { mode: 'index', intersect: false },
          layout: { padding: { top: 16, right: 10, bottom: 2, left: 2 } },
          scales: { x: axisX(T), y: axisY(T, v => v.toFixed(1) + '%', { max: 0, suggestedMin: -1 }) },
          plugins: {
            ddLabel: { idx: W.pct < 0 ? W.idx : -1, text: `▼ 最大回撤 ${W.pct.toFixed(1)}%`, color: ddHi, chartFont: T.chartFont },
            navSync: sync, legend: { display: false },
            tooltip: tooltipOpts(T, { displayColors: false, callbacks: { label: c => { const x = dd[c.dataIndex]; return x && x.amt < 0 ? [` 距前高 ${x.pct.toFixed(2)}%`, ` 回吐 ${fmt(x.amt)}`] : ' 位於前高'; } } })
          }
        })
      });
    } else show(wraps.dd, false);
  }

  drawHeatmap(T, histFull);

  // 這一輪沒畫到的走勢圖(資料不足 / 隱藏)才 destroy;有畫到的都已走 update()
  if (!drawn.nav && navChart) { navChart.destroy(); navChart = null; }
  if (!drawn.chg && navChgChart) { navChgChart.destroy(); navChgChart = null; }
  if (!drawn.bench && navBenchChart) { navBenchChart.destroy(); navBenchChart = null; }
  if (!drawn.dd && navDdChart) { navDdChart.destroy(); navDdChart = null; }
}

// 4.6 每日損益月曆熱圖 + 統計卡:CSS grid(欄 = 週一起算的週、列 = 週一~週五),diverging 配色(賺 = gain、賠 = loss、0 = 底色),
// 深淺 = √(|金額| / 區間最大) 讓小額也看得見;近 26 週;點格子 → 走勢圖群定位到那天
function drawHeatmap(T, histFull) {
  const P = T.palette;
  const panel = document.getElementById('heat-panel'), box = document.getElementById('heatmap'), leg = document.getElementById('heat-legend'), statsEl = document.getElementById('heat-stats');
  if (!panel || !box) return;
  const pts = histFull.filter(p => p && p.date);
  if (pts.length < 2) { panel.style.display = 'none'; return; }
  const chg = PfCalc.dailyChanges(pts.map(p => Number(p.un) || 0));
  const days = pts.slice(1).map((p, i) => ({ date: String(p.date), chg: chg[i + 1] }));   // 第一筆沒前值不列
  const MAX_WEEKS = 26;
  const toDate = ds => { const m = ds.split('-'); return new Date(+m[0], +m[1] - 1, +m[2]); };
  const monday = d => { const x = new Date(d); x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); x.setHours(0, 0, 0, 0); return x; };
  const key = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const lastMon = monday(toDate(days[days.length - 1].date));
  const capMon = new Date(lastMon); capMon.setDate(capMon.getDate() - 7 * (MAX_WEEKS - 1));
  const dataMon = monday(toDate(days[0].date));
  const startMon = dataMon > capMon ? dataMon : capMon;
  const weeks = []; for (let d = new Date(startMon); d <= lastMon; d.setDate(d.getDate() + 7)) weeks.push(new Date(d));
  const shown = days.filter(x => toDate(x.date) >= startMon);
  const byDate = new Map(shown.map(x => [x.date, x.chg]));
  const maxAbs = Math.max(1, ...shown.map(x => Math.abs(x.chg)));
  const alpha = v => 0.18 + 0.82 * Math.sqrt(Math.min(1, Math.abs(v) / maxAbs));
  const cellBg = v => v > 0 ? withAlpha(P.gain, alpha(v)) : v < 0 ? withAlpha(P.loss, alpha(v)) : '';
  const today = tpeNow().date, dows = ['一', '二', '三', '四', '五'];
  let html = '<div class="hm-mon" style="grid-column:1;grid-row:1"></div>';
  let lastM = -1;                                                   // 月份列:該週一所在月份變了才標
  weeks.forEach((w, ci) => { const m = w.getMonth(); if (m !== lastM) { html += `<div class="hm-mon" style="grid-column:${ci + 2};grid-row:1">${m + 1}月</div>`; lastM = m; } });
  dows.forEach((t, ri) => { html += `<div class="hm-dow" style="grid-column:1;grid-row:${ri + 2}">${t}</div>`; });
  weeks.forEach((w, ci) => {
    for (let ri = 0; ri < 5; ri++) {
      const d = new Date(w); d.setDate(d.getDate() + ri); const k = key(d);
      if (k > today) continue;
      const v = byDate.get(k), pos = `grid-column:${ci + 2};grid-row:${ri + 2}`;
      if (v === undefined) { html += `<div class="hm-cell hm-nodata" style="${pos}" title="${k}(週${dows[ri]}) 無資料:休市或未記錄"></div>`; continue; }
      const bg = cellBg(v);
      html += `<div class="hm-cell" data-date="${k}" style="${pos}${bg ? ';background:' + bg : ''}" title="${k}(週${dows[ri]}) ${sign(v)}${fmt(v)}　點一下 → 走勢圖定位" role="button" tabindex="0"></div>`;
    }
  });
  box.style.gridTemplateColumns = `28px repeat(${weeks.length}, minmax(0, 1fr))`;
  box.style.maxWidth = `${28 + weeks.length * 37}px`;              // 格子最大 34px + 3px 間距;週數少不放大、螢幕窄等比縮
  box.innerHTML = html;
  if (!box._bound) {                                                // 點格子 → 走勢圖群定位(事件委派,只綁一次)
    box._bound = true;
    const act = e => { const c = e.target.closest('.hm-cell[data-date]'); if (c) navSyncTo(c.dataset.date); };
    box.addEventListener('click', act);
    box.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); act(e); } });
  }
  if (leg) {
    const steps = [1, .55, .25];
    leg.innerHTML = '<span>賠</span>'
      + steps.map(t => `<span class="hm-sw" style="background:${withAlpha(P.loss, alpha(t * maxAbs))}"></span>`).join('')
      + '<span class="hm-sw" style="background:var(--total-bg)"></span>'
      + steps.slice().reverse().map(t => `<span class="hm-sw" style="background:${withAlpha(P.gain, alpha(t * maxAbs))}"></span>`).join('')
      + `<span>賺</span><span class="hm-legend-max">最深 = ${fmt(maxAbs)}</span>`;
  }
  if (statsEl) {                                                    // 統計卡(近 26 週)
    const s = PfCalc.dailyStats(shown);
    const tile = (k, v, cls2) => `<div class="hs"><div class="k">${k}</div><div class="v ${cls2 || ''}">${v}</div></div>`;
    const streakTxt = s.curStreak > 0 ? `連賺 ${s.curStreak} 天` : s.curStreak < 0 ? `連賠 ${-s.curStreak} 天` : '持平';
    statsEl.innerHTML =
      tile('勝率', `${(s.winRate * 100).toFixed(0)}%`, s.winRate >= .5 ? 'up' : 'down') +
      tile('賺 / 賠 天數', `${s.wins} / ${s.losses}`) +
      tile('平均賺一天', s.wins ? '+' + fmt(s.avgWin) : '—', 'up') +
      tile('平均賠一天', s.losses ? fmt(s.avgLoss) : '—', 'down') +
      tile('最佳日', s.best && s.best.chg > 0 ? `${s.best.date.slice(5)} +${fmt(s.best.chg)}` : '—', 'up') +
      tile('最差日', s.worst && s.worst.chg < 0 ? `${s.worst.date.slice(5)} ${fmt(s.worst.chg)}` : '—', 'down') +
      tile('最長連賺 / 連賠', `${s.maxWinStreak} / ${s.maxLossStreak} 天`) +
      tile('目前', streakTxt, s.curStreak > 0 ? 'up' : s.curStreak < 0 ? 'down' : '');
  }
  panel.style.display = '';
}

/* ==================== 5. 統籌 ==================== */
function drawCharts(held, ys) {
  const T = chartTheme();
  drawPie(T, held);
  drawReturn(T, held);
  drawPl(T, held);
  drawYearly(T, ys);
  drawNavGroup(T);
}
// 切分頁回總覽時 canvas 尺寸可能變了,全部 resize 一次
function resizeAllCharts() {
  [pieChart, barChart, plChart, navChart, navChgChart, navBenchChart, navDdChart, wfChart].forEach(c => { if (c) c.resize(); });
}
