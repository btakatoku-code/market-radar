# -*- coding: utf-8 -*-
"""スワップポイント（金利差の受け払い）。

FXの予測期間は24時間なので、シグナルに従うと必ず日をまたぐ。つまり
**毎回スワップが発生する**。買えば受け取り、売れば支払い（高金利通貨側を
買っている場合）で、方向によって符号が変わる。

主要5ペアのうち4つは円クロスで、円が低金利側にある。したがって
「売り」のシグナルは体系的に支払い側になりやすい。この差を無視すると、
コストの見積もりが方向によって偏る。

実額の目安（この検証時点）:
    ドル円1万通貨・1日   約118〜140円 = 想定元本の 0.008%
    実測の1回あたり利益  +0.088%
つまり優位性の1割弱に相当する。

**値は業者ごとに違うので、推測しない。** 各社が「1万通貨あたり1日◯円」の
形で公表しているので、それを設定に入れてもらう。入っていないときは
「未計上」と明示し、影響の大きさだけを示す。金利差から概算できるのは
米ドル絡みだけ（無料で取れる短期金利が米国のものしかないため）。
"""
import sources

# 無料で取れる短期金利。ここにない通貨は概算もしない。
US_SHORT_SYMBOL = "^IRX"        # 米13週物


def us_short_rate(use_cache=True):
    """米国の短期金利（％）。取れなければ None。"""
    d = sources.fetch_yahoo(US_SHORT_SYMBOL, rng="1y", use_cache=use_cache)
    if not d or not d.get("c"):
        return None
    vals = [c for c in d["c"] if c is not None]
    return vals[-1] if vals else None


def estimate_usdjpy(spot, us_rate, jpy_rate, units=10000):
    """ドル円のスワップの概算（円／1万通貨／1日）。

    金利差だけの理屈値で、業者の上乗せは含まない。実際の受け取りは
    これより少なく、支払いはこれより多くなるのが普通。
    """
    if spot is None or us_rate is None or jpy_rate is None:
        return None
    notional = units * spot
    return notional * (us_rate - jpy_rate) / 100.0 / 365.0


def impact(swap_yen_per_day, notional_jpy):
    """1日のスワップが、想定元本（円）に対して何％かを返す。"""
    if swap_yen_per_day is None or not notional_jpy:
        return None
    return swap_yen_per_day / float(notional_jpy)


def share_of_edge(swap_pct, edge_per_trade):
    """スワップが実測の優位性の何割にあたるか。"""
    if swap_pct is None or not edge_per_trade:
        return None
    return abs(swap_pct) / abs(edge_per_trade)


def sensitivity(edge_per_trade, levels=(0.00005, 0.0001, 0.0002)):
    """スワップがいくらなら優位性の何割が消えるか、の目安表。

    実際の値を入れてもらう前でも、影響の大きさは示せる。
    """
    out = []
    for lv in levels:
        out.append({
            "swap_pct": lv,
            "share": (lv / edge_per_trade) if edge_per_trade else None,
            "net_edge": edge_per_trade - lv if edge_per_trade else None,
        })
    return out
