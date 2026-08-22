# -*- coding: utf-8 -*-
"""市場環境による絞り込みを外した場合の数値を、3標本で測る。

レジームありは平均56.7%（振れ4.8pt）、なしは平均55.7%（振れ1.8pt）。
差は平均+1.0ptだが標本ごとに符号が変わる。効果が示せない仕掛けを
残しておく理由はないので、外した場合の数値を揃えて判断する。

ついでに、アプリに載せる 1回あたりの損益・t値・件数も3標本で測る。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))

import backtest
import config
import dataset
import run_rates as R

OFFSETS = (0, 1, 2)
CONFS = (0.53, 0.56, 0.60)


def measure(mode):
    assets = dataset.load_all(use_cache=True, progress=False, regime_mode=mode)
    per = {c: [] for c in CONFS}
    base = []
    for o in OFFSETS:
        rows = backtest.collect(assets, config.HORIZON_FX, n_dates=400, step=3,
                                use_knn=True, kinds={"fx"}, verbose=False, offset=o)
        td = len(set(r["ts"] for r in rows))
        maj = [r for r in rows if r["key"] in R.MAJOR]
        base.append(R.stat(maj, td))
        for c in CONFS:
            per[c].append(R.stat([r for r in maj
                                  if max(r["p_up"], 1 - r["p_up"]) >= c], td))
    return per, base


def show(title, per, base):
    print()
    print("=== {} ===".format(title))
    print("  {:<12}{:>8}{:>8}{:>8}{:>8}{:>8}{:>8}{:>7}{:>7}".format(
        "確信度", "並び0", "並び1", "並び2", "平均", "振れ", "1回あたり", "t値", "件数"))
    print("  " + "-" * 76)
    rows = [("全予測", base)] + [("{:.0f}%以上".format(c * 100), per[c]) for c in CONFS]
    out = {}
    for name, xs in rows:
        ok = [x for x in xs if x]
        if not ok:
            print("  {:<12}{:>8}".format(name, "件数不足"))
            continue
        hits = [x["hit"] for x in ok]
        missing = len(xs) - len(ok)   # 件数不足で測れなかった標本の数
        avg = sum(hits) / len(hits)
        mean = sum(x["mean"] for x in ok) / len(ok)
        t = sum(x["t"] for x in ok) / len(ok)
        n = sum(x["n"] for x in ok) // len(ok)
        pd = sum(x["per_day"] for x in ok) / len(ok)
        cells = ["{:.1f}%".format(h * 100) for h in hits]
        while len(cells) < 3:
            cells.append("—")          # 件数不足の標本は空欄にする
        print("  {:<12}{:>8}{:>8}{:>8}{:>7.1f}%{:>7.1f}pt{:>9}{:>7.2f}{:>7,}".format(
            name, cells[0], cells[1], cells[2],
            avg * 100, (max(hits) - min(hits)) * 100,
            "{:+.3f}%".format(mean * 100), t, n))
        out[name] = dict(hit=round(avg, 3), samples=len(ok), missing=missing, by_offset=[round(h, 3) for h in hits],
                         spread=round(max(hits) - min(hits), 3), mean=round(mean, 5),
                         t=round(t, 2), n=n, per_day=round(pd, 2))
    return out


if __name__ == "__main__":
    print("測定中...")
    res = {}
    for mode, label in [("none", "絞り込みなし"), ("risk_breadth9", "リスク×広がり(9段階)")]:
        per, base = measure(mode)
        res[mode] = show(label + "（主要5ペア）", per, base)
    print()
    print("=== コードに入れる値（絞り込みなし）===")
    import json
    print(json.dumps(res["none"], ensure_ascii=False, indent=1))
