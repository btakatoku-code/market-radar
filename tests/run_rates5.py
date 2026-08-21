# -*- coding: utf-8 -*-
"""採用する形を最終確認する。

分かったこと: 金利が大きく動いているとき、予測がその向きに逆らっていると当たらない。
       主要5ペア 47.9/50.0/50.9%、試し打ちの8ペア 37.8/38.9/38.9%。

そこで「金利が大きく動いていて、かつ予測が逆向き」のシグナルを見送りにする。
新しい当たりを主張するのではなく、外れるものを外す使い方。

確認すること:
  1. 見送りにした後の全体の勝率が、3期間・両群とも上がるか
  2. 1日あたりの期待値が下がらないか（機会を失いすぎていないか）
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
BIG = 0.27          # 20日変化がこれ以上なら「大きく動いた」（上位1/3の境目）


def run(assets, ser, n_dates):
    rows = backtest.collect(assets, config.HORIZON_FX, n_dates=n_dates, step=3,
                            use_knn=True, kinds={"fx"}, verbose=False)
    td = len(set(r["ts"] for r in rows))
    A.attach_lagged(rows, ser, LAG)
    base = [r for r in rows
            if max(r["p_up"], 1 - r["p_up"]) >= config.FX_MIN_CONFIDENCE
            and r["rate20"] is not None]

    def veto(r):
        return abs(r["rate20"]) >= BIG and (r["rate20"] > 0) != (r["pred"] > 0)

    out = {}
    for g, sel in [("主要5ペア", [r for r in base if r["key"] in R.MAJOR]),
                   ("残り8ペア（試し打ち）", [r for r in base if r["key"] not in R.MAJOR])]:
        out[g] = {
            "現行（全部）":        R.stat(sel, td),
            "逆風の強い時を見送り": R.stat([r for r in sel if not veto(r)], td),
            "（見送った分）":      R.stat([r for r in sel if veto(r)], td),
        }
    return out


if __name__ == "__main__":
    print("データ読み込み中...")
    assets = dataset.load_all(use_cache=True, progress=False)
    ser = R.yields()
    res = {w: run(assets, ser, w) for w in (400, 360, 440)}

    ok = True
    for g in ["主要5ペア", "残り8ペア（試し打ち）"]:
        print()
        print("=== {} ===".format(g))
        print("  {:<22}{:>8}{:>8}{:>8}{:>7}{:>7}{:>10}".format(
            "条件", "400", "360", "440", "件数", "1日", "1日期待値"))
        print("  " + "-" * 70)
        for name in ["現行（全部）", "逆風の強い時を見送り", "（見送った分）"]:
            s = res[400][g][name]
            if not s:
                print("  {:<22}{:>8}".format(name, "件数不足"))
                continue
            cells = ["{:.1f}%".format(res[w][g][name]["hit"] * 100)
                     if res[w][g][name] else "—" for w in (400, 360, 440)]
            print("  {:<22}{:>8}{:>8}{:>8}{:>7,}{:>7.2f}{:>9.3f}%".format(
                name, cells[0], cells[1], cells[2], s["n"], s["per_day"], s["daily"] * 100))
        up = all(res[w][g]["逆風の強い時を見送り"]["hit"] > res[w][g]["現行（全部）"]["hit"]
                 for w in (400, 360, 440))
        keep = res[400][g]["逆風の強い時を見送り"]["daily"] >= res[400][g]["現行（全部）"]["daily"]
        print("  → 勝率: {} / 1日の期待値: {}".format(
            "3期間とも改善" if up else "改善せず", "維持" if keep else "低下"))
        ok = ok and up

    print()
    print("=== 判定: {} ===".format(
        "両群とも3期間で勝率が上がる → 採用" if ok else "条件を満たさず → 不採用"))
    print()
    print("  採用する数値（コードに入れる形）:")
    for g in ["主要5ペア", "残り8ペア（試し打ち）"]:
        a, b = res[400][g]["現行（全部）"], res[400][g]["逆風の強い時を見送り"]
        v = res[400][g]["（見送った分）"]
        print("    {:<22} 現行{:.3f} → 見送り後{:.3f} / 見送った分{:.3f}(n={})".format(
            g, a["hit"], b["hit"], v["hit"] if v else float("nan"), v["n"] if v else 0))
        print("      windows: " + " / ".join(
            "{:.3f}".format(res[w][g]["逆風の強い時を見送り"]["hit"]) for w in (400, 360, 440)))
