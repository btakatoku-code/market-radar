# -*- coding: utf-8 -*-
"""採点の集計（track）の試験。通信はしない。

    python tests/test_track.py

確かめること（2026-10-18 の変更）
- 全銘柄平均（bench）を、予測した時点〜期限の同じ期間で付ける（指数・FX・レバレッジ型は除く）
- 同じ日の予測はまとめて1回と数え、その日数で95%の幅を出す
- 「全体」から指定銘柄を外す
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))
import track  # noqa: E402

DAY = 86400


def _asset(kind, closes, leveraged=False):
    return {"kind": kind, "leveraged": leveraged,
            "bars": {"t": [i * DAY for i in range(len(closes))], "c": list(closes)}}


def test_bench_is_the_equal_weight_return_of_the_universe():
    assets = {f"S{i}": _asset("us_stock", [100, 100, 110]) for i in range(20)}     # 全部 +10%
    assets["IDX"] = _asset("index", [100, 100, 300])                               # 指数は数えない
    assets["FX"] = _asset("fx", [100, 100, 50])
    assets["LEV"] = _asset("us_etf", [100, 100, 500], leveraged=True)
    b, n = track.bench_return(assets, 1 * DAY, 2 * DAY)
    assert n == 20 and abs(b - 0.10) < 1e-12, (b, n)


def test_bench_needs_enough_assets():
    assets = {f"S{i}": _asset("jp_stock", [100, 110]) for i in range(5)}
    b, n = track.bench_return(assets, 0, DAY)
    assert b is None and n == 5


def test_add_bench_only_for_scored_long_predictions():
    assets = {f"S{i}": _asset("us_stock", [100, 100, 105]) for i in range(25)}
    preds = [{"bucket": "top5", "ts": DAY, "due": 2 * DAY, "actual": 0.02},
             {"bucket": "fx", "ts": DAY, "due": 2 * DAY, "actual": 0.01},
             {"bucket": "top5", "ts": DAY, "due": 2 * DAY, "actual": None}]
    assert track.add_bench(preds, assets) == 1
    assert abs(preds[0]["bench"] - 0.05) < 1e-12 and "bench" not in preds[1] and "bench" not in preds[2]


def _p(date, bucket, pred, actual, bench=None):
    r = {"date": date, "bucket": bucket, "pred": pred, "actual": actual,
         "hit": (pred > 0) == (actual > 0), "error": actual - pred, "ts": 1e10,
         "due": 1e10 + DAY, "actual_at": 1e10 + DAY, "key": "K"}
    if bench is not None:
        r["bench"] = bench
    return r


def test_days_are_counted_once():
    rows = [_p("2026-09-10", "top5", 0.01, -0.05, -0.01) for _ in range(5)] + \
           [_p("2026-09-11", "top5", 0.01, 0.02, 0.01) for _ in range(5)]
    s = track._stats(rows)
    assert s["n"] == 10 and s["days"] == 2
    assert abs(s["hit_day"] - 0.5) < 1e-12                          # 日ごと 0% と 100% の平均
    assert abs(s["excess_day"] - ((-0.04) + 0.01) / 2) < 1e-12      # 日ごとの超過の平均
    assert s["beat_rate"] == 0.5
    assert s["hit_day_lo"] is not None and s["hit_day_lo"] < s["hit_day"] < s["hit_day_hi"]


def test_overall_leaves_out_pinned():
    rows = [_p("2026-09-10", "top5", 0.01, -0.05), _p("2026-09-10", "pinned", 0.01, 0.05),
            _p("2026-09-10", "pinned", 0.01, 0.06)]
    s = track.summary(rows)
    assert s["overall"]["n"] == 1 and s["pinned"]["n"] == 2
    assert "指定銘柄を除く" in s["overall_note"]




def test_weekend_fx_records_are_left_out_and_counted():
    rows = [_p("2026-10-16", "fx", 0.001, 0.002), _p("2026-10-17", "fx", 0.001, 0.002),   # 金・土
            _p("2026-10-18", "fx", 0.001, -0.002)]                                         # 日
    s = track.summary(rows)
    assert s["fx"]["n"] == 1 and s["fx_weekend_excluded"] == 2
    assert s["before_fix"]["overall"] is None                     # 週末の分を「修正前」に混ぜない


def test_direction_bias():
    rows = [_p("2026-10-14", "fx", 0.001, 0.002), _p("2026-10-14", "fx", 0.001, -0.002),
            _p("2026-10-15", "fx", -0.001, -0.002)]
    b = track.direction_bias(rows)
    assert b["up_n"] == 2 and b["down_n"] == 1 and b["up_hit"] == 0.5 and b["down_hit"] == 1.0
    assert abs(b["actual_up_share"] - 1 / 3) < 1e-12


def test_fx_market_closed_window():
    import datetime
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))
    import run
    jst = datetime.timezone(datetime.timedelta(hours=9))
    ts = lambda *a: int(datetime.datetime(*a, tzinfo=jst).timestamp())
    assert not run.fx_market_closed(ts(2026, 10, 16, 22, 0))      # 金曜の夜
    assert run.fx_market_closed(ts(2026, 10, 17, 6, 30))          # 土曜の朝
    assert run.fx_market_closed(ts(2026, 10, 18, 12, 0))          # 日曜
    assert run.fx_market_closed(ts(2026, 10, 19, 6, 30))          # 月曜の開く前
    assert not run.fx_market_closed(ts(2026, 10, 19, 9, 0))       # 月曜の朝


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("  ok", fn.__name__)
    print(f"{len(fns)} 件すべて通りました")
