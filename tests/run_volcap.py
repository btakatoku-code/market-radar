# -*- coding: utf-8 -*-
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))
import backtest, compare, config, dataset
horizon = int(sys.argv[1]) if len(sys.argv) > 1 else config.HORIZON_LONG
assets = dataset.load_all(use_cache=True, progress=False)
rows = backtest.collect(assets, horizon, n_dates=150, step=8, use_knn=False, verbose=True)
compare.vol_cap_report(rows, horizon)
