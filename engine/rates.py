# -*- coding: utf-8 -*-
"""米国金利 — FXの追い風・向かい風の判定。

金利差はFXの教科書的な材料で、テクニカルとも需給とも種類が違う。
米10年国債利回り（^TNX）をYahooから取り、20営業日の変化を「追い風」とする。

**先読みへの注意**: 日足の終値が確定するのは日本時間の翌朝で、
予測を出す時点ではまだ分からない。そのため必ず1日以上前の足だけを使う。
検証でも同じ規則で測っており、この扱いを外すと数値が水増しされる
（62.6% → 61.7%）。

実測（主要5ペア・確信度56%以上・400/360/440時点）:
    追い風と同じ向き  61.7 / 60.9 / 59.5%
    そうでない       53.8 / 52.8 / 55.8%
条件作りに使っていない残り8ペアでも +3.8 / +3.8 / +3.1pt の改善を確認済み。
"""
import bisect

import sources

DAY = 86400
LAG_SECONDS = DAY          # 前日以前の終値だけを使う
LOOKBACK = 20              # 20営業日の変化を追い風とみなす

# 米金利が上がったとき、そのペアが上がる向きなら +1、下がる向きなら -1。
# ドルが絡むペアは金利差、円クロスは「円は低金利通貨」という関係から決めており、
# データに合わせて選んだものではない。
USD_SIGN = {
    "USDJPY=X": +1, "EURUSD=X": -1, "EURJPY=X": +1, "GBPJPY=X": +1, "AUDJPY=X": +1,
    "GBPUSD=X": -1, "AUDUSD=X": -1, "NZDUSD=X": -1, "USDCAD=X": +1, "USDCHF=X": +1,
    "NZDJPY=X": +1, "CADJPY=X": +1, "CHFJPY=X": +1,
}


def load(use_cache=True):
    """金利の日足から、各営業日の20日変化を作る。"""
    d = sources.fetch_yahoo("^TNX", rng="10y", use_cache=use_cache)
    if not d or not d.get("c"):
        return []
    pairs = [(t, c) for t, c in zip(d["t"], d["c"]) if c is not None]
    out = []
    for i, (t, c) in enumerate(pairs):
        out.append({"t": t, "y": c,
                    "chg20": c - pairs[i - LOOKBACK][1] if i >= LOOKBACK else None})
    return out


def at(ser, at_ts):
    """その時点で確定している直近の金利。まだ確定していない足は使わない。"""
    if not ser:
        return None
    ts = [x["t"] for x in ser]
    i = bisect.bisect_left(ts, at_ts - LAG_SECONDS) - 1
    return ser[i] if i >= 0 else None


def tailwind(ser, pair, at_ts):
    """そのペアから見た金利の追い風。正なら上昇方向、負なら下落方向。

    値が None のときは判定材料がない（金利が取れていない等）。
    """
    sign = USD_SIGN.get(pair)
    x = at(ser, at_ts)
    if sign is None or not x or x["chg20"] is None:
        return None
    return sign * x["chg20"]
