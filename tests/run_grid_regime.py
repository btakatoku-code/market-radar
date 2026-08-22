# -*- coding: utf-8 -*-
"""FXの優位性の土台である「市場環境による絞り込み」を、
時点の並びを1日ずつずらした3標本で測り直す。

これが崩れるならFX枠の主張そのものを取り下げる必要がある。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))

import backtest
import config
import dataset
import run_rates as R

OFFSETS = (0, 1, 2)


def run(mode):
    assets = dataset.load_all(use_cache=True, progress=False, regime_mode=mode)
    out = {}
    for o in OFFSETS:
        rows = backtest.collect(assets, config.HORIZON_FX, n_dates=400, step=3,
                                use_knn=True, kinds={"fx"}, verbose=False, offset=o)
        td = len(set(r["ts"] for r in rows))
        maj = [r for r in rows if r["key"] in R.MAJOR
               and max(r["p_up"], 1 - r["p_up"]) >= config.FX_MIN_CONFIDENCE]
        out[o] = R.stat(maj, td)
    return out


if __name__ == "__main__":
    print("測定中（レジーム2通り × 時点3通り）...")
    res = {m: run(m) for m in ("none", "risk_breadth9", "breadth3")}
    print()
    print("=== 主要5ペア・確信度56%以上 ===")
    print("  {:<22}{:>9}{:>9}{:>9}{:>9}{:>8}".format(
        "レジーム", "ずらし0", "ずらし1", "ずらし2", "平均", "振れ幅"))
    print("  " + "-" * 66)
    for m, label in [("none", "絞り込みなし"),
                     ("risk_breadth9", "リスク×広がり(9段階)"),
                     ("breadth3", "市場の広がり(3段階)")]:
        vals = [res[m][o]["hit"] for o in OFFSETS if res[m][o]]
        cells = ["{:.1f}%".format(res[m][o]["hit"] * 100) if res[m][o] else "—"
                 for o in OFFSETS]
        print("  {:<22}{:>9}{:>9}{:>9}{:>8.1f}%{:>7.1f}pt".format(
            label, cells[0], cells[1], cells[2],
            sum(vals) / len(vals) * 100, (max(vals) - min(vals)) * 100))
    a = sum(res["none"][o]["hit"] for o in OFFSETS) / 3
    b = sum(res["risk_breadth9"][o]["hit"] for o in OFFSETS) / 3
    print()
    print("  絞り込みによる改善: {:+.1f}pt".format((b - a) * 100))
    each = [(res["risk_breadth9"][o]["hit"] - res["none"][o]["hit"]) * 100 for o in OFFSETS]
    print("  標本ごと: " + " / ".join("{:+.1f}pt".format(x) for x in each))
    print("  → {}".format("3標本とも改善 → 主張は維持できる" if all(x > 0 for x in each)
                          else "改善しない標本がある → 主張を弱める必要がある"))
