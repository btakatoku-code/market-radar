# -*- coding: utf-8 -*-
"""FX（短期）のシグナルと資金計画。

シグナルは長期枠と同じ類似局面法を1営業日先に適用して作る。
そのうえで、検証で実測した優位性をもとに
「今の資金でいくら狙えるか」「1日1万円には資金がいくら必要か」を逆算する。

利益を約束するものではない。実測値は過去5年の検証結果であり、
将来も同じ優位性が続く保証はない。
"""
import math
import time

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

# 確信度の閾値ごとの実測（主要5ペア）。検証期間を400/360/440時点と
# ずらしても順位が変わらないことを確認している。
CONFIDENCE_LEVELS = [
    {"conf": 0.53, "hit": 0.523, "per_day": 2.13, "mean": 0.00035, "t": 1.20,
     "windows": [0.523, 0.518, 0.528], "first": 0.511, "second": 0.535},
    {"conf": 0.56, "hit": 0.580, "per_day": 0.83, "mean": 0.00096, "t": 2.37,
     "windows": [0.580, 0.570, 0.579], "first": 0.542, "second": 0.614},
    {"conf": 0.60, "hit": 0.628, "per_day": 0.23, "mean": 0.00202, "t": 3.04,
     "windows": [0.628, 0.624, 0.605], "first": 0.532, "second": 0.723},
]

# 曜日と経済指標による絞り込みは、いったん採用したが取り下げた。
# 前半・後半に割る検査は通ったのに、検証期間を前後にずらすと効果が消えたため。
# 同じ失敗を繰り返さないよう、記録として残しておく。
TIMING_RETRACTED = {
    "claimed": 0.642,
    "windows": [0.562, 0.578, 0.546],
    "baseline_windows": [0.556, 0.555, 0.544],
    "note": ("前半64.7%／後半63.6%と分割検査は通ったが、検証期間を400→360→440時点と"
             "ずらすと56.2%→57.8%→54.6%となり、基準（55.6%→55.5%→54.4%）と"
             "変わらなくなった。優位性の証拠としては不十分と判断して取り下げた。"),
}


def confidence_stats(conf):
    """指定した確信度に最も近い実測値を返す（設定画面の表示用）"""
    return min(CONFIDENCE_LEVELS, key=lambda x: abs(x["conf"] - conf))


# 米国金利による判定の実測（主要5ペア・確信度56%以上・前日の金利のみ使用）。
#
# 分かったこと: 金利が大きく動いているとき、予測がその向きに逆らっていると当たらない。
#   主要5ペア  45.7 / 45.2 / 48.0%（400/360/440時点）
#   残り8ペア  36.2 / 35.4 / 36.1%（条件作りに使っていない試し打ち）
# どちらも1回あたりの損益がマイナスで、実際に損をする取引だった。
# これを見送りにすると全体の勝率が 58.0→60.0% に上がり、
# シグナルが減っても1日あたりの期待値は 0.079→0.083% と落ちない。
#
# 「当たるものを新しく主張する」のではなく「外れるものを外す」使い方なので、
# 主張の強さとしても安全側にある。
RATE_BIG_MOVE = 0.27        # 20日変化がこれ以上なら「大きく動いた」（上位1/3の境目）

RATE_VETO = {"hit": 0.457, "windows": [0.457, 0.452, 0.480], "n": 46,
             "held_out": [0.362, 0.354, 0.361],
             "label": "金利が強い逆風"}
RATE_AFTER_VETO = {"hit": 0.600, "windows": [0.600, 0.589, 0.593], "n": 285,
                   "per_day": 0.71, "daily": 0.00083,
                   "before": 0.580, "before_windows": [0.580, 0.570, 0.579]}
RATE_HELD_OUT = {"pairs": 8, "before": [0.544, 0.548, 0.530],
                 "after": [0.574, 0.578, 0.554],
                 "note": "条件作りに使っていない8ペアでも同じ改善を確認"}

# 追い風・逆風それぞれの実測（大きさを問わない符号だけの判定）。
# 60%区分は件数45件で期間ごとに逆転したため、そこでは区別しない。
RATE_LEVELS = {
    0.53: {"with":    {"hit": 0.538, "n": 426, "windows": [0.538, 0.542, 0.539]},
           "without": {"hit": 0.508, "n": 427, "windows": [0.508, 0.495, 0.516]}},
    0.56: {"with":    {"hit": 0.617, "n": 175, "windows": [0.617, 0.609, 0.595]},
           "without": {"hit": 0.538, "n": 156, "windows": [0.538, 0.528, 0.558]}},
}
RATE_UNRELIABLE_ABOVE = 0.60   # これ以上の確信度では金利で区別しない


def rate_backing(conf, tailwind, direction):
    """金利がその予測を後押ししているか、逆らっているかを判定する。

    帯域別の実測では、効果は「金利が大きく動いたとき」に集中していた。
    小さい変化のときは追い風と逆風でほとんど差がない（57.7% 対 54.5%）ため、
    そこでは判定を出さない。誤差の符号を読んでも意味がない。

    返り値の state:
      tailwind        大きく動いていて、予測と同じ向き
      headwind_strong 大きく動いていて、予測と逆向き → 見送り
      flat            金利がほとんど動いていない（判定材料にしない）
      unknown         金利データがない
    """
    if tailwind is None:
        return {"state": "unknown", "label": "金利データなし", "hit": None,
                "tailwind": None, "veto": False}
    if abs(tailwind) < RATE_BIG_MOVE:
        return {"state": "flat", "label": "金利はほぼ横ばい", "hit": None,
                "tailwind": tailwind, "veto": False,
                "note": ("20日の変化が{:+.2f}%と小さく、判定材料にしていません。"
                         "実測でも、この範囲では追い風と逆風で差が出ませんでした。"
                         ).format(tailwind)}
    agree = (tailwind > 0) == (direction > 0)
    if not agree:
        return {"state": "headwind_strong", "label": RATE_VETO["label"],
                "hit": RATE_VETO["hit"], "windows": RATE_VETO["windows"],
                "n": RATE_VETO["n"], "tailwind": tailwind, "veto": True,
                "note": ("金利が20日で{:+.2f}%動いていて、予測はその向きに逆らっています。"
                         "実測45.7%で、1回あたりの損益もマイナスでした。"
                         ).format(tailwind)}
    lv = None
    if conf < RATE_UNRELIABLE_ABOVE:
        for th in sorted(RATE_LEVELS, reverse=True):
            if conf >= th:
                lv = RATE_LEVELS[th]
                break
    st = lv["with"] if lv else None
    return {"state": "tailwind", "label": "金利の追い風あり",
            "hit": st["hit"] if st else None,
            "windows": st["windows"] if st else None,
            "n": st["n"] if st else None,
            "tailwind": tailwind, "veto": False,
            "note": ("金利が20日で{:+.2f}%動いていて、予測と同じ向きです。"
                     ).format(tailwind)}


def confidence_stats_for(conf):
    """その確信度が実際に届いている区分を返す。

    確信度62%なら「60%以上（実測62.8%）」の区分。
    どの区分にも届かなければ、実測されていない扱いにする。
    """
    reached = [l for l in CONFIDENCE_LEVELS if conf >= l["conf"]]
    if not reached:
        return {"conf": None, "hit": 0.50, "per_day": None, "mean": None,
                "t": None, "label": "実測区分に届かず"}
    best = max(reached, key=lambda l: l["conf"])
    return dict(best, label="{:.0f}%以上".format(best["conf"] * 100))


# 主要通貨ペアの片道スプレッド目安（対価格比）。国内FX業者の標準的な水準。
SPREAD = {
    "USDJPY=X": 0.0000125, "EURJPY=X": 0.0000200, "GBPJPY=X": 0.0000550,
    "AUDJPY=X": 0.0000450, "NZDJPY=X": 0.0000700, "CADJPY=X": 0.0000600,
    "CHFJPY=X": 0.0000900, "EURUSD=X": 0.0000250, "GBPUSD=X": 0.0000600,
    "AUDUSD=X": 0.0000500, "NZDUSD=X": 0.0000900, "USDCHF=X": 0.0000700,
    "USDCAD=X": 0.0000700, "EURGBP=X": 0.0000700, "XAUUSD=X": 0.0003000,
}
DEFAULT_SPREAD = 0.00007

# 各ペアを構成する通貨。経済指標がそのペアに関係するかの判定に使う。
PAIR_CURRENCIES = {
    "USDJPY=X": ("USD", "JPY"), "EURJPY=X": ("EUR", "JPY"),
    "GBPJPY=X": ("GBP", "JPY"), "AUDJPY=X": ("AUD", "JPY"),
    "NZDJPY=X": ("NZD", "JPY"), "CADJPY=X": ("CAD", "JPY"),
    "CHFJPY=X": ("CHF", "JPY"), "EURUSD=X": ("EUR", "USD"),
    "GBPUSD=X": ("GBP", "USD"), "AUDUSD=X": ("AUD", "USD"),
    "NZDUSD=X": ("NZD", "USD"), "USDCHF=X": ("USD", "CHF"),
    "USDCAD=X": ("USD", "CAD"), "EURGBP=X": ("EUR", "GBP"),
    "XAUUSD=X": ("XAU", "USD"),
}
MAX_LEVERAGE = 25.0             # 国内FXの個人口座の上限


def timing_quality(weekday, has_own_event):
    """その日の状況を情報として返す。的中率の主張は伴わない。

    曜日と経済指標で的中率が変わるかを実測し、いったんは採用したが、
    検証期間をずらすと効果が消えたため取り下げた（TIMING_RETRACTED）。
    いまは絞り込みにも重み付けにも使わず、「明日この通貨の指標がある」
    という事実だけを伝える。
    """
    names = ["月", "火", "水", "木", "金", "土", "日"]
    return {
        "weekday": names[weekday] if 0 <= weekday < 7 else "?",
        "has_event": bool(has_own_event),
        "note": ("この通貨に関係する経済指標が予定されています。"
                 "指標の前後は値動きが荒くなることがあります。"
                 if has_own_event else
                 "この通貨に関係する重要な経済指標の予定はありません。"),
    }


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


def signals(fx_assets, pool, horizon=None, top_n=None, pairs=None,
            rate_series=None, at_ts=None):
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
    #
    # 並び順は「的中確率の高い順 → 裏付けの強い順」。的中確率には
    # 金利の追い風の有無まで織り込む（56%区分なら追い風あり61.7%／なし53.8%）。
    # 的中確率は、その確信度が属する区分の実測勝率を使う（53%区分=52.3%、
    # 56%区分=58.0%、60%区分=62.8%）。同じ区分の中では裏付けの強さで並べ、
    # それも同じなら確信度そのもので並べる。
    #
    # なお「14ペアから的中確率の高い上位5つを毎日選び直す」方式も実測したが、
    # 勝率が58.0%→56.4%（検証期間3通りすべて）と下がったため採用していない。
    # 主要5ペア自体の成績が良く、入れ替えると質の劣るペアが混ざるため。
    import rates as rates_mod
    if at_ts is None:
        at_ts = int(time.time())
    for x in out:
        x["conf_stats"] = confidence_stats_for(x["confidence"])
        tw = (rates_mod.tailwind(rate_series, x["key"], at_ts)
              if rate_series else None)
        x["rate"] = rate_backing(x["confidence"], tw,
                                 1 if x["direction"] == "買い" else -1)
        # 確信度が足りていても、金利が強い逆風なら見送る（実測45.7%）。
        x["tradeable"] = (x["confidence"] >= config.FX_MIN_CONFIDENCE
                          and not x["rate"]["veto"])
        x["status"] = ("シグナルあり" if x["tradeable"]
                       else ("見送り（金利が逆風）" if x["rate"]["veto"] else "見送り"))
        # 金利の裏付けまで実測できている場合は、そちらの方が細かい区分なので優先する。
        x["expected_hit"] = (x["rate"]["hit"] if x["rate"]["hit"] is not None
                             else x["conf_stats"]["hit"])
    out.sort(key=lambda x: (-x["expected_hit"], -x["confirm"]["level"],
                            -x["confidence"], -x["abs_move"]))
    for i, x in enumerate(out):
        x["order"] = i + 1
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
