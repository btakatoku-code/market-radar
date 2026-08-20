# -*- coding: utf-8 -*-
"""リスクの見える化と、銘柄選定の分散。

年率ボラだけでは「どれくらい落ちうるか」が分からない。上下対称でない
下落局面の痛みを示すために、最大下落率・下方偏差・下位5%の想定を出す。

また、スコア順に上位5件を並べると同じ業種で埋まることがある（実際に
海運3社が並んだ）。5銘柄に見えて実質1つの賭けになるので、
値動きの相関を見て重複を避ける。
"""
import math

CORR_WINDOW = 120        # 相関を測る期間（営業日）
CORR_LIMIT = 0.75        # これを超える相関の銘柄は同じ賭けとみなす


def returns(bars, n=CORR_WINDOW):
    c = bars["c"][-(n + 1):]
    out = []
    for i in range(1, len(c)):
        if c[i - 1]:
            out.append(c[i] / c[i - 1] - 1)
    return out


def correlation(a, b):
    """2本のリターン列の相関係数。長さが違う場合は短い方に揃える。"""
    n = min(len(a), len(b))
    if n < 30:
        return 0.0
    a, b = a[-n:], b[-n:]
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((x - mb) ** 2 for x in b)
    if va <= 0 or vb <= 0:
        return 0.0
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    return cov / math.sqrt(va * vb)


def max_drawdown(bars, n=252):
    """期間中の高値からの最大下落率（負の値）"""
    c = bars["c"][-n:]
    if len(c) < 20:
        return None
    peak, worst = c[0], 0.0
    for x in c:
        if x > peak:
            peak = x
        if peak:
            worst = min(worst, x / peak - 1)
    return worst


def downside_deviation(bars, n=252):
    """下落した日だけで測ったばらつき（年率）。上昇の大きさは含めない。"""
    r = returns(bars, n)
    neg = [x for x in r if x < 0]
    if len(neg) < 10:
        return None
    return math.sqrt(sum(x * x for x in neg) / len(r)) * math.sqrt(252)


def worst_period(bars, horizon, n=756):
    """過去 n 営業日で、horizon 営業日保有したときの最悪の結果"""
    c = bars["c"][-n:]
    if len(c) < horizon + 20:
        return None
    worst = 0.0
    for i in range(len(c) - horizon):
        if c[i]:
            worst = min(worst, c[i + horizon] / c[i] - 1)
    return worst


def value_at_risk(fc, level=0.05):
    """予測分布の下位5%。だいたいこれくらいまでは覚悟しておく水準。

    プールは平均と標準偏差で保持しているため、正規分布で近似する。
    """
    if not fc or fc.get("expected_z") is None:
        return None
    lo, hi = fc.get("low"), fc.get("high")
    if lo is None or hi is None or hi <= lo:
        return None
    # 四分位（±0.6745σ）から標準偏差を戻す
    sd = (hi - lo) / (2 * 0.6745)
    z = -1.6449 if level == 0.05 else -2.3263
    return fc["expected_return"] + z * sd


def profile(bars, fc, horizon):
    """1銘柄の下方リスクをまとめる"""
    return {
        "max_drawdown_1y": max_drawdown(bars, 252),
        "max_drawdown_3y": max_drawdown(bars, 756),
        "downside_dev": downside_deviation(bars, 252),
        "worst_hold": worst_period(bars, horizon, 756),
        "var5": value_at_risk(fc, 0.05),
    }


def diversify(candidates, limit, corr_limit=CORR_LIMIT, key=lambda x: x):
    """スコア順の候補から、値動きが重複しないように選ぶ。

    candidates: スコアの高い順に並んだリスト
    key(x) -> asset（bars を持つ dict）
    戻り値: (選ばれたリスト, 除外された [(候補, 相関相手, 相関値)])
    """
    picked, picked_rets, skipped = [], [], []
    for cand in candidates:
        if len(picked) >= limit:
            break
        a = key(cand)
        r = returns(a["bars"])
        worst_corr, worst_with = 0.0, None
        for i, pr in enumerate(picked_rets):
            c = abs(correlation(r, pr))
            if c > worst_corr:
                worst_corr, worst_with = c, key(picked[i])
        if worst_corr >= corr_limit and worst_with is not None:
            skipped.append((cand, worst_with, worst_corr))
            continue
        picked.append(cand)
        picked_rets.append(r)
    # 分散を優先した結果、件数が足りない場合は相関の低い順に補充する
    if len(picked) < limit and skipped:
        skipped.sort(key=lambda s: s[2])
        for cand, _, _ in skipped:
            if len(picked) >= limit:
                break
            if cand in picked:
                continue
            picked.append(cand)
    return picked, skipped


def portfolio_correlation(assets):
    """選ばれた銘柄同士の相関の平均と最大。1に近いほど「実質1銘柄」。"""
    rets = [returns(a["bars"]) for a in assets]
    pairs = []
    for i in range(len(rets)):
        for j in range(i + 1, len(rets)):
            pairs.append(abs(correlation(rets[i], rets[j])))
    if not pairs:
        return None
    return {"mean": sum(pairs) / len(pairs), "max": max(pairs), "pairs": len(pairs)}


def concentration_warning(items, assets):
    """分散が効いているかを判定する。

    業種データは無料で取れないため、値動きの相関で代用する。
    資産の種類（米国株・日本株など）の内訳は参考情報として返すだけで、
    それ自体は警告にしない。同じ種類でも値動きが違えば分散は効いている。
    """
    pc = portfolio_correlation(assets)
    if not pc:
        return None
    msgs = []
    if pc["mean"] >= 0.6:
        msgs.append("選ばれた銘柄の値動きが似ています（平均相関 {:.2f}）。"
                    "分散したつもりでも実質1つの賭けに近い状態です。".format(pc["mean"]))
    elif pc["max"] >= CORR_LIMIT:
        msgs.append("一部の銘柄の値動きが強く連動しています（最大相関 {:.2f}）。".format(pc["max"]))
    kinds = {}
    for it in items:
        kinds[it["kind_label"]] = kinds.get(it["kind_label"], 0) + 1
    return {"mean": pc["mean"], "max": pc["max"], "pairs": pc["pairs"],
            "composition": sorted(kinds.items(), key=lambda kv: -kv[1]),
            "messages": msgs, "ok": not msgs}


def position_size(capital, risk_pct, entry, stop):
    """損切りまでの距離から建玉サイズを求める（株用）"""
    if not entry or not stop or entry <= stop:
        return None
    risk_amount = capital * risk_pct
    per_share = entry - stop
    shares = risk_amount / per_share
    return {
        "risk_amount": risk_amount,
        "stop_distance_pct": per_share / entry,
        "shares": shares,
        "position_value": shares * entry,
        "position_pct": (shares * entry) / capital if capital else None,
    }
