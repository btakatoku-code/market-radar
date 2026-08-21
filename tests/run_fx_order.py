# -*- coding: utf-8 -*-
"""FXの表示ペアを「的中確率の高い順」に選ぶと成績が上がるかを実測する。

いまは主要5ペアを固定で表示している。これを毎日「確信度の高い順に14ペアから
上位5つ」に変えるとどうなるかを比べる。裏付け（MACDとトレンドの一致）を
並べ替えに使う効果も測る。

前回、期間を前後にずらす検査を怠って誤った結論を出したので、
今回は必ず400／360／440時点の3通りで確認する。
"""
import datetime
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))

import backtest
import config
import dataset
import fx as fxmod

MAJOR = ["USDJPY=X", "EURJPY=X", "GBPJPY=X", "AUDJPY=X", "EURUSD=X"]


def confirm_level(r):
    """予測方向とテクニカルの一致数から裏付けの強さを出す（0〜2）"""
    up = r["pred"] > 0
    macd_ok = (r["macd"] > 0) == up
    trend_ok = (r["trend"] > 0) == up
    if macd_ok and trend_ok:
        return 2
    agree = sum([macd_ok, trend_ok,
                 (r["momentum"] > 0) == up, (r["rsi"] > 50) == up])
    return 1 if agree >= 2 else 0


def stat(rows, total_days):
    if len(rows) < 15:
        return None
    g = [r["actual"] * (1 if r["pred"] > 0 else -1) for r in rows]
    per = {}
    for r, x in zip(rows, g):
        per.setdefault(r["ts"], []).append(x)
    daily = [sum(v) / len(v) for v in per.values()]
    m = sum(daily) / len(daily)
    sd = math.sqrt(sum((x - m) ** 2 for x in daily) / max(1, len(daily) - 1))
    return dict(n=len(rows), hit=sum(1 for x in g if x > 0) / len(g),
                mean=sum(g) / len(g), days=len(daily),
                t=(m / (sd / math.sqrt(len(daily)))) if sd else 0.0,
                per_day=len(rows) / total_days)


def build(rows, conf, mode):
    """mode ごとに、その日に表示・採用するペアを選ぶ"""
    by_t = {}
    for r in rows:
        by_t.setdefault(r["ts"], []).append(r)
    out = []
    for ts, rs in by_t.items():
        if mode == "固定5ペア":
            cand = [r for r in rs if r["key"] in set(MAJOR)]
        elif mode == "確信度上位5":
            cand = sorted(rs, key=lambda r: -r["conf"])[:5]
        elif mode == "確信度上位5→裏付け":
            cand = sorted(rs, key=lambda r: (-r["conf"], -r["cl"]))[:5]
        elif mode == "裏付け→確信度 上位5":
            cand = sorted(rs, key=lambda r: (-r["cl"], -r["conf"]))[:5]
        elif mode == "実質期待値の上位5":
            cand = sorted(rs, key=lambda r: -(r["conf"] - 0.5 - r["sp"] * 100))[:5]
        else:
            cand = rs
        out.extend([r for r in cand if r["conf"] >= conf])
    return out


def measure(assets, n_dates):
    rows = backtest.collect(assets, config.HORIZON_FX, n_dates=n_dates, step=3,
                            use_knn=True, kinds={"fx"}, verbose=False)
    total_days = len(set(r["ts"] for r in rows))
    for r in rows:
        r["conf"] = max(r["p_up"], 1 - r["p_up"])
        r["cl"] = confirm_level(r)
        r["sp"] = fxmod.SPREAD.get(r["key"], fxmod.DEFAULT_SPREAD)
    res = {}
    for mode in ["固定5ペア", "確信度上位5", "確信度上位5→裏付け",
                 "裏付け→確信度 上位5", "実質期待値の上位5"]:
        for conf in (0.56, 0.60):
            res[(mode, conf)] = stat(build(rows, conf, mode), total_days)
    return res


if __name__ == "__main__":
    print("データ読み込み中...")
    assets = dataset.load_all(use_cache=True, progress=False)
    windows = [400, 360, 440]
    res = {w: measure(assets, w) for w in windows}

    for conf in (0.56, 0.60):
        print()
        print("=== 確信度{:.0f}%以上のとき ===".format(conf * 100))
        print("  {:<22}{:>9}{:>9}{:>9}{:>8}{:>8}{:>7}".format(
            "選び方", "勝率400", "勝率360", "勝率440", "件数", "1日", "t値"))
        print("  " + "-" * 74)
        rows = []
        for mode in ["固定5ペア", "確信度上位5", "確信度上位5→裏付け",
                     "裏付け→確信度 上位5", "実質期待値の上位5"]:
            s = res[400].get((mode, conf))
            if not s:
                continue
            cells = []
            for w in windows:
                x = res[w].get((mode, conf))
                cells.append("—" if not x else "{:.1f}%".format(x["hit"] * 100))
            rows.append((mode, cells, s))
        for mode, cells, s in rows:
            print("  {:<22}{:>9}{:>9}{:>9}{:>8,}{:>8.2f}{:>7.2f}".format(
                mode, cells[0], cells[1], cells[2], s["n"], s["per_day"], s["t"]))

    print()
    print("  ※ 3つの期間すべてで固定5ペアを上回らなければ採用しない。")
    print("     1つの期間だけで良く見えるものは、前回と同じ失敗になる。")
