# -*- coding: utf-8 -*-
"""COTの逆張り条件が本物かを、条件作りに使っていないペアで確かめる。

run_cot.py では主要5ペアで8通りを試し、逆張り系の2つが3期間とも改善した。
8通り試して2つ通ったのだから、まぐれの可能性を潰す必要がある。

いちばん強い確認方法は、条件を決めるのに一切使っていない
残り10ペアで同じことが起きるかを見ること。
"""
import datetime
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))

import backtest
import config
import cot
import dataset

JST = datetime.timezone(datetime.timedelta(hours=9))
MAJOR = set(config.FX_SIGNAL_PAIRS)

TILT = {
    "USDJPY=X": [("JPY", -1)],
    "EURUSD=X": [("EUR", +1)],
    "EURJPY=X": [("EUR", +1), ("JPY", -1)],
    "GBPJPY=X": [("GBP", +1), ("JPY", -1)],
    "AUDJPY=X": [("AUD", +1), ("JPY", -1)],
    # ここから下は条件作りに使っていない（試し打ち用）
    "GBPUSD=X": [("GBP", +1)],
    "AUDUSD=X": [("AUD", +1)],
    "NZDUSD=X": [("NZD", +1)],
    "USDCAD=X": [("CAD", -1)],
    "USDCHF=X": [("CHF", -1)],
    "NZDJPY=X": [("NZD", +1), ("JPY", -1)],
    "CADJPY=X": [("CAD", +1), ("JPY", -1)],
    "CHFJPY=X": [("CHF", +1), ("JPY", -1)],
    "EURGBP=X": [("EUR", +1), ("GBP", -1)],
    "EURCHF=X": [("EUR", +1), ("CHF", -1)],
}
CURRENCIES = ["JPY", "EUR", "GBP", "AUD", "CAD", "CHF", "NZD"]


def stat(rows, total_days):
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
                per_day=len(g) / total_days, daily=mean * len(g) / total_days)


def attach(rows, ser):
    cache = {}
    for r in rows:
        d = datetime.datetime.fromtimestamp(r["ts"], JST).date()
        z = ch = 0.0
        ok = bool(TILT.get(r["key"]))
        for curr, sign in TILT.get(r["key"], []):
            k = (curr, d)
            if k not in cache:
                cache[k] = cot.as_of(ser[curr], d)
            x = cache[k]
            if not x or x["z"] is None:
                ok = False
                break
            z += sign * x["z"]
            ch += sign * x["change"]
        r["cot_z"] = z if ok else None
        r["cot_change"] = ch if ok else None


RULES = [
    ("条件なし",            lambda r: True),
    ("偏り大きい時の逆張り",  lambda r: abs(r["cot_z"]) >= 1.0 and (r["cot_z"] > 0) != (r["pred"] > 0)),
    ("週間の増減と逆向き",    lambda r: (r["cot_change"] > 0) != (r["pred"] > 0)),
    ("両方とも逆向き",       lambda r: (r["cot_z"] > 0) != (r["pred"] > 0)
                                   and (r["cot_change"] > 0) != (r["pred"] > 0)),
]


def run(assets, ser, n_dates):
    rows = backtest.collect(assets, config.HORIZON_FX, n_dates=n_dates, step=3,
                            use_knn=True, kinds={"fx"}, verbose=False)
    td = len(set(r["ts"] for r in rows))
    attach(rows, ser)
    base = [r for r in rows
            if max(r["p_up"], 1 - r["p_up"]) >= config.FX_MIN_CONFIDENCE
            and r["cot_z"] is not None]
    groups = {
        "主要5ペア（条件を作った側）": [r for r in base if r["key"] in MAJOR],
        "残り10ペア（試し打ち）":     [r for r in base if r["key"] not in MAJOR],
    }
    return {g: {name: stat([r for r in rs if fn(r)], td) for name, fn in RULES}
            for g, rs in groups.items()}


if __name__ == "__main__":
    print("データ読み込み中...")
    assets = dataset.load_all(use_cache=True, progress=False)
    ser = cot.load(CURRENCIES)
    missing = [c for c in CURRENCIES if not ser.get(c)]
    if missing:
        print("  取得できなかった通貨:", missing)
    res = {w: run(assets, ser, w) for w in (400, 360, 440)}

    for g in ["主要5ペア（条件を作った側）", "残り10ペア（試し打ち）"]:
        print()
        print("=== {} ===".format(g))
        print("  {:<22}{:>8}{:>8}{:>8}{:>8}{:>7}{:>10}".format(
            "条件", "400", "360", "440", "件数", "1日", "1日期待値"))
        print("  " + "-" * 72)
        for name, _ in RULES:
            s = res[400][g].get(name)
            if not s:
                print("  {:<22}{:>8}".format(name, "件数不足"))
                continue
            cells = ["—" if not res[w][g].get(name) else
                     "{:.1f}%".format(res[w][g][name]["hit"] * 100) for w in (400, 360, 440)]
            b = res[400][g]["条件なし"]
            better = all(res[w][g].get(name) and res[w][g][name]["hit"] > res[w][g]["条件なし"]["hit"]
                         for w in (400, 360, 440)) if name != "条件なし" else False
            print("  {:<22}{:>8}{:>8}{:>8}{:>8,}{:>7.2f}{:>9.3f}%{}".format(
                name, cells[0], cells[1], cells[2], s["n"], s["per_day"], s["daily"] * 100,
                " ○" if better else ""))
    print()
    print("  試し打ち側でも3期間そろって改善していれば本物とみてよい。")
    print("  そこで消えるなら、主要5ペアでの結果はまぐれだったということ。")
