# -*- coding: utf-8 -*-
"""先読みを取り除いた条件で、金利の効果を測り直す。

run_rates.py は同じ日の米国市場の終値を使っていた。日足の終値が確定するのは
日本時間の翌朝で、予測を出す23:30時点ではまだ分からない。
ここでは「前日の米国終値」だけを使う（1日遅らせ）。念のため2日遅らせも測る。

採用の条件は変えない:
  主要5ペアと残り8ペアの両方で、400／360／440の3期間すべて改善すること。
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))

import backtest
import config
import dataset
import run_rates as R
import run_rates_audit as A


def run(assets, ser, n_dates, lag):
    rows = backtest.collect(assets, config.HORIZON_FX, n_dates=n_dates, step=3,
                            use_knn=True, kinds={"fx"}, verbose=False)
    td = len(set(r["ts"] for r in rows))
    A.attach_lagged(rows, ser, lag)
    base = [r for r in rows
            if max(r["p_up"], 1 - r["p_up"]) >= config.FX_MIN_CONFIDENCE
            and r["rate20"] is not None]
    out = {}
    for g, sel in [("主要5ペア", [r for r in base if r["key"] in R.MAJOR]),
                   ("残り8ペア（試し打ち）", [r for r in base if r["key"] not in R.MAJOR])]:
        agree = [r for r in sel if (r["rate20"] > 0) == (r["pred"] > 0)]
        out[g] = {"条件なし": R.stat(sel, td), "金利の追い風と同じ向き": R.stat(agree, td)}
    return out


if __name__ == "__main__":
    print("データ読み込み中...")
    assets = dataset.load_all(use_cache=True, progress=False)
    ser = R.yields()

    for lag in (1, 2):
        res = {w: run(assets, ser, w, lag) for w in (400, 360, 440)}
        print()
        print("=== 金利を{}日遅らせたとき（前日以前の米国終値だけを使う）===".format(lag))
        print("  {:<28}{:<14}{:>8}{:>8}{:>8}{:>7}{:>7}{:>10}".format(
            "ペア群", "条件", "400", "360", "440", "件数", "1日", "1日期待値"))
        print("  " + "-" * 92)
        verdict = {}
        for g in ["主要5ペア", "残り8ペア（試し打ち）"]:
            for name in ["条件なし", "金利の追い風と同じ向き"]:
                s = res[400][g][name]
                if not s:
                    continue
                cells = ["—" if not res[w][g][name] else
                         "{:.1f}%".format(res[w][g][name]["hit"] * 100) for w in (400, 360, 440)]
                better = (name != "条件なし" and
                          all(res[w][g][name]["hit"] > res[w][g]["条件なし"]["hit"]
                              for w in (400, 360, 440)))
                if name != "条件なし":
                    verdict[g] = (better, [res[w][g][name]["hit"] - res[w][g]["条件なし"]["hit"]
                                           for w in (400, 360, 440)])
                print("  {:<28}{:<14}{:>8}{:>8}{:>8}{:>7,}{:>7.2f}{:>9.3f}%{}".format(
                    g if name == "条件なし" else "", name, cells[0], cells[1], cells[2],
                    s["n"], s["per_day"], s["daily"] * 100, " ○" if better else ""))
        print("  判定: {}".format(
            "両群とも3期間で改善 → 採用してよい" if all(v[0] for v in verdict.values())
            else "条件を満たさず → 不採用"))
        for g, (ok, diffs) in verdict.items():
            print("     {:<24} 改善幅 {}".format(
                g, " / ".join("{:+.1f}pt".format(d * 100) for d in diffs)))
