# -*- coding: utf-8 -*-
"""価格データの異常値（株式分割の未調整・データ欠陥）を洗い出す。"""
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))

import dataset

assets = dataset.load_all(use_cache=True, progress=False)
print("銘柄数", len(assets))

bad = []
for a in assets:
    c, t = a["bars"]["c"], a["bars"]["t"]
    worst = 0.0
    worst_i = None
    for i in range(1, len(c)):
        if c[i - 1] <= 0:
            continue
        r = c[i] / c[i - 1] - 1
        if abs(r) > abs(worst):
            worst, worst_i = r, i
    if abs(worst) > 0.5:
        bad.append((abs(worst), a["key"], a["name"], worst,
                    datetime.date.fromtimestamp(t[worst_i]),
                    c[worst_i - 1], c[worst_i]))

bad.sort(reverse=True)
print()
print("1日で50%以上動いたバー（上位30件）")
print("{:<12}{:<24}{:>12}{:>12}{:>14}{:>14}".format(
    "銘柄", "名称", "変化率", "日付", "前日終値", "当日終値"))
for _, key, name, r, d, p0, p1 in bad[:30]:
    print("{:<12}{:<24}{:>11.1f}%{:>12}{:>14.4f}{:>14.4f}".format(
        key, name[:22], r * 100, str(d), p0, p1))
print()
print("該当銘柄数:", len(bad))
