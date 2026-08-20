# -*- coding: utf-8 -*-
"""選定ルールの比較を実行する。

使い方: python tests/run_compare.py [予測期間] [検証時点数] [間隔] [knn:0/1]
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))

import backtest
import compare
import config
import dataset

if __name__ == "__main__":
    horizon = int(sys.argv[1]) if len(sys.argv) > 1 else config.HORIZON_LONG
    n_dates = int(sys.argv[2]) if len(sys.argv) > 2 else 150
    step = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    use_knn = bool(int(sys.argv[4])) if len(sys.argv) > 4 else False

    print("データ読み込み中...")
    t0 = time.time()
    assets = dataset.load_all(use_cache=True, progress=True)
    print("  {:.1f}秒".format(time.time() - t0))
    print()
    t0 = time.time()
    rows = backtest.collect(assets, horizon, n_dates=n_dates, step=step,
                            use_knn=use_knn)
    print("  収集 {:.1f}秒".format(time.time() - t0))
    compare.report(rows, horizon)
