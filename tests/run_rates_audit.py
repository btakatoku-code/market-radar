# -*- coding: utf-8 -*-
"""金利の効果が「先読み」でないことを確かめる。

これだけ効果が大きいと、まず疑うべきは実装の穴で、
「予測時点ではまだ知りえない金利を使ってしまっている」可能性。

確かめ方: 金利データをわざと余分に遅らせる。
本物なら、1日・3日遅らせても効果はある程度残る。
先読みが原因なら、遅らせた瞬間に消える。
"""
import bisect
import datetime
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))

import backtest
import config
import dataset
import run_rates as R

JST = datetime.timezone(datetime.timedelta(hours=9))
DAY = 86400


def attach_lagged(rows, ser, lag_days):
    ts = [x["t"] for x in ser]
    for r in rows:
        cut = r["ts"] - lag_days * DAY
        i = bisect.bisect_left(ts, cut) - 1
        x = ser[i] if i >= 0 else None
        sign = R.USD_SIGN.get(r["key"])
        if not x or x["chg20"] is None or sign is None:
            r["rate20"] = None
            r["used_t"] = None
            continue
        r["rate20"] = sign * x["chg20"]
        r["used_t"] = x["t"]


def measure(rows, td, lag, ser):
    attach_lagged(rows, ser, lag)
    base = [r for r in rows
            if max(r["p_up"], 1 - r["p_up"]) >= config.FX_MIN_CONFIDENCE
            and r["rate20"] is not None]
    out = {}
    for gname, sel in [("主要5", [r for r in base if r["key"] in R.MAJOR]),
                       ("残り8", [r for r in base if r["key"] not in R.MAJOR])]:
        agree = [r for r in sel if (r["rate20"] > 0) == (r["pred"] > 0)]
        out[gname] = (R.stat(sel, td), R.stat(agree, td))
    return out


if __name__ == "__main__":
    print("データ読み込み中...")
    assets = dataset.load_all(use_cache=True, progress=False)
    ser = R.yields()
    rows = backtest.collect(assets, config.HORIZON_FX, n_dates=400, step=3,
                            use_knn=True, kinds={"fx"}, verbose=False)
    td = len(set(r["ts"] for r in rows))

    # 1. 時刻の関係を目で確認する
    attach_lagged(rows, ser, 0)
    print()
    print("=== 使っている金利データの時刻（先読みしていないか）===")
    shown = 0
    for r in rows:
        if r.get("used_t") and shown < 5:
            p = datetime.datetime.fromtimestamp(r["ts"], JST)
            u = datetime.datetime.fromtimestamp(r["used_t"], JST)
            print("   予測 {}  ←  金利 {}  ({:.1f}日前)".format(
                p.strftime("%Y-%m-%d %H:%M"), u.strftime("%Y-%m-%d %H:%M"),
                (r["ts"] - r["used_t"]) / DAY))
            shown += 1
    gaps = [(r["ts"] - r["used_t"]) / DAY for r in rows if r.get("used_t")]
    print("   間隔: 最小{:.2f}日 / 中央{:.2f}日 / 最大{:.2f}日".format(
        min(gaps), sorted(gaps)[len(gaps) // 2], max(gaps)))

    # 2. わざと遅らせて効果が残るか
    print()
    print("=== 金利データを余分に遅らせたとき（400時点）===")
    print("  {:<12}{:>10}{:>10}{:>10}{:>10}".format(
        "遅らせ量", "主要5 条件なし", "→同じ向き", "残り8 条件なし", "→同じ向き"))
    print("  " + "-" * 54)
    for lag in (0, 1, 3, 7):
        m = measure(rows, td, lag, ser)
        f = lambda x: "{:.1f}%".format(x["hit"] * 100) if x else "—"
        print("  {:<12}{:>10}{:>10}{:>10}{:>10}".format(
            "{}日".format(lag), f(m["主要5"][0]), f(m["主要5"][1]),
            f(m["残り8"][0]), f(m["残り8"][1])))

    # 3. ペア別に広く効いているか（1ペアの偶然ではないか）
    print()
    print("=== ペア別（400時点・遅らせ0日）===")
    attach_lagged(rows, ser, 0)
    base = [r for r in rows
            if max(r["p_up"], 1 - r["p_up"]) >= config.FX_MIN_CONFIDENCE
            and r["rate20"] is not None]
    print("  {:<12}{:>10}{:>12}{:>8}  {}".format("ペア", "条件なし", "同じ向き", "件数", "差"))
    print("  " + "-" * 52)
    better = 0
    total = 0
    for k in sorted(set(r["key"] for r in base)):
        rs = [r for r in base if r["key"] == k]
        ag = [r for r in rs if (r["rate20"] > 0) == (r["pred"] > 0)]
        a, b = R.stat(rs, td), R.stat(ag, td)
        if not a or not b:
            continue
        total += 1
        if b["hit"] > a["hit"]:
            better += 1
        print("  {:<12}{:>9.1f}%{:>11.1f}%{:>8,}  {:+.1f}pt{}".format(
            k.replace("=X", ""), a["hit"] * 100, b["hit"] * 100, b["n"],
            (b["hit"] - a["hit"]) * 100, "  ◯" if b["hit"] > a["hit"] else ""))
    print("  改善したペア: {}/{}".format(better, total))
