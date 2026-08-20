# -*- coding: utf-8 -*-
"""複数のテクニカル要素を合成して銘柄をランク付けする。

各要素はおおむね -1〜+1 に正規化してから重み付き合成する。
最終的な並べ替えは「その日の全銘柄の中での相対順位」で行う。
絶対値のしきい値で選ぶとボラティリティの高い銘柄ばかりが選ばれ、
検証では市場平均に負けたため採用しない。
"""
import math

import config


def _clip(x, lo=-1.0, hi=1.0):
    return lo if x < lo else (hi if x > hi else x)


def components(a, idx, bench_roc20=None):
    """1銘柄・1時点のスコア構成要素を返す。計算不能なら None。"""
    ind, bars = a["ind"], a["bars"]
    c = bars["c"]
    px = c[idx]
    s20, s50, s200 = ind["sma20"][idx], ind["sma50"][idx], ind["sma200"][idx]
    adx, atr = ind["adx14"][idx], ind["atr14"][idx]
    mh, rsi = ind["macd_hist"][idx], ind["rsi14"][idx]
    r20, r60 = ind["roc20"][idx], ind["roc60"][idx]
    vol, obvz = ind["vol20"][idx], ind["obv_z"][idx]
    vr = ind["vol_ratio"][idx]
    if None in (s20, s50, adx, atr, mh, rsi, r20, vol) or vol <= 0 or atr <= 0:
        return None
    dvol = vol / math.sqrt(252)

    # トレンド: 中期・長期の並びと強さ
    trend = 0.0
    trend += 0.35 if px > s20 else -0.35
    trend += 0.35 if px > s50 else -0.35
    if s200 is not None:
        trend += 0.30 if s50 > s200 else -0.30
    else:
        trend *= 1.4
    if adx >= 25:
        trend *= 1.25                      # 明確なトレンドなら効きを強める
    elif adx < 15:
        trend *= 0.6                       # 方向感なしなら弱める
    trend = _clip(trend)

    # モメンタム: MACD ヒストグラム + 中期騰落 + RSI の位置
    mom = 0.0
    mom += 0.45 * _clip(mh / atr)
    mom += 0.35 * _clip(r20 / (dvol * math.sqrt(20)) / 2.0)
    if r60 is not None:
        mom += 0.20 * _clip(r60 / (dvol * math.sqrt(60)) / 2.0)
    if rsi > 78:
        mom -= 0.35                        # 買われすぎは反落しやすい
    elif rsi < 22:
        mom += 0.20
    mom = _clip(mom)

    # 相対強度: ベンチマークに対する20日騰落の差
    rel = 0.0
    if bench_roc20 is not None:
        rel = _clip((r20 - bench_roc20) / (dvol * math.sqrt(20)) / 2.0)

    # 出来高の裏付け
    volsc = 0.0
    if vr and vr > 0:
        volsc += 0.5 * _clip(math.log(vr))
    if obvz is not None:
        volsc += 0.5 * _clip(obvz / 2.0)
    volsc = _clip(volsc)

    return dict(trend=trend, momentum=mom, rel=rel, volume=volsc,
                daily_vol=dvol, rsi=rsi, adx=adx, atr=atr, price=px,
                macd=_clip(mh / atr), bb=ind["bb_pctb"][idx],
                stoch=ind["stoch_k"][idx])


def total_score(comp, fc):
    """構成要素 + 類似局面予測 → 合成スコア（おおむね -1〜+1）"""
    if comp is None or fc is None:
        return None
    # 予測リターンをボラで割り、銘柄間で比較可能な形にする
    scale = comp["daily_vol"] * math.sqrt(fc["horizon"])
    analog_n = _clip(fc["expected_return"] / scale / 1.5) if scale else 0.0
    w = config.WEIGHTS
    return (w["analog"] * analog_n + w["trend"] * comp["trend"]
            + w["momentum"] * comp["momentum"] + w["rel"] * comp["rel"]
            + w["volume"] * comp["volume"])


def bench_roc20(assets_by_key, kind):
    """銘柄種別に対応するベンチマークの20日騰落率"""
    key = {"jp_stock": config.BENCH_JP, "jp_etf": config.BENCH_JP,
           "jp_reit": config.BENCH_JP, "crypto": config.BENCH_CRYPTO}.get(
        kind, config.BENCH_US)
    b = assets_by_key.get(key)
    if not b:
        return None
    return b["ind"]["roc20"][-1]


def bench_roc20_at(assets_by_key, kind, ts, index_at):
    key = {"jp_stock": config.BENCH_JP, "jp_etf": config.BENCH_JP,
           "jp_reit": config.BENCH_JP, "crypto": config.BENCH_CRYPTO}.get(
        kind, config.BENCH_US)
    b = assets_by_key.get(key)
    if not b:
        return None
    i = index_at(b["bars"], ts)
    if i is None:
        return None
    return b["ind"]["roc20"][i]
