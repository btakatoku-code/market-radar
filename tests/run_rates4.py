# -*- coding: utf-8 -*-
"""金利の変化が小さいときにも効果があるかを確かめる。

いまは20日変化の「符号」だけで追い風か逆風かを決めている。
変化が0.01%しかない日も、0.5%動いた日も同じ扱い。
小さい変化のときに効果がないなら、その判定は誤差を読んでいることになる。

主要5ペアと残り8ペアの両方で見る。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))

import backtest
import config
import dataset
import run_rates as R
import run_rates_audit as A

LAG = 1


def run(assets, ser, n_dates):
    rows = backtest.collect(assets, config.HORIZON_FX, n_dates=n_dates, step=3,
                            use_knn=True, kinds={"fx"}, verbose=False)
    td = len(set(r["ts"] for r in rows))
    A.attach_lagged(rows, ser, LAG)
    base = [r for r in rows
            if max(r["p_up"], 1 - r["p_up"]) >= config.FX_MIN_CONFIDENCE
            and r["rate20"] is not None]
    mags = sorted(abs(r["rate20"]) for r in base)
    if not mags:
        return {}
    q1, q2 = mags[len(mags) // 3], mags[2 * len(mags) // 3]
    bands = [("小さい（下位1/3）", lambda m: m < q1),
             ("普通（中位1/3）",   lambda m: q1 <= m < q2),
             ("大きい（上位1/3）", lambda m: m >= q2)]
    out = {}
    for g, sel in [("主要5ペア", [r for r in base if r["key"] in R.MAJOR]),
                   ("残り8ペア（試し打ち）", [r for r in base if r["key"] not in R.MAJOR])]:
        out[g] = {}
        for bname, fn in bands:
            rs = [r for r in sel if fn(abs(r["rate20"]))]
            ag = [r for r in rs if (r["rate20"] > 0) == (r["pred"] > 0)]
            dg = [r for r in rs if (r["rate20"] > 0) != (r["pred"] > 0)]
            out[g][bname] = (R.stat(rs, td), R.stat(ag, td), R.stat(dg, td))
    out["境目"] = (q1, q2)
    return out


if __name__ == "__main__":
    print("データ読み込み中...")
    assets = dataset.load_all(use_cache=True, progress=False)
    ser = R.yields()
    res = {w: run(assets, ser, w) for w in (400, 360, 440)}
    print("  金利変化の大きさの境目: {:.3f}% / {:.3f}%".format(*res[400]["境目"]))

    for g in ["主要5ペア", "残り8ペア（試し打ち）"]:
        print()
        print("=== {} ===".format(g))
        print("  {:<18}{:<10}{:>8}{:>8}{:>8}{:>7}".format(
            "金利変化の大きさ", "区分", "400", "360", "440", "件数"))
        print("  " + "-" * 60)
        for bname in ["小さい（下位1/3）", "普通（中位1/3）", "大きい（上位1/3）"]:
            for i, label in [(1, "追い風"), (2, "逆風")]:
                cells = []
                n = 0
                for w in (400, 360, 440):
                    x = res[w][g][bname][i]
                    cells.append("{:.1f}%".format(x["hit"] * 100) if x else "—")
                    if w == 400 and x:
                        n = x["n"]
                print("  {:<18}{:<10}{:>8}{:>8}{:>8}{:>7,}".format(
                    bname if label == "追い風" else "", label,
                    cells[0], cells[1], cells[2], n))
            print()
    print("  小さい区分でも追い風＞逆風なら、符号だけの判定でよい。")
    print("  そこで差が消えるなら、最低限の大きさを条件に加えるべき。")
