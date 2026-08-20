# -*- coding: utf-8 -*-
"""テクニカル指標。外部ライブラリ不使用（標準ライブラリのみ）。

各関数は入力と同じ長さのリストを返し、計算不能な期間には None を入れる。
"""
import math
from collections import deque


def rolling_max(xs, n):
    """幅 n の移動窓の最大値。窓が埋まる前は利用可能な範囲で計算。O(n)。"""
    out, dq = [None] * len(xs), deque()
    for i, v in enumerate(xs):
        while dq and xs[dq[-1]] <= v:
            dq.pop()
        dq.append(i)
        if dq[0] <= i - n:
            dq.popleft()
        out[i] = xs[dq[0]]
    return out


def rolling_min(xs, n):
    out, dq = [None] * len(xs), deque()
    for i, v in enumerate(xs):
        while dq and xs[dq[-1]] >= v:
            dq.pop()
        dq.append(i)
        if dq[0] <= i - n:
            dq.popleft()
        out[i] = xs[dq[0]]
    return out


def sma(xs, n):
    out, s = [None] * len(xs), 0.0
    for i, v in enumerate(xs):
        s += v
        if i >= n:
            s -= xs[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(xs, n):
    out = [None] * len(xs)
    if len(xs) < n:
        return out
    k = 2.0 / (n + 1)
    prev = sum(xs[:n]) / n
    out[n - 1] = prev
    for i in range(n, len(xs)):
        prev = xs[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def _wilder(xs, n):
    """Wilder平滑（RSI/ATR/ADX用）。xs は None を含まない実数列。"""
    out = [None] * len(xs)
    if len(xs) < n:
        return out
    prev = sum(xs[:n]) / n
    out[n - 1] = prev
    for i in range(n, len(xs)):
        prev = (prev * (n - 1) + xs[i]) / n
        out[i] = prev
    return out


def rsi(closes, n=14):
    out = [None] * len(closes)
    if len(closes) < n + 1:
        return out
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag = _wilder(gains, n)
    al = _wilder(losses, n)
    for i in range(len(ag)):
        if ag[i] is None:
            continue
        loss = al[i]
        out[i + 1] = 100.0 if loss == 0 else 100.0 - 100.0 / (1 + ag[i] / loss)
    return out


def macd(closes, fast=12, slow=26, signal=9):
    ef, es = ema(closes, fast), ema(closes, slow)
    line = [None if (ef[i] is None or es[i] is None) else ef[i] - es[i]
            for i in range(len(closes))]
    vals = [v for v in line if v is not None]
    sig_vals = ema(vals, signal)
    off = len(line) - len(vals)
    sig = [None] * len(line)
    for i, v in enumerate(sig_vals):
        sig[i + off] = v
    hist = [None if (line[i] is None or sig[i] is None) else line[i] - sig[i]
            for i in range(len(line))]
    return line, sig, hist


def true_range(highs, lows, closes):
    tr = [None] * len(closes)
    for i in range(1, len(closes)):
        tr[i] = max(highs[i] - lows[i],
                    abs(highs[i] - closes[i - 1]),
                    abs(lows[i] - closes[i - 1]))
    return tr


def atr(highs, lows, closes, n=14):
    tr = true_range(highs, lows, closes)
    vals = [v for v in tr if v is not None]
    sm = _wilder(vals, n)
    out = [None] * len(closes)
    off = len(closes) - len(vals)
    for i, v in enumerate(sm):
        out[i + off] = v
    return out


def bollinger(closes, n=20, k=2.0):
    """中心線, %B, バンド幅 を返す。%B は下限0・上限1に対する位置。"""
    mid = sma(closes, n)
    pctb, width = [None] * len(closes), [None] * len(closes)
    s = s2 = 0.0
    for i, v in enumerate(closes):
        s += v
        s2 += v * v
        if i >= n:
            s -= closes[i - n]
            s2 -= closes[i - n] ** 2
        if i < n - 1:
            continue
        m = s / n
        var = max(0.0, s2 / n - m * m)
        sd = math.sqrt(var)
        if sd == 0:
            continue
        up, lo = m + k * sd, m - k * sd
        pctb[i] = (closes[i] - lo) / (up - lo)
        width[i] = (up - lo) / m
    return mid, pctb, width


def adx(highs, lows, closes, n=14):
    """トレンドの強さ。25超で明確なトレンド。方向は示さない。"""
    out = [None] * len(closes)
    if len(closes) < 2 * n + 2:
        return out
    plus_dm, minus_dm = [], []
    for i in range(1, len(closes)):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        plus_dm.append(up if (up > dn and up > 0) else 0.0)
        minus_dm.append(dn if (dn > up and dn > 0) else 0.0)
    tr = [v for v in true_range(highs, lows, closes) if v is not None]
    atr_s, p_s, m_s = _wilder(tr, n), _wilder(plus_dm, n), _wilder(minus_dm, n)
    dx = []
    for i in range(len(atr_s)):
        if atr_s[i] is None or atr_s[i] == 0:
            dx.append(None)
            continue
        pdi = 100 * p_s[i] / atr_s[i]
        mdi = 100 * m_s[i] / atr_s[i]
        dx.append(0.0 if (pdi + mdi) == 0 else 100 * abs(pdi - mdi) / (pdi + mdi))
    valid = [v for v in dx if v is not None]
    adx_s = _wilder(valid, n)
    off = len(closes) - len(valid)
    for i, v in enumerate(adx_s):
        out[i + off] = v
    return out


def stochastic(highs, lows, closes, n=14, d=3):
    hh = rolling_max(highs, n)
    ll = rolling_min(lows, n)
    k = [None] * len(closes)
    for i in range(n - 1, len(closes)):
        rng = hh[i] - ll[i]
        k[i] = 50.0 if rng == 0 else 100 * (closes[i] - ll[i]) / rng
    vals = [v for v in k if v is not None]
    ds = sma(vals, d)
    dd = [None] * len(closes)
    off = len(closes) - len(vals)
    for i, v in enumerate(ds):
        dd[i + off] = v
    return k, dd


def obv(closes, volumes):
    out = [0.0] * len(closes)
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            out[i] = out[i - 1] + volumes[i]
        elif closes[i] < closes[i - 1]:
            out[i] = out[i - 1] - volumes[i]
        else:
            out[i] = out[i - 1]
    return out


def roc(closes, n):
    out = [None] * len(closes)
    for i in range(n, len(closes)):
        if closes[i - n]:
            out[i] = closes[i] / closes[i - n] - 1
    return out


def realized_vol(closes, n=20):
    """年率換算ボラティリティ"""
    out = [None] * len(closes)
    rets = []
    for i in range(1, len(closes)):
        rets.append(closes[i] / closes[i - 1] - 1 if closes[i - 1] else 0.0)
    s = s2 = 0.0
    for j, r in enumerate(rets):
        s += r
        s2 += r * r
        if j >= n:
            s -= rets[j - n]
            s2 -= rets[j - n] ** 2
        if j < n - 1:
            continue
        m = s / n
        var = max(0.0, (s2 - n * m * m) / (n - 1))
        out[j + 1] = math.sqrt(var) * math.sqrt(252)
    return out


def dist_from_high(closes, n=252):
    """52週高値からの乖離。0 は高値更新中、-0.2 は高値から20パーセント下。"""
    out = [None] * len(closes)
    hh = rolling_max(closes, n)
    for i in range(len(closes)):
        if i < 59 or not hh[i]:
            continue
        out[i] = closes[i] / hh[i] - 1
    return out


def zscore(xs, n=20):
    out = [None] * len(xs)
    s = s2 = 0.0
    for i, v in enumerate(xs):
        v = v or 0.0
        s += v
        s2 += v * v
        if i >= n:
            p = xs[i - n] or 0.0
            s -= p
            s2 -= p * p
        if i < n - 1 or xs[i] is None:
            continue
        m = s / n
        var = max(0.0, (s2 - n * m * m) / (n - 1))
        sd = math.sqrt(var)
        if sd:
            out[i] = (xs[i] - m) / sd
    return out


def compute_all(bars):
    """OHLCV から全指標を計算し dict of list で返す。

    bars: t, o, h, l, c, v をキーに持つ dict
    """
    c, h, l, v = bars["c"], bars["h"], bars["l"], bars["v"]
    macd_line, macd_sig, macd_hist = macd(c)
    bb_mid, bb_pctb, bb_width = bollinger(c)
    stoch_k, stoch_d = stochastic(h, l, c)
    ob = obv(c, v)
    vol_sma = sma(v, 20)
    vol_ratio = [None] * len(v)
    for i in range(len(v)):
        if vol_sma[i]:
            vol_ratio[i] = v[i] / vol_sma[i]
    return {
        "sma10": sma(c, 10), "sma20": sma(c, 20),
        "sma50": sma(c, 50), "sma200": sma(c, 200),
        "ema20": ema(c, 20),
        "rsi14": rsi(c, 14),
        "macd": macd_line, "macd_signal": macd_sig, "macd_hist": macd_hist,
        "bb_mid": bb_mid, "bb_pctb": bb_pctb, "bb_width": bb_width,
        "atr14": atr(h, l, c, 14),
        "adx14": adx(h, l, c, 14),
        "stoch_k": stoch_k, "stoch_d": stoch_d,
        "obv": ob, "obv_z": zscore(ob, 20),
        "roc5": roc(c, 5), "roc20": roc(c, 20), "roc60": roc(c, 60),
        "vol20": realized_vol(c, 20),
        "dist_high": dist_from_high(c, 252),
        "vol_ratio": vol_ratio,
    }
