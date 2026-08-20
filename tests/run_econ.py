# -*- coding: utf-8 -*-
"""経済指標の有無でFXの的中率が変わるかを実測する。

FXは金利決定や雇用統計で大きく動く。テクニカルの延長では読めないので、
  - 指標がある日は避けるべきか
  - むしろ動きが大きいぶん狙い目なのか
  - 通貨に直接関係する指標だけが効くのか
を、実際の検証データに当てはめて確かめる。

判断は後付けせず、あらかじめ決めた区分で比べたうえで結果を全部出す。
"""
import datetime
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))

import backtest
import config
import dataset
import events

JST = datetime.timezone(datetime.timedelta(hours=9))
# 通貨ペアと、それに直接効く通貨
PAIR_CUR = {
    "USDJPY=X": ("USD", "JPY"), "EURJPY=X": ("EUR", "JPY"),
    "GBPJPY=X": ("GBP", "JPY"), "AUDJPY=X": ("AUD", "JPY"),
    "EURUSD=X": ("EUR", "USD"), "NZDJPY=X": ("NZD", "JPY"),
    "CADJPY=X": ("CAD", "JPY"), "CHFJPY=X": ("CHF", "JPY"),
    "GBPUSD=X": ("GBP", "USD"), "AUDUSD=X": ("AUD", "USD"),
    "NZDUSD=X": ("NZD", "USD"), "USDCHF=X": ("USD", "CHF"),
    "USDCAD=X": ("USD", "CAD"), "EURGBP=X": ("EUR", "GBP"),
}


def _tstat(vals):
    n = len(vals)
    if n < 2:
        return 0.0
    m = sum(vals) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in vals) / (n - 1))
    return (m / (sd / math.sqrt(n))) if sd else 0.0


def gain(r):
    return r["actual"] * (1 if r["pred"] > 0 else -1)


def report(rows, label):
    if len(rows) < 15:
        print("  {:<32} 件数不足（{}件）".format(label, len(rows)))
        return None
    g = [gain(r) for r in rows]
    per_day = {}
    for r, x in zip(rows, g):
        per_day.setdefault(r["ts"], []).append(x)
    daily = [sum(v) / len(v) for v in per_day.values()]
    hit = sum(1 for x in g if x > 0) / len(g)
    mean = sum(g) / len(g)
    print("  {:<32} {:>5,}件  的中率 {:>5.1f}%  平均 {:+.4f}%  t {:>5.2f}（{}日）".format(
        label, len(rows), hit * 100, mean * 100, _tstat(daily), len(daily)))
    return dict(n=len(rows), hit=hit, mean=mean, t=_tstat(daily), days=len(daily))


if __name__ == "__main__":
    n_dates = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    step = int(sys.argv[2]) if len(sys.argv) > 2 else 3

    print("データ読み込み中...")
    assets = dataset.load_all(use_cache=True, progress=False)
    rows = backtest.collect(assets, config.HORIZON_FX, n_dates=n_dates, step=step,
                            use_knn=True, kinds={"fx"}, verbose=False)
    print("  予測 {:,}件 / {}時点".format(len(rows), len(set(r["ts"] for r in rows))))

    # 検証時点の日付と、その翌日（予測が実現する日）の指標を取る
    tss = sorted(set(r["ts"] for r in rows))
    need = set()
    for ts in tss:
        d = datetime.datetime.fromtimestamp(ts, JST).date()
        need.add(d.isoformat())
        need.add((d + datetime.timedelta(days=1)).isoformat())
    print("  経済指標を取得中（{}日分）...".format(len(need)))
    ev = events.economic_events(sorted(need))
    got = sum(1 for v in ev.values() if v)
    print("  取得できた日: {}/{}".format(got, len(need)))

    # 各予測に「指標の状況」を付ける
    for r in rows:
        d = datetime.datetime.fromtimestamp(r["ts"], JST).date()
        today = events.econ_summary(ev, d.isoformat())
        nxt = events.econ_summary(ev, (d + datetime.timedelta(days=1)).isoformat())
        r["ev_high_today"] = today["high_count"]
        r["ev_high_next"] = nxt["high_count"]
        cur = set(PAIR_CUR.get(r["key"], ()))
        r["ev_mine_next"] = bool(cur & set(nxt["currencies"]))
        r["ev_mine_today"] = bool(cur & set(today["currencies"]))

    conf = config.FX_MIN_CONFIDENCE
    strong = [r for r in rows if max(r["p_up"], 1 - r["p_up"]) >= conf]

    print()
    print("=== 経済指標とFXの的中率（確信度{:.0f}%以上のみ）===".format(conf * 100))
    base = report(strong, "全体（基準）")
    print()
    print("  ▼ 予測が実現する日に重要指標があるか")
    report([r for r in strong if r["ev_high_next"] == 0], "重要指標なし")
    report([r for r in strong if r["ev_high_next"] >= 1], "重要指標あり")
    report([r for r in strong if r["ev_high_next"] >= 5], "重要指標5件以上")
    report([r for r in strong if r["ev_high_next"] >= 10], "重要指標10件以上")
    print()
    print("  ▼ その通貨ペアに直接関係する指標か")
    report([r for r in strong if not r["ev_mine_next"]], "自分の通貨に指標なし")
    report([r for r in strong if r["ev_mine_next"]], "自分の通貨に指標あり")
    print()
    print("  ▼ 予測を出す日（当日）の指標")
    report([r for r in strong if r["ev_high_today"] == 0], "当日は重要指標なし")
    report([r for r in strong if r["ev_high_today"] >= 1], "当日に重要指標あり")
    print()
    print("  ▼ 組み合わせ")
    report([r for r in strong if r["ev_high_next"] == 0 and not r["ev_mine_next"]],
           "翌日も自通貨も指標なし")
    report([r for r in strong if r["ev_high_next"] >= 1 and r["ev_mine_next"]],
           "翌日に自通貨の指標あり")

    print()
    print("  ▼ 曜日（指標の代わりになるか）")
    for wd, name in enumerate(["月", "火", "水", "木", "金"]):
        report([r for r in strong
                if datetime.datetime.fromtimestamp(r["ts"], JST).weekday() == wd],
               "{}曜日に予測".format(name))
    print()
    print("  ※ t値2以上で統計的に有意。基準より的中率が上がっても、")
    print("     件数が減れば機会も減る。両方を見て判断すること。")
