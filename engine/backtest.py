# -*- coding: utf-8 -*-
"""ウォークフォワード検証のデータ収集。

過去の各時点で、その時点までのデータだけを使って予測を作り、実際の結果と
突き合わせる。プールには「その時点で前方リターンが確定済み」のバーだけを
順次追加していくため、未来の情報は混入しない。

銘柄ごとに営業日数も取引カレンダーも違う（米国株・日本株・暗号資産）ため、
時点の指定はインデックスではなくタイムスタンプで行う。
"""
import bisect

import analog
import config
import scoring

DAY = 86400


def index_at(bars, ts):
    """タイムスタンプ ts 以前で最後のバーの位置。無ければ None。"""
    i = bisect.bisect_right(bars["t"], ts) - 1
    return i if i >= 0 else None


def calendar(assets):
    """検証時点の基準となる取引日の並び（最も本数の多い米国株を使う）"""
    us = [a for a in assets if a["kind"] in ("us_stock", "us_etf")]
    ref = max(us or assets, key=lambda a: a["bars_count"])
    return ref["bars"]["t"]


def pick_dates(assets, horizon, n_dates, step, warmup=280):
    cal = calendar(assets)
    dates = []
    p = len(cal) - horizon - 1
    while len(dates) < n_dates and p > warmup:
        dates.append(cal[p])
        p -= step
    dates.reverse()
    return dates


def collect(assets, horizon, n_dates=150, step=10, k=None,
            use_knn=False, verbose=True, kinds=None):
    """各時点・各銘柄の予測とスコア構成要素、実際の結果を集める。

    プールは時点を進めながら逐次追加するので、全期間を通して各バーは1回しか
    処理されない。
    """
    k = k or config.ANALOG_K
    if kinds is None:
        tradable = [a for a in assets
                    if a["kind"] not in ("index", "fx") and not a["leveraged"]
                    and a["bars_count"] >= config.MIN_BARS]
    else:
        tradable = [a for a in assets
                    if a["kind"] in kinds and not a["leveraged"]
                    and a["bars_count"] >= config.MIN_BARS]
    by_key = {a["key"]: a for a in assets}
    dates = pick_dates(assets, horizon, n_dates, step)
    if not dates:
        return []
    if verbose:
        import datetime
        d0 = datetime.date.fromtimestamp(dates[0])
        d1 = datetime.date.fromtimestamp(dates[-1])
        print("  検証時点 {} 個（{} 〜 {}） / 対象 {} 銘柄 / 予測期間 {}営業日".format(
            len(dates), d0, d1, len(tradable), horizon))

    pool = analog.Pool(horizon)
    cursor = {a["key"]: 0 for a in tradable}
    rows = []

    for di, ts in enumerate(dates):
        # その時点で前方リターンが確定したバーをプールへ追加
        for a in tradable:
            bars = a["bars"]
            last = bisect.bisect_right(bars["t"], ts) - 1 - horizon
            end = min(len(bars["c"]) - horizon, last + 1)
            c0 = cursor[a["key"]]
            if end > c0:
                pool.add_asset_range(a["feats"], bars, a["ind"], c0, end,
                                     a.get("regime"))
                cursor[a["key"]] = end

        for a in tradable:
            bars = a["bars"]
            idx = index_at(bars, ts)
            if idx is None or idx < 260:
                continue
            if idx + horizon >= len(bars["c"]):
                continue
            if ts - bars["t"][idx] > 7 * DAY:
                continue
            fc = analog.forecast(bars, a["ind"], a["feats"], pool, horizon,
                                 k=k, use_knn=use_knn, idx=idx,
                                 regime=a.get("regime"))
            if fc is None:
                continue
            br = scoring.bench_roc20_at(by_key, a["kind"], ts, index_at)
            comp = scoring.components(a, idx, br)
            if comp is None:
                continue
            c = bars["c"]
            rows.append(dict(
                key=a["key"], kind=a["kind"], ts=ts,
                actual=c[idx + horizon] / c[idx] - 1,
                pred=fc["expected_return"], pred_z=fc["expected_z"],
                p_up=fc["prob_up"], n_eff=fc["n_eff"],
                daily_vol=comp["daily_vol"], adv=a["adv"],
                trend=comp["trend"], momentum=comp["momentum"],
                rel=comp["rel"], volume=comp["volume"],
                macd=comp["macd"], bb=(comp["bb"] if comp["bb"] is not None else 0.5),
                rsi=comp["rsi"], rsi_dir=(comp["rsi"] - 50.0), adx=comp["adx"],
                score=scoring.total_score(comp, fc)))
        if verbose and (di + 1) % 10 == 0:
            print("    {}/{} 時点 完了 (累計 {:,} 行 / プール {:,} 件)".format(
                di + 1, len(dates), len(rows), pool.size()), flush=True)

    # 各時点の市場中央値に対する超過を付与（外れ値に強い基準を使う）
    by_t = {}
    for r in rows:
        by_t.setdefault(r["ts"], []).append(r)
    for rs in by_t.values():
        vals = sorted(x["actual"] for x in rs)
        m = vals[len(vals) // 2]
        for r in rs:
            r["excess"] = r["actual"] - m
    return rows
