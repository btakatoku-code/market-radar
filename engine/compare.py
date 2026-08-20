# -*- coding: utf-8 -*-
"""選定ルールの比較。

同じウォークフォワードのデータに対して、あらかじめ決めた複数の並べ替えルールを
当てはめ、どれが「ランダムに5銘柄選んだ場合」を上回るかを比べる。

基準はその時点の対象銘柄の等加重平均リターン。これはランダムに選んだときの
期待値そのものなので、ルールに実力があるかどうかを直接測れる。
ランダム（対照）は20回の平均を取り、基準が正しく0付近に来ることの確認に使う。

ルールは後付けで増やさず、結果は良し悪しに関わらず全て出す。
"""
import math
import random

import config


def _z(r):
    return r["pred_z"]


RULES = [
    ("予測リターン（絶対値）", lambda r: r["pred"]),
    ("予測リターン÷ボラ", _z),
    ("予測×上昇確率", lambda r: _z(r) * (r["p_up"] - 0.5) * 2),
    ("合成スコア", lambda r: r["score"]),
    ("テクニカルのみ", lambda r: 0.45 * r["trend"] + 0.35 * r["momentum"]
                                + 0.20 * r["rel"]),
    ("トレンドのみ", lambda r: r["trend"]),
    ("モメンタムのみ", lambda r: r["momentum"]),
    ("相対強度のみ", lambda r: r["rel"]),
    ("ランダム（対照）", lambda r: random.random()),
]


def _tstat(vals):
    n = len(vals)
    if n < 2:
        return 0.0
    m = sum(vals) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in vals) / (n - 1))
    return (m / (sd / math.sqrt(n))) if sd else 0.0


def _eligible(rows, min_liquidity=True, max_annual_vol=None):
    by_t = {}
    for r in rows:
        if min_liquidity and r["adv"] < config.MIN_DOLLAR_VOLUME:
            continue
        if max_annual_vol is not None and r["daily_vol"] * 15.8745 > max_annual_vol:
            continue
        by_t.setdefault(r["ts"], []).append(r)
    return by_t


def evaluate(rows, keyfn, top_n=None, min_liquidity=True, seeds=1,
             max_annual_vol=None):
    """ルールで各時点の上位 top_n を選び、等加重平均に対する超過を測る。

    seeds > 1 の場合は keyfn を seeds 回評価して平均する（ランダム対照用）。
    """
    top_n = top_n or config.TOP_N
    by_t = _eligible(rows, min_liquidity, max_annual_vol)
    per_seed = []
    for sd in range(seeds):
        random.seed(1000 + sd)
        per = []
        for ts, rs in sorted(by_t.items()):
            if len(rs) < top_n * 3:
                continue
            picks = sorted(rs, key=lambda r: -keyfn(r))[:top_n]
            mkt = sum(x["actual"] for x in rs) / len(rs)
            ret = sum(x["actual"] for x in picks) / len(picks)
            per.append(dict(ts=ts, ret=ret, excess=ret - mkt))
        if len(per) < 2:
            return None
        per_seed.append(per)

    # シード間で各時点の結果を平均してから統計を取る
    n_per = len(per_seed[0])
    merged = []
    for i in range(n_per):
        ret = sum(ps[i]["ret"] for ps in per_seed) / seeds
        ex = sum(ps[i]["excess"] for ps in per_seed) / seeds
        merged.append(dict(ret=ret, excess=ex))
    ex = [x["excess"] for x in merged]
    return dict(periods=len(merged),
                mean=sum(x["ret"] for x in merged) / len(merged),
                excess=sum(ex) / len(ex),
                win_rate=sum(1 for x in merged if x["ret"] > 0) / len(merged),
                beat_rate=sum(1 for x in merged if x["excess"] > 0) / len(merged),
                best=max(x["ret"] for x in merged),
                worst=min(x["ret"] for x in merged),
                t_stat=_tstat(ex))


def spread(rows, keyfn, n_bins=5):
    """ルールで並べたときの分位ごとの超過リターン（等加重平均が基準）"""
    by_t = {}
    for r in rows:
        by_t.setdefault(r["ts"], []).append(r)
    bins = [[] for _ in range(n_bins)]
    for rs in by_t.values():
        mkt = sum(x["actual"] for x in rs) / len(rs)
        srt = sorted(rs, key=keyfn)
        m = len(srt)
        for rank, r in enumerate(srt):
            bins[min(n_bins - 1, rank * n_bins // m)].append(r["actual"] - mkt)
    return [(sum(b) / len(b) if b else 0.0) for b in bins]


def report(rows, horizon):
    random.seed(0)
    print()
    print("=== 選定ルールの比較（上位{}銘柄・{}営業日保有） ===".format(
        config.TOP_N, horizon))
    n_dates = len(set(r["ts"] for r in rows))
    print("  予測 {:,} 件 / {} 時点".format(len(rows), n_dates))
    print()
    print("  {:<24}{:>8}{:>10}{:>8}{:>10}{:>8}".format(
        "ルール", "平均", "市場超過", "勝率", "市場勝率", "t値"))
    print("  " + "-" * 68)
    results = []
    for name, fn in RULES:
        r = evaluate(rows, fn, seeds=(20 if "ランダム" in name else 1))
        if not r:
            continue
        results.append((name, r, fn))
        mark = " *" if abs(r["t_stat"]) >= 2 else ""
        print("  {:<24}{:+7.2f}%{:+9.2f}%{:7.0f}%{:9.0f}%{:8.2f}{}".format(
            name, r["mean"] * 100, r["excess"] * 100,
            r["win_rate"] * 100, r["beat_rate"] * 100, r["t_stat"], mark))
    print("  (* = t値2以上 / 統計的に有意)")
    print()
    print("  分位別の市場超過リターン（1=ルール最下位 … 5=最上位）")
    for name, fn in RULES:
        sp = spread(rows, fn)
        print("  {:<24}{}".format(
            name, "  ".join("{:+6.2f}%".format(x * 100) for x in sp)))
    return results


def fx_report(rows, horizon):
    """FX向けの評価。

    株と違い「上位5つを買う」ではなく「予測方向にポジションを取る」形なので、
    方向的中率と1回あたりの平均損益で測る。売買コスト（スプレッド）は
    別途差し引いて考える必要がある。
    """
    print()
    print("=== FX 検証結果（{}営業日先） ===".format(horizon))
    n_dates = len(set(r["ts"] for r in rows))
    print("  予測 {:,} 件 / {} 時点 / 通貨ペア {} 個".format(
        len(rows), n_dates, len(set(r["key"] for r in rows))))
    if not rows:
        return

    def stats(sel, label):
        if len(sel) < 2:
            print("  {:<26} 対象なし".format(label))
            return
        gains = [r["actual"] * (1 if r["pred"] > 0 else -1) for r in sel]
        hit = sum(1 for g in gains if g > 0) / len(gains)
        m = sum(gains) / len(gains)
        # 同じ日の通貨ペアは互いに強く相関するため、日ごとに平均してから検定する
        per_day = {}
        for r, g in zip(sel, gains):
            per_day.setdefault(r["ts"], []).append(g)
        daily = [sum(v) / len(v) for v in per_day.values()]
        print("  {:<26} 件数{:>6,}  的中率 {:>5.1f}%  平均 {:+.3f}%  "
              "t値 {:>5.2f}（日次集計 {:>5.2f} / {}日）".format(
                  label, len(sel), hit * 100, m * 100, _tstat(gains),
                  _tstat(daily), len(daily)))

    stats(rows, "全予測")
    for thr in (0.001, 0.002, 0.003):
        stats([r for r in rows if abs(r["pred"]) >= thr],
              "予測変動 {:.1f}% 以上".format(thr * 100))
    for p in (0.53, 0.56):
        stats([r for r in rows if max(r["p_up"], 1 - r["p_up"]) >= p],
              "確信度 {:.0f}% 以上".format(p * 100))

    # 各時点で予測変動の大きい上位5ペアだけを取る
    by_t = {}
    for r in rows:
        by_t.setdefault(r["ts"], []).append(r)
    picks = []
    for ts, rs in by_t.items():
        rs.sort(key=lambda r: -abs(r["pred"]))
        picks.extend(rs[:config.TOP_N])
    stats(picks, "各日の上位{}ペア".format(config.TOP_N))

    # 通貨ペア別
    print()
    print("  通貨ペア別の方向的中率")
    per = {}
    for r in rows:
        per.setdefault(r["key"], []).append(r["actual"] * (1 if r["pred"] > 0 else -1))
    for key, gains in sorted(per.items(), key=lambda kv: -sum(1 for g in kv[1] if g > 0) / len(kv[1])):
        hit = sum(1 for g in gains if g > 0) / len(gains)
        print("    {:<12} 的中率 {:>5.1f}%  平均 {:+.3f}%  件数 {:>5,}".format(
            key, hit * 100, sum(gains) / len(gains) * 100, len(gains)))


def vol_cap_report(rows, horizon):
    """ボラティリティ上限を変えたときに、優位性が残るかを確認する。"""
    random.seed(0)
    print()
    print("=== ボラティリティ上限の影響（予測リターン順・上位{}銘柄） ===".format(config.TOP_N))
    print("  {:<18}{:>9}{:>10}{:>10}{:>9}{:>8}".format(
        "年率ボラ上限", "対象/日", "平均", "市場超過", "市場勝率", "t値"))
    print("  " + "-" * 66)
    for cap in (None, 1.2, 0.9, 0.7, 0.55, 0.45, 0.35):
        r = evaluate(rows, lambda x: x["pred"], max_annual_vol=cap)
        ctrl = evaluate(rows, lambda x: random.random(), seeds=20, max_annual_vol=cap)
        if not r:
            continue
        by_t = _eligible(rows, True, cap)
        avg_n = sum(len(v) for v in by_t.values()) / max(1, len(by_t))
        label = "なし" if cap is None else "{:.0f}%".format(cap * 100)
        print("  {:<18}{:>9.0f}{:+9.2f}%{:+10.2f}%{:>8.0f}%{:>8.2f}   （対照 {:+.2f}%）".format(
            label, avg_n, r["mean"] * 100, r["excess"] * 100,
            r["beat_rate"] * 100, r["t_stat"], ctrl["excess"] * 100 if ctrl else 0))
