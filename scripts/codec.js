/* 胖虎的小財庫 — data.json 編解碼共用模組(UMD)
   前端 index.html:<script src="scripts/codec.js"> → window.PfCodec
   GitHub Action scripts/update-prices.mjs、tools/show-data.mjs:createRequire(import.meta.url)('./codec.js')
   兩邊都用 WebCrypto(globalThis.crypto.subtle;Node 20+ 內建),沒有 node:crypto 依賴。

   為什麼有 v2(2026-10-31):v1 是整包 AES-GCM 一行密文、每次隨機 iv,排程每 10 分鐘重寫 → 每版 38 KB 全新、git 完全沒 delta,
   3,433 版就吃掉 57 MB(repo 歷史的 57%),一年約 1 GB。v2 把會變的拆開、不變的部分每次產出的 byte 一模一樣:
     {"enc":2,
      "updated":"…","priceUpdated":"…",                     ← 明文:時間戳不敏感
      "quotes":{"2330":{"price":…,"prevClose":…,…},…},      ← 明文:各檔市價 / 昨收 / 抓價時間 / Yahoo 後綴 / 除息。代號是公開資訊,沒有張數與成本
      "head":"<b64 iv+ct>",                                  ← 加密:持股(去掉上面市價欄位)、費率、帳戶、年度、密碼雜湊、提醒狀態…只在你儲存或提醒狀態變時才變
      "hist":["<b64 iv+ct>",…]}                              ← 加密:history 一天一筆、一行一筆;只有今天那筆每次不同
   iv 不再隨機,改成 HMAC-SHA256(金鑰, 明文) 前 12 bytes(SIV 式):同樣明文 → 同樣密文,git 才有 delta;
   同 iv 只會在同明文時出現,所以 GCM 的 iv 重用問題不存在;只洩漏「這一筆和上次一樣」,對「防君子不防小人」的混淆夠用。
   解碼相容 v1({enc:1})與更早的明文檔;前端讀到 v1、Action 下次寫回就自動變 v2。 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.PfCodec = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  var KEY_B64 = '3Nr6TNQZewwC/3wye+lwc60BCeWcaPRmQddHyAbS+uc=';   // 混淆金鑰(公開程式內 = 防君子不防小人);改了舊檔就解不開
  var QUOTE_FIELDS = ['price', 'prevClose', 'priceTime', 'yahooSym', 'exDiv'];   // 與 calc.js SERVER_FIELDS 同一組:Action 寫、前端只讀
  var subtle = (typeof crypto !== 'undefined' && crypto.subtle) || (typeof globalThis !== 'undefined' && globalThis.crypto && globalThis.crypto.subtle);
  var enc = new TextEncoder(), dec = new TextDecoder();
  var hasBuffer = typeof Buffer !== 'undefined';
  function b64enc(bytes) {
    bytes = new Uint8Array(bytes);
    if (hasBuffer) return Buffer.from(bytes).toString('base64');
    var s = ''; for (var i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return btoa(s);
  }
  function b64dec(s) {
    if (hasBuffer) return new Uint8Array(Buffer.from(s, 'base64'));
    var bin = atob(s), out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }
  var _aes = null, _mac = null;
  function aesKey() { return _aes || (_aes = subtle.importKey('raw', b64dec(KEY_B64), { name: 'AES-GCM' }, false, ['encrypt', 'decrypt'])); }
  function macKey() { return _mac || (_mac = subtle.importKey('raw', b64dec(KEY_B64), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'])); }

  // 確定性加密:iv = HMAC(key, 明文)[0..12);輸出 b64(iv ‖ ct ‖ tag)
  async function sealDet(text) {
    var pt = enc.encode(text);
    var iv = new Uint8Array(await subtle.sign('HMAC', await macKey(), pt)).subarray(0, 12);
    var ct = new Uint8Array(await subtle.encrypt({ name: 'AES-GCM', iv: iv }, await aesKey(), pt));
    var out = new Uint8Array(12 + ct.length); out.set(iv, 0); out.set(ct, 12);
    return b64enc(out);
  }
  async function open(b64) {
    var all = b64dec(b64);
    var pt = await subtle.decrypt({ name: 'AES-GCM', iv: all.subarray(0, 12) }, await aesKey(), all.subarray(12));
    return dec.decode(pt);
  }
  // v1:{enc:1, iv, ct}(ct 尾 16 bytes 是 tag,WebCrypto 的 decrypt 本來就這樣吃)
  async function openV1(o) {
    var pt = await subtle.decrypt({ name: 'AES-GCM', iv: b64dec(o.iv) }, await aesKey(), b64dec(o.ct));
    return JSON.parse(dec.decode(pt));
  }

  // 明文物件 → v2 物件(不含換行;要落檔用 stringify)
  async function encode(data) {
    var head = {}, quotes = {};
    Object.keys(data).forEach(function (k) { if (k !== 'history' && k !== 'holdings' && k !== 'updated' && k !== 'priceUpdated') head[k] = data[k]; });
    head.holdings = (data.holdings || []).map(function (h) {
      var o = {};
      Object.keys(h).forEach(function (k) { if (QUOTE_FIELDS.indexOf(k) < 0) o[k] = h[k]; });
      if (h.code) {
        var q = {};
        QUOTE_FIELDS.forEach(function (k) { if (h[k] !== undefined) q[k] = h[k]; });
        if (Object.keys(q).length) quotes[h.code] = q;
      }
      return o;
    });
    var hist = [];
    for (var i = 0; i < (data.history || []).length; i++) hist.push(await sealDet(JSON.stringify(data.history[i])));
    var out = { enc: 2 };
    if (data.updated !== undefined) out.updated = data.updated;
    if (data.priceUpdated !== undefined) out.priceUpdated = data.priceUpdated;
    out.quotes = quotes;
    out.head = await sealDet(JSON.stringify(head));
    out.hist = hist;
    return out;
  }
  // v2 物件 → 落檔字串:hist 一行一筆,git diff 只看到今天那行
  function stringify(v2) {
    var o = {}; Object.keys(v2).forEach(function (k) { if (k !== 'hist') o[k] = v2[k]; });
    var top = JSON.stringify(o);
    return top.slice(0, -1) + ',\n"hist":[\n' + (v2.hist || []).map(function (s) { return JSON.stringify(s); }).join(',\n') + '\n]}\n';
  }
  // 任何版本(明文 / v1 / v2)→ 明文物件
  async function decode(raw) {
    if (!raw || typeof raw !== 'object') return raw;
    if (raw.enc === 1) return openV1(raw);
    if (raw.enc !== 2) return raw;
    var data = JSON.parse(await open(raw.head));
    data.holdings = data.holdings || [];
    var quotes = raw.quotes || {};
    data.holdings.forEach(function (h) {
      var q = h && h.code && quotes[h.code];
      if (q) QUOTE_FIELDS.forEach(function (k) { if (q[k] !== undefined) h[k] = q[k]; });
    });
    data.history = [];
    for (var i = 0; i < (raw.hist || []).length; i++) data.history.push(JSON.parse(await open(raw.hist[i])));
    if (raw.updated !== undefined) data.updated = raw.updated;
    if (raw.priceUpdated !== undefined) data.priceUpdated = raw.priceUpdated;
    return data;
  }
  return { encode: encode, decode: decode, stringify: stringify, QUOTE_FIELDS: QUOTE_FIELDS, KEY_B64: KEY_B64 };
});
