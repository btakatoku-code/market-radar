# -*- coding: utf-8 -*-
"""検証時点の並びを1日ずらしたときに、結論が変わらないかを調べる。

pick_dates は最新日から3営業日おきに遡るので、新しい足が1本増えると
選ばれる時点がすべて1日ずれる。offset=0/1/2 は互いに1日も重ならない
別々の標本になる。

n_dates を 400/360/440 と変える検査は時点の並びを共有しているため、
この種の揺れを検出できない。取り下げた曜日の条件も、今回の金利の条件も、
その検査は通っていた。
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
BIG = 0.27


def run(assets, ser, offset):
    rows = backtest.collect(assets, config.HORIZON_FX, n_dates=400, step=3,
                            use_knn=True, kinds={"fx"}, verbose=False, offset=offset)
    td = len(set(r["ts"] for r in rows))
    A.attach_lagged(rows, ser, LAG)
    sel = [r for r in rows
           if max(r["p_up"], 1 - r["p_up"]) >= config.FX_MIN_CONFIDENCE
           and r["rate20"] is not None]

    def veto(r):
        return abs(r["rate20"]) >= BIG and (r["rate20"] > 0) != (r["pred"] > 0)

    out = {}
    for g, s2 in [("主要5ペア", [r for r in sel if r["key"] in R.MAJOR]),
                  ("残り8ペア", [r for r in sel if r["key"] not in R.MAJOR])]:
        out[g] = {"全部": R.stat(s2, td),
                  "金利で見送り後": R.stat([r for r in s2 if not veto(r)], td),
                  "見送った分": R.stat([r for r in s2 if veto(r)], td)}
    return out


if __name__ == "__main__":
    print("データ読み込み中...")
    assets = dataset.load_all(use_cache=True, progress=False)
    ser = R.yields()
    res = {o: run(assets, ser, o) for o in (0, 1, 2)}

    for g in ["主要5ペア", "残り8ペア"]:
        print()
        print("=== {} （時点の並びを1日ずつずらす）===".format(g))
        print("  {:<18}{:>10}{:>10}{:>10}{:>9}".format(
            "条件", "ずらし0", "ずらし1", "ずらし2", "振れ幅"))
        print("  " + "-" * 58)
        for name in ["全部", "金利で見送り後", "見送った分"]:
            vals = [res[o][g][name]["hit"] if res[o][g][name] else None for o in (0, 1, 2)]
            cells = ["{:.1f}%".format(v * 100) if v is not None else "—" for v in vals]
            ok = [v for v in vals if v is not None]
            span = "{:.1f}pt".format((max(ok) - min(ok)) * 100) if len(ok) > 1 else "—"
            print("  {:<18}{:>10}{:>10}{:>10}{:>9}".format(
                name, cells[0], cells[1], cells[2], span))
        diffs = []
        for o in (0, 1, 2):
            a, b = res[o][g]["全部"], res[o][g]["金利で見送り後"]
            if a and b:
                diffs.append((b["hit"] - a["hit"]) * 100)
        print("  見送りによる改善幅: " + " / ".join("{:+.1f}pt".format(d) for d in diffs))
        print("  → {}".format("3通りとも改善" if all(d > 0 for d in diffs)
                              else "ずらすと改善しない通りがある"))
