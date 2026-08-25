# -*- coding: utf-8 -*-
"""フィボナッチの水準が、的中率に関係するかを測る。

このアプリでは、テクニカルの裏付けが的中率と関係しないことが既に
分かっている（4/4一致の方がむしろ低かった）。フィボナッチも同じ
可能性があるので、表示する前に測る。

試す条件は3つだけに絞る。多く試すほど、まぐれを拾いやすくなる。
  A 水準に近いときだけ（0.3%以内）
  B 水準から遠いときだけ
  C 予測の進む先に水準があるとき（水準に向かって動く予測）

判定は3標本すべてで改善すること。1つでも崩れたら不採用。
"""
import bisect
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))

import backtest
import config
import dataset
import fibonacci
import fx as fxmod

OFFSETS = (0, 1, 2)
NEAR = 0.003
LOOKBACK = 60


def stat(rows, td):
    if len(rows) < 12:
        return None
    g = [r["actual"] * (1 if r["pred"] > 0 else -1) for r in rows]
    per = {}
    for r, x in zip(rows, g):
        per.setdefault(r["ts"], []).append(x)
    daily = [sum(v) / len(v) for v in per.values()]
    m = sum(daily) / len(daily)
    sd = math.sqrt(sum((y - m) ** 2 for y in daily) / max(1, len(daily) - 1))
    mean = sum(g) / len(g)
    return dict(n=len(g), hit=sum(1 for v in g if v > 0) / len(g), mean=mean,
                t=(m / (sd / math.sqrt(len(daily)))) if sd else 0.0,
                per_day=len(g) / td)


def attach(rows, assets, lookback):
    by = {a["key"]: a for a in assets if a["kind"] == "fx"}
    for r in rows:
        a = by.get(r["key"])
        if not a:
            r["fib"] = None
            continue
        i = bisect.bisect_right(a["bars"]["t"], r["ts"]) - 1
        if i < lookback:
            r["fib"] = None
            continue
        c = fibonacci.context(a["bars"], lookback, i)
        if not c or not c["nearest"]:
            r["fib"] = None
            continue
        n = c["nearest"]
        r["fib"] = {"dist": n["distance"], "above": n["above"], "ratio": n["ratio"]}


RULES = [
    ("条件なし", lambda r: True),
    ("水準に近い（0.3%以内）", lambda r: r["fib"]["dist"] <= NEAR),
    ("水準から遠い", lambda r: r["fib"]["dist"] > NEAR),
    ("予測の先に水準がある", lambda r: (r["fib"]["above"]) == (r["pred"] > 0)),
]


def run(assets, offset, lookback=LOOKBACK):
    rows = backtest.collect(assets, config.HORIZON_FX, n_dates=400, step=3,
                            use_knn=True, kinds={"fx"}, verbose=False, offset=offset)
    td = len(set(r["ts"] for r in rows))
    attach(rows, assets, lookback)
    sig = set(config.FX_SIGNAL_PAIRS)
    base = [r for r in rows if r["key"] in sig
            and max(r["p_up"], 1 - r["p_up"]) >= config.FX_MIN_CONFIDENCE
            and r["fib"]]
    return {nm: stat([r for r in base if fn(r)], td) for nm, fn in RULES}


if __name__ == "__main__":
    print("データ読み込み中...")
    assets = dataset.load_all(use_cache=True, progress=False)
    res = {o: run(assets, o) for o in OFFSETS}

    print()
    print("=== フィボナッチの水準と的中率（選び直した5ペア・確信度56%以上）===")
    print("  {:<24}{:>8}{:>8}{:>8}{:>8}{:>7}{:>7}".format(
        "条件", "標本0", "標本1", "標本2", "平均", "件数", "1日"))
    print("  " + "-" * 70)
    base = [res[o]["条件なし"] for o in OFFSETS]
    for nm, _ in RULES:
        xs = [res[o][nm] for o in OFFSETS if res[o][nm]]
        if not xs:
            print("  {:<24}{:>8}".format(nm, "件数不足")); continue
        hits = [x["hit"] for x in xs]
        cells = ["{:.1f}%".format(h * 100) for h in hits] + ["—"] * (3 - len(hits))
        better = (nm != "条件なし" and len(xs) == 3
                  and all(res[o][nm]["hit"] > res[o]["条件なし"]["hit"] for o in OFFSETS))
        print("  {:<24}{:>8}{:>8}{:>8}{:>7.1f}%{:>7,}{:>7.2f}{}".format(
            nm, cells[0], cells[1], cells[2], sum(hits) / len(hits) * 100,
            sum(x["n"] for x in xs) // len(xs),
            sum(x["per_day"] for x in xs) / len(xs), "  ○" if better else ""))

    print()
    print("=== 波の取り方を変えても同じか（水準に近い条件）===")
    for lb in (30, 120):
        r2 = {o: run(assets, o, lb) for o in OFFSETS}
        xs = [r2[o]["水準に近い（0.3%以内）"] for o in OFFSETS]
        bs = [r2[o]["条件なし"] for o in OFFSETS]
        if not all(xs):
            print("  {}本: 件数不足".format(lb)); continue
        print("  {:>3}本: {} （条件なし {}）".format(
            lb, " / ".join("{:.1f}%".format(x["hit"] * 100) for x in xs),
            " / ".join("{:.1f}%".format(b["hit"] * 100) for b in bs)))
    print()
    print("  ○ = 3標本すべてで改善。1つでも崩れたら不採用。")
