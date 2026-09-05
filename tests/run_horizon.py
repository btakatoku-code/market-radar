# -*- coding: utf-8 -*-
"""FXの予測期間を変えると成績がどう変わるかを測る。

いまは24時間（翌営業日）。1か月（21営業日）にすると:
  良くなりうる点  1回の値幅が大きくなるので、スプレッドの重みが下がる
  悪くなりうる点  シグナルの回数が減る／スワップが21日ぶん積み上がる

判断は「1回あたりの勝率」ではなく「同じ期間でいくら期待できるか」で行う。
勝率が上がっても回数が20分の1になれば意味がない。
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
HORIZONS = (1, 5, 21)
PRICE = {}


def stat(rows, td, horizon):
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
    net = mean - cost
    # 1営業日あたりに直した期待値。期間が違うものを比べるにはこれが要る。
    per_day_signals = len(g) / td
    daily_net = net * per_day_signals / horizon if horizon else 0
    return dict(n=len(g), hit=sum(1 for v in g if v > 0) / len(g), mean=mean,
                cost=cost, net=net, per_day=per_day_signals,
                t=(m / (sd / math.sqrt(len(daily)))) if sd else 0.0,
                daily_net=daily_net)


def run(assets, horizon, offset):
    rows = backtest.collect(assets, horizon, n_dates=400, step=3,
                            use_knn=True, kinds={"fx"}, verbose=False, offset=offset)
    td = len(set(r["ts"] for r in rows))
    sig = set(config.FX_SIGNAL_PAIRS)
    sel = [r for r in rows if r["key"] in sig
           and max(r["p_up"], 1 - r["p_up"]) >= config.FX_MIN_CONFIDENCE]
    allr = [r for r in rows if r["key"] in sig]
    return {"確信度56%以上": stat(sel, td, horizon), "全予測": stat(allr, td, horizon)}


if __name__ == "__main__":
    print("データ読み込み中...")
    assets = dataset.load_all(use_cache=True, progress=False)
    for a in assets:
        if a["kind"] == "fx":
            cs = [c for c in a["bars"]["c"][-1200:] if c]
            if cs:
                PRICE[a["key"]] = sum(cs) / len(cs)

    res = {}
    for h in HORIZONS:
        res[h] = {o: run(assets, h, o) for o in OFFSETS}
        print("  {}営業日 済み".format(h))

    for grp in ("確信度56%以上", "全予測"):
        print()
        print("=== {} ===".format(grp))
        print("  {:<12}{:>8}{:>8}{:>8}{:>8}{:>7}{:>10}{:>10}{:>9}{:>7}".format(
            "予測期間", "標本0", "標本1", "標本2", "勝率平均", "振れ",
            "1回あたり", "コスト後", "1日の回数", "t値"))
        print("  " + "-" * 88)
        for h in HORIZONS:
            xs = [res[h][o][grp] for o in OFFSETS if res[h][o][grp]]
            if not xs:
                print("  {:<12}{:>8}".format("{}営業日".format(h), "件数不足")); continue
            hits = [x["hit"] for x in xs]
            cells = ["{:.1f}%".format(v * 100) for v in hits] + ["—"] * (3 - len(hits))
            lab = {1: "24時間", 5: "1週間", 21: "1か月"}[h]
            print("  {:<12}{:>8}{:>8}{:>8}{:>7.1f}%{:>6.1f}pt{:>10}{:>10}{:>9.2f}{:>7.2f}".format(
                lab, cells[0], cells[1], cells[2],
                sum(hits) / len(hits) * 100, (max(hits) - min(hits)) * 100,
                "{:+.3f}%".format(sum(x["mean"] for x in xs) / len(xs) * 100),
                "{:+.3f}%".format(sum(x["net"] for x in xs) / len(xs) * 100),
                sum(x["per_day"] for x in xs) / len(xs),
                sum(x["t"] for x in xs) / len(xs)))

    print()
    print("=== 同じ期間でいくら期待できるか（1営業日あたりに直した値）===")
    print("  {:<12}{:>14}{:>16}{:>12}".format("予測期間", "1日の期待値", "20営業日で", "資金10万円なら"))
    print("  " + "-" * 56)
    for h in HORIZONS:
        xs = [res[h][o]["確信度56%以上"] for o in OFFSETS if res[h][o]["確信度56%以上"]]
        if not xs:
            continue
        dn = sum(x["daily_net"] for x in xs) / len(xs)
        lab = {1: "24時間", 5: "1週間", 21: "1か月"}[h]
        print("  {:<12}{:>13.4f}%{:>15.2f}%{:>11,.0f}円".format(
            lab, dn * 100, dn * 20 * 100, dn * 100000))
    print()
    print("  ※ 1回の勝率が上がっても、回数が減れば同じ期間で得られる額は下がる。")
    print("  ※ スワップは未計上。1か月保有なら21日ぶん積み上がるので、")
    print("     24時間の場合より21倍効く（方向によって受け取りにも支払いにもなる）。")
