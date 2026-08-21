# -*- coding: utf-8 -*-
"""米国金利がFXの的中率を上げるかを実測する。

金利差はFXの教科書的な材料で、テクニカルとも需給とも種類が違う。
米10年国債利回り（^TNX）と13週物（^IRX）をYahooから取る。

COTの失敗を踏まえ、今回は最初から次の設計にする:
  1. 試す条件は4つだけに絞る（たくさん試すほど、まぐれを拾いやすい）
  2. 主要5ペアと「残り10ペア」を最初から同時に測る
  3. 400／360／440の3期間で測る
  採用は「両方のペア群で、3期間すべて改善」した場合のみ。
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
import sources

MAJOR = set(config.FX_SIGNAL_PAIRS)

# 米金利が上がったとき、そのペアが上がる向きなら +1、下がる向きなら -1。
# ドルが絡むペアは金利差、円クロスは「円は低金利通貨」という関係で決める。
USD_SIGN = {
    "USDJPY=X": +1, "EURUSD=X": -1, "EURJPY=X": +1, "GBPJPY=X": +1, "AUDJPY=X": +1,
    # ここから下は条件作りに使わない（試し打ち用）
    "GBPUSD=X": -1, "AUDUSD=X": -1, "NZDUSD=X": -1, "USDCAD=X": +1, "USDCHF=X": +1,
    "NZDJPY=X": +1, "CADJPY=X": +1, "CHFJPY=X": +1,
}


def yields():
    """金利の日足を取り、各営業日の変化量を作る。"""
    ten = sources.fetch_yahoo("^TNX", rng="10y")
    three = sources.fetch_yahoo("^IRX", rng="10y")
    short = {t: c for t, c in zip(three["t"], three["c"]) if c is not None}
    st = sorted(short)
    out = []
    ts = [t for t, c in zip(ten["t"], ten["c"]) if c is not None]
    cs = [c for c in ten["c"] if c is not None]
    for i, (t, c) in enumerate(zip(ts, cs)):
        j = bisect.bisect_right(st, t) - 1
        sl = (c - short[st[j]]) if j >= 0 else None
        out.append({"t": t, "y": c,
                    "chg5": c - cs[i - 5] if i >= 5 else None,
                    "chg20": c - cs[i - 20] if i >= 20 else None,
                    "slope": sl})
    return out


def attach(rows, ser):
    """各予測に「その時点で分かっている」直近の金利の状態を付ける。"""
    ts = [x["t"] for x in ser]
    for r in rows:
        i = bisect.bisect_left(ts, r["ts"]) - 1      # 予測時点より前の足だけ使う
        x = ser[i] if i >= 0 else None
        sign = USD_SIGN.get(r["key"])
        if not x or x["chg20"] is None or sign is None:
            r["rate20"] = r["rate5"] = None
            continue
        r["rate20"] = sign * x["chg20"]              # ペアから見た金利の追い風
        r["rate5"] = sign * (x["chg5"] if x["chg5"] is not None else 0.0)


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


# 事前に決めた4条件だけを試す
RULES = [
    ("条件なし",              lambda r, m: True),
    ("金利の追い風と同じ向き",  lambda r, m: (r["rate20"] > 0) == (r["pred"] > 0)),
    ("金利の追い風と逆向き",    lambda r, m: (r["rate20"] > 0) != (r["pred"] > 0)),
    ("金利が動いていない時だけ", lambda r, m: abs(r["rate20"]) < m),
]


def run(assets, ser, n_dates):
    rows = backtest.collect(assets, config.HORIZON_FX, n_dates=n_dates, step=3,
                            use_knn=True, kinds={"fx"}, verbose=False)
    td = len(set(r["ts"] for r in rows))
    attach(rows, ser)
    base = [r for r in rows
            if max(r["p_up"], 1 - r["p_up"]) >= config.FX_MIN_CONFIDENCE
            and r["rate20"] is not None]
    mags = sorted(abs(r["rate20"]) for r in base)
    med = mags[len(mags) // 2] if mags else 0.0
    groups = {
        "主要5ペア": [r for r in base if r["key"] in MAJOR],
        "残り8ペア（試し打ち）": [r for r in base if r["key"] not in MAJOR],
    }
    return {g: {name: stat([r for r in rs if fn(r, med)], td) for name, fn in RULES}
            for g, rs in groups.items()}


if __name__ == "__main__":
    print("データ読み込み中...")
    assets = dataset.load_all(use_cache=True, progress=False)
    ser = yields()
    print("  金利データ: {}営業日 / 直近の10年利回り {:.2f}%".format(len(ser), ser[-1]["y"]))
    res = {w: run(assets, ser, w) for w in (400, 360, 440)}

    ok_all = {}
    for g in ["主要5ペア", "残り8ペア（試し打ち）"]:
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
            better = (name != "条件なし" and
                      all(res[w][g].get(name) and
                          res[w][g][name]["hit"] > res[w][g]["条件なし"]["hit"]
                          for w in (400, 360, 440)))
            ok_all.setdefault(name, []).append(better)
            print("  {:<22}{:>8}{:>8}{:>8}{:>8,}{:>7.2f}{:>9.3f}%{}".format(
                name, cells[0], cells[1], cells[2], s["n"], s["per_day"],
                s["daily"] * 100, " ○" if better else ""))

    print()
    print("=== 判定 ===")
    for name, flags in ok_all.items():
        if name == "条件なし":
            continue
        print("  {:<22} {}".format(
            name, "両群とも3期間で改善 → 検討に値する" if all(flags)
            else "条件を満たさず → 不採用"))
