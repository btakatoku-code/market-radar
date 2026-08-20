# -*- coding: utf-8 -*-
"""市場全体の状態（レジーム）を日付ごとに求める。

同じテクニカル形状でも、相場が落ち着いているときと荒れているときでは
その後の値動きがまるで違う。類似局面を探すときに「市場の状態も似ているか」を
条件に加えれば、より意味のある比較になるはず——という仮説を検証するための土台。

使う材料はすべて無料で取れるもの:
  - VIX（恐怖指数）とその短期版 VIX9D … 警戒の度合いと、その期間構造
  - S&P500 の移動平均に対する位置      … 地合いが強気か弱気か
  - 市場の広がり（銘柄の何割が上向きか）… 上昇が一部の銘柄に偏っていないか
  - 米国債の利回り曲線（10年 − 13週）  … 景気後退の織り込み具合

先読みを防ぐため、各バーには「前営業日時点の」レジームを割り当てる。
日本株や暗号資産は米国市場が閉まる前に取引が終わるので、同日のレジームを
使うと未来の情報が混ざってしまう。
"""
import bisect
import datetime

import indicators

DAY = 86400

# レジームの種類（config.REGIME_MODE で選ぶ）
MODES = {
    "none": 1,          # レジームを使わない
    "vix3": 3,          # VIXの水準を3段階
    "trend2": 2,        # S&P500が50日線の上か下か
    "risk3": 3,         # VIXと地合いを合わせた「リスク許容度」3段階
    "breadth3": 3,      # 市場の広がりを3段階
    "vix_trend6": 6,    # VIX3段階 × 地合い2段階
    "risk_breadth9": 9,  # リスク許容度3段階 × 広がり3段階
}


def _terciles(vals):
    """3分割の境界（33%点・67%点）"""
    s = sorted(v for v in vals if v is not None)
    if len(s) < 30:
        return None
    return s[len(s) // 3], s[len(s) * 2 // 3]


def _level(v, edges):
    if v is None or edges is None:
        return 1
    return 0 if v < edges[0] else (2 if v > edges[1] else 1)


class Regime:
    """日付 → レジーム番号 の対応表。"""

    def __init__(self, mode, dates, codes, detail=None):
        self.mode = mode
        self.levels = MODES.get(mode, 1)
        self.dates = dates              # 昇順のタイムスタンプ
        self.codes = codes              # 同じ長さのレジーム番号
        self.detail = detail or {}

    def code_at(self, ts):
        """ts より前の営業日のレジーム番号。無ければ中間値を返す。"""
        if self.levels <= 1 or not self.dates:
            return 0
        i = bisect.bisect_left(self.dates, ts) - 1
        if i < 0:
            return self.levels // 2
        return self.codes[i]

    def series_for(self, bars):
        """バー列に合わせたレジーム番号のリスト"""
        if self.levels <= 1:
            return [0] * len(bars["t"])
        return [self.code_at(t) for t in bars["t"]]


def _get(by_key, sym):
    a = by_key.get(sym)
    return a["bars"] if a else None


def build(assets, mode="risk3"):
    """全銘柄からレジーム系列を作る。"""
    if mode == "none" or mode not in MODES:
        return Regime("none", [], [])

    by_key = {a["key"]: a for a in assets}
    spx = by_key.get("^GSPC")
    vix = by_key.get("^VIX")
    if not spx:
        return Regime("none", [], [])

    cal = spx["bars"]["t"]
    n = len(cal)

    # --- VIXの水準（過去1年の中での位置）---
    vix_lv = [None] * n
    if vix:
        vt, vc = vix["bars"]["t"], vix["bars"]["c"]
        for i, ts in enumerate(cal):
            j = bisect.bisect_right(vt, ts) - 1
            if j < 60:
                continue
            win = vc[max(0, j - 251):j + 1]
            e = _terciles(win)
            vix_lv[i] = _level(vc[j], e)

    # --- 地合い（S&P500が50日線の上か）---
    sc = spx["bars"]["c"]
    sma50 = indicators.sma(sc, 50)
    trend = [None] * n
    for i in range(n):
        if sma50[i]:
            trend[i] = 1 if sc[i] > sma50[i] else 0

    # --- 市場の広がり（50日線を上回る銘柄の割合）---
    breadth_lv = [None] * n
    if mode in ("breadth3", "risk_breadth9"):
        pool = [a for a in assets
                if a["kind"] in ("us_stock", "jp_stock") and not a["leveraged"]]
        raw = [None] * n
        for i, ts in enumerate(cal):
            above = total = 0
            for a in pool:
                j = bisect.bisect_right(a["bars"]["t"], ts) - 1
                if j < 50:
                    continue
                s = a["ind"]["sma50"][j]
                if not s:
                    continue
                total += 1
                if a["bars"]["c"][j] > s:
                    above += 1
            if total >= 50:
                raw[i] = above / total
        e = _terciles([r for r in raw if r is not None])
        for i in range(n):
            breadth_lv[i] = _level(raw[i], e)

    # --- レジーム番号の合成 ---
    codes = []
    for i in range(n):
        v = vix_lv[i] if vix_lv[i] is not None else 1
        t = trend[i] if trend[i] is not None else 1
        b = breadth_lv[i] if breadth_lv[i] is not None else 1
        if mode == "vix3":
            c = v
        elif mode == "trend2":
            c = t
        elif mode == "breadth3":
            c = b
        elif mode == "vix_trend6":
            c = v * 2 + t
        elif mode == "risk3":
            # VIXが低く地合いが強い=2（リスクを取れる）、VIXが高く弱い=0
            score = (2 - v) + t          # 0..3
            c = 0 if score <= 1 else (1 if score == 2 else 2)
        elif mode == "risk_breadth9":
            score = (2 - v) + t
            r = 0 if score <= 1 else (1 if score == 2 else 2)
            c = r * 3 + b
        else:
            c = 0
        codes.append(c)

    detail = {"vix_level": vix_lv[-1], "trend": trend[-1], "breadth": breadth_lv[-1]}
    return Regime(mode, cal, codes, detail)


def snapshot(assets, regime):
    """アプリ表示用の、いまの市場環境のまとめ。"""
    by_key = {a["key"]: a for a in assets}
    out = {"mode": regime.mode, "levels": regime.levels}

    vix = by_key.get("^VIX")
    vix9d = by_key.get("^VIX9D")
    if vix:
        vc = vix["bars"]["c"]
        out["vix"] = round(vc[-1], 2)
        win = vc[-252:]
        e = _terciles(win)
        out["vix_level"] = _level(vc[-1], e)
        if vix9d and vix9d["bars"]["c"]:
            out["vix9d"] = round(vix9d["bars"]["c"][-1], 2)
            out["vix_term"] = round(vix9d["bars"]["c"][-1] / vc[-1], 3)

    spx = by_key.get("^GSPC")
    if spx:
        sc = spx["bars"]["c"]
        s50 = indicators.sma(sc, 50)[-1]
        s200 = indicators.sma(sc, 200)[-1]
        out["spx_above_sma50"] = bool(s50 and sc[-1] > s50)
        out["spx_above_sma200"] = bool(s200 and sc[-1] > s200)

    # 市場の広がり
    pool = [a for a in assets
            if a["kind"] in ("us_stock", "jp_stock") and not a["leveraged"]]
    for label, key in (("breadth50", "sma50"), ("breadth200", "sma200")):
        above = total = 0
        for a in pool:
            s = a["ind"][key][-1]
            if not s:
                continue
            total += 1
            if a["bars"]["c"][-1] > s:
                above += 1
        if total:
            out[label] = round(above / total, 3)
            out[label + "_n"] = total

    # 利回り曲線（10年 − 13週）
    tnx, irx = by_key.get("^TNX"), by_key.get("^IRX")
    if tnx and irx:
        out["yield_curve"] = round(tnx["bars"]["c"][-1] - irx["bars"]["c"][-1], 3)

    # 景気の体温計として銅／金
    hg, gc = by_key.get("HG=F"), by_key.get("GC=F")
    if hg and gc and gc["bars"]["c"][-1]:
        out["copper_gold"] = round(hg["bars"]["c"][-1] / gc["bars"]["c"][-1] * 1000, 3)

    out["label"] = _regime_label(out)
    return out


def _regime_label(s):
    v = s.get("vix_level")
    up = s.get("spx_above_sma50")
    if v is None or up is None:
        return "判定不能"
    if v == 0 and up:
        return "落ち着いた上昇局面"
    if v == 2 and not up:
        return "警戒すべき下落局面"
    if v == 2:
        return "変動が大きい局面"
    if up:
        return "上昇局面"
    return "軟調な局面"


def weekday_of(ts):
    """タイムスタンプ → 曜日（0=月）"""
    return datetime.datetime.utcfromtimestamp(ts).weekday()


def month_of(ts):
    return datetime.datetime.utcfromtimestamp(ts).month
