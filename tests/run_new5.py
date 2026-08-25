# -*- coding: utf-8 -*-
"""選び直した5ペアで、公表している数値を測り直す。

ペアの構成が変わったので、確信度の区分ごとの勝率も、1回あたりの損益も、
すべて測り直す必要がある。旧5ペアの数字をそのまま載せてはいけない。
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))

import backtest
import config
import dataset
import fx as fxmod

OFFSETS = (0, 1, 2)
CONFS = (0.53, 0.56, 0.60)
PRICE = {}


def stat(rows, td):
    if len(rows) < 10:
        return None
    g = [r["actual"] * (1 if r["pred"] > 0 else -1) for r in rows]
    per = {}
    for r, x in zip(rows, g):
        per.setdefault(r["ts"], []).append(x)
    daily = [sum(v) / len(v) for v in per.values()]
    m = sum(daily) / len(daily)
    sd = math.sqrt(sum((y - m) ** 2 for y in daily) / max(1, len(daily) - 1))
    mean = sum(g) / len(g)
    cost = sum(fxmod.spread_pct(r["key"], PRICE.get(r["key"])) * 2 for r in rows) / len(rows)
    return dict(n=len(g), hit=sum(1 for v in g if v > 0) / len(g), mean=mean,
                net=mean - cost, cost=cost,
                t=(m / (sd / math.sqrt(len(daily)))) if sd else 0.0,
                per_day=len(g) / td)


if __name__ == "__main__":
    print("データ読み込み中...")
    assets = dataset.load_all(use_cache=True, progress=False)
    for a in assets:
        if a["kind"] == "fx":
            cs = [c for c in a["bars"]["c"][-1200:] if c]
            if cs:
                PRICE[a["key"]] = sum(cs) / len(cs)
    sig = set(config.FX_SIGNAL_PAIRS)
    res = {}
    for o in OFFSETS:
        rows = backtest.collect(assets, config.HORIZON_FX, n_dates=400, step=3,
                                use_knn=True, kinds={"fx"}, verbose=False, offset=o)
        td = len(set(r["ts"] for r in rows))
        maj = [r for r in rows if r["key"] in sig]
        res[o] = {"全予測": stat(maj, td)}
        for c in CONFS:
            res[o]["{:.0f}%以上".format(c * 100)] = stat(
                [r for r in maj if max(r["p_up"], 1 - r["p_up"]) >= c], td)
        print("  標本{} 済み".format(o))

    names = ["全予測"] + ["{:.0f}%以上".format(c * 100) for c in CONFS]
    print()
    print("=== 選び直した5ペアの実測（3標本）===")
    print("  {:<10}{:>8}{:>8}{:>8}{:>8}{:>7}{:>10}{:>9}{:>7}{:>7}".format(
        "確信度", "標本0", "標本1", "標本2", "平均", "振れ", "1回あたり",
        "コスト後", "t値", "件数"))
    print("  " + "-" * 84)
    out = {}
    for nm in names:
        xs = [res[o][nm] for o in OFFSETS if res[o][nm]]
        if not xs:
            print("  {:<10}{:>8}".format(nm, "件数不足")); continue
        hits = [x["hit"] for x in xs]
        avg = sum(hits) / len(hits)
        cells = ["{:.1f}%".format(h * 100) for h in hits] + ["—"] * (3 - len(hits))
        mean = sum(x["mean"] for x in xs) / len(xs)
        net = sum(x["net"] for x in xs) / len(xs)
        t = sum(x["t"] for x in xs) / len(xs)
        n = sum(x["n"] for x in xs) // len(xs)
        pd = sum(x["per_day"] for x in xs) / len(xs)
        print("  {:<10}{:>8}{:>8}{:>8}{:>7.1f}%{:>6.1f}pt{:>10}{:>9}{:>7.2f}{:>7,}".format(
            nm, cells[0], cells[1], cells[2], avg * 100,
            (max(hits) - min(hits)) * 100, "{:+.3f}%".format(mean * 100),
            "{:+.3f}%".format(net * 100), t, n))
        out[nm] = dict(hit=round(avg, 3), by_offset=[round(h, 3) for h in hits],
                       spread=round(max(hits) - min(hits), 3), mean=round(mean, 5),
                       net=round(net, 5), t=round(t, 2), n=n, per_day=round(pd, 2))
    print()
    import json
    print(json.dumps(out, ensure_ascii=False, indent=1))
