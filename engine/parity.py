# -*- coding: utf-8 -*-
"""実運用と検証が、同じ入力に同じ答えを返すかを確かめる。

これまでの不具合対策は「既知の症状を見張る」ものばかりだった。それでは
次の未知の不具合は捕まえられない。実際、未確定の足の件は19日間気づかれず、
その間ずっと逆の予測を出し続けた。

ここでやるのは直接の照合。

  過去のある日 D までのデータだけを与えて **実運用の経路** を動かし、
  同じ D について **検証の経路** が出す予測と一致するかを比べる。

一致しなければ、検証で測った成績は実運用に当てはまらない。
どちらが正しいかは分からないが、**食い違っていること自体が異常**であり、
それが分かれば数字を信用しないという判断ができる。

未確定の足の不具合は、この検査なら初日に見つかった。実運用の経路が
D より後の情報（進行中の足）を使っていたので、検証と答えが違ったはず。
"""
import bisect

import analog
import config
import indicators


def truncate(asset, i):
    """その銘柄のデータを i 本目までに切り詰め、指標も作り直す。

    実運用がその時点で見ていたはずの状態を再現する。指標を作り直すのが
    要点で、切るだけでは後の足の情報が指標に残ってしまう。
    """
    b = asset["bars"]
    bars = {k: (v[:i + 1] if isinstance(v, list) else v) for k, v in b.items()}
    ind = indicators.compute_all(bars)
    feats = analog.feature_matrix(bars, ind)
    out = dict(asset)
    out["bars"] = bars
    out["ind"] = ind
    out["feats"] = feats
    out["bars_count"] = len(bars["c"])
    # レジームも同じ長さに切る（先の情報を混ぜないため）
    if isinstance(asset.get("regime"), list):
        out["regime"] = asset["regime"][:i + 1]
    return out


def truncated_set(assets, ts, extra_bars=0):
    """その時点までに切り詰めた銘柄一式を作る。

    extra_bars は検査用。1にすると「その時点より後の足を1本使ってしまった」
    状態を再現できる。未確定の足の不具合はこれと同じことをしていた。
    """
    out = []
    for a in assets:
        i = bisect.bisect_right(a["bars"]["t"], ts) - 1 + extra_bars
        i = min(i, len(a["bars"]["c"]) - 1)
        if i < config.MIN_BARS:
            continue
        out.append(truncate(a, i))
    return out


def live_forecast(cut, pool, key, horizon):
    """実運用の経路。切り詰めた一式とプールを受け取って予測する。"""
    target = next((a for a in cut if a["key"] == key), None)
    if not target:
        return None
    return analog.forecast(target["bars"], target["ind"], target["feats"], pool,
                           horizon, k=config.ANALOG_K, use_knn=True,
                           regime=target.get("regime"))


def backtest_forecast(assets, key, ts, horizon):
    """検証の経路。プールを時点まで逐次に積み上げる、いつものやり方。"""
    pool = analog.Pool(horizon)
    target = None
    for a in assets:
        bars = a["bars"]
        end = min(len(bars["c"]) - horizon,
                  bisect.bisect_right(bars["t"], ts) - 1 - horizon + 1)
        if end > 0:
            pool.add_asset_range(a["feats"], bars, a["ind"], 0, end, a.get("regime"))
        if a["key"] == key:
            target = a
    if not target:
        return None
    i = bisect.bisect_right(target["bars"]["t"], ts) - 1
    if i < config.MIN_BARS:
        return None
    return analog.forecast(target["bars"], target["ind"], target["feats"], pool,
                           horizon, k=config.ANALOG_K, use_knn=True,
                           regime=target.get("regime"), idx=i)


def compare(assets, keys, ts, horizon, tol=1e-6, extra_bars=0):
    """1時点ぶんの照合。extra_bars>0 は検査そのものが効くかを確かめる用。"""
    cut = truncated_set(assets, ts, extra_bars)
    pool = analog.build_pool(cut, horizon)
    rows = []
    for k in keys:
        lf = live_forecast(cut, pool, k, horizon)
        bf = backtest_forecast(assets, k, ts, horizon)
        if not lf or not bf:
            rows.append({"key": k, "ok": None, "detail": "予測を作れず"})
            continue
        d_ret = abs(lf["expected_return"] - bf["expected_return"])
        d_prob = abs(lf["prob_up"] - bf["prob_up"])
        ok = d_ret <= tol and d_prob <= tol
        rows.append({"key": k, "ok": ok,
                     "live_return": lf["expected_return"], "bt_return": bf["expected_return"],
                     "live_prob": lf["prob_up"], "bt_prob": bf["prob_up"],
                     "diff_return": d_ret, "diff_prob": d_prob,
                     "same_direction": (lf["expected_return"] > 0) == (bf["expected_return"] > 0)})
    return rows


def summarize(rows):
    done = [r for r in rows if r.get("ok") is not None]
    ng = [r for r in done if not r["ok"]]
    return {
        "n": len(done), "failed": len(ng), "ok": not ng,
        "max_diff_return": max((r["diff_return"] for r in done), default=0.0),
        "max_diff_prob": max((r["diff_prob"] for r in done), default=0.0),
        "direction_mismatch": sum(1 for r in done if not r["same_direction"]),
        "pairs": [r["key"] for r in ng],
    }
