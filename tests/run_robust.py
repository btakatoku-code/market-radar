# -*- coding: utf-8 -*-
"""有望に見えたルールが本物かどうかを確かめる。

比較で上位に来たルールについて、
  1. ボラティリティ上限を変えても優位性が残るか
  2. 期間を前半・後半に分けても同じ向きに出るか
を見る。前回、見かけ上+0.90%だったルールがこの検査で崩れた。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))

import backtest
import compare
import config
import dataset

RULES = [
    ("トレンドのみ", lambda r: r["trend"]),
    ("予測リターン（絶対値）", lambda r: r["pred"]),
    ("合成スコア", lambda r: r["score"]),
    ("モメンタムのみ", lambda r: r["momentum"]),
]
CAPS = [None, 0.90, 0.70, 0.55, 0.45, 0.35]


def half(rows, first):
    ts = sorted(set(r["ts"] for r in rows))
    mid = ts[len(ts) // 2]
    return [r for r in rows if (r["ts"] < mid if first else r["ts"] >= mid)]


if __name__ == "__main__":
    horizon = int(sys.argv[1]) if len(sys.argv) > 1 else config.HORIZON_LONG
    n_dates = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    step = int(sys.argv[3]) if len(sys.argv) > 3 else horizon

    assets = dataset.load_all(use_cache=True, progress=False)
    rows = backtest.collect(assets, horizon, n_dates=n_dates, step=step,
                            use_knn=False, verbose=True)

    print()
    print("=== ボラティリティ上限を変えたときの市場超過（{}営業日先） ===".format(horizon))
    header = "  {:<22}".format("ルール") + "".join(
        "{:>13}".format("上限なし" if c is None else "{:.0f}%".format(c * 100)) for c in CAPS)
    print(header)
    print("  " + "-" * (22 + 13 * len(CAPS)))
    for name, fn in RULES:
        cells = []
        for cap in CAPS:
            r = compare.evaluate(rows, fn, max_annual_vol=cap)
            cells.append("—" if not r else "{:+.2f}% ({:.1f})".format(
                r["excess"] * 100, r["t_stat"]))
        print("  {:<22}".format(name) + "".join("{:>13}".format(c) for c in cells))
    print("  ※ かっこ内は t値。上限を変えても符号と大きさが保たれるかを見る。")

    print()
    print("=== 期間を半分に割ったとき（上限なし） ===")
    print("  {:<22}{:>18}{:>18}".format("ルール", "前半", "後半"))
    print("  " + "-" * 58)
    for name, fn in RULES:
        a = compare.evaluate(half(rows, True), fn)
        b = compare.evaluate(half(rows, False), fn)
        f = lambda r: "—" if not r else "{:+.2f}% (t {:.2f})".format(r["excess"] * 100, r["t_stat"])
        print("  {:<22}{:>18}{:>18}".format(name, f(a), f(b)))
    print("  ※ 前半と後半で符号が変わるルールは、たまたま当たっていた可能性が高い。")
