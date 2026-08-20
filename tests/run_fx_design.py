# -*- coding: utf-8 -*-
"""FXの設計を決めるための実測。

  1. 通貨ペアごとの成績は期間を分けても安定しているか（=選ぶ根拠になるか）
  2. スプレッドを引いたあとの実質的な優位性はどれか
  3. 通貨ペアを5つに絞ると、分析プールが小さくなって精度が落ちないか
  4. MACD・RSI・ボリンジャーによる裏付けを条件に加えると的中率は上がるか
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))

import analog
import backtest
import config
import dataset
import fx as fxmod
import scoring


def _tstat(vals):
    n = len(vals)
    if n < 2:
        return 0.0
    m = sum(vals) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in vals) / (n - 1))
    return (m / (sd / math.sqrt(n))) if sd else 0.0


def gain_of(r):
    return r["actual"] * (1 if r["pred"] > 0 else -1)


def daily_t(rows):
    per = {}
    for r in rows:
        per.setdefault(r["ts"], []).append(gain_of(r))
    return _tstat([sum(v) / len(v) for v in per.values()]), len(per)


def summarize(rows, label, conf=None):
    sel = rows if conf is None else [r for r in rows
                                     if max(r["p_up"], 1 - r["p_up"]) >= conf]
    if len(sel) < 20:
        print("  {:<30} 対象が少なすぎる（{}件）".format(label, len(sel)))
        return None
    g = [gain_of(r) for r in sel]
    t, days = daily_t(sel)
    hit = sum(1 for x in g if x > 0) / len(g)
    mean = sum(g) / len(g)
    print("  {:<30} {:>6,}件  的中率 {:>5.1f}%  平均 {:+.4f}%  t {:>5.2f}（{}日）".format(
        label, len(sel), hit * 100, mean * 100, t, days))
    return dict(n=len(sel), hit=hit, mean=mean, t=t, days=days)


def collect_fx(assets, pairs, n_dates, step):
    """指定した通貨ペアだけでプールを作り、その中で予測する。"""
    keys = set(pairs)
    subset = [a for a in assets if a["kind"] != "fx" or a["key"] in keys]
    return backtest.collect(subset, config.HORIZON_FX, n_dates=n_dates, step=step,
                            use_knn=True, kinds={"fx"}, verbose=False)


if __name__ == "__main__":
    n_dates = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    step = int(sys.argv[2]) if len(sys.argv) > 2 else 3

    print("データ読み込み中...")
    assets = dataset.load_all(use_cache=True, progress=False)
    all_pairs = [p[0] for p in config.FX_PAIRS]
    names = dict(config.FX_PAIRS)

    rows = collect_fx(assets, all_pairs, n_dates, step)
    ts_all = sorted(set(r["ts"] for r in rows))
    mid = ts_all[len(ts_all) // 2]

    # ---------- 1 & 2 ----------
    print()
    print("=== 通貨ペア別の成績（前半・後半・スプレッド差引後） ===")
    print("  {:<20}{:>9}{:>9}{:>9}{:>12}{:>12}".format(
        "通貨ペア", "全期間", "前半", "後半", "平均損益", "スプ差引後"))
    print("  " + "-" * 74)
    per = {}
    for k in all_pairs:
        rs = [r for r in rows if r["key"] == k]
        if not rs:
            continue
        g = [gain_of(r) for r in rs]
        a = [gain_of(r) for r in rs if r["ts"] < mid]
        b = [gain_of(r) for r in rs if r["ts"] >= mid]
        hit = sum(1 for x in g if x > 0) / len(g)
        ha = sum(1 for x in a if x > 0) / max(1, len(a))
        hb = sum(1 for x in b if x > 0) / max(1, len(b))
        mean = sum(g) / len(g)
        sp = fxmod.SPREAD.get(k, fxmod.DEFAULT_SPREAD)
        net = mean - sp * 2
        per[k] = dict(hit=hit, first=ha, second=hb, mean=mean, net=net, sp=sp)
        print("  {:<20}{:>8.1f}%{:>8.1f}%{:>8.1f}%{:>11.4f}%{:>11.4f}%".format(
            names.get(k, k), hit * 100, ha * 100, hb * 100, mean * 100, net * 100))

    stable = [k for k, v in per.items() if v["first"] > 0.5 and v["second"] > 0.5]
    print()
    print("  前半・後半とも50%を超えたペア: {}".format(
        "、".join(names.get(k, k) for k in stable) or "なし"))

    by_net = sorted(per.items(), key=lambda kv: -kv[1]["net"])
    print("  スプレッド差引後の上位5: {}".format(
        "、".join(names.get(k, k) for k, _ in by_net[:5])))

    # ---------- 3 ----------
    print()
    print("=== 通貨ペアを絞ったときの影響 ===")
    candidates = {
        "全14ペア": all_pairs,
        "実質上位5": [k for k, _ in by_net[:5]],
        "前後半とも勝ち越し": stable[:6] or all_pairs[:5],
        "国内の主要5（円絡み中心）": ["USDJPY=X", "EURJPY=X", "GBPJPY=X", "AUDJPY=X", "EURUSD=X"],
    }
    results = {}
    for label, pairs in candidates.items():
        sub = collect_fx(assets, pairs, n_dates, step)
        r = summarize(sub, "{}（{}ペア）".format(label, len(pairs)),
                      conf=config.FX_MIN_CONFIDENCE)
        results[label] = r

    # 14ペアのプールのまま、表示だけ5ペアに絞った場合
    print()
    print("  プールは14ペアのまま、シグナルだけ絞った場合:")
    for label, pairs in candidates.items():
        if label == "全14ペア":
            continue
        sub = [r for r in rows if r["key"] in set(pairs)]
        summarize(sub, "  → " + label, conf=config.FX_MIN_CONFIDENCE)

    # ---------- 4 ----------
    print()
    print("=== テクニカル指標による裏付けを条件に加えた場合（14ペア・確信度56%以上）===")
    base = [r for r in rows if max(r["p_up"], 1 - r["p_up"]) >= config.FX_MIN_CONFIDENCE]
    summarize(base, "条件なし")

    def with_filter(fn, label):
        summarize([r for r in base if fn(r)], label)

    # 予測方向とテクニカルの向きが一致しているか
    with_filter(lambda r: (r["pred"] > 0) == (r["macd"] > 0), "MACDヒストグラムが同じ向き")
    with_filter(lambda r: (r["pred"] > 0) == (r["trend"] > 0), "トレンドが同じ向き")
    with_filter(lambda r: (r["pred"] > 0) == (r["momentum"] > 0), "モメンタムが同じ向き")
    with_filter(lambda r: (r["pred"] > 0) == (r["rsi_dir"] > 0), "RSIが50をまたぐ向きと一致")
    with_filter(lambda r: r["adx"] >= 25, "ADX25以上（方向感あり）")
    with_filter(lambda r: r["adx"] < 20, "ADX20未満（方向感なし）")
    with_filter(lambda r: (r["pred"] > 0 and r["bb"] < 0.2) or (r["pred"] < 0 and r["bb"] > 0.8),
                "ボリンジャーの端（逆張り）")
    with_filter(lambda r: (r["pred"] > 0) == (r["macd"] > 0) and (r["pred"] > 0) == (r["trend"] > 0),
                "MACDとトレンドが両方一致")
