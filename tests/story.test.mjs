// 說書人(scripts/story.js):同一天同一則、換一則會變、只用帶進來的數字、兩個世界都能講、修仙境界換算、避開前幾天的句子
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const S = createRequire(import.meta.url)('../scripts/story.js');

const inp = { date: '2026-10-19', hhmm: 1025, day: 84, taiexPct: -0.018, todayChg: -279900, todayPct: -0.0238, totalReturn: 4334328, mv: 11461150,
  lv: 21, vaultTier: 5, best: { name: '元大台灣50之甲', pct: 0.003, rarity: 'common' }, worst: { name: '台積電之盾', pct: -0.031 },
  ath: false, exDiv: [], buys: ['0050 元大台灣50 1 張'], sells: [], stops: [], targets: [], ach: ['雙傳說'] };
const a = S.tell(inp, { world: '奇幻' }), b = S.tell(inp, { world: '奇幻' }), c = S.tell(inp, { world: '奇幻', roll: 1 });
assert.deepEqual(a, b, '同一天同一則');
assert.notDeepEqual(a.lines.map(l => l.t), c.lines.map(l => l.t), '換一則會變');
const text = a.lines.map(l => l.t).join('\n');
assert.match(text, /-28\.0萬\(-2\.38%\)/, '今日戰果用帶進來的數字');
assert.match(text, /台積電之盾/); assert.match(text, /0050 元大台灣50 1 張/); assert.match(text, /雙傳說/);
assert.match(a.title, /^第 84 回　/);
assert.ok(!/\{[^}]+\}/.test(text + a.title), '沒有沒展開的 {佔位}');
const x = S.tell(inp, { world: '修仙' });
assert.match(x.lines.map(l => l.t).join(''), /今日修為/);
assert.equal(S.TERMS['修仙'].lv(21), '煉虛・一層');
assert.equal(S.TERMS['奇幻'].lv(21), 'Lv.21');
assert.equal(S.mood(0.02), 2); assert.equal(S.mood(-0.02), -2); assert.equal(S.mood(0), 0);
// 避開前幾天用過的句子:把 a 用過的全部列入 avoid,開場句應該換掉
const d = S.tell(inp, { world: '奇幻', avoid: a.used });
assert.notEqual(d.lines[0].t, a.lines[0].t);
// 上漲日 + 新高 + 除息
const up = S.tell({ ...inp, taiexPct: 0.02, todayChg: 150000, todayPct: 0.013, ath: true, exDiv: ['0050 每股 1.5 元'], ach: [], buys: [] }, { world: '奇幻' });
const ut = up.lines.map(l => l.t).join('\n');
assert.match(ut, /\+15\.0萬\(\+1\.30%\)/); assert.match(ut, /新高/); assert.match(ut, /0050 每股 1\.5 元/);
console.log('story.test: 18 項通過');
