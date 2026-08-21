# -*- coding: utf-8 -*-
"""金利の裏付けを「並べ替えと表示」に使うための数値を測る。

シグナルを捨てるのではなく、金利の裏付けがあるものを上位に出す。
そのために「裏付けあり／なし」それぞれの実測値が要る。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))

import backtest
import config
import dataset
import run_rates as R
import run_rates_audit as A

LAG = 1        # 前日の米国終値だけを使う（先読みを避ける）


def run(assets, ser, n_dates):
    rows = backtest.collect(assets, config.HORIZON_FX, n_dates=n_dates, step=3,
                            use_knn=True, kinds={"fx"}, verbose=False)
    td = len(set(r["ts"] for r in rows))
    A.attach_lagged(rows, ser, LAG)
    maj = [r for r in rows if r["key"] in R.MAJOR and r["rate20"] is not None]
    out = {}
    for conf in (0.53, 0.56, 0.60):
        sel = [r for r in maj if max(r["p_up"], 1 - r["p_up"]) >= conf]
        ag = [r for r in sel if (r["rate20"] > 0) == (r["pred"] > 0)]
        dg = [r for r in sel if (r["rate20"] > 0) != (r["pred"] > 0)]
        out[conf] = {"全体": R.stat(sel, td), "裏付けあり": R.stat(ag, td),
                     "裏付けなし": R.stat(dg, td)}
    return out


if __name__ == "__main__":
    print("データ読み込み中...")
    assets = dataset.load_all(use_cache=True, progress=False)
    ser = R.yields()
    res = {w: run(assets, ser, w) for w in (400, 360, 440)}

    print()
    print("=== 確信度 × 金利の裏付け（主要5ペア・前日の金利だけを使用）===")
    print("  {:<8}{:<12}{:>8}{:>8}{:>8}{:>7}{:>7}{:>10}".format(
        "確信度", "区分", "400", "360", "440", "件数", "1日", "1回の損益"))
    print("  " + "-" * 70)
    for conf in (0.53, 0.56, 0.60):
        for name in ["全体", "裏付けあり", "裏付けなし"]:
            s = res[400][conf][name]
            if not s:
                print("  {:<8}{:<12}{:>8}".format(
                    "{:.0f}%".format(conf * 100) if name == "全体" else "", name, "件数不足"))
                continue
            cells = ["—" if not res[w][conf][name] else
                     "{:.1f}%".format(res[w][conf][name]["hit"] * 100) for w in (400, 360, 440)]
            print("  {:<8}{:<12}{:>8}{:>8}{:>8}{:>7,}{:>7.2f}{:>9.3f}%".format(
                "{:.0f}%".format(conf * 100) if name == "全体" else "", name,
                cells[0], cells[1], cells[2], s["n"], s["per_day"], s["mean"] * 100))
        print()
    print("  ※ アプリでは5ペアすべて表示したまま、裏付けのあるものを上位に並べる。")
    print("     表示する的中率もこの実測値を使う。")
    print()
    print("=== 採用する数値（そのままコードに入れる形）===")
    for conf in (0.53, 0.56, 0.60):
        for key, name in [("with", "裏付けあり"), ("without", "裏付けなし")]:
            s = res[400][conf][name]
            if not s:
                continue
            w = [res[x][conf][name]["hit"] for x in (400, 360, 440) if res[x][conf][name]]
            print('  {:.2f} {:<8} hit={:.3f} n={} per_day={:.2f} mean={:.5f} windows={}'.format(
                conf, key, s["hit"], s["n"], s["per_day"], s["mean"],
                "[" + ", ".join("{:.3f}".format(x) for x in w) + "]"))
