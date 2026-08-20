# -*- coding: utf-8 -*-
"""FX（短期）のシグナルと資金計画。

シグナルは長期枠と同じ類似局面法を1営業日先に適用して作る。
そのうえで、検証で実測した優位性をもとに
「今の資金でいくら狙えるか」「1日1万円には資金がいくら必要か」を逆算する。

利益を約束するものではない。実測値は過去5年の検証結果であり、
将来も同じ優位性が続く保証はない。
"""
import math

import analog
import config

# 検証で実測した優位性（tests/run_fx.py の結果）
# 「各日の予測変動が大きい上位5ペアに、予測方向でエントリーした場合」
# 市場レジーム（リスク許容度×市場の広がり／9段階）で類似局面を絞ったうえで、
# 確信度56%以上のシグナルだけを採用した場合の実測値。
MEASURED = {
    "hit_rate": 0.586,          # 方向的中率
    "edge_per_trade": 0.00121,  # 1回あたりの平均損益（想定元本比）
    "t_stat": 3.89,             # 日次集計のt値
    "days": 229,                # シグナルが出た日数（検証400日中）
    "signals": 326,
    "period": "2021-11 〜 2026-08",
    "regime": "risk_breadth9",
    "pairs": 5,
    "pool_pairs": 14,
    # 検証400日のうちシグナルが出たのは229日。出た日は平均1.4回。
    "signal_days": 229,
    "test_days": 400,
    "signals_per_day": 0.82,     # 全日平均（シグナルが出ない日も含む）
    "signals_per_active_day": 1.42,
}

# テクニカルの裏付けがあるシグナルの実測（14ペア・確信度56%以上での測定）
CONFIRMED = {
    "hit_rate": 0.591,          # MACDとトレンドが予測と同じ向き
    "edge_per_trade": 0.00113,
    "t_stat": 3.39,
    "n": 340,
}
UNCONFIRMED_HIT = 0.571         # 裏付けを問わない場合

# 主要通貨ペアの片道スプレッド目安（対価格比）。国内FX業者の標準的な水準。
SPREAD = {
    "USDJPY=X": 0.0000125, "EURJPY=X": 0.0000200, "GBPJPY=X": 0.0000550,
    "AUDJPY=X": 0.0000450, "NZDJPY=X": 0.0000700, "CADJPY=X": 0.0000600,
    "CHFJPY=X": 0.0000900, "EURUSD=X": 0.0000250, "GBPUSD=X": 0.0000600,
    "AUDUSD=X": 0.0000500, "NZDUSD=X": 0.0000900, "USDCHF=X": 0.0000700,
    "USDCAD=X": 0.0000700, "EURGBP=X": 0.0000700, "XAUUSD=X": 0.0003000,
}
DEFAULT_SPREAD = 0.00007
MAX_LEVERAGE = 25.0             # 国内FXの個人口座の上限


def confirmation(direction, comp):
    """予測方向にテクニカルの裏付けがあるかを調べる。

    実測では、MACDヒストグラムとトレンドの両方が予測と同じ向きのとき
    的中率が 57.1% → 59.1% に上がった。強制的に絞り込むと機会が3分の1に
    減るため、除外はせず「裏付けの強さ」として表示するだけにする。
    """
    up = direction > 0
    checks = [
        ("MACD", (comp["macd"] > 0) == up, "MACDヒストグラムが{}向き".format(
            "上" if up else "下")),
        ("トレンド", (comp["trend"] > 0) == up, "移動平均の並びが{}向き".format(
            "上昇" if up else "下降")),
        ("モメンタム", (comp["momentum"] > 0) == up, "勢いが{}向き".format(
            "上" if up else "下")),
        ("RSI", (comp["rsi"] > 50) == up, "RSIが50より{}".format(
            "上" if up else "下")),
    ]
    agree = [c for c in checks if c[1]]
    core = ((comp["macd"] > 0) == up) and ((comp["trend"] > 0) == up)
    if core:
        level, label = 2, "強い"
    elif len(agree) >= 2:
        level, label = 1, "普通"
    else:
        level, label = 0, "弱い"
    return {
        "level": level,
        "label": label,
        "agree": len(agree),
        "total": len(checks),
        "core": core,
        "items": [{"name": c[0], "ok": c[1], "text": c[2]} for c in checks],
        "hit_rate": CONFIRMED["hit_rate"] if core else UNCONFIRMED_HIT,
    }


def signals(fx_assets, pool, horizon=None, top_n=None, pairs=None):
    """各通貨ペアの予測を作り、確信度の高い順に並べる。

    プールは渡された全ペアで作るが、シグナルとして出すのは pairs のみ。
    """
    import scoring

    horizon = horizon or config.HORIZON_FX
    top_n = top_n or config.TOP_N
    allow = set(pairs if pairs is not None else config.FX_SIGNAL_PAIRS)
    out = []
    for a in fx_assets:
        if a["key"] not in allow:
            continue
        fc = analog.forecast(a["bars"], a["ind"], a["feats"], pool, horizon,
                             k=config.ANALOG_K, use_knn=True,
                             regime=a.get("regime"))
        if fc is None:
            continue
        ind, bars = a["ind"], a["bars"]
        px = bars["c"][-1]
        atr = ind["atr14"][-1]
        if not atr or atr <= 0 or not px:
            continue
        comp = scoring.components(a, len(bars["c"]) - 1, None)
        if comp is None:
            continue
        direction = 1 if fc["expected_return"] > 0 else -1
        stop_dist = atr * config.FX_STOP_ATR_MULT
        target_dist = atr * config.FX_TARGET_ATR_MULT
        conf = max(fc["prob_up"], 1 - fc["prob_up"])
        spread = SPREAD.get(a["key"], DEFAULT_SPREAD)
        out.append({
            "key": a["key"], "name": a["name"],
            "price": px,
            "direction": "買い" if direction > 0 else "売り",
            "dir_sign": direction,
            "expected_move": fc["expected_return"],
            "abs_move": abs(fc["expected_return"]),
            "prob": fc["prob_up"] if direction > 0 else 1 - fc["prob_up"],
            "confidence": conf,
            "entry": px,
            "stop": px - direction * stop_dist,
            "target": px + direction * target_dist,
            "stop_pct": stop_dist / px,
            "target_pct": target_dist / px,
            "risk_reward": config.FX_TARGET_ATR_MULT / config.FX_STOP_ATR_MULT,
            "atr": atr,
            "atr_pct": atr / px,
            "spread_pct": spread,
            "rsi": ind["rsi14"][-1],
            "adx": ind["adx14"][-1],
            "macd": ind["macd"][-1],
            "macd_signal": ind["macd_signal"][-1],
            "macd_hist": ind["macd_hist"][-1],
            "bb_pctb": ind["bb_pctb"][-1],
            "stoch_k": ind["stoch_k"][-1],
            "sma20": ind["sma20"][-1],
            "sma50": ind["sma50"][-1],
            "n_eff": fc["n_eff"],
            "samples": fc["n"],
            "confirm": confirmation(direction, comp),
        })
    # 5ペアは毎日すべて表示する。確信度は「見送りかどうか」の印として使う。
    # 検証で優位性が確認できたのは確信度56%以上のときだけなので、
    # それ未満は tradeable=False として区別する。
    for x in out:
        x["tradeable"] = x["confidence"] >= config.FX_MIN_CONFIDENCE
        x["status"] = "シグナルあり" if x["tradeable"] else "見送り"
    out.sort(key=lambda x: (-x["tradeable"], -x["confidence"], -x["abs_move"]))
    return out


def position_size(capital, risk_per_trade, stop_pct, price):
    """許容損失と損切り幅から建玉サイズを求める。

    戻り値: (想定元本, 必要証拠金, 必要レバレッジ, 上限に収まるか)
    """
    risk_jpy = capital * risk_per_trade
    if stop_pct <= 0:
        return 0.0, 0.0, 0.0, False
    notional = risk_jpy / stop_pct
    leverage = notional / capital if capital else 0.0
    margin = notional / MAX_LEVERAGE
    return notional, margin, leverage, leverage <= MAX_LEVERAGE


def plan(capital=None, target=None, risk_per_trade=None, trades_per_day=None,
         avg_stop_pct=0.005, avg_spread_pct=0.00004):
    """資金計画。実測した優位性をもとに、狙える額と必要資金を出す。"""
    capital = capital if capital is not None else config.FX_CAPITAL_JPY
    target = target if target is not None else config.FX_DAILY_TARGET_JPY
    risk = risk_per_trade if risk_per_trade is not None else config.FX_RISK_PER_TRADE
    trades = trades_per_day if trades_per_day is not None else config.FX_TRADES_PER_DAY

    edge = MEASURED["edge_per_trade"]
    net_edge = edge - avg_spread_pct * 2      # 往復スプレッドを差し引く

    # 1回あたりの想定元本（許容損失 ÷ 損切り幅）
    notional = (capital * risk) / avg_stop_pct
    leverage = notional / capital if capital else 0.0
    capped = min(notional, capital * MAX_LEVERAGE)
    leverage_ok = leverage <= MAX_LEVERAGE

    daily_gross = capped * edge * trades
    daily_net = capped * net_edge * trades
    monthly_net = daily_net * 20

    # 目標達成に必要な資金（同じリスク設定のまま）
    if net_edge > 0 and trades > 0:
        need_notional = target / (net_edge * trades)
        need_capital = need_notional * avg_stop_pct / risk
    else:
        need_notional = need_capital = float("inf")

    # リスクの目安。優位性が続く前提の破産確率だけ見せると楽観的すぎるので、
    # 「優位性が消えた場合」と「連敗したときの損失」も併せて出す。
    p = MEASURED["hit_rate"]
    b = config.FX_TARGET_ATR_MULT / config.FX_STOP_ATR_MULT
    ev_r = p * b - (1 - p)                    # 1トレードの期待値（R単位）
    units = 1.0 / risk if risk > 0 else 0.0
    if ev_r > 0 and p * b > 0:
        ratio = (1 - p) / (p * b)
        risk_of_ruin = min(1.0, ratio ** units) if ratio < 1 else 1.0
    else:
        risk_of_ruin = 1.0

    # 優位性が完全に消えた場合（勝率が五分に戻った場合）の1日あたり損益
    no_edge_daily = capped * (-avg_spread_pct * 2) * trades

    # 連敗の確率と、そのときの資金減少
    streak = 10
    streak_prob = (1 - p) ** streak
    streak_loss_pct = 1 - (1 - risk) ** streak
    streak_loss = capital * streak_loss_pct

    # 1日の損益のばらつき（1トレードを ±1R とみなした概算）
    daily_sd = math.sqrt(trades) * (capital * risk) * math.sqrt(
        p * b * b + (1 - p)) if trades else 0.0
    # 目標が資金に対して何%か
    daily_target_pct = target / capital if capital else float("inf")

    return {
        "capital": capital,
        "target": target,
        "risk_per_trade": risk,
        "trades_per_day": trades,
        "avg_stop_pct": avg_stop_pct,
        "notional_per_trade": capped,
        "leverage": min(leverage, MAX_LEVERAGE),
        "leverage_required": leverage,
        "leverage_ok": leverage_ok,
        "edge_per_trade": edge,
        "net_edge_per_trade": net_edge,
        "expected_daily_gross": daily_gross,
        "expected_daily_net": daily_net,
        "expected_monthly_net": monthly_net,
        "target_daily_pct": daily_target_pct,
        "required_capital": need_capital,
        "required_notional_per_trade": need_notional,
        "achievable_ratio": (daily_net / target) if target else 0.0,
        "expected_value_r": ev_r,
        "risk_of_ruin": risk_of_ruin,
        "no_edge_daily": no_edge_daily,
        "streak_n": streak,
        "streak_prob": streak_prob,
        "streak_loss": streak_loss,
        "streak_loss_pct": streak_loss_pct,
        "daily_sd": daily_sd,
        "hit_rate": p,
        "risk_reward": b,
        "measured": MEASURED,
    }


def realistic_target(capital=None, **kw):
    """その資金で無理なく狙える1日あたりの利益額"""
    p = plan(capital=capital, **kw)
    return max(0.0, p["expected_daily_net"])


def summary_lines(p):
    """資金計画を日本語の短い説明にする"""
    lines = []
    if p["target_daily_pct"] > 0.05:
        lines.append(
            "資金{:,.0f}円に対して1日{:,.0f}円は日利{:.0f}%です。"
            "検証で確認できた優位性（1回あたり{:.3f}%）では届きません。".format(
                p["capital"], p["target"], p["target_daily_pct"] * 100,
                p["edge_per_trade"] * 100))
    lines.append(
        "今の設定（1回のリスク{:.0f}%・1日{}回）で見込める利益は"
        "1日およそ{:,.0f}円、月{:,.0f}円です。".format(
            p["risk_per_trade"] * 100, p["trades_per_day"],
            p["expected_daily_net"], p["expected_monthly_net"]))
    if p["required_capital"] != float("inf"):
        lines.append(
            "1日{:,.0f}円を同じリスク設定で狙うには、資金がおよそ{:,.0f}円必要です。".format(
                p["target"], p["required_capital"]))
    if not p["leverage_ok"]:
        lines.append(
            "この設定は{:.1f}倍のレバレッジが必要で、国内FXの上限{:.0f}倍を超えます。"
            "1回のリスクを下げるか、損切り幅を広げてください。".format(
                p["leverage_required"], MAX_LEVERAGE))
    lines.append(
        "1回の期待値は{:+.2f}R（勝率{:.1f}%・損益比{:.2f}）です。".format(
            p["expected_value_r"], p["hit_rate"] * 100, p["risk_reward"]))
    lines.append(
        "検証どおりの優位性が続かず勝率が五分に戻った場合は、"
        "スプレッド分だけ1日およそ{:,.0f}円のマイナスになります。".format(
            abs(p["no_edge_daily"])))
    lines.append(
        "{}連敗する確率は{:.1%}で、そのとき資金は{:.0f}%（{:,.0f}円）減ります。"
        "1日の損益のばらつきは±{:,.0f}円程度を見ておいてください。".format(
            p["streak_n"], p["streak_prob"], p["streak_loss_pct"] * 100,
            p["streak_loss"], p["daily_sd"]))
    m = p.get("measured") or {}
    if m.get("signal_days"):
        lines.append(
            "なお条件を満たすシグナルは毎日出るわけではありません。"
            "検証{}日のうち出たのは{}日（{:.0f}%）で、出た日の平均は{:.1f}回でした。".format(
                m["test_days"], m["signal_days"],
                m["signal_days"] / m["test_days"] * 100, m["signals_per_active_day"]))
    return lines
