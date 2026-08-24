# -*- coding: utf-8 -*-
"""FXポジション全体のリスク診断。

主要5ペアのうち4つは円クロスで、値動きが揃う。実測（直近120営業日）では
ユーロ/円とポンド/円の相関は +0.86、円クロス4本の平均相関は +0.59。

各シグナルを独立に2%リスクで建てると、名目では8%でも、値動きが揃うぶん
実際には1つの大きな賭けに近づく。ここではその度合いを数字にして、
合計リスクから逆算した1本あたりの適正リスクを出す。

「何本建てるか」ではなく「合計でいくら失う覚悟か」から考えるのが、
ポジション管理の基本的な順序。
"""
import math

import risk

# ペアを構成する通貨（買うと前者を買い、後者を売ることになる）
PAIR_LEGS = {
    "USDJPY=X": ("USD", "JPY"), "EURJPY=X": ("EUR", "JPY"),
    "GBPJPY=X": ("GBP", "JPY"), "AUDJPY=X": ("AUD", "JPY"),
    "NZDJPY=X": ("NZD", "JPY"), "CADJPY=X": ("CAD", "JPY"),
    "CHFJPY=X": ("CHF", "JPY"), "EURUSD=X": ("EUR", "USD"),
    "GBPUSD=X": ("GBP", "USD"), "AUDUSD=X": ("AUD", "USD"),
    "NZDUSD=X": ("NZD", "USD"), "USDCAD=X": ("USD", "CAD"),
    "USDCHF=X": ("USD", "CHF"), "EURGBP=X": ("EUR", "GBP"),
    "EURCHF=X": ("EUR", "CHF"),
}
CURRENCY_NAMES = {"USD": "米ドル", "JPY": "円", "EUR": "ユーロ", "GBP": "ポンド",
                  "AUD": "豪ドル", "NZD": "NZドル", "CAD": "カナダドル",
                  "CHF": "スイスフラン"}

CORR_WINDOW = 120
HIGH_CORR = 0.70          # これを超えたら実質同じ取引として警告する


def correlations(fx_assets, pairs):
    """ペア同士の日次変化率の相関を測る。"""
    by = {a["key"]: a for a in fx_assets}
    rets = {p: risk.returns(by[p]["bars"], CORR_WINDOW) for p in pairs if p in by}
    out = {}
    for a in rets:
        for b in rets:
            if a < b:
                out[(a, b)] = risk.correlation(rets[a], rets[b])
    return out


def _corr(corrs, a, b):
    if a == b:
        return 1.0
    return corrs.get((a, b), corrs.get((b, a), 0.0))


def mean_correlation(corrs, positions):
    """向きを踏まえた平均相関。逆向きに建てていれば符号が反転する。"""
    if len(positions) < 2:
        return 0.0
    vals = []
    for i, p in enumerate(positions):
        for q in positions[i + 1:]:
            c = _corr(corrs, p["key"], q["key"])
            vals.append(c * p["sign"] * q["sign"])
    return sum(vals) / len(vals) if vals else 0.0


def effective_bets(n, mean_corr):
    """実質いくつの独立した賭けになっているか。

    n本を等しく建てたときの分散は n(1+(n-1)ρ)。相関が0なら n、
    相関が1なら n^2 になる。有効数 = n^2 / (分散比) = n / (1+(n-1)ρ)。
    """
    if n <= 1:
        return float(n)
    denom = 1.0 + (n - 1) * mean_corr
    if denom <= 0:
        return float(n)
    # 逆相関で「n本より分散している」と出ることがあるが、それを前提に
    # ポジションを増やすのは危険。相関は市場が荒れると1に近づく。
    return min(n / denom, float(n))


def risk_multiplier(n, mean_corr):
    """1本あたりのリスクに対して、合計リスクが何倍になるか。"""
    if n <= 0:
        return 0.0
    v = n * (1.0 + (n - 1) * mean_corr)
    return math.sqrt(max(v, 0.0))


def currency_exposure(positions):
    """通貨ごとの正味の持ち高。買えば前者を買い、後者を売ることになる。

    重みは各ポジションのリスク額。合計が見やすいよう割合に直す。
    """
    net = {}
    for p in positions:
        base, quote = PAIR_LEGS.get(p["key"], (None, None))
        if not base:
            continue
        w = p.get("weight", 1.0) * p["sign"]
        net[base] = net.get(base, 0.0) + w
        net[quote] = net.get(quote, 0.0) - w
    total = sum(abs(v) for v in net.values()) or 1.0
    return sorted(
        ({"currency": c, "name": CURRENCY_NAMES.get(c, c), "net": v,
          "share": abs(v) / total,
          "side": "買い越し" if v > 0 else "売り越し" if v < 0 else "中立"}
         for c, v in net.items() if abs(v) > 1e-9),
        key=lambda x: -abs(x["net"]))


def diagnose(signals, fx_assets, capital, risk_per_trade, total_risk_budget=None):
    """建てようとしているポジション全体を診断する。

    signals: tradeable なシグナル（key, direction を持つ）
    """
    positions = [{"key": s["key"], "name": s["name"],
                  "sign": 1 if s["direction"] == "買い" else -1,
                  "weight": 1.0}
                 for s in signals]
    n = len(positions)
    pairs = [p["key"] for p in positions]
    corrs = correlations(fx_assets, pairs) if n >= 2 else {}
    mc = mean_correlation(corrs, positions)
    eff = effective_bets(n, mc)
    mult = risk_multiplier(n, mc)

    # 全部が損切りに掛かった場合の損失。相関が高いほど、これが同時に
    # 起きやすくなる。合計リスクとして見るべきはこの数字。
    worst_total = risk_per_trade * n

    # 値動きの揃い具合。独立なら合計の振れは sqrt(n) 倍で済むが、
    # 相関があるとそれより大きくなる。比が1.0に近いほど分散していない。
    indep_mult = math.sqrt(n) if n > 0 else 0.0
    diversification = (indep_mult / mult) if mult > 0 else 1.0

    budget = total_risk_budget if total_risk_budget is not None else risk_per_trade * 2

    # 1本あたりの適正リスクは2通りの考え方があるので、両方出して厳しい方を採る。
    #   (1) 合計の値動きの振れを想定内に収める      … budget / 相関を踏まえた倍率
    #   (2) 全部が損切りに掛かっても想定内に収める  … budget / 本数
    # 損切りを置く以上 (2) は実際に起こりうるので、こちらを無視できない。
    by_vol = (budget / mult) if mult > 0 else risk_per_trade
    by_worst = (budget / n) if n > 0 else risk_per_trade
    # 現在の設定より大きな数字は出さない。逆相関を根拠にリスクを増やすのは、
    # 相場が荒れて相関が1に近づいたときに効かない前提に賭けること。
    suggested = min(by_vol, by_worst, risk_per_trade)
    suggested_worst = suggested * n
    reduce_needed = suggested < risk_per_trade * 0.95
    offsetting = mc < -0.2 and n >= 2

    # 相関の高い組み合わせを名指しする
    hot = []
    for i, p in enumerate(positions):
        for q in positions[i + 1:]:
            c = _corr(corrs, p["key"], q["key"]) * p["sign"] * q["sign"]
            if abs(c) >= HIGH_CORR:
                hot.append({"a": p["name"], "b": q["name"], "corr": round(c, 2),
                            "same": c > 0})
    hot.sort(key=lambda x: -abs(x["corr"]))

    warnings = []
    if n >= 2 and eff < n * 0.6:
        warnings.append(
            "{}本のうち、実質{:.1f}本ぶんの賭けにしかなっていません。"
            "値動きが揃うため、分散したつもりで同じ方向に賭けている状態です。"
            .format(n, eff))
    if mc < -0.2 and n >= 2:
        warnings.append(
            "いまは値動きが逆向き（平均相関{:+.2f}）で打ち消し合っていますが、"
            "相場が荒れると相関は1に近づきます。これを前提にポジションを"
            "増やさないでください。".format(mc))
    for h in hot[:3]:
        warnings.append(
            "{}と{}は相関{:+.2f}で、ほぼ同じ取引です。{}"
            .format(h["a"], h["b"], h["corr"],
                    "片方に絞ることを検討してください。" if h["same"]
                    else "互いに打ち消し合っています。"))
    if worst_total > budget * 1.2:
        if reduce_needed:
            warnings.append(
                "全部が損切りに掛かると資金の{:.1%}を失います。1本あたりを{:.1%}"
                "（{}本で合計{:.1%}）に下げるか、本数を減らしてください。"
                .format(worst_total, suggested, n, suggested_worst))
        else:
            warnings.append(
                "全部が損切りに掛かると資金の{:.1%}を失います。想定していた"
                "{:.1%}を超えるので、本数を減らすか、1回のリスク設定を"
                "見直してください。".format(worst_total, budget))

    return {
        "count": n,
        "mean_corr": round(mc, 3),
        "effective_bets": round(eff, 2),
        "risk_multiplier": round(mult, 2),
        "worst_total_risk": round(worst_total, 4),
        "worst_total_yen": round(capital * worst_total),
        "independent_multiplier": round(indep_mult, 2),
        "diversification": round(diversification, 2),
        "risk_budget": round(budget, 4),
        "suggested_per_trade": round(suggested, 4),
        "suggested_worst_risk": round(suggested_worst, 4),
        "suggested_worst_yen": round(capital * suggested_worst),
        "suggested_by_vol": round(min(by_vol, risk_per_trade), 4),
        "suggested_by_worst": round(min(by_worst, risk_per_trade), 4),
        "reduce_needed": reduce_needed,
        "offsetting": offsetting,
        "risk_per_trade": risk_per_trade,
        "exposure": currency_exposure(positions),
        "high_corr_pairs": hot,
        "warnings": warnings,
        "matrix": [{"a": a, "b": b, "corr": round(c, 2)}
                   for (a, b), c in sorted(corrs.items())],
    }
