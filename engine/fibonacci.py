# -*- coding: utf-8 -*-
"""フィボナッチ・リトレースメントと、その周辺の水準。

プロが実際に見ている道具の一つ。直近の大きな値動き（高値と安値）を取り、
その値幅の 23.6% / 38.2% / 50% / 61.8% / 78.6% の位置に線を引く。
戻りが止まりやすい水準とされる。

**効果は必ず測ってから使う。** このアプリでは、テクニカルの裏付けが
的中率と関係しないことが既に分かっている（4/4一致の方がむしろ低かった）。
フィボナッチも同じ可能性があるので、表示するにしても
「的中率が上がる」という主張は測定結果が支持したときだけにする。

計算自体に曖昧さはない。曖昧なのは「どの高値と安値を使うか」で、
そこが今回の判断を分けた。

**測定結果: 効果は確認できなかった（表示のみ）。**

    条件            標本0   標本1   標本2   平均
    条件なし        63.1%  60.5%  58.1%  60.6%
    水準に近い(60本) 66.7%  60.7%  65.0%  64.1%   ← 3標本とも改善

一見すると効いている。しかし波を取る本数を1段変えると崩れる。

    30本   64.7%  62.2%  53.7%   ← 標本2が基準58.2%を下回る
    120本  65.8%  56.5%  61.7%   ← 標本1が基準60.9%を下回る

「直近何本を波とみるか」に決まった正解はない。60本だけで効いて前後で
消えるのは、たまたま良い値を拾っただけの形。これを採用すると、
曜日・金利・テクニカル裏付けと同じ失敗になる。

したがって**絞り込みにも重み付けにも使わず、水準を表示するだけ**にする。
プロが実際に見ている道具なので、判断の材料として置く価値はある。
検証は tests/run_fib.py。
"""
RATIOS = (0.236, 0.382, 0.5, 0.618, 0.786)
EXT_RATIOS = (1.272, 1.618)


def swing(bars, lookback=60, i=None):
    """直近 lookback 本の高値・安値と、その並び順を返す。

    安値が先で高値が後なら上昇の波（direction=+1）、逆なら下降の波。
    戻りの向きが変わるので、この区別が要る。
    """
    n = len(bars["c"]) if i is None else i + 1
    lo_i = hi_i = None
    start = max(0, n - lookback)
    for k in range(start, n):
        h, l = bars["h"][k], bars["l"][k]
        if h is None or l is None:
            continue
        if hi_i is None or h > bars["h"][hi_i]:
            hi_i = k
        if lo_i is None or l < bars["l"][lo_i]:
            lo_i = k
    if hi_i is None or lo_i is None or hi_i == lo_i:
        return None
    return {"high": bars["h"][hi_i], "low": bars["l"][lo_i],
            "high_i": hi_i, "low_i": lo_i,
            "direction": 1 if lo_i < hi_i else -1}


def levels(sw):
    """戻りの水準。上昇の波なら高値から下へ、下降の波なら安値から上へ。"""
    if not sw:
        return []
    hi, lo = sw["high"], sw["low"]
    span = hi - lo
    if span <= 0:
        return []
    out = []
    for r in RATIOS:
        price = (hi - span * r) if sw["direction"] > 0 else (lo + span * r)
        out.append({"ratio": r, "price": price, "kind": "戻り"})
    # 波を抜けた先の目標水準
    for r in EXT_RATIOS:
        price = (lo + span * r) if sw["direction"] > 0 else (hi - span * r)
        out.append({"ratio": r, "price": price, "kind": "延長"})
    out.sort(key=lambda x: x["price"])
    return out


def nearest(price, lvls, kinds=("戻り",)):
    """いまの値段に最も近い水準と、そこまでの距離（価格比）。"""
    cand = [l for l in lvls if l["kind"] in kinds]
    if not cand or not price:
        return None
    best = min(cand, key=lambda l: abs(l["price"] - price))
    return {"ratio": best["ratio"], "price": best["price"], "kind": best["kind"],
            "distance": abs(best["price"] - price) / price,
            "above": best["price"] > price}


def context(bars, lookback=60, i=None):
    """表示用にまとめて返す。"""
    sw = swing(bars, lookback, i)
    if not sw:
        return None
    lv = levels(sw)
    px = bars["c"][i if i is not None else -1]
    return {"swing": sw, "levels": lv, "price": px,
            "nearest": nearest(px, lv),
            "lookback": lookback}
