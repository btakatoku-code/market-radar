# -*- coding: utf-8 -*-
"""外為オンラインの24ペアから、実際に使う5ペアを選び直す。

要望は「勝ち率の高い順TOP5」だが、勝ち率だけで選ぶと危ない理由が2つある。

  1. コストを無視すると、取引できないペアを選んでしまう。
     ポンド/NZドルの往復スプレッドは0.0875%で、実測の優位性0.088%を
     ほぼ食い尽くす。南アランド/円は2.995%で論外。
  2. 24ペアから上位5つを選ぶと、たまたま良かったものを拾いやすい。
     これは何度もやらかした失敗。

そこで:
  - 指標は「勝ち率」と「コスト差し引き後の1回あたり損益」の両方を出す
  - 標本0と1で順位を決め、標本2（選定に使っていない）で確かめる
  - いまの5ペアと、選び直した5ペアを同じ土俵で比べる
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))

import backtest
import config
import dataset
import fx as fxmod

OFFSETS = (0, 1, 2)
PRICE = {}          # ペアごとの検証期間の平均値段
PICK = (0, 1)      # 順位付けに使う標本
TEST = 2           # 確かめに使う標本（選定に使わない）


def stat(rows, total_days, key=None):
    if len(rows) < 10:
        return None
    g = [r["actual"] * (1 if r["pred"] > 0 else -1) for r in rows]
    per = {}
    for r, x in zip(rows, g):
        per.setdefault(r["ts"], []).append(x)
    daily = [sum(v) / len(v) for v in per.values()]
    m = sum(daily) / len(daily)
    sd = math.sqrt(sum((y - m) ** 2 for y in daily) / max(1, len(daily) - 1))
    mean = sum(g) / len(g)
    # コスト：往復スプレッド。業者は価格の単位で示すので、
    # その期間の平均値段で割って割合にする。
    px = PRICE.get(key)
    sp = fxmod.spread_pct(key, px) if (key and px) else fxmod.DEFAULT_SPREAD
    return dict(n=len(g), hit=sum(1 for v in g if v > 0) / len(g), mean=mean,
                net=mean - sp * 2, spread=sp,
                t=(m / (sd / math.sqrt(len(daily)))) if sd else 0.0,
                per_day=len(g) / total_days)


def run(assets, offset):
    rows = backtest.collect(assets, config.HORIZON_FX, n_dates=400, step=3,
                            use_knn=True, kinds={"fx"}, verbose=False, offset=offset)
    td = len(set(r["ts"] for r in rows))
    out = {}
    for k in sorted(set(r["key"] for r in rows)):
        sel = [r for r in rows
               if r["key"] == k
               and max(r["p_up"], 1 - r["p_up"]) >= config.FX_MIN_CONFIDENCE]
        out[k] = stat(sel, td, key=k)
    return out, rows, td


def combined(res, keys, offsets):
    """複数ペアをまとめて評価する（実際は同じ日に複数建てる）。"""
    vals = []
    for o in offsets:
        rs = [res[o][k] for k in keys if res[o].get(k)]
        if not rs:
            continue
        n = sum(r["n"] for r in rs)
        if not n:
            continue
        hit = sum(r["hit"] * r["n"] for r in rs) / n
        net = sum(r["net"] * r["n"] for r in rs) / n
        pd = sum(r["per_day"] for r in rs)
        vals.append((hit, net, pd, n))
    if not vals:
        return None
    return dict(hit=sum(v[0] for v in vals) / len(vals),
                net=sum(v[1] for v in vals) / len(vals),
                per_day=sum(v[2] for v in vals) / len(vals),
                n=sum(v[3] for v in vals) // len(vals),
                daily=sum(v[1] * v[2] for v in vals) / len(vals))


if __name__ == "__main__":
    print("データ読み込み中...")
    assets = dataset.load_all(use_cache=True, progress=False)
    # 検証期間（直近1200営業日ほど）の平均値段。スプレッドを割合に直すのに使う。
    for a in assets:
        if a["kind"] != "fx":
            continue
        cs = [c for c in a["bars"]["c"][-1200:] if c]
        if cs:
            PRICE[a["key"]] = sum(cs) / len(cs)
    res = {}
    for o in OFFSETS:
        res[o], _, _ = run(assets, o)
        print("  標本{} 済み".format(o))

    names = dict(config.FX_PAIRS)
    keys = sorted(res[0])

    def avg(k, field, offsets):
        vals = [res[o][k][field] for o in offsets if res[o].get(k)]
        return sum(vals) / len(vals) if vals else None

    print()
    print("=== 24ペアの成績（確信度56%以上・標本0と1の平均）===")
    print("  {:<18}{:>8}{:>10}{:>10}{:>10}{:>7}".format(
        "ペア", "勝ち率", "1回あたり", "往復コスト", "差引後", "1日"))
    print("  " + "-" * 66)
    rowsel = []
    for k in keys:
        h = avg(k, "hit", PICK); m = avg(k, "mean", PICK)
        sp = avg(k, "spread", PICK); net = avg(k, "net", PICK)
        pd = avg(k, "per_day", PICK)
        if h is None:
            continue
        rowsel.append((k, h, m, sp, net, pd))
    for k, h, m, sp, net, pd in sorted(rowsel, key=lambda x: -x[1]):
        print("  {:<18}{:>7.1f}%{:>10}{:>10}{:>10}{:>7.2f}{}".format(
            names.get(k, k)[:9], h * 100,
            "{:+.3f}%".format(m * 100), "{:.3f}%".format(sp * 200),
            "{:+.3f}%".format(net * 100), pd,
            "  ← 取引不可" if net <= 0 else ""))

    by_hit = [k for k, *_ in sorted(rowsel, key=lambda x: -x[1])][:5]
    by_net = [k for k, *_ in sorted(rowsel, key=lambda x: -x[4])][:5]
    cur = list(config.FX_SIGNAL_PAIRS)

    print()
    print("=== 選び方ごとの比較 ===")
    for lab, ks in [("いまの5ペア", cur),
                    ("勝ち率の上位5", by_hit),
                    ("コスト差引後の上位5", by_net)]:
        p = combined(res, ks, PICK)
        t = combined(res, ks, [TEST])
        print("  {:<20}".format(lab))
        print("     選定に使った標本: 勝ち率{:.1f}% 差引後{:+.4f}% 1日{:.2f}回".format(
            p["hit"] * 100, p["net"] * 100, p["per_day"]))
        print("     確かめの標本    : 勝ち率{:.1f}% 差引後{:+.4f}% 1日{:.2f}回".format(
            t["hit"] * 100, t["net"] * 100, t["per_day"]))
        print("     " + " / ".join(names.get(k, k) for k in ks))
    # スプレッドが広がったときに耐えられるか。原則固定でも指標発表時や
    # 早朝は広がる。クロス通貨は広がり方が大きいので、ここで差が出る。
    print()
    print("=== スプレッド拡大時（指標発表時・早朝）に耐えられるか ===")
    print("  {:<18}{:>10}{:>11}{:>11}{:>11}".format(
        "ペア", "1回あたり", "通常時差引", "拡大時往復", "拡大時差引"))
    print("  " + "-" * 62)
    survive = []
    for k, h, m, sp, net, pd in sorted(rowsel, key=lambda x: -x[1]):
        px = PRICE.get(k)
        wide = fxmod.spread_pct(k, px, wide=True) * 2 if px else None
        wnet = (m - wide) if wide is not None else None
        if wnet is not None and wnet > 0 and net > 0:
            survive.append(k)
        print("  {:<18}{:>10}{:>11}{:>11}{:>11}{}".format(
            names.get(k, k)[:9], "{:+.3f}%".format(m * 100),
            "{:+.3f}%".format(net * 100),
            "{:.3f}%".format(wide * 100) if wide is not None else "—",
            "{:+.3f}%".format(wnet * 100) if wnet is not None else "—",
            "  ○" if (wnet is not None and wnet > 0 and net > 0) else ""))

    by_hit_robust = [k for k, *_ in sorted(rowsel, key=lambda x: -x[1])
                     if k in survive][:5]
    print()
    print("=== 拡大時でも成立するものだけで、勝ち率の上位5 ===")
    p2 = combined(res, by_hit_robust, PICK)
    t2 = combined(res, by_hit_robust, [TEST])
    print("     " + " / ".join(names.get(k, k) for k in by_hit_robust))
    print("     選定に使った標本: 勝ち率{:.1f}% 差引後{:+.4f}% 1日{:.2f}回".format(
        p2["hit"] * 100, p2["net"] * 100, p2["per_day"]))
    print("     確かめの標本    : 勝ち率{:.1f}% 差引後{:+.4f}% 1日{:.2f}回".format(
        t2["hit"] * 100, t2["net"] * 100, t2["per_day"]))

    print()
    print("  確かめの標本は順位付けに使っていません。ここで崩れるなら、")
    print("  上位5つは「たまたま良かったもの」を拾っただけということです。")
