'use strict';

let DATA = null, VALID = null, VIEW = 'home', CAT = 0;
let BASE_LONG = null, BASE_FX = null;   // 何もせず買った場合の上昇率
let DIR = null, DIR_LOADING = false;    // 銘柄索引（保有タブでだけ使う・別ファイル）
let HOLD_Q = '';                        // 銘柄検索の入力
let HOLD_TAB = 'stock';                 // 保有タブ内の切り替え（株 / FX）
let SWAP_OPEN = false;                  // スワップ設定欄を開いたままにするか

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
    holdings: [], fxPositions: [],
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
  // 裏付けの強さと的中率に関係は見られなかったため、的中率は出さない。
  return `<div class="confirm"><div class="confirm-head">
      <span class="pill ${k}">テクニカル ${c.agree}/${c.total} 一致</span>
      <span class="muted num cf-hit">的中率との関係は確認できず</span>
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
    tradeable: x.confidence >= stH.fxConf,
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
        / テクニカル${s.confirm ? s.confirm.agree + '/' + s.confirm.total : '—'}
</span>
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

  if (HOLD_TAB === 'fx') {
    return `<div class="chips" style="margin-bottom:10px">
      <button class="chip" data-htab="stock">株・ETF</button>
      <button class="chip on" data-htab="fx">FX</button></div>` + fxHoldBlock(s);
  }
  return `<div class="chips" style="margin-bottom:10px">
      <button class="chip on" data-htab="stock">株・ETF</button>
      <button class="chip" data-htab="fx">FX</button></div>
    <div class="banner"><strong>保有ポジション</strong>
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



/* ---------- 買う前の点検表 ----------
   材料はすべてアプリの中にあるのに、一つの答えになっていなかった。
   「この取引を、いまの建玉に足すとどうなるか」を一枚にまとめる。
   ○×は事実の確認であって、売買の指示ではない。 */
function preTradeCheck(sig, st) {
  const cap = st.capital || 0;
  const lv = ((DATA.fx_levels || []).slice().sort((a, b) =>
    Math.abs(a.conf - st.fxConf) - Math.abs(b.conf - st.fxConf))[0]) || null;
  const edge = (DATA.fx && DATA.fx.plan && DATA.fx.plan.measured
    && DATA.fx.plan.measured.edge_per_trade) || 0.00088;
  const spread2 = (sig.spread_pct || 0) * 2;

  // 適正な通貨量：損切りまでの値幅で、資金の risk% だけ失う量
  const legs = fxLegs(sig.key);
  const rate = (DATA.usdjpy && DATA.usdjpy.rate) || null;
  // 決済通貨が円ならそのまま、それ以外はドル円で円に直す。
  // どちらも分からないときは数量を出さない（誤った数字を出すより空欄にする）。
  const conv = !legs ? null : legs[1] === 'JPY' ? 1 : (legs[1] === 'USD' ? rate : null);
  const perUnit = conv ? Math.abs((sig.entry || 0) - (sig.stop || 0)) * conv : null;
  const qty = (perUnit > 0) ? Math.floor(cap * (st.risk || 0.02) / perUnit) : null;

  // いまの建玉に1本足したらどうなるか
  const cur = fxPositions(st);
  const add = { key: sig.key, name: sig.name,
    sign: sig.direction === '買い' ? 1 : -1,
    risk: st.risk || 0.02, weight: st.risk || 0.02 };
  const before = cur.length ? fxDiagnoseLocal(cur, cap, st.risk, st.risk * 2) : null;
  const after = fxDiagnoseLocal(cur.concat([add]), cap, st.risk, st.risk * 2);
  const worstBefore = before ? before.worst_total_risk : 0;
  const worstAfter = after.worst_total_risk;
  const budget = (st.risk || 0.02) * 2;

  // 既存建玉のうち、値動きが揃うもの
  const clash = cur.map(p => ({ name: p.name, samePair: p.key === sig.key,
    corr: fxCorrOf(p.key, sig.key) * p.sign * add.sign }))
    .filter(x => Math.abs(x.corr) >= 0.7)
    .sort((a, b) => Math.abs(b.corr) - Math.abs(a.corr));
  const clashText = c => c.samePair
    ? `${c.name}の${c.corr > 0 ? '同じ' : '反対'}向きの建玉があります。`
      + (c.corr > 0 ? '実質、1つの大きな建玉になります。' : '実質、決済に近い動きになります。')
    : `${c.name}と相関${c.corr >= 0 ? '+' : ''}${c.corr.toFixed(2)}。`
      + (c.corr > 0 ? '実質、同じ取引を重ねることになります。' : '互いに打ち消し合います。');

  const ev = sig.timing && sig.timing.has_event;
  const items = [
    { ok: sig.confidence >= st.fxConf,
      t: `確信度 ${(sig.confidence * 100).toFixed(0)}%`,
      d: sig.confidence >= st.fxConf
        ? `基準の${(st.fxConf * 100).toFixed(0)}%以上です（この区分の実測${
          lv ? (lv.hit * 100).toFixed(1) : '—'}%）。`
        : `基準の${(st.fxConf * 100).toFixed(0)}%に届いていません。この水準未満に優位性は確認できていません。` },
    { ok: spread2 < edge * 0.5,
      t: `往復コスト ${(spread2 * 100).toFixed(3)}%`,
      d: `実測の1回あたりの利益${(edge * 100).toFixed(3)}%に対して${
        edge > 0 ? (spread2 / edge * 100).toFixed(0) : '—'}%です。` },
    { ok: sig.leverage_ok !== false,
      t: `必要レバレッジ ${num(sig.leverage, 1)}倍`,
      d: sig.leverage_ok !== false ? '国内業者の上限25倍に収まっています。'
        : '25倍を超えています。通貨量を減らす必要があります。' },
    { ok: !ev,
      t: ev ? '経済指標あり' : '経済指標なし',
      d: ev ? `${(sig.timing.currencies || []).join('・')}の指標が予定されています（${
        (sig.timing.events || []).slice(0, 2).join('、')}）。値動きが荒くなることがあります。`
        : 'この通貨に関係する重要な指標の予定はありません。' },
    { ok: !clash.length,
      t: clash.length ? '値動きが連動する建玉あり' : '建玉との重複なし',
      d: clash.length ? clash.map(clashText).join(' ')
        : 'いまの建玉と値動きが揃うものはありません。' },
    (() => {
      const sp = swapPct(st, sig.key, sig.direction, sig.entry, qty);
      const per10k = swapOf(st, sig.key, sig.direction);
      if (sp == null) return { ok: false, t: 'スワップ未設定',
        d: '24時間保有では必ず発生します。設定に入れるまで、この費用は計算に入っていません。' };
      const yenDay = per10k * ((qty || 0) / 10000);
      return { ok: sp >= 0 || Math.abs(sp) < edge * 0.3,
        t: `スワップ ${sp >= 0 ? '受け取り' : '支払い'} ${yen(Math.round(Math.abs(yenDay)))}／日`,
        d: `想定元本の${(sp * 100).toFixed(4)}%。実測の1回あたりの利益${
          (edge * 100).toFixed(3)}%に対して${(Math.abs(sp) / edge * 100).toFixed(0)}%です。`
          + (sp < 0 ? ' 差し引くと' + ((edge + sp) * 100).toFixed(3) + '%になります。' : '') };
    })(),
    { ok: worstAfter <= budget * 1.05,
      t: `建てた後の合計リスク ${(worstAfter * 100).toFixed(1)}%`,
      d: `${(worstBefore * 100).toFixed(1)}% → ${(worstAfter * 100).toFixed(1)}%（${
        yen(Math.round(cap * worstAfter))}）。想定は${(budget * 100).toFixed(1)}%です。` },
  ];
  const ng = items.filter(x => !x.ok).length;

  return `<details class="detail"><summary>この取引を建てる前の点検（${
    ng ? `${ng}件の注意` : 'すべて確認済み'}）</summary>
    <ul class="checks" style="grid-template-columns:1fr">
      ${items.map(i => `<li class="${i.ok ? 'yes' : 'no'}">${i.ok ? '✓' : '✕'} ${
        esc(i.t)}<br><span class="muted" style="font-size:11.5px">${esc(i.d)}</span></li>`).join('')}
    </ul>
    <div class="metrics" style="margin-top:10px">
      <div class="metric"><span class="k">適正な通貨量</span>
        <span class="v">${qty != null ? qty.toLocaleString('ja-JP') : '—'}</span></div>
      <div class="metric"><span class="k">損切り時の損失</span>
        <span class="v down">${yen(Math.round(cap * (st.risk || 0.02)))}</span></div>
      <div class="metric"><span class="k">建玉数</span>
        <span class="v">${cur.length} → ${after.count} 本</span></div>
      <div class="metric"><span class="k">実質の賭けの数</span>
        <span class="v">${after.offsetting ? '打ち消し合い' : after.effective_bets.toFixed(1) + '本'}</span></div>
    </div>
    <p class="muted" style="margin-top:9px">通貨量は、資金${yen(cap)}の${
      ((st.risk || 0.02) * 100).toFixed(1)}%を損切りで失う大きさとして計算しています。
      資金設定を変えるとこの数字も変わります。</p></details>`;
}


/* ---------- スワップポイント ----------
   FXの予測期間は24時間なので、必ず日をまたぐ＝毎回スワップが発生する。
   値は業者ごとに違い、無料で取れる短期金利も米国のものだけなので、
   推測はしない。設定に入れてもらい、入っていなければ「未計上」と明示する。 */
function swapOf(st, key, side) {
  const t = (st.swap || {})[key];
  if (!t) return null;
  const v = side === '買い' ? t.buy : t.sell;
  return (v === null || v === undefined || v === '') ? null : Number(v);
}
// 想定元本（円）に対する1日あたりの割合
function swapPct(st, key, side, price, qty) {
  const per10k = swapOf(st, key, side);
  if (per10k == null || !price || !qty) return null;
  const legs = fxLegs(key);
  const rate = (DATA.usdjpy && DATA.usdjpy.rate) || null;
  const conv = !legs ? null : legs[1] === 'JPY' ? 1 : (legs[1] === 'USD' ? rate : null);
  if (!conv) return null;
  const notional = qty * price * conv;
  const yenPerDay = per10k * (qty / 10000);
  return notional ? yenPerDay / notional : null;
}

function swapSettingsCard(st) {
  const sigs = (DATA.fx && DATA.fx.signals) || [];
  const sw = st.swap || {};
  const unset = sigs.filter(x => swapOf(st, x.key, '買い') == null
    || swapOf(st, x.key, '売り') == null).length;
  const sens = (DATA.fx_swap && DATA.fx_swap.sensitivity) || [];
  return `<details class="detail" ${unset || SWAP_OPEN ? 'open' : ''}>
    <summary>スワップの設定（${unset ? `未設定 ${unset}ペア` : '設定済み'}）</summary>
    <p class="muted" style="margin:8px 0">
      FXの予測期間は24時間なので<b>必ず日をまたぎます</b>。つまりスワップが毎回発生します。
      値は業者ごとに違うため、こちらでは推測しません。
      ご利用の業者が公表している<b>1万通貨あたり1日の金額</b>を入れてください。
      受け取りは＋、支払いは−で入力します。</p>
    ${sigs.map(x => `<div class="pf-exp-row" style="grid-template-columns:78px 1fr 1fr">
      <span class="pf-exp-nm">${esc(x.name)}</span>
      <label style="font-size:11px;color:var(--tx3)">買い
        <input class="sw-in" data-sw="${esc(x.key)}" data-side="buy" type="number"
          inputmode="numeric" step="1" placeholder="＋140"
          value="${(sw[x.key] && sw[x.key].buy != null) ? sw[x.key].buy : ''}"></label>
      <label style="font-size:11px;color:var(--tx3)">売り
        <input class="sw-in" data-sw="${esc(x.key)}" data-side="sell" type="number"
          inputmode="numeric" step="1" placeholder="−190"
          value="${(sw[x.key] && sw[x.key].sell != null) ? sw[x.key].sell : ''}"></label>
    </div>`).join('')}
    ${unset && sens.length ? `<p class="muted" style="margin-top:10px">
      未設定のあいだ、この費用は計算に入っていません。目安として、
      ${sens.map(v => `1日${(v.swap_pct * 100).toFixed(3)}%なら実測の優位性の${
        (v.share * 100).toFixed(0)}%`).join('、')}が消えます。</p>` : ''}
    ${(DATA.fx_swap && DATA.fx_swap.us_short_rate) ? `<p class="muted" style="font-size:11.5px">
      参考：米国の短期金利は${DATA.fx_swap.us_short_rate.toFixed(2)}%です。
      金利差だけの理屈値は業者の上乗せを含まないので、実際の受け取りはこれより少なく、
      支払いはこれより多くなるのが普通です。</p>` : ''}
  </details>`;
}

/* ---------- FXの建玉とリスク計算 ----------
   建玉の入力はこの端末にしかないので、相関表だけサーバーから受け取り、
   計算はここで行う。式は engine/fxrisk.py と同じ。 */
function fxCorrOf(a, b) {
  if (a === b) return 1;
  const c = (DATA && DATA.fx_corr && DATA.fx_corr.pairs) || {};
  const v = c[a + '|' + b];
  return v != null ? v : (c[b + '|' + a] != null ? c[b + '|' + a] : 0);
}
function fxLegs(k) {
  const l = (DATA && DATA.fx_corr && DATA.fx_corr.legs) || {};
  if (l[k]) return l[k];
  // データが古いなどで対応表が無いときは、記号から読み取る（USDJPY=X → USD/JPY）。
  // ここが取れないと円換算を誤り、通貨量の計算が桁違いになるため必ず補う。
  const m = String(k || '').match(/^([A-Z]{3})([A-Z]{3})=X$/);
  return m ? [m[1], m[2]] : null;
}
function fxCurName(c) {
  const n = (DATA && DATA.fx_corr && DATA.fx_corr.names) || {};
  return n[c] || c;
}
function fxMeanCorr(ps) {
  if (ps.length < 2) return 0;
  let sum = 0, cnt = 0;
  for (let i = 0; i < ps.length; i++)
    for (let j = i + 1; j < ps.length; j++) {
      sum += fxCorrOf(ps[i].key, ps[j].key) * ps[i].sign * ps[j].sign;
      cnt++;
    }
  return cnt ? sum / cnt : 0;
}
function fxRiskMult(n, mc) {
  if (n <= 0) return 0;
  return Math.sqrt(Math.max(n * (1 + (n - 1) * mc), 0));
}
function fxEffectiveBets(n, mc) {
  if (n <= 1) return n;
  const d = 1 + (n - 1) * mc;
  return d <= 0 ? n : Math.min(n / d, n);
}
function fxExposure(ps) {
  const net = {};
  ps.forEach(p => {
    const legs = fxLegs(p.key);
    if (!legs) return;
    const w = (p.weight == null ? 1 : p.weight) * p.sign;
    net[legs[0]] = (net[legs[0]] || 0) + w;
    net[legs[1]] = (net[legs[1]] || 0) - w;
  });
  const total = Object.values(net).reduce((t, v) => t + Math.abs(v), 0) || 1;
  return Object.entries(net).filter(([, v]) => Math.abs(v) > 1e-9)
    .map(([c, v]) => ({ currency: c, name: fxCurName(c), net: v,
      share: Math.abs(v) / total,
      side: v > 0 ? '買い越し' : '売り越し' }))
    .sort((a, b) => Math.abs(b.net) - Math.abs(a.net));
}
// engine/fxrisk.diagnose と同じ結果を返す
function fxDiagnoseLocal(ps, capital, riskPerTrade, budget) {
  const n = ps.length;
  if (!n) return null;
  const mc = fxMeanCorr(ps);
  const mult = fxRiskMult(n, mc);
  // 実際の損切り幅が分かっていればそれを合計する。分からなければ設定値×本数。
  const known = ps.filter(p => p.risk != null);
  const worst = known.length === n
    ? ps.reduce((t, p) => t + p.risk, 0) : riskPerTrade * n;
  const byVol = mult > 0 ? budget / mult : riskPerTrade;
  const byWorst = budget / n;
  const suggested = Math.min(byVol, byWorst, riskPerTrade);
  const high = (DATA.fx_corr && DATA.fx_corr.high) || 0.7;
  const hot = [];
  for (let i = 0; i < n; i++)
    for (let j = i + 1; j < n; j++) {
      const c = fxCorrOf(ps[i].key, ps[j].key) * ps[i].sign * ps[j].sign;
      if (Math.abs(c) >= high) hot.push({ a: ps[i].name, b: ps[j].name, corr: c, same: c > 0 });
    }
  hot.sort((x, y) => Math.abs(y.corr) - Math.abs(x.corr));
  return {
    count: n, mean_corr: mc, effective_bets: fxEffectiveBets(n, mc),
    risk_multiplier: mult, worst_total_risk: worst,
    worst_total_yen: Math.round(capital * worst),
    suggested_per_trade: suggested, suggested_worst_risk: suggested * n,
    risk_budget: budget, reduce_needed: suggested < riskPerTrade * 0.95,
    offsetting: mc < -0.2 && n >= 2, exposure: fxExposure(ps),
    high_corr_pairs: hot,
    matrix: (() => {
      const out = [];
      for (let i = 0; i < n; i++)
        for (let j = i + 1; j < n; j++)
          out.push({ a: ps[i].key, b: ps[j].key, corr: fxCorrOf(ps[i].key, ps[j].key) });
      return out;
    })(),
    warnings: (() => {
      const w = [];
      const eff = fxEffectiveBets(n, mc);
      if (n >= 2 && eff < n * 0.6)
        w.push(`${n}本のうち、実質${eff.toFixed(1)}本ぶんの賭けにしかなっていません。`
          + '値動きが揃うため、分散したつもりで同じ方向に賭けている状態です。');
      if (mc < -0.2 && n >= 2)
        w.push(`いまは値動きが逆向き（平均相関${mc.toFixed(2)}）で打ち消し合っていますが、`
          + '相場が荒れると相関は1に近づきます。これを前提にポジションを増やさないでください。');
      hot.slice(0, 3).forEach(h => w.push(
        `${h.a}と${h.b}は相関${h.corr >= 0 ? '+' : ''}${h.corr.toFixed(2)}で、ほぼ同じ取引です。`
        + (h.same ? '片方に絞ることを検討してください。' : '互いに打ち消し合っています。')));
      if (worst > budget * 1.2)
        w.push(`全部が損切りに掛かると資金の${(worst * 100).toFixed(1)}%を失います。`
          + (suggested < riskPerTrade * 0.95
            ? `1本あたりを${(suggested * 100).toFixed(1)}%（${n}本で合計`
              + `${(suggested * n * 100).toFixed(1)}%）に下げるか、本数を減らしてください。`
            : `想定していた${(budget * 100).toFixed(1)}%を超えるので、本数を減らすか、`
              + '1回のリスク設定を見直してください。'));
      return w;
    })(),
  };
}

// 建玉を診断に渡せる形にする。
// 同じペアを同じ向きで複数持っているのは「1つの大きな建玉」なのでまとめる。
// 重みには、損切りまでの実際の損失額（資金比）を使う。仮の2%より正確。
function fxPositions(st) {
  const cap = st.capital || 1;
  const acc = {};
  (st.fxPositions || []).forEach(p => {
    const k = p.key + '|' + p.side;
    const m = fxMark(p, st);
    const risk = (m.riskJpy != null && cap) ? m.riskJpy / cap : (st.risk || 0.02);
    if (!acc[k]) acc[k] = { key: p.key, name: p.name,
      sign: p.side === '買い' ? 1 : -1, risk: 0, weight: 0 };
    acc[k].risk += risk;
    acc[k].weight += risk;
  });
  return Object.values(acc);
}

// その建玉の、いまの値と損益
function fxMark(p, st) {
  const sig = ((DATA.fx && DATA.fx.signals) || []).find(x => x.key === p.key);
  const cur = sig ? sig.price : null;
  const legs = fxLegs(p.key);
  const rate = (DATA.usdjpy && DATA.usdjpy.rate) || null;
  // 円換算：決済通貨が円ならそのまま、ドルならドル円を掛ける。
  // 判別できないときは金額を出さない（誤った円換算を出さないため）。
  const conv = !legs ? null : legs[1] === 'JPY' ? 1 : (legs[1] === 'USD' ? rate : null);
  const toJpy = v => (v == null || !conv ? null : v * conv);
  const sign = p.side === '買い' ? 1 : -1;
  const move = (cur != null && p.entry) ? (cur - p.entry) * sign : null;
  const pl = toJpy(move != null ? move * p.qty : null);
  const spread = (DATA.fx_spread && DATA.fx_spread[p.key]) || 0;
  const costJpy = toJpy(p.entry * spread * 2 * p.qty);
  const toStop = (cur != null && p.stop) ? Math.abs(cur - p.stop) / cur : null;
  const toTarget = (cur != null && p.target) ? Math.abs(cur - p.target) / cur : null;
  const riskJpy = toJpy(p.stop ? Math.abs(p.entry - p.stop) * p.qty : null);
  // 建ててからの日数ぶんのスワップ。24時間保有でも1日ぶんは必ず付く。
  const per10k = swapOf(st, p.key, p.side);
  const days = p.opened
    ? Math.max(1, Math.round((Date.now() - new Date(p.opened).getTime()) / 86400000))
    : 1;
  const swapJpy = per10k == null ? null : per10k * (p.qty / 10000) * days;
  const hit = p.stop != null && cur != null &&
    (sign > 0 ? cur <= p.stop : cur >= p.stop);
  const won = p.target != null && cur != null &&
    (sign > 0 ? cur >= p.target : cur <= p.target);
  return { sig, cur, pl, costJpy, toStop, toTarget, riskJpy, hit, won, sign,
    swapJpy, days, agree: sig ? (sig.direction === p.side) : null };
}


/* ---------- FXの建玉：いま持っているものをどうするか ----------
   アプリは買う側だけを扱ってきたが、実際は持っているものの扱いの方が
   回数が多い。ここでは事実だけを並べる（到達したか、モデルは何と言っているか、
   コストを取り返したか）。売れ・持てとは言わない。 */
function fxHoldBlock(st) {
  const sigs = (DATA.fx && DATA.fx.signals) || [];
  const opts = sigs.map(x =>
    `<option value="${esc(x.key)}">${esc(x.name)}</option>`).join('');
  const form = `<div class="card"><h2>FXの建玉を追加</h2>
    <div class="set-grid">
      <label>通貨ペア<select id="fp-pair">${opts}</select></label>
      <label>売買<select id="fp-side"><option>買い</option><option>売り</option></select></label>
      <label>建値<input id="fp-entry" type="number" inputmode="decimal" step="0.0001" placeholder="158.78"></label>
      <label>通貨量<input id="fp-qty" type="number" inputmode="numeric" step="1000" placeholder="10000"></label>
      <label>損切り<input id="fp-stop" type="number" inputmode="decimal" step="0.0001" placeholder="160.47"></label>
      <label>利確<input id="fp-target" type="number" inputmode="decimal" step="0.0001" placeholder="156.26"></label>
    </div>
    <button id="fp-add" class="add" style="margin-top:9px">建玉を追加</button>
    <p class="muted" style="margin-top:8px">通貨量は「1万通貨なら 10000」のように入れてください。
      損切りと利確は空でも構いません。入力内容は<b>この端末にだけ</b>保存されます。</p></div>`;

  const list = (st.fxPositions || []).map((p, i) => {
    const m = fxMark(p, st);
    const notes = [];
    if (m.hit) notes.push('損切り価格に到達しています。');
    if (m.won) notes.push('利確価格に到達しています。');
    if (m.agree === false && m.sig && m.sig.confidence >= st.fxConf)
      notes.push(`いまのモデルは反対の${esc(m.sig.direction)}を示しています`
        + `（確信度${(m.sig.confidence * 100).toFixed(0)}%）。`);
    if (m.agree === true && m.sig && m.sig.confidence >= st.fxConf)
      notes.push(`いまのモデルも同じ${esc(m.sig.direction)}を示しています`
        + `（確信度${(m.sig.confidence * 100).toFixed(0)}%）。`);
    if (m.swapJpy == null)
      notes.push('スワップが未設定です。24時間以上持つと必ず発生するので、'
        + '損益はその分ずれています。FXタブの「スワップ」で設定できます。');
    if (m.pl != null && m.costJpy != null && m.pl > 0 && m.pl < m.costJpy)
      notes.push(`含み益${yen(Math.round(m.pl))}は往復コスト${yen(Math.round(m.costJpy))}`
        + 'をまだ取り返していません。');
    return `<article class="item">
      <div class="item-head">
        <div class="item-title">
          <span class="nm">${esc(p.name)}
            <span class="pill ${p.side === '買い' ? 'ok' : 'no'}">${esc(p.side)}</span></span>
          <span class="sub">建値 ${num(p.entry, 4)} · ${(p.qty || 0).toLocaleString('ja-JP')}通貨</span>
        </div>
        <div class="item-fig">
          <div class="pct ${cls(m.pl)}">${m.pl != null ? yen(Math.round(m.pl)) : '—'}</div>
          <div class="pr">いま ${num(m.cur, 4)}</div>
        </div>
      </div>
      <div class="metrics">
        <div class="metric"><span class="k">損切りまで</span>
          <span class="v ${m.hit ? 'down' : ''}">${m.toStop != null ? pct(m.toStop) : '—'}</span></div>
        <div class="metric"><span class="k">利確まで</span>
          <span class="v ${m.won ? 'up' : ''}">${m.toTarget != null ? pct(m.toTarget) : '—'}</span></div>
        <div class="metric"><span class="k">損切り時の損失</span>
          <span class="v">${m.riskJpy != null ? yen(Math.round(m.riskJpy)) : '—'}</span></div>
        <div class="metric"><span class="k">往復コスト</span>
          <span class="v">${m.costJpy != null ? yen(Math.round(m.costJpy)) : '—'}</span></div>
        <div class="metric"><span class="k">スワップ（${m.days}日）</span>
          <span class="v ${m.swapJpy == null ? '' : cls(m.swapJpy)}">${
            m.swapJpy == null ? '未設定' : yen(Math.round(m.swapJpy))}</span></div>
        <div class="metric"><span class="k">スワップ込み</span>
          <span class="v ${m.swapJpy == null ? '' : cls((m.pl || 0) + m.swapJpy)}">${
            m.swapJpy == null ? '—' : yen(Math.round((m.pl || 0) + m.swapJpy))}</span></div>
      </div>
      ${notes.length ? `<ul class="pf-warn" style="margin-top:10px">${
        notes.map(t => `<li>${t}</li>`).join('')}</ul>` : ''}
      <button class="del" data-fpdel="${i}" style="margin-top:9px">削除</button>
    </article>`;
  }).join('');

  const ps = fxPositions(st);
  const diag = ps.length
    ? fxDiagnoseLocal(ps, st.capital, st.risk, st.risk * 2) : null;
  const totalPl = (st.fxPositions || []).reduce((t, p) => {
    const m = fxMark(p, st);
    return t + (m.pl || 0);
  }, 0);
  const totals = ps.length ? `<div class="card"><h2>建玉の合計</h2>
    <div class="row"><span class="muted">含み損益</span>
      <span class="num ${cls(totalPl)}">${yen(Math.round(totalPl))}</span></div>
    <div class="row"><span class="muted">建玉数</span>
      <span class="num">${ps.length} 本</span></div>
    <div class="row"><span class="muted">全部が損切りに掛かったら</span>
      <span class="num down">${yen(Math.round((st.fxPositions || []).reduce((t, p) =>
        t + (fxMark(p, st).riskJpy || 0), 0)))}</span></div></div>` : '';

  return `<div class="banner"><strong>FXの建玉</strong>
    いま持っているポジションを入れると、損益・損切りまでの距離・
    いまのモデルの見方・全体のリスクを並べて見られます。
    ここに出るのは<b>事実だけ</b>です。売買の指示ではありません。</div>
    ${form}${totals}
    ${diag ? pfBlock(diag, st, '建玉全体の診断',
      'いま持っているポジションを通貨に分解した結果です。') : ''}
    ${list}`;
}

/* ---------- FX ---------- */

/* ---------- ポジション全体の診断 ----------
   主要5ペアのうち4つは円クロスで値動きが揃う。各シグナルを独立に建てると、
   分散したつもりで同じ賭けを重ねることになる。それを数字と図で示す。

   色は検証を通したものだけを使う（色覚特性でも区別できることを確認済み）。 */
const PF_SHORT = {
  '米ドル/円': 'ドル円', 'ユーロ/円': 'ユロ円', 'ポンド/円': 'ポンド円',
  '豪ドル/円': '豪ドル円', 'ユーロ/米ドル': 'ユロドル', 'NZドル/円': 'NZ円',
  'カナダドル/円': 'カナダ円', 'スイスフラン/円': 'スイス円',
};
const pfShort = n => PF_SHORT[n] || String(n || '').replace('/', '');

// 相関の強さを色に変換する。0付近は目立たせず、±1に近づくほど濃くする。
function corrColor(c) {
  const t = Math.min(Math.abs(c), 1);
  if (t < 0.12) return 'var(--pf-zero)';
  const hue = c > 0 ? '200,132,42' : '91,140,255';
  return `rgba(${hue},${(0.18 + t * 0.72).toFixed(2)})`;
}

function pfBlock(pf, st, title, note) {
  if (!pf || !pf.count) return '';
  const cap = st.capital || 0;
  const worstYen = Math.round(cap * pf.worst_total_risk);
  const sugYen = Math.round(cap * pf.suggested_per_trade);
  const concentrated = pf.count >= 2 && pf.effective_bets < pf.count * 0.6;

  const tiles = `<div class="pf-tiles">
    <div class="pf-tile"><span class="k">建てる本数</span>
      <span class="v">${pf.count}<span class="u">本</span></span></div>
    <div class="pf-tile ${concentrated || pf.offsetting ? 'alert' : ''}">
      <span class="k">実質の賭けの数</span>
      <span class="v">${pf.offsetting ? '—' : pf.effective_bets.toFixed(1)}<span class="u">${
        pf.offsetting ? '打ち消し合い' : '本ぶん'}</span></span></div>
    <div class="pf-tile ${pf.worst_total_risk > pf.risk_budget * 1.2 ? 'alert' : ''}">
      <span class="k">全部やられたら</span>
      <span class="v">${yen(worstYen)}<span class="u">${(pf.worst_total_risk * 100).toFixed(1)}%</span></span></div>
    <div class="pf-tile ${pf.reduce_needed || pf.worst_total_risk > pf.risk_budget * 1.2 ? 'alert' : ''}">
      <span class="k">推奨 1本あたり</span>
      <span class="v">${(pf.suggested_per_trade * 100).toFixed(1)}<span class="u">% · ${yen(sugYen)}</span></span>
      ${pf.count ? `<span class="k" style="margin-top:3px">いま平均 ${
        ((pf.worst_total_risk / pf.count) * 100).toFixed(1)}%</span>` : ''}</div>
  </div>`;

  const maxShare = Math.max(...pf.exposure.map(e => e.share), 0.001);
  const exp = pf.exposure.length ? `<div class="pf-exp">
    ${pf.exposure.map(e => {
      const w = (e.net > 0 ? 1 : -1);
      const pct2 = (e.share / maxShare) * 50;
      return `<div class="pf-exp-row" title="${esc(e.name)} ${esc(e.side)} ${(e.share * 100).toFixed(0)}%">
        <span class="pf-exp-nm">${esc(e.name)}</span>
        <span class="pf-exp-track"><span class="pf-exp-bar ${w > 0 ? 'long' : 'short'}"
          style="width:${pct2.toFixed(1)}%"></span></span>
        <span class="pf-exp-val ${w > 0 ? '' : ''}">${(e.share * 100).toFixed(0)}%</span>
      </div>`;
    }).join('')}
    <div class="pf-axis"><span></span><span><span>← 売り越し</span><span>買い越し →</span></span><span></span></div>
  </div>` : '';

  const keys = [...new Set((pf.matrix || []).flatMap(m => [m.a, m.b]))];
  const nm = {};
  (DATA.fx.signals || []).forEach(x => { nm[x.key] = x.name; });
  const get = (a, b) => {
    if (a === b) return null;
    const m = (pf.matrix || []).find(x => (x.a === a && x.b === b) || (x.a === b && x.b === a));
    return m ? m.corr : 0;
  };
  const mx = keys.length >= 2 ? `<div class="pf-mx"
    style="grid-template-columns:46px repeat(${keys.length},1fr)">
    <div class="hd"></div>${keys.map(k => `<div class="hd">${esc(pfShort(nm[k] || k))}</div>`).join('')}
    ${keys.map(a => `<div class="rw">${esc(pfShort(nm[a] || a))}</div>${
      keys.map(b => {
        const c = get(a, b);
        if (c === null) return '<div class="cell self">—</div>';
        return `<div class="cell" style="background:${corrColor(c)}"
          title="${esc(pfShort(nm[a] || a))} と ${esc(pfShort(nm[b] || b))}: 相関 ${c >= 0 ? '+' : ''}${c.toFixed(2)}">${
          c >= 0 ? '+' : ''}${c.toFixed(2)}</div>`;
      }).join('')}`).join('')}
  </div>
  <div class="pf-legend">
    <span><span class="sw" style="background:var(--pf-same)"></span>同じ向きに動く</span>
    <span><span class="sw" style="background:var(--pf-zero)"></span>関係が薄い</span>
    <span><span class="sw" style="background:var(--pf-opp)"></span>逆向きに動く</span>
    <span>直近120営業日</span>
  </div>` : '';

  const warn = (pf.warnings || []).length
    ? `<ul class="pf-warn">${pf.warnings.map(w => `<li>${esc(w)}</li>`).join('')}</ul>` : '';

  return `<div class="card"><h2>${esc(title)}</h2>
    ${note ? `<p class="muted" style="margin:0 0 4px">${esc(note)}</p>` : ''}
    ${tiles}
    <h3 style="margin:14px 0 4px;font-size:13.5px">通貨ごとの正味の持ち高</h3>
    <p class="muted" style="margin:0 0 6px;font-size:12px">
      ペアを通貨に分解して足し合わせた結果です。何に賭けているかはここに出ます。</p>
    ${exp}
    <h3 style="margin:16px 0 4px;font-size:13.5px">ペア同士の連動</h3>
    <p class="muted" style="margin:0 0 6px;font-size:12px">
      数字が大きいほど同じ値動きをします。＋0.7を超える組は、実質ひとつの取引です。</p>
    ${mx}
    ${warn}</div>`;
}

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
    tradeable: x.confidence >= st.fxConf,
    status: x.confidence >= st.fxConf ? 'シグナルあり' : '見送り',
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
      ? `<span class="pill">${esc(s.rate.label)}</span>` : ''}
      </div>
      ${s.rate && s.rate.note
      ? `<p class="muted" style="margin:8px 0 0">${esc(s.rate.note)}</p>` : ''}
      ${chartSVG(s.chart, 140)}
      ${macdChart(s.ind_chart)}
      ${rsiChart(s.ind_chart)}
      ${preTradeCheck(s, st)}
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
    <b>勝率${lv ? (lv.hit * 100).toFixed(1) + '%' : '—'}</b>
    （1日${lv ? lv.per_day.toFixed(2) : '—'}回・${lv && lv.n != null ? lv.n + '件' : '—'}）。
    ${lv && lv.spread != null ? `これは検証時点の並びを1日ずつずらした3標本の平均で、
    標本ごとの振れ幅は${(lv.spread * 100).toFixed(1)}ポイントです。` : ''}${
    lv && lv.reliable === false ? '<b class="down">この区分は振れ幅が大きく、当てにできません。</b>' : ''}
    それ未満のペアは参考表示です。スプレッドは未計上です。</div>
    ${settingsCard}
    <div class="card"><h2>スワップ（金利差の受け払い）</h2>${swapSettingsCard(st)}</div>
    ${plan}
    ${pfBlock(d.fx.portfolio, st, 'ポジション全体の診断', 'いま売買条件を満たしているシグナルを、全部建てた場合の姿です。')}
    ${(d.fx.portfolio_all && d.fx.portfolio_all.count > (d.fx.portfolio ? d.fx.portfolio.count : 0))
      ? pfBlock(d.fx.portfolio_all, st, '参考：5ペア全部を建てた場合', '確信度が届いていないものも含めて全部建てると、こうなります。') : ''}
    <div class="card"><h2>主要5ペア（${esc(d.horizon_fx_label || '')}先）</h2>
      <div class="row"><span class="muted">売買条件を満たしているペア</span>
        <span class="num"><strong class="${nTrade ? 'up' : ''}">${nTrade}</strong> / ${all.length}</span></div>
      ${d.econ ? `<div class="row"><span class="muted">${esc(d.econ.next_date)}の重要指標</span>
        <span class="num">${d.econ.next.high_count} 件
          <span class="muted">${esc((d.econ.next.currencies || []).join(' '))}</span></span></div>` : ''}

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
        <tr><th>確信度</th><th>勝率(平均)</th><th>1日</th><th>件数</th><th>並びをずらすと</th></tr>
        ${d.fx_levels.map(l => `<tr>
          <td>${(l.conf * 100).toFixed(0)}%以上${Math.abs(l.conf - st.fxConf) < 0.005 ? ' <span class="pill ok">選択中</span>' : ''}</td>
          <td class="num ${l.reliable === false ? 'down' : (l.hit >= 0.56 ? 'up' : '')}">${(l.hit * 100).toFixed(1)}%${
        l.reliable === false ? ' <span class="muted">当てにできず</span>' : ''}</td>
          <td class="num">${l.per_day.toFixed(2)}回</td>
          <td class="num">${l.n != null ? l.n + '件' : '—'}</td>
          <td class="num muted">${(l.by_offset || l.windows || []).map(w => (w * 100).toFixed(1)).join(' / ')}%
            ${l.spread != null ? `<span class="${l.spread >= 0.06 ? 'down' : ''}">±${(l.spread * 100).toFixed(1)}pt</span>` : ''}</td></tr>`).join('')}
      </table></div>
      <p class="muted" style="margin-top:8px">確信度を上げるほど機会は減ります。
        「並びをずらすと」は検証時点の並びを1日ずつずらした3標本それぞれの勝率で、
        これらは互いに1日も重ならない別々の標本です。
        振れ幅が大きいほど、その数字は運に左右されます。
        <b>60%区分は振れ幅11.4ポイント・80件しかなく、当てにできません。</b>
        確信度を上げれば勝てる、とは言えない状態です。</p>` : ''}</div>
    ${sigs || '<p class="empty">FXデータを取得できませんでした</p>'}`;
}

/* ---------- 的中率 ---------- */

/* ---------- 優位性が消えていないかの監視 ----------
   検証で確認できた優位性は、いつまでも続く保証がない。問題は
   「消えたことにいつ気づくか」で、後から基準を決めると都合よく
   解釈できてしまう。だから基準は実績を見る前に固定してある。 */
function monitorCard(d) {
  const m = d.fx_monitor, r = d.monitor_rules;
  if (!m || !r) return '';
  const tone = { ok: 'up', watch: '', below: 'warn', stop: 'down',
    not_enough: '' }[m.verdict] || '';
  const pillCls = { ok: 'ok', watch: 'wa', below: 'wa', stop: 'no',
    not_enough: '' }[m.verdict] || '';
  const prog = Math.min(100, (m.n / r.min_samples) * 100);
  return `<div class="card"><h2>優位性が続いているかの監視</h2>
    <div class="row"><span class="big ${tone}">${esc(m.label)}</span>
      <span class="pill ${pillCls}">${m.n} / ${r.min_samples} 件</span></div>
    <p class="muted" style="margin:6px 0 10px">${esc(m.detail)}</p>
    ${m.n < r.min_samples ? `<div class="pf-exp-track" style="height:8px">
      <span class="pf-exp-bar long" style="left:0;width:${prog.toFixed(0)}%;height:6px"></span></div>
      <p class="muted" style="font-size:11.5px;margin:6px 0 0">
        判定できるまであと${r.min_samples - m.n}件です。</p>` : ''}
    <div class="metrics" style="margin-top:12px">
      <div class="metric"><span class="k">実績の的中率</span>
        <span class="v ${m.hit != null && m.hit >= m.expected ? 'up' : ''}">${
          m.hit != null ? (m.hit * 100).toFixed(1) + '%' : '—'}</span></div>
      <div class="metric"><span class="k">検証での想定</span>
        <span class="v">${(m.expected * 100).toFixed(1)}%</span></div>
      <div class="metric"><span class="k">95%区間</span>
        <span class="v">${m.n ? (m.ci_low * 100).toFixed(0) + '〜' + (m.ci_high * 100).toFixed(0) + '%' : '—'}</span></div>
      <div class="metric"><span class="k">下回る確率</span>
        <span class="v">${m.p_value != null ? m.p_value.toFixed(3) : '—'}</span></div>
    </div>
    <details class="detail" style="margin-top:10px"><summary>先に決めてある基準</summary>
      <div class="scroll-x"><table class="tbl">
        <tr><td>対象</td><td>${esc(r.target)}</td></tr>
        <tr><td>想定する的中率</td><td>${(r.expected * 100).toFixed(1)}%</td></tr>
        <tr><td>判定に要る件数</td><td>${r.min_samples}件</td></tr>
        <tr><td>警告を出す条件</td><td>想定を下回る確率が${r.alarm_p}未満</td></tr>
        <tr><td>停止を検討する条件</td><td>95%区間の上端が${(r.stop_upper * 100).toFixed(0)}%を下回る</td></tr>
        <tr><td>基準を決めた日</td><td>${esc(r.fixed_at)}</td></tr>
      </table></div>
      <p class="muted" style="margin-top:8px">${esc(r.note)}</p></details></div>`;
}

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
  const w3 = r => `<td class="num ${r.w400 >= 0.53 ? 'up' : ''}">${(r.w400 * 100).toFixed(1)}%</td>
      <td class="num">${(r.w360 * 100).toFixed(1)}%</td>
      <td class="num">${(r.w440 * 100).toFixed(1)}%</td>`;
  const regWin = wc ? `<div class="card"><h2>${esc(wc.title)}</h2>
    <p class="muted" style="margin-bottom:10px">${esc(wc.summary)}</p>
    <div class="scroll-x"><table class="tbl">
    <tr><th>絞り込み方</th><th>並び0</th><th>並び1</th><th>並び2</th><th>平均</th><th>振れ幅</th><th>件数</th><th>t値</th></tr>
    ${wc.rows.map(r => `<tr><td>${esc(r.name)}${r.adopted ? ' <span class="pill ok">採用</span>' : ''}</td>
      ${w3(r)}<td class="num"><b>${r.avg != null ? (r.avg * 100).toFixed(1) + '%' : '—'}</b></td>
      <td class="num ${r.span >= 0.04 ? 'down' : ''}">${r.span != null ? (r.span * 100).toFixed(1) + 'pt' : '—'}</td>
      <td class="num">${r.n != null ? r.n + '件' : '—'}</td>
      <td class="num ${r.t != null && r.t < 2 ? 'down' : ''}">${r.t != null ? r.t.toFixed(2) : '—'}</td></tr>`).join('')}
    </table></div>
    <p class="muted" style="margin-top:8px">${esc(wc.note)}</p>
    ${(wc.conclusions || []).length ? `<ul style="font-size:12.5px;color:var(--tx2);padding-left:18px;margin:10px 0 0">
      ${wc.conclusions.map(c => `<li>${esc(c)}</li>`).join('')}</ul>` : ''}
    </div>` : '';

  // 試して効果が出なかった情報源。同じ道を二度調べないための記録。
  const rej = v.rejected_data ? `<div class="card"><h2>${esc(v.rejected_data.title)}</h2>
    <p class="muted" style="margin-bottom:10px">${esc(v.rejected_data.summary)}</p>
    ${v.rejected_data.rows.map(r => `<div style="margin-bottom:12px">
      <div><b>${esc(r.name)}</b> <span class="pill">${esc(r.result)}</span></div>
      <div class="muted" style="font-size:12.5px;margin-top:4px">${esc(r.detail)}</div>
    </div>`).join('')}
    <p class="muted" style="margin-top:4px">${esc(v.rejected_data.note)}</p></div>` : '';

  // 時点の並びをずらした3標本での測定。これまでの検査の穴を直したもの。
  const g3 = (rt, cls3) => rt.rows.map(r => `<tr><td>${esc(r.name)}</td>
      <td class="num">${(r.o0 * 100).toFixed(1)}%</td>
      <td class="num">${(r.o1 * 100).toFixed(1)}%</td>
      <td class="num">${(r.o2 * 100).toFixed(1)}%</td>
      <td class="num ${cls3 && r.avg >= 0.55 ? 'up' : ''}"><b>${(r.avg * 100).toFixed(1)}%</b></td>
      <td class="num ${r.span >= 0.06 ? 'down' : 'muted'}">${(r.span * 100).toFixed(1)}pt</td></tr>`).join('');
  const gridCard = v.grid ? `<div class="card"><h2>${esc(v.grid.title)}</h2>
    <p class="muted" style="margin-bottom:10px">${esc(v.grid.summary)}</p>
    <div class="scroll-x"><table class="tbl">
    <tr><th>条件</th><th>並び0</th><th>並び1</th><th>並び2</th><th>平均</th><th>振れ幅</th></tr>
    ${v.grid.rows ? g3(v.grid, true) : ''}</table></div>
    <p class="muted" style="margin-top:8px">${esc(v.grid.note)}</p>
    <ul style="font-size:12.5px;color:var(--tx2);padding-left:18px;margin:10px 0 0">
    ${v.grid.conclusions.map(c => `<li>${esc(c)}</li>`).join('')}</ul></div>` : '';
  const rateCard = v.rates ? `<div class="card"><h2>${esc(v.rates.title)}</h2>
    <p class="muted" style="margin-bottom:10px">${esc(v.rates.summary)}</p>
    <div class="scroll-x"><table class="tbl">
    <tr><th>条件</th><th>並び0</th><th>並び1</th><th>並び2</th><th>平均</th><th>振れ幅</th></tr>
    ${v.rates.rows ? g3(v.rates, false) : ''}</table></div>
    <p class="muted" style="margin-top:8px">${esc(v.rates.note)}</p>
    <ul style="font-size:12.5px;color:var(--tx2);padding-left:18px;margin:10px 0 0">
    ${v.rates.conclusions.map(c => `<li>${esc(c)}</li>`).join('')}</ul></div>` : '';

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

  const legacy = v.fx.legacy_note
    ? `<p class="muted" style="margin-top:8px">${esc(v.fx.legacy_note)}</p>` : '';
  const fxr = T(v.fx.title, (v.fx.summary || '') + ' ' + (v.fx.legacy_note || ''),
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

  const cnf = v.fx.confidence ? `<div class="card"><h2>${esc(v.fx.confidence.title)}</h2>
    <p class="muted" style="margin-bottom:10px">${esc(v.fx.confidence.note)}</p>
    <div class="scroll-x"><table class="tbl">
    <tr><th>確信度</th><th>勝率(平均)</th><th>1日</th><th>件数</th><th>t値</th><th>並びをずらすと</th></tr>
    ${v.fx.confidence.rows.map(r => `<tr><td>${(r.conf * 100).toFixed(0)}%以上${
      r.adopted ? ' <span class="pill ok">既定</span>' : ''}</td>
      <td class="num ${r.reliable === false ? 'down' : (r.hit >= 0.56 ? 'up' : '')}">${(r.hit * 100).toFixed(1)}%</td>
      <td class="num">${r.per_day.toFixed(2)}回</td>
      <td class="num">${r.n}件</td>
      <td class="num ${r.t < 2 ? 'down' : ''}">${num(r.t, 2)}</td>
      <td class="num muted">${r.by_offset.map(w => (w * 100).toFixed(1)).join(' / ')}
        <span class="${r.spread >= 0.06 ? 'down' : ''}">±${(r.spread * 100).toFixed(1)}pt</span></td></tr>`).join('')}
    </table></div>
    <p class="muted" style="margin-top:8px">${esc(v.fx.confidence.conclusion)}</p></div>` : '';

  const tim = v.fx.timing ? T(v.fx.timing.title, v.fx.timing.summary + ' ' + v.fx.timing.note,
    '<th>区分</th><th>400時点</th><th>360時点</th><th>440時点</th>',
    v.fx.timing.rows.map(r => `<tr><td>${esc(r.name)}</td>
      <td class="num">${(r.w400 * 100).toFixed(1)}%</td>
      <td class="num">${(r.w360 * 100).toFixed(1)}%</td>
      <td class="num">${(r.w440 * 100).toFixed(1)}%</td></tr>`).join('')) : '';

  const tv = v.tradingview ? `<div class="card"><h2>${esc(v.tradingview.title)}</h2>
    <p style="font-size:13px;margin:0 0 8px">${esc(v.tradingview.summary)}</p>
    <p class="muted">${esc(v.tradingview.note)}</p></div>` : '';

  const ind = v.fx.indicators ? `<div class="card"><h2>${esc(v.fx.indicators.title)}</h2>
    <p class="muted" style="margin-bottom:10px">${esc(v.fx.indicators.note)}</p>
    <div class="scroll-x"><table class="tbl">
    <tr><th>区分</th><th>勝率(平均)</th><th>並び0/1/2</th><th>件数</th></tr>
    ${v.fx.indicators.rows.map(r => `<tr><td>${esc(r.name)}</td>
      <td class="num ${r.hit >= 0.57 ? 'up' : r.hit < 0.55 ? 'down' : ''}">${(r.hit * 100).toFixed(1)}%</td>
      <td class="num muted">${r.by_offset.map(w => (w * 100).toFixed(1)).join(' / ')}%</td>
      <td class="num">${r.n}件</td></tr>`).join('')}
    </table></div>
    <p class="muted" style="margin-top:8px">${esc(v.fx.indicators.conclusion)}</p></div>` : '';

  const costTbl = v.costs ? T(v.costs.title, v.costs.note,
    '<th>区分</th><th>片道</th><th>往復</th><th>うち為替</th>',
    v.costs.rows.map(r => `<tr><td>${esc(r.kind)}</td>
      <td class="num">${pct(r.one_way, 2)}</td>
      <td class="num warn">${pct(r.round_trip, 2)}</td>
      <td class="num">${r.fx ? pct(r.fx, 3) : '—'}</td></tr>`).join('')) : '';

  const cav = v.caveats.map(c => `<li style="margin-bottom:5px">${esc(c)}</li>`).join('');

  return monitorCard(d) + live + prog + cmp + costCard + `
  <div class="banner"><strong>事前検証の結論</strong>
    株の順位付け: <b class="down">優位性を確認できず</b>／FX: <b class="up">統計的に有意</b>。
    ${esc(v.period)}。予測期間は株${esc(v.horizons ? v.horizons.long : '')}／FX${esc(v.horizons ? v.horizons.fx : '')}。
    ${v.costs ? esc(v.costs.summary) : ''}</div>
  ${costTbl}${reg}${regWin}${rules}${caps}${split}${fxr}${psel}${psplit}${gridCard}${cnf}${rateCard}${tim}${ind}${rej}${tv}
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
  // スワップの入力。FXタブにあるので、ここで拾う。
  // 再描画すると開いていた欄が閉じてしまうので、値の保存だけ行い描画し直す。
  document.querySelectorAll('.sw-in').forEach(inp =>
    inp.addEventListener('change', () => {
      const st = settings();
      st.swap = st.swap || {};
      const k = inp.dataset.sw;
      st.swap[k] = st.swap[k] || {};
      const v = String(inp.value).trim();
      st.swap[k][inp.dataset.side] = v === '' ? null : Number(v);
      saveSettings(st);
      SWAP_OPEN = true;      // 設定欄は開いたままにする
      render();
    }));

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

  document.querySelectorAll('[data-htab]').forEach(b =>
    b.addEventListener('click', () => { HOLD_TAB = b.dataset.htab; render(); }));

  const fadd = $('#fp-add');
  if (fadd) fadd.addEventListener('click', () => {
    const key = $('#fp-pair').value;
    const sig = ((DATA.fx && DATA.fx.signals) || []).find(x => x.key === key);
    const entry = parseFloat($('#fp-entry').value);
    const qty = parseFloat($('#fp-qty').value);
    if (!key || !(entry > 0) || !(qty > 0)) return;
    const num2 = el => { const v = parseFloat(el.value); return v > 0 ? v : null; };
    const st = settings();
    st.fxPositions = (st.fxPositions || []).concat([{
      key, name: sig ? sig.name : key, side: $('#fp-side').value,
      entry, qty, stop: num2($('#fp-stop')), target: num2($('#fp-target')),
      opened: new Date().toISOString().slice(0, 10),
    }]);
    saveSettings(st);
    render();
  });
  document.querySelectorAll('[data-fpdel]').forEach(b =>
    b.addEventListener('click', () => {
      const st = settings();
      (st.fxPositions || []).splice(+b.dataset.fpdel, 1);
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

/* ---------- 版の確認 ----------
   iPhoneのホーム画面から使うとページが長時間そのまま残るため、
   更新しても古い画面を見続けることがある。復帰したときに版を確かめ、
   変わっていればキャッシュを捨てて読み直す。 */
const APP_VERSION = (() => {
  const el = document.querySelector('script[src*="app.js"]');
  const m = el && String(el.src).match(/[?&]v=(\d+)/);
  return m ? m[1] : null;
})();

async function checkVersion() {
  if (!APP_VERSION) return;
  if (sessionStorage.getItem('mr-reloaded') === APP_VERSION) return;
  try {
    const r = await fetch('version.json?cb=' + Date.now(), { cache: 'no-store' });
    if (!r.ok) return;
    const v = String((await r.json()).version || '');
    if (!v || v === APP_VERSION) return;
    // 読み直しの繰り返しを防ぐため、一度試したことを覚えておく
    sessionStorage.setItem('mr-reloaded', APP_VERSION);
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k.indexOf('mr-shell') === 0).map(k => caches.delete(k)));
    if (navigator.serviceWorker) {
      const regs = await navigator.serviceWorker.getRegistrations();
      await Promise.all(regs.map(x => x.update().catch(() => { })));
    }
    location.reload();
  } catch (e) { /* 通信できないときは何もしない */ }
}

document.addEventListener('visibilitychange', () => {
  if (!document.hidden) checkVersion();
});

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('sw.js').catch(() => { });
    checkVersion();
  });
}
