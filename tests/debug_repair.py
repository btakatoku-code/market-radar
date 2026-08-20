# -*- coding: utf-8 -*-
"""特定銘柄の修復処理を追跡する。"""
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))

import clean
import sources

SYMS = sys.argv[1:] or ["8303.T", "1489.T", "SOXS"]

for sym in SYMS:
    bars = sources.fetch_yahoo(sym)
    if not bars:
        print(sym, "取得失敗")
        continue
    c, t, v = bars["c"], bars["t"], bars["v"]
    print("=" * 70)
    print("{}  {}本  分割履歴={}".format(
        sym, len(c),
        [(datetime.date.fromtimestamp(d).isoformat(), round(r, 4)) for d, r in
         (bars.get("splits") or [])]))

    print("  修復前の大きな段差:")
    for i in range(1, len(c)):
        if c[i - 1] > 0 and abs(c[i] / c[i - 1] - 1) > 0.5:
            sp = clean._volume_spike(bars, i)
            print("    {}  {:>18.4f} -> {:>18.4f}  ({:+.4g}%)  出来高倍率={}".format(
                datetime.date.fromtimestamp(t[i]), c[i - 1], c[i],
                (c[i] / c[i - 1] - 1) * 100,
                "なし" if sp is None else "{:.2f}".format(sp)))

    n_split, trimmed, notes = clean.repair(bars)
    print("  修復: 分割{}件 / 切捨{}本 / {}".format(n_split, trimmed, notes or "なし"))
    c = bars["c"]
    print("  修復後の大きな段差:")
    any_left = False
    for i in range(1, len(c)):
        if c[i - 1] > 0 and abs(c[i] / c[i - 1] - 1) > 0.5:
            any_left = True
            print("    {}  {:>18.4f} -> {:>18.4f}  ({:+.4g}%)".format(
                datetime.date.fromtimestamp(bars["t"][i]), c[i - 1], c[i],
                (c[i] / c[i - 1] - 1) * 100))
    if not any_left:
        print("    なし")
    print("  直近価格 {:.2f} / 最小 {:.4f} / 最大 {:.2f}".format(
        c[-1], min(c), max(c)))
