'use strict';

let DATA = null, VALID = null, VIEW = 'home', CAT = 0;
let BASE_LONG = null, BASE_FX = null;   // 何もせず買った場合の上昇率
let DIR = null, DIR_LOADING = false;    // 銘柄索引（保有タブでだけ使う・別ファイル）
let HOLD_Q = '';                        // 銘柄検索の入力

/* 索引は600件近くあり本体に含めると重いので、保有タブを開いたときだけ取りに行く。 */
async function loadDirectory() {
  if (DIR || DIR_LOADING) return DIR;
  DIR_LOADING = true;
  try {
    const r = await fetch('data/directory.json');
    DIR = (await r.json()).items || [];
  } catch (e) {
    DIR = [];
  } finally {
    DIR_LOADING = false;
  }
  if (VIEW === 'hold') render();
  return DIR;
}

/* ---------- 小さなヘルパ ---------- */
const $ = s => document.querySelector(s);
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const pct = (v, d = 2) => (v == null ? '—' : (v >= 0 ? '+' : '') + (v * 100).toFixed(d) + '%');
const cls = v => (v == null ? '' : v > 0 ? 'up' : v < 0 ? 'down' : '');
const num = (v, d = 2) => (v == null ? '—' : Number(v).toLocaleString('ja-JP',
  { minimumFractionDigits: d, maximumFractionDigits: d }));
const yen = v => (v == null || !isFinite(v) ? '—' : '¥' + Math.round(v).toLocaleString('ja-JP'));

function price(v, cur) {
  if (v == null) return '—';
  const d = v >= 1000 ? 0 : v >= 10 ? 2 : v >= 1 ? 3 : 4;
  const s = num(v, d);
  return cur === 'JPY' ? '¥' + s : cur === 'USD' ? '$' + s : s;
}

function ymd(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`;
}

/* ---------- 設定（この端末にだけ保存される） ---------- */
const SET_KEY = 'mr-settings';
const MAX_LEVERAGE = 25;

function settings() {
  const d = DATA || {};
  const sd = d.stock_defaults || {};
  const fp = (d.fx && d.fx.plan) || {};
  const def = {
    capital: fp.capital || 40000, target: fp.target || 10000,
    risk: fp.risk_per_trade || 0.02, trades: fp.trades_per_day || 1,
    stockCapital: sd.capital || 300000, stockRisk: sd.risk || 0.02,
    fxConf: d.fx_min_confidence || 0.56,   // シグナルとみなす確信度の下限
    holdings: [],
  };
  try {
    return Object.assign({}, def, JSON.parse(localStorage.getItem(SET_KEY) || '{}'));
  } catch (e) { return def; }
}

function saveSettings(s) {
  try { localStorage.setItem(SET_KEY, JSON.stringify(s)); } catch (e) { }
}

/* ---------- 価格チャート ---------- */
function chartSVG(ch, height) {
  if (!ch || !ch.c || ch.c.length < 2) return '';
  const c = ch.c, n = c.length;
  const H = height || 150, W = 320, PAD_T = 10, PAD_B = 18, PAD_R = 46;
  const plotW = W - PAD_R, plotH = H - PAD_T - PAD_B;
  const all = c.concat((ch.sma50 || []).filter(v => v != null));
  let lo = Math.min(...all), hi = Math.max(...all);
  if (hi === lo) { hi = lo * 1.01 || 1; lo = lo * 0.99 || 0; }
  const pad = (hi - lo) * 0.06;
  lo -= pad; hi += pad;
  const X = i => (i / (n - 1)) * plotW;
  const Y = v => PAD_T + plotH - ((v - lo) / (hi - lo)) * plotH;
  const line = arr => {
    let d = '', pen = false;
    for (let i = 0; i < n; i++) {
      const v = arr[i];
      if (v == null) { pen = false; continue; }
      d += (pen ? 'L' : 'M') + X(i).toFixed(1) + ' ' + Y(v).toFixed(1) + ' ';
      pen = true;
    }
    return d.trim();
  };
  const rising = c[n - 1] >= c[0];
  const col = rising ? 'var(--up)' : 'var(--down)';
  const area = line(c) + ` L${plotW.toFixed(1)} ${(PAD_T + plotH).toFixed(1)} L0 ${(PAD_T + plotH).toFixed(1)} Z`;
  const gid = 'g' + Math.random().toString(36).slice(2, 8);
  const ticks = [hi - pad, (hi + lo) / 2, lo + pad].map(v => `
    <line x1="0" y1="${Y(v).toFixed(1)}" x2="${plotW}" y2="${Y(v).toFixed(1)}"
      stroke="var(--line)" stroke-width="0.6" stroke-dasharray="2 3"/>
    <text x="${plotW + 5}" y="${(Y(v) + 3.5).toFixed(1)}" class="ax">${num(v, v >= 1000 ? 0 : v >= 10 ? 1 : 3)}</text>`).join('');
  const last = c[n - 1];
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img">
    <defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="${col}" stop-opacity="0.26"/>
      <stop offset="100%" stop-color="${col}" stop-opacity="0"/>
    </linearGradient></defs>
    ${ticks}
    <path d="${area}" fill="url(#${gid})" stroke="none"/>
    <path d="${line(ch.sma50)}" fill="none" stroke="var(--tx3)" stroke-width="1"
      stroke-dasharray="4 3" vector-effect="non-scaling-stroke"/>
    <path d="${line(ch.sma20)}" fill="none" stroke="var(--accent)" stroke-width="1.1"
      vector-effect="non-scaling-stroke"/>
    <path d="${line(c)}" fill="none" stroke="${col}" stroke-width="1.8"
      stroke-linejoin="round" vector-effect="non-scaling-stroke"/>
    <circle cx="${X(n - 1).toFixed(1)}" cy="${Y(last).toFixed(1)}" r="2.6" fill="${col}"/>
    <text x="0" y="${H - 5}" class="ax">${ymd(ch.t0)}</text>
    <text x="${plotW}" y="${H - 5}" class="ax" text-anchor="end">${ymd(ch.t1)}</text>
  </svg>
  <div class="legend"><span class="lg-c" style="background:${col}"></span>終値
    <span class="lg-c" style="background:var(--accent)"></span>20日線
    <span class="lg-c dash"></span>50日線
    <span class="muted" style="margin-left:auto">${n}営業日</span></div>`;
}

/* ---------- 補助指標（FX用） ---------- */
function macdChart(ic) {
  if (!ic || !ic.macd_hist) return '';
  const h = ic.macd_hist, m = ic.macd, sg = ic.macd_signal, n = h.length;
  const vals = h.concat(m, sg).filter(v => v != null);
  if (vals.length < 2) return '';
  const H = 62, W = 320, PAD_R = 46, PAD_T = 6, PAD_B = 12;
  const plotW = W - PAD_R, plotH = H - PAD_T - PAD_B;
  const mx = Math.max(...vals.map(Math.abs)) || 1;
  const X = i => (i / (n - 1)) * plotW;
  const Y = v => PAD_T + plotH / 2 - (v / mx) * (plotH / 2);
  const zero = Y(0), bw = Math.max(0.8, plotW / n * 0.62);
  let bars = '';
  for (let i = 0; i < n; i++) {
    const v = h[i];
    if (v == null) continue;
    const y = Y(v), top = Math.min(y, zero), hh = Math.abs(y - zero) || 0.5;
    bars += `<rect x="${(X(i) - bw / 2).toFixed(1)}" y="${top.toFixed(1)}"
      width="${bw.toFixed(1)}" height="${hh.toFixed(1)}"
      fill="${v >= 0 ? 'var(--up)' : 'var(--down)'}" opacity="0.55"/>`;
  }
  const line = arr => {
    let d = '', pen = false;
    for (let i = 0; i < n; i++) {
      if (arr[i] == null) { pen = false; continue; }
      d += (pen ? 'L' : 'M') + X(i).toFixed(1) + ' ' + Y(arr[i]).toFixed(1) + ' ';
      pen = true;
    }
    return d.trim();
  };
  const last = h[n - 1];
  return `<div class="sub-lbl">MACD <span class="muted">(12,26,9)</span>
      <span class="${last >= 0 ? 'up' : 'down'} num" style="margin-left:auto">
        ヒストグラム ${last == null ? '—' : (last >= 0 ? '+' : '') + last.toFixed(4)}</span></div>
    <svg class="chart sub" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img">
      <line x1="0" y1="${zero.toFixed(1)}" x2="${plotW}" y2="${zero.toFixed(1)}"
        stroke="var(--line)" stroke-width="0.8"/>
      ${bars}
      <path d="${line(sg)}" fill="none" stroke="var(--warn)" stroke-width="1"
        vector-effect="non-scaling-stroke"/>
      <path d="${line(m)}" fill="none" stroke="var(--accent)" stroke-width="1.2"
        vector-effect="non-scaling-stroke"/>
      <text x="${plotW + 5}" y="${(zero + 3.5).toFixed(1)}" class="ax">0</text>
    </svg>`;
}

function rsiChart(ic) {
  if (!ic || !ic.rsi) return '';
  const r = ic.rsi, n = r.length;
  if (n < 2) return '';
  const H = 58, W = 320, PAD_R = 46, PAD_T = 6, PAD_B = 12;
  const plotW = W - PAD_R, plotH = H - PAD_T - PAD_B;
  const X = i => (i / (n - 1)) * plotW;
  const Y = v => PAD_T + plotH - (v / 100) * plotH;
  let d = '', pen = false;
  for (let i = 0; i < n; i++) {
    if (r[i] == null) { pen = false; continue; }
    d += (pen ? 'L' : 'M') + X(i).toFixed(1) + ' ' + Y(r[i]).toFixed(1) + ' ';
    pen = true;
  }
  const last = r[n - 1];
  const st = last >= 70 ? ['買われすぎ', 'down'] : last <= 30 ? ['売られすぎ', 'up'] : ['中立', ''];
  return `<div class="sub-lbl">RSI <span class="muted">(14)</span>
      <span class="${st[1]} num" style="margin-left:auto">${last == null ? '—' : last.toFixed(1)}
        <span class="muted">${st[0]}</span></span></div>
    <svg class="chart sub" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img">
      <line x1="0" y1="${Y(70).toFixed(1)}" x2="${plotW}" y2="${Y(70).toFixed(1)}"
        stroke="var(--down)" stroke-width="0.6" stroke-dasharray="3 3"/>
      <line x1="0" y1="${Y(30).toFixed(1)}" x2="${plotW}" y2="${Y(30).toFixed(1)}"
        stroke="var(--up)" stroke-width="0.6" stroke-dasharray="3 3"/>
      <path d="${d.trim()}" fill="none" stroke="var(--tx)" stroke-width="1.3"
        vector-effect="non-scaling-stroke"/>
      <text x="${plotW + 5}" y="${(Y(70) + 3.5).toFixed(1)}" class="ax">70</text>
      <text x="${plotW + 5}" y="${(Y(30) + 3.5).toFixed(1)}" class="ax">30</text>
    </svg>`;
}

function confirmBlock(c, tradeable) {
  if (!c) return '';
  const k = c.level === 2 ? 'ok' : c.level === 1 ? 'wa' : 'no';
  const items = (c.items || []).map(i =>
    `<li class="${i.ok ? 'yes' : 'no'}">${i.ok ? '✓' : '✕'} ${esc(i.text)}</li>`).join('');
  const hit = tradeable
    ? `<span class="muted num cf-hit">実測的中率 ${(c.hit_rate * 100).toFixed(1)}%</span>`
    : '<span class="muted num cf-hit">見送りのため実測値の対象外</span>';
  return `<div class="confirm"><div class="confirm-head">
      <span class="pill ${k}">裏付け ${esc(c.label)}</span>
      <span class="muted">${c.agree}/${c.total} 一致</span>${hit}
    </div><ul class="checks">${items}</ul></div>`;
}


/* ---------- TradingView のチャート ----------
   公式の埋め込みウィジェット（無料）。描画ツールや多数の指標が使えるので、
   自前のチャートで足りないときの詳細確認に使う。

   注意: ウィジェットは表示専用で、そこから数値を読み取ることはできない。
   予測やスコアには一切関与しない（このアプリの計算は自前のデータで完結している）。
   外部読み込みなので、開いたときだけ読み込む。 */
function tvSymbol(x) {
  const code = String(x.code || x.key || '');
  switch (x.kind) {
    case 'us_stock': case 'us_etf': return code;                 // 取引所は自動判別に任せる
    case 'jp_stock': case 'jp_etf': case 'jp_reit': return 'TSE:' + code;
    case 'crypto': return 'BINANCE:' + code;
    case 'fx': return 'FX_IDC:' + code.replace('=X', '');
    case 'metal': {
      const m = { 'GC=F': 'TVC:GOLD', 'SI=F': 'TVC:SILVER', 'PL=F': 'TVC:PLATINUM' };
      return m[code] || code;
    }
    default: return code;
  }
}

/* 日本株はTradingViewの無料ウィジェットでは表示できない（取引所データの制限）。
   埋め込みの代わりにサイトへのリンクを出す。 */
const TV_EMBEDDABLE = { us_stock: 1, us_etf: 1, crypto: 1, fx: 1, metal: 1 };

function tvBlock(x) {
  const sym = tvSymbol(x);
  if (!sym) return '';
  if (!TV_EMBEDDABLE[x.kind]) {
    return `<p class="tv-link"><a href="https://www.tradingview.com/chart/?symbol=${encodeURIComponent(sym)}"
      target="_blank" rel="noopener noreferrer">TradingViewで詳細チャートを開く</a>
      <span class="muted">日本株はアプリ内に埋め込めないため、別画面で開きます</span></p>`;
  }
  const id = 'tv' + Math.random().toString(36).slice(2, 9);
  return `<details class="detail tv" data-sym="${esc(sym)}" data-box="${id}">
    <summary>TradingViewの詳細チャートを開く</summary>
    <div id="${id}" class="tv-box"><p class="muted">読み込み中…</p></div>
    <p class="muted" style="margin:6px 0 0">TradingView提供の表示用チャートです。
      このアプリの予測やスコアには使っていません。</p>
  </details>`;
}

/* 開かれたときに初めてウィジェットを差し込む */
function bindTradingView() {
  document.querySelectorAll('details.tv').forEach(d => {
    if (d.dataset.ready) return;
    d.addEventListener('toggle', () => {
      if (!d.open || d.dataset.ready) return;
      d.dataset.ready = '1';
      const box = document.getElementById(d.dataset.box);
      if (!box) return;
      box.innerHTML = '';
      const dark = true;
      const holder = document.createElement('div');
      holder.className = 'tradingview-widget-container';
      const inner = document.createElement('div');
      inner.className = 'tradingview-widget-container__widget';
      holder.appendChild(inner);
      box.appendChild(holder);
      const sc = document.createElement('script');
      sc.type = 'text/javascript';
      sc.async = true;
      sc.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
      sc.innerHTML = JSON.stringify({
        autosize: false, width: '100%', height: 420,
        symbol: d.dataset.sym, interval: 'D', timezone: 'Asia/Tokyo',
        theme: dark ? 'dark' : 'light', style: '1', locale: 'ja',
        hide_side_toolbar: false, allow_symbol_change: false,
        studies: ['MASimple@tv-basicstudies', 'RSI@tv-basicstudies'],
        support_host: 'https://www.tradingview.com',
      });
      holder.appendChild(sc);
    });
  });
}


/* ---------- タイミング表示 ----------
   曜日と経済指標による絞り込みは、いったん採用したが取り下げた。
   前半・後半に割る検査は通ったのに、検証期間を前後にずらすと効果が
   消えたため（56.2/57.8/54.6% 対 基準55.6/55.5/54.4%）。
   いまは的中率の主張を伴わず、「明日この通貨の指標がある」という
   事実だけを表示している。 */
function timingBlock(t) {
  if (!t) return '';
  const ev = (t.events || []).length
    ? `<ul class="checks" style="grid-template-columns:1fr">${t.events.map(e =>
      `<li class="yes">・${esc(e)}</li>`).join('')}</ul>`
    : '';
  return `<div class="confirm"><div class="confirm-head">
      <span class="pill">${esc(t.weekday)}曜 · ${esc(t.date || '')}</span>
      <span class="muted">${t.has_event ? esc((t.currencies || []).join('/')) + 'の指標あり' : '重要指標なし'}</span>
    </div>
    <p class="muted" style="margin:7px 0 0;font-size:11.5px">${esc(t.note || '')}</p>
    ${ev}</div>`;
}

/* ---------- 的中率バッジ（基準線と比べて色分け） ---------- */
function hitBadge(hr, n, gain, base) {
  if (hr == null) return '<span class="pill">的中率 データ不足</span>';
  const b = base == null ? 0.5 : base;
  const d = hr - b;
  const k = d >= 0.03 ? 'ok' : d <= -0.03 ? 'no' : 'wa';
  const tail = n == null ? `基準 ${(b * 100).toFixed(0)}%`
    : `基準 ${(b * 100).toFixed(0)}% · ${n}件${gain == null ? '' : ' ' + pct(gain, 2)}`;
  return `<span class="pill ${k}">的中率 ${(hr * 100).toFixed(0)}%</span>
    <span class="muted">${tail}</span>`;
}

function rangeBar(lo, mid, hi) {
  if (lo == null || hi == null || hi <= lo) return '';
  const p = Math.max(0, Math.min(100, (mid - lo) / (hi - lo) * 100));
  return `<div class="range">
    <div class="range-bar"><div class="range-fill"></div>
      <div class="range-mark" style="left:${p.toFixed(1)}%"></div></div>
    <div class="range-lbl"><span>${pct(lo, 1)}</span>
      <span>予測 ${pct(mid)}</span><span>${pct(hi, 1)}</span></div></div>`;
}

/* ---------- 銘柄カードの詳細（折りたたみ） ---------- */
function detailBlock(x) {
  const s = settings();
  const c = x.cost || {};
  const r = x.risk || {};

  const hz = (x.horizons || []).concat([{
    days: DATA.horizon_long, label: DATA.horizon_long_label || '1か月',
    expected_return: x.expected_return, expected_net: x.expected_net, prob_up: x.prob_up
  }]).sort((a, b) => a.days - b.days);
  const hzRows = hz.map(h => `<tr><td>${esc(h.label)}</td>
    <td class="num ${cls(h.expected_return)}">${pct(h.expected_return)}</td>
    <td class="num ${cls(h.expected_net)}">${pct(h.expected_net)}</td>
    <td class="num">${(h.prob_up * 100).toFixed(0)}%</td></tr>`).join('');

  const costRows = c.tradable ? `
    <tr><td>スプレッド（片道）</td><td class="num">${pct(c.spread, 2)}</td></tr>
    ${c.fx ? `<tr><td>為替手数料（片道）</td><td class="num">${pct(c.fx, 3)}</td></tr>` : ''}
    <tr><td><strong>往復コスト</strong></td><td class="num warn"><strong>${pct(c.round_trip, 2)}</strong></td></tr>
    <tr><td>コストを取り返すのに必要な保有期間</td><td class="num">${x.hold_months == null ? '—' : num(x.hold_months, 1) + 'か月'}</td></tr>`
    : `<tr><td colspan="2" class="muted">${esc(c.note || '')}</td></tr>`;

  const fxRow = x.fx_effect == null ? '' : `
    <div class="dsec"><h4>為替の影響</h4><table class="tbl">
      <tr><td>現地通貨での予測</td><td class="num ${cls(x.expected_return)}">${pct(x.expected_return)}</td></tr>
      <tr><td>ドル円の1か月予測</td><td class="num ${cls(x.fx_effect)}">${pct(x.fx_effect)}</td></tr>
      <tr><td><strong>円建ての予測</strong></td><td class="num ${cls(x.expected_return_jpy)}"><strong>${pct(x.expected_return_jpy)}</strong></td></tr>
      <tr><td>円建て・コスト後</td><td class="num ${cls(x.expected_net_jpy)}">${pct(x.expected_net_jpy)}</td></tr>
    </table></div>`;

  const sizeRow = (x.stop == null) ? '' : `
    <div class="dsec"><h4>損切りとポジションサイズ</h4><table class="tbl">
      <tr><td>損切り価格（ATR×${(DATA.stock_defaults || {}).stop_atr || 2}）</td>
        <td class="num down">${price(x.stop, x.currency)} <span class="muted">${pct(-x.stop_pct, 1)}</span></td></tr>
      <tr><td>許容損失（資金${yen(s.stockCapital)}の${(s.stockRisk * 100).toFixed(1)}%）</td>
        <td class="num">${yen(s.stockCapital * s.stockRisk)}</td></tr>
      <tr><td>投資してよい金額</td><td class="num">${yen(s.stockCapital * s.stockRisk / x.stop_pct)}</td></tr>
      <tr><td>資金に対する比率</td><td class="num">${((s.stockRisk / x.stop_pct) * 100).toFixed(1)}%</td></tr>
    </table><p class="muted" style="margin:6px 0 0">損切りに達したときの損失が
      許容額に収まるサイズです。資金の設定はFXタブで変更できます。</p></div>`;

  return `<details class="detail"><summary>詳細を見る</summary>
    <div class="dsec"><h4>期間別の予測</h4><table class="tbl">
      <tr><th>期間</th><th>予測</th><th>コスト後</th><th>上昇確率</th></tr>${hzRows}
    </table><p class="muted" style="margin:6px 0 0">短期と長期で向きが食い違う場合は、
      どちらか一方の見立てに偏っている可能性があります。</p></div>
    <div class="dsec"><h4>売買コスト</h4><table class="tbl">${costRows}</table>
      <p class="muted" style="margin:6px 0 0">${esc(c.note || '')}</p></div>
    ${fxRow}
    <div class="dsec"><h4>下方リスク</h4><table class="tbl">
      <tr><td>過去1年の最大下落</td><td class="num down">${pct(r.max_drawdown_1y, 1)}</td></tr>
      <tr><td>過去3年の最大下落</td><td class="num down">${pct(r.max_drawdown_3y, 1)}</td></tr>
      <tr><td>同じ期間を保有した最悪値</td><td class="num down">${pct(r.worst_hold, 1)}</td></tr>
      <tr><td>下位5%の想定</td><td class="num down">${pct(r.var5, 1)}</td></tr>
      <tr><td>下方ボラティリティ（年率）</td><td class="num">${r.downside_dev == null ? '—' : (r.downside_dev * 100).toFixed(1) + '%'}</td></tr>
    </table></div>
    ${sizeRow}
    <div class="dsec"><h4>参照した過去局面</h4>
      <p class="muted">${(x.samples || 0).toLocaleString('ja-JP')}件
        （期間の重複を補正すると ${num(x.n_eff, 1)}件相当）</p></div>
  </details>`;
}

/* ---------- 銘柄カード ---------- */
function itemCard(x, showRank, chartH) {
  const rank = showRank && x.rank ? `<div class="rank">${x.rank}</div>` : '';
  const reasons = (x.reasons || []).map(r => `<li>${esc(r)}</li>`).join('');
  const warns = (x.warnings || []).map(w => `<li>${esc(w)}</li>`).join('');
  const net = x.expected_net_jpy != null ? x.expected_net_jpy : x.expected_net;
  const tags = [];
  if (x.earnings_in_horizon) tags.push(`<span class="pill wa">決算 ${esc(x.earnings_date)}</span>`);
  else if (x.earnings_date) tags.push(`<span class="pill">決算 ${esc(x.earnings_date)}</span>`);
  if (x.dividend_yield) tags.push(`<span class="pill">配当 ${(x.dividend_yield * 100).toFixed(1)}%</span>`);

  return `<article class="item">
    <div class="item-head">${rank}
      <div class="item-title">
        <span class="nm">${esc(x.name)}${x.required ? ' <span class="pill ok">指定</span>' : ''}</span>
        <span class="sub">${esc(x.code)} · ${esc(x.kind_label)}${x.note ? ' · ' + esc(x.note) : ''}</span>
      </div>
      <div class="item-fig">
        <div class="pct ${cls(net)}">${pct(net)}</div>
        <div class="pr">コスト後 · ${price(x.price, x.currency)}</div>
      </div>
    </div>
    <div class="gross-row">
      <span>コスト前 <span class="${cls(x.expected_return)}">${pct(x.expected_return)}</span></span>
      ${x.fx_effect != null ? `<span>為替 <span class="${cls(x.fx_effect)}">${pct(x.fx_effect)}</span></span>` : ''}
      <span>往復コスト ${x.breakeven == null ? '—' : pct(x.breakeven, 2)}</span>
    </div>
    ${warns ? `<ul class="warns">${warns}</ul>` : ''}
    <div class="badges">${hitBadge(x.hit_rate, x.hit_n, x.hit_gain, BASE_LONG)}${tags.join('')}</div>
    ${chartSVG(x.chart, chartH)}
    ${rangeBar(x.low, x.expected_return, x.high)}
    <div class="metrics">
      <div class="metric"><span class="k">上昇確率</span><span class="v">${(x.prob_up * 100).toFixed(0)}%</span></div>
      <div class="metric"><span class="k">RSI</span><span class="v">${x.rsi ?? '—'}</span></div>
      <div class="metric"><span class="k">ADX</span><span class="v">${x.adx ?? '—'}</span></div>
      <div class="metric"><span class="k">年率ボラ</span><span class="v">${x.annual_vol ? (x.annual_vol * 100).toFixed(0) + '%' : '—'}</span></div>
    </div>
    ${reasons ? `<ul class="reasons">${reasons}</ul>` : ''}
    ${detailBlock(x)}
    ${tvBlock(x)}
  </article>`;
}

/* ---------- FXの資金計画（engine/fx.py の plan() と同じ計算） ---------- */
function computePlan(base, s) {
  const stopPct = base.avg_stop_pct || 0.005;
  const spread = 0.00004;
  const edge = (base.measured && base.measured.edge_per_trade) || 0.00121;
  const p = base.hit_rate || 0.586;
  const b = base.risk_reward || 1.5;
  const netEdge = edge - spread * 2;
  const notional = (s.capital * s.risk) / stopPct;
  const leverage = s.capital ? notional / s.capital : 0;
  const capped = Math.min(notional, s.capital * MAX_LEVERAGE);
  const dailyNet = capped * netEdge * s.trades;
  const needNotional = (netEdge > 0 && s.trades > 0) ? s.target / (netEdge * s.trades) : Infinity;
  const streak = 10;
  return Object.assign({}, base, {
    capital: s.capital, target: s.target, risk_per_trade: s.risk, trades_per_day: s.trades,
    notional_per_trade: capped, leverage: Math.min(leverage, MAX_LEVERAGE),
    leverage_required: leverage, leverage_ok: leverage <= MAX_LEVERAGE,
    expected_daily_net: dailyNet, expected_monthly_net: dailyNet * 20,
    required_capital: isFinite(needNotional) ? needNotional * stopPct / s.risk : Infinity,
    achievable_ratio: s.target ? dailyNet / s.target : 0,
    target_daily_pct: s.capital ? s.target / s.capital : Infinity,
    edge_per_trade: edge, no_edge_daily: capped * (-spread * 2) * s.trades,
    streak_n: streak, streak_prob: Math.pow(1 - p, streak),
    streak_loss_pct: 1 - Math.pow(1 - s.risk, streak),
    streak_loss: s.capital * (1 - Math.pow(1 - s.risk, streak)),
    daily_sd: Math.sqrt(s.trades) * (s.capital * s.risk) * Math.sqrt(p * b * b + (1 - p)),
    expected_value_r: p * b - (1 - p), hit_rate: p, risk_reward: b,
  });
}

function planLines(p) {
  const L = [];
  if (p.target_daily_pct > 0.05) {
    L.push('資金' + yen(p.capital) + 'に対して1日' + yen(p.target) + 'は日利'
      + (p.target_daily_pct * 100).toFixed(0) + '%です。検証で確認できた優位性（1回あたり'
      + (p.edge_per_trade * 100).toFixed(3) + '%）では届きません。');
  }
  L.push('今の設定（1回のリスク' + (p.risk_per_trade * 100).toFixed(1) + '%・1日'
    + p.trades_per_day + '回）で見込める利益は1日およそ' + yen(p.expected_daily_net)
    + '、月' + yen(p.expected_monthly_net) + 'です。');
  if (isFinite(p.required_capital)) {
    L.push('1日' + yen(p.target) + 'を同じリスク設定で狙うには、資金がおよそ'
      + yen(p.required_capital) + '必要です。');
  }
  if (!p.leverage_ok) {
    L.push('この設定は' + p.leverage_required.toFixed(1)
      + '倍のレバレッジが必要で、国内FXの上限25倍を超えます。1回のリスクを下げてください。');
  }
  L.push('1回の期待値は' + (p.expected_value_r >= 0 ? '+' : '') + p.expected_value_r.toFixed(2)
    + 'R（勝率' + (p.hit_rate * 100).toFixed(1) + '%・損益比' + p.risk_reward.toFixed(2) + '）です。');
  L.push('優位性が続かず勝率が五分に戻った場合は、スプレッド分だけ1日およそ'
    + yen(Math.abs(p.no_edge_daily)) + 'のマイナスになります。');
  L.push(p.streak_n + '連敗する確率は' + (p.streak_prob * 100).toFixed(2) + '%で、そのとき資金は'
    + (p.streak_loss_pct * 100).toFixed(0) + '%（' + yen(p.streak_loss) + '）減ります。'
    + '1日の損益のばらつきは±' + yen(p.daily_sd) + '程度です。');
  const m = p.measured || {};
  if (m.signal_days) {
    L.push('条件を満たすシグナルは毎日出るわけではありません。検証' + m.test_days + '日のうち出たのは'
      + m.signal_days + '日（' + (m.signal_days / m.test_days * 100).toFixed(0) + '%）、'
      + '出た日の平均は' + m.signals_per_active_day.toFixed(1) + '回でした。');
  }
  return L;
}


/* ---------- 動作状況 ----------
   数字が並んでいても、それが今日のものか止まっているのか分からない。
   最終更新からの経過と次の更新予定、実行履歴を出して、生きていることを示す。 */
function hoursAgo(iso) {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (!isFinite(t)) return null;
  return (Date.now() - t) / 3600000;
}

function nextUpdateLabel(hours) {
  // 実行時刻は配信データから受け取る（既定は日本時間の偶数時＝2時間ごと）
  const slots = (hours && hours.length) ? hours.slice().sort((a, b) => a - b)
    : [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22];
  const now = new Date();
  const jst = new Date(now.getTime() + (now.getTimezoneOffset() + 540) * 60000);
  const cur = jst.getHours() + jst.getMinutes() / 60;
  let h = slots.find(x => x > cur);
  let day = '今日';
  if (h === undefined) { h = slots[0]; day = '明日'; }
  const diff = ((h - cur) + 24) % 24;
  return { label: day + ' ' + String(h).padStart(2, '0') + ':00', inHours: diff };
}

function statusCard(d) {
  const ago = hoursAgo(d.generated_at);
  const nx = nextUpdateLabel(d.update_hours);
  const fresh = ago == null ? null : ago < 5;    // 2時間ごとなので5時間を超えたら異常
  const runs = d.runs || [];
  const runRows = runs.slice(0, 6).map(r => {
    const t = new Date(r.ts * 1000);
    const jst = new Date(t.getTime() + (t.getTimezoneOffset() + 540) * 60000);
    const md = (jst.getMonth() + 1) + '/' + jst.getDate() + ' '
      + String(jst.getHours()).padStart(2, '0') + ':' + String(jst.getMinutes()).padStart(2, '0');
    return `<div class="row mini"><span class="muted">${md}</span>
      <span class="muted num">記録 ${r.added || 0}件 / 採点 ${r.scored || 0}件 / 累計 ${r.total || 0}件</span></div>`;
  }).join('');

  return `<div class="card"><h2>動作状況</h2>
    <div class="row"><span class="muted">最終更新</span>
      <span class="num"><span class="pill ${fresh === null ? '' : fresh ? 'ok' : 'no'}">${
    ago == null ? '不明' : ago < 1 ? Math.round(ago * 60) + '分前' : ago.toFixed(1) + '時間前'}</span></span></div>
    <div class="row"><span class="muted">更新の間隔</span><span class="num">2時間ごと</span></div>
    <div class="row"><span class="muted">次の更新</span>
      <span class="num">${esc(nx.label)} <span class="muted">（あと${nx.inHours.toFixed(1)}時間）</span></span></div>
    <div class="row"><span class="muted">分析した銘柄</span><span class="num">${(d.universe_size || 0).toLocaleString('ja-JP')} 件</span></div>
    <div class="row"><span class="muted">記録した予測</span><span class="num">${(d.accuracy && d.accuracy.total_logged || 0).toLocaleString('ja-JP')} 件</span></div>
    ${runRows ? `<div style="margin-top:10px"><div class="muted" style="font-size:11px;margin-bottom:4px">これまでの実行</div>${runRows}</div>` : ''}
    <p class="muted" style="margin-top:9px">2時間ごとに更新されます。
      「最終更新」が5時間以上前のままなら自動更新が止まっています。
      GitHubのActionsタブから再開できます。</p></div>`;
}

/* 進行中の予測の途中経過。採点を待たずに動きが見えるようにする。 */
function progressCard(d) {
  const p = d.progress;
  if (!p || !p.summary) return '';
  const g = p.summary;
  const rate = g.on_track_rate;
  const rows = (p.items || []).map(x => `<tr>
    <td>${esc(x.name)}<br><span class="muted">${esc(x.date)}時点 · 残り${x.days_left}日</span></td>
    <td class="num ${cls(x.pred)}">${pct(x.pred)}</td>
    <td class="num ${cls(x.so_far)}">${pct(x.so_far)}</td>
    <td class="num">${x.on_track == null ? '—' : (x.on_track ? '<span class="up">合</span>' : '<span class="down">逆</span>')}</td>
  </tr>`).join('');

  return `<div class="card"><h2>進行中の予測（途中経過）</h2>
    <div class="row"><span class="muted">採点待ちの予測</span><span class="num">${g.open} 件</span></div>
    <div class="row"><span class="muted">いま方向が合っているもの</span>
      <span class="num ${rate == null ? '' : rate >= 0.5 ? 'up' : 'down'}">
        ${g.on_track} / ${g.judged}${rate == null ? '' : '（' + (rate * 100).toFixed(0) + '%）'}</span></div>
    <div class="bar"><span style="width:${rate == null ? 0 : (rate * 100).toFixed(0)}%;
      background:${rate == null ? 'var(--tx3)' : rate >= 0.5 ? 'var(--up)' : 'var(--down)'}"></span></div>
    <div class="row"><span class="muted">予測の平均 / 現時点の平均</span>
      <span class="num"><span class="${cls(g.mean_pred)}">${pct(g.mean_pred)}</span>
        / <span class="${cls(g.mean_so_far)}">${pct(g.mean_so_far)}</span></span></div>
    <div class="scroll-x" style="margin-top:10px"><table class="tbl">
      <tr><th>銘柄</th><th>予測</th><th>いま</th><th>方向</th></tr>${rows}
    </table></div>
    <p class="muted" style="margin-top:9px">期限が来ると自動で採点され、「このアプリの実績」に反映されます。
      途中経過なので、ここでの「合」がそのまま的中になるわけではありません。</p></div>`;
}

/* ---------- 今日 ---------- */
function viewHome(d) {
  const r = d.regime || {}, u = d.usdjpy || {};
  const regimeCard = `<div class="card"><h2>いまの市場環境</h2>
    <div class="row"><span class="big">${esc(r.label || '—')}</span></div>
    <div class="ctx" style="margin-top:10px">
      <div class="ctx-item"><div class="nm">VIX（恐怖指数）</div><div class="v">${num(r.vix, 2)}</div>
        <div class="c muted">${r.vix_level === 0 ? '低い' : r.vix_level === 2 ? '高い' : '普通'}</div></div>
      <div class="ctx-item"><div class="nm">50日線を上回る銘柄</div>
        <div class="v">${r.breadth50 == null ? '—' : (r.breadth50 * 100).toFixed(0) + '%'}</div>
        <div class="c muted">${r.breadth50_n || 0}銘柄中</div></div>
      <div class="ctx-item"><div class="nm">S&P500の位置</div>
        <div class="v">${r.spx_above_sma50 ? '50日線の上' : '50日線の下'}</div>
        <div class="c muted">${r.spx_above_sma200 ? '200日線も上' : '200日線は下'}</div></div>
      <div class="ctx-item"><div class="nm">ドル円（1か月予測）</div>
        <div class="v ${cls(u.expected_return)}">${pct(u.expected_return)}</div>
        <div class="c muted">${num(u.rate, 2)}</div></div>
    </div>
    <p class="muted" style="margin-top:9px">市場環境の判定は<b>FXの予測にだけ</b>使っています
      （株では逆効果でした）。ドル円の予測は、米ドル建て資産の円建て期待値に反映しています。</p></div>`;

  const ctx = (d.context || []).map(c => `
    <div class="ctx-item"><div class="nm">${esc(c.name)}</div>
      <div class="v">${num(c.price, c.price >= 1000 ? 0 : 2)}</div>
      <div class="c ${cls(c.change)}">${pct(c.change)} <span class="muted">/5日 ${pct(c.change5)}</span></div>
    </div>`).join('');

  const fg = d.fear_greed;
  const fgBlock = fg ? `<div class="card"><h2>暗号資産センチメント</h2>
    <div class="row"><span class="big ${fg.value < 40 ? 'down' : fg.value > 60 ? 'up' : ''}">${fg.value}</span>
      <span class="pill">${esc(fg.label)}</span></div>
    <div class="bar"><span style="width:${fg.value}%"></span></div>
    <p class="muted">0 = 極度の恐怖 / 100 = 極度の強欲</p></div>` : '';

  const line = x => {
    const net = x.expected_net_jpy != null ? x.expected_net_jpy : x.expected_net;
    return `<div class="row mini">
      <span>${x.rank ? `<strong>${x.rank}.</strong> ` : ''}${esc(x.name)}
        <span class="muted">${esc(x.kind_label)}</span>
        ${x.earnings_in_horizon ? '<span class="pill wa">決算</span>' : ''}</span>
      <span><span class="${cls(net)} num"><strong>${pct(net)}</strong></span>
        <span class="muted num"> 的中${x.hit_rate == null ? '—' : (x.hit_rate * 100).toFixed(0) + '%'}</span></span>
    </div>`;
  };

  const stH = settings();
  const fxAll = ((d.fx && d.fx.signals) || []).map(x => Object.assign({}, x, {
    tradeable: x.confidence >= stH.fxConf && !(x.rate && x.rate.veto),
  })).sort((a, b) => (b.expected_hit || 0) - (a.expected_hit || 0)
    || ((b.confirm && b.confirm.level) || 0) - ((a.confirm && a.confirm.level) || 0)
    || b.confidence - a.confidence);
  const fxTop = fxAll.map((s, i) => `
    <div class="row mini ${s.tradeable ? '' : 'dim'}">
      <span><strong>${i + 1}.</strong> ${esc(s.name)}
        <span class="pill ${s.tradeable ? (s.dir_sign > 0 ? 'ok' : 'no') : ''}">${esc(s.direction)}</span>
        ${s.tradeable ? '' : '<span class="muted">見送り</span>'}</span>
      <span class="muted num">確信度 ${(s.confidence * 100).toFixed(0)}%
        / 実測${s.conf_stats && s.conf_stats.conf ? (s.conf_stats.hit * 100).toFixed(1) + '%' : '—'}
        / 裏付け${s.confirm ? esc(s.confirm.label) : '—'}
        ${s.rate && (s.rate.state === 'tailwind' || s.rate.veto)
      ? `/ <span class="${s.rate.veto ? 'down' : 'up'}">${esc(s.rate.label)}</span>` : ''}</span>
    </div>`).join('');

  const dv = d.diversification;
  const dvBlock = dv ? `<div class="card"><h2>上位候補の分散</h2>
    <div class="row"><span class="muted">銘柄間の平均相関</span>
      <span class="num ${dv.mean < 0.4 ? 'up' : dv.mean < 0.6 ? 'warn' : 'down'}">${num(dv.mean, 2)}</span></div>
    <div class="row"><span class="muted">最大相関</span><span class="num">${num(dv.max, 2)}</span></div>
    <div class="row"><span class="muted">内訳</span><span class="muted">${
    (dv.composition || []).map(c => `${esc(c[0])}${c[1]}`).join(' / ')}</span></div>
    ${(dv.messages || []).map(m => `<p class="warn" style="font-size:12.5px;margin:8px 0 0">${esc(m)}</p>`).join('')}
    ${dv.ok ? '<p class="muted" style="margin-top:8px">値動きの重複は避けられています。1に近いほど「実質1銘柄」です。</p>' : ''}
    ${(dv.excluded || []).length ? `<p class="muted" style="margin-top:8px">重複のため見送った銘柄:
      ${dv.excluded.map(e => `${esc(e.name)}（${esc(e.similar_to)}と相関${e.corr}）`).join('、')}</p>` : ''}
  </div>` : '';

  return `
  ${statusCard(d)}
  ${(d.missing_required || []).length ? `<div class="banner warn">
    <strong>表示できていない銘柄があります</strong>
    ${d.missing_required.map(m => esc(m.name)).join('、')}のデータを取得できませんでした。
    一時的な取得失敗の可能性があります。次の更新で戻らない場合は不具合です。</div>` : ''}
  <div class="banner"><strong>この数字の読み方</strong>
    大きく出している％は<b>売買コストを引いたあと</b>の値です。
    株・貴金属・暗号資産は${esc(d.horizon_long_label || '')}先、FXは${esc(d.horizon_fx_label || '')}先の予測。
    的中率は基準線（何もせず買った場合の上昇率）と比べて見てください。
    <b>株の順位付けに統計的な優位性は確認できていません</b>。FXのみ有意です。</div>
  ${regimeCard}
  <div class="card"><h2>主要指標</h2><div class="ctx">${ctx}</div></div>
  ${fgBlock}
  <div class="card"><h2>指定銘柄（常時表示）</h2>${(d.pinned || []).map(line).join('') || '<p class="empty">データがありません</p>'}</div>
  <div class="card"><h2>本日の上位候補</h2>${(d.top5 || []).map(line).join('') || '<p class="empty">条件を満たす候補がありません</p>'}</div>
  ${dvBlock}
  <div class="card"><h2>FX 主要5ペア</h2>${fxTop || '<p class="empty">データがありません</p>'}
    <p class="muted" style="margin-top:8px">売買条件を満たしているのは
      ${fxAll.filter(x => x.tradeable).length} / ${fxAll.length} ペアです。</p></div>
  <div class="card"><h2>分析の規模</h2>
    <div class="row"><span class="muted">参照した過去局面</span><span class="num">${(d.pool_size || 0).toLocaleString('ja-JP')} 件</span></div>
    <div class="row"><span class="muted">決算日を把握している銘柄</span><span class="num">${(d.earnings_known || 0).toLocaleString('ja-JP')} 件</span></div>
    <div class="row"><span class="muted">的中率を算出済みの銘柄</span><span class="num">${(d.asset_accuracy_n || 0).toLocaleString('ja-JP')} 件</span></div>
    <div class="row"><span class="muted">更新予定</span><span class="muted">${esc(d.next_update)}</span></div>
  </div>`;
}

function viewTop5(d) {
  const items = (d.top5 || []).map(x => itemCard(x, true, 150)).join('');
  const dv = d.diversification;
  return `<div class="banner"><strong>選び方</strong>
    PayPay証券で買える銘柄のうち、流動性と値動きの荒さ（年率ボラ60%以下）の条件を満たすものから、
    トレンド・勢い・相対強度・過去の類似局面を合成して並べ、
    <b>値動きが重複する銘柄は除いています</b>。予測期間は${esc(d.horizon_long_label || '')}先。
    表示は売買コストを引いた値です。</div>
    ${dv && !dv.ok ? `<div class="banner"><strong>分散の注意</strong>${
    (dv.messages || []).map(esc).join(' ')}</div>` : ''}
    ${items || '<p class="empty">本日は条件を満たす候補がありませんでした</p>'}`;
}

function viewRank(d) {
  const groups = [];
  if ((d.pinned || []).length) groups.push({ label: '指定銘柄', items: d.pinned, pinned: true });
  (d.categories || []).forEach(c => groups.push(c));
  if (!groups.length) return '<p class="empty">データがありません</p>';
  CAT = Math.min(CAT, groups.length - 1);
  const g = groups[CAT];
  const chips = groups.map((c, i) =>
    `<button class="chip ${i === CAT ? 'on' : ''}" data-cat="${i}">${esc(c.label)}</button>`).join('');
  const items = g.items.length
    ? g.items.map(x => itemCard(x, !g.pinned, 130)).join('')
    : `<p class="empty">${esc(g.empty_note || 'この区分に表示できる銘柄がありません')}</p>`;
  const note = g.pinned
    ? `<div class="banner info"><strong>指定銘柄は常に表示します</strong>
        スコアや足切りの条件に関係なく、この5銘柄は毎回この順番で出します。</div>`
    : `<div class="banner"><strong>この区分はスコア順です</strong>
        その日のスコア順に並べています。ただし<b>「指定」の付いた銘柄は
        順位に関わらず必ず表示</b>します（暗号資産のBTC・ETH・XRP・SOL、
        貴金属の金・銀・プラチナ）。</div>`;
  return `${note}<div class="chips">${chips}</div>${items}`;
}

/* ---------- 保有ポジション ---------- */
function viewHold(d) {
  const s = settings();
  if (DIR === null) {
    loadDirectory();
    return '<div class="loading"><div class="spinner"></div><p>銘柄データを読み込んでいます…</p></div>';
  }
  const byCode = {};
  DIR.forEach(x => { byCode[String(x.c).toUpperCase()] = x; });

  const fxRate = (d.usdjpy && d.usdjpy.rate) || null;
  const toJpy = (v, curr) => (v == null ? null : (curr === 'JPY' ? v : (fxRate ? v * fxRate : null)));

  const rows = (s.holdings || []).map((h, i) => {
    const a = byCode[String(h.code || '').toUpperCase()];
    const curr = a ? a.u : null;
    const cur = a ? a.p : null;
    const pl = (cur != null && h.cost) ? (cur / h.cost - 1) : null;
    const value = (cur != null) ? cur * h.qty : null;
    const plAmt = (cur != null && h.cost) ? (cur - h.cost) * h.qty : null;
    return {
      i, h, a, curr, cur, pl, value, plAmt,
      valueJpy: toJpy(value, curr), plJpy: toJpy(plAmt, curr),
      costJpy: toJpy(h.cost * h.qty, curr),
      name: a ? a.n : (h.name || h.code),
    };
  });

  const sum = (list, k) => list.reduce((t, r) => t + (r[k] || 0), 0);
  const totalValue = sum(rows, 'valueJpy');
  const totalPl = sum(rows, 'plJpy');
  const totalCost = sum(rows, 'costJpy');

  const byCur = [['円建て', 'JPY'], ['ドル建て', 'USD']].map(pair => {
    const lbl = pair[0], cu = pair[1];
    const list = rows.filter(r => (r.curr === 'JPY') === (cu === 'JPY'));
    if (!list.length) return '';
    const v = sum(list, 'value'), p = sum(list, 'plAmt');
    const c = list.reduce((t, r) => t + (r.h.cost * r.h.qty || 0), 0);
    return '<div class="row"><span class="muted">' + lbl + '（' + list.length + '銘柄）</span>'
      + '<span class="num">' + price(v, cu)
      + ' <span class="' + cls(p) + '">' + (p >= 0 ? '+' : '−') + price(Math.abs(p), cu) + '</span>'
      + ' <span class="muted">' + (c ? pct(p / c) : '') + '</span></span></div>';
  }).join('');

  const totals = rows.length ? byCur
    + '<div class="row" style="border-top:1px solid var(--line);padding-top:8px;margin-top:6px">'
    + '<span><strong>合計（円換算）</strong></span>'
    + '<span class="num"><strong>' + yen(totalValue) + '</strong> '
    + '<span class="' + cls(totalPl) + '">' + (totalPl >= 0 ? '+' : '−') + yen(Math.abs(totalPl)) + '</span> '
    + '<span class="muted">' + (totalCost ? pct(totalPl / totalCost) : '') + '</span></span></div>'
    + (fxRate ? '<p class="muted" style="margin-top:6px">ドル円 ' + num(fxRate, 2) + ' で換算しています。</p>'
      : '<p class="warn" style="font-size:12.5px;margin-top:6px">ドル円のレートが取得できず、円換算できていません。</p>')
    : '<p class="muted">まだ登録がありません</p>';

  const list = rows.length ? rows.map(r => `
    <article class="item">
      <div class="item-head">
        <div class="item-title"><span class="nm">${esc(r.name)}</span>
          <span class="sub">${esc(r.h.code)}${r.a ? ' · ' + esc(r.a.l) : ' · 分析対象外'} ·
            ${num(r.h.qty, r.h.qty < 10 ? 4 : 0)}単位 · 取得 ${price(r.h.cost, r.curr)}</span></div>
        <div class="item-fig"><div class="pct ${cls(r.pl)}">${pct(r.pl)}</div>
          <div class="pr">${price(r.cur, r.curr)}</div></div>
      </div>
      <div class="metrics">
        <div class="metric"><span class="k">評価額</span><span class="v">${price(r.value, r.curr)}</span></div>
        <div class="metric"><span class="k">損益</span><span class="v ${cls(r.plAmt)}">${r.plAmt == null ? '—' : (r.plAmt >= 0 ? '+' : '−') + price(Math.abs(r.plAmt), r.curr)}</span></div>
        <div class="metric"><span class="k">構成比</span><span class="v">${totalValue && r.valueJpy != null ? ((r.valueJpy / totalValue) * 100).toFixed(0) + '%' : '—'}</span></div>
        <div class="metric"><span class="k">今の予測</span><span class="v ${cls(r.a && (r.a.j != null ? r.a.j : r.a.e))}">${r.a ? pct(r.a.j != null ? r.a.j : r.a.e) : '—'}</span></div>
      </div>
      ${r.a ? `<div class="badges">${hitBadge(r.a.h, null, null, BASE_LONG)}
        <span class="muted">上昇確率 ${(r.a.b * 100).toFixed(0)}%</span></div>` : ''}
      <button class="del" data-del="${r.i}">削除</button>
    </article>`).join('') : '<p class="empty">保有はまだ登録されていません</p>';

  // 候補は入力に応じて最大20件だけ描く（全件並べると端末が固まるため）
  const q = HOLD_Q.trim().toUpperCase();
  const hits = q ? DIR.filter(x =>
    String(x.c).toUpperCase().indexOf(q) >= 0 || x.n.toUpperCase().indexOf(q) >= 0).slice(0, 20) : [];
  const sugg = q ? (hits.length
    ? '<ul class="sugg">' + hits.map(x =>
      '<li data-code="' + esc(x.c) + '"><strong>' + esc(x.c) + '</strong> ' + esc(x.n)
      + '<span class="muted">' + esc(x.l) + ' · ' + price(x.p, x.u) + '</span></li>').join('') + '</ul>'
    : '<p class="muted" style="margin-top:8px">該当する銘柄がありません</p>') : '';

  let conc = '';
  if (totalValue && rows.length) {
    const mx = Math.max.apply(null, rows.map(r => (r.valueJpy || 0) / totalValue));
    if (mx >= 0.5) conc = '<p class="warn" style="font-size:12.5px;margin:8px 0 0">1銘柄が全体の'
      + (mx * 100).toFixed(0) + '%を占めています。1つの値動きに結果が左右されます。</p>';
    else if (rows.length < 3) conc = '<p class="muted" style="margin:8px 0 0">'
      + '銘柄数が少ないため分散は効いていません。</p>';
  }

  return `<div class="banner"><strong>保有ポジション</strong>
    取得単価と数量を入れると、損益・構成比・いまの予測を並べて見られます。
    入力内容は<b>この端末にだけ</b>保存され、どこにも送信されません。</div>
    <div class="card"><h2>保有を追加</h2>
      <label class="fld">銘柄を検索（コードまたは名前）
        <input id="h-code" placeholder="NVDA / トヨタ / 7203" autocomplete="off" value="${esc(HOLD_Q)}"></label>
      ${sugg}
      <div class="set-grid" style="margin-top:9px">
        <label>数量<input id="h-qty" type="number" inputmode="decimal" min="0" step="0.0001" placeholder="10"></label>
        <label>取得単価<input id="h-cost" type="number" inputmode="decimal" min="0" step="0.01" placeholder="180.5"></label>
      </div>
      <button id="h-add" class="add" style="margin-top:9px">選んだ銘柄を追加</button>
      <p class="muted" style="margin-top:8px">単価は現地通貨で入力してください（米国株はドル、日本株は円）。
      構成比と合計はドル円で円換算して比べています。「今の予測」は米国株なら為替の影響を含めた円建てです。</p>
      <p class="muted">${DIR.length.toLocaleString('ja-JP')} 銘柄から検索できます。</p>
    </div>
    <div class="card"><h2>合計</h2>${totals}${conc}</div>
    ${list}`;
}

/* ---------- FX ---------- */
function viewFx(d) {
  const base = d.fx && d.fx.plan;
  if (!base) return '<p class="empty">FXデータがありません</p>';
  const st = settings();
  const p = computePlan(base, st);
  const ratio = Math.max(0, Math.min(100, (p.achievable_ratio || 0) * 100));
  const lines = planLines(p).map(l => '<p style="margin:0 0 7px">' + esc(l) + '</p>').join('');
  const barCol = ratio < 30 ? 'var(--down)' : ratio < 80 ? 'var(--warn)' : 'var(--up)';
  const m = base.measured || {};
  const all = (d.fx.signals || []).map(x => Object.assign({}, x, {
    tradeable: x.confidence >= st.fxConf && !(x.rate && x.rate.veto),
    status: (x.rate && x.rate.veto) ? '見送り（金利が逆風）'
      : (x.confidence >= st.fxConf ? 'シグナルあり' : '見送り'),
  })).sort((a, b) => (b.expected_hit || 0) - (a.expected_hit || 0)
    || ((b.confirm && b.confirm.level) || 0) - ((a.confirm && a.confirm.level) || 0)
    || b.confidence - a.confidence);
  const nTrade = all.filter(x => x.tradeable).length;
  const lv = (d.fx_levels || []).slice().sort((a, b) =>
    Math.abs(a.conf - st.fxConf) - Math.abs(b.conf - st.fxConf))[0];

  const settingsCard = `<div class="card"><h2>資金設定</h2><div class="set-grid">
    <label>FX運用資金（円）<input id="s-cap" type="number" inputmode="numeric" min="1000" step="1000" value="${st.capital}"></label>
    <label>1日の目標（円）<input id="s-tgt" type="number" inputmode="numeric" min="100" step="100" value="${st.target}"></label>
    <label>1回のリスク（%）<input id="s-risk" type="number" inputmode="decimal" min="0.1" max="20" step="0.1" value="${(st.risk * 100).toFixed(1)}"></label>
    <label>1日の取引回数<input id="s-trd" type="number" inputmode="numeric" min="1" max="20" step="1" value="${st.trades}"></label>
    <label>株の運用資金（円）<input id="s-scap" type="number" inputmode="numeric" min="1000" step="10000" value="${st.stockCapital}"></label>
    <label>株の1銘柄リスク（%）<input id="s-srisk" type="number" inputmode="decimal" min="0.1" max="20" step="0.1" value="${(st.stockRisk * 100).toFixed(1)}"></label>
    <label>シグナルの確信度<select id="s-conf">${(d.fx_levels || []).map(l =>
      `<option value="${l.conf}"${Math.abs(l.conf - st.fxConf) < 0.005 ? ' selected' : ''}>${(l.conf * 100).toFixed(0)}%以上（勝率${(l.hit * 100).toFixed(1)}%・1日${l.per_day.toFixed(2)}回）</option>`).join('')}</select></label>
    </div><p class="muted" style="margin-top:8px">この端末に保存され、株のポジションサイズ計算にも使われます。</p></div>`;

  const plan = `<div class="card"><h2>資金計画</h2>
    <div class="row"><span class="muted">運用資金</span><span class="num">${yen(p.capital)}</span></div>
    <div class="row"><span class="muted">目標（1日）</span><span class="num">${yen(p.target)}</span></div>
    <div class="row"><span class="muted">見込み（1日）</span><span class="num ${p.expected_daily_net >= 0 ? 'up' : 'down'}">${yen(p.expected_daily_net)}</span></div>
    <div class="bar"><span style="width:${ratio}%;background:${barCol}"></span></div>
    <p class="muted">目標に対する達成度 ${ratio.toFixed(1)}%</p>
    <div style="margin-top:12px;font-size:13px">${lines}</div></div>
    <div class="card"><h2>目標達成に必要な条件</h2><table class="tbl">
    <tr><td>目標を達成できる資金</td><td class="num warn">${yen(p.required_capital)}</td></tr>
    <tr><td>1回あたりの想定元本</td><td class="num">${yen(p.notional_per_trade)}</td></tr>
    <tr><td>必要レバレッジ</td><td class="num">${num(p.leverage_required, 1)}倍 ${p.leverage_ok ? '' : '<span class="pill no">上限超過</span>'}</td></tr>
    <tr><td>1回の期待値</td><td class="num ${p.expected_value_r >= 0 ? 'up' : 'down'}">${num(p.expected_value_r, 2)}R</td></tr>
    <tr><td>想定勝率 / 損益比</td><td class="num">${(p.hit_rate * 100).toFixed(1)}% / ${num(p.risk_reward, 2)}</td></tr>
    <tr><td>1日の損益のばらつき</td><td class="num">±${yen(p.daily_sd)}</td></tr>
    <tr><td>${p.streak_n}連敗の確率 / 損失</td><td class="num">${(p.streak_prob * 100).toFixed(2)}% / −${yen(p.streak_loss)}</td></tr>
    </table></div>`;

  const risk = p.capital * p.risk_per_trade;
  const sigs = all.map(s => {
    const on = s.tradeable;
    const notional = s.stop_pct > 0 ? risk / s.stop_pct : 0;
    const lev = p.capital ? notional / p.capital : 0;
    return `<article class="item ${on ? '' : 'dim'}">
      <div class="fx-head">
        <div style="display:flex;gap:9px;align-items:flex-start;flex:1;min-width:0">
          ${s.order ? `<div class="rank" style="margin-top:3px">${s.order}</div>` : ''}
          <div style="min-width:0">
            <h3 style="margin:0">${esc(s.name)}
              <span class="pill ${on ? 'ok' : ''}">${esc(s.status || (on ? 'シグナルあり' : '見送り'))}</span></h3>
            <span class="muted">${num(s.price, 4)} · ATR ${(s.atr_pct * 100).toFixed(2)}% · 予測 ${pct(s.expected_move, 3)}</span>
          </div>
        </div>
        <span class="dir ${on ? (s.dir_sign > 0 ? 'buy' : 'sell') : 'off'}">${esc(s.direction)}</span>
      </div>
      <div class="badges">
        <span class="pill ${on ? 'ok' : 'wa'}">確信度 ${(s.confidence * 100).toFixed(0)}%</span>
        ${s.conf_stats && s.conf_stats.conf
      ? `<span class="pill ${s.conf_stats.hit >= 0.58 ? 'ok' : 'wa'}">この区分の実測 ${(s.conf_stats.hit * 100).toFixed(1)}%</span>`
      : '<span class="pill">実測区分に届かず</span>'}
        ${hitBadge(s.hit_rate, s.hit_n, s.hit_gain, BASE_FX)}
        ${s.rate && s.rate.state !== 'unknown'
      ? `<span class="pill ${s.rate.state === 'tailwind' ? 'ok' : s.rate.veto ? 'no' : ''}">${esc(s.rate.label)}${
        s.rate.hit != null ? ' ' + (s.rate.hit * 100).toFixed(1) + '%' : ''}</span>` : ''}
      </div>
      ${s.rate && s.rate.note ? `<p class="muted" style="margin:8px 0 0">${esc(s.rate.note)}${
        s.rate.veto ? ` 期間3通りで${s.rate.windows.map(w => (w * 100).toFixed(1)).join('/')}%、
        条件作りに使っていない8ペアでも36%前後です。見送りを推奨します。` : ''}${
        s.rate.state === 'tailwind' && s.rate.hit != null
          ? ` 実測${(s.rate.hit * 100).toFixed(1)}%。` : ''}</p>` : ''}
      ${chartSVG(s.chart, 140)}
      ${macdChart(s.ind_chart)}
      ${rsiChart(s.ind_chart)}
      ${confirmBlock(s.confirm, on)}
      ${timingBlock(s.timing)}
      <div class="levels">
        <div class="level"><span class="k">エントリー</span><span class="v">${num(s.entry, 4)}</span></div>
        <div class="level"><span class="k">損切り</span><span class="v down">${num(s.stop, 4)}</span></div>
        <div class="level"><span class="k">利確</span><span class="v up">${num(s.target, 4)}</span></div>
      </div>
      <div class="metrics">
        <div class="metric"><span class="k">R:R</span><span class="v">${num(s.risk_reward, 2)}</span></div>
        <div class="metric"><span class="k">必要レバ</span><span class="v ${lev > MAX_LEVERAGE ? 'down' : ''}">${num(lev, 1)}倍</span></div>
        <div class="metric"><span class="k">損失上限</span><span class="v">${yen(risk)}</span></div>
        <div class="metric"><span class="k">利確なら</span><span class="v up">${yen(risk * s.risk_reward)}</span></div>
      </div>
      <div class="metrics">
        <div class="metric"><span class="k">ADX</span><span class="v">${num(s.adx, 1)}</span></div>
        <div class="metric"><span class="k">ボリンジャー</span><span class="v">${s.bb_pctb == null ? '—' : (s.bb_pctb * 100).toFixed(0) + '%'}</span></div>
        <div class="metric"><span class="k">スプレッド</span><span class="v">${(s.spread_pct * 100).toFixed(4)}%</span></div>
        <div class="metric"><span class="k">コスト後</span><span class="v ${cls(s.expected_net)}">${pct(s.expected_net, 3)}</span></div>
      </div>
      <p class="muted" style="margin:9px 0 0">想定元本 ${yen(notional)}／必要証拠金 ${yen(notional / MAX_LEVERAGE)}</p>
      ${tvBlock({ code: s.key, kind: 'fx' })}
    </article>`;
  }).join('');

  return `<div class="banner info"><strong>FXは検証で優位性が確認できた唯一の枠です</strong>
    分析は${d.fx_pool_pairs || 14}ペアで行い、主要${d.fx_signal_pairs || 5}ペアを毎日表示します。
    いま選んでいる確信度${(st.fxConf * 100).toFixed(0)}%以上での実測は
    <b>勝率${((lv ? lv.hit : 0.58) * 100).toFixed(1)}%・1回あたり${pct(lv ? lv.mean : 0.00096, 3)}</b>
    （1日${(lv ? lv.per_day : 0.83).toFixed(2)}回・t値${(lv ? lv.t : 2.37).toFixed(2)}）。
    それ未満のペアは参考表示です。スプレッドは未計上です。</div>
    ${settingsCard}${plan}
    <div class="card"><h2>主要5ペア（${esc(d.horizon_fx_label || '')}先）</h2>
      <div class="row"><span class="muted">売買条件を満たしているペア</span>
        <span class="num"><strong class="${nTrade ? 'up' : ''}">${nTrade}</strong> / ${all.length}</span></div>
      ${d.econ ? `<div class="row"><span class="muted">${esc(d.econ.next_date)}の重要指標</span>
        <span class="num">${d.econ.next.high_count} 件
          <span class="muted">${esc((d.econ.next.currencies || []).join(' '))}</span></span></div>` : ''}
      ${d.fx_rate_after_veto ? `<div class="row"><span class="muted">金利の逆風を除いた実測的中率</span>
        <span class="num up">${(d.fx_rate_after_veto.hit * 100).toFixed(1)}%
          <span class="muted">除く前 ${(d.fx_rate_after_veto.before * 100).toFixed(1)}%</span></span></div>` : ''}
      ${d.us_yield ? `<div class="row"><span class="muted">米10年国債利回り</span>
        <span class="num">${num(d.us_yield.value, 2)}%
          <span class="${d.us_yield.chg20 >= 0 ? 'up' : 'down'}">20日で${d.us_yield.chg20 >= 0 ? '+' : ''}${num(d.us_yield.chg20, 2)}%</span></span></div>` : ''}
      <p class="muted" style="margin:8px 0 0">5ペアは毎日すべて表示し、
        <b>的中確率の高い順 → 裏付けの強い順</b>で並べています。
        確信度の下限は資金設定で変更できます。</p>
      <p class="muted" style="margin:6px 0 0">なお「14ペアから的中確率上位5つを毎日選び直す」方式も
        実測しましたが、勝率が58.0%→56.4%（検証期間3通りすべて）と下がったため採用していません。
        主要5ペア自体の成績が良く、入れ替えると質の劣るペアが混ざるためです。</p>
      ${(d.fx_levels || []).length ? `<div class="scroll-x" style="margin-top:10px"><table class="tbl">
        <tr><th>確信度</th><th>勝率</th><th>1日</th><th>1回あたり</th><th>期間をずらすと</th></tr>
        ${d.fx_levels.map(l => `<tr>
          <td>${(l.conf * 100).toFixed(0)}%以上${Math.abs(l.conf - st.fxConf) < 0.005 ? ' <span class="pill ok">選択中</span>' : ''}</td>
          <td class="num ${l.hit >= 0.58 ? 'up' : ''}">${(l.hit * 100).toFixed(1)}%</td>
          <td class="num">${l.per_day.toFixed(2)}回</td>
          <td class="num">${pct(l.mean, 3)}</td>
          <td class="num muted">${l.windows.map(w => (w * 100).toFixed(1)).join(' / ')}%</td></tr>`).join('')}
      </table></div>
      <p class="muted" style="margin-top:8px">確信度を上げるほど勝率は上がりますが、機会は減ります。
        「期間をずらすと」は検証期間を400／360／440時点に変えたときの勝率で、
        どの期間でも順位が変わらないことを確認しています。
        ただし60%は前半53.2%／後半72.3%と偏りがあり、62.8%という数字自体の確からしさは
        56%（前半54.2%／後半61.4%）より低い点に注意してください。</p>` : ''}</div>
    ${sigs || '<p class="empty">FXデータを取得できませんでした</p>'}`;
}

/* ---------- 的中率 ---------- */
function viewAcc(d) {
  const a = d.accuracy || {}, v = VALID;
  const stat = (s, label) => {
    if (!s) return `<tr><td>${label}</td><td colspan="3" class="muted">まだ実績なし</td></tr>`;
    return `<tr><td>${label}</td><td class="num">${s.n}</td>
      <td class="num ${s.hit_rate >= 0.5 ? 'up' : 'down'}">${(s.hit_rate * 100).toFixed(1)}%</td>
      <td class="num ${cls(s.mean_gain)}">${pct(s.mean_gain)}</td></tr>`;
  };

  const live = `<div class="card"><h2>このアプリの実績（配信した予測の採点）</h2>
    <table class="tbl">
      <tr><th>区分</th><th>件数</th><th>方向的中率</th><th>平均損益</th></tr>
      ${stat(a.overall, '全体')}${stat(a.top5, 'TOP5')}${stat(a.pinned, '指定銘柄')}
      ${stat(a.category, 'ランキング')}${stat(a.fx, 'FX（シグナルあり）')}${stat(a.fx_watch, 'FX（見送り）')}
      ${stat(a.recent30, '直近30件')}
    </table>
    <p class="muted" style="margin-top:9px">記録済み ${(a.total_logged || 0).toLocaleString('ja-JP')} 件
      ／ 採点待ち ${(a.overall && a.overall.pending) ?? a.total_logged ?? 0} 件。
      ${a.overall ? '' : 'FXは翌営業日、株は1か月後に採点されるため、最初の実績が出るまで数日かかります。それまでは下の「進行中の予測」で途中経過を確認できます。'}</p></div>`;

  const prog = progressCard(d);

  const bl = d.baseline_long, bf = d.baseline_fx;
  const cmp = (bl || bf) ? `<div class="card"><h2>モデルは基準線を上回っているか</h2>
    <div class="scroll-x"><table class="tbl">
      <tr><th>枠</th><th>予測期間</th><th>モデル</th><th>基準線</th><th>差</th><th>件数</th></tr>
      ${bl ? `<tr><td>株・貴金属など</td><td>${esc(d.horizon_long_label || '')}</td>
        <td class="num">${(bl.hit_rate * 100).toFixed(1)}%</td>
        <td class="num">${(bl.base_up_rate * 100).toFixed(1)}%</td>
        <td class="num ${bl.hit_rate - bl.base_up_rate > 0.01 ? 'up' : bl.hit_rate - bl.base_up_rate < -0.01 ? 'down' : ''}">
          ${((bl.hit_rate - bl.base_up_rate) * 100).toFixed(1)}pt</td>
        <td class="num">${bl.n.toLocaleString('ja-JP')}</td></tr>` : ''}
      ${bf ? `<tr><td>FX</td><td>${esc(d.horizon_fx_label || '')}</td>
        <td class="num">${(bf.hit_rate * 100).toFixed(1)}%</td>
        <td class="num">${(bf.base_up_rate * 100).toFixed(1)}%</td>
        <td class="num ${bf.hit_rate - bf.base_up_rate > 0.01 ? 'up' : ''}">
          ${((bf.hit_rate - bf.base_up_rate) * 100).toFixed(1)}pt</td>
        <td class="num">${bf.n.toLocaleString('ja-JP')}</td></tr>` : ''}
    </table></div>
    <p class="muted" style="margin-top:9px">基準線は「何もせず買っていたら上がっていた割合」です。
      株は1か月で55%前後上がるため、的中率55%はモデルの実力ではありません。</p></div>` : '';

  const costCard = d.costs ? `<div class="card"><h2>売買コスト（PayPay証券）</h2>
    <table class="tbl">
      <tr><td>日本株・国内ETF（片道）</td><td class="num">${pct(d.costs.jp, 2)}</td></tr>
      <tr><td>米国株（現地立会時間内・片道）</td><td class="num">${pct(d.costs.us_regular, 2)}</td></tr>
      <tr><td>米国株（時間外・片道）</td><td class="num">${pct(d.costs.us_off, 2)}</td></tr>
      <tr><td>為替手数料（片道）</td><td class="num">${d.costs.fx_fee_yen}銭/ドル</td></tr>
      <tr><td>譲渡益課税</td><td class="num">${(d.costs.tax_rate * 100).toFixed(3)}%</td></tr>
    </table>
    <p class="muted" style="margin-top:8px">いまは米国市場の${d.costs.us_in_hours ? '立会時間内' : '時間外'}です。
      アプリの表示はすべて往復コストを引いた値です。税金は利益に対してかかるため別枠で、
      NISA口座なら非課税です。1か月で回転させるとコストの影響が大きいので、
      各カードの「コストを取り返すのに必要な保有期間」も見てください。</p></div>` : '';

  if (!v) return live + prog + cmp + costCard + '<p class="empty">検証データを読み込めませんでした</p>';

  const T = (title, note, head, rows) => `<div class="card"><h2>${esc(title)}</h2>
    <div class="scroll-x"><table class="tbl"><tr>${head}</tr>${rows}</table></div>
    ${note ? `<p class="muted" style="margin-top:8px">${esc(note)}</p>` : ''}</div>`;

  const reg = v.regime ? T(v.regime.title, v.regime.note,
    '<th>絞り込み方</th><th>FX的中率</th><th>t値</th><th>株的中率</th><th>t値</th>',
    v.regime.rows.map(r => `<tr><td>${esc(r.name)}${r.adopted ? ' <span class="pill ok">採用</span>' : ''}</td>
      <td class="num ${r.fx_hit >= 0.53 ? 'up' : ''}">${(r.fx_hit * 100).toFixed(1)}%</td>
      <td class="num">${num(r.fx_t, 2)}</td>
      <td class="num">${(r.stock_hit * 100).toFixed(1)}%</td>
      <td class="num">${num(r.stock_t, 2)}</td></tr>`).join('')) : '';

  // 期間をずらしても成立するかの検査。曜日の絞り込みはここで崩れて取り下げた。
  const wc = v.regime && v.regime.window_check;
  const oc = v.regime && v.regime.operating_check;
  const w3 = r => `<td class="num ${r.w400 >= 0.53 ? 'up' : ''}">${(r.w400 * 100).toFixed(1)}%</td>
      <td class="num">${(r.w360 * 100).toFixed(1)}%</td>
      <td class="num">${(r.w440 * 100).toFixed(1)}%</td>`;
  const regWin = wc ? `<div class="card"><h2>${esc(wc.title)}</h2>
    <p class="muted" style="margin-bottom:10px">${esc(wc.summary)}</p>
    <div class="scroll-x"><table class="tbl">
    <tr><th>絞り込み方</th><th>400時点</th><th>360時点</th><th>440時点</th><th>t値</th></tr>
    ${wc.rows.map(r => `<tr><td>${esc(r.name)}${r.adopted ? ' <span class="pill ok">採用</span>' : ''}</td>
      ${w3(r)}<td class="num">${num(r.t400, 2)}</td></tr>`).join('')}
    </table></div>
    <p class="muted" style="margin-top:8px">${esc(wc.note)}</p>
    ${oc ? `<h3 style="margin:14px 0 6px">${esc(oc.title)}</h3>
      <div class="scroll-x"><table class="tbl">
      <tr><th>絞り込み方</th><th>400時点</th><th>360時点</th><th>440時点</th><th>1日の回数</th><th>1日の期待値</th></tr>
      ${oc.rows.map(r => `<tr><td>${esc(r.name)}${r.adopted ? ' <span class="pill ok">採用</span>' : ''}</td>
        ${w3(r)}<td class="num">${num(r.per_day, 2)}回</td>
        <td class="num ${cls(r.daily)}">${pct(r.daily)}</td></tr>`).join('')}
      </table></div>
      <p class="muted" style="margin-top:8px">${esc(oc.note)}</p>` : ''}
    </div>` : '';

  // 試して効果が出なかった情報源。同じ道を二度調べないための記録。
  const rej = v.rejected_data ? `<div class="card"><h2>${esc(v.rejected_data.title)}</h2>
    <p class="muted" style="margin-bottom:10px">${esc(v.rejected_data.summary)}</p>
    ${v.rejected_data.rows.map(r => `<div style="margin-bottom:12px">
      <div><b>${esc(r.name)}</b> <span class="pill">${esc(r.result)}</span></div>
      <div class="muted" style="font-size:12.5px;margin-top:4px">${esc(r.detail)}</div>
    </div>`).join('')}
    <p class="muted" style="margin-top:4px">${esc(v.rejected_data.note)}</p></div>` : '';

  // 米国金利による見送り判定。採用した数少ない追加。
  const rt = v.rates;
  const w3r = r => `<td class="num ${r.w400 >= 0.55 ? 'up' : r.w400 < 0.50 ? 'down' : ''}">${(r.w400 * 100).toFixed(1)}%</td>
      <td class="num">${(r.w360 * 100).toFixed(1)}%</td><td class="num">${(r.w440 * 100).toFixed(1)}%</td>`;
  const rateCard = rt ? `<div class="card"><h2>${esc(rt.title)}</h2>
    <p class="muted" style="margin-bottom:10px">${esc(rt.summary)}</p>
    <div class="scroll-x"><table class="tbl">
    <tr><th>条件</th><th>400時点</th><th>360時点</th><th>440時点</th><th>1日の回数</th><th>1日の期待値</th></tr>
    ${rt.rows.map(r => `<tr><td>${esc(r.name)}${r.adopted ? ' <span class="pill ok">採用</span>' : ''}</td>
      ${w3r(r)}<td class="num">${num(r.per_day, 2)}回</td>
      <td class="num ${cls(r.daily)}">${pct(r.daily)}</td></tr>`).join('')}
    </table></div>
    <p class="muted" style="margin-top:8px">${esc(rt.held_out_note)}</p>
    <h3 style="margin:14px 0 6px">${esc(rt.bands.title)}</h3>
    <div class="scroll-x"><table class="tbl">
    <tr><th>金利変化の大きさ</th><th>追い風（400/360/440）</th><th>逆風（400/360/440）</th></tr>
    ${rt.bands.rows.map(r => `<tr><td>${esc(r.band)}</td>
      <td class="num up">${r.with.map(x => (x * 100).toFixed(1)).join(' / ')}%</td>
      <td class="num ${r.without[0] < 0.50 ? 'down' : ''}">${r.without.map(x => (x * 100).toFixed(1)).join(' / ')}%</td></tr>`).join('')}
    </table></div>
    <p class="muted" style="margin-top:8px">${esc(rt.bands.note)}</p>
    <p class="muted" style="margin-top:8px">${esc(rt.note)}</p></div>` : '';

  const rules = T(v.stocks.title, 't値が2以上で統計的に有意。どのルールも頑健性検査を通りませんでした。',
    '<th>並べ替えルール</th><th>市場超過</th><th>t値</th>',
    v.stocks.rules.map(r => `<tr><td>${esc(r.name)}${r.note ? `<br><span class="muted">${esc(r.note)}</span>` : ''}</td>
      <td class="num ${cls(r.excess)}">${pct(r.excess)}</td><td class="num">${num(r.t, 2)}</td></tr>`).join(''));

  const caps = T(v.stocks.vol_cap_test.title, v.stocks.vol_cap_test.note,
    '<th>年率ボラ上限</th><th>市場超過</th><th>t値</th>',
    v.stocks.vol_cap_test.rows.map(r => `<tr><td>${r.cap == null ? 'なし' : (r.cap * 100).toFixed(0) + '%'}</td>
      <td class="num ${cls(r.excess)}">${pct(r.excess)}</td><td class="num">${num(r.t, 2)}</td></tr>`).join(''));

  const split = v.stocks.split_test ? T(v.stocks.split_test.title, v.stocks.split_test.note,
    '<th>ルール</th><th>前半</th><th>t値</th><th>後半</th><th>t値</th>',
    v.stocks.split_test.rows.map(r => `<tr><td>${esc(r.name)}</td>
      <td class="num ${cls(r.first)}">${pct(r.first)}</td><td class="num">${num(r.first_t, 2)}</td>
      <td class="num ${cls(r.second)}">${pct(r.second)}</td><td class="num">${num(r.second_t, 2)}</td></tr>`).join('')) : '';

  const fxr = T(v.fx.title, v.fx.summary,
    '<th>条件</th><th>件数</th><th>的中率</th><th>t値</th>',
    v.fx.rules.map(r => `<tr><td>${esc(r.name)}${r.adopted ? ' <span class="pill ok">採用</span>' : ''}</td>
      <td class="num">${r.n.toLocaleString('ja-JP')}</td>
      <td class="num ${r.hit_rate >= 0.5 ? 'up' : 'down'}">${(r.hit_rate * 100).toFixed(1)}%</td>
      <td class="num">${num(r.t_daily, 2)}</td></tr>`).join(''));

  const psel = v.fx.pair_selection ? T(v.fx.pair_selection.title, v.fx.pair_selection.note,
    '<th>組み合わせ</th><th>的中率</th><th>1回あたり</th><th>t値</th>',
    v.fx.pair_selection.rows.map(r => `<tr><td>${esc(r.name)}${r.adopted ? ' <span class="pill ok">採用</span>' : ''}</td>
      <td class="num ${r.hit_rate >= 0.57 ? 'up' : ''}">${(r.hit_rate * 100).toFixed(1)}%</td>
      <td class="num">${pct(r.mean, 3)}</td><td class="num">${num(r.t, 2)}</td></tr>`).join('')) : '';

  const psplit = v.fx.per_pair_split ? T(v.fx.per_pair_split.title, v.fx.per_pair_split.note,
    '<th>通貨ペア</th><th>全期間</th><th>前半</th><th>後半</th><th>スプ差引後</th>',
    v.fx.per_pair_split.rows.map(r => `<tr>
      <td>${r.signal ? '<span class="pill ok">配信</span> ' : ''}${esc(r.name)}</td>
      <td class="num ${r.hit >= 0.53 ? 'up' : r.hit < 0.5 ? 'down' : ''}">${(r.hit * 100).toFixed(1)}%</td>
      <td class="num">${(r.first * 100).toFixed(1)}%</td><td class="num">${(r.second * 100).toFixed(1)}%</td>
      <td class="num ${cls(r.net)}">${pct(r.net, 3)}</td></tr>`).join('')) : '';

  const cnf = v.fx.confidence ? T(v.fx.confidence.title,
    v.fx.confidence.summary + ' ' + v.fx.confidence.note,
    '<th>確信度</th><th>勝率</th><th>1日</th><th>t値</th><th>期間をずらすと</th><th>前半/後半</th>',
    v.fx.confidence.rows.map(r => `<tr><td>${(r.conf * 100).toFixed(0)}%以上${r.adopted ? ' <span class="pill ok">既定</span>' : ''}</td>
      <td class="num ${r.hit >= 0.58 ? 'up' : ''}">${(r.hit * 100).toFixed(1)}%</td>
      <td class="num">${r.per_day.toFixed(2)}回</td>
      <td class="num">${num(r.t, 2)}</td>
      <td class="num muted">${r.windows.map(w => (w * 100).toFixed(1)).join(' / ')}</td>
      <td class="num muted">${(r.first * 100).toFixed(1)} / ${(r.second * 100).toFixed(1)}</td></tr>`).join('')) : '';

  const tim = v.fx.timing ? T(v.fx.timing.title, v.fx.timing.summary + ' ' + v.fx.timing.note,
    '<th>区分</th><th>400時点</th><th>360時点</th><th>440時点</th>',
    v.fx.timing.rows.map(r => `<tr><td>${esc(r.name)}</td>
      <td class="num">${(r.w400 * 100).toFixed(1)}%</td>
      <td class="num">${(r.w360 * 100).toFixed(1)}%</td>
      <td class="num">${(r.w440 * 100).toFixed(1)}%</td></tr>`).join('')) : '';

  const tv = v.tradingview ? `<div class="card"><h2>${esc(v.tradingview.title)}</h2>
    <p style="font-size:13px;margin:0 0 8px">${esc(v.tradingview.summary)}</p>
    <p class="muted">${esc(v.tradingview.note)}</p></div>` : '';

  const ind = v.fx.indicators ? T(v.fx.indicators.title, v.fx.indicators.note,
    '<th>条件</th><th>件数</th><th>的中率</th><th>1回あたり</th><th>t値</th>',
    v.fx.indicators.rows.map(r => `<tr><td>${esc(r.name)}${r.adopted ? ' <span class="pill ok">表示に採用</span>' : ''}</td>
      <td class="num">${r.n}</td>
      <td class="num ${r.hit_rate >= 0.58 ? 'up' : ''}">${(r.hit_rate * 100).toFixed(1)}%</td>
      <td class="num">${pct(r.mean, 3)}</td><td class="num">${num(r.t, 2)}</td></tr>`).join('')) : '';

  const costTbl = v.costs ? T(v.costs.title, v.costs.note,
    '<th>区分</th><th>片道</th><th>往復</th><th>うち為替</th>',
    v.costs.rows.map(r => `<tr><td>${esc(r.kind)}</td>
      <td class="num">${pct(r.one_way, 2)}</td>
      <td class="num warn">${pct(r.round_trip, 2)}</td>
      <td class="num">${r.fx ? pct(r.fx, 3) : '—'}</td></tr>`).join('')) : '';

  const cav = v.caveats.map(c => `<li style="margin-bottom:5px">${esc(c)}</li>`).join('');

  return live + prog + cmp + costCard + `
  <div class="banner"><strong>事前検証の結論</strong>
    株の順位付け: <b class="down">優位性を確認できず</b>／FX: <b class="up">統計的に有意</b>。
    ${esc(v.period)}。予測期間は株${esc(v.horizons ? v.horizons.long : '')}／FX${esc(v.horizons ? v.horizons.fx : '')}。
    ${v.costs ? esc(v.costs.summary) : ''}</div>
  ${costTbl}${reg}${regWin}${rules}${caps}${split}${fxr}${psel}${psplit}${cnf}${rateCard}${tim}${ind}${rej}${tv}
  <div class="card"><h2>検証方法と注意点</h2>
    <p style="font-size:13px">${esc(v.method)}</p>
    <p class="muted">${esc(v.data_note)}</p>
    <ul style="font-size:12.5px;color:var(--tx2);padding-left:18px;margin:10px 0 0">${cav}</ul></div>`;
}

/* ---------- 描画 ---------- */
function render() {
  if (!DATA) return;
  const views = { home: viewHome, top5: viewTop5, rank: viewRank, hold: viewHold, fx: viewFx, acc: viewAcc };
  try {
    $('#main').innerHTML = views[VIEW](DATA);
  } catch (e) {
    $('#main').innerHTML = `<p class="empty">表示中にエラーが発生しました<br><span class="muted">${esc(e.message)}</span></p>`;
  }
  bindTradingView();
  if (VIEW === 'fx') bindSettings();
  if (VIEW === 'rank') bindChips();
  if (VIEW === 'hold') bindHoldings();
  window.scrollTo({ top: 0, behavior: 'instant' });
}

function bindSettings() {
  const apply = () => {
    const s = settings();
    const g = id => { const v = parseFloat($('#' + id).value); return v > 0 ? v : null; };
    const cap = g('s-cap'), tgt = g('s-tgt'), rsk = g('s-risk'), trd = g('s-trd');
    const scap = g('s-scap'), srisk = g('s-srisk');
    if (cap) s.capital = cap;
    if (tgt) s.target = tgt;
    if (rsk) s.risk = Math.min(0.5, rsk / 100);
    if (trd) s.trades = Math.round(trd);
    if (scap) s.stockCapital = scap;
    if (srisk) s.stockRisk = Math.min(0.5, srisk / 100);
    saveSettings(s);
    render();
  };
  const cs = $('#s-conf');
  if (cs) cs.addEventListener('change', () => {
    const st2 = settings();
    st2.fxConf = parseFloat(cs.value) || 0.56;
    saveSettings(st2);
    render();
  });
  ['s-cap', 's-tgt', 's-risk', 's-trd', 's-scap', 's-srisk'].forEach(id => {
    const el = $('#' + id);
    if (el) el.addEventListener('change', apply);
  });
}

function bindChips() {
  document.querySelectorAll('.chip').forEach(c =>
    c.addEventListener('click', () => { CAT = +c.dataset.cat; render(); }));
}

function bindHoldings() {
  const inp = $('#h-code');
  if (inp) {
    // 入力のたびに全体を描き直すと重いので、少し待ってからまとめて反映する
    let timer = null;
    inp.addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        HOLD_Q = inp.value;
        const pos = inp.selectionStart;
        render();
        const el = $('#h-code');
        if (el) { el.focus(); try { el.setSelectionRange(pos, pos); } catch (e) { } }
      }, 220);
    });
  }
  document.querySelectorAll('.sugg li').forEach(li =>
    li.addEventListener('click', () => {
      HOLD_Q = li.dataset.code;
      render();
      const q = $('#h-qty');
      if (q) q.focus();
    }));
  const add = $('#h-add');
  if (add) add.addEventListener('click', () => {
    const code = (HOLD_Q || '').trim();
    const qty = parseFloat($('#h-qty').value);
    const cost = parseFloat($('#h-cost').value);
    if (!code || !(qty > 0) || !(cost > 0)) return;
    const dir = (DIR || []).find(x => String(x.c).toUpperCase() === code.toUpperCase());
    const st = settings();
    st.holdings = (st.holdings || []).concat([{
      code: dir ? dir.c : code, name: dir ? dir.n : code, qty, cost,
    }]);
    saveSettings(st);
    HOLD_Q = '';
    render();
  });
  document.querySelectorAll('[data-del]').forEach(b =>
    b.addEventListener('click', () => {
      const st = settings();
      st.holdings.splice(+b.dataset.del, 1);
      saveSettings(st);
      render();
    }));
}

async function load(force) {
  const btn = $('#refresh');
  btn.classList.add('spin');
  try {
    const bust = force ? '?t=' + Date.now() : '';
    const [d, v] = await Promise.all([
      fetch('data/latest.json' + bust, { cache: force ? 'reload' : 'default' }).then(r => r.json()),
      fetch('data/validation.json' + bust).then(r => r.json()).catch(() => null),
    ]);
    DATA = d; VALID = v;
    BASE_LONG = d.baseline_long ? d.baseline_long.base_up_rate : null;
    BASE_FX = d.baseline_fx ? d.baseline_fx.base_up_rate : null;
    $('#updated').textContent = `最終更新 ${d.generated_label}`;
    render();
  } catch (e) {
    $('#main').innerHTML = `<p class="empty">データを読み込めませんでした<br>
      <span class="muted">${esc(e.message)}</span></p>`;
    $('#updated').textContent = '読み込み失敗';
  } finally {
    btn.classList.remove('spin');
  }
}

document.querySelectorAll('.tab').forEach(t => {
  t.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    VIEW = t.dataset.view;
    render();
  });
});
$('#refresh').addEventListener('click', () => load(true));

load(false);

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => navigator.serviceWorker.register('sw.js').catch(() => { }));
}
