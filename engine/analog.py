# -*- coding: utf-8 -*-
"""類似局面法による期待リターンの推定。

「今と似た状態が過去に起きたとき、その後 H 日でどうなったか」を実データから
集計する。数字を仮定で作らず、過去の分布からそのまま出すのが狙い。

2つの推定を標準誤差の逆数の2乗で加重合成する:
  1. プール推定  … 全銘柄の履歴を粗い特徴シグネチャでバケット化（標本大）
  2. 個別kNN推定 … その銘柄自身の履歴から最近傍を抽出（標本小・銘柄固有）

前方リターンは各時点のボラティリティで正規化してから集計するため、
値動きの大きさが違う銘柄同士を同じ土俵で比較できる。

プール側は逐次更新できる形（件数・和・二乗和・正の件数）で統計を保持する。
中央値ではなく平均を使うが、前方リターンは事前に±5シグマで頭打ちにしてあるため
極端値の影響は抑えられている。
"""
import math

CLIP = 3.0
FWD_CLIP = 5.0
FEATURE_NAMES = ["rsi", "bb", "macd", "roc20", "roc60",
                 "adx", "stoch", "disthigh", "trend", "volratio"]
# バケット化に使う特徴（粗いシグネチャ用）
SIG_FEATURES = ["rsi", "bb", "roc20", "trend", "adx"]
SIG_EDGES = (-0.5, 0.5)          # 3分割の境界
KNN_WEIGHTS = [1.0, 1.0, 0.8, 1.2, 0.8, 0.6, 0.6, 0.8, 1.2, 0.4]
SIG_IDX = [FEATURE_NAMES.index(n) for n in SIG_FEATURES]


def _clip(x, lo=-CLIP, hi=CLIP):
    return lo if x < lo else (hi if x > hi else x)


def feature_matrix(bars, ind):
    """各バーの特徴ベクトル（無次元）を返す。計算不能な位置は None。"""
    c = bars["c"]
    n = len(c)
    out = [None] * n
    rsi_a, bb_a, mh_a, atr_a = ind["rsi14"], ind["bb_pctb"], ind["macd_hist"], ind["atr14"]
    r20_a, r60_a, adx_a = ind["roc20"], ind["roc60"], ind["adx14"]
    st_a, dh_a, s50_a, vol_a = ind["stoch_k"], ind["dist_high"], ind["sma50"], ind["vol20"]
    vr_a = ind["vol_ratio"]
    sqrt20, sqrt50, sqrt60 = math.sqrt(20), math.sqrt(50), math.sqrt(60)
    for i in range(n):
        rsi, bb, mh, atr = rsi_a[i], bb_a[i], mh_a[i], atr_a[i]
        r20, r60, adx = r20_a[i], r60_a[i], adx_a[i]
        st, dh, s50, vol = st_a[i], dh_a[i], s50_a[i], vol_a[i]
        vr = vr_a[i]
        if (rsi is None or bb is None or mh is None or atr is None or r20 is None
                or r60 is None or adx is None or st is None or s50 is None
                or vol is None or vol <= 0 or atr <= 0):
            continue
        dvol = vol / 15.874507866387544        # sqrt(252)
        out[i] = [
            _clip((rsi - 50) / 25.0),
            _clip((bb - 0.5) * 2.0),
            _clip(mh / atr),
            _clip(r20 / (dvol * sqrt20)),
            _clip(r60 / (dvol * sqrt60)),
            _clip((adx - 25) / 15.0),
            _clip((st - 50) / 25.0),
            _clip((dh if dh is not None else 0.0) * 4.0),
            _clip((c[i] / s50 - 1) / (dvol * sqrt50)),
            _clip(math.log(vr) if (vr and vr > 0) else 0.0),
        ]
    return out


def signature(f, regime=0):
    """特徴ベクトル → 粗い3値シグネチャ（バケットキー）

    regime を渡すと「市場の状態も同じだった局面」だけを同じバケットに集める。
    """
    lo, hi = SIG_EDGES
    key = tuple(0 if f[j] < lo else (2 if f[j] > hi else 1) for j in SIG_IDX)
    return key if regime == 0 else key + (regime,)


_signature = signature      # 後方互換


def normalized_forward(bars, ind, i, horizon):
    """i 時点から horizon 日後までの、ボラで正規化した前方リターン。"""
    c = bars["c"]
    j = i + horizon
    if j >= len(c) or not c[i]:
        return None
    vol = ind["vol20"][i]
    if not vol or vol <= 0:
        return None
    dvol = vol / 15.874507866387544
    raw = c[j] / c[i] - 1
    return _clip(raw / (dvol * math.sqrt(horizon)), -FWD_CLIP, FWD_CLIP)


class Pool:
    """バケット別の前方リターン統計。逐次追加できる。"""

    def __init__(self, horizon):
        self.horizon = horizon
        self.b = {}          # sig -> [件数, 和, 二乗和, 正の件数]

    def add(self, sig, fwd):
        e = self.b.get(sig)
        if e is None:
            self.b[sig] = [1, fwd, fwd * fwd, 1 if fwd > 0 else 0]
        else:
            e[0] += 1
            e[1] += fwd
            e[2] += fwd * fwd
            if fwd > 0:
                e[3] += 1

    def add_asset_range(self, feats, bars, ind, i0, i1, regime=None):
        """[i0, i1) の範囲のバーをプールに追加。追加した件数を返す。"""
        n = 0
        for i in range(i0, i1):
            f = feats[i]
            if f is None:
                continue
            fwd = normalized_forward(bars, ind, i, self.horizon)
            if fwd is None:
                continue
            self.add(signature(f, regime[i] if regime else 0), fwd)
            n += 1
        return n

    def stats(self, sig):
        e = self.b.get(sig)
        if e is None or e[0] < 2:
            return None
        n, s, s2, pos = e
        mean = s / n
        var = max(0.0, (s2 - n * mean * mean) / (n - 1))
        sd = math.sqrt(var)
        n_eff = max(1.0, n / float(self.horizon))
        return dict(median=mean, p_up=pos / n, q25=mean - 0.6745 * sd,
                    q75=mean + 0.6745 * sd, n=n, n_eff=n_eff, sd=sd)

    def size(self):
        return sum(e[0] for e in self.b.values())


def build_pool(assets, horizon):
    """全銘柄の全履歴からプールを作る（本番の予測用）。"""
    pool = Pool(horizon)
    for a in assets:
        bars = a["bars"]
        pool.add_asset_range(a["feats"], bars, a["ind"], 0, len(bars["c"]) - horizon,
                             a.get("regime"))
    return pool


def _stats(vals, horizon):
    """正規化リターン列 → 中央値・上昇確率・四分位などの統計（kNN用）"""
    n = len(vals)
    if n < 2:
        return None
    s = sorted(vals)

    def q(p):
        k = p * (n - 1)
        lo = int(math.floor(k))
        hi = int(math.ceil(k))
        return s[lo] if lo == hi else s[lo] + (s[hi] - s[lo]) * (k - lo)

    med = q(0.5)
    mean = sum(s) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in s) / (n - 1))
    p_up = sum(1 for x in s if x > 0) / n
    n_eff = max(1.0, n / float(horizon))
    return dict(median=med, p_up=p_up, q25=q(0.25), q75=q(0.75),
                n=n, n_eff=n_eff, sd=sd)


def knn(query, feats, bars, ind, horizon, k=60, max_lookback=1500, upto=None):
    """その銘柄自身の履歴から最近傍を抽出。upto を指定するとそこまでで打ち切る。"""
    limit = len(bars["c"]) - horizon if upto is None else min(len(bars["c"]) - horizon, upto)
    start = max(0, limit - max_lookback)
    cands = []
    w = KNN_WEIGHTS
    for i in range(start, limit):
        f = feats[i]
        if f is None:
            continue
        fwd = normalized_forward(bars, ind, i, horizon)
        if fwd is None:
            continue
        d = 0.0
        for j in range(10):
            diff = query[j] - f[j]
            d += w[j] * diff * diff
        cands.append((d, fwd))
    if len(cands) < 40:
        return None
    cands.sort(key=lambda x: x[0])
    kk = max(20, min(k, len(cands) // 4))
    return _stats([v for _, v in cands[:kk]], horizon)


def shrink(st):
    """標本誤差に対して信号が小さければ 0 に寄せる（過信の抑制）"""
    if st is None:
        return 0.0, 1.0
    se = 1.2533 * st["sd"] / math.sqrt(max(1.0, st["n_eff"]))
    m = abs(st["median"])
    if m + se == 0:
        return 0.0, max(se, 1e-6)
    return (m * m) / (m * m + se * se), max(se, 1e-6)


_shrink = shrink            # 後方互換


def combine(parts, scale, horizon):
    """[(統計, 縮小係数, 標準誤差)] を標準誤差で加重合成する。"""
    if not parts:
        return None
    ws = [1.0 / (p[2] ** 2) for p in parts]
    wsum = sum(ws)
    med = sum(p[0]["median"] * p[1] * w for p, w in zip(parts, ws)) / wsum
    p_up = sum(p[0]["p_up"] * w for p, w in zip(parts, ws)) / wsum
    q25 = sum(p[0]["q25"] * w for p, w in zip(parts, ws)) / wsum
    q75 = sum(p[0]["q75"] * w for p, w in zip(parts, ws)) / wsum
    return {
        "expected_return": med * scale,
        "expected_z": med,
        "prob_up": p_up,
        "low": q25 * scale,
        "high": q75 * scale,
        "n": sum(p[0]["n"] for p in parts),
        "n_eff": round(sum(p[0]["n_eff"] for p in parts), 1),
        "horizon": horizon,
        "shrink": round(sum(p[1] for p in parts) / len(parts), 3),
    }


def forecast(bars, ind, feats, pool, horizon, k=60, use_knn=True, idx=None,
             regime=None):
    """1銘柄の予測を返す。データ不足なら None。"""
    i = (len(bars["c"]) - 1) if idx is None else idx
    q = feats[i]
    if q is None:
        return None
    vol = ind["vol20"][i]
    if not vol or vol <= 0:
        return None
    dvol = vol / 15.874507866387544
    scale = dvol * math.sqrt(horizon)

    parts = []
    ps = pool.stats(signature(q, regime[i] if regime else 0))
    if ps and ps["n_eff"] >= 3:
        sh, se = shrink(ps)
        parts.append((ps, sh, se))
    if use_knn:
        ks = knn(q, feats, bars, ind, horizon, k, upto=(None if idx is None else idx))
        if ks and ks["n_eff"] >= 3:
            sh, se = shrink(ks)
            parts.append((ks, sh, se))
    out = combine(parts, scale, horizon)
    if out:
        out["daily_vol"] = dvol
    return out
