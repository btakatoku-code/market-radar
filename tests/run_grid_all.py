# -*- coding: utf-8 -*-
"""いま採用している数値を、時点の並びを3通りに変えて全部測り直す。

これまでの検査（n_dates を 400/360/440 と変える）は時点の並びを共有しており、
1日ずらすと結果が変わる種類の揺れを見逃していた。金利の条件はそれで
採用してしまった。ここでは互いに重ならない3標本で測る。

測るもの:
  1. 確信度の区分ごとの勝率（アプリに表示している数字そのもの）
  2. 金利による見送りの効果
  3. テクニカルの裏付け（4/4・3/4以上・2/4以下）で絞った場合
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

OFFSETS = (0, 1, 2)
LAG, BIG = 1, 0.27


def agree_count(r):
    up = r["pred"] > 0
    return sum([(r["macd"] > 0) == up, (r["trend"] > 0) == up,
                (r["momentum"] > 0) == up, (r["rsi"] > 50) == up])


def run(assets, ser, offset):
    rows = backtest.collect(assets, config.HORIZON_FX, n_dates=400, step=3,
                            use_knn=True, kinds={"fx"}, verbose=False, offset=offset)
    td = len(set(r["ts"] for r in rows))
    A.attach_lagged(rows, ser, LAG)
    for r in rows:
        r["conf"] = max(r["p_up"], 1 - r["p_up"])
        r["ag"] = agree_count(r)
    maj = [r for r in rows if r["key"] in R.MAJOR]
    out = {}
    for c in (0.53, 0.56, 0.60):
        out["確信度{:.0f}%以上".format(c * 100)] = R.stat([r for r in maj if r["conf"] >= c], td)
    sel = [r for r in maj if r["conf"] >= config.FX_MIN_CONFIDENCE and r["rate20"] is not None]
    veto = lambda r: abs(r["rate20"]) >= BIG and (r["rate20"] > 0) != (r["pred"] > 0)
    out["金利で見送り後"] = R.stat([r for r in sel if not veto(r)], td)
    s56 = [r for r in maj if r["conf"] >= config.FX_MIN_CONFIDENCE]
    out["裏付け4/4のみ"] = R.stat([r for r in s56 if r["ag"] == 4], td)
    out["裏付け3/4以上"] = R.stat([r for r in s56 if r["ag"] >= 3], td)
    out["裏付け2/4以下"] = R.stat([r for r in s56 if r["ag"] <= 2], td)
    return out


NAMES = ["確信度53%以上", "確信度56%以上", "確信度60%以上", "金利で見送り後",
         "裏付け4/4のみ", "裏付け3/4以上", "裏付け2/4以下"]

if __name__ == "__main__":
    print("データ読み込み中...")
    assets = dataset.load_all(use_cache=True, progress=False)
    ser = R.yields()
    res = {o: run(assets, ser, o) for o in OFFSETS}

    print()
    print("=== 主要5ペア・時点の並びを1日ずつずらして測定 ===")
    print("  {:<16}{:>9}{:>9}{:>9}{:>9}{:>8}{:>7}".format(
        "条件", "ずらし0", "ずらし1", "ずらし2", "平均", "振れ幅", "件数"))
    print("  " + "-" * 70)
    for name in NAMES:
        vals = [res[o][name]["hit"] if res[o][name] else None for o in OFFSETS]
        ok = [v for v in vals if v is not None]
        if not ok:
            print("  {:<16}{:>9}".format(name, "件数不足"))
            continue
        cells = ["{:.1f}%".format(v * 100) if v is not None else "—" for v in vals]
        n = sum(res[o][name]["n"] for o in OFFSETS if res[o][name]) // len(ok)
        print("  {:<16}{:>9}{:>9}{:>9}{:>8.1f}%{:>7.1f}pt{:>7,}".format(
            name, cells[0], cells[1], cells[2],
            sum(ok) / len(ok) * 100, (max(ok) - min(ok)) * 100, n))
    print()
    print("  平均が実力に近い値。振れ幅は、どれだけ運に左右されるかの目安。")
    print("  3標本の平均なので、単独の標本より信頼できる。")
