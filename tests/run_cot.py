# -*- coding: utf-8 -*-
"""CFTC建玉報告（COT）を条件に加えると勝率が上がるかを実測する。

投機筋の買い越し・売り越しは、テクニカルとは種類の違う情報（需給）。
これを予測に重ねて、順張り・逆張りの両方向で効果を測る。

判定基準（前回の失敗を踏まえて固定）:
  1. 400／360／440時点の3期間すべてで改善すること
  2. 1日あたりの期待値（勝率×頻度）が下がらないこと
  どちらか欠けたら採用しない。
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

# ペアごとの「建玉が示す向き」の作り方。通貨先物はすべて対米ドルなので、
# 米ドルの偏りは0とみなし、相手通貨の偏りの差で向きを出す。
TILT = {
    "USDJPY=X": [("JPY", -1)],              # 円の買い越し = ドル円は下
    "EURUSD=X": [("EUR", +1)],
    "EURJPY=X": [("EUR", +1), ("JPY", -1)],
    "GBPJPY=X": [("GBP", +1), ("JPY", -1)],
    "AUDJPY=X": [("AUD", +1), ("JPY", -1)],
}


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


def attach_cot(rows, ser):
    """各予測に、その時点で参照してよい建玉の偏りを付ける。"""
    cache = {}
    for r in rows:
        d = datetime.datetime.fromtimestamp(r["ts"], JST).date()
        z = ch = 0.0
        ok = True
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
    ("条件なし（現行）",        lambda r: True),
    ("建玉と同じ向きだけ",      lambda r: (r["cot_z"] > 0) == (r["pred"] > 0)),
    ("建玉と逆向きだけ",        lambda r: (r["cot_z"] > 0) != (r["pred"] > 0)),
    ("偏りが大きい時だけ順張り", lambda r: abs(r["cot_z"]) >= 1.0 and (r["cot_z"] > 0) == (r["pred"] > 0)),
    ("偏りが大きい時だけ逆張り", lambda r: abs(r["cot_z"]) >= 1.0 and (r["cot_z"] > 0) != (r["pred"] > 0)),
    ("偏りが小さい時だけ",      lambda r: abs(r["cot_z"]) < 1.0),
    ("週間の増減と同じ向き",    lambda r: (r["cot_change"] > 0) == (r["pred"] > 0)),
    ("週間の増減と逆向き",      lambda r: (r["cot_change"] > 0) != (r["pred"] > 0)),
]


def measure(assets, ser, n_dates):
    rows = backtest.collect(assets, config.HORIZON_FX, n_dates=n_dates, step=3,
                            use_knn=True, kinds={"fx"}, verbose=False)
    total_days = len(set(r["ts"] for r in rows))
    attach_cot(rows, ser)
    sel = [r for r in rows if r["key"] in MAJOR
           and max(r["p_up"], 1 - r["p_up"]) >= config.FX_MIN_CONFIDENCE
           and r["cot_z"] is not None]
    return {name: stat([r for r in sel if fn(r)], total_days) for name, fn in RULES}, len(sel)


if __name__ == "__main__":
    print("データ読み込み中...")
    assets = dataset.load_all(use_cache=True, progress=False)
    ser = cot.load(["JPY", "EUR", "GBP", "AUD"])
    print("  建玉データ: " + " / ".join(
        "{} {}回".format(c, len(v)) for c, v in sorted(ser.items())))

    res, n = {}, {}
    for w in (400, 360, 440):
        res[w], n[w] = measure(assets, ser, w)
    print("  対象シグナル（主要5ペア・確信度{:.0f}%以上）: {}件".format(
        config.FX_MIN_CONFIDENCE * 100, n[400]))
    print()
    print("=== 建玉報告を条件に加えたとき（主要5ペア・確信度56%以上）===")
    print("  {:<24}{:>8}{:>8}{:>8}{:>7}{:>8}{:>10}".format(
        "条件", "400", "360", "440", "件数", "1日", "1日期待値"))
    print("  " + "-" * 74)
    base = res[400]["条件なし（現行）"]
    for name, _ in RULES:
        s = res[400].get(name)
        if not s:
            print("  {:<24}{:>8}".format(name, "件数不足"))
            continue
        cells = []
        for w in (400, 360, 440):
            x = res[w].get(name)
            cells.append("—" if not x else "{:.1f}%".format(x["hit"] * 100))
        mark = ""
        if name != "条件なし（現行）":
            better = all(res[w].get(name) and res[w][name]["hit"] > res[w]["条件なし（現行）"]["hit"]
                         for w in (400, 360, 440))
            keeps = s["daily"] >= base["daily"]
            mark = " ◎" if (better and keeps) else (" ○" if better else "")
        print("  {:<24}{:>8}{:>8}{:>8}{:>7,}{:>8.2f}{:>9.3f}%{}".format(
            name, cells[0], cells[1], cells[2], s["n"], s["per_day"], s["daily"] * 100, mark))
    print()
    print("  ◎ = 3期間すべてで改善し、1日あたりの期待値も落ちない（採用の条件）")
    print("  ○ = 勝率は3期間とも上がるが、シグナルが減って1日の期待値は下がる")
