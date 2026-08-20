# -*- coding: utf-8 -*-
"""市場レジームでの絞り込みが的中率を上げるかを実測する。

同じデータ・同じ検証時点に対して、レジームの定義だけを変えて比べる。
良くなった場合だけ採用する。悪くなったらそのまま報告する。

使い方: python tests/run_ablation.py [対象] [検証時点数] [間隔]
  対象: stock（既定）または fx
"""
import math
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))

import backtest
import compare
import config
import dataset
import market

MODES = ["none", "vix3", "trend2", "risk3", "breadth3", "vix_trend6", "risk_breadth9"]


def _tstat(vals):
    n = len(vals)
    if n < 2:
        return 0.0
    m = sum(vals) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in vals) / (n - 1))
    return (m / (sd / math.sqrt(n))) if sd else 0.0


def stock_metrics(rows):
    """アプリが実際に表示する条件で、的中率と市場超過を測る。"""
    if not rows:
        return None
    # 投資対象として成立するものだけに絞る（アプリと同じ条件）
    ok = [r for r in rows
          if r["adv"] >= config.MIN_DOLLAR_VOLUME
          and r["daily_vol"] * 15.8745 <= config.MAX_ANNUAL_VOL
          and r["pred"] > 0 and r["p_up"] >= config.MIN_PROB_UP]
    by_t = {}
    for r in ok:
        by_t.setdefault(r["ts"], []).append(r)

    picks, per_period = [], []
    for ts, rs in sorted(by_t.items()):
        if len(rs) < config.TOP_N:
            continue
        rs.sort(key=lambda r: -r["score"])
        top = rs[:config.TOP_N]
        picks.extend(top)
        allr = [x for x in rows if x["ts"] == ts]
        mkt = sum(x["actual"] for x in allr) / len(allr)
        ret = sum(x["actual"] for x in top) / len(top)
        per_period.append(ret - mkt)
    if len(picks) < 20:
        return None

    hit = sum(1 for r in picks if r["actual"] > 0) / len(picks)
    # 全予測の方向的中率（予測の大きさ上位半分）
    thr = sorted(abs(r["pred"]) for r in rows)[len(rows) // 2]
    dirs = [r for r in rows if abs(r["pred"]) >= thr]
    dir_hit = sum(1 for r in dirs if (r["pred"] > 0) == (r["actual"] > 0)) / len(dirs)
    base = sum(1 for r in rows if r["actual"] > 0) / len(rows)

    return dict(picks=len(picks), periods=len(per_period),
                hit=hit, dir_hit=dir_hit, base=base,
                excess=sum(per_period) / len(per_period),
                t=_tstat(per_period),
                mean=sum(r["actual"] for r in picks) / len(picks))


def fx_metrics(rows):
    if not rows:
        return None
    by_t = {}
    for r in rows:
        by_t.setdefault(r["ts"], []).append(r)
    picks = []
    for ts, rs in by_t.items():
        rs.sort(key=lambda r: -abs(r["pred"]))
        picks.extend(rs[:config.TOP_N])
    gains = [r["actual"] * (1 if r["pred"] > 0 else -1) for r in picks]
    per_day = {}
    for r, g in zip(picks, gains):
        per_day.setdefault(r["ts"], []).append(g)
    daily = [sum(v) / len(v) for v in per_day.values()]
    allg = [r["actual"] * (1 if r["pred"] > 0 else -1) for r in rows]
    return dict(picks=len(picks), periods=len(daily),
                hit=sum(1 for g in gains if g > 0) / len(gains),
                dir_hit=sum(1 for g in allg if g > 0) / len(allg),
                base=0.5,
                mean=sum(gains) / len(gains),
                excess=sum(gains) / len(gains),
                t=_tstat(daily))


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "stock"
    n_dates = int(sys.argv[2]) if len(sys.argv) > 2 else 150
    step = int(sys.argv[3]) if len(sys.argv) > 3 else 8

    is_fx = target == "fx"
    horizon = config.HORIZON_FX if is_fx else config.HORIZON_LONG
    kinds = {"fx"} if is_fx else None

    print("データ読み込み中...")
    assets = dataset.load_all(use_cache=True, progress=False, regime_mode="none")
    print("  {} 銘柄".format(len(assets)))
    print()

    results = []
    for mode in MODES:
        t0 = time.time()
        reg = dataset.attach_regime(assets, mode)
        rows = backtest.collect(assets, horizon, n_dates=n_dates, step=step,
                                use_knn=is_fx, kinds=kinds, verbose=False)
        m = fx_metrics(rows) if is_fx else stock_metrics(rows)
        results.append((mode, reg.levels, m))
        if m:
            print("  {:<16} 段階{:<3} 的中率 {:>5.1f}%  平均 {:+.3f}%  超過 {:+.3f}%  "
                  "t {:>5.2f}  ({:.0f}秒)".format(
                      mode, reg.levels, m["hit"] * 100, m["mean"] * 100,
                      m["excess"] * 100, m["t"], time.time() - t0))
        else:
            print("  {:<16} 測定不能".format(mode))

    print()
    print("=== レジーム別の結果（{}・{}営業日先） ===".format(
        "FX" if is_fx else "株・長期枠", horizon))
    print("  {:<18}{:>6}{:>10}{:>11}{:>11}{:>9}{:>8}".format(
        "レジーム", "段階", "採用数", "的中率", "方向的中率", "市場超過", "t値"))
    print("  " + "-" * 76)
    base_hit = None
    for mode, levels, m in results:
        if not m:
            continue
        if mode == "none":
            base_hit = m["hit"]
        delta = "" if base_hit is None or mode == "none" else \
            " ({:+.1f}pt)".format((m["hit"] - base_hit) * 100)
        print("  {:<18}{:>6}{:>10,}{:>10.1f}%{:>10.1f}%{:>+9.3f}%{:>8.2f}{}".format(
            mode, levels, m["picks"], m["hit"] * 100, m["dir_hit"] * 100,
            m["excess"] * 100, m["t"], delta))
    if results and results[0][2]:
        print()
        print("  参考: 全銘柄の上昇率（基準線） {:.1f}%".format(results[0][2]["base"] * 100))
    print()
    print("  ※ t値2以上で統計的に有意。的中率の差は誤差の範囲かどうかをt値と併せて見ること。")
