# -*- coding: utf-8 -*-
"""勝率を最大にする組み合わせを総当たりで探す。

勝率は絞れば上がるが、そのぶん機会が減る。1か月に1回しか出ないシグナルは
実用にならないので、勝率と頻度を必ず並べて見る。

さらに、勝率が高く見えるだけの偶然を排除するため、期間を前半・後半に割って
どちらでも成立するものだけを候補とする。
"""
import datetime
import itertools
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))

import backtest
import config
import dataset
import events
import fx as fxmod

JST = datetime.timezone(datetime.timedelta(hours=9))

PAIR_SETS = {
    "主要5（現行）": ["USDJPY=X", "EURJPY=X", "GBPJPY=X", "AUDJPY=X", "EURUSD=X"],
    "実測上位5": ["NZDUSD=X", "GBPJPY=X", "USDJPY=X", "AUDUSD=X", "AUDJPY=X"],
    "実測上位3": ["NZDUSD=X", "USDJPY=X", "GBPJPY=X"],
    "円絡みのみ": ["USDJPY=X", "EURJPY=X", "GBPJPY=X", "AUDJPY=X", "NZDJPY=X", "CADJPY=X"],
    "全14ペア": None,
}
CONFS = [0.53, 0.56, 0.60, 0.65]
TIMINGS = {
    "条件なし": lambda r: True,
    "自通貨の指標あり": lambda r: r["mine"],
    "月水のみ": lambda r: r["wd"] in (0, 2),
    "月水＋自通貨指標": lambda r: r["wd"] in (0, 2) and r["mine"],
    "金曜を除く": lambda r: r["wd"] != 4,
}


def _t(vals):
    n = len(vals)
    if n < 2:
        return 0.0
    m = sum(vals) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in vals) / (n - 1))
    return (m / (sd / math.sqrt(n))) if sd else 0.0


def stat(rows, total_days):
    if len(rows) < 12:
        return None
    g = [r["actual"] * (1 if r["pred"] > 0 else -1) for r in rows]
    per = {}
    for r, x in zip(rows, g):
        per.setdefault(r["ts"], []).append(x)
    daily = [sum(v) / len(v) for v in per.values()]
    return dict(n=len(rows), hit=sum(1 for x in g if x > 0) / len(g),
                mean=sum(g) / len(g), t=_t(daily), days=len(daily),
                per_day=len(rows) / total_days)


if __name__ == "__main__":
    print("データ読み込み中...")
    assets = dataset.load_all(use_cache=True, progress=False)
    rows = backtest.collect(assets, config.HORIZON_FX, n_dates=400, step=3,
                            use_knn=True, kinds={"fx"}, verbose=False)
    tss = sorted(set(r["ts"] for r in rows))
    total_days = len(tss)
    mid = tss[len(tss) // 2]

    need = set()
    for ts in tss:
        d = datetime.datetime.fromtimestamp(ts, JST).date()
        need.add(d.isoformat())
        need.add((d + datetime.timedelta(days=1)).isoformat())
    ev = events.economic_events(sorted(need))

    for r in rows:
        d = datetime.datetime.fromtimestamp(r["ts"], JST).date()
        nxt = events.econ_summary(ev, (d + datetime.timedelta(days=1)).isoformat())
        cur = set(fxmod.PAIR_CURRENCIES.get(r["key"], ()))
        r["mine"] = bool(cur & set(nxt["currencies"]))
        r["wd"] = d.weekday()          # 予測を出す日の曜日（検証の定義に合わせる）
        r["conf"] = max(r["p_up"], 1 - r["p_up"])

    print("  予測 {:,}件 / {}時点".format(len(rows), total_days))
    print()
    print("=== 勝率を最大にする組み合わせ（総当たり）===")
    print("  {:<16}{:>6} {:<16}{:>7}{:>8}{:>7}{:>8}{:>8} {}".format(
        "通貨ペア", "確信度", "タイミング", "件数", "勝率", "1日", "前半", "後半", "頑健"))
    print("  " + "-" * 100)

    results = []
    for pname, pairs in PAIR_SETS.items():
        base = rows if pairs is None else [r for r in rows if r["key"] in set(pairs)]
        for conf in CONFS:
            sel0 = [r for r in base if r["conf"] >= conf]
            for tname, fn in TIMINGS.items():
                sel = [r for r in sel0 if fn(r)]
                s = stat(sel, total_days)
                if not s or s["per_day"] < 0.15:      # 1週間に1回未満は実用外
                    continue
                a = stat([r for r in sel if r["ts"] < mid], total_days / 2)
                b = stat([r for r in sel if r["ts"] >= mid], total_days / 2)
                robust = bool(a and b and a["hit"] > 0.52 and b["hit"] > 0.52)
                results.append((pname, conf, tname, s, a, b, robust))

    results.sort(key=lambda x: -x[3]["hit"])
    for pname, conf, tname, s, a, b, robust in results[:22]:
        print("  {:<16}{:>5.0f}% {:<16}{:>7,}{:>7.1f}%{:>7.2f}{:>7}{:>8} {}".format(
            pname, conf * 100, tname, s["n"], s["hit"] * 100, s["per_day"],
            "{:.1f}%".format(a["hit"] * 100) if a else "—",
            "{:.1f}%".format(b["hit"] * 100) if b else "—",
            "○" if robust else "×"))

    print()
    print("=== 頑健なものだけを勝率順に（前半・後半とも52%超）===")
    ok = [x for x in results if x[6]]
    print("  {:<16}{:>6} {:<16}{:>7}{:>8}{:>7}{:>7}".format(
        "通貨ペア", "確信度", "タイミング", "件数", "勝率", "1日", "t値"))
    print("  " + "-" * 78)
    for pname, conf, tname, s, a, b, _ in ok[:12]:
        print("  {:<16}{:>5.0f}% {:<16}{:>7,}{:>7.1f}%{:>7.2f}{:>7.2f}".format(
            pname, conf * 100, tname, s["n"], s["hit"] * 100, s["per_day"], s["t"]))
    print()
    print("  ※ 1日 = 1日あたりの平均シグナル数。勝率を上げるほどここが減る。")
    print("  ※ 総当たりなので、上位に来たものほど偶然の可能性も上がる。")
    print("     前半・後半の両方で成立しているかを必ず見ること。")
