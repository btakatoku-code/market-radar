# -*- coding: utf-8 -*-
"""経済指標・曜日で見つかった差が本物かを確かめる。

的中率が上がる切り口はいくつも見つかるが、多くは偶然。
期間を前半・後半に割って、どちらでも同じ向きに出るかを見る。
片方でしか出ないものは採用しない。
"""
import datetime
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))

import backtest
import config
import dataset
import events

JST = datetime.timezone(datetime.timedelta(hours=9))
PAIR_CUR = {
    "USDJPY=X": ("USD", "JPY"), "EURJPY=X": ("EUR", "JPY"),
    "GBPJPY=X": ("GBP", "JPY"), "AUDJPY=X": ("AUD", "JPY"),
    "EURUSD=X": ("EUR", "USD"), "NZDJPY=X": ("NZD", "JPY"),
    "CADJPY=X": ("CAD", "JPY"), "CHFJPY=X": ("CHF", "JPY"),
    "GBPUSD=X": ("GBP", "USD"), "AUDUSD=X": ("AUD", "USD"),
    "NZDUSD=X": ("NZD", "USD"), "USDCHF=X": ("USD", "CHF"),
    "USDCAD=X": ("USD", "CAD"), "EURGBP=X": ("EUR", "GBP"),
}


def _t(vals):
    n = len(vals)
    if n < 2:
        return 0.0
    m = sum(vals) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in vals) / (n - 1))
    return (m / (sd / math.sqrt(n))) if sd else 0.0


def stat(rows):
    if len(rows) < 15:
        return None
    g = [r["actual"] * (1 if r["pred"] > 0 else -1) for r in rows]
    per = {}
    for r, x in zip(rows, g):
        per.setdefault(r["ts"], []).append(x)
    daily = [sum(v) / len(v) for v in per.values()]
    return dict(n=len(rows), hit=sum(1 for x in g if x > 0) / len(g),
                mean=sum(g) / len(g), t=_t(daily), days=len(daily))


def show(label, sel, half_a, half_b):
    a, b, w = stat(sel), stat(half_a), stat(half_b)
    def f(s):
        return "—" if not s else "{:>5.1f}% (t{:>5.2f}, {:>3}日)".format(
            s["hit"] * 100, s["t"], s["days"])
    ok = "○" if (b and w and b["hit"] > 0.5 and w["hit"] > 0.5) else "×"
    print("  {:<26}{:<24}{:<24}{:<24}{}".format(
        label, f(a), f(b), f(w), ok))


if __name__ == "__main__":
    print("データ読み込み中...")
    assets = dataset.load_all(use_cache=True, progress=False)
    rows = backtest.collect(assets, config.HORIZON_FX, n_dates=400, step=3,
                            use_knn=True, kinds={"fx"}, verbose=False)

    tss = sorted(set(r["ts"] for r in rows))
    need = set()
    for ts in tss:
        d = datetime.datetime.fromtimestamp(ts, JST).date()
        need.add(d.isoformat())
        need.add((d + datetime.timedelta(days=1)).isoformat())
    ev = events.economic_events(sorted(need))

    for r in rows:
        d = datetime.datetime.fromtimestamp(r["ts"], JST).date()
        nxt = events.econ_summary(ev, (d + datetime.timedelta(days=1)).isoformat())
        cur = set(PAIR_CUR.get(r["key"], ()))
        r["mine"] = bool(cur & set(nxt["currencies"]))
        r["wd"] = d.weekday()

    conf = config.FX_MIN_CONFIDENCE
    strong = [r for r in rows if max(r["p_up"], 1 - r["p_up"]) >= conf]
    mid = tss[len(tss) // 2]
    A = lambda sel: [r for r in sel if r["ts"] < mid]
    B = lambda sel: [r for r in sel if r["ts"] >= mid]

    print()
    print("=== 前半・後半に割ったときの的中率（確信度{:.0f}%以上）===".format(conf * 100))
    print("  {:<26}{:<24}{:<24}{:<24}{}".format("区分", "全期間", "前半", "後半", "両方50%超"))
    print("  " + "-" * 122)
    show("全体（基準）", strong, A(strong), B(strong))
    print()
    mine = [r for r in strong if r["mine"]]
    nomine = [r for r in strong if not r["mine"]]
    show("自通貨の指標あり", mine, A(mine), B(mine))
    show("自通貨の指標なし", nomine, A(nomine), B(nomine))
    print()
    for wd, name in enumerate(["月", "火", "水", "木", "金"]):
        sel = [r for r in strong if r["wd"] == wd]
        show("{}曜日".format(name), sel, A(sel), B(sel))
    print()
    combo = [r for r in strong if r["mine"] and r["wd"] in (0, 2)]
    show("月水 かつ 自通貨の指標あり", combo, A(combo), B(combo))
    print()
    print("  ※ 前半・後半のどちらかで50%を割る区分は、たまたま当たっていた可能性が高い。")
