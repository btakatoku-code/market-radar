# -*- coding: utf-8 -*-
"""裏付けが3/4以上のものだけを見る場合の実測値を出す。

表示を絞ると、実際に売買する対象が変わる。いま載せている
「確信度56%以上で60.0%」は絞る前の数字なので、そのままは使えない。

判定基準はこれまでと同じ:
  主要5ペアと残り8ペアの両方で、400／360／440の3期間すべてを見る。
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

LAG = 1
BIG = 0.27


def agree_count(r):
    """fx.confirmation と同じ数え方（4項目のうちいくつが予測と同じ向きか）"""
    up = r["pred"] > 0
    return sum([(r["macd"] > 0) == up, (r["trend"] > 0) == up,
                (r["momentum"] > 0) == up, (r["rsi"] > 50) == up])


def run(assets, ser, n_dates):
    rows = backtest.collect(assets, config.HORIZON_FX, n_dates=n_dates, step=3,
                            use_knn=True, kinds={"fx"}, verbose=False)
    td = len(set(r["ts"] for r in rows))
    A.attach_lagged(rows, ser, LAG)
    base = [r for r in rows
            if max(r["p_up"], 1 - r["p_up"]) >= config.FX_MIN_CONFIDENCE
            and r["rate20"] is not None
            and not (abs(r["rate20"]) >= BIG and (r["rate20"] > 0) != (r["pred"] > 0))]
    for r in base:
        r["ag"] = agree_count(r)
    out = {}
    for g, sel in [("主要5ペア", [r for r in base if r["key"] in R.MAJOR]),
                   ("残り8ペア（試し打ち）", [r for r in base if r["key"] not in R.MAJOR])]:
        out[g] = {
            "いまの表示（全部）": R.stat(sel, td),
            "4/4 のみ":         R.stat([r for r in sel if r["ag"] == 4], td),
            "3/4 以上":         R.stat([r for r in sel if r["ag"] >= 3], td),
            "2/4 以下（外す分）": R.stat([r for r in sel if r["ag"] <= 2], td),
        }
    return out


if __name__ == "__main__":
    print("データ読み込み中...")
    assets = dataset.load_all(use_cache=True, progress=False)
    ser = R.yields()
    res = {w: run(assets, ser, w) for w in (400, 360, 440)}

    names = ["いまの表示（全部）", "4/4 のみ", "3/4 以上", "2/4 以下（外す分）"]
    for g in ["主要5ペア", "残り8ペア（試し打ち）"]:
        print()
        print("=== {} （金利の逆風を除いた後）===".format(g))
        print("  {:<20}{:>8}{:>8}{:>8}{:>7}{:>7}{:>10}".format(
            "裏付け", "400", "360", "440", "件数", "1日", "1日期待値"))
        print("  " + "-" * 68)
        for name in names:
            s = res[400][g][name]
            if not s:
                print("  {:<20}{:>8}".format(name, "件数不足"))
                continue
            cells = ["{:.1f}%".format(res[w][g][name]["hit"] * 100)
                     if res[w][g][name] else "—" for w in (400, 360, 440)]
            better = (name not in ("いまの表示（全部）", "2/4 以下（外す分）") and
                      all(res[w][g][name] and
                          res[w][g][name]["hit"] > res[w][g]["いまの表示（全部）"]["hit"]
                          for w in (400, 360, 440)))
            print("  {:<20}{:>8}{:>8}{:>8}{:>7,}{:>7.2f}{:>9.3f}%{}".format(
                name, cells[0], cells[1], cells[2], s["n"], s["per_day"],
                s["daily"] * 100, " ○" if better else ""))
    print()
    print("  ○ = 3期間すべてで「全部表示」を上回る")
    print("  1日の回数も見ること。絞ると勝率は上がるが、出る日が減る。")
