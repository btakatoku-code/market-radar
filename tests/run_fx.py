# -*- coding: utf-8 -*-
"""FXの予測を検証する。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))
import backtest, compare, config, dataset

if __name__ == "__main__":
    horizon = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    n_dates = int(sys.argv[2]) if len(sys.argv) > 2 else 400
    step = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    assets = dataset.load_all(use_cache=True, progress=False)
    rows = backtest.collect(assets, horizon, n_dates=n_dates, step=step,
                            kinds={"fx"}, use_knn=True, verbose=True)
    compare.fx_report(rows, horizon)
