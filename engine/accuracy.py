# -*- coding: utf-8 -*-
"""銘柄ごとの「過去の的中率」を求めて保存する。

アプリでは各銘柄のカードに的中率を出したい。実運用の記録（track.py）は
貯まるまで時間がかかるので、それとは別に、過去データでのウォークフォワード
検証から銘柄ごとの成績を出しておく。

計算に数分かかるので、結果はファイルに残して1週間は使い回す。
"""
import json
import os
import time

import backtest
import config

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "public", "data", "accuracy_by_asset.json")
MAX_AGE = 7 * 24 * 3600      # 1週間で作り直す
MIN_SAMPLES = 20             # これ未満は的中率を出さない


def _summarize(rows):
    """銘柄ごとに、予測方向が当たった割合と平均損益を出す。"""
    per = {}
    for r in rows:
        per.setdefault(r["key"], []).append(r)
    out = {}
    for key, rs in per.items():
        n = len(rs)
        if n < MIN_SAMPLES:
            continue
        hit = sum(1 for r in rs if (r["pred"] > 0) == (r["actual"] > 0))
        up = sum(1 for r in rs if r["actual"] > 0)
        gains = [r["actual"] * (1 if r["pred"] > 0 else -1) for r in rs]
        errs = [abs(r["actual"] - r["pred"]) for r in rs]
        out[key] = {
            "n": n,
            "hit_rate": round(hit / n, 4),          # 方向が当たった割合
            "up_rate": round(up / n, 4),            # 実際に上がった割合
            "mean_gain": round(sum(gains) / n, 6),  # 予測方向に賭けたときの平均
            "mean_error": round(sum(errs) / n, 6),  # 予測と実績のずれ
            "mean_actual": round(sum(r["actual"] for r in rs) / n, 6),
        }
    return out


def _overall(rows):
    """全体の基準線。的中率を読むときの比較対象になる。"""
    if not rows:
        return None
    n = len(rows)
    hit = sum(1 for r in rows if (r["pred"] > 0) == (r["actual"] > 0))
    return {
        "n": n,
        "hit_rate": round(hit / n, 4),
        # 何もせず買った場合に上がっていた割合（この期間の地合い）
        "base_up_rate": round(sum(1 for r in rows if r["actual"] > 0) / n, 4),
        "mean_actual": round(sum(r["actual"] for r in rows) / n, 6),
        "dates": len(set(r["ts"] for r in rows)),
    }


def build(assets, horizon=None, n_dates=100, step=21, kinds=None,
          use_knn=False, verbose=True):
    horizon = horizon or config.HORIZON_LONG
    rows = backtest.collect(assets, horizon, n_dates=n_dates, step=step,
                            use_knn=use_knn, kinds=kinds, verbose=verbose)
    return _summarize(rows), len(rows), _overall(rows)


def load():
    if not os.path.exists(OUT):
        return None
    try:
        with open(OUT, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def is_fresh(data):
    return bool(data) and (time.time() - data.get("built_at", 0)) < MAX_AGE


def ensure(assets, verbose=True):
    """必要なら作り直して返す。1週間以内に作ったものがあればそれを使う。"""
    cached = load()
    if is_fresh(cached):
        if verbose:
            age = (time.time() - cached["built_at"]) / 3600
            print("   銘柄別の的中率: {:.0f}時間前の結果を使用（{}銘柄）".format(
                age, len(cached.get("assets", {}))))
        return cached

    if verbose:
        print("   銘柄別の的中率を計算中（数分かかります）...")
    t0 = time.time()
    stocks, n1, base_long = build(assets, config.HORIZON_LONG,
                                  n_dates=100, step=config.HORIZON_LONG, verbose=False)
    fx, n2, base_fx = build(assets, config.HORIZON_FX, n_dates=400, step=3,
                            kinds={"fx"}, use_knn=True, verbose=False)
    stocks.update(fx)

    data = {
        "built_at": int(time.time()),
        "horizon_long": config.HORIZON_LONG,
        "horizon_fx": config.HORIZON_FX,
        "regime_mode_long": config.REGIME_MODE_LONG,
        "regime_mode_fx": config.REGIME_MODE_FX,
        "samples": n1 + n2,
        "min_samples": MIN_SAMPLES,
        "baseline_long": base_long,
        "baseline_fx": base_fx,
        "assets": stocks,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, OUT)
    if verbose:
        print("   完了: {}銘柄 / {:,}件の検証 / {:.0f}秒".format(
            len(stocks), n1 + n2, time.time() - t0))
    return data


if __name__ == "__main__":
    import dataset
    print("データ読み込み中...")
    a = dataset.load_all(use_cache=True, progress=True)
    if os.path.exists(OUT):
        os.remove(OUT)
    ensure(a)
